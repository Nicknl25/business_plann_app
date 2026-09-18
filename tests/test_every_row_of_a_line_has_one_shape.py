"""Every product row of a line carries the same capacity key set.

Vasquez-Lindqvist Timber Frames ec2da9c7, replay turn 21, 2026-09-13. After a
fix that carried key PRESENCE forward, the store read by key presence showed:

    row 0  13 keys - week / period / periods PRESENT = null
    row 1   8 keys - week / period / periods ABSENT
    row 2   9 keys - week / period ABSENT, operating_periods_per_year PRESENT = 0

Worse than before. Carrying presence forward only stops a key being ERASED; a
row that never had the key has nothing to carry, so the shapes can never
converge that way. The pin for that fix passed because its fixture started every
row WITH the keys - which the live draft did not.

Cowork reads the store with hasOwnProperty, and so do my own store checks:
absent-versus-null is the distinction that found the original defect. So the
row normaliser gives every product row the same capacity key set, present and
null where nothing is known, and a periods figure of 0 - which means nothing a
business can have - is treated as missing rather than stored as a value.

These pins use the LIVE draft's shape, not an idealised one.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_CAPACITY_KEYS = ("units_per_week_capacity", "units_per_period_capacity",
                  "operating_periods_per_year")


def _live_draft_shape():
  """Exactly what the store held at 21:43:38."""
  home = {"product_name": "Custom residential timber frames", "unit_cadence": "contract",
          "concurrent_capacity_units": 6, "annual_turns_per_year": 34 / 6,
          "utilization_rate": 26 / 34, "units_per_week_capacity": None,
          "units_per_period_capacity": None, "operating_periods_per_year": None}
  row1 = {"product_name": "Commercial timber structures", "unit_cadence": "contract",
          "utilization_rate": None}
  row2 = {"product_name": "Shipped frame kits for builders", "unit_cadence": "contract",
          "utilization_rate": None, "operating_periods_per_year": 0}
  return {"lob_models": [{"lob_name": "Primary line of business",
                          "products": [home, row1, row2]}]}


class _Normalised(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import _normalize_ops_capacity_compat  # type: ignore

    self.rows = _normalize_ops_capacity_compat(_live_draft_shape())["lob_models"][0]["products"]


class EveryRowCarriesTheCapacityKeys(_Normalised):
  def test_every_row_has_every_capacity_key(self):
    for i, row in enumerate(self.rows):
      for k in _CAPACITY_KEYS:
        self.assertIn(k, row, "row %d has no %s - absent is not null" % (i, k))

  def test_the_shape_is_one_shape_and_the_right_one(self):
    """Not merely matching: an earlier version passed when every row was
    uniformly WITHOUT the keys."""
    shapes = {tuple(k in r for k in _CAPACITY_KEYS) for r in self.rows}
    self.assertEqual(shapes, {(True, True, True)})

  def test_nothing_unknown_is_invented(self):
    for row in self.rows[1:]:
      for k in _CAPACITY_KEYS:
        self.assertIsNone(row[k], "a value appeared where nothing was known")


class AZeroPeriodsFigureIsNotAValue(_Normalised):
  def test_zero_periods_becomes_missing(self):
    self.assertIsNone(self.rows[2]["operating_periods_per_year"],
                      "zero operating periods a year is stored as though it were a fact")


class TheHomedRowIsUntouched(_Normalised):
  def test_row_0_still_holds_the_confirmed_values(self):
    row = self.rows[0]
    self.assertEqual(row["units_per_period_capacity"], 6)
    self.assertAlmostEqual(row["operating_periods_per_year"], 34 / 6, 12)
    self.assertAlmostEqual(row["utilization_rate"], 26 / 34, 12)
    self.assertNotIn("_capacity_pair_refused", row)


class TheRootOfAMultiLineModelGainsNoFlatKeys(unittest.TestCase):
  """Materialising the key set belongs on PRODUCT ROWS. On a multi-line model
  a flat capacity key at the root has no line and is the thing A-113 drops."""

  def test_the_ops_root_does_not_sprout_capacity_keys(self):
    from api_handlers.intake_consult import _normalize_ops_capacity_compat  # type: ignore

    out = _normalize_ops_capacity_compat(_live_draft_shape())
    for k in _CAPACITY_KEYS:
      self.assertNotIn(k, out, "a flat %s appeared at the root of a multi-line model" % k)


if __name__ == "__main__":
  unittest.main(verbosity=2)
