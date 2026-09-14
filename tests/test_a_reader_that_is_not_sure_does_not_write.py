"""A reader that is not sure does not write; an unanswered question is not an answer;
a figure she stated is not dropped because its stage has not come up yet.

Nick ruled 2026-09-14, on Green Meadow e82068806f5a4d978ededf5121bf8b05:
  - message 105, "I expect most current customers to stay ... the utilization might
    be higher than 70%", was read by the retention parser as 70% of customers kept,
    and 63,000 x 0.7 = 44,100 cut the revenue. Not a tighter pattern: R3 - when it
    cannot be certain what a percentage refers to, it writes nothing and the app asks.
  - message 57 (costs and marketing) was answered "Understood - your prices are not
    fixed by contract", the same question was asked again, and her marketing figure
    ("closer to 4% ... around $28,000 a year. Please adjust accordingly.") was dropped.

These pins state, for any shape of the case:
  - a retention answer is certain only when her message carries no figure beyond the
    answer's own; her message 105 is not certain; a clean answer is;
  - an uncertain answer leaves the frame open and the next question names the doubt
    in her figure instead of repeating itself;
  - no commitment acknowledgement is spoken for a field that did not land;
  - a later stage's field lands when its value is a figure she stated, and closes that
    stage; a value she did not state stays out.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))

MSG_105 = ("The $63,000 annual revenue figure is correct according to our records. We have stable client retention, "
           "so I expect most current customers to stay. Given that, I believe the utilization might be higher than "
           "70%, or perhaps we have some additional revenue streams not reflected in the volume x price calculation. "
           "For now, please keep the $63,000 revenue and $60 price per visit, and you may update utilization to "
           "reconcile those numbers.")
MSG_57 = ("Actually, our materials cost is $63,000 annually, as mentioned earlier. Regarding marketing, 8% sounds a bit "
          "high for us; we typically spend closer to 4% of revenue on marketing efforts, so around $28,000 a year. "
          "Please adjust accordingly.")


class ARetentionReaderThatIsNotSureDoesNotWrite(unittest.TestCase):
  def setUp(self):
    from api_handlers import intake_consult as ic  # type: ignore
    self.ic = ic

  def test_certain_only_when_no_other_figure_is_in_her_message(self):
    ic = self.ic
    uncertain = (MSG_105,
                 "Most of them will stay, and utilization is about 70% on 40 visits a week.",
                 "We'd keep 90% of customers at $60 a visit.",
                 "I think we keep 8 of my 10 clients, and 3 new ones a month.")
    certain = ("We'd keep about 90% of our customers.", "Call it 90% staying.", "Keep 30 of my 34.",
               "We'd lose one in ten.", "Most would stay - maybe 0.85 of them.")
    for m in uncertain:
      ans = ic._parse_retention_answer(m)
      self.assertIsNotNone(ans, "the parser is unchanged: it still finds an answer in %r" % m)
      self.assertFalse(ic._retention_answer_is_certain(m, ans), m)
    for m in certain:
      ans = ic._parse_retention_answer(m)
      self.assertIsNotNone(ans, m)
      self.assertTrue(ic._retention_answer_is_certain(m, ans), m)
    self.assertFalse(ic._retention_answer_is_certain("anything", None))

  def test_the_resolver_writes_nothing_on_an_uncertain_answer(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    at = src.index("_ret_ans = _parse_retention_answer(str(message or \"\"))")
    block = src[at:src.index("RETENTION_FRAME_RESOLVE_FAILED", at)]
    guard = block.index("not _retention_answer_is_certain(")
    apply = block.index("apply_retention_answer(")
    self.assertLess(guard, apply, "the certainty check must decide before anything is applied")
    self.assertIn("_ret_ans = None", block[guard:apply])
    self.assertIn('"uncertain_answer"', block[guard:apply])
    # the app asks on the SAME turn, whatever path builds the reply
    self.assertIn("uncertain_retention_question(_ret_state)", block[guard:apply])
    self.assertIn("_guard_questions", block[guard:apply])

  def test_the_question_names_the_doubt_in_her_figure(self):
    from client_intake_and_finmo.intake_coherence import section as sec  # type: ignore
    base = {"retention_pending": {"prices": [{"product": "veterinary visit", "to": 60.0}], "retained_used": 1.0}}
    plain = sec._pending_question_hold(base, "")
    self.assertIn("do you expect your current customers to stay", plain)
    self.assertEqual(sec.uncertain_retention_question(base), "", "no refused answer, no named question")
    self.assertEqual(sec.uncertain_retention_question({}), "")
    for words in ("70%", "8 of 10", "0.85"):
      st = {"retention_pending": dict(base["retention_pending"], uncertain_answer={"words": words})}
      self.assertIn(words, sec.uncertain_retention_question(st))
      q = sec._pending_question_hold(st, "")
      self.assertIn("I couldn't be sure what the %s in your last message referred to" % words, q)
      self.assertIn("haven't changed anything", q)
      self.assertNotIn("Quick check on the new price", q, "the doubt is named, the old question is not repeated")


class AnUnansweredCommitmentIsNotAnAnswer(unittest.TestCase):
  def test_no_acknowledgement_for_a_field_that_did_not_land(self):
    from api_handlers import intake_consult as ic  # type: ignore
    for stage, field, yes, no in (("price_commitment", "price_contracted", True, False),
                                  ("lease_commitment", "lease_signed", True, False),
                                  ("staffing_ceiling", "staffing_ceiling", 12, 0)):
      for fin in ({}, {"current_revenue": 700000.0}, {field: None}):
        self.assertEqual(ic._build_financials_stage_acknowledgement(stage_name=stage, financials_json=fin), "",
                         (stage, fin))
        got = ic._build_financials_stage_acknowledgement_first(
          "Got it - I'll dial back the marketing line to about $28,000.", stage_name=stage, financials_json=fin,
          user_message=MSG_57)
        self.assertNotIn("contract", got.lower()); self.assertNotIn("ceiling", got.lower()); self.assertNotIn("lease", got.lower())
      for value in (yes, no):
        self.assertTrue(ic._build_financials_stage_acknowledgement(stage_name=stage, financials_json={field: value}),
                        (stage, value))


class AFigureSheStatedForALaterStageLands(unittest.TestCase):
  def setUp(self):
    from api_handlers import intake_consult as ic  # type: ignore
    self.ic = ic
    self.fin = {"current_revenue": 700000.0, "_financials_revenue_intro_done": True, "current_cogs": 63000.0,
                "cogs_total_year1": 63000.0, "cogs_percent_of_revenue": 0.09, "cogs_basis": "dollars"}

  def norm(self, patch, message, stage="price_commitment", report=None):
    return self.ic._normalize_financials_router_patch(
      patch=patch, active_stage=stage, financials_json=dict(self.fin),
      financials_year1_json={"company_revenue_total_year1": 700000.0},
      last_assistant="Are your prices fixed by contract for the plan period, or can you move them?",
      user_message=message, report=report)

  def test_her_message_57_lands_marketing_and_closes_its_stage(self):
    router = {"cogs_total_year1": 63000, "current_cogs": 63000, "cogs_percent_of_revenue": 0.09,
              "marketing_total_year1": 28000, "marketing_percent_of_revenue": 0.04}
    out = self.norm(router, MSG_57)
    self.assertIsNotNone(out)
    self.assertEqual(out.get("marketing_total_year1"), 28000)
    self.assertAlmostEqual(out.get("marketing_percent_of_revenue"), 0.04)
    self.assertTrue(out.get("_financials_marketing_stage_done"), "her figure closes the stage - never asked again")
    self.assertIsNone(out.get("price_contracted"), "and nothing is invented for the question she did not answer")

  def test_a_later_stage_value_she_did_not_state_stays_out(self):
    for patch, message in (({"marketing_total_year1": 50000}, MSG_57),
                           ({"marketing_percent_of_revenue": 0.08}, "We keep prices flexible."),
                           ({"monthly_rent_expense": 3000}, "No, nothing is fixed by contract."),
                           ({"marketing_total_year1": 28000}, "No, prices can move.")):
      out = self.norm(dict(patch, price_contracted=False), message)
      for k in patch:
        self.assertNotEqual((out or {}).get(k), patch[k], "a value she did not state landed: %r" % ((patch, message),))

  def test_only_a_later_stage_is_admitted(self):
    ic = self.ic
    self.assertTrue(ic._stated_for_later_stage("marketing_total_year1", 28000, "price_commitment", MSG_57))
    self.assertTrue(ic._stated_for_later_stage("marketing_percent_of_revenue", 0.04, "price_commitment", MSG_57))
    self.assertFalse(ic._stated_for_later_stage("marketing_total_year1", 28000, "", MSG_57), "completed state: not this door")
    self.assertFalse(ic._stated_for_later_stage("current_revenue", 63000, "price_commitment", MSG_57), "an EARLIER stage")
    self.assertFalse(ic._stated_for_later_stage("marketing_total_year1", 29000.0 * 1.5, "price_commitment", MSG_57))


if __name__ == "__main__":
  unittest.main(verbosity=2)
