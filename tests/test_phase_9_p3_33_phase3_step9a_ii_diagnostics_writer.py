"""Phase 9 P3.33 Phase 3 step 9a part 2 — diagnostics DDL + writer.

Hermetic tests for ``post_intake_diagnostics.run_diagnostics_table``.
Uses an in-memory fake cursor (no MySQL needed). The closed enums
themselves are covered in step 9a part 1's test file
(test_phase_9_p3_33_phase3_step9a_phase_codes.py).

Confirms:
  - ensure_run_diagnostics_table emits idempotent CREATE TABLE IF NOT
    EXISTS for ``post_intake_run_diagnostics``.
  - emit_diagnostic accepts the canonical row shape and writes the
    expected INSERT tuple in the spec §9a column order.
  - (phase, event_code) pair validation: mismatches raise ValueError.
  - Required fields (draft_id, planning_run_id) raise ValueError early.
  - Unknown phase / event_code / status strings raise.
  - JSON encoding of diagnostic_data handles dicts + nested values.
  - String enum inputs are coerced to enum values.
  - emit_diagnostic(conn=None) is a no-op returning None.
  - fetch_diagnostics returns inserted rows in id-ASC order; conn=None
    returns [].
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

from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # noqa: E402,E501
  EventCode, PhaseCode, Status,
)
from client_intake_and_finmo.post_intake_diagnostics.run_diagnostics_table import (  # noqa: E402,E501
  RUN_DIAGNOSTICS_TABLE_NAME,
  emit_diagnostic,
  ensure_run_diagnostics_table,
  fetch_diagnostics,
)


class _FakeCursor:
  def __init__(self, store):
    self._store = store
    self.lastrowid = None

  def execute(self, sql, params=None):
    self._store["calls"].append((sql, params))
    s = sql.strip().lower()
    if s.startswith("create table"):
      self._store["create_sql"] = sql
      return
    if s.startswith("insert"):
      self._store["rows"].append(params)
      self._store["next_id"] += 1
      self.lastrowid = self._store["next_id"]
      return
    if s.startswith("select"):
      self._store["last_select"] = (sql, params)

  def fetchall(self):
    return list(self._store.get("rows", []))

  def close(self):
    pass


class _FakeConn:
  def __init__(self):
    self._store = {"calls": [], "rows": [], "next_id": 0}

  def cursor(self, dictionary=False):
    return _FakeCursor(self._store)

  def commit(self):
    pass


class EnsureTableTest(unittest.TestCase):
  def test_ddl_idempotent(self) -> None:
    conn = _FakeConn()
    ensure_run_diagnostics_table(conn)
    ensure_run_diagnostics_table(conn)
    self.assertIn("create_sql", conn._store)
    self.assertIn("CREATE TABLE IF NOT EXISTS", conn._store["create_sql"])
    self.assertIn(RUN_DIAGNOSTICS_TABLE_NAME, conn._store["create_sql"])
    self.assertEqual(RUN_DIAGNOSTICS_TABLE_NAME, "post_intake_run_diagnostics")

  def test_none_conn_safe(self) -> None:
    ensure_run_diagnostics_table(None)  # must not raise


class EmitDiagnosticHappyPathTest(unittest.TestCase):
  def test_round_trip_canonical_row(self) -> None:
    conn = _FakeConn()
    row_id = emit_diagnostic(
      conn,
      draft_id="draft_abc", planning_run_id="run_001",
      phase=PhaseCode.CASCADE_WALK,
      event_code=EventCode.CASCADE_PROPOSAL_CONFIRMED,
      status=Status.COMPLETED,
      diagnostic_data={"tier_id": "V1", "section": "drivers", "applied_value": 0.65},
      latency_ms=42,
    )
    self.assertEqual(row_id, 1)
    rows = conn._store["rows"]
    self.assertEqual(len(rows), 1)
    p = rows[0]
    self.assertEqual(p[0], "draft_abc")
    self.assertEqual(p[1], "run_001")
    self.assertEqual(p[2], "cascade_walk")
    self.assertEqual(p[3], "cascade_proposal_confirmed")
    self.assertEqual(p[4], "completed")
    self.assertIn("tier_id", p[5])  # JSON-encoded string
    self.assertEqual(p[6], 42)

  def test_default_status_is_completed(self) -> None:
    conn = _FakeConn()
    emit_diagnostic(
      conn, draft_id="d", planning_run_id="r",
      phase=PhaseCode.MIRROR_BUILD,
      event_code=EventCode.MIRROR_BUILD_COMPLETED,
    )
    self.assertEqual(conn._store["rows"][0][4], "completed")

  def test_string_enum_inputs_coerced(self) -> None:
    conn = _FakeConn()
    row_id = emit_diagnostic(
      conn, draft_id="d", planning_run_id="r",
      phase="cascade_walk", event_code="cascade_entered", status="started",
    )
    self.assertEqual(row_id, 1)
    p = conn._store["rows"][0]
    self.assertEqual(p[2], "cascade_walk")
    self.assertEqual(p[3], "cascade_entered")
    self.assertEqual(p[4], "started")

  def test_diagnostic_data_json_encoded(self) -> None:
    conn = _FakeConn()
    emit_diagnostic(
      conn, draft_id="d", planning_run_id="r",
      phase=PhaseCode.CASCADE_WALK,
      event_code=EventCode.CASCADE_TIER_WALKED,
      diagnostic_data={"tier_id": "V2", "nested": {"a": [1, 2, 3]}},
    )
    decoded = json.loads(conn._store["rows"][0][5])
    self.assertEqual(decoded["tier_id"], "V2")
    self.assertEqual(decoded["nested"]["a"], [1, 2, 3])

  def test_diagnostic_data_none_passes_through(self) -> None:
    conn = _FakeConn()
    emit_diagnostic(
      conn, draft_id="d", planning_run_id="r",
      phase=PhaseCode.MIRROR_BUILD,
      event_code=EventCode.MIRROR_BUILD_STARTED,
      status=Status.STARTED,
    )
    p = conn._store["rows"][0]
    self.assertIsNone(p[5])
    self.assertIsNone(p[6])

  def test_none_conn_returns_none(self) -> None:
    self.assertIsNone(emit_diagnostic(
      None, draft_id="d", planning_run_id="r",
      phase=PhaseCode.MIRROR_BUILD,
      event_code=EventCode.MIRROR_BUILD_COMPLETED,
    ))


class EmitDiagnosticValidationTest(unittest.TestCase):
  def test_unknown_phase_raises(self) -> None:
    conn = _FakeConn()
    with self.assertRaises(ValueError) as ctx:
      emit_diagnostic(
        conn, draft_id="d", planning_run_id="r",
        phase="not_a_real_phase",
        event_code=EventCode.CASCADE_ENTERED,
      )
    self.assertIn("unknown phase", str(ctx.exception))

  def test_unknown_event_code_raises(self) -> None:
    conn = _FakeConn()
    with self.assertRaises(ValueError):
      emit_diagnostic(
        conn, draft_id="d", planning_run_id="r",
        phase=PhaseCode.CASCADE_WALK,
        event_code="invented_event",
      )

  def test_mismatched_phase_event_pair_rejected(self) -> None:
    conn = _FakeConn()
    with self.assertRaises(ValueError) as ctx:
      emit_diagnostic(
        conn, draft_id="d", planning_run_id="r",
        phase=PhaseCode.FINALIZE,
        event_code=EventCode.CASCADE_PROPOSAL_CONFIRMED,
      )
    self.assertIn("not registered for", str(ctx.exception))

  def test_missing_draft_id_raises(self) -> None:
    conn = _FakeConn()
    with self.assertRaises(ValueError):
      emit_diagnostic(
        conn, draft_id="", planning_run_id="r",
        phase=PhaseCode.MIRROR_BUILD,
        event_code=EventCode.MIRROR_BUILD_COMPLETED,
      )

  def test_missing_planning_run_id_raises(self) -> None:
    conn = _FakeConn()
    with self.assertRaises(ValueError):
      emit_diagnostic(
        conn, draft_id="d", planning_run_id="",
        phase=PhaseCode.MIRROR_BUILD,
        event_code=EventCode.MIRROR_BUILD_COMPLETED,
      )


class FetchDiagnosticsTest(unittest.TestCase):
  def test_fetch_returns_inserted_rows(self) -> None:
    conn = _FakeConn()
    for ev in (EventCode.MIRROR_BUILD_STARTED, EventCode.MIRROR_BUILD_COMPLETED):
      emit_diagnostic(conn, draft_id="d", planning_run_id="r",
                      phase=PhaseCode.MIRROR_BUILD, event_code=ev)
    rows = fetch_diagnostics(conn, draft_id="d", planning_run_id="r")
    self.assertEqual(len(rows), 2)

  def test_fetch_with_no_conn_returns_empty(self) -> None:
    self.assertEqual(
      fetch_diagnostics(None, draft_id="d", planning_run_id="r"), [],
    )


if __name__ == "__main__":
  unittest.main()
