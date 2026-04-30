from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PAYROLL_DERIVATION_POLICY_VERSION = "payroll_revenue_oews_policy_v2"
PAYROLL_DERIVATION_SOURCE = "revenue_oews_derived"
PAYROLL_DERIVATION_LEVER_ID = "expenses::Payroll"
DEFAULT_AVG_ANNUAL_SALARY = 150000.0
DEFAULT_REVENUE_PER_EMPLOYEE = 650000.0
PAYROLL_RATIO_FLOOR = 0.05
PAYROLL_RATIO_CEILING = 0.50
MAX_FTE_GROWTH_PER_QUARTER = 0.50
ROOT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"

_OEWS_ALL_OCCUPATIONS_WAGE_CACHE: Dict[str, Tuple[float, str]] = {}

__all__ = [
  "PAYROLL_DERIVATION_POLICY_VERSION",
  "PAYROLL_DERIVATION_SOURCE",
  "PAYROLL_DERIVATION_LEVER_ID",
  "default_payroll_derivation_policy",
  "normalized_payroll_derivation_policy",
  "apply_stage_ramp_payroll_growth_contract_to_model_input",
  "apply_payroll_derivation_policy_to_model_input",
  "validate_payroll_derivation_contract",
]


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


def _load_root_env() -> None:
  if not ROOT_ENV_PATH.exists():
    return
  try:
    for line in ROOT_ENV_PATH.read_text(encoding="utf-8").splitlines():
      text = line.strip()
      if not text or text.startswith("#") or "=" not in text:
        continue
      key, value = text.split("=", 1)
      key = key.strip()
      value = value.strip().strip('"').strip("'")
      if key and os.getenv(key) is None:
        os.environ[key] = value
  except Exception:
    return


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


def _placeholder_index(value: Any, prefix: str) -> Optional[int]:
  raw = str(value or "").strip()
  if not raw:
    return None
  lowered = raw.lower()
  normalized_prefix = str(prefix or "").strip().lower()
  if not lowered.startswith(normalized_prefix.lower()):
    return None
  suffix = raw[len(normalized_prefix):].strip()
  if not suffix:
    return None
  try:
    return max(0, int(suffix) - 1)
  except Exception:
    return None


def _revenue_slot_key(lob_index: int, product_index: int) -> str:
  return f"lob_{max(0, int(lob_index)) + 1}_product_{max(0, int(product_index)) + 1}"


def _revenue_slot_identity(
  *,
  row_lob: Any,
  row_product: Any,
  revenue_row_ordinal: Optional[int] = None,
) -> Dict[str, Any]:
  lob_index = _placeholder_index(row_lob, "LOB")
  product_index = _placeholder_index(row_product, "Product")
  if lob_index is None or product_index is None:
    slot_ordinal = max(0, int(revenue_row_ordinal or 0)) // 3
    lob_index = slot_ordinal // 3
    product_index = slot_ordinal % 3
  return {
    "lob_slot_index": lob_index,
    "product_slot_index": product_index,
    "revenue_slot_key": _revenue_slot_key(lob_index, product_index),
  }


def _payroll_row_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  for row in (sections.get("expenses") or []):
    if isinstance(row, dict) and str(row.get("label") or "").strip() == "Payroll":
      return row
  return None


