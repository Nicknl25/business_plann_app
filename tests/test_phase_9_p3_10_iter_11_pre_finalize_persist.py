"""Phase 9 P3.10 iter 11 diagnostic — pre-finalize state persist.

Iter 11's failure analysis revealed `_persist_failed_system_run_snapshot`
reads from SQL (intake_consult_drafts.model_input_json), but on the
orchestrator's failure path SQL was last written BEFORE the cascade.
The persisted snapshot was therefore PRE-cascade post-grid state —
NOT what finalize actually validated.

This test asserts the orchestrator persists the in-memory
pre-finalize state immediately before run_finalize_post_intake_validation
so failure post-mortems read the actual finalize-time state.

Note: the original de3de02 implementation went through
_persist_unified_convergence_state (which routed through a deep
abstraction). Iter 12 Piece A replaced that with a direct SQL UPDATE
that hits the same columns the failure-snapshot reader consults +
read-back verification + hard-fail under test mode. Tests below check
the architectural invariants (persist exists, ordered before finalize,
captures in-memory state, wrapped in try/except), not the specific
API call. The Piece A specifics live in
test_phase_9_p3_10_iter_12_blind_spot_diagnostic.py.
"""

from __future__ import annotations

import os
import pathlib
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
  def test_pre_finalize_persist_exists(self) -> None:
    """A pre-finalize persist MUST exist (any implementation)."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "pre_finalize",
      text,
      "Some pre-finalize persist mechanism must exist in orchestrator",
    )

  def test_pre_finalize_persist_marker_tag_present(self) -> None:
    """The persist must include a stable marker tag a post-mortem
    can verify."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      '"tag": "pre_finalize_persist"',
      text,
      "Persist must embed a stable marker tag for post-mortem verification",
    )

  def test_pre_finalize_persist_appears_before_finalize_call(self) -> None:
    """The persist must be ordered before run_finalize_post_intake_validation."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    persist_idx = text.find('"tag": "pre_finalize_persist"')
    self.assertGreater(persist_idx, 0)
    finalize_idx = text.find(
      "finalize_result = run_finalize_post_intake_validation(",
      persist_idx,
    )
    self.assertGreater(
      finalize_idx, persist_idx,
      "Pre-finalize persist must appear in source BEFORE the finalize call.",
    )

  def test_pre_finalize_persist_captures_in_memory_final_state(self) -> None:
    """Persist must use the orchestrator's in-memory final_model_input_json
    and final_finmo_json — NOT a stale snapshot."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    persist_idx = text.find('"tag": "pre_finalize_persist"')
    block = text[persist_idx: persist_idx + 4000]
    self.assertIn(
      "final_model_input_json",
      block,
      "Pre-finalize persist must capture the orchestrator's in-memory final_model_input_json",
    )
    self.assertIn(
      "final_finmo_json",
      block,
      "Pre-finalize persist must capture the orchestrator's in-memory final_finmo_json",
    )

  def test_pre_finalize_persist_wrapped_in_try_except(self) -> None:
    """A persist failure must be caught with completion_trace recording.
    Under test mode the catch may re-raise (Piece A) but must record
    the failure first."""
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    persist_idx = text.find('"tag": "pre_finalize_persist"')
    pre_block = text[max(0, persist_idx - 600):persist_idx]
    self.assertIn(
      "try:",
      pre_block,
      "Pre-finalize persist must be inside a try/except block",
    )
    next_block = text[persist_idx: persist_idx + 4000]
    self.assertIn(
      "except Exception",
      next_block,
      "Persist failure must be caught explicitly",
    )
    self.assertIn(
      "completion_trace[\"persist_pre_finalize_state\"]",
      next_block,
      "completion_trace must record the persist outcome (success or failure)",
    )


if __name__ == "__main__":
  unittest.main()
