"""W2 (2026-08-18) — the Dashboard sheet (docs/WRITING_PHASE_RESEARCH_2.md
Area 5 / R1-R6). Placed AFTER FINMO (``wb.active`` stays FINMO). Every KPI
tile is a live formula and every chart is a native openpyxl chart whose
series ``Reference`` live workbook cells (FINMO / Revenue Drivers / Payroll
Schedule / Debt Schedule, or small helper tables on this sheet that are
themselves formulas), so the sheet updates with the model and renders on
Excel open (``fullCalcOnLoad``). Nothing here is pasted from finmo_json
except the judged EBITDA-margin band (low/high literals from the executive
margin-band judgment stamped in ``solver_input.finmo_output_targets`` - the
band this plan was judged against), which is labelled as such.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from openpyxl.chart import BarChart, LineChart, PieChart, Reference, Series
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill
from openpyxl.utils import get_column_letter

from .break_even_sheet import BREAK_EVEN_STATEMENT, CVP_HELPER_KEY, build_cvp_chart
from .data import DraftWorkbookData, text
from .excel_utils import (
  ANNUAL_START_COL,
  CURRENCY_FORMAT,
  DASHBOARD_SHEET,
  DEBT_SHEET,
  FILL_BLUE,
  FILL_LIGHT,
  FILL_NAVY,
  FINMO_SHEET,
  FIRST_LIVE_COL,
  FONT_WHITE,
  LAST_LIVE_COL,
  NUMBER_FORMAT,
  PAYROLL_SHEET,
  PERCENT_FORMAT,
  REVENUE_SHEET,
  THIN_GRAY,
  WorkbookBuildContext,
  create_sheet,
  local_ref,
  qsheet,
  ref,
  set_formula_style,
  set_title,
)

# Helper tables live far to the right of the charts so the visible sheet is
# tiles + charts. Column 40 = AN.
HELPER_COL = 40
_QCOUNT = LAST_LIVE_COL - FIRST_LIVE_COL + 1


def _fin(ctx: WorkbookBuildContext, statement: str, label: str, col: int) -> str:
  return ref(FINMO_SHEET, ctx.finmo_row(statement, label), col)


def _fin_range(ctx: WorkbookBuildContext, statement: str, label: str) -> str:
  r = ctx.finmo_row(statement, label)
  return f"{qsheet(FINMO_SHEET)}!{get_column_letter(FIRST_LIVE_COL)}{r}:{get_column_letter(LAST_LIVE_COL)}{r}"


def _sched_range(sheet: str, row: int) -> str:
  return f"{qsheet(sheet)}!{get_column_letter(FIRST_LIVE_COL)}{row}:{get_column_letter(LAST_LIVE_COL)}{row}"


def _tile(ws, row: int, col: int, label: str, formula: str, number_format: str, note: str = "") -> None:
  """A KPI tile: label cell above a bold formula cell (2 rows x 3 cols merged)."""
  ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 2)
  ws.merge_cells(start_row=row + 1, start_column=col, end_row=row + 1, end_column=col + 2)
  lab = ws.cell(row=row, column=col, value=label)
  lab.font = Font(bold=True, color=FONT_WHITE, size=9)
  lab.fill = PatternFill("solid", fgColor=FILL_NAVY)
  lab.alignment = Alignment(horizontal="center")
  val = ws.cell(row=row + 1, column=col, value=formula)
  val.font = Font(bold=True, size=13, color=FILL_NAVY)
  val.fill = PatternFill("solid", fgColor=FILL_BLUE)
  val.alignment = Alignment(horizontal="center")
  val.number_format = number_format
  if note:
    n = ws.cell(row=row + 2, column=col, value=note)
    n.font = Font(size=8, italic=True, color="666666")


def _helper_header(ws, row: int, col: int, title: str, span: int = 3) -> None:
  ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
  c = ws.cell(row=row, column=col, value=title)
  c.font = Font(bold=True, color=FONT_WHITE, size=9)
  c.fill = PatternFill("solid", fgColor="595959")


def _quarter_labels(ws, row: int, col: int) -> None:
  for i in range(_QCOUNT):
    ws.cell(row=row, column=col + i, value=f"Q{i + 1}").font = Font(bold=True, size=9)


def _judged_band(data: DraftWorkbookData) -> Optional[List[Tuple[float, float]]]:
  """Per-quarter (low, high) EBITDA-margin band THIS plan was judged against:
  the executive margin-band judgment stamped at
  ``model_input_json.solver_input.finmo_output_targets.metrics.ebitda_margin
  .provenance.judged_margin_band`` (q11 / q20 low-high). Quarters up to 11
  carry the Q11 band, later quarters the Q20 band. Returns None when the
  judgment is absent (the raw cohort envelope is NOT used - it is not a
  band the plan was judged against)."""
  try:
    metrics = ((((data.model_input_json or {}).get("solver_input") or {}).get("finmo_output_targets") or {}).get("metrics") or {})
    prov = ((metrics.get("ebitda_margin") or {}).get("provenance") or {})
    jb = prov.get("judged_margin_band") or {}
    q11, q20 = jb.get("q11") or {}, jb.get("q20") or {}
    if q11.get("low") is None or q11.get("high") is None:
      return None
    late = q20 if (q20.get("low") is not None and q20.get("high") is not None) else q11
    out: List[Tuple[float, float]] = []
    for i in range(1, _QCOUNT + 1):
      src = q11 if i <= 11 else late
      out.append((float(src["low"]), float(src["high"])))
    return out
  except Exception:
    return None


def _revenue_slots(data: DraftWorkbookData) -> List[Tuple[str, str]]:
  ordered: List[str] = []
  display: Dict[str, str] = {}
  for source_row in data.revenue_rows:
    slot = text(source_row.get("revenue_slot_key")) or f"{text(source_row.get('lob'))}::{text(source_row.get('product'))}"
    if slot not in display:
      ordered.append(slot)
      display[slot] = " / ".join([text(source_row.get("lob")) or "LOB", text(source_row.get("product")) or "Product"])
  return [(slot, display[slot]) for slot in ordered]


def build_dashboard_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, DASHBOARD_SHEET)
  ws.sheet_view.showGridLines = False
  set_title(ws, f"{data.business_name} - Dashboard", "Live KPIs and charts driven by the model's own cells (FINMO, Revenue Drivers, Payroll Schedule, Debt Schedule). Helper tables for the charts sit in columns AN onward.")
  for col in range(1, 30):
    ws.column_dimensions[get_column_letter(col)].width = 11
  IS, BS, CF = "Income Statement", "Balance Sheet", "Cash Flow"
  y1 = ANNUAL_START_COL
  y5 = ANNUAL_START_COL + 4
  ebitda_rng = _fin_range(ctx, IS, "EBITDA")
  cash_rng = _fin_range(ctx, CF, "Ending Cash")
  be_q1 = _fin(ctx, BREAK_EVEN_STATEMENT, "Break-Even Revenue", FIRST_LIVE_COL)
  fte_row = ctx.schedule_row(PAYROLL_SHEET, "Total Ending FTE")
  closing_debt_row = ctx.schedule_row(DEBT_SHEET, "Closing Debt")

  # --- KPI tiles (rows 4-6, 8-10) ---------------------------------------
  tiles_row1 = [
    ("Year 1 Revenue", f"={_fin(ctx, IS, 'Revenue', y1)}", CURRENCY_FORMAT, ""),
    ("Year 5 Revenue", f"={_fin(ctx, IS, 'Revenue', y5)}", CURRENCY_FORMAT, ""),
    ("Year 1 EBITDA", f"={_fin(ctx, IS, 'EBITDA', y1)}", CURRENCY_FORMAT, ""),
    ("Year 1 EBITDA Margin", f"=IF({_fin(ctx, IS, 'Revenue', y1)}>0,{_fin(ctx, IS, 'EBITDA', y1)}/{_fin(ctx, IS, 'Revenue', y1)},0)", PERCENT_FORMAT, ""),
    ("Year 5 EBITDA Margin", f"=IF({_fin(ctx, IS, 'Revenue', y5)}>0,{_fin(ctx, IS, 'EBITDA', y5)}/{_fin(ctx, IS, 'Revenue', y5)},0)", PERCENT_FORMAT, ""),
    ("First EBITDA-Positive Quarter", f'=IFERROR("Q"&MATCH(TRUE,INDEX({ebitda_rng}>=0,0),0),"none in 5 yrs")', "General", "quarter where EBITDA first >= 0"),
  ]
  tiles_row2 = [
    ("Break-Even Revenue (Q1, pre-tax)", f"={be_q1}", CURRENCY_FORMAT, "headline: fixed / contribution margin"),
    ("Cash Break-Even Revenue (Q1)", f"={_fin(ctx, BREAK_EVEN_STATEMENT, 'Cash Break-Even Revenue', FIRST_LIVE_COL)}", CURRENCY_FORMAT, "adds scheduled principal, drops depreciation"),
    ("Margin of Safety (Q1)", f"={_fin(ctx, BREAK_EVEN_STATEMENT, 'Margin of Safety', FIRST_LIVE_COL)}", PERCENT_FORMAT, "planned revenue above break-even"),
    ("Cash Low Point", f"=MIN({cash_rng})", CURRENCY_FORMAT, ""),
    ("Cash Low Quarter", f'=IFERROR("Q"&MATCH(MIN({cash_rng}),{cash_rng},0),"-")', "General", ""),
    ("Peak Debt Balance", (f"=MAX({_sched_range(DEBT_SHEET, closing_debt_row)})" if closing_debt_row else "=0"), CURRENCY_FORMAT, ""),
  ]
  tiles_row3 = [
    ("Headcount Q1 (FTE)", (f"={ref(PAYROLL_SHEET, fte_row, FIRST_LIVE_COL)}" if fte_row else "=0"), NUMBER_FORMAT, ""),
    ("Headcount Q20 (FTE)", (f"={ref(PAYROLL_SHEET, fte_row, LAST_LIVE_COL)}" if fte_row else "=0"), NUMBER_FORMAT, ""),
    ("Year 1 Net Income", f"={_fin(ctx, IS, 'Net Income', y1)}", CURRENCY_FORMAT, ""),
    ("Year 5 Net Income", f"={_fin(ctx, IS, 'Net Income', y5)}", CURRENCY_FORMAT, ""),
    ("Year 1 Gross Margin", f"=IF({_fin(ctx, IS, 'Revenue', y1)}>0,{_fin(ctx, IS, 'Gross Profit', y1)}/{_fin(ctx, IS, 'Revenue', y1)},0)", PERCENT_FORMAT, ""),
    ("Ending Cash Q20", f"={_fin(ctx, CF, 'Ending Cash', LAST_LIVE_COL)}", CURRENCY_FORMAT, ""),
  ]
  for r, tiles in ((4, tiles_row1), (8, tiles_row2), (12, tiles_row3)):
    for i, (label, formula, fmt, note) in enumerate(tiles):
      _tile(ws, r, 1 + i * 4, label, formula, fmt, note)

  # --- Helper tables (col AN+) --------------------------------------------
  hcol = HELPER_COL
  hrow = 4
  # (a) Margins by quarter + industry band
  _helper_header(ws, hrow, hcol, "Margins by quarter (formulas) + the EBITDA-margin band this plan was judged against (executive judgment, Q11 / Q20)", span=8)
  hrow += 1
  _quarter_labels(ws, hrow, hcol + 1)
  gm_row, em_row, band_lo_row, band_hi_row = hrow + 1, hrow + 2, hrow + 3, hrow + 4
  ws.cell(row=gm_row, column=hcol, value="Gross Margin %")
  ws.cell(row=em_row, column=hcol, value="EBITDA Margin %")
  band = _judged_band(data)
  ws.cell(row=band_lo_row, column=hcol, value="Judged EBITDA band - low")
  ws.cell(row=band_hi_row, column=hcol, value="Judged EBITDA band - high")
  for i in range(_QCOUNT):
    col = FIRST_LIVE_COL + i
    c = hcol + 1 + i
    rev = _fin(ctx, IS, "Revenue", col)
    ws.cell(row=gm_row, column=c, value=f"=IF({rev}>0,{_fin(ctx, IS, 'Gross Profit', col)}/{rev},0)").number_format = PERCENT_FORMAT
    ws.cell(row=em_row, column=c, value=f"=IF({rev}>0,{_fin(ctx, IS, 'EBITDA', col)}/{rev},0)").number_format = PERCENT_FORMAT
    if band:
      ws.cell(row=band_lo_row, column=c, value=band[i][0]).number_format = PERCENT_FORMAT
      ws.cell(row=band_hi_row, column=c, value=band[i][1]).number_format = PERCENT_FORMAT
  hrow = band_hi_row + 2
  # (b) Cost structure Y1
  _helper_header(ws, hrow, hcol, "Year 1 cost structure (formulas off FINMO Y1)", span=3)
  hrow += 1
  cost_first = hrow
  for label in ("Cost of Goods Sold", "Marketing", "Research & Development", "Lease/Rent", "Payroll", "General & Administrative", "Depreciation", "Interest"):
    ws.cell(row=hrow, column=hcol, value=label)
    ws.cell(row=hrow, column=hcol + 1, value=f"={_fin(ctx, IS, label, y1)}").number_format = CURRENCY_FORMAT
    hrow += 1
  cost_last = hrow - 1
  hrow += 1
  # (c) Sources & uses Y1
  _helper_header(ws, hrow, hcol, "Year 1 sources & uses of cash (formulas off FINMO Y1)", span=3)
  hrow += 1
  su_first = hrow
  su_items = [
    ("Operating cash flow", f"={_fin(ctx, CF, 'Operating Cash Flow', y1)}"),
    ("New borrowing", f"={_fin(ctx, CF, 'Debt Issuance (New Borrowing)', y1)}"),
    ("Owner equity in", f"={_fin(ctx, CF, 'Equity', y1)}"),
    ("Capital expenditures", f"=-ABS({_fin(ctx, CF, 'Capital Expenditures', y1)})"),
    ("Debt repayment", f"=-ABS({_fin(ctx, CF, 'Debt Repayment', y1)})"),
    ("Lease principal", f"=-ABS({_fin(ctx, CF, 'Capital Lease Principal Payments', y1)})"),
    ("Distributions", f"=-ABS({_fin(ctx, CF, 'Distributions', y1)})"),
  ]
  for label, formula in su_items:
    ws.cell(row=hrow, column=hcol, value=label)
    ws.cell(row=hrow, column=hcol + 1, value=formula).number_format = CURRENCY_FORMAT
    hrow += 1
  su_last = hrow - 1
  hrow += 1
  # (d) Cash + debt by quarter (formulas)
  _helper_header(ws, hrow, hcol, "Ending cash and closing debt by quarter", span=8)
  hrow += 1
  _quarter_labels(ws, hrow, hcol + 1)
  cash_row, debt_row = hrow + 1, hrow + 2
  ws.cell(row=cash_row, column=hcol, value="Ending Cash")
  ws.cell(row=debt_row, column=hcol, value="Closing Debt")
  for i in range(_QCOUNT):
    col = FIRST_LIVE_COL + i
    c = hcol + 1 + i
    ws.cell(row=cash_row, column=c, value=f"={_fin(ctx, CF, 'Ending Cash', col)}").number_format = CURRENCY_FORMAT
    ws.cell(row=debt_row, column=c, value=(f"={ref(DEBT_SHEET, closing_debt_row, col)}" if closing_debt_row else "=0")).number_format = CURRENCY_FORMAT
  hrow = debt_row + 2
  # (e) Revenue by line + headcount (formulas)
  slots = _revenue_slots(data)
  _helper_header(ws, hrow, hcol, "Revenue by line and headcount by quarter", span=8)
  hrow += 1
  _quarter_labels(ws, hrow, hcol + 1)
  line_rows: List[Tuple[int, str]] = []
  for slot, display in slots:
    hrow += 1
    ws.cell(row=hrow, column=hcol, value=display)
    src = ctx.schedule_row(REVENUE_SHEET, f"{slot}::Revenue")
    for i in range(_QCOUNT):
      ws.cell(row=hrow, column=hcol + 1 + i, value=f"={ref(REVENUE_SHEET, src, FIRST_LIVE_COL + i)}").number_format = CURRENCY_FORMAT
    line_rows.append((hrow, display))
  hrow += 1
  head_row = hrow
  ws.cell(row=head_row, column=hcol, value="Total Ending FTE")
  for i in range(_QCOUNT):
    ws.cell(row=head_row, column=hcol + 1 + i, value=(f"={ref(PAYROLL_SHEET, fte_row, FIRST_LIVE_COL + i)}" if fte_row else "=0")).number_format = NUMBER_FORMAT
  qlab_row_margins = gm_row - 1

  # --- Charts -----------------------------------------------------------
  cats = Reference(ws, min_col=hcol + 1, max_col=hcol + _QCOUNT, min_row=qlab_row_margins)

  # 1 Revenue by line (stacked bars)
  c1 = BarChart(); c1.type = "col"; c1.grouping = "stacked"; c1.overlap = 100
  c1.title = "Revenue by quarter" + (" (by line)" if len(line_rows) > 1 else "")
  c1.y_axis.title = "$"; c1.y_axis.number_format = "$#,##0"
  for r, display in line_rows:
    s = Series(Reference(ws, min_col=hcol + 1, max_col=hcol + _QCOUNT, min_row=r), title=display)
    c1.series.append(s)
  c1.set_categories(cats)
  c1.varyColors = False
  if len(line_rows) <= 1:
    c1.legend = None
  c1.height, c1.width = 8, 16
  ws.add_chart(c1, "A16")

  # 2 Margins + band
  c2 = LineChart(); c2.title = "Gross margin and EBITDA margin (dashed = judged EBITDA band)"
  c2.y_axis.title = "% of revenue"; c2.y_axis.number_format = "0%"
  for r, title, color in ((gm_row, "Gross Margin %", "1F4E79"), (em_row, "EBITDA Margin %", "C00000")):
    s = Series(Reference(ws, min_col=hcol + 1, max_col=hcol + _QCOUNT, min_row=r), title=title)
    s.graphicalProperties.line.solidFill = color; s.graphicalProperties.line.width = 28575; s.smooth = False
    c2.series.append(s)
  if band:
    for r, title in ((band_lo_row, "Judged EBITDA band - low"), (band_hi_row, "Judged EBITDA band - high")):
      s = Series(Reference(ws, min_col=hcol + 1, max_col=hcol + _QCOUNT, min_row=r), title=title)
      s.graphicalProperties.line.solidFill = "A5A5A5"; s.graphicalProperties.line.dashStyle = "dash"; s.smooth = False
      c2.series.append(s)
  c2.set_categories(cats)
  c2.height, c2.width = 8, 16
  ws.add_chart(c2, "K16")

  # 3 Cash + debt
  c3 = LineChart(); c3.title = "Ending cash and closing debt"
  c3.y_axis.title = "$"; c3.y_axis.number_format = "$#,##0"
  for r, title, color in ((cash_row, "Ending Cash", "70AD47"), (debt_row, "Closing Debt", "ED7D31")):
    s = Series(Reference(ws, min_col=hcol + 1, max_col=hcol + _QCOUNT, min_row=r), title=title)
    s.graphicalProperties.line.solidFill = color; s.graphicalProperties.line.width = 28575; s.smooth = False
    c3.series.append(s)
  c3.set_categories(cats)
  c3.height, c3.width = 8, 16
  ws.add_chart(c3, "A34")

  # 4 Break-even CVP (same helper range as FINMO, referenced cross-sheet)
  helper = ctx.schedule_rows.get(CVP_HELPER_KEY) or {}
  if helper:
    fin_ws = wb[FINMO_SHEET]
    c4 = build_cvp_chart(fin_ws, first=helper["first"], last=helper["last"], be_r=helper["be"], plan_r1=helper["plan1"], plan_r2=helper["plan2"], loss_r=helper["loss"], profit_r=helper["profit"], title="Break-Even (Cost-Volume-Profit) - Q1")
    c4.height, c4.width = 8, 16
    ws.add_chart(c4, "K34")

  # 5 Cost structure Y1 (pie)
  c5 = PieChart(); c5.title = "Year 1 cost structure"
  c5.add_data(Reference(ws, min_col=hcol + 1, min_row=cost_first, max_row=cost_last), titles_from_data=False)
  c5.set_categories(Reference(ws, min_col=hcol, min_row=cost_first, max_row=cost_last))
  c5.dataLabels = DataLabelList(); c5.dataLabels.showPercent = True; c5.dataLabels.showVal = False; c5.dataLabels.showSerName = False; c5.dataLabels.showCatName = False; c5.dataLabels.showLegendKey = False
  c5.height, c5.width = 8, 16
  ws.add_chart(c5, "A52")

  # 6 Headcount ramp
  c6 = LineChart(); c6.title = "Headcount (total ending FTE)"
  c6.y_axis.title = "FTE"
  s = Series(Reference(ws, min_col=hcol + 1, max_col=hcol + _QCOUNT, min_row=head_row), title="Total Ending FTE")
  s.graphicalProperties.line.solidFill = "7030A0"; s.graphicalProperties.line.width = 28575; s.smooth = False
  c6.series.append(s); c6.set_categories(cats)
  c6.height, c6.width = 8, 16
  ws.add_chart(c6, "K52")

  # 7 Sources & uses Y1 (bars)
  c7 = BarChart(); c7.type = "bar"; c7.title = "Year 1 sources (+) and uses (-) of cash"
  c7.x_axis.number_format = "$#,##0"
  c7.add_data(Reference(ws, min_col=hcol + 1, min_row=su_first, max_row=su_last), titles_from_data=False)
  c7.set_categories(Reference(ws, min_col=hcol, min_row=su_first, max_row=su_last))
  c7.legend = None
  for s7 in c7.series:
    s7.invertIfNegative = False  # negatives (uses) render solid, extending left
    s7.graphicalProperties.solidFill = "1F4E79"
    s7.dLbls = DataLabelList(); s7.dLbls.showVal = True; s7.dLbls.showSerName = False; s7.dLbls.showCatName = False; s7.dLbls.showLegendKey = False; s7.dLbls.numFmt = "$#,##0"
  c7.height, c7.width = 8, 16
  ws.add_chart(c7, "A70")

  for ch in ws._charts:
    try:
      ch.x_axis.delete = False
      ch.y_axis.delete = False
      if ch.legend is not None:
        ch.legend.position = "b"
    except Exception:
      pass
  ws.sheet_properties.tabColor = "00B050"
