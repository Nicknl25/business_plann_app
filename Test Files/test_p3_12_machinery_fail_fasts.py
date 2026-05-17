"""Phase 9 P3.12 — Machinery fail-fast tests across iter 19 stages.

Adds unit tests for the 11 new machinery fail-fast invariants:
  Funding handler (Stage 4):
    1. funding_handler_round_count_drift
    2. funding_handler_budget_decoupling_violation
    3. funding_handler_state_corruption_between_rounds
    4. funding_handler_authority_violation
    5. funding_handler_output_malformed
    6. funding_handler_best_effort_selection_drift
  Stage ramp handler (Stage 5):
    7. stage_ramp_handler_round_count_drift
    8. stage_ramp_handler_budget_decoupling_violation
    9. stage_ramp_handler_state_corruption_between_rounds
    10. stage_ramp_handler_authority_violation
  Stage 2:
    11. payroll_tier_bounds_mirror_drift

Each test:
  (a) constructs synthetic state representing the malfunction
  (b) invokes the relevant code path
  (c) asserts PostIntakePreconditionFailed with the expected
      operation code

Run: ``.venv\\Scripts\\python.exe "Test Files\\test_p3_12_machinery_fail_fasts.py"``
"""

from __future__ import annotations

import copy
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo.fail_fast.common import (  # noqa: E402
  PostIntakePreconditionFailed,
)
from client_intake_and_finmo.post_intake_funding_handler import (  # noqa: E402
  FundingHandlerResult,
  FundingHandlerStatus,
  apply_authored_lever_changes_to_model_input,
)
from client_intake_and_finmo.post_intake_funding_handler import (  # noqa: E402
  handler as _fh,
)
from client_intake_and_finmo.post_intake_stage_ramp_handler import (  # noqa: E402
  handler as _sr,
)
from client_intake_and_finmo import post_intake_mapping as _mapping  # noqa: E402


_RESULTS: List[Tuple[str, bool, str]] = []


def _run(name: str, fn: Callable[[], None]) -> None:
  try:
    fn()
    _RESULTS.append((name, True, ""))
    print(f"  PASS  {name}")
  except AssertionError as exc:
    _RESULTS.append((name, False, str(exc)))
    print(f"  FAIL  {name}: {exc}")
  except Exception as exc:
    _RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
    print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    traceback.print_exc()


def _expect_fail_fast(operation: str, callable_: Callable[[], Any]) -> None:
  raised = None
  try:
    callable_()
  except PostIntakePreconditionFailed as exc:
    raised = exc
  assert raised is not None, f"expected PostIntakePreconditionFailed (operation={operation})"
  assert raised.operation == operation, (
    f"expected operation={operation}, got {raised.operation}"
  )


# =============================================================================
# Funding handler — categories 1-6.
# =============================================================================


def test_funding_handler_round_count_drift_raises() -> None:
  # Contextvar set to 0 (entering loop scope), then mismatched count.
  token = _fh._FUNDING_HANDLER_GPT_CALL_COUNT.set(0)
  try:
    _expect_fail_fast(
      "funding_handler_round_count_drift",
      lambda: _fh._assert_funding_handler_round_count_consistent(
        loop_round_index=3,
        tool_calls_used=5,  # ahead of contextvar (0)
      ),
    )
  finally:
    _fh._FUNDING_HANDLER_GPT_CALL_COUNT.reset(token)


def test_funding_handler_round_count_drift_passes_when_consistent() -> None:
  token = _fh._FUNDING_HANDLER_GPT_CALL_COUNT.set(3)
  try:
    _fh._assert_funding_handler_round_count_consistent(
      loop_round_index=3,
      tool_calls_used=3,
    )
  finally:
    _fh._FUNDING_HANDLER_GPT_CALL_COUNT.reset(token)


def test_funding_handler_round_count_drift_raises_when_contextvar_uninitialized() -> None:
  # Force-reset to None to simulate outside-scope invocation.
  _expect_fail_fast(
    "funding_handler_round_count_drift",
    lambda: _fh._assert_funding_handler_round_count_consistent(
      loop_round_index=1,
      tool_calls_used=1,
    ),
  )


def test_funding_handler_budget_decoupling_violation() -> None:
  _expect_fail_fast(
    "funding_handler_budget_decoupling_violation",
    lambda: _fh._assert_funding_handler_budget_decoupled(
      round_n=1,
      counts_against_run_budget_arg=True,  # violation
    ),
  )


