"""Per-sub-contract acceptance tests for
``WorkbookPayloadContract``. Covers the 10 sub-contract classes
in isolation: WorkbookPeriod, FinmoStatementRow,
FinmoOutputContract, PayrollHeadcountRow, PayrollHeadcountContract,
DebtScheduleRow, DebtScheduleContract, StageRampQuarter +
StageRampContract, RealismCheckEntry, RunDiagnosticsContract.

The top-level WorkbookPayloadContract + cross-field invariants +
API boundary test (Adjustment B) land in
``test_p3_40_contract_2_workbook_payload.py``.

Spec: ``docs/architecture/p3_40_contract_2_workbook_payload_spec.md``.
Shared fixtures in ``_p3_40_contract_2_fixtures.py``.
"""

from __future__ import annotations

import math
import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


from pydantic import ValidationError  # noqa: E402

from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (  # noqa: E402
  DebtScheduleContract,
  DebtScheduleRow,
  FinmoOutputContract,
  FinmoStatementRow,
  LIVE_QUARTER_COUNT,
  PERIOD_COUNT,
  PayrollHeadcountContract,
  PayrollHeadcountRow,
  PlanningRunJsonForWorkbookContract,
  RealismCheckEntry,
  RunDiagnosticsContract,
  StageRampContract,
  StageRampQuarter,
  WorkbookPeriod,
)
from _p3_40_contract_2_fixtures import (  # noqa: E402
  valid_debt_schedule_dict,
  valid_debt_schedule_row,
  valid_finmo_output_dict,
  valid_finmo_quarter_row,
  valid_finmo_statement_row,
  valid_payroll_headcount_dict,
  valid_payroll_row,
  valid_planning_run_json_dict,
  valid_realism_check_entry,
  valid_run_diagnostics_dict,
  valid_stage_ramp_contract_dict,
  valid_stage_ramp_quarter,
  valid_workbook_period,
  valid_workbook_periods_21,
)


# ---------------------------------------------------------------------------
# WorkbookPeriod
# ---------------------------------------------------------------------------

class WorkbookPeriodTest(unittest.TestCase):

  def test_valid_stub(self) -> None:
    WorkbookPeriod.model_validate(valid_workbook_period(0))

  def test_valid_live(self) -> None:
    WorkbookPeriod.model_validate(valid_workbook_period(5))

  def test_slot_index_above_20_rejected(self) -> None:
    bad = valid_workbook_period(5)
    bad["slot_index"] = 21
    with self.assertRaises(ValidationError):
      WorkbookPeriod.model_validate(bad)

  def test_slot_index_below_0_rejected(self) -> None:
    bad = valid_workbook_period(5)
    bad["slot_index"] = -1
    with self.assertRaises(ValidationError):
      WorkbookPeriod.model_validate(bad)

  def test_extra_fields_ignored(self) -> None:
    """Per Flag 2 amended: rows allow extras."""
    p = valid_workbook_period(3)
    p["column_index"] = 10  # quarter_rows carries this
    p["column_letter"] = "K"
    p["year_fraction"] = 1.0
    WorkbookPeriod.model_validate(p)


# ---------------------------------------------------------------------------
# FinmoStatementRow
# ---------------------------------------------------------------------------

class FinmoStatementRowTest(unittest.TestCase):

  def test_valid(self) -> None:
    FinmoStatementRow.model_validate(valid_finmo_statement_row())

  def test_empty_label_rejected(self) -> None:
    bad = valid_finmo_statement_row()
    bad["label"] = ""
    with self.assertRaises(ValidationError):
      FinmoStatementRow.model_validate(bad)

  def test_wrong_values_length_rejected(self) -> None:
    bad = valid_finmo_statement_row()
    bad["values"] = [0.0] * 20  # 20 not 21
    with self.assertRaises(ValidationError):
      FinmoStatementRow.model_validate(bad)


# ---------------------------------------------------------------------------
# FinmoOutputContract — including invariants 4.2 and 4.4
# ---------------------------------------------------------------------------

