"""Shared fixture builders for Contract 2 (WorkbookPayloadContract)
acceptance tests. Same single-source-of-truth pattern as
``_p3_40_contract_1_fixtures.py``.

Module is leading-underscore-prefixed so the test runner does NOT
auto-discover it as a test module.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (  # noqa: E402
  LIVE_QUARTER_COUNT,
  PERIOD_COUNT,
)

# Re-use Contract 1 fixtures so the composed model_input_json field
# stays in lockstep with Contract 1's fixture conventions.
from _p3_40_contract_1_fixtures import (  # noqa: E402
  valid_top_level as valid_model_input_json_dict,
)


# ---------------------------------------------------------------------------
# WorkbookPeriod
# ---------------------------------------------------------------------------

def valid_workbook_period(
  slot_index: int,
  *,
  include_days_in_quarter: bool = True,
) -> Dict[str, Any]:
  is_stub = slot_index == 0
  return {
    "slot_index": slot_index,
    "quarter": 0.0 if is_stub else float(slot_index),
    "year": 2026.0 + slot_index / 4.0,
    "date": "2026-01-01",
    "days_in_quarter": None if (is_stub or not include_days_in_quarter) else 91.0,
    "is_stub": is_stub,
  }


def valid_workbook_periods_21(*, include_days_in_quarter: bool = True) -> List[Dict[str, Any]]:
  return [
    valid_workbook_period(i, include_days_in_quarter=include_days_in_quarter)
    for i in range(PERIOD_COUNT)
  ]


# ---------------------------------------------------------------------------
# FinmoOutputContract
# ---------------------------------------------------------------------------

def valid_finmo_statement_row(label: str = "Revenue", value: float = 1000.0) -> Dict[str, Any]:
  return {
    "label": label,
    "values": [value] * PERIOD_COUNT,
  }


def valid_finmo_quarter_row(slot_index: int) -> Dict[str, Any]:
  """One quarter_rows[i] entry. Stub uses days_in_quarter=0 (allowed
  by the invariant); live quarters carry 91."""
  is_stub = slot_index == 0
  return {
    "slot_index": slot_index,
    "quarter_index": slot_index,
    "quarter": float(slot_index),
    "year": 2026.0,
    "date": "2026-01-01",
    "days_in_quarter": 0 if is_stub else 91,
    "revenue": 1000.0 * slot_index,
  }


def valid_finmo_output_dict(*, include_quarter_rows: bool = True) -> Dict[str, Any]:
  return {
    "contract_version": "finmo_output_v1",
    "finmo_path": "",
    "periods": valid_workbook_periods_21(include_days_in_quarter=True),
    "pl": [valid_finmo_statement_row("Revenue")],
    "balance_sheet": [valid_finmo_statement_row("Cash")],
    "cash_flow": [valid_finmo_statement_row("Net Cash Flow")],
    "quarter_rows": (
      [valid_finmo_quarter_row(i) for i in range(PERIOD_COUNT)]
      if include_quarter_rows
      else None
    ),
    "accounting_check": None,
  }


# ---------------------------------------------------------------------------
# PayrollHeadcountContract
# ---------------------------------------------------------------------------

def valid_payroll_row(
  quarter_index: int = 1,
  *,
  position_title: Optional[str] = "Engineer",
  person_name: Optional[str] = None,
  oews_occ_title: Optional[str] = "Software Developer",
  oews_matched_title: Optional[str] = None,
  wage_source: Optional[str] = "OEWS",
  wage_source_code: Optional[str] = None,
  starting_fte: float = 1.0,
  hires: float = 0.0,
  annual_wage: float = 100000.0,
  benefits: float = 0.2,
) -> Dict[str, Any]:
  row: Dict[str, Any] = {
    "quarter_index": quarter_index,
    "staffing_class": "supporting_staff",
    "starting_fte": starting_fte,
    "hires": hires,
    "annual_wage": annual_wage,
    "payroll_taxes_benefits_percent": benefits,
  }
  if position_title is not None:
    row["position_title"] = position_title
  if person_name is not None:
    row["person_name"] = person_name
  if oews_occ_title is not None:
    row["oews_occ_title"] = oews_occ_title
  if oews_matched_title is not None:
    row["oews_matched_title"] = oews_matched_title
  if wage_source is not None:
    row["wage_source"] = wage_source
  if wage_source_code is not None:
    row["wage_source_code"] = wage_source_code
  return row


def valid_payroll_headcount_dict(
  *,
  one_row_per_quarter: bool = True,
) -> Dict[str, Any]:
  rows: List[Dict[str, Any]]
  if one_row_per_quarter:
    rows = [valid_payroll_row(quarter_index=q) for q in range(1, LIVE_QUARTER_COUNT + 1)]
  else:
    rows = [valid_payroll_row(quarter_index=1)]
  return {
    "capacity_labor_model": "capacity_units_per_supporting_fte",
    "labor_intensity_class": "moderate",
    "wage_positioning_tier": "p50_median",
    "wage_positioning_multiplier": 1.0,
    "capacity_units_per_supporting_fte": 100.0,
    "target_payroll_percent_of_revenue": 0.30,
    "rows": rows,
  }


# ---------------------------------------------------------------------------
# DebtScheduleContract
# ---------------------------------------------------------------------------

def valid_debt_schedule_row(quarter_index: int = 1) -> Dict[str, Any]:
  """19-field row per
  ``post_intake_debt_schedule/schedule.py:384-405``. Aliases carry
  the same numeric values as their canonical fields by the writer's
  construction."""
  opening = 100000
  issuance = 0
  repayment = 5000
  closing = 95000
  rate = 0.05
  interest = 4750
  available = 100000
  return {
    "quarter_index": quarter_index,
    "date": "2026-01-01",
    "opening_debt": opening,
    "opening_principal_balance": opening,
    "requested_debt_issuance": issuance,
    "actual_debt_issuance": issuance,
    "new_borrowing": issuance,
    "requested_debt_repayment": repayment,
    "actual_debt_repayment": repayment,
    "total_principal_payment": repayment,
    "closing_debt": closing,
    "closing_principal_balance": closing,
    "interest_rate": rate,
    "annual_interest_rate": rate,
    "interest_expense": interest,
    "available_debt_before_repayment": available,
    "available_principal_before_payment": available,
    "total_debt_service": repayment + interest,
    "finmo_formula": (
      "closing_debt = max(0, opening_debt + debt_issuance - debt_repayment); "
      "interest = average(opening_debt, closing_debt) * interest_rate"
    ),
  }


def valid_debt_schedule_dict() -> Dict[str, Any]:
  return {
    "contract_version": "post_intake_debt_amortization_schedule_v1",
    "schedule_role": "persisted_final_debt_amortization_schedule",
    "source_of_truth": "sql.post_intake_cash_policy_lookup",
    "lookup_function": "post_intake_cash_debt_schedule_policy",
    "source_stage": "post_intake_finalize_validation",
    "finmo_formula_unchanged": True,
    "horizon_quarters": LIVE_QUARTER_COUNT,
    "model_input_drivers": [
      "expenses::Interest Rate",
      "schedules::Debt Issuance (New Borrowing)",
      "schedules::Debt Repayment (Scheduled)",
    ],
    "rows": [valid_debt_schedule_row(q) for q in range(1, LIVE_QUARTER_COUNT + 1)],
    "persisted_column": "intake_consult_drafts.debt_schedule",
  }


# ---------------------------------------------------------------------------
# PlanningRunJsonForWorkbookContract
# ---------------------------------------------------------------------------

def valid_stage_ramp_quarter(q: int = 1) -> Dict[str, Any]:
  return {
    "q": q,
    "rev_target": 0.10,
    "rev_max": 0.15,
    "rev_spike_max": 0.25,
    "max_util": 0.85,
    "cogs_target": 0.30,
    "cogs_max": 0.40,
    "marketing_max": 0.20,
    "rd_max": 0.15,
    "ga_max": 0.20,
    "lease_max": 0.10,
    "ni_floor": -0.20,
  }


def valid_stage_ramp_contract_dict() -> Dict[str, Any]:
  return {
    "stage_family": "growth",
    "quarter_ramp_grid": [
      valid_stage_ramp_quarter(q) for q in range(1, LIVE_QUARTER_COUNT + 1)
    ],
  }


def valid_planning_run_json_dict(
  *,
  include_stage_ramp: bool = True,
) -> Dict[str, Any]:
  if include_stage_ramp:
    return {
      "unified_convergence_context": {
        "business_world_contract": {
          "stage_ramp_contract": valid_stage_ramp_contract_dict(),
        },
      },
    }
  return {}


# ---------------------------------------------------------------------------
# RunDiagnosticsContract
# ---------------------------------------------------------------------------

def valid_realism_check_entry(metric_key: str = "ebitda_margin", passed: bool = True) -> Dict[str, Any]:
  return {"metric_key": metric_key, "passed": passed}


def valid_run_diagnostics_dict() -> Dict[str, Any]:
  return {
    "draft_id": "draft_test_001",
    "planning_run_id": "run_test_001",
    "business_name": "Test Co",
    "business_naics_6": "722515",
    "business_stage": "growth",
    "business_start_date": "2024-06-01",
    "planning_mode": "growth",
    "cash_strategy_name": "moderate",
    "acceptance_passed": True,
    "acceptance_score": 92.5,
    "realism_checks": [valid_realism_check_entry()],
    "handler_fired": False,
    "handler_status": None,
    "handler_scope": None,
    "tool_calls_used": None,
    "budget_extension_triggered": None,
    "workbook_path": "/tmp/test.xlsx",
    "captured_at": "2026-05-25T12:00:00Z",
  }


# ---------------------------------------------------------------------------
# Top-level WorkbookPayloadContract
# ---------------------------------------------------------------------------

def valid_workbook_payload_dict(
  *,
  include_planning_run: bool = True,
  include_run_diagnostics: bool = True,
) -> Dict[str, Any]:
  payload: Dict[str, Any] = {
    "model_input_json": valid_model_input_json_dict(),  # from Contract 1 fixtures
    "finmo_json": valid_finmo_output_dict(),
    "payroll_headcount": valid_payroll_headcount_dict(),
    "debt_schedule": valid_debt_schedule_dict(),
  }
  if include_planning_run:
    payload["planning_run_json"] = valid_planning_run_json_dict()
  if include_run_diagnostics:
    payload["run_diagnostics"] = valid_run_diagnostics_dict()
  return payload
