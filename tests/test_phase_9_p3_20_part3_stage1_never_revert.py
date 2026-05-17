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


class ConvergenceRunnerNeverRevertTests(unittest.TestCase):
  """Source-shape regression checks on the unified convergence
  cash strategy path (post_intake_convergence/runner.py inside
  _run_unified_post_grid_system_run)."""

  def setUp(self) -> None:
    self._src = _CONVERGENCE_RUNNER.read_text(encoding="utf-8")

  def test_convergence_runner_revert_else_branch_removed(self) -> None:
    """The `else:` branch that set final_model_input_json from
    pre_cash and mutated cash_strategy_second_pass_result["status"]
    to "reverted_post_validation" must be gone."""
    self.assertNotIn(
      "reverted_post_validation",
      self._src,
      "convergence runner must no longer set cash_strategy_second_pass_result['status'] = 'reverted_post_validation'",
    )
    self.assertNotIn(
      "converged_model_reverted",
      self._src,
      "convergence runner must no longer set cash_strategy_second_pass_result['final_model_source'] = 'converged_model_reverted'",
    )

  def test_convergence_runner_unconditional_proposer_outputs(self) -> None:
    """After the revert removal, the final_model_input_json
    assignment block runs unconditionally and reads from
    cash_strategy_second_pass_result + cash_post_validation."""
    # The Stage 1 fix replaces the if/else with the if-body alone.
    # Look for the pattern signature of the new code.
    self.assertIn(
      "final_model_input_json = _model_input_with_controller_catalog(",
      self._src,
    )
    self.assertIn(
      "final_finmo_json = copy.deepcopy(cash_strategy_second_pass_result.get(\"updated_finmo_json\") or {})",
      self._src,
    )

  def test_convergence_runner_pre_cash_revert_pattern_removed(self) -> None:
    """The `else: final_model_input_json = copy.deepcopy(pre_cash_model_input_json)`
    pattern in the cash post-validation block is gone."""
    # The pre-iter pattern had `final_model_input_json = copy.deepcopy(pre_cash_model_input_json)`
    # inside an else branch following the keep_changes check.
    pattern = re.compile(
      r"if bool\(cash_post_validation\.get\(\"keep_changes\"\)\):[^}]*?else:\s*\n\s*final_model_input_json\s*=\s*copy\.deepcopy\(pre_cash_model_input_json\)",
      re.DOTALL,
    )
    self.assertIsNone(
      pattern.search(self._src),
      "convergence runner must no longer revert final_model_input_json to pre_cash on keep_changes=False",
    )


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

  def test_convergence_runner_persists_second_pass_result_in_application_stage(self) -> None:
    """The convergence runner persists cash_strategy_second_pass_result
    at the cash_pass_validation_running stage via
    _persist_cash_pass_stage. With the revert removed, that
    payload now contains the actual proposer outputs even when
    keep_changes=False."""
    src = _CONVERGENCE_RUNNER.read_text(encoding="utf-8")
    self.assertIn(
      "cash_strategy_second_pass_result_payload=copy.deepcopy(cash_strategy_second_pass_result)",
      src,
      "convergence runner must persist cash_strategy_second_pass_result with proposer outputs intact",
    )


if __name__ == "__main__":
  unittest.main()
