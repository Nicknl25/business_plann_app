"""Phase 9 P3.33 Phase 3 step 9c — downstream pipeline emit
instrumentation.

The target_seeking / cash_pass / realism_gate / finalize orchestrator
is ~3600 lines deep and resistant to hermetic full-flow invocation
(requires a live DB + intake state). These tests cover the
instrumentation as source-shape regression checks: every required
phase-boundary emit must be present in the orchestrator source by
PhaseCode + EventCode reference.

The acceptance gate (workbook_accept) emit is exercised against a
fake conn that records INSERT params tuples.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import List


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


ORCHESTRATOR_PATH = (
  Path(__file__).resolve().parent.parent / "python"
  / "client_intake_and_finmo" / "post_intake_solver" / "orchestrator.py"
)
ACCEPTANCE_GATE_PATH = (
  Path(__file__).resolve().parent.parent / "python"
  / "client_intake_and_finmo" / "post_intake_acceptance" / "gate.py"
)


class _FakeCursor:
  def __init__(self, store): self._store = store; self.lastrowid = None
  def execute(self, sql, params=None):
    s = sql.strip().lower()
    self._store["calls"].append((sql, params))
    if s.startswith("create table"):
      self._store["create_sql"] = sql
    elif s.startswith("insert"):
      self._store["rows"].append(params)
      self._store["next_id"] += 1
      self.lastrowid = self._store["next_id"]
  def fetchall(self): return list(self._store.get("rows", []))
  def close(self): pass


class _FakeConn:
  def __init__(self):
    self._store = {"calls": [], "rows": [], "next_id": 0}
  def cursor(self, dictionary=False): return _FakeCursor(self._store)
  def commit(self): pass


class OrchestratorEmitsSourceShapeTest(unittest.TestCase):
  """Confirm the orchestrator source carries the required emits at
  every phase boundary the step-9 directive named."""

  @classmethod
  def setUpClass(cls) -> None:
    cls.src = ORCHESTRATOR_PATH.read_text(encoding="utf-8")

  def _assert_has(self, marker: str) -> None:
    self.assertIn(marker, self.src,
                  msg=f"orchestrator source missing marker: {marker!r}")

  def test_imports_diagnostics_package(self) -> None:
    self._assert_has("from client_intake_and_finmo.post_intake_diagnostics import")
    self._assert_has("safe_emit as _diag_safe_emit")
    self._assert_has("def _emit_diag(")

  def test_target_seeking_feasibility_started_emitted(self) -> None:
    self._assert_has("TARGET_SEEKING_FEASIBILITY_STARTED")

  def test_target_seeking_adaptation_cascade_started_emitted(self) -> None:
    self._assert_has("TARGET_SEEKING_ADAPTATION_CASCADE_STARTED")

  def test_target_seeking_completed_emitted(self) -> None:
    self._assert_has("TARGET_SEEKING_COMPLETED")

  def test_cash_pass_started_emitted(self) -> None:
    self._assert_has("CASH_PASS_STARTED")

  def test_cash_pass_completed_emitted(self) -> None:
    self._assert_has("CASH_PASS_COMPLETED")

  def test_realism_gate_started_emitted(self) -> None:
    self._assert_has("REALISM_GATE_STARTED")

  def test_realism_gate_completed_emitted(self) -> None:
    self._assert_has("REALISM_GATE_COMPLETED")

  def test_realism_gate_check_failed_emitted(self) -> None:
    self._assert_has("REALISM_GATE_CHECK_FAILED")

  def test_finalize_started_emitted(self) -> None:
    self._assert_has("FINALIZE_STARTED")

  def test_finalize_validation_passed_and_failed_emitted(self) -> None:
    self._assert_has("FINALIZE_VALIDATION_PASSED")
    self._assert_has("FINALIZE_VALIDATION_FAILED")


class AcceptanceGateEmitTest(unittest.TestCase):
  """The acceptance gate's verdict triggers a WORKBOOK_ACCEPT_
  ACCEPTED / REJECTED emit. Exercise the verdict path with a hermetic
  fake conn so the emit can be observed."""

  def _patch_verdict_internals(self, *, passed: bool):
    """Patch the helpers verify_run_acceptance reads so we can drive
    it to a known outcome. Returns the cleanup."""
    from client_intake_and_finmo.post_intake_acceptance import gate as _gate_mod
    original_planning_run = _gate_mod._planning_run_row
    original_draft = _gate_mod._draft_row
    original_persist = _gate_mod._persist_verdict
    original_parse = _gate_mod._parse_json
    # The verdict logic walks checks based on planning_run + draft +
    # finmo + realism_memo + planning_run_json. To drive passed=True
    # we'd need fully-shaped fixtures. To drive passed=False we just
    # need one check to fail. Simpler: replace _record-chain wholesale
    # by patching the gate's _planning_run_row to return a minimal row
    # that produces ALL FAILING checks; verify the emit is REJECTED.
    _gate_mod._planning_run_row = lambda *a, **kw: {
      "planning_run_id": "fake_run_001",
      "current_stage": "stage",
      "run_status": "ok",
    }
    _gate_mod._draft_row = lambda *a, **kw: {
      "finmo_json": "{}",
      "realism_memo_json": "{}",
      "planning_run_json": "{}",
    }
    _gate_mod._persist_verdict = lambda *a, **kw: None
    _gate_mod._parse_json = lambda v: {} if not isinstance(v, dict) else v

    def cleanup():
      _gate_mod._planning_run_row = original_planning_run
      _gate_mod._draft_row = original_draft
      _gate_mod._persist_verdict = original_persist
      _gate_mod._parse_json = original_parse
    return cleanup

  def test_failed_verdict_emits_workbook_accept_rejected(self) -> None:
    from client_intake_and_finmo.post_intake_acceptance.gate import (
      verify_run_acceptance,
    )
    cleanup = self._patch_verdict_internals(passed=False)
    try:
      conn = _FakeConn()
      verdict = verify_run_acceptance(conn, draft_id="d", planning_run_id="r")
      self.assertFalse(verdict["passed"])
      emitted_events = [r[3] for r in conn._store["rows"] if isinstance(r, tuple)]
      # The verdict is failing so we expect the REJECTED emit.
      self.assertIn("workbook_accept_rejected", emitted_events)
    finally:
      cleanup()


class AcceptanceGateSourceShapeTest(unittest.TestCase):
  """Source-shape regression for the workbook_accept emit shape."""
  @classmethod
  def setUpClass(cls) -> None:
    cls.src = ACCEPTANCE_GATE_PATH.read_text(encoding="utf-8")

  def test_acceptance_gate_imports_diagnostics(self) -> None:
    self.assertIn("from client_intake_and_finmo.post_intake_diagnostics import",
                  self.src)

  def test_acceptance_gate_emits_both_accepted_and_rejected(self) -> None:
    self.assertIn("WORKBOOK_ACCEPT_ACCEPTED", self.src)
    self.assertIn("WORKBOOK_ACCEPT_REJECTED", self.src)


if __name__ == "__main__":
  unittest.main()
