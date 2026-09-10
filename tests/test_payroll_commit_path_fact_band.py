"""The Q1 payroll fact band runs on EVERY lineage (Nick's ruling 2026-09-10).

The band existed and worked, but was wired only into the round-1
GPT-author retry loop - the SUPPLIED-contract path (the lineage most live
contracts take) committed without it, and Bramblewood 2f71e20d shipped a
day-one step at 1.67x the stated payroll through exactly that hole. Same
hole, same path: labor-scaling enforcement ran only where the round-1
anchor existed; the anchor is now computed for the supplied lineage too.

Pinned: (1) a supplied contract whose Q1 launch sits outside 0.70-1.30 of
stated current_payroll is REJECTED with q1_payroll_off_stated_fact;
(2) an in-band supplied contract commits (the band does not false-fire);
(3) the supplied lineage computes the anchor and invokes labor-scaling
enforcement when the business is labor-bound.
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

from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (  # noqa: E402
  set_payroll_schedule,
)


def _contract(q1_fte, q1_wage):
  return {
    "target_payroll_percent_of_revenue": 0.5,
    "payroll_headcount_grid": [
      {"quarter_index": 1, "oews_occ_title": "Physical Therapists",
       "starting_fte": 0.0, "hires": q1_fte, "ending_fte": q1_fte,
       "annual_wage": q1_wage},
    ],
  }


def _run(contract, stated, **extra):
  return set_payroll_schedule(
    conn=None, draft_id="d" * 32, planning_run_id="r" * 32,
    contract=contract,
    financials_json={"current_payroll": stated},
    business_facts={}, ops_json={}, people_json={},
    _validator=lambda payload: payload,
    _builder=lambda **kw: {"rows": [], "quarter_totals": []},
    **extra,
  )


class CommitPathFactBandTests(unittest.TestCase):
  def test_out_of_band_supplied_contract_is_rejected(self):
    """The Bramblewood shape: Q1 annualizes to 757,017 vs stated 454,000
    (1.67x) - the supplied lineage now rejects it with the fact code."""
    out = _run(_contract(9.0, 84113), 454000.0)
    self.assertFalse(out["accepted"])
    codes = [v.get("code") for v in out.get("violations") or []]
    self.assertIn("q1_payroll_off_stated_fact", codes)

  def test_in_band_supplied_contract_commits(self):
    out = _run(_contract(6.0, 75667), 454000.0)
    codes = [v.get("code") for v in out.get("violations") or []]
    self.assertNotIn("q1_payroll_off_stated_fact", codes)
    self.assertTrue(out["accepted"], out.get("violations"))

  def test_no_stated_payroll_means_no_fact_check(self):
    out = _run(_contract(9.0, 84113), 0.0)
    codes = [v.get("code") for v in out.get("violations") or []]
    self.assertNotIn("q1_payroll_off_stated_fact", codes)

  def test_supplied_lineage_runs_labor_scaling_enforcement(self):
    """The anchor is computed for the supplied lineage and, when the
    business is labor-bound, enforcement runs on the built payload."""
    calls = {}
    import client_intake_and_finmo.post_intake_headcount.schedule as sched

    def _fake_anchor(**kw):
      return {"labor_intensity_class": "high"}

    def _fake_enforce(payload, anchor, **kw):
      calls["enforced"] = True
      return {"applied": True}

    with mock.patch.object(sched, "compute_round1_payroll_anchor", _fake_anchor), \
         mock.patch.object(sched, "enforce_labor_scaling_on_payload", _fake_enforce):
      out = _run(_contract(6.0, 75667), 454000.0)
    self.assertTrue(out["accepted"], out.get("violations"))
    self.assertTrue(calls.get("enforced"),
                    "labor-scaling enforcement did not run on the supplied lineage")


if __name__ == "__main__":
  unittest.main()
