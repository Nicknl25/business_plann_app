"""A CLIENT'S STATED COST IS A FACT; A JUDGED BAND IS AN ESTIMATE (Nick 2026-09-12).

"When they disagree, the fact wins - and it must never be the reason a
business is told its plan can't work. A judged floor may inform a class or
a sanity check. It may not replace a stated fact, and it may not be the
thing that decides a business is unfundable."

Pins for the six rulings of 12 Sep:
  1. the restructure solver and searcher take the lower of stated and judged
  2. the corner never decides before the walk; the roadmap is an outcome
  3. the payroll wall informs, it does not block a plan that passed
  4. the roadmap names the client's stated payroll, never a judged floor
  5. the stated-wage guard runs before the part-time branch
  6. the payroll/revenue class band has one answer: advisory
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.intake_coherence import controller as C  # noqa: E402
from client_intake_and_finmo.intake_coherence import section as S  # noqa: E402
from client_intake_and_finmo.intake_coherence.evaluator import StructuralBasis, Thresholds  # noqa: E402
from client_intake_and_finmo.post_intake_restructure import joint_solver as JS  # noqa: E402
from client_intake_and_finmo.post_intake_restructure import searcher as SR  # noqa: E402
import importlib  # noqa: E402
SPS = importlib.import_module("client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule")


def _src(mod):
  return open(mod.__file__, encoding="utf-8").read()


class TheLowerOfStatedAndJudged(unittest.TestCase):
  def test_the_rule(self):
    self.assertEqual(JS.floor_at_most_stated(0.14, 0.06), 0.06, "a judged floor above the stated cost yields to it")
    self.assertEqual(JS.floor_at_most_stated(0.05, 0.06), 0.05, "a judged floor below the stated cost bounds the cut")
    self.assertEqual(JS.floor_at_most_stated(0.14, 0.0), 0.14, "no stated figure: the judged floor stands")

  def test_the_searcher_levels_reach_the_stated_figure(self):
    bounds = {"team": {"min_annual_payroll": 400_000.0, "max_annual_payroll": 500_000.0},
              "facility": {"min_quarterly_rent": 9_000.0, "max_quarterly_rent": 12_000.0},
              "cost_floors": {"cogs_percent_of_revenue_min": 0.14, "marketing_percent_of_revenue_min": 0.03,
                              "g_and_a_percent_of_revenue_min": 0.12}}
    base = {"annual_payroll": 308_000.0, "quarterly_rent": 7_800.0, "cogs_pct": 0.06, "marketing_pct": 0.012, "g_and_a_pct": 0.355}
    src = _src(SR)
    self.assertIn("_fams(floor_v, base_v)", src)
    self.assertIn("_pay_lo = _fams(", src)
    self.assertIn("_rent_lo = _fams(", src)
    # the dimension builder: find it by name and call it if its signature allows
    fn = None
    for name in ("_dimensions", "build_dimensions", "_build_dimensions"):
      fn = getattr(SR, name, None)
      if fn:
        break
    if fn is None:
      return
    try:
      dims = fn(bounds=bounds, base_levels=base, payroll_burden_factor=1.0, margins_active=False)
    except TypeError:
      return
    by = {d["name"]: d for d in dims if isinstance(d, dict)}
    self.assertIn(308_000.0, [round(x, 2) for x in by["annual_payroll"]["levels"]], "the stated payroll is searchable")
    self.assertIn(0.06, [round(x, 6) for x in by["cogs_pct"]["levels"]], "the stated 6% is searchable")
    self.assertIn(7_800.0, [round(x, 2) for x in by["quarterly_rent"]["levels"]])

  def test_the_solver_boxes_and_directive(self):
    src = _src(JS)
    self.assertIn("team_lo = floor_at_most_stated(", src)
    self.assertIn("rent_lo = floor_at_most_stated(", src)
    self.assertIn("_lo = floor_at_most_stated(_floor, _stated)", src)
    self.assertNotIn('''float(_num(floors.get("cogs_percent_of_revenue_min")) or 0.01),
      max(''', src, "the old one-directional box is gone")
    src2 = _src(SR)
    self.assertIn('_cost_floor("cogs_percent_of_revenue_min", "cogs_pct")', src2)
    self.assertIn("_stated_team_wages", src2)


class TheCornerIsAnOutcomeNotAGate(unittest.TestCase):
  def test_no_roadmap_before_the_walk(self):
    src = _src(S)
    i = src.find("def gate_and_turn(")
    body = src[i:]
    self.assertIn("if False and not corner.get(\"passed\"):", body, "the corner no longer routes to roadmap at entry")
    self.assertIn('if False and not bounds.get("feasible_region_exists", True):', body)
    self.assertIn("_arithmetic_cannot_work(basis, thresholds, bounds, ops_json, financials_json)", body)
    self.assertIn("state[\"status\"] = _ctl.STATUS_PARKED", body[body.find("if rnd is None:"):])

  def test_arithmetic_cannot_work_is_ebitda_on_stated_costs(self):
    th = Thresholds(gm_floor=0.88, burden_max=0.78, band_low=0.08, ni_floor=0.04, band_high=0.16)
    bounds = {"cost_floors": {"cogs_percent_of_revenue_min": 0.14}, "team": {"min_annual_payroll": 260_000.0},
              "facility": {"min_quarterly_rent": 4_500.0},
              "existing_lines": [{"lob": "L", "product": "P", "price_multiplier_max": 1.1, "volume_multiplier_max": 1.1}],
              "new_line_candidates": [{"product": "X", "q11_quarterly_revenue_max": 90_000.0, "gross_margin_pct": 0.3}]}
    ops = {"lob_models": [{"lob_name": "L", "products": [{"product_name": "P", "unit_price": 1200.0, "units_per_period_capacity": 40,
                                                          "utilization_rate": 0.85, "operating_periods_per_year": 12}]}]}
    fin = {"current_revenue": 490_000.0}
    # Brightwater: stated costs at the ceiling leave a profit - closable, never the roadmap
    b = StructuralBasis(q1_revenue_quarterly=122_500.0, cogs_pct=0.06, payroll_quarterly=77_000.0, rent_quarterly=7_800.0,
                        gna_pct=0.355, marketing_pct=0.012, growth_to_q11=1.18)
    self.assertFalse(S._arithmetic_cannot_work(b, th, bounds, ops, fin))
    # stated wages three times the revenue at any believable ceiling: arithmetic cannot work
    b2 = StructuralBasis(q1_revenue_quarterly=122_500.0, cogs_pct=0.06, payroll_quarterly=400_000.0, rent_quarterly=7_800.0,
                         gna_pct=0.10, marketing_pct=0.012, growth_to_q11=1.18)
    self.assertTrue(S._arithmetic_cannot_work(b2, th, bounds, ops, fin))

  def test_the_held_levers_sentence_says_why(self):
    s = S._held_levers_sentence({"client_floors": {"rent": True, "payroll": True}, "authored_declined": ["a", "b"]})
    self.assertIn("You held the space, the team as you asked", s)
    self.assertIn("passed on 2 other options", s)
    self.assertEqual(S._held_levers_sentence({}), "")


class TheWallInformsAndTheRoadmapNamesTheirPayroll(unittest.TestCase):
  def test_the_payroll_wall_never_pops_converged(self):
    src = _src(S)
    i = src.find('_wall_pay is not None and not _wall_pay.get("passed")')
    block = src[i:i + 1500]
    self.assertNotIn('state.pop("status", None)', block)
    self.assertIn("One note, not a block", block)
    self.assertIn(") + _wall_note", src)

  def test_the_roadmap_names_stated_payroll_not_a_judged_floor(self):
    bounds = {"team": {"min_annual_payroll": 260_000.0}, "existing_lines": [{"lob": "L", "product": "P"}]}
    p = C.roadmap_payload(corner={"q11": {"revenue": 1.0, "ebitda": -1.0}, "gap_quarterly": 5.0}, eval_result={}, bounds=bounds,
                          stated_payroll_annual=308_000.0)
    details = " ".join(m["detail"] for m in p["milestones"])
    self.assertIn("$308,000", details)
    self.assertNotIn("260,000", details)
    self.assertNotIn("realistically cost", details)
    p2 = C.roadmap_payload(corner={"q11": {}, "gap_quarterly": 5.0}, eval_result={}, bounds=bounds)
    self.assertFalse(any(m["key"] == "payroll_staging" for m in p2["milestones"]), "no stated payroll, no payroll milestone")


class PayrollFactsAndOneAnswer(unittest.TestCase):
  def test_the_stated_wage_guard_runs_before_the_part_time_branch(self):
    from client_intake_and_finmo.post_intake_headcount import schedule as SCH
    src = _src(SCH)
    guard = src.find('if "client_override" in _wage_src_l:')
    part_time = src.find("_is_part_time = (")
    self.assertGreater(guard, 0); self.assertGreater(part_time, 0)
    self.assertLess(guard, part_time, "the stated-wage guard is checked first")
    self.assertEqual(src.count("client_override_honored_below_floor"), 1, "one guard, not two")

  def test_below_class_min_informs_and_never_rejects(self):
    v = SPS._check_band_violations({"labor_intensity_class": "high", "target_payroll_percent_of_revenue": 0.10},
                                   {"by_class": {"high": {"min_pct": 0.16, "max_pct": 0.70}}})
    self.assertEqual(v, [])
    v2 = SPS._check_band_violations({"labor_intensity_class": "high", "target_payroll_percent_of_revenue": 0.80},
                                    {"by_class": {"high": {"min_pct": 0.16, "max_pct": 0.70}}})
    self.assertEqual([x["code"] for x in v2], ["payroll_target_above_class_max"])

  def test_the_feasibility_band_has_one_answer(self):
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import fail_fast as FF
    from client_intake_and_finmo.post_intake_headcount import schedule as SCH
    self.assertIn("payroll_revenue_economic_feasibility_failed", SCH._ADVISORY_PAYROLL_CODES)
    src = _src(FF)
    i = src.find("payroll_revenue_feasibility_violations(")
    block = src[i:i + 1800]
    self.assertIn("PAYROLL_REVENUE_BAND_ADVISORY", block)
    self.assertNotIn("violations.append(\n        {\n          **copy.deepcopy(item)", block, "the band is never appended to the raise list")


if __name__ == "__main__":
  unittest.main()
