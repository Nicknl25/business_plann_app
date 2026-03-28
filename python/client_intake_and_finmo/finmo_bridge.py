from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.utils.datetime import from_excel


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


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
  try:
    return from_excel(numeric).date().isoformat()
  except Exception:
    return None


def _ratio(numerator: Any, denominator: Any) -> float:
  num = _safe_float(numerator) or 0.0
  den = _safe_float(denominator) or 0.0
  if abs(den) < 1e-9:
    return 0.0
  return num / den


def _clone(value: Any) -> Any:
  return deepcopy(value)


def _normalize_finmo_path(finmo_path: Any) -> str:
  cleaned = str(finmo_path or "").strip()
  if not cleaned:
    raise ValueError("finmo_path is required")
  return cleaned


def _defined_range_bounds(wb, name: str) -> Tuple[Any, int, int, int, int]:
  if name not in wb.defined_names:
    raise KeyError(f"Named range not found in workbook: {name}")
  destinations = list(wb.defined_names[name].destinations)
  if not destinations:
    raise ValueError(f"Named range has no destinations: {name}")
  sheet_name, ref = destinations[0]
  min_col, min_row, max_col, max_row = range_boundaries(ref)
  return wb[sheet_name], min_row, max_row, min_col, max_col


def _period_slots_from_model_inputs(wb) -> List[Dict[str, Any]]:
  ws, min_row, _max_row, min_col, max_col = _defined_range_bounds(wb, "model_input_periods")
  label_to_row: Dict[str, int] = {}
  for row_idx in range(min_row, min_row + 5):
    label = str(ws.cell(row=row_idx, column=min_col + 1).value or "").strip().lower()
    if label:
      label_to_row[label] = row_idx
  quarter_row = label_to_row.get("quarter")
  year_row = label_to_row.get("year")
  date_row = label_to_row.get("date")
  fraction_row = label_to_row.get("year fraction")
  if quarter_row is None or year_row is None:
    return []
  slots: List[Dict[str, Any]] = []
  slot_index = 0
  for col_idx in range(min_col + 2, max_col + 1):
    quarter_val = _safe_float(ws.cell(row=quarter_row, column=col_idx).value)
    year_val = _safe_float(ws.cell(row=year_row, column=col_idx).value)
    if quarter_val is None or year_val is None:
      continue
    slots.append(
      {
        "slot_index": slot_index,
        "column_index": col_idx,
        "column_letter": get_column_letter(col_idx),
        "year": year_val,
        "quarter": quarter_val,
        "date": _as_iso_date(ws.cell(row=date_row, column=col_idx).value) if date_row is not None else None,
        "year_fraction": _safe_float(ws.cell(row=fraction_row, column=col_idx).value) if fraction_row is not None else None,
      }
    )
    slot_index += 1
  return slots


def _period_slots_from_finmo(wb) -> List[Dict[str, Any]]:
  ws, min_row, _max_row, min_col, max_col = _defined_range_bounds(wb, "finmo_periods")
  label_to_row: Dict[str, int] = {}
  for row_idx in range(min_row, min_row + 3):
    label = str(ws.cell(row=row_idx, column=min_col).value or "").strip().lower()
    if label:
      label_to_row[label] = row_idx
  quarter_row = label_to_row.get("quarter")
  year_row = label_to_row.get("year")
  date_row = label_to_row.get("date")
  if quarter_row is None or year_row is None or date_row is None:
    return []
  slots: List[Dict[str, Any]] = []
  slot_index = 0
  for col_idx in range(min_col + 1, max_col + 1):
    quarter_val = ws.cell(row=quarter_row, column=col_idx).value
    if quarter_val in (None, ""):
      continue
    slots.append(
      {
        "slot_index": slot_index,
        "column_index": col_idx,
        "column_letter": get_column_letter(col_idx),
        "year": _safe_float(ws.cell(row=year_row, column=col_idx).value),
        "quarter": _safe_float(quarter_val),
        "date": _as_iso_date(ws.cell(row=date_row, column=col_idx).value),
      }
    )
    slot_index += 1
  return slots


def _read_named_cell(wb, name: str) -> Any:
  if name not in wb.defined_names:
    raise KeyError(f"Named range not found in workbook: {name}")
  destinations = list(wb.defined_names[name].destinations)
  if not destinations:
    raise ValueError(f"Named range has no destinations: {name}")
  sheet_name, cell_ref = destinations[0]
  return wb[sheet_name][cell_ref].value


def _write_named_cell(wb, name: str, value: Any) -> None:
  if name not in wb.defined_names:
    raise KeyError(f"Named range not found in workbook: {name}")
  destinations = list(wb.defined_names[name].destinations)
  if not destinations:
    raise ValueError(f"Named range has no destinations: {name}")
  sheet_name, cell_ref = destinations[0]
  wb[sheet_name][cell_ref].value = value


def _model_input_slot_for_full_quarter(slots: Sequence[Dict[str, Any]], quarter_index: int) -> Optional[Dict[str, Any]]:
  quarter_index = max(1, int(quarter_index or 1))
  full_slots = [slot for slot in (slots or []) if _safe_float(slot.get("quarter")) not in (None, 0.0)]
  if quarter_index <= len(full_slots):
    return full_slots[quarter_index - 1]
  return full_slots[-1] if full_slots else None


def _finmo_slot_for_full_quarter(slots: Sequence[Dict[str, Any]], quarter_index: int) -> Optional[Dict[str, Any]]:
  quarter_index = max(1, int(quarter_index or 1))
  full_slots = [slot for slot in (slots or []) if _safe_float(slot.get("quarter")) not in (None, 0.0)]
  if quarter_index <= len(full_slots):
    return full_slots[quarter_index - 1]
  return full_slots[-1] if full_slots else None