class FinmoOutputContractTest(unittest.TestCase):

  def test_valid_with_quarter_rows(self) -> None:
    FinmoOutputContract.model_validate(valid_finmo_output_dict())

  def test_valid_without_quarter_rows(self) -> None:
    """quarter_rows is Optional — may be absent when data.periods
    falls back to finmo_json.periods instead."""
    FinmoOutputContract.model_validate(
      valid_finmo_output_dict(include_quarter_rows=False),
    )

  def test_wrong_contract_version_rejected(self) -> None:
    bad = valid_finmo_output_dict()
    bad["contract_version"] = "finmo_output_v0"
    with self.assertRaises(ValidationError):
      FinmoOutputContract.model_validate(bad)

  def test_periods_wrong_length_rejected(self) -> None:
    bad = valid_finmo_output_dict()
    bad["periods"] = bad["periods"][:20]  # 20 not 21
    with self.assertRaises(ValidationError):
      FinmoOutputContract.model_validate(bad)

  def test_empty_pl_rejected(self) -> None:
    bad = valid_finmo_output_dict()
    bad["pl"] = []
    with self.assertRaises(ValidationError):
      FinmoOutputContract.model_validate(bad)

  def test_invariant_4_2_quarter_rows_length_mismatch_rejected(self) -> None:
    bad = valid_finmo_output_dict()
    bad["quarter_rows"] = bad["quarter_rows"][:20]  # 20 not 21
    with self.assertRaises(ValidationError) as ctx:
      FinmoOutputContract.model_validate(bad)
    self.assertIn("quarter_rows length", str(ctx.exception))
    self.assertIn("does not match", str(ctx.exception))

  def test_invariant_4_4_stub_days_in_quarter_zero_ok(self) -> None:
    """Stub (index 0) is allowed to have days_in_quarter=0."""
    payload = valid_finmo_output_dict()
    payload["quarter_rows"][0]["days_in_quarter"] = 0
    FinmoOutputContract.model_validate(payload)

  def test_invariant_4_4_live_quarter_zero_days_rejected(self) -> None:
    bad = valid_finmo_output_dict()
    bad["quarter_rows"][5]["days_in_quarter"] = 0
    with self.assertRaises(ValidationError) as ctx:
      FinmoOutputContract.model_validate(bad)
    self.assertIn("days_in_quarter", str(ctx.exception))
    self.assertIn("DIV/0", str(ctx.exception))

  def test_invariant_4_4_live_quarter_missing_days_rejected(self) -> None:
    bad = valid_finmo_output_dict()
    bad["quarter_rows"][5].pop("days_in_quarter", None)
    with self.assertRaises(ValidationError) as ctx:
      FinmoOutputContract.model_validate(bad)
    self.assertIn("days_in_quarter", str(ctx.exception))

  def test_accounting_check_optional_opaque_accepted(self) -> None:
    payload = valid_finmo_output_dict()
    payload["accounting_check"] = {"rows": [], "all_ok": True, "any_extra": "ok"}
    FinmoOutputContract.model_validate(payload)


# ---------------------------------------------------------------------------
# PayrollHeadcountRow — title/oews/wage either-or validators
# ---------------------------------------------------------------------------

