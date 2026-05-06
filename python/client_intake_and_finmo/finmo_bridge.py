from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
  from financial_model_engine.finmo_model import calculate_finmo_model
  from financial_model_engine.model_inputs import FinancialModelInputs
except Exception:
  import sys

  ROOT = Path(__file__).resolve().parents[1]
  if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
  from financial_model_engine.finmo_model import calculate_finmo_model
  from financial_model_engine.model_inputs import FinancialModelInputs

from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
  PAYROLL_HEADCOUNT_LEVER_ID as _PAYROLL_HEADCOUNT_LEVER_ID,
  PAYROLL_HEADCOUNT_SOURCE as _PAYROLL_HEADCOUNT_SOURCE,
  apply_payroll_headcount_policy_to_model_input,
  default_payroll_headcount_policy,
)
from client_intake_and_finmo.post_intake_driver_formulas import apply_seed_formula  # type: ignore
from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
  baseline_seed_provenance,
  post_intake_baseline_applicability_for_naics2,
  post_intake_industry_baseline_for_naics,
)


DEBT_ISSUANCE_LABEL = "Debt Issuance (New Borrowing)"
DEBT_REPAYMENT_LABEL = "Debt Repayment (Scheduled)"
LEGACY_NET_DEBT_LABEL = "Plus: Additions (repayments), net"
R_AND_D_APPLICABILITY_LEVER_ID = "expenses::Research & Development"
R_AND_D_APPLICABILITY_POLICY_VERSION = "r_and_d_applicability_pre_forecast_v1"
BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY = "balance_sheet_contextual_seed"
ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _column_letter(column_index: Any) -> str:
  index = int(column_index or 0)
  if index <= 0:
    return ""
  letters = ""
  while index > 0:
    index, remainder = divmod(index - 1, 26)
    letters = chr(65 + remainder) + letters
  return letters


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


def _annualized_lease_commitment(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  if isinstance(value, (int, float)):
    return max(0.0, float(value)) * 12.0
  raw = str(value).strip()
  if not raw:
    return None
  lowered = raw.lower()
  if lowered in {"0", "0,none", "none", "no", "n/a", "na", "zero"}:
    return 0.0

  amount_part = raw
  period_part = ""
  if "," in raw:
    pieces = [piece.strip() for piece in raw.split(",")]
    if pieces:
      amount_part = pieces[0]
    if len(pieces) > 1:
      period_part = pieces[1].lower()

  amount = _safe_float(amount_part)
  if amount is None:
    return None
  amount = max(0.0, amount)
  if not period_part:
    return amount * 12.0
  if period_part == "annual":
    period_part = "yearly"
  multiplier = {
    "daily": 365.0,
    "weekly": 52.0,
    "monthly": 12.0,
    "quarterly": 4.0,
    "yearly": 1.0,
    "one-time": 1.0,
    "unknown": 1.0,
    "none": 0.0,
  }.get(period_part)
  if multiplier is None:
    return amount
  return round(amount * multiplier, 6)


def _safe_int(value: Any) -> int:
  if value is None or value == "":
    return 0
  try:
    return int(float(value))
  except Exception:
    return 0


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _as_iso_date(value: Any) -> Optional[str]:
  if value is None or value == "":
    return None
  if isinstance(value, datetime):
    return value.date().isoformat()
  if isinstance(value, str):
    cleaned = value.strip()
    if not cleaned:
      return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
      try:
        return datetime.strptime(cleaned, fmt).date().isoformat()
      except Exception:
        continue
    return cleaned
  numeric = _safe_float(value)
  if numeric is None:
    return None
  return None


def _forecast_anchor_date_iso(*, now: Optional[datetime] = None) -> str:
  current = now or datetime.now()
  return current.date().isoformat()


def _ratio(numerator: Any, denominator: Any) -> float:
  num = _safe_float(numerator) or 0.0
  den = _safe_float(denominator) or 0.0
  if abs(den) < 1e-9:
    return 0.0
  return num / den


def _clone(value: Any) -> Any:
  return deepcopy(value)


def _canonical_model_input_text(value: Any) -> str:
  return str(value or "").strip()


def _revenue_lever_id(lob: Any, product: Any, driver: Any) -> str:
  return "::".join(
    [
      "revenue",
      _canonical_model_input_text(lob),
      _canonical_model_input_text(product),
      _canonical_model_input_text(driver),
    ]
  )


def _simple_lever_id(section: str, label: Any) -> str:
  return "::".join([section, _canonical_model_input_text(label)])


def _mapping_formula_contract_for_lever(lever_id: Any) -> Optional[Dict[str, Any]]:
  try:
    from client_intake_and_finmo.post_intake_mapping import post_intake_driver_formula_contract  # type: ignore

    contract = post_intake_driver_formula_contract(lever_id, required=False)
  except Exception:
    return None
  return contract if isinstance(contract, dict) else None


def _business_text_has_any(payload: Dict[str, Any], tokens: Sequence[str]) -> bool:
  try:
    text = json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False).lower()
  except Exception:
    text = str(payload or "").lower()
  return any(str(token or "").lower() in text for token in tokens)


def _mapping_applicability_tokens_for_lever(
  lever_id: str,
  token_kind: str,
) -> Sequence[str]:
  contract = _mapping_formula_contract_for_lever(lever_id)
  if not isinstance(contract, dict):
    return ()
  raw = contract.get(token_kind)
  if not isinstance(raw, list):
    return ()
  return tuple(str(item or "").strip().lower() for item in raw if str(item or "").strip())


def _deferred_revenue_applicable(ops_json: Dict[str, Any], financials_json: Dict[str, Any]) -> bool:
  tokens = _mapping_applicability_tokens_for_lever(
    "balance_sheet::Deferred Revenue (% of Revenue)",
    "applicability_positive_tokens",
  )
  return _business_text_has_any(ops_json or {}, tokens) or _business_text_has_any(financials_json or {}, tokens)


def _inventory_driver_applicable(ops_json: Dict[str, Any], financials_json: Dict[str, Any]) -> bool:
  if max(0.0, _safe_float((financials_json or {}).get("inventory_balance")) or 0.0) > 0.0:
    return True
  positive_tokens = _mapping_applicability_tokens_for_lever(
    "balance_sheet::Inventory Days",
    "applicability_positive_tokens",
  )
  negative_tokens = _mapping_applicability_tokens_for_lever(
    "balance_sheet::Inventory Days",
    "applicability_negative_tokens",
  )
  if _business_text_has_any(ops_json or {}, negative_tokens) or _business_text_has_any(financials_json or {}, negative_tokens):
    return False
  return _business_text_has_any(ops_json or {}, positive_tokens) or _business_text_has_any(financials_json or {}, positive_tokens)


