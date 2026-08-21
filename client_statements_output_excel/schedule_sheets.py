from __future__ import annotations

from typing import Dict, List

from openpyxl.styles import Font, PatternFill

from . import design
from .data import DraftWorkbookData, live_values, number, row_by_label, text, values_21
from .excel_utils import (
  ANNUAL_ANNUALIZE,
  ANNUAL_AVERAGE,
  ANNUAL_SUM,
  ANNUAL_YEAR_END,
  ANNUAL_YEAR_START,
  hide_stub_column,
  ANNUAL_YEAR_END,
  ANNUAL_START_COL,
  CAPEX_SHEET,
  CASH_EQUITY_SHEET,
  CURRENCY_FORMAT,
  DATE_FORMAT,
  DEBT_SHEET,
  FILL_BLUE,
  FILL_GRAY,
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
  local_ref,
  qsheet,
  ref,
  set_formula_style,
  set_input_style,
  set_title,
  style_row,
  write_period_headers,
  write_section_header,
  write_values_row,
)


def _fmt_for_row(row: Dict[str, object]) -> str:
  kind = text(row.get("value_kind"))
  semantics = text(row.get("input_semantics")).lower()
  label = text(row.get("label")).lower()
  if kind == "ratio" or "percent" in semantics or "rate" in label or "percent" in label:
    return PERCENT_FORMAT
  if kind == "count" or "days" in semantics or "fte" in semantics or "day" in label:
    return NUMBER_FORMAT
  if kind == "currency":
    return CURRENCY_FORMAT
  return CURRENCY_FORMAT


def _annual_quarter_bounds(year_index: int) -> tuple[int, int]:
  start_col = FIRST_LIVE_COL + ((year_index - 1) * 4)
  return start_col, start_col + 3


def _add_annual_average_formulas(ws, row: int, *, number_format: str) -> None:
  for year in range(1, 6):
    start_col, end_col = _annual_quarter_bounds(year)
    cell = ws.cell(
      row=row,
      column=ANNUAL_START_COL + year - 1,
      value=f"=AVERAGE({local_ref(row, start_col)}:{local_ref(row, end_col)})",
    )
    set_formula_style(cell, number_format=number_format)


def _add_annual_ratio_formulas(
  ws,
  row: int,
  *,
  numerator_row: int,
  denominator_row: int,
  number_format: str,
) -> None:
  for year in range(1, 6):
    col = ANNUAL_START_COL + year - 1
    cell = ws.cell(
      row=row,
      column=col,
      value=f"=IFERROR({local_ref(numerator_row, col)}/{local_ref(denominator_row, col)},0)",
    )
    set_formula_style(cell, number_format=number_format)


