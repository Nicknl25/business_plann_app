"""A FACT ABOUT THE BUSINESS, NOT PERMISSION (Nick 2026-09-13, Sorrel & Dunne
691a4763 and Wren & Calloway 07a5b10f).

"Not by contract, but I do not want to raise them in year one" became
"Prices can move if the numbers call for it"; the client's correction ("that
is not quite what I said - please record that as a constraint") was followed
by a marketing question; "the commercial fixture contracts are bid and cannot
be raised" - one line of three - collapsed into a business-wide false.

TAKE WHAT YOU ASKED FOR. NOTHING ELSE GOES IN THAT FIELD. Anything beyond the
yes/no is recorded in the client's words as a stated limit; the
acknowledgement reads back what was HELD; a per-line contracted price holds
that line in the solve; a correction always sends the reply to door B's
model with the third question.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from api_handlers import intake_consult as H  # noqa: E402
from client_intake_and_finmo import intent_router as IR  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_guard import door_b as B  # noqa: E402

SORREL = "Not contractually, no. But I do not want to raise them in year one. We are building accounts and I would rather grow the volume than push the price up."
WREN = ("It depends on the line. The commercial fixture contracts are bid and priced, so those cannot be raised. "
        "The cabinetry I can raise somewhat, builders expect it. The refinishing work is small enough that it does not much matter.")
SORREL_TEAM = "No ceiling on hiring - if the accounts come we will staff for them. But I will not cut the production team."


class TheLimitIsRecordedInTheClientsWords(unittest.TestCase):
  def test_sorrels_year_one_decision_lands_beside_the_boolean(self):
    out = H._commitment_answer_door("price_commitment", SORREL, {})
    self.assertIs(out["financials.price_contracted"], False)
    limits = out["financials.stated_limits"]
    self.assertEqual(len(limits), 1, limits)
    self.assertEqual(limits[0]["topic"], "pricing"); self.assertFalse(limits[0]["contractual"])
    self.assertIn("year one", limits[0]["words"])

  def test_wrens_contracted_line_is_a_contractual_limit(self):
    out = H._commitment_answer_door("price_commitment", WREN, {})
    limits = out["financials.stated_limits"]
    self.assertTrue(any(l["contractual"] and "cannot be raised" in l["words"] for l in limits), limits)

  def test_the_team_floor_beside_no_ceiling_is_kept(self):
    out = H._commitment_answer_door("staffing_ceiling", SORREL_TEAM, {})
    self.assertEqual(out["financials.staffing_ceiling"], 0)
    limits = out["financials.stated_limits"]
    self.assertEqual(limits[0]["topic"], "team"); self.assertIn("will not cut", limits[0]["words"])

  def test_a_plain_yes_no_records_no_limit(self):
    out = H._commitment_answer_door("price_commitment", "No contracts - we set our own prices.", {})
    self.assertNotIn("financials.stated_limits", out)

  def test_the_router_landing_stands_and_limits_merge_once(self):
    out = H._commitment_answer_door("price_commitment", SORREL, {"financials.stated_limits": [{"topic": "pricing", "scope": "business", "words": "x", "contractual": False}]})
    self.assertEqual(out["financials.stated_limits"][0]["words"], "x", "the router's record stands")
    merged = H._merge_stated_limits([{"topic": "pricing", "scope": "business", "words": "I do not want to raise them in year one.", "contractual": False}],
                                    [{"topic": "pricing", "scope": "business", "words": "i do not want to raise them in year one.", "contractual": False},
                                     {"topic": "team", "scope": "business", "words": "I will not cut the production team.", "contractual": False}])
    self.assertEqual([m["topic"] for m in merged], ["pricing", "team"])

  def test_the_router_knows_the_field_and_the_rule(self):
    src = inspect.getsource(IR)
    self.assertGreaterEqual(src.count('"stated_limits"'), 2, "schema + allowlist")
    self.assertIn("TAKE WHAT YOU ASKED FOR. NOTHING ELSE GOES IN THAT FIELD", src)
    self.assertIn("A CORRECTION", src)
    self.assertIn("NOT PERMISSION", src)


class TheAcknowledgementSaysWhatWasHeld(unittest.TestCase):
  def _ack(self, stage, fin):
    return H._build_financials_stage_acknowledgement(stage_name=stage, financials_json=fin)

  def test_the_three_templates_are_gone(self):
    outs = [self._ack("lease_commitment", {"lease_signed": False}),
            self._ack("price_commitment", {"price_contracted": False}),
            self._ack("staffing_ceiling", {"staffing_ceiling": 0}),
            self._ack("price_commitment", {"price_contracted": False, "stated_limits": [{"topic": "pricing", "scope": "business", "words": "not in year one", "contractual": False}]})]
    for a in outs:
      for gone in ("we can look at", "can move if the numbers", "can hire as the work calls", "if the numbers call for it"):
        self.assertNotIn(gone, a, a)

  def test_a_decision_is_read_back_in_the_clients_words(self):
    fin = {"price_contracted": False, "stated_limits": [{"topic": "pricing", "scope": "business",
                                                          "words": "I do not want to raise them in year one.", "contractual": False}]}
    a = self._ack("price_commitment", fin)
    self.assertIn("not fixed by contract", a)
    self.assertIn("I do not want to raise them in year one", a)
    self.assertIn("hold to that", a)
    self.assertNotIn("can move", a)

  def test_a_contracted_line_is_read_back_as_held(self):
    fin = {"price_contracted": False, "stated_limits": [{"topic": "pricing", "scope": "Commercial store fixtures and casework",
                                                          "words": "the commercial fixture contracts are bid and priced, so those cannot be raised", "contractual": True}]}
    a = self._ack("price_commitment", fin)
    self.assertIn("Commercial store fixtures and casework is under contract", a)
    self.assertIn("leave that price alone", a)

  def test_facts_read_back_as_facts(self):
    self.assertEqual(self._ack("lease_commitment", {"lease_signed": False}), "Understood - nothing signed on the space, month to month.")
    self.assertEqual(self._ack("price_commitment", {"price_contracted": False}), "Understood - your prices are not fixed by contract.")
    self.assertEqual(self._ack("staffing_ceiling", {"staffing_ceiling": 0}), "Understood - no ceiling on headcount.")
    a = self._ack("staffing_ceiling", {"staffing_ceiling": 0, "stated_limits": [{"topic": "team", "scope": "business", "words": "I will not cut the production team.", "contractual": False}]})
    self.assertIn("I will not cut the production team", a)


class TheLimitTravelsWithTheHandoverAndHoldsTheLine(unittest.TestCase):
  def test_the_constraints_record_carries_the_limits(self):
    fin = {"stated_limits": [{"topic": "pricing", "scope": "business", "words": "not in year one", "contractual": False}]}
    rec = S._constraints_record({}, fin)
    self.assertEqual(rec["stated_limits"][0]["words"], "not in year one")

  def test_a_contracted_line_holds_its_price_in_the_solve(self):
    fin = {"stated_limits": [{"topic": "pricing", "scope": "Commercial store fixtures and casework", "words": "bid and priced", "contractual": True},
                             {"topic": "pricing", "scope": "business", "words": "not in year one", "contractual": False}]}
    self.assertEqual(S._contracted_lines(fin), {"commercial store fixtures and casework"})
    src = inspect.getsource(S._path_box_for)
    self.assertIn("_contracted_lines(financials_json)", src)
    self.assertIn("return 1.0", src)
    self.assertIn("effective_pmax=_pmax", src)


class DoorBAsksTheThirdQuestion(unittest.TestCase):
  def _post(self, calls):
    def fake_post(**kw):
      calls.append(kw.get("payload"))
      class R:
        status_code = 200
        text = ""
        def json(self):
          return {"output": [{"content": [{"type": "output_text", "text": '{"reply": "", "changed": false, "why": "fine"}'}]}]}
      return R()
    return fake_post

  def test_a_correction_always_reaches_the_model_with_the_clients_words(self):
    calls = []
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}):
      v = B.review(text="Got it. I'll use a marketing budget of $210,000 a year.", store={"financials": {"marketing_total_year1": 210000.0}},
                   user_text="That is not quite what I said. Contractually they can move, but I do not want them moved in year one - please record that as a constraint, not as permission. Marketing will be about 210,000 a year.",
                   post=self._post(calls))
    self.assertTrue(v.ran_model, "no unexplained figure, but a correction: the model is consulted")
    self.assertTrue(v.correction.startswith("That is not quite what I said"))
    body = calls[0]["input"][1]["content"] if isinstance(calls[0]["input"][1]["content"], str) else str(calls[0]["input"][1]["content"])
    self.assertIn("correction", body)
    self.assertIn("not quite what I said", body)

  def test_without_a_correction_a_clean_reply_needs_no_model(self):
    calls = []
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}):
      v = B.review(text="Got it. I'll use a marketing budget of $210,000 a year.", store={"financials": {"marketing_total_year1": 210000.0}},
                   user_text="Marketing will be about 210,000 a year.", post=self._post(calls))
    self.assertFalse(v.ran_model); self.assertEqual(v.correction, ""); self.assertEqual(calls, [])

  def test_the_instruction_carries_the_third_question(self):
    self.assertIn("THE THIRD QUESTION", B.SYSTEM)
    self.assertIn("Never restate an owner's limit as permission", B.SYSTEM)


if __name__ == "__main__":
  unittest.main()
