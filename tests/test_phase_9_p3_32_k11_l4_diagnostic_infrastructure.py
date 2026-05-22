"""Phase 9 P3.32 K11 L-4 — handler diagnostic trace infrastructure.

Smoke tests for ``post_intake_handler_traces``. They exercise the
in-memory + DB-less degradation path only (no MySQL is configured in
CI): the contract is that the sink records traces in-memory, never
raises, and disables durable persistence gracefully when no DB is
reachable. The incremental-SQL path is verified manually against the
live DB during the Phase 2 re-runs.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


def _no_db():
  raise RuntimeError("no_db_in_test")


class HandlerTraceSinkTest(unittest.TestCase):
  def setUp(self) -> None:
    from client_intake_and_finmo import post_intake_handler_traces as mod  # noqa: WPS433
    self.mod = mod
    # Force the DB-less degradation path so the test is hermetic even on
    # a dev machine with MYSQL_* configured (no real-DB pollution).
    self._db_patch = patch(
      "client_intake_and_finmo.intake_submission.get_mysql_connection",
      _no_db,
    )
    self._db_patch.start()
    self.addCleanup(self._db_patch.stop)
    mod.begin_trace_run("draft_abc", "run_001")

  def test_begin_trace_run_stamps_active_and_clears(self) -> None:
    active = self.mod.active_run()
    self.assertEqual(active["draft_id"], "draft_abc")
    self.assertEqual(active["planning_run_id"], "run_001")
    self.assertEqual(active["trace_count"], 0)

  def test_record_handler_call_buffers_in_memory(self) -> None:
    self.mod.record_handler_call(
      handler=self.mod.HANDLER_H2,
      call_n=1,
      payload={"all_pass": False, "viability_checks": {"ebitda_positive_by_q11": "FAIL"}},
    )
    rows = self.mod.get_trace_buffer(handler=self.mod.HANDLER_H2)
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["call_n"], 1)
    self.assertEqual(rows[0]["trace_kind"], self.mod.KIND_PER_CALL)
    self.assertFalse(rows[0]["payload"]["all_pass"])

  def test_record_gpt_io_captures_latency_and_usage(self) -> None:
    self.mod.record_gpt_io(
      consultant_name="handler_c_turn_2",
      decision_source="python_proposer_plus_gpt_critic",
      model="gpt-4.1-mini",
      elapsed_ms=1234,
      usage={"input_tokens": 100, "output_tokens": 20},
      tool_call_names=["propose_payroll_headcount_schedule"],
    )
    rows = self.mod.get_trace_buffer(trace_kind=self.mod.KIND_GPT_IO)
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["elapsed_ms"], 1234)
    self.assertEqual(rows[0]["payload"]["usage"]["input_tokens"], 100)

  def test_runtime_status_latest_snapshot_and_trace(self) -> None:
    self.mod.record_runtime_status(
      handler=self.mod.HANDLER_H2,
      status={"tool_calls_used": 3, "failing_checks": ["ebitda_positive_by_q11"]},
    )
    snap = self.mod.get_runtime_status(self.mod.HANDLER_H2)
    self.assertEqual(snap["tool_calls_used"], 3)
    # Status updates are also persisted as a runtime_status trace row.
    rows = self.mod.get_trace_buffer(trace_kind=self.mod.KIND_RUNTIME_STATUS)
    self.assertEqual(len(rows), 1)

  def test_never_raises_on_unserializable_payload(self) -> None:
    class Opaque:
      pass

    # default=str in the bounded serializer must absorb this.
    self.mod.record_handler_call(
      handler=self.mod.HANDLER_C,
      call_n=1,
      payload={"obj": Opaque()},
    )
    rows = self.mod.get_trace_buffer(handler=self.mod.HANDLER_C)
    self.assertEqual(len(rows), 1)

  def test_begin_trace_run_rearms_and_clears(self) -> None:
    self.mod.record_handler_call(
      handler=self.mod.HANDLER_H2, call_n=1, payload={"x": 1}
    )
    self.assertEqual(len(self.mod.get_trace_buffer()), 1)
    self.mod.begin_trace_run("draft_xyz", "run_002")
    self.assertEqual(len(self.mod.get_trace_buffer()), 0)
    self.assertEqual(self.mod.active_run()["draft_id"], "draft_xyz")

  def test_draft_id_alone_suffices_and_run_id_stamps_later(self) -> None:
    # Payroll Handler C runs before the planning_run_id exists: a trace
    # recorded with only draft_id must still buffer (and would persist).
    self.mod.begin_trace_run("draft_only", "")
    self.mod.record_handler_call(
      handler=self.mod.HANDLER_C, call_n=1, payload={"tool_name": "x"}
    )
    rows = self.mod.get_trace_buffer(handler=self.mod.HANDLER_C)
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["draft_id"], "draft_only")
    self.assertEqual(rows[0]["planning_run_id"], "")
    # Once the grid build creates the planning_run_id, stamp it; later
    # traces carry it, the buffer/seq are NOT reset.
    self.mod.set_planning_run_id("run_late")
    self.mod.record_handler_call(
      handler=self.mod.HANDLER_H2, call_n=1, payload={}
    )
    h2 = self.mod.get_trace_buffer(handler=self.mod.HANDLER_H2)
    self.assertEqual(h2[0]["planning_run_id"], "run_late")
    self.assertEqual(self.mod.active_run()["trace_count"], 2)

  def test_seq_is_monotonic_across_kinds(self) -> None:
    self.mod.record_handler_call(handler=self.mod.HANDLER_H2, call_n=1, payload={})
    self.mod.record_gpt_io(
      consultant_name="x", decision_source="python_proposer_plus_gpt_critic"
    )
    self.mod.record_runtime_status(handler=self.mod.HANDLER_H2, status={})
    seqs = [r["seq"] for r in self.mod.get_trace_buffer()]
    self.assertEqual(seqs, sorted(seqs))
    self.assertEqual(len(set(seqs)), len(seqs))


if __name__ == "__main__":
  unittest.main()
