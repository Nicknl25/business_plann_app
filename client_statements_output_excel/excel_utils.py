from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from openpyxl import Workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .data import PERIOD_COUNT


MODEL_INPUT_SHEET = "Model Inputs"
FINMO_SHEET = "FINMO"
CHECKS_SHEET = "Checks"
SOURCE_SHEET = "Audit Source"
REVENUE_SHEET = "Revenue Drivers"
PAYROLL_SHEET = "Payroll Schedule"
DEBT_SHEET = "Debt Schedule"
CAPEX_SHEET = "CapEx Depreciation"
WORKING_CAPITAL_SHEET = "Working Capital"
CASH_EQUITY_SHEET = "Cash Equity Schedule"
DASHBOARD_SHEET = "Dashboard"  # W2 (2026-08-18)

PERIOD_START_COL = 3
PERIOD_END_COL = PERIOD_START_COL + PERIOD_COUNT - 1
FIRST_LIVE_COL = PERIOD_START_COL + 1
LAST_LIVE_COL = PERIOD_END_COL
ANNUAL_START_COL = PERIOD_END_COL + 1

FILL_NAVY = "1F4E79"
FILL_BLUE = "D9EAF7"
FILL_LIGHT = "F3F6F8"
FILL_GREEN = "E2F0D9"
FILL_YELLOW = "FFF2CC"
FILL_GRAY = "E7E6E6"
FONT_BLUE = "0000FF"
FONT_GREEN = "008000"
FONT_BLACK = "000000"
FONT_WHITE = "FFFFFF"
FONT_RED = "FF0000"

THIN_GRAY = Side(style="thin", color="D9E2F3")
MEDIUM_BLUE = Side(style="medium", color=FILL_NAVY)

CURRENCY_FORMAT = '$#,##0;[Red]($#,##0);-'
NUMBER_FORMAT = '#,##0.0;[Red](#,##0.0);-'
INTEGER_FORMAT = '#,##0;[Red](#,##0);-'
PERCENT_FORMAT = '0.0%;[Red](0.0%);-'
MULTIPLE_FORMAT = '0.0x'
DATE_FORMAT = 'yyyy-mm-dd'


@dataclass
class WorkbookBuildContext:
  period_cols: Dict[int, int] = field(default_factory=dict)
  annual_cols: Dict[int, int] = field(default_factory=dict)
  schedule_rows: Dict[str, Dict[str, int]] = field(default_factory=dict)
  model_input_rows: Dict[str, int] = field(default_factory=dict)
  finmo_rows: Dict[str, Dict[str, int]] = field(default_factory=dict)
  source_rows: Dict[str, Dict[str, int]] = field(default_factory=dict)

  def add_schedule_row(self, sheet: str, key: str, row: int) -> None:
    self.schedule_rows.setdefault(sheet, {})[key] = row

  def schedule_row(self, sheet: str, key: str) -> int:
    return self.schedule_rows.get(sheet, {}).get(key, 0)

  def add_model_input_row(self, key: str, row: int) -> None:
    self.model_input_rows[key] = row

  def model_input_row(self, key: str) -> int:
    return self.model_input_rows.get(key, 0)

  def add_finmo_row(self, statement: str, key: str, row: int) -> None:
    self.finmo_rows.setdefault(statement, {})[key] = row

  def finmo_row(self, statement: str, key: str) -> int:
    return self.finmo_rows.get(statement, {}).get(key, 0)

  def add_source_row(self, statement: str, key: str, row: int) -> None:
    self.source_rows.setdefault(statement, {})[key] = row

  def source_row(self, statement: str, key: str) -> int:
    return self.source_rows.get(statement, {}).get(key, 0)


def qsheet(name: str) -> str:
  return "'" + name.replace("'", "''") + "'"


def ref(sheet: str, row: int, col: int, *, abs_ref: bool = False) -> str:
  prefix = "$" if abs_ref else ""
  return f"{qsheet(sheet)}!{prefix}{get_column_letter(col)}{prefix}{row}"


def local_ref(row: int, col: int, *, abs_ref: bool = False) -> str:
  prefix = "$" if abs_ref else ""
  return f"{prefix}{get_column_letter(col)}{prefix}{row}"


