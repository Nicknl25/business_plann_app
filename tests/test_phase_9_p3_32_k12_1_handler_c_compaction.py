"""Phase 9 P3.32 K12.1 (G-B2) — Handler C context compaction.

Verifies the compaction shrinks Handler C's GPT context without dropping
any field GPT consults, and that the initial-prompt serialization is
compact (no indentation whitespace). Load-bearing fields
(feasibility_mapping, stage_ramp_contract) must survive verbatim.
"""

from __future__ import annotations

import json
import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


def _sample_context():
  return {
    "oews_title_catalog": {
      "candidate_count": 2,
      "title_candidates": [
        {"occ_title": "Pilots", "occ_code": "53-2011", "annual_wage": 160000, "wage_source": "oews_median"},
        {"occ_title": "Flight Attendants", "occ_code": "53-2031", "annual_wage": 62000, "wage_source": "oews_median"},
      ],
    },
    "payroll_capacity_grid": [
      {"q": 1, "total_structural_capacity_units": 218400.0, "rule": "Context only. GPT selects the mix."},
      {"q": 2, "total_structural_capacity_units": 218400.0, "rule": "Context only. GPT selects the mix."},
    ],
    "revenue_driver_context": {
      "horizon_quarters": 20,
      "quarter_rows": [
        {"quarter_index": 1, "computed_revenue_from_model_input": 22113000, "finmo_revenue": 22113000,
         "product_rows": [{"slot_key": "lob_1_product_1", "capacity_units": 218400, "unit_price": 135.0, "utilization": 0.75}]},
      ],
    },
    "payroll_feasibility_mapping": {"rows": [{"lever_id": "revenue::*::*::Capacity", "repair_direction_rules": {"x": 1}}]},
    "stage_ramp_contract": {"rev_max": 0.06, "cogs_max": 0.8},
  }


class HandlerCCompactionTest(unittest.TestCase):
  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import schedule as sched  # noqa: WPS433
    self.sched = sched

  def test_catalog_drops_wage_source_keeps_decision_fields(self) -> None:
    out = self.sched._compact_payroll_gpt_context(_sample_context())
    for c in out["oews_title_catalog"]["title_candidates"]:
      self.assertNotIn("wage_source", c)
      self.assertIn("occ_title", c)
      self.assertIn("occ_code", c)
      self.assertIn("annual_wage", c)

  def test_capacity_grid_rule_hoisted_once(self) -> None:
    out = self.sched._compact_payroll_gpt_context(_sample_context())
    self.assertIn("payroll_capacity_grid_note", out)
    self.assertTrue(out["payroll_capacity_grid_note"].startswith("Context only"))
    for row in out["payroll_capacity_grid"]:
      self.assertNotIn("rule", row)
      self.assertIn("total_structural_capacity_units", row)  # data preserved

  def test_revenue_driver_drops_product_rows_keeps_revenue(self) -> None:
    out = self.sched._compact_payroll_gpt_context(_sample_context())
    for row in out["revenue_driver_context"]["quarter_rows"]:
      self.assertNotIn("product_rows", row)
      self.assertIn("computed_revenue_from_model_input", row)
      self.assertIn("finmo_revenue", row)

  def test_load_bearing_fields_preserved_verbatim(self) -> None:
    base = _sample_context()
    fm_before = json.dumps(base["payroll_feasibility_mapping"], sort_keys=True)
    sr_before = json.dumps(base["stage_ramp_contract"], sort_keys=True)
    out = self.sched._compact_payroll_gpt_context(base)
    self.assertEqual(json.dumps(out["payroll_feasibility_mapping"], sort_keys=True), fm_before)
    self.assertEqual(json.dumps(out["stage_ramp_contract"], sort_keys=True), sr_before)

  def test_compaction_reduces_size(self) -> None:
    base = _sample_context()
    before = len(json.dumps(base))
    after = len(json.dumps(self.sched._compact_payroll_gpt_context(_sample_context())))
    self.assertLess(after, before)

  def test_defensive_non_dict(self) -> None:
    self.assertEqual(self.sched._compact_payroll_gpt_context(None), None)
    self.assertEqual(self.sched._compact_payroll_gpt_context([1, 2]), [1, 2])

  def test_initial_prompt_is_compact_json(self) -> None:
    from client_intake_and_finmo.post_intake_headcount import tool_calling_session as tcs  # noqa: WPS433
    ctx = _sample_context()
    prompt = tcs._build_initial_user_prompt(request_context=ctx, external_seed_text=None)
    # Compact separators -> no ",\n      " indentation blocks from indent=2.
    self.assertNotIn('  "occ_title"', prompt)
    self.assertIn('"occ_title":"Pilots"', prompt)


if __name__ == "__main__":
  unittest.main()