def _full_quarter_scope(slots: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
  full_slots = _full_quarter_slots(slots)
  valid_quarter_indices = list(range(1, len(full_slots) + 1))
  valid_period_columns = [str(slot.get("column_letter") or "").strip() for slot in full_slots if str(slot.get("column_letter") or "").strip()]
  return {
    "valid_quarter_indices": valid_quarter_indices,
    "valid_period_columns": valid_period_columns,
    "total_period_count": len([slot for slot in (slots or []) if isinstance(slot, dict)]) or len(full_slots),
    "writable_full_quarters_only": True,
  }


def _revenue_input_semantics(driver: str) -> Dict[str, str]:
  driver_text = _canonical_model_input_text(driver).lower()
  contract = _mapping_formula_contract_for_lever(f"revenue::*::*::{_canonical_model_input_text(driver)}")
  if isinstance(contract, dict):
    value_kind = str(contract.get("value_kind") or "").strip()
    input_semantics = str(contract.get("input_semantics") or "").strip()
    if value_kind and input_semantics:
      return {"value_kind": value_kind, "input_semantics": input_semantics}
  if driver_text == "capacity":
    return {"value_kind": "direct_number", "input_semantics": "quarter_capacity_units"}
  if driver_text == "unit price":
    return {"value_kind": "direct_number", "input_semantics": "currency_per_unit"}
  if driver_text == "utilization":
    return {"value_kind": "ratio", "input_semantics": "utilization_ratio"}
  return {"value_kind": "direct_number", "input_semantics": "direct_input"}


def _simple_input_semantics(section_key: str, label: str) -> Dict[str, str]:
  contract = _mapping_formula_contract_for_lever(_simple_lever_id(section_key, label))
  if isinstance(contract, dict):
    value_kind = str(contract.get("value_kind") or "").strip()
    input_semantics = str(contract.get("input_semantics") or "").strip()
    if value_kind and input_semantics:
      return {"value_kind": value_kind, "input_semantics": input_semantics}
  normalized_section = _canonical_model_input_text(section_key).lower()
  normalized_label = _canonical_model_input_text(label).lower()
  if normalized_section == "expenses":
    if normalized_label in {
      "cost of goods sold",
      "marketing",
      "research & development",
      "general & administrative",
      "interest rate",
      "taxes",
    }:
      return {"value_kind": "ratio", "input_semantics": "percent_of_revenue"}
    if normalized_label == "depreciation":
      return {"value_kind": "ratio", "input_semantics": "percent_of_prior_ppe"}
    if normalized_label in {"lease", "payroll"}:
      return {"value_kind": "direct_number", "input_semantics": "quarter_currency"}
  if normalized_section == "balance_sheet":
    if normalized_label in {"accounts receivable days", "inventory days", "accounts payable days"}:
      return {"value_kind": "day_count", "input_semantics": "days"}
    if normalized_label in {
      "prepaid expenses (% of revenue)",
      "deferred revenue (% of revenue)",
    }:
      return {"value_kind": "ratio", "input_semantics": "percent_of_revenue"}
    if normalized_label == "short term debt (% of ltd)":
      return {"value_kind": "ratio", "input_semantics": "percent_of_long_term_debt"}
    if normalized_label in {"owner's capital", "other equity"}:
      return {"value_kind": "direct_number", "input_semantics": "quarter_currency"}
  if normalized_section == "schedules":
    if normalized_label == "debt issuance (new borrowing)":
      return {"value_kind": "direct_number", "input_semantics": "debt_new_borrowing"}
    if normalized_label == "debt repayment (scheduled)":
      return {"value_kind": "direct_number", "input_semantics": "debt_scheduled_repayment"}
    if normalized_label == "capital expenditures":
      return {"value_kind": "direct_number", "input_semantics": "capital_expenditures_cash"}
    if normalized_label == "less: principal repayments":
      return {"value_kind": "direct_number", "input_semantics": "capital_lease_principal_repayments"}
    if normalized_label == "plus: net additions":
      return {"value_kind": "direct_number", "input_semantics": "capital_lease_additions_noncash"}
    return {"value_kind": "direct_number", "input_semantics": "quarter_currency"}
  return {"value_kind": "direct_number", "input_semantics": "direct_input"}


def _safe_ratio(value: Any) -> Optional[float]:
  ratio = _safe_float(value)
  if ratio is None:
    return None
  if ratio > 1.0 and ratio <= 100.0:
    ratio = ratio / 100.0
  return ratio


def _naics_6_from_ops(ops_json: Any) -> Optional[str]:
  if not isinstance(ops_json, dict):
    return None
  digits = re.sub(r"[^0-9]", "", str(ops_json.get("business_naics_6") or "").strip())
  return digits or None


def _attach_seed_provenance(row: Dict[str, Any], payload: Dict[str, Any]) -> None:
  """Stamp a model_input row with the NAICS-cascade provenance metadata so the
  workbook + Module 3 finalize gate can surface it. No-op when payload has no
  trust_flag (caller supplied something unresolved).
  """
  if not isinstance(row, dict) or not isinstance(payload, dict):
    return
  if not payload.get("trust_flag"):
    return
  prov = baseline_seed_provenance(payload)
  bucket = row.setdefault("seed_provenance_json", {})
  if isinstance(bucket, dict):
    metric_key = str(prov.get("metric_key") or "").strip()
    if metric_key:
      bucket[metric_key] = prov


def _cogs_ratio_from_financials(financials: Optional[Dict[str, Any]], revenue_total_year1: Any) -> float:
  """Return the intake-derived COGS ratio. Returns 0.0 when intake omitted COGS;
  the caller is responsible for any NAICS-cascade forecast substitution
  (Module 1 Task 1.3) so stub 0 (= intake fact) stays at the intake value
  while forecast Q1-Q20 can use a NAICS substitute.
  """
  payload = financials if isinstance(financials, dict) else {}
  for key in ("cogs_percent_of_revenue", "cogs_percent", "estimated_cogs_percent"):
    explicit_ratio = _safe_ratio(payload.get(key))
    if explicit_ratio is not None and explicit_ratio > 0.0:
      return max(0.0, float(explicit_ratio))
  cogs_value = (
    _safe_float(payload.get("cogs_total_year1"))
    if payload.get("cogs_total_year1") is not None
    else _safe_float(payload.get("current_cogs"))
  )
  if cogs_value is None or cogs_value <= 0.0:
    return 0.0
  revenue = _safe_float(revenue_total_year1) or 0.0
  direct_ratio = _ratio(cogs_value, revenue)
  if 1.0 < cogs_value <= 100.0 and direct_ratio < 0.05:
    return cogs_value / 100.0
  return max(0.0, direct_ratio)


def _naics_substitute_ratio(
  metric_key: str,
  naics_6: Optional[str],
  *,
  applicability_naics_2: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
  """Resolve a NAICS-typical ratio for forecast substitution.

  Returns the resolver payload when a non-zero `benchmark_target` is found
  AND (if applicability_naics_2 is provided) the metric is applicable for
  that sector. Returns None to signal "leave the silent zero in place"
  (legitimate zero per Part 9.1) when:
   - naics_6 is missing
   - the resolver returns no_coverage / zero target
   - the applicability check rejects the metric for the sector
  """
  if not naics_6:
    return None
  if applicability_naics_2:
    gate = post_intake_baseline_applicability_for_naics2(
      metric_key=metric_key, naics_2=applicability_naics_2
    )
    if not gate.get("applicable"):
      return None
  try:
    band = post_intake_industry_baseline_for_naics(metric_key=metric_key, naics_6=naics_6)
  except Exception:
    return None
  if not band or band.get("benchmark_target") is None:
    return None
  target = float(band["benchmark_target"])
  if target <= 0.0:
    return None
  return band


def _placeholder_index(value: Any, prefix: str) -> Optional[int]:
  match = re.search(rf"{re.escape(prefix)}\s*(\d+)", str(value or "").strip(), re.IGNORECASE)
  if not match:
    return None
  try:
    return max(0, int(match.group(1)) - 1)
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


_BALANCE_SHEET_STUB_CONTINUITY_EXCLUDED_LABELS = {
  # Aggregate/check rows are allowed to move based on their components. The
  # continuity contract applies to actual balance-sheet lines.
  "Current Assets",
  "Current Liabilites",
  "Total Assets",
  "Total Liabilities",
  "Total Equity",
  "Total Liabilities & Equity",
  # Debt may be intentionally amortized to zero through scheduled repayments;
  # that is not the same class as AR / inventory / AP disappearing because the
  # driver row was left empty.
  "Long Term Debt",
  "Short Term Debt",
}

_BALANCE_SHEET_STOCK_LEVEL_LABELS = {
  "Owner's Capital",
  "Other Equity",
}


def _enforce_balance_sheet_stock_level_carryforward(
  model_input_json: Dict[str, Any],
  *,
  live_count: int,
) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  normalized_live_count = max(0, int(live_count or 0))
  if normalized_live_count <= 0:
    return payload
  for row in balance_rows:
    label = str(row.get("label") or "").strip()
    if label not in _BALANCE_SHEET_STOCK_LEVEL_LABELS:
      continue
    stub_value, live_values = _row_stub_and_live_values(
      row.get("values") or [],
      live_count=normalized_live_count,
    )
    carry_value = max(0.0, round(float(stub_value or 0.0), 6))
    normalized_live_values: List[float] = []
    adjusted_quarters: List[int] = []
    for quarter_index, raw_value in enumerate(live_values, start=1):
      current_value = max(0.0, round(_safe_float(raw_value) or 0.0, 6))
      if carry_value > 1e-6 and current_value <= 1e-6:
        current_value = carry_value
        adjusted_quarters.append(quarter_index)
      elif current_value + 1e-6 < carry_value:
        current_value = carry_value
        adjusted_quarters.append(quarter_index)
      carry_value = max(carry_value, current_value)
      normalized_live_values.append(round(current_value, 6))
    row["values"] = _compose_period_values(
      stub_value=stub_value,
      live_values=normalized_live_values,
    )
    if adjusted_quarters:
      row["balance_sheet_stock_carryforward"] = {
        "source": "deterministic_balance_sheet_stock_level_carryforward",
        "reason": "Opening and contributed equity are balance-sheet stock levels; distributions are modeled separately.",
        "adjusted_quarters": adjusted_quarters,
      }
  return payload


def _enforce_balance_sheet_stub_continuity(
  balance_rows: Sequence[Dict[str, Any]],
  *,
  dependency_series_by_label: Optional[Dict[str, Sequence[Any]]] = None,
) -> None:
  dependencies = dependency_series_by_label if isinstance(dependency_series_by_label, dict) else {}
  violations: List[Dict[str, Any]] = []
  for row in balance_rows or []:
    if not isinstance(row, dict):
      continue
    label = str(row.get("label") or "").strip()
    if not label or label in _BALANCE_SHEET_STUB_CONTINUITY_EXCLUDED_LABELS:
      continue
    values = list(row.get("values") or [])
    if len(values) <= 1:
      continue
    stub_value = round(_safe_float(values[0]) or 0.0, 6)
    if abs(stub_value) <= 1e-6:
      continue
    dependency_series = list(dependencies.get(label) or [])
    if dependency_series and all(abs(round(_safe_float(value) or 0.0, 6)) <= 1e-6 for value in dependency_series):
      continue
    empty_live_quarters = [
      idx
      for idx, value in enumerate(values[1:], start=1)
      if abs(round(_safe_float(value) or 0.0, 6)) <= 1e-6
    ]
    if empty_live_quarters:
      violations.append(
        {
          "label": label,
          "stub_value": stub_value,
          "empty_live_quarters": empty_live_quarters,
          "first_empty_quarter": empty_live_quarters[0],
        }
      )
  if violations:
    raise ValueError(
      "balance_sheet_stub_continuity_failed: nonzero stub/opening balance-sheet lines must not become empty in live forecast periods. "
      + json.dumps({"violations": violations}, ensure_ascii=False)
    )


def _enforce_revenue_driver_formula_contract(
  *,
  model_input_json: Dict[str, Any],
  quarter_rows_raw: Sequence[Dict[str, Any]],
) -> None:
  live_rows = [row for row in (quarter_rows_raw or []) if isinstance(row, dict)]
  driver_revenue_series = _revenue_live_series_from_model_input(
    model_input_json,
    live_count=len(live_rows),
  )
  violations: List[Dict[str, Any]] = []
  for idx, row in enumerate(live_rows, start=1):
    finmo_revenue = float(_safe_float(row.get("revenue")) or 0.0)
    driver_revenue = float(driver_revenue_series[idx - 1]) if idx - 1 < len(driver_revenue_series) else 0.0
    if int(round(finmo_revenue)) != int(round(driver_revenue)):
      violations.append(
        {
          "quarter_index": idx,
          "finmo_revenue": int(round(finmo_revenue)),
          "driver_formula_revenue": int(round(driver_revenue)),
          "delta": int(round(finmo_revenue - driver_revenue)),
          "formula": "sum(Capacity * Unit Price * Utilization) across revenue products",
        }
      )
  if violations:
    raise ValueError(
      "revenue_driver_formula_contract_failed: FINMO revenue must equal model-input revenue drivers for every live quarter. "
      + json.dumps({"violations": violations}, ensure_ascii=False)
    )


def _named_lob(value: Any, fallback: str) -> str:
  text = _canonical_model_input_text(value)
  return text or fallback


def _named_product(value: Any, fallback: str) -> str:
  text = _canonical_model_input_text(value)
  return text or fallback


def build_python_finmo_json(
  *,
  model_input_json: Dict[str, Any],
  finmo_path: Optional[str] = None,
) -> Dict[str, Any]:
  normalized_model_input = apply_derived_driver_policies_to_model_input(
    model_input_json if isinstance(model_input_json, dict) else {}
  )
  book = FinancialModelInputs.from_model_input_json(normalized_model_input)
  result = calculate_finmo_model(book)
  quarter_rows_raw = result.quarter_rows()
  _enforce_revenue_driver_formula_contract(
    model_input_json=normalized_model_input,
    quarter_rows_raw=quarter_rows_raw,
  )
  quarter_rows_with_stub = result.quarter_rows(include_stub=True)
  first_live_row = next((row for row in quarter_rows_raw if isinstance(row, dict)), None)
  quarter_rows_with_stub = _apply_operating_stub_to_quarter_rows(
    quarter_rows_with_stub,
    model_input_json=normalized_model_input,
    first_live_row=first_live_row,
  )
  raw_periods = [
    _clone(item)
    for item in (((normalized_model_input.get("periods") or []) if isinstance(normalized_model_input, dict) else []) or [])
    if isinstance(item, dict)
  ]
  periods: List[Dict[str, Any]] = []
  start_date_iso = _as_iso_date((normalized_model_input or {}).get("start_date")) if isinstance(normalized_model_input, dict) else None
  if raw_periods:
    has_stub_period = any(_safe_float(item.get("quarter")) == 0.0 for item in raw_periods)
    if has_stub_period:
      periods = [
        {
          "slot_index": int(_safe_float(item.get("slot_index")) or idx),
          "column_index": int(_safe_float(item.get("column_index")) or (7 + idx)),
          "column_letter": str(item.get("column_letter") or _column_letter(int(_safe_float(item.get("column_index")) or (7 + idx)))).strip(),
          "year": item.get("year"),
          "quarter": item.get("quarter"),
          "date": item.get("date"),
          "is_stub": bool(item.get("is_stub")) or _safe_float(item.get("quarter")) == 0.0,
        }
        for idx, item in enumerate(raw_periods)
      ]
    else:
      opening_year = _safe_float(raw_periods[0].get("year"))
      if opening_year is None and start_date_iso:
        try:
          opening_year = float(datetime.fromisoformat(start_date_iso).year)
        except Exception:
          opening_year = None
      periods.append(
        {
          "slot_index": 0,
          "column_index": 7,
          "column_letter": "G",
          "year": opening_year,
          "quarter": 0.0,
          "date": start_date_iso or raw_periods[0].get("date"),
          "is_stub": True,
        }
      )
      for idx, item in enumerate(raw_periods, start=1):
        periods.append(
          {
            "slot_index": idx,
            "column_index": 7 + idx,
            "column_letter": _column_letter(7 + idx),
            "year": item.get("year"),
            "quarter": item.get("quarter"),
            "date": item.get("date"),
            "is_stub": False,
          }
        )
  else:
    opening_date = start_date_iso
    opening_year = None
    if opening_date:
      try:
        opening_year = float(datetime.fromisoformat(opening_date).year)
      except Exception:
        opening_year = None
    periods = [
      {
        "slot_index": 0,
        "column_index": 7,
        "column_letter": "G",
        "year": opening_year,
        "quarter": 0.0,
        "date": opening_date,
        "is_stub": True,
      }
    ]
    for idx, row in enumerate(quarter_rows_raw, start=1):
      if not isinstance(row, dict):
        continue
      periods.append(
        {
          "slot_index": idx,
          "column_index": 7 + idx,
          "column_letter": _column_letter(7 + idx),
          "year": row.get("year"),
          "quarter": row.get("quarter"),
          "date": row.get("date"),
          "is_stub": False,
        }
      )

  def _series(metric_key: str, *, include_stub: bool = False) -> List[float]:
    values: List[float] = []
    source_rows = quarter_rows_with_stub if include_stub else quarter_rows_raw
    for row in source_rows:
      if not isinstance(row, dict):
        continue
      values.append(round(_safe_float(row.get(metric_key)) or 0.0, 6))
    return values

  pl_rows = [
    {"label": "Revenue", "values": _series("revenue", include_stub=True)},
    {"label": "Cost of Goods Sold", "values": _series("cost_of_goods_sold", include_stub=True)},
    {"label": "Gross Profit", "values": _series("gross_profit", include_stub=True)},
    {"label": "Marketing", "values": _series("marketing", include_stub=True)},
    {"label": "Research & Development", "values": _series("research_and_development", include_stub=True)},
    {"label": "Lease/Rent", "values": _series("lease_rent", include_stub=True)},
    {"label": "Payroll", "values": _series("payroll", include_stub=True)},
    {"label": "General & Administrative", "values": _series("general_and_administrative", include_stub=True)},
    {"label": "EBITDA", "values": _series("ebitda", include_stub=True)},
    {"label": "Interest", "values": _series("interest", include_stub=True)},
    {"label": "Depreciation", "values": _series("depreciation", include_stub=True)},
    {"label": "Taxes", "values": _series("taxes", include_stub=True)},
    {"label": "Net Income", "values": _series("net_income", include_stub=True)},
  ]
  balance_rows = [
    {"label": "Cash", "values": _series("cash", include_stub=True)},
    {"label": "Accounts Receivable", "values": _series("accounts_receivable", include_stub=True)},
    {"label": "Inventory", "values": _series("inventory", include_stub=True)},
    {"label": "Current Assets", "values": _series("current_assets", include_stub=True)},
    {"label": "PPE", "values": _series("ppe", include_stub=True)},
    {"label": "Accumulated Depreciation", "values": _series("accumulated_depreciation", include_stub=True)},
    {"label": "Total Assets", "values": _series("total_assets", include_stub=True)},
    {"label": "Accounts Payable", "values": _series("accounts_payable", include_stub=True)},
    {"label": "Prepaid Expenses (% of Revenue)", "values": _series("prepaid_expenses", include_stub=True)},
    {"label": "Short Term Debt", "values": _series("short_term_debt", include_stub=True)},
    {"label": "Deferred Revenue (% of Revenue)", "values": _series("deferred_revenue", include_stub=True)},
    {"label": "Current Liabilites", "values": _series("current_liabilities", include_stub=True)},
    {"label": "Long Term Debt", "values": _series("long_term_debt", include_stub=True)},
    {"label": "Total Liabilities", "values": _series("total_liabilities", include_stub=True)},
    {"label": "Owner's Capital", "values": _series("owners_capital", include_stub=True)},
    {"label": "Retained Earnings", "values": _series("retained_earnings", include_stub=True)},
    {"label": "Other Equity", "values": _series("other_equity", include_stub=True)},
    {"label": "Total Equity", "values": _series("total_equity", include_stub=True)},
    {"label": "Total Liabilities & Equity", "values": _series("total_liabilities_and_equity", include_stub=True)},
  ]
  _enforce_balance_sheet_stub_continuity(
    balance_rows,
    dependency_series_by_label={
      "Accounts Receivable": _series("revenue"),
      "Inventory": _series("cost_of_goods_sold"),
      "Accounts Payable": [
        (
          (_safe_float(row.get("marketing")) or 0.0)
          + (_safe_float(row.get("research_and_development")) or 0.0)
          + (_safe_float(row.get("lease_rent")) or 0.0)
          + (_safe_float(row.get("payroll")) or 0.0)
          + (_safe_float(row.get("general_and_administrative")) or 0.0)
        )
        for row in quarter_rows_raw
        if isinstance(row, dict)
      ],
    },
  )
  cfs_rows = [
    {"label": "Beginning Cash", "values": _series("beginning_cash", include_stub=True)},
    {"label": "Net Income", "values": _series("net_income", include_stub=True)},
    {"label": "Depreciatoin", "values": _series("depreciation", include_stub=True)},
    {"label": "Changes in Current Assets", "values": _series("changes_in_current_assets", include_stub=True)},
    {"label": "Changes in Current Liabilites", "values": _series("changes_in_current_liabilities", include_stub=True)},
    {"label": "Operating Cash Flow", "values": _series("operating_cash_flow", include_stub=True)},
    {"label": "Capital Expenditures", "values": _series("capital_expenditures", include_stub=True)},
    {"label": "Investing Cash Flow", "values": _series("investing_cash_flow", include_stub=True)},
    {"label": "Debt Issuance (New Borrowing)", "values": _series("debt_issuance", include_stub=True)},
    {"label": "Debt Repayment", "values": [round(-(abs(_safe_float(value)) or 0.0), 6) for value in _series("debt_repayment", include_stub=True)]},
    {"label": "Equity", "values": _series("equity", include_stub=True)},
    {"label": "Distributions", "values": _series("owner_distributions", include_stub=True)},
    {"label": "Financing Cash Flow", "values": _series("financing_cash_flow", include_stub=True)},
    {"label": "Net Cash Flow", "values": _series("net_cash_flow", include_stub=True)},
    {"label": "Ending Cash", "values": _series("ending_cash", include_stub=True)},
  ]
  numeric_values = _series("accounting_equation_check", include_stub=True)
  tolerance = 1.0
  status_values = ["OK" if abs(value) <= tolerance else "FAIL" for value in numeric_values]
  quarter_rows: List[Dict[str, Any]] = []
  for idx, row in enumerate(quarter_rows_with_stub):
    if not isinstance(row, dict):
      continue
    quarter_payload = deepcopy(row)
    quarter_payload.update(
      {
        "slot_index": idx,
        "quarter_index": int(row.get("quarter_index") or idx),
        "year": row.get("year"),
        "quarter": row.get("quarter"),
        "date": row.get("date"),
        "cogs": row.get("cost_of_goods_sold"),
        "g_and_a": row.get("general_and_administrative"),
      }
    )
    if "owner_distributions" in row and "distributions" not in quarter_payload:
      quarter_payload["distributions"] = row.get("owner_distributions")
    if "cash" in row and "ending_cash" not in quarter_payload:
      quarter_payload["ending_cash"] = row.get("cash")
    quarter_rows.append(
      quarter_payload
    )

  return {
    "contract_version": "finmo_output_v1",
    "finmo_path": str(finmo_path or "").strip(),
    "periods": periods,
    "accounting_check": {
      "rows": [
        {"label": "Check", "values": status_values},
        {"label": "Accounting Equation Check", "values": numeric_values},
      ],
      "all_ok": all(item == "OK" for item in status_values),
      "status_values": status_values,
      "numeric_values": numeric_values,
    },
    "pl": pl_rows,
    "balance_sheet": balance_rows,
    "cash_flow": cfs_rows,
    "quarter_rows": quarter_rows,
  }


def build_forecast_view_from_finmo(finmo_json: Dict[str, Any]) -> Dict[str, Any]:
  finmo_obj = finmo_json if isinstance(finmo_json, dict) else {}
  raw_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  full_quarters = [
    row for row in raw_rows
    if _safe_float(row.get("quarter")) not in (None, 0.0)
  ]
  if not full_quarters:
    full_quarters = raw_rows
  full_quarters = full_quarters[:20]

  quarter_view: List[Dict[str, Any]] = []
  for idx, row in enumerate(full_quarters, start=1):
    r_and_d = _safe_float(row.get("research_and_development")) or 0.0
    lease_rent = _safe_float(row.get("lease_rent")) or 0.0
    g_and_a = _safe_float(row.get("g_and_a")) or 0.0
    quarter_view.append(
      {
        "quarter_index": idx,
        "period_label": f"Year {((idx - 1) // 4) + 1} Q{((idx - 1) % 4) + 1}",
        "year": _safe_float(row.get("year")),
        "quarter": _safe_float(row.get("quarter")),
        "date": row.get("date"),
        "revenue": _safe_float(row.get("revenue")) or 0.0,
        "cogs": _safe_float(row.get("cogs")) or 0.0,
        "gross_profit": _safe_float(row.get("gross_profit")) or 0.0,
        "marketing": _safe_float(row.get("marketing")) or 0.0,
        "research_and_development": r_and_d,
        "lease_rent": lease_rent,
        "payroll": _safe_float(row.get("payroll")) or 0.0,
        "g_and_a": g_and_a,
        "opex": round(r_and_d + lease_rent + g_and_a, 6),
        "ebitda": _safe_float(row.get("ebitda")) or 0.0,
        "interest": _safe_float(row.get("interest")) or 0.0,
        "depreciation": _safe_float(row.get("depreciation")) or 0.0,
        "taxes": _safe_float(row.get("taxes")) or 0.0,
        "net_income": _safe_float(row.get("net_income")) or 0.0,
        "cash": _safe_float(row.get("cash")) or 0.0,
        "ending_cash": _safe_float(row.get("ending_cash")) or 0.0,
        "total_assets": _safe_float(row.get("total_assets")) or 0.0,
        "total_liabilities_and_equity": _safe_float(row.get("total_liabilities_and_equity")) or 0.0,
        "source_level": "finmo",
      }
    )

  forecast_years: List[Dict[str, Any]] = []
  for year_index in range(0, len(quarter_view), 4):
    year_quarters = quarter_view[year_index:year_index + 4]
    if not year_quarters:
      continue
    year_number = (year_index // 4) + 1
    forecast_years.append(
      {
        "year_index": year_number,
        "period_label": f"Year {year_number}",
        "revenue": round(sum(_safe_float(item.get("revenue")) or 0.0 for item in year_quarters), 2),
        "cogs": round(sum(_safe_float(item.get("cogs")) or 0.0 for item in year_quarters), 2),
        "gross_profit": round(sum(_safe_float(item.get("gross_profit")) or 0.0 for item in year_quarters), 2),
        "marketing": round(sum(_safe_float(item.get("marketing")) or 0.0 for item in year_quarters), 2),
        "payroll": round(sum(_safe_float(item.get("payroll")) or 0.0 for item in year_quarters), 2),
        "opex": round(sum(_safe_float(item.get("opex")) or 0.0 for item in year_quarters), 2),
        "ebitda": round(sum(_safe_float(item.get("ebitda")) or 0.0 for item in year_quarters), 2),
        "interest": round(sum(_safe_float(item.get("interest")) or 0.0 for item in year_quarters), 2),
        "depreciation": round(sum(_safe_float(item.get("depreciation")) or 0.0 for item in year_quarters), 2),
        "taxes": round(sum(_safe_float(item.get("taxes")) or 0.0 for item in year_quarters), 2),
        "net_income": round(sum(_safe_float(item.get("net_income")) or 0.0 for item in year_quarters), 2),
        "cash": _safe_float((year_quarters[-1] or {}).get("cash")) or 0.0,
        "ending_cash": _safe_float((year_quarters[-1] or {}).get("ending_cash")) or 0.0,
        "source_level": "finmo",
      }
    )

  return {
    "quarter_driver_path": quarter_view,
    "forecast_years": forecast_years,
  }


def _slot_quarters(period_count: int, forecast_quarters: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  quarters = [item for item in (forecast_quarters or []) if isinstance(item, dict)]
  if period_count <= 0:
    return []
  if not quarters:
    return [{} for _ in range(period_count)]
  slots: List[Dict[str, Any]] = [_clone(quarters[0])]
  for idx in range(1, period_count):
    source_idx = min(idx - 1, len(quarters) - 1)
    slots.append(_clone(quarters[source_idx]))
  return slots[:period_count]


def _full_quarter_slots(slots: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  full_slots = [
    _clone(slot) for slot in (slots or [])
    if isinstance(slot, dict) and _safe_float(slot.get("quarter")) not in (None, 0.0)
  ]
  return full_slots if full_slots else [_clone(slot) for slot in (slots or []) if isinstance(slot, dict)]


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
  return [round(_safe_float(stub_value) or 0.0, 6), *[round(_safe_float(item) or 0.0, 6) for item in (live_values or [])]]


def _normalized_r_and_d_applicability_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
  policies = payload.get("derived_driver_policies") if isinstance(payload.get("derived_driver_policies"), dict) else {}
  raw_policy = (
    policies.get(R_AND_D_APPLICABILITY_LEVER_ID)
    if isinstance(policies.get(R_AND_D_APPLICABILITY_LEVER_ID), dict)
    else {}
  )
  if not isinstance(raw_policy, dict):
    raw_policy = {}
  enabled_raw = raw_policy.get("r_and_d_enabled")
  enabled = bool(enabled_raw) if isinstance(enabled_raw, bool) else True
  return {
    "policy_version": str(raw_policy.get("policy_version") or R_AND_D_APPLICABILITY_POLICY_VERSION).strip(),
    "decision_source": str(raw_policy.get("decision_source") or "default_enabled").strip(),
    "r_and_d_enabled": enabled,
    "rationale": str(raw_policy.get("rationale") or "").strip(),
  }


def apply_r_and_d_applicability_policy_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  *,
  r_and_d_enabled: bool,
  decision_source: str = "gpt_pre_forecast",
  rationale: str = "",
) -> Dict[str, Any]:
  next_payload = _clone(model_input_json if isinstance(model_input_json, dict) else {})
  next_payload.setdefault("derived_driver_policies", {})
  policies = next_payload.get("derived_driver_policies")
  if isinstance(policies, dict):
    policies[R_AND_D_APPLICABILITY_LEVER_ID] = {
      "policy_version": R_AND_D_APPLICABILITY_POLICY_VERSION,
      "decision_source": str(decision_source or "gpt_pre_forecast").strip(),
      "r_and_d_enabled": bool(r_and_d_enabled),
      "rationale": str(rationale or "").strip(),
      "forecast_world_applied_before_grid": True,
      "finmo_formula_unchanged": True,
    }
  return apply_derived_driver_policies_to_model_input(next_payload)


def r_and_d_enabled_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> bool:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  return bool(_normalized_r_and_d_applicability_policy(payload).get("r_and_d_enabled", True))


_CAPEX_DEPRECIATION_POLICY_KEY = "capex_depreciation_policy"
_CAPEX_DEPRECIATION_POLICY_VERSION = "utilization_first_structural_capacity_capex_v2"
_CAPEX_DEPRECIATION_SOURCE = "structural_capacity_ppe_derived"
_CAPEX_USEFUL_LIFE_YEARS = 5.0
_CAPEX_DEPRECIATION_MIN_PRIOR_PPE = 1e-6
_CAPACITY_UTILIZATION_CEILING = 0.85
_CAPACITY_POST_EXPANSION_UTILIZATION = 0.70
_SBA_BUSINESS_LOAN_RATE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _median(values: List[float]) -> Optional[float]:
  clean = sorted(float(value) for value in values if value is not None and float(value) > 0.0)
  if not clean:
    return None
  mid = len(clean) // 2
  if len(clean) % 2:
    return float(clean[mid])
  return float((clean[mid - 1] + clean[mid]) / 2.0)


def _sba_business_loan_interest_rate_and_source(
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  naics_value = re.sub(r"[^0-9]", "", str(ops.get("business_naics_6") or "").strip())
  state_value = str(financials.get("state") or ops.get("address_state") or ops.get("state") or "").strip().upper()
  cache_key = f"{naics_value or '__fallback__'}::{state_value or '__any_state__'}"
  cached = _SBA_BUSINESS_LOAN_RATE_CACHE.get(cache_key)
  if cached:
    return round(float(cached[0]), 6), deepcopy(cached[1])

  query_specs: List[Tuple[str, str, str]] = []
  if naics_value:
    query_specs.append(("exact_naics_6", "NAICSCode = %s", naics_value))
    for prefix_len in (5, 4, 3, 2):
      if len(naics_value) >= prefix_len:
        query_specs.append((f"naics_{prefix_len}_prefix", "NAICSCode LIKE %s", f"{naics_value[:prefix_len]}%"))
  query_specs.append(("all_sba_7a", "NAICSCode IS NOT NULL", ""))

  _load_root_env()
  conn = None
  cur = None
  try:
    from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
    conn = get_mysql_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
      """
      SELECT MAX(ApprovalFY) AS max_year
      FROM sba_loan_7a_raw
      WHERE InitialInterestRate IS NOT NULL
        AND InitialInterestRate > 0
        AND InitialInterestRate <= 50
      """
    )
    max_year = _safe_float((cur.fetchone() or {}).get("max_year"))
    min_year = int(max_year - 4) if max_year is not None and max_year >= 2000 else None
    for match_basis, predicate, parameter in query_specs:
      params: List[Any] = []
      state_clause = ""
      if state_value:
        state_clause = " AND ProjectState = %s"
        params.append(state_value)
      year_clause = ""
      if min_year is not None:
        year_clause = " AND ApprovalFY >= %s"
        params.append(min_year)
      if parameter:
        params.append(parameter)
      cur.execute(
        f"""
        SELECT InitialInterestRate
        FROM sba_loan_7a_raw
        WHERE InitialInterestRate IS NOT NULL
          AND InitialInterestRate > 0
          AND InitialInterestRate <= 50
          {state_clause}
          {year_clause}
          AND {predicate}
        """,
        tuple(params),
      )
      rates = [
        float(_safe_float(row.get("InitialInterestRate")) or 0.0)
        for row in (cur.fetchall() or [])
        if _safe_float(row.get("InitialInterestRate")) is not None
      ]
      median_rate_pct = _median(rates)
      if median_rate_pct is None and state_value:
        params = []
        year_clause = ""
        if min_year is not None:
          year_clause = " AND ApprovalFY >= %s"
          params.append(min_year)
        if parameter:
          params.append(parameter)
        cur.execute(
          f"""
          SELECT InitialInterestRate
          FROM sba_loan_7a_raw
          WHERE InitialInterestRate IS NOT NULL
            AND InitialInterestRate > 0
            AND InitialInterestRate <= 50
            {year_clause}
            AND {predicate}
          """,
          tuple(params),
        )
        rates = [
          float(_safe_float(row.get("InitialInterestRate")) or 0.0)
          for row in (cur.fetchall() or [])
          if _safe_float(row.get("InitialInterestRate")) is not None
        ]
        median_rate_pct = _median(rates)
      if median_rate_pct is None:
        continue
      annual_rate = round(float(median_rate_pct) / 100.0, 6)
      source = {
        "source": "sba_loan_7a_raw",
        "rate_basis": "median_initial_interest_rate_pct_last_5_approval_years",
        "match_basis": match_basis,
        "naics": naics_value or None,
        "state": state_value or None,
        "approval_fy_min": min_year,
        "approval_fy_max": int(max_year) if max_year is not None else None,
        "sample_count": len(rates),
        "median_rate_pct": round(float(median_rate_pct), 4),
        "annual_rate_decimal": annual_rate,
      }
      _SBA_BUSINESS_LOAN_RATE_CACHE[cache_key] = (annual_rate, deepcopy(source))
      return annual_rate, source
  except Exception as exc:
    intake_rate = _ratio(financials.get("annual_interest_payment"), financials.get("total_debt_outstanding"))
    source = {
      "source": "intake_interest_payment_fallback_after_sba_lookup_error",
      "error": str(exc),
      "annual_rate_decimal": round(float(intake_rate), 6),
    }
    _SBA_BUSINESS_LOAN_RATE_CACHE[cache_key] = (round(float(intake_rate), 6), deepcopy(source))
    return round(float(intake_rate), 6), source
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
  intake_rate = _ratio(financials.get("annual_interest_payment"), financials.get("total_debt_outstanding"))
  source = {
    "source": "intake_interest_payment_fallback_no_sba_rows",
    "annual_rate_decimal": round(float(intake_rate), 6),
  }
  _SBA_BUSINESS_LOAN_RATE_CACHE[cache_key] = (round(float(intake_rate), 6), deepcopy(source))
  return round(float(intake_rate), 6), source


def _default_capex_depreciation_policy(
  *,
  financials_json: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  forecast_starting_ppe: Optional[float] = None,
  maintenance_rate: Optional[float] = None,
  explicit_capex_overrides: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  forecast_ppe = float(max(0.0, _safe_float(forecast_starting_ppe) or 0.0))
  normalized_maintenance_rate = _safe_ratio(maintenance_rate)
  if normalized_maintenance_rate is None or normalized_maintenance_rate < 0.02 or normalized_maintenance_rate > 0.15:
    raise ValueError(
      "capex_depreciation_maintenance_rate_invalid: GPT-authored annual maintenance_rate is required and must satisfy 0.02 <= rate <= 0.15."
    )
  client_reported_ppe = float(max(0.0, _safe_float(financials.get("initial_assets")) or 0.0))
  normalized_overrides = {
    int(quarter_index): round(max(0.0, _safe_float(value) or 0.0), 6)
    for quarter_index, value in ((explicit_capex_overrides or {}).items())
    if int(_safe_float(quarter_index) or 0) >= 1 and _safe_float(value) is not None
  }
  return {
    "policy_version": _CAPEX_DEPRECIATION_POLICY_VERSION,
    "capex_source": _CAPEX_DEPRECIATION_SOURCE,
    "maintenance_rate": float(normalized_maintenance_rate),
    "maintenance_rate_source": "gpt_maintenance_capex_percent",
    "useful_life_years": float(_CAPEX_USEFUL_LIFE_YEARS),
    "capacity_utilization_ceiling": float(_CAPACITY_UTILIZATION_CEILING),
    "capacity_post_expansion_utilization": float(_CAPACITY_POST_EXPANSION_UTILIZATION),
    "initial_assets": float(forecast_ppe),
    "initial_assets_source": "financials_json.initial_assets_authoritative_balance_sheet",
    "forecast_starting_ppe": float(forecast_ppe),
    "forecast_starting_ppe_source": "financials_json.initial_assets_authoritative_balance_sheet",
    "client_reported_ppe_stub": float(client_reported_ppe),
    "client_reported_ppe_stub_source": "financials_json.initial_assets",
    "explicit_capex_overrides": normalized_overrides,
    "business_type": str(ops.get("business_type") or "").strip() or None,
    "naics": str(ops.get("business_naics_6") or "").strip() or None,
  }


def _normalized_capex_depreciation_policy(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  policies = payload.get("derived_driver_policies") if isinstance(payload.get("derived_driver_policies"), dict) else {}
  raw_policy = (
    policies.get(_CAPEX_DEPRECIATION_POLICY_KEY)
    if isinstance(policies.get(_CAPEX_DEPRECIATION_POLICY_KEY), dict)
    else {}
  )
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  fallback_initial_assets = round(
    max(
      0.0,
      _safe_float(raw_policy.get("initial_assets"))
      or _safe_float(raw_policy.get("forecast_starting_ppe"))
      or _safe_float((schedules or {}).get("forecast_ppe_opening_balance_seed"))
      or _safe_float((schedules or {}).get("ppe_opening_balance_seed"))
      or 0.0,
    ),
    6,
  )
  explicit_capex_overrides = {
    int(_safe_float(quarter_index) or 0): round(max(0.0, _safe_float(value) or 0.0), 6)
    for quarter_index, value in (((raw_policy.get("explicit_capex_overrides") or {}) if isinstance(raw_policy.get("explicit_capex_overrides"), dict) else {}).items())
    if int(_safe_float(quarter_index) or 0) >= 1 and _safe_float(value) is not None
  }
  maintenance_rate = _safe_ratio(raw_policy.get("maintenance_rate"))
  if maintenance_rate is None or maintenance_rate < 0.02 or maintenance_rate > 0.15:
    raise ValueError(
      "capex_depreciation_maintenance_rate_invalid: GPT-authored annual maintenance_rate is required and must satisfy 0.02 <= rate <= 0.15."
    )
  return {
    "policy_version": str(raw_policy.get("policy_version") or _CAPEX_DEPRECIATION_POLICY_VERSION).strip() or _CAPEX_DEPRECIATION_POLICY_VERSION,
    "capex_source": str(raw_policy.get("capex_source") or _CAPEX_DEPRECIATION_SOURCE).strip() or _CAPEX_DEPRECIATION_SOURCE,
    "maintenance_rate": float(maintenance_rate),
    "maintenance_rate_source": str(raw_policy.get("maintenance_rate_source") or "").strip() or None,
    "useful_life_years": float(max(1.0, _safe_float(raw_policy.get("useful_life_years")) or _CAPEX_USEFUL_LIFE_YEARS)),
    "capacity_utilization_ceiling": float(max(0.0, _safe_ratio(raw_policy.get("capacity_utilization_ceiling")) or _CAPACITY_UTILIZATION_CEILING)),
    "capacity_post_expansion_utilization": float(max(0.0, _safe_ratio(raw_policy.get("capacity_post_expansion_utilization")) or _CAPACITY_POST_EXPANSION_UTILIZATION)),
    "initial_assets": float(fallback_initial_assets),
    "initial_assets_source": (
      str(raw_policy.get("initial_assets_source") or "").strip()
      or ("model_input.sections.schedules.forecast_ppe_opening_balance_seed" if fallback_initial_assets > 0.0 else None)
    ),
    "forecast_starting_ppe": float(_safe_float(raw_policy.get("forecast_starting_ppe")) or fallback_initial_assets),
    "forecast_starting_ppe_source": str(raw_policy.get("forecast_starting_ppe_source") or "").strip() or None,
    "client_reported_ppe_stub": float(max(0.0, _safe_float(raw_policy.get("client_reported_ppe_stub")) or _safe_float((schedules or {}).get("client_reported_ppe_stub")) or _safe_float((schedules or {}).get("ppe_opening_balance_seed")) or 0.0)),
    "client_reported_ppe_stub_source": str(raw_policy.get("client_reported_ppe_stub_source") or "").strip() or None,
    "explicit_capex_overrides": explicit_capex_overrides,
    "business_type": str(raw_policy.get("business_type") or "").strip() or None,
    "naics": str(raw_policy.get("naics") or "").strip() or None,
  }


def _revenue_slot_key_from_row(row: Dict[str, Any]) -> str:
  return str(
    row.get("revenue_slot_key")
    or _revenue_slot_identity(
      row_lob=row.get("lob") or row.get("placeholder_lob"),
      row_product=row.get("product") or row.get("placeholder_product"),
    ).get("revenue_slot_key")
    or ""
  ).strip()


def _shape_revenue_capacity_and_utilization(
  model_input_json: Optional[Dict[str, Any]],
  *,
  live_count: int,
  policy: Dict[str, Any],
) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  if not revenue_rows:
    raise ValueError(
      "capacity_shaping_revenue_rows_missing: model_input.sections.revenue must include Capacity, Unit Price, and Utilization rows."
    )

  utilization_ceiling = round(float(_safe_ratio(policy.get("capacity_utilization_ceiling")) or 0.0), 6)
  post_expansion_utilization = round(float(_safe_ratio(policy.get("capacity_post_expansion_utilization")) or 0.0), 6)
  if utilization_ceiling <= 0.0 or utilization_ceiling > 1.0:
    raise ValueError(
      "capacity_shaping_policy_invalid: capacity_utilization_ceiling must be greater than 0 and no more than 1."
    )
  if post_expansion_utilization <= 0.0 or post_expansion_utilization >= utilization_ceiling:
    raise ValueError(
      "capacity_shaping_policy_invalid: capacity_post_expansion_utilization must be greater than 0 and less than capacity_utilization_ceiling."
    )

  grouped: Dict[str, Dict[str, Any]] = {}
  for row in revenue_rows:
    driver = str(row.get("driver") or "").strip().lower()
    if driver not in {"capacity", "unit price", "utilization"}:
      continue
    key = _revenue_slot_key_from_row(row)
    if not key:
      raise ValueError(
        "capacity_shaping_revenue_slot_missing: every revenue driver row must have a revenue_slot_key."
      )
    group = grouped.setdefault(
      key,
      {
        "rows": {},
        "stub_values": {},
        "live_values": {},
        "lob": str(row.get("lob") or row.get("placeholder_lob") or "").strip(),
        "product": str(row.get("product") or row.get("placeholder_product") or "").strip(),
      },
    )
    if driver in group["rows"]:
      raise ValueError(
        f"capacity_shaping_duplicate_driver_row: duplicate {driver} row for revenue_slot_key {key}."
      )
    stub_value, live_values = _row_stub_and_live_values(row.get("values") or [], live_count=live_count)
    group["rows"][driver] = row
    group["stub_values"][driver] = round(max(0.0, _safe_float(stub_value) or 0.0), 6)
    group["live_values"][driver] = [round(max(0.0, _safe_float(value) or 0.0), 6) for value in live_values[:live_count]]

  if not grouped:
    raise ValueError(
      "capacity_shaping_capacity_signal_missing: structural Capacity driver rows are required in model_input.sections.revenue."
    )

  product_logs: List[Dict[str, Any]] = []
  total_capacity_by_quarter = [0.0 for _ in range(max(0, int(live_count or 0)))]
  total_revenue_before_by_quarter = [0.0 for _ in range(max(0, int(live_count or 0)))]
  total_revenue_after_by_quarter = [0.0 for _ in range(max(0, int(live_count or 0)))]
  total_expansion_quarters: List[int] = []

  for key, group in sorted(grouped.items()):
    missing = [driver for driver in ("capacity", "unit price", "utilization") if driver not in group["rows"]]
    if missing:
      raise ValueError(
        f"capacity_shaping_driver_set_incomplete: revenue_slot_key {key} is missing {', '.join(missing)}."
      )
    capacity_row = group["rows"]["capacity"]
    utilization_row = group["rows"]["utilization"]
    unit_price_row = group["rows"]["unit price"]
    payroll_supported_capacity = (
      str(capacity_row.get("derived_driver") or "").strip() == "payroll_supported_capacity"
      or isinstance(capacity_row.get("payroll_supported_capacity"), dict)
    )
    capacity_stub = round(float(group["stub_values"].get("capacity") or 0.0), 6)
    capacity_values = group["live_values"].get("capacity") or [0.0 for _ in range(live_count)]
    initial_capacity = next(
      (
        round(max(0.0, _safe_float(value) or 0.0), 6)
        for value in capacity_values[:live_count]
        if round(max(0.0, _safe_float(value) or 0.0), 6) > 0.0
      ),
      0.0,
    )
    if initial_capacity <= 0.0:
      raise ValueError(
        f"capacity_shaping_initial_capacity_missing: revenue_slot_key {key} must have a positive structural Capacity value in the live forecast."
      )

    unit_price_values = group["live_values"].get("unit price") or [0.0 for _ in range(live_count)]
    utilization_values = group["live_values"].get("utilization") or [0.0 for _ in range(live_count)]
    shaped_capacity_values: List[float] = []
    shaped_utilization_values: List[float] = []
    quarter_logs: List[Dict[str, Any]] = []
    previous_capacity = initial_capacity

    for idx in range(max(0, int(live_count or 0))):
      quarter_index = idx + 1
      original_capacity = round(max(0.0, _safe_float(capacity_values[idx]) or 0.0), 6)
      unit_price = round(max(0.0, _safe_float(unit_price_values[idx]) or 0.0), 6)
      original_utilization = round(max(0.0, _safe_float(utilization_values[idx]) or 0.0), 6)
      intended_revenue = round(original_capacity * unit_price * original_utilization, 6)
      if intended_revenue > 0.0 and unit_price <= 0.0:
        raise ValueError(
          f"capacity_shaping_unit_price_missing: revenue_slot_key {key} has positive intended revenue in Q{quarter_index} but no Unit Price."
        )

      utilization_if_no_expansion = 0.0
      expansion_triggered = False
      capacity_delta = 0.0
      if payroll_supported_capacity:
        shaped_capacity = original_capacity
        shaped_utilization = min(max(0.0, original_utilization), utilization_ceiling)
        shaped_revenue = round(shaped_capacity * unit_price * shaped_utilization, 6)
        if intended_revenue > shaped_revenue + 1e-6:
          capacity_delta = 0.0
          expansion_triggered = False
          utilization_if_no_expansion = round(
            intended_revenue / max(shaped_capacity * unit_price, 1e-9),
            6,
          ) if shaped_capacity > 0.0 and unit_price > 0.0 else 0.0
        shaped_capacity_values.append(round(shaped_capacity, 6))
        shaped_utilization_values.append(round(shaped_utilization, 6))
        total_capacity_by_quarter[idx] += round(shaped_capacity, 6)
        total_revenue_before_by_quarter[idx] += intended_revenue
        total_revenue_after_by_quarter[idx] += shaped_revenue
        quarter_logs.append(
          {
            "quarter_index": quarter_index,
            "original_capacity": original_capacity,
            "unit_price": unit_price,
            "original_utilization": original_utilization,
            "intended_revenue": intended_revenue,
            "previous_structural_capacity": round(previous_capacity, 6),
            "utilization_if_no_expansion": utilization_if_no_expansion,
            "utilization_ceiling": utilization_ceiling,
            "post_expansion_utilization": post_expansion_utilization,
            "shaped_capacity": round(shaped_capacity, 6),
            "shaped_utilization": round(shaped_utilization, 6),
            "capacity_delta": 0.0,
            "expansion_triggered": False,
            "payroll_supported_capacity_enforced": True,
            "shaped_revenue": shaped_revenue,
          }
        )
        previous_capacity = round(shaped_capacity, 6)
        continue

      if intended_revenue <= 0.0 or unit_price <= 0.0:
        shaped_capacity = previous_capacity
        shaped_utilization = 0.0
      else:
        utilization_if_no_expansion = round(intended_revenue / max(previous_capacity * unit_price, 1e-9), 6)
        if utilization_if_no_expansion <= utilization_ceiling:
          shaped_capacity = previous_capacity
          shaped_utilization = utilization_if_no_expansion
        else:
          shaped_capacity = round(intended_revenue / max(unit_price * post_expansion_utilization, 1e-9), 6)
          shaped_capacity = max(previous_capacity, shaped_capacity)
          shaped_utilization = round(intended_revenue / max(shaped_capacity * unit_price, 1e-9), 6)
          capacity_delta = round(max(0.0, shaped_capacity - previous_capacity), 6)
          expansion_triggered = capacity_delta > 0.0

      shaped_revenue = round(shaped_capacity * unit_price * shaped_utilization, 6)
      if intended_revenue > 0.0 and shaped_revenue <= 0.0:
        raise ValueError(
          f"capacity_shaping_revenue_preservation_failed: revenue_slot_key {key} produced zero shaped revenue in Q{quarter_index}."
        )
      shaped_capacity_values.append(round(shaped_capacity, 6))
      shaped_utilization_values.append(round(shaped_utilization, 6))
      total_capacity_by_quarter[idx] += round(shaped_capacity, 6)
      total_revenue_before_by_quarter[idx] += intended_revenue
      total_revenue_after_by_quarter[idx] += shaped_revenue
      if expansion_triggered:
        total_expansion_quarters.append(quarter_index)
      quarter_logs.append(
        {
          "quarter_index": quarter_index,
          "original_capacity": original_capacity,
          "unit_price": unit_price,
          "original_utilization": original_utilization,
          "intended_revenue": intended_revenue,
          "previous_structural_capacity": round(previous_capacity, 6),
          "utilization_if_no_expansion": utilization_if_no_expansion,
          "utilization_ceiling": utilization_ceiling,
          "post_expansion_utilization": post_expansion_utilization,
          "shaped_capacity": round(shaped_capacity, 6),
          "shaped_utilization": round(shaped_utilization, 6),
          "capacity_delta": capacity_delta,
          "expansion_triggered": expansion_triggered,
          "shaped_revenue": shaped_revenue,
        }
      )
      previous_capacity = round(shaped_capacity, 6)

    if len(shaped_capacity_values) != live_count or len(shaped_utilization_values) != live_count:
      raise ValueError(
        f"capacity_shaping_series_contract_invalid: revenue_slot_key {key} did not produce every live quarter."
      )
    capacity_row["capacity_shaping"] = {
      "policy_version": str(policy.get("policy_version") or _CAPEX_DEPRECIATION_POLICY_VERSION).strip(),
      "source": _CAPEX_DEPRECIATION_SOURCE,
      "utilization_ceiling": utilization_ceiling,
      "post_expansion_utilization": post_expansion_utilization,
    }
    utilization_row["capacity_shaping"] = deepcopy(capacity_row["capacity_shaping"])
    unit_price_row["capacity_shaping"] = {
      **deepcopy(capacity_row["capacity_shaping"]),
      "role": "price_preserved",
    }
    capacity_row["values"] = _compose_period_values(
      stub_value=capacity_stub,
      live_values=shaped_capacity_values,
    )
    utilization_row["values"] = _compose_period_values(
      stub_value=group["stub_values"].get("utilization") or 0.0,
      live_values=shaped_utilization_values,
    )
    product_logs.append(
      {
        "revenue_slot_key": key,
        "lob": group.get("lob") or None,
        "product": group.get("product") or None,
        "capacity_stub": capacity_stub,
        "initial_live_capacity": initial_capacity,
        "utilization_stub": round(float(group["stub_values"].get("utilization") or 0.0), 6),
        "unit_price_stub": round(float(group["stub_values"].get("unit price") or 0.0), 6),
        "expansion_quarters": [item["quarter_index"] for item in quarter_logs if item.get("expansion_triggered")],
        "quarter_logs": quarter_logs,
      }
    )

  if len(total_capacity_by_quarter) != live_count:
    raise ValueError(
      "capacity_shaping_series_contract_invalid: shaped aggregate capacity did not cover every live quarter."
    )
  return {
    "policy_version": str(policy.get("policy_version") or _CAPEX_DEPRECIATION_POLICY_VERSION).strip(),
    "source": _CAPEX_DEPRECIATION_SOURCE,
    "utilization_ceiling": utilization_ceiling,
    "post_expansion_utilization": post_expansion_utilization,
    "total_capacity_by_quarter": [round(float(value), 6) for value in total_capacity_by_quarter],
    "total_revenue_before_by_quarter": [round(float(value), 6) for value in total_revenue_before_by_quarter],
    "total_revenue_after_by_quarter": [round(float(value), 6) for value in total_revenue_after_by_quarter],
    "expansion_quarters": sorted(set(total_expansion_quarters)),
    "product_logs": product_logs,
  }


def _structural_capacity_series_from_model_input(
  model_input_json: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = [
    row for row in (sections.get("revenue") or [])
    if isinstance(row, dict) and str(row.get("driver") or "").strip().lower() == "capacity"
  ]
  if not revenue_rows:
    raise ValueError(
      "capex_depreciation_capacity_signal_missing: structural Capacity driver rows are required in model_input.sections.revenue."
    )
  live_capacity = [0.0 for _ in range(max(0, int(live_count or 0)))]
  for row in revenue_rows:
    _stub_value, live_values = _row_stub_and_live_values(row.get("values") or [], live_count=live_count)
    for idx, value in enumerate(live_values[:live_count]):
      live_capacity[idx] += max(0.0, float(_safe_float(value) or 0.0))
  initial_capacity = next(
    (
      round(max(0.0, float(value)), 6)
      for value in live_capacity
      if round(max(0.0, float(value)), 6) > 0.0
    ),
    0.0,
  )
  initial_capacity = round(initial_capacity, 6)
  live_capacity = [round(float(value), 6) for value in live_capacity]
  if initial_capacity <= 0.0:
    raise ValueError(
      "capex_depreciation_initial_capacity_missing: total structural live-forecast Capacity must be greater than zero."
    )
  return {
    "initial_capacity": initial_capacity,
    "live_capacity_by_quarter": live_capacity,
  }


def _derived_capex_and_depreciation_runtime(
  *,
  model_input_json: Optional[Dict[str, Any]],
  live_count: int,
  policy: Dict[str, Any],
) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  opening_ppe = round(
    max(
      0.0,
      _safe_float((schedules or {}).get("forecast_ppe_opening_balance_seed"))
      or _safe_float((schedules or {}).get("ppe_opening_balance_seed"))
      or 0.0,
    ),
    6,
  )
  initial_assets = round(max(0.0, float(_safe_float(policy.get("initial_assets")) or 0.0)), 6)
  capacity_runtime = _structural_capacity_series_from_model_input(
    payload,
    live_count=live_count,
  )
  initial_capacity = float(capacity_runtime.get("initial_capacity") or 0.0)
  if initial_capacity <= 0.0:
    raise ValueError(
      "capex_depreciation_initial_capacity_missing: total structural opening Capacity must be greater than zero."
    )
  capital_per_capacity_unit = round(initial_assets / initial_capacity, 6) if initial_assets > 0.0 else 0.0
  maintenance_rate = float(_safe_ratio(policy.get("maintenance_rate")) or 0.0)
  if maintenance_rate < 0.02 or maintenance_rate > 0.15:
    raise ValueError(
      "capex_depreciation_maintenance_rate_invalid: GPT-authored annual maintenance_rate is required and must satisfy 0.02 <= rate <= 0.15."
    )
  useful_life_years = float(policy.get("useful_life_years") or _CAPEX_USEFUL_LIFE_YEARS)
  if useful_life_years <= 0.0:
    raise ValueError(
      "capex_depreciation_useful_life_invalid: useful_life_years must be greater than zero for deterministic depreciation derivation."
    )
  quarterly_maintenance_rate = round(maintenance_rate / 4.0, 6)
  useful_life_quarters = round(useful_life_years * 4.0, 6)
  explicit_capex_overrides = (
    policy.get("explicit_capex_overrides")
    if isinstance(policy.get("explicit_capex_overrides"), dict)
    else {}
  )

  previous_capacity = initial_capacity
  previous_ppe = opening_ppe
  useful_life_quarter_count = int(round(float(useful_life_quarters)))
  if useful_life_quarter_count <= 0 or abs(float(useful_life_quarters) - float(useful_life_quarter_count)) > 0.000001:
    raise ValueError(
      "capex_depreciation_useful_life_quarters_invalid: useful_life_years must resolve to a positive whole number of quarters."
    )
  capex_depreciation_vintages: List[Dict[str, Any]] = []
  capex_live_values: List[float] = []
  depreciation_percent_live_values: List[float] = []
  depreciation_amount_live_values: List[float] = []
  quarter_logs: List[Dict[str, Any]] = []
  for quarter_index, current_capacity in enumerate(capacity_runtime.get("live_capacity_by_quarter") or [], start=1):
    structural_capacity = round(max(0.0, _safe_float(current_capacity) or 0.0), 6)
    capacity_growth_units = round(max(0.0, structural_capacity - previous_capacity), 6)
    maintenance_capex = round(max(0.0, previous_ppe) * quarterly_maintenance_rate, 6)
    expansion_capex = round(capacity_growth_units * capital_per_capacity_unit, 6)
    derived_capex = round(maintenance_capex + expansion_capex, 6)
    explicit_capex = _safe_float(explicit_capex_overrides.get(quarter_index))
    final_capex = round(max(0.0, explicit_capex), 6) if explicit_capex is not None else derived_capex
    if final_capex > 0.0:
      capex_depreciation_vintages.append(
        {
          "placed_quarter": quarter_index,
          "basis": final_capex,
          "quarterly_depreciation": round(final_capex / float(useful_life_quarter_count), 6),
          "remaining_quarters": useful_life_quarter_count,
        }
      )
    active_vintage_components: List[Dict[str, Any]] = []
    depreciation_dollars = 0.0
    remaining_vintages: List[Dict[str, Any]] = []
    for vintage in capex_depreciation_vintages:
      remaining_quarters = int(_safe_float(vintage.get("remaining_quarters")) or 0)
      if remaining_quarters <= 0:
        continue
      quarterly_depreciation = round(max(0.0, float(_safe_float(vintage.get("quarterly_depreciation")) or 0.0)), 6)
      basis = round(max(0.0, float(_safe_float(vintage.get("basis")) or 0.0)), 6)
      placed_quarter = int(_safe_float(vintage.get("placed_quarter")) or quarter_index)
      depreciation_dollars = round(depreciation_dollars + quarterly_depreciation, 6)
      active_vintage_components.append(
        {
          "placed_quarter": placed_quarter,
          "basis": basis,
          "quarterly_depreciation": quarterly_depreciation,
          "remaining_quarters_before_current": remaining_quarters,
        }
      )
      updated_vintage = deepcopy(vintage)
      updated_vintage["remaining_quarters"] = remaining_quarters - 1
      if int(updated_vintage.get("remaining_quarters") or 0) > 0:
        remaining_vintages.append(updated_vintage)
    capex_depreciation_vintages = remaining_vintages
    if depreciation_dollars < 0.0:
      raise ValueError(
        "capex_depreciation_schedule_invalid: scheduled depreciation cannot be negative."
      )
    if previous_ppe <= _CAPEX_DEPRECIATION_MIN_PRIOR_PPE:
      depreciation_percent = 0.0
      modeled_depreciation = 0.0
      zero_prior_ppe = True
    else:
      depreciation_percent = round(depreciation_dollars / previous_ppe, 6)
      modeled_depreciation = round(depreciation_percent * previous_ppe, 6)
      zero_prior_ppe = False
    closing_ppe = round(max(0.0, previous_ppe + final_capex - modeled_depreciation), 6)
    capex_live_values.append(final_capex)
    depreciation_percent_live_values.append(depreciation_percent)
    depreciation_amount_live_values.append(modeled_depreciation)
    quarter_logs.append(
      {
        "quarter_index": quarter_index,
        "prior_ppe": round(previous_ppe, 6),
        "structural_capacity": structural_capacity,
        "previous_structural_capacity": round(previous_capacity, 6),
        "capacity_growth_units": capacity_growth_units,
        "capital_per_capacity_unit": capital_per_capacity_unit,
        "maintenance_rate": round(maintenance_rate, 6),
        "annual_maintenance_rate": round(maintenance_rate, 6),
        "quarterly_maintenance_rate": quarterly_maintenance_rate,
        "maintenance_capex": maintenance_capex,
        "expansion_capex": expansion_capex,
        "derived_capex": derived_capex,
        "explicit_capex_override": round(max(0.0, explicit_capex), 6) if explicit_capex is not None else None,
        "final_capex_used": final_capex,
        "useful_life_years": useful_life_years,
        "useful_life_quarters": useful_life_quarters,
        "useful_life_quarter_count": useful_life_quarter_count,
        "depreciation_schedule_method": "rolling_capex_vintage_straight_line",
        "active_capex_vintage_count": len(active_vintage_components),
        "active_capex_vintage_components": active_vintage_components,
        "depreciation_dollars": depreciation_dollars,
        "depreciation_percent": depreciation_percent,
        "modeled_depreciation": modeled_depreciation,
        "closing_ppe": closing_ppe,
        "zero_prior_ppe": zero_prior_ppe,
      }
    )
    previous_capacity = structural_capacity
    previous_ppe = closing_ppe
  if len(capex_live_values) != live_count or len(depreciation_percent_live_values) != live_count:
    raise ValueError(
      "capex_depreciation_series_contract_invalid: derived capex/depreciation series did not cover every live quarter."
    )
  return {
    "initial_assets": initial_assets,
    "initial_capacity": round(initial_capacity, 6),
    "opening_ppe": opening_ppe,
    "client_reported_ppe_stub": round(
      max(
        0.0,
        _safe_float((schedules or {}).get("client_reported_ppe_stub"))
        or _safe_float((schedules or {}).get("ppe_opening_balance_seed"))
        or 0.0,
      ),
      6,
    ),
    "capital_per_capacity_unit": capital_per_capacity_unit,
    "maintenance_rate": round(maintenance_rate, 6),
    "annual_maintenance_rate": round(maintenance_rate, 6),
    "quarterly_maintenance_rate": quarterly_maintenance_rate,
    "useful_life_years": round(useful_life_years, 6),
    "useful_life_quarters": useful_life_quarters,
    "useful_life_quarter_count": useful_life_quarter_count,
    "depreciation_schedule_method": "rolling_capex_vintage_straight_line",
    "capex_live_values": capex_live_values,
    "depreciation_percent_live_values": depreciation_percent_live_values,
    "depreciation_amount_live_values": depreciation_amount_live_values,
    "quarter_logs": quarter_logs,
  }


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
  for row in revenue_rows:
    driver = str(row.get("driver") or "").strip().lower()
    if driver != str(driver_name or "").strip().lower():
      continue
    key = str(
      row.get("revenue_slot_key")
      or _revenue_slot_identity(
        row_lob=row.get("lob") or row.get("placeholder_lob"),
        row_product=row.get("product") or row.get("placeholder_product"),
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


def _model_input_live_values_for_label(
  model_input_json: Optional[Dict[str, Any]],
  *,
  section_key: str,
  label: str,
  live_count: int,
) -> List[float]:
  row = _find_controller_row(model_input_json, section_key=section_key, label=label)
  _stub_value, live_values = _row_stub_and_live_values((row or {}).get("values") or [], live_count=live_count)
  return [
    round(_safe_float(live_values[idx]) or 0.0, 6)
    if idx < len(live_values) else 0.0
    for idx in range(max(0, live_count))
  ]


def _apply_authoritative_working_capital_driver_policies(
  model_input_json: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> Dict[str, Any]:
  next_payload = _clone(model_input_json if isinstance(model_input_json, dict) else {})
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  if not isinstance(sections, dict) or not isinstance(schedules, dict):
    return next_payload
  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  if not balance_rows:
    return next_payload

  ar_balance_seed = max(0.0, _safe_float(schedules.get("accounts_receivable_opening_balance_seed")) or 0.0)
  inventory_balance_seed = max(0.0, _safe_float(schedules.get("inventory_opening_balance_seed")) or 0.0)
  ap_balance_seed = max(0.0, _safe_float(schedules.get("accounts_payable_opening_balance_seed")) or 0.0)
  if ar_balance_seed <= 0.0 and inventory_balance_seed <= 0.0 and ap_balance_seed <= 0.0:
    return next_payload

  days_in_quarter = 90.0
  revenue_series = _revenue_live_series_from_model_input(next_payload, live_count=live_count)
  cogs_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Cost of Goods Sold",
    live_count=live_count,
  )
  marketing_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Marketing",
    live_count=live_count,
  )
  r_and_d_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Research & Development",
    live_count=live_count,
  )
  lease_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Lease",
    live_count=live_count,
  )
  payroll_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Payroll",
    live_count=live_count,
  )
  g_and_a_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="General & Administrative",
    live_count=live_count,
  )

  # Module 5 Task 5.3: When intake provides AR/AP/Inventory opening balances,
  # the Q1+ trajectory now uses NAICS-cascade days as the steady-state target,
  # not `intake_balance / per-quarter-activity` propagation. Per master diagnostic
  # Part 12.6: "AR/AP/inventory: intake-anchored at stub 0 (Tier A); seed step's
  # residual job is the *trajectory* into Q1 (deterministic via NAICS days)."
  # The legacy "balance / activity" propagation produced quarter-1 lever values
  # well outside NAICS bands for sectors where intake reality diverges from
  # industry norms (e.g., software businesses with low AP balances), tripping
  # the M3 finalize realism gate. Stub 0 is preserved unchanged (set by the
  # initial intake/opening-balance build and never written here).
  #
  # Source priority for NAICS days target, in order:
  #   1. `derived_driver_policies[balance_sheet_contextual_seed]` — written by
  #      the M5 seed step; per-lever NAICS target is the `seed_value` field.
  #      This is the authoritative source after the seed step runs.
  #   2. NAICS resolver (post_intake_industry_baseline) — when the seed policy
  #      hasn't been written yet (e.g., during initial model_input
  #      construction before post-intake pipeline runs). Requires NAICS in the
  #      payload; we look at `business_naics_6` first, then `ops.business_naics_6`.
  policies = next_payload.get("derived_driver_policies") if isinstance(next_payload.get("derived_driver_policies"), dict) else {}
  seed_policy = policies.get(BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY) if isinstance(policies, dict) else {}
  seed_grid = (seed_policy or {}).get("balance_sheet_seed_grid") or []
  seed_by_lever_id: Dict[str, float] = {}
  for entry in seed_grid:
    if not isinstance(entry, dict):
      continue
    lever_id = str(entry.get("lever_id") or "").strip()
    if not lever_id or not bool(entry.get("applicable")):
      continue
    seed_value = _safe_float(entry.get("seed_value"))
    if seed_value is None or seed_value <= 0.0:
      continue
    seed_by_lever_id[lever_id] = float(seed_value)

  business_naics_6 = "".join(ch for ch in str(next_payload.get("business_naics_6") or "") if ch.isdigit())
  if not business_naics_6:
    ops_section = next_payload.get("ops") if isinstance(next_payload.get("ops"), dict) else {}
    business_naics_6 = "".join(ch for ch in str(ops_section.get("business_naics_6") or "") if ch.isdigit())

  def _naics_days_target(metric_key: str, lever_id: str) -> Optional[float]:
    seeded = seed_by_lever_id.get(lever_id)
    if seeded is not None:
      return seeded
    if not business_naics_6:
      return None
    try:
      band = post_intake_industry_baseline_for_naics(metric_key=metric_key, naics_6=business_naics_6)
    except Exception:
      return None
    if not isinstance(band, dict) or band.get("trust_flag") == "no_coverage":
      return None
    target = band.get("benchmark_target")
    if target is None:
      target = band.get("benchmark_min") or band.get("benchmark_max")
    return float(target) if target is not None else None

  ar_naics_days = _naics_days_target("ar_days_dso", "balance_sheet::Accounts Receivable Days")
  ap_naics_days = _naics_days_target("ap_days_dpo", "balance_sheet::Accounts Payable Days")
  inv_naics_days = _naics_days_target("inventory_days", "balance_sheet::Inventory Days")

  runtime_rows: List[Dict[str, Any]] = []
  pending_dependency_rows: List[Dict[str, Any]] = []
  seen_working_capital_labels: set[str] = set()
  for row in balance_rows:
    label = str(row.get("label") or "").strip()
    if label not in {"Accounts Receivable Days", "Inventory Days", "Accounts Payable Days"}:
      continue
    seen_working_capital_labels.add(label)
    stub_value, _existing_live_values = _row_stub_and_live_values(row.get("values") or [], live_count=live_count)
    existing_live_values = list(_existing_live_values or [])
    live_values: List[float] = []
    derivation_basis = "naics_target_days_for_q1_to_qN_trajectory"
    for idx in range(max(0, live_count)):
      revenue = max(0.0, float(revenue_series[idx]) if idx < len(revenue_series) else 0.0)
      cogs_ratio = max(0.0, float(cogs_ratio_series[idx]) if idx < len(cogs_ratio_series) else 0.0)
      marketing_ratio = max(0.0, float(marketing_ratio_series[idx]) if idx < len(marketing_ratio_series) else 0.0)
      r_and_d_ratio = max(0.0, float(r_and_d_ratio_series[idx]) if idx < len(r_and_d_ratio_series) else 0.0)
      lease = max(0.0, float(lease_series[idx]) if idx < len(lease_series) else 0.0)
      payroll = max(0.0, float(payroll_series[idx]) if idx < len(payroll_series) else 0.0)
      g_and_a_ratio = max(0.0, float(g_and_a_ratio_series[idx]) if idx < len(g_and_a_ratio_series) else 0.0)
      cogs = revenue * cogs_ratio
      ap_expense_base = (revenue * marketing_ratio) + (revenue * r_and_d_ratio) + lease + payroll + (revenue * g_and_a_ratio)
      existing_value = (
        round(float(_safe_float(existing_live_values[idx]) or 0.0), 6)
        if idx < len(existing_live_values)
        else 0.0
      )
      if label == "Accounts Receivable Days":
        if ar_balance_seed > 0.0 and revenue <= 0.0:
          raise ValueError(
            "working_capital_days_contract_failed: Accounts Receivable Days requires positive live revenue "
            f"when authoritative opening AR exists. quarter_index={idx + 1} ar_balance_seed={ar_balance_seed} revenue={revenue}"
          )
        if revenue > 0.0 and ar_naics_days is not None:
          value = ar_naics_days
        elif revenue > 0.0 and ar_balance_seed > 0.0:
          # No NAICS coverage; Tier A intake-implied days as last resort.
          value = (ar_balance_seed / revenue) * days_in_quarter
          derivation_basis = "tier_a_intake_implied_days_naics_no_coverage_fallback"
        else:
          value = existing_value
      elif label == "Inventory Days":
        if inventory_balance_seed > 0.0 and cogs <= 0.0:
          pending_dependency_rows.append(
            {
              "label": label,
              "quarter_index": idx + 1,
              "dependency": "Cost of Goods Sold",
              "opening_balance_seed": inventory_balance_seed,
              "dependency_value": cogs,
              "preserved_existing_value": existing_value,
            }
          )
          value = existing_value
        elif cogs > 0.0 and inv_naics_days is not None:
          value = inv_naics_days
        elif cogs > 0.0 and inventory_balance_seed > 0.0:
          value = (inventory_balance_seed / cogs) * days_in_quarter
          derivation_basis = "tier_a_intake_implied_days_naics_no_coverage_fallback"
        else:
          value = existing_value
      else:  # Accounts Payable Days
        if ap_balance_seed > 0.0 and ap_expense_base <= 0.0:
          raise ValueError(
            "working_capital_days_contract_failed: Accounts Payable Days requires positive live AP expense base "
            f"when authoritative opening AP exists. quarter_index={idx + 1} ap_balance_seed={ap_balance_seed} ap_expense_base={ap_expense_base}"
          )
        if ap_expense_base > 0.0 and ap_naics_days is not None:
          value = ap_naics_days
        elif ap_expense_base > 0.0 and ap_balance_seed > 0.0:
          value = (ap_balance_seed / ap_expense_base) * days_in_quarter
          derivation_basis = "tier_a_intake_implied_days_naics_no_coverage_fallback"
        else:
          value = existing_value
      if (
        (label == "Accounts Receivable Days" and ar_balance_seed > 0.0 and revenue > 0.0)
        or (label == "Inventory Days" and inventory_balance_seed > 0.0 and cogs > 0.0)
        or (label == "Accounts Payable Days" and ap_balance_seed > 0.0 and ap_expense_base > 0.0)
      ) and value <= 0.0:
        raise ValueError(
          "working_capital_days_contract_failed: authoritative working-capital trajectory produced a non-positive live driver. "
          f"label={label} quarter_index={idx + 1} value={value}"
        )
      live_values.append(round(float(value), 6))
    row["derived_driver"] = "authoritative_balance_sheet_working_capital_days"
    row["working_capital_derivation"] = {
      "source": "naics_cascade_with_intake_anchored_stub_0",
      "driver_basis": derivation_basis,
      "days_in_quarter": days_in_quarter,
      "naics_6": business_naics_6 or None,
      "naics_target_days": (
        ar_naics_days if label == "Accounts Receivable Days"
        else inv_naics_days if label == "Inventory Days"
        else ap_naics_days
      ),
      "opening_balance_seed": round(
        ar_balance_seed
        if label == "Accounts Receivable Days"
        else inventory_balance_seed
        if label == "Inventory Days"
        else ap_balance_seed,
        6,
      ),
    }
    row["values"] = _compose_period_values(stub_value=stub_value, live_values=live_values)
    runtime_rows.append(
      {
        "lever_id": str(row.get("lever_id") or "").strip(),
        "label": label,
        "opening_balance_seed": row["working_capital_derivation"]["opening_balance_seed"],
        "naics_target_days": row["working_capital_derivation"]["naics_target_days"],
        "live_values": deepcopy(live_values),
      }
    )

  required_missing: List[str] = []
  if ar_balance_seed > 0.0 and "Accounts Receivable Days" not in seen_working_capital_labels:
    required_missing.append("Accounts Receivable Days")
  if inventory_balance_seed > 0.0 and "Inventory Days" not in seen_working_capital_labels:
    required_missing.append("Inventory Days")
  if ap_balance_seed > 0.0 and "Accounts Payable Days" not in seen_working_capital_labels:
    required_missing.append("Accounts Payable Days")
  if required_missing:
    raise ValueError(
      "working_capital_days_contract_failed: authoritative working-capital balances require model-input day driver rows. "
      + json.dumps(
        {
          "missing_rows": required_missing,
          "ar_balance_seed": ar_balance_seed,
          "inventory_balance_seed": inventory_balance_seed,
          "ap_balance_seed": ap_balance_seed,
        },
        ensure_ascii=False,
      )
    )

  if runtime_rows:
    next_payload.setdefault("derived_driver_runtime", {})
    if isinstance(next_payload.get("derived_driver_runtime"), dict):
      next_payload["derived_driver_runtime"]["authoritative_balance_sheet_working_capital_days"] = {
        "source": "authoritative_balance_sheet_opening_balances",
        "rows": runtime_rows,
        "pending_dependency_rows": pending_dependency_rows,
      }
  return next_payload


def _apply_contextual_balance_sheet_driver_seed_policy(
  model_input_json: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> Dict[str, Any]:
  next_payload = _clone(model_input_json if isinstance(model_input_json, dict) else {})
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  if not isinstance(sections, dict):
    return next_payload
  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  if not balance_rows:
    return next_payload
  revenue_series = _revenue_live_series_from_model_input(next_payload, live_count=live_count)
  cogs_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Cost of Goods Sold",
    live_count=live_count,
  )
  marketing_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Marketing",
    live_count=live_count,
  )
  r_and_d_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Research & Development",
    live_count=live_count,
  )
  lease_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Lease",
    live_count=live_count,
  )
  payroll_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="Payroll",
    live_count=live_count,
  )
  g_and_a_ratio_series = _model_input_live_values_for_label(
    next_payload,
    section_key="expenses",
    label="General & Administrative",
    live_count=live_count,
  )
  policies = next_payload.get("derived_driver_policies") if isinstance(next_payload.get("derived_driver_policies"), dict) else {}
  policy = policies.get(BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY) if isinstance(policies, dict) else {}
  seed_rows = [
    item for item in ((policy or {}).get("balance_sheet_seed_grid") or [])
    if isinstance(item, dict)
  ]
  seed_by_lever = {
    str(item.get("lever_id") or "").strip(): item
    for item in seed_rows
    if str(item.get("lever_id") or "").strip()
  }
  lever_by_label = {
    "Accounts Receivable Days": "balance_sheet::Accounts Receivable Days",
    "Accounts Payable Days": "balance_sheet::Accounts Payable Days",
    "Inventory Days": "balance_sheet::Inventory Days",
    "Prepaid Expenses (% of Revenue)": "balance_sheet::Prepaid Expenses (% of Revenue)",
    "Deferred Revenue (% of Revenue)": "balance_sheet::Deferred Revenue (% of Revenue)",
  }
  runtime_rows: List[Dict[str, Any]] = []
  for row in balance_rows:
    label = str(row.get("label") or "").strip()
    lever_id = str(row.get("lever_id") or lever_by_label.get(label) or "").strip()
    seed_row = seed_by_lever.get(lever_id)
    if not isinstance(seed_row, dict) or not bool(seed_row.get("applicable")):
      continue
    seed_value = _safe_float(seed_row.get("seed_value"))
    if seed_value is None or seed_value <= 0.0:
      raise ValueError(
        "balance_sheet_contextual_seed_invalid: applicable balance-sheet driver is missing a positive business-context seed. "
        f"lever_id={lever_id} seed_value={seed_row.get('seed_value')!r}"
      )
    stub_value, existing_live_values = _row_stub_and_live_values(row.get("values") or [], live_count=live_count)
    live_values: List[float] = []
    changed_quarters: List[int] = []
    for idx in range(max(0, live_count)):
      revenue = max(0.0, float(revenue_series[idx]) if idx < len(revenue_series) else 0.0)
      cogs_ratio = max(0.0, float(cogs_ratio_series[idx]) if idx < len(cogs_ratio_series) else 0.0)
      marketing_ratio = max(0.0, float(marketing_ratio_series[idx]) if idx < len(marketing_ratio_series) else 0.0)
      r_and_d_ratio = max(0.0, float(r_and_d_ratio_series[idx]) if idx < len(r_and_d_ratio_series) else 0.0)
      lease = max(0.0, float(lease_series[idx]) if idx < len(lease_series) else 0.0)
      payroll = max(0.0, float(payroll_series[idx]) if idx < len(payroll_series) else 0.0)
      g_and_a_ratio = max(0.0, float(g_and_a_ratio_series[idx]) if idx < len(g_and_a_ratio_series) else 0.0)
      ap_expense_base = (revenue * marketing_ratio) + (revenue * r_and_d_ratio) + lease + payroll + (revenue * g_and_a_ratio)
      existing_value = (
        round(float(_safe_float(existing_live_values[idx]) or 0.0), 6)
        if idx < len(existing_live_values)
        else 0.0
      )
      cogs = revenue * cogs_ratio
      should_apply = (
        (label in {"Accounts Receivable Days", "Prepaid Expenses (% of Revenue)", "Deferred Revenue (% of Revenue)"} and revenue > 0.0)
        or (label == "Accounts Payable Days" and ap_expense_base > 0.0)
        or (label == "Inventory Days" and cogs > 0.0)
      )
      # Module 5 Task 5.3: when the proposer/critic decided this lever is
      # applicable, the seed_value (NAICS target, possibly amended by the
      # critic) is the authoritative Q1+ trajectory. Overwrite any prior
      # value the model_input overlay placed there. The legacy "fill zeros
      # only" behavior preserved Tier A intake-implied days across Q1+,
      # which violated the diagnostic Part 12.6 invariant ("Tier A for
      # stub 0; NAICS for trajectory") and tripped the realism gate at
      # finalize for sectors where intake reality is well outside NAICS
      # bands (e.g., software businesses with low AP balances).
      if should_apply:
        live_values.append(round(float(seed_value), 6))
        if abs(float(seed_value) - float(existing_value)) > 1e-9:
          changed_quarters.append(idx + 1)
      else:
        live_values.append(existing_value)
    if changed_quarters:
      row["derived_driver"] = "balance_sheet_contextual_seed"
      row["balance_sheet_contextual_seed"] = {
        "source_contract": "balance_sheet_contextual_seed",
        "source_table": "post_intake_gpt_contract_lookup",
        "lever_id": lever_id,
        "business_applicability_key": str(seed_row.get("business_applicability_key") or "").strip(),
        "rationale": str(seed_row.get("rationale") or "").strip(),
        "changed_quarters": changed_quarters,
      }
      row["values"] = _compose_period_values(stub_value=stub_value, live_values=live_values)
      runtime_rows.append(
        {
          "lever_id": lever_id,
          "label": label,
          "seed_value": round(float(seed_value), 6),
          "changed_quarters": changed_quarters,
        }
      )
  if runtime_rows and isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY] = {
      "source_contract": "balance_sheet_contextual_seed",
      "rows": runtime_rows,
    }
  return next_payload


