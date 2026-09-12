"""COHERENCE OPTIONS, STEP 3: THE AGENT PROPOSES, THE ENGINE PRICES (Nick 2026-09-12).

"A coherence agent that authors the options. The agent thinks like a
consultant... It decides what this business should consider. The engine
tells it what each one does and refuses the ones that aren't allowed."
"A SELECTED OPTION IS APPLIED BY CODE AGAINST A NAMED LEVER."
"floors_read recorded before generation."
"If a business genuinely has only two sensible moves, two is the honest
menu. If it has six, I'd rather see six than four chosen by a rule."

The author here is a fake: the pins are about what the SECTION does with
what the agent returns. The live call is GPT through the response lock.
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

from client_intake_and_finmo.intake_coherence import author as A  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence.evaluator import StructuralBasis, Thresholds  # noqa: E402

LK = "␟"


def _sablecreek():
  basis = StructuralBasis(q1_revenue_quarterly=1_320_000.0, cogs_pct=0.22, payroll_quarterly=635_000.0,
                          rent_quarterly=66_000.0, gna_pct=0.773, marketing_pct=0.031)
  th = Thresholds(gm_floor=0.35, burden_max=0.60, band_low=0.10, ni_floor=0.05, band_high=0.22)
  bounds = {"cost_floors": {"g_and_a_percent_of_revenue_min": 0.12, "cogs_percent_of_revenue_min": 0.21},
            "facility": {"min_quarterly_rent": 40_000.0}, "team": {},
            "existing_lines": [
              {"lob": "Installations", "product": "install", "price_multiplier_max": 1.2, "volume_multiplier_max": 1.3},
              {"lob": "Monitoring", "product": "monitoring", "price_multiplier_max": 1.15, "volume_multiplier_max": 1.5},
            ]}
  ops = {"business_name": "Sablecreek Security", "business_type": "security integrator", "lob_models": [
    {"lob_name": "Installations", "products": [
      {"product_name": "install", "unit_price": 150_000.0, "units_per_period_capacity": 2.8125, "utilization_rate": 0.8,
       "operating_periods_per_year": 12}]},
    {"lob_name": "Monitoring", "products": [
      {"product_name": "monitoring", "unit_price": 900.0, "units_per_period_capacity": 45.36, "utilization_rate": 0.7,
       "operating_periods_per_year": 12}]},
  ]}
  fin = {"current_revenue": 5_280_000.0, "cogs_basis": "ratio", "business_stage": "existing",
         "_coherence": {"status": C.STATUS_WALKING, "digest_hash": "d"}}
  return basis, th, bounds, ops, fin


TRANSCRIPT = [
  {"role": "assistant", "content": "What is your space costing you?"},
  {"role": "user", "content": "The warehouse is a signed five-year lease, so rent cannot move."},
]


def _fake_author(reply):
  calls = []
  def _author(*, payload):
    calls.append(payload)
    return reply
  _author.calls = calls
  return _author


# an EBITDA-bound wall, where a materials move closes something (under the
# fixture's own burden wall it closes nothing and the engine refuses it)
NO_BURDEN = Thresholds(gm_floor=0.35, burden_max=2.0, band_low=0.10, ni_floor=0.05, band_high=0.22)


def _run(reply, fin_extra=None, transcript=None, th=None):
  basis, _th, bounds, ops, fin = _sablecreek()
  th = th or _th
  if fin_extra:
    fin["_coherence"].update(fin_extra)
  state = S.get_state(fin)
  au = _fake_author(reply)
  rnd, state2, fin2 = S._authored_round(state=state, basis=basis, thresholds=th, bounds=bounds, ops_json=ops,
                                        financials_json=fin, transcript=transcript or TRANSCRIPT,
                                        gap=C._gap(basis, th), author=au)
  return rnd, state2, fin2, au


class FloorsAreReadBeforeGeneration(unittest.TestCase):
  def test_a_refusal_the_agent_read_removes_the_lever_before_the_moves_exist(self):
    reply = {"floors_read": [{"cost": "rent", "because": "the warehouse is a signed five-year lease"}],
             "candidates": [
               {"kind": "cost", "levers": ["gna", "rent"], "depth": 0.5, "line_moves": [], "label": "overhead and space", "why": "w"},
               {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "trim overhead halfway", "why": "spend less on the day-to-day"},
             ]}
    rnd, state, fin, au = _run(reply)
    self.assertTrue(state["client_floors"].get("rent"), "recorded as a client floor")
    self.assertEqual([o["id"] for o in rnd["options"]], ["costs_gna_d50"], "the rent candidate never priced")
    self.assertEqual(state["authored_rejections"][0]["reason"], "lever_floored_or_unavailable")
    self.assertEqual(S.get_state(fin)["floors_read"][0]["cost"], "rent")
    self.assertEqual(rnd["key"], C.ROUND_AUTHORED)

  def test_a_round_floor_marks_the_family_walked(self):
    reply = {"floors_read": [{"cost": "pricing", "because": "those are contracted"}],
             "candidates": [{"kind": "cost", "levers": ["gna"], "depth": 0.25, "line_moves": [], "label": "l", "why": "w"}]}
    _rnd, state, _fin, _au = _run(reply)
    self.assertIn(C.ROUND_PRICING, state["rounds_done"])
    self.assertTrue(state["client_floors"].get(C.ROUND_PRICING))

  def test_the_agent_sees_the_transcript_the_recorded_floors_and_the_levers(self):
    reply = {"floors_read": [], "candidates": [{"kind": "cost", "levers": ["gna"], "depth": 0.25, "line_moves": [], "label": "l", "why": "w"}]}
    _rnd, _state, _fin, au = _run(reply, fin_extra={"client_floors": {"payroll": True}, "authored_declined": ["costs_cogs"]})
    payload = au.calls[0]
    body = payload["input"][1]["content"]
    self.assertIn("signed five-year lease", body)
    self.assertIn('"payroll": true', body)
    self.assertIn('"costs_cogs"', body)
    self.assertIn(f"Installations{LK}install", body)
    self.assertIn('"lever": "gna"', body)
    self.assertEqual(payload["text"]["format"]["strict"], True)
    self.assertNotIn("$", body.split('"transcript"')[0].split('"cost_levers_available"')[0], "the gap is the engine's; the levers carry displays")


class TheEnginePricesAndRefuses(unittest.TestCase):
  def test_the_menu_is_what_the_agent_proposed_and_the_engine_accepted(self):
    reply = {"floors_read": [], "candidates": [
      {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "trim overhead halfway", "why": "spend less on the day-to-day"},
      {"kind": "cost", "levers": ["cogs", "gna"], "depth": 0.25, "line_moves": [], "label": "a little off both", "why": "suppliers and overhead each give a little"},
      {"kind": "price", "levers": [], "depth": 1.0, "line_moves": [{"line": f"Installations{LK}install", "multiplier": 1.1}], "label": "raise install pricing", "why": "installs carry a bit more"},
      {"kind": "volume", "levers": [], "depth": 1.0, "line_moves": [{"line": f"Monitoring{LK}monitoring", "multiplier": 1.3}], "label": "fill the monitoring book", "why": "more accounts on the same team"},
      {"kind": "price", "levers": [], "depth": 1.0, "line_moves": [{"line": f"Installations{LK}install", "multiplier": 1.6}], "label": "big price rise", "why": "w"},
      {"kind": "cost", "levers": ["hire_timing"], "depth": 1.0, "line_moves": [], "label": "x", "why": "w"},
    ]}
    rnd, state, _fin, _au = _run(reply)
    ids = [o["id"] for o in rnd["options"]]
    self.assertEqual(len(ids), 4, ids)
    self.assertEqual(ids[0], "costs_gna_d50")
    self.assertEqual(ids[1], "costs_cogs_gna_d25")
    self.assertTrue(ids[2].startswith("pricing_") and ids[3].startswith("volume_"), ids)
    reasons = [r["reason"] for r in state["authored_rejections"]]
    self.assertEqual(reasons, ["breaches_bound", "lever_floored_or_unavailable"])
    for o in rnd["options"]:
      self.assertIn("patch", o, "applied by code against a named lever")
      self.assertTrue(o.get("closes_display"))
      self.assertTrue(o.get("why"))
    self.assertEqual(sum(1 for o in rnd["options"] if o.get("recommended")), 1, "the rail still recommends by reason")
    self.assertEqual(rnd["options"][0]["label"], "trim overhead halfway")
    self.assertEqual(rnd["options"][0]["why"], "spend less on the day-to-day")

  def test_two_is_the_honest_menu_and_nothing_priceable_falls_back(self):
    reply = {"floors_read": [], "candidates": [
      {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "l1", "why": "w"},
      {"kind": "cost", "levers": ["cogs"], "depth": 1.0, "line_moves": [], "label": "l2", "why": "w"},
    ]}
    rnd, _s, _f, _a = _run(reply, th=NO_BURDEN)
    self.assertEqual(len(rnd["options"]), 2)
    rnd, state, _f, _a = _run({"floors_read": [], "candidates": [
      {"kind": "cost", "levers": ["rent"], "depth": 5.0, "line_moves": [], "label": "l", "why": "w"}]})
    self.assertIsNone(rnd)
    self.assertEqual(state["authored_fallback"], "nothing_priceable")
    rnd, state, _f, _a = _run(None)
    self.assertIsNone(rnd)
    self.assertEqual(state["authored_fallback"], "author_unavailable")
    self.assertEqual(state["authored_attempts"], 1)

  def test_the_agents_wording_may_carry_no_number(self):
    reply = {"floors_read": [], "candidates": [
      {"kind": "cost", "levers": ["cogs"], "depth": 1.0, "line_moves": [], "label": "save $40,000 on materials", "why": "suppliers come down 4.5%"}]}
    rnd, _s, _f, _a = _run(reply, th=NO_BURDEN)
    o = rnd["options"][0]
    self.assertNotIn("$40,000", o["label"])
    self.assertIn("suppliers would need to come down about", o["why"], "the engine's own why replaced it")
    for t, expect in (("a little less overhead", False), ("$1", True), ("up 12%", True), ("1,200 units", True), ("two crews", False)):
      self.assertEqual(A.wording_has_a_number(t), expect, t)


class DeclinesReauthor(unittest.TestCase):
  def test_declining_an_authored_round_remembers_the_ids_not_a_family(self):
    reply = {"floors_read": [], "candidates": [
      {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "l1", "why": "w"}]}
    rnd, state, fin, _a = _run(reply)
    state["round"] = rnd
    fin = S.put_state(fin, state)
    _r, _o, fin2, notes = S.apply_router_patch(patch={"coherence.option": "none"}, ops_json={}, financials_json=fin,
                                               user_text="none of those")
    st = S.get_state(fin2)
    self.assertIn("declined:authored", notes)
    self.assertEqual(st["authored_declined"], ["costs_gna_d50"])
    self.assertNotIn("authored", st.get("rounds_done") or [])
    # the next authoring skips what was declined even if the agent repeats it
    rnd2, _s, _f, _a = _run(reply, fin_extra={"authored_declined": ["costs_gna_d50"]})
    self.assertIsNone(rnd2)

  def test_the_question_reads_each_option_with_its_why_and_closure(self):
    reply = {"floors_read": [{"cost": "rent", "because": "signed lease"}], "candidates": [
      {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "trim overhead halfway", "why": "spend less on the day-to-day"},
      {"kind": "cost", "levers": ["cogs"], "depth": 1.0, "line_moves": [], "label": "pay less for materials", "why": "your suppliers would need to come down a little"}]}
    rnd, _s, _f, _a = _run(reply, th=NO_BURDEN)
    q = S._round_question(rnd, "$904,510")
    self.assertIn("Holding the space as you asked", q)
    self.assertIn("1) Trim overhead halfway: spend less on the day-to-day, closing about $", q)
    self.assertIn("2) Pay less for materials", q)
    self.assertIn("work on paper", q)
    self.assertNotRegex(q, r"(?<![a-z])(gna|cogs|d50)(?![a-z])")


class TheHandlerHandsTheTranscriptOver(unittest.TestCase):
  def test_every_gate_call_site_passes_the_transcript(self):
    src = open(os.path.join(ROOT, "python", "api_handlers", "intake_consult.py"), encoding="utf-8").read()
    sites = re.findall(r"_coherence_gate\(\n(?:.*\n){6,8}?\s*\)", src)
    calls = [s for s in sites if "user_text=message" in s]
    self.assertGreaterEqual(len(calls), 5)
    for s in calls:
      self.assertIn("transcript=[*(messages or [])", s)
    self.assertIn("transcript=transcript,", src)
    sec = open(S.__file__, encoding="utf-8").read()
    i = sec.find("def gate_and_turn(")
    self.assertLess(sec.find("_authored_round(", i), sec.find("_ctl.plan_rounds(", i), "the author runs before the legacy planner")


if __name__ == "__main__":
  unittest.main()


class TheOfferStandsUntilSomethingMoves(unittest.TestCase):
  def test_a_pending_authored_round_is_reused_while_gap_and_floors_hold(self):
    basis, th, _b, _o, _f = _sablecreek()
    gap = C._gap(basis, th)
    state = {"client_floors": {"rent": True}, "rounds_done": ["pricing"]}
    key = S._authored_for(state, gap)
    self.assertEqual(key, S._authored_for(dict(state), gap + 0.2))
    self.assertNotEqual(key, S._authored_for(dict(state), gap - 5000))
    self.assertNotEqual(key, S._authored_for({"client_floors": {"rent": True, "payroll": True}, "rounds_done": ["pricing"]}, gap))
    reply = {"floors_read": [], "candidates": [{"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "l", "why": "w"}]}
    rnd, _s, _f2, _a = _run(reply)
    self.assertEqual(rnd["authored_for"], S._authored_for({}, gap))
    src = open(S.__file__, encoding="utf-8").read()
    self.assertIn('_pending.get("authored_for") == _authored_for(state, gap)', src)


class WhatTheProofFound(unittest.TestCase):
  """Run over last night's drafts, the first authored rounds showed three
  holes; each is pinned here."""

  def test_a_refused_family_refuses_every_revenue_candidate(self):
    """Sablecreek point B: the agent read 'No more volume' as a floor and
    still proposed a volume move; the engine accepted it. Never again."""
    basis, th, bounds, ops, fin = _sablecreek()
    split = C.ops_line_split(ops, fin)
    k = f"Monitoring{LK}monitoring"
    ok = C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.3})
    self.assertNotIn("rejected", ok)
    r = C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.3},
                                  floors={C.ROUND_VOLUME: True})
    self.assertEqual(r["rejected"], "lever_floored_or_unavailable")
    r = C.price_revenue_candidate(kind="price", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.1},
                                  floors={C.ROUND_PRICING: True})
    self.assertEqual(r["rejected"], "lever_floored_or_unavailable")
    reply = {"floors_read": [{"cost": "volume", "because": "No more volume."}], "candidates": [
      {"kind": "volume", "levers": [], "depth": 1.0, "line_moves": [{"line": k, "multiplier": 1.3}], "label": "lock in the sites", "why": "w"},
      {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "l", "why": "w"}]}
    rnd, state, _f, _a = _run(reply)
    self.assertEqual([o["id"] for o in rnd["options"]], ["costs_gna_d50"])
    self.assertEqual(state["authored_rejections"][0]["reason"], "lever_floored_or_unavailable")

  def test_a_move_that_closes_nothing_is_refused(self):
    """Meriwether: direct costs do not touch a fixed-cost-burden gap, and the
    client was shown 'closing about $0'."""
    src = open(C.__file__, encoding="utf-8").read()
    self.assertEqual(src.count('"rejected": "closes_nothing"'), 3, "cost, price and volume pricers all refuse a no-op")
    basis, th, bounds, ops, fin = _sablecreek()
    split = C.ops_line_split(ops, fin)
    k = f"Monitoring{LK}monitoring"
    tiny = C.price_revenue_candidate(kind="volume", basis=basis, thresholds=th, bounds=bounds, split=split, multipliers={k: 1.0000001})
    self.assertIn(tiny.get("rejected"), ("closes_nothing", "no_change"), tiny)

  def test_the_holding_line_names_each_floor_once_and_keeps_the_engines_casing(self):
    reply = {"floors_read": [{"cost": "volume", "because": "no more volume"}, {"cost": "volume", "because": "final answer on volume"},
                             {"cost": "rent", "because": "signed lease"}], "candidates": [
      {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "trim overhead - and only if I say so", "why": "w"}]}
    rnd, state, _f, _a = _run(reply)
    self.assertEqual([f["cost"] for f in state["floors_read"]], ["volume", "rent"])
    q = S._round_question(rnd, "$1")
    self.assertIn("Holding your volumes, the space as you asked", q)
    self.assertIn("1) Trim overhead - and only if I say so", q)

  def test_the_prompt_says_a_description_is_not_a_floor(self):
    self.assertIn("'mentioned' is kept for the record and holds nothing", A.SYSTEM)
    self.assertIn("when in doubt", A.SYSTEM)


class OnlyARefusalOrACommitmentIsAFloor(unittest.TestCase):
  def test_a_cost_merely_mentioned_holds_nothing(self):
    """Castellane point A: 'Rent and the plant lease come to 78,000 a month
    together' was read as a rent floor. The agent now classifies what it
    read; only refused / cannot_move bind."""
    class _Resp:
      status_code = 200
      def json(self):
        return {"output": [{"content": [{"type": "output_text", "text": json.dumps({
          "floors_read": [
            {"cost": "rent", "because": "Rent and the plant lease come to 78,000 a month together.", "kind": "mentioned"},
            {"cost": "pricing", "because": "I cannot move aerospace pricing - those are contracted.", "kind": "cannot_move"},
            {"cost": "volume", "because": "No more volume.", "kind": "refused"},
          ],
          "candidates": [{"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "l", "why": "w"}],
        })}]}]}
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    res = A.author(payload={"model": "x"}, post=lambda **kw: _Resp())
    self.assertEqual([f["cost"] for f in res["floors_read"]], ["pricing", "volume"])
    self.assertEqual([f["cost"] for f in res["floors_mentioned"]], ["rent"])
    self.assertEqual(A.SCHEMA["properties"]["floors_read"]["items"]["required"], ["cost", "because", "kind"])
    reply = dict(res)
    rnd, state, _f, _a = _run(reply)
    self.assertNotIn("rent", state["client_floors"])
    self.assertTrue(state["client_floors"].get("pricing") and state["client_floors"].get("volume"))
    self.assertEqual(state["floors_mentioned"][0]["cost"], "rent")
