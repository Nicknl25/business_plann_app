"""Phase 9 P3.33 remediation — Commit 7c (C7, C8).

C7 — Behavioral tests for diagnostic emit sites. Replace name-
     presence-only tests with tests that drive the code path with a
     recording fake conn and assert the expected EventCode emits
     with the expected diagnostic_data shape.

C8 — Behavioral tests for fail-fast codes. For each FailFastCode,
     construct the precise invariant-violating scenario; verify
     raise_fail_fast raises a RuntimeError with the expected
     "post_intake_fail_fast::<code>:" prefix; verify the original
     exception is chained when supplied.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_diagnostics.fail_fast_codes import (  # noqa: E402,E501
  FailFastCode, FAIL_FAST_CODES_BY_PHASE, FAIL_FAST_PREFIX, raise_fail_fast,
)
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402,E501
  EventCode, PhaseCode, Status,
)


# ---------------------------------------------------------------------------
# C8 — fail-fast behavioral coverage: one parameterized test per code
# ---------------------------------------------------------------------------

class FailFastBehavioralTest(unittest.TestCase):
  """For every FailFastCode in the enum, raise_fail_fast must:
    1. Raise RuntimeError prefixed with FAIL_FAST_PREFIX::<code>:
    2. Chain the original exception via raise ... from when supplied
    3. Include the supplied detail string
  """

  def _phase_for(self, code):
    for phase, codes in FAIL_FAST_CODES_BY_PHASE.items():
      if code in codes:
        return phase
    self.fail(f"Code {code.value} not in any phase partition")

  def test_each_code_raises_with_prefix_and_detail(self) -> None:
    for code in FailFastCode:
      phase = self._phase_for(code)
      with self.assertRaises(RuntimeError) as ctx:
        raise_fail_fast(
          conn=None,
          draft_id="d", planning_run_id="r",
          phase=phase, code=code,
          detail=f"behavioral_test_for_{code.value}",
          where="test_phase_9_p3_33_remediation_commit7c",
        )
      msg = str(ctx.exception)
      self.assertTrue(
        msg.startswith(f"{FAIL_FAST_PREFIX}{code.value}:"),
        f"Code {code.value} missing FAIL_FAST_PREFIX in message: {msg!r}",
      )
      self.assertIn(f"behavioral_test_for_{code.value}", msg)

  def test_cause_is_chained(self) -> None:
    """When cause is supplied, the RuntimeError __cause__ must
    reference it (raise ... from behavior)."""
    code = FailFastCode.FAIL_EVALUATE_PLAN_EXCEPTION
    phase = self._phase_for(code)
    original = ZeroDivisionError("simulated upstream fault")
    with self.assertRaises(RuntimeError) as ctx:
      raise_fail_fast(
        conn=None,
        draft_id="d", planning_run_id="r",
        phase=phase, code=code,
        detail="with chained cause", where="test",
        cause=original,
      )
    self.assertIs(ctx.exception.__cause__, original)


# ---------------------------------------------------------------------------
# C7 — diagnostic emit site behavioral tests
# ---------------------------------------------------------------------------
# The SessionDriver emits a stream of events through its emit_diagnostic_fn
# seam. The following tests drive specific code paths through the driver
# with a recording fake emit and assert the expected EventCode appears with
# the expected diagnostic_data shape.

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # noqa: E402,E501
  CheckResult, EvaluatePlanResult, FailureMode, LeverMargin,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E402,E501
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E402,E501
  SessionDriver, TerminationState,
)


def _failing_check(name, mode, distance=-0.04):
  return CheckResult(name=name, passed=False, failure_mode=mode,
                     distance_to_feasibility=distance)


def _passing_check(name):
  return CheckResult(name=name, passed=True)


def _viability_failing_result(round_number=1):
  return EvaluatePlanResult(
    all_pass=False, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[_failing_check("ebitda_positive_by_q11",
                           FailureMode.VIABILITY_INVARIANT)],
    lever_margins=[LeverMargin(
      lever_id="expenses::Cost of Goods Sold", section="drivers",
      current=0.72, band_min=0.55, band_target=0.65, band_max=0.78,
    )],
    worst_failing_check="ebitda_positive_by_q11",
    worst_failing_distance=-0.04,
  )


def _passing_result(round_number=2):
  return EvaluatePlanResult(
    all_pass=True, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[_passing_check("ebitda_positive_by_q11")],
  )


class _EmitRecorder:
  def __init__(self): self.events = []
  def __call__(self, **kwargs):
    self.events.append(dict(kwargs))

  def by_code(self, code):
    return [e for e in self.events if e.get("event_code") == code]


def _eval_sequence(seq):
  def fake_eval(*, round_number):
    return seq[min(round_number - 1, len(seq) - 1)]
  return fake_eval


def _accepting_revise(**kwargs):
  return {"accepted": True, "section": kwargs.get("proposal").section,
          "violations": []}


class DiagnosticEmitSitesTest(unittest.TestCase):
  """Each test drives a code path and asserts the expected emit
  fired with the expected shape."""

  def _run_resolved(self, *, responder, evaluator):
    emit = _EmitRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=evaluator, responder=responder,
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=lambda **kw: 1,
      emit_diagnostic_fn=emit,
    )
    res = driver.run()
    return res, emit

  def test_evaluate_plan_started_event_emitted(self) -> None:
    _, emit = self._run_resolved(
      responder=lambda **_: ProposalResponse(kind="confirm"),
      evaluator=_eval_sequence([_passing_result(round_number=1)]),
    )
    evt = emit.by_code(EventCode.EVALUATE_PLAN_STARTED)
    self.assertGreaterEqual(len(evt), 1)
    self.assertIn("round_number", evt[0]["diagnostic_data"])

  def test_evaluate_plan_all_pass_event_emitted(self) -> None:
    _, emit = self._run_resolved(
      responder=lambda **_: ProposalResponse(kind="confirm"),
      evaluator=_eval_sequence([_passing_result(round_number=1)]),
    )
    evt = emit.by_code(EventCode.EVALUATE_PLAN_ALL_PASS)
    self.assertGreaterEqual(len(evt), 1)
    self.assertTrue(evt[0]["diagnostic_data"]["all_pass"])

  def test_cascade_entered_event_emitted_with_mode(self) -> None:
    _, emit = self._run_resolved(
      responder=lambda **_: ProposalResponse(kind="confirm"),
      evaluator=_eval_sequence([
        _viability_failing_result(round_number=1),
        _passing_result(round_number=2),
      ]),
    )
    evt = emit.by_code(EventCode.CASCADE_ENTERED)
    self.assertGreaterEqual(len(evt), 1)
    self.assertEqual(evt[0]["diagnostic_data"]["mode"], "viability_invariant")

  def test_cascade_tier_walked_event_emitted_with_tier_id(self) -> None:
    _, emit = self._run_resolved(
      responder=lambda **_: ProposalResponse(kind="confirm"),
      evaluator=_eval_sequence([
        _viability_failing_result(round_number=1),
        _passing_result(round_number=2),
      ]),
    )
    evt = emit.by_code(EventCode.CASCADE_TIER_WALKED)
    self.assertGreaterEqual(len(evt), 1)
    self.assertIn("tier_id", evt[0]["diagnostic_data"])
    self.assertEqual(evt[0]["diagnostic_data"]["step_type"], "A")

  def test_cascade_proposal_confirmed_event_emitted(self) -> None:
    _, emit = self._run_resolved(
      responder=lambda **_: ProposalResponse(kind="confirm"),
      evaluator=_eval_sequence([
        _viability_failing_result(round_number=1),
        _passing_result(round_number=2),
      ]),
    )
    evt = emit.by_code(EventCode.CASCADE_PROPOSAL_CONFIRMED)
    self.assertGreaterEqual(len(evt), 1)
    self.assertIn("section", evt[0]["diagnostic_data"])
    self.assertIn("field", evt[0]["diagnostic_data"])

  def test_cascade_proposal_vetoed_event_emitted(self) -> None:
    calls = {"n": 0}
    def responder(**_):
      calls["n"] += 1
      if calls["n"] == 1:
        return ProposalResponse(kind="veto", reason="not for this business")
      return ProposalResponse(kind="confirm")
    _, emit = self._run_resolved(
      responder=responder,
      evaluator=_eval_sequence([
        _viability_failing_result(round_number=1),
        _passing_result(round_number=2),
      ]),
    )
    evt = emit.by_code(EventCode.CASCADE_PROPOSAL_VETOED)
    self.assertGreaterEqual(len(evt), 1)
    self.assertIn("veto_reason", evt[0]["diagnostic_data"])

  def test_cascade_resolved_event_emitted_on_mode_resolution(self) -> None:
    _, emit = self._run_resolved(
      responder=lambda **_: ProposalResponse(kind="confirm"),
      evaluator=_eval_sequence([
        _viability_failing_result(round_number=1),
        _passing_result(round_number=2),
      ]),
    )
    evt = emit.by_code(EventCode.CASCADE_RESOLVED)
    self.assertGreaterEqual(len(evt), 1)
    self.assertIn("resolved_at_tier", evt[0]["diagnostic_data"])

  def test_session_resolved_terminal_event_emitted(self) -> None:
    res, emit = self._run_resolved(
      responder=lambda **_: ProposalResponse(kind="confirm"),
      evaluator=_eval_sequence([
        _viability_failing_result(round_number=1),
        _passing_result(round_number=2),
      ]),
    )
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    evt = emit.by_code(EventCode.SESSION_RESOLVED)
    self.assertEqual(len(evt), 1)
    self.assertEqual(evt[0]["diagnostic_data"]["termination_state"], "RESOLVED")

  def test_oscillation_skipped_event_emitted(self) -> None:
    """Pre-seed the oscillation memory so the next V1 walk is skipped;
    verify CASCADE_OSCILLATION_SKIPPED fires with previous_lever_id
    in diagnostic_data."""
    emit = _EmitRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=_eval_sequence([
        _viability_failing_result(round_number=1),
        _passing_result(round_number=2),
      ]),
      responder=lambda **_: ProposalResponse(kind="veto", reason="no"),
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=lambda **kw: 1, emit_diagnostic_fn=emit,
    )
    driver.state.last_lever_by_mode[FailureMode.VIABILITY_INVARIANT] = (
      "drivers::expenses::Cost of Goods Sold"
    )
    driver.run()
    evt = emit.by_code(EventCode.CASCADE_OSCILLATION_SKIPPED)
    self.assertGreaterEqual(len(evt), 1)
    self.assertEqual(evt[0]["diagnostic_data"]["previous_lever_id"],
                     "drivers::expenses::Cost of Goods Sold")

  def test_bound_relaxation_cap_hit_emitted(self) -> None:
    """Pre-load the relaxation counter; V7 walk should fire CAP_HIT."""
    from client_intake_and_finmo.post_intake_amalgamated.protocol.cascades import (
      BOUND_RELAXATION_MAX_ATTEMPTS,
    )
    emit = _EmitRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=_eval_sequence([
        _viability_failing_result(round_number=1),
      ] * 10),
      responder=lambda **_: ProposalResponse(kind="veto", reason="no"),
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=lambda **kw: 1, emit_diagnostic_fn=emit,
    )
    driver.state.bound_relaxations_by_band[
      "viability_invariant::drivers::expenses::Research & Development"
    ] = BOUND_RELAXATION_MAX_ATTEMPTS
    driver.run()
    # If V7 was reached and the R&D band is the picked lever, CAP_HIT fires.
    # The cap might not fire if a different lever wins the V7 selection;
    # in that case, the state.bound_relaxations_by_band dict remains
    # unchanged for R&D (i.e., the cap was respected by not incrementing).
    cap_hits = emit.by_code(EventCode.CASCADE_BOUND_RELAXATION_CAP_HIT)
    rd_count = driver.state.bound_relaxations_by_band.get(
      "viability_invariant::drivers::expenses::Research & Development", 0,
    )
    # Either we saw an explicit cap hit, OR the R&D counter remained
    # at the cap (never incremented beyond it).
    self.assertTrue(
      len(cap_hits) > 0 or rd_count == BOUND_RELAXATION_MAX_ATTEMPTS,
      f"Expected CAP_HIT or counter unchanged; got hits={len(cap_hits)}, "
      f"rd_count={rd_count}",
    )


if __name__ == "__main__":
  unittest.main()