def apply_derived_driver_policies_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  next_payload = _clone(model_input_json if isinstance(model_input_json, dict) else {})
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  if not isinstance(sections, dict):
    return next_payload
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  schedule_rows = [row for row in ((schedules or {}).get("rows") or []) if isinstance(row, dict)]
  period_live_count = len([
    item for item in (next_payload.get("periods") or [])
    if isinstance(item, dict) and not bool(item.get("is_stub"))
  ])
  value_live_count = max(
    [
      max(0, len(list(row.get("values") or [])) - 1)
      for row in (revenue_rows + expense_rows + balance_rows + schedule_rows)
      if isinstance(row, dict)
    ] or [0]
  )
  live_count = max(0, period_live_count, value_live_count)

  next_payload.setdefault("derived_driver_policies", {})
  next_payload.setdefault("derived_driver_runtime", {})

  r_and_d_policy = _normalized_r_and_d_applicability_policy(next_payload)
  r_and_d_row = next((
    row for row in expense_rows
    if str(row.get("label") or "").strip() == "Research & Development"
  ), None)
  if isinstance(r_and_d_row, dict) and not bool(r_and_d_policy.get("r_and_d_enabled")):
    stub_value, _existing_live_values = _row_stub_and_live_values(
      r_and_d_row.get("values") or [],
      live_count=live_count,
    )
    r_and_d_row["controller_write"] = False
    r_and_d_row["derived_driver"] = "r_and_d_disabled_by_business_applicability"
    r_and_d_row["r_and_d_applicability"] = deepcopy(r_and_d_policy)
    r_and_d_row["values"] = _compose_period_values(
      stub_value=stub_value,
      live_values=[0.0 for _ in range(live_count)],
    )
    if isinstance(next_payload.get("controller_write_levers"), list):
      next_payload["controller_write_levers"] = [
        deepcopy(item)
        for item in (next_payload.get("controller_write_levers") or [])
        if isinstance(item, dict)
        and str(item.get("lever_id") or "").strip() != R_AND_D_APPLICABILITY_LEVER_ID
      ]
    if isinstance(next_payload.get("lever_catalog"), dict):
      lever_catalog = deepcopy(next_payload.get("lever_catalog") or {})
      lever_catalog.pop(R_AND_D_APPLICABILITY_LEVER_ID, None)
      next_payload["lever_catalog"] = lever_catalog
    if isinstance(next_payload.get("derived_driver_runtime"), dict):
      next_payload["derived_driver_runtime"][R_AND_D_APPLICABILITY_LEVER_ID] = {
        **deepcopy(r_and_d_policy),
        "forecast_live_values_forced_zero": True,
        "controller_write_removed": True,
      }
  elif isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][R_AND_D_APPLICABILITY_LEVER_ID] = {
      **deepcopy(r_and_d_policy),
      "forecast_live_values_forced_zero": False,
      "controller_write_removed": False,
    }

  capex_policy = _normalized_capex_depreciation_policy(next_payload)
  capacity_shaping_runtime = _shape_revenue_capacity_and_utilization(
    next_payload,
    live_count=live_count,
    policy=capex_policy,
  )
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"]["capacity_shaping"] = deepcopy(capacity_shaping_runtime)

  next_payload = apply_payroll_headcount_policy_to_model_input(
    next_payload,
    live_count=live_count,
  )

  next_payload = _apply_authoritative_working_capital_driver_policies(
    next_payload,
    live_count=live_count,
  )
  next_payload = _apply_contextual_balance_sheet_driver_seed_policy(
    next_payload,
    live_count=live_count,
  )
  next_payload = _enforce_balance_sheet_stock_level_carryforward(
    next_payload,
    live_count=live_count,
  )
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  schedule_rows = [row for row in ((schedules or {}).get("rows") or []) if isinstance(row, dict)]

  depreciation_row = next((
    row for row in expense_rows
    if str(row.get("label") or "").strip() == "Depreciation"
  ), None)
  if not isinstance(depreciation_row, dict):
    raise ValueError(
      "capex_depreciation_row_missing: model_input.sections.expenses must include the Depreciation row."
    )
  if not isinstance(schedules, dict):
    raise ValueError(
      "capex_depreciation_schedule_missing: model_input.sections.schedules is required for deterministic capex/depreciation derivation."
    )
  capex_row = next((
    row for row in schedule_rows
    if str(row.get("label") or "").strip() == "Capital Expenditures"
  ), None)
  if not isinstance(capex_row, dict):
    raise ValueError(
      "capex_depreciation_row_missing: model_input.sections.schedules.rows must include the Capital Expenditures row."
    )

  capex_policy = _normalized_capex_depreciation_policy(next_payload)
  capex_runtime = _derived_capex_and_depreciation_runtime(
    model_input_json=next_payload,
    live_count=live_count,
    policy=capex_policy,
  )
  capex_stub_value, _existing_capex_live_values = _row_stub_and_live_values(
    capex_row.get("values") or [],
    live_count=live_count,
  )
  depreciation_stub_value, _existing_depreciation_live_values = _row_stub_and_live_values(
    depreciation_row.get("values") or [],
    live_count=live_count,
  )
  explicit_override_quarters = sorted(
    quarter_index
    for quarter_index in (
      int(_safe_float(item) or 0)
      for item in ((capex_policy.get("explicit_capex_overrides") or {}).keys() if isinstance(capex_policy.get("explicit_capex_overrides"), dict) else [])
    )
    if quarter_index >= 1
  )
  capex_row["derived_driver"] = _CAPEX_DEPRECIATION_SOURCE
  capex_row["value_kind"] = "direct_number"
  capex_row["input_semantics"] = "capital_expenditures_cash"
  capex_row["capex_depreciation"] = {
    "policy_version": str(capex_policy.get("policy_version") or _CAPEX_DEPRECIATION_POLICY_VERSION).strip(),
    "capex_source": _CAPEX_DEPRECIATION_SOURCE,
    "maintenance_rate": round(float(capex_runtime.get("maintenance_rate") or 0.0), 6),
    "useful_life_years": round(float(capex_runtime.get("useful_life_years") or _CAPEX_USEFUL_LIFE_YEARS), 6),
    "capacity_utilization_ceiling": round(float(capacity_shaping_runtime.get("utilization_ceiling") or _CAPACITY_UTILIZATION_CEILING), 6),
    "capacity_post_expansion_utilization": round(float(capacity_shaping_runtime.get("post_expansion_utilization") or _CAPACITY_POST_EXPANSION_UTILIZATION), 6),
    "capital_per_capacity_unit": round(float(capex_runtime.get("capital_per_capacity_unit") or 0.0), 6),
    "initial_assets": round(float(capex_runtime.get("initial_assets") or 0.0), 6),
    "initial_capacity": round(float(capex_runtime.get("initial_capacity") or 0.0), 6),
    "opening_ppe": round(float(capex_runtime.get("opening_ppe") or 0.0), 6),
    "forecast_starting_ppe": round(float(capex_runtime.get("opening_ppe") or 0.0), 6),
    "client_reported_ppe_stub": round(float(capex_runtime.get("client_reported_ppe_stub") or 0.0), 6),
    "explicit_override_quarters": explicit_override_quarters,
    "quarter_logs": deepcopy(capex_runtime.get("quarter_logs") or []),
  }
  capex_row["values"] = _compose_period_values(
    stub_value=capex_stub_value,
    live_values=list(capex_runtime.get("capex_live_values") or []),
  )
  depreciation_row["derived_driver"] = _CAPEX_DEPRECIATION_SOURCE
  depreciation_row["value_kind"] = "ratio"
  depreciation_row["input_semantics"] = "percent_of_prior_ppe"
  depreciation_row["capex_depreciation"] = {
    "policy_version": str(capex_policy.get("policy_version") or _CAPEX_DEPRECIATION_POLICY_VERSION).strip(),
    "depreciation_source": _CAPEX_DEPRECIATION_SOURCE,
    "depreciation_driver_basis": "final_capex_used",
    "useful_life_years": round(float(capex_runtime.get("useful_life_years") or _CAPEX_USEFUL_LIFE_YEARS), 6),
    "quarter_logs": deepcopy(capex_runtime.get("quarter_logs") or []),
  }
  depreciation_row["values"] = _compose_period_values(
    stub_value=depreciation_stub_value,
    live_values=list(capex_runtime.get("depreciation_percent_live_values") or []),
  )
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"][_CAPEX_DEPRECIATION_POLICY_KEY] = deepcopy(capex_policy)
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][_CAPEX_DEPRECIATION_POLICY_KEY] = {
      "capex_source": _CAPEX_DEPRECIATION_SOURCE,
      "policy_version": str(capex_policy.get("policy_version") or _CAPEX_DEPRECIATION_POLICY_VERSION).strip(),
      "maintenance_rate": round(float(capex_runtime.get("maintenance_rate") or 0.0), 6),
      "useful_life_years": round(float(capex_runtime.get("useful_life_years") or _CAPEX_USEFUL_LIFE_YEARS), 6),
      "capacity_utilization_ceiling": round(float(capacity_shaping_runtime.get("utilization_ceiling") or _CAPACITY_UTILIZATION_CEILING), 6),
      "capacity_post_expansion_utilization": round(float(capacity_shaping_runtime.get("post_expansion_utilization") or _CAPACITY_POST_EXPANSION_UTILIZATION), 6),
      "capital_per_capacity_unit": round(float(capex_runtime.get("capital_per_capacity_unit") or 0.0), 6),
      "initial_assets": round(float(capex_runtime.get("initial_assets") or 0.0), 6),
      "initial_capacity": round(float(capex_runtime.get("initial_capacity") or 0.0), 6),
      "opening_ppe": round(float(capex_runtime.get("opening_ppe") or 0.0), 6),
      "forecast_starting_ppe": round(float(capex_runtime.get("opening_ppe") or 0.0), 6),
      "client_reported_ppe_stub": round(float(capex_runtime.get("client_reported_ppe_stub") or 0.0), 6),
      "explicit_capex_overrides": deepcopy(capex_policy.get("explicit_capex_overrides") or {}),
      "capex_live_values": deepcopy(capex_runtime.get("capex_live_values") or []),
      "depreciation_percent_live_values": deepcopy(capex_runtime.get("depreciation_percent_live_values") or []),
      "depreciation_amount_live_values": deepcopy(capex_runtime.get("depreciation_amount_live_values") or []),
      "capacity_shaping": deepcopy(capacity_shaping_runtime),
      "quarter_logs": deepcopy(capex_runtime.get("quarter_logs") or []),
    }
  return next_payload


