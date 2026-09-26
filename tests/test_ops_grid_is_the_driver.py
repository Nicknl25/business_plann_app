"""THE APP PICKS THE CELL (Nick 2026-09-26).

The ops section was the only router-driven section with no controller, and
it is the only one with a ROW dimension. That combination cost Thackery Linen
and Laundry her price: she said "260 is the price per account per week", the
router read it correctly, and the write door refused it because a flat driver
key on a three-line business has no row to land on.

These pin the grid itself - which cell is open, in what order, derived from
her cadence, and the queue that hands back a figure she volunteered early.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from client_intake_and_finmo import ops_cell_grid as G  # noqa: E402


def _product(name, **kw):
  row = {"product_name": name, "unit_name": None, "unit_description": None,
         "unit_cadence": None, "units_per_week_capacity": None,
         "units_per_period_capacity": None, "utilization_rate": None,
         "unit_price": None}
  row.update(kw)
  return row


def _ops(*products, **fields):
  ops = {"lob_models": [{"lob_name": "Primary line of business",
                         "products": list(products)}]}
  ops.update(fields)
  return ops


#: Thackery, as the store actually held her at the moment the price was lost.
THACKERY = _ops(
  _product("Commercial restaurant/hotel linen service", unit_cadence="weekly",
           unit_name="week of service per account",
           unit_description="one week of linen for one account",
           units_per_week_capacity=85),
  _product("Medical laundry for clinics", unit_cadence="weekly"),
  _product("Walk-in dry cleaning and alterations", unit_cadence="weekly"),
)


class TheGridKnowsWhichCellIsOpen(unittest.TestCase):

  def test_it_asks_line_by_line_not_field_by_field(self):
    """A client thinks about one part of her business at a time, and it is
    the only order where the row frame is unambiguous every turn."""
    cells = G.missing_cells(THACKERY)
    first_line = [c for c in cells
                  if c[0] == "Commercial restaurant/hotel linen service"]
    self.assertEqual(cells[:len(first_line)], first_line,
                     "the first line's cells must all come before the next line's")

  def test_the_open_cell_is_the_one_she_was_asked_about(self):
    """Her linen line has its unit, what it is, and its capacity; how full
    she runs is next."""
    self.assertEqual(
      ("Commercial restaurant/hotel linen service", "utilization_rate"),
      G.next_cell(THACKERY))

  def test_the_order_within_a_line(self):
    product = _product("x", unit_cadence="weekly")
    self.assertEqual(
      ["unit_name", "unit_description", "units_per_week_capacity",
       "utilization_rate", "unit_price"],
      G.cells_for_product(product))

  def test_per_line_direct_costs_are_not_an_ops_cell(self):
    """They have their own door in FINANCIALS, with a uniform-rate ask and a
    refusal path. In this grid they asked her twice and, with no refusal
    path, a client who cannot split costs per line could never leave ops."""
    for cadence in ("weekly", "monthly", "contract"):
      self.assertNotIn("cogs_percent_of_line_revenue",
                       G.cells_for_product(_product("x", unit_cadence=cadence)))

  def test_what_you_sell_is_a_cell_because_submit_requires_it(self):
    """unit_description is required by the submit validator on every
    single-row business and nothing else asks for it any more."""
    self.assertIn("unit_description",
                  G.cells_for_product(_product("x", unit_cadence="weekly")))

  def test_the_cadence_decides_the_capacity_cell(self):
    """Asking a weekly business a per-period figure (or the reverse) is the
    defect 91b7d7f3 was written to stop."""
    self.assertEqual("units_per_week_capacity",
                     G.capacity_field_for(_product("x", unit_cadence="weekly")))
    for cadence in ("monthly", "contract"):
      self.assertEqual("units_per_period_capacity",
                       G.capacity_field_for(_product("x", unit_cadence=cadence)))
    # and the field that does not belong to this row is never asked for
    weekly_cells = G.cells_for_product(_product("x", unit_cadence="weekly"))
    self.assertNotIn("units_per_period_capacity", weekly_cells)
    monthly_cells = G.cells_for_product(_product("x", unit_cadence="monthly"))
    self.assertNotIn("units_per_week_capacity", monthly_cells)

  def test_with_no_cadence_the_cadence_itself_is_the_cell(self):
    product = _product("x", unit_name="a job", unit_description="one job")
    self.assertEqual("", G.capacity_field_for(product))
    self.assertIn("unit_cadence", G.cells_for_product(product))
    self.assertEqual(("x", "unit_cadence"), G.next_cell(_ops(product)))

  def test_zero_is_not_an_answer_for_a_number(self):
    """THE DEAD END: this grid read 0 as filled and the wrap gate reads <= 0
    as missing, so a row priced at 0 made the grid say full and the gate say
    not ready - no question to ask and no way to finish. The consultant's
    schema makes price and capacity REQUIRED non-nullable numbers, so the
    model must emit something when it first restates her lines, and that
    something is 0."""
    zeroed = _product("x", unit_cadence="weekly", unit_name="a job",
                      unit_description="one job", units_per_week_capacity=0,
                      utilization_rate=0, unit_price=0)
    open_cells = [c[1] for c in G.missing_cells(_ops(zeroed)) if c[0]]
    self.assertEqual(["units_per_week_capacity", "utilization_rate",
                      "unit_price"], open_cells)
    self.assertFalse(G.grid_is_full(_ops(zeroed)))
    # a real answer closes them
    answered = _product("x", unit_cadence="weekly", unit_name="a job",
                        unit_description="one job", units_per_week_capacity=10,
                        utilization_rate=0.8, unit_price=100)
    self.assertEqual([], [c for c in G.missing_cells(_ops(answered))
                          if c[0] is not None])
    everything = _ops(answered, **{f: "yes" for f in G._business_wide_fields()})
    self.assertTrue(G.grid_is_full(everything))

  def test_the_business_wide_cells_come_after_the_lines(self):
    """MINI KILLED THE FIRST VERSION: its fixture had every product cell
    already filled, so there was nothing for the business-wide cells to come
    AFTER and the claim in the name was unverifiable. This one leaves the row
    open, which is the only state where the order is observable."""
    open_row = _product("x", unit_cadence="weekly", unit_name="a job")
    cells = G.missing_cells(_ops(open_row))
    row_cells = [i for i, c in enumerate(cells) if c[0] == "x"]
    wide_cells = [i for i, c in enumerate(cells) if c[0] is None]
    self.assertTrue(row_cells, "her line still has open cells")
    self.assertTrue(wide_cells, "the business-wide cells are still open")
    self.assertLess(max(row_cells), min(wide_cells),
                    "every cell of her line comes before any business-wide one")
    self.assertIn((None, "legal_entity"), cells)
    # and with the row finished they are all that is left
    done = _product("x", unit_cadence="weekly", unit_name="a job",
                    unit_description="one job", units_per_week_capacity=10,
                    utilization_rate=0.8, unit_price=100)
    self.assertTrue(all(c[0] is None for c in G.missing_cells(_ops(done))))

  def test_the_section_is_not_done_before_her_lines_exist(self):
    """MINI KILLED THE FIRST VERSION: both its fixtures had every
    business-wide field empty too, so missing_cells was non-empty regardless
    and the guard it names could be deleted outright. The case the guard
    exists for is a business whose eight business-wide answers are all in and
    which has NO LINES - without the guard the section reports itself done
    with nothing to sell."""
    answered = {f: "yes" for f in G._business_wide_fields()}
    self.assertFalse(G.grid_is_full(dict(answered, lob_models=[])),
                     "no lines: the section is not done, whatever else is")
    self.assertFalse(G.grid_is_full(dict(answered)))
    self.assertFalse(G.grid_is_full(
      dict(answered, lob_models=[{"lob_name": "L", "products": []}])),
      "a line of business with no product rows is still no lines")
    self.assertFalse(G.grid_is_full({"lob_models": []}))
    self.assertFalse(G.grid_is_full({}))


class ACadenceOnlyCountsWhenItHasACapacityCell(unittest.TestCase):
  """A cadence the app cannot price with is not a cadence.

  The grid read any non-empty `unit_cadence` as an answered cell, and
  `capacity_field_for` returned "" for anything outside weekly/monthly/
  contract - so a row whose cadence came back as "daily" had NO capacity cell
  at all. The grid reported the row complete with no capacity figure, which
  means the line has no volume and its revenue in the delivered plan has no
  basis. That is the Sablecreek dead end in different clothes: the grid says
  full, the hand-over gate says not ready.
  """

  def _row(self, cadence):
    return _product("x", unit_cadence=cadence, unit_name="a job",
                    unit_description="one job", utilization_rate=0.8,
                    unit_price=100)

  def _full(self, cadence):
    ops = _ops(self._row(cadence), **{f: "yes" for f in G._business_wide_fields()})
    return G.grid_is_full(ops), G.next_cell(ops)

  def test_an_unpriceable_cadence_leaves_the_cadence_cell_open(self):
    for cadence in ("daily", "annual", "per job", "yearly", "", None):
      full, nxt = self._full(cadence)
      self.assertFalse(full, "%r reported the grid full with no capacity" % cadence)
      self.assertEqual(("x", "unit_cadence"), nxt, repr(cadence))

  def test_every_priceable_cadence_resolves_to_a_capacity_cell(self):
    """MINI KILLED THE ASSERTION: it compared the grid's answer against
    capacity_field_for, the function under test, so a uniform bug in it - always
    returning the weekly field - was invisible. The expected field is written
    out."""
    want = {"weekly": "units_per_week_capacity",
            "monthly": "units_per_period_capacity",
            "contract": "units_per_period_capacity"}
    for cadence, field in want.items():
      self.assertEqual(field, G.capacity_field_for(self._row(cadence)), cadence)
      full, nxt = self._full(cadence)
      self.assertFalse(full, cadence)
      self.assertEqual(field, nxt[1], cadence)

  def test_the_gate_and_the_grid_cannot_disagree_about_a_row(self):
    """The two readers of the same row: the grid (the store) and the
    hand-over gate. A state where one says done and the other says not is a
    section with nothing to ask and no way to finish."""
    import api_handlers.intake_consult as ic
    for cadence in ("weekly", "monthly", "contract", "daily", None):
      ops = _ops(self._row(cadence),
                 **{f: "yes" for f in G._business_wide_fields()})
      self.assertFalse(G.grid_is_full(ops), repr(cadence))
      self.assertFalse(ic._ops_ready_for_wrap_from_gate_obj(ops), repr(cadence))


class ACellSheWillNotAnswerNeverBECOMESADeadEnd(unittest.TestCase):
  """After three asks a cell stops holding the section open - but only a cell
  the hand-over gate does not require.

  Released indiscriminately, exhaustion produced the disagreement it was
  meant to avoid: the grid reported itself full and the gate reported not
  ready, so there was no cell to ask and no way to finish. A required cell
  sinks to the back of the order instead and the consultant is told it has
  asked before, so the QUESTION changes and the cell does not.
  """

  def _ops_with(self, **row):
    base = dict(unit_cadence="weekly", unit_name="a job",
                unit_description="one job", units_per_week_capacity=10,
                utilization_rate=0.8, unit_price=100)
    base.update(row)
    return _ops(_product("x", **base),
                **{f: "yes" for f in G._business_wide_fields()})

  def test_a_cell_the_gate_does_not_require_is_released(self):
    ops = self._ops_with(unit_description=None)
    cell = ("x", "unit_description")
    self.assertFalse(G.cell_is_gate_required(cell))
    for _ in range(G.MAX_ASKS_PER_CELL):
      G.note_ask(ops, cell)
    self.assertTrue(G.grid_is_full(ops),
                    "a client who cannot describe a line is let past it")

  def test_a_cell_the_gate_requires_is_never_released(self):
    import api_handlers.intake_consult as ic
    for field, value in (("units_per_week_capacity", None),
                         ("unit_price", None),
                         ("utilization_rate", None),
                         ("unit_name", None)):
      ops = self._ops_with(**{field: value})
      cell = ("x", field)
      self.assertTrue(G.cell_is_gate_required(cell), field)
      for _ in range(G.MAX_ASKS_PER_CELL + 2):
        G.note_ask(ops, cell)
      self.assertFalse(G.grid_is_full(ops), field)
      self.assertEqual(cell, G.next_cell(ops), field)
      self.assertFalse(ic._ops_ready_for_wrap_from_gate_obj(ops), field)

  def test_a_worn_out_cell_goes_to_the_back_not_away(self):
    """MINI KILLED THE FIRST VERSION: it wore out unit_price, which is ALREADY
    last in the ask order, so the partition could be deleted outright and the
    test stayed green. It wears out the EARLIER cell now, where sinking it is
    the only thing that can change the order."""
    ops = self._ops_with(utilization_rate=None, unit_price=None)
    util, price = ("x", "utilization_rate"), ("x", "unit_price")
    self.assertEqual([util, price], G.missing_cells(ops),
                     "utilization comes before price, or this proves nothing")
    for _ in range(G.MAX_ASKS_PER_CELL):
      G.note_ask(ops, util)
    self.assertEqual([price, util], G.missing_cells(ops),
                     "the worn-out cell sinks behind the fresh one")
    self.assertEqual(price, G.next_cell(ops), "so she is asked the fresh one")
    self.assertIn(util, G.missing_cells(ops), "and it is still needed")
    self.assertIn(util, G.asked_too_often(ops))

  def test_the_consultant_is_told_it_has_asked_before(self):
    import api_handlers.intake_consult as ic
    ops = self._ops_with(unit_price=None)
    cell = ("x", "unit_price")
    self.assertNotIn("asked_before", ic._ops_ask_this(ops, cell))
    for _ in range(G.MAX_ASKS_PER_CELL):
      G.note_ask(ops, cell)
    self.assertTrue(ic._ops_ask_this(ops, cell)["asked_before"])

  def test_an_unnamed_row_is_never_released_either(self):
    """It is a whole revenue line with no name; the section cannot end with one
    in it, and the loop is broken by changing the question, not by dropping it.

    MINI READ THIS PRECISELY: `missing_cells` never consults the released set
    for the unnamed-row cell at all - that cell is unconditional - so two of
    the three original assertions passed however `_exhausted` behaved. Both
    reasons it cannot be dropped are asserted separately now."""
    ops = _ops(_product("", unit_cadence="weekly"),
               **{f: "yes" for f in G._business_wide_fields()})
    cell = (None, G.UNNAMED_ROW)
    self.assertEqual(cell, G.next_cell(ops))
    # reason one: it is gate-required, so exhaustion could never release it
    self.assertTrue(G.cell_is_gate_required(cell))
    for _ in range(G.MAX_ASKS_PER_CELL + 3):
      G.note_ask(ops, cell)
    self.assertNotIn(cell, G._exhausted(ops),
                     "a gate-required cell is never in the released set")
    # reason two: the branch that emits it does not consult that set anyway
    self.assertFalse(G.grid_is_full(ops))
    self.assertIn(cell, G.missing_cells(ops))
    # and the consultant is told to come at it differently
    self.assertIn(cell, G.asked_too_often(ops))
    import api_handlers.intake_consult as ic
    self.assertTrue(ic._ops_ask_this(ops, cell)["asked_before"])


class TheGridAndTheGateReadARowTheSameWay(unittest.TestCase):
  """MINI BUILT THE DISAGREEMENT I ASKED IT TO ATTACK AND IT WAS REAL.

  A row with `unit_cadence="daily"` and a STALE `units_per_week_capacity` left
  over from before the cadence changed: the grid held the cadence cell open
  (daily resolves to no capacity cell) while the hand-over gate reported the row
  complete, because the gate asked only "is the cadence non-empty" and "is some
  capacity field set". It could not surface at runtime - the gate is only
  consulted inside `if grid_is_full(...)` - but a call site is a weaker
  guarantee than one reading, and the veto that used to sit there could come
  back. Both readers use CADENCE_TO_CAPACITY now.
  """

  def _stale(self, cadence):
    return _ops(_product("x", unit_cadence=cadence, unit_name="a job",
                         unit_description="one job",
                         units_per_week_capacity=10,   # stale, from before
                         utilization_rate=0.8, unit_price=100),
                **{f: "yes" for f in G._business_wide_fields()})

  def test_an_unpriceable_cadence_with_a_stale_capacity_fools_neither(self):
    import api_handlers.intake_consult as ic
    for cadence in ("daily", "annual", "per job", "yearly"):
      ops = self._stale(cadence)
      self.assertFalse(G.grid_is_full(ops), cadence)
      self.assertFalse(ic._ops_ready_for_wrap_from_gate_obj(ops),
                       "%s: the gate must not call this row complete" % cadence)

  def test_a_priceable_cadence_satisfies_both(self):
    import api_handlers.intake_consult as ic
    ops = self._stale("weekly")
    self.assertTrue(G.grid_is_full(ops))
    self.assertTrue(ic._ops_ready_for_wrap_from_gate_obj(ops))

  def test_the_two_readers_share_one_table(self):
    import inspect
    import api_handlers.intake_consult as ic
    src = inspect.getsource(ic._ops_ready_for_wrap_from_gate_obj)
    self.assertIn("CADENCE_TO_CAPACITY", src,
                  "the gate reads the grid's table, not its own idea of it")

  def test_the_grid_is_full_only_when_every_cell_is(self):
    done = _product("x", unit_cadence="weekly", unit_name="a job",
                    unit_description="one job", units_per_week_capacity=10,
                    utilization_rate=0.8, unit_price=100)
    ops = _ops(done, **{f: "yes" for f in G._business_wide_fields()})
    self.assertTrue(G.grid_is_full(ops))
    ops["lob_models"][0]["products"][0]["unit_price"] = None
    self.assertFalse(G.grid_is_full(ops))
    self.assertEqual(("x", "unit_price"), G.next_cell(ops))


class TheModelMaySteerButNotLeaveTheBoard(unittest.TestCase):

  def test_an_open_cell_is_allowed(self):
    self.assertTrue(G.is_open_cell(
      THACKERY, ("Medical laundry for clinics", "unit_price")))

  def test_a_filled_cell_is_not(self):
    self.assertFalse(G.is_open_cell(
      THACKERY, ("Commercial restaurant/hotel linen service",
                 "units_per_week_capacity")))

  def test_a_cell_that_does_not_exist_is_not(self):
    self.assertFalse(G.is_open_cell(THACKERY, ("Gift shop", "unit_price")))
    self.assertFalse(G.is_open_cell(
      THACKERY, ("Medical laundry for clinics", "units_per_period_capacity")),
      "a weekly line has no per-period capacity cell")
    self.assertFalse(G.is_open_cell(THACKERY, (None, "favourite_colour")))
    self.assertFalse(G.is_open_cell(THACKERY, None))

  def test_the_naming_cell_is_open_to_both_readers(self):
    """TWO READERS OF ONE QUESTION DISAGREED. `missing_cells` emits
    (None, "__unnamed_row__") whenever a row has no name; `is_open_cell` said
    it was not a cell at all. Every caller that asks "is the cell the app just
    asked about still open" would have concluded the naming question was
    already answered - the staleness check would forget it on the very next
    turn and the reorder resolver would refuse to move to it, so the app could
    ask her to name a line and then throw the question away."""
    nameless = _ops(_product("", unit_cadence=None))
    cell = (None, G.UNNAMED_ROW)
    self.assertEqual(cell, G.next_cell(nameless))
    self.assertIn(cell, G.missing_cells(nameless))
    self.assertTrue(G.is_open_cell(nameless, cell),
                    "the cell the grid is asking about must read as open")
    named = _ops(_product("Granite restoration", unit_cadence=None))
    self.assertFalse(G.is_open_cell(named, cell), "and closed once she names it")
    self.assertNotIn(cell, G.missing_cells(named))

  def test_the_two_readers_agree_about_every_cell(self):
    """The property, not the instance: anything missing_cells emits is open,
    and nothing it omits is."""
    for ops in (THACKERY, _ops(_product("", unit_cadence=None)),
                _ops(_product("x", unit_cadence="contract"),
                     _product("y", unit_cadence="monthly"))):
      missing = G.missing_cells(ops)
      for cell in missing:
        self.assertTrue(G.is_open_cell(ops, cell), repr(cell))
      for row in G.products_of(ops):
        name = str(row.get("product_name") or "").strip()
        if not name:
          continue
        for field in G.cells_for_product(row):
          if (name, field) not in missing:
            self.assertFalse(G.is_open_cell(ops, (name, field)),
                             "%r is not missing but reads as open" % ((name, field),))

  def test_a_business_wide_cell_is_allowed_while_empty(self):
    self.assertTrue(G.is_open_cell(THACKERY, (None, "legal_entity")))
    filled = dict(THACKERY, legal_entity="S-corp")
    self.assertFalse(G.is_open_cell(filled, (None, "legal_entity")))


class TheExtrasQueue(unittest.TestCase):
  """Her figure, held until the grid reaches its cell - Nick 2026-09-14:
  extras are NOTED and confirmed at their own turn."""

  def test_a_volunteered_figure_is_held_for_its_own_cell(self):
    ops = {"lob_models": THACKERY["lob_models"]}
    G.note_extra(ops, product_name="Commercial restaurant/hotel linen service",
                 field="unit_price", value=260,
                 words="260 is the price per account per week", turn=11)
    note = G.note_for(ops, ("Commercial restaurant/hotel linen service",
                            "unit_price"))
    self.assertEqual(260, note["value"])
    self.assertIn("260", note["words"])

  def test_the_note_belongs_to_its_row(self):
    ops = {"lob_models": THACKERY["lob_models"]}
    G.note_extra(ops, product_name="Medical laundry for clinics",
                 field="unit_price", value=310)
    self.assertIsNone(G.note_for(
      ops, ("Commercial restaurant/hotel linen service", "unit_price")))
    self.assertEqual(310, G.note_for(
      ops, ("Medical laundry for clinics", "unit_price"))["value"])

  def test_she_said_it_twice_and_the_second_is_what_she_means(self):
    ops = {}
    G.note_extra(ops, product_name="x", field="unit_price", value=260)
    G.note_extra(ops, product_name="x", field="unit_price", value=275)
    notes = ops[G.NOTED_KEY]
    self.assertEqual(1, len(notes))
    self.assertEqual(275, notes[0]["value"])

  def test_a_settled_cell_forgets_its_note(self):
    ops = {}
    G.note_extra(ops, product_name="x", field="unit_price", value=260)
    G.drop_note(ops, ("x", "unit_price"))
    self.assertIsNone(G.note_for(ops, ("x", "unit_price")))
    self.assertNotIn(G.NOTED_KEY, ops)

  def test_a_business_wide_note_has_no_row(self):
    ops = {}
    G.note_extra(ops, product_name=None, field="legal_entity", value="S-corp")
    self.assertEqual("S-corp", G.note_for(ops, (None, "legal_entity"))["value"])


class TheGridReadsHerLinesWhereTheyLive(unittest.TestCase):

  def test_products_live_inside_the_lob(self):
    """Reading lob rows instead of products reports one line on a business
    with three, which is indistinguishable from the merge defect."""
    self.assertEqual(3, len(G.products_of(THACKERY)))
    self.assertEqual(
      ["Commercial restaurant/hotel linen service",
       "Medical laundry for clinics",
       "Walk-in dry cleaning and alterations"],
      G.product_names(THACKERY))

  def test_a_row_is_found_by_name_however_it_is_cased(self):
    self.assertIsNotNone(G.find_product(THACKERY, "Medical laundry for clinics"))
    self.assertIsNotNone(G.find_product(THACKERY, "medical laundry FOR clinics"))
    self.assertIsNone(G.find_product(THACKERY, "Gift shop"))
    self.assertIsNone(G.find_product(THACKERY, ""))


if __name__ == "__main__":
  unittest.main()
