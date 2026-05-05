"""Finalize gate for production post-intake runtime validation."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
  assert_post_intake_cash_buffer_integrity,
  assert_post_intake_global_invariants,
  assert_post_intake_mapping_formula_application_integrity,
  assert_post_intake_mapping_formula_contract_integrity,
)
from client_intake_and_finmo.post_intake_foundation import (  # type: ignore
  post_intake_assert_runtime_table_integrity,
)
from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_assert_required_process_sequence,
  post_intake_process_step_context,
)
from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # type: ignore
  balance_sheet_driver_finalize_errors,
)


_FINALIZE_HORIZON = 20


def _raise_if_errors(errors: List[str]) -> None:
  if errors:
    raise RuntimeError(
      "post_intake_finalize_validation_failed: "
      + "; ".join(str(item) for item in errors[:80])
    )


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


def _live_model_input_values(row: Dict[str, Any], *, horizon: int = _FINALIZE_HORIZON) -> List[Any]:
  values = list(row.get("values") or [])
  if len(values) >= horizon + 1:
    return values[1:horizon + 1]
  return values[:horizon]


def _iter_model_input_rows(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_name in ("revenue", "expenses", "balance_sheet"):
    section_rows = sections.get(section_name)
    if isinstance(section_rows, list):
      rows.extend(row for row in section_rows if isinstance(row, dict))
  schedule_rows = sections.get("schedules")
  if isinstance(schedule_rows, dict):
    raw_rows = schedule_rows.get("rows")
    if isinstance(raw_rows, list):
      rows.extend(row for row in raw_rows if isinstance(row, dict))
  elif isinstance(schedule_rows, list):
    rows.extend(row for row in schedule_rows if isinstance(row, dict))
  return rows


def _find_model_input_row(model_input_json: Optional[Dict[str, Any]], label: str) -> Optional[Dict[str, Any]]:
  target = str(label or "").strip().lower()
  for row in _iter_model_input_rows(model_input_json):
    if str(row.get("label") or "").strip().lower() == target:
      return row
  return None


def _revenue_driver_role(row: Dict[str, Any]) -> str:
  semantics = str(row.get("input_semantics") or "").strip().lower()
  if semantics == "capacity_units":
    return "capacity"
  if semantics == "unit_price":
    return "unit_price"
  if semantics == "ratio":
    return "utilization"
  suffix = str(row.get("lever_id") or row.get("label") or "").strip().split("::")[-1].strip().lower()
  if suffix == "capacity":
    return "capacity"
  if suffix == "unit price":
    return "unit_price"
  if suffix == "utilization":
    return "utilization"
  return ""


def _revenue_driver_group_key(row: Dict[str, Any]) -> str:
  lever_id = str(row.get("lever_id") or "").strip()
  if "::" in lever_id:
    return "::".join(lever_id.split("::")[:-1])
  return str(row.get("label") or "").strip()


def _live_finmo_rows(finmo_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  rows = (finmo_json or {}).get("quarter_rows") if isinstance(finmo_json, dict) else []
  live_rows = [
    row for row in (rows or [])
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  ]
  live_rows.sort(key=lambda row: int(_safe_float(row.get("quarter_index")) or 0))
  return live_rows


def _assert_forecast_horizon_complete(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  errors: List[str],
) -> None:
  ramp_rows = (stage_ramp_contract or {}).get("quarter_ramp_grid") if isinstance(stage_ramp_contract, dict) else []
  ramp_quarters = sorted(
    int(_safe_float(row.get("quarter_index") or row.get("q")) or 0)
    for row in (ramp_rows or [])
    if isinstance(row, dict)
  )
  if ramp_quarters != list(range(1, _FINALIZE_HORIZON + 1)):
    errors.append(
      "stage_ramp_contract_horizon_invalid: "
      f"expected_q1_to_q20 actual={ramp_quarters[:25]}"
    )

  periods = (model_input_json or {}).get("periods") if isinstance(model_input_json, dict) else []
  live_periods = [
    period for period in (periods or [])
    if isinstance(period, dict) and not bool(period.get("is_stub"))
  ]
  stub_periods = [
    period for period in (periods or [])
    if isinstance(period, dict) and bool(period.get("is_stub"))
  ]
  if len(stub_periods) != 1:
    errors.append(f"model_input_stub_period_invalid: expected=1 actual={len(stub_periods)}")
  if len(live_periods) != _FINALIZE_HORIZON:
    errors.append(f"model_input_live_period_count_invalid: expected=20 actual={len(live_periods)}")

  finmo_live_rows = _live_finmo_rows(finmo_json)
  finmo_quarters = [int(_safe_float(row.get("quarter_index")) or 0) for row in finmo_live_rows]
  if finmo_quarters != list(range(1, _FINALIZE_HORIZON + 1)):
    errors.append(f"finmo_live_quarter_rows_invalid: expected_q1_to_q20 actual={finmo_quarters[:25]}")
  if any(int(_safe_float(row.get("quarter_index")) or 0) > _FINALIZE_HORIZON for row in finmo_live_rows):
    errors.append("finmo_q21_or_later_detected")


def _assert_model_input_values_complete(
  *,
  model_input_json: Optional[Dict[str, Any]],
  errors: List[str],
) -> None:
  blank_rows: List[Dict[str, Any]] = []
  invalid_horizon_rows: List[Dict[str, Any]] = []
  for row in _iter_model_input_rows(model_input_json):
    label = str(row.get("label") or row.get("lever_id") or "").strip()
    values = _live_model_input_values(row)
    if len(values) != _FINALIZE_HORIZON:
      invalid_horizon_rows.append(
        {"row": label, "expected_live_values": _FINALIZE_HORIZON, "actual_live_values": len(values)}
      )
      continue
    for quarter_index, value in enumerate(values, start=1):
      if value is None or str(value).strip() == "" or _safe_float(value) is None:
        blank_rows.append({"row": label, "quarter_index": quarter_index, "value": value})
        break
  if invalid_horizon_rows:
    errors.append(f"model_input_row_horizon_invalid: {invalid_horizon_rows[:20]}")
  if blank_rows:
    errors.append(f"model_input_row_values_blank_or_nonnumeric: {blank_rows[:20]}")


def _assert_finmo_values_complete(
  *,
  finmo_json: Optional[Dict[str, Any]],
  errors: List[str],
) -> None:
  required_fields = [
    "revenue",
    "cost_of_goods_sold",
    "gross_profit",
    "marketing",
    "research_and_development",
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
    "beginning_cash",
    "operating_cash_flow",
    "capital_expenditures",
    "debt_issuance",
    "debt_repayment",
    "equity",
    "owner_distributions",
    "ending_cash",
  ]
  missing_values: List[Dict[str, Any]] = []
  for row in _live_finmo_rows(finmo_json):
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    for field in required_fields:
      value = row.get(field)
      if value is None or str(value).strip() == "" or _safe_float(value) is None:
        missing_values.append({"quarter_index": quarter_index, "field": field, "value": value})
        break
  if missing_values:
    errors.append(f"finmo_live_values_blank_or_nonnumeric: {missing_values[:30]}")


def _assert_revenue_formula_reconciles(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  errors: List[str],
) -> None:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = sections.get("revenue") if isinstance(sections.get("revenue"), list) else []
  grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
  for row in revenue_rows:
    if not isinstance(row, dict):
      continue
    role = _revenue_driver_role(row)
    if role not in {"capacity", "unit_price", "utilization"}:
      continue
    group_key = _revenue_driver_group_key(row)
    if not group_key:
      continue
    grouped.setdefault(group_key, {})[role] = row
  complete_groups = {
    group_key: rows
    for group_key, rows in grouped.items()
    if {"capacity", "unit_price", "utilization"}.issubset(rows.keys())
  }
  if not complete_groups:
    errors.append(
      "revenue_formula_driver_rows_missing: "
      "expected at least one complete revenue driver bundle with capacity_units, unit_price, and ratio semantics"
    )
    return
  violations = []
  for row in _live_finmo_rows(finmo_json):
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    idx = quarter_index - 1
    expected = 0
    missing_group_value = ""
    for group_key, rows in sorted(complete_groups.items()):
      capacities = _live_model_input_values(rows["capacity"])
      prices = _live_model_input_values(rows["unit_price"])
      utilizations = _live_model_input_values(rows["utilization"])
      if idx < 0 or idx >= min(len(capacities), len(prices), len(utilizations)):
        missing_group_value = group_key
        break
      capacity = float(_safe_float(capacities[idx]) or 0.0)
      price = float(_safe_float(prices[idx]) or 0.0)
      utilization = float(_safe_float(utilizations[idx]) or 0.0)
      expected += int(round(capacity * price * utilization))
    if missing_group_value:
      violations.append(
        {
          "quarter_index": quarter_index,
          "reason": "driver_value_missing",
          "revenue_driver_bundle": missing_group_value,
        }
      )
      continue
    actual = int(round(float(_safe_float(row.get("revenue")) or 0.0)))
    if abs(int(expected) - int(actual)) > 1:
      violations.append(
        {
          "quarter_index": quarter_index,
          "actual_revenue": actual,
          "expected_capacity_x_price_x_utilization": expected,
          "allowed_rounding_tolerance_dollars": 1,
        }
      )
      break
  if violations:
    errors.append(f"revenue_formula_reconciliation_failed: {violations[:10]}")


def _assert_payroll_schedule_reconciles(
  *,
  payroll_headcount: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  errors: List[str],
) -> None:
  try:
    from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
      assert_finmo_payroll_matches_headcount_schedule,
      assert_payroll_headcount_model_input_applied,
      assert_payroll_headcount_payload_ready,
    )

    assert_payroll_headcount_payload_ready(
      copy.deepcopy(payroll_headcount or {}),
      model_input_json=copy.deepcopy(model_input_json or {}),
      stage="post_intake_finalize_validation_payroll_payload",
    )
    assert_payroll_headcount_model_input_applied(
      copy.deepcopy(model_input_json or {}),
      copy.deepcopy(payroll_headcount or {}),
      stage="post_intake_finalize_validation_payroll_model_input",
    )
    assert_finmo_payroll_matches_headcount_schedule(
      copy.deepcopy(finmo_json or {}),
      copy.deepcopy(payroll_headcount or {}),
      stage="post_intake_finalize_validation_payroll_finmo",
    )
  except Exception as exc:
    errors.append(f"payroll_schedule_reconciliation_failed: {exc}")


def _assert_debt_schedule_reconciles(
  *,
  debt_schedule: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  errors: List[str],
) -> None:
  try:
    from client_intake_and_finmo.post_intake_debt_schedule import (  # type: ignore
      assert_debt_schedule_payload_ready,
      assert_finmo_matches_debt_schedule,
    )

    assert_debt_schedule_payload_ready(
      copy.deepcopy(debt_schedule or {}),
      stage="post_intake_finalize_validation_debt_payload",
    )
    assert_finmo_matches_debt_schedule(
      debt_schedule=copy.deepcopy(debt_schedule or {}),
      finmo_json=copy.deepcopy(finmo_json or {}),
      stage="post_intake_finalize_validation_debt_finmo",
    )
  except Exception as exc:
    errors.append(f"debt_schedule_reconciliation_failed: {exc}")


def _assert_cash_phase_trace_complete(payload: Optional[Dict[str, Any]], errors: List[str]) -> None:
  trace = payload if isinstance(payload, dict) else {}
  contract = trace.get("cash_pass_phase_contract") if isinstance(trace.get("cash_pass_phase_contract"), dict) else {}
  phases = contract.get("phase_sequence") if isinstance(contract.get("phase_sequence"), list) else []
  completed = {
    str(item.get("phase_code") or "").strip().lower()
    for item in (trace.get("completed_phases") or [])
    if isinstance(item, dict)
  }
  required = {
    str(item.get("phase_code") or "").strip().lower()
    for item in phases
    if isinstance(item, dict) and bool(item.get("required"))
  }
  missing = sorted(item for item in required if item and item not in completed)
  if missing:
    errors.append(f"cash_phase_trace_incomplete: missing={missing}")


def run_finalize_post_intake_validation(
  *,
  draft_id: str = "",
  planning_run_id: str = "",
  stage_ramp_contract: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]] = None,
  debt_schedule: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  contract_name: str = "unified_convergence_decision",
) -> Dict[str, Any]:
  """Validate that the completed post-intake state obeys table authority."""
  errors: List[str] = []
  runtime_table_integrity: Dict[str, Any] = {}
  required_process_sequence: Dict[str, Any] = {}
  process_step_contexts: Dict[str, Any] = {}

  try:
    runtime_table_integrity = post_intake_assert_runtime_table_integrity()
  except Exception as exc:
    errors.append(f"runtime_table_integrity_unavailable: {exc}")
  try:
    required_process_sequence = post_intake_assert_required_process_sequence()
  except Exception as exc:
    errors.append(f"process_sequence_unavailable: {exc}")
  for step_key in [
    "post_intake_finalize_validation",
    "cash_minimum_debt_schedule",
    "cash_strategy_review",
    "cash_pass_validation",
    "final_hard_gates",
  ]:
    try:
      process_step_contexts[step_key] = post_intake_process_step_context(step_key=step_key)
    except Exception as exc:
      errors.append(f"process_step_context_unavailable: {step_key}: {exc}")

  try:
    assert_post_intake_mapping_formula_contract_integrity(stage="post_intake_finalize_validation_mapping_contract")
  except Exception as exc:
    errors.append(f"mapping_formula_contract_invalid: {exc}")
  try:
    assert_post_intake_mapping_formula_application_integrity(
      model_input_json=copy.deepcopy(model_input_json or {}),
      finmo_json=copy.deepcopy(finmo_json or {}),
      stage="post_intake_finalize_validation_mapping_application",
      contract_name=contract_name,
    )
  except Exception as exc:
    errors.append(f"mapping_formula_application_invalid: {exc}")
  try:
    assert_post_intake_global_invariants(
      stage_ramp_contract=copy.deepcopy(stage_ramp_contract or {}),
      model_input_json=copy.deepcopy(model_input_json or {}),
      finmo_json=copy.deepcopy(finmo_json or {}),
      payroll_headcount=copy.deepcopy(payroll_headcount or {}),
      debt_schedule=copy.deepcopy(debt_schedule or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      enforce_cash_buffer=True,
      stage="post_intake_finalize_validation_global",
      contract_name=contract_name,
    )
  except Exception as exc:
    errors.append(f"global_invariants_invalid: {exc}")
  try:
    assert_post_intake_cash_buffer_integrity(
      financials_json=copy.deepcopy(financials_json or {}),
      model_input_json=copy.deepcopy(model_input_json or {}),
      finmo_json=copy.deepcopy(finmo_json or {}),
      stage="post_intake_finalize_validation_cash_buffer",
    )
  except Exception as exc:
    errors.append(f"cash_buffer_invalid: {exc}")

  if not isinstance(payroll_headcount, dict) or not payroll_headcount:
    errors.append("payroll_headcount_schedule_missing_at_finalize")
  if not isinstance(debt_schedule, dict) or not debt_schedule:
    errors.append("debt_schedule_missing_at_finalize")
  _assert_forecast_horizon_complete(
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    errors=errors,
  )
  _assert_model_input_values_complete(
    model_input_json=copy.deepcopy(model_input_json or {}),
    errors=errors,
  )
  _assert_finmo_values_complete(
    finmo_json=copy.deepcopy(finmo_json or {}),
    errors=errors,
  )
  _assert_revenue_formula_reconciles(
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    errors=errors,
  )
  _assert_payroll_schedule_reconciles(
    payroll_headcount=copy.deepcopy(payroll_headcount or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    errors=errors,
  )
  _assert_debt_schedule_reconciles(
    debt_schedule=copy.deepcopy(debt_schedule or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    errors=errors,
  )
  try:
    errors.extend(
      balance_sheet_driver_finalize_errors(
        financials_json=copy.deepcopy(financials_json or {}),
        ops_json=copy.deepcopy(ops_json or {}),
        model_input_json=copy.deepcopy(model_input_json or {}),
        finmo_json=copy.deepcopy(finmo_json or {}),
        debt_schedule=copy.deepcopy(debt_schedule or {}),
        cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result or {}),
      )
    )
  except Exception as exc:
    errors.append(f"balance_sheet_driver_validation_unavailable: {exc}")
  _assert_cash_phase_trace_complete(
    (cash_strategy_second_pass_result or {}).get("cash_pass_phase_trace")
    if isinstance(cash_strategy_second_pass_result, dict)
    else None,
    errors,
  )

  _raise_if_errors(errors)
  return {
    "validation_gate": "post_intake_finalize_validation",
    "status": "completed",
    "draft_id": str(draft_id or "").strip(),
    "planning_run_id": str(planning_run_id or "").strip(),
    "runtime_table_integrity": copy.deepcopy(runtime_table_integrity),
    "required_process_sequence": copy.deepcopy(required_process_sequence),
    "process_step_contexts": copy.deepcopy(process_step_contexts),
    "validated_outputs": [
      "model_input_json",
      "finmo_json",
      "stage_ramp_contract",
      "payroll_headcount",
      "debt_schedule",
      "cash_pass_phase_trace",
      "balance_sheet_driver_formula_application",
    ],
  }