def _read_model_input_json(finmo_path: str) -> Dict[str, Any]:
  wb = load_workbook(finmo_path, data_only=False)
  try:
    slots = _period_slots_from_model_inputs(wb)
    slot_columns = [int(slot["column_index"]) for slot in slots]

    revenue_rows: List[Dict[str, Any]] = []
    ws, min_row, max_row, min_col, max_col = _defined_range_bounds(wb, "model_input_revenue")
    for row_idx in range(min_row, max_row + 1):
      controller_marker = str(ws.cell(row=row_idx, column=min_col).value or "").strip()
      if controller_marker.lower() != "controller write":
        continue
      revenue_rows.append(
        {
          "lob": str(ws.cell(row=row_idx, column=min_col + 2).value or "").strip(),
          "product": str(ws.cell(row=row_idx, column=min_col + 3).value or "").strip(),
          "driver": str(ws.cell(row=row_idx, column=min_col + 4).value or "").strip(),
          "values": [ws.cell(row=row_idx, column=col_idx).value for col_idx in slot_columns if col_idx <= max_col],
        }
      )

    def _read_simple_rows(range_name: str) -> List[Dict[str, Any]]:
      local_ws, local_min_row, local_max_row, local_min_col, local_max_col = _defined_range_bounds(wb, range_name)
      rows: List[Dict[str, Any]] = []
      for row_idx in range(local_min_row, local_max_row + 1):
        controller_marker = str(local_ws.cell(row=row_idx, column=local_min_col).value or "").strip()
        if controller_marker.lower() != "controller write":
          continue
        rows.append(
          {
            "label": str(local_ws.cell(row=row_idx, column=local_min_col + 1).value or "").strip(),
            "values": [local_ws.cell(row=row_idx, column=col_idx).value for col_idx in slot_columns if col_idx <= local_max_col],
          }
        )
      return rows

    schedule_ws, sched_min_row, sched_max_row, sched_min_col, sched_max_col = _defined_range_bounds(wb, "model_input_schedules")
    seed_col = slot_columns[0] - 1 if slot_columns else sched_min_col + 2
    schedule_rows = _read_simple_rows("model_input_schedules")

    return {
      "contract_version": "finmo_model_input_v1",
      "finmo_path": finmo_path,
      "start_date": _as_iso_date(_read_named_cell(wb, "model_input_startdate")),
      "periods": slots,
      "sections": {
        "revenue": revenue_rows,
        "expenses": _read_simple_rows("model_input_expenses"),
        "balance_sheet": _read_simple_rows("model_input_balancehseet"),
        "schedules": {
          "debt_opening_balance_seed": schedule_ws.cell(row=sched_min_row + 3, column=seed_col).value,
          "lease_opening_balance_seed": schedule_ws.cell(row=sched_min_row + 12, column=seed_col).value,
          "rows": schedule_rows,
        },
      },
    }
  finally:
    wb.close()


def _read_finmo_json(finmo_path: str) -> Dict[str, Any]:
  wb = load_workbook(finmo_path, data_only=True)
  try:
    slots = _period_slots_from_finmo(wb)
    slot_columns = [int(slot["column_index"]) for slot in slots]

    def _read_rows(range_name: str) -> List[Dict[str, Any]]:
      ws, min_row, max_row, min_col, max_col = _defined_range_bounds(wb, range_name)
      rows: List[Dict[str, Any]] = []
      for row_idx in range(min_row, max_row + 1):
        label = str(ws.cell(row=row_idx, column=min_col).value or "").strip()
        if not label:
          continue
        rows.append(
          {
            "label": label,
            "values": [ws.cell(row=row_idx, column=col_idx).value for col_idx in slot_columns if col_idx <= max_col],
          }
        )
      return rows

    accounting_rows = _read_rows("finmo_accountingcheck")
    pl_rows = _read_rows("finmo_pl")
    balance_rows = _read_rows("finmo_balancesheet")
    cfs_rows = _read_rows("finmo_cfs")

    row_maps = {
      "pl": {row["label"]: row["values"] for row in pl_rows},
      "balance": {row["label"]: row["values"] for row in balance_rows},
      "cfs": {row["label"]: row["values"] for row in cfs_rows},
    }
    quarter_rows: List[Dict[str, Any]] = []
    for slot in slots:
      idx = int(slot["slot_index"])
      quarter_rows.append(
        {
          "slot_index": idx,
          "year": slot.get("year"),
          "quarter": slot.get("quarter"),
          "date": slot.get("date"),
          "revenue": (row_maps["pl"].get("Revenue") or [None])[idx] if idx < len(row_maps["pl"].get("Revenue") or []) else None,
          "cogs": (row_maps["pl"].get("Cost of Goods Sold") or [None])[idx] if idx < len(row_maps["pl"].get("Cost of Goods Sold") or []) else None,
          "gross_profit": (row_maps["pl"].get("Gross Profit") or [None])[idx] if idx < len(row_maps["pl"].get("Gross Profit") or []) else None,
          "marketing": (row_maps["pl"].get("Marketing") or [None])[idx] if idx < len(row_maps["pl"].get("Marketing") or []) else None,
          "research_and_development": (row_maps["pl"].get("Research & Development") or [None])[idx] if idx < len(row_maps["pl"].get("Research & Development") or []) else None,
          "lease_rent": (row_maps["pl"].get("Lease/Rent") or [None])[idx] if idx < len(row_maps["pl"].get("Lease/Rent") or []) else None,
          "payroll": (row_maps["pl"].get("Payroll") or [None])[idx] if idx < len(row_maps["pl"].get("Payroll") or []) else None,
          "g_and_a": (row_maps["pl"].get("General & Administrative") or [None])[idx] if idx < len(row_maps["pl"].get("General & Administrative") or []) else None,
          "ebitda": (row_maps["pl"].get("EBITDA") or [None])[idx] if idx < len(row_maps["pl"].get("EBITDA") or []) else None,
          "interest": (row_maps["pl"].get("Interest") or [None])[idx] if idx < len(row_maps["pl"].get("Interest") or []) else None,
          "depreciation": (row_maps["pl"].get("Depreciation") or [None])[idx] if idx < len(row_maps["pl"].get("Depreciation") or []) else None,
          "taxes": (row_maps["pl"].get("Taxes") or [None])[idx] if idx < len(row_maps["pl"].get("Taxes") or []) else None,
          "net_income": (row_maps["pl"].get("Net Income") or [None])[idx] if idx < len(row_maps["pl"].get("Net Income") or []) else None,
          "cash": (row_maps["balance"].get("Cash") or [None])[idx] if idx < len(row_maps["balance"].get("Cash") or []) else None,
          "total_assets": (row_maps["balance"].get("Total Assets") or [None])[idx] if idx < len(row_maps["balance"].get("Total Assets") or []) else None,
          "total_liabilities_and_equity": (row_maps["balance"].get("Total Liabilities & Equity") or [None])[idx] if idx < len(row_maps["balance"].get("Total Liabilities & Equity") or []) else None,
          "ending_cash": (row_maps["cfs"].get("Ending Cash") or [None])[idx] if idx < len(row_maps["cfs"].get("Ending Cash") or []) else None,
        }
      )

    check_status_values = accounting_rows[0]["values"] if accounting_rows else []
    check_numeric_values = accounting_rows[1]["values"] if len(accounting_rows) > 1 else []
    all_ok = all(str(value or "").strip().upper() == "OK" for value in check_status_values if value not in (None, ""))

    return {
      "contract_version": "finmo_output_v1",
      "finmo_path": finmo_path,
      "periods": slots,
      "accounting_check": {
        "rows": accounting_rows,
        "all_ok": all_ok,
        "status_values": check_status_values,
        "numeric_values": check_numeric_values,
      },
      "pl": pl_rows,
      "balance_sheet": balance_rows,
      "cash_flow": cfs_rows,
      "quarter_rows": quarter_rows,
    }
  finally:
    wb.close()


