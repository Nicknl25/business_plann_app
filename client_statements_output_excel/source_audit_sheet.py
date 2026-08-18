from __future__ import annotations

from .data import DraftWorkbookData, values_21
from .excel_utils import (
  CURRENCY_FORMAT,
  PERCENT_FORMAT,
  PERIOD_COUNT,
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
  # W2 (2026-08-18): mirror the persisted W1 break-even read-out
  # (finmo_json["break_even"], OPTIONAL - pre-W1 drafts have none) so the
  # Checks sheet can tie the live FINMO block out against it.
  break_even = data.finmo_json.get("break_even") if isinstance(data.finmo_json, dict) else None
  quarters = (break_even or {}).get("quarters") if isinstance(break_even, dict) else None
  if isinstance(quarters, list) and quarters:
    write_section_header(ws, row, "Break-Even Analysis")
    row += 1
    by_index = {}
    for item in quarters:
      if isinstance(item, dict):
        try:
          by_index[int(item.get("quarter_index") or 0)] = item
        except Exception:
          continue
    for label, key, fmt in [
      ("Break-Even Revenue", "be_revenue", CURRENCY_FORMAT),
      ("Cash Break-Even Revenue", "cash_be_revenue", CURRENCY_FORMAT),
      ("EBITDA-Basis Break-Even Revenue", "be_revenue_ebitda_basis", CURRENCY_FORMAT),
      ("Fixed Costs", "fixed_costs", CURRENCY_FORMAT),
      ("Variable Cost Ratio", "variable_ratio", PERCENT_FORMAT),
      ("Contribution Margin Ratio", "cm_ratio", PERCENT_FORMAT),
      ("Planned Revenue", "planned_revenue", CURRENCY_FORMAT),
      ("Margin of Safety", "margin_of_safety", PERCENT_FORMAT),
      ("Break-Even Revenue (G&A as fixed)", "be_revenue_g_and_a_fixed_sensitivity", CURRENCY_FORMAT),
    ]:
      ws.cell(row=row, column=1, value=label)
      ws.cell(row=row, column=2, value="Persisted break-even read-out (W1)")
      for idx in range(PERIOD_COUNT):
        item = by_index.get(idx) if idx >= 1 else None
        value = item.get(key) if isinstance(item, dict) else None
        cell = ws.cell(row=row, column=3 + idx, value=(value if isinstance(value, (int, float)) else None))
        set_input_style(cell, number_format=fmt)
      ctx.add_source_row("Break-Even Analysis", label, row)
      row += 1
  ws.sheet_state = "hidden"

