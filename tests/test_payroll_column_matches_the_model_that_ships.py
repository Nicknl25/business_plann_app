"""The payroll_headcount column must equal the model that ships.

The workbook re-renders payroll from intake_consult_drafts.payroll_headcount
while the written plan reads model_input. A stage that adopts a schedule in
memory without persisting the column (Phase B labor refresh, 2026-09-25,
T&R scratch: Q20 cash 1,589,472 in the workbook vs 383,063 in the model)
leaves the two disagreeing. The pre-finalize persist is the chokepoint: it
writes the schedule the F6 invariant has just proved equal to the model in
the SAME UPDATE as model_input/finmo, so any in-memory adopter lands.

General case, any business: varied horizons, magnitudes and shapes. The
fake connection is a real SQL-shaped store (it parses the UPDATE's column
list), so a writer that leaves payroll_headcount out is caught.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)

from client_intake_and_finmo.post_intake_solver.orchestrator import (  # noqa: E402
  _write_pre_finalize_state,
)


class _Store:
  def __init__(self, row):
    self.row = row
    self.commits = 0


class _Cursor:
  def __init__(self, store):
    self.store = store
    self._result = None

  def execute(self, sql, params):
    sql = " ".join(sql.split())
    m = re.match(r"UPDATE intake_consult_drafts SET (.+) WHERE draft_id=%s", sql)
    if m:
      cols = [c.split("=")[0].strip() for c in m.group(1).split(",")]
      assert params[-1] == self.store.row["draft_id"]
      for col, val in zip(cols, params[:-1]):
        self.store.row[col] = val
      return
    m = re.match(r"SELECT (.+) FROM intake_consult_drafts WHERE draft_id=%s", sql)
    if m:
      cols = [c.strip() for c in m.group(1).split(",")]
      self._result = tuple(self.store.row.get(c) for c in cols)
      return
    raise AssertionError(f"unexpected SQL: {sql}")

  def fetchone(self):
    return self._result

  def close(self):
    pass


class _Conn:
  def __init__(self, store):
    self.store = store

  def cursor(self, dictionary=False):
    return _Cursor(self.store)

  def commit(self):
    self.store.commits += 1


def _schedule(quarters, base, growth, first_scaled=None, scale=1.0):
  totals = []
  for q in range(0, quarters + 1):
    pay = base * (1.0 + growth) ** q
    if first_scaled is not None and q >= first_scaled:
      pay *= scale
    totals.append({"quarter_index": q, "payroll": round(pay, 2)})
  return {"labor_intensity_class": "labor_bound", "rows": [], "quarter_totals": totals}


def _model_for(schedule):
  vals = [t["payroll"] for t in schedule["quarter_totals"]]
  return {
    "sections": {"expenses": [{"lever_id": "expenses::Payroll", "values": vals}]},
    "derived_driver_runtime": {"expenses::Payroll": {"payroll_headcount": copy.deepcopy(schedule)}},
  }


def _marker(epoch=1790000000):
  return {"tag": "pre_finalize_persist", "wrote_at_epoch_seconds": epoch}


def _persist(store, schedule, model):
  mi = copy.deepcopy(model)
  fm = {"quarter_rows": []}
  mi["_pre_finalize_persist_marker"] = _marker()
  fm["_pre_finalize_persist_marker"] = _marker()
  return _write_pre_finalize_state(
    _Conn(store),
    draft_id_clean=store.row["draft_id"],
    model_input_to_persist=mi,
    finmo_to_persist=fm,
    payroll_headcount=schedule,
    marker=_marker(),
  )


def _column_vs_model_gap(store):
  col = json.loads(store.row["payroll_headcount"])
  mi = json.loads(store.row["model_input_json"])
  vals = mi["sections"]["expenses"][0]["values"]
  return max(
    abs(float(t["payroll"]) - float(vals[int(t["quarter_index"])]))
    for t in col["quarter_totals"] if int(t["quarter_index"]) >= 1
  )


# (quarters, base payroll, growth per quarter, first scaled quarter, scale)
SHAPES = [
  (20, 454_447.0, 0.02, 5, 1.17),     # T&R: sign shop, refresh from Q5
  (20, 38_000.0, 0.00, 2, 1.40),      # two-person cafe, flat, early scale
  (12, 1_250_000.0, 0.035, 9, 1.05),  # short horizon, late small scale
  (20, 210_500.55, -0.01, 1, 0.80),   # shrinking staff, scaled DOWN from Q1
]


class PayrollColumnMatchesTheModelThatShips(unittest.TestCase):
  def test_in_memory_adopter_without_a_persist_lands_at_pre_finalize(self):
    for quarters, base, growth, first, scale in SHAPES:
      with self.subTest(quarters=quarters, base=base, scale=scale):
        stale = _schedule(quarters, base, growth)
        adopted = _schedule(quarters, base, growth, first_scaled=first, scale=scale)
        # The column still holds the pre-refresh schedule; memory and the
        # model carry the adopted one (the F6 invariant holds in memory).
        store = _Store({
          "draft_id": "d" * 32,
          "payroll_headcount": json.dumps(stale),
          "model_input_json": "{}",
          "finmo_json": "{}",
        })
        wrote = _persist(store, adopted, _model_for(adopted))
        self.assertLessEqual(_column_vs_model_gap(store), 1.0)
        self.assertTrue(wrote)
        self.assertEqual(
          json.loads(store.row["payroll_headcount"])["quarter_totals"],
          adopted["quarter_totals"],
        )

  def test_trim_adopted_draft_stays_gap_zero(self):
    for quarters, base, growth, first, scale in SHAPES:
      with self.subTest(quarters=quarters, base=base):
        trimmed = _schedule(quarters, base, growth, first_scaled=first, scale=scale * 0.9)
        store = _Store({
          "draft_id": "e" * 32,
          "payroll_headcount": json.dumps(trimmed),  # the lever trial persisted it
          "model_input_json": "{}",
          "finmo_json": "{}",
        })
        _persist(store, trimmed, _model_for(trimmed))
        self.assertLessEqual(_column_vs_model_gap(store), 1.0)

  def test_no_schedule_leaves_the_column_alone(self):
    for schedule in (None, {}, {"rows": [], "quarter_totals": []}):
      with self.subTest(schedule=schedule):
        store = _Store({
          "draft_id": "f" * 32,
          "payroll_headcount": "SENTINEL",
          "model_input_json": "{}",
          "finmo_json": "{}",
        })
        wrote = _persist(store, schedule, {"sections": {"expenses": []}})
        self.assertFalse(wrote)
        self.assertEqual(store.row["payroll_headcount"], "SENTINEL")
        self.assertEqual(
          json.loads(store.row["model_input_json"])["_pre_finalize_persist_marker"]["tag"],
          "pre_finalize_persist",
        )

  def test_a_write_that_does_not_land_is_refused(self):
    adopted = _schedule(20, 100_000.0, 0.01, first_scaled=3, scale=1.2)

    class _DroppingCursor(_Cursor):
      def execute(self, sql, params):
        super().execute(sql, params)
        if sql.lstrip().startswith("UPDATE"):
          self.store.row["payroll_headcount"] = json.dumps(_schedule(20, 100_000.0, 0.01))

    class _DroppingConn(_Conn):
      def cursor(self, dictionary=False):
        return _DroppingCursor(self.store)

    store = _Store({"draft_id": "a" * 32, "payroll_headcount": None,
                    "model_input_json": "{}", "finmo_json": "{}"})
    mi = _model_for(adopted)
    mi["_pre_finalize_persist_marker"] = _marker()
    with self.assertRaisesRegex(RuntimeError, "payroll_headcount_mismatch"):
      _write_pre_finalize_state(
        _DroppingConn(store), draft_id_clean="a" * 32,
        model_input_to_persist=mi,
        finmo_to_persist={"_pre_finalize_persist_marker": _marker()},
        payroll_headcount=adopted, marker=_marker(),
      )


if __name__ == "__main__":
  unittest.main()
