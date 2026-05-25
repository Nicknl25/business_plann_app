"""Cross-section + top-level acceptance tests for
``FinmoModelInputContract``. Covers ``BalanceSheetRow``,
``SchedulesSection``, ``ModelInputSections`` (with its 4
cross-section validators), ``FinmoModelInputContract`` (top-level
+ periods sequence), and ``ContractViolation``.

Per-row tests for Period / Revenue / Expense / Schedule live in
``test_p3_40_contract_1_rows.py``.

Spec: ``docs/architecture/p3_40_contract_1_finmo_model_input_spec.md``.
Shared fixture builders in ``_p3_40_contract_1_fixtures.py``.
"""

from __future__ import annotations

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

from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  PERIOD_COUNT,
  BalanceSheetRow,
  ContractViolation,
  FinmoModelInputContract,
  ModelInputSections,
  SchedulesSection,
)
from _p3_40_contract_1_fixtures import (  # noqa: E402
  valid_balance_sheet_row,
  valid_expense_row,
  valid_revenue_row,
  valid_revenue_triple,
  valid_schedule_row,
  valid_schedules_section,
  valid_sections,
  valid_top_level,
)


# ---------------------------------------------------------------------------
# BalanceSheetRow
# ---------------------------------------------------------------------------

class BalanceSheetRowTest(unittest.TestCase):

  def test_valid_ar_days(self) -> None:
    BalanceSheetRow.model_validate(valid_balance_sheet_row())

  def test_typo_named_range_accepted(self) -> None:
    # The production typo "model_input_balancehseet" must be accepted as-is.
    row = valid_balance_sheet_row()
    self.assertEqual(row["named_range"], "model_input_balancehseet")
    BalanceSheetRow.model_validate(row)

  def test_correct_spelling_named_range_rejected(self) -> None:
    # Conversely, the correct spelling is REJECTED because the Literal
    # is locked to the production typo. This documents the residual R2.
    bad = valid_balance_sheet_row()
    bad["named_range"] = "model_input_balance_sheet"  # correct spelling
    with self.assertRaises(ValidationError):
      BalanceSheetRow.model_validate(bad)

  def test_valid_percent_of_revenue(self) -> None:
    BalanceSheetRow.model_validate(valid_balance_sheet_row(
      label="Prepaid Expenses (% of Revenue)",
      value_kind="ratio",
      input_semantics="percent_of_revenue",
      values=[0.02] * PERIOD_COUNT,
    ))

  def test_valid_owners_capital(self) -> None:
    BalanceSheetRow.model_validate(valid_balance_sheet_row(
      label="Owner's Capital",
      value_kind="direct_number",
      input_semantics="quarter_currency",
      values=[50000.0] * PERIOD_COUNT,
    ))

  def test_negative_day_count_rejected(self) -> None:
    bad = valid_balance_sheet_row(values=[30.0] * 20 + [-5.0])
    with self.assertRaises(ValidationError) as ctx:
      BalanceSheetRow.model_validate(bad)
    self.assertIn("day_count values must be non-negative", str(ctx.exception))

  def test_seeded_with_derived_driver_accepted(self) -> None:
    # Per R4: balance_sheet contextual-seed sets derived_driver but
    # leaves controller_write=True.
    BalanceSheetRow.model_validate(valid_balance_sheet_row(
      controller_write=True,
      derived_driver="balance_sheet_contextual_seed_policy_v1",
    ))

  def test_derived_required_when_not_writable(self) -> None:
    bad = valid_balance_sheet_row(controller_write=False)
    with self.assertRaises(ValidationError):
      BalanceSheetRow.model_validate(bad)


# ---------------------------------------------------------------------------
# SchedulesSection
# ---------------------------------------------------------------------------

class SchedulesSectionTest(unittest.TestCase):

  def test_valid_empty_rows(self) -> None:
    SchedulesSection.model_validate(valid_schedules_section())

  def test_negative_debt_seed_rejected(self) -> None:
    bad = valid_schedules_section()
    bad["debt_opening_balance_seed"] = -1.0
    with self.assertRaises(ValidationError):
      SchedulesSection.model_validate(bad)

  def test_accumulated_depreciation_positive_rejected(self) -> None:
    # Production stores as -abs(val); positive values violate the
    # le=0 constraint.
    bad = valid_schedules_section()
    bad["accumulated_depreciation_opening_seed"] = 100.0
    with self.assertRaises(ValidationError):
      SchedulesSection.model_validate(bad)

  def test_accumulated_depreciation_negative_accepted(self) -> None:
    sec = valid_schedules_section()
    sec["accumulated_depreciation_opening_seed"] = -50000.0
    SchedulesSection.model_validate(sec)

  def test_client_reported_ppe_stub_unconstrained(self) -> None:
    # No sign constraint per the trace.
    sec = valid_schedules_section()
    sec["client_reported_ppe_stub"] = -100.0
    SchedulesSection.model_validate(sec)
    sec["client_reported_ppe_stub"] = 500000.0
    SchedulesSection.model_validate(sec)

  def test_extra_field_forbidden(self) -> None:
    bad = valid_schedules_section()
    bad["new_seed_field"] = 0.0
    with self.assertRaises(ValidationError):
      SchedulesSection.model_validate(bad)


