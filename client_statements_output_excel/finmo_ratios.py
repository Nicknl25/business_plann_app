"""X3 — the RATIOS section of the FINMO sheet (2026-08-19).

Nick's ruling: ratios are a SECTION stacked below the break-even section on
FINMO, not a separate tab. Every ratio is a live formula over the statement
cells directly above it, so it recalculates with the model and there is no
second copy of any number.

Column-agnostic by construction: a ratio written into an annual column reads
that column's statement cells, and the statement rows already carry the right
annual treatment (income-statement rows SUM, balance-sheet rows year-end), so
the annual ratio is correct without a second formula.

Guards are mandatory, not cosmetic (docs/WORKBOOK_ANALYTICS_RESEARCH.md §3.2):
Bellweather's interest reaches 0 by Q20 and net debt turns negative, so
coverage ratios divide by zero. Every row ships wrapped — a lender-facing
sheet that prints #DIV/0! is worse than one that omits the row.
"""
from __future__ import annotations

from typing import List, Tuple

from . import design
from .excel_utils import (
  ANNUAL_START_COL,
  MODEL_INPUT_SHEET,
  FIRST_LIVE_COL,
  PERIOD_COUNT,
  PERIOD_START_COL,
  WorkbookBuildContext,
  local_ref,
  ref,
  write_section_header,
)

RATIOS_STATEMENT = "Ratios"

#: (label, number-format role). Order is the lender's reading order.
_ROWS: List[Tuple[str, str]] = [
  ("-- Liquidity", "header"),
  ("Current Ratio", "ratio"),
  ("Quick Ratio", "ratio"),
  ("Working Capital", "money"),
  ("Cash as Months of Operating Cost", "ratio"),
  ("-- Leverage", "header"),
  ("Total Debt", "money"),
  ("Net Debt", "money"),
  ("Debt to Equity", "ratio"),
  ("Debt to Assets", "percent"),
  ("Debt to EBITDA (annualised)", "ratio"),
  ("-- Coverage", "header"),
  ("EBIT", "money"),
  ("Debt Service", "money"),
  ("Interest Coverage", "ratio"),
  ("Debt Service Coverage Ratio (DSCR)", "ratio"),
  ("Fixed Charge Coverage", "ratio"),
  ("-- Profitability", "header"),
  ("Gross Margin", "percent"),
  ("EBITDA Margin", "percent"),
  ("Operating Margin (EBIT)", "percent"),
  ("Net Margin", "percent"),
  ("Return on Assets", "percent"),
  ("Return on Equity", "percent"),
  ("Return on Invested Capital", "percent"),
  ("-- Efficiency", "header"),
  ("Asset Turnover", "ratio"),
  ("Receivable Days (DSO)", "days"),
  ("Inventory Days", "days"),
  ("Payable Days (opex basis)", "days"),
  ("Cash Conversion Cycle", "days"),
  ("Revenue per Employee", "money"),
  ("-- Growth", "header"),
  ("Revenue Growth", "percent"),
  ("EBITDA Growth", "percent"),
]

_FORMATS = {
  "ratio": design.FMT_RATIO,
  "money": design.FMT_MONEY,
  "percent": design.FMT_PERCENT,
  "days": design.FMT_DAYS,
  "header": design.FMT_GENERAL,
}


def write_ratio_rows(ws, ctx: WorkbookBuildContext, *, start_row: int) -> int:
  """Reserve and label the rows; formulas are filled once the statements exist."""
  write_section_header(ws, start_row, "Ratio Analysis")
  row = start_row + 1
  for label, kind in _ROWS:
    display = label[3:] if label.startswith("-- ") else label
    cell = ws.cell(row=row, column=1, value=display)
    if kind == "header":
      cell.font = design.font("label_strong")
      cell.fill = design.fill(design.TINT_2)
    ctx.add_finmo_row(RATIOS_STATEMENT, label, row)
    row += 1
  note = ws.cell(
    row=row,
    column=1,
    value="Ratios read the statement cells above; coverage ratios show a dash when there is no "
          "debt service in the period. Payable days use the model's own opex basis.",
  )
  note.font = design.font("footnote")
  return row + 2


