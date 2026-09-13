"""A ZERO THE CLIENT DID NOT SAY IS NOT A VALUE (2026-09-12, the issue-578
class). Northgate's owner answered the utilization question - "About 85
percent - we have 34 sites under contract" - and the router's line-row patch
carried unit_price = 0.0, a placeholder. Door A's model let it stand and door
C tagged the write router_patch/authorised; the price only became $1,200 two
turns later when the price question was asked. Door A now drops a zero on a
stated-fact leaf when the client's words carry no zero, none, no or nothing -
deterministically, before the model, and on the fail-open path too.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_guard import door_a as A  # noqa: E402


NORTHGATE_PATCH = {
  "ops.lob_models[0].products[0].unit_price": 0.0,
  "ops.lob_models[0].products[0].units_per_week_capacity": 40.0,
  "ops.lob_models[0].products[0].utilization_rate": 0.85,
}
WORDS = "About 85 percent - we have 34 sites under contract."


class APlaceholderZeroNeverLands(unittest.TestCase):
  def test_the_zero_price_is_dropped_and_the_stated_figures_stay(self):
    kept, dropped = A.drop_unsaid_zeros(NORTHGATE_PATCH, WORDS)
    self.assertNotIn("ops.lob_models[0].products[0].unit_price", kept)
    self.assertEqual(kept["ops.lob_models[0].products[0].units_per_week_capacity"], 40.0)
    self.assertEqual(kept["ops.lob_models[0].products[0].utilization_rate"], 0.85)
    self.assertEqual([d["key"] for d in dropped], ["ops.lob_models[0].products[0].unit_price"])
    self.assertIn("did not say", dropped[0]["why"])

  def test_a_zero_the_client_said_is_a_value(self):
    for words in ("No debt - zero.", "None, nothing owed.", "We don't have any - $0.", "no", "0"):
      kept, dropped = A.drop_unsaid_zeros({"financials.total_debt_outstanding": 0.0}, words)
      self.assertEqual(kept, {"financials.total_debt_outstanding": 0.0}, words)
      self.assertEqual(dropped, [], words)

  def test_a_figure_with_a_zero_in_it_is_not_a_zero(self):
    kept, dropped = A.drop_unsaid_zeros({"financials.monthly_rent_expense": 0.0}, "About 4,500 a month - 10 rooms.")
    self.assertEqual(dropped[0]["key"], "financials.monthly_rent_expense", "the 0 inside 4,500 and 10 is not the client saying zero")

  def test_only_stated_facts_are_judged(self):
    kept, dropped = A.drop_unsaid_zeros({"ops.utilization_note_count": 0, "financials.confidence": 0.0}, WORDS)
    self.assertEqual(dropped, [])
    self.assertEqual(len(kept), 2)

  def test_the_rule_runs_before_the_model_and_on_the_fail_open_path(self):
    def boom(**kw):
      raise RuntimeError("no network")
    with unittest.mock.patch.object(A, "enabled", return_value=True), \
         unittest.mock.patch.object(A, "_key", return_value="test-key"):
      # the store holds the 40 a week the client stated on an earlier turn (a restatement is not an invention)
      v = A.review(patch=dict(NORTHGATE_PATCH), user_text=WORDS, messages=[],
                   store={"lines": [{"product_name": "Office cleaning", "units_per_week_capacity": 40.0}]}, post=boom)
    self.assertTrue(v.timed_out or v.error)
    self.assertNotIn("ops.lob_models[0].products[0].unit_price", v.patch, "dropped even though the model never ran")
    self.assertEqual(len(v.dropped), 1)
    self.assertEqual(v.patch["ops.lob_models[0].products[0].units_per_week_capacity"], 40.0, "held in the store: stays")
    self.assertTrue(v.changed)




class AnUnsaidNumberIsTheSameClassAsAnUnsaidZero(unittest.TestCase):
  """Nick 2026-09-13 (Wren & Calloway 07a5b10f): the router wrote a unit
  price of 1 from 'About 33 a year per slot'; door A's model called it a
  placeholder the client never said and then rewrote it onto the line,
  because the number matcher let 1.0 pass within 0.5 of a stated 6 / 4.
  Now the matcher is tight (half a percent) and reads number words and
  percents; and when the model has judged the router's number wrong and
  its replacement is not in the client's words either, the key is dropped
  - neither number is written."""
  WREN_PATCH = {"ops.units_per_week_capacity": 3.8077, "ops.units_per_period_capacity": 6,
                "ops.operating_periods_per_year": 33, "ops.unit_price": 1,
                "ops.business_description_summary": "Wren & Calloway Millwork is a custom millwork shop."}
  WREN_WORDS = "About 33 a year per slot. They move quickly."

  @staticmethod
  def _post_with(rewrites):
    import json as _json
    def fake_post(**kw):
      class R:
        status_code = 200
        text = ""
        def json(self):
          return {"output": [{"content": [{"type": "output_text", "text": _json.dumps(
            {"allowed": [], "rewrites": rewrites, "asks": [], "hold_cleared": False})}]}]}
      return R()
    return fake_post

  WREN_STORE = {"financials": {"current_revenue": 5800000.0, "monthly_rent_expense": 34000.0},
                "lines": [{"product_name": "Historic interior repair", "unit_price": None, "units_per_period_capacity": 6.0,
                           "operating_periods_per_year": None}]}

  def test_the_one_dollar_placeholder_is_dropped_in_code_before_the_model(self):
    kept, dropped = A.drop_unsaid_numbers(self.WREN_PATCH, self.WREN_WORDS, self.WREN_STORE)
    self.assertEqual([d["key"] for d in dropped], ["ops.unit_price"])
    self.assertEqual(dropped[0]["action"], "dropped_unsaid_number")
    self.assertEqual(kept["ops.operating_periods_per_year"], 33, "said")
    self.assertEqual(kept["ops.units_per_period_capacity"], 6, "held in the store")
    self.assertAlmostEqual(kept["ops.units_per_week_capacity"], 3.8077, msg="6 held x 33 said / 52 - arithmetic on both")
    self.assertIn("ops.business_description_summary", kept, "text is never judged")

  def test_a_restated_store_figure_on_a_pick_turn_survives(self):
    kept, dropped = A.drop_unsaid_numbers({"coherence.option": "opt_1", "financials.monthly_rent_expense": 2600.0},
                                          "Option 1.", {"financials": {"monthly_rent_expense": 2600.0}})
    self.assertEqual(dropped, []); self.assertEqual(kept["financials.monthly_rent_expense"], 2600.0)

  def test_words_with_no_number_are_left_to_the_model(self):
    kept, dropped = A.drop_unsaid_numbers({"ops.operating_periods_per_year": 52}, "Year-round, every week.", {})
    self.assertEqual(dropped, []); self.assertEqual(kept["ops.operating_periods_per_year"], 52)

  def test_the_one_dollar_placeholder_is_dropped_neither_number_written(self):
    rw = [{"from_key": "ops.unit_price", "to_key": "ops.lob_models[0].products[2].unit_price", "value_json": "1.0",
           "client_words": "About 33 a year per slot", "receipt": "", "why": "an internal placeholder, not a price the client said"}]
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}):
      v = A.review(patch=dict(self.WREN_PATCH), user_text=self.WREN_WORDS, messages=[], store=self.WREN_STORE, post=self._post_with(rw))
    self.assertNotIn("ops.unit_price", v.patch)
    self.assertNotIn("ops.lob_models[0].products[2].unit_price", v.patch)
    self.assertEqual(v.patch["ops.operating_periods_per_year"], 33, "the stated turns stay")
    self.assertEqual(v.patch["ops.units_per_period_capacity"], 6, "a held value stays")
    self.assertTrue(any(d["action"] == "dropped_unsaid_number" and d["key"] == "ops.unit_price" for d in v.dropped))
    self.assertEqual(v.rewrites, [], "a rewrite to an unsaid number is refused")

  def test_a_router_number_the_client_did_say_survives_a_bad_rewrite(self):
    rw = [{"from_key": "financials.monthly_rent_expense", "to_key": "", "value_json": "2400",
           "client_words": "$2,600 a month for the office", "receipt": "", "why": "x"}]
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}):
      v = A.review(patch={"financials.monthly_rent_expense": 2600}, user_text="$2,600 a month for the office.",
                   messages=[], store={"financials": {}}, post=self._post_with(rw))
    self.assertEqual(v.patch, {"financials.monthly_rent_expense": 2600})
    self.assertEqual(v.dropped, [])

  def test_the_matcher_is_tight_and_reads_number_words_and_percents(self):
    self.assertFalse(A._value_in_words(1.0, "About 6 slots, 33 a year per slot"), "1.0 is not 6/4 any more")
    self.assertTrue(A._value_in_words(0.05, "Shampoo and supplies run about 5 percent of revenue."))
    self.assertTrue(A._value_in_words(7, "Seven of us, including me."))
    self.assertTrue(A._value_in_words(30, "about thirty months left"))
    self.assertTrue(A._value_in_words(14500, "About $14.5k a month"))
    self.assertTrue(A._value_in_words(28800, "$2,400 a month for the three vans"))
    self.assertTrue(A._value_in_words(12, "Twelve at the most."))
    self.assertFalse(A._value_in_words(485040, "It is about 308,000 for the fourteen of them."))

  def test_an_already_captured_entry_is_a_question_not_a_write(self):
    """Nick 2026-09-13: the judgment is a REQUIRED field the model fills for
    every numeric key; an entry holds the key back behind the question,
    whatever the model put in `allowed`."""
    import json as _json
    def fake_post(**kw):
      class R:
        status_code = 200
        text = ""
        def json(self):
          return {"output": [{"content": [{"type": "output_text", "text": _json.dumps({
            "allowed": [{"key": "financials.other_operating_expense", "value_json": "2500"}], "rewrites": [], "asks": [], "hold_cleared": False,
            "already_captured": [{"key": "financials.other_operating_expense", "items": "cleaning supplies",
                                  "captured_line": "direct costs (6% of revenue)",
                                  "question": "You told me cleaning supplies are inside the 6% direct costs - is the $2,500 besides those, or does it include them?"}]})}]}]}
      return R()
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}):
      v = A.review(patch={"financials.other_operating_expense": 2500.0},
                   user_text="About $2,500 a month - cleaning supplies, van fuel, insurance, software and phones.",
                   messages=[], store={"financials": {"cogs_percent_of_revenue": 0.06}}, post=fake_post)
    self.assertNotIn("financials.other_operating_expense", v.patch, "a question, not a write")
    self.assertEqual(len(v.asks), 1)
    self.assertIn("cleaning supplies", v.asks[0]["question"])
    self.assertIn("already_captured", A.SCHEMA["required"])

  def test_compound_number_words_are_one_value(self):
    """R23 (CW-028 #4): 'one hundred and eighty-five' is 185, never the 85 fragment."""
    self.assertIn(185.0, A.numbers_in_words("We can do one hundred and eighty-five a week."))
    self.assertIn(36.0, A.numbers_in_words("about thirty-six months left"))
    self.assertIn(25.0, A.numbers_in_words("twenty five at the most"))
    self.assertIn(150000.0, A.numbers_in_words("one hundred fifty thousand a year for the five"))
    kept, dropped = A.drop_unsaid_numbers({"ops.lob_models[0].products[0].units_per_week_capacity": 185.0},
                                          "One hundred and eighty-five a week, not 100.", {})
    self.assertEqual(dropped, []); self.assertEqual(kept["ops.lob_models[0].products[0].units_per_week_capacity"], 185.0)

  def test_the_instruction_carries_the_already_captured_move(self):
    self.assertIn("4. ALREADY CAPTURED", A.SYSTEM)
    self.assertIn("count them twice", A.SYSTEM)
    self.assertIn("That is a question, not a write", A.SYSTEM)


if __name__ == "__main__":
  unittest.main()
