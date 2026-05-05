"""Table-backed balance-sheet driver sampling and formula validation."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_driver_formula_contract_rows,
)


HORIZON = 20
DAYS_IN_QUARTER = 90.0


def _safe_float(value: Any) -> Optional[float]:
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _clean(value: Any) -> str:
  return str(value or "").strip()


def _lower(value: Any) -> str:
  return _clean(value).lower()


def _json_dict(value: Any) -> Dict[str, Any]:
  if isinstance(value, dict):
    return value
  if isinstance(value, str) and value.strip():
    try:
      parsed = json.loads(value)
    except Exception:
      return {}
    return parsed if isinstance(parsed, dict) else {}
  return {}


def _live_finmo_rows(finmo_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  rows = (finmo_json or {}).get("quarter_rows") if isinstance(finmo_json, dict) else []
  live_rows = [
    row for row in (rows or [])
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  ]
  live_rows.sort(key=lambda row: int(_safe_float(row.get("quarter_index")) or 0))
  return live_rows[:HORIZON]


def _iter_model_input_rows(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_name in ("revenue", "expenses", "balance_sheet"):
    section_rows = sections.get(section_name)
    if isinstance(section_rows, list):
      rows.extend(row for row in section_rows if isinstance(row, dict))
  schedules = sections.get("schedules")
  if isinstance(schedules, dict):
    schedule_rows = schedules.get("rows")
    if isinstance(schedule_rows, list):
      rows.extend(row for row in schedule_rows if isinstance(row, dict))
  elif isinstance(schedules, list):
    rows.extend(row for row in schedules if isinstance(row, dict))
  return rows


def _model_input_row_for_lever(
  model_input_json: Optional[Dict[str, Any]],
  mapping_row: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  lever_id = _clean(mapping_row.get("lever_id"))
  target_driver = _lower(mapping_row.get("target_driver"))
  for row in _iter_model_input_rows(model_input_json):
    if _clean(row.get("lever_id")) == lever_id:
      return row
  for row in _iter_model_input_rows(model_input_json):
    label = _lower(row.get("label"))
    if target_driver and target_driver == label.replace(" ", "_").replace("/", "_"):
      return row
  return None


def _live_values(row: Dict[str, Any]) -> List[Any]:
  values = list(row.get("values") or [])
  if len(values) >= HORIZON + 1:
    return values[1:HORIZON + 1]
  return values[:HORIZON]


def _any_positive(values: List[Any]) -> bool:
  return any(float(_safe_float(value) or 0.0) > 0.0 for value in values)


def _financial_seed(financials_json: Optional[Dict[str, Any]], *keys: str) -> float:
  source = financials_json if isinstance(financials_json, dict) else {}
  for key in keys:
    value = _safe_float(source.get(key))
    if value is not None:
      return max(0.0, float(value))
  return 0.0


def _text_blob(*payloads: Optional[Dict[str, Any]]) -> str:
  parts: List[str] = []
  for payload in payloads:
    if isinstance(payload, dict):
      try:
        parts.append(json.dumps(payload, ensure_ascii=False).lower())
      except Exception:
        parts.append(str(payload).lower())
  return " ".join(parts)


def _tokens_from_mapping_row(mapping_row: Dict[str, Any], key: str) -> Tuple[str, ...]:
  raw = mapping_row.get(key)
  if not isinstance(raw, list):
    return ()
  return tuple(
    str(item or "").strip().lower()
    for item in raw
    if str(item or "").strip()
  )


def _business_text_has_any(text: str, tokens: Tuple[str, ...]) -> bool:
  return any(token in text for token in tokens)


def _contextual_seed_row_for_lever(
  model_input_json: Optional[Dict[str, Any]],
  lever_id: str,
) -> Optional[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  policies = payload.get("derived_driver_policies") if isinstance(payload.get("derived_driver_policies"), dict) else {}
  seed_policy = policies.get("balance_sheet_contextual_seed") if isinstance(policies, dict) else {}
  for row in ((seed_policy or {}).get("balance_sheet_seed_grid") or []):
    if isinstance(row, dict) and _clean(row.get("lever_id")) == lever_id:
      return row
  for model_row in _iter_model_input_rows(model_input_json):
    if _clean(model_row.get("lever_id")) != lever_id:
      continue
    seed_row = model_row.get("balance_sheet_contextual_seed")
    if isinstance(seed_row, dict):
      return seed_row
  return None


def _quarter_days_from_finmo_row(row: Dict[str, Any]) -> float:
  raw_date = _clean(row.get("date") or row.get("period_date"))
  parsed: Optional[date] = None
  if raw_date:
    try:
      parsed = datetime.fromisoformat(raw_date[:10]).date()
    except Exception:
      parsed = None
  if parsed is None:
    year = int(_safe_float(row.get("year") or row.get("period_year")) or 0)
    quarter = int(_safe_float(row.get("quarter") or row.get("period_quarter")) or 0)
    month = quarter * 3 if quarter in {1, 2, 3, 4} else 3
    if year > 0:
      parsed = date(year, month, 1)
  if parsed is None:
    return DAYS_IN_QUARTER
  quarter = ((parsed.month - 1) // 3) + 1
  start_month = (quarter - 1) * 3 + 1
  end_month = start_month + 2
  next_month = end_month + 1
  next_year = parsed.year
  if next_month == 13:
    next_month = 1
    next_year += 1
  start = date(parsed.year, start_month, 1)
  end_exclusive = date(next_year, next_month, 1)
  return float(max(1, (end_exclusive - start).days))


def _revenue_positive(finmo_rows: List[Dict[str, Any]], financials_json: Optional[Dict[str, Any]]) -> bool:
  if any(float(_safe_float(row.get("revenue")) or 0.0) > 0.0 for row in finmo_rows):
    return True
  return _financial_seed(
    financials_json,
    "current_revenue",
    "annual_revenue",
    "revenue",
    "year1_revenue",
  ) > 0.0


def _expense_base_positive(finmo_rows: List[Dict[str, Any]]) -> bool:
  fields = ("cost_of_goods_sold", "marketing", "research_and_development", "lease_rent", "payroll", "general_and_administrative")
  return any(
    sum(float(_safe_float(row.get(field)) or 0.0) for field in fields) > 0.0
    for row in finmo_rows
  )


def _debt_policy_or_existing_debt(
  *,
  financials_json: Optional[Dict[str, Any]],
  debt_schedule: Optional[Dict[str, Any]],
  cash_strategy_second_pass_result: Optional[Dict[str, Any]],
) -> bool:
  if _financial_seed(financials_json, "total_debt_outstanding", "short_term_debt") > 0.0:
    return True
  schedule = debt_schedule if isinstance(debt_schedule, dict) else {}
  for row in (schedule.get("rows") or schedule.get("debt_schedule_rows") or []):
    if not isinstance(row, dict):
      continue
    if any(float(_safe_float(row.get(field)) or 0.0) > 0.0 for field in ("opening_debt", "actual_debt_issuance", "closing_debt")):
      return True
  trace = cash_strategy_second_pass_result if isinstance(cash_strategy_second_pass_result, dict) else {}
  text = _text_blob(trace)
  return "debt_raise" in text or "debt_paydown" in text


def _mapping_row_applicable(
  mapping_row: Dict[str, Any],
  *,
  financials_json: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  debt_schedule: Optional[Dict[str, Any]],
  cash_strategy_second_pass_result: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
  key = _lower(mapping_row.get("business_applicability_key"))
  finmo_rows = _live_finmo_rows(finmo_json)
  text = _text_blob(ops_json, financials_json)
  if key in {"always", "revenue_positive"}:
    return _revenue_positive(finmo_rows, financials_json), key
  if key == "revenue_positive_ar_applicable":
    if _financial_seed(financials_json, "ar_balance") > 0.0:
      return True, key
    seed_row = _contextual_seed_row_for_lever(model_input_json, _clean(mapping_row.get("lever_id")))
    if isinstance(seed_row, dict) and "applicable" in seed_row:
      return bool(seed_row.get("applicable")), key
    return _revenue_positive(finmo_rows, financials_json), key
  if key == "operating_expense_positive_ap_applicable":
    no_vendor_tokens = _tokens_from_mapping_row(mapping_row, "applicability_negative_tokens")
    return _expense_base_positive(finmo_rows) and not _business_text_has_any(text, no_vendor_tokens), key
  if key == "inventory_business_or_seed":
    if _financial_seed(financials_json, "inventory_balance") > 0.0:
      return True, key
    seed_row = _contextual_seed_row_for_lever(model_input_json, _clean(mapping_row.get("lever_id")))
    if isinstance(seed_row, dict) and "applicable" in seed_row:
      return bool(seed_row.get("applicable")), key
    positive_tokens = _tokens_from_mapping_row(mapping_row, "applicability_positive_tokens")
    negative_tokens = _tokens_from_mapping_row(mapping_row, "applicability_negative_tokens")
    if _business_text_has_any(text, negative_tokens):
      return False, key
    return _business_text_has_any(text, positive_tokens), key
  if key == "optional_prepaid_expense":
    return False, key
  if key == "revenue_positive_prepaid_applicable":
    return _revenue_positive(finmo_rows, financials_json), key
  if key == "deferred_revenue_business":
    if _financial_seed(financials_json, "deferred_revenue") > 0.0:
      return True, key
    seed_row = _contextual_seed_row_for_lever(model_input_json, _clean(mapping_row.get("lever_id")))
    if isinstance(seed_row, dict) and "applicable" in seed_row:
      return bool(seed_row.get("applicable")), key
    deferred_tokens = _tokens_from_mapping_row(mapping_row, "applicability_positive_tokens")
    return _business_text_has_any(text, deferred_tokens), key
  if key == "debt_policy_or_existing_debt":
    return _debt_policy_or_existing_debt(
      financials_json=financials_json,
      debt_schedule=debt_schedule,
      cash_strategy_second_pass_result=cash_strategy_second_pass_result,
    ), key
  if key == "cash_strategy_requires":
    return _debt_policy_or_existing_debt(
      financials_json=financials_json,
      debt_schedule=debt_schedule,
      cash_strategy_second_pass_result=cash_strategy_second_pass_result,
    ), key
  if key == "optional":
    return False, key
  return False, key or "missing"


def _balance_sheet_mapping_rows() -> List[Dict[str, Any]]:
  rows = []
  for row in post_intake_driver_formula_contract_rows():
    if not isinstance(row, dict):
      continue
    lever_id = _clean(row.get("lever_id"))
    bundle = _lower(row.get("driver_bundle"))
    if lever_id.startswith("balance_sheet::") and bundle in {"working_capital_bundle", "debt_schedule_bundle"}:
      rows.append(row)
  return rows


def _formula_sample_requires_forecast_driver(mapping_row: Dict[str, Any], formula_sample_base: float) -> bool:
  if formula_sample_base <= 0.0:
    return False
  key = _lower(mapping_row.get("business_applicability_key"))
  lever_id = _clean(mapping_row.get("lever_id"))
  if key in {
    "revenue_positive_ar_applicable",
    "operating_expense_positive_ap_applicable",
    "revenue_positive_prepaid_applicable",
  }:
    return True
  if lever_id in {
    "balance_sheet::Accounts Receivable Days",
    "balance_sheet::Accounts Payable Days",
    "balance_sheet::Prepaid Expenses (% of Revenue)",
  }:
    return True
  return False


def build_balance_sheet_driver_initialization_sample(
  *,
  draft_row: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Sample intake omissions against table-backed balance-sheet driver rules."""
  draft = draft_row if isinstance(draft_row, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else _json_dict(draft.get("financials_json"))
  financials_year1 = _json_dict(draft.get("financials_year1_json"))
  ops = ops_json if isinstance(ops_json, dict) else _json_dict(draft.get("operating_model_json"))
  mapped_rows = _balance_sheet_mapping_rows()
  sample_rows: List[Dict[str, Any]] = []
  sample_revenue = _financial_seed(
    financials,
    "current_revenue",
    "annual_revenue",
    "revenue",
    "year1_revenue",
  )
  if sample_revenue <= 0.0:
    sample_revenue = _financial_seed(
      financials_year1,
      "company_revenue_total_year1",
      "revenue_total_year1",
      "year1_revenue",
    )
  sample_expense_base = sum(
    _financial_seed(financials, key)
    for key in (
      "current_cogs",
      "marketing_total_year1",
      "other_operating_expense",
      "monthly_rent_expense",
      "current_payroll",
      "owner_compensation",
    )
  )
  for row in mapped_rows:
    lever_id = _clean(row.get("lever_id"))
    seed_keys: Tuple[str, ...]
    if lever_id == "balance_sheet::Accounts Receivable Days":
      seed_keys = ("ar_balance",)
    elif lever_id == "balance_sheet::Inventory Days":
      seed_keys = ("inventory_balance",)
    elif lever_id == "balance_sheet::Accounts Payable Days":
      seed_keys = ("ap_balance",)
    elif lever_id == "balance_sheet::Short Term Debt (% of LTD)":
      seed_keys = ("short_term_debt", "total_debt_outstanding")
    else:
      seed_keys = ()
    seed_value = _financial_seed(financials, *seed_keys) if seed_keys else 0.0
    validation_formula_key = _lower(row.get("validation_formula_key"))
    if validation_formula_key in {"finmo_equals_revenue_times_model_input_ratio"}:
      formula_sample_base = sample_revenue
    elif lever_id == "balance_sheet::Accounts Receivable Days":
      formula_sample_base = sample_revenue
    elif lever_id == "balance_sheet::Accounts Payable Days":
      formula_sample_base = sample_expense_base
    elif lever_id == "balance_sheet::Inventory Days":
      formula_sample_base = _financial_seed(financials, "current_cogs", "cogs", "current_cogs_absolute")
    elif lever_id == "balance_sheet::Short Term Debt (% of LTD)":
      formula_sample_base = _financial_seed(financials, "total_debt_outstanding")
    else:
      formula_sample_base = 0.0
    applicable, applicability_key = _mapping_row_applicable(
      row,
      financials_json=financials,
      ops_json=ops,
      model_input_json=None,
      finmo_json=None,
      debt_schedule=None,
      cash_strategy_second_pass_result=None,
    )
    formula_sample_requires_driver = _formula_sample_requires_forecast_driver(row, formula_sample_base)
    sample_rows.append(
      {
        "lever_id": lever_id,
        "business_applicability_key": applicability_key,
        "forecast_presence_rule_key": _lower(row.get("forecast_presence_rule_key")),
        "validation_formula_key": validation_formula_key,
        "intake_seed_keys": list(seed_keys),
        "intake_seed_value": seed_value,
        "intake_seed_missing_or_zero": seed_value <= 0.0,
        "formula_sample_base": formula_sample_base,
        "formula_sample_indicates_required": formula_sample_requires_driver,
        "forecast_driver_required_by_table": bool(applicable or formula_sample_requires_driver),
        "source_of_truth": "sql.post_intak_mapping_lookup",
      }
    )
  return {
    "sample_name": "balance_sheet_driver_initialization_sample",
    "source_of_truth": "sql.post_intak_mapping_lookup",
    "mapped_driver_count": len(mapped_rows),
    "rows": sample_rows,
    "intake_omissions_requiring_forecast_accounting": [
      row for row in sample_rows
      if row["intake_seed_missing_or_zero"] and row["forecast_driver_required_by_table"]
    ],
  }


def balance_sheet_driver_initialization_sample_errors(sample: Optional[Dict[str, Any]]) -> List[str]:
  payload = sample if isinstance(sample, dict) else {}
  errors: List[str] = []
  rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
  if payload.get("source_of_truth") != "sql.post_intak_mapping_lookup":
    errors.append("balance_sheet_driver_sample_source_invalid")
  if int(_safe_float(payload.get("mapped_driver_count")) or 0) != len(rows) or len(rows) < 5:
    errors.append(
      f"balance_sheet_driver_sample_row_count_invalid: "
      f"mapped_driver_count={payload.get('mapped_driver_count')} rows={len(rows)}"
    )
  required_fields = {
    "lever_id",
    "business_applicability_key",
    "forecast_presence_rule_key",
    "validation_formula_key",
    "formula_sample_base",
    "formula_sample_indicates_required",
    "forecast_driver_required_by_table",
    "source_of_truth",
  }
  for row in rows:
    lever_id = _clean(row.get("lever_id")) or "unknown"
    missing = sorted(field for field in required_fields if field not in row or row.get(field) in {None, ""})
    if missing:
      errors.append(f"balance_sheet_driver_sample_row_missing_fields: {lever_id} missing={missing}")
    if row.get("source_of_truth") != "sql.post_intak_mapping_lookup":
      errors.append(f"balance_sheet_driver_sample_row_source_invalid: {lever_id}")
    if bool(row.get("formula_sample_indicates_required")) and not bool(row.get("forecast_driver_required_by_table")):
      errors.append(f"balance_sheet_driver_sample_required_flag_inconsistent: {lever_id}")
  required_levers = {
    "balance_sheet::Accounts Receivable Days",
    "balance_sheet::Accounts Payable Days",
    "balance_sheet::Prepaid Expenses (% of Revenue)",
  }
  present = {_clean(row.get("lever_id")) for row in rows}
  missing_required_levers = sorted(item for item in required_levers if item not in present)
  if missing_required_levers:
    errors.append(f"balance_sheet_driver_sample_required_levers_missing: {missing_required_levers}")
  return errors


def balance_sheet_driver_finalize_errors(
  *,
  financials_json: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  debt_schedule: Optional[Dict[str, Any]],
  cash_strategy_second_pass_result: Optional[Dict[str, Any]],
) -> List[str]:
  """Validate applicable balance-sheet drivers and FINMO formula results."""
  errors: List[str] = []
  finmo_rows = _live_finmo_rows(finmo_json)
  if len(finmo_rows) != HORIZON:
    errors.append(f"balance_sheet_driver_finmo_horizon_invalid: expected=20 actual={len(finmo_rows)}")
    return errors
  for mapping_row in _balance_sheet_mapping_rows():
    lever_id = _clean(mapping_row.get("lever_id"))
    validation_key = _lower(mapping_row.get("validation_formula_key"))
    presence_rule = _lower(mapping_row.get("forecast_presence_rule_key"))
    applicable, applicability_key = _mapping_row_applicable(
      mapping_row,
      financials_json=financials_json,
      ops_json=ops_json,
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      debt_schedule=debt_schedule,
      cash_strategy_second_pass_result=cash_strategy_second_pass_result,
    )
    model_row = _model_input_row_for_lever(model_input_json, mapping_row)
    if model_row is None:
      errors.append(f"balance_sheet_driver_missing: {lever_id} applicability={applicability_key}")
      continue
    values = _live_values(model_row)
    if len(values) != HORIZON:
      errors.append(f"balance_sheet_driver_horizon_invalid: {lever_id} expected=20 actual={len(values)}")
      continue
    numeric_values = [_safe_float(value) for value in values]
    if any(value is None for value in numeric_values):
      errors.append(f"balance_sheet_driver_nonnumeric: {lever_id}")
      continue
    if applicable and presence_rule == "positive_driver_when_applicable" and not _any_positive(values):
      errors.append(
        f"balance_sheet_driver_zero_but_applicable: {lever_id} "
        f"applicability={applicability_key} zero_allowed_reason={_clean(mapping_row.get('zero_allowed_reason_key'))}"
      )
      continue
    if not applicable and not _any_positive(values):
      continue
    for quarter_index, finmo_row in enumerate(finmo_rows, start=1):
      value = float(numeric_values[quarter_index - 1] or 0.0)
      if validation_key == "finmo_working_capital_days":
        days_in_quarter = _quarter_days_from_finmo_row(finmo_row)
        if lever_id == "balance_sheet::Accounts Receivable Days":
          target_field = "accounts_receivable"
          base = float(_safe_float(finmo_row.get("revenue")) or 0.0)
        elif lever_id == "balance_sheet::Inventory Days":
          target_field = "inventory"
          base = float(_safe_float(finmo_row.get("cost_of_goods_sold")) or 0.0)
        else:
          target_field = "accounts_payable"
          base = sum(
            float(_safe_float(finmo_row.get(field)) or 0.0)
            for field in ("marketing", "research_and_development", "lease_rent", "payroll", "general_and_administrative")
          )
        expected = int(round((value / days_in_quarter) * base))
        actual = int(round(float(_safe_float(finmo_row.get(target_field)) or 0.0)))
        if expected != actual:
          errors.append(
            f"balance_sheet_driver_formula_failed: {lever_id} q={quarter_index} "
            f"field={target_field} actual={actual} expected={expected}"
          )
          break
      elif validation_key == "finmo_equals_revenue_times_model_input_ratio":
        target = "prepaid_expenses" if "Prepaid" in lever_id else "deferred_revenue"
        expected = int(round(float(_safe_float(finmo_row.get("revenue")) or 0.0) * value))
        actual = int(round(float(_safe_float(finmo_row.get(target)) or 0.0)))
        if expected != actual:
          errors.append(
            f"balance_sheet_driver_formula_failed: {lever_id} q={quarter_index} "
            f"field={target} actual={actual} expected={expected}"
          )
          break
      elif validation_key == "finmo_short_term_debt_percent_of_ltd":
        schedule = debt_schedule if isinstance(debt_schedule, dict) else {}
        schedule_rows = [
          item for item in (schedule.get("rows") or schedule.get("debt_schedule_rows") or [])
          if isinstance(item, dict)
        ]
        schedule_row = next(
          (item for item in schedule_rows if int(_safe_float(item.get("quarter_index")) or 0) == quarter_index),
          {},
        )
        closing_debt = float(_safe_float(schedule_row.get("closing_debt")) or 0.0)
        if closing_debt <= 0.0 and not applicable:
          continue
        expected = int(round(value * closing_debt))
        actual = int(round(float(_safe_float(finmo_row.get("short_term_debt")) or 0.0)))
        if expected != actual:
          errors.append(
            f"balance_sheet_driver_formula_failed: {lever_id} q={quarter_index} "
            f"field=short_term_debt actual={actual} expected={expected}"
          )
          break
  return errors
