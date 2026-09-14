"""The ask on a per-contract business: no pasted clause, no wrong slot, no key.

Vasquez-Lindqvist Timber Frames ec2da9c7, replay turn 17, 2026-09-13. After the
capacity finally survived the store, the client saw:

    "So that I record it the right way round - is 34 would be flat out your
     capacity per period, or your weekly capacity?"

Three defects in one question, each pinned here on what the client READS:

1. A PASTED CLAUSE. The issue-589 rule keeps the client's phrase when it starts
   with the figure. "34 would be flat out" starts with the figure and then runs
   on into a verb, so it survived and was pasted in as a noun.

2. A WRONG SLOT. On a per-contract business the period slot is not a rate at
   all - financials_year1 aliases it to concurrent load - and a per-contract row
   has no weekly rate (4f166370). So "Over a year that works out around 26 of
   them" settling to units_per_period_capacity would record 26 a year as
   twenty-six AT ONCE, and offering the weekly slot offers a field the business
   cannot have.

3. A KEY SPOKEN ALOUD. _humanize_field_for_ask falls back to de-underscoring the
   key when _ASK_FIELD_NAMES has no entry, and the concurrent pair had none - the
   source of "is that capacity per period, or your concurrent capacity units?".
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_PAIR = ["ops.units_per_period_capacity", "ops.units_per_week_capacity"]


def _draft(cadence):
  return {"lob_models": [{"lob_name": "Primary line of business", "products": [
    {"product_name": "Custom residential timber frames", "unit_cadence": cadence},
    {"product_name": "Commercial timber structures", "unit_cadence": cadence},
    {"product_name": "Shipped frame kits for builders", "unit_cadence": cadence},
  ]}]}


class TheAskNeverPastesAClause(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import _unresolved_figures_ask  # type: ignore

    self.ask = _unresolved_figures_ask

  def _q(self, value, words, cands=None):
    return self.ask([{"value": value, "client_words": words,
                      "candidate_fields": cands or ["ops.units_per_period_capacity"]}])

  def test_the_turn_17_question(self):
    q = self._q(34, "34 would be flat out", list(_PAIR))
    self.assertNotIn("would be flat out", q, "a clause was pasted in as a noun: %r" % q)
    self.assertIn("34", q)

  def test_a_phrase_that_runs_on_into_a_verb_is_not_kept(self):
    """SHORT clauses, deliberately. The first version used eight-word phrases,
    which the existing seven-word length gate already drops - so it passed on
    the unfixed code and proved nothing about the clause rule it is named for.
    Every phrase here clears both older gates (starts with its figure, seven
    words or fewer, forty characters or fewer), so only the clause rule can
    keep it out of the question."""
    for value, words in ((6, "6 is the most"),
                         (34, "34 would be flat out"),
                         (26, "26 works out a year"),
                         (10, "10 takes about ten weeks")):
      self.assertLessEqual(len(words.split()), 7, "the length gate would catch it")
      self.assertLessEqual(len(words), 40, "the length gate would catch it")
      q = self._q(value, words)
      self.assertNotIn(words, q, "pasted clause: %r" % q)
      self.assertIn(str(value), q)

  def test_good_phrasing_is_still_kept(self):
    """The router pin requires "40 a week"; issue 589's pin requires
    "four hulls at once". Neither is a clause."""
    self.assertIn("40 a week", self._q(40, "40 a week",
                                       ["ops.units_per_week_capacity", "ops.unit_price"]))
    self.assertIn("four hulls at once", self._q(4, "four hulls at once"))


class AContractDraftNeverRecordsAYearAsConcurrent(unittest.TestCase):
  """Driven through _unresolved_figures_open - the decider, not the builder."""

  def setUp(self):
    from api_handlers.intake_consult import _unresolved_figures_open  # type: ignore

    self.open = _unresolved_figures_open

  def _open(self, cadence, value, words, cands):
    return self.open([{"value": value, "client_words": words, "candidate_fields": cands}],
                     ops_json=_draft(cadence), people_json={}, financials_json={})

  def test_a_year_is_not_settled_into_the_period_slot_on_a_contract_draft(self):
    out = self._open("contract", 26, "Over a year that works out around 26 of them", list(_PAIR))
    self.assertTrue(
      any(f.get("value") == 26 for f in out),
      "26 a year was SETTLED into units_per_period_capacity on a per-contract "
      "draft, where that slot means how many at once - 26 at once, not 26 a year")

  def test_the_weekly_slot_is_never_offered_on_a_contract_draft(self):
    out = self._open("contract", 34, "34 would be flat out", list(_PAIR))
    for f in out:
      self.assertNotIn("ops.units_per_week_capacity", f.get("candidate_fields") or [],
                       "a per-contract row has no weekly rate (4f166370)")

  def test_a_weekly_draft_still_settles_a_weekly_figure(self):
    """Forward-only: the fix is scoped to contract rows."""
    out = self._open("weekly", 45, "Countertops run about 45 a week", list(_PAIR))
    self.assertEqual(out, [], "a weekly draft stopped settling 'a week'")


class TheAskHasWordsForTheConcurrentPair(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import _humanize_field_for_ask  # type: ignore

    self.say = _humanize_field_for_ask

  def test_neither_key_is_spoken(self):
    for field in ("ops.concurrent_capacity_units", "ops.annual_turns_per_year"):
      said = self.say(field)
      leaf = field.split(".")[-1]
      self.assertNotEqual(said, leaf.replace("_", " "),
                          "the ask spoke %s as its own key" % leaf)
      self.assertNotIn("_", said)
      self.assertTrue(said)


if __name__ == "__main__":
  unittest.main(verbosity=2)