def _revenue_driver_live_series(
  model_input_json: Optional[Dict[str, Any]],
  *,
  driver_name: str,
  live_count: int,
) -> Dict[str, List[float]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  out: Dict[str, List[float]] = {}
  for ordinal, row in enumerate(revenue_rows):
    driver = str(row.get("driver") or "").strip().lower()
    if driver != str(driver_name or "").strip().lower():
      continue
    key = str(
      row.get("revenue_slot_key")
      or _revenue_slot_identity(
        row_lob=row.get("lob") or row.get("placeholder_lob"),
        row_product=row.get("product") or row.get("placeholder_product"),
        revenue_row_ordinal=ordinal,
      ).get("revenue_slot_key")
      or ""
    ).strip()
    if not key:
      continue
    _stub_value, live_values = _row_stub_and_live_values(row.get("values") or [], live_count=live_count)
    out[key] = [round(max(0.0, _safe_float(value) or 0.0), 6) for value in live_values[:live_count]]
  return out


def _revenue_live_series_from_model_input(
  model_input_json: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> List[float]:
  capacity_series = _revenue_driver_live_series(model_input_json, driver_name="Capacity", live_count=live_count)
  unit_price_series = _revenue_driver_live_series(model_input_json, driver_name="Unit Price", live_count=live_count)
  utilization_series = _revenue_driver_live_series(model_input_json, driver_name="Utilization", live_count=live_count)
  revenue_by_quarter: List[float] = [0.0 for _ in range(live_count)]
  for key in sorted(set(list(capacity_series.keys()) + list(unit_price_series.keys()) + list(utilization_series.keys()))):
    capacities = capacity_series.get(key) or [0.0 for _ in range(live_count)]
    unit_prices = unit_price_series.get(key) or [0.0 for _ in range(live_count)]
    utilizations = utilization_series.get(key) or [0.0 for _ in range(live_count)]
    for idx in range(live_count):
      revenue_by_quarter[idx] += (
        max(0.0, _safe_float(capacities[idx]) or 0.0)
        * max(0.0, _safe_float(unit_prices[idx]) or 0.0)
        * max(0.0, _safe_float(utilizations[idx]) or 0.0)
      )
  return [round(float(value), 6) for value in revenue_by_quarter]


def _payroll_average_annual_salary_and_source(
  ops_json: Optional[Dict[str, Any]],
) -> Tuple[float, str]:
  ops = ops_json if isinstance(ops_json, dict) else {}
  naics_value = str(ops.get("business_naics_6") or "").strip()
  cache_key = naics_value or "__fallback__"
  cached = _OEWS_ALL_OCCUPATIONS_WAGE_CACHE.get(cache_key)
  if cached:
    return round(float(cached[0]), 6), str(cached[1] or "cached_oews_all_occupations_mean")

  query_codes: List[str] = []
  if naics_value:
    query_codes.append(naics_value)
    for prefix_len in (4, 3, 2):
      if len(naics_value) >= prefix_len:
        prefix = naics_value[:prefix_len]
        if prefix not in query_codes:
          query_codes.append(prefix)
  for fallback_code in ("000001", "000000"):
    if fallback_code not in query_codes:
      query_codes.append(fallback_code)

  _load_root_env()
  conn = None
  cur = None
  try:
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
    conn = get_mysql_connection()
    cur = conn.cursor(dictionary=True)
    for code in query_codes:
      cur.execute(
        """
        SELECT naics, a_mean, a_median
        FROM oews_state_wages
        WHERE prim_state = %s
          AND naics = %s
          AND occ_title = %s
          AND o_group = %s
        LIMIT 1
        """,
        ("US", code, "All Occupations", "total"),
      )
      row = cur.fetchone() or {}
      mean_value = _safe_float(row.get("a_mean"))
      if mean_value is not None and mean_value > 0.0:
        source = f"oews_all_occupations_mean:{code}"
        _OEWS_ALL_OCCUPATIONS_WAGE_CACHE[cache_key] = (round(float(mean_value), 6), source)
        return round(float(mean_value), 6), source
      median_value = _safe_float(row.get("a_median"))
      if median_value is not None and median_value > 0.0:
        source = f"oews_all_occupations_median_fallback:{code}"
        _OEWS_ALL_OCCUPATIONS_WAGE_CACHE[cache_key] = (round(float(median_value), 6), source)
        return round(float(median_value), 6), source
  except Exception:
    pass
  finally:
    try:
      if cur is not None:
        cur.close()
    except Exception:
      pass
    try:
      if conn is not None:
        conn.close()
    except Exception:
      pass
  fallback = float(DEFAULT_AVG_ANNUAL_SALARY)
  _OEWS_ALL_OCCUPATIONS_WAGE_CACHE[cache_key] = (fallback, "default_fallback_annual_wage")
  return fallback, "default_fallback_annual_wage"


def _payroll_revenue_per_employee_and_source(
  financials_json: Optional[Dict[str, Any]],
  *,
  avg_salary: float,
) -> Tuple[float, str]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  current_revenue = max(0.0, _safe_float(financials.get("current_revenue")) or 0.0)
  current_num_employees = max(0.0, _safe_float(financials.get("current_num_employees")) or 0.0)
  if current_revenue > 0.0 and current_num_employees > 0.0:
    candidate = float(current_revenue / current_num_employees)
    implied_ratio = float(avg_salary / max(candidate, 1.0))
    if PAYROLL_RATIO_FLOOR <= implied_ratio <= PAYROLL_RATIO_CEILING:
      return round(candidate, 6), "intake_current_revenue_per_employee"
  return float(DEFAULT_REVENUE_PER_EMPLOYEE), "default_revenue_per_employee"


def default_payroll_derivation_policy(
  *,
  financials_json: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  avg_salary, avg_salary_source = _payroll_average_annual_salary_and_source(ops_json)
  revenue_per_employee, revenue_per_employee_source = _payroll_revenue_per_employee_and_source(
    financials_json,
    avg_salary=avg_salary,
  )
  ops = ops_json if isinstance(ops_json, dict) else {}
  return {
    "policy_version": PAYROLL_DERIVATION_POLICY_VERSION,
    "payroll_source": PAYROLL_DERIVATION_SOURCE,
    "lever_id": PAYROLL_DERIVATION_LEVER_ID,
    "driver_basis": "quarter_revenue",
    "salary_basis": "oews_all_occupations_mean",
    "avg_salary": float(avg_salary),
    "revenue_per_employee": float(revenue_per_employee),
    "payroll_ratio_floor": float(PAYROLL_RATIO_FLOOR),
    "payroll_ratio_ceiling": float(PAYROLL_RATIO_CEILING),
    "max_fte_growth_per_quarter": float(MAX_FTE_GROWTH_PER_QUARTER),
    "avg_salary_source": avg_salary_source,
    "revenue_per_employee_source": revenue_per_employee_source,
    "business_type": str(ops.get("business_type") or "").strip() or None,
    "naics": str(ops.get("business_naics_6") or "").strip() or None,
  }


def normalized_payroll_derivation_policy(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  policies = payload.get("derived_driver_policies") if isinstance(payload.get("derived_driver_policies"), dict) else {}
  raw_policy = policies.get(PAYROLL_DERIVATION_LEVER_ID) if isinstance(policies.get(PAYROLL_DERIVATION_LEVER_ID), dict) else {}
  avg_salary = float(max(1.0, _safe_float(raw_policy.get("avg_salary")) or DEFAULT_AVG_ANNUAL_SALARY))
  revenue_per_employee = float(max(1.0, _safe_float(raw_policy.get("revenue_per_employee")) or DEFAULT_REVENUE_PER_EMPLOYEE))
  payroll_ratio_floor = float(max(0.0, _safe_ratio(raw_policy.get("payroll_ratio_floor")) or PAYROLL_RATIO_FLOOR))
  payroll_ratio_ceiling = float(max(payroll_ratio_floor, _safe_ratio(raw_policy.get("payroll_ratio_ceiling")) or PAYROLL_RATIO_CEILING))
  max_fte_growth_per_quarter = float(max(0.0, _safe_ratio(raw_policy.get("max_fte_growth_per_quarter")) or MAX_FTE_GROWTH_PER_QUARTER))
  raw_growth_rows = raw_policy.get("payroll_growth_by_quarter")
  payroll_growth_by_quarter: List[Dict[str, Any]] = []
  if isinstance(raw_growth_rows, list):
    seen_quarters: set[int] = set()
    for item in raw_growth_rows:
      if not isinstance(item, dict):
        continue
      quarter_index = int(round(float(_safe_float(item.get("quarter_index")) or 0.0)))
      if quarter_index < 1 or quarter_index in seen_quarters:
        continue
      seen_quarters.add(quarter_index)
      growth_target = float(_safe_ratio(item.get("payroll_growth_target")) or 0.0)
      growth_max = float(_safe_ratio(item.get("payroll_growth_max")) or growth_target)
      payroll_growth_by_quarter.append(
        {
          "quarter_index": quarter_index,
          "payroll_growth_target": round(max(0.0, growth_target), 6),
          "payroll_growth_max": round(max(max(0.0, growth_target), growth_max), 6),
        }
      )
  payroll_growth_by_quarter = sorted(payroll_growth_by_quarter, key=lambda row: int(row.get("quarter_index") or 0))
  return {
    "policy_version": str(raw_policy.get("policy_version") or PAYROLL_DERIVATION_POLICY_VERSION).strip(),
    "payroll_source": PAYROLL_DERIVATION_SOURCE,
    "lever_id": PAYROLL_DERIVATION_LEVER_ID,
    "driver_basis": str(raw_policy.get("driver_basis") or "quarter_revenue").strip() or "quarter_revenue",
    "salary_basis": str(raw_policy.get("salary_basis") or "oews_all_occupations_mean").strip() or "oews_all_occupations_mean",
    "avg_salary": avg_salary,
    "revenue_per_employee": revenue_per_employee,
    "payroll_ratio_floor": payroll_ratio_floor,
    "payroll_ratio_ceiling": payroll_ratio_ceiling,
    "max_fte_growth_per_quarter": max_fte_growth_per_quarter,
    "payroll_growth_source": str(raw_policy.get("payroll_growth_source") or "").strip() or None,
    "payroll_growth_by_quarter": payroll_growth_by_quarter,
    "avg_salary_source": str(raw_policy.get("avg_salary_source") or "default_fallback_annual_wage").strip() or "default_fallback_annual_wage",
    "revenue_per_employee_source": str(raw_policy.get("revenue_per_employee_source") or "default_revenue_per_employee").strip() or "default_revenue_per_employee",
    "business_type": str(raw_policy.get("business_type") or "").strip() or None,
    "naics": str(raw_policy.get("naics") or "").strip() or None,
  }


def apply_stage_ramp_payroll_growth_contract_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  next_payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  contract = stage_ramp_contract if isinstance(stage_ramp_contract, dict) else {}
  grid_rows = [row for row in (contract.get("quarter_ramp_grid") or []) if isinstance(row, dict)]
  payroll_growth_rows: List[Dict[str, Any]] = []
  for row in grid_rows:
    quarter_index = int(round(float(_safe_float(row.get("quarter_index")) or 0.0)))
    if quarter_index < 1:
      continue
    growth_target = round(float(_safe_ratio(row.get("payroll_growth_target")) or 0.0), 6)
    growth_max = round(float(_safe_ratio(row.get("payroll_growth_max")) or _safe_ratio(row.get("payroll_growth_target")) or 0.0), 6)
    if growth_target > growth_max + 1e-9:
      raise RuntimeError(
        f"payroll_growth_contract_invalid_bounds: Q{quarter_index} payroll_growth_target cannot exceed payroll_growth_max."
      )
    payroll_growth_rows.append(
      {
        "quarter_index": quarter_index,
        "payroll_growth_target": growth_target,
        "payroll_growth_max": growth_max,
      }
    )
  expected_quarters = set(range(1, 21))
  actual_quarters = {int(row.get("quarter_index") or 0) for row in payroll_growth_rows}
  if len(payroll_growth_rows) != 20 or actual_quarters != expected_quarters:
    raise RuntimeError(
      "payroll_growth_contract_missing_full_horizon: stage_ramp_contract must include payroll_growth_target/payroll_growth_max for Q1-Q20."
    )
  next_payload.setdefault("derived_driver_policies", {})
  policies = next_payload.get("derived_driver_policies") if isinstance(next_payload.get("derived_driver_policies"), dict) else {}
  raw_policy = policies.get(PAYROLL_DERIVATION_LEVER_ID) if isinstance(policies.get(PAYROLL_DERIVATION_LEVER_ID), dict) else {}
  policy = normalized_payroll_derivation_policy({
    **deepcopy(next_payload),
    "derived_driver_policies": {
      **deepcopy(policies),
      PAYROLL_DERIVATION_LEVER_ID: deepcopy(raw_policy),
    },
  })
  policy["payroll_growth_source"] = "gpt_stage_ramp_contract"
  policy["payroll_growth_contract_version"] = str(contract.get("contract_version") or "").strip() or "stage_ramp_contract"
  policy["payroll_growth_by_quarter"] = sorted(
    payroll_growth_rows,
    key=lambda item: int(item.get("quarter_index") or 0),
  )
  next_payload["derived_driver_policies"][PAYROLL_DERIVATION_LEVER_ID] = deepcopy(policy)
  return next_payload


def apply_payroll_derivation_policy_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> Dict[str, Any]:
  next_payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  if isinstance(next_payload.get("controller_write_levers"), list):
    next_payload["controller_write_levers"] = [
      deepcopy(item)
      for item in (next_payload.get("controller_write_levers") or [])
      if isinstance(item, dict) and str(item.get("lever_id") or "").strip() != PAYROLL_DERIVATION_LEVER_ID
    ]
  if isinstance(next_payload.get("lever_catalog"), dict):
    lever_catalog = deepcopy(next_payload.get("lever_catalog") or {})
    lever_catalog.pop(PAYROLL_DERIVATION_LEVER_ID, None)
    next_payload["lever_catalog"] = lever_catalog

  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  payroll_row = next((row for row in expense_rows if str(row.get("label") or "").strip() == "Payroll"), None)
  if not isinstance(payroll_row, dict):
    return next_payload

  next_payload.setdefault("derived_driver_policies", {})
  next_payload.setdefault("derived_driver_runtime", {})
  values = list(payroll_row.get("values") or [])
  stub_value, _existing_live_values = _row_stub_and_live_values(values, live_count=live_count)
  policy = normalized_payroll_derivation_policy(next_payload)
  revenue_by_quarter = _revenue_live_series_from_model_input(next_payload, live_count=live_count)
  avg_annual_salary = float(policy.get("avg_salary") or DEFAULT_AVG_ANNUAL_SALARY)
  revenue_per_employee = float(policy.get("revenue_per_employee") or DEFAULT_REVENUE_PER_EMPLOYEE)
  payroll_growth_by_quarter: Dict[int, Dict[str, Any]] = {}
  for item in (policy.get("payroll_growth_by_quarter") or []):
    if not isinstance(item, dict):
      continue
    quarter_index = int(round(float(_safe_float(item.get("quarter_index")) or 0.0)))
    if quarter_index >= 1:
      payroll_growth_by_quarter[quarter_index] = deepcopy(item)

  derived_live_values: List[float] = []
  quarter_logs: List[Dict[str, Any]] = []
  previous_implied_fte_raw: Optional[float] = None
  for idx, quarter_revenue in enumerate(revenue_by_quarter, start=1):
    effective_revenue_per_employee = max(revenue_per_employee, 1.0)
    payroll_growth_row = payroll_growth_by_quarter.get(idx)
    payroll_growth_target = None
    if quarter_revenue > 0.0 and isinstance(payroll_growth_row, dict):
      payroll_growth_target = float(_safe_ratio(payroll_growth_row.get("payroll_growth_target")) or 0.0)
    implied_fte_raw = float((max(0.0, quarter_revenue) * 4.0) / max(effective_revenue_per_employee, 1.0)) if quarter_revenue > 0.0 else 0.0
    derived_payroll = round(float((max(0.0, quarter_revenue) * avg_annual_salary) / max(effective_revenue_per_employee, 1.0)), 6) if quarter_revenue > 0.0 else 0.0
    payroll_to_revenue = round(float(derived_payroll / quarter_revenue), 6) if quarter_revenue > 0.0 else 0.0
    fte_growth_qoq = None
    if previous_implied_fte_raw is not None and previous_implied_fte_raw > 0.0:
      fte_growth_qoq = round(float((implied_fte_raw - previous_implied_fte_raw) / previous_implied_fte_raw), 6)
    derived_live_values.append(derived_payroll)
    quarter_logs.append(
      {
        "quarter_index": idx,
        "payroll_source": PAYROLL_DERIVATION_SOURCE,
        "quarter_revenue": round(float(max(0.0, quarter_revenue)), 6),
        "base_revenue_per_employee": round(float(revenue_per_employee), 6),
        "effective_revenue_per_employee": round(float(effective_revenue_per_employee), 6),
        "avg_salary": round(float(avg_annual_salary), 6),
        "payroll_growth_source": policy.get("payroll_growth_source"),
        "payroll_growth_target": payroll_growth_target,
        "payroll_growth_target_payroll": None,
        "implied_fte_raw": round(float(implied_fte_raw), 6),
        "derived_payroll": derived_payroll,
        "payroll_to_revenue": payroll_to_revenue,
        "fte_growth_qoq": fte_growth_qoq,
      }
    )
    previous_implied_fte_raw = float(implied_fte_raw)

  payroll_row["controller_write"] = False
  payroll_row["derived_driver"] = PAYROLL_DERIVATION_SOURCE
  payroll_row["payroll_derivation"] = {
    "policy_version": str(policy.get("policy_version") or PAYROLL_DERIVATION_POLICY_VERSION).strip(),
    "payroll_source": PAYROLL_DERIVATION_SOURCE,
    "driver_basis": str(policy.get("driver_basis") or "quarter_revenue").strip() or "quarter_revenue",
    "salary_basis": str(policy.get("salary_basis") or "oews_all_occupations_mean").strip() or "oews_all_occupations_mean",
    "revenue_per_employee": round(float(revenue_per_employee), 6),
    "avg_salary": round(float(avg_annual_salary), 6),
    "revenue_per_employee_source": str(policy.get("revenue_per_employee_source") or "").strip() or None,
    "avg_salary_source": str(policy.get("avg_salary_source") or "").strip() or None,
    "payroll_ratio_floor": round(float(policy.get("payroll_ratio_floor") or PAYROLL_RATIO_FLOOR), 6),
    "payroll_ratio_ceiling": round(float(policy.get("payroll_ratio_ceiling") or PAYROLL_RATIO_CEILING), 6),
    "max_fte_growth_per_quarter": round(float(policy.get("max_fte_growth_per_quarter") or MAX_FTE_GROWTH_PER_QUARTER), 6),
    "payroll_growth_source": policy.get("payroll_growth_source"),
    "payroll_growth_by_quarter": deepcopy(policy.get("payroll_growth_by_quarter") or []),
    "quarter_logs": deepcopy(quarter_logs),
  }
  payroll_row["values"] = _compose_period_values(
    stub_value=stub_value,
    live_values=derived_live_values,
  )
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"][PAYROLL_DERIVATION_LEVER_ID] = deepcopy(policy)
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][PAYROLL_DERIVATION_LEVER_ID] = {
      "payroll_source": PAYROLL_DERIVATION_SOURCE,
      "policy_version": str(policy.get("policy_version") or PAYROLL_DERIVATION_POLICY_VERSION).strip(),
      "driver_basis": str(policy.get("driver_basis") or "quarter_revenue").strip() or "quarter_revenue",
      "salary_basis": str(policy.get("salary_basis") or "oews_all_occupations_mean").strip() or "oews_all_occupations_mean",
      "revenue_per_employee": round(float(revenue_per_employee), 6),
      "avg_salary": round(float(avg_annual_salary), 6),
      "revenue_per_employee_source": str(policy.get("revenue_per_employee_source") or "").strip() or None,
      "avg_salary_source": str(policy.get("avg_salary_source") or "").strip() or None,
      "payroll_ratio_floor": round(float(policy.get("payroll_ratio_floor") or PAYROLL_RATIO_FLOOR), 6),
      "payroll_ratio_ceiling": round(float(policy.get("payroll_ratio_ceiling") or PAYROLL_RATIO_CEILING), 6),
      "max_fte_growth_per_quarter": round(float(policy.get("max_fte_growth_per_quarter") or MAX_FTE_GROWTH_PER_QUARTER), 6),
      "payroll_growth_source": policy.get("payroll_growth_source"),
      "payroll_growth_by_quarter": deepcopy(policy.get("payroll_growth_by_quarter") or []),
      "quarter_logs": deepcopy(quarter_logs),
    }
  return next_payload


def _stage_ramp_grid_rows(contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = contract if isinstance(contract, dict) else {}
  raw_rows = payload.get("quarter_ramp_grid")
  if not isinstance(raw_rows, list) or not raw_rows:
    return []
  rows_by_quarter: Dict[int, Dict[str, Any]] = {}
  for row in raw_rows:
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if 1 <= quarter_index <= 20 and quarter_index not in rows_by_quarter:
      normalized = deepcopy(row)
      normalized["quarter_index"] = quarter_index
      rows_by_quarter[quarter_index] = normalized
  return [rows_by_quarter[quarter] for quarter in sorted(rows_by_quarter)]


def validate_payroll_derivation_contract(
  *,
  model_input_json: Optional[Dict[str, Any]],
  business_world_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  details: List[Dict[str, Any]] = []
  current_row = _payroll_row_from_model_input(payload)
  if not isinstance(current_row, dict):
    return {
      "status": "failed",
      "details": [{
        "error": "payroll_row_missing",
        "lever_id": PAYROLL_DERIVATION_LEVER_ID,
        "quarter": 0,
        "previous_value": None,
        "current_value": None,
        "reason": "Model input is missing the Payroll row in sections.expenses.",
        "validation_category": "payroll_derivation",
      }],
      "current_policy": {},
      "current_runtime": {},
      "expected_runtime": {},
    }

  current_values = list(current_row.get("values") or [])
  live_count = max(
    0,
    len([item for item in (payload.get("periods") or []) if isinstance(item, dict) and not bool(item.get("is_stub"))])
    or (len(current_values) - 1 if len(current_values) >= 1 else 0),
  )
  stub_value = _safe_float(current_values[0] if current_values else None)
  if len(current_values) < live_count + 1:
    details.append({
      "error": "payroll_stub_missing",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": None,
      "current_value": None,
      "reason": "Payroll values must include a Q0 stub plus all live forecast quarters.",
      "validation_category": "payroll_derivation",
    })
  if bool(current_row.get("controller_write", True)):
    details.append({
      "error": "payroll_row_should_not_be_writable",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": stub_value,
      "current_value": stub_value,
      "reason": "Payroll must not remain controller-writable once payroll is revenue/OEWS-derived.",
      "validation_category": "payroll_derivation",
    })
  if str(current_row.get("derived_driver") or "").strip() != PAYROLL_DERIVATION_SOURCE:
    details.append({
      "error": "payroll_row_missing_derived_driver_marker",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": stub_value,
      "current_value": stub_value,
      "reason": f"Payroll row must be marked with derived_driver='{PAYROLL_DERIVATION_SOURCE}'.",
      "validation_category": "payroll_derivation",
    })
  if any(isinstance(item, dict) and str(item.get("lever_id") or "").strip() == PAYROLL_DERIVATION_LEVER_ID for item in (payload.get("controller_write_levers") or [])):
    details.append({
      "error": "payroll_lever_still_writable_catalog",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": stub_value,
      "current_value": stub_value,
      "reason": "Payroll must not remain in controller_write_levers once it becomes derived.",
      "validation_category": "payroll_derivation",
    })
  lever_catalog = payload.get("lever_catalog") if isinstance(payload.get("lever_catalog"), dict) else {}
  if isinstance(lever_catalog, dict) and PAYROLL_DERIVATION_LEVER_ID in lever_catalog:
    details.append({
      "error": "payroll_lever_still_writable_catalog",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": stub_value,
      "current_value": stub_value,
      "reason": "Payroll must not remain in lever_catalog once it becomes derived.",
      "validation_category": "payroll_derivation",
    })

  current_policy = ((payload.get("derived_driver_policies") or {}).get(PAYROLL_DERIVATION_LEVER_ID)) if isinstance(payload.get("derived_driver_policies"), dict) else {}
  current_runtime = ((payload.get("derived_driver_runtime") or {}).get(PAYROLL_DERIVATION_LEVER_ID)) if isinstance(payload.get("derived_driver_runtime"), dict) else {}
  if not isinstance(current_policy, dict) or not current_policy:
    details.append({
      "error": "payroll_derivation_policy_missing",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": stub_value,
      "current_value": stub_value,
      "reason": "Derived payroll policy metadata is missing from model_input_json.derived_driver_policies.",
      "validation_category": "payroll_derivation",
    })
  if not isinstance(current_runtime, dict) or not current_runtime:
    details.append({
      "error": "payroll_derivation_runtime_missing",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": stub_value,
      "current_value": stub_value,
      "reason": "Derived payroll runtime metadata is missing from model_input_json.derived_driver_runtime.",
      "validation_category": "payroll_derivation",
    })

  world_contract = business_world_contract if isinstance(business_world_contract, dict) else {}
  stage_ramp_contract = world_contract.get("stage_ramp_contract") if isinstance(world_contract.get("stage_ramp_contract"), dict) else {}
  stage_payroll_by_quarter: Dict[int, Dict[str, float]] = {}
  for row in _stage_ramp_grid_rows(stage_ramp_contract):
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    target = _safe_float(row.get("payroll_growth_target"))
    max_growth = _safe_float(row.get("payroll_growth_max"))
    if 1 <= quarter_index <= 20 and target is not None and max_growth is not None:
      stage_payroll_by_quarter[quarter_index] = {
        "payroll_growth_target": round(float(target), 6),
        "payroll_growth_max": round(float(max_growth), 6),
      }
  policy_growth_by_quarter: Dict[int, Dict[str, float]] = {}
  for row in list((current_policy or {}).get("payroll_growth_by_quarter") or []) if isinstance(current_policy, dict) else []:
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    target = _safe_float(row.get("payroll_growth_target"))
    max_growth = _safe_float(row.get("payroll_growth_max"))
    if 1 <= quarter_index <= 20 and target is not None and max_growth is not None:
      policy_growth_by_quarter[quarter_index] = {
        "payroll_growth_target": round(float(target), 6),
        "payroll_growth_max": round(float(max_growth), 6),
      }
  if isinstance(current_policy, dict) and str(current_policy.get("payroll_growth_source") or "").strip() != "gpt_stage_ramp_contract":
    details.append({
      "error": "payroll_growth_contract_source_missing",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": "gpt_stage_ramp_contract",
      "current_value": current_policy.get("payroll_growth_source") if isinstance(current_policy, dict) else None,
      "reason": "Payroll growth realism must come from the GPT-authored stage_ramp_contract, not a hardcoded FTE cap or fallback.",
      "validation_category": "payroll_growth_contract",
    })
  if set(policy_growth_by_quarter.keys()) != set(range(1, 21)):
    details.append({
      "error": "payroll_growth_contract_missing_full_horizon",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": list(range(1, 21)),
      "current_value": sorted(policy_growth_by_quarter.keys()),
      "reason": "Payroll growth policy must include exactly one row for every live forecast quarter Q1-Q20.",
      "validation_category": "payroll_growth_contract",
    })
  if set(stage_payroll_by_quarter.keys()) != set(range(1, 21)):
    details.append({
      "error": "payroll_growth_stage_ramp_contract_missing_full_horizon",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": list(range(1, 21)),
      "current_value": sorted(stage_payroll_by_quarter.keys()),
      "reason": "business_world_contract.stage_ramp_contract must carry payroll_growth_target/payroll_growth_max for Q1-Q20.",
      "validation_category": "payroll_growth_contract",
    })
  for quarter_index in range(1, 21):
    policy_row = policy_growth_by_quarter.get(quarter_index)
    stage_row = stage_payroll_by_quarter.get(quarter_index)
    if not isinstance(policy_row, dict) or not isinstance(stage_row, dict):
      continue
    if (
      abs(float(policy_row.get("payroll_growth_target") or 0.0) - float(stage_row.get("payroll_growth_target") or 0.0)) > 1e-6
      or abs(float(policy_row.get("payroll_growth_max") or 0.0) - float(stage_row.get("payroll_growth_max") or 0.0)) > 1e-6
    ):
      details.append({
        "error": "payroll_growth_contract_mismatch",
        "lever_id": PAYROLL_DERIVATION_LEVER_ID,
        "quarter": quarter_index,
        "previous_value": deepcopy(stage_row),
        "current_value": deepcopy(policy_row),
        "reason": "Model-input payroll growth policy must exactly mirror the GPT stage_ramp_contract payroll-growth row.",
        "validation_category": "payroll_growth_contract",
      })
      break

  expected_payload = apply_payroll_derivation_policy_to_model_input(deepcopy(payload), live_count=live_count)
  expected_row = _payroll_row_from_model_input(expected_payload)
  expected_runtime = ((expected_payload.get("derived_driver_runtime") or {}).get(PAYROLL_DERIVATION_LEVER_ID)) if isinstance(expected_payload.get("derived_driver_runtime"), dict) else {}
  expected_values = list((expected_row or {}).get("values") or [])
  if len(expected_values) >= live_count + 1 and len(current_values) >= live_count + 1:
    for quarter_index in range(1, live_count + 1):
      current_value = _safe_float(current_values[quarter_index])
      expected_value = _safe_float(expected_values[quarter_index])
      tolerance = max(1e-6, abs(float(expected_value or 0.0)) * 1e-6)
      if current_value is None or expected_value is None or abs(float(current_value) - float(expected_value)) > tolerance:
        details.append({
          "error": "payroll_values_not_fully_derived",
          "lever_id": PAYROLL_DERIVATION_LEVER_ID,
          "quarter": quarter_index,
          "previous_value": expected_value,
          "current_value": current_value,
          "reason": "Payroll forecast values must exactly match the deterministic revenue/OEWS-derived recomputation from current revenue drivers.",
          "validation_category": "payroll_derivation",
        })
        break

  current_logs = list((current_runtime or {}).get("quarter_logs") or []) if isinstance(current_runtime, dict) else []
  expected_logs = list((expected_runtime or {}).get("quarter_logs") or []) if isinstance(expected_runtime, dict) else []
  if live_count and len(current_logs) != live_count:
    details.append({
      "error": "payroll_derivation_log_count_mismatch",
      "lever_id": PAYROLL_DERIVATION_LEVER_ID,
      "quarter": 0,
      "previous_value": float(live_count),
      "current_value": float(len(current_logs)),
      "reason": "Payroll derivation runtime must log one derived record per live forecast quarter.",
      "validation_category": "payroll_derivation",
    })
  for quarter_index in range(1, min(len(current_logs), len(expected_logs)) + 1):
    current_log = current_logs[quarter_index - 1] if isinstance(current_logs[quarter_index - 1], dict) else {}
    expected_log = expected_logs[quarter_index - 1] if isinstance(expected_logs[quarter_index - 1], dict) else {}
    current_payroll = _safe_float(current_log.get("derived_payroll"))
    expected_payroll = _safe_float(expected_log.get("derived_payroll"))
    current_quarter_revenue = _safe_float(current_log.get("quarter_revenue"))
    expected_quarter_revenue = _safe_float(expected_log.get("quarter_revenue"))
    current_payroll_ratio = _safe_float(current_log.get("payroll_to_revenue"))
    expected_payroll_ratio = _safe_float(expected_log.get("payroll_to_revenue"))
    if (
      current_payroll is None
      or expected_payroll is None
      or abs(float(current_payroll) - float(expected_payroll)) > max(1e-6, abs(float(expected_payroll)) * 1e-6)
      or current_quarter_revenue is None
      or expected_quarter_revenue is None
      or abs(float(current_quarter_revenue) - float(expected_quarter_revenue)) > max(1e-6, abs(float(expected_quarter_revenue)) * 1e-6)
      or current_payroll_ratio is None
      or expected_payroll_ratio is None
      or abs(float(current_payroll_ratio) - float(expected_payroll_ratio)) > max(1e-6, abs(float(expected_payroll_ratio)) * 1e-6)
    ):
      details.append({
        "error": "payroll_derivation_log_inconsistent",
        "lever_id": PAYROLL_DERIVATION_LEVER_ID,
        "quarter": quarter_index,
        "previous_value": expected_payroll,
        "current_value": current_payroll,
        "reason": "Payroll derivation runtime log is inconsistent with the deterministic revenue/OEWS payroll recomputation.",
        "validation_category": "payroll_derivation",
      })
      break

  ratio_floor = max(0.0, _safe_float((current_policy or {}).get("payroll_ratio_floor")) or PAYROLL_RATIO_FLOOR)
  ratio_ceiling = max(ratio_floor, _safe_float((current_policy or {}).get("payroll_ratio_ceiling")) or PAYROLL_RATIO_CEILING)
  for quarter_index in range(1, len(current_logs) + 1):
    current_log = current_logs[quarter_index - 1] if isinstance(current_logs[quarter_index - 1], dict) else {}
    quarter_revenue = _safe_float(current_log.get("quarter_revenue")) or 0.0
    payroll_ratio = _safe_float(current_log.get("payroll_to_revenue"))
    if quarter_revenue > 0.0 and (payroll_ratio is None or payroll_ratio < ratio_floor or payroll_ratio > ratio_ceiling):
      details.append({
        "error": "payroll_ratio_outside_sanity_band",
        "lever_id": PAYROLL_DERIVATION_LEVER_ID,
        "quarter": quarter_index,
        "previous_value": ratio_floor,
        "current_value": payroll_ratio,
        "reason": "Revenue-derived payroll must stay within the deterministic payroll-to-revenue sanity band.",
        "validation_category": "payroll_derivation",
      })
      break

  for quarter_index in range(2, min(live_count, 20) + 1):
    growth_row = policy_growth_by_quarter.get(quarter_index) or {}
    allowed_growth = _safe_float(growth_row.get("payroll_growth_max"))
    if allowed_growth is None:
      continue
    previous_value = _safe_float(current_values[quarter_index - 1] if len(current_values) > quarter_index - 1 else None)
    current_value = _safe_float(current_values[quarter_index] if len(current_values) > quarter_index else None)
    if previous_value is None or current_value is None or previous_value <= 0.0:
      continue
    actual_growth = (float(current_value) - float(previous_value)) / max(abs(float(previous_value)), 1e-9)
    if actual_growth > float(allowed_growth) + 0.000001:
      details.append({
        "error": "payroll_growth_exceeds_gpt_stage_ramp_contract",
        "lever_id": PAYROLL_DERIVATION_LEVER_ID,
        "quarter": quarter_index,
        "previous_value": round(float(allowed_growth), 6),
        "current_value": round(float(actual_growth), 6),
        "reason": "Payroll growth may not exceed payroll_growth_max from the GPT-authored stage_ramp_contract.",
        "validation_category": "payroll_growth_contract",
      })
      break

  return {
    "status": "failed" if details else "passed",
    "details": deepcopy(details),
    "current_policy": deepcopy(current_policy) if isinstance(current_policy, dict) else {},
    "current_runtime": deepcopy(current_runtime) if isinstance(current_runtime, dict) else {},
    "expected_runtime": deepcopy(expected_runtime) if isinstance(expected_runtime, dict) else {},
  }
