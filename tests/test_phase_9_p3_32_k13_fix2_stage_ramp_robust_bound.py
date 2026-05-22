"""Phase 9 P3.32 K13 Fix 2 (G-B5) — stage_ramp builder robust-bound +
principled cogs schema widening.

Root cause: the deterministic builder mapped NAICS cohort benchmark_max
directly onto contract cost-ratio maxes; for high-cost / artifact
cohorts that exceeds the canonical economic envelope (cogs 1.0 from a
distressed 4-firm trucking cohort; marketing 0.53 / rd 0.64 from
misclassification) -> invalid contract -> B5. The robust-bound caps each
field to the registry envelope; cogs_max ceiling widened 0.95 -> 0.97
(3% min gross margin) to admit genuine high-COGS sectors.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class StageRampRobustBoundTest(unittest.TestCase):
  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_contracts import runner as R  # noqa: WPS433
    self.R = R

  def test_robust_bound_caps_distressed_cogs_to_schema(self) -> None:
    contract = {
      "utilization_high_watermark": 1.5,
      "quarter_ramp_grid": [
        {"q": 1, "cogs_max": 1.0, "marketing_max": 0.53, "rd_max": 0.64},
        {"q": 2, "cogs_max": 1.0, "marketing_max": 0.53, "rd_max": 0.64},
      ],
    }
    out = self.R.robust_bound_stage_ramp_contract(contract)
    for row in out["quarter_ramp_grid"]:
      self.assertLessEqual(row["cogs_max"], 0.97)   # widened cogs ceiling
      self.assertLessEqual(row["marketing_max"], 0.40)  # sound cap, not widened
      self.assertLessEqual(row["rd_max"], 0.50)         # sound cap, not widened
    self.assertLessEqual(out["utilization_high_watermark"], 0.98)

  def test_schema_cogs_ceiling_is_0_97(self) -> None:
    ranges = self.R._stage_ramp_schema_field_ranges()
    self.assertIn("cogs_max", ranges)
    self.assertEqual(ranges["cogs_max"][1], 0.97)
    # Other cost-ratio caps remain economically sound (not widened).
    self.assertEqual(ranges["marketing_max"][1], 0.40)
    self.assertEqual(ranges["rd_max"][1], 0.50)

  def test_robust_bound_preserves_in_range_values(self) -> None:
    contract = {"quarter_ramp_grid": [{"q": 1, "cogs_max": 0.84, "marketing_max": 0.08}]}
    out = self.R.robust_bound_stage_ramp_contract(contract)
    self.assertEqual(out["quarter_ramp_grid"][0]["cogs_max"], 0.84)
    self.assertEqual(out["quarter_ramp_grid"][0]["marketing_max"], 0.08)

  def test_robust_bound_defensive_non_dict(self) -> None:
    self.assertEqual(self.R.robust_bound_stage_ramp_contract(None), None)


if __name__ == "__main__":
  unittest.main()
