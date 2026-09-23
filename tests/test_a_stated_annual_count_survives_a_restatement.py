"""A figure the client stated about a line survives a restatement that is silent about it.

Ashgrove Bindery bf731ee4, 2026-09-22, the killing turn. She said ten at once
and about eleven hundred a year. Her 1,100 landed on both rows through the
per-line door at 19:39:38 and was gone by 19:39:45 - the ops consultant returns
a FULL lob_models snapshot every turn, `_apply_model_ops_patch` assigns that
list wholesale, and the consultant's strict schema has no key named
annual_completed_units at all. `_carry_forward_per_line_drivers` restores only
the keys in `_CARRIED_PER_LINE_KEYS`, and her driver's name had never been in
that tuple.

What it cost: with her own figure erased, the turns slot was the only home left
for her annual volume. Two turns later she answered a question about her working
year, 48 landed in the turns slot, and 10 x 48 = 480 - a 56% cut to her year
from a question she answered truthfully, with no field left on the row that
could contradict it. The contradiction hold (intake_consult.py:892+) was built
to catch exactly that and could not: it reads annual_completed_units off the
row, and from the next turn on there was nothing there. THE KEEPER WAS NOT KEPT.

THE PROPERTY, not the instance (Nick, standing: every fix is for any business).
A pin that fires only on Ashgrove's two rows is evidence, not protection. What
is pinned here is the general rule, over varied shapes - different businesses,
cadences, row counts, and row positions:

    FOR ANY ROW CARRYING A CLIENT-STATED PER-LINE DRIVER, AN OPS-CONSULTANT
    SNAPSHOT THAT DOES NOT MENTION THAT DRIVER LEAVES IT ON THE ROW.

These pins drive the REAL door and read KEY PRESENCE, never `.get()` - a missing
key and a null read identically through `.get()`, and absent-vs-null is the
exact difference this whole class of defect lives in.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


#: The ops consultant's strict schema, key for key (intake_consultant.py:546-585).
#: EVERY product key is required and there is no annual key among them - which is
#: why a snapshot is silent about her figure without ever intending to clear it.
_CONSULTANT_PRODUCT_KEYS = (
  "product_name", "unit_name", "unit_description", "unit_cadence",
  "units_per_week_capacity", "units_per_period_capacity",
  "operating_periods_per_year", "utilization_rate", "unit_price",
  "cogs_percent_of_line_revenue", "origin",
)

#: Varied shapes. Each is (business, lob name, row names, the row she was talking
#: about, cadence) - single-line and multi-line, the stated row first, last and in
#: the middle, three different cadences.
_SHAPES = (
  ("Ashgrove Bindery", "Primary line of business",
   ("Book binding & repair job", "Short-run print job"), 0, "contract"),
  ("Harlow Street Cycles", "Repairs and service",
   ("Full service", "Wheel build", "Frame respray"), 2, "weekly"),
  ("Perrin Row Ceramics", "Studio work",
   ("Commissioned dinner service",), 0, "contract"),
  ("Vasquez-Lindqvist Timber Frames", "Frames",
   ("Custom residential timber frames", "Commercial timber structures",
    "Shipped frame kits for builders"), 1, "monthly"),
)

#: The drivers a client states about a line that an ops restatement never emits.
#: Both halves of the annual pair: the count she finishes, and the ceiling - which
#: can sit at rest on a row for turns before a concurrent figure arrives to home it.
_STATED_DRIVERS = ("annual_completed_units", "annual_capacity_units")


def _snapshot(lob_name, row_names, cadence="contract", **first_row_overrides):
  """A consultant restatement: every schema key present, nulls where it has
  nothing to say. This is what actually arrives, not a hand-trimmed patch - and
  it does restate the cadence, which is how the real snapshots read."""
  rows = []
  for name in row_names:
    row = {k: None for k in _CONSULTANT_PRODUCT_KEYS}
    row["product_name"] = name
    row["unit_cadence"] = cadence
    rows.append(row)
  rows[0].update(first_row_overrides)
  return {"lob_models": [{"lob_name": lob_name, "products": rows}]}


def _stored(lob_name, row_names, stated_index, cadence, **stated):
  rows = []
  for name in row_names:
    rows.append({"product_name": name, "unit_cadence": cadence})
  rows[stated_index].update(stated)
  return {"lob_models": [{"lob_name": lob_name, "products": rows}]}


class AStatedAnnualDriverSurvivesASilentRestatement(unittest.TestCase):
  """The property, over every shape in _SHAPES x every driver."""

  def setUp(self):
    from api_handlers.intake_consult import _apply_model_ops_patch  # type: ignore

    self.door = _apply_model_ops_patch

  def test_a_snapshot_silent_about_her_driver_leaves_it_on_the_row(self):
    for business, lob_name, row_names, idx, cadence in _SHAPES:
      for driver in _STATED_DRIVERS:
        with self.subTest(business=business, driver=driver):
          ops = _stored(lob_name, row_names, idx, cadence, **{driver: 1100})
          out = self.door(ops, _snapshot(lob_name, row_names, cadence),
                          user_message="About eleven hundred.")
          row = out["lob_models"][0]["products"][idx]
          self.assertIn(driver, row,
                        "%s: the key is ABSENT - the restatement erased what she "
                        "stated (the store Cowork read on Ashgrove)" % business)
          self.assertEqual(row[driver], 1100,
                           "%s: her figure did not survive the restatement" % business)

  def test_the_rows_she_never_spoke_about_gain_nothing(self):
    """Carrying is not spreading. A driver stated about one row stays on it."""
    for business, lob_name, row_names, idx, cadence in _SHAPES:
      if len(row_names) < 2:
        continue
      with self.subTest(business=business):
        ops = _stored(lob_name, row_names, idx, cadence, annual_completed_units=1100)
        out = self.door(ops, _snapshot(lob_name, row_names, cadence))
        for i, row in enumerate(out["lob_models"][0]["products"]):
          if i == idx:
            continue
          self.assertIsNone(row.get("annual_completed_units"),
                            "%s: a figure appeared on a line she never discussed" % business)

  def test_a_restatement_that_carries_its_own_figure_is_a_statement(self):
    """Carrying restores what silence would have erased; it never overrules a
    figure the restatement actually states."""
    for business, lob_name, row_names, idx, cadence in _SHAPES:
      with self.subTest(business=business):
        ops = _stored(lob_name, row_names, idx, cadence, annual_completed_units=1100)
        snap = _snapshot(lob_name, row_names, cadence)
        snap["lob_models"][0]["products"][idx]["annual_completed_units"] = 1300
        out = self.door(ops, snap)
        row = out["lob_models"][0]["products"][idx]
        self.assertEqual(row.get("annual_completed_units"), 1300)

  def test_the_driver_survives_restatement_after_restatement(self):
    """One turn of survival is not enough - the 48 arrived two turns later."""
    for business, lob_name, row_names, idx, cadence in _SHAPES:
      with self.subTest(business=business):
        ops = _stored(lob_name, row_names, idx, cadence, annual_completed_units=1100)
        for _ in range(4):
          ops = self.door(ops, _snapshot(lob_name, row_names, cadence))
        row = ops["lob_models"][0]["products"][idx]
        self.assertIn("annual_completed_units", row)
        self.assertEqual(row["annual_completed_units"], 1100)


class TheCarriedPairStillHomesWhenTheCeilingArrivesLater(unittest.TestCase):
  """The named neighbour. Making the pair survive must not stop it being
  CONSUMED: a carried actual beside a ceiling that arrives later still homes to
  utilisation and pops, exactly as ANNUAL_PAIR_HOMED did before this carry."""

  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _apply_model_ops_patch, _normalize_ops_capacity_compat)

    self.door = _apply_model_ops_patch
    self.normalize = _normalize_ops_capacity_compat

  def test_a_carried_actual_homes_to_utilisation_when_the_pair_completes(self):
    lob_name, row_names, idx, cadence = "Frames", ("Custom frames", "Kits"), 0, "contract"
    ops = _stored(lob_name, row_names, idx, cadence, annual_completed_units=26)
    # a restatement that says nothing about it - previously the erasure
    ops = self.door(ops, _snapshot(lob_name, row_names))
    self.assertEqual(ops["lob_models"][0]["products"][idx]["annual_completed_units"], 26)
    # now the rest of the pair arrives, the way the router writes it
    row = ops["lob_models"][0]["products"][idx]
    row["concurrent_capacity_units"] = 6
    row["annual_capacity_units"] = 34
    self.normalize(ops)
    row = ops["lob_models"][0]["products"][idx]
    # homed as turns, then folded into the canonical slot at the same door
    self.assertAlmostEqual(row.get("operating_periods_per_year"), 34 / 6, places=9)
    self.assertAlmostEqual(row.get("utilization_rate"), 26 / 34, places=9)
    self.assertNotIn("annual_capacity_units", row, "the ceiling was not consumed")
    self.assertNotIn("annual_completed_units", row, "the actual was not consumed")
    # and the round trip returns what she said, unrounded
    self.assertAlmostEqual(
      row["units_per_period_capacity"] * row["operating_periods_per_year"]
      * row["utilization_rate"], 26.0, places=9)

  def test_a_carried_ceiling_homes_when_the_concurrent_figure_arrives_later(self):
    """The ceiling half: it can sit at rest on a row for turns, through any
    number of silent restatements, before a concurrent figure gives it a home."""
    lob_name, row_names, idx, cadence = "Studio work", ("Dinner service",), 0, "contract"
    ops = _stored(lob_name, row_names, idx, cadence, annual_capacity_units=34)
    for _ in range(3):
      ops = self.door(ops, _snapshot(lob_name, row_names))
    self.assertEqual(ops["lob_models"][0]["products"][idx]["annual_capacity_units"], 34)
    ops["lob_models"][0]["products"][idx]["concurrent_capacity_units"] = 6
    self.normalize(ops)
    row = ops["lob_models"][0]["products"][idx]
    self.assertAlmostEqual(row.get("operating_periods_per_year"), 34 / 6, places=9)
    self.assertEqual(row.get("units_per_period_capacity"), 6)
    self.assertNotIn("annual_capacity_units", row)


class ACarriedFigureIsSomethingTheHoldCanRead(unittest.TestCase):
  """Why the carry is the deal breaker. With her figure surviving, a later write
  that contradicts it is HELD and put back to her; without it, nothing notices.

  This is Ashgrove's arithmetic stated generally: any stated annual count, any
  concurrent figure, and a later answer that lands in the turns slot.
  """

  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _apply_model_ops_patch, _normalize_ops_capacity_compat)

    self.door = _apply_model_ops_patch
    self.normalize = _normalize_ops_capacity_compat

  def test_a_working_year_written_as_turns_is_held_against_her_own_count(self):
    for annual, concurrent, weeks in ((1100, 10, 48), (2600, 25, 50), (780, 3, 46)):
      with self.subTest(annual=annual):
        lob_name, row_names = "Primary line of business", ("The line", "Another line")
        ops = _stored(lob_name, row_names, 0, "contract",
                      annual_completed_units=annual,
                      units_per_period_capacity=concurrent)
        ops = self.door(ops, _snapshot(lob_name, row_names))   # a silent restatement
        row = ops["lob_models"][0]["products"][0]
        self.assertEqual(row.get("annual_completed_units"), annual,
                         "the erasure is back and nothing below can be true")
        row["operating_periods_per_year"] = weeks               # her working year, mislabelled
        self.normalize(ops)
        row = ops["lob_models"][0]["products"][0]
        self.assertIsNone(row.get("operating_periods_per_year"),
                          "a count that contradicts her own figure was stored anyway")
        recs = row.get("_implausible_writes") or []
        self.assertTrue(
          any(r.get("field") == "operating_periods_per_year" for r in recs),
          "her figure survived but nothing held the write that contradicts it")

  def test_her_own_count_still_converts_when_nothing_contradicts_it(self):
    """The hold is for contradictions only. On a row with no turns figure, her
    count is converted to turns and KEPT beside them."""
    lob_name, row_names = "Primary line of business", ("The line",)
    ops = _stored(lob_name, row_names, 0, "contract",
                  annual_completed_units=1100, units_per_period_capacity=10)
    ops = self.door(ops, _snapshot(lob_name, row_names))
    self.normalize(ops)
    row = ops["lob_models"][0]["products"][0]
    self.assertAlmostEqual(row.get("operating_periods_per_year"), 110.0, places=9)
    self.assertEqual(row.get("annual_completed_units"), 1100,
                     "her figure must stay as she said it, not only as a factor")
    self.assertFalse(row.get("_implausible_writes"),
                     "a correctly homed count was called a contradiction")


class TheCarryListNamesTheAnnualPair(unittest.TestCase):
  """If the names leave the tuple again, this is the line that says so."""

  def test_both_halves_are_carried(self):
    from api_handlers.intake_consult import _CARRIED_PER_LINE_KEYS  # type: ignore

    for driver in _STATED_DRIVERS:
      self.assertIn(driver, _CARRIED_PER_LINE_KEYS)


if __name__ == "__main__":
  unittest.main(verbosity=2)