class PayrollHeadcountRowTest(unittest.TestCase):

  def test_valid_with_position_title_only(self) -> None:
    PayrollHeadcountRow.model_validate(valid_payroll_row())

  def test_valid_with_person_name_only(self) -> None:
    PayrollHeadcountRow.model_validate(valid_payroll_row(
      position_title=None, person_name="Jane Smith",
    ))

  def test_neither_title_nor_person_rejected(self) -> None:
    bad = valid_payroll_row(position_title=None, person_name=None)
    with self.assertRaises(ValidationError) as ctx:
      PayrollHeadcountRow.model_validate(bad)
    self.assertIn("position_title or person_name", str(ctx.exception))

  def test_valid_with_oews_matched_title_only(self) -> None:
    PayrollHeadcountRow.model_validate(valid_payroll_row(
      oews_occ_title=None, oews_matched_title="Software Developer (matched)",
    ))

  def test_neither_oews_title_rejected(self) -> None:
    bad = valid_payroll_row(oews_occ_title=None, oews_matched_title=None)
    with self.assertRaises(ValidationError) as ctx:
      PayrollHeadcountRow.model_validate(bad)
    self.assertIn("oews_occ_title or oews_matched_title", str(ctx.exception))

  def test_valid_with_wage_source_code_only(self) -> None:
    PayrollHeadcountRow.model_validate(valid_payroll_row(
      wage_source=None, wage_source_code="WS_INTAKE",
    ))

  def test_neither_wage_source_rejected(self) -> None:
    bad = valid_payroll_row(wage_source=None, wage_source_code=None)
    with self.assertRaises(ValidationError) as ctx:
      PayrollHeadcountRow.model_validate(bad)
    self.assertIn("wage_source or wage_source_code", str(ctx.exception))

  def test_annual_wage_zero_rejected(self) -> None:
    bad = valid_payroll_row(annual_wage=0.0)
    with self.assertRaises(ValidationError):
      PayrollHeadcountRow.model_validate(bad)

  def test_benefits_above_1_rejected(self) -> None:
    bad = valid_payroll_row(benefits=1.5)
    with self.assertRaises(ValidationError):
      PayrollHeadcountRow.model_validate(bad)

  def test_extra_writer_fields_ignored(self) -> None:
    """Producer adds average_fte, quarterly_wage_cost, etc.
    (schedule.py:1948-1957). Per Flag 2: extra=ignore on rows."""
    row = valid_payroll_row()
    row["average_fte"] = 1.0
    row["quarterly_wage_cost"] = 25000
    row["quarterly_taxes_benefits"] = 5000
    row["total_quarterly_payroll"] = 30000
    PayrollHeadcountRow.model_validate(row)


# ---------------------------------------------------------------------------
# PayrollHeadcountContract — horizon-coverage invariant
# ---------------------------------------------------------------------------

class PayrollHeadcountContractTest(unittest.TestCase):

  def test_valid(self) -> None:
    PayrollHeadcountContract.model_validate(valid_payroll_headcount_dict())

  def test_missing_required_root_field_rejected(self) -> None:
    bad = valid_payroll_headcount_dict()
    del bad["capacity_labor_model"]
    with self.assertRaises(ValidationError):
      PayrollHeadcountContract.model_validate(bad)

  def test_invariant_horizon_coverage_partial_rejected(self) -> None:
    """rows must cover quarters 1..20."""
    bad = valid_payroll_headcount_dict(one_row_per_quarter=False)  # only Q1
    with self.assertRaises(ValidationError) as ctx:
      PayrollHeadcountContract.model_validate(bad)
    self.assertIn("missing entries for quarters", str(ctx.exception))

  def test_invariant_horizon_coverage_missing_q5_rejected(self) -> None:
    payload = valid_payroll_headcount_dict()
    # Remove Q5 entries
    payload["rows"] = [r for r in payload["rows"] if r["quarter_index"] != 5]
    with self.assertRaises(ValidationError) as ctx:
      PayrollHeadcountContract.model_validate(payload)
    self.assertIn("5", str(ctx.exception))

  def test_extra_writer_fields_ignored(self) -> None:
    """contract_version, decision_source, quarter_totals are
    writer-added (T5) but unread; ignored at the contract."""
    payload = valid_payroll_headcount_dict()
    payload["contract_version"] = "payroll_headcount_schedule_v1"
    payload["decision_source"] = "x"
    payload["quarter_totals"] = [{"quarter_index": q, "ending_fte": 1.0, "payroll": 25000} for q in range(1, 21)]
    payload["headcount_economic_basis"] = "capacity_units_per_supporting_fte"
    PayrollHeadcountContract.model_validate(payload)

  def test_multiple_rows_per_quarter_allowed(self) -> None:
    """Production has multiple titles per quarter (one row per
    title); coverage invariant only requires at-least-one per
    quarter."""
    payload = valid_payroll_headcount_dict()
    extra_q1 = valid_payroll_row(quarter_index=1, position_title="Designer")
    payload["rows"].append(extra_q1)
    PayrollHeadcountContract.model_validate(payload)


# ---------------------------------------------------------------------------
# DebtScheduleRow — 19 fields per quarter (verbatim writer shape)
# ---------------------------------------------------------------------------

