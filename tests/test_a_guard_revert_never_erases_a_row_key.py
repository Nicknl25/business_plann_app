"""A guard that reverts a write on a product row keeps the key.

Vasquez-Lindqvist Timber Frames ec2da9c7, replay turn 23, 2026-09-13. After every
product row was given the same capacity key set, row 2 still came back with
units_per_week_capacity and units_per_period_capacity ABSENT. Reproduced locally
and matched the store exactly:

  1. The consultant's snapshot broadcast 0.0 into week and period across rows.
  2. The multi-line guard restores unnamed rows - "a restore to nothing removes
     the field" - but treated row 2 ("shipped FRAME kits") as named, because the
     client said "a frame takes about ten weeks". So row 2's 0.0 stood.
  3. The consultant door normalised. Materialising the key set is a no-op on keys
     that already exist, so row 2 left holding 0.0.
  4. THEN, at line 20674, _guard_underivable_ops_lever_writes ran - after the
     normalisation - saw a zero the client never said, found no prior value to
     restore, and did node_after.pop(leaf, None).

Two guards, one sentence in both: a revert to nothing removes the field. On a
product row that is an erasure - absent is not null, and it is the distinction
that found the original defect. So on product rows a revert to nothing leaves
the key present and null.

At the ops ROOT the lever guard still pops: on a multi-line model a flat
capacity key at the root has no line, and that is what A-113 exists to prevent.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_MSG = ("Six. That's the most the shop will hold, and we're usually running five or six. "
        "A frame takes about ten weeks from design through to raising it. Over a year that "
        "works out around 26 of them, and 34 would be flat out. We can't go past six at once "
        "whatever the demand, that's the building.")
_CAP = ("units_per_week_capacity", "units_per_period_capacity", "operating_periods_per_year")


def _turn21_store():
  home = {"product_name": "Custom residential timber frames", "unit_cadence": "contract",
          # FOLDED (2026-09-18): the store holds her six and her turns in the
          # canonical slots on a contract row.
          "utilization_rate": 26 / 34, "units_per_week_capacity": None,
          "units_per_period_capacity": 6, "operating_periods_per_year": 34 / 6}
  r1 = {"product_name": "Commercial timber structures", "unit_cadence": "contract",
        "utilization_rate": None}
  r2 = {"product_name": "Shipped frame kits for builders", "unit_cadence": "contract",
        "utilization_rate": None, "operating_periods_per_year": 0}
  return {"lob_models": [{"lob_name": "Primary line of business", "products": [home, r1, r2]}]}


def _zero_broadcast_snapshot():
  rows = [{"product_name": n, "unit_cadence": "contract", "units_per_week_capacity": 0.0,
           "units_per_period_capacity": 0.0, "operating_periods_per_year": 0.0}
          for n in ("Custom residential timber frames", "Commercial timber structures",
                    "Shipped frame kits for builders")]
  rows[0].update({"units_per_week_capacity": 6, "units_per_period_capacity": 6,
                  "operating_periods_per_year": None})
  return {"lob_models": [{"lob_name": "Primary line of business", "products": rows}]}


class TheRealSequenceKeepsEveryRowKey(unittest.TestCase):
  """The consultant door, then the lever guard - line 20674's order."""

  def setUp(self):
    from api_handlers.intake_consult import (  # type: ignore
      _apply_model_ops_patch, _guard_underivable_ops_lever_writes,
    )

    before = _turn21_store()
    after = _apply_model_ops_patch(copy.deepcopy(before), _zero_broadcast_snapshot(),
                                   user_message=_MSG, draft_id="pin")
    out = _guard_underivable_ops_lever_writes(ops_before=copy.deepcopy(before), ops_after=after,
                                              user_message=_MSG, last_assistant="")
    self.rows = out["lob_models"][0]["products"]

  def test_every_row_keeps_every_capacity_key(self):
    for i, row in enumerate(self.rows):
      for k in _CAP:
        self.assertIn(k, row, "row %d lost %s after the lever guard" % (i, k))

  def test_row_0_still_holds_the_confirmed_values(self):
    row = self.rows[0]
    self.assertEqual(row["units_per_period_capacity"], 6)
    self.assertAlmostEqual(row["operating_periods_per_year"], 34 / 6, 12)
    self.assertAlmostEqual(row["utilization_rate"], 26 / 34, 12)


class TheLeverGuardKeepsRowKeysButNotRootKeys(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import _guard_underivable_ops_lever_writes  # type: ignore

    self.guard = _guard_underivable_ops_lever_writes

  def test_a_derivable_row_write_still_lands(self):
    before = {"lob_models": [{"products": [{"product_name": "a"}, {"product_name": "b"}]}]}
    after = copy.deepcopy(before)
    after["lob_models"][0]["products"][1]["units_per_period_capacity"] = 40.0
    out = self.guard(ops_before=before, ops_after=after, user_message="about 40 a month",
                     last_assistant="")
    self.assertEqual(out["lob_models"][0]["products"][1]["units_per_period_capacity"], 40.0)


class TheMultiLineGuardKeepsTheKeyItRestoresToNothing(unittest.TestCase):
  def test_a_capacity_broadcast_restored_to_nothing_leaves_the_key_null(self):
    """The first version of this pin used unit_price, and broke the Ardenwald
    pins - correctly. A row with no price normally has NO price key; making it
    null would create the asymmetry this exists to remove. Only the capacity
    keys every row carries (_ROW_SHAPE_KEYS) keep their key on a restore."""
    from api_handlers.intake_consult import _guard_multiline_ops_rows  # type: ignore

    prev = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "alpha"}, {"product_name": "bravo"}]}]}
    patch = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "alpha", "units_per_period_capacity": 977.0},
      {"product_name": "bravo", "units_per_period_capacity": 977.0}]}]}
    restored = _guard_multiline_ops_rows(prev, patch, "we can do some jobs")
    self.assertTrue(restored, "the broadcast signature was not detected")
    for row in patch["lob_models"][0]["products"]:
      self.assertIn("units_per_period_capacity", row,
                    "the restore erased a shape key from the snapshot row")
      self.assertIsNone(row["units_per_period_capacity"])

  def test_a_price_broadcast_restored_to_nothing_still_removes_the_key(self):
    """Ardenwald, unchanged: an unpriced row has no price key."""
    from api_handlers.intake_consult import _guard_multiline_ops_rows  # type: ignore

    prev = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "alpha"}, {"product_name": "bravo"}]}]}
    patch = {"lob_models": [{"lob_name": "L", "products": [
      {"product_name": "alpha", "unit_price": 1400.0},
      {"product_name": "bravo", "unit_price": 1400.0}]}]}
    _guard_multiline_ops_rows(prev, patch, "the price is 1400")
    for row in patch["lob_models"][0]["products"]:
      self.assertNotIn("unit_price", row)


if __name__ == "__main__":
  unittest.main(verbosity=2)