def build_revenue_drivers_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, REVENUE_SHEET)
  apply_base_style(ws)
  set_title(ws, "Revenue Drivers", "Source operating drivers. Model Inputs links to these rows.")
  write_period_headers(ws, data.periods)
  write_section_header(ws, 6, "Revenue Driver Source Rows")
  row = 7
  revenue_groups: Dict[str, Dict[str, Dict[str, object]]] = {}
  ordered: List[str] = []
  for source_row in data.revenue_rows:
    slot = text(source_row.get("revenue_slot_key")) or f"{text(source_row.get('lob'))}::{text(source_row.get('product'))}"
    if slot not in revenue_groups:
      ordered.append(slot)
      revenue_groups[slot] = {}
    revenue_groups[slot][text(source_row.get("driver"))] = source_row

  total_capacity_rows: List[int] = []
  total_revenue_rows: List[int] = []
  for slot in ordered:
    group = revenue_groups[slot]
    display = " / ".join(
      [
        text(next(iter(group.values())).get("lob")) or "LOB",
        text(next(iter(group.values())).get("product")) or "Product",
      ]
    )
    write_section_header(ws, row, display)
    row += 1
    # WS1(b): the per-line "COGS %" source row exists only on multi-line
    # drafts whose lines carry their own COGS percents — single-line
    # workbooks are unchanged.
    slot_drivers = ["Capacity", "Unit Price", "Utilization"] + (["COGS %"] if "COGS %" in group else [])
    for driver in slot_drivers:
      source = group.get(driver, {"values": []})
      fmt = NUMBER_FORMAT if driver == "Capacity" else CURRENCY_FORMAT if driver == "Unit Price" else PERCENT_FORMAT
      write_values_row(
        ws,
        row,
        f"{display} - {driver}",
        values_21(source.get("values")),
        detail="Source driver",
        number_format=fmt,
      )
      ctx.add_schedule_row(REVENUE_SHEET, f"{slot}::{driver}", row)
      if driver == "Capacity":
        total_capacity_rows.append(row)
      style_row(ws, row, number_format=fmt)
      row += 1
    revenue_row = row
    ws.cell(row=row, column=1, value=f"{display} - Revenue")
    ws.cell(row=row, column=2, value="Capacity x Unit Price x Utilization")
    for idx in range(PERIOD_COUNT):
      col = PERIOD_START_COL + idx
      cap = local_ref(ctx.schedule_row(REVENUE_SHEET, f"{slot}::Capacity"), col)
      price = local_ref(ctx.schedule_row(REVENUE_SHEET, f"{slot}::Unit Price"), col)
      util = local_ref(ctx.schedule_row(REVENUE_SHEET, f"{slot}::Utilization"), col)
      cell = ws.cell(row=row, column=col, value=f"={cap}*{price}*{util}")
      set_formula_style(cell, number_format=CURRENCY_FORMAT)
    add_annual_formulas(ws, row, label=f"{display} - Revenue")
    style_row(ws, row, fill=FILL_GREEN, bold=True, number_format=CURRENCY_FORMAT, border_top=True)
    ctx.add_schedule_row(REVENUE_SHEET, f"{slot}::Revenue", row)
    total_revenue_rows.append(revenue_row)
    row += 2

  ws.cell(row=row, column=1, value="Total Capacity Units")
  ws.cell(row=row, column=2, value="All revenue driver capacity units")
  for idx in range(PERIOD_COUNT):
    col = PERIOD_START_COL + idx
    refs = [local_ref(r, col) for r in total_capacity_rows]
    ws.cell(row=row, column=col, value=f"=SUM({','.join(refs)})" if refs else "=0")
    set_formula_style(ws.cell(row=row, column=col), number_format=NUMBER_FORMAT)
  add_annual_formulas(ws, row, label="Total Capacity Units", number_format=NUMBER_FORMAT)
  style_row(ws, row, fill=FILL_LIGHT, bold=True, number_format=NUMBER_FORMAT, border_top=True)
  ctx.add_schedule_row(REVENUE_SHEET, "Total Capacity Units", row)
  row += 1

  ws.cell(row=row, column=1, value="Total Revenue")
  ws.cell(row=row, column=2, value="All revenue products")
  for idx in range(PERIOD_COUNT):
    col = PERIOD_START_COL + idx
    refs = [local_ref(r, col) for r in total_revenue_rows]
    ws.cell(row=row, column=col, value=f"=SUM({','.join(refs)})" if refs else "=0")
    set_formula_style(ws.cell(row=row, column=col), number_format=CURRENCY_FORMAT)
  add_annual_formulas(ws, row, label="Total Revenue")
  style_row(ws, row, fill=FILL_BLUE, bold=True, number_format=CURRENCY_FORMAT, border_top=True)
  ctx.add_schedule_row(REVENUE_SHEET, "Total Revenue", row)
  total_revenue_row = row
  row += 2

  # ACTUAL REVENUE QoQ GROWTH lives HERE now, in the live driver section
  # directly under revenue, because it is a RESULT of the drivers above and it
  # recomputes when a client edits them. It used to sit inside a "Stage Ramp
  # Contract" block that has been omitted (R_RAMP_01, 7f9be65) - leaving the one
  # live row under a header for a block that no longer exists would have
  # mislabelled it. Addressed through the ctx key, never a literal row number,
  # because its row moves with the number of products.
  ws.cell(row=row, column=1, value="Actual Revenue QoQ Growth")
  ws.cell(row=row, column=2, value="Total revenue growth from modeled revenue drivers")
  for idx in range(PERIOD_COUNT):
    col = PERIOD_START_COL + idx
    formula = "=0" if idx == 0 else f"=IFERROR({local_ref(total_revenue_row, col)}/{local_ref(total_revenue_row, col - 1)}-1,0)"
    cell = ws.cell(row=row, column=col, value=formula)
    set_formula_style(cell, number_format=PERCENT_FORMAT, internal_link=True)
  _add_annual_average_formulas(ws, row, number_format=PERCENT_FORMAT)
  style_row(ws, row, fill=FILL_LIGHT, number_format=PERCENT_FORMAT)
  ctx.add_schedule_row(REVENUE_SHEET, "Actual Revenue QoQ Growth", row)
  row += 1

  hide_stub_column(ws)

  # THE STAGE RAMP CONTRACT BLOCK IS OMITTED (Nick's ruling on R_RAMP_01 A1).
  # Eleven rows x 21 columns of engine constants that NOTHING in the workbook
  # consumed - proven across formulas, defined names, data validation,
  # conditional formatting, chart series and hyperlinks, on both fixtures - and
  # all 231 cells carried the amber input styling, so a client scanning for what
  # they could change found eleven rows of solver constraints dressed as levers.
  #
  # The record is NOT lost: stage_ramp_contract stays in planning_run_json with
  # its rationale, decision_source and business_stage. This omits a RENDERING.
  #
  # Marketing % Max, which the Marketing Schedule shows as context, never came
  # from here either - it reads stage_ramp_contract.quarter_ramp_grid directly.


