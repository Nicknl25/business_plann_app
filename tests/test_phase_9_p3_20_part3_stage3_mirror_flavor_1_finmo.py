"""Phase 9 P3.20 Part 3 Stage 3 — Mirror Flavor 1 FINMO state.

Confirms a single FINMO rebuild site is canonical -- the post-pass
validator, the handler trigger, the handler itself, and the
downstream final state all see the SAME FINMO. No outer
"after-the-fact" rebuild can change what downstream consumers see
compared to what the validator saw.

Before Stage 3, the orchestrator did two FINMO rebuilds in cash
strategy:
  1. Each cash sub-step (apply_cash_strategy_exact_updates,
     apply_cash_pass_minimum_debt_schedule, apply_cash_policy_
     surplus_cleanup) rebuilt FINMO internally via execute_numeric_
     plan or similar.
  2. After the validator + handler dance completed, an OUTER
     rebuild from final_model_input_json overwrote
     final_finmo_json.

If the outer rebuild produced different numbers than the cash
sub-steps' rebuild (or the handler's rebuild), the validator
made decisions on a stale FINMO and downstream saw something
else. Mirror Flavor 1 doctrine violation.

After Stage 3 there is ONE canonical rebuild, located BEFORE the
post-pass validator. The result is written to
cash_strategy_second_pass_result["updated_finmo_json"]. Every
downstream consumer reads from that single source.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(_PYTHON_DIR))

_ORCHESTRATOR_INVOCATION = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "post_intake_cash_strategy" / "orchestrator_invocation.py"
)


class MirrorFlavor1FinmoStateTests(unittest.TestCase):
  """Source-shape regression checks on the rebuild ordering."""

  def setUp(self) -> None:
    self._src = _ORCHESTRATOR_INVOCATION.read_text(encoding="utf-8")

  def test_pre_validator_rebuild_is_present(self) -> None:
    """A FINMO rebuild block exists BEFORE the post-pass validator
    call, reading from cash_strategy_second_pass_result.updated_
    model_input_json and writing back to its updated_finmo_json."""
    # Anchor on the pre-validator rebuild's distinctive variable
    # name introduced by Stage 3.
    self.assertIn(
      "_rebuilt_pre_validation",
      self._src,
      "Pre-validator FINMO rebuild must exist (introduced in Stage 3)",
    )
    self.assertIn(
      'cash_strategy_second_pass_result["updated_finmo_json"] = _rebuilt_pre_validation',
      self._src,
      "Pre-validator rebuild must write back to cash_strategy_second_pass_result.updated_finmo_json",
    )

  def test_pre_validator_rebuild_runs_before_validator(self) -> None:
    """Verify ordering: the rebuild assignment must appear in the
    source BEFORE the _validate_cash_strategy_post_pass call."""
    rebuild_idx = self._src.find('cash_strategy_second_pass_result["updated_finmo_json"] = _rebuilt_pre_validation')
    validator_idx = self._src.find("_validate_cash_strategy_post_pass(")
    self.assertGreater(rebuild_idx, 0, "Rebuild assignment not found")
    self.assertGreater(validator_idx, 0, "Validator call not found")
    self.assertLess(
      rebuild_idx, validator_idx,
      "Pre-validator rebuild must appear in the source BEFORE the validator call",
    )

  def test_outer_rebuild_block_removed(self) -> None:
    """The pre-Stage-3 OUTER rebuild block (after the validator and
    after the final_model_input_json assignment) must be gone. The
    `cash_strategy_final_finmo_rebuild_failed` operation code is
    preserved at the NEW pre-validator rebuild location (preserves
    the Phase 9 P3.10 Commit 4 intent that FINMO rebuild failures
    raise under test mode). Verify position: any occurrence of
    that operation code must appear BEFORE the validator call,
    not after final_model_input_json assignment."""
    # Operation code should appear exactly once
    occurrences = self._src.count("cash_strategy_final_finmo_rebuild_failed")
    self.assertEqual(
      occurrences, 1,
      f"cash_strategy_final_finmo_rebuild_failed should appear exactly once (at the new pre-validator location), found {occurrences}",
    )
    # And that occurrence must be BEFORE the validator call
    op_code_idx = self._src.find("cash_strategy_final_finmo_rebuild_failed")
    validator_idx = self._src.find("_validate_cash_strategy_post_pass(")
    self.assertGreater(op_code_idx, 0)
    self.assertGreater(validator_idx, 0)
    self.assertLess(
      op_code_idx, validator_idx,
      "cash_strategy_final_finmo_rebuild_failed must be at the pre-validator rebuild site, not at any post-validator location",
    )

  def test_outer_rebuild_overwrite_pattern_removed(self) -> None:
    """The specific outer-rebuild assignment pattern
    `final_finmo_json = rebuilt_finmo` after the if-keep_changes
    block must be gone."""
    # The pre-Stage-3 code used `rebuilt_finmo = build_python_finmo_json(...)`
    # followed by `final_finmo_json = rebuilt_finmo`. That variable
    # name should no longer appear in the function body.
    self.assertNotIn(
      "rebuilt_finmo = build_python_finmo_json(",
      self._src,
      "Outer rebuild assignment using `rebuilt_finmo = build_python_finmo_json(...)` must be removed",
    )

  def test_doctrine_comment_documents_single_source_of_truth(self) -> None:
    """The Stage 3 comment must explicitly document the Mirror
    Flavor 1 principle so future readers understand why the
    rebuild was hoisted."""
    self.assertIn(
      "Mirror Flavor 1",
      self._src,
      "Stage 3 comment must reference Mirror Flavor 1 doctrine",
    )
    self.assertIn(
      "single source of truth",
      self._src.lower(),
      "Stage 3 comment must reference single source of truth principle",
    )

  def test_final_state_assignment_reads_from_cash_strategy_second_pass_result(self) -> None:
    """The final_model_input_json / final_finmo_json assignments
    must read from cash_strategy_second_pass_result (the canonical
    source post-Stage-3, since the outer rebuild is gone)."""
    self.assertIn(
      'final_finmo_json = (\n    cash_strategy_second_pass_result.get("updated_finmo_json")',
      self._src,
      "final_finmo_json must read from cash_strategy_second_pass_result.updated_finmo_json",
    )
    self.assertIn(
      'final_model_input_json = (\n    cash_strategy_second_pass_result.get("updated_model_input_json")',
      self._src,
      "final_model_input_json must read from cash_strategy_second_pass_result.updated_model_input_json",
    )

  def test_stage_1_and_stage_2_changes_still_in_place(self) -> None:
    """Sanity: Stage 3 didn't accidentally revert Stages 1 or 2."""
    # Stage 1: no atomic revert pattern
    self.assertNotIn(
      "final_model_input_json = copy.deepcopy(pre_cash_model_input_json)\n    final_finmo_json = copy.deepcopy(pre_cash_finmo_json)",
      self._src,
      "Stage 1 NEVER-revert change must still be in effect",
    )
    # Stage 2: handler trigger no longer requires buffer violations
    self.assertNotIn(
      "and cash_buffer_violations_for_handler\n",
      self._src,
      "Stage 2 handler trigger relaxation must still be in effect",
    )


if __name__ == "__main__":
  unittest.main()
