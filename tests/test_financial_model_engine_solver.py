from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))


from financial_model_engine.finmo_model import calculate_finmo_model  # type: ignore  # noqa: E402
from financial_model_engine.model_inputs import FinancialModelInputs  # type: ignore  # noqa: E402
from financial_model_engine.solver import (  # type: ignore  # noqa: E402
  LeverControl,
  OutputTarget,
  SolverOptions,
  solve_financial_model,
)


class FinancialModelSolverTests(unittest.TestCase):
  def _baseline_book(self) -> FinancialModelInputs:
    book = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="Solver Smoke Test",
    )
    for quarter_index in range(1, 21):
      book.set_revenue_drivers(
        quarter_index=quarter_index,
        lob_name="Primary line of business",
        product_name="In-home care hour",
        revenue_slot_key="lob_1_product_1",
        capacity_units=100.0,
        unit_price=10.0,
        utilization=0.50,
      )
      book.set_expense_drivers(
        quarter_index=quarter_index,
        cogs_percent=0.20,
        marketing_percent=0.0,
        r_and_d_percent=0.0,
        lease_amount=0.0,
        payroll_amount=450.0,
        g_and_a_percent=0.0,
        interest_rate=0.0,
        depreciation_percent=0.0,
        tax_percent=0.0,
      )
      book.set_simple_driver(
        section="balance_sheet",
        label="Owner's Capital",
        quarter_index=quarter_index,
        value=5000.0,
        named_range="model_input_balancehseet",
        lever_id="balance_sheet::Owner's Capital",
      )
    return book

  def test_solver_improves_output_targets_and_preserves_exact_price(self) -> None:
    baseline = self._baseline_book()
    baseline_rows = calculate_finmo_model(baseline).quarter_rows()

    result = solve_financial_model(
      baseline,
      controls=[
        LeverControl(
          lever_id="revenue::Primary line of business::In-home care hour::Unit Price",
          quarter_start=1,
          quarter_end=20,
          exact_value=12.0,
        ),
        LeverControl(
          lever_id="revenue::Primary line of business::In-home care hour::Utilization",
          quarter_start=1,
          quarter_end=20,
          min_value=0.50,
          max_value=0.90,
        ),
      ],
      targets=[
        OutputTarget(metric="Revenue", quarter_start=1, quarter_end=20, min_value=1000.0, max_value=1300.0),
        OutputTarget(metric="EBITDA", quarter_start=1, quarter_end=20, min_value=100.0, max_value=500.0),
      ],
      options=SolverOptions(max_iterations=6),
    )

    self.assertTrue(result.success)
    self.assertLess(result.objective_after, result.objective_before)

    solved_rows = result.solved_outputs
    self.assertGreaterEqual(solved_rows[0]["revenue"], 1000.0)
    self.assertGreaterEqual(solved_rows[0]["ebitda"], 100.0)
    self.assertGreater(result.objective_before, 0.0)
    self.assertEqual(len(result.solved_controller_seed), 20)
    self.assertEqual(len(result.solved_model_input_json["sections"]["revenue"]), 3)

    baseline_revenue = baseline_rows[0]["revenue"]
    solved_revenue = solved_rows[0]["revenue"]
    self.assertGreater(solved_revenue, baseline_revenue)

    price_row = next(
      row for row in result.solved_model_input_json["sections"]["revenue"]
      if row["driver"] == "Unit Price"
    )
    self.assertTrue(all(abs(value - 12.0) < 1e-9 for value in price_row["values"]))

  def test_solver_supports_period_grouped_exact_values(self) -> None:
    baseline = self._baseline_book()

    result = solve_financial_model(
      baseline,
      controls=[
        LeverControl(
          lever_id="revenue::Primary line of business::In-home care hour::Unit Price",
          quarter_start=1,
          quarter_end=4,
          exact_value=12.0,
        ),
        LeverControl(
          lever_id="revenue::Primary line of business::In-home care hour::Unit Price",
          quarter_start=5,
          quarter_end=20,
          exact_value=15.0,
        ),
      ],
      targets=[],
      options=SolverOptions(max_iterations=2),
    )

    price_row = next(
      row for row in result.solved_model_input_json["sections"]["revenue"]
      if row["driver"] == "Unit Price"
    )
    self.assertEqual(price_row["values"][:4], [12.0, 12.0, 12.0, 12.0])
    self.assertTrue(all(abs(value - 15.0) < 1e-9 for value in price_row["values"][4:]))


if __name__ == "__main__":
  unittest.main()
