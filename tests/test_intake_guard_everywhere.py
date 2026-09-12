"""THE GUARD RUNS EVERYWHERE (Nick 2026-09-12).

"It ran on one code path. Not financials - the stage where revenue, rent,
overhead and payroll get captured, where it made zero calls across forty
turns. Not the coherence apply, where an option's click rewrote my stated
revenue. Every stage. Every path a value can land through. And tell me how
you know you've found them all - a structural argument."

The argument, pinned here: the four intake sections are written by exactly
one function, append_messages, and door C sits inside it, diffing the
pre-turn row against the post-turn sections. Every path lands there.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_guard import door_c as D  # noqa: E402
from client_intake_and_finmo.intake_guard import provenance as P  # noqa: E402

SECTION_COLUMNS = ("operating_model_json", "target_market_json", "people_json", "financials_json")


class TheStructuralArgument(unittest.TestCase):
  """One door to the sections. Read the code, not a grep of call sites."""

  def _updates(self, src):
    return [m.group(0) for m in re.finditer(r"UPDATE\s+intake_consult_drafts[\s\S]*?WHERE", src)]

  def test_only_append_messages_writes_a_section(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intake_consult_draft.py"), encoding="utf-8").read()
    fn_at = [(m.start(), m.group(1)) for m in re.finditer(r"^def (\w+)\(", src, re.M)]
    def owner(pos):
      name = None
      for start, fn in fn_at:
        if start <= pos:
          name = fn
      return name
    writers = set()
    for m in re.finditer(r"UPDATE\s+intake_consult_drafts", src):
      fn = owner(m.start())
      body = src[m.start():src.find("WHERE", m.start())]
      # a VALUE landing on a section (column = %s), never a reset to NULL
      if any((c + " = %s") in body for c in SECTION_COLUMNS) or "set_parts" in body:
        writers.add(fn)
    self.assertEqual(writers, {"append_messages"}, writers)

  def test_no_other_module_writes_the_draft_sections(self):
    offenders = []
    for base in (os.path.join(ROOT, "python"), os.path.join(ROOT, "scripts")):
      for dirpath, _dirs, files in os.walk(base):
        for f in files:
          if not f.endswith(".py") or f == "intake_consult_draft.py":
            continue
          path = os.path.join(dirpath, f)
          try:
            src = open(path, encoding="utf-8", errors="replace").read()
          except Exception:
            continue
          for m in re.finditer(r"UPDATE\s+`?intake_consult_drafts`?\s+SET\s+([^\n]{0,200})", src):
            if any(c in m.group(1) for c in SECTION_COLUMNS):
              offenders.append((path, m.group(1)[:80]))
    self.assertEqual(offenders, [])

  def test_door_c_sits_inside_the_one_door_before_door_b(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intake_consult_draft.py"), encoding="utf-8").read()
    i = src.find("def append_messages(")
    body = src[i:src.find("\ndef ", i + 10)]
    c = body.find("_guard_writes_before_persist(")
    b = body.find("_guard_reply_before_persist(")
    self.assertGreater(c, 0)
    self.assertGreater(b, c, "door C (the writes) runs before door B (the reply)")

  def test_the_provenance_rule_is_now_called_by_a_door(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intake_guard", "door_c.py"), encoding="utf-8").read()
    self.assertIn("_prov.origin_of(", src)


class DoorCReadsEveryWrite(unittest.TestCase):
  def test_the_diff_sees_numbers_strings_and_nested_rows(self):
    pre = {"financials": {"current_revenue": 4600000.0, "_coherence": {"x": 1}},
           "ops": {"lob_models": [{"products": [{"unit_price": 780, "utilization_rate": 0.75}]}]},
           "people": {}, "market": {"summary": "old"}}
    post = {"financials": {"current_revenue": 3450000.0, "_coherence": {"x": 2}},
            "ops": {"lob_models": [{"products": [{"unit_price": 780, "utilization_rate": 0.5625}]}]},
            "people": None, "market": {"summary": "new"}}
    paths = {c["path"]: (c["from"], c["to"]) for c in D.diff_sections(pre, post)}
    self.assertEqual(paths["financials.current_revenue"], (4600000.0, 3450000.0))
    self.assertEqual(paths["ops.lob_models[0].products[0].utilization_rate"], (0.75, 0.5625))
    self.assertEqual(paths["market.summary"], ("old", "new"))
    self.assertNotIn("financials._coherence.x", paths, "private app state is never a client write")
    self.assertFalse(any(p.startswith("people") for p in paths), "a section not handed in was not written")

  def test_a_stated_fact_is_reviewed_and_its_twin_is_spared(self):
    changes = [{"path": "financials.current_revenue", "from": None, "to": 4600000.0},
               {"path": "financials.other_operating_expense", "from": None, "to": 210000.0},
               {"path": "financials.other_opex_absolute", "from": None, "to": 2520000.0},
               {"path": "financials.cogs_total_year1", "from": 1.0, "to": 1648000.0}]
    out = {c["path"]: c["origin"] for c in D.classify(changes, allowed_patch={}, lever_delta={}, guard_rewrites=[],
                                                          user_text="About 4.6 million a year. And about 210,000 a month in other bills.")}
    # a stated fact goes to the model even when the client said the number (the
    # van lease was in their words and landed on rent); its twin is arithmetic
    self.assertEqual(out["financials.current_revenue"], "unreviewed")
    self.assertEqual(out["financials.other_operating_expense"], "unreviewed")
    self.assertEqual(out["financials.other_opex_absolute"], "twin")
    self.assertEqual(out["financials.cogs_total_year1"], "unreviewed", "a stated fact the client did not say is reviewed")

  def test_origins_from_the_doors_and_the_walk(self):
    changes = [{"path": "financials.monthly_rent_expense", "from": 2600, "to": 2400},
               {"path": "financials.other_opex_absolute", "from": 2520000.0, "to": 2068762.56},
               {"path": "financials.baseline_marketing", "from": 1, "to": 2},
               {"path": "ops.shipping_method", "from": "a", "to": "b"},
               {"path": "financials.some_rollup_note", "from": "x", "to": "y"}]
    out = {c["path"]: c["origin"] for c in D.classify(
      changes, allowed_patch={"ops.shipping_method": "b"},
      lever_delta={"other_opex_absolute": {"from": 2520000.0, "to": 2068762.56}}, guard_rewrites=["financials.monthly_rent_expense"],
      user_text="ok")}
    self.assertEqual(out["ops.shipping_method"], P.ROUTER_PATCH)
    self.assertEqual(out["financials.other_opex_absolute"], P.OPTION_PICK)
    self.assertEqual(out["financials.baseline_marketing"], P.ESTIMATOR_BASELINE)
    self.assertEqual(out["financials.monthly_rent_expense"], P.GUARD_REWRITE)
    self.assertEqual(out["financials.some_rollup_note"], "derived")

  def test_a_cost_option_may_never_touch_stated_revenue(self):
    pre = {"financials": {"current_revenue": 4600000.0, "marketing_total_year1": 145000.0, "other_opex_absolute": 2520000.0,
                          "_coherence": {"_lever_writes": {}}}, "ops": {}, "market": {}, "people": {}}
    post = {"financials": {"current_revenue": 3450000.0, "marketing_total_year1": 103500.0, "other_opex_absolute": 2331000.0,
                           "_coherence": {"_lever_writes": {
                             "marketing_total_year1": {"from": 145000.0, "to": 103500.0},
                             "other_opex_absolute": {"from": 2520000.0, "to": 2331000.0},
                             "current_revenue": {"from": 4600000.0, "to": 3450000.0}}}},
            "ops": None, "market": None, "people": None}
    v = D.review(pre=pre, post=post, user_text="Let's go with option 3 - Tighten overhead to fund sales that really work.",
                 messages=[], stage="financials")
    self.assertEqual(v.sections["financials"]["current_revenue"], 4600000.0)
    self.assertNotIn("current_revenue", v.sections["financials"]["_coherence"]["_lever_writes"])
    self.assertEqual(len(v.refused), 1)
    self.assertIn("Your revenue stays at $4,600,000 a year", v.receipts[0])
    self.assertFalse(v.ran_model, "the refusal is a rule, not a model call")
    self.assertEqual(v.sections["financials"]["marketing_total_year1"], 103500.0, "the cost writes themselves stand")

  def test_a_price_lever_moving_revenue_is_the_walk_not_a_side_effect(self):
    pre = {"financials": {"current_revenue": 4600000.0, "_coherence": {"_lever_writes": {}}}, "ops": {}, "market": {}, "people": {}}
    post = {"financials": {"current_revenue": 4830000.0, "_coherence": {"_lever_writes": {
              "current_revenue": {"from": 4600000.0, "to": 4830000.0},
              "ops:Wholesale:unit_price": {"from": 780, "to": 819}}}}, "ops": None, "market": None, "people": None}
    v = D.review(pre=pre, post=post, user_text="option 1", messages=[], stage="financials")
    self.assertEqual(v.sections["financials"]["current_revenue"], 4830000.0)
    self.assertEqual(v.refused, [])

  def test_an_unreviewed_stated_fact_goes_to_the_model_and_an_ask_holds_the_value(self):
    calls = []
    class _Resp:
      status_code = 200
      def json(self):
        return {"output": [{"content": [{"type": "output_text", "text": json.dumps({
          "allowed": [], "rewrites": [],
          "asks": [{"key": "financials.monthly_rent_expense", "client_words": "the vans are about 2,400 a month",
                    "question": "Is the $2,400 a month the van lease rather than rent?", "why": "it reads as a vehicle lease"}],
          "hold_cleared": False})}]}]}
    def fake_post(**kw):
      calls.append(kw)
      return _Resp()
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    pre = {"financials": {"monthly_rent_expense": 2600.0}, "ops": {}, "market": {}, "people": {}}
    post = {"financials": {"monthly_rent_expense": 2400.0}, "ops": None, "market": None, "people": None}
    v = D.review(pre=pre, post=post, user_text="the vans are about 2,400 a month on top of everything",
                 messages=[{"role": "user", "content": "the vans are about 2,400 a month on top of everything"}],
                 stage="financials", post_fn=fake_post)
    self.assertTrue(v.ran_model)
    self.assertEqual(len(calls), 1)
    self.assertEqual(v.sections["financials"]["monthly_rent_expense"], 2600.0, "held back until answered")
    self.assertEqual(len(v.asks), 1)
    self.assertIn("van lease", v.questions[0])
    self.assertEqual(v.changes[0]["origin"], "asked")

  def test_derived_leaves_never_reach_the_model(self):
    calls = []
    def fake_post(**kw):
      calls.append(kw)
      raise AssertionError("no model call expected")
    pre = {"financials": {"payroll_basis_note": "a"}, "ops": {}, "market": {}, "people": {}}
    post = {"financials": {"payroll_basis_note": "b", "financials_year1_twin": 12.0}, "ops": None, "market": None, "people": None}
    v = D.review(pre=pre, post=post, user_text="ok", messages=[], stage="financials", post_fn=fake_post)
    self.assertFalse(v.ran_model)
    self.assertEqual({c["origin"] for c in v.changes}, {"derived"})

  def test_the_record_is_one_row_per_turn_even_when_nothing_changed(self):
    rows = []
    class _Conn:
      pass
    from client_intake_and_finmo.intake_guard import audit as A
    orig = A.record
    A.record = lambda conn, **kw: rows.append(kw)
    try:
      v = D.review(pre={"financials": {"x": 1}, "ops": {}, "market": {}, "people": {}},
                   post={"financials": {"x": 1}, "ops": None, "market": None, "people": None}, user_text="hi", messages=[], stage="ops")
      D.record(_Conn(), draft_id="d", turn=7, stage="ops", verdict=v)
    finally:
      A.record = orig
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["action"], "turn_review")
    self.assertEqual(rows[0]["field"], "stage:ops")
    self.assertEqual(rows[0]["turn"], 7)
    self.assertEqual(rows[0]["to_value"]["changed"], 0, "objects, not pre-encoded strings - the audit encodes")


class TheGateProvesItRan(unittest.TestCase):
  def test_every_persona_carries_g4_and_the_gate_prints_the_table(self):
    pers = open(os.path.join(ROOT, "scripts", "intake_personas.py"), encoding="utf-8").read()
    self.assertEqual(pers.count("    G4,\n"), 5)
    gate = open(os.path.join(ROOT, "scripts", "intake_persona_gate.py"), encoding="utf-8").read()
    self.assertIn("FROM intake_guard_actions", gate)
    self.assertIn("turn  stage        door action", gate)


if __name__ == "__main__":
  unittest.main()


class DoorAIsOnTheFinancialsPath(unittest.TestCase):
  def test_both_router_calls_in_the_financials_handler_pass_through_door_a(self):
    src = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8").read()
    i = src.find("def _run_financials_turn_and_sync_inner(")
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    self.assertEqual(body.count("routed = route_intent("), 2)
    self.assertEqual(body.count("_intake_guard_door_a("), 2, "every router call on the financials path goes through door A")

  def test_door_c_never_applies_a_rewrite(self):
    src = open(os.path.join(ROOT, "python", "client_intake_and_finmo", "intake_guard", "door_c.py"), encoding="utf-8").read()
    self.assertIn("NO REWRITE AT THE PERSIST DOOR", src)
    self.assertIn('"model_opinion"', src)
