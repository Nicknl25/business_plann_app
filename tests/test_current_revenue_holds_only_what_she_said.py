"""current_revenue holds only what the client said.

Nick ruled 2026-09-14: current_revenue may not hold a figure the app worked out.
Revenue is what she says; if she hasn't stated it, the field is empty and the app
asks. And pre-revenue is not a stated zero - "I haven't started" and "I turn over
nothing" are different sentences, so the app asks.

The map found the app writing its own arithmetic into the field: the recalc
stamped the drivers' total into it on every pass, before she answered; a plain
"yes" to the revenue question turned that stamp into her stated baseline; a
driver change multiplied her figure by the drivers' ratio; a pre-revenue label
closed the stage with nothing stated.

These pins state, for any draft shape:
  - the recalc never writes current_revenue - absent stays absent, a stated figure
    stays exactly what she said, whatever the drivers add up to;
  - a yes to the revenue stage writes nothing, and the stage offers no app figure
    to accept;
  - a pre-revenue business is asked, not skipped;
  - no intake-handler path assigns current_revenue from anything but her figure;
  - door B still explains a reply stating the drivers' total, with current_revenue
    empty (Cowork 1087), and its view never writes back.
"""
from __future__ import annotations

import itertools
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "client_intake_and_finmo"))

TOTALS = (0.0, 96_000.0, 175_000.0, 1_679_600.0)
STATED = (None, "same", 0.0, 250_000.0)


class TheRecalcNeverWritesHerRevenue(unittest.TestCase):
  def test_absent_stays_absent_and_stated_stays_stated(self):
    from api_handlers import intake_consult as ic  # type: ignore
    # the rest of the pass (COGS and marketing families) must run too - a pin whose
    # drafts carry nothing past the revenue step cannot see the recalc break there
    rest = ({}, {"cogs_percent_of_revenue": 0.32, "cogs_basis": "ratio"},
            {"current_cogs": 99_840.0, "cogs_basis": "dollars", "marketing_total_year1": 4_800.0},
            {"marketing_percent_of_revenue": 0.03, "current_payroll": 120_000.0})
    for total, stated, intro_done, extra in itertools.product(TOTALS, STATED, (False, True), rest):
      fin0 = dict(extra)
      if stated is not None:
        fin0["current_revenue"] = total if stated == "same" else stated
      if intro_done:
        fin0["_financials_revenue_intro_done"] = True
      fin, _y1 = ic._sync_financials_consult_persistence_state(
        financials_json=dict(fin0), financials_year1_json={"company_revenue_total_year1": total, "lobs": []},
        marketing_model_json={}, people_json={}, ops_json={},
      )
      case = (total, stated, intro_done, sorted(extra))
      if "current_revenue" in fin0:
        self.assertEqual(fin.get("current_revenue"), fin0["current_revenue"], case)
      else:
        self.assertNotIn("current_revenue", fin, "the recalc wrote the drivers' total as her revenue: %r" % (case,))


class AYesIsNotAFigure(unittest.TestCase):
  def test_the_revenue_stage_offers_nothing_to_accept_and_writes_nothing(self):
    from api_handlers import intake_consult as ic  # type: ignore
    for total in TOTALS:
      patch = ic._financials_stage_default_patch(
        stage_name="revenue_intro", shared_context={}, financials_year1_json={"company_revenue_total_year1": total},
        business_facts={}, conn=None,
      )
      self.assertIsNone(patch, total)
    self.assertIsNone(ic._financials_stage_confirm_question("revenue_intro"))
    self.assertFalse(ic._financials_stage_spec("revenue_intro").get("confirmable_baseline"))


class NothingLandedNothingAcknowledged(unittest.TestCase):
  def test_the_revenue_acknowledgement_needs_her_revenue_in_the_store(self):
    """The forced "Yes." replay: the guard dropped the write, and the stage still
    said "we'll build from your current revenue picture"."""
    from api_handlers import intake_consult as ic  # type: ignore
    router_prose = ("Thanks for confirming. I’ll use about $3.45M as your current annual revenue so the plan "
                    "is grounded in today’s scale.")
    for fin in ({}, {"current_payroll": 120000.0}, {"_financials_revenue_intro_done": False}):
      self.assertEqual(ic._build_financials_stage_acknowledgement(stage_name="revenue_intro", financials_json=fin), "", fin)
      got = ic._build_financials_stage_acknowledgement_first(router_prose, stage_name="revenue_intro",
                                                              financials_json=fin, user_message="Yes.")
      self.assertNotIn("3.45", got)
      self.assertNotIn("revenue picture", got)
    for rev in (0.0, 780_000.0, 4_600_000.0):
      ack = ic._build_financials_stage_acknowledgement(stage_name="revenue_intro", financials_json={"current_revenue": rev})
      self.assertTrue(ack, rev)


