"""Post-intake fail-fast switches and named failure groups."""

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from client_intake_and_finmo.fail_fast.common import (  # type: ignore
  FailFastError,
  convergence_test_mode_enabled,
  fail_fast_enabled,
  fail_fast_raise,
  fail_fast_result,
)


POST_INTAKE_FAIL_FAST_ENV = "POST_INTAKE_FAIL_FAST_ENABLED"


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
  "payroll_headcount_schedule_missing_at_application",
  "payroll_headcount_quarter_total_mismatch",
  "payroll_headcount_economic_coverage_failed",
  "payroll_headcount_contract_invalid_fail_fast",
  "payroll_headcount_model_input_not_applied",
  "payroll_headcount_finmo_mismatch",
}

BUSINESS_SHAPE_TEST_MODE_FAIL_FLAGS: Set[str] = {
  "stage_ramp_revenue_path_not_applied",
  "stage_ramp_expense_path_not_applied",
  "marketing_missing_or_zero",
  "marketing_model_input_missing",
}

GLOBAL_POST_INTAKE_TEST_MODE_FAIL_FLAGS: Set[str] = {
  "post_intake_horizon_invalid",
  "post_intake_model_input_missing",
  "post_intake_finmo_missing",
  "post_intake_model_input_row_missing",
  "post_intake_model_input_values_missing",
  "post_intake_model_input_value_invalid",
  "post_intake_revenue_driver_bundle_invalid",
  "post_intake_revenue_driver_formula_mismatch",
  "post_intake_finmo_core_row_invalid",
  "post_intake_statement_math_invalid",
  "post_intake_schedule_marker_missing",
  "post_intake_cash_buffer_violation",
  "post_intake_lookup_table_contract_invalid",
  "post_intake_mapping_formula_contract_invalid",
  "post_intake_mapping_formula_application_invalid",
}

TRANSLATION_TEST_MODE_FAIL_FLAGS: Set[str] = {
  "metric_to_lever_translation_failed",
}


def post_intake_fail_fast_enabled() -> bool:
  return fail_fast_enabled("POST_INTAKE")


def post_intake_convergence_test_mode_enabled() -> bool:
  return convergence_test_mode_enabled()


