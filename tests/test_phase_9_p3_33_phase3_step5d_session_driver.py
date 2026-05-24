"""Phase 9 P3.33 Phase 3 step 5d — SessionDriver core state machine.

Hermetic tests on the §12 state machine, covering the core flows:

  - Already-passing first round -> RESOLVED, no proposals.
  - Single-mode cascade resolves at V1 with Type A confirm.
  - Veto advances tier; second tier confirm resolves.
  - META check failing -> META_HALTED + META audit row.

Stagnation, budget exhaustion, Type B choose dispatch, and 'other'
out-of-band downgrade tests land in the next commit (step 5e).
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
  AppliedBy, ReasonCode, StepType,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E402,E501
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E402,E501
  SessionDriver, TerminationState,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _check(name, passed, mode=None, distance=None):
  return CheckResult(name=name, passed=passed, failure_mode=mode,
                     distance_to_feasibility=distance)


def _margin(*, section, lever_id, current, band_min, band_target, band_max,
            outside_band=False):
  return LeverMargin(
    lever_id=lever_id, section=section,
    current=current, band_min=band_min, band_target=band_target, band_max=band_max,
    outside_band=outside_band,
  )


def _result(*, passing, checks, margins=None, worst=None, dist=None, round_number=1):
  return EvaluatePlanResult(
    all_pass=passing, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=list(checks), lever_margins=list(margins or []),
    worst_failing_check=worst, worst_failing_distance=dist,
  )


def _viability_failing_result(round_number=1, dist=-0.04):
  return _result(
    passing=False,
    checks=[_check("ebitda_positive_by_q11", False,
                   FailureMode.VIABILITY_INVARIANT, distance=dist)],
    margins=[_margin(section="drivers",
                     lever_id="expenses::Cost of Goods Sold",
                     current=0.72, band_min=0.55, band_target=0.65, band_max=0.78)],
    worst="ebitda_positive_by_q11", dist=dist, round_number=round_number,
  )


def _passing_result(round_number=2):
  return _result(passing=True, checks=[_check("ebitda_positive_by_q11", True)],
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


def _accepting_revise(**kwargs):
  return {"accepted": True, "section": kwargs.get("proposal").section,
          "violations": []}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class HappyPathTest(unittest.TestCase):
  def test_all_pass_first_round_resolves_immediately(self) -> None:
    fake_eval = _eval_sequence([_passing_result(round_number=1)])
    def never_called(**_): self.fail("responder should not be called")
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval, responder=never_called,
      revise_fn_for_section=lambda s: None,
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    self.assertEqual(res.applied_steps, 0)
    self.assertEqual(res.floor_invocations, 0)


# ---------------------------------------------------------------------------
# Single-mode cascade with confirm
# ---------------------------------------------------------------------------

class CascadeConfirmTest(unittest.TestCase):
  def test_v1_confirm_resolves(self) -> None:
    fake_eval = _eval_sequence([
      _viability_failing_result(round_number=1),
      _passing_result(round_number=2),
    ])
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="confirm"),
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log,
      current_payload_for=lambda s: {"expenses::Cost of Goods Sold": {"q1": 0.72}},
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    self.assertEqual(res.applied_steps, 1)
    self.assertEqual(len(log.rows), 1)
    self.assertEqual(log.rows[0]["applied_by"],
                     AppliedBy.AMALGAMATED_GPT_CONFIRMED)
    self.assertEqual(log.rows[0]["cascade_tier"], "V1")


# ---------------------------------------------------------------------------
# Veto -> advance -> next tier confirm
# ---------------------------------------------------------------------------

class VetoAdvanceTest(unittest.TestCase):
  def test_first_tier_veto_then_v2_confirm_resolves(self) -> None:
    fake_eval = _eval_sequence([
      _viability_failing_result(round_number=1),
      _passing_result(round_number=2),
    ])
    calls = {"n": 0}
    def responder(**_):
      calls["n"] += 1
      if calls["n"] == 1:
        return ProposalResponse(kind="veto", reason="cohort target unsuitable")
      return ProposalResponse(kind="confirm")
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval, responder=responder,
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log,
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    self.assertEqual(len(log.rows), 2)
    self.assertEqual(log.rows[0]["applied_by"], AppliedBy.AMALGAMATED_GPT_VETOED)
    self.assertEqual(log.rows[1]["applied_by"], AppliedBy.AMALGAMATED_GPT_CONFIRMED)
    self.assertEqual(log.rows[1]["cascade_tier"], "V2")


# ---------------------------------------------------------------------------
# META halt
# ---------------------------------------------------------------------------

class MetaHaltTest(unittest.TestCase):
  def test_meta_check_failure_halts_with_audit_row(self) -> None:
    fake_eval = _eval_sequence([_result(
      passing=False,
      checks=[_check("stage_reached_finalize", False,
                     FailureMode.META_INVARIANT)],
    )])
    def never_called(**_): self.fail("META path must not invoke responder")
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval, responder=never_called,
      revise_fn_for_section=lambda s: None, log_fn=log,
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.META_HALTED)
    self.assertEqual(len(log.rows), 1)
    self.assertEqual(log.rows[0]["reason_code"], ReasonCode.META_ESCALATED)
    self.assertEqual(log.rows[0]["step_type"], StepType.META)


if __name__ == "__main__":
  unittest.main()