class PreRevenueIsAsked(unittest.TestCase):
  def test_nothing_closes_the_revenue_stage_but_her_answer(self):
    from api_handlers import intake_consult as ic  # type: ignore
    self.assertFalse(hasattr(ic, "_maybe_autocomplete_revenue_intro"), "the pre-revenue skip came back")
    for extra in ({}, {"current_payroll": 120000.0}, {"_financials_revenue_intro_skipped": "pre-revenue"}):
      self.assertEqual(ic._next_financials_stage(dict(extra)), "revenue_intro", extra)
    self.assertNotEqual(ic._next_financials_stage({"_financials_revenue_intro_done": True}), "revenue_intro")


class NoHandlerPathWritesAWorkedOutRevenue(unittest.TestCase):
  def test_every_assignment_to_current_revenue_in_the_handler_is_her_figure(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(encoding="utf-8-sig")
    writes = [m for m in re.finditer(r'\[\s*"current_revenue"\s*\]\s*=(?!=)\s*([^\n]+)', src)]
    rhs = sorted(m.group(1).strip() for m in writes)
    # the one remaining direct write is the forward move landing HER figure (_vf, the value of her claim)
    self.assertEqual(rhs, ["_vf"], "a new direct write of current_revenue: %r" % rhs)
    for banned in ('"current_revenue": float(baseline_revenue)', "stated * factor)", 'float(_rp_prop)'):
      self.assertNotIn(banned, src)


class DoorBStillExplainsTheDriversTotal(unittest.TestCase):
  def test_a_reply_stating_the_drivers_total_is_explained_without_the_echo(self):
    from client_intake_and_finmo.intake_consult_draft import _door_b_derived  # type: ignore
    from client_intake_and_finmo.intake_guard.door_b import find_disagreements  # type: ignore
    for total in (96_000.0, 421_200.0, 1_679_600.0, 3_450_000.0):
      fin = {"current_payroll": 88_000.0}
      shown = format(int(total), ",")
      text = "Your prices and volumes add up to $%s a year." % shown
      bare = find_disagreements(text, {"financials": fin, "ops": {}, "people": {}}, None, "", [])
      self.assertTrue(any(abs((d.get("value") or 0) - total) < 1 for d in bare), "the pin cannot fail: %s" % shown)
      store = {"financials": fin, "ops": {}, "people": {}, "derived_explained": _door_b_derived({"company_revenue_total_year1": total})}
      dis = find_disagreements(text, store, None, "", [])
      self.assertFalse(any(abs((d.get("value") or 0) - total) < 1 for d in dis), shown)
      self.assertEqual(fin, {"current_payroll": 88_000.0}, "door B's view wrote back")
      # a derived figure explains a reply SINGLY - never inside a pair sum
      pair = find_disagreements("That comes to $%s." % format(int(total + 88_000.0), ","), store, None, "", [])
      self.assertTrue(any(abs((d.get("value") or 0) - (total + 88_000.0)) < 1 for d in pair), shown)
    self.assertEqual(_door_b_derived(None), {})
    self.assertEqual(_door_b_derived({"company_revenue_total_year1": 0}), {})

  def test_a_rewrite_is_never_handed_nor_allowed_the_drivers_total(self):
    """The forced "Yes." replay: door B rewrote a figure-free reply into "You
    should use $3,450,000 as your starting annual revenue" - the drivers' total."""
    import json as _json
    from client_intake_and_finmo.intake_guard import door_b as B  # type: ignore
    for total in (421_200.0, 3_450_000.0):
      shown = format(int(total), ",")
      seen = {}

      class _R:
        status_code = 200

        def json(self):
          reply = "You should use $%s as your starting annual revenue number." % shown
          return {"output": [{"content": [{"type": "output_text",
                                           "text": _json.dumps({"reply": reply, "changed": True, "why": "x"})}]}]}

      def post(**kw):
        seen["body"] = kw["payload"]["input"][1]["content"]
        return _R()
      store = {"financials": {"current_payroll": 88_000.0}, "ops": {}, "people": {},
               "derived_explained": {"company_revenue_total_year1": total}}
      import os as _os
      _os.environ.setdefault("OPENAI_API_KEY", "pin")
      v = B._post_rewrite("Understood. We'll build from your current revenue picture.", [], store, None, post)
      self.assertEqual(v.error, "rewrite_introduced_figure", shown)
      self.assertEqual(v.text, "Understood. We'll build from your current revenue picture.")
      self.assertNotIn(str(int(total)), seen["body"].replace(",", ""), "the rewrite model was handed the drivers' total")

  def test_the_reply_door_is_handed_the_drivers_total(self):
    src = (ROOT / "python" / "client_intake_and_finmo" / "intake_consult_draft.py").read_text(encoding="utf-8-sig")
    self.assertIn('"derived_explained": _door_b_derived(y1)}', src)
    self.assertIn("existing_messages=existing_messages, financials_year1_json=financials_year1_json,", src)


if __name__ == "__main__":
  unittest.main(verbosity=2)