def _controller_row_values(row: Any) -> List[float]:
  values = (row or {}).get("values") if isinstance(row, dict) else []
  return [round(_safe_float(item) or 0.0, 6) for item in (values or [])]


def _controller_row_stub_value(row: Any) -> float:
  values = _controller_row_values(row)
  return float(values[0]) if values else 0.0


def _find_controller_row(
  model_input_json: Optional[Dict[str, Any]],
  *,
  section_key: str,
  label: str,
) -> Optional[Dict[str, Any]]:
  sections = (model_input_json or {}).get("sections") if isinstance(model_input_json, dict) else {}
  rows = (sections or {}).get(section_key) if isinstance(sections, dict) else []
  for row in (rows or []):
    if not isinstance(row, dict):
      continue
    if str(row.get("label") or "").strip() == str(label or "").strip():
      return row
  return None


def _q1_fallback_metric(row: Optional[Dict[str, Any]], metric_key: str) -> float:
  if not isinstance(row, dict):
    return 0.0
  return round(_safe_float(row.get(metric_key)) or 0.0, 6)


def _build_operating_stub_metrics(
  model_input_json: Optional[Dict[str, Any]],
  *,
  first_live_row: Optional[Dict[str, Any]],
) -> Dict[str, float]:
  sections = (model_input_json or {}).get("sections") if isinstance(model_input_json, dict) else {}
  revenue_rows = (sections or {}).get("revenue") if isinstance(sections, dict) else []
  expense_rows = (sections or {}).get("expenses") if isinstance(sections, dict) else []
  schedules = (sections or {}).get("schedules") if isinstance(sections, dict) else {}
  balance_rows = (sections or {}).get("balance_sheet") if isinstance(sections, dict) else []

  driver_map: Dict[Tuple[str, str], Dict[str, float]] = {}
  stub_signals: List[float] = []
  for row in (revenue_rows or []):
    if not isinstance(row, dict):
      continue
    lob = str(row.get("lob") or "").strip()
    product = str(row.get("product") or "").strip()
    driver = str(row.get("driver") or "").strip().lower()
    if not lob or not product or not driver:
      continue
    stub_value = _controller_row_stub_value(row)
    driver_map.setdefault((lob, product), {})[driver] = stub_value
    stub_signals.append(abs(stub_value))

  expense_stub_by_label: Dict[str, float] = {}
  for row in (expense_rows or []):
    if not isinstance(row, dict):
      continue
    label = str(row.get("label") or "").strip()
    if not label:
      continue
    stub_value = _controller_row_stub_value(row)
    expense_stub_by_label[label] = stub_value
    stub_signals.append(abs(stub_value))

  balance_stub_by_label: Dict[str, float] = {}
  for row in (balance_rows or []):
    if not isinstance(row, dict):
      continue
    label = str(row.get("label") or "").strip()
    if not label:
      continue
    balance_stub_by_label[label] = _controller_row_stub_value(row)

  schedule_seed_map = schedules if isinstance(schedules, dict) else {}
  opening_debt = round(
    _safe_float(schedule_seed_map.get("debt_opening_balance_seed")) or 0.0,
    6,
  )
  opening_ppe = round(
    _safe_float(schedule_seed_map.get("ppe_opening_balance_seed")) or 0.0,
    6,
  )

  revenue_stub = 0.0
  for drivers in driver_map.values():
    capacity = float(drivers.get("capacity") or 0.0)
    unit_price = float(drivers.get("unit price") or 0.0)
    utilization = float(drivers.get("utilization") or 0.0)
    if capacity > 0.0 and unit_price > 0.0 and utilization > 0.0:
      revenue_stub += capacity * unit_price * utilization

  revenue = round(revenue_stub, 6)
  cogs_ratio = float(expense_stub_by_label.get("Cost of Goods Sold") or 0.0)
  marketing_ratio = float(expense_stub_by_label.get("Marketing") or 0.0)
  r_and_d_ratio = float(expense_stub_by_label.get("Research & Development") or 0.0)
  g_and_a_ratio = float(expense_stub_by_label.get("General & Administrative") or 0.0)
  lease_rent = round(float(expense_stub_by_label.get("Lease") or 0.0), 6)
  payroll = round(float(expense_stub_by_label.get("Payroll") or 0.0), 6)
  interest_rate = float(expense_stub_by_label.get("Interest Rate") or 0.0)
  depreciation_ratio = float(expense_stub_by_label.get("Depreciation") or 0.0)
  tax_rate = float(expense_stub_by_label.get("Taxes") or 0.0)

  cost_of_goods_sold = round(revenue * cogs_ratio, 6)
  gross_profit = round(revenue - cost_of_goods_sold, 6)
  marketing = round(revenue * marketing_ratio, 6)
  research_and_development = round(revenue * r_and_d_ratio, 6)
  general_and_administrative = round(revenue * g_and_a_ratio, 6)
  ebitda = round(
    gross_profit - (marketing + research_and_development + lease_rent + payroll + general_and_administrative),
    6,
  )
  interest = round(opening_debt * interest_rate, 6)
  depreciation = round(max(0.0, opening_ppe) * depreciation_ratio, 6)
  pre_tax_income = round(ebitda - interest - depreciation, 6)
  taxes = round(max(0.0, pre_tax_income) * tax_rate, 6)
  net_income = round(ebitda - interest - depreciation - taxes, 6)

  return {
    "revenue": revenue,
    "cost_of_goods_sold": cost_of_goods_sold,
    "gross_profit": gross_profit,
    "marketing": marketing,
    "research_and_development": research_and_development,
    "lease_rent": lease_rent,
    "payroll": payroll,
    "general_and_administrative": general_and_administrative,
    "ebitda": ebitda,
    "interest": interest,
    "depreciation": depreciation,
    "taxes": taxes,
    "net_income": net_income,
  }