def test_funding_handler_budget_decoupling_passes_on_false() -> None:
  _fh._assert_funding_handler_budget_decoupled(
    round_n=1,
    counts_against_run_budget_arg=False,
  )


def test_funding_handler_state_corruption_input_items_not_list() -> None:
  _expect_fail_fast(
    "funding_handler_state_corruption_between_rounds",
    lambda: _fh._assert_funding_handler_state_intact(
      round_n=2,
      input_items=None,
      history=[],
      verified_commit_candidate=None,
    ),
  )


def test_funding_handler_state_corruption_input_items_contains_non_dict() -> None:
  _expect_fail_fast(
    "funding_handler_state_corruption_between_rounds",
    lambda: _fh._assert_funding_handler_state_intact(
      round_n=2,
      input_items=[{"role": "system"}, "not a dict"],
      history=[],
      verified_commit_candidate=None,
    ),
  )


def test_funding_handler_state_corruption_history_not_list() -> None:
  _expect_fail_fast(
    "funding_handler_state_corruption_between_rounds",
    lambda: _fh._assert_funding_handler_state_intact(
      round_n=2,
      input_items=[{"role": "system"}],
      history="not a list",
      verified_commit_candidate=None,
    ),
  )


def test_funding_handler_state_corruption_verified_candidate_malformed() -> None:
  # An object without `arguments` attr — simulates a refactor that
  # swapped the record type without updating the session loop.
  _expect_fail_fast(
    "funding_handler_state_corruption_between_rounds",
    lambda: _fh._assert_funding_handler_state_intact(
      round_n=2,
      input_items=[{"role": "system"}],
      history=[],
      verified_commit_candidate=object(),  # has no .arguments
    ),
  )


def test_funding_handler_state_corruption_passes_when_healthy() -> None:
  class _Rec:
    arguments = {"x": 1}
  _fh._assert_funding_handler_state_intact(
    round_n=2,
    input_items=[{"role": "system"}],
    history=[_Rec()],
    verified_commit_candidate=_Rec(),
  )


def test_funding_handler_authority_violation_raises() -> None:
  _expect_fail_fast(
    "funding_handler_authority_violation",
    lambda: _fh._assert_funding_handler_authority_respected(
      authored_lever_changes={
        "schedules::Debt Issuance (New Borrowing)": {3: 10_000.0},
        "expenses::Payroll": {3: 5_000.0},  # OUT of authority
      },
    ),
  )


def test_funding_handler_authority_passes_in_scope() -> None:
  _fh._assert_funding_handler_authority_respected(
    authored_lever_changes={
      "schedules::Debt Issuance (New Borrowing)": {3: 10_000.0},
      "balance_sheet::Owner's Capital": {5: 20_000.0},
    },
  )


def test_funding_handler_apply_authored_changes_raises_on_violation() -> None:
  # Wire-level test: the lever-write helper now hard-fails instead of
  # silently skipping out-of-authority lever_ids.
  _expect_fail_fast(
    "funding_handler_authority_violation",
    lambda: apply_authored_lever_changes_to_model_input(
      model_input_json={"sections": {"schedules": [], "balance_sheet": []}},
      authored_lever_changes={"expenses::Payroll": {3: 5_000.0}},
    ),
  )


def test_funding_handler_output_malformed_resolved_no_changes() -> None:
  bad_result = FundingHandlerResult(
    status=FundingHandlerStatus.RESOLVED,
    authored_lever_changes={},
    diagnostic="synthetic",
  )
  _expect_fail_fast(
    "funding_handler_output_malformed",
    lambda: _fh._assert_funding_handler_output_well_formed(result=bad_result),
  )


def test_funding_handler_output_malformed_exhausted_no_diagnostic() -> None:
  bad_result = FundingHandlerResult(
    status=FundingHandlerStatus.EXHAUSTED,
    residual_violations=[],
    diagnostic="",
  )
  _expect_fail_fast(
    "funding_handler_output_malformed",
    lambda: _fh._assert_funding_handler_output_well_formed(result=bad_result),
  )


def test_funding_handler_output_passes_when_well_formed() -> None:
  good = FundingHandlerResult(
    status=FundingHandlerStatus.RESOLVED,
    authored_lever_changes={"balance_sheet::Owner's Capital": {3: 100.0}},
    diagnostic="ok",
  )
  _fh._assert_funding_handler_output_well_formed(result=good)


