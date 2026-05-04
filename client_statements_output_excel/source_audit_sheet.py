from __future__ import annotations

from .data import DraftWorkbookData, values_21
from .excel_utils import (
  CURRENCY_FORMAT,
  SOURCE_SHEET,
  WorkbookBuildContext,
  apply_base_style,
  create_sheet,
  set_input_style,
  set_title,
  write_period_headers,
  write_section_header,
)


def build_source_audit_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, SOURCE_SHEET)
  apply_base_style(ws)
  set_title(ws, "Audit Source", "Persisted system outputs used only for checks and audit tie-outs.")
  write_period_headers(ws, data.periods)
  row = 6
  for statement_key, statement_title in [
    ("pl", "Income Statement"),
    ("balance_sheet", "Balance Sheet"),
    ("cash_flow", "Cash Flow"),
  ]:
    write_section_header(ws, row, statement_title)
    row += 1
    for item in data.finmo_json.get(statement_key) or []:
      if not isinstance(item, dict):
        continue
      label = str(item.get("label") or "").strip()
      if not label:
        continue
      ws.cell(row=row, column=1, value=label)
      ws.cell(row=row, column=2, value="Persisted FINMO")
      for idx, value in enumerate(values_21(item.get("values"))):
        cell = ws.cell(row=row, column=3 + idx, value=value)
        set_input_style(cell, number_format=CURRENCY_FORMAT)
      ctx.add_source_row(statement_title, label, row)
      row += 1
    row += 2
  ws.sheet_state = "hidden"

