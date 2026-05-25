"""Phase 9 P3.33 remediation — Commit 7b (C10, C11, C13).

C10 — Multi-mode cascade dispatch: BAND -> COHERENCE -> VIABILITY
      priority order when all three are failing simultaneously.
C11 — Veto-chain-to-floor: every viability tier vetoed; floor enters
      and the cascade-as-floor walker plus §9.2 primitive produce a
      terminal state.
C13 — V6 payroll restructure floor wiring: GPT routes through V6 +
      "other" out-of-band path; floor handles the residual.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402,E501
  CheckResult, EvaluatePlanResult, FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E402,E501
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E402,E501
  SessionDriver, TerminationState,
)


def _check(name, passed, mode=None, distance=None):
  return CheckResult(name=name, passed=passed, failure_mode=mode,
                     distance_to_feasibility=distance)


def _margin(*, section, lever_id, current=None, band_min=None,
            band_target=None, band_max=None, outside_band=False):
  return LeverMargin(
    lever_id=lever_id, section=section, current=current,
    band_min=band_min, band_target=band_target, band_max=band_max,
    outside_band=outside_band,
  )


def _result(*, all_pass, checks, margins=None, worst=None, dist=None,
            round_number=1):
  return EvaluatePlanResult(
    all_pass=all_pass, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=list(checks), lever_margins=list(margins or []),
    worst_failing_check=worst, worst_failing_distance=dist,
  )


def _passing_result(round_number=1):
  return _result(all_pass=True, checks=[_check("ebitda_positive_by_q11", True)],
                 round_number=round_number, dist=0.01)


def _eval_sequence(seq):
  def fake_eval(*, round_number):
    return seq[min(round_number - 1, len(seq) - 1)]
  return fake_eval


class _LogRecorder:
  def __init__(self): self.rows = []
  def __call__(self, **kwargs):
    self.rows.append(dict(kwargs))
    return len(self.rows)


class _EmitRecorder:
  def __init__(self): self.events = []
  def __call__(self, **kwargs):
    self.events.append(dict(kwargs))


def _accepting_revise(**kwargs):
  return {"accepted": True, "section": kwargs.get("proposal").section,
          "violations": []}


def _rejecting_revise(**kwargs):
  return {"accepted": False, "section": kwargs.get("proposal").section,
          "violations": []}


# ---------------------------------------------------------------------------
# C10 — Multi-mode dispatch priority
# ---------------------------------------------------------------------------

class MultiModeDispatchTest(unittest.TestCase):
  """When BAND + COHERENCE + VIABILITY all fail, the driver must
  dispatch in MODE_PRIORITY order: BAND first, then COHERENCE after
  BAND resolves, then VIABILITY after COHERENCE resolves."""

  def test_three_modes_resolve_in_priority_order(self) -> None:
    # Build a sequence of evaluate_plan results that retire one mode
    # at a time in MODE_PRIORITY order.
    band_margin = _margin(section="drivers", lever_id="expenses::Marketing",
                          current=0.5, band_min=0.3, band_target=0.4,
                          band_max=0.6, outside_band=True)
    coherence_margin = _margin(section="drivers", lever_id="expenses::Marketing",
                               current=0.5, band_min=0.3, band_target=0.4,
                               band_max=0.6)
    viability_margin = _margin(section="drivers",
                               lever_id="expenses::Cost of Goods Sold",
                               current=0.5, band_min=0.3, band_target=0.4,
                               band_max=0.6)

    # Each cascade apply re-evaluates internally, so we need ample
    # round slots. fake_eval_by_state returns based on which modes are
    # currently passing rather than by round_number — keeps the
    # progression deterministic regardless of how many rounds the
    # driver consumes.
    state = {"band_resolved": False, "coherence_resolved": False,
             "viability_resolved": False}

    def fake_eval(*, round_number):
      checks = []
      margins_now = []
      worst = None; worst_dist = None
      if not state["band_resolved"]:
        checks.append(_check("realism_gate_no_hard_fail_violations", False,
                             FailureMode.BAND_INVARIANT, distance=-0.1))
        margins_now.append(band_margin)
        worst = "realism_gate_no_hard_fail_violations"; worst_dist = -0.1
      else:
        checks.append(_check("realism_gate_no_hard_fail_violations", True))
      if not state["coherence_resolved"]:
        checks.append(_check("stage_ramp_rev_max_respected", False,
                             FailureMode.COHERENCE_INVARIANT, distance=-0.05))
        margins_now.append(coherence_margin)
        if worst is None:
          worst = "stage_ramp_rev_max_respected"; worst_dist = -0.05
      else:
        checks.append(_check("stage_ramp_rev_max_respected", True))
      if not state["viability_resolved"]:
        checks.append(_check("ebitda_positive_by_q11", False,
                             FailureMode.VIABILITY_INVARIANT, distance=-0.04))
        margins_now.append(viability_margin)
        if worst is None:
          worst = "ebitda_positive_by_q11"; worst_dist = -0.04
      else:
        checks.append(_check("ebitda_positive_by_q11", True))
      all_pass = all(c.passed for c in checks)
      return _result(all_pass=all_pass, checks=checks, margins=margins_now,
                     worst=worst, dist=worst_dist, round_number=round_number)

    # The revise function flips the matching mode's resolution flag.
    def per_mode_revise(**kwargs):
      proposal = kwargs.get("proposal")
      mode = proposal.mode
      if mode == FailureMode.BAND_INVARIANT:
        state["band_resolved"] = True
      elif mode == FailureMode.COHERENCE_INVARIANT:
        state["coherence_resolved"] = True
      elif mode == FailureMode.VIABILITY_INVARIANT:
        state["viability_resolved"] = True
      return {"accepted": True, "section": proposal.section, "violations": []}
    log = _LogRecorder()
    emit = _EmitRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn_for_section=lambda s: per_mode_revise,
      log_fn=log, emit_diagnostic_fn=emit,
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    # Verify the mode order in the cascade-entered events.
    cascade_entered = [e for e in emit.events
                       if e["event_code"].value == "cascade_entered"]
    modes_entered = [e["diagnostic_data"]["mode"] for e in cascade_entered]
    self.assertEqual(
      modes_entered[:3],
      ["band_invariant", "coherence_invariant", "viability_invariant"],
      f"Mode dispatch must follow MODE_PRIORITY order; got {modes_entered}",
    )


# ---------------------------------------------------------------------------
# C11 — Veto-chain-to-floor
# ---------------------------------------------------------------------------

class VetoChainToFloorTest(unittest.TestCase):
  """All viability tiers vetoed -> cascade enters floor -> session
  terminates in floor state."""

  def test_every_viability_tier_vetoed_lands_floor(self) -> None:
    # Failing viability result; never passing.
    failing = _result(
      all_pass=False,
      checks=[_check("ebitda_positive_by_q11", False,
                     FailureMode.VIABILITY_INVARIANT, distance=-0.04)],
      margins=[_margin(section="drivers",
                       lever_id="expenses::Cost of Goods Sold",
                       current=0.72, band_min=0.55, band_target=0.65,
                       band_max=0.78)],
      worst="ebitda_positive_by_q11", dist=-0.04,
    )
    fake_eval = _eval_sequence([failing] * 30)

    veto_count = {"n": 0}
    def vetoing_responder(**_):
      veto_count["n"] += 1
      return ProposalResponse(kind="veto", reason="not acceptable for this business")

    log = _LogRecorder()
    emit = _EmitRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval, responder=vetoing_responder,
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log, emit_diagnostic_fn=emit,
    )
    res = driver.run()
    # Floor must have fired at least once (cascade-as-floor walker +
    # primitive). Termination must be one of the floor states OR
    # stagnation-floor-all (which is the §8.6 escape hatch when no
    # progress is being made).
    self.assertIn(res.termination_state, {
      TerminationState.MODE_FLOOR,
      TerminationState.STAGNATION_FLOOR_ALL,
      TerminationState.BUDGET_EXHAUSTED_FLOOR,
    })
    self.assertGreater(res.floor_invocations, 0,
                       "Veto chain must have reached the floor primitive")
    # At least one CASCADE_PROPOSAL_VETOED row recorded per tier walked.
    vetoed_emits = [e for e in emit.events
                    if e["event_code"].value == "cascade_proposal_vetoed"]
    self.assertGreater(len(vetoed_emits), 0)


# ---------------------------------------------------------------------------
# C13 — V6 payroll restructure floor (Type B + out-of-band other)
# ---------------------------------------------------------------------------

class V6PayrollRestructureFloorTest(unittest.TestCase):
  """V6 is the Type B payroll restructure. GPT chose "other" with an
  out-of-band value; the response is treated as out-of-band veto and
  the cascade advances toward floor."""

  def test_v6_other_out_of_band_advances_cascade(self) -> None:
    failing = _result(
      all_pass=False,
      checks=[_check("ebitda_positive_by_q11", False,
                     FailureMode.VIABILITY_INVARIANT, distance=-0.04)],
      margins=[_margin(section="drivers",
                       lever_id="expenses::Cost of Goods Sold",
                       current=0.72, band_min=0.55, band_target=0.65,
                       band_max=0.78)],
      worst="ebitda_positive_by_q11", dist=-0.04,
    )
    fake_eval = _eval_sequence([failing] * 20)

    # Responder vetoes V1-V5 with reason, then for V6 (Type B) returns
    # "other" with validation_errors (treated as out-of-band).
    counter = {"n": 0}
    def responder(**kwargs):
      counter["n"] += 1
      tier = kwargs["tier"]
      if tier.tier_id == "V6":
        # Out-of-band other: validation_errors is non-empty.
        return ProposalResponse(
          kind="other",
          section="payroll", field="classes.r_and_d", value=99.0,
          validation_errors=[{"code": "value_out_of_band",
                              "detail": "99.0 is impossible"}],
        )
      return ProposalResponse(kind="veto", reason="not for this business")

    log = _LogRecorder()
    emit = _EmitRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval, responder=responder,
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log, emit_diagnostic_fn=emit,
    )
    res = driver.run()
    # The V6 tier must have been reached and produced an out-of-band emit.
    out_of_band_emits = [e for e in emit.events
                        if e["event_code"].value == "cascade_proposal_out_of_band"]
    v6_emits = [e for e in out_of_band_emits
                if e["diagnostic_data"]["tier_id"] == "V6"]
    self.assertGreater(len(v6_emits), 0,
                       "V6 must have produced an out-of-band emit")
    # The session must terminate in a floor or stagnation state since
    # no tier ever accepted a proposal.
    self.assertIn(res.termination_state, {
      TerminationState.MODE_FLOOR,
      TerminationState.STAGNATION_FLOOR_ALL,
      TerminationState.BUDGET_EXHAUSTED_FLOOR,
    })


if __name__ == "__main__":
  unittest.main()
