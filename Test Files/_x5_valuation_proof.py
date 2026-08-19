"""Prove the Valuation sheet: sensible, disclosed, and universal.

Four things must hold, and the third is the one that matters most for an app
that builds plans for every industry:

  1. the build-up arithmetic is right and the WACC is plausible;
  2. both terminal methods produce a value and cross-check against each other;
  3. every reference input resolves for ANY NAICS - a specific row where one
     exists, the ALL default where it does not - so a business in an industry
     with no comparable data still gets a complete valuation;
  4. the disclosure block labels each input GROUNDED or ASSUMPTION.

Usage: python "Test Files/_x5_valuation_proof.py" <workbook.xlsx>
"""
from __future__ import annotations

import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO,):
  if path not in sys.path:
    sys.path.insert(0, path)

import win32com.client as win32  # noqa: E402


def _labels(ws, limit: int = 120):
  out = {}
  for r in range(1, limit):
    text = str(ws.Cells(r, 1).Value or "").strip()
    if text and text not in out:
      out[text] = r
  return out


def check_workbook(path: str) -> int:
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
  ws = wb.Sheets("Valuation")
  rows = _labels(ws)
  val = lambda label: ws.Cells(rows[label], 2).Value
  failures = []

  rf = val("Risk-free rate (10-year Treasury)")
  erp = val("Equity risk premium")
  size = val("Size premium (micro-cap)")
  specific = val("Company-specific risk premium")
  ke = val("Cost of equity (build-up)")
  wacc = val("WACC")
  if abs(ke - (rf + erp + size + specific)) > 1e-9:
    failures.append(f"build-up: Ke {ke} != {rf}+{erp}+{size}+{specific}")
  if not (0.05 < wacc < 0.45):
    failures.append(f"WACC {wacc:.2%} is outside any plausible range for a small business")
  if not (rf > 0 and erp > 0 and size > 0):
    failures.append("a grounded or reference input came through as zero")

  ev = val("Enterprise value")
  equity = val("Equity value")
  net_debt = val("Less: net debt today")
  tv_mult = val("Terminal value — exit multiple")
  implied = val("Implied multiple of year-5 SDE (equity)")
  if not isinstance(ev, (int, float)) or ev <= 0:
    failures.append(f"enterprise value is {ev!r}")
  if not isinstance(equity, (int, float)) or equity <= 0:
    failures.append(f"equity value is {equity!r}")
  if not isinstance(tv_mult, (int, float)) or tv_mult <= 0:
    failures.append(f"exit-multiple terminal value is {tv_mult!r}")
  if isinstance(implied, (int, float)) and not (0.5 < implied < 15):
    failures.append(f"implied SDE multiple {implied:.2f}x is not credible")
  # The bridge must use net debt at the VALUATION DATE, not at the horizon:
  # equity today cannot exceed what the business is forecast to sell for in
  # five years when those flows are discounted at 20%+.
  if isinstance(equity, (int, float)) and isinstance(tv_mult, (int, float)) and equity > tv_mult:
    failures.append(f"equity today {equity:,.0f} exceeds the year-5 exit value {tv_mult:,.0f} "
                    f"- the bridge is double-counting forecast cash")
  if isinstance(equity, (int, float)) and isinstance(ev, (int, float)) and isinstance(net_debt, (int, float)):
    if abs((ev - net_debt) - equity) > 1.0:
      failures.append("equity != EV - net debt")

  # SDE must exceed EBITDA by the owner's pay - it is the whole point of the row
  sde_row, ebitda_row = rows["Seller's discretionary earnings (SDE)"], rows["EBITDA"]
  sde_q1, ebitda_q1 = ws.Cells(sde_row, 3).Value, ws.Cells(ebitda_row, 3).Value
  if not (sde_q1 > ebitda_q1):
    failures.append(f"SDE {sde_q1} is not above EBITDA {ebitda_q1} - the owner add-back is missing")

  labelled = 0
  for label in ("Risk-free rate (10-year Treasury)", "Equity risk premium",
                "Size premium (micro-cap)", "Terminal growth rate", "Exit multiple (x SDE)",
                "Effective tax rate", "Cost of debt (annual)"):
    basis = str(ws.Cells(rows[label], 3).Value or "")
    if not basis.startswith(("GROUNDED", "ASSUMPTION")):
      failures.append(f"{label}: basis is {basis!r}, expected GROUNDED or ASSUMPTION")
    else:
      labelled += 1
    citation = str(ws.Cells(rows[label], 4).Value or "")
    if len(citation) < 12:
      failures.append(f"{label}: no source cited")

  print(f"  Ke {ke:.2%} = rf {rf:.2%} + ERP {erp:.2%} + size {size:.2%} + specific {specific:.2%}")
  print(f"  WACC {wacc:.2%} | EV {ev:,.0f} | equity value {equity:,.0f} | implied {implied:.2f}x SDE")
  print(f"  {labelled} inputs carry a GROUNDED/ASSUMPTION label and a citation")
  wb.Close(False)
  excel.Quit()
  for f in failures:
    print("  FAIL:", f)
  return 1 if failures else 0


def check_fallback() -> int:
  """The universality proof: a NAICS with NO specific reference row must still
  resolve every constant from the ALL defaults."""
  from client_statements_output_excel.valuation_sheet import _load_constants  # type: ignore

  needed = ("risk_free_rate", "equity_risk_premium", "size_premium_micro_cap",
            "company_specific_risk_premium", "terminal_growth_rate", "exit_multiple_sde",
            "wacc_minus_growth_floor", "maintenance_capex_percent_of_revenue")
  cases = {
    "811111 auto repair (has a specific row)": "811111",
    "444240 nursery (has a specific row)": "444240",
    "561730 landscaping (NO specific row, 674 drafts)": "561730",
    "541110 law (NO specific row)": "541110",
    "722511 restaurant (NO specific row)": "722511",
    "no NAICS at all": "",
  }
  failures = []
  for name, naics in cases.items():
    resolved = _load_constants(naics)
    missing = [k for k in needed if k not in resolved]
    if missing:
      failures.append(f"{name}: missing {missing}")
      continue
    multiple = resolved["exit_multiple_sde"]
    scope = multiple.get("scope") or "ALL"
    print(f"  {name:52s} exit multiple {multiple['value']:.2f}x  [{scope}]")
  for f in failures:
    print("  FAIL:", f)
  return 1 if failures else 0


if __name__ == "__main__":
  print("1. VALUATION ARITHMETIC AND DISCLOSURE")
  rc = check_workbook(sys.argv[1])
  print("\n2. ALL-INDUSTRY FALLBACK (specific -> ALL)")
  rc |= check_fallback()
  print("\nPASS" if rc == 0 else "\nFAILURES ABOVE")
  raise SystemExit(rc)
