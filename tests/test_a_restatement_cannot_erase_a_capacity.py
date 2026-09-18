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
  """The row as the store holds it AFTER THE FOLD (2026-09-18): her six at once
  lives in units_per_period_capacity, which is what that slot means on a
  contract row. There is no parked pair - the refusal is gone with the second
  home that created it."""
  rows = [{"product_name": n, "unit_cadence": "contract"} for n in _NAMES]
  rows[0]["units_per_period_capacity"] = 6
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
    """The snapshot restates week = 6 and period = 6 over her recorded six."""
    out = self.door(_store_after_turn_9(),
                    _consultant_snapshot(units_per_week_capacity=6,
                                         units_per_period_capacity=6),
                    user_message="Six at once on the residential home frames.")
    row = self._row(out)
    self.assertIsNotNone(row.get("units_per_period_capacity"),
                  "the key is ABSENT - the snapshot erased it (the store Cowork read)")
    self.assertEqual(row.get("units_per_period_capacity"), 6,
                     "her six left the slot that means at once")
    self.assertNotIn("_capacity_pair_refused", row,
                     "the refusal is gone with the second home that created it")
    # The week slot is the COMPATIBILITY MIRROR on a contract row - the ops
    # finalize prompt has required it since before 09-12 ("for monthly or
    # contract cadence, mirror that value into units_per_week_capacity") and the
    # engine reads period x periods as authoritative for this cadence. A 6 here
    # is that mirror, not a claim that she does six a week.

  def test_a_snapshot_that_omits_capacity_does_not_erase_it(self):
    out = self.door(_store_after_turn_9(), _consultant_snapshot())
    row = self._row(out)
    self.assertEqual(row.get("units_per_period_capacity"), 6)
    self.assertNotIn("_capacity_pair_refused", row)

  def test_the_other_lines_are_untouched(self):
    out = self.door(_store_after_turn_9(),
                    _consultant_snapshot(units_per_week_capacity=6,
                                         units_per_period_capacity=6))
    for i in (1, 2):
      row = self._row(out, i)
      self.assertIsNone(row.get("units_per_period_capacity"))
      self.assertNotIn("_capacity_pair_refused", row)
      self.assertIsNone(row.get("units_per_week_capacity"))
      self.assertIsNone(row.get("units_per_period_capacity"))

  def test_a_different_throughput_is_not_swept_up(self):
    """Only an EQUAL figure is treated as mislabelled. A value that differs
    from the concurrent figure is left for the rules to judge."""
    out = self.door(_store_after_turn_9(),
                    _consultant_snapshot(units_per_period_capacity=26))
    row = self._row(out)
    self.assertEqual(row.get("units_per_period_capacity"), 26,
                     "a restatement that carries its own figure is a statement")


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