def build_consistency_forecast_view_from_finmo(finmo_json: Dict[str, Any]) -> Dict[str, Any]:
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
      child_map[(f"LOB {lob_idx + 1}", f"Product {product_idx + 1}")] = {
        "Capacity": round(capacity or 0.0, 6),
        "Unit Price": round(price or 0.0, 6),
        "Utilization": round(utilization or 0.0, 6),
      }
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


def _build_model_input_overlay(
  *,
  baseline_model_input: Dict[str, Any],
  business_facts: Dict[str, Any],
  financials_json: Dict[str, Any],
  controller_input_seed: Optional[Sequence[Dict[str, Any]]] = None,
  forecast_quarters: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
  next_payload = _clone(baseline_model_input if isinstance(baseline_model_input, dict) else {})
  periods = [item for item in (next_payload.get("periods") or []) if isinstance(item, dict)]
  seed_slots = [item for item in (controller_input_seed or []) if isinstance(item, dict)]
  slots = seed_slots[:len(periods)] if seed_slots else _slot_quarters(len(periods), forecast_quarters)
  start_date = _as_iso_date((business_facts or {}).get("start_date"))
  if start_date:
    next_payload["start_date"] = start_date

  sections = next_payload.setdefault("sections", {})
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  quarter_child_maps = [
    _child_driver_map_for_quarter({"lobs": (slot.get("revenue_products") or []) if isinstance(slot, dict) else []})
    if seed_slots else
    _child_driver_map_for_quarter(slot if isinstance(slot, dict) else {})
    for slot in slots
  ]
  for row in revenue_rows:
    lob = str(row.get("lob") or "").strip()
    product = str(row.get("product") or "").strip()
    driver = str(row.get("driver") or "").strip()
    values: List[float] = []
    for child_map in quarter_child_maps:
      driver_map = child_map.get((lob, product)) or {}
      values.append(round(_safe_float(driver_map.get(driver)) or 0.0, 6))
    row["values"] = values

  lease_amount = _quarter_lease_amount(financials_json or {})
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  for row in expense_rows:
    label = str(row.get("label") or "").strip()
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
        values.append(round(_ratio(slot.get("cogs"), revenue), 6))
      elif label == "Marketing":
        values.append(round(_ratio(slot.get("marketing"), revenue), 6))
      elif label == "Research & Development":
        values.append(0.0)
      elif label == "Lease":
        values.append(round(lease_amount, 6))
      elif label == "Payroll":
        values.append(round(_safe_float(slot.get("payroll")) or 0.0, 6))
      elif label == "General & Administrative":
        values.append(round(max(0.0, _ratio((_safe_float(slot.get("opex")) or 0.0) - lease_amount, revenue)), 6))
      elif label == "Interest Rate":
        base_rate = _ratio((financials_json or {}).get("annual_interest_payment"), (financials_json or {}).get("total_debt_outstanding"))
        values.append(round(base_rate, 6))
      elif label == "Depreciation":
        values.append(round(_ratio(slot.get("depreciation"), revenue), 6))
      elif label == "Taxes":
        values.append(round(_ratio(slot.get("taxes"), revenue), 6))
      else:
        values.append(round(_safe_float((row.get("values") or [0.0])[0]) or 0.0, 6))
    row["values"] = values

  balance_rows = [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)]
  opening_ppe = _safe_float((financials_json or {}).get("current_capex"))
  if opening_ppe is None:
    opening_ppe = _safe_float((financials_json or {}).get("initial_assets")) or 0.0
  opening_accum_dep = _safe_float((financials_json or {}).get("accumulated_depreciation")) or 0.0
  cumulative_capex = 0.0
  cumulative_dep = 0.0
  for row in balance_rows:
    label = str(row.get("label") or "").strip()
    values: List[float] = []
    cumulative_capex = 0.0
    cumulative_dep = 0.0
    base_values = list(row.get("values") or [])
    for slot_idx, slot in enumerate(slots):
      working_capital = slot.get("working_capital") if isinstance(slot.get("working_capital"), dict) else {}
      cumulative_capex += _safe_float(slot.get("capex")) or 0.0
      cumulative_dep += _safe_float(slot.get("depreciation")) or 0.0
      if label == "Accounts Receivable Days":
        values.append(round(_safe_float(working_capital.get("dso")) or 0.0, 6))
      elif label == "Inventory Days":
        values.append(round(_safe_float(working_capital.get("inventory_days")) or 0.0, 6))
      elif label == "PPE $ (Excluding Capital Leases)":
        values.append(round(opening_ppe + cumulative_capex, 6))
      elif label == "Accumulated Depreciation":
        values.append(round(opening_accum_dep - cumulative_dep, 6))
      elif label == "Accounts Payable Days":
        values.append(round(_safe_float(working_capital.get("dpo")) or 0.0, 6))
      elif label == "Prepaid Expenses":
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
      elif label == "Deferred Revnue":
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
      elif label == "Short Term Debt (% of LTD)":
        short_term_ratio = _ratio((financials_json or {}).get("short_term_debt"), (financials_json or {}).get("total_debt_outstanding"))
        values.append(round(short_term_ratio, 6))
      elif label == "Owner's Capital":
        values.append(round(_safe_float((financials_json or {}).get("initial_equity")) or (_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0), 6) if base_values else round(_safe_float((financials_json or {}).get("initial_equity")) or 0.0, 6))
      elif label == "Other Equity":
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
      else:
        values.append(round(_safe_float(base_values[min(slot_idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0)
    row["values"] = values

  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  debt_seed = _safe_float((financials_json or {}).get("total_debt_outstanding"))
  if debt_seed is not None:
    schedules["debt_opening_balance_seed"] = round(debt_seed, 6)
  lease_seed = _safe_float((financials_json or {}).get("initial_lease"))
  if lease_seed is not None:
    schedules["lease_opening_balance_seed"] = round(lease_seed, 6)
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    label = str(row.get("label") or "").strip()
    base_values = list(row.get("values") or [])
    if label == "Plus: Additions (repayments), net":
      row["values"] = [0.0 for _ in slots]
    elif label == "Less: Principal Repayments":
      annual_principal = _safe_float((financials_json or {}).get("annual_principal_payment")) or 0.0
      quarterly = round(-(annual_principal / 4.0), 6) if annual_principal else 0.0
      row["values"] = [quarterly for _ in slots]
    elif label == "Plus: Net Additions":
      row["values"] = [0.0 for _ in slots]
    else:
      row["values"] = [round(_safe_float(base_values[min(idx, len(base_values) - 1)]) or 0.0, 6) if base_values else 0.0 for idx, _slot in enumerate(slots)]
  sections["schedules"] = schedules
  return next_payload


def _write_model_input_json_to_workbook(finmo_path: str, model_input_json: Dict[str, Any]) -> None:
  wb = load_workbook(finmo_path, data_only=False)
  try:
    period_slots = _period_slots_from_model_inputs(wb)
    period_columns = [int(slot["column_index"]) for slot in period_slots]
    if isinstance(model_input_json.get("start_date"), str) and str(model_input_json.get("start_date")).strip():
      _write_named_cell(wb, "model_input_startdate", str(model_input_json.get("start_date")).strip())

    revenue_section = [row for row in (((model_input_json.get("sections") or {}) if isinstance(model_input_json.get("sections"), dict) else {}).get("revenue") or []) if isinstance(row, dict)]
    ws, min_row, max_row, min_col, max_col = _defined_range_bounds(wb, "model_input_revenue")
    revenue_row_lookup: Dict[Tuple[str, str, str], int] = {}
    for row_idx in range(min_row, max_row + 1):
      marker = str(ws.cell(row=row_idx, column=min_col).value or "").strip().lower()
      if marker != "controller write":
        continue
      revenue_row_lookup[
        (
          str(ws.cell(row=row_idx, column=min_col + 2).value or "").strip(),
          str(ws.cell(row=row_idx, column=min_col + 3).value or "").strip(),
          str(ws.cell(row=row_idx, column=min_col + 4).value or "").strip(),
        )
      ] = row_idx
    for row in revenue_section:
      key = (str(row.get("lob") or "").strip(), str(row.get("product") or "").strip(), str(row.get("driver") or "").strip())
      row_idx = revenue_row_lookup.get(key)
      if row_idx is None:
        continue
      for idx, col_idx in enumerate(period_columns):
        if col_idx > max_col:
          continue
        values = row.get("values") or []
        ws.cell(row=row_idx, column=col_idx).value = values[idx] if idx < len(values) else 0

    def _write_simple_rows(range_name: str, rows_payload: Sequence[Dict[str, Any]]) -> None:
      local_ws, local_min_row, local_max_row, local_min_col, local_max_col = _defined_range_bounds(wb, range_name)
      label_lookup: Dict[str, int] = {}
      for row_idx in range(local_min_row, local_max_row + 1):
        marker = str(local_ws.cell(row=row_idx, column=local_min_col).value or "").strip().lower()
        if marker != "controller write":
          continue
        label_lookup[str(local_ws.cell(row=row_idx, column=local_min_col + 1).value or "").strip()] = row_idx
      for row in rows_payload:
        label = str(row.get("label") or "").strip()
        row_idx = label_lookup.get(label)
        if row_idx is None:
          continue
        values = list(row.get("values") or [])
        for idx, col_idx in enumerate(period_columns):
          if col_idx > local_max_col:
            continue
          local_ws.cell(row=row_idx, column=col_idx).value = values[idx] if idx < len(values) else 0

    sections = model_input_json.get("sections") if isinstance(model_input_json.get("sections"), dict) else {}
    _write_simple_rows("model_input_expenses", [row for row in (sections.get("expenses") or []) if isinstance(row, dict)])
    _write_simple_rows("model_input_balancehseet", [row for row in (sections.get("balance_sheet") or []) if isinstance(row, dict)])

    schedule_section = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
    schedule_ws, sched_min_row, sched_max_row, sched_min_col, sched_max_col = _defined_range_bounds(wb, "model_input_schedules")
    label_lookup: Dict[str, int] = {}
    for row_idx in range(sched_min_row, sched_max_row + 1):
      label = str(schedule_ws.cell(row=row_idx, column=sched_min_col + 1).value or "").strip()
      if label:
        label_lookup[label] = row_idx
    seed_col = period_columns[0] - 1 if period_columns else sched_min_col + 2
    debt_seed_row = label_lookup.get("Closing Balance")
    if debt_seed_row is not None and seed_col <= sched_max_col:
      debt_seed = schedule_section.get("debt_opening_balance_seed")
      if debt_seed is not None:
        schedule_ws.cell(row=debt_seed_row, column=seed_col).value = debt_seed
    lease_seed_row = label_lookup.get("Closing Balance (Total)")
    if lease_seed_row is not None and seed_col <= sched_max_col:
      lease_seed = schedule_section.get("lease_opening_balance_seed")
      if lease_seed is not None:
        schedule_ws.cell(row=lease_seed_row, column=seed_col).value = lease_seed
    for row in [item for item in (schedule_section.get("rows") or []) if isinstance(item, dict)]:
      label = str(row.get("label") or "").strip()
      row_idx = label_lookup.get(label)
      if row_idx is None:
        continue
      values = list(row.get("values") or [])
      for idx, col_idx in enumerate(period_columns):
        if col_idx > sched_max_col:
          continue
        schedule_ws.cell(row=row_idx, column=col_idx).value = values[idx] if idx < len(values) else 0

    wb.save(finmo_path)
  finally:
    wb.close()


def _resolve_finmo_calibration_shell(
  *,
  finmo_path: str,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  calibration_spec: Dict[str, Any],
) -> Dict[str, Any]:
  wb = load_workbook(finmo_path, data_only=False)
  try:
    model_slots = [item for item in (model_input_json.get("periods") or []) if isinstance(item, dict)]
    finmo_slots = [item for item in (finmo_json.get("periods") or []) if isinstance(item, dict)]

    def _resolve_model_input_cell(spec: Dict[str, Any]) -> Dict[str, Any]:
      section = str(spec.get("section") or "").strip().lower()
      quarter_index = _safe_int(spec.get("quarter_index")) or 1
      slot = _model_input_slot_for_full_quarter(model_slots, quarter_index)
      if slot is None:
        return {}
      if section == "revenue":
        ws, min_row, max_row, min_col, _max_col = _defined_range_bounds(wb, "model_input_revenue")
        for row_idx in range(min_row, max_row + 1):
          if str(ws.cell(row=row_idx, column=min_col).value or "").strip().lower() != "controller write":
            continue
          if (
            str(ws.cell(row=row_idx, column=min_col + 2).value or "").strip() == str(spec.get("lob") or "").strip()
            and str(ws.cell(row=row_idx, column=min_col + 3).value or "").strip() == str(spec.get("product") or "").strip()
            and str(ws.cell(row=row_idx, column=min_col + 4).value or "").strip() == str(spec.get("driver") or "").strip()
          ):
            col_idx = int(slot["column_index"])
            return {"sheet": ws.title, "cell": f"{get_column_letter(col_idx)}{row_idx}"}
      if section == "expenses":
        ws, min_row, max_row, min_col, _max_col = _defined_range_bounds(wb, "model_input_expenses")
        for row_idx in range(min_row, max_row + 1):
          if str(ws.cell(row=row_idx, column=min_col).value or "").strip().lower() != "controller write":
            continue
          if str(ws.cell(row=row_idx, column=min_col + 1).value or "").strip() == str(spec.get("label") or "").strip():
            col_idx = int(slot["column_index"])
            return {"sheet": ws.title, "cell": f"{get_column_letter(col_idx)}{row_idx}"}
      return {}

    def _resolve_finmo_output_cell(objective: Dict[str, Any]) -> Dict[str, Any]:
      range_name = str(objective.get("sheet_range") or "").strip()
      if not range_name:
        return {}
      ws, min_row, max_row, min_col, _max_col = _defined_range_bounds(wb, range_name)
      slot = _finmo_slot_for_full_quarter(finmo_slots, _safe_int(objective.get("quarter_index")) or 1)
      if slot is None:
        return {}
      for row_idx in range(min_row, max_row + 1):
        if str(ws.cell(row=row_idx, column=min_col).value or "").strip() == str(objective.get("line_item") or "").strip():
          col_idx = int(slot["column_index"])
          return {"sheet": ws.title, "cell": f"{get_column_letter(col_idx)}{row_idx}"}
      return {}

    next_shell = _clone(calibration_spec if isinstance(calibration_spec, dict) else {})
    for request in [item for item in (next_shell.get("goal_seek_requests") or []) if isinstance(item, dict)]:
      request["objective_cell"] = _resolve_finmo_output_cell((request.get("objective") or {}) if isinstance(request.get("objective"), dict) else {})
      request["changing_input_cells"] = [
        _resolve_model_input_cell(item)
        for item in (request.get("changing_inputs") or [])
        if isinstance(item, dict)
      ]
    for request in [item for item in (next_shell.get("solver_requests") or []) if isinstance(item, dict)]:
      request["objective_cell"] = _resolve_finmo_output_cell((request.get("objective") or {}) if isinstance(request.get("objective"), dict) else {})
      resolved_inputs = []
      resolved_constraints = [item for item in (request.get("constraints") or []) if isinstance(item, dict)]
      for item in (request.get("changing_inputs") or []):
        if not isinstance(item, dict):
          continue
        resolved = _resolve_model_input_cell(item)
        if not resolved:
          continue
        resolved_inputs.append(resolved)
        band = item.get("band") if isinstance(item.get("band"), dict) else {}
        min_value = _safe_float(band.get("min"))
        max_value = _safe_float(band.get("max"))
        if min_value is not None:
          resolved_constraints.append({"cell": f"{resolved.get('sheet')}!{resolved.get('cell')}", "relation": 3, "value": min_value})
        if max_value is not None:
          resolved_constraints.append({"cell": f"{resolved.get('sheet')}!{resolved.get('cell')}", "relation": 1, "value": max_value})
      for band_constraint in [item for item in (request.get("band_constraints") or []) if isinstance(item, dict)]:
        resolved_target = _resolve_finmo_output_cell((band_constraint.get("target") or {}) if isinstance(band_constraint.get("target"), dict) else {})
        if not resolved_target:
          continue
        goal_band = band_constraint.get("goal_band") if isinstance(band_constraint.get("goal_band"), dict) else {}
        min_value = _safe_float(goal_band.get("min"))
        max_value = _safe_float(goal_band.get("max"))
        if min_value is not None:
          resolved_constraints.append({"cell": f"{resolved_target.get('sheet')}!{resolved_target.get('cell')}", "relation": 3, "value": min_value})
        if max_value is not None:
          resolved_constraints.append({"cell": f"{resolved_target.get('sheet')}!{resolved_target.get('cell')}", "relation": 1, "value": max_value})
      request["changing_input_cells"] = resolved_inputs
      request["constraints"] = resolved_constraints
      request["execution_mode"] = "excel_solver_shell"
    return next_shell
  finally:
    wb.close()


def _execute_finmo_calibration_shell(
  *,
  finmo_path: str,
  calibration_shell: Dict[str, Any],
) -> Dict[str, Any]:
  shell = calibration_shell if isinstance(calibration_shell, dict) else {}
  goal_seek_requests: List[Dict[str, Any]] = []
  for request in [item for item in (shell.get("goal_seek_requests") or []) if isinstance(item, dict)]:
    objective_cell = (request.get("objective_cell") or {}) if isinstance(request.get("objective_cell"), dict) else {}
    changing_cells = [item for item in (request.get("changing_input_cells") or []) if isinstance(item, dict)]
    goal_value = _goal_value_from_band((((request.get("objective") or {}) if isinstance(request.get("objective"), dict) else {}).get("goal_band") or {}))
    if not objective_cell or not changing_cells or goal_value is None:
      continue
    goal_seek_requests.append(
      {
        "request_id": str(request.get("request_id") or "").strip(),
        "objective_cell": objective_cell,
        "changing_input_cell": changing_cells[0],
        "goal_value": goal_value,
      }
    )
  solver_requests: List[Dict[str, Any]] = []
  for request in [item for item in (shell.get("solver_requests") or []) if isinstance(item, dict)]:
    objective_cell = (request.get("objective_cell") or {}) if isinstance(request.get("objective_cell"), dict) else {}
    changing_cells = [item for item in (request.get("changing_input_cells") or []) if isinstance(item, dict)]
    if not objective_cell or not changing_cells:
      continue
    goal_band = (((request.get("objective") or {}) if isinstance(request.get("objective"), dict) else {}).get("goal_band") or {})
    solver_requests.append(
      {
        "request_id": str(request.get("request_id") or "").strip(),
        "objective_cell": objective_cell,
        "changing_input_cells": changing_cells,
        "target_value": _goal_value_from_band(goal_band if isinstance(goal_band, dict) else {}),
        "goal_band": _clone(goal_band if isinstance(goal_band, dict) else {}),
        "constraints": [item for item in (request.get("constraints") or []) if isinstance(item, dict)],
      }
    )
  if not goal_seek_requests and not solver_requests:
    return {"goal_seek_results": [], "solver_results": []}

  workbook_path = _normalize_finmo_path(finmo_path)
  payload = {
    "goal_seek_requests": goal_seek_requests,
    "solver_requests": solver_requests,
  }
  payload_json = json.dumps(payload)
  script = (
    "$path = " + json.dumps(workbook_path) + ";"
    "$payload = @'\n" + payload_json + "\n'@ | ConvertFrom-Json -Depth 100;"
    "$excel = New-Object -ComObject Excel.Application;"
    "$excel.Visible = $false;"
    "$excel.DisplayAlerts = $false;"
    "$goalResults = New-Object System.Collections.ArrayList;"
    "$solverResults = New-Object System.Collections.ArrayList;"
    "$wb = $null;"
    "try {"
    "$solver = $excel.AddIns.Item('Solver Add-in');"
    "if ($solver -and -not $solver.Installed) { $solver.Installed = $true }"
    "$wb = $excel.Workbooks.Open($path, $false, $false);"
    "foreach ($request in $payload.goal_seek_requests) {"
    "  $objectiveParts = $request.objective_cell.cell.ToString() -split '(?<=\\D)(?=\\d)';"
    "  $objectiveRange = $wb.Worksheets.Item($request.objective_cell.sheet).Range($request.objective_cell.cell);"
    "  $changingRange = $wb.Worksheets.Item($request.changing_input_cell.sheet).Range($request.changing_input_cell.cell);"
    "  $result = $objectiveRange.GoalSeek([double]$request.goal_value, $changingRange);"
    "  $excel.CalculateFullRebuild();"
    "  [void]$goalResults.Add(@{ request_id = $request.request_id; success = [bool]$result; goal_value = [double]$request.goal_value });"
    "}"
    "foreach ($request in $payload.solver_requests) {"
    "  $excel.Run('Solver.xlam!SolverReset');"
    "  $objectiveSpec = \"'\" + $request.objective_cell.sheet + \"'!\" + $request.objective_cell.cell;"
    "  $changeSpec = (($request.changing_input_cells | ForEach-Object { \"'\" + $_.sheet + \"'!\" + $_.cell }) -join ',');"
    "  if ($request.target_value -ne $null) {"
    "    $excel.Run('Solver.xlam!SolverOK', $objectiveSpec, 3, [double]$request.target_value, $changeSpec);"
    "  } else {"
    "    $excel.Run('Solver.xlam!SolverOK', $objectiveSpec, 2, $null, $changeSpec);"
    "  }"
    "  if ($request.goal_band.min -ne $null) { $excel.Run('Solver.xlam!SolverAdd', $objectiveSpec, 3, [double]$request.goal_band.min) }"
    "  if ($request.goal_band.max -ne $null) { $excel.Run('Solver.xlam!SolverAdd', $objectiveSpec, 1, [double]$request.goal_band.max) }"
    "  foreach ($constraint in $request.constraints) {"
    "    if (-not $constraint.cell) { continue }"
    "    $parts = $constraint.cell.ToString().Split('!');"
    "    $constraintSpec = \"'\" + $parts[0] + \"'!\" + $parts[1];"
    "    $excel.Run('Solver.xlam!SolverAdd', $constraintSpec, [int]$constraint.relation, $constraint.value);"
    "  }"
    "  $solveResult = $excel.Run('Solver.xlam!SolverSolve', $true);"
    "  $excel.Run('Solver.xlam!SolverFinish', 1);"
    "  $excel.CalculateFullRebuild();"
    "  [void]$solverResults.Add(@{ request_id = $request.request_id; success = [bool]$solveResult; solver_result = $solveResult.ToString() });"
    "}"
    "$wb.Save();"
    "$wb.Close($true);"
    "Write-Output (@{ goal_seek_results = $goalResults; solver_results = $solverResults } | ConvertTo-Json -Compress -Depth 100);"
    "} finally {"
    "if ($wb) { try { $wb.Close($false) } catch {} }"
    "$excel.Quit();"
    "}"
  )
  try:
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True, text=True)
  except subprocess.CalledProcessError as exc:
    return {
      "goal_seek_results": [],
      "solver_results": [],
      "success": False,
      "error": str(exc.stderr or exc.stdout or exc),
    }
  except Exception as exc:
    return {
      "goal_seek_results": [],
      "solver_results": [],
      "success": False,
      "error": str(exc),
    }
  try:
    parsed = json.loads(str(completed.stdout or "").strip() or "{}")
  except Exception:
    parsed = {}
  if isinstance(parsed, dict):
    parsed.setdefault("success", True)
    return parsed
  return {"goal_seek_results": [], "solver_results": [], "success": False, "error": "invalid_calibration_response"}


def _recalculate_excel_workbook(finmo_path: str) -> None:
  workbook_path = _normalize_finmo_path(finmo_path)
  script = (
    "$path = " + json.dumps(workbook_path) + ";"
    "$excel = New-Object -ComObject Excel.Application;"
    "$excel.Visible = $false;"
    "$excel.DisplayAlerts = $false;"
    "try {"
    "$wb = $excel.Workbooks.Open($path, $false, $false);"
    "$excel.CalculateFullRebuild();"
    "$wb.Save();"
    "$wb.Close($true);"
    "} finally {"
    "if ($wb) { try { $wb.Close($false) } catch {} }"
    "$excel.Quit();"
    "}"
  )
  subprocess.run(
    ["powershell", "-NoProfile", "-Command", script],
    check=True,
    capture_output=True,
    text=True,
  )


def run_finmo_goal_seek(
  *,
  finmo_path: str,
  objective_cell: Dict[str, Any],
  changing_input_cell: Dict[str, Any],
  goal_value: float,
) -> Dict[str, Any]:
  workbook_path = _normalize_finmo_path(finmo_path)
  objective_ref = f"{objective_cell.get('sheet')}!{objective_cell.get('cell')}"
  changing_ref = f"{changing_input_cell.get('sheet')}!{changing_input_cell.get('cell')}"
  script = (
    "$path = " + json.dumps(workbook_path) + ";"
    "$objective = " + json.dumps(objective_ref) + ";"
    "$changing = " + json.dumps(changing_ref) + ";"
    "$goal = " + json.dumps(goal_value) + ";"
    "$excel = New-Object -ComObject Excel.Application;"
    "$excel.Visible = $false;"
    "$excel.DisplayAlerts = $false;"
    "try {"
    "$wb = $excel.Workbooks.Open($path, $false, $false);"
    "$parts = $objective.Split('!');"
    "$objectiveRange = $wb.Worksheets.Item($parts[0]).Range($parts[1]);"
    "$parts2 = $changing.Split('!');"
    "$changingRange = $wb.Worksheets.Item($parts2[0]).Range($parts2[1]);"
    "$result = $objectiveRange.GoalSeek($goal, $changingRange);"
    "$excel.CalculateFullRebuild();"
    "$wb.Save();"
    "$wb.Close($true);"
    "Write-Output ($result.ToString());"
    "} finally {"
    "if ($wb) { try { $wb.Close($false) } catch {} }"
    "$excel.Quit();"
    "}"
  )
  completed = subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True, text=True)
  return {
    "objective_cell": objective_cell,
    "changing_input_cell": changing_input_cell,
    "goal_value": goal_value,
    "success": "True" in str(completed.stdout or ""),
  }


def _goal_value_from_band(goal_band: Optional[Dict[str, Any]]) -> Optional[float]:
  band = goal_band if isinstance(goal_band, dict) else {}
  min_value = _safe_float(band.get("min"))
  max_value = _safe_float(band.get("max"))
  if min_value is not None and max_value is not None:
    return (min_value + max_value) / 2.0
  if min_value is not None:
    return min_value
  if max_value is not None:
    return max_value
  return None


def run_finmo_goal_seek_request(
  *,
  finmo_path: str,
  request: Dict[str, Any],
) -> Dict[str, Any]:
  objective = (request.get("objective") or {}) if isinstance(request.get("objective"), dict) else {}
  objective_cell = (request.get("objective_cell") or {}) if isinstance(request.get("objective_cell"), dict) else {}
  changing_inputs = [item for item in (request.get("changing_input_cells") or []) if isinstance(item, dict)]
  goal_value = _goal_value_from_band(objective.get("goal_band") if isinstance(objective, dict) else {})
  if not objective_cell or not changing_inputs or goal_value is None:
    return {
      "request_id": str(request.get("request_id") or "").strip(),
      "success": False,
      "error": "goal_seek_request_incomplete",
    }
  result = run_finmo_goal_seek(
    finmo_path=finmo_path,
    objective_cell=objective_cell,
    changing_input_cell=changing_inputs[0],
    goal_value=goal_value,
  )
  result["request_id"] = str(request.get("request_id") or "").strip()
  result["goal_band"] = _clone(objective.get("goal_band") or {})
  return result


def run_finmo_excel_solver(
  *,
  finmo_path: str,
  objective_cell: Dict[str, Any],
  changing_input_cells: Sequence[Dict[str, Any]],
  goal_band: Optional[Dict[str, Any]] = None,
  constraints: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  workbook_path = _normalize_finmo_path(finmo_path)
  objective_ref = f"{objective_cell.get('sheet')}!{objective_cell.get('cell')}"
  changing_refs = [
    f"{item.get('sheet')}!{item.get('cell')}"
    for item in (changing_input_cells or [])
    if isinstance(item, dict) and item.get("sheet") and item.get("cell")
  ]
  if not objective_ref or not changing_refs:
    return {
      "objective_cell": objective_cell,
      "changing_input_cells": list(changing_input_cells or []),
      "goal_band": _clone(goal_band or {}),
      "success": False,
      "error": "excel_solver_request_incomplete",
    }
  target_value = _goal_value_from_band(goal_band or {})
  min_value = _safe_float((goal_band or {}).get("min"))
  max_value = _safe_float((goal_band or {}).get("max"))
  constraints_payload = [item for item in (constraints or []) if isinstance(item, dict)]
  script = (
    "$path = " + json.dumps(workbook_path) + ";"
    "$objective = " + json.dumps(objective_ref) + ";"
    "$changingRefs = " + json.dumps(changing_refs) + ";"
    "$target = " + json.dumps(target_value) + ";"
    "$minGoal = " + json.dumps(min_value) + ";"
    "$maxGoal = " + json.dumps(max_value) + ";"
    "$constraints = " + json.dumps(constraints_payload) + ";"
    "$excel = New-Object -ComObject Excel.Application;"
    "$excel.Visible = $false;"
    "$excel.DisplayAlerts = $false;"
    "$wb = $null;"
    "try {"
    "$solver = $excel.AddIns.Item('Solver Add-in');"
    "if (-not $solver.Installed) { $solver.Installed = $true }"
    "$wb = $excel.Workbooks.Open($path, $false, $false);"
    "$excel.Run('Solver.xlam!SolverReset');"
    "$changeSpec = ($changingRefs | ForEach-Object { $parts = $_.Split('!'); $sheet = $parts[0]; $cell = $parts[1]; \"'\" + $sheet + \"'!\" + $cell }) -join ',';"
    "$parts = $objective.Split('!');"
    "$objectiveSpec = \"'\" + $parts[0] + \"'!\" + $parts[1];"
    "if ($target -ne $null) {"
    "$excel.Run('Solver.xlam!SolverOK', $objectiveSpec, 3, $target, $changeSpec);"
    "} else {"
    "$excel.Run('Solver.xlam!SolverOK', $objectiveSpec, 2, $null, $changeSpec);"
    "}"
    "if ($minGoal -ne $null) { $excel.Run('Solver.xlam!SolverAdd', $objectiveSpec, 3, $minGoal) }"
    "if ($maxGoal -ne $null) { $excel.Run('Solver.xlam!SolverAdd', $objectiveSpec, 1, $maxGoal) }"
    "foreach ($constraint in $constraints) {"
    "if (-not $constraint.cell) { continue }"
    "$relation = [int]($constraint.relation);"
    "if ($relation -lt 1) { continue }"
    "$constraintParts = $constraint.cell.Split('!');"
    "$constraintSpec = \"'\" + $constraintParts[0] + \"'!\" + $constraintParts[1];"
    "$formulaText = $constraint.value;"
    "$excel.Run('Solver.xlam!SolverAdd', $constraintSpec, $relation, $formulaText);"
    "}"
    "$solveResult = $excel.Run('Solver.xlam!SolverSolve', $true);"
    "$excel.Run('Solver.xlam!SolverFinish', 1);"
    "$excel.CalculateFullRebuild();"
    "$wb.Save();"
    "$wb.Close($true);"
    "Write-Output ($solveResult.ToString());"
    "} finally {"
    "if ($wb) { try { $wb.Close($false) } catch {} }"
    "$excel.Quit();"
    "}"
  )
  completed = subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True, text=True)
  return {
    "objective_cell": objective_cell,
    "changing_input_cells": list(changing_input_cells or []),
    "goal_band": _clone(goal_band or {}),
    "constraints": _clone(list(constraints or [])),
    "success": bool(str(completed.stdout or "").strip()),
    "solver_result": str(completed.stdout or "").strip(),
  }


def run_finmo_excel_solver_request(
  *,
  finmo_path: str,
  request: Dict[str, Any],
) -> Dict[str, Any]:
  objective = (request.get("objective") or {}) if isinstance(request.get("objective"), dict) else {}
  objective_cell = (request.get("objective_cell") or {}) if isinstance(request.get("objective_cell"), dict) else {}
  changing_inputs = [item for item in (request.get("changing_input_cells") or []) if isinstance(item, dict)]
  if not objective_cell or not changing_inputs:
    return {
      "request_id": str(request.get("request_id") or "").strip(),
      "success": False,
      "error": "excel_solver_request_incomplete",
    }
  result = run_finmo_excel_solver(
    finmo_path=finmo_path,
    objective_cell=objective_cell,
    changing_input_cells=changing_inputs,
    goal_band=(objective.get("goal_band") or {}) if isinstance(objective, dict) else {},
    constraints=request.get("constraints") if isinstance(request.get("constraints"), list) else [],
  )
  result["request_id"] = str(request.get("request_id") or "").strip()
  return result


def sync_consistency_state_to_finmo(
  *,
  finmo_path: Any,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  marketing_model_json: Optional[Dict[str, Any]],
  model_input_json_override: Optional[Dict[str, Any]] = None,
  controller_input_seed: Optional[Sequence[Dict[str, Any]]] = None,
  forecast_quarters: Sequence[Dict[str, Any]],
  calibration_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del ops_json
  del people_json
  del financials_year1_json
  del marketing_model_json

  path = _normalize_finmo_path(finmo_path)
  if not Path(path).exists():
    raise FileNotFoundError(f"Finmo workbook not found at {path}")
  if isinstance(model_input_json_override, dict) and model_input_json_override:
    model_input_json = _clone(model_input_json_override)
  else:
    baseline_input = _read_model_input_json(path)
    model_input_json = _build_model_input_overlay(
      baseline_model_input=baseline_input,
      business_facts=business_facts or {},
      financials_json=financials_json or {},
      controller_input_seed=controller_input_seed,
      forecast_quarters=forecast_quarters,
    )
  _write_model_input_json_to_workbook(path, model_input_json)
  _recalculate_excel_workbook(path)
  written_model_input_json = _read_model_input_json(path)
  finmo_json = _read_finmo_json(path)
  calibration_results: Dict[str, Any] = {}
  if isinstance(calibration_spec, dict) and calibration_spec:
    resolved_shell = _resolve_finmo_calibration_shell(
      finmo_path=path,
      model_input_json=written_model_input_json,
      finmo_json=finmo_json,
      calibration_spec=calibration_spec,
    )
    calibration_results = _execute_finmo_calibration_shell(
      finmo_path=path,
      calibration_shell=resolved_shell,
    )
    written_model_input_json = _read_model_input_json(path)
    finmo_json = _read_finmo_json(path)
    written_model_input_json["calibration_shell"] = _clone(resolved_shell)
    written_model_input_json["calibration_results"] = _clone(calibration_results)
    finmo_json["calibration_shell"] = _clone(resolved_shell)
    finmo_json["calibration_results"] = _clone(calibration_results)
  return {
    "finmo_path": path,
    "model_input_json": written_model_input_json,
    "finmo_json": finmo_json,
  }
