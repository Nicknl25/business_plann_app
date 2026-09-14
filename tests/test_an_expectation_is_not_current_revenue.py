"""An expected year-one revenue is not current revenue, and it stands on her words.

Cowork 1156/1163, 2026-09-14, on Halloran & Voss 955d2b460c0e4796a4bc55e5bf3fd0d1: a
pre-revenue client said "We expect about 9.3 million in the first full year" three times;
current_revenue ended on a derived 14,546,688.53 that is in none of her 135 messages. One
field holding both "what it brings in now" and "what she expects" is a rescale anchor whose
meaning changes without the rescale knowing - known bad. Her expectation gets its own field,
landed only with one unbroken stretch of her message that carries the figure.

These pins state, for any business and any phrasing the router hands over:
  - the router is offered the field and told an expectation is never current_revenue;
  - the figure lands with her words when the words are a contiguous span of her message
    carrying that figure, at the revenue stage and as a later correction;
  - paraphrased words, missing words, words without the figure, or a figure she did not
    say write nothing, and current_revenue is never touched by it;
  - "nothing yet" and an expectation in one message are two facts in two fields;
  - the field has words before it ships.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))

HALLORAN_63 = ("The percentages sound about right, but that dollar figure cannot be. We expect about 9.3 million in the "
               "first full year, so 6.25 million of direct cost would be most of our revenue. Something is off in the total.")
NOTHING_YET = "Nothing yet - we open in March. We're expecting around 400k in year one."


class TheRouterIsToldTheDifference(unittest.TestCase):
  def test_the_field_is_offered_and_explained(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "intent_router.py").read_text(encoding="utf-8")
    self.assertIn('"expected_revenue_year1": {"type": "number"}', src)
    self.assertIn('"expected_revenue_year1_words": {"type": "string"}', src)
    self.assertIn("current_revenue is ONLY what the business brings in now", src)
    self.assertIn("is never current_revenue", src)
    fields_block = src[src.index('"financials": [', src.index("def ")):]
    self.assertIn('"expected_revenue_year1"', fields_block[:600])

  def test_the_field_has_words(self):
    from client_intake_and_finmo.intake_required_fields import human_field_name
    self.assertEqual(human_field_name("expected_revenue_year1"), "the revenue you expect in your first full year")


class AnExpectationLandsOnlyOnHerWords(unittest.TestCase):
  def setUp(self):
    from api_handlers import intake_consult as ic  # type: ignore
    self.ic = ic

  def norm(self, patch, message, stage="revenue_intro", fin=None):
    return self.ic._normalize_financials_router_patch(
      patch=patch, active_stage=stage, financials_json=dict(fin or {}),
      financials_year1_json={"company_revenue_total_year1": 14796439.2},
      last_assistant="About how much is the business bringing in so far, if anything?", user_message=message)

  def test_her_words_carry_it_in_at_the_revenue_stage_and_as_a_later_correction(self):
    for stage, fin in (("revenue_intro", {}),
                       ("marketing", {"current_revenue": 0.0, "_financials_revenue_intro_done": True,
                                      "current_cogs": 1.0, "cogs_total_year1": 1.0, "cogs_percent_of_revenue": 0.155,
                                      "price_contracted": False, "current_payroll": 900000.0,
                                      "payroll_total_year1": 900000.0})):
      out = self.norm({"expected_revenue_year1": 9300000, "expected_revenue_year1_words": "We expect about 9.3 million in the first full year"},
                      HALLORAN_63, stage=stage, fin=fin)
      self.assertIsNotNone(out, stage)
      self.assertEqual(out.get("expected_revenue_year1"), 9300000.0, stage)
      self.assertEqual(out.get("expected_revenue_year1_words"), "We expect about 9.3 million in the first full year")
      self.assertNotEqual(out.get("current_revenue"), 9300000.0, "an expectation is never current revenue")

  def test_nothing_yet_and_an_expectation_are_two_facts(self):
    out = self.norm({"current_revenue": 0, "expected_revenue_year1": 400000,
                     "expected_revenue_year1_words": "We're expecting around 400k in year one"}, NOTHING_YET)
    self.assertEqual(out.get("current_revenue"), 0.0)
    self.assertEqual(out.get("expected_revenue_year1"), 400000.0)
    self.assertTrue(out.get("_financials_revenue_intro_done"))

  def test_without_her_words_nothing_is_written(self):
    for patch, message in (
        ({"expected_revenue_year1": 9300000}, HALLORAN_63),                                       # no words
        ({"expected_revenue_year1": 9300000, "expected_revenue_year1_words": "they expect 9.3 million in year one"}, HALLORAN_63),  # paraphrase
        ({"expected_revenue_year1": 9300000, "expected_revenue_year1_words": "We expect about 9.3 million the first full year"}, HALLORAN_63),  # stitched
        ({"expected_revenue_year1": 9300000, "expected_revenue_year1_words": "Something is off in the total"}, HALLORAN_63),  # no figure
        ({"expected_revenue_year1": 14546688.53, "expected_revenue_year1_words": "We expect about 9.3 million in the first full year"}, HALLORAN_63),  # not her figure
        ({"expected_revenue_year1": 400000, "expected_revenue_year1_words": "We're expecting around 400k in year one"}, "We're still working it out."),  # not her message
    ):
      out = self.norm(dict(patch), message) or {}
      self.assertNotIn("expected_revenue_year1", out, patch)
      self.assertNotIn("expected_revenue_year1_words", out, patch)
      self.assertNotIn("current_revenue", out, patch)


if __name__ == "__main__":
  unittest.main(verbosity=2)
