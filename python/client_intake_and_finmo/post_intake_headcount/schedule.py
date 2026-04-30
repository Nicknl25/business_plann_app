from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .lookup import (
  PAYROLL_HEADCOUNT_DRAFT_COLUMN,
  post_intake_headcount_policy_for,
  validate_payroll_headcount_payload,
)


PAYROLL_HEADCOUNT_SOURCE = "headcount_schedule_derived"
PAYROLL_HEADCOUNT_POLICY_VERSION = "payroll_headcount_schedule_policy_v1"
PAYROLL_HEADCOUNT_LEVER_ID = "expenses::Payroll"


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


def _safe_ratio(value: Any) -> Optional[float]:
  parsed = _safe_float(value)
  if parsed is None:
    return None
  if abs(parsed) > 1.0 and abs(parsed) <= 100.0:
    return parsed / 100.0
  return parsed


def _round_currency(value: Any) -> int:
  return int(round(float(_safe_float(value) or 0.0)))


def _row_stub_and_live_values(values: Sequence[Any], *, live_count: int) -> Tuple[float, List[float]]:
  normalized = [round(_safe_float(item) or 0.0, 6) for item in (values or [])]
  if len(normalized) >= live_count + 1:
    stub_value = float(normalized[0])
    live_values = list(normalized[1:live_count + 1])
  else:
    stub_value = 0.0
    live_values = list(normalized[:live_count])
  if len(live_values) < live_count:
    live_values.extend([0.0 for _ in range(live_count - len(live_values))])
  return stub_value, live_values[:live_count]


def _compose_period_values(*, stub_value: float, live_values: Sequence[Any]) -> List[float]:
  return [
    round(_safe_float(stub_value) or 0.0, 6),
    *[round(_safe_float(item) or 0.0, 6) for item in (live_values or [])],
  ]


def payroll_row_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  for row in (sections.get("expenses") or []):
    if isinstance(row, dict) and str(row.get("label") or "").strip() == "Payroll":
      return row
  return None


