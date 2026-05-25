"""P3.33 Phase 3 step 9d — raise_fail_fast helper behaviour.

The helper is the wrapper-D pattern made concrete:

  1. Emit best-effort audit row via safe_emit (swallows on failure).
  2. ALWAYS raise RuntimeError with the post_intake_fail_fast:: prefix.

These tests verify the contract with a hermetic FakeConn that records
INSERT params tuples, plus a path that bypasses the audit row entirely
(no conn) to prove the raise still fires.
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


from client_intake_and_finmo.post_intake_diagnostics import (
  FAIL_FAST_PREFIX,
  FailFastCode,
  PhaseCode,
  ensure_run_diagnostics_table,
  raise_fail_fast,
)


class _FakeCursor:
  def __init__(self, store):
    self._store = store
    self.lastrowid = None

  def execute(self, sql, params=None):
    s = sql.strip().lower()
    self._store["calls"].append((sql, params))
    if s.startswith("create table"):
      self._store["create_sql"] = sql
    elif s.startswith("create index"):
      self._store["index_sql"].append(sql)
    elif s.startswith("insert"):
      self._store["rows"].append(params)
      self._store["next_id"] += 1
      self.lastrowid = self._store["next_id"]

  def fetchall(self): return list(self._store.get("rows", []))
  def close(self): pass


class _FakeConn:
  def __init__(self):
    self._store = {"calls": [], "rows": [], "index_sql": [], "next_id": 0}
  def cursor(self, dictionary=False): return _FakeCursor(self._store)
  def commit(self): pass


class RaiseFailFastHelperTest(unittest.TestCase):
  def test_raise_message_carries_prefix_and_code(self) -> None:
    conn = _FakeConn()
    with self.assertRaises(RuntimeError) as ctx:
      raise_fail_fast(
        conn,
        draft_id="d", planning_run_id="r",
        phase=PhaseCode.REALISM_GATE,
        code=FailFastCode.FAIL_REALISM_BAND_SOURCE_MISSING,
        detail="row index 4 missing band_source",
        where="orchestrator._run_post_cascade_completion",
      )
    msg = str(ctx.exception)
    self.assertTrue(msg.startswith(FAIL_FAST_PREFIX),
                    msg=f"missing prefix: {msg!r}")
    self.assertIn("fail_realism_band_source_missing", msg)
    self.assertIn("row index 4 missing band_source", msg)

  def test_audit_row_emitted_before_raise(self) -> None:
    conn = _FakeConn()
    try:
      raise_fail_fast(
        conn,
        draft_id="d", planning_run_id="r",
        phase=PhaseCode.CASH_PASS,
        code=FailFastCode.FAIL_CASH_PASS_RESULT_MALFORMED,
        detail="cash_result.applied_updates_count is None",
      )
    except RuntimeError:
      pass
    insert_rows = conn._store["rows"]
    self.assertEqual(len(insert_rows), 1,
                     msg="expected exactly one audit INSERT")
    params = insert_rows[0]
    # Column order in run_diagnostics_table: draft_id, planning_run_id,
    # phase, event_code, status, diagnostic_data, latency_ms.
    self.assertEqual(params[0], "d")
    self.assertEqual(params[1], "r")
    self.assertEqual(params[2], "cash_pass")
    self.assertEqual(params[4], "failed")
    diag = json.loads(params[5])
    self.assertEqual(diag["fail_fast_code"], "fail_cash_pass_result_malformed")
    self.assertIn("None", diag["detail"])

  def test_phase_code_mismatch_raises_value_error(self) -> None:
    conn = _FakeConn()
    with self.assertRaises(ValueError) as ctx:
      raise_fail_fast(
        conn, draft_id="d", planning_run_id="r",
        phase=PhaseCode.CASH_PASS,  # wrong phase for this code
        code=FailFastCode.FAIL_REALISM_BAND_SOURCE_MISSING,
        detail="x",
      )
    self.assertIn("fail_fast_code_phase_mismatch", str(ctx.exception))

  def test_audit_emit_swallows_when_conn_fails(self) -> None:
    """safe_emit must never crash the pipeline — if the audit row
    write fails, the RuntimeError still raises."""
    class _BadConn:
      def cursor(self, dictionary=False):
        raise IOError("db is down")
    with self.assertRaises(RuntimeError) as ctx:
      raise_fail_fast(
        _BadConn(), draft_id="d", planning_run_id="r",
        phase=PhaseCode.WORKBOOK_ACCEPT,
        code=FailFastCode.FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID,
        detail="d_id was empty",
      )
    # The RuntimeError is the fail-fast — NOT the IOError from the
    # audit emit. safe_emit swallowed that.
    self.assertTrue(str(ctx.exception).startswith(FAIL_FAST_PREFIX))
    self.assertNotIsInstance(ctx.exception.__cause__, IOError)

  def test_cause_chain_preserved(self) -> None:
    """If a cause is supplied, the raised RuntimeError chains it via
    ``raise ... from cause`` so traceback consumers can see the
    underlying fault."""
    inner = KeyError("missing_key")
    conn = _FakeConn()
    with self.assertRaises(RuntimeError) as ctx:
      raise_fail_fast(
        conn, draft_id="d", planning_run_id="r",
        phase=PhaseCode.FINMO_SYNC,
        code=FailFastCode.FAIL_FINMO_NO_QUARTER_ROWS,
        detail="quarter_rows missing",
        cause=inner,
      )
    self.assertIs(ctx.exception.__cause__, inner)


if __name__ == "__main__":
  unittest.main()
