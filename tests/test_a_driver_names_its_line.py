"""A driver that names its line has a row to land on.

MEASURED across every server log, 2026-09-13: 106 unrouted `unit_price` writes,
91 `units_per_week_capacity`, 89 `units_per_period_capacity`, 77
`operating_periods_per_year` - six driver fields in all. Each one is a turn
where a client answered a question and nothing was recorded, because a bare
`ops.unit_price` carries no line and a multi-line business has no row to put it
on. Thackeray & Nunes answered the capacity question three times and the store
held nothing.

Dropping the row-less write is right (A-113: writing it anyway manufactured
receipts no reader consumed). The fix is not to drop it better - it is for the
number to arrive with its line attached.

THE SHAPE IS ALREADY SHIPPED. `financials.cogs_per_line_overrides` (A-110) puts
row identity in the VALUE, so the `<group>.<field>` patch grammar never changes
and `_resolve_cogs_line` - which refuses ambiguity rather than guessing - does
the matching. This is the same door for ops drivers.

The nets underneath stay. They stop being the only thing between a client and a
wrong number.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


def _ops():
  return {"lob_models": [{"lob_name": "Stone fabrication and installation",
                          "products": [
    {"product_name": "Residential countertops and vanities", "unit_cadence": "contract"},
    {"product_name": "Commercial architectural stonework", "unit_cadence": "contract"},
    {"product_name": "Memorials and headstones", "unit_cadence": "contract"},
  ]}]}


class ADriverLandsOnTheLineItNames(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _apply_ops_product_overrides,
    )

    self.apply = _apply_ops_product_overrides

  def _rows(self, ops):
    return ops["lob_models"][0]["products"]

  def test_it_lands_on_the_named_row(self):
    ops = _ops()
    receipt = self.apply(ops, {"Residential countertops and vanities": {
      "concurrent_capacity_units": 30, "annual_turns_per_year": 18}})
    row = self._rows(ops)[0]
    self.assertEqual(row.get("concurrent_capacity_units"), 30)
    self.assertEqual(row.get("annual_turns_per_year"), 18)
    self.assertTrue(receipt["written"])

  def test_the_other_lines_are_untouched(self):
    """The failure this replaces put one line's number on all of them, or on
    none. Both are wrong; only the named row moves."""
    ops = _ops()
    self.apply(ops, {"Memorials and headstones": {"unit_price": 1800}})
    self.assertEqual(self._rows(ops)[2].get("unit_price"), 1800)
    for other in (0, 1):
      self.assertIsNone(self._rows(ops)[other].get("unit_price"),
                        "a driver leaked onto a line the client did not name")

  def test_several_lines_in_one_patch(self):
    ops = _ops()
    self.apply(ops, {
      "Residential countertops and vanities": {"unit_price": 4200},
      "Memorials and headstones": {"unit_price": 1800},
    })
    self.assertEqual(self._rows(ops)[0].get("unit_price"), 4200)
    self.assertEqual(self._rows(ops)[2].get("unit_price"), 1800)
    self.assertIsNone(self._rows(ops)[1].get("unit_price"))

  def test_a_name_we_cannot_place_is_reported_not_dropped(self):
    """The whole point. An unplaceable name comes back so the caller can ASK;
    silence is what cost the Thackeray run three turns."""
    ops = _ops()
    receipt = self.apply(ops, {"the stone bit": {"unit_price": 4200}})
    self.assertFalse(receipt["written"])
    self.assertEqual(len(receipt["unmatched"]), 1)
    self.assertEqual(receipt["unmatched"][0]["line_name"], "the stone bit")
    self.assertEqual(receipt["unmatched"][0]["values"], {"unit_price": 4200})

  def test_an_ambiguous_name_is_refused_rather_than_guessed(self):
    """_resolve_cogs_line returns nothing when a name fits two rows. A driver
    on the wrong line is a wrong number that reads as a real one."""
    ops = {"lob_models": [{"lob_name": "Stone", "products": [
      {"product_name": "Countertops"}, {"product_name": "Countertops"}]}]}
    receipt = self.apply(ops, {"Countertops": {"unit_price": 4200}})
    self.assertFalse(receipt["written"])
    self.assertTrue(receipt["unmatched"])

  def test_only_driver_fields_are_accepted(self):
    """The value is client-shaped data arriving from a model - it must not be
    a way to set arbitrary keys on a product row."""
    ops = _ops()
    receipt = self.apply(ops, {"Memorials and headstones": {
      "unit_price": 1800, "_guard": 1, "cogs_percent_of_line_revenue": 0.9}})
    row = self._rows(ops)[2]
    self.assertEqual(row.get("unit_price"), 1800)
    self.assertNotIn("_guard", row)
    self.assertNotIn("cogs_percent_of_line_revenue", row,
                     "direct costs have their own door with its own unit rule")
    self.assertIn("_guard", receipt["ignored"])

  def test_nothing_happens_on_an_empty_or_malformed_patch(self):
    for value in ({}, None, [], "nonsense", {"a line": "not an object"}):
      ops = _ops()
      receipt = self.apply(ops, value)
      self.assertFalse(receipt["written"])
      self.assertEqual(self._rows(ops)[0].get("unit_price"), None)


class TheRouterCanEmitIt(unittest.TestCase):
  """A door the router cannot reach is a door that does not exist - the lesson
  from concurrent_capacity_units sitting unused in 3,127 rows."""

  def setUp(self):
    self.src = (ROOT / "python" / "client_intake_and_finmo" / "intent_router.py").read_text(
      encoding="utf-8-sig")

  def test_ops_can_emit_product_overrides(self):
    i = self.src.index('"ops": [')
    self.assertIn('"product_overrides",', self.src[i:i + 2500],
                  "ops cannot emit the key, so the door is unreachable")

  def test_the_router_is_told_a_bare_driver_has_no_line(self):
    self.assertIn("has NO line attached to it", self.src,
                  "without this the router keeps emitting bare driver keys and "
                  "they keep being dropped")

  def test_it_is_only_offered_when_there_are_lines_to_name(self):
    """Single-row drafts keep the flat keys - 5,854 of them, where a bare
    driver is unambiguous and correct."""
    i = self.src.index("Per-line drivers (this business has SEVERAL revenue lines)")
    self.assertIn("_draft_has_multiple_revenue_lines(shared_context)",
                  self.src[max(0, i - 800):i],
                  "the per-line door must be gated on the draft having lines")



class ThePatchDoorItselfIsExercised(unittest.TestCase):
  """The pin that would have caught the 500.

  e5b28c76 shipped `(draft_id or "-")[:12]` inside a log line in
  `_apply_scoped_patch`, which has no `draft_id` parameter. The first per-line
  driver the router ever emitted - "on the memorials and headstones line we can
  have about 12 going at once" - crashed the turn with NameError, on origin.

  The class above tests `_apply_ops_product_overrides` directly and passes
  happily, because the defect was never in the applier: it was in the hook into
  it. The applier was tested; the call site was not. That is the same shape as
  a filter written and never called, and the same NameError class as `ops_json`
  earlier the same day - a name assumed to be in scope, in a line that only
  runs when the feature actually fires.

  So this drives the real door, with the real patch key, and reads the row that
  comes back out of it.
  """

  def setUp(self):
    from api_handlers.intake_consult import _apply_scoped_patch  # type: ignore

    self.apply = _apply_scoped_patch

  def _run(self, patch, ops=None):
    return self.apply(
      patch,
      business_facts={}, ops_json=(ops if ops is not None else _ops()),
      market_json={}, people_json={}, financials_json={}, fulfillment_json={},
      user_message="",
    )

  def test_a_per_line_driver_goes_through_the_real_door(self):
    """The door WRITES; the normaliser FOLDS. The live turn does both in that
    order (_apply_scoped_patch, then _normalize_ops_capacity_compat), so the
    pin does too - an earlier version asserted the fold straight out of the
    door and failed on correct code, which is testing the wrong layer.
    """
    from api_handlers.intake_consult import (  # type: ignore
      _normalize_ops_capacity_compat,
    )

    _b, ops_out, _m, _p, _f, _fu = self._run(
      {"ops.product_overrides": {
        "Memorials and headstones": {"concurrent_capacity_units": 12,
                                     "annual_turns_per_year": 12}}})
    rows = ops_out["lob_models"][0]["products"]
    self.assertEqual(rows[2].get("concurrent_capacity_units"), 12,
                     "the door did not land the driver on the named row")
    for other in (0, 1):
      self.assertIsNone(rows[other].get("concurrent_capacity_units"),
                        "a driver leaked onto a line the client did not name")

    folded = _normalize_ops_capacity_compat(ops_out)
    row = folded["lob_models"][0]["products"][2]
    # REVERSED 2026-09-13: the six stays in the field that means at once -
    # the fold that moved it into the period slot is gone.
    self.assertIn("concurrent_capacity_units", row,
                  "the concurrent figure left the field that means at once")
    self.assertEqual(row["concurrent_capacity_units"], 12)
    self.assertEqual(row.get("annual_turns_per_year"), 12)
    self.assertIsNone(row.get("units_per_period_capacity"))
    self.assertIsNone(row.get("operating_periods_per_year"))

  def test_a_price_for_one_line_goes_through_the_real_door(self):
    _b, ops_out, _m, _p, _f, _fu = self._run(
      {"ops.product_overrides": {
        "Residential countertops and vanities": {"unit_price": 4200}}})
    rows = ops_out["lob_models"][0]["products"]
    self.assertEqual(rows[0].get("unit_price"), 4200)
    self.assertIsNone(rows[1].get("unit_price"))

  def test_an_unplaceable_name_is_recorded_at_the_real_door(self):
    """It must reach the record the which-line question reads, not vanish."""
    _b, ops_out, _m, _p, _f, _fu = self._run(
      {"ops.product_overrides": {"the stone bit": {"unit_price": 4200}}})
    open_recs = ops_out.get("_unrouted_driver_writes") or []
    self.assertTrue(open_recs, "an unplaceable line name was dropped in silence")
    self.assertEqual(open_recs[0].get("field"), "unit_price")
    self.assertEqual(open_recs[0].get("named"), "the stone bit")

  def test_the_door_does_not_raise_on_any_shape(self):
    """The NameError fired only when the feature actually ran. Every shape the
    router can emit must go through without raising."""
    for value in ({}, None, "nonsense", [],
                  {"Memorials and headstones": {"unit_price": 1800}},
                  {"no such line": {"unit_price": 1}},
                  {"Memorials and headstones": {"_guard": 1}}):
      try:
        self._run({"ops.product_overrides": value})
      except Exception as exc:                       # noqa: BLE001
        self.fail("the patch door raised on %r: %s: %s"
                  % (value, type(exc).__name__, exc))

  def test_a_flat_driver_still_works_on_a_single_row_draft(self):
    """5,854 drafts have one row, where a bare driver is unambiguous. Step 4:
    they keep the flat keys."""
    single = {"lob_models": [{"lob_name": "Stone", "products": [
      {"product_name": "Countertops", "unit_cadence": "weekly"}]}]}
    _b, ops_out, _m, _p, _f, _fu = self._run({"ops.unit_price": 4200}, ops=single)
    self.assertEqual(
      ops_out["lob_models"][0]["products"][0].get("unit_price"), 4200,
      "a single-row draft must still land a bare driver on its one row")


if __name__ == "__main__":
  unittest.main(verbosity=2)
