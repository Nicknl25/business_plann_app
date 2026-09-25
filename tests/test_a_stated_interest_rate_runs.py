"""Her own interest rate runs, for any business (Nick 2026-09-25).

"When the client states an interest rate, use it. When they don't, use the SBA
lookup as now. The lookup divides the annual rate by 4 because it's annual and
the model is quarterly - that part is right and stays. Make sure a client-stated
rate goes through the same quarterly structure."

8c58bcb4 made the bridge prefer her rate, and stamped it source "client_stated".
Two gates still refused anything but "sba_loan_7a_raw": the debt schedule RAISED
(schedule.py sba_forecast_interest_rate_policy) and the cash pass filed
cash_debt_interest_rate_policy_not_sba_backed. So every client who stated
interest AND debt lost the run. These pins hold, over varied shapes:
  1. a stated rate becomes the policy, annual = interest / debt, quarterly = /4,
     stamped with HER provenance, never the SBA's;
  2. no stated rate (or no debt) falls back to the SBA lookup, unchanged;
  3. both gates pass either source, at the same quarterly rate;
  4. any other source is still refused by both gates.
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
_EXTRA = os.path.join(ROOT, "python", "client_intake_and_finmo")
if _EXTRA not in sys.path:
  sys.path.append(_EXTRA)

import api_handlers.intake_consult as IC  # noqa: E402  (binds the cash runner's runtime dependencies)
from client_intake_and_finmo import finmo_bridge as FB  # noqa: E402
from client_intake_and_finmo.post_intake_debt_schedule import schedule as S  # noqa: E402

R = IC._post_intake_cash_runner
SBA_ANNUAL = 0.09
SBA_SOURCE = {"source": "sba_loan_7a_raw", "annual_rate_decimal": SBA_ANNUAL}

# (annual interest, debt outstanding) she might state - varied scale and rate.
STATED = [
  (100000, 1450000),   # Tollemache & Reyes, 6.90%
  (4200, 60000),       # a small shop, 7.00%
  (315000, 2500000),   # 12.60%
  (1800, 90000),       # 2.00%
]
NOT_STATED = [
  {"total_debt_outstanding": 500000},
  {"annual_interest_payment": 0, "total_debt_outstanding": 500000},
  {"annual_interest_payment": 25000},
  {},
]


def _model_input(financials):
  orig_sba = FB._sba_business_loan_interest_rate_and_source
  orig_apply = FB.apply_derived_driver_policies_to_model_input
  # The lookup reads the SBA table; the policy application downstream needs a
  # full revenue model. Neither is what these pins are about.
  FB._sba_business_loan_interest_rate_and_source = lambda *a, **k: (SBA_ANNUAL, dict(SBA_SOURCE))
  FB.apply_derived_driver_policies_to_model_input = lambda payload: payload
  try:
    return FB.build_python_model_input_json(
      business_facts={"business_name": "Any Business"},
      ops_json={},
      people_json={},
      financials_json=dict(financials, initial_assets=250000),
      financials_year1_json={},
      marketing_model_json={},
      forecast_starting_ppe=250000.0,
      maintenance_rate=0.02,
    )
  finally:
    FB._sba_business_loan_interest_rate_and_source = orig_sba
    FB.apply_derived_driver_policies_to_model_input = orig_apply


def _policy(model_input):
  return model_input["derived_driver_policies"]["debt_interest_rate_policy"]


def _cash_rate_errors(model_input):
  out = R._validate_cash_strategy_post_pass(
    ops_json={},
    financials_json={},
    baseline_issue_ledger=[],
    candidate_model_input_json=model_input,
    candidate_finmo_json={},
    iteration=1,
  )
  return [
    str(item.get("error"))
    for item in (out.get("cash_contract_failures") or [])
    if isinstance(item, dict) and "interest_rate" in str(item.get("error"))
  ]


class StatedRateRuns(unittest.TestCase):

  def test_a_stated_rate_is_the_policy_and_carries_her_provenance(self):
    for interest, debt in STATED:
      with self.subTest(interest=interest, debt=debt):
        pol = _policy(_model_input({"annual_interest_payment": interest, "total_debt_outstanding": debt}))
        annual = round(interest / debt, 6)
        self.assertEqual(pol["source_detail"]["source"], "client_stated")
        self.assertEqual(pol["driver_source"], "client_stated")
        self.assertNotIn("sba", pol["policy_version"])
        self.assertEqual(pol["annual_rate_decimal"], annual)
        self.assertEqual(pol["quarterly_rate_decimal"], round(interest / debt / 4.0, 6))

  def test_no_stated_rate_falls_back_to_the_sba_lookup(self):
    for fin in NOT_STATED:
      with self.subTest(financials=fin):
        pol = _policy(_model_input(fin))
        self.assertEqual(pol["source_detail"]["source"], "sba_loan_7a_raw")
        self.assertEqual(pol["driver_source"], "sba_loan_7a_raw")
        self.assertEqual(pol["policy_version"], "sba_7a_business_loan_interest_rate_v1")
        self.assertEqual(pol["annual_rate_decimal"], SBA_ANNUAL)
        self.assertEqual(pol["quarterly_rate_decimal"], round(SBA_ANNUAL / 4.0, 6))

  def test_both_gates_pass_either_source_at_the_quarterly_rate(self):
    cases = [{"annual_interest_payment": i, "total_debt_outstanding": d} for i, d in STATED] + NOT_STATED
    for fin in cases:
      with self.subTest(financials=fin):
        mi = _model_input(fin)
        pol = _policy(mi)
        gated = S.sba_forecast_interest_rate_policy(mi)
        self.assertEqual(gated["quarterly_rate_decimal"], pol["quarterly_rate_decimal"])
        self.assertEqual(_cash_rate_errors(mi), [])

  def test_any_other_source_is_still_refused(self):
    for bad in ("", "judged", "fallback_default"):
      with self.subTest(source=bad):
        mi = _model_input({"annual_interest_payment": 100000, "total_debt_outstanding": 1450000})
        _policy(mi)["source_detail"]["source"] = bad
        with self.assertRaisesRegex(RuntimeError, "debt_schedule_interest_rate_policy_not_sba_backed"):
          S.sba_forecast_interest_rate_policy(mi)
        self.assertIn("cash_debt_interest_rate_policy_not_sba_backed", _cash_rate_errors(mi))


if __name__ == "__main__":
  unittest.main()