def _build_balance_sheet_intake_stub_metrics(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, float]:
  sections = (model_input_json or {}).get("sections") if isinstance(model_input_json, dict) else {}
  schedules = (sections or {}).get("schedules") if isinstance(sections, dict) else {}
  balance_rows = (sections or {}).get("balance_sheet") if isinstance(sections, dict) else []

  schedule_seed_map = schedules if isinstance(schedules, dict) else {}
  balance_stub_by_label: Dict[str, float] = {}
  for row in (balance_rows or []):
    if not isinstance(row, dict):
      continue
    label = str(row.get("label") or "").strip()
    if not label:
      continue
    balance_stub_by_label[label] = _controller_row_stub_value(row)

  def _seed_value(key: str) -> float:
    return round(float(_safe_float(schedule_seed_map.get(key)) or 0.0), 6)

  cash = max(0.0, _seed_value("cash_opening_balance_seed"))
  accounts_receivable = max(0.0, _seed_value("accounts_receivable_opening_balance_seed"))
  inventory = max(0.0, _seed_value("inventory_opening_balance_seed"))
  prepaid_expenses = 0.0
  current_assets = round(cash + accounts_receivable + inventory + prepaid_expenses, 6)

  ppe = max(0.0, _seed_value("ppe_opening_balance_seed"))
  accumulated_depreciation = round(float(_safe_float(schedule_seed_map.get("accumulated_depreciation_opening_seed")) or 0.0), 6)
  total_assets = round(current_assets + ppe + accumulated_depreciation, 6)

  accounts_payable = max(0.0, _seed_value("accounts_payable_opening_balance_seed"))
  short_term_debt = max(0.0, _seed_value("short_term_debt_opening_balance_seed"))
  deferred_revenue = 0.0
  current_liabilities = round(accounts_payable + short_term_debt + deferred_revenue, 6)

  total_debt_opening = max(0.0, _seed_value("debt_opening_balance_seed"))
  long_term_debt = round(max(0.0, total_debt_opening - short_term_debt), 6)
  total_liabilities = round(current_liabilities + long_term_debt, 6)

  owners_capital = round(float(balance_stub_by_label.get("Owner's Capital") or 0.0), 6)
  other_equity = round(float(balance_stub_by_label.get("Other Equity") or 0.0), 6)
  retained_earnings = round(total_assets - total_liabilities - owners_capital - other_equity, 6)
  total_equity = round(owners_capital + retained_earnings + other_equity, 6)
  total_liabilities_and_equity = round(total_liabilities + total_equity, 6)

  return {
    "cash": round(cash, 6),
    "accounts_receivable": round(accounts_receivable, 6),
    "inventory": round(inventory, 6),
    "prepaid_expenses": round(prepaid_expenses, 6),
    "current_assets": current_assets,
    "ppe": round(ppe, 6),
    "accumulated_depreciation": accumulated_depreciation,
    "total_assets": total_assets,
    "accounts_payable": round(accounts_payable, 6),
    "short_term_debt": round(short_term_debt, 6),
    "deferred_revenue": round(deferred_revenue, 6),
    "current_liabilities": current_liabilities,
    "long_term_debt": long_term_debt,
    "total_liabilities": total_liabilities,
    "owners_capital": owners_capital,
    "retained_earnings": retained_earnings,
    "other_equity": other_equity,
    "total_equity": total_equity,
    "total_liabilities_and_equity": total_liabilities_and_equity,
    "beginning_cash": round(cash, 6),
    "ending_cash": round(cash, 6),
  }