def test_funding_handler_best_effort_selection_drift_raises() -> None:
  class _Rec:
    call_n = 5
    result = {"all_violations_resolved": True}
  _expect_fail_fast(
    "funding_handler_best_effort_selection_drift",
    lambda: _fh._assert_funding_handler_best_effort_selection_consistent(
      best_effort_record=_Rec(),
      history=[_Rec()],
    ),
  )


def test_funding_handler_best_effort_passes_when_residual_nonzero() -> None:
  class _Rec:
    call_n = 5
    result = {"all_violations_resolved": False, "buffer_residual_violations": [{}]}
  _fh._assert_funding_handler_best_effort_selection_consistent(
    best_effort_record=_Rec(),
    history=[_Rec()],
  )


# =============================================================================
# Stage ramp handler — categories 1-4.
# =============================================================================


def test_stage_ramp_handler_round_count_drift_raises() -> None:
  token = _sr._STAGE_RAMP_HANDLER_GPT_CALL_COUNT.set(2)
  try:
    _expect_fail_fast(
      "stage_ramp_handler_round_count_drift",
      lambda: _sr._assert_stage_ramp_handler_round_count_consistent(
        loop_round_index=2,
        gpt_calls_made=4,
      ),
    )
  finally:
    _sr._STAGE_RAMP_HANDLER_GPT_CALL_COUNT.reset(token)


def test_stage_ramp_handler_round_count_passes_when_consistent() -> None:
  token = _sr._STAGE_RAMP_HANDLER_GPT_CALL_COUNT.set(2)
  try:
    _sr._assert_stage_ramp_handler_round_count_consistent(
      loop_round_index=2,
      gpt_calls_made=2,
    )
  finally:
    _sr._STAGE_RAMP_HANDLER_GPT_CALL_COUNT.reset(token)


def test_stage_ramp_handler_budget_decoupling_violation() -> None:
  _expect_fail_fast(
    "stage_ramp_handler_budget_decoupling_violation",
    lambda: _sr._assert_stage_ramp_handler_budget_decoupled(
      round_n=1,
      counts_against_run_budget_arg=True,
    ),
  )


def test_stage_ramp_handler_budget_decoupling_passes_on_false() -> None:
  _sr._assert_stage_ramp_handler_budget_decoupled(
    round_n=1,
    counts_against_run_budget_arg=False,
  )


def test_stage_ramp_handler_state_corruption() -> None:
  _expect_fail_fast(
    "stage_ramp_handler_state_corruption_between_rounds",
    lambda: _sr._assert_stage_ramp_handler_state_intact(
      round_n=2,
      input_items=None,
      history=[],
      verified_commit_candidate=None,
    ),
  )


def test_stage_ramp_handler_state_intact_passes_healthy() -> None:
  class _Rec:
    arguments = {"x": 1}
  _sr._assert_stage_ramp_handler_state_intact(
    round_n=2,
    input_items=[{"role": "system"}],
    history=[_Rec()],
    verified_commit_candidate=_Rec(),
  )


def test_stage_ramp_handler_authority_violation_raises() -> None:
  _expect_fail_fast(
    "stage_ramp_handler_authority_violation",
    lambda: _sr._assert_stage_ramp_handler_authority_respected(
      refined_contract={
        "stage_family": "operational",
        "expenses::Payroll": {"q1": 1000},  # OUT of authority
      },
    ),
  )


def test_stage_ramp_handler_authority_passes_in_scope() -> None:
  _sr._assert_stage_ramp_handler_authority_respected(
    refined_contract={
      "stage_family": "operational",
      "utilization_high_watermark": 0.85,
      "quarter_ramp_grid": [],
      "rationale": "ok",
      "decision_source": "stage_ramp_handler_refined",
      "business_stage": "operational",
    },
  )


# =============================================================================
# Stage 2 — policy-mirror drift.
# =============================================================================


def test_payroll_tier_bounds_mirror_consistent_passes_today() -> None:
  # The current state has Python mirror matching the SQL policy
  # (Stage 2 was built that way). This check is the watchdog for
  # future drift; it should pass today.
  _mapping._assert_payroll_tier_bounds_mirror_consistent()


