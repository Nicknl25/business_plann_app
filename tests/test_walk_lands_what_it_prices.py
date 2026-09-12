"""Items 6, 7, 9, 10 of Nick's 2026-09-12 directive, after CW-062.

6. NO LEVER TOUCHES STATED REVENUE. $4,600,000 became $3,449,999.99 from a
   marketing decision.
7. THE PRICER BUG. Fix the basis composition so a combined move can't
   overwrite the scaled percentage. And the widening refusal must test what
   LANDED, not what the pricer computed.
9. EVERY ROUND ACKNOWLEDGES THE LAST PICK, including when the gap widened.
10. SHOW THE CUMULATIVE EFFECT EVERY ROUND.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from client_intake_and_finmo.intake_coherence.evaluator import StructuralBasis, Thresholds  # noqa: E402
from replay_gate import legs as L  # noqa: E402


def _basis(rev_q=1575982.0):
  return StructuralBasis(q1_revenue_quarterly=rev_q, cogs_pct=0.3583, payroll_quarterly=416000.0, rent_quarterly=78000.0,
                         gna_pct=863364.0 / rev_q, marketing_pct=0.08, interest_quarterly=0.0, depreciation_quarterly=0.0,
                         growth_to_q11=1.0, notes={})


THRESH = Thresholds(gm_floor=0.45, burden_max=0.37, band_low=0.08, ni_floor=0.04, band_high=0.17, judged=True)
BOUNDS = {"cost_floors": {"marketing_percent_of_revenue_min": 0.03, "g_and_a_percent_of_revenue_min": 0.30},
          "team": {}, "facility": {}}


class NoLeverTouchesStatedRevenue(unittest.TestCase):
  def test_a_coupled_marketing_cut_is_not_a_lever(self):
    demand = {"marketing_response": {"verdict": "coupled", "demand_at_reduced_spend_band": [0.75, 0.9]}}
    moves = C.available_cost_moves(_basis(), THRESH, BOUNDS, {"current_revenue": 4600000.0}, demand=demand)
    self.assertNotIn("marketing", moves, "a cut that would cost customers is not generated")

  def test_a_pure_savings_marketing_cut_lands_on_the_stated_basis(self):
    demand = {"marketing_response": {"verdict": "independent", "demand_at_reduced_spend_band": [1.0, 1.0]}}
    moves = C.available_cost_moves(_basis(), THRESH, BOUNDS, {"current_revenue": 4600000.0}, demand=demand)
    self.assertIn("marketing", moves)
    self.assertNotIn("coupled_basis", moves["marketing"])
    self.assertEqual(moves["marketing"]["demand_consequence"]["demand_mult_lo"], 1.0)

  def test_the_apply_never_carries_a_demand_landing(self):
    src = open(S.__file__, encoding="utf-8").read()
    self.assertNotIn('next_fin["current_revenue"] = _rev_after_m', src)
    self.assertIn("demand_landing_ignored", src)


class ThePricerHasOneBasis(unittest.TestCase):
  def test_a_move_with_a_second_basis_is_refused_outright(self):
    b = _basis()
    moves = {"gna": {"basis_patch": {"gna_pct": 0.45}, "field_patch": {"group": "financials", "field": "other_operating_expense", "value": 1.0}},
             "marketing": {"basis_patch": {}, "coupled_basis": C._marketing_cut_move_basis(b, 0.03, 0.75),
                           "field_patch": {"group": "financials", "field": "marketing_total_year1", "value": 1.0}}}
    o = C.price_cost_candidate(basis=b, thresholds=THRESH, moves=moves, lever_ids=["gna", "marketing"], depth=1.0)
    self.assertEqual(o.get("rejected"), "coupled_basis_not_allowed")

  def test_no_move_carries_a_coupled_basis_any_more(self):
    src = open(C.__file__, encoding="utf-8").read()
    self.assertNotIn('"coupled_basis": _marketing_cut_move_basis', src)


def _walking_fixture():
  """The gate's fixture, with a team the revenue can carry and overhead above
  its floor, so the walk has a lever to offer and keeps walking."""
  fin = dict(L.GOAL_FIN)
  fin.update({"baseline_payroll_year1": 120000.0, "current_payroll": 120000.0, "payroll_total_year1": 120000.0,
              "other_opex_absolute": 90000.0, "other_operating_expense": 7500.0})
  st = L._goal_walking_state(S, fin, L.GOAL_OPS)
  fin["_coherence"] = st
  return fin


class TheWideningRefusalTestsWhatLanded(unittest.TestCase):
  def _option(self, oid, monthly_opex, closes, label):
    return {"id": oid, "label": label, "closes_quarterly": closes,
            "patch": {"kind": "financials_fields", "fields": [{"group": "financials", "field": "other_operating_expense", "value": monthly_opex}]}}

  def test_a_pick_that_widens_on_landing_is_reverted_and_stamped(self):
    fin = _walking_fixture()
    before = S._landed_gap(fin, L.GOAL_OPS)
    self.assertIsNotNone(before)
    # a "cut" whose landed value is HIGHER than today's overhead: priced as a closure, widens on landing
    bad = self._option("costs_gna_bad", float(fin["other_operating_expense"]) * 1.5, 12345.0, "Trim overhead")  # lands HIGHER
    fin["_coherence"]["round"] = {"key": C.ROUND_AUTHORED, "options": [bad]}
    _r, ops, fin1, notes = S.apply_router_patch(patch={"coherence.option": "costs_gna_bad"}, ops_json=copy.deepcopy(L.GOAL_OPS),
                                                financials_json=fin, user_text="option 1")
    self.assertTrue(any(n.startswith("option_widened_on_landing:costs_gna_bad") for n in notes), notes)
    self.assertEqual(float(fin1["other_operating_expense"]), float(fin["other_operating_expense"]), "reverted in full")
    st1 = S.get_state(fin1)
    self.assertEqual(st1["widened_pick"]["id"], "costs_gna_bad")
    self.assertAlmostEqual(st1["widened_pick"]["promised"], 12345.0)
    self.assertGreater(st1["widened_pick"]["gap_after"], st1["widened_pick"]["gap_before"])
    self.assertNotIn("round", st1, "the menu rebuilds on the unchanged numbers")
    self.assertNotIn("other_operating_expense", (st1.get("_lever_writes") or {}), "no lever write survives a reverted pick")

  def test_a_pick_that_closes_on_landing_stands_and_is_stamped(self):
    fin = _walking_fixture()
    good = self._option("costs_gna", float(fin["other_operating_expense"]) * 0.8, 2000.0, "Trim overhead")
    fin["_coherence"]["round"] = {"key": C.ROUND_AUTHORED, "options": [good]}
    _r, ops, fin1, notes = S.apply_router_patch(patch={"coherence.option": "costs_gna"}, ops_json=copy.deepcopy(L.GOAL_OPS),
                                                financials_json=fin, user_text="option 1")
    self.assertIn("option:costs_gna:costs", notes)
    self.assertAlmostEqual(float(fin1["other_operating_expense"]), float(fin["other_operating_expense"]) * 0.8)
    self.assertEqual(S.get_state(fin1)["last_pick"]["id"], "costs_gna")


class EveryRoundAcknowledgesAndShowsTheCumulativeEffect(unittest.TestCase):
  def _gate(self, fin, text="ok"):
    return S.gate_and_turn(ops_json=L.GOAL_OPS, people_json={}, market_json={}, marketing_model_json={},
                           financials_json=fin, financials_year1_json={}, user_text=text,
                           transcript=[{"role": "user", "content": text}],
                           author=lambda payload: {"floors_read": [], "floors_mentioned": [], "candidates": [
                             {"kind": "cost", "levers": ["gna"], "depth": 0.5, "line_moves": [], "label": "Trim overhead", "why": "w"}]})

  def test_a_widened_pick_is_said_with_its_arithmetic(self):
    fin = _walking_fixture()
    fin["_coherence"]["widened_pick"] = {"id": "costs_gna_bad", "promised": 118627.0, "gap_before": 774251.0, "gap_after": 855277.0,
                                         "label": "Tighten overhead to fund sales that really work"}
    turn, fin1, _ = self._gate(fin, "Let's go with option 3")
    msg = str((turn or {}).get("assistant_message") or "")
    self.assertIn("I did not apply 'Tighten overhead to fund sales that really work'", msg)
    self.assertIn("priced to close $118,627", msg)
    self.assertIn("widened the gap by $81,026", msg)
    self.assertNotIn("widened_pick", S.get_state(fin1))

  def test_a_pick_that_did_not_move_the_gap_is_still_acknowledged(self):
    fin = _walking_fixture()
    fin["_coherence"]["gap_open"] = S._landed_gap(fin, L.GOAL_OPS)   # the previous round's gap, on these numbers
    fin["_coherence"]["last_pick"] = {"id": "costs_gna", "promised": 1.0, "label": "Trim overhead"}
    turn, _fin1, _ = self._gate(fin, "option 1")
    msg = str((turn or {}).get("assistant_message") or "")
    self.assertIn("That change is in as you chose it - 'Trim overhead' - but it did not move the gap", msg)

  def test_every_round_states_where_the_numbers_stand_against_the_start(self):
    fin = _walking_fixture()
    turn, _fin1, _ = self._gate(fin, "what's next?")
    msg = str((turn or {}).get("assistant_message") or "")
    self.assertIn("Where the numbers stand against what you first told me: the marketing budget $23,850 to $12,000 (-50%)", msg)


if __name__ == "__main__":
  unittest.main()
