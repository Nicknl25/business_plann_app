from __future__ import annotations

from typing import Optional, Dict, List, Tuple

from .data import DraftWorkbookData, row_by_label, text
from .marketing_schedule_sheet import MARKETING_PERCENT_ROW_KEY
from .excel_utils import (
  ANNUAL_ANNUALIZE,
  MARKETING_SCHEDULE_SHEET,
  ANNUAL_START_COL,
  CAPEX_SHEET,
  CASH_EQUITY_SHEET,
  CURRENCY_FORMAT,
  DEBT_SHEET,
  FILL_BLUE,
  FILL_GREEN,
  FILL_LIGHT,
  FIRST_LIVE_COL,
  INTEGER_FORMAT,
  LAST_LIVE_COL,
  MODEL_INPUT_SHEET,
  NUMBER_FORMAT,
  PAYROLL_SHEET,
  PERCENT_FORMAT,
  PERIOD_COUNT,
  PERIOD_END_COL,
  PERIOD_START_COL,
  REVENUE_SHEET,
  WORKING_CAPITAL_SHEET,
  WorkbookBuildContext,
  add_annual_formulas,
  apply_base_style,
  create_sheet,
  ref,
  set_formula_style,
  set_title,
  style_row,
  write_period_headers,
  write_section_header,
)


def _format_for_label(label: str, *, default: str = CURRENCY_FORMAT) -> str:
  lower = label.lower()
  if "%" in label or "rate" in lower or lower in {"cost of goods sold", "marketing", "research & development", "general & administrative", "depreciation", "taxes", "utilization"}:
    return PERCENT_FORMAT
  if "days" in lower or "fte" in lower or "capacity" in lower:
    return NUMBER_FORMAT
  if "unit price" in lower:
    return CURRENCY_FORMAT
  return default


def _write_linked_row(
  ws,
  ctx: WorkbookBuildContext,
  *,
  row: int,
  key: str,
  label: str,
  source_sheet: str,
  source_row: int,
  detail: str,
  number_format: str,
  annual_mode: Optional[str] = None,
) -> None:
  ws.cell(row=row, column=1, value=label)
  ws.cell(row=row, column=2, value=detail)
  ctx.add_model_input_row(key, row)
  for idx in range(PERIOD_COUNT):
    col = PERIOD_START_COL + idx
    cell = ws.cell(row=row, column=col, value=f"={ref(source_sheet, source_row, col)}")
    set_formula_style(cell, number_format=number_format, internal_link=True)
  add_annual_formulas(ws, row, mode=annual_mode, label=label, number_format=number_format)
  style_row(ws, row, fill=FILL_GREEN if "Schedule" in detail else None, number_format=number_format)