def test_payroll_tier_bounds_mirror_drift_raises_on_synthetic_mismatch() -> None:
  # Temporarily mutate the Python mirror to introduce drift.
  original = dict(_mapping._PAYROLL_INTENSITY_TIER_BOUNDS)
  try:
    _mapping._PAYROLL_INTENSITY_TIER_BOUNDS["medium"] = (0.99, 0.999)
    _expect_fail_fast(
      "payroll_tier_bounds_mirror_drift",
      _mapping._assert_payroll_tier_bounds_mirror_consistent,
    )
  finally:
    _mapping._PAYROLL_INTENSITY_TIER_BOUNDS.clear()
    _mapping._PAYROLL_INTENSITY_TIER_BOUNDS.update(original)


# =============================================================================
# Run.
# =============================================================================


def main() -> int:
  print("running test_p3_12_machinery_fail_fasts.py")
  print("-" * 70)
  tests = [
    # Funding handler
    ("fh_round_count_drift", test_funding_handler_round_count_drift_raises),
    ("fh_round_count_consistent_passes", test_funding_handler_round_count_drift_passes_when_consistent),
    ("fh_round_count_uninitialized_raises", test_funding_handler_round_count_drift_raises_when_contextvar_uninitialized),
    ("fh_budget_decoupling_violation", test_funding_handler_budget_decoupling_violation),
    ("fh_budget_decoupling_passes_false", test_funding_handler_budget_decoupling_passes_on_false),
    ("fh_state_corruption_input_items", test_funding_handler_state_corruption_input_items_not_list),
    ("fh_state_corruption_input_non_dict", test_funding_handler_state_corruption_input_items_contains_non_dict),
    ("fh_state_corruption_history_not_list", test_funding_handler_state_corruption_history_not_list),
    ("fh_state_corruption_verified_malformed", test_funding_handler_state_corruption_verified_candidate_malformed),
    ("fh_state_intact_passes_healthy", test_funding_handler_state_corruption_passes_when_healthy),
    ("fh_authority_violation_raises", test_funding_handler_authority_violation_raises),
    ("fh_authority_passes_in_scope", test_funding_handler_authority_passes_in_scope),
    ("fh_apply_changes_authority_wire", test_funding_handler_apply_authored_changes_raises_on_violation),
    ("fh_output_malformed_resolved_empty", test_funding_handler_output_malformed_resolved_no_changes),
    ("fh_output_malformed_exhausted_empty", test_funding_handler_output_malformed_exhausted_no_diagnostic),
    ("fh_output_well_formed_passes", test_funding_handler_output_passes_when_well_formed),
    ("fh_best_effort_drift_raises", test_funding_handler_best_effort_selection_drift_raises),
    ("fh_best_effort_residual_passes", test_funding_handler_best_effort_passes_when_residual_nonzero),
    # Stage ramp handler
    ("sr_round_count_drift", test_stage_ramp_handler_round_count_drift_raises),
    ("sr_round_count_consistent_passes", test_stage_ramp_handler_round_count_passes_when_consistent),
    ("sr_budget_decoupling_violation", test_stage_ramp_handler_budget_decoupling_violation),
    ("sr_budget_decoupling_passes_false", test_stage_ramp_handler_budget_decoupling_passes_on_false),
    ("sr_state_corruption", test_stage_ramp_handler_state_corruption),
    ("sr_state_intact_passes_healthy", test_stage_ramp_handler_state_intact_passes_healthy),
    ("sr_authority_violation_raises", test_stage_ramp_handler_authority_violation_raises),
    ("sr_authority_passes_in_scope", test_stage_ramp_handler_authority_passes_in_scope),
    # Stage 2 policy-mirror
    ("policy_mirror_consistent_passes", test_payroll_tier_bounds_mirror_consistent_passes_today),
    ("policy_mirror_drift_raises", test_payroll_tier_bounds_mirror_drift_raises_on_synthetic_mismatch),
  ]
  for name, fn in tests:
    _run(name, fn)
  print("-" * 70)
  passed = sum(1 for _, ok, _ in _RESULTS if ok)
  failed = [(n, why) for n, ok, why in _RESULTS if not ok]
  print(f"{passed}/{len(_RESULTS)} passed")
  if failed:
    print("FAILURES:")
    for name, why in failed:
      print(f"  {name}: {why}")
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
