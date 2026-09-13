"""COHERENCE ON THE FORECAST, ONE ROUND (Nick 2026-09-12).

The walk hill-climbed one lever at a time and judged one frozen quarter;
Dunmore took twelve rounds searching an empty set. Coherence now solves the
forecast path once: today's actuals grown along the judged growth path,
overhead held in dollars, levers as ramps (annual price steps, volume to its
ceiling by Q11, cost lines easing to their floors). Coherent as stated ->
converged. Feasible -> one round of three complete configurations; the
client picks one and that is the agreement, stored as a plan directive the
executive refines within - the client's actuals are never edited. Not
feasible -> the proof, with the A-162 doors.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_coherence import path as P  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence.evaluator import StructuralBasis, Thresholds  # noqa: E402


TH = Thresholds(gm_floor=0.45, burden_max=0.37, band_low=0.08, ni_floor=0.04)
GROWTH = {q: 1.0 + 0.04 * (q - 1) for q in range(1, 21)}   # +4% of today's revenue a quarter, linear


def _box(*, rev_q=1000000.0, cogs=0.36, payroll_q=450000.0, rent_q=78000.0, gna_q=300000.0, mkt_q=30000.0,
         pmax=1.15, vmax=1.4, retained=0.7, floors=None):
  base = StructuralBasis(q1_revenue_quarterly=rev_q, cogs_pct=cogs, payroll_quarterly=payroll_q, rent_quarterly=rent_q,
                         gna_pct=gna_q / rev_q, marketing_pct=mkt_q / rev_q, growth_to_q11=1.0,
                         notes={"payroll_basis": {"stated_wages_annual": payroll_q * 4 / 1.22}})
  split = [{"lob": "Roasting", "product": "Wholesale", "q1_revenue_quarterly": rev_q, "unit_price": 780.0,
            "annual_units": 5128.0, "utilization_rate": 0.56}]
  bounds = {"existing_lines": [{"lob": "Roasting", "product": "Wholesale", "price_multiplier_max": pmax, "volume_multiplier_max": vmax}],
            "cost_floors": {"cogs_percent_of_revenue_min": 0.33, "g_and_a_percent_of_revenue_min": 0.09}, "facility": {}, "team": {}}
  matched = C.match_bounds_lines(split, bounds)
  demand = {"price_response": {"retained_fraction_band": [retained, 0.85]}}
  box = P.build_path_box(basis_today=base, thresholds=TH, bounds=bounds, split=split, matched=matched, growth=GROWTH,
                         client_floors=floors or {}, demand=demand, effective_pmax=C._effective_pmax, effective_vmax=C._effective_vmax)
  return box, bounds


class ThePathNotAFrozenQuarter(unittest.TestCase):
  def test_overhead_holds_in_dollars_so_its_share_falls_as_revenue_grows(self):
    box, _ = _box()
    b1 = P.quarter_basis(box, box.stated(), 1)
    b11 = P.quarter_basis(box, box.stated(), 11)
    self.assertAlmostEqual(b1.gna_pct * b1.q1_revenue_quarterly, b11.gna_pct * b11.q1_revenue_quarterly, places=2, msg="the same dollars")
    self.assertLess(b11.gna_pct, b1.gna_pct)
    self.assertAlmostEqual(b11.q1_revenue_quarterly, 1000000.0 * GROWTH[11], places=2)

  def test_a_price_step_is_annual_from_q5_and_never_passes_the_ceiling(self):
    box, _ = _box(pmax=1.10)
    self.assertEqual(P.price_multiplier(box, 0, 0.06, 4), 1.0)
    self.assertAlmostEqual(P.price_multiplier(box, 0, 0.06, 5), 1.06, places=6)
    self.assertAlmostEqual(P.price_multiplier(box, 0, 0.06, 8), 1.06, places=6)
    self.assertAlmostEqual(P.price_multiplier(box, 0, 0.06, 9), 1.10, places=6, msg="1.06^2 = 1.1236 is capped at the ceiling")

  def test_the_retained_step_applies_on_a_moved_price_and_the_proportional_reading_is_stored_beside_it(self):
    box, bounds = _box(retained=0.7)
    self.assertEqual(P.retained_fraction(box, 0, 1.03, "step"), 0.7)
    self.assertAlmostEqual(P.retained_fraction(box, 0, 1.15, "proportional"), 0.7, places=6)
    self.assertGreater(P.retained_fraction(box, 0, 1.03, "proportional"), 0.9)
    res = P.solve_configurations(box, bounds, {})
    self.assertEqual(res["retained_rule"], "step")
    self.assertIn("proportional_reading", res)


class ExistenceIsAProof(unittest.TestCase):
  def test_a_business_that_never_turns_positive_gets_the_proof_with_its_number(self):
    box, bounds = _box(payroll_q=1500000.0)   # payroll larger than revenue: nothing inside the bounds reaches zero
    res = P.solve_configurations(box, bounds, {})
    self.assertFalse(res["feasible"]); self.assertFalse(res["coherent_as_stated"])
    self.assertEqual(res["configurations"], [])
    sentence = P.proof_sentence(res)
    self.assertIn("Every lever at its believable limit", sentence)
    self.assertIn("never turns positive", sentence)
    self.assertGreater(res["limit"]["worst_ni_short_from_target"], 0)

  def test_a_business_that_clears_as_stated_needs_no_round(self):
    box, bounds = _box(gna_q=50000.0, payroll_q=200000.0)
    res = P.solve_configurations(box, bounds, {})
    self.assertTrue(res["coherent_as_stated"])
    self.assertEqual(res["configurations"], [])
    self.assertLessEqual(res["stated"]["first_positive_ni_q"], 11)


class ThreeCompleteConfigurations(unittest.TestCase):
  def test_the_same_answer_three_ways_each_positive_by_q11_and_holding(self):
    box, bounds = _box(gna_q=250000.0, payroll_q=560000.0, retained=0.85)
    res = P.solve_configurations(box, bounds, {})
    self.assertTrue(res["feasible"], res["limit"])
    self.assertFalse(res["coherent_as_stated"])
    ids = [c["id"] for c in res["configurations"]]
    self.assertGreaterEqual(len(ids), 2, ids)
    self.assertEqual(ids[0], "config_least_change"); self.assertTrue(res["configurations"][0].get("recommended"))
    for c in res["configurations"]:
      ev = P.evaluate_cfg(box, c["x"])
      self.assertTrue(ev["positive_by_target_and_holds"], c["id"])
      self.assertLessEqual(c["first_positive_ni_q"], 11)
      self.assertIn("Net income turns positive at Q", c["why"])
      d = c["directive"]
      self.assertTrue(d["feasible"]); self.assertEqual(d["source"], "intake_coherence_path")
      self.assertIn("revenue_mix", d); self.assertIn("cost_structure", d)

  def test_a_contracted_price_and_a_held_volume_remove_those_levers(self):
    box, bounds = _box(floors={"pricing": True, "volume": True})
    self.assertEqual(box.lines[0].pmax, 1.0); self.assertEqual(box.lines[0].vmax, 1.0)
    self.assertEqual(P.describe_levers(box, box.limit()), [])

  def test_the_directive_carries_the_price_at_q11_and_q20_under_the_annual_steps(self):
    box, _ = _box(pmax=1.30)
    x = [0.05, 1.2, box.base.cogs_pct, box.gna_q]
    d = P.directive_for(box, x)
    line = d["revenue_mix"]["lines"][0]
    self.assertAlmostEqual(line["price_multiplier_q11"], 1.05 ** 2, places=6)   # Q5 and Q9 steps by Q11
    self.assertAlmostEqual(line["price_multiplier_q20"], 1.05 ** 4, places=6)   # Q5, Q9, Q13, Q17
    self.assertEqual(line["volume_multiplier_q11"], 1.2)
    self.assertEqual(d["team"]["annual_payroll"], round(box.base.payroll_quarterly * 4 / 1.22, 2), "the team as stated wages, never cut")


class TheGateOffersOneRoundAndTheAgreementNeverEditsAnActual(unittest.TestCase):
  def _fin(self):
    return {"current_revenue": 4000000.0, "cogs_percent_of_revenue": 0.36, "baseline_payroll_year1": 1400000.0,
            "payroll_basis_people_roles": [{"role_title": "Owner", "year1_payroll_amount": 150000.0}],
            "monthly_rent_expense": 26000.0, "other_operating_expense": 83333.33, "marketing_total_year1": 120000.0,
            "current_num_employees": 20}

  def test_a_pick_stores_the_configuration_and_leaves_every_intake_field_as_stated(self):
    fin = self._fin()
    rnd = {"key": C.ROUND_SOLVED, "options": [{"id": "config_least_change", "label": "Least change", "why": "w", "closes_quarterly": 1000.0,
                                             "patch": {"kind": "directive", "directive": {"feasible": True, "source": "intake_coherence_path"},
                                                       "shape": "least_change", "x": [0.02, 1.1, 0.36, 250000.0], "moves": ["m"],
                                                       "points": {}, "first_positive_ni_q": 9}}], "authored_for": "x"}
    fin = S.put_state(fin, {"status": "walking", "round": rnd, "gap_open": 1000.0, "client_floors": {}})
    before = {k: v for k, v in fin.items() if k != "_coherence"}
    ops = {"lob_models": []}
    _r, next_ops, next_fin, notes = S.apply_router_patch(patch={"coherence.option": "config_least_change"}, ops_json=ops, financials_json=fin, user_text="Option 1.")
    after = {k: v for k, v in next_fin.items() if k != "_coherence"}
    self.assertEqual(before, after, "the client's actuals are not edited by a pick")
    st = S.get_state(next_fin)
    self.assertEqual(st["configuration"]["id"], "config_least_change")
    self.assertEqual(st["directive"]["source"], "intake_coherence_path")
    self.assertNotIn("round", st)
    self.assertTrue(any("configuration_chosen" in str(n) for n in notes), notes)

  def test_a_directive_option_never_reads_as_touching_a_floor(self):
    self.assertEqual(S._option_touches_a_floor({"patch": {"kind": "directive"}}, {"client_floors": {"rent": True, "pricing": True}}), "")

  def test_the_terminal_statement_carries_the_proof(self):
    st = {"corner_proof": {"exists": False, "sentence": "Every lever at its believable limit still leaves net income at -20% of revenue at Q11 (-1% at Q20) and never turns positive in the five years."},
          "intake_commitments": {"rent": "a signed lease with about 30 months left"}, "client_floors": {"rent": True}}
    text = S._terminal_statement(st, 1000.0, None)
    self.assertIn("Every lever at its believable limit", text)
    self.assertIn("a signed lease with about 30 months left", text)
    self.assertIn("not a verdict on the business", text)

  def test_the_runner_reads_the_agreement_from_the_draft_when_no_restructure_directive_is_active(self):
    import inspect
    from client_intake_and_finmo.post_intake_initial_grid import runner as R
    src = inspect.getsource(R)
    self.assertIn('("_coherence") or {}).get("directive")', src)
    self.assertIn('"intake_coherence"', src)


if __name__ == "__main__":
  unittest.main()
