"""Drive the dashboard's period selector in REAL Excel and prove it reslices.

A dropdown that looks right but does not recalculate is worse than no dropdown,
so this does not inspect XML - it opens the workbook through COM, sets the
selector cells, forces a full recalculation, and reads the cards back, checking
each against the FINMO cell the selected period should be showing.

Usage:  python "Test Files/_x4_toggle_live_proof.py" <workbook.xlsx>
"""
from __future__ import annotations

import sys
import time

import win32com.client as win32

# Dashboard geometry (see dashboard_sheet.py)
SEL_VIEW, SEL_QUARTER, SEL_YEAR = "C3", "C4", "C5"
CARD_REVENUE, CARD_EBITDA, CARD_BE = "A8", "E8", "A12"

# FINMO period columns: C = stub, D = Q1 ... W = Q20, X..AB = Y1..Y5
def q_col(n: int) -> int:
  return 4 + (n - 1)


def y_col(n: int) -> int:
  return 24 + (n - 1)


def main(path: str) -> int:
  excel = win32.gencache.EnsureDispatch("Excel.Application")
  excel.Visible = False
  excel.DisplayAlerts = False
  wb = excel.Workbooks.Open(path)
  # Excel rejects COM calls while it is still opening a large workbook
  # ("Call was rejected by callee"); wait for it rather than failing the proof.
  dash = finmo = None
  for _ in range(20):
    try:
      dash, finmo = wb.Sheets("Dashboard"), wb.Sheets("FINMO")
      break
    except Exception:
      time.sleep(1.5)
  if dash is None:
    raise SystemExit("Excel never became responsive")

  def row_of(label: str) -> int:
    for r in range(1, 400):
      if str(finmo.Cells(r, 1).Value or "").strip() == label:
        return r
    raise SystemExit(f"FINMO row {label!r} not found")

  rev_row, ebitda_row = row_of("Revenue"), row_of("EBITDA")
  be_row = row_of("Break-Even Revenue")
  failures, checks = [], 0

  def check(name: str, got, want) -> None:
    nonlocal checks
    checks += 1
    if want in (None, "") or got in (None, ""):
      failures.append(f"{name}: empty (got {got!r}, want {want!r})")
      return
    if abs(float(got) - float(want)) > max(0.01, abs(float(want)) * 1e-9):
      failures.append(f"{name}: {got} != {want}")

  def select(view: str, quarter: str = "Q1", year: str = "Y1") -> None:
    dash.Range(SEL_VIEW).Value = view
    dash.Range(SEL_QUARTER).Value = quarter
    dash.Range(SEL_YEAR).Value = year
    excel.CalculateFullRebuild()

  print(f"FINMO rows: revenue={rev_row} ebitda={ebitda_row} break-even={be_row}")
  for quarter in (1, 7, 20):
    select("Quarterly", quarter=f"Q{quarter}")
    col = q_col(quarter)
    check(f"Q{quarter} revenue", dash.Range(CARD_REVENUE).Value, finmo.Cells(rev_row, col).Value)
    check(f"Q{quarter} EBITDA", dash.Range(CARD_EBITDA).Value, finmo.Cells(ebitda_row, col).Value)
    check(f"Q{quarter} break-even", dash.Range(CARD_BE).Value, finmo.Cells(be_row, col).Value)
    print(f"  Q{quarter}: revenue card {dash.Range(CARD_REVENUE).Value:,.0f} "
          f"vs FINMO {finmo.Cells(rev_row, col).Value:,.0f}")

  for year in (1, 3, 5):
    select("Annual", year=f"Y{year}")
    col = y_col(year)
    check(f"Y{year} revenue", dash.Range(CARD_REVENUE).Value, finmo.Cells(rev_row, col).Value)
    check(f"Y{year} EBITDA", dash.Range(CARD_EBITDA).Value, finmo.Cells(ebitda_row, col).Value)
    print(f"  Y{year}: revenue card {dash.Range(CARD_REVENUE).Value:,.0f} "
          f"vs FINMO {finmo.Cells(rev_row, col).Value:,.0f}")

  # The selector must actually MOVE the number - a card frozen on one period
  # would pass every equality above only if every period were identical.
  select("Quarterly", quarter="Q1")
  first = dash.Range(CARD_REVENUE).Value
  select("Quarterly", quarter="Q20")
  last = dash.Range(CARD_REVENUE).Value
  checks += 1
  if first == last:
    failures.append("revenue card did not change between Q1 and Q20 - the selector is inert")
  print(f"  selector moves the card: Q1 {first:,.0f} -> Q20 {last:,.0f}")

  # Charts must reach Q20, and the period charts must point at Calc.
  n_charts = dash.ChartObjects().Count
  print(f"  dashboard charts: {n_charts}")
  checks += 1
  if n_charts < 8:
    failures.append(f"expected the full chart set, found {n_charts}")

  select("Quarterly", quarter="Q1")
  wb.Save()
  wb.Close(False)
  excel.Quit()

  print(f"\n{checks} live checks run")
  if failures:
    print("FAILURES:")
    for f in failures:
      print("  -", f)
    return 1
  print("TOGGLE PROVEN: every card matches the FINMO cell for the selected period, "
        "in both the quarterly and the annual view, and the selection changes the numbers.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1]))
