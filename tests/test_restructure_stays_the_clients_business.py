"""The restructure stays the client's business (Nick 2026-09-11).

"A client can be handed a plan for a business they didn't describe, with three
lines they never mentioned, and nothing tells them. That's not a restructure,
that's a different company." Five rules:
  1. new lines only if the client named them;
  2. no dropping a client's line without asking;
  3. price and volume ceilings tied to market data;
  4. a failed review blocks the design, never approves it;
  5. a restructured plan is always labelled as one.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)
_EXTRA = os.path.join(ROOT, "python", "client_intake_and_finmo")
if _EXTRA not in sys.path:
  sys.path.append(_EXTRA)

import api_handlers.intake_consult as IC  # noqa: E402
from client_intake_and_finmo.post_intake_restructure import client_bounds as CB  # noqa: E402
from client_intake_and_finmo.post_intake_restructure import constraint_author as CA  # noqa: E402

CLIENT = [
  "We sell loose-leaf tea blends online and at two farmers markets.",
  "At some point we'd like to start a wholesale program for local cafes, maybe next year.",
]
BOUNDS = {
  "feasible_region_exists": True,
  "existing_lines": [
    {"lob": "Retail", "product": "Loose-leaf blends", "price_multiplier_max": 2.4,
     "volume_multiplier_max": 3.0, "can_drop": False, "rationale": "core"},
    {"lob": "Markets", "product": "Farmers market stall", "price_multiplier_max": 1.3,
     "volume_multiplier_max": 1.5, "can_drop": True, "rationale": "low margin"},
  ],
  "new_line_candidates": [
    {"lob": "Wholesale", "product": "Cafe wholesale program", "unit_price": 18.0,
     "q11_quarterly_revenue_max": 40000.0,
     "client_quote": "we'd like to start a wholesale program for local cafes"},
    {"lob": "Subscriptions", "product": "Monthly tea subscription box", "unit_price": 30.0,
     "q11_quarterly_revenue_max": 60000.0,
     "client_quote": "customers would love a monthly subscription box"},
    {"lob": "Events", "product": "Tea tasting events", "unit_price": 45.0,
     "q11_quarterly_revenue_max": 15000.0, "client_quote": ""},
  ],
}


def _bound(market=None):
  return CB.bound_to_the_clients_business(BOUNDS, client_statements=CLIENT, market_ceiling=market)


class RuleOneNewLinesOnlyIfTheClientNamedThem(unittest.TestCase):
  def test_a_real_quote_naming_the_line_verifies(self):
    ok, why = CB.quote_is_the_clients(
      "we'd like to start a wholesale program for local cafes", CLIENT, "Wholesale Cafe wholesale program")
    self.assertTrue(ok, why)

  def test_words_the_client_never_typed_are_not_a_quote(self):
    ok, why = CB.quote_is_the_clients(
      "customers would love a monthly subscription box", CLIENT, "Monthly tea subscription box")
    self.assertFalse(ok)
    self.assertEqual(why, "quote_not_in_the_clients_words")

  def test_no_quote_no_line(self):
    self.assertEqual(CB.quote_is_the_clients("", CLIENT, "Tea tasting events")[1], "no_client_quote")

  def test_a_real_quote_about_something_else_does_not_name_the_line(self):
    ok, why = CB.quote_is_the_clients(
      "We sell loose-leaf tea blends online", CLIENT, "Cafe wholesale program")
    self.assertFalse(ok)
    self.assertEqual(why, "quote_does_not_name_the_line")

  def test_unnamed_lines_never_reach_the_search(self):
    b = _bound(market=lambda entry, kind: 20000.0)
    names = [nl["product"] for nl in b["new_line_candidates"]]
    self.assertEqual(names, ["Cafe wholesale program"])
    dropped = {d["name"]: d["reason"] for d in b["client_bounds"]["new_lines_dropped"]}
    self.assertEqual(dropped["Subscriptions Monthly tea subscription box"], "quote_not_in_the_clients_words")
    self.assertEqual(dropped["Events Tea tasting events"], "no_client_quote")


class RuleTwoNoDroppingWithoutAsking(unittest.TestCase):
  def test_no_line_can_be_dropped_and_the_proposal_is_kept_as_a_question(self):
    b = _bound()
    self.assertFalse(any(l["can_drop"] for l in b["existing_lines"]))
    self.assertEqual([d["line"] for d in b["client_bounds"]["drops_proposed"]],
                     ["Markets/Farmers market stall"])


class RuleThreeCeilingsTiedToMarketData(unittest.TestCase):
  def test_without_market_data_there_is_no_headroom(self):
    b = _bound()
    for line in b["existing_lines"]:
      self.assertEqual(line["price_multiplier_max"], 1.0)
      self.assertEqual(line["volume_multiplier_max"], 1.0)
    self.assertTrue(all(c["source"] == "no_market_data" for c in b["client_bounds"]["price_capped"]))

  def test_without_market_data_even_a_client_named_line_is_not_sized(self):
    b = _bound()
    self.assertEqual(b["new_line_candidates"], [])
    reasons = {d["reason"] for d in b["client_bounds"]["new_lines_dropped"]}
    self.assertIn("no_market_data", reasons)

  def test_a_market_figure_caps_the_judgment_and_never_raises_it(self):
    b = _bound(market=lambda entry, kind: {"price": 1.2, "volume": 5.0}.get(kind, 20000.0))
    core = b["existing_lines"][0]
    self.assertEqual(core["price_multiplier_max"], 1.2)   # market 1.2 < judged 2.4
    self.assertEqual(core["volume_multiplier_max"], 3.0)  # judged 3.0 < market 5.0
    self.assertEqual(b["new_line_candidates"][0]["q11_quarterly_revenue_max"], 20000.0)

  def test_applying_twice_changes_nothing_and_keeps_the_record(self):
    once = _bound()
    twice = CB.bound_to_the_clients_business(once, client_statements=CLIENT)
    self.assertEqual(once, twice)


class RuleFourAFailedReviewBlocks(unittest.TestCase):
  def test_no_review_is_not_an_approval(self):
    src = inspect.getsource(IC.post_intake_consult_system_run_handler)
    self.assertIn("if _rs_review is None:", src)
    self.assertIn('_rs_blocked_reason = "review_unavailable"', src)
    self.assertNotIn("if _rs_review is not None and not bool(_rs_review.get(\"approved\")):", src)


class RuleFiveAlwaysLabelled(unittest.TestCase):
  SRC = inspect.getsource(IC.post_intake_consult_system_run_handler)

  def test_the_sentence_is_gone(self):
    self.assertNotIn("simply IS the forecast", self.SRC)

  def test_the_workbook_the_email_and_the_writing_trigger_all_read_the_mark(self):
    self.assertIn("_RS_LABEL", self.SRC)
    self.assertIn("RESTRUCTURED PLAN, NOT THE BUSINESS AS DESCRIBED", self.SRC)
    self.assertIn("WRITING_PHASE_WITHHELD", self.SRC)
    guard = self.SRC.find("if _rs_delivered_restructure:\n        # ALWAYS LABELLED (Nick 2026-09-11): the written plan")
    trigger = self.SRC.find("_auto_trigger_writing_phase(app, diagnostic_payload, result_draft_id)")
    self.assertGreater(guard, 0)
    self.assertGreater(trigger, guard)

  def test_the_label_lists_every_change(self):
    b = _bound(market=lambda entry, kind: 20000.0 if kind == "new_line" else None)
    design = {
      "team": {"annual_payroll": 380000.0},
      "facility": {"quarterly_rent_target": 9000.0},
      "cost_structure": {"cogs_percent_of_revenue": 0.31},
      "revenue_mix": {"lines": [], "new_lines": [{"lob": "Wholesale", "product": "Cafe wholesale program"}]},
    }
    text = CB.restructure_label_text(design, b["client_bounds"], stated={"payroll_total_year1": 450000.0})
    for part in ("NOT THE BUSINESS AS DESCRIBED", "$380,000", "as described: $450,000",
                 "Cafe wholesale program", "wholesale program for local cafes",
                 "NOT applied", "Farmers market stall", "No written plan"):
      self.assertIn(part, text)


class TheIntakeWalkIsUntouchedTests(unittest.TestCase):
  def test_the_default_tool_has_no_quote_field(self):
    items = CA._submit_tool(False)["function"]["parameters"]["properties"]["new_line_candidates"]["items"]
    self.assertNotIn("client_quote", items["properties"])
    self.assertIs(CA._submit_tool(False), CA._SUBMIT_TOOL)

  def test_the_restructure_tool_requires_the_quote(self):
    items = CA._submit_tool(True)["function"]["parameters"]["properties"]["new_line_candidates"]["items"]
    self.assertIn("client_quote", items["required"])

  def test_the_clients_words_only_appear_when_given(self):
    kw = dict(compact={}, stated_facts={}, current_structure={})
    self.assertNotIn("CLIENT'S OWN WORDS", CA._build_user_prompt(**kw))
    self.assertIn("CLIENT'S OWN WORDS", CA._build_user_prompt(**kw, client_statements=CLIENT))

  def test_the_validator_carries_the_quote(self):
    v = CA.validate_restructure_bounds(bounds={
      "feasible_region_exists": True, "existing_lines": [],
      "new_line_candidates": [{"lob": "W", "product": "Cafe wholesale", "unit_price": 10,
                               "q11_quarterly_revenue_max": 100, "client_quote": "a quote"}],
      "team": {"min_annual_payroll": 1}, "reality_constraints": {
        "real_market": "x", "real_physics": "x", "still_this_business": "x", "lender_defensible": "x"},
    }, stated_owner_annual_wage=0.0)
    self.assertEqual(v["new_line_candidates"][0]["client_quote"], "a quote")

  def test_the_restructure_path_uses_the_client_bounds_after_every_bounds_change(self):
    src = inspect.getsource(IC.post_intake_consult_system_run_handler)
    self.assertIn("require_client_quote=True", src)
    self.assertGreaterEqual(src.count("_rs_bound_to_client("), 2)


if __name__ == "__main__":
  unittest.main()
