"""Shared fixture builders for the FinmoModelInputContract acceptance
tests. Producing minimal-valid payloads here keeps the per-test files
under the 700 LOC cap and prevents helper drift across test files.

This module is leading-underscore-prefixed because it is a test-only
helper, NOT a test module to be auto-discovered by the test runner.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  PERIOD_COUNT,
)


def values_zero() -> List[float]:
  return [0.0 for _ in range(PERIOD_COUNT)]


def valid_period(slot_index: int) -> Dict[str, Any]:
  is_stub = slot_index == 0
  return {
    "slot_index": slot_index,
    "column_index": 7 + slot_index,
    "column_letter": "H" if slot_index == 0 else "I",
    "year": 2026.0 + slot_index / 4.0,
    "quarter": 0.0 if is_stub else float(slot_index),
    "date": "2026-01-01",
    "year_fraction": 0.0 if is_stub else 1.0,
    "is_stub": is_stub,
  }


def valid_periods_21() -> List[Dict[str, Any]]:
  return [valid_period(i) for i in range(PERIOD_COUNT)]


def valid_revenue_row(driver: str = "Capacity") -> Dict[str, Any]:
  semantics_by_driver = {
    "Capacity": ("direct_number", "quarter_capacity_units"),
    "Unit Price": ("direct_number", "currency_per_unit"),
    "Utilization": ("ratio", "utilization_ratio"),
  }
  vk, sem = semantics_by_driver[driver]
  return {
    "named_range": "model_input_revenue",
    "controller_write": True,
    "lever_id": f"revenue::LOB 1::Product 1::{driver}",
    "lob": "LOB 1",
    "product": "Product 1",
    "driver": driver,
    "revenue_slot_key": "lob_1_product_1",
    "value_kind": vk,
    "input_semantics": sem,
    "values": [0.5] * PERIOD_COUNT if sem == "utilization_ratio" else values_zero(),
  }


def valid_revenue_triple() -> List[Dict[str, Any]]:
  return [
    valid_revenue_row("Capacity"),
    valid_revenue_row("Unit Price"),
    valid_revenue_row("Utilization"),
  ]


def valid_expense_row(
  label: str = "Cost of Goods Sold",
  value_kind: str = "ratio",
  input_semantics: str = "percent_of_revenue",
  controller_write: bool = True,
  derived_driver: Optional[str] = None,
  values: Optional[List[float]] = None,
) -> Dict[str, Any]:
  row: Dict[str, Any] = {
    "named_range": "model_input_expenses",
    "controller_write": controller_write,
    "lever_id": f"expenses::{label}",
    "label": label,
    "value_kind": value_kind,
    "input_semantics": input_semantics,
    "values": values if values is not None else values_zero(),
  }
  if derived_driver is not None:
    row["derived_driver"] = derived_driver
  return row


def valid_balance_sheet_row(
  label: str = "Accounts Receivable Days",
  value_kind: str = "day_count",
  input_semantics: str = "days",
  controller_write: bool = True,
  derived_driver: Optional[str] = None,
  values: Optional[List[float]] = None,
) -> Dict[str, Any]:
  row: Dict[str, Any] = {
    "named_range": "model_input_balancehseet",  # sic — production typo
    "controller_write": controller_write,
    "lever_id": f"balance_sheet::{label}",
    "label": label,
    "value_kind": value_kind,
    "input_semantics": input_semantics,
    "values": values if values is not None else [30.0] * PERIOD_COUNT,
  }
  if derived_driver is not None:
    row["derived_driver"] = derived_driver
  return row


def valid_wc_days_triple() -> List[Dict[str, Any]]:
  return [
    valid_balance_sheet_row(label=lab)
    for lab in ("Accounts Receivable Days", "Inventory Days", "Accounts Payable Days")
  ]


def valid_schedule_row(
  label: str = "Debt Issuance (New Borrowing)",
  input_semantics: str = "debt_new_borrowing",
  controller_write: bool = True,
  derived_driver: Optional[str] = None,
) -> Dict[str, Any]:
  row: Dict[str, Any] = {
    "named_range": "model_input_schedules",
    "controller_write": controller_write,
    "lever_id": f"schedules::{label}",
    "label": label,
    "value_kind": "direct_number",
    "input_semantics": input_semantics,
    "values": values_zero(),
  }
  if derived_driver is not None:
    row["derived_driver"] = derived_driver
  return row


def valid_schedules_section(
  rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  return {
    "debt_opening_balance_seed": 0.0,
    "lease_opening_balance_seed": 0.0,
    "ppe_opening_balance_seed": 0.0,
    "forecast_ppe_opening_balance_seed": 0.0,
    "accumulated_depreciation_opening_seed": 0.0,
    "cash_opening_balance_seed": 0.0,
    "accounts_receivable_opening_balance_seed": 0.0,
    "inventory_opening_balance_seed": 0.0,
    "accounts_payable_opening_balance_seed": 0.0,
    "short_term_debt_opening_balance_seed": 0.0,
    "client_reported_ppe_stub": 0.0,
    "rows": rows if rows is not None else [],
  }


def valid_sections() -> Dict[str, Any]:
  return {
    "revenue": valid_revenue_triple(),
    "expenses": [valid_expense_row()],
    "balance_sheet": valid_wc_days_triple(),
    "schedules": valid_schedules_section(),
  }


def valid_top_level() -> Dict[str, Any]:
  return {
    "contract_version": "finmo_model_input_v3",
    "canonical_lever_vocabulary": "model_inputs_controller_write_only",
    "finmo_path": "",
    "business_name": "Test Co",
    "start_date": "2026-01-01",
    "business_start_date": "2024-06-01",
    "periods": valid_periods_21(),
    "lever_catalog": {},
    "controller_write_levers": [],
    "sections": valid_sections(),
  }
