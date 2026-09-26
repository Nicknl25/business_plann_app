"""THE OPS GRID: the app picks the cell, the consultant speaks it.

Nick 2026-09-26, after watching a client state her price twice and lose it:

  "The app picks the cell, the model speaks it. The frame carries row and
   field, the answer lands in that cell or is refused out loud naming it,
   the grid derives from her cadence, and the section ends when the grid is
   full."

WHAT WENT WRONG WITHOUT THIS. The ops consultant chose its own subject and
phrased its own question, and nothing recorded what the question was FOR. So
when Thackery Linen and Laundry was asked for her unit and answered "a week
of service for one account - that runs about 260 a week", the app had no
question to measure the answer against: it read her PRICE as her CAPACITY,
she corrected it, the router read the correction perfectly
(`ops.unit_price=260, ops.units_per_week_capacity=85`), and the write door
refused both because a flat driver key on a three-line business has no row
to land on. Her 260 is not in that draft. She said it twice.

Every other router-driven section already tells the router what it asked:
financials has `financials_controller`, people has `people_controller`,
coherence has `coherence_controller`. Ops had `{"enabled": true}`.

THE GRID IS NOT A FORM. The app decides WHICH cell is open; the consultant
still writes every word the client reads, in her language, in context. The
model may also steer - it can ask for a different cell when the client has
just moved there - but only to a cell that is real and still empty.

WHAT IS A CELL. One product row, one field:

    ("Medical laundry for clinics", "unit_price")

plus the business-wide cells that belong to no product:

    (None, "legal_entity")

WHY THE ORDER IS WHAT IT IS. A line is worth nothing until you know what one
unit IS, so `unit_name` leads. Capacity before utilisation, because
utilisation is a share OF capacity and cannot be asked first. Price after
both, because a price is easiest to state once the unit is settled. Direct
cost last: it is the only cell whose answer is a share of the line's own
revenue, which needs the price in hand to feel real.

THE CADENCE DECIDES THE CAPACITY CELL. A weekly line is asked what it can do
in a week; a monthly or contract line is asked per period. Asking a weekly
business for an annual turns figure is the defect
`91b7d7f3` was written to stop ("a weekly or monthly business has no annual
or turns fields").
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence, Tuple

# A cell is (product_name or None, field). None means a business-wide field.
Cell = Tuple[Optional[str], str]

NOTED_KEY = "_noted_figures"

#: Cells the app has asked about and she has not answered. A cell she cannot
#: or will not answer must not hold the section open forever: after
#: MAX_ASKS_PER_CELL attempts the grid moves on and the record says which
#: cell went unanswered, so the gap is visible instead of being a loop. The
#: alternative is what the watcher calls a stuck conversation - the same
#: question three times - with no way out of the section at all.
ASKED_KEY = "_cells_asked_unanswered"
MAX_ASKS_PER_CELL = 3

UNIT_NAME = "unit_name"
UNIT_CADENCE = "unit_cadence"
UTILIZATION = "utilization_rate"
UNIT_PRICE = "unit_price"
PERIODS_PER_YEAR = "operating_periods_per_year"
LINE_COGS = "cogs_percent_of_line_revenue"     # financials' door, not a cell
UNIT_DESCRIPTION = "unit_description"

#: A row the consultant created without naming it. Not a field on any row -
#: a hole in the grid that has to be closed before the section can end.
UNNAMED_ROW = "__unnamed_row__"

CAPACITY_WEEKLY = "units_per_week_capacity"
CAPACITY_PERIOD = "units_per_period_capacity"

#: A CADENCE THE APP CANNOT PRICE WITH IS NOT A CADENCE. Each of these resolves
#: to a capacity cell; anything else - "daily", "annual", "per job", whatever
#: the model coins for a row - resolves to none, and a row with no capacity
#: cell has no volume, so the plan's revenue for that line has no basis. The
#: grid used to read such a value as an answered cadence cell and then report
#: the row complete with no capacity figure at all: the Sablecreek dead end
#: again, wearing different clothes. Now an unpriceable cadence leaves the
#: cadence cell OPEN, so she is asked whether that work is counted by the week
#: or by the month, and the capacity cell appears named correctly after.
CADENCE_TO_CAPACITY = {
  "weekly": CAPACITY_WEEKLY,
  "monthly": CAPACITY_PERIOD,
  "contract": CAPACITY_PERIOD,
  "per_period": CAPACITY_PERIOD,
  "period": CAPACITY_PERIOD,
}

#: Every capacity field, so a reader can tell "is this cell the capacity one"
#: without knowing the cadence.
CAPACITY_FIELDS = (CAPACITY_WEEKLY, CAPACITY_PERIOD)

#: The per-product cells, in the order they are asked. The capacity slot is a
#: placeholder resolved per row by `capacity_field_for`.
CAPACITY_SLOT = "__capacity__"
PRODUCT_CELL_ORDER: Sequence[str] = (
  UNIT_NAME,
  UNIT_DESCRIPTION,
  CAPACITY_SLOT,
  UTILIZATION,
  UNIT_PRICE,
)

# PER-LINE DIRECT COSTS ARE NOT AN OPS CELL. cogs_percent_of_line_revenue has
# its own door in FINANCIALS (the A-110 per-line door, with its uniform-rate
# ask and its refusal path for "work it out from my totals"). Putting it in
# this grid asked her twice and, worse, held the ops hand-off on a cell with
# no refusal path - a client who cannot split her costs per line could never
# leave the section. Neither the submit validator nor the wrap gate requires
# it here.
#
# UNIT_DESCRIPTION IS one, and it is the gap the removals opened: the submit
# validator requires it on every single-row business ("what you sell is
# required") and nothing else asks for it any more.

#: Business-wide cells, asked after the lines are complete. The list is the
#: registry's, not a second copy of it - `intake_required_fields` owns the
#: names and the words.
def _business_wide_fields() -> Sequence[str]:
  try:
    from client_intake_and_finmo.intake_required_fields import (  # type: ignore
      OPS_BUSINESS_WIDE_REQUIRED,
    )
  except Exception:
    try:
      from intake_required_fields import OPS_BUSINESS_WIDE_REQUIRED  # type: ignore
    except Exception:
      return ()
  return tuple(OPS_BUSINESS_WIDE_REQUIRED or ())


#: The cells whose value is a NUMBER, where zero means "not answered yet".
NUMERIC_CELLS = (
  CAPACITY_WEEKLY, CAPACITY_PERIOD, UTILIZATION, UNIT_PRICE, PERIODS_PER_YEAR,
)


def _has_value(value: Any, field: str = "") -> bool:
  """A cell is filled when it holds something a reader can use.

  ZERO IS NOT AN ANSWER FOR A NUMBER, and the disagreement was a dead end:
  the wrap gate has always read `<= 0` as missing, while this read 0 as
  filled. A row priced at 0 made the grid say full and the gate say not
  ready - no question to ask, no way to finish the section. The consultant's
  own schema makes unit_price and both capacities REQUIRED non-nullable
  numbers on every row, so the model must emit something the moment it
  restates her lines, and the something is usually 0. The two readers agree
  now.

  AND A CADENCE ONLY COUNTS WHEN IT RESOLVES TO A CAPACITY CELL. Empty text
  is the only empty for every other kind of cell.
  """
  if value is None:
    return False
  if field == UNIT_CADENCE:
    return str(value).strip().lower() in CADENCE_TO_CAPACITY
  if isinstance(value, str):
    return bool(value.strip())
  if isinstance(value, (list, dict)):
    return bool(value)
  if field in NUMERIC_CELLS and isinstance(value, (int, float)) and not isinstance(value, bool):
    return float(value) > 0.0
  return True


def products_of(ops_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  """Every product row, in order, across every line of business.

  HER LINES LIVE IN `lob_models[*].products`, not in the lob rows. Reading
  the wrong level reports one line on a business that has three, which looks
  exactly like the line-merge defect.
  """
  out: List[Dict[str, Any]] = []
  for lob in ((ops_json or {}).get("lob_models") or []):
    if not isinstance(lob, dict):
      continue
    for product in (lob.get("products") or []):
      if isinstance(product, dict):
        out.append(product)
  return out


def product_names(ops_json: Optional[Dict[str, Any]]) -> List[str]:
  names: List[str] = []
  for product in products_of(ops_json):
    name = str(product.get("product_name") or "").strip()
    if name and name not in names:
      names.append(name)
  return names


def find_product(ops_json: Optional[Dict[str, Any]],
                 product_name: Any,
                 *, only_open: str = "") -> Optional[Dict[str, Any]]:
  """The row by name, matched exactly then case-insensitively.

  TWO LINES CAN SHARE A NAME, and taking the first match silently wrote the
  client's answers onto the wrong one forever: with two rows both called
  "Repair job", every answer overwrote row 0's good value, row 1 stayed
  empty, the grid reported the same cell missing, and the section could
  never end. When `only_open` names the field being written, a row that
  already has that field filled is passed over, so the answer lands on the
  row the app is actually asking about.
  """
  wanted = str(product_name or "").strip()
  if not wanted:
    return None
  rows = products_of(ops_json)
  for match in (lambda a, b: a == b,
                lambda a, b: a.casefold() == b.casefold()):
    named = [p for p in rows
             if match(str(p.get("product_name") or "").strip(), wanted)]
    if not named:
      continue
    if only_open:
      for product in named:
        if not _has_value(product.get(only_open), only_open):
          return product
    return named[0]
  return None


def capacity_field_for(product: Optional[Dict[str, Any]]) -> str:
  """Which capacity cell this row has, from its own cadence.

  A weekly line is asked what it can do in a WEEK. A monthly or contract
  line is asked per PERIOD. The other field does not exist for that row and
  is never asked, never filled, and never reported missing.
  """
  cadence = str((product or {}).get(UNIT_CADENCE) or "").strip().lower()
  # Cadence not stated, or stated as something that resolves to no capacity
  # cell: the capacity cell is not askable yet, and `cells_for_product` puts
  # UNIT_CADENCE in front of it.
  return CADENCE_TO_CAPACITY.get(cadence, "")


def cells_for_product(product: Optional[Dict[str, Any]]) -> List[str]:
  """The fields this row needs, in ask order, derived from its cadence."""
  row = product if isinstance(product, dict) else {}
  out: List[str] = []
  for slot in PRODUCT_CELL_ORDER:
    if slot != CAPACITY_SLOT:
      out.append(slot)
      continue
    capacity = capacity_field_for(row)
    if capacity:
      out.append(capacity)
    else:
      # No cadence yet, so no capacity cell yet - ask the cadence first and
      # the capacity cell appears on the next pass with the right name.
      out.append(UNIT_CADENCE)
    # A CONTRACT LINE HAS ONE EXTRA CELL. How many times a year a contract
    # slot turns over is the only way its annual volume exists, which is why
    # the readiness gate has always required it for this cadence and only
    # this one. A weekly line's periods are 52 and a monthly line's are 12 -
    # derived, never asked.
    if str(row.get(UNIT_CADENCE) or "").strip().lower() == "contract":
      out.append(PERIODS_PER_YEAR)
  return out


#: THE CELLS THE HAND-OVER GATE ITSELF REQUIRES (_ops_ready_for_wrap_from_gate_obj
#: in intake_consult.py, which is the same list the submit validator enforces).
#: Exhaustion may never release one of these: the grid would report itself full
#: while the gate reported not ready, which is a section with nothing to ask and
#: no way to finish - the Sablecreek dead end. An exhausted required cell goes to
#: the BACK of the order instead, so every other cell is asked first and the
#: consultant is told it has asked this one before; the section still cannot end
#: without it, because the plan has no volume for that line without it.
#:
#: unit_description is deliberately NOT here: the gate does not require it, so a
#: client who cannot describe a line can be let past it after three tries.
GATE_REQUIRED_ROW_CELLS = frozenset((
  UNIT_NAME, UNIT_CADENCE, CAPACITY_WEEKLY, CAPACITY_PERIOD,
  UTILIZATION, UNIT_PRICE, PERIODS_PER_YEAR,
))


def cell_is_gate_required(cell: Optional[Cell]) -> bool:
  """Would the hand-over gate refuse the section with this cell empty?"""
  if not cell:
    return False
  product_name, field = cell
  if product_name or field == UNNAMED_ROW:
    return field in GATE_REQUIRED_ROW_CELLS or field == UNNAMED_ROW
  return field in _business_wide_fields()


def _exhausted(ops_json: Optional[Dict[str, Any]]) -> set:
  """Cells asked MAX_ASKS_PER_CELL times with nothing landing.

  Only cells the gate does NOT require can be released this way; see
  GATE_REQUIRED_ROW_CELLS.
  """
  out = set()
  for entry in ((ops_json or {}).get(ASKED_KEY) or []):
    if not isinstance(entry, dict):
      continue
    if int(_f(entry.get("attempts")) or 0) >= MAX_ASKS_PER_CELL:
      cell = ((str(entry.get("product_name") or "") or None),
              str(entry.get("field") or ""))
      if not cell_is_gate_required(cell):
        out.add(cell)
  return out


def note_ask(ops_json: Dict[str, Any], cell: Optional[Cell]) -> int:
  """Record that the app asked this cell again. Returns the attempt count."""
  if not isinstance(ops_json, dict) or not cell:
    return 0
  product_name, field = cell
  wanted = (str(product_name).strip() if product_name else None)
  queue = [e for e in (ops_json.get(ASKED_KEY) or []) if isinstance(e, dict)]
  for entry in queue:
    if (str(entry.get("field") or "") == str(field or "")
        and (entry.get("product_name") or None) == wanted):
      entry["attempts"] = int(_f(entry.get("attempts")) or 0) + 1
      ops_json[ASKED_KEY] = queue
      return int(entry["attempts"])
  queue.append({"product_name": wanted, "field": str(field or ""), "attempts": 1})
  ops_json[ASKED_KEY] = queue
  return 1


def _f(value: Any) -> float:
  try:
    return float(value)
  except (TypeError, ValueError):
    return 0.0


def missing_cells(ops_json: Optional[Dict[str, Any]]) -> List[Cell]:
  """Every empty cell, in ask order: each line finished before the next.

  LINE BY LINE, not field by field across lines. A client thinks about one
  part of her business at a time, and it is the only order in which a row
  frame is unambiguous for every turn of the conversation.
  """
  ops = ops_json or {}
  _spent = _exhausted(ops)
  _tired = asked_too_often(ops)
  out: List[Cell] = []
  for product in products_of(ops):
    name = str(product.get("product_name") or "").strip()
    if not name:
      # AN UNNAMED ROW IS A HOLE, NOT A FINISHED LINE. Skipping it silently
      # let the grid declare itself full while a whole revenue line sat
      # unmeasured - `product_name` is a non-nullable string in the
      # consultant's schema, so "" is what an unnamed row looks like. Its
      # name is the cell that is missing.
      out.append((None, UNNAMED_ROW))
      continue
    for field in cells_for_product(product):
      if not _has_value(product.get(field), field):
        if (name, field) not in _spent:
          out.append((name, field))
  for field in _business_wide_fields():
    if not _has_value(ops.get(field), field) and (None, field) not in _spent:
      out.append((None, field))
  if _tired:
    # Stable partition: everything not yet worn out first, in order, then the
    # cells she has already been asked three times. The order changes; the
    # membership does not, so the section still ends only when all of them fill.
    out = ([c for c in out if c not in _tired]
           + [c for c in out if c in _tired])
  return out


def asked_too_often(ops_json: Optional[Dict[str, Any]]) -> set:
  """Cells asked MAX_ASKS_PER_CELL times or more, released or not.

  The consultant is told when the cell it is handed is one of these, so it can
  come at the question a different way instead of repeating itself - which is
  what a stuck conversation looks like from the client's side.
  """
  out = set()
  for entry in ((ops_json or {}).get(ASKED_KEY) or []):
    if not isinstance(entry, dict):
      continue
    if int(_f(entry.get("attempts")) or 0) >= MAX_ASKS_PER_CELL:
      out.add(((str(entry.get("product_name") or "") or None),
               str(entry.get("field") or "")))
  return out


def next_cell(ops_json: Optional[Dict[str, Any]]) -> Optional[Cell]:
  """The one cell the app is asking about now, or None when the grid is full."""
  cells = missing_cells(ops_json)
  return cells[0] if cells else None


def grid_is_full(ops_json: Optional[Dict[str, Any]]) -> bool:
  """THE SECTION ENDS WHEN THE GRID IS FULL - not when the model says so.

  A business with no lines yet has an empty grid and is NOT complete: the
  section cannot end before the client's lines exist.
  """
  if not products_of(ops_json):
    return False
  return not missing_cells(ops_json)


def is_open_cell(ops_json: Optional[Dict[str, Any]], cell: Optional[Cell]) -> bool:
  """Is this a real cell that is still empty?

  THE REORDER ALLOWANCE (Nick 2026-09-26): "the model can follow her within
  the grid; it just can't leave the board." A consultant that wants to ask
  about a different cell - because the client has just moved there - is
  allowed to, and this is the check that keeps it on the board.
  """
  if not cell:
    return False
  product_name, field = cell
  field = str(field or "").strip()
  if not field:
    return False
  if field == UNNAMED_ROW:
    # THE ONE ROWLESS CELL THAT IS STILL ABOUT A LINE. `missing_cells` emits it
    # whenever a row has no name, and this reader said it was not a cell at
    # all - so the two readers of "is this cell open" disagreed about it. Every
    # caller that asks this question about the cell the app just asked would
    # have concluded the naming question was already answered and dropped it:
    # the staleness check would forget it on the very next turn, and the
    # reorder resolver would refuse to move to it.
    return any(not str(row.get("product_name") or "").strip()
               for row in products_of(ops_json))
  if product_name is None:
    return (field in _business_wide_fields()
            and not _has_value((ops_json or {}).get(field), field))
  product = find_product(ops_json, product_name)
  if product is None:
    return False
  return (field in cells_for_product(product)
          and not _has_value(product.get(field), field))


# ---------------------------------------------------------------------------
# THE NOTED QUEUE
#
# Nick 2026-09-14: "take the answer to the question asked, ignore the rest -
# extras NOTED and confirmed at their own turn". The queue is what makes that
# real instead of remembered: a figure she volunteers while the app is asking
# about something else is held here, and the grid hands it back when it
# reaches that cell, so she is asked to confirm her own number instead of
# being asked cold for a number she already gave.
# ---------------------------------------------------------------------------

def note_extra(ops_json: Dict[str, Any], *, product_name: Optional[str],
               field: str, value: Any, words: str = "",
               turn: Optional[int] = None) -> Dict[str, Any]:
  """Hold a figure the client volunteered for a cell the app did not ask for."""
  if not isinstance(ops_json, dict) or not str(field or "").strip():
    return ops_json
  queue = [n for n in (ops_json.get(NOTED_KEY) or []) if isinstance(n, dict)]
  entry = {
    "product_name": (str(product_name).strip() if product_name else None),
    "field": str(field).strip(),
    "value": value,
  }
  if words:
    entry["words"] = str(words)[:300]
  if turn is not None:
    entry["turn"] = int(turn)
  # ONE NOTE PER CELL, the latest. She said it twice; the second time is what
  # she means, and two notes for one cell would be offered back twice.
  queue = [
    n for n in queue
    if not (str(n.get("field") or "") == entry["field"]
            and (n.get("product_name") or None) == entry["product_name"])
  ]
  queue.append(entry)
  ops_json[NOTED_KEY] = queue
  return ops_json


def note_for(ops_json: Optional[Dict[str, Any]],
             cell: Optional[Cell]) -> Optional[Dict[str, Any]]:
  """What she already told us about this cell, if anything."""
  if not cell:
    return None
  product_name, field = cell
  wanted_product = (str(product_name).strip() if product_name else None)
  for entry in ((ops_json or {}).get(NOTED_KEY) or []):
    if not isinstance(entry, dict):
      continue
    if str(entry.get("field") or "") != str(field or ""):
      continue
    if (entry.get("product_name") or None) == wanted_product:
      return copy.deepcopy(entry)
  return None


def drop_note(ops_json: Dict[str, Any], cell: Optional[Cell]) -> Dict[str, Any]:
  """Forget a note once its cell is settled - offered and answered."""
  if not isinstance(ops_json, dict) or not cell:
    return ops_json
  product_name, field = cell
  wanted_product = (str(product_name).strip() if product_name else None)
  queue = [
    n for n in (ops_json.get(NOTED_KEY) or [])
    if isinstance(n, dict)
    and not (str(n.get("field") or "") == str(field or "")
             and (n.get("product_name") or None) == wanted_product)
  ]
  if queue:
    ops_json[NOTED_KEY] = queue
  else:
    ops_json.pop(NOTED_KEY, None)
  return ops_json
