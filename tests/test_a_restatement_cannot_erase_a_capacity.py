"""A consultant's snapshot cannot erase a capacity, or leave its quarantine behind.

Vasquez-Lindqvist Timber Frames ec2da9c7, 2026-09-13. The client said six frames
at once. The per-line door recorded concurrent_capacity_units = 6 at 20:23:06.
At 20:23:16 the ops consultant's lob_models snapshot went through
`_apply_model_ops_patch`, which assigned the list wholesale - the row it wrote
did not carry the key, so the key ceased to exist. The same snapshot restated
the six as units_per_week_capacity = 6 AND units_per_period_capacity = 6, the
pair refusal nulled both, and parked {6, 6} in `_capacity_pair_refused`.

I reported that write as landed from a log line. Cowork read the store:
concurrent_capacity_units was ABSENT - not null, gone - and the quarantine
object was present beside an empty row.

THESE PINS DRIVE THE REAL DOOR and read KEY PRESENCE, never `.get()`. A missing
key and a null read identically through `.get()`, and that is precisely the
difference Cowork had to point out.

The carry-forward had been added to `_apply_scoped_patch` - a different door,
which the consultant's snapshot never passes through. A pin on that door passed
while this one was wide open.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_NAMES = ("Custom residential timber frames", "Commercial timber structures",
          "Shipped frame kits for builders")


def _store_after_turn_9():
  """The row as the store held it: concurrent recorded, and a parked {6, 6}
  left by an earlier refusal."""
  rows = [{"product_name": n, "unit_cadence": "contract"} for n in _NAMES]
  rows[0]["concurrent_capacity_units"] = 6
  rows[0]["_capacity_pair_refused"] = {
    "units_per_week_capacity": 6, "units_per_period_capacity": 6,
    "cadence": "contract", "operating_periods_per_year": None,
    "why": "conversions of one another cannot hold values that disagree",
  }
  return {"lob_models": [{"lob_name": "Primary line of business", "products": rows}]}


def _consultant_snapshot(**first_row):
  rows = [{"product_name": n, "unit_cadence": "contract"} for n in _NAMES]
  rows[0].update(first_row)
  return {"lob_models": [{"lob_name": "Primary line of business", "products": rows}]}


class TheConsultantDoorCarriesTheRowForward(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import _apply_model_ops_patch  # type: ignore

    self.door = _apply_model_ops_patch

  def _row(self, ops, i=0):
    return ops["lob_models"][0]["products"][i]

  def test_the_exact_timber_snapshot_leaves_the_capacity_recorded(self):
    """week = 6 and period = 6 restated over a recorded concurrent six."""
    out = self.door(_store_after_turn_9(),
                    _consultant_snapshot(units_per_week_capacity=6,
                                         units_per_period_capacity=6),
                    user_message="Six at once on the residential home frames.")
    row = self._row(out)
    self.assertIn("concurrent_capacity_units", row,
                  "the key is ABSENT - the snapshot erased it (the store Cowork read)")
    self.assertEqual(row["concurrent_capacity_units"], 6)
    self.assertNotIn("_capacity_pair_refused", row,
                     "a parked {6, 6} beside a recorded six is not a correct row")
    self.assertNotEqual(row.get("units_per_week_capacity"), 6,
                        "six at once was stored as six a week")
    self.assertNotEqual(row.get("units_per_period_capacity"), 6,
                        "six at once was stored as six a period")

  def test_a_snapshot_that_omits_capacity_does_not_erase_it(self):
    out = self.door(_store_after_turn_9(), _consultant_snapshot())
    row = self._row(out)
    self.assertIn("concurrent_capacity_units", row)
    self.assertEqual(row["concurrent_capacity_units"], 6)
    self.assertNotIn("_capacity_pair_refused", row)

  def test_the_other_lines_are_untouched(self):
    out = self.door(_store_after_turn_9(),
                    _consultant_snapshot(units_per_week_capacity=6,
                                         units_per_period_capacity=6))
    for i in (1, 2):
      row = self._row(out, i)
      self.assertNotIn("concurrent_capacity_units", row)
      self.assertNotIn("_capacity_pair_refused", row)
      self.assertIsNone(row.get("units_per_week_capacity"))
      self.assertIsNone(row.get("units_per_period_capacity"))

  def test_a_different_throughput_is_not_swept_up(self):
    """Only an EQUAL figure is treated as mislabelled. A value that differs
    from the concurrent figure is left for the rules to judge."""
    out = self.door(_store_after_turn_9(),
                    _consultant_snapshot(units_per_period_capacity=26))
    row = self._row(out)
    self.assertEqual(row["concurrent_capacity_units"], 6)
    self.assertEqual(row.get("units_per_period_capacity"), 26,
                     "a different number was cleared as though it were the same one")


class TheCarryForwardIsOnTheDoorTheSnapshotUses(unittest.TestCase):
  """It was written on the wrong door once. This fails if it moves off again."""

  def test_the_consultant_door_calls_it(self):
    src = (ROOT / "python" / "api_handlers" / "intake_consult.py").read_text(
      encoding="utf-8-sig")
    i = src.index("def _apply_model_ops_patch(")
    body = src[i:src.index("\ndef ", i + 10)]
    self.assertIn("_carry_forward_per_line_drivers(", body)


if __name__ == "__main__":
  unittest.main(verbosity=2)
