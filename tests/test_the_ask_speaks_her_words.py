"""THE APP ASKED HER TO CHOOSE BETWEEN TWO RAW FIELD NAMES, AND BOTH WERE WRONG.

Ashworth and Delacroix Conservatory, draft d5b77aae, turn 21, verbatim:

    "The 200 - is that your capacity per period, or your operating periods
     per year?"

Two defects in one sentence.

FIRST, "operating periods per year" is the field key with its underscores
swapped for spaces. `_humanize_field_for_ask` carried a five-entry hand map for
"a few leaves whose raw names read poorly" and let everything else fall straight
through to `leaf.replace("_", " ")` - so every ops cell outside that map reached
the client as its own key. `_ops_cell_words` is where her words for every one of
those cells already live, and this function did not consult it: two
vocabularies, and the poorer one was the one she read.

SECOND, and worse: her 200 was NEITHER option. She had just said the hall
physically handles "no more than about 200 bookings over a full year" - an
ANNUAL MAXIMUM, which is not a per-period capacity and not a turns count. A
two-way choice that excludes the truth forces a wrong answer, and what followed
was:

    t22 "...you actually run about 140 bookings total; we'll use that 140 figure
         for how often your available slots turn over across the year."
    t24 "...running the hall at about seventy percent of its hard 200-booking
         ceiling (so roughly 140 bookings a year)"

The app put her annual VOLUME into the turns field and then applied her 70% on
top of a figure that already contained it: 4 x 140 x 0.7 = 392 bookings a year
against her stated ceiling of 200. Hall revenue $531,784 instead of about
$252,000, in a delivered workbook.

This module pins the question. Enforcing a ceiling she stated needs somewhere to
PUT it - her 200 is nowhere on the stored ops object - and that is a field, which
needs a name Nick has agreed before it ships.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python"),
          os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo import ops_cell_grid as G  # noqa: E402


def _every_ops_cell():
  cells = set(G._business_wide_fields())
  for cadence in ("weekly", "monthly", "contract", None):
    cells |= set(G.cells_for_product({"product_name": "x",
                                      "unit_cadence": cadence}))
  return sorted(cells)


class NoFieldKeyReachesHerInAQuestion(unittest.TestCase):

  def test_the_two_fields_from_the_live_question(self):
    for field in ("units_per_period_capacity", "operating_periods_per_year"):
      words = IC._humanize_field_for_ask(field)
      self.assertNotIn("_", words, field)
      self.assertNotEqual(field.replace("_", " "), words,
                          "%s is still the key with spaces" % field)
    self.assertEqual("how often that turns over in a year",
                     IC._humanize_field_for_ask("operating_periods_per_year"))

  def test_no_ops_cell_at_all_comes_back_as_its_key(self):
    """The property, not the two instances: every cell the grid can ask about."""
    for field in _every_ops_cell():
      words = IC._humanize_field_for_ask(field)
      self.assertTrue(words, field)
      self.assertNotIn("_", words, field)
      self.assertNotEqual(field.replace("_", " "), words,
                          "%s reaches her as its own key" % field)

  def test_it_reads_her_words_from_the_one_place_they_live(self):
    """Two vocabularies is how the poorer one ends up on her screen."""
    for field in _every_ops_cell():
      self.assertEqual(G and IC._ops_cell_words(field),
                       IC._humanize_field_for_ask(field), field)

  def test_a_prefixed_target_is_handled_too(self):
    self.assertEqual(IC._humanize_field_for_ask("operating_periods_per_year"),
                     IC._humanize_field_for_ask("ops.operating_periods_per_year"))

  def test_the_financials_fields_read_better_than_the_map_they_replaced(self):
    """_ops_cell_words turned out to be the client-words dictionary for far more
    than the grid's own cells, and every entry the old five-leaf hand map held
    reads better in it. So the map became unreachable and was removed rather
    than left beside the new thing - a second vocabulary that looks live is how
    the poorer one reached her screen."""
    for field, was, now in (
      ("unit_price", "price", "what you charge"),
      ("units_per_period_capacity", "capacity per period",
       "how much you can take on"),
      ("units_per_week_capacity", "weekly capacity",
       "how much you can take on in a week"),
      ("current_revenue", "annual revenue",
       "the revenue the business brings in now"),
      ("rest_of_team_payroll_year1", "rest-of-team payroll",
       "what the rest of the team is paid"),
    ):
      self.assertEqual(now, IC._humanize_field_for_ask(field), field)
      self.assertNotEqual(was, IC._humanize_field_for_ask(field), field)
    # AND THE MAP IS GONE, proven by behaviour rather than by scanning the
    # source - the first version of this assertion matched the phrase inside
    # this function's own comment, which is the trap that made six earlier pins
    # worthless. A field with no words now falls through to its key with
    # spaces, which is what "no private alias layer underneath" looks like from
    # the outside.
    self.assertEqual("", IC._ops_cell_words("some_invented_field"))
    self.assertEqual("some invented field",
                     IC._humanize_field_for_ask("some_invented_field"))

  def test_other_financials_fields_have_words_too(self):
    for field, want in (("monthly_rent_expense", "your rent"),
                        ("total_debt_outstanding", "what the business owes"),
                        ("inventory_balance", "the stock on hand")):
      self.assertEqual(want, IC._humanize_field_for_ask(field), field)


class AChoiceThatExcludesTheTruthOffersAWayOut(unittest.TestCase):

  def _ask(self, candidates):
    return IC._unresolved_figures_ask([{
      "value": 200, "client_words": "200 bookings a year",
      "candidate_fields": candidates}])

  def test_the_live_question_rebuilt(self):
    ask = self._ask(["ops.units_per_period_capacity",
                     "ops.operating_periods_per_year"])
    self.assertIn("200 bookings a year", ask)
    self.assertNotIn("_", ask)
    self.assertNotIn("operating periods per year", ask,
                     "the raw key must not reach her")
    self.assertIn("how much you can take on", ask)
    self.assertIn("how often that turns over in a year", ask)

  def test_she_can_say_neither(self):
    """Her 200 was an annual maximum - neither field offered. With no third
    option the app homed her figures wrongly and double-counted her 70%."""
    ask = self._ask(["ops.units_per_period_capacity",
                     "ops.operating_periods_per_year"])
    self.assertIn("neither", ask.lower())
    self.assertIn("right place", ask.lower())

  def test_a_single_candidate_also_offers_the_way_out(self):
    ask = self._ask(["ops.operating_periods_per_year"])
    self.assertIn("if not", ask.lower())
    self.assertNotIn("_", ask)

  def test_a_figure_with_no_candidate_still_asks_plainly(self):
    ask = IC._unresolved_figures_ask([{
      "value": 62, "client_words": "we have 62 accounts",
      "candidate_fields": []}])
    self.assertIn("62", ask)
    self.assertIn("?", ask)
    self.assertNotIn("_", ask)


class WhatThisDoesNotFixYet(unittest.TestCase):
  """Stated honestly, so nobody reads this module as more than it is."""

  def test_her_stated_ceiling_is_still_stored_nowhere(self):
    """She said "no more than about 200 bookings over a full year". There is no
    cell for it, so no reader can compare her row's arithmetic against it - and
    the ceiling the coherence check DOES use is derived from the same cells, so
    a wrong cell corrupts both the figure and its own check."""
    cells = _every_ops_cell()
    self.assertFalse([c for c in cells if "ceiling" in c or "max" in c],
                     "if a stated-ceiling cell exists now, enforce it and "
                     "delete this test")

  def test_and_the_row_that_breached_it_is_internally_consistent(self):
    """Which is why the question mattered so much: without her 200, 4 slots
    turning over 140 times is not detectably wrong."""
    row = {"product_name": "Recital hall booking", "unit_cadence": "contract",
           "units_per_period_capacity": 4, "operating_periods_per_year": 140,
           "utilization_rate": 0.7, "unit_price": 1800,
           "unit_name": "an evening slot", "unit_description": "one concert"}
    ops = {"lob_models": [{"lob_name": "Hall", "products": [row]}]}
    for f in G._business_wide_fields():
      ops[f] = "yes"
    self.assertTrue(G.grid_is_full(ops),
                    "the grid sees nothing wrong with it, which is the point")
    self.assertEqual(392, int(4 * 140 * 0.7))


if __name__ == "__main__":
  unittest.main()
