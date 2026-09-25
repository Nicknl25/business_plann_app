"""Nick 2026-09-25 rulings (b) and (c), pinned as properties.

(b) A rate written PER QUARTER is never printed as an annual rate. The
    delivered plan said "2.25% per quarter-cycle ... existing facility
    terms carried forward" on a 9% loan.

(c) A judged margin band speaks for its own quarter and after. The Q11
    band was reporting years 1 and 2 - which END BEFORE Q11 - as out of
    band, for margins the business was never asked to hit yet.

Both are properties over varied shapes, not one business: any rate, any
band, any margin path (Nick: every fix is for any business).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "python",
                             "client_intake_and_finmo"))

from writing_phase_v2 import bundle as B  # noqa: E402
from writing_phase_v2 import qa as QA  # noqa: E402


def _schedule_row(quarterly):
  """What schedule.py actually writes: the PER-QUARTER rate, twice."""
  return {"quarter_index": 1, "date": "2026-01-01", "opening_debt": 800000,
          "actual_debt_issuance": 0, "actual_debt_repayment": 20000,
          "interest_expense": 18000, "closing_debt": 780000,
          "interest_rate": quarterly, "annual_interest_rate": quarterly}


def _v1(margins, band_low, band_high, quarterly_rate=0.0225):
  return {
      "meta": {"business_name": "Pin & Co", "draft_id": "pin",
               "planning_run_id": "pin", "bundle_prepared": "2026-09-25",
               "industry_code_on_record": "541611"},
      "record": {
          "financials": {
              "_coherence": {"margin_band_judgment": {
                  "q11": {"low": band_low, "high": band_high},
              }},
              "annual_interest_payment": 72000,
              "total_debt_outstanding": 800000,
          },
          "financials_year1": {},
          "people": {},
      },
      "model": {
          "annual": [{"revenue": 1000000.0, "ebitda": 1000000.0 * m,
                      "payroll": 200000} for m in margins],
          "debt_schedule": [B._debt_row(_schedule_row(quarterly_rate))],
          "quarter_totals": [],
      },
      "derived": {},
  }


def _kinds(v1):
  rep = QA.build_qa_report(v1, {})
  return {f["kind"]: f.get("what", "") for f in rep.get("findings", [])}


class BandAndRate(unittest.TestCase):

  def test_b_the_bundle_names_the_quarterly_rate_quarterly(self):
    """Any rate, any business: what the author reads as annual IS annual."""
    for annual in (0.06, 0.09, 0.1125, 0.045, 0.14):
      row = B._debt_row(_schedule_row(round(annual / 4.0, 6)))
      self.assertAlmostEqual(row["annual_interest_rate"], annual, places=5,
                             msg="annual_interest_rate is not the %s annual "
                                 "rate" % annual)
      self.assertAlmostEqual(row["quarterly_interest_rate"], annual / 4.0,
                             places=5)
      self.assertGreater(row["annual_interest_rate"],
                         row["quarterly_interest_rate"])

  def test_b_a_missing_rate_stays_missing(self):
    row = _schedule_row(None)
    row["annual_interest_rate"] = None
    out = B._debt_row(row)
    self.assertIsNone(out["annual_interest_rate"])
    self.assertIsNone(out["quarterly_interest_rate"])

  def test_b_the_loan_rate_finding_compares_annual_to_annual(self):
    """9% stated, 9% carried (0.0225/qtr) - agreement, not a 4x finding."""
    k = _kinds(_v1([0.15, 0.16, 0.15, 0.16, 0.17], 0.12, 0.20,
                   quarterly_rate=0.0225))
    self.assertNotIn("loan_rate", k, k.get("loan_rate"))

    # a real disagreement still fires: 9% stated, 4% carried
    what = _kinds(_v1([0.15, 0.16, 0.15, 0.16, 0.17], 0.12, 0.20,
                      quarterly_rate=0.01)).get("loan_rate")
    self.assertTrue(what and "4.00%" in what and "9.00%" in what, what)

  def test_c_a_ramping_year_one_is_not_judged_against_the_q11_band(self):
    """Years 1-2 end before Q11. A thin ramp year is not a band finding."""
    k = _kinds(_v1([0.02, 0.06, 0.15, 0.16, 0.17], 0.12, 0.20))
    self.assertNotIn("projections_vs_judged_band", k,
                     k.get("projections_vs_judged_band"))

  def test_c_the_target_year_and_after_are_still_judged(self):
    """Year 3 contains Q11 - it answers to the band, and so do 4 and 5."""
    what = _kinds(_v1([0.15, 0.16, 0.02, 0.16, 0.17], 0.12,
                      0.20)).get("projections_vs_judged_band")
    self.assertTrue(what and "Year-3" in what, what)
    self.assertNotIn("Year-1", what)
    self.assertNotIn("Year-2", what)

    what = _kinds(_v1([0.15, 0.16, 0.15, 0.40, 0.17], 0.12,
                      0.20)).get("projections_vs_judged_band")
    self.assertTrue(what and "Year-4" in what, what)

  def test_c_the_operator_signal_reads_only_judged_years(self):
    """'above band in EVERY year' is not defeated by an unjudged year."""
    k = _kinds(_v1([0.02, 0.05, 0.35, 0.36, 0.37], 0.12, 0.20))
    self.assertIn("margins_above_band_every_year", k, k)


if __name__ == "__main__":
  unittest.main()
