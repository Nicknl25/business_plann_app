"""Unified post-grid convergence runner.

This file owns the convergence loop body. The API handler binds the existing
runtime helpers once and then calls this module as the convergence phase owner.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

from client_intake_and_finmo.post_intake_mapping import (
  post_intake_assert_required_process_sequence,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_process_sequence_step,
)
from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
  assert_post_intake_sequence_controller_authoritative,
  build_post_intake_sequence_controller,
  build_single_step_handler_registry,
)
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (
  CASH_STRATEGY_TEST_MODE_FAIL_FLAGS,
  PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS,
  assert_post_intake_global_invariants,
)
from client_intake_and_finmo.post_intake_foundation import (
  bind_table_safe_runtime_dependencies,
  post_intake_assert_runtime_table_integrity,
)
from client_intake_and_finmo.post_intake_runtime_validation import (  # type: ignore
  run_finalize_post_intake_validation,
)

_PLAN_BUILDER_MAX_SECONDS = 35.0
_RETRY_MEMORY_MAX_PRIOR_LEVER_UNIONS = 4
_RETRY_MEMORY_MAX_PRIOR_TARGET_KEYS = 4
_RETRY_MEMORY_MAX_VALIDATION_ERRORS = 3
_RETRY_MEMORY_MAX_ATTEMPT_RECORDS = 3
_CASH_STRATEGY_TEST_MODE_FAIL_FLAGS = set(CASH_STRATEGY_TEST_MODE_FAIL_FLAGS)
_PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS = set(PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS)
# Module 4 Task 4.3 — convergence guard values now read from the
# `post_intake_process_sequence_lookup` row for `unified_convergence_decision`.
# Defaults below match the legacy Python constants exactly and are used as
# the fail-safe fallback when the column is NULL (e.g., during initial
# table-init paths or when a forked deployment hasn't run the v4 DDL yet).
_CONVERGENCE_GUARD_DEFAULTS: Dict[str, float] = {
  "cycle_deadline_guard_seconds": 8.0,
  "planner_gpt_max_seconds": 150.0,
  "verification_gpt_max_seconds": 45.0,
  "non_productive_cycle_limit": 3.0,
  "total_phase_budget_seconds": 720.0,
}


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


def _sequence_numeric_setting(step_key: str, field_name: str) -> float:
  row = post_intake_process_sequence_step(step_key, required=True) or {}
  value = row.get(field_name)
  if value is None or value == "":
    raise RuntimeError(
      f"post_intake_process_sequence_missing_numeric_setting: step={step_key} field={field_name}"
    )
  return float(value)


def _sequence_setting_or_default(step_key: str, field_name: str) -> float:
  """Module 4 Task 4.3 — read a numeric guard column from the sequence row;
  fall back to `_CONVERGENCE_GUARD_DEFAULTS[field_name]` when the column is
  NULL/missing. Used for the convergence guard values that moved from
  Python constants to sequence-row columns.

  Raises if the field is unknown to the defaults map (catches typos).
  """
  if field_name not in _CONVERGENCE_GUARD_DEFAULTS:
    raise RuntimeError(
      f"post_intake_convergence_unknown_guard_field: {field_name}"
    )
  try:
    row = post_intake_process_sequence_step(step_key, required=True) or {}
  except Exception:
    return float(_CONVERGENCE_GUARD_DEFAULTS[field_name])
  value = row.get(field_name)
  if value is None or value == "":
    return float(_CONVERGENCE_GUARD_DEFAULTS[field_name])
  try:
    return float(value)
  except Exception:
    return float(_CONVERGENCE_GUARD_DEFAULTS[field_name])


def _convergence_guard_int(field_name: str) -> int:
  return int(round(_sequence_setting_or_default("unified_convergence_decision", field_name)))


def _convergence_guard_float(field_name: str) -> float:
  return float(_sequence_setting_or_default("unified_convergence_decision", field_name))


_UNIFIED_CONVERGENCE_MAX_CYCLES = int(
  _sequence_numeric_setting("unified_convergence_decision", "max_attempts")
)
_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS = float(
  _sequence_numeric_setting("unified_convergence_decision", "timeout_seconds")
)


def _contract_forecast_quarter_count() -> int:
  count = int(
    post_intake_contract_forecast_horizon_quarter_count(
      contract_name="unified_convergence_decision",
    )
    or 0
  )
  if count <= 0:
    raise RuntimeError(
      "post_intake_contract_horizon_missing: "
      "post_intake_gpt_contract_lookup must define a positive convergence forecast horizon."
    )
  return count


def _bounded_cycle_deadline(cycle_deadline: float, max_seconds: float) -> float:
  """Keep each subcall inside the total 180s cycle budget with a return guard."""
  now = time.perf_counter()
  guarded_cycle_deadline = float(cycle_deadline) - float(_convergence_guard_float("cycle_deadline_guard_seconds"))
  return min(guarded_cycle_deadline, now + max(1.0, float(max_seconds)))


def _abort_for_cascade_result(
  *,
  abort_reason: str,
  diagnostics: Dict[str, Any],
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Phase 6 Step 7 — convert a mid-flight band-respecting failure into a
  cascade-routable status return, instead of raising and bypassing the
  cascade entirely.

  The three reasons the directive specified as cascade-routable:
    - convergence_total_phase_budget_exceeded — runner.py:1264
    - solver_not_invoked / planner_not_completed (incl.
      failed_missing_full_horizon_model_input_contract) — runner.py:1748
    - no_meaningful_progress — runner.py:1791, 1799, 2393

  Other StructuredSystemRunFailure raises in this file
  (payroll_validation_failed, solver_target_miss_before_verification,
  negative_net_income_hard_gate, convergence_cycle_timeout,
  convergence_cycle_insufficient_stage_budget) stay as raises — those
  are real internal bugs / hard-gate violations the cascade can't fix
  by retrying with relaxed inputs.

  The orchestrator inspects ``status == "abort_for_cascade"`` after
  ``_inner_runner(...)`` returns and routes the result through
  ``run_adaptation_cascade`` with the last-known-good model_input + finmo
  payloads, the abort_reason as input for tier selection (Step 8), and
  the diagnostics preserved for the run report.
  """
  return {
    "status": "abort_for_cascade",
    "abort_reason": str(abort_reason or "").strip() or "unknown_abort",
    "diagnostics": copy.deepcopy(diagnostics or {}),
    "model_input_json": copy.deepcopy(model_input_json) if isinstance(model_input_json, dict) else None,
    "finmo_json": copy.deepcopy(finmo_json) if isinstance(finmo_json, dict) else None,
  }


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  """Bind handler/runtime helpers used by the extracted convergence loop."""
  bind_table_safe_runtime_dependencies(globals(), dependencies or {})


