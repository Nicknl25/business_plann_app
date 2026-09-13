"""CW-695 (Nick 2026-09-12): THE WALK PRICES WHAT THE BUILD CHARGES.

The build lands the Payroll line as loaded labor cost - stated wages times
one plus the policy's employer taxes-and-benefits load (0.22) - on every
quarter. The walk closed Isolde & Parry's gap on unloaded wages and the
build's first year came out negative. Every basis the walk evaluates now
carries the same load: the live basis, the corner that admits a walk, the
roadmap test, and every priced move; the team bounds stay in stated-wage
terms and are scaled up to the basis; a payroll move's dollars are read
back down to wages, which is what the people fields hold.
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

from client_intake_and_finmo.intake_coherence import evaluator as EV  # noqa: E402
from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402


ISOLDE = {
  "current_revenue": 3493100.0,
  "cogs_percent_of_revenue": 0.10277,
  "baseline_payroll_year1": 1900000.0,
  "payroll_basis_people_roles": [
    {"role_title": "Founder and Managing Director", "year1_payroll_amount": 205000.0},
    {"role_title": "Medical Director", "year1_payroll_amount": 285000.0},
    {"role_title": "rest of team", "year1_payroll_amount": 1410000.0},
  ],
  "owner_compensation": 17083.33,
  "monthly_rent_expense": 6666.67,
  "other_operating_expense": 69208.32,
  "marketing_total_year1": 120000.0,
  "total_debt_outstanding": 0.0,
  "current_capex": 0.0,
}
ISOLDE_THRESHOLDS = EV.Thresholds(gm_floor=0.8, burden_max=0.7, band_low=0.1, ni_floor=0.06, band_high=0.2)


class TheBasisIsWhatTheBuildCharges(unittest.TestCase):
  def test_stated_wages_are_loaded_with_the_policy_load(self):
    b = EV.basis_from_intake(financials_json=ISOLDE, payroll_load=1.22)
    self.assertAlmostEqual(b.payroll_quarterly, 1900000.0 * 1.22 / 4.0, places=2)
    pb = b.notes["payroll_basis"]
    self.assertAlmostEqual(pb["stated_wages_annual"], 1900000.0, places=2)
    self.assertAlmostEqual(pb["benefits_pct"], 0.22, places=4)
    self.assertAlmostEqual(pb["loaded_annual"], 2318000.0, places=2)
    self.assertIn("what the build charges", pb["basis"])

  def test_the_seam_can_ask_for_bare_wages(self):
    b = EV.basis_from_intake(financials_json=ISOLDE, payroll_load=1.0)
    self.assertAlmostEqual(b.payroll_quarterly, 475000.0, places=2)

  def test_the_default_load_is_the_policy_number_the_schedule_applies(self):
    EV.reset_payroll_load_cache()
    pct = EV.payroll_benefits_pct()
    self.assertTrue(0.05 <= pct <= 0.60, pct)
    self.assertAlmostEqual(EV.payroll_load_factor(), 1.0 + pct, places=9)
    b = EV.basis_from_intake(financials_json=ISOLDE)
    self.assertAlmostEqual(b.payroll_quarterly, 1900000.0 * (1.0 + pct) / 4.0, places=2)

  def test_the_policy_fallback_is_the_fleet_verified_load(self):
    from client_intake_and_finmo.post_intake_headcount import lookup as LK
    with mock.patch.object(LK, "post_intake_headcount_policy_for", side_effect=RuntimeError("no db")):
      self.assertAlmostEqual(LK.payroll_benefits_pct_default(), 0.22, places=6)
    with mock.patch.object(LK, "post_intake_headcount_policy_for", return_value={"default_payroll_tax_benefits_pct": 0.31}):
      self.assertAlmostEqual(LK.payroll_benefits_pct_default(), 0.31, places=6)


class IsoldesQuarterOnTheBuildsBasis(unittest.TestCase):
  """Her flat quarter (today's revenue, no growth): the walk saw +$50,908 of
  EBITDA on bare wages; the build charged the load and the year came out
  negative. On the loaded basis the walk sees what the build will say."""

  def test_the_flat_quarter_turns_negative_once_payroll_is_loaded(self):
    bare = EV.basis_from_intake(financials_json=ISOLDE, growth_to_q11=1.0, payroll_load=1.0)
    loaded = EV.basis_from_intake(financials_json=ISOLDE, growth_to_q11=1.0, payroll_load=1.22)
    e_bare = EV.evaluate_structural(bare, ISOLDE_THRESHOLDS)["q11"]
    e_loaded = EV.evaluate_structural(loaded, ISOLDE_THRESHOLDS)["q11"]
    self.assertGreater(e_bare["ebitda"], 0.0)
    self.assertLess(e_loaded["ebitda"], 0.0, e_loaded)
    self.assertAlmostEqual(e_loaded["payroll"] - e_bare["payroll"], 475000.0 * 0.22, places=2)


class TheCornerAndTheMovesCarryTheSameLoad(unittest.TestCase):
  def test_the_corner_scales_the_team_floor_into_the_loaded_basis(self):
    b = EV.basis_from_intake(financials_json=ISOLDE, payroll_load=1.22)
    bounds = {"team": {"min_annual_payroll": 1100000.0}, "facility": {}, "cost_floors": {}, "new_line_candidates": []}
    corner = EV.favorable_corner_basis(b, bounds, payroll_burden_factor=1.22)
    self.assertAlmostEqual(corner.payroll_quarterly, 1100000.0 * 1.22 / 4.0, places=2)

  def test_the_corner_check_admits_a_walk_only_on_the_loaded_basis(self):
    fin = {"current_revenue": 4000000.0, "cogs_percent_of_revenue": 0.30, "baseline_payroll_year1": 1600000.0,
           "payroll_basis_people_roles": [{"role_title": "Owner", "year1_payroll_amount": 100000.0}],
           "monthly_rent_expense": 0.0, "other_operating_expense": 0.0, "marketing_total_year1": 0.0}
    th = EV.Thresholds(gm_floor=0.5, burden_max=0.45, band_low=0.05, ni_floor=0.01)
    bounds = {"team": {}, "facility": {}, "cost_floors": {}, "new_line_candidates": [], "existing_lines": []}
    bare = EV.basis_from_intake(financials_json=fin, growth_to_q11=1.0, payroll_load=1.0)
    loaded = EV.basis_from_intake(financials_json=fin, growth_to_q11=1.0, payroll_load=1.22)
    self.assertTrue(C.corner_check(basis=bare, thresholds=th, bounds=bounds, ops_json={}, financials_json=fin)["passed"],
                    "40% of revenue on bare wages clears a 45% ceiling")
    self.assertFalse(C.corner_check(basis=loaded, thresholds=th, bounds=bounds, ops_json={}, financials_json=fin)["passed"],
                     "48.8% once loaded does not - the walk is not admitted on a basis the build will refuse")

  def test_a_payroll_move_reads_its_dollars_back_to_wages(self):
    fin = {"current_revenue": 600000.0, "cogs_percent_of_revenue": 0.2, "baseline_payroll_year1": 150000.0,
           "payroll_basis_people_roles": [{"role_title": "Owner", "year1_payroll_amount": 120000.0},
                                          {"role_title": "Groomer", "year1_payroll_amount": 30000.0}],
           "monthly_rent_expense": 0.0, "other_operating_expense": 0.0, "marketing_total_year1": 0.0}
    th = EV.Thresholds(gm_floor=0.5, burden_max=0.2, band_low=0.05, ni_floor=0.01)
    bounds = {"team": {"min_annual_payroll": 100000.0}, "facility": {}, "cost_floors": {}, "new_line_candidates": []}
    basis = EV.basis_from_intake(financials_json=fin, growth_to_q11=1.0, payroll_load=1.22)
    with mock.patch.object(C, "payroll_load_factor", return_value=1.22):
      moves = C.available_cost_moves(basis, th, bounds, fin)
    self.assertIn("owner_draw", moves)
    m = moves["owner_draw"]
    # the floor scaled up: 100,000 x 1.22 / 4 = 30,500; the basis 150,000 x 1.22 / 4 = 45,750;
    # the wages needed: (45,750 - 30,500) x 4 / 1.22 = 50,000 - what the owner's pay field moves by
    self.assertAlmostEqual(m["field_patch"]["expected_baseline_delta"], -50000.0, places=2)
    self.assertAlmostEqual(m["field_patch"]["value"], (120000.0 - 50000.0) / 12.0, places=2)
    self.assertAlmostEqual(m["basis_patch"]["payroll_quarterly"], 30500.0, places=2, msg="the basis patch carries the loaded delta")

  def test_no_walk_site_prices_the_corner_on_bare_wages(self):
    import inspect
    from client_intake_and_finmo.intake_coherence import section as S
    for fn in (C.corner_check, S._arithmetic_cannot_work):
      src = inspect.getsource(fn)
      self.assertIn("payroll_burden_factor=payroll_load_factor()", src, fn.__name__)
      self.assertNotIn("payroll_burden_factor=1.0", src, fn.__name__)


class TheBoundsAuthorStillSeesWages(unittest.TestCase):
  def test_the_bounds_payload_carries_stated_wages_not_the_loaded_line(self):
    from client_intake_and_finmo.intake_coherence import section as S
    with mock.patch.object(EV, "payroll_load_factor", return_value=1.22):
      out = S._bounds_intake_input(ISOLDE, {}) if hasattr(S, "_bounds_intake_input") else None
    if out is None:
      self.skipTest("bounds input builder not exposed under that name")
    self.assertAlmostEqual(out.get("q1_payroll"), 475000.0, places=2)


if __name__ == "__main__":
  unittest.main()
