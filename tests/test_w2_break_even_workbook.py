"""W2 (2026-08-18) — break-even rendered in the workbook + Dashboard sheet.

Pins, on the P3.40 valid workbook payload fixture (no DB):
  1. the Break-Even Analysis block sits DIRECTLY BELOW the P&L (Net Income)
     on FINMO, before the Balance Sheet, with live formulas across all 21
     periods + 5 annual columns, referencing P&L cells (not literals);
  2. the headline row is pre-tax BE, with cash BE and EBITDA-basis rows and
     the units row(s) referencing Revenue Drivers unit price;
  3. the CVP helper range + native scatter chart exist on FINMO, and the
     Dashboard sheet sits right after FINMO with formula tiles + 7 charts;
     wb.active stays FINMO;
  4. ABSENT-TOLERANT: a finmo_json WITHOUT break_even (pre-W1) still builds
     (block + charts render; no Audit Source tie-out rows), and WITH a
     break_even block the Audit Source mirror + Checks tie-out rows appear;
  5. no cell text starts with '=' unless it is a formula (the '= Revenue'
     note that made Excel refuse the file - regression pin).
"""
from __future__ import annotations

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, "python"), os.path.join(REPO, "tests")):
  if path not in sys.path:
    sys.path.insert(0, path)

from _p3_40_contract_2_fixtures import valid_workbook_payload_dict  # noqa: E402
from client_statements_output_excel.break_even_sheet import BREAK_EVEN_STATEMENT  # noqa: E402
from client_statements_output_excel.data import DraftWorkbookData  # noqa: E402
from client_statements_output_excel.workbook_builder import build_client_financial_model_workbook  # noqa: E402


def _data(payload: dict) -> DraftWorkbookData:
  return DraftWorkbookData(
    draft_row={},
    model_input_json=payload.get("model_input_json") or {},
    finmo_json=payload.get("finmo_json") or {},
    payroll_headcount=payload.get("payroll_headcount") or {},
    debt_schedule=payload.get("debt_schedule") or {},
    planning_run_json=payload.get("planning_run_json") or {},
    run_diagnostics=payload.get("run_diagnostics"),
  )


def _labels(ws):
  """label -> FIRST row carrying it (Net Income / Depreciation appear on both the P&L and the Cash Flow)."""
  out = {}
  for r in range(1, ws.max_row + 1):
    v = ws.cell(row=r, column=1).value
    if isinstance(v, str) and v not in out:
      out[v] = r
  return out


def _fake_break_even() -> dict:
  q = lambda i: {  # noqa: E731
    "quarter_index": i, "fixed_costs": 1000.0 + i, "fixed_components": {"payroll": 800.0, "lease": 200.0, "depreciation": 0.0, "interest": float(i)},
    "variable_ratio": 0.4, "variable_components": {"cogs": 0.4}, "cm_ratio": 0.6, "be_revenue": (1000.0 + i) / 0.6,
    "be_revenue_ebitda_basis": 1000.0 / 0.6, "cash_be_revenue": (1000.0 + i) / 0.6, "scheduled_principal": 0.0,
    "be_revenue_g_and_a_fixed_sensitivity": (1000.0 + i) / 0.6, "planned_revenue": 5000.0, "ebitda": 100.0,
    "margin_of_safety": 0.5, "per_line": [],
  }
  return {"version": "break_even_v1", "basis": {}, "methodology": {"notes": []}, "summary": {"first_ebitda_positive_quarter": 1}, "quarters": [q(i) for i in range(1, 21)]}


