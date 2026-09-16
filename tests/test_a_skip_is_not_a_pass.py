"""A SKIP IS NOT A PASS (Nick 2026-09-16: "we cant miss charts or sections, and the
check for that is not robust enough"; Cowork 1307/1309).

The completeness gate already re-tests whether an absence REASON is true (the 09-10
reason gate). What no check covered is whether a true reason is SUFFICIENT. Cedarbrook
skipped revenue_by_line on "single line of business - the figure would repeat the revenue
chart" - true, validated, accepted - and Products & Services, the section that defines the
whole revenue engine, shipped with no figure at all. A census of the 21 delivered builds on
this machine found that skip on EVERY single-line business, the wage chart absent entirely
on three others ("no roster role could be matched to an occupation"), and Luna Boutique
shipped at 10 of 15 with five self-certified absences nobody was told about.

skip_report names both: what was skipped, and which sections lost every figure they were
meant to have. Pinned over the real shapes, not Cedarbrook alone.
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

from writing_phase_v2 import completeness as CP  # noqa: E402

REGISTRY = json.load(open(os.path.join(
  ROOT, "python", "writing_phase_v2", "assets", "figure_registry.json"),
  encoding="utf-8"))["items"]


def _all_placed():
  return {i["id"]: {"placed": True} for i in REGISTRY}


def _absent(report, ident, reason):
  report[ident] = {"placed": False, "reason": reason}
  return report


class ASkipIsNamed(unittest.TestCase):

  def test_a_clean_build_reports_nothing(self):
    skipped, gaps = CP.skip_report(REGISTRY, _all_placed())
    self.assertEqual(skipped, [])
    self.assertEqual(gaps, [])

  def test_cedarbrook_the_products_section_is_named(self):
    """The real 09917eac shape: two skips, one of which empties a section."""
    rep = _absent(_all_placed(), "revenue_by_line",
                  "single line of business - the figure would repeat the revenue chart")
    rep = _absent(rep, "debt_schedule", "data condition not met (all-empty table)")
    skipped, gaps = CP.skip_report(REGISTRY, rep)
    self.assertEqual({s["id"] for s in skipped}, {"revenue_by_line", "debt_schedule"})
    self.assertEqual([g["section"] for g in gaps], ["products_and_services"])

  def test_a_skipped_table_never_empties_a_section_of_figures(self):
    """debt_schedule is a TABLE. The financial plan keeps its figures, so it is
    not a gap - a section that was never meant to carry a figure cannot lose one."""
    rep = _absent(_all_placed(), "debt_schedule", "data condition not met (all-empty table)")
    skipped, gaps = CP.skip_report(REGISTRY, rep)
    self.assertEqual([s["id"] for s in skipped], ["debt_schedule"])
    self.assertEqual(gaps, [])

  def test_luna_boutique_five_skips_and_every_hollow_section(self):
    """The worst delivered build: 10 of 15, five self-certified absences."""
    rep = _all_placed()
    for ident, reason in [
      ("revenue_by_line", "single line of business - the figure would repeat the revenue chart"),
      ("industry_establishments_history", "no BDS establishment history for the trade group"),
      ("competitor_size_bands", "no bds_firm_size slice in the bundle"),
      ("capacity_vs_plan_y1", "no line carries weekly capacity and utilisation"),
      ("wage_positioning", "no roster role could be matched to an occupation"),
    ]:
      rep = _absent(rep, ident, reason)
    skipped, gaps = CP.skip_report(REGISTRY, rep)
    self.assertEqual(len(skipped), 5)
    named = {g["section"] for g in gaps}
    # staffing keeps headcount_payroll, so it is NOT hollow; the other four are
    self.assertIn("products_and_services", named)
    self.assertIn("market_and_industry", named)
    self.assertIn("competitive_landscape", named)
    self.assertIn("operations", named)
    self.assertNotIn("staffing_and_human_capital", named)

  def test_the_staffing_section_is_named_when_BOTH_its_figures_go(self):
    """Three delivered builds lost wage_positioning outright. If headcount_payroll
    ever goes with it, the section must be named - that is Nick's missing chart."""
    rep = _absent(_all_placed(), "wage_positioning",
                  "no roster role could be matched to an occupation")
    rep = _absent(rep, "headcount_payroll", "renderer had no roster")
    _skipped, gaps = CP.skip_report(REGISTRY, rep)
    self.assertIn("staffing_and_human_capital", {g["section"] for g in gaps})

  def test_a_reason_the_renderer_never_wrote_is_still_a_skip(self):
    """An item missing from the report entirely is not on the page either."""
    rep = _all_placed()
    rep.pop("cvp_year1")
    skipped, _gaps = CP.skip_report(REGISTRY, rep)
    self.assertIn("cvp_year1", {s["id"] for s in skipped})


if __name__ == "__main__":
  unittest.main()
