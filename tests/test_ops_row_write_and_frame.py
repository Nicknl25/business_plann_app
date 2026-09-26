"""THE ROW-ADDRESSED WRITE, AND THE FRAME THAT MAKES IT POSSIBLE.

Thackery Linen and Laundry, 2026-09-26, live Cowork run, draft 32a9a43f:

    her:  "No - 260 is the price per account per week, not the number.
           We have 62 accounts and could handle about 85."
    router: patch={'ops.unit_price': 260, 'ops.units_per_week_capacity': 85}
    door:   OPS_DRIVER_WRITE_UNROUTED field=unit_price value=260
            (multi-line model, no row resolution at this door)
    store:  unit_price = None

The router read her perfectly. The write door refused it, correctly, because
a flat driver key on a three-line business cannot say WHICH line - and then
nothing asked her which. These pin the door that can land it and the frame
that tells the router how to address it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from api_handlers import intake_consult as IC  # noqa: E402
from client_intake_and_finmo import intent_router as ROUTER  # noqa: E402
from client_intake_and_finmo import ops_cell_grid as G  # noqa: E402


def _thackery():
  return {"lob_models": [{"lob_name": "Primary line of business", "products": [
    {"product_name": "Commercial restaurant/hotel linen service",
     "unit_cadence": "weekly", "unit_name": "week of service per account",
     "unit_description": "one week of linen for one account",
     "units_per_week_capacity": 85, "utilization_rate": None,
     "unit_price": None},
    {"product_name": "Medical laundry for clinics", "unit_cadence": "weekly",
     "unit_name": None, "unit_description": None,
     "units_per_week_capacity": None, "utilization_rate": None,
     "unit_price": None},
    {"product_name": "Walk-in dry cleaning and alterations",
     "unit_cadence": "weekly", "unit_name": None, "unit_description": None,
     "units_per_week_capacity": None, "utilization_rate": None,
     "unit_price": None},
  ]}]}


def json_round_trip(obj):
  import json as _json
  return _json.loads(_json.dumps(obj))


def _apply(patch, ops):
  _b, next_ops, _m, _p, _f, _ff = IC._apply_scoped_patch(
    patch, business_facts={}, ops_json=ops, market_json={}, people_json={},
    financials_json={}, fulfillment_json={})
  return next_ops


class HerPriceLands(unittest.TestCase):

  def test_the_figure_she_lost_now_lands_on_the_line_she_meant(self):
    ops = _apply({"ops.product_overrides": {
      "Commercial restaurant/hotel linen service": {"unit_price": 260}}},
      _thackery())
    row = G.find_product(ops, "Commercial restaurant/hotel linen service")
    self.assertEqual(260, row["unit_price"])
    # and only that line
    self.assertIsNone(G.find_product(ops, "Medical laundry for clinics")["unit_price"])

  def test_two_lines_in_one_answer_both_land(self):
    ops = _apply({"ops.product_overrides": {
      "Commercial restaurant/hotel linen service": {"unit_price": 260},
      "Medical laundry for clinics": {"unit_price": 310}}}, _thackery())
    self.assertEqual(260, G.find_product(
      ops, "Commercial restaurant/hotel linen service")["unit_price"])
    self.assertEqual(310, G.find_product(
      ops, "Medical laundry for clinics")["unit_price"])

  def test_the_line_she_names_wins_over_the_line_asked(self):
    """HER WORDS OUTRANK THE FRAME: the identity rides in the value, so an
    answer about another line lands on that line, not on the one asked."""
    ops = _apply({"ops.product_overrides": {
      "Medical laundry for clinics": {"unit_price": 310}}}, _thackery())
    self.assertEqual(310, G.find_product(
      ops, "Medical laundry for clinics")["unit_price"])
    self.assertIsNone(G.find_product(
      ops, "Commercial restaurant/hotel linen service")["unit_price"])

  def test_a_line_that_does_not_exist_is_reported_not_swallowed(self):
    ops = _apply({"ops.product_overrides": {"Gift shop": {"unit_price": 12}}},
                 _thackery())
    self.assertIn("Gift shop", ops["_product_override_receipt"]["unmatched"])
    self.assertEqual([], ops["_product_override_receipt"]["landed"])

  def test_a_cell_that_row_does_not_have_is_reported_not_written(self):
    """A weekly line has no per-period capacity cell."""
    ops = _apply({"ops.product_overrides": {
      "Medical laundry for clinics": {"units_per_period_capacity": 40}}},
      _thackery())
    row = G.find_product(ops, "Medical laundry for clinics")
    self.assertIsNone(row.get("units_per_period_capacity"))
    self.assertIn("Medical laundry for clinics.units_per_period_capacity",
                  ops["_product_override_receipt"]["unmatched"])

  def test_the_flat_key_is_still_refused_on_a_multi_line_business(self):
    """The A-113 drop stays: it is correct, and it is what the row-addressed
    door exists to replace - not something to quietly re-enable.

    MINI KILLED THE FIRST VERSION: it asserted only that no row ended up with
    the price, and `_derive_ops_cells` strips flat driver keys anyway, so the
    A-113 guard could be deleted outright and this stayed green. It pins the
    REFUSAL now - no row touched, nothing claimed as landed, and the SAME
    figure landing when it is addressed to a row - which is the only set of
    facts that guard alone decides."""
    flat = _apply({"ops.unit_price": 260}, _thackery())
    self.assertEqual([None, None, None],
                     [r.get("unit_price") for r in G.products_of(flat)])
    self.assertIsNone(flat.get("unit_price"))
    self.assertNotIn("_product_override_receipt", flat,
                     "it landed nowhere, so there is nothing to claim landed")
    addressed = _apply(
      {"ops.product_overrides":
       {"Commercial restaurant/hotel linen service": {"unit_price": 260}}},
      _thackery())
    self.assertEqual([260, None, None],
                     [r.get("unit_price") for r in G.products_of(addressed)])


class TheFrameTellsTheRouterWhatWasAsked(unittest.TestCase):

  def test_it_carries_the_row_and_the_field(self):
    frame = IC._build_ops_controller_context(_thackery())
    self.assertEqual("Commercial restaurant/hotel linen service",
                     frame["product_name"])
    self.assertEqual("utilization_rate", frame["field"])
    self.assertEqual(["ops.product_overrides"], frame["patch_targets"])

  def test_a_business_wide_cell_declares_its_own_field_not_the_row_door(self):
    """THE LAST EIGHT CELLS WERE UNWRITABLE: declaring ops.product_overrides
    for a cell with no row sent the value to a door that looks for a line,
    found none, and dropped it - so ops could never end."""
    ops = _thackery()
    for row in G.products_of(ops):
      row.update({"unit_name": "x", "unit_description": "one x",
                  "units_per_week_capacity": 10, "utilization_rate": 0.8,
                  "unit_price": 100})
    frame = IC._build_ops_controller_context(ops)
    self.assertEqual("", frame["product_name"])
    self.assertEqual(["ops.%s" % frame["field"]], frame["patch_targets"])
    self.assertNotIn("ops.product_overrides", frame["patch_targets"])

  def test_it_speaks_in_her_words_never_a_field_name(self):
    frame = IC._build_ops_controller_context(_thackery())
    self.assertEqual("how full you usually run", frame["asked_in_words"])
    self.assertNotIn("_", frame["asked_in_words"])

  def test_it_lists_her_lines_so_the_router_can_name_one(self):
    frame = IC._build_ops_controller_context(_thackery())
    self.assertEqual(3, len(frame["rows"]))
    self.assertIn("Medical laundry for clinics", frame["rows"])

  def test_a_figure_she_already_gave_rides_on_the_frame(self):
    ops = _thackery()
    G.note_extra(ops, product_name="Commercial restaurant/hotel linen service",
                 field="utilization_rate", value=0.73,
                 words="we have 62 accounts and could handle about 85")
    frame = IC._build_ops_controller_context(ops)
    self.assertEqual(0.73, frame["already_said"]["value"])
    self.assertIn("62", frame["already_said"]["her_words"])

  def test_there_is_no_frame_once_the_grid_is_full(self):
    ops = _thackery()
    for row in G.products_of(ops):
      row.update({"unit_name": "x", "unit_description": "one x",
                  "units_per_week_capacity": 10, "utilization_rate": 0.8,
                  "unit_price": 100})
    for field in G._business_wide_fields():
      ops[field] = "stated"
    self.assertTrue(G.grid_is_full(ops))
    self.assertIsNone(IC._build_ops_controller_context(ops))


class EveryCellTheAppAsksAboutCanBeRecorded(unittest.TestCase):
  """A STAGE THAT ASKS A QUESTION IT CANNOT RECORD MISLABELS IT.

  The lesson survives from the three test modules the 25 September revert
  orphaned (they imported ASKABLE_OPS_FIELDS, _app_asked_field,
  CONCURRENT_ONLY_FIELDS and question_field - none of which exist, so all
  three have been failing on import since, and none were in preflight).
  Perrin Row is what it cost: the stage asked "how many do you complete in a
  year", had no field it could declare, declared operating_periods_per_year,
  and 930 landed in the slot that means TURNS - the row then claimed
  8 x 930 = 7,440 jobs a year against her 930.

  Under the grid the rule is structural: the app only ever asks about a cell
  of a row, and the row door writes exactly the cells that row has.
  """

  def test_every_cell_of_every_cadence_lands_through_the_row_door(self):
    for cadence in ("weekly", "monthly", "contract"):
      ops = {"lob_models": [{"lob_name": "L", "products": [
        {"product_name": "A line", "unit_cadence": cadence}]}]}
      for field in G.cells_for_product(G.products_of(ops)[0]):
        if field == "unit_cadence":
          continue                      # already stated, or it is the cell
        value = "a job" if field == "unit_name" else 7
        after = _apply({"ops.product_overrides": {"A line": {field: value}}},
                       json_round_trip(ops))
        row = G.find_product(after, "A line")
        self.assertEqual(value, row.get(field),
                         "%s cadence: the app can ask for %s and could not "
                         "record it" % (cadence, field))

  def test_every_cell_has_words_for_the_client(self):
    """A cell with no words cannot be asked about at all - the model would
    say the key. The frame refuses to carry one."""
    for cadence in ("weekly", "monthly", "contract"):
      for field in G.cells_for_product({"unit_cadence": cadence}):
        self.assertTrue(IC._ops_cell_words(field),
                        "%s has no words for the client" % field)
    for field in G._business_wide_fields():
      self.assertTrue(IC._ops_cell_words(field),
                      "%s has no words for the client" % field)


class ARefusedWriteSpeaksAndTheModelSaysIt(unittest.TestCase):
  """ONE MOUTH'S CHANNEL, FINALLY CONNECTED.

  aa06fde4 deleted the machine's parentheticals and added the vocabulary for
  the model to carry them instead - new_turn_material, add_material,
  context_with_material, and the MATERIAL_INSTRUCTION telling the consultant
  how to say each entry. Nothing ever called any of it: zero callers for the
  producer, zero for the consumer, and "WHAT THE APP DID THIS TURN" appeared
  in no prompt. So the app lost its old way of saying "I couldn't apply that"
  and never gained the new one, and Thackery heard a bare "I wasn't able to
  apply that change yet" that named neither the figure nor her three lines.
  """

  def test_the_channel_has_a_producer_and_a_consumer_now(self):
    """MINI KILLED THE FIRST VERSION OF THIS TEST. It scanned the handler's
    own source for the wiring, and a version with the whole block commented
    out passed it - the exact wiring this class exists to prove. The assembly
    is a function now, and this drives it."""
    from client_intake_and_finmo import turn_material as TM
    ops = _apply({"ops.product_overrides":
                  {"Commercial restaurant/hotel linen service":
                   {"unit_price": 260}}}, _thackery())
    material = IC._ops_material_from_receipt(ops)
    self.assertEqual([("landed", "what you charge", 260)],
                     [(m["kind"], m["about"], m["value"]) for m in material])
    self.assertIn("Commercial restaurant/hotel linen service",
                  material[0]["detail"])
    ctx = TM.context_with_material({"draft_id": "x"}, material)
    self.assertIn(TM.MATERIAL_KEY, ctx)
    self.assertIn("WHAT THE APP DID THIS TURN", ctx[TM.INSTRUCTION_KEY])
    self.assertNotIn("_product_override_receipt", ops,
                     "the receipt is spent, so a later turn cannot say it twice")
    self.assertEqual([], IC._ops_material_from_receipt(ops))

  def test_the_instruction_travels_with_the_material(self):
    from client_intake_and_finmo import turn_material as TM
    ctx = TM.context_with_material({"a": 1}, [{"kind": "not_landed",
                                              "about": "what you charge"}])
    self.assertEqual(1, ctx["a"])
    self.assertIn(TM.MATERIAL_KEY, ctx)
    self.assertIn("WHAT THE APP DID THIS TURN", ctx[TM.INSTRUCTION_KEY])

  def test_nothing_is_carried_when_nothing_happened(self):
    from client_intake_and_finmo import turn_material as TM
    ctx = TM.context_with_material({"a": 1}, [])
    self.assertNotIn(TM.MATERIAL_KEY, ctx)
    self.assertNotIn(TM.INSTRUCTION_KEY, ctx)

  def test_the_consultant_is_told_how_to_carry_it(self):
    from client_intake_and_finmo import intake_consultant as OC
    import inspect
    src = inspect.getsource(OC.consultant_chat_turn)
    self.assertIn("turn_material", src)
    self.assertIn("how_to_say_what_the_app_did", src)

  def test_an_unplaceable_figure_becomes_material_naming_her_lines(self):
    """The refusal the client actually needed: which of the three is it?

    Driven through the real producer, not re-implemented here - a test that
    rebuilds the material itself proves only that the test can."""
    ops = _apply({"ops.product_overrides": {"Gift shop": {"unit_price": 12}}},
                 _thackery())
    material = IC._ops_material_from_receipt(ops)
    self.assertEqual(1, len(material))
    self.assertEqual("not_landed", material[0]["kind"])
    for line in G.product_names(_thackery()):
      self.assertIn(line, material[0]["detail"])

  def test_a_wrong_section_is_not_reported_as_a_wrong_line(self):
    """A wrong LINE and a wrong SECTION are different refusals. A per-line
    cost percentage belongs to the row but is financials door, not an ops
    cell; telling her the LINE is wrong sends her back to re-answer something
    she got right."""
    ops = _apply({"ops.product_overrides":
                  {"Medical laundry for clinics":
                   {"cogs_percent_of_line_revenue": 0.4}}}, _thackery())
    material = IC._ops_material_from_receipt(ops)
    self.assertEqual(1, len(material))
    detail = material[0]["detail"]
    self.assertIn("Medical laundry for clinics", detail)
    self.assertNotIn("does not belong", detail)
    self.assertIn("not something I record", detail)


class TheBlockersMiniFound(unittest.TestCase):
  """Six blockers from the adversarial audit, and the one that killed a live
  run. Each is pinned where it broke."""

  def test_the_asked_cell_is_never_stamped_on_a_message(self):
    """IT COST A LIVE RUN. Stored messages are replayed into the consultant
    call verbatim - conversation_messages=[*messages, user_msg], no key
    filtering - so an assistant message carrying an extra key is rejected by
    the model API on every later turn of that draft:

        OpenAI API error 400: Unknown parameter: 'input[4].asked_cell'

    and the draft is poisoned permanently. The cell lives on the section."""
    import inspect
    src = inspect.getsource(IC)
    self.assertTrue(IC.OPS_ASKED_CELL_KEY.startswith("_"),
                    "an ops_json key, not a message key")
    self.assertNotIn("_ops_reply_msg[OPS_ASKED_CELL_KEY]", src)
    self.assertNotIn('dict(_am, asked_field=', src)
    ops = {"lob_models": []}
    IC._ops_remember_asked_cell(ops, ("A line", "unit_price"))
    self.assertEqual(("A line", "unit_price"), IC._ops_asked_cell(ops))

  def test_the_frame_reads_the_section_not_the_transcript(self):
    """MINI KILLED THE FIRST VERSION: it scanned for the call, and a comment
    carrying the same text satisfied it while the behaviour was disabled.

    The behaviour is that the frame describes the QUESTION she is answering -
    read back from the section, not wherever the grid has moved to since -
    and that it survives every branch which persists ops_json, because the
    cell lives on ops_json and never on a message."""
    ops = _thackery()
    asked = ("Walk-in dry cleaning and alterations", "unit_price")
    self.assertNotEqual(asked, G.next_cell(ops),
                        "the grid must have moved on, or this proves nothing")
    IC._ops_remember_asked_cell(ops, asked)
    ops = json_round_trip(ops)              # as the store round-trips it
    frame = IC._build_ops_controller_context(
      ops, asked_cell=IC._ops_asked_cell(ops))
    self.assertEqual("Walk-in dry cleaning and alterations",
                     frame["product_name"])
    self.assertEqual("unit_price", frame["field"])
    self.assertEqual(["ops.product_overrides"], frame["patch_targets"])

  def test_two_lines_with_one_name_do_not_overwrite_each_other(self):
    """Taking the first match wrote every answer onto row 0 forever: row 1
    stayed empty, the grid reported the same cell missing, and ops could
    never hand off."""
    ops = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "Repair job", "unit_cadence": "weekly",
       "unit_name": "a job", "unit_description": "one repair",
       "units_per_week_capacity": 10},
      {"product_name": "Repair job", "unit_cadence": "weekly",
       "unit_name": None, "unit_description": None,
       "units_per_week_capacity": None},
    ]}]}
    after = _apply({"ops.product_overrides": {
      "Repair job": {"units_per_week_capacity": 40}}}, json_round_trip(ops))
    rows = G.products_of(after)
    self.assertEqual(10, rows[0]["units_per_week_capacity"],
                     "her first line's good value must not be overwritten")
    self.assertEqual(40, rows[1]["units_per_week_capacity"])

  def test_the_door_does_not_write_through_to_the_callers_object(self):
    """next_ops was a SHALLOW copy, so the row dicts were the caller's: the
    write escaped even on paths that discard the return value, while the
    receipt did not travel with it."""
    ops = _thackery()
    before = json_round_trip(ops)
    _apply({"ops.product_overrides": {
      "Medical laundry for clinics": {"unit_price": 310}}}, ops)
    self.assertEqual(before, ops, "the caller's ops_json must be untouched")

  def test_a_cell_asked_three_times_stops_holding_the_section(self):
    """No cell may be asked forever. A client who cannot answer one would
    otherwise meet the same question until the section died."""
    ops = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "A", "unit_cadence": "weekly", "unit_name": "x",
       "unit_description": "y", "units_per_week_capacity": 5,
       "utilization_rate": 0.5}]}]}
    self.assertEqual(("A", "unit_price"), G.next_cell(ops))
    for _ in range(G.MAX_ASKS_PER_CELL):
      G.note_ask(ops, ("A", "unit_price"))
    self.assertNotEqual(("A", "unit_price"), G.next_cell(ops))

  def test_a_volunteered_figure_with_no_cell_is_still_asked_about(self):
    """STRICTLY WORSE THAN THE GUESS IT REPLACED: filtering candidates to her
    cells left "we have 62 accounts" with an empty candidate list, and the
    handler then held nothing and asked nothing.

    Driven through the real fallback - what the app calls when a figure has
    no cell to be noted against - instead of scanning for the call."""
    ask = IC._unresolved_figures_ask(
      [{"value": 62, "client_words": "we have 62 accounts",
        "candidate_fields": []}])
    self.assertTrue(str(ask or "").strip(),
                    "a figure with no cell must still produce a question")
    self.assertIn("62", str(ask))
    self.assertIn("?", str(ask))
    self.assertFalse(IC._unresolved_figures_ask([]))

  def test_the_model_is_never_handed_a_field_key(self):
    """ask_this is serialised whole into the prompt."""
    ask = IC._ops_ask_this(_thackery(),
                           ("Medical laundry for clinics", "unit_price"))
    self.assertEqual({"in_words", "line"}, set(ask))
    self.assertNotIn("field", ask)
    self.assertEqual("what you charge", ask["in_words"])


class TheReorderAllowanceCanActuallyBeGranted(unittest.TestCase):
  """Nick 2026-09-26: "Keep the reorder allowance. The model can follow her
  within the grid; it just can't leave the board."

  The model is never handed a field key and is told to write in its own
  words, so a reorder request arrives in ENGLISH. Resolving it by exact
  string equality against the curated phrase made the allowance decorative -
  it could only be granted when the model copied the phrase character for
  character. It resolves on normalised words now, and only when exactly one
  cell matches.
  """

  def _ops(self):
    return {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "Tile", "unit_cadence": "weekly",
       "unit_name": "a crew week", "unit_description": "one crew week",
       "units_per_week_capacity": None, "utilization_rate": None,
       "unit_price": None}]}]}

  def test_with_no_request_the_grid_picks(self):
    self.assertEqual(("Tile", "units_per_week_capacity"),
                     IC._ops_cell_to_ask(self._ops()))

  def test_the_apps_own_words_come_back_as_the_cell(self):
    words = IC._ops_cell_words("unit_price")
    self.assertTrue(words)
    self.assertEqual(("Tile", "unit_price"), IC._ops_cell_to_ask(
      self._ops(), requested={"line": "Tile", "field": words}))

  def test_a_paraphrase_of_those_words_still_resolves(self):
    """Casing, trailing punctuation and stray whitespace are what a model
    that is writing prose actually returns."""
    words = IC._ops_cell_words("unit_price")
    for shape in ("  %s?" % words.upper(), "%s." % words.capitalize(),
                  words.replace(" ", "  ")):
      self.assertEqual(("Tile", "unit_price"), IC._ops_cell_to_ask(
        self._ops(), requested={"line": "Tile", "field": shape}), shape)

  def test_a_field_key_is_honoured_too(self):
    self.assertEqual(("Tile", "unit_price"), IC._ops_cell_to_ask(
      self._ops(), requested={"line": "Tile", "field": "unit_price"}))

  def test_a_cell_off_the_board_is_refused_and_the_grid_asks_instead(self):
    for junk in ("her favourite colour", "", "   ", "the weather"):
      self.assertEqual(("Tile", "units_per_week_capacity"),
                       IC._ops_cell_to_ask(self._ops(),
                                           requested={"line": "Tile",
                                                      "field": junk}), junk)

  def test_a_cell_that_is_already_filled_is_refused(self):
    ops = self._ops()
    ops["lob_models"][0]["products"][0]["unit_price"] = 4200
    self.assertEqual(("Tile", "units_per_week_capacity"), IC._ops_cell_to_ask(
      ops, requested={"line": "Tile", "field": IC._ops_cell_words("unit_price")}))

  def test_a_line_that_does_not_exist_is_refused(self):
    self.assertEqual(("Tile", "units_per_week_capacity"), IC._ops_cell_to_ask(
      self._ops(), requested={"line": "Granite",
                              "field": IC._ops_cell_words("unit_price")}))

  def test_a_business_wide_cell_can_be_moved_to(self):
    ops = self._ops()
    self.assertEqual((None, "legal_entity"), IC._ops_cell_to_ask(
      ops, requested={"line": None,
                      "field": IC._ops_cell_words("legal_entity")}))

  def test_the_model_is_told_to_use_the_apps_own_words(self):
    """The instruction used to say "return ask_instead with the line and the
    field" to a model that is never given a field - so it invented one and
    the request never resolved."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "python",
                            "client_intake_and_finmo", "intake_consultant.py"),
               encoding="utf-8").read()
    self.assertIn("USING THE APP'S OWN WORDS FOR IT", src)
    self.assertIn("never write a field key", src)