def fill_ratio_formulas(ws, ctx: WorkbookBuildContext) -> None:
  def r(label: str) -> int:
    return ctx.finmo_row(RATIOS_STATEMENT, label)

  def fin(statement: str, label: str, col: int) -> str:
    return local_ref(ctx.finmo_row(statement, label), col)

  def payroll_row(key: str) -> int:
    return ctx.schedule_row("Payroll Schedule", key)

  columns = [PERIOD_START_COL + i for i in range(PERIOD_COUNT)]
  columns += [ANNUAL_START_COL + i for i in range(5)]

  for col in columns:
    is_annual = col >= ANNUAL_START_COL
    rev = fin("Income Statement", "Revenue", col)
    ebitda = fin("Income Statement", "EBITDA", col)
    dep = fin("Income Statement", "Depreciation", col)
    interest = fin("Income Statement", "Interest", col)
    ni = fin("Income Statement", "Net Income", col)
    gp = fin("Income Statement", "Gross Profit", col)
    cogs = fin("Income Statement", "Cost of Goods Sold", col)
    lease = fin("Income Statement", "Lease/Rent", col)
    opex_block = (f"SUM({fin('Income Statement', 'Marketing', col)}:"
                  f"{fin('Income Statement', 'General & Administrative', col)})")
    cash = fin("Balance Sheet", "Cash", col)
    ar = fin("Balance Sheet", "Accounts Receivable", col)
    inv = fin("Balance Sheet", "Inventory", col)
    ca = fin("Balance Sheet", "Current Assets", col)
    cl = fin("Balance Sheet", "Current Liabilities", col)
    ap = fin("Balance Sheet", "Accounts Payable", col)
    std = fin("Balance Sheet", "Short Term Debt", col)
    ltd = fin("Balance Sheet", "Long Term Debt", col)
    lease_ob = fin("Balance Sheet", "Capital Lease Obligation", col)
    assets = fin("Balance Sheet", "Total Assets", col)
    equity = fin("Balance Sheet", "Total Equity", col)
    debt_repay = fin("Cash Flow", "Debt Repayment", col)
    lease_principal = fin("Cash Flow", "Capital Lease Principal Payments", col)
    # The tax factor lives on MODEL INPUTS. A same-sheet reference here used to
    # resolve to FINMO row 22 - the "Balance Sheet" section header, blank - so
    # (1 - blank) = 1 and ROIC was computed PRE-TAX. Sheet-qualified now; safe
    # in the annual columns only because the annual rate is AVERAGEd, not summed.
    _tax_row = ctx.model_input_row("is::Taxes")
    tax_rate = ref(MODEL_INPUT_SHEET, _tax_row, col) if _tax_row else "0"
    # FINMO row 6 (Days in Quarter) is written for the PERIOD columns only, so
    # in an annual column a naive reference multiplies by blank and prints
    # "0 days" - a false claim that receivables collect same-day. Annual columns
    # take the year's four quarters of days.
    if is_annual:
      year_index = col - ANNUAL_START_COL
      first_q = FIRST_LIVE_COL + year_index * 4
      days = f"SUM({local_ref(6, first_q)}:{local_ref(6, first_q + 3)})"
    else:
      days = local_ref(6, col)

    total_debt = f"({std}+{ltd}+{lease_ob})"
    # CF debt repayment is written as a negative; principal paid is its absolute
    # value. Lease principal is positive.
    service = f"({interest}+ABS({debt_repay})+ABS({lease_principal}))"
    ebit = f"({ebitda}-{dep})"

    def put(label: str, formula: str, kind: str) -> None:
      row = r(label)
      if not row:
        return
      cell = ws.cell(row=row, column=col, value=formula)
      design.calculated_cell(cell, number_format=_FORMATS[kind])

    def guarded(numerator: str, denominator: str, *, pct: bool = False) -> str:
      # A ratio never divides by a crumb (CW-043 TURN A). A denominator under
      # half a cent is the zero it would be on any statement - Harrow's paid-
      # off loan left 5e-12 of interest and Interest Coverage printed 2e17
      # where "-" belonged. Same dash as an exact zero or a negative.
      return f'=IFERROR(IF({denominator}<0.005,"-",{numerator}/{denominator}),"-")'

    put("Current Ratio", guarded(ca, cl), "ratio")
    put("Quick Ratio", guarded(f"({cash}+{ar})", cl), "ratio")
    put("Working Capital", f"={ca}-{cl}", "money")
    months = 12 if is_annual else 3
    put("Cash as Months of Operating Cost",
        f'=IFERROR(IF(({cogs}+{opex_block})<0.005,"-",{cash}/(({cogs}+{opex_block})/{months})),"-")', "ratio")

    put("Total Debt", f"={total_debt}", "money")
    put("Net Debt", f"={total_debt}-{cash}", "money")
    put("Debt to Equity", guarded(total_debt, equity), "ratio")
    put("Debt to Assets", guarded(total_debt, assets), "percent")
    put("Debt to EBITDA (annualised)",
        guarded(total_debt, f"({ebitda}*{1 if is_annual else 4})"), "ratio")

    put("EBIT", f"={ebit}", "money")
    put("Debt Service", f"={service}", "money")
    put("Interest Coverage", guarded(ebit, interest), "ratio")
    put("Debt Service Coverage Ratio (DSCR)", guarded(ebitda, service), "ratio")
    put("Fixed Charge Coverage", guarded(f"({ebitda}+{lease})", f"({service}+{lease})"), "ratio")

    put("Gross Margin", guarded(gp, rev), "percent")
    put("EBITDA Margin", guarded(ebitda, rev), "percent")
    put("Operating Margin (EBIT)", guarded(ebit, rev), "percent")
    put("Net Margin", guarded(ni, rev), "percent")
    put("Return on Assets", guarded(ni, assets), "percent")
    put("Return on Equity", guarded(ni, equity), "percent")
    # Invested capital collapses toward zero once a business is debt-free and
    # cash-rich, which turns a real ratio into a meaningless 400%. Below a tenth
    # of revenue the denominator is not an economic capital base, so say so.
    _invested = f"({equity}+{total_debt}-{cash})"
    put("Return on Invested Capital",
        f'=IFERROR(IF({_invested}<=0.1*{rev},"-",({ebit}*(1-{tax_rate}))/{_invested}),"-")', "percent")

    put("Asset Turnover", guarded(rev, assets), "ratio")
    put("Receivable Days (DSO)", guarded(f"({ar}*{days})", rev), "days")
    put("Inventory Days", guarded(f"({inv}*{days})", cogs), "days")
    put("Payable Days (opex basis)", guarded(f"({ap}*{days})", opex_block), "days")
    cc_dso = local_ref(r("Receivable Days (DSO)"), col)
    cc_dio = local_ref(r("Inventory Days"), col)
    cc_dpo = local_ref(r("Payable Days (opex basis)"), col)
    put("Cash Conversion Cycle",
        f'=IFERROR(IF(OR(ISTEXT({cc_dso}),ISTEXT({cc_dio}),ISTEXT({cc_dpo})),"-",'
        f'{cc_dso}+{cc_dio}-{cc_dpo}),"-")', "days")
    fte = payroll_row("Total Average FTE")
    if fte:
      fte_ref = ref("Payroll Schedule", fte, col)
      put("Revenue per Employee", f'=IFERROR(IF({fte_ref}<=0,"-",{rev}/{fte_ref}),"-")', "money")

    # Growth needs the PRIOR comparable column: the previous quarter inside the
    # quarterly band, the previous YEAR inside the annual band. Year 1 has no
    # prior year and the stub has no prior quarter, so both read "-".
    prior = None
    if not is_annual and col > FIRST_LIVE_COL:
      prior = col - 1
    elif is_annual and col > ANNUAL_START_COL:
      prior = col - 1
    if prior:
      for label, statement, line in (("Revenue Growth", "Income Statement", "Revenue"),
                                     ("EBITDA Growth", "Income Statement", "EBITDA")):
        now_ref = fin(statement, line, col)
        prior_ref = fin(statement, line, prior)
        put(label, f'=IFERROR(IF({prior_ref}<=0,"-",{now_ref}/{prior_ref}-1),"-")', "percent")
    else:
      put("Revenue Growth", '="-"', "percent")
      put("EBITDA Growth", '="-"', "percent")
