"""Prove the ANNUAL columns display each row the way its own kind requires.

The defect this pins: annual aggregation used to have two modes (SUM or
last-quarter) chosen by a boolean, so RATE rows were summed and a client saw a
$2,599 unit price for a $640 service, 247% utilisation and a 107% tax rate.

This opens a REAL workbook in Excel, recalculates it, and asserts each row
against the rule its semantics demand:

  RATE / LEVEL   the annual figure must lie within the range of that year's
                 four quarters (an average cannot escape its own inputs) -
                 which a sum does not, so the old bug fails this by
                 construction.
  FLOW           the annual figure must equal the sum of the four quarters.
  BALANCE        the annual figure must equal the year-END quarter, and an
                 "Opening ..." row the year-START quarter.

Usage: python "Test Files/_x5_annual_columns_correct.py" <workbook.xlsx>
"""
from __future__ import annotations

import sys
import time

import win32com.client as win32

FIRST_Q_COL = 4        # D = Q1
ANNUAL_COL = 24        # X = Y1
TOL = 0.02

# sheet -> {row label: kind}
EXPECTED = {
  "Model Inputs": {
    "Unit Price": "rate", "Utilization": "rate", "Capacity": "flow",
    "Cost of Goods Sold": "rate", "Marketing": "rate", "General & Administrative": "rate",
    "Taxes": "rate", "Depreciation": "rate",
    "Accounts Receivable Days": "rate", "Inventory Days": "rate",
    "Accounts Payable Days": "rate", "Prepaid Expenses (% of Revenue)": "rate",
    "Revenue": "flow", "Payroll": "flow", "Lease": "flow", "Distributions": "flow",
    "Debt Opening Balance": "year_start", "Debt Closing Balance": "year_end",
    "PPE Closing Balance": "year_end",
  },
  "Debt Schedule": {"Interest Rate": "annualized", "Opening Debt": "year_start",
                    "Closing Debt": "year_end", "Interest Expense": "flow"},
  "CapEx Depreciation": {"Depreciation Rate": "rate", "Opening PPE": "year_start",
                         "Closing PPE": "year_end", "Capital Expenditures": "flow"},
  "FINMO": {"Revenue": "flow", "EBITDA": "flow", "Cash": "year_end",
            "Gross Margin": "rate", "EBITDA Margin": "rate", "Net Margin": "rate",
            "Receivable Days (DSO)": "positive", "Inventory Days": "positive",
            "Payable Days (opex basis)": "positive", "Cash Conversion Cycle": "nonzero",
            "Return on Invested Capital": "rate_or_dash",
            "Cash as Months of Operating Cost": "positive",
            "Contribution Margin Ratio": "rate", "Margin of Safety": "rate"},
}


def main(path: str) -> int:
  excel = win32.gencache.EnsureDispatch("Excel.Application")
  excel.Visible = False
  excel.DisplayAlerts = False
  wb = excel.Workbooks.Open(path)
  for _ in range(20):
    try:
      wb.Sheets(1).Name
      break
    except Exception:
      time.sleep(1.5)
  excel.CalculateFullRebuild()

  failures, checked = [], 0
  for sheet_name, rows in EXPECTED.items():
    ws = wb.Sheets(sheet_name)
    labels = {}
    for r in range(1, 260):
      text = str(ws.Cells(r, 1).Value or "").strip()
      if text and text not in labels:
        labels[text] = r
    for label, kind in rows.items():
      row = labels.get(label)
      if row is None:  # driver rows are prefixed with the line of business
        row = next((r for text, r in labels.items() if text.endswith(f"- {label}")), None)
      if row is None:
        failures.append(f"{sheet_name}!{label}: row not found")
        continue
      quarters = [ws.Cells(row, FIRST_Q_COL + i).Value for i in range(4)]
      annual = ws.Cells(row, ANNUAL_COL).Value
      if any(q is None for q in quarters):
        continue
      qs = [float(q) for q in quarters]
      checked += 1
      if kind == "rate":
        if not isinstance(annual, (int, float)):
          failures.append(f"{sheet_name}!{label}: annual is {annual!r}, expected a number")
        elif not (min(qs) - TOL <= float(annual) <= max(qs) + TOL):
          failures.append(
            f"{sheet_name}!{label}: annual {annual:.6f} is OUTSIDE the quarters "
            f"[{min(qs):.6f}, {max(qs):.6f}] - a rate was aggregated like a flow")
      elif kind == "annualized":
        want = sum(qs)
        if not isinstance(annual, (int, float)) or abs(float(annual) - want) > max(TOL, abs(want) * 1e-6):
          failures.append(f"{sheet_name}!{label}: annualized {annual!r} != 4x average {want:.6f}")
      elif kind == "flow":
        want = sum(qs)
        if not isinstance(annual, (int, float)) or abs(float(annual) - want) > max(TOL, abs(want) * 1e-6):
          failures.append(f"{sheet_name}!{label}: flow annual {annual!r} != sum {want:.2f}")
      elif kind == "year_end":
        if not isinstance(annual, (int, float)) or abs(float(annual) - qs[3]) > TOL:
          failures.append(f"{sheet_name}!{label}: year-end annual {annual!r} != Q4 {qs[3]:.2f}")
      elif kind == "year_start":
        if not isinstance(annual, (int, float)) or abs(float(annual) - qs[0]) > TOL:
          failures.append(f"{sheet_name}!{label}: year-start annual {annual!r} != Q1 {qs[0]:.2f}")
      elif kind in ("positive", "nonzero"):
        if isinstance(annual, (int, float)) and abs(float(annual)) < 1e-9:
          failures.append(f"{sheet_name}!{label}: annual is 0 - the factor it needs is blank in "
                          f"the annual column (quarters were {qs[0]:.2f}..{qs[3]:.2f})")
      elif kind == "rate_or_dash":
        if isinstance(annual, (int, float)) and float(annual) > 2.0:
          failures.append(f"{sheet_name}!{label}: annual {annual:.2%} - implausible, guard missing")

  # The ratio section's headers must not print a number at all.
  fin = wb.Sheets("FINMO")
  for r in range(1, 260):
    text = str(fin.Cells(r, 1).Value or "").strip()
    if text in ("Liquidity", "Leverage", "Coverage", "Profitability", "Efficiency", "Growth"):
      checked += 1
      value = fin.Cells(r, ANNUAL_COL).Value
      if isinstance(value, (int, float)):
        failures.append(f"FINMO!{text} (section header): annual prints {value!r}, expected blank")

  wb.Close(False)
  excel.Quit()

  print(f"{checked} annual cells checked against their row's semantics")
  if failures:
    print(f"\nFAILURES ({len(failures)}):")
    for f in failures:
      print("  -", f)
    return 1
  print("ALL CORRECT: every rate lands inside its own quarters, every flow sums, "
        "every balance takes the right end of the year, and no section header prints a number.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1]))