def build_payroll_schedule_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, PAYROLL_SHEET)
  apply_base_style(ws)
  set_title(ws, "Payroll Schedule", "OEWS-title, capacity/utilization-driven payroll source. Model Inputs links to Total Payroll.")
  write_period_headers(ws, data.periods)
  root = data.payroll_headcount
  summary_row = 6
  write_section_header(ws, summary_row, "Payroll Assumptions")
  assumptions = [
    ("Capacity Labor Model", root.get("capacity_labor_model")),
    ("Labor Intensity Class", root.get("labor_intensity_class")),
    ("Wage Positioning Tier", root.get("wage_positioning_tier")),
    ("Wage Positioning Multiplier", root.get("wage_positioning_multiplier")),
    ("Capacity Units per Supporting FTE", root.get("capacity_units_per_supporting_fte")),
    ("Target Payroll % of Revenue", root.get("target_payroll_percent_of_revenue")),
  ]
  row = summary_row + 1
  for label, value in assumptions:
    ws.cell(row=row, column=1, value=label)
    ws.cell(row=row, column=2, value=value)
    row += 1

  row += 1
  write_section_header(ws, row, "Quarter Summary")
  row += 1
  summary_rows: Dict[str, tuple[int, str, str]] = {}
  for label, key, fmt in [
    ("Total Ending FTE", "ending_fte", NUMBER_FORMAT),
    ("Total Average FTE", "average_fte", NUMBER_FORMAT),
    ("Total Payroll", "payroll", CURRENCY_FORMAT),
    ("Total Revenue", "revenue", CURRENCY_FORMAT),
    ("Total Capacity Units", "capacity_units", NUMBER_FORMAT),
    ("Revenue per Employee", "revenue_per_employee", CURRENCY_FORMAT),
    ("Units per Employee", "units_per_employee", NUMBER_FORMAT),
    ("Payroll % of Revenue", "payroll_percent_of_revenue", PERCENT_FORMAT),
  ]:
    ws.cell(row=row, column=1, value=label)
    detail = "Formula output from payroll detail"
    if key in {"revenue", "capacity_units"}:
      detail = "Linked from Revenue Drivers"
    elif key in {"revenue_per_employee", "units_per_employee", "payroll_percent_of_revenue"}:
      detail = "Python-built productivity formula"
    ws.cell(row=row, column=2, value=detail)
    ctx.add_schedule_row(PAYROLL_SHEET, label, row)
    summary_rows[label] = (row, key, fmt)
    row += 1

  row += 2
  write_section_header(ws, row, "Payroll Detail")
  row += 1
  detail_header_row = row
  headers = [
    "Quarter",
    "Staffing Class",
    "Title / Person",
    "OEWS Title",
    "Starting FTE",
    "Hires",
    "Ending FTE",
    "Average FTE",
    "Annual Wage",
    "Benefits %",
    "Wage Cost",
    "Taxes & Benefits",
    "Total Payroll",
    "Wage Source",
  ]
  for col, header in enumerate(headers, start=1):
    cell = ws.cell(row=row, column=col, value=header)
    cell.fill = design.fill(design.NAVY_DEEP)
    cell.font = design.font("colhead")
  row += 1
  detail_start_row = row
  for item in root.get("rows") or []:
    if not isinstance(item, dict):
      continue
    ws.cell(row=row, column=1, value=number(item.get("quarter_index")))
    ws.cell(row=row, column=2, value=text(item.get("staffing_class")))
    ws.cell(row=row, column=3, value=text(item.get("position_title") or item.get("person_name")))
    ws.cell(row=row, column=4, value=text(item.get("oews_occ_title") or item.get("oews_matched_title")))
    ws.cell(row=row, column=5, value=number(item.get("starting_fte")))
    ws.cell(row=row, column=6, value=number(item.get("hires")))
    ws.cell(row=row, column=7, value=f"={local_ref(row, 5)}+{local_ref(row, 6)}")
    ws.cell(row=row, column=8, value=f"=({local_ref(row, 5)}+{local_ref(row, 7)})/2")
    ws.cell(row=row, column=9, value=number(item.get("annual_wage")))
    ws.cell(row=row, column=10, value=number(item.get("payroll_taxes_benefits_percent")))
    ws.cell(row=row, column=11, value=f"={local_ref(row, 8)}*{local_ref(row, 9)}/4")
    ws.cell(row=row, column=12, value=f"={local_ref(row, 11)}*{local_ref(row, 10)}")
    ws.cell(row=row, column=13, value=f"={local_ref(row, 11)}+{local_ref(row, 12)}")
    ws.cell(row=row, column=14, value=text(item.get("wage_source") or item.get("wage_source_code")))
    for col in [5, 6, 9, 10]:
      set_input_style(ws.cell(row=row, column=col), number_format=PERCENT_FORMAT if col == 10 else CURRENCY_FORMAT if col == 9 else NUMBER_FORMAT)
    for col in [7, 8]:
      set_formula_style(ws.cell(row=row, column=col), number_format=NUMBER_FORMAT, internal_link=True)
    for col in [11, 12, 13]:
      set_formula_style(ws.cell(row=row, column=col), number_format=CURRENCY_FORMAT, internal_link=True)
    row += 1
  detail_last_row = row - 1
  ctx.add_schedule_row(PAYROLL_SHEET, "Payroll Detail First Row", detail_start_row)
  ctx.add_schedule_row(PAYROLL_SHEET, "Payroll Detail Last Row", detail_last_row)

  for label, (summary_output_row, key, fmt) in summary_rows.items():
    for q in range(PERIOD_COUNT):
      col = PERIOD_START_COL + q
      if key in {"ending_fte", "average_fte", "payroll"} and detail_last_row >= detail_start_row:
        source_col_letter = {"ending_fte": "G", "average_fte": "H", "payroll": "M"}[key]
        formula = (
          f"=SUMIFS(${source_col_letter}${detail_start_row}:${source_col_letter}${detail_last_row},"
          f"$A${detail_start_row}:$A${detail_last_row},{q})"
        )
      elif key == "revenue":
        source_row = ctx.schedule_row(REVENUE_SHEET, "Total Revenue")
        formula = f"={ref(REVENUE_SHEET, source_row, col)}" if source_row else "=0"
      elif key == "capacity_units":
        source_row = ctx.schedule_row(REVENUE_SHEET, "Total Capacity Units")
        formula = f"={ref(REVENUE_SHEET, source_row, col)}" if source_row else "=0"
      elif key == "revenue_per_employee":
        formula = f"=IFERROR({local_ref(summary_rows['Total Revenue'][0], col)}/{local_ref(summary_rows['Total Average FTE'][0], col)},0)"
      elif key == "units_per_employee":
        formula = f"=IFERROR({local_ref(summary_rows['Total Capacity Units'][0], col)}/{local_ref(summary_rows['Total Average FTE'][0], col)},0)"
      elif key == "payroll_percent_of_revenue":
        formula = f"=IFERROR({local_ref(summary_rows['Total Payroll'][0], col)}/{local_ref(summary_rows['Total Revenue'][0], col)},0)"
      else:
        formula = "=0"
      cell = ws.cell(row=summary_output_row, column=col, value=formula)
      set_formula_style(cell, number_format=fmt, internal_link=True)
    if key == "average_fte":
      _add_annual_average_formulas(ws, summary_output_row, number_format=fmt)
    elif key == "revenue_per_employee":
      _add_annual_ratio_formulas(
        ws,
        summary_output_row,
        numerator_row=summary_rows["Total Revenue"][0],
        denominator_row=summary_rows["Total Average FTE"][0],
        number_format=fmt,
      )
    elif key == "units_per_employee":
      _add_annual_ratio_formulas(
        ws,
        summary_output_row,
        numerator_row=summary_rows["Total Capacity Units"][0],
        denominator_row=summary_rows["Total Average FTE"][0],
        number_format=fmt,
      )
    elif key == "payroll_percent_of_revenue":
      _add_annual_ratio_formulas(
        ws,
        summary_output_row,
        numerator_row=summary_rows["Total Payroll"][0],
        denominator_row=summary_rows["Total Revenue"][0],
        number_format=fmt,
      )
    else:
      add_annual_formulas(ws, summary_output_row,
                          mode=ANNUAL_YEAR_END if key == "ending_fte" else None,
                          label=label, number_format=fmt)
    style_row(
      ws,
      summary_output_row,
      fill=FILL_GREEN if key in {"payroll", "revenue_per_employee", "units_per_employee"} else FILL_LIGHT,
      bold=(key in {"payroll", "revenue_per_employee", "units_per_employee"}),
      number_format=fmt,
    )

  for col in range(1, len(headers) + 1):
    ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = max(ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width or 12, 16)
  ws.auto_filter.ref = f"A{detail_header_row}:N{max(detail_header_row, detail_last_row)}"