def _reset_non_productive_cycle_tracker(retry_memory: Dict[str, Any]) -> None:
  """Reset retry-loop stall memory after a solver-ready cycle is accepted."""
  if not isinstance(retry_memory, dict):
    return
  retry_memory["non_productive_cycle_tracker"] = {
    "consecutive_non_productive_cycles": 0,
    "repeated_same_pattern": False,
    "repeated_failure_pattern": "",
    "last_known_state": {},
  }
  retry_memory["recent_validation_errors"] = []


def _hard_rule_failure_count(assessment: Optional[Dict[str, Any]]) -> int:
  payload = assessment if isinstance(assessment, dict) else {}
  if bool(payload.get("all_hard_rules_cleared")):
    return 0
  for key in ("failed_count", "violation_count", "failure_count", "open_violation_count"):
    value = _safe_float(payload.get(key))
    if value is not None:
      return max(0, int(round(float(value))))
  count = 0
  for key in ("failures", "violations", "remaining_violations", "failed_rules"):
    value = payload.get(key)
    if isinstance(value, list):
      count += len(value)
  return count


def _apply_stage_ramp_revenue_driver_limits(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  """Use mapped revenue formula drivers to enforce the stage-ramp max path."""
  from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
  from client_intake_and_finmo.post_intake_convergence.runtime import _solved_lever_value_map  # type: ignore
  from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
    post_intake_driver_target_mapping_entry,
    post_intake_normalize_lever_value,
  )
  from client_intake_and_finmo.quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore

  def _stage_rows(contract: Any) -> Dict[int, Dict[str, Any]]:
    payload = contract if isinstance(contract, dict) else {}
    return {
      int(_safe_float(row.get("quarter_index") or row.get("q")) or 0): row
      for row in (payload.get("quarter_ramp_grid") or [])
      if isinstance(row, dict) and int(_safe_float(row.get("quarter_index") or row.get("q")) or 0) >= 1
    }

  def _growth_multiplier(value: Any) -> Optional[float]:
    parsed = _safe_float(value)
    if parsed is None or parsed <= 0:
      return None
    return float(parsed) if parsed >= 1.0 else 1.0 + float(parsed)

  next_model_input = copy.deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  next_finmo = copy.deepcopy(finmo_json if isinstance(finmo_json, dict) else {})
  ramp_rows = _stage_rows(stage_ramp_contract)
  if not next_model_input or not ramp_rows:
    return next_model_input, next_finmo, {"applied": False, "reason": "missing_model_or_stage_ramp"}

  adjustment_rows: List[Dict[str, Any]] = []
  for _attempt in range(4):
    revenue_by_q = {
      int(_safe_float(row.get("quarter_index")) or 0): float(_safe_float(row.get("revenue")) or 0.0)
      for row in ((next_finmo or {}).get("quarter_rows") or [])
      if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
    }
    baseline = _solved_lever_value_map(next_model_input)
    formula_groups: Dict[str, Dict[str, str]] = {}
    for lever_id in baseline.keys():
      mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
      if str(mapping_entry.get("target_metric_name") or "").strip().lower() != "revenue":
        continue
      if str(mapping_entry.get("driver_bundle") or "").strip().lower() != "revenue_formula_bundle":
        continue
      target_driver = str(mapping_entry.get("target_driver") or "").strip().lower()
      if target_driver in {"capacity", "unit_price", "utilization"}:
        formula_groups.setdefault(str(lever_id).rsplit("::", 1)[0], {})[target_driver] = str(lever_id)
    complete_groups = [
      group for group in formula_groups.values()
      if all(driver in group for driver in ("capacity", "unit_price", "utilization"))
    ]
    if len(complete_groups) != 1:
      return next_model_input, next_finmo, {
        "applied": bool(adjustment_rows),
        "reason": "requires_single_revenue_formula_group",
        "adjustments": adjustment_rows,
      }
    drivers = complete_groups[0]
    updates: List[Dict[str, Any]] = []

    for quarter in range(2, 21):
      previous_revenue = revenue_by_q.get(quarter - 1)
      current_revenue = revenue_by_q.get(quarter)
      ramp_row = ramp_rows.get(quarter) or {}
      max_growth = _growth_multiplier(ramp_row.get("revenue_qoq_max") or ramp_row.get("rev_max"))
      if previous_revenue is None or current_revenue is None or previous_revenue <= 0.0 or max_growth is None:
        continue
      maximum_revenue = float(previous_revenue) * float(max_growth)
      if float(current_revenue) <= maximum_revenue + max(1.0, maximum_revenue * 0.001):
        continue

      def _lever_value(driver_name: str) -> Optional[float]:
        values = baseline.get(drivers[driver_name])
        if isinstance(values, list) and 1 <= quarter <= len(values):
          return _safe_float(values[quarter - 1])
        return None

      capacity = _lever_value("capacity")
      unit_price = _lever_value("unit_price")
      utilization = _lever_value("utilization")
      if capacity is None or unit_price is None or utilization is None:
        continue
      candidates: List[Dict[str, Any]] = []
      if float(capacity) > 0.0 and float(utilization) > 0.0:
        lever_id = drivers["unit_price"]
        normalized = post_intake_normalize_lever_value(
          lever_id,
          maximum_revenue / (float(capacity) * float(utilization)),
        )
        projected = float(capacity) * float(_safe_float(normalized) or 0.0) * float(utilization)
        candidates.append({"lever_id": lever_id, "exact_value": normalized, "projected_revenue": projected})
      if float(capacity) > 0.0 and float(unit_price) > 0.0:
        raw_utilization = maximum_revenue / (float(capacity) * float(unit_price))
        if 0.0 <= raw_utilization <= 1.0:
          lever_id = drivers["utilization"]
          normalized = post_intake_normalize_lever_value(lever_id, raw_utilization)
          projected = float(capacity) * float(unit_price) * float(_safe_float(normalized) or 0.0)
          candidates.append({"lever_id": lever_id, "exact_value": normalized, "projected_revenue": projected})
      candidates.sort(key=lambda item: abs(float(item.get("projected_revenue") or 0.0) - maximum_revenue))
      if not candidates:
        continue
      chosen = candidates[0]
      updates.append({"lever_id": chosen["lever_id"], "quarter_index": quarter, "exact_value": chosen["exact_value"]})
      adjustment_rows.append(
        {
          "quarter_index": quarter,
          "previous_revenue": int(round(float(previous_revenue))),
          "actual_revenue": int(round(float(current_revenue))),
          "maximum_revenue": int(round(float(maximum_revenue))),
          "adjusted_lever_id": chosen["lever_id"],
          "adjusted_value": chosen["exact_value"],
          "projected_revenue": int(round(float(chosen.get("projected_revenue") or 0.0))),
        }
      )
    if not updates:
      break
    next_model_input = apply_exact_lever_updates_to_model_input(
      model_input_json=copy.deepcopy(next_model_input),
      exact_updates=updates,
    )
    next_finmo = build_python_finmo_json(model_input_json=copy.deepcopy(next_model_input))
  return next_model_input, next_finmo, {
    "applied": bool(adjustment_rows),
    "adjustments": adjustment_rows,
    "rule": "stage_ramp_revenue_max_enforced_by_revenue_formula_driver_adjustment",
  }


