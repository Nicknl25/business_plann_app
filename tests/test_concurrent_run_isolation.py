"""Concurrency isolation (Nick 2026-09-10, going-live prerequisite).

"Concurrency isn't optional - it's what production IS. Two clients
submit within minutes of each other and their system runs finish
together. That's the normal case."

1. RUN IDENTITY: the draft/run making GPT calls is carried in a
   ContextVar - per run thread, never shared between concurrent runs.
2. THE USAGE LEDGER: the store is a CONTENT-ADDRESSED CACHE, so a run
   whose request matches an existing row REPLAYS it and writes nothing -
   the store's own stamp records who FIRST made a call, never who USED
   it (proved live: a concurrent PT run replayed an earlier run's growth
   judgment, left no trace, and recovery tied four ways). Usage is
   recorded per (request, draft) on a replay exactly as on a live call,
   and judgment recovery reads THAT: two concurrent runs can never see
   each other's judgments, whatever the timestamps. A draft with no
   usage rows predates the ledger and keeps the window rule.
3. CALL LOG: per-run via ContextVar; concurrent runs cannot reset each
   other or interleave entries.
4. EXCEL COM: one-at-a-time via a process-wide lock (the 08-29
   no-cached-values defect resurfaces when two threads drive Excel).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "python")):
  if p not in sys.path:
    sys.path.insert(0, p)

from client_intake_and_finmo.openai_http import (  # noqa: E402
  get_gpt_run_identity,
  set_gpt_run_identity,
)
from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # noqa: E402
  _record_gpt_call,
  get_gpt_call_log,
  reset_gpt_call_log,
)
from writing_phase_v2 import judgments as JG  # noqa: E402


class RunIdentityTests(unittest.TestCase):
  def test_identity_is_per_thread(self):
    seen = {}

    def run(draft, run_id):
      set_gpt_run_identity(draft_id=draft, planning_run_id=run_id)
      time.sleep(0.05)
      seen[draft] = get_gpt_run_identity()

    ts = [threading.Thread(target=run, args=("draft_a", "run_a")),
          threading.Thread(target=run, args=("draft_b", "run_b"))]
    for t in ts:
      t.start()
    for t in ts:
      t.join()
    self.assertEqual(seen["draft_a"]["planning_run_id"], "run_a")
    self.assertEqual(seen["draft_b"]["planning_run_id"], "run_b")

  def test_partial_update_keeps_draft(self):
    set_gpt_run_identity(draft_id="d1")
    set_gpt_run_identity(planning_run_id="r1")
    ident = get_gpt_run_identity()
    self.assertEqual(ident, {"draft_id": "d1", "planning_run_id": "r1"})


class CallLogIsolationTests(unittest.TestCase):
  def test_two_runs_keep_separate_logs(self):
    out = {}

    def run(name, n):
      reset_gpt_call_log()
      for i in range(n):
        _record_gpt_call(f"{name}_{i}", "test")
        time.sleep(0.01)
      out[name] = [e["consultant_name"] for e in get_gpt_call_log()]

    ts = [threading.Thread(target=run, args=("a", 3)),
          threading.Thread(target=run, args=("b", 5))]
    for t in ts:
      t.start()
    for t in ts:
      t.join()
    self.assertEqual(out["a"], ["a_0", "a_1", "a_2"])
    self.assertEqual(len(out["b"]), 5)
    self.assertTrue(all(n.startswith("b_") for n in out["b"]))


class HandlerTraceIsolationTests(unittest.TestCase):
  def test_two_runs_do_not_steal_each_others_traces(self):
    """Second instance of the call-log class, found while fixing the
    first: begin_trace_run() stamped a PROCESS-global active draft_id,
    so run B's begin re-pointed run A's remaining traces at B. A
    diagnostic that lies is worse than no diagnostic."""
    from client_intake_and_finmo import post_intake_handler_traces as T
    seen = {}

    def run(draft):
      T.begin_trace_run(draft, "run_" + draft)
      time.sleep(0.05)          # the other run begins here
      T.record_runtime_status(handler="h", status={"x": 1})
      time.sleep(0.05)
      seen[draft] = (T.active_run(),
                     [e["draft_id"] for e in T.get_trace_buffer()])

    ts = [threading.Thread(target=run, args=(d,))
          for d in ("draft_a", "draft_b")]
    for t in ts:
      t.start()
    for t in ts:
      t.join()
    for draft in ("draft_a", "draft_b"):
      active, buffered = seen[draft]
      self.assertEqual(active["draft_id"], draft)
      self.assertEqual(active["planning_run_id"], "run_" + draft)
      self.assertTrue(buffered, "no traces buffered for " + draft)
      self.assertEqual(set(buffered), {draft})


CREATED = dt.datetime(2026, 9, 10, 11, 39, 8)
UPDATED = dt.datetime(2026, 9, 10, 11, 59, 19)


def _draft(**over):
  d = {"draft_id": "draft_self", "created_at": CREATED, "updated_at": UPDATED,
       "financials_json": json.dumps(
           {"_coherence": {"a": 0.03, "b": 0.06, "c": 0.08}}),
       "model_input_json": None, "marketing_model_json": None}
  d.update(over)
  return d


def _row(payload, ts, used_by=()):
  """used_by = the drafts whose runs USED this stored request (the usage
  ledger); a replay puts a second draft on the same stored row."""
  return {"created_at": ts, "used_by": tuple(used_by),
          "response_text": json.dumps(
              {"choices": [{"message": {"tool_calls": [{"function": {
                  "name": "submit_growth_judgment",
                  "arguments": json.dumps(payload)}}]}}]})}


class _Cur:
  """Emulates the two recovery pools: OWNED (usage JOIN) and UNCLAIMED
  (in-window rows no OTHER draft used)."""

  def __init__(self, rows):
    self._rows = rows

  def execute(self, sql, params):
    if "JOIN" in sql:
      (me,) = params
      self._out = [r for r in self._rows if me in r.get("used_by", ())]
    elif "NOT EXISTS" in sql:
      lo, hi, me = params
      self._out = [r for r in self._rows
                   if lo <= r["created_at"] <= hi
                   and not [d for d in r.get("used_by", ()) if d != me]]
    else:
      lo, hi = params
      self._out = [r for r in self._rows
                   if lo <= r["created_at"] <= hi]

  def fetchall(self):
    return self._out


class _Conn:
  def __init__(self, rows):
    self._rows = rows

  def cursor(self, dictionary=True):
    return _Cur(self._rows)


MINE = {"year1_annual_growth": 0.06, "mature_annual_growth": 0.03,
        "rationale": "dental clinic"}
THEIRS = {"year1_annual_growth": 0.08, "mature_annual_growth": 0.03,
          "rationale": "massage studio"}


class RecoveryOwnershipTests(unittest.TestCase):
  def test_concurrent_runs_see_only_their_own(self):
    """Both rows INSIDE the window (true concurrency): usage separates
    them where corroboration tied 2-2."""
    rows = [_row(THEIRS, CREATED + dt.timedelta(minutes=10), ["draft_other"]),
            _row(MINE, CREATED + dt.timedelta(minutes=12), ["draft_self"])]
    out = JG.recover_from_store(_Conn(rows), _draft())
    self.assertEqual(out["growth"]["rationale"], "dental clinic")

  def test_lone_foreign_row_is_not_adopted(self):
    """The silent-adoption door, closed: the other run's judgment is the
    only candidate in my window and I never made that call. With usage I
    get ABSENT - never the other business's judgment."""
    other_growth = _row(THEIRS, CREATED + dt.timedelta(minutes=10),
                        ["draft_other"])
    my_other_call = {
      "created_at": CREATED + dt.timedelta(minutes=1),
      "used_by": ("draft_self",),
      "response_text": json.dumps({"choices": [{"message": {"tool_calls": [
          {"function": {"name": "submit_wc_judgment",
                        "arguments": json.dumps({"days": 30})}}]}}]}),
    }
    out = JG.recover_from_store(_Conn([other_growth, my_other_call]), _draft())
    self.assertNotIn("growth", out)
    self.assertIn("working_capital", out)

  def test_a_wholly_pre_ledger_draft_keeps_the_window_rule(self):
    """A draft with NO usage at all is pre-ledger and falls back to the
    window, ties and all - the behavior before the ledger existed."""
    rows = [_row(THEIRS, CREATED + dt.timedelta(minutes=10), ["draft_other"]),
            _row(MINE, CREATED + dt.timedelta(minutes=12), ["draft_self"])]
    with self.assertRaises(LookupError):
      JG.recover_from_store(_Conn(rows), _draft(draft_id="draft_third"))

  def test_a_genuine_legacy_tie_still_fails_loud(self):
    """Two UNCLAIMED in-window rows (both pre-ledger) still refuse."""
    rows = [_row(THEIRS, CREATED + dt.timedelta(minutes=10)),
            _row(MINE, CREATED + dt.timedelta(minutes=12))]
    with self.assertRaises(LookupError):
      JG.recover_from_store(_Conn(rows), _draft(draft_id="draft_third"))

  def test_an_unclaimed_window_row_is_never_adopted(self):
    """THE DEFECT THE LIVE PROOF CAUGHT. A per-judgment fallback over
    'rows no other draft claimed' looks safe and is not: the true owner
    may be a PRE-LEDGER run that could never have claimed its own row.
    It put a dental practice's cogs-fit judgment into a physiotherapy
    plan. A ledgered draft is judged by its usage ALONE - the unclaimed
    row stays absent, never adopted."""
    my_run_call = {
      "created_at": CREATED + dt.timedelta(minutes=5),
      "used_by": ("draft_self",),
      "response_text": json.dumps({"choices": [{"message": {"tool_calls": [
          {"function": {"name": "submit_wc_judgment",
                        "arguments": json.dumps({"days": 30})}}]}}]}),
    }
    someone_elses_growth = _row(THEIRS, CREATED + dt.timedelta(minutes=2))
    out = JG.recover_from_store(
      _Conn([my_run_call, someone_elses_growth]), _draft())
    self.assertIn("working_capital", out)
    self.assertNotIn("growth", out)

  def test_a_replayed_row_belongs_to_every_run_that_used_it(self):
    """The live finding: a run whose request matched an existing row
    REPLAYS it and writes nothing. The row was first made by another
    draft and is legitimately mine too - usage says so, the store's own
    stamp never could."""
    rows = [_row(MINE, CREATED - dt.timedelta(days=1),
                 ["draft_earlier", "draft_self"])]
    out = JG.recover_from_store(_Conn(rows), _draft())
    self.assertEqual(out["growth"]["rationale"], "dental clinic")

  def test_usage_beats_timestamps_entirely(self):
    """My row is a day old (replayed), the other run's is inside my
    window: timestamps would pick theirs, usage picks mine."""
    rows = [_row(MINE, CREATED - dt.timedelta(days=1), ["draft_self"]),
            _row(THEIRS, CREATED + dt.timedelta(minutes=10), ["draft_other"])]
    out = JG.recover_from_store(_Conn(rows), _draft())
    self.assertEqual(out["growth"]["rationale"], "dental clinic")

  def test_legacy_draft_with_no_usage_keeps_the_window_rule(self):
    rows = [_row(THEIRS, CREATED - dt.timedelta(minutes=2)),  # pre-creation
            _row(MINE, CREATED + dt.timedelta(minutes=12))]
    out = JG.recover_from_store(_Conn(rows), _draft())
    self.assertEqual(out["growth"]["rationale"], "dental clinic")


class ExcelComLockTests(unittest.TestCase):
  def test_recalc_serializes_on_the_process_lock(self):
    from client_intake_and_finmo.post_intake_runtime_validation import (
      workbook_model_status as W,
    )
    order = []

    def fake_unlocked(path):
      order.append("enter:" + path)
      time.sleep(0.1)
      order.append("exit:" + path)
      return None

    real = W._recalc_workbook_via_excel_com_unlocked
    W._recalc_workbook_via_excel_com_unlocked = fake_unlocked
    try:
      ts = [threading.Thread(target=W._recalc_workbook_via_excel_com,
                             args=(n,)) for n in ("a", "b")]
      for t in ts:
        t.start()
      for t in ts:
        t.join()
    finally:
      W._recalc_workbook_via_excel_com_unlocked = real
    # serialized: every enter is immediately followed by its own exit
    for i in range(0, 4, 2):
      self.assertEqual(order[i].split(":")[1], order[i + 1].split(":")[1],
                       order)


if __name__ == "__main__":
  unittest.main()