class TheRouterIsGivenTheFrameLikeEveryOtherSection(unittest.TestCase):

  def test_the_write_target_is_admitted_only_when_the_frame_is_live(self):
    """MINI KILLED THE FIRST VERSION: it scanned route_intent's source for two
    substrings, and a comment carrying both of them satisfied it while the
    admission block was disabled - i.e. the whole feature could be deleted and
    this stayed green.

    The chain is pinned in two real pieces instead. (a) The static ops
    allowlist does not contain product_overrides - checked by parsing the
    literal, not by reading the file as text - so the ONLY way it is ever
    allowed is the conditional branch that reads the frame's patch_targets.
    (b) The allowlist genuinely gates the model: the structured schema handed
    to it is built from that list, and a field absent from the list is absent
    from the schema, so the model cannot emit it and the enforcement at
    "Intent router returned disallowed patch field" raises if it somehow did.

    What this still does NOT cover is route_intent's own assembly of the list,
    which needs the model call; that is the live-router leg's job."""
    import ast
    src = open(ROUTER.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    static_ops = None
    for node in ast.walk(tree):
      if not isinstance(node, ast.Dict):
        continue
      for key, val in zip(node.keys, node.values):
        if (isinstance(key, ast.Constant) and key.value == "ops"
            and isinstance(val, ast.List) and len(val.elts) >= 10):
          static_ops = [e.value for e in val.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    self.assertIsNotNone(static_ops, "the static ops allowlist must be findable")
    self.assertIn("unit_price", static_ops, "sanity: this is the right list")
    self.assertNotIn("product_overrides", static_ops)
    self.assertNotIn("ops.product_overrides", static_ops)

    # (b) the list is what constrains the model
    import json
    with_it = json.dumps(ROUTER._final_schema(
      allowed_patch_fields=["unit_price", "ops.product_overrides"],
      consult_type="ops"))
    without = json.dumps(ROUTER._final_schema(
      allowed_patch_fields=["unit_price"], consult_type="ops"))
    self.assertIn("product_overrides", with_it)
    self.assertNotIn("product_overrides", without)

  def test_the_frame_is_what_names_the_target(self):
    """And the target it names follows the CELL: a row cell is written through
    the row door, a business-wide cell as its own flat field, and the naming
    of a row - the one rowless cell that is still about a line - through the
    row door keyed by the empty name."""
    row_frame = IC._build_ops_controller_context(_thackery())
    self.assertEqual(["ops.product_overrides"], row_frame["patch_targets"])
    wide = dict(_thackery())
    for line in G.products_of(wide):
      line.update({"unit_name": "u", "unit_description": "d",
                   "units_per_week_capacity": 5, "utilization_rate": 0.8,
                   "unit_price": 10})
    wide_frame = IC._build_ops_controller_context(wide)
    self.assertEqual(["ops.%s" % wide_frame["field"]],
                     wide_frame["patch_targets"])
    self.assertEqual("", wide_frame["product_name"])
    nameless = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "", "unit_cadence": None}]}]}
    name_frame = IC._build_ops_controller_context(nameless)
    self.assertEqual(G.UNNAMED_ROW, name_frame["field"])
    self.assertEqual(["ops.product_overrides"], name_frame["patch_targets"])

  def test_naming_a_line_lands_on_the_row_and_the_grid_moves_on(self):
    """IT USED TO LAND NOWHERE. The frame named ops.__unnamed_row__ - a key
    with no handler and no reader - and called it a fact about the business as
    a whole, so her answer went onto a throwaway top-level field and the same
    question came back every turn, forever."""
    ops = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "Tile", "unit_cadence": "weekly", "unit_name": "a week",
       "unit_description": "one crew week", "units_per_week_capacity": 6,
       "utilization_rate": 0.8, "unit_price": 4200},
      {"product_name": "", "unit_cadence": None}]}]}
    self.assertEqual((None, G.UNNAMED_ROW), G.next_cell(ops))
    after = _apply({"ops.product_overrides":
                    {"": {"product_name": "Stone restoration"}}}, ops)
    self.assertEqual(["Tile", "Stone restoration"], G.product_names(after))
    self.assertNotIn(G.UNNAMED_ROW, after,
                     "no throwaway top-level key is written")
    self.assertEqual(("Stone restoration", "unit_name"),
                     G.next_cell(after),
                     "and the grid has moved into that row, at its first cell")
    self.assertEqual([{"product_name": "Stone restoration",
                       "field": "product_name",
                       "value": "Stone restoration"}],
                     after["_product_override_receipt"]["landed"])

  def test_a_flat_value_for_a_row_is_placed_or_spoken_never_dropped(self):
    """The nested shape is prompted, not enforced - the router's schema for
    product_overrides is an open object - so {"line": 260} is a shape the model
    can emit. It used to vanish: no receipt, no log, nothing for the consultant
    to say. That is the Thackery failure through a shape deviation."""
    ops = _thackery()
    IC._ops_remember_asked_cell(
      ops, ("Medical laundry for clinics", "unit_price"))
    after = _apply({"ops.product_overrides":
                    {"Medical laundry for clinics": 310}}, ops)
    self.assertEqual(310, G.find_product(after, "Medical laundry for clinics")
                     .get("unit_price"))
    # and with no asked cell to place it in, it is REPORTED, not dropped
    bare = _thackery()
    after2 = _apply({"ops.product_overrides":
                     {"Medical laundry for clinics": 310}}, bare)
    self.assertIn("_product_override_receipt", after2)
    self.assertEqual(["Medical laundry for clinics"],
                     after2["_product_override_receipt"]["unmatched"])
    self.assertTrue(IC._ops_material_from_receipt(after2),
                    "the consultant has something to say about it")

  def test_the_instruction_only_exists_with_the_frame(self):
    import inspect
    src = inspect.getsource(ROUTER.route_intent)
    self.assertEqual(1, src.count("The app's question this turn"))
    guard = src.index('_ops_frame = (shared_context or {}).get("ops_controller")')
    text = src.index("The app's question this turn")
    self.assertLess(guard, text)

  def test_her_cells_rank_ahead_of_another_sections_guess(self):
    """"we have 62 accounts" came back as candidate financials.current_revenue,
    and the app asked a laundry whether 62 was its annual revenue.

    THE FIRST FIX WENT TOO FAR (mini, 2026-09-26): it REPLACED the allowed set
    with her cells, so a figure that genuinely belongs to another section - the
    rent, said in passing during ops - was dropped instead of deprioritised,
    which is the same "she said it once" loss in different clothes. The consumer
    reads candidate_fields[0], so order is the lever: hers in front, the rest
    behind, nothing thrown away."""
    raw = [{"value_json": "62", "client_words": "We have 62 accounts",
            "candidate_fields": ["financials.current_revenue",
                                 "ops.unit_price"]}]
    allowed = ["financials.current_revenue", "ops.unit_price",
               "ops.utilization_rate"]
    loose = ROUTER._clean_unresolved_figures(raw, allowed)
    self.assertEqual(["financials.current_revenue", "ops.unit_price"],
                     loose[0]["candidate_fields"],
                     "with no frame the router's own order stands")
    held = ROUTER._clean_unresolved_figures(
      raw, allowed, cell_fields=["unit_price", "utilization_rate"])
    self.assertEqual("ops.unit_price", held[0]["candidate_fields"][0],
                     "her cell is what the consumer will read")
    self.assertIn("financials.current_revenue", held[0]["candidate_fields"],
                  "and the other section's candidate is kept, not dropped")

  def test_a_figure_for_another_section_survives_an_ops_turn(self):
    """The rent, mentioned while the app was asking about a line. It is not an
    ops cell and it must still be there afterwards."""
    raw = [{"value_json": "11000", "client_words": "rent is 11 thousand a month",
            "candidate_fields": ["financials.rent_monthly"]}]
    held = ROUTER._clean_unresolved_figures(
      raw, ["financials.rent_monthly"], cell_fields=["unit_price"])
    self.assertEqual(["financials.rent_monthly"], held[0]["candidate_fields"])
    self.assertEqual(11000, held[0]["value"])

  def test_only_a_cell_of_hers_can_be_noted_against(self):
    """And the handler will not note it against the other section's field:
    a note keyed by something that is not a cell can never be offered back at
    a cell, and taking the first candidate regardless is what asked a laundry
    whether 62 was its revenue. It goes to the unplaced path instead."""
    import inspect
    src = inspect.getsource(IC)
    self.assertIn("if c and c in _her_cells", src)
    frame = IC._build_ops_controller_context(_thackery())
    cells = set(frame["cell_fields"])
    self.assertIn("unit_price", cells)
    self.assertNotIn("current_revenue", cells)
    self.assertNotIn("rent_monthly", cells)

  def test_her_words_survive_the_filter(self):
    raw = [{"value_json": "260", "client_words": "260 is the price per account",
            "candidate_fields": ["ops.unit_price"]}]
    out = ROUTER._clean_unresolved_figures(
      raw, ["ops.unit_price"], cell_fields=["unit_price"])
    self.assertEqual(260, out[0]["value"])
    self.assertIn("260 is the price", out[0]["client_words"])


if __name__ == "__main__":
  unittest.main()