def post_intake_fail_fast_result(
  code: str,
  message: str = "",
  *,
  stage: str = "",
  details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return fail_fast_result(
    code,
    message,
    phase="POST_INTAKE",
    stage=stage,
    details=details,
  )


def _post_intake_runtime_validation_stage(stage: str) -> bool:
  normalized = str(stage or "").strip().lower()
  return normalized.startswith("post_intake_initialize_validation") or normalized.startswith(
    "post_intake_finalize_validation"
  )


def post_intake_fail_fast_raise(
  code: str,
  message: str = "",
  *,
  stage: str = "",
  details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  result = fail_fast_raise(
    code,
    message,
    phase="POST_INTAKE",
    stage=stage,
    details=details,
  )
  if _post_intake_runtime_validation_stage(stage):
    raise FailFastError(
      result["code"],
      result["message"],
      phase=result["phase"],
      stage=result["stage"],
      details=result["details"],
    )
  return result


def _safe_float(value: Any) -> Optional[float]:
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _safe_int(value: Any) -> Optional[int]:
  number = _safe_float(value)
  if number is None:
    return None
  return int(round(float(number)))


def _ratio_2dp(value: Any) -> Optional[Decimal]:
  number = _safe_float(value)
  if number is None:
    return None
  return Decimal(str(float(number))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _live_quarter_rows(finmo_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = finmo_json if isinstance(finmo_json, dict) else {}
  rows = payload.get("quarter_rows") if isinstance(payload.get("quarter_rows"), list) else []
  live_rows = [
    row for row in rows
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  ]
  live_rows.sort(key=lambda row: int(_safe_float(row.get("quarter_index")) or 0))
  return live_rows


def _expected_horizon(contract_name: str = "unified_convergence_decision") -> int:
  try:
    from client_intake_and_finmo.post_intake_mapping import post_intake_contract_forecast_horizon_quarter_count  # type: ignore

    count = int(post_intake_contract_forecast_horizon_quarter_count(contract_name=contract_name) or 0)
    if count > 0:
      return count
  except Exception:
    pass
  return 20


def _row_live_values(row: Optional[Dict[str, Any]], *, horizon: int) -> List[Any]:
  values = list((row or {}).get("values") or []) if isinstance(row, dict) else []
  if len(values) >= horizon + 1:
    return values[1:horizon + 1]
  return values[:horizon]


def _iter_model_input_rows(
  model_input_json: Optional[Dict[str, Any]],
  *,
  section_names: Iterable[str] = ("revenue", "expenses", "balance_sheet", "schedules"),
) -> List[Tuple[str, Dict[str, Any]]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  rows: List[Tuple[str, Dict[str, Any]]] = []
  for section_name in section_names:
    source = sections.get(section_name) if isinstance(sections, dict) else None
    if section_name == "schedules" and isinstance(source, dict):
      source = source.get("rows")
    if not isinstance(source, list):
      continue
    for row in source:
      if isinstance(row, dict):
        rows.append((section_name, row))
  return rows


def _find_model_input_row(
  model_input_json: Optional[Dict[str, Any]],
  *,
  section_name: str,
  label: str = "",
  lever_id: str = "",
) -> Optional[Dict[str, Any]]:
  target_label = str(label or "").strip().lower()
  target_lever = str(lever_id or "").strip().lower()
  for current_section, row in _iter_model_input_rows(model_input_json, section_names=(section_name,)):
    del current_section
    current_label = str(row.get("label") or "").strip().lower()
    current_lever = str(row.get("lever_id") or "").strip().lower()
    if target_label and current_label == target_label:
      return row
    if target_lever and current_lever == target_lever:
      return row
  return None


def _finmo_field_from_mapping(financial_model_field: Any) -> str:
  raw = str(financial_model_field or "").strip()
  prefix = "finmo_json.quarter_rows[*]."
  if raw.startswith(prefix):
    field = raw[len(prefix):].strip()
  else:
    field = raw.strip()
  aliases = {
    "cogs": "cost_of_goods_sold",
    "g_and_a": "general_and_administrative",
    "distributions": "owner_distributions",
  }
  return aliases.get(field, field)


def _model_input_row_for_mapping(
  model_input_json: Optional[Dict[str, Any]],
  mapping_row: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  lever_id = str(mapping_row.get("lever_id") or "").strip()
  if lever_id.startswith("revenue::*::*::"):
    return None
  section = lever_id.split("::", 1)[0] if "::" in lever_id else ""
  label = lever_id.split("::", 1)[1] if "::" in lever_id else ""
  if section == "balance_sheet":
    section_name = "balance_sheet"
  elif section == "expenses":
    section_name = "expenses"
  elif section == "schedules":
    section_name = "schedules"
  else:
    section_name = section
  return _find_model_input_row(
    model_input_json,
    section_name=section_name,
    label=label,
    lever_id=lever_id,
  )


def _formula_required_for_quarter(
  *,
  required_when_key: str,
  finmo_row: Dict[str, Any],
  prior_finmo_row: Optional[Dict[str, Any]],
) -> bool:
  key = str(required_when_key or "").strip().lower()
  if key == "optional":
    return False
  if key in {"", "always", "cash_strategy_requires"}:
    return True
  if key == "revenue_positive":
    return float(_safe_float(finmo_row.get("revenue")) or 0.0) > 0
  if key == "debt_outstanding":
    return (
      float(_safe_float(finmo_row.get("long_term_debt")) or 0.0)
      + float(_safe_float(finmo_row.get("short_term_debt")) or 0.0)
    ) > 0
  if key == "prior_ppe_positive":
    prior = prior_finmo_row if isinstance(prior_finmo_row, dict) else {}
    return float(_safe_float(prior.get("ppe")) or 0.0) > 0
  return True


def _model_input_live_values_by_lever(
  model_input_json: Optional[Dict[str, Any]],
  *,
  horizon: int,
) -> Dict[str, List[Any]]:
  values_by_lever: Dict[str, List[Any]] = {}
  for _section, row in _iter_model_input_rows(model_input_json):
    lever_id = str(row.get("lever_id") or "").strip()
    if not lever_id:
      continue
    values_by_lever[lever_id] = _row_live_values(row, horizon=horizon)
  return values_by_lever


def _raise_if_violations(
  code: str,
  message: str,
  *,
  stage: str,
  violations: List[Dict[str, Any]],
  extra_details: Optional[Dict[str, Any]] = None,
) -> None:
  if not violations:
    return
  details = dict(extra_details or {})
  details["violation_count"] = len(violations)
  details["violations"] = violations[:50]
  post_intake_fail_fast_raise(code, message, stage=stage, details=details)


def _stage_ramp_rows(stage_ramp_contract: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
  payload = stage_ramp_contract if isinstance(stage_ramp_contract, dict) else {}
  rows: Dict[int, Dict[str, Any]] = {}
  for row in payload.get("quarter_ramp_grid") or []:
    if not isinstance(row, dict):
      continue
    quarter = int(_safe_float(row.get("quarter_index") or row.get("q")) or 0)
    if quarter >= 1:
      rows[quarter] = row
  return rows


def _model_input_lever_values(
  model_input_json: Optional[Dict[str, Any]],
  lever_id: str,
) -> Optional[List[Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  for rows in sections.values():
    if not isinstance(rows, list):
      continue
    for row in rows:
      if not isinstance(row, dict):
        continue
      if str(row.get("lever_id") or "").strip().lower() == str(lever_id or "").strip().lower():
        values = row.get("values")
        return list(values) if isinstance(values, list) else []
  return None


def assert_stage_ramp_revenue_path_applied(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  """Fail if actual revenue stops obeying the GPT-selected Q1-Q20 ramp."""
  ramp_rows = _stage_ramp_rows(stage_ramp_contract)
  live_rows = _live_quarter_rows(finmo_json)
  if not ramp_rows:
    post_intake_fail_fast_raise(
      "stage_ramp_revenue_path_not_applied",
      "stage_ramp_contract is missing quarter_ramp_grid, so revenue path cannot be validated.",
      stage=stage,
      details={"stage_ramp_contract_present": isinstance(stage_ramp_contract, dict)},
    )
    return
  violations: List[Dict[str, Any]] = []
  revenue_by_q = {
    int(_safe_float(row.get("quarter_index")) or 0): float(_safe_float(row.get("revenue")) or 0.0)
    for row in live_rows
  }
  for quarter in range(2, 21):
    previous_revenue = revenue_by_q.get(quarter - 1)
    current_revenue = revenue_by_q.get(quarter)
    ramp_row = ramp_rows.get(quarter) or {}
    target_growth = _safe_float(
      ramp_row.get("revenue_qoq_target")
      or ramp_row.get("rev_target")
    )
    max_growth = _safe_float(
      ramp_row.get("revenue_qoq_max")
      or ramp_row.get("rev_max")
    )
    if previous_revenue is None or current_revenue is None or previous_revenue <= 0.0:
      continue
    actual_growth_2dp = _ratio_2dp(float(current_revenue) / max(float(previous_revenue), 1e-9))
    if target_growth is not None and target_growth > 1.0:
      required_growth_2dp = _ratio_2dp(target_growth)
      if (
        actual_growth_2dp is not None
        and required_growth_2dp is not None
        and actual_growth_2dp < required_growth_2dp
      ):
        required_revenue = int(round(float(previous_revenue) * float(target_growth)))
        violations.append(
          {
            "quarter_index": quarter,
            "previous_revenue": int(round(float(previous_revenue))),
            "actual_revenue": int(round(float(current_revenue))),
            "actual_growth_2dp": str(actual_growth_2dp),
            "required_revenue_from_ramp_target": required_revenue,
            "required_growth_2dp": str(required_growth_2dp),
            "revenue_qoq_target": target_growth,
            "ramp_grid_row": ramp_row,
          }
        )
    if max_growth is not None and max_growth > 0.0:
      allowed_growth_2dp = _ratio_2dp(max_growth)
      if (
        actual_growth_2dp is not None
        and allowed_growth_2dp is not None
        and actual_growth_2dp > allowed_growth_2dp
      ):
        maximum_revenue = int(round(float(previous_revenue) * float(max_growth)))
        violations.append(
          {
            "quarter_index": quarter,
            "previous_revenue": int(round(float(previous_revenue))),
            "actual_revenue": int(round(float(current_revenue))),
            "actual_growth_2dp": str(actual_growth_2dp),
            "maximum_revenue_from_ramp_max": maximum_revenue,
            "allowed_growth_2dp": str(allowed_growth_2dp),
            "revenue_qoq_max": max_growth,
            "ramp_grid_row": ramp_row,
          }
        )
  if violations:
    post_intake_fail_fast_raise(
      "stage_ramp_revenue_path_not_applied",
      "Actual FINMO revenue does not obey the GPT-selected stage_ramp_contract Q1-Q20 revenue path.",
      stage=stage,
      details={
        "violation_count": len(violations),
        "violations": violations[:20],
      },
    )


def assert_stage_ramp_expense_path_applied(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  """Fail if actual cost/expense ratios exceed GPT's table-backed stage ramp bands."""
  ramp_rows = _stage_ramp_rows(stage_ramp_contract)
  live_rows = _live_quarter_rows(finmo_json)
  if not ramp_rows or not live_rows:
    return
  field_specs = [
    ("cost_of_goods_sold", "cogs_percent_of_revenue_max", "cogs_max"),
    ("marketing", "marketing_percent_of_revenue_max", "marketing_max"),
    ("research_and_development", "rd_percent_of_revenue_max", "rd_max"),
    ("general_and_administrative", "g_and_a_percent_of_revenue_max", "g_and_a_max"),
    ("lease_rent", "lease_percent_of_revenue_max", "lease_max"),
  ]
  violations: List[Dict[str, Any]] = []
  for row in live_rows:
    quarter = int(_safe_float(row.get("quarter_index")) or 0)
    revenue = float(_safe_float(row.get("revenue")) or 0.0)
    if quarter < 1 or revenue <= 0.0:
      continue
    ramp_row = ramp_rows.get(quarter) or {}
    for finmo_field, full_key, compact_key in field_specs:
      max_ratio = _safe_float(
        ramp_row.get(full_key)
        if ramp_row.get(full_key) is not None
        else ramp_row.get(compact_key)
      )
      if max_ratio is None or max_ratio <= 0.0:
        continue
      actual_value = float(_safe_float(row.get(finmo_field)) or 0.0)
      actual_ratio = actual_value / revenue if revenue > 0.0 else 0.0
      if actual_ratio > float(max_ratio) + 0.0001:
        violations.append(
          {
            "quarter_index": quarter,
            "finmo_field": finmo_field,
            "actual_value": int(round(actual_value)),
            "revenue": int(round(revenue)),
            "actual_ratio": round(actual_ratio, 6),
            "stage_ramp_max_ratio": round(float(max_ratio), 6),
            "ramp_grid_row": ramp_row,
          }
        )
  _raise_if_violations(
    "stage_ramp_expense_path_not_applied",
    "Actual FINMO cost/expense ratios exceed the GPT-selected stage_ramp_contract Q1-Q20 bands.",
    stage=stage,
    violations=violations,
  )


def assert_marketing_presence_applied(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  """Fail if a revenue-producing business silently carries zero marketing."""
  ramp_rows = _stage_ramp_rows(stage_ramp_contract)
  marketing_values = _model_input_lever_values(model_input_json, "expenses::Marketing")
  if marketing_values is None:
    post_intake_fail_fast_raise(
      "marketing_model_input_missing",
      "Marketing model-input lever row is missing; mapping table expects expenses::Marketing to be available.",
      stage=stage,
      details={"lever_id": "expenses::Marketing"},
    )
    return
  live_rows = _live_quarter_rows(finmo_json)
  revenue_positive_quarters = [
    int(_safe_float(row.get("quarter_index")) or 0)
    for row in live_rows
    if float(_safe_float(row.get("revenue")) or 0.0) > 0.0
  ]
  if not revenue_positive_quarters:
    return
  marketing_by_q = {
    int(_safe_float(row.get("quarter_index")) or 0): float(_safe_float(row.get("marketing")) or 0.0)
    for row in live_rows
  }
  ramp_requires_marketing = any(
    float(_safe_float(row.get("marketing_percent_of_revenue_max") or row.get("marketing_max")) or 0.0) > 0.0
    for row in ramp_rows.values()
  )
  if not ramp_requires_marketing:
    return
  positive_marketing_quarters = [
    quarter for quarter in revenue_positive_quarters
    if float(marketing_by_q.get(quarter) or 0.0) > 0.0
  ]
  if not positive_marketing_quarters:
    post_intake_fail_fast_raise(
      "marketing_missing_or_zero",
      "Marketing is zero for every live revenue quarter even though stage_ramp_contract allows/requires marketing as an operating cost.",
      stage=stage,
      details={
        "revenue_positive_quarters": revenue_positive_quarters,
        "marketing_values_sample": marketing_values[:21],
        "ramp_marketing_max_by_quarter": {
          quarter: (
            row.get("marketing_percent_of_revenue_max")
            if row.get("marketing_percent_of_revenue_max") is not None
            else row.get("marketing_max")
          )
          for quarter, row in sorted(ramp_rows.items())
        },
      },
    )


def assert_post_intake_business_shape_applied(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  assert_stage_ramp_revenue_path_applied(
    stage_ramp_contract=stage_ramp_contract,
    finmo_json=finmo_json,
    stage=stage,
  )
  assert_marketing_presence_applied(
    stage_ramp_contract=stage_ramp_contract,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    stage=stage,
  )
  assert_stage_ramp_expense_path_applied(
    stage_ramp_contract=stage_ramp_contract,
    finmo_json=finmo_json,
    stage=stage,
  )


def assert_post_intake_horizon_integrity(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
  contract_name: str = "unified_convergence_decision",
) -> None:
  """Fail if post-intake stops being exactly Q1-Q20 forecast plus optional Q0 stub."""
  horizon = _expected_horizon(contract_name)
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  if not payload:
    post_intake_fail_fast_raise(
      "post_intake_model_input_missing",
      "model_input_json is required before any post-intake stage can pass.",
      stage=stage,
    )
    return
  if not isinstance(finmo_json, dict) or not finmo_json:
    post_intake_fail_fast_raise(
      "post_intake_finmo_missing",
      "finmo_json is required before any post-intake stage can pass.",
      stage=stage,
    )
    return
  violations: List[Dict[str, Any]] = []
  finmo_rows = [
    row for row in (finmo_json.get("quarter_rows") or [])
    if isinstance(row, dict)
  ]
  finmo_quarters = [
    int(_safe_float(row.get("quarter_index")) or -1)
    for row in finmo_rows
  ]
  live_finmo_quarters = sorted(quarter for quarter in finmo_quarters if quarter >= 1)
  expected_live_quarters = list(range(1, horizon + 1))
  if live_finmo_quarters != expected_live_quarters:
    violations.append(
      {
        "object": "finmo_json.quarter_rows",
        "expected_live_quarters": expected_live_quarters,
        "actual_live_quarters": live_finmo_quarters,
      }
    )
  extra_finmo_quarters = sorted(quarter for quarter in finmo_quarters if quarter > horizon)
  if extra_finmo_quarters:
    violations.append(
      {
        "object": "finmo_json.quarter_rows",
        "reason": "forecast_horizon_exceeded",
        "extra_quarters": extra_finmo_quarters,
      }
    )
  periods = payload.get("periods") if isinstance(payload.get("periods"), list) else []
  if periods:
    live_periods = [
      item for item in periods
      if isinstance(item, dict) and not bool(item.get("is_stub"))
    ]
    stub_periods = [
      item for item in periods
      if isinstance(item, dict) and bool(item.get("is_stub"))
    ]
    if len(live_periods) != horizon:
      violations.append(
        {
          "object": "model_input_json.periods",
          "expected_live_period_count": horizon,
          "actual_live_period_count": len(live_periods),
        }
      )
    if len(stub_periods) > 1:
      violations.append(
        {
          "object": "model_input_json.periods",
          "reason": "multiple_stub_periods",
          "stub_period_count": len(stub_periods),
        }
      )
  _raise_if_violations(
    "post_intake_horizon_invalid",
    "Post-intake state must be exactly one stub Q0 plus live forecast Q1-Q20; Q21 or partial horizons are invalid.",
    stage=stage,
    violations=violations,
    extra_details={"contract_name": contract_name, "horizon": horizon},
  )


def assert_post_intake_mapping_formula_contract_integrity(
  *,
  stage: str,
) -> None:
  """Fail unless the SQL mapping table contains usable formula metadata."""
  try:
    from client_intake_and_finmo.post_intake_mapping import post_intake_driver_target_mapping_errors  # type: ignore

    errors = list(post_intake_driver_target_mapping_errors() or [])
  except Exception as exc:
    post_intake_fail_fast_raise(
      "post_intake_mapping_formula_contract_invalid",
      f"Unable to validate SQL mapping formula contracts: {exc}",
      stage=stage,
      details={"exception": str(exc)},
    )
    return
  formula_errors = [
    str(item)
    for item in errors
    if "formula" in str(item).lower()
    or "seed_" in str(item).lower()
    or "required_when" in str(item).lower()
    or "allow_zero" in str(item).lower()
  ]
  _raise_if_violations(
    "post_intake_mapping_formula_contract_invalid",
    "Every active mapping row must declare table-backed formula metadata before post-intake runs.",
    stage=stage,
    violations=[{"reason": item} for item in formula_errors],
  )


def assert_post_intake_mapping_formula_application_integrity(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
  contract_name: str = "unified_convergence_decision",
) -> None:
  """Fail if mapped model-input rows do not flow to FINMO per table formula contracts."""
  horizon = _expected_horizon(contract_name)
  try:
    from client_intake_and_finmo.post_intake_mapping import post_intake_driver_formula_contract_rows  # type: ignore

    formula_rows = post_intake_driver_formula_contract_rows()
  except Exception as exc:
    post_intake_fail_fast_raise(
      "post_intake_mapping_formula_contract_invalid",
      f"Unable to load SQL mapping formula rows: {exc}",
      stage=stage,
      details={"exception": str(exc)},
    )
    return

  live_rows = _live_quarter_rows(finmo_json)
  live_by_q = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in live_rows
  }
  violations: List[Dict[str, Any]] = []
  for mapping_row in formula_rows:
    lever_id = str(mapping_row.get("lever_id") or "").strip()
    validation_key = str(mapping_row.get("validation_formula_key") or "").strip().lower()
    if lever_id.startswith("revenue::*::*::"):
      continue
    model_row = _model_input_row_for_mapping(model_input_json, mapping_row)
    if model_row is None:
      violations.append(
        {
          "lever_id": lever_id,
          "reason": "mapped_model_input_row_missing",
          "model_input_field": mapping_row.get("model_input_field"),
          "source_of_truth": "sql.post_intak_mapping_lookup",
        }
      )
      continue
    live_values = _row_live_values(model_row, horizon=horizon)
    if len(live_values) != horizon:
      violations.append(
        {
          "lever_id": lever_id,
          "reason": "mapped_model_input_row_horizon_invalid",
          "expected_live_count": horizon,
          "actual_live_count": len(live_values),
        }
      )
      continue
    target_field = _finmo_field_from_mapping(mapping_row.get("financial_model_field"))
    allow_zero = bool(mapping_row.get("allow_zero"))
    required_when_key = str(mapping_row.get("required_when_key") or "").strip().lower()
    for quarter in range(1, horizon + 1):
      finmo_row = live_by_q.get(quarter) or {}
      prior_finmo_row = live_by_q.get(quarter - 1) if quarter > 1 else {}
      required_now = _formula_required_for_quarter(
        required_when_key=required_when_key,
        finmo_row=finmo_row,
        prior_finmo_row=prior_finmo_row,
      )
      value = _safe_float(live_values[quarter - 1])
      if value is None:
        violations.append(
          {
            "lever_id": lever_id,
            "quarter_index": quarter,
            "reason": "mapped_model_input_value_nonnumeric",
            "value": live_values[quarter - 1],
          }
        )
        break
      if required_now and not allow_zero and value <= 0:
        violations.append(
          {
            "lever_id": lever_id,
            "quarter_index": quarter,
            "reason": "mapped_model_input_value_zero_disallowed",
            "value": value,
            "required_when_key": required_when_key,
          }
        )
        break
      if validation_key == "finmo_equals_revenue_times_model_input_ratio":
        revenue = float(_safe_float(finmo_row.get("revenue")) or 0.0)
        actual = int(round(float(_safe_float(finmo_row.get(target_field)) or 0.0)))
        expected = int(round(revenue * value))
        if actual != expected:
          violations.append(
            {
              "lever_id": lever_id,
              "quarter_index": quarter,
              "field": target_field,
              "actual_finmo": actual,
              "expected_from_mapping_formula": expected,
              "validation_formula_key": validation_key,
            }
          )
          break
      elif validation_key == "finmo_equals_model_input_value":
        actual = int(round(float(_safe_float(finmo_row.get(target_field)) or 0.0)))
        expected = int(round(value))
        if actual != expected:
          violations.append(
            {
              "lever_id": lever_id,
              "quarter_index": quarter,
              "field": target_field,
              "actual_finmo": actual,
              "expected_from_mapping_formula": expected,
              "validation_formula_key": validation_key,
            }
          )
          break
  _raise_if_violations(
    "post_intake_mapping_formula_application_invalid",
    "Every mapped model-input row must exist and reconcile to FINMO through its SQL mapping formula contract.",
    stage=stage,
    violations=violations,
    extra_details={"horizon": horizon, "mapping_table": "post_intak_mapping_lookup"},
  )


def assert_post_intake_model_input_rows_integrity(
  *,
  model_input_json: Optional[Dict[str, Any]],
  stage: str,
  contract_name: str = "unified_convergence_decision",
) -> None:
  """Fail if any model-input driver row is missing, short, nonnumeric, or negative."""
  horizon = _expected_horizon(contract_name)
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  if not isinstance(sections, dict):
    post_intake_fail_fast_raise(
      "post_intake_model_input_missing",
      "model_input_json.sections is required.",
      stage=stage,
    )
    return
  required_rows = [
    ("expenses", "Cost of Goods Sold", ""),
    ("expenses", "Marketing", "expenses::Marketing"),
    ("expenses", "Lease", ""),
    ("expenses", "Payroll", "expenses::Payroll"),
    ("expenses", "General & Administrative", ""),
    ("expenses", "Interest Rate", ""),
    ("expenses", "Depreciation", ""),
    ("expenses", "Taxes", ""),
    ("balance_sheet", "Accounts Receivable Days", ""),
    ("balance_sheet", "Inventory Days", ""),
    ("balance_sheet", "Prepaid Expenses (% of Revenue)", ""),
    ("balance_sheet", "Accounts Payable Days", ""),
    ("balance_sheet", "Deferred Revenue (% of Revenue)", ""),
    ("balance_sheet", "Short Term Debt (% of LTD)", ""),
    ("balance_sheet", "Owner's Capital", ""),
    ("balance_sheet", "Distributions", ""),
    ("balance_sheet", "Other Equity", ""),
    ("schedules", "Capital Expenditures", "schedules::Capital Expenditures"),
    ("schedules", "Debt Issuance (New Borrowing)", "schedules::Debt Issuance (New Borrowing)"),
    ("schedules", "Debt Repayment (Scheduled)", "schedules::Debt Repayment (Scheduled)"),
  ]
  missing_rows: List[Dict[str, Any]] = []
  for section_name, label, lever_id in required_rows:
    if _find_model_input_row(model_input_json, section_name=section_name, label=label, lever_id=lever_id) is None:
      missing_rows.append({"section": section_name, "label": label, "lever_id": lever_id})
  if missing_rows:
    post_intake_fail_fast_raise(
      "post_intake_model_input_row_missing",
      "Required post-intake model-input rows are missing.",
      stage=stage,
      details={"missing_rows": missing_rows},
    )
  value_violations: List[Dict[str, Any]] = []
  for section_name, row in _iter_model_input_rows(model_input_json):
    label = str(row.get("label") or row.get("driver") or "").strip()
    lever_id = str(row.get("lever_id") or "").strip()
    values = list(row.get("values") or [])
    live_values = _row_live_values(row, horizon=horizon)
    if len(values) not in {horizon, horizon + 1}:
      value_violations.append(
        {
          "section": section_name,
          "label": label,
          "lever_id": lever_id,
          "reason": "values_length_invalid",
          "expected_length": [horizon, horizon + 1],
          "actual_length": len(values),
        }
      )
      continue
    if len(live_values) != horizon:
      value_violations.append(
        {
          "section": section_name,
          "label": label,
          "lever_id": lever_id,
          "reason": "live_values_missing_full_horizon",
          "expected_live_count": horizon,
          "actual_live_count": len(live_values),
        }
      )
      continue
    for idx, value in enumerate(live_values, start=1):
      number = _safe_float(value)
      if number is None:
        value_violations.append(
          {
            "section": section_name,
            "label": label,
            "lever_id": lever_id,
            "quarter_index": idx,
            "reason": "nonnumeric_value",
            "value": value,
          }
        )
        break
      if number < 0:
        value_violations.append(
          {
            "section": section_name,
            "label": label,
            "lever_id": lever_id,
            "quarter_index": idx,
            "reason": "negative_model_input_value",
            "value": number,
          }
        )
        break
  _raise_if_violations(
    "post_intake_model_input_value_invalid",
    "Every post-intake model-input driver row must cover Q1-Q20 with finite nonnegative values.",
    stage=stage,
    violations=value_violations,
    extra_details={"horizon": horizon},
  )


def assert_post_intake_revenue_driver_integrity(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
  contract_name: str = "unified_convergence_decision",
) -> None:
  """Fail if revenue is not generated by Capacity x Unit Price x Utilization."""
  horizon = _expected_horizon(contract_name)
  revenue_rows = [
    row for section, row in _iter_model_input_rows(model_input_json, section_names=("revenue",))
    if section == "revenue"
  ]
  if not revenue_rows:
    post_intake_fail_fast_raise(
      "post_intake_revenue_driver_bundle_invalid",
      "Revenue driver rows are missing; revenue must be driven by Capacity, Unit Price, and Utilization.",
      stage=stage,
    )
    return
  bundle: Dict[str, Dict[str, Dict[str, Any]]] = {}
  for row in revenue_rows:
    slot = str(row.get("revenue_slot_key") or "").strip()
    if not slot:
      slot = "::".join([
        str(row.get("lob") or "LOB 1").strip(),
        str(row.get("product") or "Product 1").strip(),
      ])
    driver = str(row.get("driver") or "").strip()
    bundle.setdefault(slot, {})[driver] = row
  bundle_violations: List[Dict[str, Any]] = []
  for slot, drivers in sorted(bundle.items()):
    missing = [driver for driver in ("Capacity", "Unit Price", "Utilization") if driver not in drivers]
    if missing:
      bundle_violations.append({"revenue_slot_key": slot, "missing_drivers": missing})
      continue
    for driver, row in drivers.items():
      live_values = _row_live_values(row, horizon=horizon)
      for idx, value in enumerate(live_values, start=1):
        number = float(_safe_float(value) or 0.0)
        if driver == "Utilization" and number > 1.0:
          bundle_violations.append(
            {
              "revenue_slot_key": slot,
              "driver": driver,
              "quarter_index": idx,
              "reason": "utilization_above_100_percent",
              "value": number,
            }
          )
          break
  _raise_if_violations(
    "post_intake_revenue_driver_bundle_invalid",
    "Every revenue product must have Capacity, Unit Price, and Utilization rows with valid Q1-Q20 values.",
    stage=stage,
    violations=bundle_violations,
    extra_details={"horizon": horizon},
  )
  formula_violations: List[Dict[str, Any]] = []
  computed_revenue_by_q = {quarter: 0.0 for quarter in range(1, horizon + 1)}
  for drivers in bundle.values():
    if not all(driver in drivers for driver in ("Capacity", "Unit Price", "Utilization")):
      continue
    capacity = _row_live_values(drivers["Capacity"], horizon=horizon)
    price = _row_live_values(drivers["Unit Price"], horizon=horizon)
    utilization = _row_live_values(drivers["Utilization"], horizon=horizon)
    for quarter in range(1, horizon + 1):
      computed_revenue_by_q[quarter] += (
        max(0.0, float(_safe_float(capacity[quarter - 1]) or 0.0))
        * max(0.0, float(_safe_float(price[quarter - 1]) or 0.0))
        * max(0.0, float(_safe_float(utilization[quarter - 1]) or 0.0))
      )
  actual_revenue_by_q = {
    int(_safe_float(row.get("quarter_index")) or 0): float(_safe_float(row.get("revenue")) or 0.0)
    for row in _live_quarter_rows(finmo_json)
  }
  for quarter in range(1, horizon + 1):
    expected = int(round(computed_revenue_by_q.get(quarter) or 0.0))
    actual = int(round(actual_revenue_by_q.get(quarter) or 0.0))
    if expected != actual:
      formula_violations.append(
        {
          "quarter_index": quarter,
          "computed_from_model_input_drivers": expected,
          "finmo_revenue": actual,
          "formula": "sum(Capacity * Unit Price * Utilization)",
        }
      )
  _raise_if_violations(
    "post_intake_revenue_driver_formula_mismatch",
    "FINMO revenue must equal model-input Capacity x Unit Price x Utilization for every live quarter.",
    stage=stage,
    violations=formula_violations,
  )


def assert_post_intake_finmo_statement_integrity(
  *,
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
  contract_name: str = "unified_convergence_decision",
) -> None:
  horizon = _expected_horizon(contract_name)
  live_rows = _live_quarter_rows(finmo_json)
  required_keys = [
    "revenue",
    "cost_of_goods_sold",
    "gross_profit",
    "marketing",
    "lease_rent",
    "payroll",
    "general_and_administrative",
    "ebitda",
    "interest",
    "depreciation",
    "taxes",
    "net_income",
    "cash",
    "accounts_receivable",
    "inventory",
    "current_assets",
    "ppe",
    "total_assets",
    "accounts_payable",
    "short_term_debt",
    "current_liabilities",
    "long_term_debt",
    "total_liabilities",
    "owners_capital",
    "retained_earnings",
    "other_equity",
    "total_equity",
    "total_liabilities_and_equity",
    "capital_expenditures",
    "debt_issuance",
    "debt_repayment",
    "financing_cash_flow",
    "ending_cash",
  ]
  invalid_rows: List[Dict[str, Any]] = []
  for row in live_rows:
    quarter = int(_safe_float(row.get("quarter_index")) or 0)
    for key in required_keys:
      number = _safe_float(row.get(key))
      if number is None:
        invalid_rows.append({"quarter_index": quarter, "field": key, "reason": "missing_or_nonnumeric"})
        break
    if len(invalid_rows) >= horizon:
      break
  _raise_if_violations(
    "post_intake_finmo_core_row_invalid",
    "FINMO must expose every core P&L, balance-sheet, and cash-flow field for every live quarter.",
    stage=stage,
    violations=invalid_rows,
  )
  math_violations: List[Dict[str, Any]] = []
  for row in live_rows:
    quarter = int(_safe_float(row.get("quarter_index")) or 0)
    revenue = float(_safe_float(row.get("revenue")) or 0.0)
    cogs = float(_safe_float(row.get("cost_of_goods_sold")) or 0.0)
    gross_profit = float(_safe_float(row.get("gross_profit")) or 0.0)
    ebitda = float(_safe_float(row.get("ebitda")) or 0.0)
    interest = float(_safe_float(row.get("interest")) or 0.0)
    depreciation = float(_safe_float(row.get("depreciation")) or 0.0)
    taxes = float(_safe_float(row.get("taxes")) or 0.0)
    net_income = float(_safe_float(row.get("net_income")) or 0.0)
    total_assets = float(_safe_float(row.get("total_assets")) or 0.0)
    total_le = float(_safe_float(row.get("total_liabilities_and_equity")) or 0.0)
    if int(round(revenue - cogs)) != int(round(gross_profit)):
      math_violations.append({"quarter_index": quarter, "field": "gross_profit", "reason": "revenue_minus_cogs_mismatch"})
    if int(round(ebitda - interest - depreciation - taxes)) != int(round(net_income)):
      math_violations.append({"quarter_index": quarter, "field": "net_income", "reason": "ebitda_less_below_line_mismatch"})
    if int(round(total_assets)) != int(round(total_le)):
      math_violations.append(
        {
          "quarter_index": quarter,
          "field": "balance_sheet",
          "total_assets": int(round(total_assets)),
          "total_liabilities_and_equity": int(round(total_le)),
          "reason": "balance_sheet_not_balanced",
        }
      )
  _raise_if_violations(
    "post_intake_statement_math_invalid",
    "FINMO statement math must reconcile before post-intake can continue.",
    stage=stage,
    violations=math_violations,
  )


def assert_post_intake_schedule_markers_integrity(
  *,
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]] = None,
  debt_schedule: Optional[Dict[str, Any]] = None,
  stage: str,
  contract_name: str = "unified_convergence_decision",
) -> None:
  horizon = _expected_horizon(contract_name)
  violations: List[Dict[str, Any]] = []
  payroll_row = _find_model_input_row(model_input_json, section_name="expenses", label="Payroll", lever_id="expenses::Payroll")
  capex_row = _find_model_input_row(model_input_json, section_name="schedules", label="Capital Expenditures")
  depreciation_row = _find_model_input_row(model_input_json, section_name="expenses", label="Depreciation")
  if not isinstance(payroll_row, dict):
    violations.append({"row": "expenses::Payroll", "reason": "missing"})
  else:
    if bool(payroll_row.get("controller_write", True)):
      violations.append({"row": "expenses::Payroll", "reason": "payroll_must_not_be_controller_writable"})
    if str(payroll_row.get("derived_driver") or "").strip() != "headcount_schedule_derived":
      violations.append(
        {
          "row": "expenses::Payroll",
          "reason": "missing_payroll_headcount_schedule_marker",
          "actual_derived_driver": str(payroll_row.get("derived_driver") or ""),
        }
      )
  if not isinstance(capex_row, dict):
    violations.append({"row": "schedules::Capital Expenditures", "reason": "missing"})
  elif str(capex_row.get("derived_driver") or "").strip() != "structural_capacity_ppe_derived":
    violations.append(
      {
        "row": "schedules::Capital Expenditures",
        "reason": "missing_capacity_driven_capex_marker",
        "actual_derived_driver": str(capex_row.get("derived_driver") or ""),
      }
    )
  if not isinstance(depreciation_row, dict):
    violations.append({"row": "expenses::Depreciation", "reason": "missing"})
  elif str(depreciation_row.get("derived_driver") or "").strip() != "structural_capacity_ppe_derived":
    violations.append(
      {
        "row": "expenses::Depreciation",
        "reason": "missing_capex_depreciation_schedule_marker",
        "actual_derived_driver": str(depreciation_row.get("derived_driver") or ""),
      }
    )
  runtime = (
    (model_input_json or {}).get("derived_driver_runtime")
    if isinstance(model_input_json, dict) and isinstance(model_input_json.get("derived_driver_runtime"), dict)
    else {}
  )
  policies = (
    (model_input_json or {}).get("derived_driver_policies")
    if isinstance(model_input_json, dict) and isinstance(model_input_json.get("derived_driver_policies"), dict)
    else {}
  )
  if not isinstance(runtime.get("expenses::Payroll"), dict):
    violations.append({"runtime": "derived_driver_runtime.expenses::Payroll", "reason": "missing"})
  if not isinstance(runtime.get("capex_depreciation_policy"), dict):
    violations.append({"runtime": "derived_driver_runtime.capex_depreciation_policy", "reason": "missing"})
  debt_runtime = runtime.get("debt_schedule") if isinstance(runtime.get("debt_schedule"), dict) else {}
  if isinstance(debt_schedule, dict) and debt_schedule:
    debt_runtime = debt_schedule
  if isinstance(debt_schedule, dict) and debt_schedule:
    if str(debt_schedule.get("source_of_truth") or "").strip() != "sql.post_intake_cash_policy_lookup":
      violations.append({"object": "debt_schedule", "reason": "not_sql_cash_policy_backed"})
    if str(debt_schedule.get("lookup_function") or "").strip() != "post_intake_cash_debt_schedule_policy":
      violations.append({"object": "debt_schedule", "reason": "missing_cash_policy_lookup_function"})
    debt_rows = [row for row in (debt_schedule.get("rows") or []) if isinstance(row, dict)]
    debt_quarters = sorted(int(_safe_float(row.get("quarter_index")) or 0) for row in debt_rows)
    if debt_quarters != list(range(1, horizon + 1)):
      violations.append(
        {
          "object": "debt_schedule.rows",
          "reason": "does_not_cover_full_horizon",
          "expected_quarters": list(range(1, horizon + 1)),
          "actual_quarters": debt_quarters,
        }
      )
  elif stage.lower().endswith("final") or "finalize" in stage.lower() or "post_cash" in stage.lower():
    violations.append({"object": "debt_schedule", "reason": "missing"})
  r_and_d_policy = policies.get("expenses::Research & Development") if isinstance(policies, dict) else {}
  r_and_d_row = _find_model_input_row(model_input_json, section_name="expenses", label="Research & Development")
  if not isinstance(r_and_d_policy, dict) or "r_and_d_enabled" not in r_and_d_policy:
    violations.append({"policy": "derived_driver_policies.expenses::Research & Development", "reason": "missing_r_and_d_toggle"})
  elif bool(r_and_d_policy.get("r_and_d_enabled")) is False:
    if not isinstance(r_and_d_row, dict):
      violations.append({"row": "expenses::Research & Development", "reason": "r_and_d_disabled_row_missing"})
    else:
      if bool(r_and_d_row.get("controller_write", True)):
        violations.append({"row": "expenses::Research & Development", "reason": "r_and_d_disabled_still_controller_writable"})
      leaked = [
        {"quarter_index": idx, "value": float(_safe_float(value) or 0.0)}
        for idx, value in enumerate(_row_live_values(r_and_d_row, horizon=horizon), start=1)
        if abs(float(_safe_float(value) or 0.0)) > 1e-9
      ]
      if leaked:
        violations.append({"row": "expenses::Research & Development", "reason": "r_and_d_disabled_live_value_leakage", "leaking_values": leaked[:20]})
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) and payroll_headcount else (
    runtime.get("expenses::Payroll", {}).get("payroll_headcount")
    if isinstance(runtime.get("expenses::Payroll"), dict)
    else {}
  )
  if not isinstance(schedule, dict) or not schedule:
    violations.append({"object": "payroll_headcount_schedule", "reason": "missing"})
  else:
    quarter_totals = schedule.get("quarter_totals") if isinstance(schedule.get("quarter_totals"), list) else []
    quarters = sorted(
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in quarter_totals
      if isinstance(item, dict)
    )
    if quarters != list(range(1, horizon + 1)):
      violations.append(
        {
          "object": "payroll_headcount_schedule.quarter_totals",
          "reason": "does_not_cover_full_horizon",
          "expected_quarters": list(range(1, horizon + 1)),
          "actual_quarters": quarters,
        }
      )
  _raise_if_violations(
    "post_intake_schedule_marker_missing",
    "Payroll, debt, capex, and depreciation schedules must be used and marked before post-intake can pass.",
    stage=stage,
    violations=violations,
  )


def assert_post_intake_rebuilt_finmo_matches_model_input(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
  contract_name: str = "unified_convergence_decision",
) -> None:
  """Fail if the persisted FINMO is stale relative to model_input_json."""
  horizon = _expected_horizon(contract_name)
  try:
    from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore

    rebuilt = build_python_finmo_json(model_input_json=json.loads(json.dumps(model_input_json or {})))
  except Exception as exc:
    post_intake_fail_fast_raise(
      "post_intake_finmo_missing",
      f"Unable to rebuild FINMO from model_input_json for fail-fast verification: {exc}",
      stage=stage,
      details={"exception": str(exc)},
    )
    return
  actual_by_q = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in _live_quarter_rows(finmo_json)
  }
  expected_by_q = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in _live_quarter_rows(rebuilt)
  }
  fields = [
    "revenue",
    "cost_of_goods_sold",
    "marketing",
    "research_and_development",
    "lease_rent",
    "payroll",
    "general_and_administrative",
    "interest",
    "depreciation",
    "net_income",
    "cash",
    "ppe",
    "long_term_debt",
    "short_term_debt",
    "ending_cash",
  ]
  violations: List[Dict[str, Any]] = []
  for quarter in range(1, horizon + 1):
    actual_row = actual_by_q.get(quarter) or {}
    expected_row = expected_by_q.get(quarter) or {}
    for field in fields:
      actual = int(round(float(_safe_float(actual_row.get(field)) or 0.0)))
      expected = int(round(float(_safe_float(expected_row.get(field)) or 0.0)))
      if actual != expected:
        violations.append(
          {
            "quarter_index": quarter,
            "field": field,
            "actual_finmo": actual,
            "rebuilt_from_model_input": expected,
            "reason": "finmo_stale_or_not_model_input_derived",
          }
        )
        break
  _raise_if_violations(
    "post_intake_finmo_core_row_invalid",
    "Persisted FINMO must equal a fresh rebuild from model_input_json.",
    stage=stage,
    violations=violations,
    extra_details={"horizon": horizon},
  )


def assert_post_intake_cash_buffer_integrity(
  *,
  financials_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  """Final hard gate: ending cash must stay at or above SQL cash-policy buffer."""
  try:
    from client_intake_and_finmo.post_intake_cash.runner import _cash_strategy_validation_violation_envelope, _resolved_cash_strategy  # type: ignore

    envelope = _cash_strategy_validation_violation_envelope(
      selected_cash_strategy=_resolved_cash_strategy(financials_json),
      finmo_payload=json.loads(json.dumps(finmo_json or {})),
      model_input_json=json.loads(json.dumps(model_input_json or {})),
    )
  except Exception as exc:
    post_intake_fail_fast_raise(
      "post_intake_cash_buffer_violation",
      f"Unable to build SQL cash-policy validation envelope: {exc}",
      stage=stage,
      details={"exception": str(exc)},
    )
    return
  violations = [
    {
      "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
      "ending_cash": int(round(float(_safe_float(item.get("ending_cash")) or 0.0))),
      "required_cash_buffer": int(round(float(_safe_float(item.get("buffer")) or 0.0))),
      "cash_strategy": envelope.get("selected_cash_strategy"),
    }
    for item in (envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
    and int(round(float(_safe_float(item.get("ending_cash")) or 0.0)))
    < int(round(float(_safe_float(item.get("buffer")) or 0.0)))
  ]
  _raise_if_violations(
    "post_intake_cash_buffer_violation",
    "Final cash pass failed: every live quarter must satisfy ending_cash >= required SQL cash-policy buffer.",
    stage=stage,
    violations=violations,
    extra_details={"cash_validation_envelope": envelope},
  )


def assert_post_intake_global_invariants(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
  payroll_headcount: Optional[Dict[str, Any]] = None,
  debt_schedule: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  enforce_cash_buffer: bool = False,
  contract_name: str = "unified_convergence_decision",
) -> None:
  """One gate for post-intake: table-backed state, schedules, FINMO, and shape must all be valid."""
  assert_post_intake_horizon_integrity(
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    stage=stage,
    contract_name=contract_name,
  )
  assert_post_intake_mapping_formula_contract_integrity(
    stage=f"{stage}_mapping_formula_contract",
  )
  assert_post_intake_model_input_rows_integrity(
    model_input_json=model_input_json,
    stage=stage,
    contract_name=contract_name,
  )
  assert_post_intake_revenue_driver_integrity(
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    stage=stage,
    contract_name=contract_name,
  )
  assert_post_intake_schedule_markers_integrity(
    model_input_json=model_input_json,
    payroll_headcount=payroll_headcount,
    debt_schedule=debt_schedule,
    stage=stage,
    contract_name=contract_name,
  )
  if isinstance(debt_schedule, dict) and debt_schedule:
    try:
      from client_intake_and_finmo.post_intake_debt_schedule import (  # type: ignore
        assert_debt_schedule_payload_ready,
        assert_finmo_matches_debt_schedule,
      )

      assert_debt_schedule_payload_ready(
        debt_schedule,
        stage=f"{stage}_global_debt_payload",
      )
      assert_finmo_matches_debt_schedule(
        debt_schedule=debt_schedule,
        finmo_json=finmo_json,
        stage=f"{stage}_global_debt_finmo",
      )
    except Exception as exc:
      post_intake_fail_fast_raise(
        "post_intake_schedule_marker_missing",
        f"Debt schedule fail-fast failed; all debt must use the table-backed amortizing debt schedule: {exc}",
        stage=stage,
        details={"exception": str(exc)},
      )
  try:
    from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
      assert_finmo_payroll_matches_headcount_schedule,
      assert_payroll_headcount_model_input_applied,
      assert_payroll_headcount_payload_ready,
    )

    assert_payroll_headcount_payload_ready(
      payroll_headcount,
      model_input_json=model_input_json,
      stage=f"{stage}_global_payroll_payload",
    )
    assert_payroll_headcount_model_input_applied(
      model_input_json,
      payroll_headcount,
      stage=f"{stage}_global_payroll_model_input",
    )
    assert_finmo_payroll_matches_headcount_schedule(
      finmo_json,
      payroll_headcount,
      stage=f"{stage}_global_payroll_finmo",
    )
  except Exception as exc:
    post_intake_fail_fast_raise(
      "post_intake_schedule_marker_missing",
      f"Payroll schedule fail-fast failed; payroll must use the table-backed headcount schedule: {exc}",
      stage=stage,
      details={"exception": str(exc)},
    )
  assert_post_intake_finmo_statement_integrity(
    finmo_json=finmo_json,
    stage=stage,
    contract_name=contract_name,
  )
  assert_post_intake_mapping_formula_application_integrity(
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    stage=f"{stage}_mapping_formula_application",
    contract_name=contract_name,
  )
  assert_post_intake_rebuilt_finmo_matches_model_input(
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    stage=stage,
    contract_name=contract_name,
  )
  assert_post_intake_business_shape_applied(
    stage_ramp_contract=stage_ramp_contract,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    stage=stage,
  )
  if enforce_cash_buffer:
    assert_post_intake_cash_buffer_integrity(
      financials_json=financials_json,
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      stage=stage,
    )
