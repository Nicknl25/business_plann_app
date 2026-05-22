"""Generate the sample intake-bypass scenario workbook.

Kept in the repo so the .xlsx is reproducible and reviewable. Re-run to
regenerate Test Files/intake_bypass_scenarios.xlsx.

  python "Test Files/make_intake_bypass_scenarios_xlsx.py"
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Font

THIS_DIR = Path(__file__).resolve().parent
OUT_PATH = THIS_DIR / "intake_bypass_scenarios.xlsx"

README_LINES = [
  ("intake-bypass scenarios", ""),
  ("", ""),
  ("Each non-underscore sheet is one scenario.", ""),
  ("Column A = field name, Column B = value.", ""),
  ("Rows whose field starts with '#' are comments and are ignored.", ""),
  ("Sheets whose name starts with '_' (like this one) are ignored.", ""),
  ("", ""),
  ("Required field:", ""),
  ("baseline", "name of a captured baseline snapshot (file in intake_bypass_baselines/)"),
  ("", ""),
  ("Override fields (blank cell = inherit the baseline value):", ""),
  ("Financial scalars (financials_json):", ""),
  ("  cash_on_hand, ar_balance, ap_balance, inventory_balance", ""),
  ("  current_capex, initial_assets, initial_lease, initial_equity", ""),
  ("  total_debt_outstanding, annual_interest_payment, annual_principal_payment", ""),
  ("  other_monthly_debt_payments, monthly_rent_expense, other_operating_expense", ""),
  ("  owner_compensation, current_payroll, payroll_total_year1, current_num_employees", ""),
  ("  current_cogs, current_revenue, cogs_percent_of_revenue (accepts 29% or 0.29)", ""),
  ("Shape-affecting (operating_model_json + financials_year1_json; solver re-derives revenue):", ""),
  ("  unit_price, units_per_week_capacity, utilization_rate", ""),
  ("Descriptors (operating_model_json):", ""),
  ("  naics, business_stage", ""),
  ("Flat draft columns:", ""),
  ("  business_name, business_start_date, business_address,", ""),
  ("  address_street, address_city, address_state, address_zip, address_country", ""),
  ("", ""),
  ("Numbers may be written plainly (20000), with separators ($20,000), or percents (29%).", ""),
  ("An unknown field name fails loudly so typos are caught.", ""),
]

# field, value, comment(prefix '#' on field => ignored example)
SUNNY_ROWS = [
  ("field", "value"),
  ("baseline", "sunny_glaze_donuts"),
  ("business_name", "Sunny Glaze Donuts"),
  ("# --- financial overrides: fill a value to change it, leave blank to inherit ---", ""),
  ("cash_on_hand", ""),
  ("current_capex", ""),
  ("total_debt_outstanding", ""),
  ("payroll_total_year1", ""),
  ("monthly_rent_expense", ""),
  ("other_operating_expense", ""),
  ("# --- shape-affecting overrides (optional) ---", ""),
  ("unit_price", ""),
  ("units_per_week_capacity", ""),
  ("utilization_rate", ""),
  ("# --- example stress edit: uncomment by removing the '#' and set a value ---", ""),
  ("# cash_on_hand", "20000"),
]


def main() -> int:
  wb = openpyxl.Workbook()
  ws_readme = wb.active
  ws_readme.title = "_README"
  bold = Font(bold=True)
  for i, (a, b) in enumerate(README_LINES, start=1):
    ws_readme.cell(row=i, column=1, value=a)
    ws_readme.cell(row=i, column=2, value=b)
  ws_readme["A1"].font = bold
  ws_readme.column_dimensions["A"].width = 60
  ws_readme.column_dimensions["B"].width = 70

  ws = wb.create_sheet("Sunny_Glaze_Donuts")
  for i, (a, b) in enumerate(SUNNY_ROWS, start=1):
    ws.cell(row=i, column=1, value=a)
    ws.cell(row=i, column=2, value=(b if b != "" else None))
  ws["A1"].font = bold
  ws["B1"].font = bold
  ws.column_dimensions["A"].width = 58
  ws.column_dimensions["B"].width = 24

  wb.save(str(OUT_PATH))
  print(f"Wrote {OUT_PATH}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