def _apply_operating_stub_to_quarter_rows(
  quarter_rows_with_stub: Sequence[Dict[str, Any]],
  *,
  model_input_json: Optional[Dict[str, Any]],
  first_live_row: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  rows = [_clone(row) for row in (quarter_rows_with_stub or []) if isinstance(row, dict)]
  if not rows:
    return []
  stub_index = next(
    (idx for idx, row in enumerate(rows) if int(_safe_float(row.get("quarter_index")) or 0) == 0),
    None,
  )
  if stub_index is None:
    return rows
  operating_stub = _build_operating_stub_metrics(
    model_input_json,
    first_live_row=first_live_row,
  )
  balance_sheet_stub = _build_balance_sheet_intake_stub_metrics(model_input_json)
  rows[stub_index].update(
    {
      **operating_stub,
      **balance_sheet_stub,
      "cogs": operating_stub.get("cost_of_goods_sold"),
      "g_and_a": operating_stub.get("general_and_administrative"),
    }
  )
  return rows


def _schedule_row_template(
  *,
  label: str,
  period_count: int,
  values: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
  normalized_values = [round(_safe_float(item) or 0.0, 6) for item in (values or [])]
  if not normalized_values:
    normalized_values = [0.0 for _ in range(max(0, int(period_count) + 1))]
  return {
    "named_range": "model_input_schedules",
    "controller_write": True,
    "lever_id": _simple_lever_id("schedules", label),
    "label": label,
    **_simple_input_semantics("schedules", label),
    "values": normalized_values,
  }


def _normalize_schedule_rows_for_explicit_debt_controls(
  rows: Sequence[Dict[str, Any]],
  *,
  period_count: int,
) -> List[Dict[str, Any]]:
  live_count = max(0, int(period_count))
  normalized_rows = [_clone(item) for item in (rows or []) if isinstance(item, dict)]
  legacy_row = None
  explicit_issuance_present = False
  explicit_repayment_present = False
  retained_rows: List[Dict[str, Any]] = []
  for row in normalized_rows:
    label = str(row.get("label") or "").strip()
    if label == LEGACY_NET_DEBT_LABEL:
      legacy_row = row
      continue
    if label == DEBT_ISSUANCE_LABEL:
      explicit_issuance_present = True
    elif label == DEBT_REPAYMENT_LABEL:
      explicit_repayment_present = True
    retained_rows.append(row)

  legacy_stub_value = 0.0
  legacy_issuance_values = [0.0 for _ in range(live_count)]
  legacy_repayment_values = [0.0 for _ in range(live_count)]
  if isinstance(legacy_row, dict):
    legacy_stub_value, legacy_live_values = _row_stub_and_live_values(legacy_row.get("values") or [], live_count=live_count)
    legacy_issuance_values = [round(max(0.0, _safe_float(value) or 0.0), 6) for value in legacy_live_values]
    legacy_repayment_values = [round(max(0.0, -(_safe_float(value) or 0.0)), 6) for value in legacy_live_values]

  if not explicit_issuance_present:
    retained_rows.insert(
      0,
      _schedule_row_template(
        label=DEBT_ISSUANCE_LABEL,
        period_count=live_count,
        values=_compose_period_values(stub_value=max(0.0, legacy_stub_value), live_values=legacy_issuance_values),
      ),
    )
  if not explicit_repayment_present:
    insert_index = 1 if retained_rows else 0
    retained_rows.insert(
      insert_index,
      _schedule_row_template(
        label=DEBT_REPAYMENT_LABEL,
        period_count=live_count,
        values=_compose_period_values(stub_value=max(0.0, -legacy_stub_value), live_values=legacy_repayment_values),
      ),
    )
  return retained_rows


def _planned_quarter_slots(period_count: int, forecast_quarters: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  quarters = [item for item in (forecast_quarters or []) if isinstance(item, dict)]
  if period_count <= 0:
    return []
  if not quarters:
    return [{} for _ in range(period_count)]
  slots: List[Dict[str, Any]] = []
  for idx in range(period_count):
    source_idx = min(idx, len(quarters) - 1)
    slots.append(_clone(quarters[source_idx]))
  return slots


def _ops_revenue_catalog(ops_json: Dict[str, Any]) -> Dict[Tuple[int, int], Dict[str, Any]]:
  ops = ops_json if isinstance(ops_json, dict) else {}
  catalog: Dict[Tuple[int, int], Dict[str, Any]] = {}
  lob_models = ops.get("lob_models") if isinstance(ops.get("lob_models"), list) else []
  if lob_models:
    for lob_idx, lob in enumerate(lob_models):
      if not isinstance(lob, dict):
        continue
      lob_name = _named_lob(
        lob.get("lob_name") or lob.get("name") or lob.get("line_of_business_name") or lob.get("label"),
        f"LOB {lob_idx + 1}",
      )
      products = lob.get("products") if isinstance(lob.get("products"), list) else []
      for product_idx, product in enumerate(products):
        if not isinstance(product, dict):
          continue
        product_name = _named_product(
          product.get("product_name") or product.get("name") or product.get("unit_name"),
          f"Product {product_idx + 1}",
        )
        catalog[(lob_idx, product_idx)] = {
          "revenue_slot_key": _revenue_slot_key(lob_idx, product_idx),
          "lob_slot_index": lob_idx,
          "product_slot_index": product_idx,
          "lob": lob_name,
          "product": product_name,
          "capacity": _quarter_capacity_from_ops_product(product=product, ops_json=ops),
          "unit_price": _safe_float(product.get("unit_price") if product.get("unit_price") is not None else ops.get("unit_price")),
          "utilization": _safe_ratio(product.get("utilization_rate") if product.get("utilization_rate") is not None else ops.get("utilization_rate")),
        }
  if catalog:
    return catalog
  catalog[(0, 0)] = {
    "revenue_slot_key": _revenue_slot_key(0, 0),
    "lob_slot_index": 0,
    "product_slot_index": 0,
    "lob": _named_lob(ops.get("business_type") or ops.get("lob_name"), "LOB 1"),
    "product": _named_product(ops.get("product_name") or ops.get("unit_name"), "Product 1"),
    "capacity": _quarter_capacity_from_ops_product(product=ops, ops_json=ops),
    "unit_price": _safe_float(ops.get("unit_price")),
    "utilization": _safe_ratio(ops.get("utilization_rate")),
  }
  return catalog


def _infer_revenue_driver_map_from_forecast_quarter(
  *,
  quarter_slot: Dict[str, Any],
  ops_catalog: Dict[Tuple[int, int], Dict[str, Any]],
  revenue_slot_key: str,
  lob: str,
  product: str,
  fallback_detail: Optional[Dict[str, Any]],
) -> Dict[str, float]:
  slot = quarter_slot if isinstance(quarter_slot, dict) else {}
  target_revenue = max(0.0, _safe_float(slot.get("revenue")) or 0.0)
  slot_details = [item for item in (ops_catalog or {}).values() if isinstance(item, dict)]
  if not slot_details and isinstance(fallback_detail, dict):
    slot_details = [fallback_detail]
  if not slot_details:
    return {}

  normalized: List[Tuple[Dict[str, Any], float, float, float, float]] = []
  matched: Optional[Tuple[Dict[str, Any], float, float, float, float]] = None
  total_baseline_revenue = 0.0
  for detail in slot_details:
    capacity = max(0.0, _safe_float(detail.get("capacity")) or 0.0)
    price = max(0.0, _safe_float(detail.get("unit_price")) or 0.0)
    utilization = max(0.0, _safe_ratio(detail.get("utilization")) or 0.0)
    baseline_revenue = max(0.0, capacity * price * utilization)
    row = (detail, baseline_revenue, capacity, price, utilization)
    normalized.append(row)
    total_baseline_revenue += baseline_revenue
    if (
      str(detail.get("revenue_slot_key") or "").strip() == str(revenue_slot_key or "").strip()
      or (
        str(detail.get("lob") or "").strip() == str(lob or "").strip()
        and str(detail.get("product") or "").strip() == str(product or "").strip()
      )
    ):
      matched = row

  if matched is None:
    matched = normalized[0]
  matched_detail, matched_baseline_revenue, _matched_capacity, matched_price, matched_utilization = matched
  if total_baseline_revenue > 0:
    revenue_share = matched_baseline_revenue / total_baseline_revenue
  else:
    revenue_share = 1.0 / float(len(normalized))
  allocated_revenue = target_revenue * revenue_share
  effective_price = max(0.0, matched_price)
  effective_utilization = max(0.0, matched_utilization)
  if effective_price <= 0.0:
    effective_price = max(1.0, _safe_float(matched_detail.get("unit_price")) or 0.0)
  if effective_utilization <= 0.0:
    effective_utilization = max(1.0, _safe_ratio(matched_detail.get("utilization")) or 0.0)
  denominator = effective_price * effective_utilization
  inferred_capacity = (allocated_revenue / denominator) if denominator > 0 else 0.0
  return {
    "Capacity": round(max(0.0, inferred_capacity), 6),
    "Unit Price": round(max(0.0, effective_price), 6),
    "Utilization": round(max(0.0, effective_utilization), 6),
  }


def _quarter_capacity_from_ops_product(*, product: Dict[str, Any], ops_json: Dict[str, Any]) -> float:
  product_obj = product if isinstance(product, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  periods_per_year = _safe_float(
    product_obj.get("operating_periods_per_year")
    if product_obj.get("operating_periods_per_year") is not None else ops.get("operating_periods_per_year")
  )
  units_per_period = _safe_float(
    product_obj.get("units_per_period_capacity")
    if product_obj.get("units_per_period_capacity") is not None else ops.get("units_per_period_capacity")
  )
  if units_per_period is not None and periods_per_year not in (None, 0.0):
    return round((units_per_period * periods_per_year) / 4.0, 6)
  units_per_week = _safe_float(
    product_obj.get("units_per_week_capacity")
    if product_obj.get("units_per_week_capacity") is not None else ops.get("units_per_week_capacity")
  )
  if units_per_week is not None:
    return round(units_per_week * 13.0, 6)
  units_per_month = _safe_float(
    product_obj.get("units_per_month_capacity")
    if product_obj.get("units_per_month_capacity") is not None else ops.get("units_per_month_capacity")
  )
  if units_per_month is not None:
    return round(units_per_month * 3.0, 6)
  concurrent_units = _safe_float(
    product_obj.get("concurrent_capacity_units")
    if product_obj.get("concurrent_capacity_units") is not None else ops.get("concurrent_capacity_units")
  )
  return round(concurrent_units or 0.0, 6)


def _resolve_row_identity_from_catalog(
  *,
  row_lob: Any,
  row_product: Any,
  ops_catalog: Dict[Tuple[int, int], Dict[str, Any]],
  revenue_slot_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
  if str(revenue_slot_key or "").strip():
    for catalog_item in ops_catalog.values():
      if not isinstance(catalog_item, dict):
        continue
      if str(catalog_item.get("revenue_slot_key") or "").strip() == str(revenue_slot_key or "").strip():
        return _clone(catalog_item)
  slot_identity = _revenue_slot_identity(row_lob=row_lob, row_product=row_product)
  resolved = ops_catalog.get((int(slot_identity.get("lob_slot_index") or 0), int(slot_identity.get("product_slot_index") or 0)))
  return _clone(resolved) if isinstance(resolved, dict) else None


def _child_driver_map_for_quarter(quarter: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, float]]:
  child_map: Dict[Tuple[str, str], Dict[str, float]] = {}
  lobs = quarter.get("lobs") if isinstance(quarter.get("lobs"), list) else []
  for lob_idx, lob in enumerate(lobs):
    if not isinstance(lob, dict):
      continue
    products = lob.get("products") if isinstance(lob.get("products"), list) else []
    for product_idx, product in enumerate(products):
      if not isinstance(product, dict):
        continue
      capacity = _safe_float(product.get("capacity_units"))
      utilization = _safe_float(product.get("utilization"))
      units = _safe_float(product.get("units"))
      price = _safe_float(product.get("price")) or _safe_float(product.get("unit_price"))
      if capacity is None and units is not None and utilization not in (None, 0.0):
        capacity = units / utilization
      driver_payload = {
        "Capacity": round(capacity or 0.0, 6),
        "Unit Price": round(price or 0.0, 6),
        "Utilization": round(utilization or 0.0, 6),
      }
      revenue_slot_key = str(product.get("revenue_slot_key") or lob.get("revenue_slot_key") or _revenue_slot_key(lob_idx, product_idx)).strip()
      if revenue_slot_key:
        child_map[("__slot__", revenue_slot_key)] = _clone(driver_payload)
      child_map[(f"LOB {lob_idx + 1}", f"Product {product_idx + 1}")] = driver_payload
      lob_name = _named_lob(lob.get("lob_name") or lob.get("name") or lob.get("label"), f"LOB {lob_idx + 1}")
      product_name = _named_product(product.get("product_name") or product.get("name") or product.get("unit_name"), f"Product {product_idx + 1}")
      child_map[(lob_name, product_name)] = _clone(driver_payload)
  if child_map:
    return child_map
  capacity = _safe_float(quarter.get("capacity_units"))
  utilization = _safe_float(quarter.get("utilization"))
  units = _safe_float(quarter.get("units"))
  price = _safe_float(quarter.get("price"))
  if capacity is None and units is not None and utilization not in (None, 0.0):
    capacity = units / utilization
  return {
    ("LOB 1", "Product 1"): {
      "Capacity": round(capacity or 0.0, 6),
      "Unit Price": round(price or 0.0, 6),
      "Utilization": round(utilization or 0.0, 6),
    }
  }


def _quarter_lease_amount(financials_json: Dict[str, Any]) -> float:
  monthly_rent = _safe_float((financials_json or {}).get("monthly_rent_expense")) or 0.0
  return round(monthly_rent * 3.0, 6)


def _non_rent_g_and_a_year1(financials_json: Dict[str, Any]) -> float:
  """Return the intake's non-rent operating overhead used for G&A percent."""
  financials = financials_json if isinstance(financials_json, dict) else {}
  contract = _mapping_formula_contract_for_lever("expenses::General & Administrative")
  if isinstance(contract, dict):
    try:
      return max(
        0.0,
        float(
          apply_seed_formula(
            formula_contract=contract,
            context={
              "financials": financials,
              "annual_revenue": 1.0,
            },
            default_value=0.0,
          )
        ),
      )
    except Exception:
      pass
  value = (
    _safe_float(financials.get("other_opex_absolute"))
    or _safe_float(financials.get("other_operating_expense"))
    or 0.0
  )
  return max(0.0, float(value or 0.0))


def _table_seed_ratio_for_lever(
  lever_id: str,
  *,
  financials_json: Dict[str, Any],
  annual_revenue: Any,
  default_value: Any = 0.0,
) -> float:
  contract = _mapping_formula_contract_for_lever(lever_id)
  if not isinstance(contract, dict):
    return float(default_value or 0.0)
  return float(
    apply_seed_formula(
      formula_contract=contract,
      context={
        "financials": financials_json if isinstance(financials_json, dict) else {},
        "annual_revenue": annual_revenue,
      },
      default_value=default_value,
    )
  )


def _add_months(base: datetime, months: int) -> datetime:
  month_index = (base.month - 1) + int(months or 0)
  year = base.year + (month_index // 12)
  month = (month_index % 12) + 1
  day = min(
    base.day,
    [
      31,
      29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
      31,
      30,
      31,
      30,
      31,
      31,
      30,
      31,
      30,
      31,
    ][month - 1],
  )
  return base.replace(year=year, month=month, day=day)


def _python_model_input_periods(*, start_date_iso: Optional[str], period_count: int = 20) -> List[Dict[str, Any]]:
  normalized_start = _as_iso_date(start_date_iso) or _forecast_anchor_date_iso()
  try:
    start_dt = datetime.fromisoformat(normalized_start)
  except Exception:
    start_dt = datetime.utcnow()
    normalized_start = start_dt.date().isoformat()
  live_period_count = max(0, int(period_count or 0))
  slots: List[Dict[str, Any]] = [
    {
      "slot_index": 0,
      "column_index": 7,
      "column_letter": _column_letter(7),
      "year": float(start_dt.year),
      "quarter": 0.0,
      "date": normalized_start,
      "year_fraction": 0.0,
      "is_stub": True,
    }
  ]
  for slot_index in range(live_period_count):
    period_date = _add_months(start_dt, slot_index * 3)
    column_index = 8 + slot_index
    slots.append(
      {
        "slot_index": slot_index + 1,
        "column_index": column_index,
        "column_letter": _column_letter(column_index),
        "year": float(period_date.year),
        "quarter": float(slot_index + 1),
        "date": period_date.date().isoformat(),
        "year_fraction": 1.0,
        "is_stub": False,
      }
    )
  return slots


def _empty_controller_write_row(
  *,
  quarter_scope: Dict[str, Any],
  named_range: str,
  section_key: str,
  label: str,
) -> Dict[str, Any]:
  semantics = _simple_input_semantics(section_key, label)
  return {
    "named_range": named_range,
    "controller_write": True,
    "lever_id": _simple_lever_id(section_key, label),
    "label": label,
    **semantics,
    **quarter_scope,
    "values": [0.0 for _ in range(max(0, int(quarter_scope.get("total_period_count") or len(quarter_scope.get("valid_quarter_indices") or []))))],
  }


def _python_model_input_template(
  *,
  start_date_iso: Optional[str],
  business_start_date_iso: Optional[str] = None,
  business_name: Optional[str],
  ops_json: Dict[str, Any],
) -> Dict[str, Any]:
  periods = _python_model_input_periods(start_date_iso=start_date_iso, period_count=20)
  quarter_scope = _full_quarter_scope(periods)
  revenue_catalog = _ops_revenue_catalog(ops_json or {})
  revenue_items = sorted(
    [item for item in revenue_catalog.values() if isinstance(item, dict)],
    key=lambda item: (
      _safe_int(item.get("lob_slot_index")),
      _safe_int(item.get("product_slot_index")),
      str(item.get("revenue_slot_key") or "").strip(),
    ),
  )
  controller_write_levers: List[Dict[str, Any]] = []
  lever_catalog: Dict[str, Dict[str, Any]] = {}

  def _register_lever(metadata: Dict[str, Any]) -> None:
    lever_id = str(metadata.get("lever_id") or "").strip()
    if not lever_id:
      return
    lever_meta = {
      **_clone(metadata),
      **quarter_scope,
    }
    lever_catalog[lever_id] = lever_meta
    controller_write_levers.append(_clone(lever_meta))

  revenue_rows: List[Dict[str, Any]] = []
  for item in revenue_items:
    lob_name = str(item.get("lob") or "").strip() or "LOB 1"
    product_name = str(item.get("product") or "").strip() or "Product 1"
    revenue_slot_key = str(item.get("revenue_slot_key") or "").strip()
    base_meta = {
      "named_range": "model_input_revenue",
      "controller_write": True,
      "placeholder_lob": lob_name,
      "placeholder_product": product_name,
      "lob_slot_index": _safe_int(item.get("lob_slot_index")),
      "product_slot_index": _safe_int(item.get("product_slot_index")),
      "revenue_slot_key": revenue_slot_key,
      "lob": lob_name,
      "product": product_name,
      **quarter_scope,
      "values": [0.0 for _ in range(max(0, int(quarter_scope.get("total_period_count") or len(quarter_scope.get("valid_quarter_indices") or []))))],
    }
    for driver_name in ("Capacity", "Unit Price", "Utilization"):
      semantics = _revenue_input_semantics(driver_name)
      lever_id = _revenue_lever_id(lob_name, product_name, driver_name)
      revenue_rows.append(
        {
          **_clone(base_meta),
          "lever_id": lever_id,
          "driver": driver_name,
          **semantics,
        }
      )
      _register_lever(
        {
          "lever_id": lever_id,
          "named_range": "model_input_revenue",
          "section": "revenue",
          "lob": lob_name,
          "product": product_name,
          "driver": driver_name,
          "placeholder_lob": lob_name,
          "placeholder_product": product_name,
          "lob_slot_index": _safe_int(item.get("lob_slot_index")),
          "product_slot_index": _safe_int(item.get("product_slot_index")),
          "revenue_slot_key": revenue_slot_key,
          "label_path": f"{lob_name} > {product_name} > {driver_name}",
          **semantics,
        }
      )

  expenses = [
    "Cost of Goods Sold",
    "Marketing",
    "Research & Development",
    "Lease",
    "Payroll",
    "General & Administrative",
    "Interest Rate",
    "Depreciation",
    "Taxes",
  ]
  expense_rows = [
    _empty_controller_write_row(
      quarter_scope=quarter_scope,
      named_range="model_input_expenses",
      section_key="expenses",
      label=label,
    )
    for label in expenses
  ]
  for row in expense_rows:
    if str(row.get("label") or "").strip() == "Payroll":
      row["controller_write"] = False
      row["derived_driver"] = _PAYROLL_HEADCOUNT_SOURCE
      continue
    _register_lever(
      {
        "lever_id": str(row.get("lever_id") or "").strip(),
        "named_range": "model_input_expenses",
        "section": "expenses",
        "label": str(row.get("label") or "").strip(),
        "label_path": str(row.get("label") or "").strip(),
        "value_kind": str(row.get("value_kind") or "").strip(),
        "input_semantics": str(row.get("input_semantics") or "").strip(),
      }
    )

  balance_sheet = [
    "Accounts Receivable Days",
    "Inventory Days",
    "Accounts Payable Days",
    "Prepaid Expenses (% of Revenue)",
    "Deferred Revenue (% of Revenue)",
    "Short Term Debt (% of LTD)",
    "Owner's Capital",
    "Distributions",
    "Other Equity",
  ]
  balance_rows = [
    _empty_controller_write_row(
      quarter_scope=quarter_scope,
      named_range="model_input_balancehseet",
      section_key="balance_sheet",
      label=label,
    )
    for label in balance_sheet
  ]
  for row in balance_rows:
    _register_lever(
      {
        "lever_id": str(row.get("lever_id") or "").strip(),
        "named_range": "model_input_balancehseet",
        "section": "balance_sheet",
        "label": str(row.get("label") or "").strip(),
        "label_path": str(row.get("label") or "").strip(),
        "value_kind": str(row.get("value_kind") or "").strip(),
        "input_semantics": str(row.get("input_semantics") or "").strip(),
      }
    )

  schedule_labels = [
    DEBT_ISSUANCE_LABEL,
    DEBT_REPAYMENT_LABEL,
    "Capital Expenditures",
    "Less: Principal Repayments",
    "Plus: Net Additions",
  ]
  schedule_rows = [
    _empty_controller_write_row(
      quarter_scope=quarter_scope,
      named_range="model_input_schedules",
      section_key="schedules",
      label=label,
    )
    for label in schedule_labels
  ]
  for row in schedule_rows:
    row_label = str(row.get("label") or "").strip()
    _register_lever(
      {
        "lever_id": str(row.get("lever_id") or "").strip(),
        "named_range": "model_input_schedules",
        "section": "schedules",
        "label": row_label,
        "label_path": row_label,
        "value_kind": str(row.get("value_kind") or "").strip(),
        "input_semantics": str(row.get("input_semantics") or "").strip(),
      }
    )

  return {
    "contract_version": "finmo_model_input_v3",
    "canonical_lever_vocabulary": "model_inputs_controller_write_only",
    "finmo_path": "",
    "business_name": str(business_name or "").strip(),
    "start_date": _as_iso_date(start_date_iso) or _forecast_anchor_date_iso(),
    "business_start_date": _as_iso_date(business_start_date_iso),
    "periods": periods,
    "lever_catalog": lever_catalog,
    "controller_write_levers": controller_write_levers,
    "sections": {
      "revenue": revenue_rows,
      "expenses": expense_rows,
      "balance_sheet": balance_rows,
      "schedules": {
        "debt_opening_balance_seed": 0.0,
        "lease_opening_balance_seed": 0.0,
        "ppe_opening_balance_seed": 0.0,
        "client_reported_ppe_stub": 0.0,
        "forecast_ppe_opening_balance_seed": 0.0,
        "accumulated_depreciation_opening_seed": 0.0,
        "cash_opening_balance_seed": 0.0,
        "accounts_receivable_opening_balance_seed": 0.0,
        "inventory_opening_balance_seed": 0.0,
        "accounts_payable_opening_balance_seed": 0.0,
        "short_term_debt_opening_balance_seed": 0.0,
        "rows": schedule_rows,
      },
    },
  }


def build_python_model_input_json(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  marketing_model_json: Optional[Dict[str, Any]],
  forecast_starting_ppe: Optional[float],
  maintenance_rate: Optional[float],
  controller_input_seed: Optional[Sequence[Dict[str, Any]]] = None,
  forecast_quarters: Sequence[Dict[str, Any]] = (),
  business_name: Optional[str] = None,
) -> Dict[str, Any]:
  business_start_date = _as_iso_date((business_facts or {}).get("start_date")) or _as_iso_date((ops_json or {}).get("start_date"))
  forecast_start_date = _forecast_anchor_date_iso()
  baseline_model_input = _python_model_input_template(
    start_date_iso=forecast_start_date,
    business_start_date_iso=business_start_date,
    business_name=business_name or (business_facts or {}).get("business_name") or (ops_json or {}).get("business_name"),
    ops_json=ops_json or {},
  )
  return _build_model_input_overlay(
    baseline_model_input=baseline_model_input,
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    people_json=people_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    marketing_model_json=marketing_model_json or {},
    forecast_starting_ppe=forecast_starting_ppe,
    maintenance_rate=maintenance_rate,
    controller_input_seed=controller_input_seed,
    forecast_quarters=forecast_quarters,
  )


def _build_model_input_overlay(
  *,
  baseline_model_input: Dict[str, Any],
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  forecast_starting_ppe: Optional[float],
  maintenance_rate: Optional[float],
  controller_input_seed: Optional[Sequence[Dict[str, Any]]] = None,
  forecast_quarters: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
  next_payload = _clone(baseline_model_input if isinstance(baseline_model_input, dict) else {})
  periods = [item for item in (next_payload.get("periods") or []) if isinstance(item, dict)]
  full_periods = _full_quarter_slots(periods)
  seed_slots = [item for item in (controller_input_seed or []) if isinstance(item, dict)]
  target_period_count = len(full_periods) or len(periods)
  if seed_slots:
    slots = [_clone(item) for item in seed_slots[:target_period_count]]
    if len(slots) < target_period_count:
      fallback_slots = _planned_quarter_slots(target_period_count, forecast_quarters)
      slots.extend(_clone(fallback_slots[idx]) for idx in range(len(slots), target_period_count))
  else:
    slots = _planned_quarter_slots(target_period_count, forecast_quarters)
  projection_mode = bool(seed_slots) or bool([item for item in (forecast_quarters or []) if isinstance(item, dict)])
  forecast_start_date = _forecast_anchor_date_iso()
  next_payload["start_date"] = forecast_start_date
  business_start_date = _as_iso_date((business_facts or {}).get("start_date")) or _as_iso_date((ops_json or {}).get("start_date"))
  if business_start_date:
    next_payload["business_start_date"] = business_start_date

  sections = next_payload.setdefault("sections", {})
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  ops_catalog = _ops_revenue_catalog(ops_json or {})
  quarter_child_maps = [
    _child_driver_map_for_quarter({"lobs": (slot.get("revenue_products") or []) if isinstance(slot, dict) else []})
    if seed_slots else
    _child_driver_map_for_quarter(slot if isinstance(slot, dict) else {})
    for slot in slots
  ]
  for row in revenue_rows:
    revenue_slot_key = str(row.get("revenue_slot_key") or "").strip()
    placeholder_lob = str(row.get("placeholder_lob") or row.get("lob") or "").strip()
    placeholder_product = str(row.get("placeholder_product") or row.get("product") or "").strip()
    base_stub_value, _base_live_values = _row_stub_and_live_values(row.get("values") or [], live_count=len(slots))
    resolved_identity = _resolve_row_identity_from_catalog(
      row_lob=placeholder_lob,
      row_product=placeholder_product,
      ops_catalog=ops_catalog,
      revenue_slot_key=revenue_slot_key,
    )
    if isinstance(resolved_identity, dict):
      row["lob"] = resolved_identity.get("lob") or row.get("lob")
      row["product"] = resolved_identity.get("product") or row.get("product")
      row["revenue_slot_key"] = resolved_identity.get("revenue_slot_key") or row.get("revenue_slot_key")
      row["lob_slot_index"] = resolved_identity.get("lob_slot_index") if resolved_identity.get("lob_slot_index") is not None else row.get("lob_slot_index")
      row["product_slot_index"] = resolved_identity.get("product_slot_index") if resolved_identity.get("product_slot_index") is not None else row.get("product_slot_index")
    lob = str(row.get("lob") or placeholder_lob).strip()
    product = str(row.get("product") or placeholder_product).strip()
    driver = str(row.get("driver") or "").strip()
    intake_stub_value = base_stub_value
    baseline_driver_map = (
      (resolved_identity or {})
      if isinstance(resolved_identity, dict) else {}
    )
    if driver == "Capacity":
      intake_stub_value = round(_safe_float(baseline_driver_map.get("capacity")) or base_stub_value or 0.0, 6)
    elif driver == "Unit Price":
      intake_stub_value = round(_safe_float(baseline_driver_map.get("unit_price")) or base_stub_value or 0.0, 6)
    elif driver == "Utilization":
      intake_stub_value = round(_safe_ratio(baseline_driver_map.get("utilization")) or base_stub_value or 0.0, 6)
    values: List[float] = []
    if projection_mode:
      for slot_idx, child_map in enumerate(quarter_child_maps):
        driver_map = (
          child_map.get(("__slot__", str(row.get("revenue_slot_key") or "").strip()))
          or
          child_map.get((lob, product))
          or child_map.get((placeholder_lob, placeholder_product))
          or {}
        )
        if not driver_map:
          driver_map = _infer_revenue_driver_map_from_forecast_quarter(
            quarter_slot=(slots[slot_idx] if slot_idx < len(slots) and isinstance(slots[slot_idx], dict) else {}),
            ops_catalog=ops_catalog,
            revenue_slot_key=str(row.get("revenue_slot_key") or "").strip(),
            lob=lob,
            product=product,
            fallback_detail=resolved_identity if isinstance(resolved_identity, dict) else None,
          )
        values.append(round(_safe_float(driver_map.get(driver)) or 0.0, 6))
    else:
      baseline_value = 0.0
      if driver == "Capacity":
        baseline_value = round(_safe_float(baseline_driver_map.get("capacity")) or 0.0, 6)
      elif driver == "Unit Price":
        baseline_value = round(_safe_float(baseline_driver_map.get("unit_price")) or 0.0, 6)
      elif driver == "Utilization":
        baseline_value = round(_safe_ratio(baseline_driver_map.get("utilization")) or 0.0, 6)
      values = [baseline_value for _ in slots]
    row["values"] = _compose_period_values(
      stub_value=intake_stub_value,
      live_values=values,
    )

  lease_amount = _quarter_lease_amount(financials_json or {})
  revenue_total_year1 = max(
    0.0,
    _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
    or _safe_float((financials_year1_json or {}).get("revenue_total_year1"))
    or _safe_float((financials_json or {}).get("current_revenue"))
    or 0.0,
  )
  cogs_ratio_baseline = _cogs_ratio_from_financials(financials_json, revenue_total_year1)
  # Module 1 Tasks 1.3-1.5: NAICS-cascade substitution for forecast Q1-Q20
  # ONLY. Stub 0 (= intake fact per Part 9.1) keeps the intake-derived values
  # below; the *_forecast variables carry the substituted target into the
  # forecast slot loop. When no NAICS coverage / applicability fails / no
  # naics_6 available, the *_forecast variables stay equal to the *_baseline
  # variables and the silent zero is preserved as a legitimate zero.
  naics_6 = _naics_6_from_ops(ops_json)
  naics_2 = naics_6[:2] if naics_6 and len(naics_6) >= 2 else None
  baseline_substitution_provenance: Dict[str, Dict[str, Any]] = {}
  cogs_ratio_forecast = cogs_ratio_baseline
  if cogs_ratio_forecast <= 0.0:
    band = _naics_substitute_ratio("cogs_percent_of_revenue", naics_6)
    if band:
      cogs_ratio_forecast = float(band["benchmark_target"])
      baseline_substitution_provenance["cogs_percent_of_revenue"] = band
  marketing_ratio_baseline = (
    _safe_ratio((marketing_model_json or {}).get("marketing_percent_of_revenue"))
    if isinstance(marketing_model_json, dict) else None
  )
  if marketing_ratio_baseline is None:
    marketing_ratio_baseline = _safe_ratio((financials_json or {}).get("marketing_percent_of_revenue"))
  marketing_ratio_forecast = marketing_ratio_baseline
  if not marketing_ratio_forecast:
    # NOTE: replaced by marketing schedule in Module 6.
    band = _naics_substitute_ratio("marketing_percent_of_revenue", naics_6)
    if band:
      marketing_ratio_forecast = float(band["benchmark_target"])
      baseline_substitution_provenance["marketing_percent_of_revenue"] = band
  r_and_d_ratio_baseline = (
    _safe_ratio((financials_json or {}).get("r_and_d_percent"))
    or _safe_ratio((financials_json or {}).get("research_and_development_percent"))
    or _safe_ratio((financials_json or {}).get("rd_percent_of_revenue"))
    or 0.0
  )
  payroll_total_year1 = (
    _safe_float((financials_json or {}).get("payroll_total_year1"))
    or _safe_float((financials_json or {}).get("current_payroll"))
    or 0.0
  )
  if payroll_total_year1 <= 0:
    payroll_total_year1 = sum(
      max(0.0, _safe_float(item.get("annual_wage")) or 0.0)
      for item in ((people_json or {}).get("people") or [])
      if isinstance(item, dict)
    )
  quarterly_payroll = round(max(0.0, payroll_total_year1) / 4.0, 6) if payroll_total_year1 else 0.0
  non_rent_opex_year1 = _non_rent_g_and_a_year1(financials_json or {})
  g_and_a_ratio_baseline = _table_seed_ratio_for_lever(
    "expenses::General & Administrative",
    financials_json=financials_json or {},
    annual_revenue=revenue_total_year1,
    default_value=_ratio(non_rent_opex_year1, revenue_total_year1),
  )
  intake_interest_rate_stub = _ratio(
    (financials_json or {}).get("annual_interest_payment"),
    (financials_json or {}).get("total_debt_outstanding"),
  )
  interest_rate_baseline, interest_rate_source = _sba_business_loan_interest_rate_and_source(
    ops_json,
    financials_json,
  )
  # Module 1 Task 1.5: NAICS-cascade tax rate substitution. Stub 0 keeps the
  # intake-derived value (None -> falls back to base_stub_value below);
  # forecast quarters use tax_rate_forecast.
  intake_tax_rate = _safe_ratio((financials_json or {}).get("taxes_percent"))
  tax_rate_forecast: Optional[float] = intake_tax_rate
  if not tax_rate_forecast:
    band = _naics_substitute_ratio("effective_tax_rate", naics_6)
    if band:
      tax_rate_forecast = float(band["benchmark_target"])
      baseline_substitution_provenance["effective_tax_rate"] = band
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  for row in expense_rows:
    label = str(row.get("label") or "").strip()
    base_stub_value, base_live_values = _row_stub_and_live_values(row.get("values") or [], live_count=len(slots))
    intake_stub_value = base_stub_value
    if label == "Cost of Goods Sold":
      intake_stub_value = round(cogs_ratio_baseline, 6)
    elif label == "Marketing":
      intake_stub_value = round(marketing_ratio_baseline or 0.0, 6)
    elif label == "Research & Development":
      intake_stub_value = round(r_and_d_ratio_baseline, 6)
    elif label == "Lease":
      intake_stub_value = round(lease_amount, 6)
    elif label == "Payroll":
      intake_stub_value = round(quarterly_payroll, 6)
    elif label == "General & Administrative":
      intake_stub_value = round(max(0.0, g_and_a_ratio_baseline), 6)
    elif label == "Interest Rate":
      intake_stub_value = round(intake_interest_rate_stub, 6)
    elif label == "Taxes":
      intake_stub_value = round(_safe_ratio((financials_json or {}).get("taxes_percent")) or base_stub_value or 0.0, 6)
    values: List[float] = []
    for slot in slots:
      revenue = _safe_float(slot.get("revenue")) or 0.0
      if seed_slots and label == "Cost of Goods Sold":
        values.append(round(_safe_float(slot.get("cogs_percent")) or 0.0, 6))
      elif seed_slots and label == "Marketing":
        values.append(round(_safe_float(slot.get("marketing_percent")) or 0.0, 6))
      elif seed_slots and label == "Research & Development":
        values.append(round(_safe_float(slot.get("r_and_d_percent")) or 0.0, 6))
      elif seed_slots and label == "Lease":
        values.append(round(_safe_float(slot.get("lease_amount")) or 0.0, 6))
      elif seed_slots and label == "Payroll":
        values.append(round(_safe_float(slot.get("payroll_amount")) or 0.0, 6))
      elif seed_slots and label == "General & Administrative":
        values.append(round(_safe_float(slot.get("g_and_a_percent")) or 0.0, 6))
      elif seed_slots and label == "Interest Rate":
        values.append(round(interest_rate_baseline, 6))
      elif seed_slots and label == "Depreciation":
        values.append(0.0)
      elif seed_slots and label == "Taxes":
        values.append(round(_safe_float(slot.get("tax_percent")) or 0.0, 6))
      elif label == "Cost of Goods Sold":
        if projection_mode:
          projected = _ratio(slot.get("cogs"), revenue)
          # Module 1 Task 1.3: substitute when projection-mode produced 0
          # (intake omitted COGS AND quarter grid plan did not fill it).
          if projected <= 0.0 and cogs_ratio_forecast > 0.0:
            projected = cogs_ratio_forecast
          values.append(round(projected, 6))
        else:
          values.append(round(cogs_ratio_forecast, 6))
      elif label == "Marketing":
        if projection_mode:
          projected = _ratio(slot.get("marketing"), revenue)
          # Module 1 Task 1.5.
          if projected <= 0.0 and (marketing_ratio_forecast or 0.0) > 0.0:
            projected = float(marketing_ratio_forecast or 0.0)
          values.append(round(projected, 6))
        else:
          values.append(round(marketing_ratio_forecast or 0.0, 6))
      elif label == "Research & Development":
        values.append(0.0)
      elif label == "Lease":
        values.append(round(lease_amount, 6))
      elif label == "Payroll":
        values.append(round(quarterly_payroll if not projection_mode else (_safe_float(slot.get("payroll")) or 0.0), 6))
      elif label == "General & Administrative":
        values.append(round(max(0.0, g_and_a_ratio_baseline if not projection_mode else _ratio((_safe_float(slot.get("opex")) or 0.0) - lease_amount, revenue)), 6))
      elif label == "Interest Rate":
        values.append(round(interest_rate_baseline, 6))
      elif label == "Depreciation":
        values.append(0.0)
      elif label == "Taxes":
        if projection_mode:
          projected = _safe_ratio((financials_json or {}).get("taxes_percent")) or _ratio(slot.get("taxes"), revenue)
          # Module 1 Task 1.5.
          if (not projected or projected <= 0.0) and (tax_rate_forecast or 0.0) > 0.0:
            projected = float(tax_rate_forecast or 0.0)
          values.append(round(projected or 0.0, 6))
        else:
          values.append(round(tax_rate_forecast or 0.0, 6))
      else:
        values.append(base_live_values[0] if base_live_values else 0.0)
    # Module 1: stamp NAICS-cascade provenance on rows whose forecast values
    # were substituted. Stub 0 is unchanged; provenance describes the seed
    # source for forecast Q1-Q20.
    if label == "Cost of Goods Sold" and "cogs_percent_of_revenue" in baseline_substitution_provenance:
      _attach_seed_provenance(row, baseline_substitution_provenance["cogs_percent_of_revenue"])
    elif label == "Marketing" and "marketing_percent_of_revenue" in baseline_substitution_provenance:
      _attach_seed_provenance(row, baseline_substitution_provenance["marketing_percent_of_revenue"])
    elif label == "Taxes" and "effective_tax_rate" in baseline_substitution_provenance:
      _attach_seed_provenance(row, baseline_substitution_provenance["effective_tax_rate"])
    row["values"] = _compose_period_values(
      stub_value=intake_stub_value,
      live_values=values,
    )

  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  ar_balance_seed = max(0.0, _safe_float((financials_json or {}).get("ar_balance")) or 0.0)
  inventory_balance_seed = max(0.0, _safe_float((financials_json or {}).get("inventory_balance")) or 0.0)
  ap_balance_seed = max(0.0, _safe_float((financials_json or {}).get("ap_balance")) or 0.0)
  days_in_quarter = 90.0
  deferred_revenue_applicable = _deferred_revenue_applicable(ops_json or {}, financials_json or {})
  # Module 1 Tasks 1.4 + 1.6: NAICS-cascade days/percent substitution for the
  # working-capital and Tier-D balance-sheet lines. Each `*_days_band` is the
  # resolver payload (or None when no coverage / applicability rejects). Stub
  # 0 rows below keep base_stub_value untouched.
  ar_days_band = _naics_substitute_ratio("ar_days_dso", naics_6)
  ap_days_band = _naics_substitute_ratio("ap_days_dpo", naics_6)
  inventory_days_band = _naics_substitute_ratio(
    "inventory_days", naics_6, applicability_naics_2=naics_2
  )
  prepaid_pct_band = _naics_substitute_ratio("prepaid_expenses_percent_of_revenue", naics_6)
  deferred_pct_band = _naics_substitute_ratio(
    "deferred_revenue_percent_of_revenue",
    naics_6,
    applicability_naics_2=naics_2,
  ) if deferred_revenue_applicable else None
  for row in balance_rows:
    label = str(row.get("label") or "").strip()
    values: List[float] = []
    base_stub_value, base_values = _row_stub_and_live_values(row.get("values") or [], live_count=len(slots))
    for slot_idx, slot in enumerate(slots):
      working_capital = slot.get("working_capital") if isinstance(slot.get("working_capital"), dict) else {}
      revenue = max(0.0, _safe_float(slot.get("revenue")) or 0.0)
      cogs = max(0.0, _safe_float(slot.get("cogs")) or 0.0)
      marketing = max(0.0, _safe_float(slot.get("marketing")) or 0.0)
      r_and_d = max(0.0, _safe_float(slot.get("r_and_d")) or 0.0)
      lease = max(0.0, _safe_float(slot.get("lease_amount")) or 0.0)
      payroll = max(0.0, _safe_float(slot.get("payroll_amount")) or 0.0)
      g_and_a = max(0.0, _safe_float(slot.get("g_and_a")) or 0.0)
      ap_expense_base = marketing + r_and_d + lease + payroll + g_and_a
      if label == "Accounts Receivable Days":
        # Stub 0 (Q0) preserves the intake-implied days from `ar_balance` —
        # that's the intake fact and is set elsewhere. The Q1+ trajectory
        # uses NAICS days (per master diagnostic Part 12.6: "Tier A for
        # stub 0; NAICS for trajectory"). Explicit working-capital input
        # from intake still wins when present (operator-provided override).
        explicit_value = _safe_float(working_capital.get("dso"))
        if explicit_value is not None and explicit_value > 0.0:
          values.append(round(explicit_value, 6))
        elif revenue > 0.0 and ar_days_band:
          values.append(round(float(ar_days_band["benchmark_target"]), 6))
        elif revenue > 0.0 and ar_balance_seed > 0.0:
          # No NAICS coverage; Tier A intake-implied days is the last-resort
          # anchor. Realism gate will surface any out-of-band result.
          values.append(round((ar_balance_seed / revenue) * days_in_quarter, 6))
        else:
          values.append(0.0)
      elif label == "Inventory Days":
        explicit_value = _safe_float(working_capital.get("inventory_days"))
        if explicit_value is not None and explicit_value > 0.0:
          values.append(round(explicit_value, 6))
        elif cogs > 0.0 and inventory_days_band:
          # NAICS owns the trajectory. Software-style sectors keep 0 via
          # NAICS-2 applicability gate (band returns no_coverage there).
          values.append(round(float(inventory_days_band["benchmark_target"]), 6))
        elif cogs > 0.0 and inventory_balance_seed > 0.0:
          # No NAICS coverage; Tier A intake-implied days as the last
          # resort, only when COGS is present (inventory makes sense).
          values.append(round((inventory_balance_seed / cogs) * days_in_quarter, 6))
        else:
          values.append(0.0)
      elif label == "Accounts Payable Days":
        explicit_value = _safe_float(working_capital.get("dpo"))
        if explicit_value is not None and explicit_value > 0.0:
          values.append(round(explicit_value, 6))
        elif ap_expense_base > 0.0 and ap_days_band:
          # NAICS owns the Q1+ trajectory.
          values.append(round(float(ap_days_band["benchmark_target"]), 6))
        elif ap_expense_base > 0.0 and ap_balance_seed > 0.0:
          # No NAICS coverage; Tier A intake-implied days is the last resort.
          values.append(round((ap_balance_seed / ap_expense_base) * days_in_quarter, 6))
        else:
          values.append(0.0)
      elif label == "Prepaid Expenses (% of Revenue)":
        existing = (
          _safe_float(base_values[min(slot_idx, len(base_values) - 1)])
          if base_values
          else None
        )
        if existing is not None and existing > 0.0:
          values.append(round(existing, 6))
        elif revenue > 0.0 and prepaid_pct_band:
          # Module 1 Task 1.6.
          values.append(round(float(prepaid_pct_band["benchmark_target"]), 6))
        else:
          values.append(0.0)
      elif label == "Deferred Revenue (% of Revenue)":
        existing = (
          _safe_float(base_values[min(slot_idx, len(base_values) - 1)])
          if base_values
          else None
        )
        if existing is not None and existing > 0.0:
          values.append(round(existing, 6))
        elif revenue > 0.0 and deferred_pct_band:
          # Module 1 Task 1.6: gated by `_deferred_revenue_applicable` AND
          # NAICS-2 sector applicability.
          values.append(round(float(deferred_pct_band["benchmark_target"]), 6))
        else:
          values.append(0.0)
      elif label == "Short Term Debt (% of LTD)":
        short_term_ratio = _ratio((financials_json or {}).get("short_term_debt"), (financials_json or {}).get("total_debt_outstanding"))
        values.append(round(short_term_ratio, 6))
      elif label == "Owner's Capital":
        opening_equity = round(_safe_float((financials_json or {}).get("initial_equity")) or base_stub_value or 0.0, 6)
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or opening_equity, 6) if base_values else opening_equity)
      elif label == "Distributions":
        values.append(0.0)
      elif label == "Other Equity":
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
      else:
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
    if label == "Deferred Revenue (% of Revenue)":
      row["mapping_table_presence_applicability"] = {
        "source_table": "post_intak_mapping_lookup",
        "lever_id": "balance_sheet::Deferred Revenue (% of Revenue)",
        "business_applicability_key": "deferred_revenue_business",
        "applicable": bool(deferred_revenue_applicable),
      }
    # Module 1: stamp NAICS-cascade provenance on balance-sheet rows that
    # were forecast-substituted.
    if label == "Accounts Receivable Days" and ar_days_band:
      _attach_seed_provenance(row, ar_days_band)
    elif label == "Accounts Payable Days" and ap_days_band:
      _attach_seed_provenance(row, ap_days_band)
    elif label == "Inventory Days" and inventory_days_band:
      _attach_seed_provenance(row, inventory_days_band)
    elif label == "Prepaid Expenses (% of Revenue)" and prepaid_pct_band:
      _attach_seed_provenance(row, prepaid_pct_band)
    elif label == "Deferred Revenue (% of Revenue)" and deferred_pct_band:
      _attach_seed_provenance(row, deferred_pct_band)
    if label == "Owner's Capital":
      stub_value = round(_safe_float((financials_json or {}).get("initial_equity")) or base_stub_value or 0.0, 6)
    elif label == "Other Equity":
      stub_value = round(base_stub_value, 6)
    elif label == "Distributions":
      stub_value = 0.0
    else:
      stub_value = round(base_stub_value, 6)
    row["values"] = _compose_period_values(
      stub_value=stub_value,
      live_values=values,
    )

  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  debt_seed = _safe_float((financials_json or {}).get("total_debt_outstanding"))
  if debt_seed is not None:
    schedules["debt_opening_balance_seed"] = round(debt_seed, 6)
  lease_seed = _annualized_lease_commitment((financials_json or {}).get("initial_lease"))
  if lease_seed is not None:
    schedules["lease_opening_balance_seed"] = round(lease_seed, 6)
  client_ppe_seed = _safe_float((financials_json or {}).get("initial_assets")) or 0.0
  forecast_ppe_seed = _safe_float(forecast_starting_ppe)
  if forecast_ppe_seed is None:
    raise ValueError(
      "forecast_starting_ppe_missing: authoritative client balance-sheet initial_assets is required before model_input can seed forecast PPE."
    )
  if round(max(0.0, float(forecast_ppe_seed)), 6) != round(max(0.0, float(client_ppe_seed)), 6):
    raise ValueError(
      "forecast_starting_ppe_must_equal_authoritative_balance_sheet: "
      f"forecast_ppe_seed={forecast_ppe_seed} client_ppe_seed={client_ppe_seed}."
    )
  schedules["ppe_opening_balance_seed"] = round(max(0.0, client_ppe_seed), 6)
  schedules["client_reported_ppe_stub"] = round(max(0.0, client_ppe_seed), 6)
  schedules["forecast_ppe_opening_balance_seed"] = round(max(0.0, forecast_ppe_seed), 6)
  accum_dep_seed = _safe_float((financials_json or {}).get("accumulated_depreciation"))
  if accum_dep_seed is None:
    accum_dep_seed = 0.0
  schedules["accumulated_depreciation_opening_seed"] = round(-abs(accum_dep_seed), 6)
  schedules["cash_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("cash_on_hand")) or 0.0), 6)
  schedules["accounts_receivable_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("ar_balance")) or 0.0), 6)
  schedules["inventory_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("inventory_balance")) or 0.0), 6)
  schedules["accounts_payable_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("ap_balance")) or 0.0), 6)
  schedules["short_term_debt_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("short_term_debt")) or 0.0), 6)
  explicit_capex_overrides: Dict[int, float] = {}
  for quarter_index, slot in enumerate(slots, start=1):
    if not isinstance(slot, dict):
      continue
    raw_capex = slot.get("capex")
    if raw_capex in {None, ""}:
      continue
    explicit_capex_overrides[quarter_index] = round(max(0.0, _safe_float(raw_capex) or 0.0), 6)
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    label = str(row.get("label") or "").strip()
    base_stub_value, base_values = _row_stub_and_live_values(row.get("values") or [], live_count=len(slots))
    if label == DEBT_ISSUANCE_LABEL:
      row["values"] = _compose_period_values(stub_value=max(0.0, base_stub_value), live_values=[0.0 for _ in slots])
    elif label == DEBT_REPAYMENT_LABEL:
      row["values"] = _compose_period_values(stub_value=max(0.0, base_stub_value), live_values=[0.0 for _ in slots])
    elif label == LEGACY_NET_DEBT_LABEL:
      row["values"] = _compose_period_values(stub_value=base_stub_value, live_values=[0.0 for _ in slots])
    elif label == "Capital Expenditures":
      row["values"] = _compose_period_values(
        stub_value=base_stub_value,
        live_values=[explicit_capex_overrides.get(idx, 0.0) for idx in range(1, len(slots) + 1)],
      )
    elif label == "Less: Principal Repayments":
      annual_principal = _safe_float((financials_json or {}).get("annual_principal_payment")) or 0.0
      quarterly = round(max(0.0, annual_principal) / 4.0, 6) if annual_principal else 0.0
      row["values"] = _compose_period_values(
        stub_value=base_stub_value,
        live_values=[quarterly for _ in slots],
      )
    elif label == "Plus: Net Additions":
      row["values"] = _compose_period_values(stub_value=base_stub_value, live_values=[0.0 for _ in slots])
    else:
      row["values"] = _compose_period_values(
        stub_value=base_stub_value,
        live_values=[round(_safe_float(base_values[min(idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0 for idx, _slot in enumerate(slots)],
      )
  sections["schedules"] = schedules
  next_payload.setdefault("derived_driver_policies", {})
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"][_PAYROLL_HEADCOUNT_LEVER_ID] = default_payroll_headcount_policy(
      financials_json=financials_json,
      ops_json=ops_json,
    )
    next_payload["derived_driver_policies"][_CAPEX_DEPRECIATION_POLICY_KEY] = _default_capex_depreciation_policy(
      financials_json=financials_json,
      ops_json=ops_json,
      forecast_starting_ppe=forecast_ppe_seed,
      maintenance_rate=maintenance_rate,
      explicit_capex_overrides=explicit_capex_overrides,
    )
    next_payload["derived_driver_policies"]["debt_interest_rate_policy"] = {
      "policy_version": "sba_7a_business_loan_interest_rate_v1",
      "driver_source": "sba_loan_7a_raw",
      "lever_id": "expenses::Interest Rate",
      "annual_rate_decimal": round(float(interest_rate_baseline), 6),
      "source_detail": deepcopy(interest_rate_source),
      "finmo_formula_unchanged": True,
      "finmo_formula": "interest = ((debt_opening + debt_closing) / 2) * expenses::Interest Rate",
    }
  return apply_derived_driver_policies_to_model_input(next_payload)


def normalize_model_input_forecast_anchor(
  model_input_json: Dict[str, Any],
  *,
  anchor_date_iso: Optional[str] = None,
) -> Dict[str, Any]:
  if not isinstance(model_input_json, dict) or not model_input_json:
    return {}
  next_payload = _clone(model_input_json)
  normalized_anchor = _as_iso_date(anchor_date_iso) or _forecast_anchor_date_iso()
  raw_periods = [item for item in (next_payload.get("periods") or []) if isinstance(item, dict)]
  period_count = len(_full_quarter_slots(raw_periods)) or len(raw_periods) or 20
  next_payload["start_date"] = normalized_anchor
  next_payload["periods"] = _python_model_input_periods(
    start_date_iso=normalized_anchor,
    period_count=period_count,
  )
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  if not isinstance(sections, dict):
    sections = {}
    next_payload["sections"] = sections
  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  retained_balance_rows: List[Dict[str, Any]] = []
  legacy_ppe_row: Optional[Dict[str, Any]] = None
  legacy_accum_dep_row: Optional[Dict[str, Any]] = None
  for row in balance_rows:
    label = str(row.get("label") or "").strip()
    if label == "PPE $ (Excluding Capital Leases)":
      legacy_ppe_row = _clone(row)
      continue
    if label == "Accumulated Depreciation":
      legacy_accum_dep_row = _clone(row)
      continue
    retained_balance_rows.append(_clone(row))
  has_distributions_row = any(
    str(row.get("label") or "").strip() == "Distributions"
    for row in retained_balance_rows
  )
  if not has_distributions_row:
    retained_balance_rows.insert(
      7 if len(retained_balance_rows) >= 7 else len(retained_balance_rows),
      {
        "named_range": "model_input_balancehseet",
        "controller_write": True,
        "lever_id": "balance_sheet::Distributions",
        "label": "Distributions",
        "value_kind": "direct_number",
        "input_semantics": "quarter_currency",
        "values": [0.0 for _ in range(period_count + 1)],
      },
    )
  sections["balance_sheet"] = retained_balance_rows

  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  if not isinstance(schedules, dict):
    schedules = {}
  schedule_rows = _normalize_schedule_rows_for_explicit_debt_controls(
    [row for row in (schedules.get("rows") or []) if isinstance(row, dict)],
    period_count=period_count,
  )
  has_capex_row = any(str(row.get("label") or "").strip() == "Capital Expenditures" for row in schedule_rows)
  if not has_capex_row:
    schedule_rows.insert(
      2 if len(schedule_rows) >= 2 else len(schedule_rows),
      _schedule_row_template(
        label="Capital Expenditures",
        period_count=period_count,
      ),
    )
  if schedules.get("ppe_opening_balance_seed") in {None, ""}:
    legacy_ppe_values = list((legacy_ppe_row or {}).get("values") or [])
    schedules["ppe_opening_balance_seed"] = round(max(0.0, _safe_float(legacy_ppe_values[0]) or 0.0), 6) if legacy_ppe_values else 0.0
  if schedules.get("accumulated_depreciation_opening_seed") in {None, ""}:
    legacy_accum_values = list((legacy_accum_dep_row or {}).get("values") or [])
    if legacy_accum_values:
      schedules["accumulated_depreciation_opening_seed"] = round(-abs(_safe_float(legacy_accum_values[0]) or 0.0), 6)
    else:
      schedules["accumulated_depreciation_opening_seed"] = 0.0
  sections["schedules"] = {
    **schedules,
    "rows": schedule_rows,
  }
  return apply_derived_driver_policies_to_model_input(next_payload)


def sync_planning_state_to_finmo(
  *,
  finmo_path: Any,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  marketing_model_json: Optional[Dict[str, Any]],
  forecast_starting_ppe: Optional[float],
  maintenance_rate: Optional[float],
  controller_input_seed: Optional[Sequence[Dict[str, Any]]] = None,
  forecast_quarters: Sequence[Dict[str, Any]],
  calibration_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  path = str(finmo_path or "").strip()
  model_input_json = build_python_model_input_json(
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    people_json=people_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    marketing_model_json=marketing_model_json or {},
    forecast_starting_ppe=forecast_starting_ppe,
    maintenance_rate=maintenance_rate,
    controller_input_seed=controller_input_seed or [],
    forecast_quarters=forecast_quarters or [],
    business_name=str((business_facts or {}).get("business_name") or "").strip(),
  )
  finmo_json = build_python_finmo_json(
    model_input_json=model_input_json,
    finmo_path=path,
  )
  calibration_results: Dict[str, Any] = {}
  if isinstance(calibration_spec, dict) and calibration_spec:
    calibration_results = {
      "success": False,
      "status": "python_finmo_calibration_not_supported",
      "request_present": True,
    }
    model_input_json["calibration_results"] = _clone(calibration_results)
    finmo_json["calibration_results"] = _clone(calibration_results)
  return {
    "finmo_path": path,
    "model_input_json": model_input_json,
    "finmo_json": finmo_json,
  }