def _stage_ramp_headcount_grid_rows(stage_ramp_contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = stage_ramp_contract if isinstance(stage_ramp_contract, dict) else {}
  raw_rows = payload.get("payroll_headcount_grid")
  if not isinstance(raw_rows, list):
    raw_rows = []
  rows_by_quarter: Dict[int, Dict[str, Any]] = {}
  for item in raw_rows:
    if not isinstance(item, dict):
      continue
    quarter_index = int(round(float(_safe_float(item.get("q") or item.get("quarter_index")) or 0.0)))
    if quarter_index < 1 or quarter_index > 20 or quarter_index in rows_by_quarter:
      continue
    starting_fte = round(max(0.0, float(_safe_float(item.get("starting_fte")) or 0.0)), 2)
    hires = round(max(0.0, float(_safe_float(item.get("hires")) or 0.0)), 2)
    ending_fte = round(max(0.0, float(_safe_float(item.get("ending_fte")) or 0.0)), 2)
    annual_wage = _round_currency(item.get("avg_annual_wage") or item.get("annual_wage"))
    payroll_tax_benefits_pct = round(max(0.0, float(_safe_ratio(item.get("payroll_tax_benefits_pct")) or 0.0)), 2)
    role_category = str(item.get("role_category") or "aggregate_staff").strip() or "aggregate_staff"
    wage_source = str(item.get("wage_source") or "gpt_business_role_wage").strip() or "gpt_business_role_wage"
    rows_by_quarter[quarter_index] = {
      "quarter_index": quarter_index,
      "role_category": role_category,
      "starting_fte": starting_fte,
      "hires": hires,
      "ending_fte": ending_fte,
      "annual_wage": annual_wage,
      "wage_source": wage_source,
      "payroll_taxes_benefits_percent": payroll_tax_benefits_pct,
    }
  return [rows_by_quarter[quarter] for quarter in sorted(rows_by_quarter)]


def build_payroll_headcount_payload_from_stage_ramp_contract(
  stage_ramp_contract: Optional[Dict[str, Any]],
  *,
  draft_id: Any = "",
  client_id: Any = "",
  policy_code: Any = "default",
) -> Dict[str, Any]:
  policy = post_intake_headcount_policy_for(policy_code=policy_code)
  horizon = int((policy or {}).get("schedule_horizon_quarters") or 20)
  if horizon != 20:
    raise RuntimeError("payroll_headcount_policy_invalid: schedule_horizon_quarters must be 20")
  rows = _stage_ramp_headcount_grid_rows(stage_ramp_contract)
  if len(rows) != horizon or {int(row.get("quarter_index") or 0) for row in rows} != set(range(1, horizon + 1)):
    raise RuntimeError(
      "payroll_headcount_schedule_missing_full_horizon: stage_ramp_contract.payroll_headcount_grid must include Q1-Q20."
    )
  normalized_rows: List[Dict[str, Any]] = []
  quarter_totals: List[Dict[str, Any]] = []
  previous_ending_fte: Optional[float] = None
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    hires = round(float(row.get("hires") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    if previous_ending_fte is not None and abs(starting_fte - previous_ending_fte) > 0.01:
      raise RuntimeError(
        f"payroll_headcount_schedule_continuity_failed: Q{quarter_index} starting_fte must equal prior quarter ending_fte."
      )
    if abs((starting_fte + hires) - ending_fte) > 0.01:
      raise RuntimeError(
        f"payroll_headcount_schedule_math_failed: Q{quarter_index} starting_fte + hires must equal ending_fte."
      )
    annual_wage = _round_currency(row.get("annual_wage"))
    if annual_wage <= 0:
      raise RuntimeError(f"payroll_headcount_schedule_wage_invalid: Q{quarter_index} annual_wage must be > 0.")
    benefits_pct = round(float(_safe_ratio(row.get("payroll_taxes_benefits_percent")) or 0.0), 2)
    if benefits_pct < 0.0 or benefits_pct > 1.0:
      raise RuntimeError(
        f"payroll_headcount_schedule_benefits_invalid: Q{quarter_index} payroll_taxes_benefits_percent must be 0.00-1.00."
      )
    average_fte = round((starting_fte + ending_fte) / 2.0, 2)
    quarterly_wage_cost = _round_currency((average_fte * annual_wage) / 4.0)
    quarterly_taxes_benefits = _round_currency(quarterly_wage_cost * benefits_pct)
    total_quarterly_payroll = int(quarterly_wage_cost + quarterly_taxes_benefits)
    schedule_row = {
      **deepcopy(row),
      "average_fte": average_fte,
      "annual_wage": annual_wage,
      "payroll_taxes_benefits_percent": benefits_pct,
      "quarterly_wage_cost": quarterly_wage_cost,
      "quarterly_taxes_benefits": quarterly_taxes_benefits,
      "total_quarterly_payroll": total_quarterly_payroll,
    }
    normalized_rows.append(schedule_row)
    quarter_totals.append(
      {
        "quarter_index": quarter_index,
        "ending_fte": ending_fte,
        "payroll": total_quarterly_payroll,
      }
    )
    previous_ending_fte = ending_fte
  payload = {
    "contract_version": str((policy or {}).get("schedule_contract_version") or "payroll_headcount_schedule_v1"),
    "draft_id": str(draft_id or "").strip(),
    "client_id": str(client_id or "").strip(),
    "policy_code": str(policy_code or "default").strip().lower() or "default",
    "source_table": "intake_consult_drafts",
    "source_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    "schedule_horizon_quarters": horizon,
    "rows": normalized_rows,
    "quarter_totals": quarter_totals,
  }
  validation_errors = validate_payroll_headcount_payload(payload, policy_code=policy_code)
  if validation_errors:
    raise RuntimeError("payroll_headcount_schedule_validation_failed: " + "; ".join(validation_errors[:20]))
  return payload


def apply_payroll_headcount_payload_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> Dict[str, Any]:
  next_payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule:
    return next_payload
  validation_errors = validate_payroll_headcount_payload(schedule)
  if validation_errors:
    raise RuntimeError("payroll_headcount_schedule_validation_failed: " + "; ".join(validation_errors[:20]))
  if isinstance(next_payload.get("controller_write_levers"), list):
    next_payload["controller_write_levers"] = [
      deepcopy(item)
      for item in (next_payload.get("controller_write_levers") or [])
      if isinstance(item, dict) and str(item.get("lever_id") or "").strip() != PAYROLL_HEADCOUNT_LEVER_ID
    ]
  if isinstance(next_payload.get("lever_catalog"), dict):
    lever_catalog = deepcopy(next_payload.get("lever_catalog") or {})
    lever_catalog.pop(PAYROLL_HEADCOUNT_LEVER_ID, None)
    next_payload["lever_catalog"] = lever_catalog
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  payroll_row = next((row for row in expense_rows if str(row.get("label") or "").strip() == "Payroll"), None)
  if not isinstance(payroll_row, dict):
    raise RuntimeError("payroll_row_missing: model_input.sections.expenses must include Payroll for headcount schedule application.")
  values = list(payroll_row.get("values") or [])
  stub_value, _existing_live_values = _row_stub_and_live_values(values, live_count=live_count)
  totals_by_quarter = {
    int(item.get("quarter_index") or 0): int(round(float(_safe_float(item.get("payroll")) or 0.0)))
    for item in (schedule.get("quarter_totals") or [])
    if isinstance(item, dict)
  }
  expected_quarters = set(range(1, live_count + 1))
  if set(totals_by_quarter.keys()) & expected_quarters != expected_quarters:
    raise RuntimeError("payroll_headcount_schedule_missing_live_quarters")
  derived_live_values = [float(totals_by_quarter[quarter]) for quarter in range(1, live_count + 1)]
  payroll_row["controller_write"] = False
  payroll_row["derived_driver"] = PAYROLL_HEADCOUNT_SOURCE
  payroll_row["payroll_headcount_schedule"] = {
    "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
    "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
    "driver_basis": "headcount_schedule",
    "schedule_storage_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    "schedule_contract_version": schedule.get("contract_version"),
    "schedule_horizon_quarters": schedule.get("schedule_horizon_quarters"),
    "quarter_totals": deepcopy(schedule.get("quarter_totals") or []),
  }
  payroll_row["values"] = _compose_period_values(stub_value=stub_value, live_values=derived_live_values)
  next_payload.setdefault("derived_driver_policies", {})
  next_payload.setdefault("derived_driver_runtime", {})
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"][PAYROLL_HEADCOUNT_LEVER_ID] = {
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "driver_basis": "headcount_schedule",
      "schedule_storage_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
      "schedule_contract_version": schedule.get("contract_version"),
      "schedule_horizon_quarters": schedule.get("schedule_horizon_quarters"),
    }
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][PAYROLL_HEADCOUNT_LEVER_ID] = {
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "driver_basis": "headcount_schedule",
      "payroll_headcount": deepcopy(schedule),
      "quarter_totals": deepcopy(schedule.get("quarter_totals") or []),
    }
  return next_payload


def validate_payroll_headcount_model_input_contract(
  *,
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  current_row = payroll_row_from_model_input(payload)
  details: List[Dict[str, Any]] = []
  if not isinstance(current_row, dict):
    return {
      "status": "failed",
      "details": [{
        "error": "payroll_row_missing",
        "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
        "quarter": 0,
        "reason": "Model input is missing the Payroll row in sections.expenses.",
        "validation_category": "payroll_headcount_schedule",
      }],
      "current_runtime": {},
      "expected_runtime": {},
    }
  live_count = max(
    0,
    len([item for item in (payload.get("periods") or []) if isinstance(item, dict) and not bool(item.get("is_stub"))])
    or (len(list(current_row.get("values") or [])) - 1 if len(list(current_row.get("values") or [])) >= 1 else 0),
  )
  current_runtime = ((payload.get("derived_driver_runtime") or {}).get(PAYROLL_HEADCOUNT_LEVER_ID)) if isinstance(payload.get("derived_driver_runtime"), dict) else {}
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule and isinstance(current_runtime, dict):
    schedule = current_runtime.get("payroll_headcount") if isinstance(current_runtime.get("payroll_headcount"), dict) else {}
  if not schedule:
    details.append({
      "error": "payroll_headcount_schedule_missing",
      "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
      "quarter": 0,
      "reason": "Payroll must be backed by intake_consult_drafts.payroll_headcount / derived_driver_runtime payroll_headcount.",
      "validation_category": "payroll_headcount_schedule",
    })
  else:
    for error in validate_payroll_headcount_payload(schedule):
      details.append({
        "error": error,
        "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
        "quarter": 0,
        "reason": "Payroll headcount schedule failed schedule validation.",
        "validation_category": "payroll_headcount_schedule",
      })
  if bool(current_row.get("controller_write", True)):
    details.append({
      "error": "payroll_row_should_not_be_writable",
      "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
      "quarter": 0,
      "reason": "Payroll must not be controller-writable once payroll is headcount-schedule-derived.",
      "validation_category": "payroll_headcount_schedule",
    })
  if str(current_row.get("derived_driver") or "").strip() != PAYROLL_HEADCOUNT_SOURCE:
    details.append({
      "error": "payroll_row_missing_headcount_derived_driver_marker",
      "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
      "quarter": 0,
      "reason": f"Payroll row must be marked with derived_driver='{PAYROLL_HEADCOUNT_SOURCE}'.",
      "validation_category": "payroll_headcount_schedule",
    })
  if schedule:
    expected_payload = apply_payroll_headcount_payload_to_model_input(deepcopy(payload), schedule, live_count=live_count)
    expected_row = payroll_row_from_model_input(expected_payload)
    current_values = list(current_row.get("values") or [])
    expected_values = list((expected_row or {}).get("values") or [])
    if len(current_values) >= live_count + 1 and len(expected_values) >= live_count + 1:
      for quarter_index in range(1, live_count + 1):
        current_value = _safe_float(current_values[quarter_index])
        expected_value = _safe_float(expected_values[quarter_index])
        if current_value is None or expected_value is None or int(round(float(current_value))) != int(round(float(expected_value))):
          details.append({
            "error": "payroll_values_not_headcount_schedule_derived",
            "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
            "quarter": quarter_index,
            "previous_value": expected_value,
            "current_value": current_value,
            "reason": "Payroll forecast values must equal the persisted payroll_headcount quarter totals.",
            "validation_category": "payroll_headcount_schedule",
          })
          break
  return {
    "status": "failed" if details else "passed",
    "details": deepcopy(details),
    "current_runtime": deepcopy(current_runtime) if isinstance(current_runtime, dict) else {},
    "expected_runtime": deepcopy((schedule or {})),
  }
