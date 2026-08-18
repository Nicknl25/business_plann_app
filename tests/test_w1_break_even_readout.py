"""W1 (2026-08-18) — break-even DERIVED READ-OUT (finmo_json['break_even']).

Docs: docs/WRITING_PHASE_RESEARCH_2.md R5 + Nick's W1 brief. Pins:
  1. the ruled formula on a synthetic model with hand-computable numbers
     (fixed / (1 - variable ratios)), EBITDA-basis + cash BE + G&A-fixed
     sensitivity + margin of safety + first_ebitda_positive_quarter;
  2. classification keys off FORMULA_REGISTRY + value_kind, so the ratio rows
     the engine does NOT apply to revenue (Interest Rate, Taxes,
     Depreciation) never enter the variable ratio;
  3. multi-line: per-line COGS source + blended-mix BE units sum to BE revenue;
  4. the block is OPTIONAL on FinmoOutputContract (pre-W1 drafts stay valid)
     AND survives the model_dump round-trip when present (the drop the
     research flagged at DraftWorkbookData.from_contract).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO / "python"
for p in (str(REPO), str(PYTHON_DIR)):
  if p not in sys.path:
    sys.path.insert(0, p)

from financial_model_engine.finmo_model import calculate_finmo_model  # type: ignore  # noqa: E402
from financial_model_engine.model_inputs import FinancialModelInputs  # type: ignore  # noqa: E402
from client_intake_and_finmo.finmo_break_even import (  # type: ignore  # noqa: E402
  compute_break_even_block,
  _revenue_ratio_expense_labels,
)


def _book(*, per_line_cogs: bool = False) -> FinancialModelInputs:
  book = FinancialModelInputs.empty(start_date="2026-01-01", business_name="BE Fixture")
  for q in range(1, 21):
    book.set_revenue_drivers(quarter_index=q, lob_name="A", product_name="widget", capacity_units=1000, unit_price=100.0, utilization=0.5, revenue_slot_key="lob_1_product_1")
    if per_line_cogs:
      book.set_revenue_drivers(quarter_index=q, lob_name="B", product_name="service", capacity_units=200, unit_price=250.0, utilization=0.5, revenue_slot_key="lob_2_product_1")
      book.quarter(q).find_or_create_product(lob_name="A", product_name="widget", revenue_slot_key="lob_1_product_1").cogs_percent = 0.50
      book.quarter(q).find_or_create_product(lob_name="B", product_name="service", revenue_slot_key="lob_2_product_1").cogs_percent = 0.20
    book.set_expense_drivers(
      quarter_index=q,
      cogs_percent=0.40, marketing_percent=0.05, r_and_d_percent=0.0, g_and_a_percent=0.05,
      lease_amount=5000.0, payroll_amount=15000.0,
      interest_rate=0.02, depreciation_percent=0.0, tax_percent=0.21,
    )
  return book


class BreakEvenReadoutTests(unittest.TestCase):
  def test_registry_classification_excludes_non_revenue_ratio_rows(self):
    labels = _revenue_ratio_expense_labels()
    self.assertEqual(set(labels), {"Cost of Goods Sold", "Marketing", "Research & Development", "General & Administrative"})
    for bad in ("Interest Rate", "Taxes", "Depreciation", "Lease", "Payroll"):
      self.assertNotIn(bad, labels)

  def test_single_line_formula_hand_check(self):
    book = _book()
    rows = calculate_finmo_model(book).quarter_rows()
    block = compute_break_even_block(book=book, quarter_rows_raw=rows)
    self.assertEqual(block["version"], "break_even_v1")
    q1 = block["quarters"][0]
    r1 = rows[0]
    # revenue 1000*0.5*100 = 50,000; variable = .40+.05+.05 = .50; fixed = 15000+5000+dep+int
    self.assertAlmostEqual(q1["planned_revenue"], 50000.0, places=3)
    self.assertAlmostEqual(q1["variable_ratio"], 0.50, places=6)
    fixed = r1["payroll"] + r1["lease_rent"] + r1["depreciation"] + r1["interest"]
    self.assertAlmostEqual(q1["fixed_costs"], fixed, places=3)
    self.assertAlmostEqual(q1["be_revenue"], fixed / 0.5, places=2)
    self.assertAlmostEqual(q1["be_revenue_ebitda_basis"], 20000.0 / 0.5, places=2)
    principal = r1["debt_repayment"] + r1["lease_principal_repayments"]
    self.assertAlmostEqual(q1["cash_be_revenue"], (20000.0 + r1["interest"] + principal) / 0.5, places=2)
    # G&A-as-fixed sensitivity: fixed + G&A $ over (cm + gna ratio)
    self.assertAlmostEqual(q1["be_revenue_g_and_a_fixed_sensitivity"], (fixed + r1["general_and_administrative"]) / 0.55, places=2)
    self.assertAlmostEqual(q1["margin_of_safety"], (50000.0 - fixed / 0.5) / 50000.0, places=6)
    # EBITDA = 50,000 - 25,000 - 20,000 = 5,000 >= 0 from Q1
    self.assertEqual(block["summary"]["first_ebitda_positive_quarter"], 1)
    self.assertEqual(len(block["quarters"]), 20)
    self.assertEqual(block["summary"]["y1_annualized"]["quarters"], [1, 2, 3, 4])
    self.assertEqual(block["summary"]["y5_annualized"]["quarters"], [17, 18, 19, 20])
    self.assertEqual(q1["per_line"][0]["cogs_pct_source"], "blended")
    self.assertAlmostEqual(q1["per_line"][0]["be_units"] * 100.0, q1["be_revenue"], places=2)

  def test_first_ebitda_positive_quarter_tracks_the_crossing(self):
    book = _book()
    # Make Q1..Q3 loss-making by cutting utilization; EBITDA crosses at Q4.
    for q in (1, 2, 3):
      book.set_revenue_drivers(quarter_index=q, lob_name="A", product_name="widget", utilization=0.1)
    rows = calculate_finmo_model(book).quarter_rows()
    block = compute_break_even_block(book=book, quarter_rows_raw=rows)
    self.assertLess(rows[0]["ebitda"], 0.0)
    self.assertEqual(block["summary"]["first_ebitda_positive_quarter"], 4)
    self.assertLess(block["quarters"][0]["margin_of_safety"], 0.0)

  def test_multi_line_per_line_units_sum_to_be_revenue(self):
    book = _book(per_line_cogs=True)
    rows = calculate_finmo_model(book).quarter_rows()
    block = compute_break_even_block(book=book, quarter_rows_raw=rows)
    q1 = block["quarters"][0]
    self.assertEqual({p["cogs_pct_source"] for p in q1["per_line"]}, {"per_line"})
    # blended COGS = mix-weighted: rev A 50,000 @ .50, rev B 25,000 @ .20 -> 30,000/75,000 = .40
    self.assertAlmostEqual(q1["variable_components"]["cogs"], 0.40, places=6)
    total = sum(p["be_units"] * p["price"] for p in q1["per_line"])
    self.assertAlmostEqual(total, q1["be_revenue"], places=2)
    self.assertAlmostEqual(sum(p["mix_share"] for p in q1["per_line"]), 1.0, places=6)
    self.assertFalse(block["basis"]["line_standalone_break_even"])

  def test_contract_optional_and_round_trip(self):
    from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import FinmoOutputContract  # type: ignore
    book = _book()
    rows = calculate_finmo_model(book).quarter_rows()
    block = compute_break_even_block(book=book, quarter_rows_raw=rows)
    periods = [{"slot_index": i, "column_index": 7 + i, "column_letter": "G", "year": 2026, "quarter": float(i), "date": "2026-01-01", "is_stub": i == 0} for i in range(21)]
    row = {"label": "Revenue", "values": [0.0] * 21}
    base = {"contract_version": "finmo_output_v1", "periods": periods, "pl": [row], "balance_sheet": [row], "cash_flow": [row]}
    absent = FinmoOutputContract.model_validate(dict(base))
    self.assertIsNone(absent.break_even)  # pre-W1 drafts remain valid
    self.assertNotIn("break_even", absent.model_dump(mode="json", exclude_none=True))
    present = FinmoOutputContract.model_validate(dict(base, break_even=block))
    dumped = present.model_dump(mode="json")
    self.assertEqual(dumped["break_even"]["summary"]["q1"]["be_revenue"], block["summary"]["q1"]["be_revenue"])
    self.assertEqual(len(dumped["break_even"]["quarters"]), 20)


if __name__ == "__main__":
  unittest.main()