def _controller_issue_records(state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = state if isinstance(state, dict) else {}
  candidates: List[Any] = [
    payload.get("remaining_issues"),
    payload.get("detected_issues"),
    (
      (payload.get("current_issue_summaries") or {}).get("detected_issues")
      if isinstance(payload.get("current_issue_summaries"), dict)
      else None
    ),
  ]
  records: List[Dict[str, Any]] = []
  for candidate in candidates:
    if isinstance(candidate, list) and candidate:
      records = [item for item in candidate if isinstance(item, dict)]
      if records:
        break
  return records


def _controller_issue_gap_summary(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  records = _controller_issue_records(state)
  total_gap_abs = 0.0
  total_severity = 0.0
  issue_count_with_gap = 0
  issue_codes: List[str] = []
  by_issue: Dict[str, Dict[str, Any]] = {}
  for record in records:
    code = str(record.get("issue_code") or record.get("issue") or "").strip().lower()
    if code:
      issue_codes.append(code)
    gap_value = _safe_float(record.get("aggregate_gap_abs"))
    if gap_value is None:
      metric_gaps = [
        abs(float(_safe_float(spec.get("gap_abs")) or 0.0))
        for spec in (record.get("metric_debug") or [])
        if isinstance(spec, dict)
      ]
      gap_value = sum(metric_gaps) if metric_gaps else None
    severity_value = _safe_float(record.get("remaining_issue_severity_score"))
    if severity_value is None:
      severity_value = _safe_float(record.get("severity_score"))
    if gap_value is not None:
      gap_float = abs(float(gap_value))
      total_gap_abs += gap_float
      issue_count_with_gap += 1
    else:
      gap_float = 0.0
    severity_float = max(0.0, float(severity_value or 0.0))
    total_severity += severity_float
    if code:
      by_issue[code] = {
        "gap_abs": gap_float,
        "severity_score": severity_float,
      }
  return {
    "issue_codes": sorted(set(issue_codes)),
    "issue_count_with_gap": issue_count_with_gap,
    "total_gap_abs": total_gap_abs,
    "total_severity_score": total_severity,
    "by_issue": by_issue,
  }


def _payroll_repair_trigger_from_failure(previous_contract_failure: Dict[str, Any]) -> str:
  failure_text = str(previous_contract_failure or "").lower()
  if "payroll_stage_profitability_feasibility_failed" in failure_text:
    return "payroll_stage_profitability_feasibility_failed"
  return "payroll_revenue_economic_feasibility_failed"


def _payroll_repair_failure_from_issue_ledger(
  issue_status_records: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
  candidate_records: List[Dict[str, Any]] = []
  stage_profitability_failure = False
  for record in issue_status_records or []:
    if not isinstance(record, dict):
      continue
    text = str(record).lower()
    metric_debug = record.get("metric_debug") if isinstance(record.get("metric_debug"), list) else []
    metric_names = {
      str(item.get("metric_name") or "").strip().lower()
      for item in metric_debug
      if isinstance(item, dict)
    }
    if (
      "payroll_revenue_economic_feasibility_failed" in text
      or "payroll_stage_profitability_feasibility_failed" in text
      or "payroll_revenue_feasibility_violations" in text
      or "payroll_headcount_schedule" in text and "profitability" in text
      or "payroll" in metric_names
    ):
      if (
        "payroll_stage_profitability_feasibility_failed" in text
        or "stage_maturity" in text
        or "profitability" in text
        or any(
          isinstance(item, dict)
          and (
            item.get("actual_net_income_margin") is not None
            or item.get("stage_maturity_floor_margin") is not None
          )
          for item in metric_debug
        )
      ):
        stage_profitability_failure = True
      candidate_records.append(copy.deepcopy(record))
  if not candidate_records:
    return {}
  signature_bits: List[str] = []
  for record in candidate_records[:3]:
    issue_code = str(record.get("issue_code") or record.get("issue") or "").strip().lower()
    quarters = [
      int(_safe_float(item) or 0)
      for item in (record.get("remaining_problem_quarters") or [])
      if int(_safe_float(item) or 0) >= 1
    ]
    payroll_metrics = [
      {
        "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
        "actual_value": _safe_float(item.get("actual_value")),
        "target_floor": _safe_float(item.get("target_floor")),
        "target_ceiling": _safe_float(item.get("target_ceiling")),
      }
      for item in (record.get("metric_debug") or [])
      if isinstance(item, dict)
      and str(item.get("metric_name") or "").strip().lower() == "payroll"
    ][:4]
    signature_bits.append(
      f"{issue_code}:{','.join(str(q) for q in quarters[:8])}:{payroll_metrics}"
    )
  return {
    "error": (
      "payroll_stage_profitability_feasibility_failed"
      if stage_profitability_failure
      else "payroll_revenue_economic_feasibility_failed"
    ),
    "source": "convergence_issue_ledger",
    "signature": "|".join(signature_bits),
    "required_rebuild": (
      "Rebuild payroll_headcount_schedule using GPT's OEWS title/FTE/productivity contract, "
      "then rederive payroll-supported Capacity, rebuild revenue and payroll, and rerun FINMO."
    ),
    "issue_records": candidate_records[:5],
  }


def _issue_gap_materially_improved(
  *,
  before_summary: Dict[str, Any],
  after_summary: Dict[str, Any],
) -> bool:
  before_gap = float(_safe_float(before_summary.get("total_gap_abs")) or 0.0)
  after_gap = float(_safe_float(after_summary.get("total_gap_abs")) or 0.0)
  if before_gap <= 0.0:
    return False
  gap_delta = before_gap - after_gap
  if gap_delta <= 0.0:
    return False
  # A cycle is productive when it materially shrinks the table-backed issue
  # diagnostic, even if the issue needs another cycle to fully clear. Large
  # gaps still need a large move, while near-boundary residual gaps should not
  # be rejected just because the remaining dollar gap is already small.
  if before_gap >= 50000.0:
    absolute_floor = 1000.0
    percent_floor = before_gap * 0.02
  else:
    absolute_floor = 25.0
    percent_floor = before_gap * 0.005
  return gap_delta >= max(absolute_floor, percent_floor)


def _build_unified_cycle_quality_assessment(
  *,
  before_controller_resolution_state: Dict[str, Any],
  before_hard_rule_assessment: Dict[str, Any],
  after_controller_resolution_state: Dict[str, Any],
  after_hard_rule_assessment: Dict[str, Any],
  before_finmo_json: Dict[str, Any],
  after_finmo_json: Dict[str, Any],
  result_payload: Dict[str, Any],
  before_numeric_guidance_packet: Dict[str, Any],
  candidate_signature: Dict[str, Any],
  prior_quality_assessment: Dict[str, Any],
) -> Dict[str, Any]:
  """Decide whether a convergence cycle made durable progress worth keeping."""
  del before_finmo_json, after_finmo_json, before_numeric_guidance_packet, prior_quality_assessment
  before_state = before_controller_resolution_state if isinstance(before_controller_resolution_state, dict) else {}
  after_state = after_controller_resolution_state if isinstance(after_controller_resolution_state, dict) else {}
  before_remaining = int(_safe_float(before_state.get("remaining_issue_count")) or 0)
  after_remaining = int(_safe_float(after_state.get("remaining_issue_count")) or 0)
  before_resolved = int(_safe_float(before_state.get("resolved_issue_count")) or 0)
  after_resolved = int(_safe_float(after_state.get("resolved_issue_count")) or 0)
  before_score = float(_safe_float(before_state.get("overall_completion_score_pct")) or 0.0)
  after_score = float(_safe_float(after_state.get("overall_completion_score_pct")) or 0.0)
  before_hard_failures = _hard_rule_failure_count(before_hard_rule_assessment)
  after_hard_failures = _hard_rule_failure_count(after_hard_rule_assessment)
  before_issue_gap_summary = _controller_issue_gap_summary(before_state)
  after_issue_gap_summary = _controller_issue_gap_summary(after_state)
  issue_count_improved = after_remaining < before_remaining
  resolved_count_improved = after_resolved > before_resolved
  score_improved = after_score >= before_score + 1.0
  issue_gap_improved = _issue_gap_materially_improved(
    before_summary=before_issue_gap_summary,
    after_summary=after_issue_gap_summary,
  )
  hard_rules_improved = after_hard_failures < before_hard_failures
  hard_rules_worsened = after_hard_failures > before_hard_failures
  issue_count_regressed = after_remaining > before_remaining
  all_cleared = bool(after_state.get("all_cleared")) and after_hard_failures == 0
  meaningful_progress = bool(
    all_cleared
    or issue_count_improved
    or resolved_count_improved
    or hard_rules_improved
    or score_improved
    or issue_gap_improved
  )
  reject_attempt = bool(
    issue_count_regressed
    or hard_rules_worsened
    or not meaningful_progress
  )
  accepted = not reject_attempt
  return {
    "status": "accepted" if accepted else "rejected_no_meaningful_progress",
    "accepted": accepted,
    "reject_attempt": reject_attempt,
    "meaningful_progress": meaningful_progress,
    "no_progress": not meaningful_progress,
    "remaining_issue_count_before": before_remaining,
    "remaining_issue_count_after": after_remaining,
    "resolved_issue_count_before": before_resolved,
    "resolved_issue_count_after": after_resolved,
    "overall_completion_score_pct_before": before_score,
    "overall_completion_score_pct_after": after_score,
    "hard_rule_failure_count_before": before_hard_failures,
    "hard_rule_failure_count_after": after_hard_failures,
    "issue_count_improved": issue_count_improved,
    "issue_count_regressed": issue_count_regressed,
    "resolved_count_improved": resolved_count_improved,
    "score_improved": score_improved,
    "issue_gap_improved": issue_gap_improved,
    "issue_gap_abs_before": before_issue_gap_summary.get("total_gap_abs"),
    "issue_gap_abs_after": after_issue_gap_summary.get("total_gap_abs"),
    "issue_gap_summary_before": before_issue_gap_summary,
    "issue_gap_summary_after": after_issue_gap_summary,
    "hard_rules_improved": hard_rules_improved,
    "hard_rules_worsened": hard_rules_worsened,
    "all_cleared": all_cleared,
    "worsened_without_compensating_improvement": bool((issue_count_regressed or hard_rules_worsened) and not meaningful_progress),
    "solver_invoked": bool((result_payload or {}).get("solver_invoked", True)),
    "candidate_signature": candidate_signature if isinstance(candidate_signature, dict) else {},
    "open_issue_codes_before": [
      str(item.get("issue_code") or "").strip().lower()
      for item in (before_state.get("remaining_issues") or [])
      if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
    ],
    "open_issue_codes_after": [
      str(item.get("issue_code") or "").strip().lower()
      for item in (after_state.get("remaining_issues") or [])
      if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
    ],
  }

# Phase 9 P3.24 — `_run_unified_post_grid_system_run` (the 3000-line
# legacy convergence cycle loop, formerly defined here) and its public
# alias `run_unified_post_grid_system_run` were deleted. The function was
# bypassed in 2026-05-08 (Phase 8 step 4) at orchestrator.py:1342 and was
# documented broken under current validator hardening. Phase 9 P3.24
# completes the deletion. The convergence package retains its utility
# helpers (build_retry_scope_payload, validate_unified_convergence_contract_horizon,
# bind_runtime_dependencies, etc.) which remain used by the target-seeking
# orchestrator + numeric solver. See docs/architecture/p3_23c_unified_convergence_status.md.
