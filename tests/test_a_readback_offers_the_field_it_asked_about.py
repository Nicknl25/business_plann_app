"""A READBACK OFFERS THE FIELD ITS QUESTION WAS ABOUT (Nick 2026-09-15, Cowork 1267).

CW-072 Marley Lane Barbers 598802b8, turn 9. The app asked for a typical week; she said
"About fifty."; the router returned the figure unresolved with candidates
[annual_completed_units, expected_revenue_year1, units_per_week_capacity,
units_per_period_capacity], and the question offered the first two: "is 50 your how many
you usually finish in a year, or your the revenue you expect in your first full year?"
Neither was the question. A readback whose options exclude the true answer turns her
confusion into her consent. The router now names the field the app's question asked for,
and that field always leads the options - for any business, any question.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python"), os.path.join(ROOT, "python", "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intent_router import _clean_unresolved_figures  # noqa: E402
from api_handlers.intake_consult import _unresolved_figures_ask, _humanize_field_for_ask  # noqa: E402


# (business, question field the app asked for, the router's other candidates, the words)
SHAPES = [
  ("barbershop", "ops.avg_units_per_week_year1",
   ["ops.annual_completed_units", "financials.expected_revenue_year1", "ops.units_per_week_capacity"], "About fifty."),
  ("kimchi maker", "ops.avg_units_per_period_year1",
   ["ops.units_per_period_capacity", "ops.annual_completed_units"], "About eight hundred."),
  ("boat yard", "ops.concurrent_capacity_units",
   ["ops.annual_completed_units", "ops.units_per_week_capacity"], "Four."),
  ("dental clinic", "ops.unit_price",
   ["ops.units_per_week_capacity", "financials.current_revenue"], "One twenty."),
]


class TheQuestionFieldLeadsTheOptions(unittest.TestCase):

  def test_the_asked_field_is_always_offered(self):
    for business, qf, others, words in SHAPES:
      with self.subTest(business=business):
        figs = [{"value": 50, "client_words": words, "candidate_fields": list(others), "question_field": qf}]
        q = _unresolved_figures_ask(figs)
        self.assertIn(_humanize_field_for_ask(qf), q, q)
        self.assertLess(q.index(_humanize_field_for_ask(qf)), len(q), q)

  def test_the_asked_field_is_first_even_when_the_router_listed_it_last(self):
    qf = "ops.avg_units_per_week_year1"
    figs = [{"value": 50, "client_words": "About fifty.", "question_field": qf,
             "candidate_fields": ["ops.annual_completed_units", "financials.expected_revenue_year1", qf]}]
    q = _unresolved_figures_ask(figs)
    self.assertIn("is 50 how many you actually do in a typical week, or ", q)

  def test_no_option_reads_your_how_or_your_the(self):
    for business, qf, others, words in SHAPES:
      with self.subTest(business=business):
        q = _unresolved_figures_ask([{"value": 5, "client_words": words, "candidate_fields": list(others), "question_field": qf}])
        self.assertIsNone(re.search(r"\byour (how|what|the)\b", q, re.I), q)

  def test_the_marley_lane_turn_offers_the_typical_week(self):
    q = _unresolved_figures_ask([{
      "value": 50, "client_words": "About fifty.", "question_field": "ops.avg_units_per_week_year1",
      "candidate_fields": ["ops.annual_completed_units", "financials.expected_revenue_year1",
                           "ops.units_per_week_capacity", "ops.units_per_period_capacity"]}])
    self.assertIn("how many you actually do in a typical week", q)
    self.assertNotIn("your the", q)
    self.assertNotIn("your how", q)

  def test_without_a_question_field_the_candidates_are_asked_as_before(self):
    q = _unresolved_figures_ask([{"value": 40, "client_words": "40 a week",
                                  "candidate_fields": ["ops.units_per_week_capacity", "ops.unit_price"], "question_field": ""}])
    self.assertIn("your weekly capacity", q)
    self.assertIn("your price", q)


class TheRouterNamesTheQuestionField(unittest.TestCase):

  def test_clean_puts_an_allowed_question_field_first(self):
    out = _clean_unresolved_figures(
      [{"value_json": "50", "client_words": "About fifty.", "question_field": "avg_units_per_week_year1",
        "candidate_fields": ["annual_completed_units", "expected_revenue_year1", "avg_units_per_week_year1"]}],
      ["annual_completed_units", "expected_revenue_year1", "avg_units_per_week_year1"])
    self.assertEqual(out[0]["question_field"], "avg_units_per_week_year1")
    self.assertEqual(out[0]["candidate_fields"][0], "avg_units_per_week_year1")
    self.assertEqual(out[0]["candidate_fields"].count("avg_units_per_week_year1"), 1)

  def test_a_question_field_outside_the_allowed_list_is_dropped(self):
    out = _clean_unresolved_figures(
      [{"value_json": "50", "client_words": "x", "question_field": "made_up_field", "candidate_fields": ["unit_price"]}],
      ["unit_price"])
    self.assertEqual(out[0]["question_field"], "")
    self.assertEqual(out[0]["candidate_fields"], ["unit_price"])

  def test_the_schema_requires_the_question_field(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intent_router.py"), encoding="utf-8").read()
    self.assertIn('"required": ["value_json", "client_words", "candidate_fields", "question_field"]', src)


if __name__ == "__main__":
  unittest.main()