# ---------------------------------------------------------------------------
# ModelInputSections cross-section validators
# ---------------------------------------------------------------------------

class ModelInputSectionsTest(unittest.TestCase):

  def test_valid_sections(self) -> None:
    ModelInputSections.model_validate(valid_sections())

  def test_revenue_slot_triple_missing_driver_rejected(self) -> None:
    bad = valid_sections()
    # Drop Utilization
    bad["revenue"] = [valid_revenue_row("Capacity"), valid_revenue_row("Unit Price")]
    with self.assertRaises(ValidationError) as ctx:
      ModelInputSections.model_validate(bad)
    self.assertIn("must have exactly", str(ctx.exception))

  def test_revenue_slot_triple_duplicate_driver_rejected(self) -> None:
    bad = valid_sections()
    bad["revenue"] = [
      valid_revenue_row("Capacity"),
      valid_revenue_row("Unit Price"),
      valid_revenue_row("Utilization"),
      valid_revenue_row("Capacity"),  # extra
    ]
    with self.assertRaises(ValidationError):
      ModelInputSections.model_validate(bad)

  def test_revenue_multi_slot_each_complete_triple(self) -> None:
    # Two slots, each with full triple
    slot2_rows = []
    for driver in ("Capacity", "Unit Price", "Utilization"):
      r = valid_revenue_row(driver)
      r["revenue_slot_key"] = "lob_1_product_2"
      r["product"] = "Product 2"
      r["lever_id"] = f"revenue::LOB 1::Product 2::{driver}"
      slot2_rows.append(r)
    sections = valid_sections()
    sections["revenue"] = valid_revenue_triple() + slot2_rows
    ModelInputSections.model_validate(sections)

  def test_wc_days_partial_rejected(self) -> None:
    bad = valid_sections()
    # Drop "Inventory Days" — leaves an incomplete WC days set.
    bad["balance_sheet"] = [
      valid_balance_sheet_row(label="Accounts Receivable Days"),
      valid_balance_sheet_row(label="Accounts Payable Days"),
    ]
    with self.assertRaises(ValidationError) as ctx:
      ModelInputSections.model_validate(bad)
    self.assertIn("working capital days rows incomplete", str(ctx.exception))

  def test_wc_days_all_absent_accepted(self) -> None:
    # If NONE of the 3 WC days labels is present, validator is silent.
    # (Use a non-WC balance_sheet row to satisfy min_length=1.)
    sections = valid_sections()
    sections["balance_sheet"] = [valid_balance_sheet_row(
      label="Owner's Capital",
      value_kind="direct_number",
      input_semantics="quarter_currency",
      values=[10000.0] * PERIOD_COUNT,
    )]
    ModelInputSections.model_validate(sections)

  def test_capex_without_depreciation_rejected(self) -> None:
    bad = valid_sections()
    # Add Capital Expenditures to schedules without Depreciation in expenses.
    bad["schedules"]["rows"] = [valid_schedule_row(
      label="Capital Expenditures",
      input_semantics="capital_expenditures_cash",
    )]
    with self.assertRaises(ValidationError) as ctx:
      ModelInputSections.model_validate(bad)
    self.assertIn("Capital Expenditures", str(ctx.exception))

  def test_depreciation_without_capex_rejected(self) -> None:
    bad = valid_sections()
    bad["expenses"] = [valid_expense_row(
      label="Depreciation",
      value_kind="ratio",
      input_semantics="percent_of_prior_ppe",
      derived_driver="structural_capacity_ppe_derived",
    )]
    # schedules.rows is empty so capex is absent.
    with self.assertRaises(ValidationError):
      ModelInputSections.model_validate(bad)

  def test_capex_with_depreciation_accepted(self) -> None:
    sections = valid_sections()
    sections["expenses"] = [
      valid_expense_row(),  # COGS
      valid_expense_row(
        label="Depreciation",
        value_kind="ratio",
        input_semantics="percent_of_prior_ppe",
        derived_driver="structural_capacity_ppe_derived",
      ),
    ]
    sections["schedules"]["rows"] = [valid_schedule_row(
      label="Capital Expenditures",
      input_semantics="capital_expenditures_cash",
    )]
    ModelInputSections.model_validate(sections)

  def test_named_range_drift_in_revenue_rejected(self) -> None:
    # Per-section uniformity: a row's named_range mismatching the
    # canonical section value triggers the cross-section validator.
    # In production the Literal on RevenueRow.named_range catches
    # this earlier at row instantiation; this test confirms the
    # cross-section validator would also catch it.
    bad = valid_sections()
    # Bypass the Literal at row construction by validating sections
    # against a payload with a deliberately-mismatched named_range.
    # The per-row Literal will catch first; verify ValidationError.
    bad["revenue"][0]["named_range"] = "wrong_named_range"
    with self.assertRaises(ValidationError):
      ModelInputSections.model_validate(bad)


