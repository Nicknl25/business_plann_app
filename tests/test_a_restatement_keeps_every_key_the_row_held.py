"""A restatement keeps every key the row held - even a key holding null.

Vasquez-Lindqvist Timber Frames ec2da9c7, replay turn 19, 2026-09-13. Cowork
confirmed the annual pair on row 0 and flagged rows 1 and 2: at 21:14 each
carried eleven keys, including units_per_week_capacity,
units_per_period_capacity and operating_periods_per_year, all null. After the
turn they carried eight. No value was lost - but the rows of one line of
business now had different shapes, and the reader that notices is exactly the
kind that found the original defect: absent is not null.

It was not deliberate. The ops consultant's lob_models snapshot restated those
rows without the three keys, and the carry-forward only carried keys holding a
non-null value, so absent stayed absent. Cowork asked which writer puts those
keys back. The answer was none, and that is the defect: under the rule that a
restatement is a statement and not a replacement, dropping a key is an erasure
even when it held null.

What is genuinely GONE must stay gone. A quarantine object that was cleared and
a router name that was consumed are absent on purpose; preserving presence must
not bring them back.

Driven through the consultant's real door, `_apply_model_ops_patch`, reading
KEY PRESENCE.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

_NULL_KEYS = ("units_per_week_capacity", "units_per_period_capacity",
              "operating_periods_per_year")


def _store_before_turn_19():
  """Row 0 homed; rows 1 and 2 carrying the three capacity keys as null."""
  home = {"product_name": "Custom residential timber frames", "unit_cadence": "contract",
          "concurrent_capacity_units": 6, "annual_turns_per_year": 34 / 6,
          "utilization_rate": 26 / 34,
          "units_per_week_capacity": None, "units_per_period_capacity": None,
          "operating_periods_per_year": None}
  rows = [home]
  for name in ("Commercial timber structures", "Shipped frame kits for builders"):
    row = {"product_name": name, "unit_cadence": "contract", "utilization_rate": None}
    for k in _NULL_KEYS:
      row[k] = None
    rows.append(row)
  return {"lob_models": [{"lob_name": "Primary line of business", "products": rows}]}


def _snapshot_omitting_the_keys():
  """What the consultant restated: the rows, without the null capacity keys."""
  return {"lob_models": [{"lob_name": "Primary line of business", "products": [
    {"product_name": "Custom residential timber frames", "unit_cadence": "contract"},
    {"product_name": "Commercial timber structures", "unit_cadence": "contract",
     "utilization_rate": None},
    {"product_name": "Shipped frame kits for builders", "unit_cadence": "contract",
     "utilization_rate": None},
  ]}]}


class ARestatementKeepsKeyPresence(unittest.TestCase):
  def setUp(self):
    from api_handlers.intake_consult import _apply_model_ops_patch  # type: ignore

    self.door = _apply_model_ops_patch

  def _rows(self, store=None, snapshot=None):
    out = self.door(store if store is not None else _store_before_turn_19(),
                    snapshot if snapshot is not None else _snapshot_omitting_the_keys())
    return out["lob_models"][0]["products"]

  def test_rows_1_and_2_keep_their_null_capacity_keys(self):
    rows = self._rows()
    for i in (1, 2):
      for k in _NULL_KEYS:
        self.assertIn(k, rows[i],
                      "row %d lost the key %s - absent is not null" % (i, k))
        self.assertIsNone(rows[i][k], "a null key came back holding a value")

  def test_every_row_of_one_line_has_the_same_capacity_shape(self):
    """Every row, every key, PRESENT. The first version only asserted the rows
    MATCHED - and it passed on the unfixed code, because the snapshot dropped
    the keys from row 0 as well, so all three rows were uniformly absent. One
    shape, and the wrong one. In the live store the asymmetry came from a
    different route (row 0's restated twins were set to null, keeping them), so
    matching shapes proves nothing; present keys do."""
    rows = self._rows()
    shapes = {tuple(k in r for k in _NULL_KEYS) for r in rows}
    self.assertEqual(shapes, {(True, True, True)},
                     "rows of one line of business do not all carry the capacity keys")

  def test_row_0_is_still_homed(self):
    row = self._rows()[0]
    self.assertIn("concurrent_capacity_units", row)
    self.assertEqual(row["concurrent_capacity_units"], 6)
    self.assertAlmostEqual(row["annual_turns_per_year"], 34 / 6, 9)
    self.assertAlmostEqual(row["utilization_rate"], 26 / 34, 9)

  def test_a_cleared_quarantine_is_not_resurrected(self):
    for row in self._rows():
      self.assertNotIn("_capacity_pair_refused", row)

  def test_a_consumed_router_name_is_not_resurrected(self):
    for row in self._rows():
      self.assertNotIn("annual_capacity_units", row)
      self.assertNotIn("annual_completed_units", row)

  def test_a_value_the_snapshot_states_is_not_overwritten(self):
    """Preserving presence must never override what the restatement says."""
    snap = _snapshot_omitting_the_keys()
    snap["lob_models"][0]["products"][1]["unit_price"] = 9500
    rows = self._rows(snapshot=snap)
    self.assertEqual(rows[1].get("unit_price"), 9500)


if __name__ == "__main__":
  unittest.main(verbosity=2)