class BreakEvenWorkbookTests(unittest.TestCase):
  def setUp(self):
    self.payload = valid_workbook_payload_dict()

  def test_block_below_pl_with_live_formulas(self):
    wb = build_client_financial_model_workbook(_data(self.payload))
    ws = wb["FINMO"]
    labels = _labels(ws)
    ni = labels["Net Income"]
    hdr = labels[BREAK_EVEN_STATEMENT]
    bs = labels["Balance Sheet"]
    self.assertGreater(hdr, ni)
    self.assertLess(hdr, bs, "block must sit between the P&L and the Balance Sheet")
    for label in ("Fixed Costs", "Variable Costs", "Variable Cost Ratio", "Contribution Margin Ratio", "Break-Even Revenue", "Cash Break-Even Revenue", "EBITDA-Basis Break-Even Revenue", "Planned Revenue", "Margin of Safety", "Break-Even Revenue (G&A as fixed)"):
      r = labels[label]
      self.assertTrue(hdr < r < bs, label)
      for col in range(3, 3 + 21 + 5):  # C..W periods + X..AB annual
        v = ws.cell(row=r, column=col).value
        self.assertIsInstance(v, str, f"{label} col {col}")
        self.assertTrue(v.startswith("="), f"{label} col {col} not a formula: {v!r}")
    # Break-Even Revenue Q1 = Fixed / CM referencing the block's own rows.
    be_q1 = ws.cell(row=labels["Break-Even Revenue"], column=4).value
    self.assertIn(f"D{labels['Fixed Costs']}", be_q1)
    self.assertIn(f"D{labels['Contribution Margin Ratio']}", be_q1)
    # Fixed = Payroll + Lease/Rent + Depreciation + Interest (P&L cells)
    fixed_q1 = ws.cell(row=labels["Fixed Costs"], column=4).value
    for pl in ("Payroll", "Lease/Rent", "Depreciation", "Interest"):
      self.assertIn(f"D{labels[pl]}", fixed_q1)
    # Units row references the Revenue Drivers unit price.
    unit_rows = [l for l in labels if l.startswith("Break-Even Units")]
    self.assertTrue(unit_rows)
    self.assertIn("'Revenue Drivers'!", ws.cell(row=labels[unit_rows[0]], column=4).value)

  def test_cvp_helper_and_charts_and_dashboard(self):
    wb = build_client_financial_model_workbook(_data(self.payload))
    ws = wb["FINMO"]
    labels = _labels(ws)
    self.assertTrue(any(str(l).startswith("Cost-Volume-Profit Chart Data") for l in labels))
    self.assertEqual(len(ws._charts), 1)
    names = wb.sheetnames
    self.assertEqual(names.index("Dashboard"), names.index("FINMO") + 1)
    self.assertEqual(wb.active.title, "FINMO")
    dash = wb["Dashboard"]
    self.assertEqual(len(dash._charts), 7)
    # KPI tiles are formulas referencing FINMO / the block.
    tile_values = [dash.cell(row=r, column=c).value for r in (5, 9, 13) for c in (1, 5, 9, 13, 17, 21)]
    self.assertTrue(all(isinstance(v, str) and v.startswith("=") for v in tile_values), tile_values)
    self.assertTrue(any("Break-Even" in str(dash.cell(row=8, column=c).value) for c in (1, 5)))

  def test_absent_tolerant_and_tie_out_when_present(self):
    payload = valid_workbook_payload_dict()
    payload["finmo_json"].pop("break_even", None)
    wb = build_client_financial_model_workbook(_data(payload))
    audit = wb["Audit Source"]
    self.assertNotIn(BREAK_EVEN_STATEMENT, _labels(audit))
    checks = wb["Checks"]
    tie_labels = [checks.cell(row=r, column=2).value for r in range(1, checks.max_row + 1)]
    self.assertFalse(any("Break-Even Revenue Q1" == v for v in tie_labels))
    # With a block: mirror + tie-outs appear.
    payload2 = valid_workbook_payload_dict()
    payload2["finmo_json"]["break_even"] = _fake_break_even()
    wb2 = build_client_financial_model_workbook(_data(payload2))
    self.assertIn(BREAK_EVEN_STATEMENT, _labels(wb2["Audit Source"]))
    tie_labels2 = [wb2["Checks"].cell(row=r, column=2).value for r in range(1, wb2["Checks"].max_row + 1)]
    self.assertIn("Break-Even Revenue Q1", tie_labels2)
    self.assertIn("Cash Break-Even Revenue Q1", tie_labels2)

  def test_no_text_cell_masquerades_as_a_formula(self):
    """Regression: a note text starting with '=' is written as a formula and
    makes Excel refuse to open the file (found in W2 verification)."""
    wb = build_client_financial_model_workbook(_data(self.payload))
    for ws in wb.worksheets:
      for row in ws.iter_rows():
        for c in row:
          if isinstance(c.value, str) and c.value.startswith("="):
            self.assertNotRegex(c.value, r"^=\s", f"{ws.title}!{c.coordinate}: {c.value!r}")


if __name__ == "__main__":
  unittest.main()
