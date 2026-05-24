"""Phase 9 P3.33 Phase 3 step 5e — SessionDriver edge-case tests.

Companion to step 5d's core tests. Covers the protocol's terminal
states beyond the happy path:

  - Two consecutive no-progress cascades -> STAGNATION_FLOOR_ALL with
    META row carrying ReasonCode.STAGNATION_FLOOR_ALL.
  - Budget at floor threshold -> BUDGET_EXHAUSTED_FLOOR (or the
    stagnation-first variant when both trigger close to each other).
  - 'other' response with structural validation failure -> logged as
    AMALGAMATED_GPT_OTHER_OUT_BAND and treated as veto.
  - Type B choose-option-B dispatches the correct option's
    proposed_value through to the audit row.
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
  AppliedBy, ReasonCode,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.response_tools import (  # noqa: E402,E501
  ProposalResponse,
)
from client_intake_and_finmo.post_intake_amalgamated.protocol.session_driver import (  # noqa: E402,E501
  SessionDriver, TerminationState,
)


# ---------------------------------------------------------------------------
# Harness (mirrors step 5d's helpers)
# ---------------------------------------------------------------------------

def _check(name, passed, mode=None, distance=None):
  return CheckResult(name=name, passed=passed, failure_mode=mode,
                     distance_to_feasibility=distance)


def _margin(*, section, lever_id, current, band_min, band_target, band_max):
  return LeverMargin(
    lever_id=lever_id, section=section,
    current=current, band_min=band_min, band_target=band_target, band_max=band_max,
  )


def _result(*, passing, checks, margins=None, worst=None, dist=None, round_number=1):
  return EvaluatePlanResult(
    all_pass=passing, round_number=round_number,
    structural_completeness=True, strictness="full_acceptance_gate",
    checks=list(checks), lever_margins=list(margins or []),
    worst_failing_check=worst, worst_failing_distance=dist,
  )


def _viability_failing(round_number=1, dist=-0.04):
  return _result(
    passing=False,
    checks=[_check("ebitda_positive_by_q11", False,
                   FailureMode.VIABILITY_INVARIANT, distance=dist)],
    margins=[_margin(section="drivers",
                     lever_id="expenses::Cost of Goods Sold",
                     current=0.72, band_min=0.55, band_target=0.65, band_max=0.78)],
    worst="ebitda_positive_by_q11", dist=dist, round_number=round_number,
  )


def _passing(round_number=2):
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
# STAGNATION_FLOOR_ALL
# ---------------------------------------------------------------------------

class StagnationFloorAllTest(unittest.TestCase):
  def test_two_consecutive_no_progress_triggers_floor_all(self) -> None:
    """Every evaluate returns the same failing distance. After two
    cascade walks with no progress, STAGNATION_FLOOR_ALL fires."""
    def fake_eval(*, round_number):
      return _viability_failing(round_number=round_number, dist=-0.04)

    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="veto", reason="never resolves"),
      revise_fn_for_section=lambda s: None,
      log_fn=log,
      primitive_kwargs_for_mode=lambda m: {},
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.STAGNATION_FLOOR_ALL)
    self.assertGreaterEqual(res.floor_invocations, 1)
    meta_rows = [r for r in log.rows
                 if r.get("reason_code") == ReasonCode.STAGNATION_FLOOR_ALL]
    self.assertEqual(len(meta_rows), 1)


# ---------------------------------------------------------------------------
# Budget exhaustion
# ---------------------------------------------------------------------------

class BudgetExhaustionTest(unittest.TestCase):
  def test_tiny_budget_terminates_in_floor_state(self) -> None:
    """A tiny budget exhausts before any cascade resolves — should
    terminate in either STAGNATION_FLOOR_ALL or BUDGET_EXHAUSTED_FLOOR
    (whichever fires first), both with budget at/below threshold."""
    def fake_eval(*, round_number):
      return _viability_failing(round_number=round_number)
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="veto", reason="x"),
      revise_fn_for_section=lambda s: None,
      log_fn=log,
      budget=3,
    )
    res = driver.run()
    self.assertIn(res.termination_state, (
      TerminationState.STAGNATION_FLOOR_ALL,
      TerminationState.BUDGET_EXHAUSTED_FLOOR,
    ))
    self.assertLessEqual(res.budget_remaining, 1)


# ---------------------------------------------------------------------------
# 'other' response with validation failure -> OUT_BAND downgrade
# ---------------------------------------------------------------------------

class OtherOutOfBandDowngradeTest(unittest.TestCase):
  def test_other_validation_failure_logs_out_band(self) -> None:
    fake_eval = _eval_sequence([_viability_failing(round_number=1),
                                _passing(round_number=2)])
    calls = {"n": 0}
    def responder(**_):
      calls["n"] += 1
      if calls["n"] == 1:
        # Type A tier got an 'other' with validation failure (stub-0 section).
        return ProposalResponse(
          kind="other",
          validation_errors=[{"code": "other_section_unknown",
                              "message": "stub 0 cannot be modified"}],
        )
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
    self.assertEqual(log.rows[0]["applied_by"],
                     AppliedBy.AMALGAMATED_GPT_OTHER_OUT_BAND)


# ---------------------------------------------------------------------------
# Type B choose dispatch
# ---------------------------------------------------------------------------

class TypeBChooseDispatchTest(unittest.TestCase):
  def test_choose_option_b_dispatches_value_positioning(self) -> None:
    """V3 (pricing, Type B) returns options A (premium=band_max) and
    B (value=band_min). Choosing B records the band_min as the
    proposed_value in the audit row."""
    # All V1+V2 levers at target so smart-entry skips them; V3 has
    # headroom on unit_price.
    margins = [
      _margin(section="drivers", lever_id="expenses::Cost of Goods Sold",
              current=0.65, band_min=0.55, band_target=0.65, band_max=0.78),
      _margin(section="drivers", lever_id="expenses::Marketing",
              current=0.10, band_min=0.06, band_target=0.10, band_max=0.14),
      _margin(section="drivers", lever_id="expenses::General & Administrative",
              current=0.18, band_min=0.10, band_target=0.18, band_max=0.25),
      _margin(section="drivers", lever_id="expenses::Research & Development",
              current=0.07, band_min=0.05, band_target=0.07, band_max=0.10),
      _margin(section="stage_ramp", lever_id="cogs_max",
              current=0.65, band_min=0.55, band_target=0.65, band_max=0.78),
      _margin(section="stage_ramp", lever_id="marketing_max",
              current=0.10, band_min=0.06, band_target=0.10, band_max=0.14),
      _margin(section="stage_ramp", lever_id="ni_floor",
              current=0.05, band_min=0.03, band_target=0.05, band_max=0.10),
      _margin(section="operating_model", lever_id="unit_price",
              current=20.0, band_min=15.0, band_target=22.0, band_max=30.0),
    ]
    failing = _result(
      passing=False,
      checks=[_check("ebitda_positive_by_q11", False,
                     FailureMode.VIABILITY_INVARIANT, distance=-0.04)],
      margins=margins, worst="ebitda_positive_by_q11", dist=-0.04,
    )
    fake_eval = _eval_sequence([failing, _passing(round_number=2)])
    log = _LogRecorder()
    driver = SessionDriver(
      draft_id="d", planning_run_id="r",
      evaluate_plan_fn=fake_eval,
      responder=lambda **_: ProposalResponse(kind="choose", option_id="B"),
      revise_fn_for_section=lambda s: _accepting_revise,
      log_fn=log,
    )
    res = driver.run()
    self.assertEqual(res.termination_state, TerminationState.RESOLVED)
    chose_rows = [r for r in log.rows
                  if r.get("applied_by") == AppliedBy.AMALGAMATED_GPT_CHOSE]
    self.assertEqual(len(chose_rows), 1)
    self.assertEqual(chose_rows[0]["cascade_tier"], "V3")
    self.assertAlmostEqual(chose_rows[0]["proposed_value"], 15.0)


if __name__ == "__main__":
  unittest.main()
