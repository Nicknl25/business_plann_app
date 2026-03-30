from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(PYTHON_DIR))


from financial_model_engine.model_inputs import FinancialModelInputs  # type: ignore  # noqa: E402


class FinancialModelInputsTests(unittest.TestCase):
  def test_from_controller_seed_round_trips_core_driver_shape(self) -> None:
    model_inputs = FinancialModelInputs.from_controller_seed(
      [
        {
          "quarter_index": 1,
          "revenue_products": [
            {
              "lob_name": "Primary line of business",
              "products": [
                {
                  "product_name": "In-home care hour",
                  "revenue_slot_key": "lob_1_product_1",
                  "capacity_units": 1300.0,
                  "price": 95.0,
                  "utilization": 0.85,
                }
              ],
            }
          ],
          "cogs_percent": 0.6,
          "marketing_percent": 0.08,
          "payroll_amount": 40000.0,
          "g_and_a_percent": 0.15,
          "interest_rate": 0.0,
          "depreciation_percent": 0.0,
          "tax_percent": 0.0,
        }
      ],
      start_date="2026-09-03",
      business_name="CareFirst Home Health Services",
    )

    payload = model_inputs.to_controller_seed()
    self.assertEqual(len(payload), 20)
    self.assertEqual(payload[0]["quarter_index"], 1)
    self.assertEqual(payload[0]["revenue_products"][0]["lob_name"], "Primary line of business")
    self.assertEqual(payload[0]["revenue_products"][0]["products"][0]["product_name"], "In-home care hour")
    self.assertEqual(payload[0]["revenue_products"][0]["products"][0]["revenue_slot_key"], "lob_1_product_1")
    self.assertEqual(payload[0]["revenue_products"][0]["products"][0]["capacity_units"], 1300.0)
    self.assertEqual(payload[0]["revenue_products"][0]["products"][0]["price"], 95.0)
    self.assertEqual(payload[0]["revenue_products"][0]["products"][0]["utilization"], 0.85)
    self.assertEqual(payload[0]["payroll_amount"], 40000.0)

  def test_setters_update_quarter_drivers(self) -> None:
    model_inputs = FinancialModelInputs.empty(
      start_date="2026-09-03",
      business_name="CareFirst Home Health Services",
    )

    model_inputs.set_revenue_drivers(
      quarter_index=5,
      lob_name="Primary line of business",
      product_name="In-home care hour",
      revenue_slot_key="lob_1_product_1",
      capacity_units=2000.0,
      unit_price=110.0,
      utilization=0.92,
    )
    model_inputs.set_expense_drivers(
      quarter_index=5,
      payroll_amount=65000.0,
      marketing_percent=0.11,
      cogs_percent=0.65,
      g_and_a_percent=0.12,
    )

    payload = model_inputs.to_controller_seed()
    q5 = payload[4]
    self.assertEqual(q5["quarter_index"], 5)
    self.assertEqual(q5["revenue_products"][0]["products"][0]["capacity_units"], 2000.0)
    self.assertEqual(q5["revenue_products"][0]["products"][0]["price"], 110.0)
    self.assertEqual(q5["revenue_products"][0]["products"][0]["utilization"], 0.92)
    self.assertEqual(q5["payroll_amount"], 65000.0)
    self.assertEqual(q5["marketing_percent"], 0.11)

  def test_model_input_json_round_trips_all_controller_write_sections(self) -> None:
    book = FinancialModelInputs.from_model_input_json(
      {
        "start_date": "2026-09-03",
        "sections": {
          "revenue": [
            {
              "lob": "Primary line of business",
              "product": "In-home care hour",
              "driver": "Capacity",
              "revenue_slot_key": "lob_1_product_1",
              "values": [1300.0 for _ in range(20)],
            },
            {
              "lob": "Primary line of business",
              "product": "In-home care hour",
              "driver": "Unit Price",
              "revenue_slot_key": "lob_1_product_1",
              "values": [95.0 for _ in range(20)],
            },
            {
              "lob": "Primary line of business",
              "product": "In-home care hour",
              "driver": "Utilization",
              "revenue_slot_key": "lob_1_product_1",
              "values": [0.85 for _ in range(20)],
            },
          ],
          "expenses": [
            {"label": "Payroll", "lever_id": "expenses::Payroll", "values": [40000.0 for _ in range(20)]},
            {"label": "Marketing", "lever_id": "expenses::Marketing", "values": [0.08 for _ in range(20)]},
          ],
          "balance_sheet": [
            {"label": "Accounts Receivable Days", "lever_id": "balance_sheet::Accounts Receivable Days", "values": [15.0 for _ in range(20)]},
            {"label": "Owner's Capital", "lever_id": "balance_sheet::Owner's Capital", "values": [100000.0 for _ in range(20)]},
          ],
          "schedules": {
            "debt_opening_balance_seed": 25000.0,
            "lease_opening_balance_seed": 10000.0,
            "rows": [
              {"label": "Plus: Additions (repayments), net", "lever_id": "schedules::Plus: Additions (repayments), net", "values": [0.0 for _ in range(20)]},
              {"label": "Less: Principal Repayments", "lever_id": "schedules::Less: Principal Repayments", "values": [500.0 for _ in range(20)]},
              {"label": "Plus: Net Additions", "lever_id": "schedules::Plus: Net Additions", "values": [1000.0 for _ in range(20)]},
            ],
          },
        },
      }
    )

    payload = book.to_model_input_json()
    self.assertEqual(payload["sections"]["expenses"][0]["label"], "Payroll")
    self.assertEqual(payload["sections"]["balance_sheet"][0]["label"], "Accounts Receivable Days")
    self.assertEqual(payload["sections"]["schedules"]["debt_opening_balance_seed"], 25000.0)
    self.assertEqual(len(payload["sections"]["schedules"]["rows"]), 3)
    self.assertEqual(payload["sections"]["schedules"]["rows"][1]["label"], "Less: Principal Repayments")
    self.assertEqual(payload["sections"]["revenue"][1]["driver"], "Unit Price")

  def test_set_simple_driver_updates_balance_sheet_and_schedule_rows(self) -> None:
    book = FinancialModelInputs.empty(start_date="2026-09-03", business_name="CareFirst")
    book.set_simple_driver(
      section="balance_sheet",
      label="Accounts Receivable Days",
      quarter_index=3,
      value=30.0,
      named_range="model_input_balancehseet",
      lever_id="balance_sheet::Accounts Receivable Days",
    )
    book.set_simple_driver(
      section="schedules",
      label="Less: Principal Repayments",
      quarter_index=3,
      value=750.0,
      named_range="model_input_schedules",
      lever_id="schedules::Less: Principal Repayments",
    )
    book.set_schedule_seed(debt_opening_balance_seed=15000.0, lease_opening_balance_seed=2500.0)

    payload = book.to_model_input_json()
    balance_rows = {row["label"]: row for row in payload["sections"]["balance_sheet"]}
    schedule_rows = {row["label"]: row for row in payload["sections"]["schedules"]["rows"]}
    self.assertEqual(balance_rows["Accounts Receivable Days"]["values"][2], 30.0)
    self.assertEqual(schedule_rows["Less: Principal Repayments"]["values"][2], 750.0)
    self.assertEqual(payload["sections"]["schedules"]["lease_opening_balance_seed"], 2500.0)


if __name__ == "__main__":
  unittest.main()
