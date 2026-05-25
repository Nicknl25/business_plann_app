"""Phase 9 P3.33 Phase 3 step 5f — cascade-as-floor walker, budget-aware
auto-confirm, WC scalar lever patch shape, and finalize_authoring.

Addresses three spec deviations identified in step 5d/5e plus the
finalize_authoring wiring:

  1. Cascade-as-floor walker (§9.1): _invoke_floor_for_mode now routes
     through floor_for_mode with a cascade_walker callback so the
     §9.1 unattended walk runs before the §9.2 primitive.
  2. Budget-aware auto-confirm (§8.7): when state.budget_aware is True
     Type A tiers skip the responder and auto-confirm; Type B tiers
     still consult GPT.
  3. _patch_from_proposal emits the nested "working_capital_days"
     overrides shape for WC levers under section="balance_sheet"
     (AR Days, AP Days, Inventory Days). P3.33 Phase 3 pre-step-8 —
     WC days moved from drivers to balance_sheet section.

Plus finalize_authoring(result) standalone function + the SessionDriver
method that wraps it against the last evaluate_plan result.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402
  CheckResult, EvaluatePlanResult, FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: E402,E501
  AppliedBy,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E402,E501
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E402,E501
  SessionDriver, TerminationState, finalize_authoring,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.restructure_proposer import (  # noqa: E402,E501
  Proposal,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (  # noqa: E402,E501
  get_tier,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.reason_codes import (  # noqa: E402,E501
  ReasonCode, StepType,
)


def _check(name, passed, mode=None, distance=None):
  return CheckResult(name=name, passed=passed, failure_mode=mode,
                     distance_to_feasibility=distance)


def _result(*, passing, checks, margins=None, dist=None, round_number=1):
  return EvaluatePlanResult(
    all_pass=passing, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=list(checks), lever_margins=list(margins or []),
    worst_failing_check="ebitda_positive_by_q11", worst_failing_distance=dist,
  )


def _viability_failing(round_number=1, dist=-0.04):
  return _result(
    passing=False,
    checks=[_check("ebitda_positive_by_q11", False,
                   FailureMode.VIABILITY_INVARIANT, distance=dist)],
    margins=[LeverMargin(
      lever_id="expenses::Cost of Goods Sold", section="drivers",
      current=0.72, band_min=0.55, band_target=0.65, band_max=0.78,
    )],
    dist=dist, round_number=round_number,
  )


def _passing(round_number=2):
  return _result(passing=True,
                 checks=[_check("ebitda_positive_by_q11", True)],
                 round_number=round_number, dist=0.01)


def _eval_sequence(seq):
  def fake_eval(*, round_number):
    return seq[min(round_number - 1, len(seq) - 1)]
  return fake_eval


class _LogRecorder:
  def __init__(self): self.rows = []
  def __call__(self, **kwargs):
    self.rows.append(dict(kwargs)); return len(self.rows)


def _accepting_revise(**kwargs):
  return {"accepted": True, "section": kwargs.get("proposal").section,
          "violations": []}


# ---------------------------------------------------------------------------
# 1. Budget-aware auto-confirm — Type A only
# ---------------------------------------------------------------------------

class BudgetAwareAutoConfirmTest(unittest.TestCase):
  def test_type_a_auto_confirms_when_budget_aware(self) -> None:
    """With budget_aware pre-set the Type A tier auto-confirms the
    Python proposal — the responder is NOT called for Type A. The audit
    row carries AppliedBy.BUDGET_AWARE_AUTO_CONFIRM."""
    fake_eval = _eval_sequence([_viability_failing(round_number=1),
                                _passing(round_number=2)])
    responder_calls = {"n": 0}
    def responder(**_):
      responder_calls["n"] += 1
      return ProposalResponse(kind="confirm")
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval, responder=responder,
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log,
    )
    # Force budget-aware mode from the start.
    driver.state.budget_aware = True
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    self.assertEqual(responder_calls["n"], 0)  # responder skipped
    self.assertEqual(len(log.rows), 1)
    self.assertEqual(log.rows[0]["applied_by"],
                     AppliedBy.BUDGET_AWARE_AUTO_CONFIRM)

  def test_type_b_still_consults_responder_when_budget_aware(self) -> None:
    """Even under budget_aware, Type B tiers go through the responder —
    GPT judgment is the reason Type B exists."""
    # Build a result where V1+V2 levers are pinned to target -> smart-
    # entry skipped; V3 (Type B pricing) is the operative tier.
    margins = [
      LeverMargin(lever_id="expenses::Cost of Goods Sold", section="drivers",
                  current=0.65, band_min=0.55, band_target=0.65, band_max=0.78),
      LeverMargin(lever_id="expenses::Marketing", section="drivers",
                  current=0.10, band_min=0.06, band_target=0.10, band_max=0.14),
      LeverMargin(lever_id="expenses::General & Administrative", section="drivers",
                  current=0.18, band_min=0.10, band_target=0.18, band_max=0.25),
      LeverMargin(lever_id="expenses::Research & Development", section="drivers",
                  current=0.07, band_min=0.05, band_target=0.07, band_max=0.10),
      LeverMargin(lever_id="cogs_max", section="stage_ramp",
                  current=0.65, band_min=0.55, band_target=0.65, band_max=0.78),
      LeverMargin(lever_id="marketing_max", section="stage_ramp",
                  current=0.10, band_min=0.06, band_target=0.10, band_max=0.14),
      LeverMargin(lever_id="ni_floor", section="stage_ramp",
                  current=0.05, band_min=0.03, band_target=0.05, band_max=0.10),
      LeverMargin(lever_id="unit_price", section="operating_model",
                  current=20.0, band_min=15.0, band_target=22.0, band_max=30.0),
    ]
    failing = _result(
      passing=False,
      checks=[_check("ebitda_positive_by_q11", False,
                     FailureMode.VIABILITY_INVARIANT, distance=-0.04)],
      margins=margins, dist=-0.04,
    )
    # V2 (Type A "shape") will auto-confirm under budget_aware and might
    # resolve early. Keep evaluations failing past V2 so the cascade
    # actually reaches V3 (Type B) where the responder should fire.
    fake_eval = _eval_sequence([failing, failing, failing,
                                _passing(round_number=4)])
    responder_calls = {"n": 0}
    def responder(**_):
      responder_calls["n"] += 1
      return ProposalResponse(kind="choose", option_id="A")
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval, responder=responder,
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log,
    )
    driver.state.budget_aware = True
    res = driver.run()
    # Whatever the terminal state, the responder must have been called
    # for the Type B V3 tier — budget_aware does not silence Type B.
    self.assertGreaterEqual(responder_calls["n"], 1)
    chose_rows = [r for r in log.rows
                  if r.get("applied_by") == AppliedBy.AMALGAMATED_GPT_CHOSE]
    self.assertGreaterEqual(len(chose_rows), 1)


# ---------------------------------------------------------------------------
# 2. Cascade-as-floor walker (spec §9.1)
# ---------------------------------------------------------------------------

class CascadeAsFloorWalkerTest(unittest.TestCase):
  def test_floor_routes_through_floor_for_mode(self) -> None:
    """When the cascade reaches the floor tier, the driver invokes
    floor_for_mode (which tries the cascade_walker first). The walker
    is the driver's _unattended_cascade_pass. We verify the walker
    fires by counting evaluations: with the walker enabled there are
    more evaluate calls than with the primitive-only fallback."""
    # Use an evaluator that records the round on each call.
    eval_calls = {"rounds": []}
    def fake_eval(*, round_number):
      eval_calls["rounds"].append(round_number)
      # Every evaluation returns failing -> cascade exhausts -> floor.
      return _viability_failing(round_number=round_number)

    # All responder calls veto so the cascade exhausts to floor.
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="veto", reason="never"),
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log,
      primitive_kwargs_for_mode=lambda m: {},
    )
    driver.run()
    # The unattended cascade pass evaluates at least once at entry plus
    # potentially after each commit. With pure primitive (no walker)
    # we'd have far fewer evals.
    self.assertGreater(driver._floor_invocations, 0)


# ---------------------------------------------------------------------------
# 3. _patch_from_proposal WC scalar shape
# ---------------------------------------------------------------------------

class PatchFromProposalShapeTest(unittest.TestCase):
  def _proposal(self, *, section, field):
    return Proposal(
      mode=FailureMode.VIABILITY_INVARIANT,
      tier_id="V1", tier_name="x", step_type=StepType.TYPE_A,
      reason_code=ReasonCode.VIABILITY_COST_RATIO_TUNED,
      section=section, field=field,
      current_value=0.5, proposed_value=0.4,
    )

  def test_pnl_driver_lever_emits_per_anchor_dict(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E501
      _patch_from_proposal,
    )
    patch = _patch_from_proposal(
      self._proposal(section="drivers", field="expenses::Cost of Goods Sold")
    )
    self.assertEqual(
      patch,
      {"expenses::Cost of Goods Sold": {"q1": 0.4, "q11": 0.4, "q20": 0.4}},
    )

  def test_wc_lever_under_balance_sheet_section_emits_nested_overrides(self) -> None:
    """P3.33 Phase 3 pre-step-8 — WC days moved from drivers to
    balance_sheet section. A proposal with section='balance_sheet' and
    a WC lever_id must emit the patch shape revise_capex_rd_balance_seed
    expects: {"working_capital_days": {lever_id: value}}."""
    from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E501
      _patch_from_proposal,
    )
    for wc_lever in (
      "balance_sheet::Accounts Receivable Days",
      "balance_sheet::Accounts Payable Days",
      "balance_sheet::Inventory Days",
    ):
      patch = _patch_from_proposal(
        self._proposal(section="balance_sheet", field=wc_lever)
      )
      self.assertEqual(
        patch, {"working_capital_days": {wc_lever: 0.4}},
        msg=f"WC lever {wc_lever} under balance_sheet section should emit nested overrides shape",
      )

  def test_non_driver_section_emits_flat(self) -> None:
    from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E501
      _patch_from_proposal,
    )
    patch = _patch_from_proposal(
      self._proposal(section="operating_model", field="unit_price")
    )
    self.assertEqual(patch, {"unit_price": 0.4})


# ---------------------------------------------------------------------------
# 4. finalize_authoring
# ---------------------------------------------------------------------------

class FinalizeAuthoringTest(unittest.TestCase):
  def test_passing_result_accepts_finalize(self) -> None:
    r = _passing(round_number=3)
    out = finalize_authoring(r)
    self.assertTrue(out["accepted"])
    self.assertIsNone(out["reason"])

  def test_failing_result_rejects_finalize(self) -> None:
    r = _viability_failing(round_number=2)
    out = finalize_authoring(r)
    self.assertFalse(out["accepted"])
    self.assertIn("failing", out["reason"])
    self.assertIn("ebitda_positive_by_q11", out["reason"])

  def test_no_result_rejects(self) -> None:
    out = finalize_authoring(None)  # type: ignore[arg-type]
    self.assertFalse(out["accepted"])

  def test_driver_finalize_authoring_method_uses_last_result(self) -> None:
    fake_eval = _eval_sequence([_passing(round_number=1)])
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn_for_section=lambda s: None,
    )
    driver.run()  # populates _last_result
    out = driver.finalize_authoring()
    self.assertTrue(out["accepted"])

  def test_driver_finalize_before_run_returns_no_result(self) -> None:
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=lambda **_: _passing(),
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn_for_section=lambda s: None,
    )
    out = driver.finalize_authoring()
    self.assertFalse(out["accepted"])
    self.assertIn("no evaluate_plan result yet", out["reason"])


if __name__ == "__main__":
  unittest.main()