def build_model_inputs_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, MODEL_INPUT_SHEET)
  apply_base_style(ws)
  set_title(ws, "Model Inputs", "Formula-driven bridge from schedules into FINMO. FINMO references this sheet only.")
  write_period_headers(ws, data.periods)
  row = 6

  write_section_header(ws, row, "Income Statement Inputs")
  row += 1
  revenue_slots: Dict[str, Dict[str, str]] = {}
  ordered_slots: List[str] = []
  for source in data.revenue_rows:
    slot = text(source.get("revenue_slot_key")) or f"{text(source.get('lob'))}::{text(source.get('product'))}"
    if slot not in revenue_slots:
      ordered_slots.append(slot)
      revenue_slots[slot] = {
        "display": " / ".join([text(source.get("lob")) or "LOB", text(source.get("product")) or "Product"])
      }
    revenue_slots[slot][text(source.get("driver"))] = slot
  for slot in ordered_slots:
    display = revenue_slots[slot]["display"]
    for driver in ["Capacity", "Unit Price", "Utilization", "COGS %", "Revenue"]:
      source_key = f"{slot}::{driver}"
      # OPTIONAL BY DESIGN, one of only two in the workbook: per-line "COGS %"
      # rows exist only on multi-line per-line-COGS drafts.
      source_row = ctx.optional_schedule_row(REVENUE_SHEET, source_key)
      if not source_row:
        # "COGS %" rows exist only on multi-line per-line-COGS drafts;
        # absent rows (all single-line workbooks) skip untouched.
        continue
      fmt = NUMBER_FORMAT if driver == "Capacity" else PERCENT_FORMAT if driver in ("Utilization", "COGS %") else CURRENCY_FORMAT
      _write_linked_row(
        ws,
        ctx,
        row=row,
        key=f"revenue::{slot}::{driver}",
        label=f"{display} - {driver}",
        source_sheet=REVENUE_SHEET,
        source_row=source_row,
        detail="Revenue Drivers schedule",
        number_format=fmt,
      )
      row += 1
  _write_linked_row(
    ws,
    ctx,
    row=row,
    key="is::Revenue",
    label="Revenue",
    source_sheet=REVENUE_SHEET,
    source_row=ctx.schedule_row(REVENUE_SHEET, "Total Revenue"),
    detail="Revenue Drivers schedule",
    number_format=CURRENCY_FORMAT,
  )
  style_row(ws, row, fill=FILL_BLUE, bold=True, number_format=CURRENCY_FORMAT, border_top=True)
  row += 1

  expense_by_label = row_by_label(data.expense_rows)
  direct_expense_sources = {
    "Cost of Goods Sold": (None, None),
    "Marketing": (None, None),
    "Research & Development": (None, None),
    # Lease/rent comes straight from the expense row, like COGS and G&A - the
    # Cash & Equity Schedule no longer carries a redundant copy (2026-08-25).
    "Lease": (None, None),
    "Payroll": (PAYROLL_SHEET, "Total Payroll"),
    "General & Administrative": (None, None),
    "Interest Rate": (DEBT_SHEET, "Interest Rate per quarter"),
    "Interest Expense": (DEBT_SHEET, "Interest Expense"),
    "Depreciation": (CAPEX_SHEET, "Depreciation Rate"),
    "Depreciation Expense": (CAPEX_SHEET, "Depreciation Expense"),
    "Taxes": (None, None),
  }
  for label, (source_sheet, source_key) in direct_expense_sources.items():
    if source_sheet and source_key:
      source_row = ctx.schedule_row(source_sheet, source_key)
      fmt = _format_for_label(label)
      _write_linked_row(
        ws,
        ctx,
        row=row,
        key=f"is::{label}",
        label=label,
        source_sheet=source_sheet,
        source_row=source_row,
        detail=f"{source_sheet} output",
        number_format=fmt,
        # DECLARED, not inferred. This row is the last consumer of
        # _ANNUALIZED_LABELS, which matches on the literal string "Interest
        # Rate" - so a reword of THIS label would have silently turned the
        # annual column from x4 into an average.
        annual_mode=ANNUAL_ANNUALIZE if label == "Interest Rate" else None,
      )
      if label == "Payroll":
        from .data import values_21

        source = expense_by_label.get(label, {"values": []})
        stub_value = values_21(source.get("values"))[0]
        stub_cell = ws.cell(row=row, column=PERIOD_START_COL, value=stub_value)
        set_formula_style(stub_cell, number_format=CURRENCY_FORMAT, internal_link=False)
      if label == "Interest Expense":
        from .data import values_21

        source = expense_by_label.get("Interest", {"values": []})
        stub_value = values_21(source.get("values"))[0] if source else 0.0
        stub_cell = ws.cell(row=row, column=PERIOD_START_COL, value=stub_value)
        set_formula_style(stub_cell, number_format=CURRENCY_FORMAT, internal_link=False)
    else:
      source = expense_by_label.get(label, {"values": []})
      values = source.get("values") or []
      ws.cell(row=row, column=1, value=label)
      # MARKETING NOW COMES FROM THE MARKETING SCHEDULE (R-MKTG-03 A1). The
      # percentage used to be 21 literals here and the Marketing Schedule read
      # them, which left that sheet downstream of the number it is supposed to
      # own - so its two levers moved nothing. The link is reversed: the
      # schedule produces the percentage, this row reads it, and FINMO reads
      # this row unchanged.
      #
      # The old literal write is REPLACED, not supplemented. Keeping both would
      # be a circular reference the moment the schedule pointed back here.
      #
      # Absent-tolerant: if the schedule sheet was not built (a draft with no
      # marketing payload) the lookup misses and this row keeps its literals,
      # exactly as before.
      marketing_source = (
        # OPTIONAL BY DESIGN, the second of two: a draft with no marketing
        # payload builds no Marketing Schedule sheet, and this row keeps its
        # literals.
        ctx.optional_schedule_row(MARKETING_SCHEDULE_SHEET, MARKETING_PERCENT_ROW_KEY)
        if label == "Marketing" else 0
      )
      ws.cell(row=row, column=2,
              value=("Marketing Schedule output" if marketing_source
                     else "Direct model driver"))
      ctx.add_model_input_row(f"is::{label}", row)
      from .data import values_21
      for idx, value in enumerate(values_21(values)):
        col = PERIOD_START_COL + idx
        if marketing_source:
          cell = ws.cell(row=row, column=col,
                         value=f"={ref(MARKETING_SCHEDULE_SHEET, marketing_source, col)}")
          set_formula_style(cell, number_format=_format_for_label(label), internal_link=True)
          continue
        cell = ws.cell(row=row, column=col, value=value)
        set_formula_style(cell, number_format=_format_for_label(label), internal_link=False)
      add_annual_formulas(ws, row, label=label, number_format=_format_for_label(label))
      style_row(ws, row, number_format=_format_for_label(label))
    row += 1

  row += 1
  write_section_header(ws, row, "Balance Sheet Inputs")
  row += 1
  bs_links: List[Tuple[str, str, str, str]] = [
    ("Accounts Receivable Days", WORKING_CAPITAL_SHEET, "Accounts Receivable Days", NUMBER_FORMAT),
    ("Inventory Days", WORKING_CAPITAL_SHEET, "Inventory Days", NUMBER_FORMAT),
    ("Accounts Payable Days", WORKING_CAPITAL_SHEET, "Accounts Payable Days", NUMBER_FORMAT),
    ("Prepaid Expenses (% of Revenue)", WORKING_CAPITAL_SHEET, "Prepaid Expenses (% of Revenue)", PERCENT_FORMAT),
    ("Deferred Revenue (% of Revenue)", WORKING_CAPITAL_SHEET, "Deferred Revenue (% of Revenue)", PERCENT_FORMAT),
    ("Short Term Debt (% of LTD)", WORKING_CAPITAL_SHEET, "Short Term Debt (% of LTD)", PERCENT_FORMAT),
    ("Owner's Capital", CASH_EQUITY_SHEET, "Owner's Capital", CURRENCY_FORMAT),
    ("Other Equity", CASH_EQUITY_SHEET, "Other Equity", CURRENCY_FORMAT),
    ("Distributions", CASH_EQUITY_SHEET, "Distributions", CURRENCY_FORMAT),
  ]
  for label, sheet, source_key, fmt in bs_links:
    _write_linked_row(
      ws,
      ctx,
      row=row,
      key=f"bs::{label}",
      label=label,
      source_sheet=sheet,
      source_row=ctx.schedule_row(sheet, source_key),
      detail=f"{sheet} schedule",
      number_format=fmt,
      # Semantics, not number format: a money row may be a FLOW (distributions,
      # capex) or a BALANCE (owner's capital), and the router knows which.
      annual_mode=None,
    )
    row += 1

  row += 1
  write_section_header(ws, row, "Cash Flow and Schedule Inputs")
  row += 1
  cash_links: List[Tuple[str, str, str, str, bool]] = [
    ("Cash Opening Balance", WORKING_CAPITAL_SHEET, "Cash Opening Balance", CURRENCY_FORMAT, True),
    ("Accounts Receivable Opening Balance", WORKING_CAPITAL_SHEET, "Accounts Receivable Opening Balance", CURRENCY_FORMAT, True),
    ("Inventory Opening Balance", WORKING_CAPITAL_SHEET, "Inventory Opening Balance", CURRENCY_FORMAT, True),
    ("Accounts Payable Opening Balance", WORKING_CAPITAL_SHEET, "Accounts Payable Opening Balance", CURRENCY_FORMAT, True),
    ("Short Term Debt Opening Balance", WORKING_CAPITAL_SHEET, "Short Term Debt Opening Balance", CURRENCY_FORMAT, True),
    ("Debt Opening Balance", DEBT_SHEET, "Opening Debt", CURRENCY_FORMAT, True),
    ("Debt Issuance", DEBT_SHEET, "Debt Issuance", CURRENCY_FORMAT, False),
    ("Debt Repayment", DEBT_SHEET, "Actual Debt Repayment", CURRENCY_FORMAT, False),
    ("Debt Closing Balance", DEBT_SHEET, "Closing Debt", CURRENCY_FORMAT, True),
    ("Lease Opening Balance", DEBT_SHEET, "Lease Opening Balance", CURRENCY_FORMAT, True),
    ("Lease Principal Repayments", DEBT_SHEET, "Lease Principal Repayments", CURRENCY_FORMAT, False),
    ("Lease Net Additions", DEBT_SHEET, "Lease Net Additions", CURRENCY_FORMAT, False),
    ("Lease Interest Expense", DEBT_SHEET, "Lease Interest Expense", CURRENCY_FORMAT, False),
    ("Lease Closing Balance", DEBT_SHEET, "Lease Closing Balance", CURRENCY_FORMAT, True),
    ("Right-of-Use Asset", DEBT_SHEET, "Right-of-Use Asset Closing", CURRENCY_FORMAT, True),
    ("Lease Asset Depreciation", DEBT_SHEET, "Lease Asset Depreciation", CURRENCY_FORMAT, False),
    ("Capital Expenditures", CAPEX_SHEET, "Capital Expenditures", CURRENCY_FORMAT, False),
    ("PPE Closing Balance", CAPEX_SHEET, "Closing PPE", CURRENCY_FORMAT, True),
    ("Accumulated Depreciation", CAPEX_SHEET, "Accumulated Depreciation", CURRENCY_FORMAT, True),
  ]
  for label, sheet, source_key, fmt, _legacy_year_end in cash_links:
    _write_linked_row(
      ws,
      ctx,
      row=row,
      key=f"cash::{label}",
      label=label,
      source_sheet=sheet,
      source_row=ctx.schedule_row(sheet, source_key),
      detail=f"{sheet} schedule",
      number_format=fmt,
      annual_mode=None,
    )
    row += 1
