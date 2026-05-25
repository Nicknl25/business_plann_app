"""Per-row acceptance tests for ``FinmoModelInputContract`` — covers
``Period``, ``RevenueRow``, ``ExpenseRow``, ``ScheduleRow``. The
top-level and cross-section tests live in
``test_p3_40_contract_1_sections.py``.

Spec: ``docs/architecture/p3_40_contract_1_finmo_model_input_spec.md``.
Shared fixture builders in ``_p3_40_contract_1_fixtures.py``.
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

from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (  # noqa: E402
  PERIOD_COUNT,
  ExpenseRow,
  Period,
  RevenueRow,
  ScheduleRow,
)
from _p3_40_contract_1_fixtures import (  # noqa: E402
  valid_expense_row,
  valid_period,
  valid_revenue_row,
  valid_schedule_row,
  values_zero,
)


# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------

class PeriodTest(unittest.TestCase):

  def test_valid_stub_period(self) -> None:
    Period.model_validate(valid_period(0))

  def test_valid_live_period(self) -> None:
    Period.model_validate(valid_period(5))

  def test_quarter_must_be_integral_rejects_fractional(self) -> None:
    bad = valid_period(3)
    bad["quarter"] = 3.5
    with self.assertRaises(ValidationError) as ctx:
      Period.model_validate(bad)
    self.assertIn("quarter must be a whole number", str(ctx.exception))

  def test_slot_index_above_20_rejected(self) -> None:
    bad = valid_period(5)
    bad["slot_index"] = 21
    with self.assertRaises(ValidationError):
      Period.model_validate(bad)

  def test_column_index_below_7_rejected(self) -> None:
    bad = valid_period(0)
    bad["column_index"] = 6
    with self.assertRaises(ValidationError):
      Period.model_validate(bad)

  def test_extra_field_forbidden(self) -> None:
    bad = valid_period(0)
    bad["extra_field"] = "not allowed"
    with self.assertRaises(ValidationError):
      Period.model_validate(bad)


# ---------------------------------------------------------------------------
# RevenueRow
# ---------------------------------------------------------------------------

class RevenueRowTest(unittest.TestCase):

  def test_valid_capacity(self) -> None:
    RevenueRow.model_validate(valid_revenue_row("Capacity"))

  def test_valid_unit_price(self) -> None:
    RevenueRow.model_validate(valid_revenue_row("Unit Price"))

  def test_valid_utilization(self) -> None:
    RevenueRow.model_validate(valid_revenue_row("Utilization"))

  def test_invalid_driver_rejected(self) -> None:
    bad = valid_revenue_row()
    bad["driver"] = "InvalidDriver"
    with self.assertRaises(ValidationError):
      RevenueRow.model_validate(bad)

  def test_slot_key_pattern_rejected(self) -> None:
    bad = valid_revenue_row()
    bad["revenue_slot_key"] = "not_a_slot_key"
    with self.assertRaises(ValidationError):
      RevenueRow.model_validate(bad)

  def test_nan_value_rejected(self) -> None:
    bad = valid_revenue_row()
    bad["values"][3] = float("nan")
    with self.assertRaises(ValidationError) as ctx:
      RevenueRow.model_validate(bad)
    self.assertIn("finite", str(ctx.exception))

  def test_inf_value_rejected(self) -> None:
    bad = valid_revenue_row()
    bad["values"][3] = math.inf
    with self.assertRaises(ValidationError):
      RevenueRow.model_validate(bad)

  def test_utilization_value_above_1_rejected(self) -> None:
    bad = valid_revenue_row("Utilization")
    bad["values"][3] = 1.5  # utilization_ratio is in _PERCENT_INPUT_SEMANTICS
    with self.assertRaises(ValidationError) as ctx:
      RevenueRow.model_validate(bad)
    self.assertIn("must be in [0, 1]", str(ctx.exception))

  def test_capacity_value_above_1_accepted(self) -> None:
    # Capacity uses input_semantics="quarter_capacity_units" — NOT
    # in the percent set, so 1.5 is fine here.
    row = valid_revenue_row("Capacity")
    row["values"][3] = 1.5
    RevenueRow.model_validate(row)

  def test_values_length_must_be_21(self) -> None:
    bad = valid_revenue_row()
    bad["values"] = values_zero()[:20]
    with self.assertRaises(ValidationError):
      RevenueRow.model_validate(bad)

  def test_derived_required_when_not_writable(self) -> None:
    bad = valid_revenue_row()
    bad["controller_write"] = False
    with self.assertRaises(ValidationError) as ctx:
      RevenueRow.model_validate(bad)
    self.assertIn("derived_driver must be set", str(ctx.exception))

  def test_writable_with_derived_driver_accepted(self) -> None:
    # Per R4: production can set derived_driver on writable rows.
    row = valid_revenue_row("Capacity")
    row["derived_driver"] = "payroll_supported_capacity"
    RevenueRow.model_validate(row)

  def test_not_writable_with_derived_driver_accepted(self) -> None:
    row = valid_revenue_row("Capacity")
    row["controller_write"] = False
    row["derived_driver"] = "payroll_supported_capacity"
    RevenueRow.model_validate(row)


# ---------------------------------------------------------------------------
# ExpenseRow
# ---------------------------------------------------------------------------

class ExpenseRowTest(unittest.TestCase):

  def test_valid_cogs(self) -> None:
    ExpenseRow.model_validate(valid_expense_row())

  def test_valid_payroll_derived(self) -> None:
    # Production: controller_write=False, derived_driver="headcount_schedule_derived"
    ExpenseRow.model_validate(valid_expense_row(
      label="Payroll",
      value_kind="direct_number",
      input_semantics="quarter_currency",
      controller_write=False,
      derived_driver="headcount_schedule_derived",
    ))

  def test_valid_depreciation_seeded_but_writable(self) -> None:
    # Production R4: depreciation row has derived_driver set
    # but controller_write remains True.
    ExpenseRow.model_validate(valid_expense_row(
      label="Depreciation",
      value_kind="ratio",
      input_semantics="percent_of_prior_ppe",
      controller_write=True,
      derived_driver="structural_capacity_ppe_derived",
    ))

  def test_invalid_value_kind_rejected(self) -> None:
    bad = valid_expense_row()
    bad["value_kind"] = "absolute"  # original directive's value, not in production enum
    with self.assertRaises(ValidationError):
      ExpenseRow.model_validate(bad)

  def test_invalid_input_semantics_rejected(self) -> None:
    bad = valid_expense_row()
    bad["input_semantics"] = "positive_is_cost"  # original directive's value
    with self.assertRaises(ValidationError):
      ExpenseRow.model_validate(bad)

  def test_percent_value_above_1_rejected(self) -> None:
    bad = valid_expense_row(values=[0.5] * 20 + [1.2])
    with self.assertRaises(ValidationError) as ctx:
      ExpenseRow.model_validate(bad)
    self.assertIn("must be in [0, 1]", str(ctx.exception))

  def test_quarter_currency_value_above_1_accepted(self) -> None:
    # quarter_currency is NOT in the percent set
    ExpenseRow.model_validate(valid_expense_row(
      label="Lease",
      value_kind="direct_number",
      input_semantics="quarter_currency",
      values=[10000.0] * PERIOD_COUNT,
    ))

  def test_derived_required_when_not_writable(self) -> None:
    bad = valid_expense_row(controller_write=False)
    with self.assertRaises(ValidationError):
      ExpenseRow.model_validate(bad)


# ---------------------------------------------------------------------------
# ScheduleRow
# ---------------------------------------------------------------------------

class ScheduleRowTest(unittest.TestCase):

  def test_valid_debt_issuance(self) -> None:
    ScheduleRow.model_validate(valid_schedule_row())

  def test_valid_capex_seeded_but_writable(self) -> None:
    # Per R4: Capital Expenditures has derived_driver set but
    # controller_write=True.
    ScheduleRow.model_validate(valid_schedule_row(
      label="Capital Expenditures",
      input_semantics="capital_expenditures_cash",
      controller_write=True,
      derived_driver="structural_capacity_ppe_derived",
    ))

  def test_nan_value_rejected(self) -> None:
    bad = valid_schedule_row()
    bad["values"][0] = float("nan")
    with self.assertRaises(ValidationError):
      ScheduleRow.model_validate(bad)

  def test_derived_required_when_not_writable(self) -> None:
    bad = valid_schedule_row(controller_write=False)
    with self.assertRaises(ValidationError):
      ScheduleRow.model_validate(bad)


if __name__ == "__main__":
  unittest.main(verbosity=2)
