"""Post-intake fail-fast flag ownership.

These flags are diagnostics, not business decisions. They live with
post-intake foundation code so intake cannot redefine which post-intake
failures are terminal.
"""

from __future__ import annotations

from typing import Set


CONVERGENCE_TEST_MODE_FAIL_FLAGS: Set[str] = {
  "repair_target_count_zero",
  "no_direct_drivers_for_closure_metric",
  "no_selected_levers_for_issue",
  "all_selected_levers_indirect",
  "weakest_metric_not_targeted",
  "expected_impact_but_actual_change_negligible",
  "gap_reduction_stalled_multiple_cycles",
  "gap_shrinking_but_score_flat",
}

CASH_STRATEGY_TEST_MODE_FAIL_FLAGS: Set[str] = {
  "cash_pass_not_executed",
  "cash_prompt_trace_missing",
  "cash_raw_response_missing",
  "cash_parse_failed",
  "cash_translation_failed",
  "cash_quarter_coverage_missing",
  "cash_quarter_underfunded",
  "cash_quarter_overfunded",
  "cash_stock_financing_carryforward_missing",
  "cash_non_gpt_fallback_used",
  "cash_required_action_missing",
  "cash_buffer_violation",
  "liquidity_failure",
  "funding_structure_mismatch",
  "working_capital_mismatch",
}

PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS: Set[str] = {
  "payroll_headcount_validator_unavailable",
  "payroll_row_missing",
  "payroll_stub_missing",
  "payroll_row_should_not_be_writable",
  "payroll_row_missing_headcount_derived_driver_marker",
  "payroll_lever_still_writable_catalog",
  "payroll_headcount_schedule_missing",
  "payroll_headcount_schedule_validation_failed",
  "payroll_headcount_schedule_missing_full_horizon",
  "payroll_headcount_schedule_missing_live_quarters",
  "payroll_values_not_headcount_schedule_derived",
  "payroll_headcount_grid must be a 20-row array",
  "payroll_headcount_grid must contain exactly 20 rows",
}

TRANSLATION_TEST_MODE_FAIL_FLAGS: Set[str] = {
  "metric_to_lever_translation_failed",
}


__all__ = [
  "CASH_STRATEGY_TEST_MODE_FAIL_FLAGS",
  "CONVERGENCE_TEST_MODE_FAIL_FLAGS",
  "PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS",
  "TRANSLATION_TEST_MODE_FAIL_FLAGS",
]