def range_ref(sheet: str, row: int, start_col: int, end_col: int) -> str:
  return f"{qsheet(sheet)}!{get_column_letter(start_col)}{row}:{get_column_letter(end_col)}{row}"


def create_workbook() -> Workbook:
  wb = Workbook()
  default = wb.active
  wb.remove(default)
  try:
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"
  except Exception:
    pass
  return wb


def create_sheet(wb: Workbook, title: str) -> Worksheet:
  ws = wb.create_sheet(title)
  ws.sheet_view.showGridLines = False
  return ws


def apply_base_style(ws: Worksheet) -> None:
  ws.freeze_panes = "C6"
  ws.sheet_view.showGridLines = False
  widths = {
    "A": 32,
    "B": 26,
  }
  for col, width in widths.items():
    ws.column_dimensions[col].width = width
  for col in range(PERIOD_START_COL, PERIOD_END_COL + 1):
    ws.column_dimensions[get_column_letter(col)].width = 14
  for col in range(ANNUAL_START_COL, ANNUAL_START_COL + 5):
    ws.column_dimensions[get_column_letter(col)].width = 14


def set_title(ws: Worksheet, title: str, subtitle: str = "") -> None:
  ws["A1"] = title
  ws["A1"].font = Font(bold=True, size=16, color=FILL_NAVY)
  if subtitle:
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, color="666666")


def write_period_headers(ws: Worksheet, periods: List[dict], *, row: int = 4, include_annual: bool = True) -> None:
  labels = ["Stub"] + [f"Q{i}" for i in range(1, PERIOD_COUNT)]
  for index, label in enumerate(labels):
    col = PERIOD_START_COL + index
    cell = ws.cell(row=row, column=col, value=label)
    cell.fill = PatternFill("solid", fgColor=FILL_NAVY)
    cell.font = Font(bold=True, color=FONT_WHITE)
    cell.alignment = Alignment(horizontal="center")
    period = periods[index] if index < len(periods) else {}
    date_value = period.get("date") or ""
    parsed_date = None
    if isinstance(date_value, str) and date_value:
      try:
        parsed_date = datetime.strptime(date_value[:10], "%Y-%m-%d").date()
      except Exception:
        parsed_date = None
    date_cell = ws.cell(row=row + 1, column=col, value=parsed_date or str(date_value or ""))
    if parsed_date:
      date_cell.number_format = DATE_FORMAT
    date_cell.font = Font(size=9, color="666666")
    date_cell.alignment = Alignment(horizontal="center")
  if include_annual:
    for year in range(1, 6):
      col = ANNUAL_START_COL + year - 1
      cell = ws.cell(row=row, column=col, value=f"Y{year}")
      cell.fill = PatternFill("solid", fgColor="595959")
      cell.font = Font(bold=True, color=FONT_WHITE)
      cell.alignment = Alignment(horizontal="center")
      ws.cell(row=row + 1, column=col, value="Annual").font = Font(size=9, color="666666")


def write_section_header(ws: Worksheet, row: int, title: str, *, end_col: int = ANNUAL_START_COL + 4) -> None:
  ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
  cell = ws.cell(row=row, column=1, value=title)
  cell.fill = PatternFill("solid", fgColor=FILL_NAVY)
  cell.font = Font(bold=True, color=FONT_WHITE)
  cell.alignment = Alignment(horizontal="left")


def style_row(
  ws: Worksheet,
  row: int,
  *,
  start_col: int = 1,
  end_col: int = ANNUAL_START_COL + 4,
  fill: Optional[str] = None,
  bold: bool = False,
  font_color: str = FONT_BLACK,
  number_format: Optional[str] = None,
  border_top: bool = False,
) -> None:
  for col in range(start_col, end_col + 1):
    cell = ws.cell(row=row, column=col)
    if fill:
      cell.fill = PatternFill("solid", fgColor=fill)
    cell.font = Font(bold=bold, color=font_color)
    cell.alignment = Alignment(horizontal="right" if col >= PERIOD_START_COL else "left")
    if number_format and col >= PERIOD_START_COL:
      cell.number_format = number_format
    cell.border = Border(
      top=MEDIUM_BLUE if border_top else THIN_GRAY,
      bottom=THIN_GRAY,
    )


