"""A COIN FLIP ON EVERY MULTI-LINE BUSINESS IS NOT A GATE (Nick 2026-09-12).

Castellane Precision Castings, 03:20:42: the quarter-grid mapping contract
raised on cost of goods sold in quarter 6 - FINMO 1,316,052 against the
formula's 1,316,054 - and the run died with no workbook and no plan.
Thistledown, three lines, had passed the same gate an hour earlier by luck.

FINMO builds COGS as the sum over lines of line_revenue x line_percent.
The contract recomputes it as total_revenue x blended_percent. Every one of
those percents is serialized at six decimals, so the two arithmetics can
differ by up to revenue x one millionth, plus a dollar of integer rounding
across the two sides. The old tolerance was a fixed one dollar. The new one
is derived from that arithmetic: 1 + |revenue| x 1e-6.
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

from financial_model_engine import finmo_model as fm  # noqa: E402
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import fail_fast as ff  # noqa: E402
from client_intake_and_finmo.fail_fast.common import FailFastError  # noqa: E402

CASTELLANE_REVENUE = 5_932_000.0
COGS_RATIO = 0.221857          # six decimals, as every model-input ratio is stored


class TheBoundIsDerivedFromTheArithmetic(unittest.TestCase):
  def test_one_dollar_floor_plus_revenue_times_the_ratio_quantum(self):
    self.assertEqual(fm.MODEL_INPUT_RATIO_DECIMALS, 6)
    self.assertEqual(fm.mapping_ratio_tolerance(0), 1.0)
    self.assertAlmostEqual(fm.mapping_ratio_tolerance(CASTELLANE_REVENUE), 1.0 + 5.932, places=6)
    self.assertAlmostEqual(fm.mapping_ratio_tolerance(-CASTELLANE_REVENUE), 1.0 + 5.932, places=6)
    self.assertEqual(fm.mapping_ratio_tolerance(None), 1.0)
    self.assertEqual(fm.mapping_ratio_tolerance("garbage"), 1.0)

  def test_a_two_dollar_difference_on_a_six_million_quarter_is_inside_the_bound(self):
    self.assertLess(2.0, fm.mapping_ratio_tolerance(CASTELLANE_REVENUE))

  def test_a_real_miss_is_still_outside_it(self):
    self.assertGreater(50.0, fm.mapping_ratio_tolerance(CASTELLANE_REVENUE))


def _run_gate(finmo_cogs: float):
  """Drive the REAL mapping validator on one COGS row, one quarter, with the
  SQL mapping table and the horizon lookup replaced by the Castellane
  shape. No stand-in comparator: the gate under test is the gate that ran."""
  expected = ff.compute_revenue_times_ratio(CASTELLANE_REVENUE, COGS_RATIO)
  mapping_rows = [{
    "lever_id": "expenses::Cost of Goods Sold",
    "model_input_field": "values",
    "financial_model_field": "finmo_json.quarter_rows[*].cogs",
    "validation_formula_key": "finmo_equals_revenue_times_model_input_ratio",
    "required_when_key": "revenue_positive",
    "allow_zero": False,
  }]
  model_input_json = {"sections": {"expenses": [
    {"lever_id": "expenses::Cost of Goods Sold", "label": "Cost of Goods Sold",
     "values": [COGS_RATIO, COGS_RATIO]},
  ]}}
  finmo_json = {"quarter_rows": [
    {"quarter_index": 1, "revenue": CASTELLANE_REVENUE, "cost_of_goods_sold": float(finmo_cogs)},
  ]}
  import client_intake_and_finmo.post_intake_mapping as pim
  with mock.patch.object(pim, "post_intake_driver_formula_contract_rows", return_value=mapping_rows), \
       mock.patch.object(pim, "post_intake_contract_forecast_horizon_quarter_count", return_value=1):
    ff.assert_post_intake_mapping_formula_application_integrity(
      model_input_json=model_input_json, finmo_json=finmo_json, stage="test")
  return expected


class TheGateThatKilledCastellane(unittest.TestCase):
  def test_two_dollars_of_rounding_on_a_six_million_quarter_passes(self):
    expected = ff.compute_revenue_times_ratio(CASTELLANE_REVENUE, COGS_RATIO)
    _run_gate(expected - 2)   # the exact Castellane shape: FINMO two below the formula
    _run_gate(expected + 2)

  def test_a_fifty_dollar_miss_still_fails_and_names_the_bound(self):
    expected = ff.compute_revenue_times_ratio(CASTELLANE_REVENUE, COGS_RATIO)
    with self.assertRaises(FailFastError) as ctx:
      _run_gate(expected - 50)
    v = (getattr(ctx.exception, "details", None) or {}).get("violations") or []
    self.assertEqual(len(v), 1)
    self.assertEqual(v[0]["field"], "cost_of_goods_sold")
    self.assertAlmostEqual(v[0]["tolerance"], round(fm.mapping_ratio_tolerance(CASTELLANE_REVENUE), 2), places=2)

  def test_both_ratio_sites_use_the_derived_bound_not_the_fixed_dollar(self):
    for rel in ("python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py",
                "python/client_intake_and_finmo/post_intake_runtime_validation/balance_sheet_driver_validation.py"):
      src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
      i = src.find('validation_key == "finmo_equals_revenue_times_model_input_ratio"')
      self.assertGreater(i, 0, rel)
      branch = src[i:i + 900]
      self.assertIn("mapping_ratio_tolerance(", branch, rel)
      self.assertNotIn("> MAPPING_FORMULA_INT_TOLERANCE", branch, rel)


if __name__ == "__main__":
  unittest.main()
