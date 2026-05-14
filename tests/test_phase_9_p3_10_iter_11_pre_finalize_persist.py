"""Phase 9 P3.10 iter 11 diagnostic — pre-finalize state persist.

Iter 11's failure analysis revealed `_persist_failed_system_run_snapshot`
reads from SQL (intake_consult_drafts.model_input_json), but on the
orchestrator's failure path SQL was last written BEFORE the cascade.
The persisted snapshot was therefore PRE-cascade post-grid state —
NOT what finalize actually validated.

This test asserts the orchestrator now persists the in-memory
pre-finalize state immediately before run_finalize_post_intake_validation
so failure post-mortems read the actual finalize-time state.

Source-level test (no E2E): the orchestrator's _run_post_cascade_completion
contains a `_persist_unified_convergence_state` call with
stage="pre_finalize_validation" status="running" placed BEFORE the
finalize call. No invisible failure states.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


ORCHESTRATOR_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_solver"
  / "orchestrator.py"
)


class PreFinalizePersistTest(unittest.TestCase):
  def test_pre_finalize_persist_call_exists(self) -> None:
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      'stage="pre_finalize_validation"',
      text,
      "Expected `stage=\"pre_finalize_validation\"` persist call in orchestrator",
    )

  def test_pre_finalize_persist_uses_running_status(self) -> None:
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    # Find the pre_finalize_validation block and verify status="running"
    idx = text.find('stage="pre_finalize_validation"')
    self.assertGreater(idx, 0)
    block = text[idx: idx + 200]
    self.assertIn(
      'status="running"',
      block,
      "Expected pre-finalize persist to use status=\"running\" "
      "(matches existing in-progress convention)",
    )

  def test_pre_finalize_persist_appears_before_finalize_call(self) -> None:
    """The persist must be ordered before run_finalize_post_intake_validation."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    persist_idx = text.find('stage="pre_finalize_validation"')
    self.assertGreater(persist_idx, 0)
    finalize_idx = text.find(
      "finalize_result = run_finalize_post_intake_validation(",
      persist_idx,  # search FROM the persist position forward
    )
    self.assertGreater(
      finalize_idx, persist_idx,
      "Pre-finalize persist must appear in source BEFORE the finalize call. "
      "Otherwise the snapshot won't reflect the state finalize actually validated.",
    )

  def test_pre_finalize_persist_passes_in_memory_final_state(self) -> None:
    """The persist call must use the orchestrator's in-memory
    final_model_input_json and final_finmo_json — NOT a stale snapshot."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    persist_idx = text.find('stage="pre_finalize_validation"')
    block_end = text.find("completion_trace[\"persist_pre_finalize_state\"]", persist_idx)
    self.assertGreater(block_end, persist_idx)
    block = text[persist_idx:block_end]
    self.assertIn(
      "model_input_json=copy.deepcopy(final_model_input_json or {})",
      block,
      "Pre-finalize persist must capture the orchestrator's in-memory final_model_input_json",
    )
    self.assertIn(
      "finmo_json=copy.deepcopy(final_finmo_json or {})",
      block,
      "Pre-finalize persist must capture the orchestrator's in-memory final_finmo_json",
    )

  def test_pre_finalize_persist_wrapped_in_try_except(self) -> None:
    """A persist failure must NOT block finalize from running. Wrap
    the persist in try/except, record completion_trace, continue."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    # Find the pre-finalize persist try block
    persist_idx = text.find('stage="pre_finalize_validation"')
    # walk backward for the enclosing `try:`
    pre_block = text[max(0, persist_idx - 600):persist_idx]
    self.assertIn(
      "try:",
      pre_block,
      "Pre-finalize persist must be inside a try/except block",
    )
    # And the except clause is just below
    next_block = text[persist_idx: persist_idx + 2500]
    self.assertIn(
      "except Exception as _pre_finalize_persist_exc",
      next_block,
      "Persist failure must be caught explicitly with completion_trace recording",
    )

  def test_pre_finalize_persist_marker_in_cash_strategy_second_pass_result(self) -> None:
    """The persist payload should mark itself as the pre-finalize snapshot
    (not a real cash_strategy_second_pass_result) so post-mortem readers
    can distinguish it from a finalize-success persist."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    persist_idx = text.find('stage="pre_finalize_validation"')
    block_end = text.find("completion_trace[\"persist_pre_finalize_state\"]", persist_idx)
    block = text[persist_idx:block_end]
    self.assertIn(
      'cash_strategy_second_pass_result={"pre_finalize_snapshot": True}',
      block,
      "Pre-finalize persist must tag cash_strategy_second_pass_result with "
      "{\"pre_finalize_snapshot\": True} so post-mortem readers can distinguish it",
    )


if __name__ == "__main__":
  unittest.main()