def set_input_style(cell: Cell, *, number_format: Optional[str] = None) -> None:
  cell.font = Font(color=FONT_BLUE)
  cell.fill = PatternFill("solid", fgColor=FILL_YELLOW)
  cell.alignment = Alignment(horizontal="right")
  if number_format:
    cell.number_format = number_format


def set_formula_style(cell: Cell, *, number_format: Optional[str] = None, internal_link: bool = False) -> None:
  cell.font = Font(color=FONT_GREEN if internal_link else FONT_BLACK)
  cell.alignment = Alignment(horizontal="right")
  if number_format:
    cell.number_format = number_format


def write_values_row(
  ws: Worksheet,
  row: int,
  label: str,
  values: Iterable[float],
  *,
  detail: str = "",
  number_format: str = CURRENCY_FORMAT,
  input_style: bool = True,
  include_stub: bool = True,
) -> None:
  ws.cell(row=row, column=1, value=label)
  ws.cell(row=row, column=2, value=detail)
  value_list = list(values)
  if include_stub and len(value_list) == PERIOD_COUNT:
    start_index = 0
  elif include_stub:
    value_list = [0.0] + value_list
    start_index = 0
  else:
    start_index = 1
  for idx, value in enumerate(value_list[start_index:], start=start_index):
    col = PERIOD_START_COL + idx
    cell = ws.cell(row=row, column=col, value=value)
    if input_style:
      set_input_style(cell, number_format=number_format)
    else:
      set_formula_style(cell, number_format=number_format)


def write_formula_row(
  ws: Worksheet,
  row: int,
  label: str,
  formulas: Iterable[str],
  *,
  detail: str = "",
  number_format: str = CURRENCY_FORMAT,
  include_stub: bool = True,
  internal_link: bool = True,
) -> None:
  ws.cell(row=row, column=1, value=label)
  ws.cell(row=row, column=2, value=detail)
  formula_list = list(formulas)
  start_index = 0 if include_stub else 1
  for idx, formula in enumerate(formula_list[start_index:], start=start_index):
    col = PERIOD_START_COL + idx
    cell = ws.cell(row=row, column=col, value=formula)
    set_formula_style(cell, number_format=number_format, internal_link=internal_link)


def annual_formula_for_row(row: int, year_index: int, *, use_year_end: bool = False) -> str:
  start_col = FIRST_LIVE_COL + ((year_index - 1) * 4)
  end_col = start_col + 3
  if use_year_end:
    return f"={local_ref(row, end_col)}"
  return f"=SUM({local_ref(row, start_col)}:{local_ref(row, end_col)})"


def add_annual_formulas(ws: Worksheet, row: int, *, use_year_end: bool = False, number_format: str = CURRENCY_FORMAT) -> None:
  for year in range(1, 6):
    col = ANNUAL_START_COL + year - 1
    cell = ws.cell(row=row, column=col, value=annual_formula_for_row(row, year, use_year_end=use_year_end))
    set_formula_style(cell, number_format=number_format)


def style_used_range(ws: Worksheet, *, max_row: int, max_col: int) -> None:
  for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
    for cell in row:
      cell.border = Border(
        left=cell.border.left or THIN_GRAY,
        right=cell.border.right or THIN_GRAY,
        top=cell.border.top or THIN_GRAY,
        bottom=cell.border.bottom or THIN_GRAY,
      )
      if cell.row >= 4 and cell.column >= PERIOD_START_COL:
        cell.alignment = Alignment(horizontal="right")


def set_tab_colors(wb: Workbook) -> None:
  colors = {
    REVENUE_SHEET: "70AD47",
    PAYROLL_SHEET: "5B9BD5",
    DEBT_SHEET: "ED7D31",
    CAPEX_SHEET: "A5A5A5",
    WORKING_CAPITAL_SHEET: "FFC000",
    CASH_EQUITY_SHEET: "4472C4",
    MODEL_INPUT_SHEET: "7030A0",
    FINMO_SHEET: "1F4E79",
    DASHBOARD_SHEET: "00B050",
    CHECKS_SHEET: "C00000",
    SOURCE_SHEET: "808080",
  }
  for sheet_name, color in colors.items():
    if sheet_name in wb.sheetnames:
      wb[sheet_name].sheet_properties.tabColor = color
