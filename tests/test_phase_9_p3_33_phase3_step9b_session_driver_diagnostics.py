"""Phase 9 P3.33 Phase 3 step 9b part 1 — SessionDriver emit
instrumentation.

Hermetic tests that the SessionDriver emits a row to
post_intake_run_diagnostics at every state transition: evaluate_plan
entry + result, cascade entered + tier walked + smart-entry skipped,
each proposal-response branch (confirmed/vetoed/chosen/other/
out-of-band), cascade resolved/exhausted, floor walker
entered/primitive applied/completed, session terminated with the
right event per terminal state.

The driver receives a recording fake emit_fn; tests inspect the
recorded sequence. No live database needed.

set_*(contract=None) / cohort_bands / mirror_build / finmo_sync
emitters land in part 2 (next commit) with their own tests.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List


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
from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402,E501
  EventCode, PhaseCode, Status,
)


class _Emitter:
  """Recording fake. Captures every emit call as a list of kwargs dicts."""
  def __init__(self) -> None:
    self.rows: List[Dict[str, Any]] = []

  def __call__(self, **kwargs: Any) -> None:
    self.rows.append(dict(kwargs))

  def events(self) -> List[EventCode]:
    return [r["event_code"] for r in self.rows]

  def filter(self, event: EventCode) -> List[Dict[str, Any]]:
    return [r for r in self.rows if r.get("event_code") == event]


def _passing(*, round_number=1):
  return EvaluatePlanResult(
    all_pass=True, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[CheckResult(name="ebitda_positive_by_q11", passed=True)],
  )


def _viability_failing(*, round_number=1, dist=-0.04):
  return EvaluatePlanResult(
    all_pass=False, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[CheckResult(
      name="ebitda_positive_by_q11", passed=False,
      failure_mode=FailureMode.VIABILITY_INVARIANT,
      distance_to_feasibility=dist,
    )],
    lever_margins=[LeverMargin(
      lever_id="expenses::Cost of Goods Sold", section="drivers",
      current=0.72, band_min=0.55, band_target=0.65, band_max=0.78,
    )],
    worst_failing_check="ebitda_positive_by_q11",
    worst_failing_distance=dist,
  )


def _meta_failing():
  return EvaluatePlanResult(
    all_pass=False, round_number=1,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=[CheckResult(
      name="stage_reached_finalize", passed=False,
      failure_mode=FailureMode.META_INVARIANT,
    )],
  )


def _build_driver(*, evals, responder=None, revise_fn=None, emit=None,
                  budget=None):
  emitter = emit or _Emitter()
  call_idx = {"n": 0}
  def fake_eval(*, round_number):
    idx = min(call_idx["n"], len(evals) - 1)
    call_idx["n"] += 1
    return evals[idx]
  kwargs = dict(
    draft_id="d", planning_run_id="r",
    evaluate_plan_fn=fake_eval,
    responder=responder or (lambda **_: ProposalResponse(kind="confirm")),
    revise_fn_for_section=revise_fn or (lambda s: None),
    emit_diagnostic_fn=emitter,
  )
  if budget is not None:
    kwargs["budget"] = budget
  driver = SessionDriver(**kwargs)
  return driver, emitter


# ---------------------------------------------------------------------------
# Happy path: all_pass round 1 -> evaluate emit + session_resolved emit
# ---------------------------------------------------------------------------

class EvaluatePlanAllPassEmitTest(unittest.TestCase):
  def test_evaluate_plan_started_then_all_pass_then_session_resolved(self) -> None:
    driver, emitter = _build_driver(evals=[_passing()])
    res = driver.run()
    events = emitter.events()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    self.assertIn(EventCode.EVALUATE_PLAN_STARTED, events)
    self.assertIn(EventCode.EVALUATE_PLAN_ALL_PASS, events)
    self.assertIn(EventCode.SESSION_RESOLVED, events)
    # Verify ordering: started -> all_pass -> session_resolved.
    started_idx = events.index(EventCode.EVALUATE_PLAN_STARTED)
    all_pass_idx = events.index(EventCode.EVALUATE_PLAN_ALL_PASS)
    resolved_idx = events.index(EventCode.SESSION_RESOLVED)
    self.assertLess(started_idx, all_pass_idx)
    self.assertLess(all_pass_idx, resolved_idx)

  def test_evaluate_emit_diagnostic_data_includes_round_number(self) -> None:
    _, emitter = _build_driver(evals=[_passing()])
    _.run()
    started_rows = emitter.filter(EventCode.EVALUATE_PLAN_STARTED)
    self.assertEqual(len(started_rows), 1)
    self.assertEqual(started_rows[0]["diagnostic_data"]["round_number"], 1)
    self.assertEqual(started_rows[0]["status"], Status.STARTED)


# ---------------------------------------------------------------------------
# Cascade enter + tier walk + confirm + resolved
# ---------------------------------------------------------------------------

class CascadeFlowEmitsTest(unittest.TestCase):
  def test_failing_then_passing_emits_cascade_flow(self) -> None:
    driver, emitter = _build_driver(
      evals=[_viability_failing(), _passing(round_number=2)],
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn=lambda s: (lambda **_: {"accepted": True, "section": s}),
    )
    res = driver.run()
    events = emitter.events()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    self.assertIn(EventCode.EVALUATE_PLAN_FAILURES_DETECTED, events)
    self.assertIn(EventCode.CASCADE_ENTERED, events)
    self.assertIn(EventCode.CASCADE_TIER_WALKED, events)
    self.assertIn(EventCode.CASCADE_PROPOSAL_CONFIRMED, events)
    self.assertIn(EventCode.CASCADE_RESOLVED, events)
    self.assertIn(EventCode.SESSION_RESOLVED, events)

  def test_cascade_entered_data_carries_mode(self) -> None:
    driver, emitter = _build_driver(
      evals=[_viability_failing(), _passing(round_number=2)],
      revise_fn=lambda s: (lambda **_: {"accepted": True, "section": s}),
    )
    driver.run()
    entered = emitter.filter(EventCode.CASCADE_ENTERED)
    self.assertEqual(len(entered), 1)
    self.assertEqual(entered[0]["diagnostic_data"]["mode"], "viability_invariant")
    self.assertEqual(entered[0]["status"], Status.STARTED)

  def test_proposal_confirmed_data_carries_section_and_field(self) -> None:
    driver, emitter = _build_driver(
      evals=[_viability_failing(), _passing(round_number=2)],
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn=lambda s: (lambda **_: {"accepted": True, "section": s}),
    )
    driver.run()
    confirmed = emitter.filter(EventCode.CASCADE_PROPOSAL_CONFIRMED)
    self.assertGreaterEqual(len(confirmed), 1)
    data = confirmed[0]["diagnostic_data"]
    self.assertEqual(data["section"], "drivers")
    self.assertEqual(data["field"], "expenses::Cost of Goods Sold")
    self.assertAlmostEqual(data["proposed_value"], 0.65)


# ---------------------------------------------------------------------------
# Per-response dispatch emits
# ---------------------------------------------------------------------------

class ResponseDispatchEmitsTest(unittest.TestCase):
  def test_veto_emits_proposal_vetoed_with_reason(self) -> None:
    # Two failing evals so the cascade emits veto then advances to V2.
    # Then keep failing so floor eventually fires; we just want the
    # veto emit. Use 3 failing evals to be safe.
    driver, emitter = _build_driver(
      evals=[_viability_failing(),
             _viability_failing(round_number=2),
             _viability_failing(round_number=3),
             _viability_failing(round_number=4)],
      responder=lambda **_: ProposalResponse(kind="veto",
                                              reason="cohort target not applicable"),
      revise_fn=lambda s: (lambda **_: {"accepted": True, "section": s}),
      budget=12,
    )
    driver.run()
    vetoes = emitter.filter(EventCode.CASCADE_PROPOSAL_VETOED)
    self.assertGreaterEqual(len(vetoes), 1)
    self.assertIn("cohort target not applicable", vetoes[0]["diagnostic_data"]["veto_reason"])

  def test_out_of_band_other_emits_out_of_band_event(self) -> None:
    driver, emitter = _build_driver(
      evals=[_viability_failing(),
             _viability_failing(round_number=2),
             _viability_failing(round_number=3)],
      responder=lambda **_: ProposalResponse(
        kind="other",
        validation_errors=[{"code": "other_section_unknown",
                            "message": "stub 0 cannot be modified"}],
      ),
      budget=8,
    )
    driver.run()
    out_band = emitter.filter(EventCode.CASCADE_PROPOSAL_OUT_OF_BAND)
    self.assertGreaterEqual(len(out_band), 1)
    self.assertIn("other_section_unknown",
                  out_band[0]["diagnostic_data"]["validation_errors"])


# ---------------------------------------------------------------------------
# META halt
# ---------------------------------------------------------------------------

class MetaHaltEmitTest(unittest.TestCase):
  def test_meta_failing_emits_session_meta_halted(self) -> None:
    driver, emitter = _build_driver(
      evals=[_meta_failing()],
      responder=lambda **_: self.fail("META path must not invoke responder"),
    )
    res = driver.run()
    events = emitter.events()
    self.assertEqual(res.termination_state, TerminationState.META_HALTED)
    self.assertIn(EventCode.SESSION_META_HALTED, events)
    meta_rows = emitter.filter(EventCode.SESSION_META_HALTED)
    self.assertEqual(meta_rows[0]["status"], Status.FAILED)


# ---------------------------------------------------------------------------
# Floor invocation
# ---------------------------------------------------------------------------

class FloorEmitsTest(unittest.TestCase):
  def test_stagnation_floor_emits_floor_invocation_events(self) -> None:
    """Two consecutive no-progress cascades -> STAGNATION_FLOOR_ALL.
    Floor invocations should emit FLOOR_WALKER_ENTERED + FLOOR_COMPLETED."""
    driver, emitter = _build_driver(
      evals=[_viability_failing(round_number=1),
             _viability_failing(round_number=2),
             _viability_failing(round_number=3),
             _viability_failing(round_number=4),
             _viability_failing(round_number=5)],
      responder=lambda **_: ProposalResponse(kind="veto", reason="never"),
      budget=20,
    )
    res = driver.run()
    events = emitter.events()
    self.assertEqual(res.termination_state, TerminationState.STAGNATION_FLOOR_ALL)
    self.assertIn(EventCode.FLOOR_WALKER_ENTERED, events)
    self.assertIn(EventCode.FLOOR_COMPLETED, events)
    self.assertIn(EventCode.SESSION_FLOOR_ALL, events)


# ---------------------------------------------------------------------------
# emit-fn failure tolerance — driver does not crash if emit raises
# ---------------------------------------------------------------------------

class EmitToleranceTest(unittest.TestCase):
  def test_driver_survives_emit_exceptions(self) -> None:
    def exploding_emit(**_):
      raise RuntimeError("simulated_emit_failure")
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=lambda *, round_number: _passing(round_number=round_number),
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn_for_section=lambda s: None,
      emit_diagnostic_fn=exploding_emit,
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)


if __name__ == "__main__":
  unittest.main()