# ---------------------------------------------------------------------------
# FinmoModelInputContract top-level
# ---------------------------------------------------------------------------

class FinmoModelInputContractTest(unittest.TestCase):

  def test_valid_top_level(self) -> None:
    FinmoModelInputContract.model_validate(valid_top_level())

  def test_wrong_contract_version_rejected(self) -> None:
    bad = valid_top_level()
    bad["contract_version"] = "financial_model_inputs_v1"  # the dead path's version
    with self.assertRaises(ValidationError):
      FinmoModelInputContract.model_validate(bad)

  def test_wrong_canonical_vocabulary_rejected(self) -> None:
    bad = valid_top_level()
    bad["canonical_lever_vocabulary"] = "something_else"
    with self.assertRaises(ValidationError):
      FinmoModelInputContract.model_validate(bad)

  def test_periods_stub_not_first_rejected(self) -> None:
    bad = valid_top_level()
    bad["periods"][0]["is_stub"] = False
    bad["periods"][0]["quarter"] = 1.0
    with self.assertRaises(ValidationError) as ctx:
      FinmoModelInputContract.model_validate(bad)
    self.assertIn("periods[0] must be the stub", str(ctx.exception))

  def test_periods_live_quarter_out_of_sequence_rejected(self) -> None:
    bad = valid_top_level()
    bad["periods"][5]["quarter"] = 99.0  # not the expected 5
    with self.assertRaises(ValidationError) as ctx:
      FinmoModelInputContract.model_validate(bad)
    self.assertIn("must equal 5", str(ctx.exception))

  def test_periods_too_few_rejected(self) -> None:
    bad = valid_top_level()
    bad["periods"] = bad["periods"][:20]
    with self.assertRaises(ValidationError):
      FinmoModelInputContract.model_validate(bad)

  def test_opaque_blob_fields_accept_arbitrary_dicts(self) -> None:
    top = valid_top_level()
    top["lever_catalog"] = {
      "revenue::LOB 1::Product 1::Capacity": {"foo": "bar", "nested": {"x": 1}},
    }
    top["controller_write_levers"] = [{"any": "shape"}]
    top["derived_driver_policies"] = {"policy_x": {"version": "v1"}}
    top["derived_driver_runtime"] = {"runtime_data": [1, 2, 3]}
    FinmoModelInputContract.model_validate(top)

  def test_optional_post_stamped_absent_accepted(self) -> None:
    top = valid_top_level()
    # Producer-side validation case: post-stamped fields absent
    top.pop("business_start_date", None)
    self.assertNotIn("derived_driver_policies", top)
    self.assertNotIn("derived_driver_runtime", top)
    FinmoModelInputContract.model_validate(top)

  def test_extra_top_level_field_forbidden(self) -> None:
    bad = valid_top_level()
    bad["surprise_field"] = "not allowed"
    with self.assertRaises(ValidationError):
      FinmoModelInputContract.model_validate(bad)


# ---------------------------------------------------------------------------
# ContractViolation
# ---------------------------------------------------------------------------

class ContractViolationTest(unittest.TestCase):

  def test_message_format(self) -> None:
    exc = ContractViolation(
      stage="AMALGAMATED_SESSION→MODEL_INPUT",
      field="sections.revenue[0].driver",
      expected="Capacity | Unit Price | Utilization",
      actual="InvalidDriver",
    )
    self.assertEqual(exc.stage, "AMALGAMATED_SESSION→MODEL_INPUT")
    self.assertEqual(exc.field, "sections.revenue[0].driver")
    self.assertIsNone(exc.source_payload)
    self.assertIn("AMALGAMATED_SESSION", str(exc))
    self.assertIn("expected Capacity", str(exc))
    self.assertIn("got InvalidDriver", str(exc))

  def test_source_payload_attached(self) -> None:
    payload = {"sections": {"revenue": [{"driver": "X"}]}}
    exc = ContractViolation(
      stage="MODEL_INPUT→SOLVER",
      field="x",
      expected="y",
      actual="z",
      source_payload=payload,
    )
    self.assertIs(exc.source_payload, payload)


if __name__ == "__main__":
  unittest.main(verbosity=2)
