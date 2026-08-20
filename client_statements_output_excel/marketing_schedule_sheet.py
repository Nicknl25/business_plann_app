"""R-MKTG-03 phase 2 — the Marketing Schedule tab.

The settled marketing percent, decomposed into the lines a client reads:
customers, returning customers, new customers and cost to acquire one.

WHAT IS LIVE AND WHAT IS NOT, stated plainly because it is the whole design.
Retention and purchases-per-customer are the two EDITABLE levers; everything
below them is a formula. Editing either moves customers, returning, new and
CAC immediately. It does NOT move the marketing percentage — that is the number
the client agreed and the solver converged the rest of the plan around, so it is
LINKED from Model Inputs rather than recomputed here. The tab flexes its
decomposition without ever changing the plan's spend.

NO CYCLE: the tab reads Revenue Drivers and Model Inputs, never FINMO, and
FINMO reads Model Inputs. This sheet is a leaf.

EXACT VS ASSUMED, in the Valuation sheet's idiom. Revenue, the percentage,
spend and units are exact arithmetic on settled values. Customers and returning
inherit purchases-per-customer; new customers inherit both; **CAC inherits
everything and absorbs every residual**, which is why it carries the loudest
label — it is the number a client quotes to a lender and the softest number the
model produces.

RETENTION IS AN EXPERT ESTIMATE, NOT A CITATION (Nick's ruling). The Valuation
sheet cites Damodaran, FRED, Kroll and BizBuySell, and that is what makes those
hold up. This says "expert estimate" in words and offers no source, because
there is none to offer.

THE FOUR CLASS RULES AS A CLIENT SEES THEM:
  R1  a quarter whose customer base does not grow shows an em dash for CAC and
      a sentence saying why; a small but real count shows its CAC and is marked
      thin. Nothing is ever silently blank.
  R2  a plan with no marketing spend renders the exact lines and says so.
  R3  a pre-revenue business needs no special case — the stub's customers are
      legitimately zero, so Q1's new customers equal its customers.
  R4  a business with no usable audience gets the exact half plus an explicit
      "not modelled for this business" band, never an invented audience.
"""
from __future__ import annotations

from typing import Any, Dict

from openpyxl.utils import get_column_letter

from . import design
from .data import DraftWorkbookData, text
from .excel_utils import (
  MARKETING_SCHEDULE_SHEET,
  MODEL_INPUT_SHEET,
  PERIOD_COUNT,
  PERIOD_START_COL,
  REVENUE_SHEET,
  WorkbookBuildContext,
  apply_base_style,
  create_sheet,
  set_formula_style,
  set_input_style,
  set_title,
  style_row,
  write_period_headers,
  write_section_header,
)

#: A missing or caveated CAC gets a sentence, not an empty cell. The payload's
#: machine-readable note maps to words the client can act on.
_NOTE_TEXT = {
  "no_marketing_spend": "No marketing spend in this plan",
  "no_net_acquisition": "Customer base does not grow this quarter",
  "thin_acquisition_count": "Few new customers — read with care",
  "not_modelled": "Not modelled for this business",
}


def _ref(column_index: int, row: int) -> str:
  return f"{get_column_letter(column_index)}{row}"


