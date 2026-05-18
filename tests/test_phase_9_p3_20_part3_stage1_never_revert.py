"""Phase 9 P3.20 Part 3 Stage 1 — NEVER revert tests.

Confirms the orchestrator/cash-strategy paths no longer discard
the cash proposer's outputs when cash_post_validation reports
keep_changes=False. The proposer's updated_model_input_json /
updated_finmo_json / second_pass_result metadata persist into
the downstream final state regardless of keep_changes.

Two revert paths existed pre-iter:
1. post_intake_cash_strategy/orchestrator_invocation.py:545-558
2. post_intake_convergence/runner.py:3130-3150 (inside
   _run_unified_post_grid_system_run)

Both are fixed. Stage 1 only changes the revert path; the handler
trigger logic at orchestrator_invocation.py:449-453 stays
unchanged (Stage 2 will relax that).
"""
from __future__ import annotations

import re
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
_CONVERGENCE_RUNNER = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "post_intake_convergence" / "runner.py"
)


class OrchestratorInvocationNeverRevertTests(unittest.TestCase):
  """Source-shape regression checks on the post-cascade cash
  strategy entry point (post_intake_cash_strategy/orchestrator_
  invocation.py)."""

  def setUp(self) -> None:
    self._src = _ORCHESTRATOR_INVOCATION.read_text(encoding="utf-8")

  def test_revert_else_branch_removed_from_orchestrator_invocation(self) -> None:
    """The `if keep_changes: ... else: final_model_input_json =
    copy.deepcopy(pre_cash_model_input_json)` pattern must be gone."""
    # The pre-iter pattern: `else:\n    final_model_input_json = copy.deepcopy(pre_cash_model_input_json)`
    # appearing IMMEDIATELY after `if keep_changes:` block.
    pattern = re.compile(
      r"if keep_changes:\s*\n[^}]*?else:\s*\n\s*final_model_input_json\s*=\s*copy\.deepcopy\(pre_cash_model_input_json\)",
      re.DOTALL,
    )
    self.assertIsNone(
      pattern.search(self._src),
      "orchestrator_invocation.py must no longer contain `if keep_changes: ... else: final_model_input_json = pre_cash_model_input_json` revert pattern",
    )

  def test_orchestrator_invocation_always_takes_proposer_outputs(self) -> None:
    """The final_model_input_json assignment is now unconditional
    (always reads from cash_strategy_second_pass_result with the
    pre_cash fallback for None)."""
    # There should be exactly ONE final_model_input_json assignment
    # in the cash-strategy result-collation area, and it should
    # use the proposer's output (not pre_cash) as the primary
    # value.
    self.assertIn(
      "final_model_input_json = (\n    cash_strategy_second_pass_result.get(\"updated_model_input_json\")",
      self._src,
      "orchestrator_invocation.py final_model_input_json must take proposer output unconditionally",
    )

  def test_orchestrator_invocation_keep_changes_still_present_for_handler_trigger(self) -> None:
    """Stage 1 does not touch handler trigger logic. `keep_changes`
    is still computed and consulted at the handler trigger
    condition. Stage 2 fixes the trigger."""
    self.assertIn(
      "keep_changes = bool(cash_post_validation.get",
      self._src,
      "orchestrator_invocation.py must still compute keep_changes from cash_post_validation",
    )
    # Handler trigger condition retains `not keep_changes`
    self.assertIn(
      "not keep_changes",
      self._src,
      "Handler trigger condition `not keep_changes` is unchanged (Stage 2 will relax it)",
    )


class ConvergenceRunnerDeletedTests(unittest.TestCase):
  """Phase 9 P3.24 — the convergence runner's
  `_run_unified_post_grid_system_run` was deleted as part of the
  unified_convergence_decision cleanup (P3.24 Commit 3). The P3.20
  Stage 1 source-shape regression tests this class replaced asserted
  the absence of revert patterns IN that function; with the function
  itself gone, the absence-of-revert property holds trivially. The
  test now asserts the deletion itself, so a future re-introduction
  of the function would surface as a test failure rather than a
  silent re-architecture.
  """

  def setUp(self) -> None:
    self._src = _CONVERGENCE_RUNNER.read_text(encoding="utf-8")

  def test_convergence_runner_function_deleted(self) -> None:
    """The legacy convergence cycle loop must remain DELETED.
    Re-introducing it would re-open the P3.23a Anderson & Blake and
    CareFirst gaps via the broken-validator-suppression path the
    Phase 8 bypass marker warned about
    (orchestrator.py:1342-1347, pre-P3.24)."""
    self.assertNotIn(
      "def _run_unified_post_grid_system_run(",
      self._src,
      "convergence runner's _run_unified_post_grid_system_run must remain deleted post P3.24",
    )
    self.assertNotIn(
      "run_unified_post_grid_system_run = _run_unified_post_grid_system_run",
      self._src,
      "the public alias must remain deleted",
    )

  def test_convergence_runner_revert_patterns_remain_absent(self) -> None:
    """P3.20 Stage 1 regression — the never-revert intent of the
    original tests held: 'reverted_post_validation' and
    'converged_model_reverted' must not appear in the convergence
    runner. With the function deleted, this holds trivially; the
    assertion still encodes the architectural intent."""
    self.assertNotIn("reverted_post_validation", self._src)
    self.assertNotIn("converged_model_reverted", self._src)


class CashContractFailureMetadataSurvivesTests(unittest.TestCase):
  """The point of Stage 1 is to make sure cash_contract_failure
  metadata (and the broader cash_strategy_second_pass_result)
  carries forward downstream. Pre-iter the revert discarded the
  result; now it persists.

  These are documentation tests on the code shape, since the
  actual persistence path is many layers downstream of the
  orchestrator function. The downstream persistence reads from
  the dict the orchestrator returns, so as long as the
  orchestrator no longer reverts, the metadata is downstream-
  reachable.
  """

  def test_orchestrator_invocation_returns_cash_strategy_second_pass_result(self) -> None:
    """The orchestrator's CashStrategyResult return includes the
    full second_pass_result (which includes any cash_contract_failure
    metadata). This was always the case; Stage 1 doesn't change
    the return shape. Documenting that the return is preserved
    is part of the Stage 1 contract."""
    src = _ORCHESTRATOR_INVOCATION.read_text(encoding="utf-8")
    self.assertIn(
      "second_pass_result=copy.deepcopy(cash_strategy_second_pass_result)",
      src,
      "Orchestrator return must include second_pass_result with the proposer + handler outputs (and any contract_failure metadata)",
    )

  def test_convergence_runner_persistence_call_no_longer_present(self) -> None:
    """Phase 9 P3.24 — the convergence runner's
    _run_unified_post_grid_system_run was deleted along with the
    legacy convergence cycle loop. The cash_strategy_second_pass_result
    persistence the original test asserted on lived inside that
    deleted function. With the function gone, the assertion holds
    trivially: no convergence-runner persistence call exists
    anywhere in the codebase outside of the new path (which now
    persists via the orchestrator's own _persist_unified_convergence_state
    at orchestrator.py:2749). The new path is exercised by the
    CashContractFailureMetadataSurvivesTests sibling test above
    that inspects the orchestrator_invocation.py return shape."""
    src = _CONVERGENCE_RUNNER.read_text(encoding="utf-8")
    self.assertNotIn(
      "cash_strategy_second_pass_result_payload=copy.deepcopy(",
      src,
      "P3.24 deletion: the convergence runner no longer carries the "
      "second_pass_result persistence call (it lived inside the "
      "deleted _run_unified_post_grid_system_run function)",
    )


if __name__ == "__main__":
  unittest.main()