class DebtScheduleRowTest(unittest.TestCase):

  def test_valid(self) -> None:
    DebtScheduleRow.model_validate(valid_debt_schedule_row())

  def test_missing_required_field_rejected(self) -> None:
    """Drop one of the 19 required fields."""
    bad = valid_debt_schedule_row()
    del bad["total_debt_service"]
    with self.assertRaises(ValidationError):
      DebtScheduleRow.model_validate(bad)

  def test_quarter_index_out_of_range_rejected(self) -> None:
    bad = valid_debt_schedule_row(quarter_index=21)
    with self.assertRaises(ValidationError):
      DebtScheduleRow.model_validate(bad)

  def test_empty_finmo_formula_rejected(self) -> None:
    bad = valid_debt_schedule_row()
    bad["finmo_formula"] = ""
    with self.assertRaises(ValidationError):
      DebtScheduleRow.model_validate(bad)

  def test_aliases_typed_independently(self) -> None:
    """opening_principal_balance is typed separately from
    opening_debt. The writer keeps them in sync, but the contract
    doesn't enforce equality — they're independently required
    fields."""
    row = valid_debt_schedule_row()
    # Diverge the alias value — contract accepts (no enforced equality)
    row["opening_principal_balance"] = 999999
    DebtScheduleRow.model_validate(row)

  def test_date_may_be_none(self) -> None:
    row = valid_debt_schedule_row()
    row["date"] = None
    DebtScheduleRow.model_validate(row)


# ---------------------------------------------------------------------------
# DebtScheduleContract
# ---------------------------------------------------------------------------

class DebtScheduleContractTest(unittest.TestCase):

  def test_valid(self) -> None:
    DebtScheduleContract.model_validate(valid_debt_schedule_dict())

  def test_wrong_contract_version_rejected(self) -> None:
    bad = valid_debt_schedule_dict()
    bad["contract_version"] = "post_intake_debt_amortization_schedule_v0"
    with self.assertRaises(ValidationError):
      DebtScheduleContract.model_validate(bad)

  def test_wrong_schedule_role_rejected(self) -> None:
    bad = valid_debt_schedule_dict()
    bad["schedule_role"] = "draft_plan"
    with self.assertRaises(ValidationError):
      DebtScheduleContract.model_validate(bad)

  def test_empty_rows_rejected(self) -> None:
    bad = valid_debt_schedule_dict()
    bad["rows"] = []
    with self.assertRaises(ValidationError):
      DebtScheduleContract.model_validate(bad)

  def test_empty_model_input_drivers_rejected(self) -> None:
    bad = valid_debt_schedule_dict()
    bad["model_input_drivers"] = []
    with self.assertRaises(ValidationError):
      DebtScheduleContract.model_validate(bad)

  def test_persisted_column_optional_absent_accepted(self) -> None:
    """persisted_column is added by orchestrator.py:3104 AFTER the
    snapshot builder returns. At the builder's return point it's
    absent — contract accepts."""
    payload = valid_debt_schedule_dict()
    del payload["persisted_column"]
    DebtScheduleContract.model_validate(payload)

  def test_extra_writer_fields_ignored(self) -> None:
    """The other debt_schedule_plan shape adds 'status',
    'schedule_method', 'opening_debt_seed', 'exact_updates';
    if anything from the plan flavor leaks in, ignore."""
    payload = valid_debt_schedule_dict()
    payload["status"] = "ready"
    payload["schedule_method"] = "amortizing_remaining_balance"
    DebtScheduleContract.model_validate(payload)


# ---------------------------------------------------------------------------
# StageRampQuarter + StageRampContract
# ---------------------------------------------------------------------------

class StageRampQuarterTest(unittest.TestCase):

  def test_valid(self) -> None:
    StageRampQuarter.model_validate(valid_stage_ramp_quarter())

  def test_missing_required_field_rejected(self) -> None:
    bad = valid_stage_ramp_quarter()
    del bad["ni_floor"]
    with self.assertRaises(ValidationError):
      StageRampQuarter.model_validate(bad)

  def test_q_optional(self) -> None:
    payload = valid_stage_ramp_quarter()
    payload["q"] = None
    StageRampQuarter.model_validate(payload)