def build_marketing_schedule_sheet(
  wb, data: DraftWorkbookData, ctx: WorkbookBuildContext
) -> None:
  """Render the tab.

  Absent-tolerant: with no payload the sheet is not created at all, so a draft
  built before this shipped simply has no tab rather than an empty one.
  """
  payload: Dict[str, Any] = data.marketing_schedule or {}
  if not payload or payload.get("status") != "ok":
    return
  periods = payload.get("periods") or []
  if not periods:
    return

  schedule_class = str(payload.get("schedule_class") or "")
  assumptions = payload.get("assumptions") or {}
  retention_meta = assumptions.get("retention") or {}
  repeat_meta = assumptions.get("repeat_units_per_customer") or {}
  context = payload.get("context") or {}
  noun = str(context.get("entity_noun") or "customers")
  # A mixed-basis business reads "households and firms", and naive
  # de-pluralising turns that into "households and firm". The singular is only
  # used in per-X phrasing, so a compound noun falls back to the generic word
  # rather than being mangled.
  if " and " in noun:
    singular = "customer"
  elif noun.endswith("s"):
    singular = noun[:-1]
  else:
    singular = noun

  ws = create_sheet(wb, MARKETING_SCHEDULE_SHEET)
  apply_base_style(ws)
  set_title(
    ws, "Marketing Schedule",
    f"Your marketing percentage, broken into the drivers behind it. Change "
    f"retention or purchases per {singular} and the lines below update.")
  write_period_headers(ws, data.periods)

  columns = [PERIOD_START_COL + i for i in range(min(len(periods), PERIOD_COUNT))]

  row = 6
  write_section_header(ws, row, "What you can change")
  row += 1

  def lever(label: str, key: str, value, number_format: str, note: str) -> int:
    nonlocal row
    # Column B carries the tag AND the note, which is the house convention
    # (write_values_row puts its `detail` there). Writing a note into column C
    # put it in the stub PERIOD column, where the next row's formula promptly
    # overwrote it - found by opening the exported file rather than by reading
    # the code.
    ws.cell(row=row, column=1, value=label)
    ws.cell(row=row, column=2, value=f"ASSUMPTION — {note}").font = design.font("note")
    cell = ws.cell(row=row, column=PERIOD_START_COL, value=value)
    set_input_style(cell, number_format=number_format)
    ctx.add_schedule_row(MARKETING_SCHEDULE_SHEET, key, row)
    written = row
    row += 1
    return written

  retention_row = lever(
    "Customer retention, quarter over quarter", "Retention",
    retention_meta.get("retention_rate"), design.FMT_PERCENT,
    "Expert estimate from your business model — not a sourced figure")
  repeat_row = lever(
    f"Purchases per {singular} per year", "Repeat units per customer",
    repeat_meta.get("value"), design.FMT_UNITS,
    "Implied by your own plan volume — an implied rate, not a measured one")
  row += 1

  write_section_header(ws, row, "Quarter by quarter")
  row += 1

  revenue_src = ctx.schedule_row(REVENUE_SHEET, "Total Revenue")
  percent_src = ctx.model_input_row("is::Marketing")

  # UNITS SOLD, not capacity. "Total Capacity Units" is the un-utilised
  # ceiling - flat across every quarter and, for Harrow, 2,743 against 1,755
  # actually sold. Rendering that under a label reading "Units sold" put a
  # wrong number in front of a client and made customers, new customers and
  # CAC all flat; found by opening the exported file.
  #
  # Units sold per product = that product's revenue / its unit price, and both
  # ARE per-quarter rows on Revenue Drivers. Summing them is exact, responds to
  # a client editing capacity, utilisation or price, and needs no periods-per-
  # year term because revenue already carries it.
  revenue_rows = ctx.schedule_rows.get(REVENUE_SHEET, {})
  unit_pairs = []
  for key in sorted(revenue_rows):
    if key.endswith("::Revenue"):
      stem = key[: -len("::Revenue")]
      price_row = revenue_rows.get(f"{stem}::Unit Price")
      if price_row:
        unit_pairs.append((revenue_rows[key], price_row))

  def period_row(label: str, key: str, formula_for, number_format: str,
                 exact: bool, note: str) -> int:
    nonlocal row
    ws.cell(row=row, column=1, value=label)
    tag = ws.cell(row=row, column=2,
                  value=f"{'Exact' if exact else 'Assumed'} — {note}")
    tag.font = design.font("status_good" if exact else "note")
    for index, column in enumerate(columns):
      cell = ws.cell(row=row, column=column, value=formula_for(index, column))
      set_formula_style(cell, number_format=number_format)
    ctx.add_schedule_row(MARKETING_SCHEDULE_SHEET, key, row)
    style_row(ws, row, number_format=number_format)
    written = row
    row += 1
    return written

  revenue_row = period_row(
    "Revenue", "Revenue",
    lambda i, c: (f"='{REVENUE_SHEET}'!{_ref(c, revenue_src)}" if revenue_src
                  else periods[i]["revenue"]),
    design.FMT_MONEY, True, "From your revenue drivers")

  percent_row = period_row(
    "Marketing % of revenue", "Marketing percent",
    lambda i, c: (f"='{MODEL_INPUT_SHEET}'!{_ref(c, percent_src)}" if percent_src
                  else periods[i]["marketing_percent_of_revenue"]),
    design.FMT_PERCENT, True,
    "The agreed percentage — this tab explains it, it does not change it")

  spend_row = period_row(
    "Marketing spend", "Marketing spend",
    lambda i, c: f"={_ref(c, revenue_row)}*{_ref(c, percent_row)}",
    design.FMT_MONEY, True, "Revenue x the percentage above")

  if schedule_class == "not_modelled":
    row += 1
    write_section_header(ws, row, "Acquisition — not modelled for this business")
    row += 1
    ws.cell(
      row=row, column=1,
      value=("This plan has no usable audience estimate, so the customer and "
             "acquisition-cost lines are left out rather than invented. "
             "Everything above is exact."),
    ).font = design.font("note")
    row += 2
  else:
    def units_formula(i, c):
      if not unit_pairs:
        return periods[i]["units"] or 0.0
      terms = "+".join(
        f"IFERROR('{REVENUE_SHEET}'!{_ref(c, rev)}/'{REVENUE_SHEET}'!{_ref(c, price)},0)"
        for rev, price in unit_pairs)
      return f"={terms}"

    units_row = period_row(
      "Units sold", "Units", units_formula, design.FMT_UNITS, True,
      "Each line's revenue divided by its price, added up")

    lever_col = get_column_letter(PERIOD_START_COL)
    customers_row = period_row(
      noun.capitalize(), "Customers",
      lambda i, c: (f"=IFERROR({_ref(c, units_row)}/(${lever_col}${repeat_row}/4),0)"),
      design.FMT_UNITS, False, f"Units divided by purchases per {singular}")

    retained_row = period_row(
      f"Returning {noun}", "Retained customers",
      lambda i, c: ("0" if i == 0
                    else f"={_ref(c - 1, customers_row)}*${lever_col}${retention_row}"),
      design.FMT_UNITS, False, "Last quarter's customers who come back")

    new_row = period_row(
      f"New {noun}", "New customers",
      lambda i, c: f"={_ref(c, customers_row)}-{_ref(c, retained_row)}",
      design.FMT_UNITS, False, "The customers marketing has to win")

    # CAC — the loudest label on the sheet, deliberately.
    ws.cell(row=row, column=1, value=f"Cost to acquire one {singular}").font = (
      design.font("label_strong"))
    ws.cell(
      row=row, column=2,
      value=("ASSUMED — the softest number here. It inherits retention AND "
             f"purchases per {singular}, and absorbs every rounding difference."),
    ).font = design.font("label_strong")
    for index, column in enumerate(columns):
      cell = ws.cell(
        row=row, column=column,
        value=(f'=IFERROR(IF({_ref(column, new_row)}<=0,"—",'
               f'{_ref(column, spend_row)}/{_ref(column, new_row)}),"—")'))
      set_formula_style(cell, number_format=design.FMT_MONEY)
    ctx.add_schedule_row(MARKETING_SCHEDULE_SHEET, "Customer acquisition cost", row)
    row += 1

    # Why a cost is missing or caveated — in words, per quarter.
    ws.cell(row=row, column=1, value="Why a cost above shows an em dash"
            ).font = design.font("note")
    for index, column in enumerate(columns):
      note_key = str(periods[index].get("customer_acquisition_cost_note") or "")
      cell = ws.cell(row=row, column=column, value=_NOTE_TEXT.get(note_key, ""))
      cell.font = design.font("note")
    ctx.add_schedule_row(MARKETING_SCHEDULE_SHEET, "Acquisition note", row)
    row += 2

  write_section_header(ws, row, "Where these figures come from")
  row += 1
  provenance = [
    ("Marketing percentage",
     "Set when your plan was built and held here. Changing retention or "
     "purchases per customer does not change it."),
    ("Customer retention",
     text(retention_meta.get("source")) or "Not available for this plan"),
  ]
  rationale = text(retention_meta.get("rationale"))
  if rationale:
    provenance.append(("Retention reasoning", rationale))
  provenance.append((
    f"Purchases per {singular}",
    text(repeat_meta.get("source")) or "Not available for this plan"))
  reachable = context.get("reachable_market")
  if reachable is not None:
    provenance.append((
      f"Reachable {noun}",
      f"{reachable} — the audience estimated for this business at intake"))
  for label, detail in provenance:
    ws.cell(row=row, column=1, value=label)
    ws.cell(row=row, column=2, value=detail).font = design.font("note")
    row += 1
