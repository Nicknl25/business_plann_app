"""QA judged-band check covers all five years + the operator signal
(Nick's ruling 4, 2026-09-10).

The judged EBITDA ceiling deliberately does not bind the build (the
costs are the client's own - the lean-practice ruling); the ceiling is
therefore a REPORT, and the report must be complete: Bright Smiles
cleared the band in every year (23.1/27.4/27.6/29.2/27.9 vs 10-22 and
15-25) and the Y1-only check reported one year. Years 1-3 answer to the
Q11 band, 4-5 to Q20. Above band in EVERY year is additionally the
signal: lean costs or missing ones (the Thornfield $84k shape).
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

from writing_phase_v2.qa import build_qa_report  # noqa: E402


def _v1(margins, q11=(0.10, 0.22), q20=(0.15, 0.25)):
  annual = [{"year": 2027 + i, "revenue": 1_000_000,
             "ebitda": 1_000_000 * m} for i, m in enumerate(margins)]
  return {
    "meta": {"business_name": "T", "draft_id": "d", "planning_run_id": "r",
             "bundle_prepared": "now"},
    "record": {"financials": {"_coherence": {"margin_band_judgment": {
        "q11": {"low": q11[0], "high": q11[1]},
        "q20": {"low": q20[0], "high": q20[1]}}}},
        "financials_year1": {}},
    "model": {"annual": annual, "payroll": {"quarter_totals": []}},
    "derived": {},
  }


def _kinds(v1):
  rep = build_qa_report(v1, {"groups": [], "record_code_fits": True})
  return {f["kind"]: f["what"] for f in rep["findings"]}


class JudgedBandAllYearsTests(unittest.TestCase):
  def test_every_year_above_fires_both_findings(self):
    kinds = _kinds(_v1([0.231, 0.274, 0.276, 0.292, 0.279]))
    self.assertIn("projections_vs_judged_band", kinds)
    self.assertIn("Year-4", kinds["projections_vs_judged_band"])
    self.assertIn("margins_above_band_every_year", kinds)
    self.assertIn("lean costs or missing ones",
                  kinds["margins_above_band_every_year"])

  def test_years_4_and_5_answer_to_the_q20_band(self):
    """24% is above the Q11 band (22 ceiling) but inside Q20's (25):
    legal in year 4, a finding in year 2."""
    kinds = _kinds(_v1([0.15, 0.16, 0.17, 0.24, 0.24]))
    self.assertNotIn("projections_vs_judged_band", kinds)
    kinds2 = _kinds(_v1([0.15, 0.24, 0.17, 0.20, 0.20]))
    self.assertIn("Year-2", kinds2.get("projections_vs_judged_band", ""))

  def test_in_band_everywhere_is_silent(self):
    kinds = _kinds(_v1([0.12, 0.15, 0.18, 0.20, 0.22]))
    self.assertNotIn("projections_vs_judged_band", kinds)
    self.assertNotIn("margins_above_band_every_year", kinds)

  def test_one_year_below_is_a_finding_but_not_the_signal(self):
    kinds = _kinds(_v1([0.05, 0.15, 0.18, 0.20, 0.22]))
    self.assertIn("Year-1", kinds.get("projections_vs_judged_band", ""))
    self.assertNotIn("margins_above_band_every_year", kinds)


if __name__ == "__main__":
  unittest.main()
