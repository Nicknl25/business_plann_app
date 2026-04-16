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
  if driver_text == "capacity":
    return {"value_kind": "direct_number", "input_semantics": "quarter_capacity_units"}
  if driver_text == "unit price":
    return {"value_kind": "direct_number", "input_semantics": "currency_per_unit"}
  if driver_text == "utilization":
    return {"value_kind": "ratio", "input_semantics": "utilization_ratio"}
  return {"value_kind": "direct_number", "input_semantics": "direct_input"}


def _simple_input_semantics(section_key: str, label: str) -> Dict[str, str]:
  normalized_section = _canonical_model_input_text(section_key).lower()
  normalized_label = _canonical_model_input_text(label).lower()
  if normalized_section == "expenses":
    if normalized_label in {
      "cost of goods sold",
      "marketing",
      "research & development",
      "general & administrative",
      "interest rate",
      "depreciation",
      "taxes",
    }:
      return {"value_kind": "ratio", "input_semantics": "percent_of_revenue"}
    if normalized_label in {"lease", "payroll"}:
      return {"value_kind": "direct_number", "input_semantics": "quarter_currency"}
  if normalized_section == "balance_sheet":
    if normalized_label in {"accounts receivable days", "inventory days", "accounts payable days"}:
      return {"value_kind": "day_count", "input_semantics": "days"}
    if normalized_label in {"prepaid expenses", "deferred revnue"}:
      return {"value_kind": "ratio", "input_semantics": "percent_of_revenue"}
    if normalized_label == "short term debt (% of ltd)":
      return {"value_kind": "ratio", "input_semantics": "percent_of_long_term_debt"}
    if normalized_label in {"owner's capital", "other equity"}:
      return {"value_kind": "direct_number", "input_semantics": "quarter_currency"}
  if normalized_section == "schedules":
    if normalized_label == "plus: additions (repayments), net":
      return {"value_kind": "direct_number", "input_semantics": "net_debt_additions_repayments"}
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
  book = FinancialModelInputs.from_model_input_json(model_input_json if isinstance(model_input_json, dict) else {})
  result = calculate_finmo_model(book)
  quarter_rows_raw = result.quarter_rows()
  quarter_rows_with_stub = result.quarter_rows(include_stub=True)
  raw_periods = [
    _clone(item)
    for item in (((model_input_json.get("periods") or []) if isinstance(model_input_json, dict) else []) or [])
    if isinstance(item, dict)
  ]
  periods: List[Dict[str, Any]] = []
  start_date_iso = _as_iso_date((model_input_json or {}).get("start_date")) if isinstance(model_input_json, dict) else None
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

  def _series(metric_key: str) -> List[float]:
    values: List[float] = []
    for row in quarter_rows_raw:
      if not isinstance(row, dict):
        continue
      values.append(round(_safe_float(row.get(metric_key)) or 0.0, 6))
    return values

  pl_rows = [
    {"label": "Revenue", "values": _series("revenue")},
    {"label": "Cost of Goods Sold", "values": _series("cost_of_goods_sold")},
    {"label": "Gross Profit", "values": _series("gross_profit")},
    {"label": "Marketing", "values": _series("marketing")},
    {"label": "Research & Development", "values": _series("research_and_development")},
    {"label": "Lease/Rent", "values": _series("lease_rent")},
    {"label": "Payroll", "values": _series("payroll")},
    {"label": "General & Administrative", "values": _series("general_and_administrative")},
    {"label": "EBITDA", "values": _series("ebitda")},
    {"label": "Interest", "values": _series("interest")},
    {"label": "Depreciation", "values": _series("depreciation")},
    {"label": "Taxes", "values": _series("taxes")},
    {"label": "Net Income", "values": _series("net_income")},
  ]
  balance_rows = [
    {"label": "Cash", "values": _series("cash")},
    {"label": "Accounts Receivable", "values": _series("accounts_receivable")},
    {"label": "Inventory", "values": _series("inventory")},
    {"label": "Current Assets", "values": _series("current_assets")},
    {"label": "PPE", "values": _series("ppe")},
    {"label": "Accumulated Depreciation", "values": _series("accumulated_depreciation")},
    {"label": "Total Assets", "values": _series("total_assets")},
    {"label": "Accounts Payable", "values": _series("accounts_payable")},
    {"label": "Prepaid Expenses (% of Revenue)", "values": _series("prepaid_expenses")},
    {"label": "Short Term Debt", "values": _series("short_term_debt")},
    {"label": "Deferred Revenue (% of Revenue)", "values": _series("deferred_revenue")},
    {"label": "Current Liabilites", "values": _series("current_liabilities")},
    {"label": "Long Term Debt", "values": _series("long_term_debt")},
    {"label": "Total Liabilities", "values": _series("total_liabilities")},
    {"label": "Owner's Capital", "values": _series("owners_capital")},
    {"label": "Retained Earnings", "values": _series("retained_earnings")},
    {"label": "Other Equity", "values": _series("other_equity")},
    {"label": "Total Equity", "values": _series("total_equity")},
    {"label": "Total Liabilities & Equity", "values": _series("total_liabilities_and_equity")},
  ]
  cfs_rows = [
    {"label": "Beginning Cash", "values": _series("beginning_cash")},
    {"label": "Net Income", "values": _series("net_income")},
    {"label": "Depreciatoin", "values": _series("depreciation")},
    {"label": "Changes in Current Assets", "values": _series("changes_in_current_assets")},
    {"label": "Changes in Current Liabilites", "values": _series("changes_in_current_liabilities")},
    {"label": "Operating Cash Flow", "values": _series("operating_cash_flow")},
    {"label": "Capital Expenditures", "values": _series("capital_expenditures")},
    {"label": "Investing Cash Flow", "values": _series("investing_cash_flow")},
    {"label": "Dept Receive(Repay)", "values": _series("debt_receive_repay")},
    {"label": "Equity", "values": _series("equity")},
    {"label": "Distributions", "values": _series("owner_distributions")},
    {"label": "Financing Cash Flow", "values": _series("financing_cash_flow")},
    {"label": "Net Cash Flow", "values": _series("net_cash_flow")},
    {"label": "Ending Cash", "values": _series("ending_cash")},
  ]
  numeric_values = _series("accounting_equation_check")
  tolerance = 1.0
  status_values = ["OK" if abs(value) <= tolerance else "FAIL" for value in numeric_values]
  quarter_rows: List[Dict[str, Any]] = []
  for idx, row in enumerate(quarter_rows_with_stub):
    if not isinstance(row, dict):
      continue
    quarter_rows.append(
      {
        "slot_index": idx,
        "quarter_index": int(row.get("quarter_index") or idx),
        "year": row.get("year"),
        "quarter": row.get("quarter"),
        "date": row.get("date"),
        "revenue": row.get("revenue"),
        "cogs": row.get("cost_of_goods_sold"),
        "gross_profit": row.get("gross_profit"),
        "marketing": row.get("marketing"),
        "research_and_development": row.get("research_and_development"),
        "lease_rent": row.get("lease_rent"),
        "payroll": row.get("payroll"),
        "g_and_a": row.get("general_and_administrative"),
        "ebitda": row.get("ebitda"),
        "interest": row.get("interest"),
        "depreciation": row.get("depreciation"),
        "taxes": row.get("taxes"),
        "net_income": row.get("net_income"),
        "cash": row.get("cash"),
        "ending_cash": row.get("ending_cash"),
        "total_assets": row.get("total_assets"),
        "total_liabilities_and_equity": row.get("total_liabilities_and_equity"),
      }
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
    "Plus: Additions (repayments), net",
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
      baseline_driver_map = (
        (resolved_identity or {})
        if isinstance(resolved_identity, dict) else {}
      )
      baseline_value = 0.0
      if driver == "Capacity":
        baseline_value = round(_safe_float(baseline_driver_map.get("capacity")) or 0.0, 6)
      elif driver == "Unit Price":
        baseline_value = round(_safe_float(baseline_driver_map.get("unit_price")) or 0.0, 6)
      elif driver == "Utilization":
        baseline_value = round(_safe_ratio(baseline_driver_map.get("utilization")) or 0.0, 6)
      values = [baseline_value for _ in slots]
    row["values"] = _compose_period_values(
      stub_value=base_stub_value,
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
  cogs_ratio_baseline = _ratio((financials_json or {}).get("cogs_total_year1"), revenue_total_year1)
  marketing_ratio_baseline = (
    _safe_ratio((marketing_model_json or {}).get("marketing_percent_of_revenue"))
    if isinstance(marketing_model_json, dict) else None
  )
  if marketing_ratio_baseline is None:
    marketing_ratio_baseline = _safe_ratio((financials_json or {}).get("marketing_percent_of_revenue"))
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
  non_rent_opex_year1 = max(
    0.0,
    (
      _safe_float((financials_json or {}).get("other_opex_absolute"))
      or _safe_float((financials_json or {}).get("other_operating_expense"))
      or 0.0
    ) - (lease_amount * 4.0)
  )
  g_and_a_ratio_baseline = _ratio(non_rent_opex_year1, revenue_total_year1)
  interest_rate_baseline = _ratio((financials_json or {}).get("annual_interest_payment"), (financials_json or {}).get("total_debt_outstanding"))
  depreciation_ratio_baseline = _ratio((financials_json or {}).get("accumulated_depreciation"), revenue_total_year1)
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  for row in expense_rows:
    label = str(row.get("label") or "").strip()
    base_stub_value, base_live_values = _row_stub_and_live_values(row.get("values") or [], live_count=len(slots))
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
        values.append(round(_safe_float(slot.get("interest_rate")) or 0.0, 6))
      elif seed_slots and label == "Depreciation":
        values.append(round(_safe_float(slot.get("depreciation_percent")) or 0.0, 6))
      elif seed_slots and label == "Taxes":
        values.append(round(_safe_float(slot.get("tax_percent")) or 0.0, 6))
      elif label == "Cost of Goods Sold":
        values.append(round(cogs_ratio_baseline if not projection_mode else _ratio(slot.get("cogs"), revenue), 6))
      elif label == "Marketing":
        values.append(round((marketing_ratio_baseline or 0.0) if not projection_mode else _ratio(slot.get("marketing"), revenue), 6))
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
        values.append(round(depreciation_ratio_baseline if not projection_mode else _ratio(slot.get("depreciation"), revenue), 6))
      elif label == "Taxes":
        values.append(round(_safe_ratio((financials_json or {}).get("taxes_percent")) or (_ratio(slot.get("taxes"), revenue) if projection_mode else 0.0), 6))
      else:
        values.append(base_live_values[0] if base_live_values else 0.0)
    row["values"] = _compose_period_values(
      stub_value=base_stub_value,
      live_values=values,
    )

  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  for row in balance_rows:
    label = str(row.get("label") or "").strip()
    values: List[float] = []
    base_stub_value, base_values = _row_stub_and_live_values(row.get("values") or [], live_count=len(slots))
    for slot_idx, slot in enumerate(slots):
      working_capital = slot.get("working_capital") if isinstance(slot.get("working_capital"), dict) else {}
      if label == "Accounts Receivable Days":
        values.append(round(_safe_float(working_capital.get("dso")) or 0.0, 6))
      elif label == "Inventory Days":
        values.append(round(_safe_float(working_capital.get("inventory_days")) or 0.0, 6))
      elif label == "Accounts Payable Days":
        values.append(round(_safe_float(working_capital.get("dpo")) or 0.0, 6))
      elif label == "Prepaid Expenses (% of Revenue)":
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
      elif label == "Deferred Revenue (% of Revenue)":
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
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
  ppe_seed = _safe_float((financials_json or {}).get("initial_assets")) or 0.0
  schedules["ppe_opening_balance_seed"] = round(max(0.0, ppe_seed), 6)
  accum_dep_seed = _safe_float((financials_json or {}).get("accumulated_depreciation"))
  if accum_dep_seed is None:
    accum_dep_seed = 0.0
  schedules["accumulated_depreciation_opening_seed"] = round(-abs(accum_dep_seed), 6)
  schedules["cash_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("cash_on_hand")) or 0.0), 6)
  schedules["accounts_receivable_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("ar_balance")) or 0.0), 6)
  schedules["inventory_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("inventory_balance")) or 0.0), 6)
  schedules["accounts_payable_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("ap_balance")) or 0.0), 6)
  schedules["short_term_debt_opening_balance_seed"] = round(max(0.0, _safe_float((financials_json or {}).get("short_term_debt")) or 0.0), 6)
  annual_capex = _safe_float((financials_json or {}).get("current_capex")) or 0.0
  quarterly_capex = round(max(0.0, annual_capex) / 4.0, 6) if annual_capex else 0.0
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    label = str(row.get("label") or "").strip()
    base_stub_value, base_values = _row_stub_and_live_values(row.get("values") or [], live_count=len(slots))
    if label == "Plus: Additions (repayments), net":
      row["values"] = _compose_period_values(stub_value=base_stub_value, live_values=[0.0 for _ in slots])
    elif label == "Capital Expenditures":
      if projection_mode:
        row["values"] = _compose_period_values(
          stub_value=base_stub_value,
          live_values=[round(max(0.0, _safe_float(slot.get("capex")) or 0.0), 6) for slot in slots],
        )
      else:
        row["values"] = _compose_period_values(
          stub_value=base_stub_value,
          live_values=[quarterly_capex for _ in slots],
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
  return next_payload


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
  schedule_rows = [row for row in (schedules.get("rows") or []) if isinstance(row, dict)]
  has_capex_row = any(str(row.get("label") or "").strip() == "Capital Expenditures" for row in schedule_rows)
  if not has_capex_row:
    schedule_rows.insert(
      1 if schedule_rows else 0,
      {
        "named_range": "model_input_schedules",
        "controller_write": True,
        "lever_id": "schedules::Capital Expenditures",
        "label": "Capital Expenditures",
        "value_kind": "direct_number",
        "input_semantics": "quarter_currency",
        "values": [0.0 for _ in range(period_count + 1)],
      },
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
  return next_payload


def sync_planning_state_to_finmo(
  *,
  finmo_path: Any,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  marketing_model_json: Optional[Dict[str, Any]],
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

