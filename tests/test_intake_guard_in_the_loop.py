"""THE INTAKE GUARD - IN THE LOOP, NOT AFTER IT (Nick 2026-09-12).

"It sees the patch before it lands and the reply before it goes out. If a
figure is going into the wrong field, it corrects it before the write
happens. If GPT is about to tell the client something that contradicts
the store, it stops it... Real authority: it can rewrite the patch, it can
hold the reply, it can make GPT ask again. Its only limit is that it
works with figures the client actually stated - it never invents one."

Door A and door B with a fake model; the audit; fail-open on a timeout.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

os.environ.setdefault("OPENAI_API_KEY", "test-key")
from client_intake_and_finmo.intake_guard import door_a as A  # noqa: E402
from client_intake_and_finmo.intake_guard import door_b as B  # noqa: E402
from client_intake_and_finmo.intake_guard import audit as AU  # noqa: E402


def _resp(payload_obj):
  class _R:
    status_code = 200
    text = ""
    def json(self):
      return {"output": [{"content": [{"type": "output_text", "text": json.dumps(payload_obj)}]}]}
  return _R()


LEASE_WORDS = "The three vans are leased - about $2,400 a month for the three, and that's inside the $14,500 of other bills I gave you."
STORE = {"financials": {"monthly_rent_expense": 2600.0, "other_operating_expense": 14500.0, "current_revenue": 490000.0},
         "ops": {"lob_models": [{"lob_name": "L", "products": [{"product_name": "Recurring office cleaning", "unit_price": 1200.0}]}]},
         "people": {"people": [{"full_name": "Luis Ortega", "role_title": "crew supervisor", "annual_wage": 54000.0}]}}


class DoorA(unittest.TestCase):
  def test_the_van_lease_never_reaches_rent(self):
    proposed = {"financials.monthly_rent_expense": 2400.0}
    reply = {"allowed": [], "rewrites": [{"from_key": "financials.monthly_rent_expense", "to_key": "financials.monthly_rent_expense",
                                          "value_json": "2600", "client_words": LEASE_WORDS + " rent is $2,600 a month.",
                                          "receipt": "You told me the $2,400 is the van lease inside your other bills, so I've left rent at $2,600.",
                                          "why": "a lease payment is not rent"}],
             "asks": [], "hold_cleared": False}
    v = A.review(patch=proposed, user_text=LEASE_WORDS, messages=[{"role": "user", "content": LEASE_WORDS}], store=STORE,
                 focus="financials", post=lambda **kw: _resp(reply))
    self.assertTrue(v.ran)
    self.assertEqual(v.patch, {}, "the rent key is dropped (2,600 is what the store already holds): rent stays what the client said")
    self.assertIn("van lease", v.receipts[0])
    self.assertTrue(v.changed)

  def test_a_rewrite_may_only_carry_a_figure_the_client_stated(self):
    proposed = {"financials.monthly_rent_expense": 2400.0}
    reply = {"allowed": [{"key": "financials.monthly_rent_expense", "value_json": "3100"}],
             "rewrites": [{"from_key": "financials.monthly_rent_expense", "to_key": "financials.monthly_rent_expense",
                           "value_json": "3100", "client_words": LEASE_WORDS, "receipt": "r", "why": "w"}],
             "asks": [], "hold_cleared": False}
    v = A.review(patch=proposed, user_text=LEASE_WORDS, messages=[], store=STORE, post=lambda **kw: _resp(reply))
    self.assertEqual(v.patch, proposed, "3,100 is nowhere in the client's words: the router's value stands")
    self.assertEqual(v.rewrites, [])

  def test_an_ask_holds_the_field_back(self):
    proposed = {"financials.cash_on_hand": 1100.0}
    reply = {"allowed": [], "rewrites": [], "hold_cleared": False,
             "asks": [{"key": "financials.cash_on_hand", "client_words": "About $1,100 a year.",
                       "question": "Just to be sure - is $1,100 a year the loan principal, or the cash the business has on hand today?",
                       "why": "the figure answers the previous question"}]}
    v = A.review(patch=proposed, user_text="About $1,100 a year.", messages=[], store=STORE, post=lambda **kw: _resp(reply))
    self.assertEqual(v.patch, {})
    self.assertEqual(len(v.questions), 1)

  def test_the_walks_choices_pass_through_and_a_silent_value_change_is_refused(self):
    proposed = {"coherence.option": "costs_gna_d50", "financials.monthly_rent_expense": 2600.0}
    reply = {"allowed": [{"key": "coherence.option", "value_json": json.dumps("costs_gna_d50")},
                         {"key": "financials.monthly_rent_expense", "value_json": "2000"},
                         {"key": "financials.marketing_total_year1", "value_json": "6000"}],
             "rewrites": [], "asks": [], "hold_cleared": False}
    v = A.review(patch=proposed, user_text="Option 1.", messages=[], store=STORE, post=lambda **kw: _resp(reply))
    self.assertEqual(v.patch, proposed, "no rewrite entry: no change; no key the router did not propose")

  def test_timeout_fails_open_loudly(self):
    def _boom(**kw):
      raise TimeoutError("deadline")
    proposed = {"financials.monthly_rent_expense": 2400.0}
    with self.assertLogs("client_intake_and_finmo.intake_guard.door_a", level="ERROR") as cm:
      v = A.review(patch=proposed, user_text="x", messages=[], store=STORE, post=_boom)
    self.assertEqual(v.patch, proposed)
    self.assertTrue(v.timed_out)
    self.assertTrue(any("INTAKE_GUARD_A_TIMEOUT" in m for m in cm.output))


class DoorB(unittest.TestCase):
  def test_a_claimed_figure_the_store_does_not_hold_is_a_disagreement(self):
    dis = B.find_disagreements("Got it - I'll use $3,400 for monthly rent.", STORE)
    self.assertEqual([d["kind"] for d in dis], ["claimed_figure_not_in_store"])
    self.assertEqual(B.find_disagreements("Got it - I'll use $2,600 for monthly rent.", STORE), [])

  def test_nothing_moved_against_lever_writes_is_a_disagreement(self):
    writes = {"current_revenue": {"from": 490000.0, "to": 562030.0}}
    dis = B.find_disagreements("Nothing you told me was moved by the levers - every number you set is yours.", STORE, writes)
    self.assertEqual([d["kind"] for d in dis], ["nothing_moved_but_writes"])

  def test_the_reply_is_rewritten_from_the_store_and_never_gains_a_figure(self):
    text = "Got it - I'll use $3,400 for monthly rent."
    good = {"reply": "Got it - I'll use $2,600 for monthly rent.", "changed": True, "why": "the store holds 2,600"}
    v = B.review(text=text, store=STORE, post=lambda **kw: _resp(good))
    self.assertTrue(v.rewritten); self.assertIn("$2,600", v.text)
    bad = {"reply": "Got it - I'll use $9,999 for monthly rent.", "changed": True, "why": "x"}
    v2 = B.review(text=text, store=STORE, post=lambda **kw: _resp(bad))
    self.assertFalse(v2.rewritten); self.assertEqual(v2.text, text); self.assertEqual(v2.error, "rewrite_introduced_figure")

  def test_door_a_receipts_and_questions_reach_the_client(self):
    v = B.review(text="Got it - I'll use $2,600 for monthly rent.", store=STORE,
                 receipts=["You told me the $2,400 is the van lease inside your other bills, so I've left rent at $2,600."],
                 questions=["Is the $1,100 a year the loan principal, or cash on hand?"])
    self.assertIn("van lease", v.text); self.assertIn("cash on hand?", v.text)
    self.assertEqual(len(v.appended), 2)

  def test_timeout_fails_open_loudly(self):
    def _boom(**kw):
      raise TimeoutError("deadline")
    text = "Got it - I'll use $3,400 for monthly rent."
    with self.assertLogs("client_intake_and_finmo.intake_guard.door_b", level="ERROR") as cm:
      v = B.review(text=text, store=STORE, post=_boom)
    self.assertEqual(v.text, text); self.assertTrue(v.timed_out)
    self.assertTrue(any("INTAKE_GUARD_B_TIMEOUT" in m for m in cm.output))


class TheAuditTrail(unittest.TestCase):
  def test_state_stamp_and_hold(self):
    fin = {"monthly_rent_expense": 2600.0}
    fin = AU.stamp(fin, {"door": "A", "action": "rewrote_patch", "field": "x", "receipt": "r"})
    self.assertEqual(fin["_guard"]["actions"][0]["action"], "rewrote_patch")
    fin = AU.set_hold(fin, {"field": "financials.cash_on_hand", "question": "q", "turn": 3})
    self.assertEqual(AU.get_hold(fin)["question"], "q")
    fin = AU.set_hold(fin, None)
    self.assertIsNone(AU.get_hold(fin))
    self.assertEqual(fin["monthly_rent_expense"], 2600.0, "the stamp never touches a stated figure")

  def test_the_wiring_is_where_the_design_says(self):
    h = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8-sig").read()
    i = h.find("patch = _normalize_unscoped_patch(patch, focus=focus)")
    self.assertGreater(i, 0)
    self.assertIn("_intake_guard_door_a(", h[i:i + 900], "door A sits right after the patch is unscoped, before any apply")
    self.assertLess(i, h.find("_normalize_financials_router_patch(", i))
    self.assertIn("_gaudit.get_hold(financials_json)", h, "a guard question blocks completion")
    d = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intake_consult_draft.py"), encoding="utf-8-sig").read()
    j = d.find("new_messages = _guard_reply_before_persist(")
    self.assertGreater(j, 0)
    self.assertLess(j, d.find("messages.extend(_naturalize_assistant_messages(new_messages))"), "door B before the write")
    self.assertNotIn("notify_turn_persisted(str(draft_id))", d, "the after-turn watcher is retired")
    a = open(os.path.join(ROOT, "python", "api.py"), encoding="utf-8-sig").read()
    self.assertIn("_guard_final_text", a, "the reply that persisted is the reply that is sent")


if __name__ == "__main__":
  unittest.main()


class FourAuthorisedOrigins(unittest.TestCase):
  def test_the_rule_names_the_estimators_baseline(self):
    from client_intake_and_finmo.intake_guard import provenance as P
    self.assertEqual(P.AUTHORISED_ORIGINS, ("router_patch", "option_pick", "guard_rewrite", "estimator_baseline"))
    self.assertEqual(P.origin_of("financials.baseline_marketing"), "estimator_baseline")
    self.assertEqual(P.origin_of("financials.monthly_rent_expense", allowed_patch={"financials.monthly_rent_expense": 2600}), "router_patch")
    self.assertEqual(P.origin_of("current_revenue", lever_writes={"current_revenue": {"from": 1, "to": 2}}), "option_pick")
    self.assertEqual(P.origin_of("ops:Recurring office cleaning:utilization_rate", lever_writes={"ops:Recurring office cleaning:utilization_rate": {}}), "option_pick")
    self.assertEqual(P.origin_of("financials.monthly_rent_expense", guard_rewrites=["financials.monthly_rent_expense"]), "guard_rewrite")
    self.assertIsNone(P.origin_of("financials.cash_on_hand"), "a write from nowhere is a leak")

  def test_door_a_never_rewrites_the_estimators_bookkeeping(self):
    proposed = {"financials.marketing_total_year1": 6000.0}
    reply = {"allowed": [{"key": "financials.marketing_total_year1", "value_json": "6000"}],
             "rewrites": [{"from_key": "financials.marketing_total_year1", "to_key": "financials.baseline_marketing",
                           "value_json": "6000", "client_words": "About $6,000 a year on marketing.", "receipt": "r", "why": "w"}],
             "asks": [], "hold_cleared": False}
    v = A.review(patch=proposed, user_text="About $6,000 a year on marketing.", messages=[], store=STORE, post=lambda **kw: _resp(reply))
    self.assertEqual(v.patch, proposed)
    self.assertEqual(v.rewrites, [], "the baseline is bookkeeping with known provenance, not a target")


class AMovedFigureIsNotAClaim(unittest.TestCase):
  def test_the_from_of_a_lever_write_is_authorised(self):
    store = {"financials": {"other_opex_absolute": 156600.0, "current_revenue": 576240.0}, "ops": {}, "people": {}}
    writes = {"other_opex_absolute": {"from": 174000.0, "to": 156600.0}, "current_revenue": {"from": 490000.0, "to": 576240.0}}
    text = ("With your agreement the levers moved: revenue $490,000 to $576,240 a year; "
            "other operating costs $174,000 to $156,600 a year. Everything else is exactly as you set it.")
    self.assertEqual(B.find_disagreements(text, store, writes), [], "guarded run 1 flagged the old value of a moved figure")
    self.assertEqual([d["value"] for d in B.find_disagreements("other operating costs moved to $999,000 a year.", store, writes)], [999000.0])


class TheInferenceDoorIsGuardedToo(unittest.TestCase):
  def test_door_a_sits_at_the_top_of_apply_forward_move(self):
    h = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8-sig").read()
    i = h.find("def _apply_forward_move(")
    body = h[i:h.find("def _parse_retention_answer(", i)]
    g = body.find("_gdoor_a.review(")
    self.assertGreater(g, 0, "the inference door is guarded")
    self.assertLess(g, body.find("_apply_scoped_patch("), "before any write")
    self.assertLess(g, body.find("_normalize_financials_router_patch("), "before the financials write")
    self.assertIn("return next_financials, shared, str(_a.get(\"question\") or \"\").strip(), True", body, "an ask holds the turn")


class TheReplyReachesThePanelWithoutMarkdown(unittest.TestCase):
  def test_bold_and_headings_are_stripped_at_the_reply_door(self):
    nl = chr(10)
    text = nl.join(["**Option 1 - Add contracts**", "That closes about **$11,313** of the gap.", "## Which fits?"])
    v = B.review(text=text, store=STORE)
    self.assertEqual(v.text, nl.join(["Option 1 - Add contracts", "That closes about $11,313 of the gap.", "Which fits?"]))


class AnOmissionChangesNothing(unittest.TestCase):
  def test_a_key_the_model_forgot_to_list_still_lands(self):
    """stated_total, guarded default pass: the router placed the competitive
    advantage correctly, the model left it out of `allowed`, the key was
    dropped and the app asked again."""
    proposed = {"ops.competitive_advantage": "Fear-free handling - dogs are never crated for hours."}
    reply = {"allowed": [], "rewrites": [], "asks": [], "hold_cleared": False}
    v = A.review(patch=proposed, user_text="Fear-free handling - dogs are never crated for hours.", messages=[], store=STORE,
                 post=lambda **kw: _resp(reply))
    self.assertEqual(v.patch, proposed)
    self.assertFalse(v.changed)

  def test_a_moved_figure_lands_on_the_field_the_client_named(self):
    proposed = {"financials.cash_on_hand": 1100.0}
    reply = {"allowed": [], "asks": [], "hold_cleared": False,
             "rewrites": [{"from_key": "financials.cash_on_hand", "to_key": "financials.annual_principal_payment", "value_json": "1100",
                           "client_words": "About $1,100 a year.", "receipt": "You told me the $1,100 a year is the loan principal, so I've recorded it there.",
                           "why": "the figure answers the principal question"}]}
    v = A.review(patch=proposed, user_text="About $1,100 a year.", messages=[], store=STORE, post=lambda **kw: _resp(reply))
    self.assertEqual(v.patch, {"financials.annual_principal_payment": 1100.0})
