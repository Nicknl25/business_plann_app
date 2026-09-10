"""The QA payroll/headcount checks are LAUNCH BANDS, not tie-outs
(Nick's ruling, 2026-09-10).

"Intake asks what people are paid NOW. That's an actual, and it belongs
in the stub - same as stated revenue. Q1 through Q20 is a FORECAST."
Verified on Bramblewood: FINMO stub Payroll = 113,499.99 = stated
454,000/4 to the cent, by construction (finmo_bridge payroll_total_year1
/ 4). The old payroll_gap check compared model Year-1 (a loaded forecast
number) to stated wages (an unloaded actual) with a 5% tie-out tolerance
and flagged every plan that hires; the old headcount check read
qt[0]["fte"], a key that does not exist, and had never fired at all.

Pinned here: (1) a forecast that RAMPS from an in-band launch produces
no finding; (2) a day-one step outside 0.70-1.30 of stated fires
payroll_launch_band computed from roster_q1 UNLOADED wages; (3) the
headcount band reads ending_fte (the real key) and fires only outside
the band AND >= 1 FTE off; (4) the Bramblewood shape (757,020 vs
454,000, FTE 9 vs 6) fires both.
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


def _v1(stated, roster_q1, q1_fte, heads, year1_payroll):
  return {
    "meta": {"industry_code_on_record": "621340", "business_name": "Pin PT",
             "draft_id": "d" * 32, "planning_run_id": "r" * 32,
             "bundle_prepared": "2026-09-10"},
    "record": {"financials": {"payroll_total_year1": stated,
                              "current_num_employees": heads},
               "financials_year1": {}},
    "model": {"annual": [{"payroll": year1_payroll, "revenue": 1.0,
                          "cost_of_goods_sold": 0.0, "marketing": 0.0,
                          "lease_rent": 0.0, "ebitda": 0.0}],
              "payroll": {"quarter_totals": [
                  {"quarter_index": 1, "ending_fte": q1_fte, "payroll": 0}],
                  "roster_q1": roster_q1},
              "debt_schedule": []},
    "derived": {},
  }


def _row(fte, wage):
  return {"quarter_index": 1, "ending_fte": fte, "annual_wage": wage}


def _kinds(v1):
  rep = build_qa_report(v1, {})
  return {f["kind"] for f in rep.get("findings", [])}


class PayrollLaunchBandTests(unittest.TestCase):
  def test_ramping_forecast_with_in_band_launch_is_clean(self):
    """Year-1 payroll 2x stated is NOT a finding when the launch ties -
    the forecast hiring through the year is the forecast's job."""
    kinds = _kinds(_v1(454000, [_row(6.0, 75666)], 6.0, 6, 908000))
    self.assertNotIn("payroll_launch_band", kinds)
    self.assertNotIn("headcount_launch_band", kinds)
    self.assertNotIn("payroll_gap", kinds)  # the old kind is gone

  def test_bramblewood_day_one_step_fires_both_bands(self):
    roster = [_row(1.0, 104000), _row(1.0, 118000), _row(1.0, 44190),
              _row(1.0, 44190), _row(1.0, 78000), _row(1.0, 78000),
              _row(3.0, 96880)]
    kinds = _kinds(_v1(454000, roster, 9.0, 6, 923572))
    self.assertIn("payroll_launch_band", kinds)
    self.assertIn("headcount_launch_band", kinds)

  def test_band_uses_unloaded_roster_wages_not_loaded_annual(self):
    """Launch exactly at stated with a loaded Year-1 22% higher: clean.
    (The old check compared the loaded number and false-fired.)"""
    kinds = _kinds(_v1(100000, [_row(2.0, 50000)], 2.0, 2, 122000))
    self.assertNotIn("payroll_launch_band", kinds)

  def test_headcount_band_small_team_grace(self):
    """Outside the ratio band but under 1 FTE of absolute difference:
    no finding (a 1-person shop modeled at 1.9 FTE is 1.9x but only 0.9
    FTE off - the absolute grace keeps tiny-team noise out)."""
    kinds = _kinds(_v1(100000, [_row(1.9, 52631)], 1.9, 1, 100000))
    self.assertNotIn("headcount_launch_band", kinds)

  def test_headcount_band_fires_outside_band_and_full_fte_off(self):
    kinds = _kinds(_v1(100000, [_row(3.0, 33333)], 3.0, 2, 100000))
    self.assertIn("headcount_launch_band", kinds)


if __name__ == "__main__":
  unittest.main()