class StageRampContractTest(unittest.TestCase):

  def test_valid(self) -> None:
    StageRampContract.model_validate(valid_stage_ramp_contract_dict())

  def test_empty_quarter_ramp_grid_rejected(self) -> None:
    bad = valid_stage_ramp_contract_dict()
    bad["quarter_ramp_grid"] = []
    with self.assertRaises(ValidationError):
      StageRampContract.model_validate(bad)

  def test_stage_family_optional(self) -> None:
    payload = valid_stage_ramp_contract_dict()
    del payload["stage_family"]
    StageRampContract.model_validate(payload)


# ---------------------------------------------------------------------------
# PlanningRunJsonForWorkbookContract (thin)
# ---------------------------------------------------------------------------

class PlanningRunJsonForWorkbookContractTest(unittest.TestCase):

  def test_valid_with_stage_ramp(self) -> None:
    PlanningRunJsonForWorkbookContract.model_validate(
      valid_planning_run_json_dict(),
    )

  def test_valid_empty(self) -> None:
    """No constraint on this contract in isolation — chain-raise
    invariant lives at the WorkbookPayloadContract level (tested
    separately in test_p3_40_contract_2_workbook_payload.py)."""
    PlanningRunJsonForWorkbookContract.model_validate({})

  def test_extra_top_level_writer_fields_ignored(self) -> None:
    """planning_run_json has ~30 top-level keys in production;
    the contract reads only one nested path."""
    payload = valid_planning_run_json_dict()
    payload["planning_mode"] = "growth"
    payload["controller_resolution_state"] = {"foo": "bar"}
    payload["adaptive_policy"] = {"baz": "qux"}
    PlanningRunJsonForWorkbookContract.model_validate(payload)


# ---------------------------------------------------------------------------
# RealismCheckEntry + RunDiagnosticsContract
# ---------------------------------------------------------------------------

class RealismCheckEntryTest(unittest.TestCase):

  def test_valid(self) -> None:
    RealismCheckEntry.model_validate(valid_realism_check_entry())

  def test_empty_metric_key_rejected(self) -> None:
    bad = valid_realism_check_entry()
    bad["metric_key"] = ""
    with self.assertRaises(ValidationError):
      RealismCheckEntry.model_validate(bad)

  def test_extra_fields_ignored(self) -> None:
    """Writer adds severity, distance, etc. (T8 details); only
    metric_key + passed are typed."""
    entry = valid_realism_check_entry()
    entry["severity"] = "high"
    entry["distance"] = -0.05
    entry["band_min"] = 0.10
    RealismCheckEntry.model_validate(entry)


class RunDiagnosticsContractTest(unittest.TestCase):

  def test_valid(self) -> None:
    RunDiagnosticsContract.model_validate(valid_run_diagnostics_dict())

  def test_optional_fields_absent_accepted(self) -> None:
    payload = valid_run_diagnostics_dict()
    for k in (
      "business_naics_6", "business_stage", "business_start_date",
      "planning_mode", "cash_strategy_name",
      "acceptance_passed", "acceptance_score",
      "handler_status", "handler_scope", "tool_calls_used",
      "budget_extension_triggered", "workbook_path", "captured_at",
    ):
      payload.pop(k, None)
    RunDiagnosticsContract.model_validate(payload)

  def test_required_handler_fired_present(self) -> None:
    bad = valid_run_diagnostics_dict()
    del bad["handler_fired"]
    with self.assertRaises(ValidationError):
      RunDiagnosticsContract.model_validate(bad)

  def test_empty_realism_checks_accepted(self) -> None:
    payload = valid_run_diagnostics_dict()
    payload["realism_checks"] = []
    RunDiagnosticsContract.model_validate(payload)

  def test_extra_writer_fields_ignored(self) -> None:
    payload = valid_run_diagnostics_dict()
    payload["future_field"] = "ok"
    RunDiagnosticsContract.model_validate(payload)


if __name__ == "__main__":
  unittest.main(verbosity=2)
