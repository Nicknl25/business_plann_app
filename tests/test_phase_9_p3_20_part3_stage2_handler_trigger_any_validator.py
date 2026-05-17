"""Phase 9 P3.20 Part 3 Stage 2 — handler trigger relaxed.

Confirms the funding handler now engages on ANY validator failure
post-pass, not just on cash_buffer_violations. The trigger
condition at post_intake_cash_strategy/orchestrator_invocation.py
is `not keep_changes AND isinstance(second_pass_result, dict)`.
The pre-Stage-2 buffer-violations-non-empty gate has been removed.

`keep_changes` is the canonical "any validator popped" signal
since the runner.py `keep_changes` formula evaluates to False
when any of:
  - hard_rule_assessment all_hard_rules_cleared is False
  - cash_buffer_violations non-empty
  - cash_distribution_violations non-empty
  - cash_contract_failures non-empty

So `not keep_changes` captures all four categories.
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


class HandlerTriggerNoLongerRequiresBufferViolationsTests(unittest.TestCase):
  """Source-shape regression checks on the handler trigger
  condition."""

  def setUp(self) -> None:
    self._src = _ORCHESTRATOR_INVOCATION.read_text(encoding="utf-8")

  def _trigger_block_source(self) -> str:
    """Slice the source from the trigger comment header through
    the `engage_funding_handler_on_violations(` call -- the
    inclusive window contains the if-block condition and the
    handler invocation."""
    start_marker = "cash_buffer_violations_for_handler = list("
    start = self._src.find(start_marker)
    self.assertGreater(start, 0, "Could not anchor trigger block start")
    end_marker = "engage_funding_handler_on_violations("
    end = self._src.find(end_marker, start)
    self.assertGreater(end, start, "Could not anchor handler call")
    return self._src[start:end]

  def test_trigger_condition_no_longer_requires_cash_buffer_violations_non_empty(self) -> None:
    """The if-block immediately before the handler invocation
    must NOT contain `and cash_buffer_violations_for_handler`
    as a truthiness gate."""
    block = self._trigger_block_source()
    # The variable still exists (used as a parameter to the
    # handler call), but the trigger condition no longer ANDs
    # on its truthiness.
    self.assertNotIn(
      "and cash_buffer_violations_for_handler\n",
      block,
      "Handler trigger condition must NOT include `and cash_buffer_violations_for_handler` truthiness gate",
    )

  def test_trigger_condition_still_requires_not_keep_changes(self) -> None:
    block = self._trigger_block_source()
    self.assertIn(
      "not keep_changes",
      block,
      "Handler trigger condition must still consult `not keep_changes`",
    )

  def test_trigger_condition_still_requires_second_pass_result_dict(self) -> None:
    block = self._trigger_block_source()
    self.assertIn(
      "isinstance(cash_strategy_second_pass_result, dict)",
      block,
      "Handler trigger condition must still require second_pass_result to be a dict",
    )

  def test_handler_call_still_passes_cash_buffer_violations_input(self) -> None:
    """Stage 2 does not change the handler's API. The handler
    still receives cash_buffer_violations_for_handler (which may
    now be empty when other validator categories trip
    keep_changes). Future stages can broaden the input to include
    distribution/contract failure categories."""
    self.assertIn(
      "cash_buffer_violations=cash_buffer_violations_for_handler",
      self._src,
      "Handler invocation must still pass cash_buffer_violations (may now be empty)",
    )

  def test_doctrine_comment_explains_any_validator_principle(self) -> None:
    """The trigger comment must document the doctrine principle:
    severity does not matter; if a validator pops, the handler
    engages."""
    self.assertIn(
      "ANY validator failure",
      self._src,
      "orchestrator_invocation.py must document the ANY-validator-failure principle in the trigger comment",
    )
    # Reference back to Part 3 Stage 2 for archaeology
    self.assertIn(
      "Stage 2",
      self._src,
      "Trigger comment must label this as the Stage 2 change",
    )

  def test_stage_1_revert_removal_still_in_place(self) -> None:
    """Sanity check: Stage 1's NEVER revert change must still
    be present. Verifies Stage 2 didn't accidentally re-introduce
    a revert path."""
    pattern = re.compile(
      r"if keep_changes:\s*\n[^}]*?else:\s*\n\s*final_model_input_json\s*=\s*copy\.deepcopy\(pre_cash_model_input_json\)",
      re.DOTALL,
    )
    self.assertIsNone(
      pattern.search(self._src),
      "Stage 1's never-revert change must still be in effect",
    )


if __name__ == "__main__":
  unittest.main()