def build_debt_schedule_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, DEBT_SHEET)
  apply_base_style(ws)
  set_title(ws, "Debt Schedule", "Debt, interest, and capital lease mechanics. Model Inputs links to calculated outputs.")
  write_period_headers(ws, data.periods)
  schedule_by_label = row_by_label(data.schedule_rows)
  expense_by_label = row_by_label(data.expense_rows)
  schedules = data.schedules
  rows = [
    # (label, detail, format, ANNUAL MODE). The mode is DECLARED, not inferred
    # from the label's words - a reworded label must never change the maths.
    ("Opening Debt", "Calculated", CURRENCY_FORMAT, ANNUAL_YEAR_START),
    ("Debt Issuance", "Source borrowing", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Requested Debt Repayment", "Source scheduled repayment", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Actual Debt Repayment", "MIN(requested repayment, opening debt + issuance)", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Closing Debt", "Calculated", CURRENCY_FORMAT, ANNUAL_YEAR_END),
    ("Interest Rate", "Source rate", PERCENT_FORMAT, ANNUAL_ANNUALIZE),
    ("Interest Expense", "Average debt balance x rate", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Total Debt Service", "Interest + actual repayment", CURRENCY_FORMAT, ANNUAL_SUM),
  ]
  row = 6
  write_section_header(ws, row, "Debt Amortization")
  row += 1
  for label, detail, fmt, annual_mode in rows:
    ws.cell(row=row, column=1, value=label)
    ws.cell(row=row, column=2, value=detail)
    ctx.add_schedule_row(DEBT_SHEET, label, row)
    row += 1
  debt_opening = ctx.schedule_row(DEBT_SHEET, "Opening Debt")
  debt_issuance = ctx.schedule_row(DEBT_SHEET, "Debt Issuance")
  requested_repay = ctx.schedule_row(DEBT_SHEET, "Requested Debt Repayment")
  actual_repay = ctx.schedule_row(DEBT_SHEET, "Actual Debt Repayment")
  closing_debt = ctx.schedule_row(DEBT_SHEET, "Closing Debt")
  interest_rate = ctx.schedule_row(DEBT_SHEET, "Interest Rate")
  interest_exp = ctx.schedule_row(DEBT_SHEET, "Interest Expense")
  debt_service = ctx.schedule_row(DEBT_SHEET, "Total Debt Service")
  issuance_values = values_21((schedule_by_label.get("Debt Issuance (New Borrowing)") or {}).get("values"))
  repay_values = values_21((schedule_by_label.get("Debt Repayment (Scheduled)") or {}).get("values"))
  rate_values = values_21((expense_by_label.get("Interest Rate") or {}).get("values"))
  for idx in range(PERIOD_COUNT):
    col = PERIOD_START_COL + idx
    if idx == 0:
      ws.cell(debt_opening, col, value=number(schedules.get("debt_opening_balance_seed")))
      ws.cell(debt_issuance, col, value=0)
      ws.cell(requested_repay, col, value=0)
    else:
      ws.cell(debt_opening, col, value=f"={local_ref(closing_debt, col - 1)}")
      ws.cell(debt_issuance, col, value=issuance_values[idx])
      ws.cell(requested_repay, col, value=repay_values[idx])
    ws.cell(actual_repay, col, value=f"=MIN({local_ref(requested_repay, col)},{local_ref(debt_opening, col)}+{local_ref(debt_issuance, col)})")
    ws.cell(closing_debt, col, value=f"=MAX(0,{local_ref(debt_opening, col)}+{local_ref(debt_issuance, col)}-{local_ref(actual_repay, col)})")
    ws.cell(interest_rate, col, value=rate_values[idx])
    ws.cell(interest_exp, col, value=f"=(({local_ref(debt_opening, col)}+{local_ref(closing_debt, col)})/2)*{local_ref(interest_rate, col)}")
    ws.cell(debt_service, col, value=f"={local_ref(interest_exp, col)}+{local_ref(actual_repay, col)}")
  for label, _, fmt, annual_mode in rows:
    r = ctx.schedule_row(DEBT_SHEET, label)
    for col in range(PERIOD_START_COL, PERIOD_END_COL + 1):
      cell = ws.cell(r, col)
      if label in {"Debt Issuance", "Requested Debt Repayment", "Interest Rate"}:
        set_input_style(cell, number_format=fmt)
      else:
        set_formula_style(cell, number_format=fmt)
    add_annual_formulas(ws, r, mode=annual_mode, number_format=fmt)
    style_row(ws, r, fill=FILL_GREEN if label in {"Closing Debt", "Interest Expense", "Actual Debt Repayment"} else None, bold=label in {"Closing Debt", "Interest Expense"}, number_format=fmt)

  row += 2
  write_section_header(ws, row, "Capital Lease Schedule")
  row += 1
  # Phase 9 P3.16 — capital lease integration. Adds ROU asset and
  # lease asset depreciation rows so the Debt Schedule sheet's
  # Capital Lease section is the canonical display for the new
  # right-of-use asset and the straight-line depreciation. Pre-iter
  # this section existed but its principal/closing rows were
  # populated from intake-leak values; this iter wires the same
  # rows to the Python-builder-produced (clipped) schedule and adds
  # the two new lines.
  lease_rows = [
    ("Lease Opening Balance", CURRENCY_FORMAT, ANNUAL_YEAR_START),
    ("Requested Lease Principal Repayments", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Lease Principal Repayments", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Lease Net Additions", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Lease Interest Expense", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Lease Closing Balance", CURRENCY_FORMAT, ANNUAL_YEAR_END),
    ("Right-of-Use Asset Opening", CURRENCY_FORMAT, ANNUAL_YEAR_START),
    ("Lease Asset Depreciation", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Right-of-Use Asset Closing", CURRENCY_FORMAT, ANNUAL_YEAR_END),
  ]
  lease_principal_values = values_21((schedule_by_label.get("Less: Principal Repayments") or {}).get("values"))
  lease_add_values = values_21((schedule_by_label.get("Plus: Net Additions") or {}).get("values"))
  # Phase 9 P3.20 Part 1 — `interest_rate_values_lease` was a
  # Python-side list of the Interest Rate row values used to
  # interpolate literals into the lease interest formula. After
  # the cell-reference fix the formula references `interest_rate`
  # directly (the row variable on this sheet), so no Python-side
  # list is needed for that path.
  for label, fmt, annual_mode in lease_rows:
    ws.cell(row=row, column=1, value=label)
    ws.cell(row=row, column=2, value="Capital leases")
    ctx.add_schedule_row(DEBT_SHEET, label, row)
    row += 1
  lease_open = ctx.schedule_row(DEBT_SHEET, "Lease Opening Balance")
  lease_requested_principal = ctx.schedule_row(DEBT_SHEET, "Requested Lease Principal Repayments")
  lease_principal = ctx.schedule_row(DEBT_SHEET, "Lease Principal Repayments")
  lease_add = ctx.schedule_row(DEBT_SHEET, "Lease Net Additions")
  lease_interest = ctx.schedule_row(DEBT_SHEET, "Lease Interest Expense")
  lease_close = ctx.schedule_row(DEBT_SHEET, "Lease Closing Balance")
  rou_open = ctx.schedule_row(DEBT_SHEET, "Right-of-Use Asset Opening")
  lease_dep = ctx.schedule_row(DEBT_SHEET, "Lease Asset Depreciation")
  rou_close = ctx.schedule_row(DEBT_SHEET, "Right-of-Use Asset Closing")
  # Phase 9 P3.20 Part 1 — lease asset depreciation now references
  # the Lease Opening Balance Q0 cell (column PERIOD_START_COL of
  # the lease_open row) instead of interpolating the Python literal
  # `lease_seed_value`. The Q0 cell is written at line 513 below
  # with `schedules.get("lease_opening_balance_seed")`; referencing
  # it keeps the formula edit-live in Excel (mirrors the
  # cell-reference pattern the debt schedule uses throughout).
  per_quarter_dep_formula = f"({local_ref(lease_open, PERIOD_START_COL)}/20)"
  for idx in range(PERIOD_COUNT):
    col = PERIOD_START_COL + idx
    ws.cell(lease_open, col, value=number(schedules.get("lease_opening_balance_seed")) if idx == 0 else f"={local_ref(lease_close, col - 1)}")
    ws.cell(lease_requested_principal, col, value=0 if idx == 0 else lease_principal_values[idx])
    ws.cell(lease_add, col, value=0 if idx == 0 else lease_add_values[idx])
    ws.cell(lease_principal, col, value=f"=MIN({local_ref(lease_requested_principal, col)},{local_ref(lease_open, col)}+{local_ref(lease_add, col)})")
    # Phase 9 P3.20 Part 1 — Lease Interest = Lease Opening *
    # Interest Rate cell (declining balance). Pre-iter this
    # interpolated `rate_cell_value` as a Python literal; now
    # references the Interest Rate row (row variable `interest_rate`
    # from line 435, written into cells at line 453) the same way
    # the debt Interest Expense formula does at line 454. Mirror
    # Flavor 1 — single cell-reference pattern across debt + lease.
    ws.cell(lease_interest, col, value=0 if idx == 0 else f"={local_ref(lease_open, col)}*{local_ref(interest_rate, col)}")
    ws.cell(lease_close, col, value=f"=MAX(0,{local_ref(lease_open, col)}+{local_ref(lease_add, col)}-{local_ref(lease_principal, col)})")
    ws.cell(rou_open, col, value=number(schedules.get("lease_opening_balance_seed")) if idx == 0 else f"={local_ref(rou_close, col - 1)}")
    ws.cell(lease_dep, col, value=0 if idx == 0 else f"=MIN({per_quarter_dep_formula},{local_ref(rou_open, col)})")
    ws.cell(rou_close, col, value=f"=MAX(0,{local_ref(rou_open, col)}-{local_ref(lease_dep, col)})")
  input_rows = {"Requested Lease Principal Repayments", "Lease Net Additions"}
  for label, fmt, annual_mode in lease_rows:
    r = ctx.schedule_row(DEBT_SHEET, label)
    for col in range(PERIOD_START_COL, PERIOD_END_COL + 1):
      set_formula_style(
        ws.cell(r, col),
        number_format=fmt,
        internal_link=label not in input_rows,
      )
    add_annual_formulas(ws, r, mode=annual_mode, number_format=fmt)
    style_row(ws, r, fill=FILL_LIGHT, number_format=fmt)


def build_capex_depreciation_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, CAPEX_SHEET)
  apply_base_style(ws)
  # CW-032 #266: the depreciation assumption is STATED where the client
  # reads the schedule - no intake question asks equipment age, so the
  # policy must be visible rather than implied.
  _life_years = number(data.schedules.get("useful_life_years")) or 5
  set_title(
    ws,
    "CapEx & Depreciation Schedule",
    "Capital expenditure and depreciation mechanics. Model Inputs links "
    "to calculated outputs. Existing equipment and new capital spending "
    f"are depreciated straight-line over {_life_years:g} years.",
  )
  write_period_headers(ws, data.periods)
  schedule_by_label = row_by_label(data.schedule_rows)
  expense_by_label = row_by_label(data.expense_rows)
  schedules = data.schedules
  row = 6
  write_section_header(ws, row, "PPE and Depreciation")
  row += 1
  labels = [
    ("Opening PPE", CURRENCY_FORMAT, ANNUAL_YEAR_START),
    ("Capital Expenditures", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Lease Additions", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Depreciation Rate", PERCENT_FORMAT, ANNUAL_AVERAGE),
    ("Depreciation Expense", CURRENCY_FORMAT, ANNUAL_SUM),
    ("Closing PPE", CURRENCY_FORMAT, ANNUAL_YEAR_END),
    ("Opening Accumulated Depreciation", CURRENCY_FORMAT, ANNUAL_YEAR_START),
    ("Accumulated Depreciation", CURRENCY_FORMAT, ANNUAL_YEAR_END),
  ]
  for label, _fmt, _mode in labels:
    ws.cell(row=row, column=1, value=label)
    ws.cell(row=row, column=2, value="Schedule source" if label in {"Capital Expenditures", "Lease Additions", "Depreciation Rate"} else "Calculated")
    ctx.add_schedule_row(CAPEX_SHEET, label, row)
    row += 1
  capex_values = values_21((schedule_by_label.get("Capital Expenditures") or {}).get("values"))
  dep_rate_values = values_21((expense_by_label.get("Depreciation") or {}).get("values"))
  opening = ctx.schedule_row(CAPEX_SHEET, "Opening PPE")
  capex = ctx.schedule_row(CAPEX_SHEET, "Capital Expenditures")
  lease_add = ctx.schedule_row(CAPEX_SHEET, "Lease Additions")
  dep_rate = ctx.schedule_row(CAPEX_SHEET, "Depreciation Rate")
  dep_exp = ctx.schedule_row(CAPEX_SHEET, "Depreciation Expense")
  closing = ctx.schedule_row(CAPEX_SHEET, "Closing PPE")
  opening_acc = ctx.schedule_row(CAPEX_SHEET, "Opening Accumulated Depreciation")
  acc = ctx.schedule_row(CAPEX_SHEET, "Accumulated Depreciation")
  for idx in range(PERIOD_COUNT):
    col = PERIOD_START_COL + idx
    ws.cell(opening, col, value=number(schedules.get("forecast_ppe_opening_balance_seed") or schedules.get("ppe_opening_balance_seed")) if idx == 0 else f"={local_ref(closing, col - 1)}")
    ws.cell(capex, col, value=0 if idx == 0 else capex_values[idx])
    ws.cell(
      lease_add,
      col,
      value=0 if idx == 0 else f"={ref(DEBT_SHEET, ctx.schedule_row(DEBT_SHEET, 'Lease Net Additions'), col)}",
    )
    ws.cell(dep_rate, col, value=dep_rate_values[idx])
    ws.cell(dep_exp, col, value=f"=MIN({local_ref(opening, col)}*{local_ref(dep_rate, col)},{local_ref(opening, col)})")
    ws.cell(closing, col, value=f"=MAX(0,{local_ref(opening, col)}+{local_ref(capex, col)}+{local_ref(lease_add, col)}-{local_ref(dep_exp, col)})")
    ws.cell(opening_acc, col, value=number(schedules.get("accumulated_depreciation_opening_seed")) if idx == 0 else f"={local_ref(acc, col - 1)}")
    ws.cell(acc, col, value=f"={local_ref(opening_acc, col)}-{local_ref(dep_exp, col)}")
  for label, fmt, annual_mode in labels:
    r = ctx.schedule_row(CAPEX_SHEET, label)
    for col in range(PERIOD_START_COL, PERIOD_END_COL + 1):
      if label in {"Capital Expenditures", "Depreciation Rate"}:
        set_input_style(ws.cell(r, col), number_format=fmt)
      elif label == "Lease Additions":
        set_formula_style(ws.cell(r, col), number_format=fmt, internal_link=True)
      else:
        set_formula_style(ws.cell(r, col), number_format=fmt)
    add_annual_formulas(ws, r, mode=annual_mode, number_format=fmt)
    style_row(ws, r, fill=FILL_GREEN if label in {"Capital Expenditures", "Depreciation Expense", "Closing PPE"} else None, bold=label in {"Depreciation Expense", "Closing PPE"}, number_format=fmt)


def build_working_capital_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, WORKING_CAPITAL_SHEET)
  apply_base_style(ws)
  set_title(ws, "Working Capital Schedule", "Working-capital drivers. Model Inputs links to these source rows.")
  write_period_headers(ws, data.periods)
  row = 6
  write_section_header(ws, row, "Working Capital Drivers")
  row += 1
  balance_by_label = row_by_label(data.balance_sheet_rows)
  labels = [
    "Accounts Receivable Days",
    "Inventory Days",
    "Accounts Payable Days",
    "Prepaid Expenses (% of Revenue)",
    "Deferred Revenue (% of Revenue)",
    "Short Term Debt (% of LTD)",
  ]
  for label in labels:
    source = balance_by_label.get(label, {"values": []})
    fmt = _fmt_for_row(source)
    write_values_row(ws, row, label, values_21(source.get("values")), detail="Working capital driver", number_format=fmt)
    ctx.add_schedule_row(WORKING_CAPITAL_SHEET, label, row)
    style_row(ws, row, number_format=fmt)
    row += 1
  row += 1
  write_section_header(ws, row, "Opening Working Capital Seeds")
  row += 1
  seed_rows = [
    ("Cash Opening Balance", "cash_opening_balance_seed"),
    ("Accounts Receivable Opening Balance", "accounts_receivable_opening_balance_seed"),
    ("Inventory Opening Balance", "inventory_opening_balance_seed"),
    ("Accounts Payable Opening Balance", "accounts_payable_opening_balance_seed"),
    ("Short Term Debt Opening Balance", "short_term_debt_opening_balance_seed"),
  ]
  for label, key in seed_rows:
    ws.cell(row=row, column=1, value=label)
    ws.cell(row=row, column=2, value="Opening balance seed")
    ws.cell(row=row, column=PERIOD_START_COL, value=number(data.schedules.get(key)))
    set_input_style(ws.cell(row=row, column=PERIOD_START_COL), number_format=CURRENCY_FORMAT)
    for col in range(FIRST_LIVE_COL, LAST_LIVE_COL + 1):
      ws.cell(row=row, column=col, value=0)
      set_formula_style(ws.cell(row=row, column=col), number_format=CURRENCY_FORMAT)
    ctx.add_schedule_row(WORKING_CAPITAL_SHEET, label, row)
    style_row(ws, row, fill=FILL_LIGHT, number_format=CURRENCY_FORMAT)
    row += 1


def build_cash_equity_sheet(wb, data: DraftWorkbookData, ctx: WorkbookBuildContext) -> None:
  ws = create_sheet(wb, CASH_EQUITY_SHEET)
  apply_base_style(ws)
  set_title(ws, "Cash & Equity Schedule", "Equity, distributions, lease/rent, and opening cash seeds. Model Inputs links to these rows.")
  write_period_headers(ws, data.periods)
  balance_by_label = row_by_label(data.balance_sheet_rows)
  expense_by_label = row_by_label(data.expense_rows)
  row = 6
  write_section_header(ws, row, "Equity and Distributions")
  row += 1
  for label in ["Owner's Capital", "Other Equity", "Distributions"]:
    source = balance_by_label.get(label, {"values": []})
    write_values_row(ws, row, label, values_21(source.get("values")), detail="Equity / distribution input", number_format=CURRENCY_FORMAT)
    ctx.add_schedule_row(CASH_EQUITY_SHEET, label, row)
    style_row(ws, row, number_format=CURRENCY_FORMAT)
    row += 1
  row += 1
  write_section_header(ws, row, "Operating Fixed Cash Items")
  row += 1
  for label in ["Lease"]:
    source = expense_by_label.get(label, {"values": []})
    write_values_row(ws, row, label, values_21(source.get("values")), detail="Operating lease/rent input", number_format=CURRENCY_FORMAT)
    ctx.add_schedule_row(CASH_EQUITY_SHEET, label, row)
    style_row(ws, row, number_format=CURRENCY_FORMAT)
    row += 1
