"""The capital-lease liability amortizes off the field intake actually writes.

CW-043, Halbrook Grounds Management (draft ecd0e148, 2026-08-24). The CW-041
field split (08-23) moved the lease SEED to capital_lease_balance but left the
principal AUTHOR in finmo_bridge reading initial_lease - None on new drafts -
so "Less: Principal Repayments" was authored all-zero and the engine consumed
it verbatim: closing balance frozen at 62,000 from stub through Q20, payment
equal to interest in every period, while the ROU asset depreciated cleanly to
zero. The app's own capital_lease_amortizes gate scored it -0.05
out_of_band_hard_fail and the plan shipped anyway.

The frozen-balance class was fixed once before, on Big_Shipper (6732816,
2026-07-13). This pins that the 07-13 design now rides the NEW field, through
the REAL production chain - build_python_model_input_json ->
apply_derived_driver_policies_to_model_input -> build_python_finmo_json - on
Halbrook's real captured intake payloads, not a restatement of the bridge.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, os.path.join(ROOT, "python")):
  if path not in sys.path:
    sys.path.insert(0, path)

from client_intake_and_finmo import finmo_bridge as fb  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "cw043_halbrook_inputs.json")


def _load_fixture():
  with open(FIXTURE, encoding="utf-8") as fh:
    return json.load(fh)


def _build(financials_json):
  fx = _load_fixture()
  ppe = float(financials_json.get("initial_assets") or 0.0)
  mij = fb.apply_derived_driver_policies_to_model_input(
    fb.build_python_model_input_json(
      business_facts=fx["business_facts"],
      ops_json=fx["operating_model_json"],
      people_json=fx["people_json"],
      financials_json=financials_json,
      financials_year1_json=fx["financials_year1_json"],
      marketing_model_json=fx["marketing_model_json"],
      forecast_starting_ppe=ppe,
      maintenance_rate=0.05,
    ))
  return mij


def _principal_row(mij):
  for row in (mij["sections"]["schedules"].get("rows") or []):
    if str(row.get("label") or "").strip() == "Less: Principal Repayments":
      return row
  raise AssertionError("Less: Principal Repayments row missing")


class TheAmortizerReadsTheNewFieldTests(unittest.TestCase):
  """Halbrook's exact intake state: capital_lease_balance=62000,
  initial_lease=None. Before the fix the principal row authored all-zero."""

  @classmethod
  def setUpClass(cls):
    cls.fin = _load_fixture()["financials_json"]
    assert cls.fin.get("capital_lease_balance") == 62000.0
    assert cls.fin.get("initial_lease") is None
    cls.mij = _build(dict(cls.fin))

  def test_principal_is_authored_nonzero(self):
    """The defect itself: the amortizer read initial_lease (None) and
    authored zero principal forever."""
    values = _principal_row(self.mij)["values"]
    live = values[1:]
    self.assertTrue(any(v > 0 for v in live),
                    "capital-lease principal authored all-zero: the "
                    "amortizer is not reading capital_lease_balance")

  def test_principal_amortizes_the_full_balance(self):
    """Straight-line over the ROU depreciation term: seed/20 per live
    quarter, so the obligation lands at zero IN STEP with the asset."""
    values = _principal_row(self.mij)["values"]
    seed = self.mij["sections"]["schedules"]["lease_opening_balance_seed"]
    self.assertEqual(seed, 62000.0)
    self.assertEqual(values[0], 0.0, "stub period never schedules a payment")
    for v in values[1:]:
      self.assertAlmostEqual(v, 3100.0, places=6)
    self.assertAlmostEqual(sum(values), seed, places=2)

  def test_the_engine_lands_the_liability_at_zero_with_the_asset(self):
    """Through the real engine: Q20 closing 0, and the app's own
    capital_lease_amortizes hard gate - the one that fired FAIL on the
    shipped Halbrook run - now passes on the same business."""
    finmo = fb.build_python_finmo_json(model_input_json=self.mij)
    rows = finmo["quarter_rows"]
    self.assertEqual(rows[1]["lease_opening_balance_total"], 62000.0)
    self.assertAlmostEqual(rows[20]["lease_closing_balance_total"], 0.0, places=2)
    self.assertAlmostEqual(rows[20]["right_of_use_asset"], 0.0, places=2)
    from client_intake_and_finmo.post_intake_realism.formulas import (
      _formula_trajectory_capital_lease_amortizes as gate,
    )
    value = gate(model_input_json=self.mij, finmo_json=finmo, quarter_index=None)
    self.assertGreaterEqual(value, 0.0,
                            "capital_lease_amortizes still failing")


class LegacyDraftsKeepTheOldPathTests(unittest.TestCase):
  """~1,780 pre-CW-041 drafts stored a monthly payment in initial_lease and
  nothing in capital_lease_balance. Their x12 seed and its amortization must
  keep working exactly as the 07-13 design shipped them."""

  def test_initial_lease_still_amortizes_via_the_fallback(self):
    fin = copy.deepcopy(_load_fixture()["financials_json"])
    fin.pop("capital_lease_balance", None)
    fin["initial_lease"] = 1200.0
    mij = _build(fin)
    seed = mij["sections"]["schedules"]["lease_opening_balance_seed"]
    self.assertEqual(seed, 14400.0, "legacy x12 seed changed")
    values = _principal_row(mij)["values"]
    self.assertEqual(values[0], 0.0)
    for v in values[1:]:
      self.assertAlmostEqual(v, 720.0, places=6)

  def test_no_lease_authors_no_principal(self):
    fin = copy.deepcopy(_load_fixture()["financials_json"])
    fin.pop("capital_lease_balance", None)
    fin.pop("initial_lease", None)
    mij = _build(fin)
    self.assertEqual(sum(_principal_row(mij)["values"]), 0.0)


if __name__ == "__main__":
  unittest.main()
