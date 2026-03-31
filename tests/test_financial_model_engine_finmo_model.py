from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))


from financial_model_engine.finmo_model import FORMULA_REGISTRY, calculate_finmo_model  # type: ignore  # noqa: E402
from financial_model_engine.model_inputs import FinancialModelInputs  # type: ignore  # noqa: E402


class FinmoModelTests(unittest.TestCase):
  def test_calculate_finmo_model_matches_expected_quarter_math(self) -> None:
    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="CareFirst Home Health Services",
    )
    for quarter_index in range(1, 5):
      book.set_revenue_drivers(
        quarter_index=quarter_index,
        lob_name="Primary line of business",
        product_name="In-home care hour",
        revenue_slot_key="lob_1_product_1",
        capacity_units=1300.0,
        unit_price=100.0,
        utilization=0.85,
      )
      book.set_expense_drivers(
        quarter_index=quarter_index,
        cogs_percent=0.773806,
        marketing_percent=0.08,
        lease_amount=3600.0,
        payroll_amount=40000.0,
        g_and_a_percent=0.15,
      )
    for quarter_index in range(5, 9):
      book.set_revenue_drivers(
        quarter_index=quarter_index,
        lob_name="Primary line of business",
        product_name="In-home care hour",
        revenue_slot_key="lob_1_product_1",
        capacity_units=2000.0,
        unit_price=110.0,
        utilization=0.92,
      )
      book.set_expense_drivers(
        quarter_index=quarter_index,
        cogs_percent=0.773806,
        marketing_percent=0.11,
        lease_amount=3600.0,
        payroll_amount=65000.0,
        g_and_a_percent=0.12,
      )
    for quarter_index in range(9, 21):
      book.set_revenue_drivers(
        quarter_index=quarter_index,
        lob_name="Primary line of business",
        product_name="In-home care hour",
        revenue_slot_key="lob_1_product_1",
        capacity_units=2600.0,
        unit_price=105.0,
        utilization=0.90,
      )
      book.set_expense_drivers(
        quarter_index=quarter_index,
        cogs_percent=0.773806,
        marketing_percent=0.05,
        lease_amount=3600.0,
        payroll_amount=80000.0,
        g_and_a_percent=0.10,
      )
    for quarter_index in range(1, 21):
      book.set_simple_driver(
        section="schedules",
        label="Capital Expenditures",
        quarter_index=quarter_index,
        value=0.0,
        named_range="model_input_schedules",
        lever_id="schedules::Capital Expenditures",
      )
    book.set_simple_driver(
      section="balance_sheet",
      label="Owner's Capital",
      quarter_index=1,
      value=100000.0,
      named_range="model_input_balancehseet",
      lever_id="balance_sheet::Owner's Capital",
    )
    book.set_schedule_seed(
      ppe_opening_balance_seed=25000.0,
      accumulated_depreciation_opening_seed=-5000.0,
    )

    result = calculate_finmo_model(book)
    quarters = result.quarter_rows()

    self.assertEqual(len(quarters), 20)
    self.assertAlmostEqual(quarters[0]["revenue"], 110500.0, places=4)
    self.assertAlmostEqual(quarters[0]["cost_of_goods_sold"], 85505.563, places=3)
    self.assertAlmostEqual(quarters[0]["marketing"], 8840.0, places=4)
    self.assertAlmostEqual(quarters[0]["general_and_administrative"], 16575.0, places=4)
    self.assertAlmostEqual(quarters[0]["ebitda"], -44020.563, places=3)
    self.assertAlmostEqual(quarters[4]["revenue"], 202400.0, places=4)
    self.assertAlmostEqual(quarters[4]["marketing"], 22264.0, places=4)
    self.assertAlmostEqual(quarters[4]["ebitda"], -69370.3344, places=3)
    self.assertAlmostEqual(quarters[8]["revenue"], 245700.0, places=4)

  def test_formula_registry_covers_core_finmo_labels(self) -> None:
    self.assertIn("Accounting Equation Check", FORMULA_REGISTRY)
    self.assertIn("Revenue", FORMULA_REGISTRY)
    self.assertIn("EBITDA", FORMULA_REGISTRY)
    self.assertIn("Total Liabilities & Equity", FORMULA_REGISTRY)
    self.assertIn("Debt Schedule / Interest Expense", FORMULA_REGISTRY)
    self.assertIn("Capital Leases Schedule / Closing Balance (Total)", FORMULA_REGISTRY)

  def test_accounting_equation_check_is_available_on_quarter_output(self) -> None:
    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="CareFirst Home Health Services",
    )
    book.set_revenue_drivers(
      quarter_index=1,
      lob_name="Primary line of business",
      product_name="In-home care hour",
      revenue_slot_key="lob_1_product_1",
      capacity_units=1300.0,
      unit_price=95.0,
      utilization=0.85,
    )
    result = calculate_finmo_model(book)
    first_quarter = result.quarter_rows()[0]
    self.assertIn("accounting_equation_check", first_quarter)

  def test_quarter_rows_can_include_stub_period(self) -> None:
    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="CareFirst Home Health Services",
    )
    book.set_schedule_seed(
      debt_opening_balance_seed=15000.0,
      lease_opening_balance_seed=9000.0,
    )

    result = calculate_finmo_model(book)
    rows = result.quarter_rows(include_stub=True)

    self.assertEqual(len(rows), 21)
    self.assertEqual(rows[0]["quarter_index"], 0)
    self.assertEqual(rows[0]["quarter"], 0)
    self.assertAlmostEqual(rows[0]["debt_closing_balance"], 15000.0, places=6)
    self.assertAlmostEqual(rows[0]["lease_closing_balance_total"], 9000.0, places=6)

  def test_ppe_is_derived_from_opening_balance_capex_and_depreciation(self) -> None:
    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="CareFirst Home Health Services",
    )
    book.set_expense_drivers(quarter_index=1, depreciation_percent=0.10)
    book.set_simple_driver(
      section="schedules",
      label="Capital Expenditures",
      quarter_index=1,
      value=5000.0,
      named_range="model_input_schedules",
      lever_id="schedules::Capital Expenditures",
    )
    book.set_schedule_seed(
      ppe_opening_balance_seed=20000.0,
      accumulated_depreciation_opening_seed=-4000.0,
    )

    result = calculate_finmo_model(book)
    first_quarter = result.quarter_rows()[0]

    self.assertAlmostEqual(first_quarter["depreciation"], 2000.0, places=6)
    self.assertAlmostEqual(first_quarter["ppe"], 23000.0, places=6)
    self.assertAlmostEqual(first_quarter["capital_expenditures"], 5000.0, places=6)

  def test_lease_balance_is_floored_at_zero(self) -> None:
    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="CareFirst Home Health Services",
    )
    book.set_schedule_seed(lease_opening_balance_seed=1000.0)
    book.set_simple_driver(
      section="schedules",
      label="Less: Principal Repayments",
      quarter_index=1,
      value=1500.0,
      named_range="model_input_schedules",
      lever_id="schedules::Less: Principal Repayments",
    )

    result = calculate_finmo_model(book)
    first_quarter = result.quarter_rows()[0]

    self.assertAlmostEqual(first_quarter["lease_closing_balance_total"], 0.0, places=6)


if __name__ == "__main__":
  unittest.main()
