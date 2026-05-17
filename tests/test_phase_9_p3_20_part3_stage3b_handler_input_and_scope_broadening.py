"""Phase 9 P3.20 Part 3 Stage 3b -- handler input + scope broadening.

Confirms the funding handler now receives ALL validator failure
categories (cash_buffer_violations, cash_distribution_violations,
cash_surplus_ceiling_violations, cash_contract_failures,
hard_rule_assessment) at its public API and downstream into the
GPT tool-calling session. Lever authority is UNCHANGED (the five
funding levers).

Pre-Stage-3b the handler's public entry
(`engage_funding_handler_on_violations`) accepted only
`cash_buffer_violations`. After Stage 2 relaxed the trigger to fire
on ANY validator failure, the handler was being invoked but had a
blind spot: it never saw WHY (which non-buffer category tripped
keep_changes). Stage 3b closes that gap.

Source-shape regression checks:
  1. Public entry signature accepts the new keyword args.
  2. `run_funding_handler` accepts the new keyword args and forwards
     them to the GPT session.
  3. `run_funding_tool_calling_session` accepts the new keyword args.
  4. The GPT system prompt mentions every failure category.
  5. The GPT initial user prompt embeds every failure category.
  6. Orchestrator invocation site extracts every category from
     `cash_post_validation` and passes them through.
  7. Handler return dict carries `failures_input_summary` with
     per-category counts.
  8. Sanity: Stage 1 (never-revert), Stage 2 (relaxed trigger),
     Stage 3 (Mirror Flavor 1 single rebuild) are preserved.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
  sys.path.insert(0, str(_PYTHON_DIR))

_HANDLER_PY = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "post_intake_funding_handler" / "handler.py"
)
_SESSION_PY = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "post_intake_funding_handler" / "tool_calling_session.py"
)
_ORCHESTRATOR_INVOCATION = (
  _REPO_ROOT / "python" / "client_intake_and_finmo"
  / "post_intake_cash_strategy" / "orchestrator_invocation.py"
)


_BROADENED_CATEGORY_KWARGS = (
  "cash_distribution_violations",
  "cash_surplus_ceiling_violations",
  "cash_contract_failures",
  "hard_rule_assessment",
)


class HandlerSignatureBroadenedTests(unittest.TestCase):
  """The handler's public entry and internal runner accept the new
  failure-category kwargs."""

  def setUp(self) -> None:
    self._src = _HANDLER_PY.read_text(encoding="utf-8")

  def test_engage_helper_accepts_all_new_category_kwargs(self) -> None:
    engage_idx = self._src.find("def engage_funding_handler_on_violations(")
    self.assertGreater(engage_idx, 0, "engage_funding_handler_on_violations not found")
    # Find the closing ) of the signature; it's the next line starting
    # with `) -> Dict[str, Any]:`.
    sig_end_idx = self._src.find(") -> Dict[str, Any]:", engage_idx)
    self.assertGreater(sig_end_idx, engage_idx)
    sig_block = self._src[engage_idx:sig_end_idx]
    for kw in _BROADENED_CATEGORY_KWARGS:
      self.assertIn(
        kw, sig_block,
        f"engage_funding_handler_on_violations signature must accept `{kw}`",
      )

  def test_run_funding_handler_accepts_all_new_category_kwargs(self) -> None:
    run_idx = self._src.find("def run_funding_handler(")
    self.assertGreater(run_idx, 0, "run_funding_handler not found")
    sig_end_idx = self._src.find(") -> FundingHandlerResult:", run_idx)
    self.assertGreater(sig_end_idx, run_idx)
    sig_block = self._src[run_idx:sig_end_idx]
    for kw in _BROADENED_CATEGORY_KWARGS:
      self.assertIn(
        kw, sig_block,
        f"run_funding_handler signature must accept `{kw}`",
      )

  def test_run_funding_handler_forwards_new_kwargs_to_session(self) -> None:
    session_call_idx = self._src.find("session_result = session_runner(")
    self.assertGreater(session_call_idx, 0, "session_runner( call not found")
    # Slice the session_runner( ... ) call.
    after = self._src[session_call_idx:session_call_idx + 2000]
    close_idx = after.find("\n  )")
    self.assertGreater(close_idx, 0, "Could not anchor session_runner( ) close")
    session_call_block = after[:close_idx]
    for kw in _BROADENED_CATEGORY_KWARGS:
      self.assertIn(
        f"{kw}=", session_call_block,
        f"run_funding_handler must forward `{kw}` to session_runner",
      )

  def test_engage_helper_forwards_new_kwargs_to_run_funding_handler(self) -> None:
    call_idx = self._src.find("result = run_funding_handler(")
    self.assertGreater(call_idx, 0, "run_funding_handler( inside engage helper not found")
    after = self._src[call_idx:call_idx + 2000]
    close_idx = after.find("\n  )")
    self.assertGreater(close_idx, 0, "Could not anchor run_funding_handler( ) close")
    call_block = after[:close_idx]
    for kw in _BROADENED_CATEGORY_KWARGS:
      self.assertIn(
        f"{kw}=", call_block,
        f"engage_funding_handler_on_violations must forward `{kw}` to run_funding_handler",
      )

  def test_lever_authority_unchanged(self) -> None:
    """Lever authority must remain the five funding levers (no
    accidental expansion under Stage 3b)."""
    expected_levers = (
      '"schedules::Debt Issuance (New Borrowing)"',
      '"schedules::Debt Repayment (Scheduled)"',
      '"balance_sheet::Owner\'s Capital"',
      '"balance_sheet::Other Equity"',
      '"balance_sheet::Distributions"',
    )
    # FUNDING_LEVER_AUTHORITY is a Tuple[str, ...]; confirm all 5 strings
    # appear and no new lever entries snuck in.
    authority_idx = self._src.find("FUNDING_LEVER_AUTHORITY: Tuple[str, ...] = (")
    self.assertGreater(authority_idx, 0)
    block_end = self._src.find(")\n", authority_idx)
    self.assertGreater(block_end, authority_idx)
    authority_block = self._src[authority_idx:block_end]
    for lever in expected_levers:
      self.assertIn(
        lever, authority_block,
        f"FUNDING_LEVER_AUTHORITY must still include {lever}",
      )
    # Count entries: 5 commas after 5 strings, no extras.
    self.assertEqual(
      authority_block.count('"'), 10,  # 5 strings * 2 quotes each
      "FUNDING_LEVER_AUTHORITY entry count drift (expected 5 levers)",
    )

  def test_return_dict_carries_failures_input_summary(self) -> None:
    self.assertIn(
      'failures_input_summary = {',
      self._src,
      "engage helper must build failures_input_summary",
    )
    # Both RESOLVED and non-RESOLVED return dicts include the summary.
    self.assertEqual(
      self._src.count('"failures_input_summary": failures_input_summary'),
      2,
      "failures_input_summary must appear in BOTH the non-RESOLVED and RESOLVED return dicts",
    )


class SessionPromptAndSignatureBroadenedTests(unittest.TestCase):
  """The GPT tool-calling session signature and prompts include the
  broadened failure-category context."""

  def setUp(self) -> None:
    self._src = _SESSION_PY.read_text(encoding="utf-8")

  def test_session_runner_signature_accepts_new_kwargs(self) -> None:
    run_idx = self._src.find("def run_funding_tool_calling_session(")
    self.assertGreater(run_idx, 0)
    sig_end_idx = self._src.find(") -> FundingToolCallSessionResult:", run_idx)
    self.assertGreater(sig_end_idx, run_idx)
    sig_block = self._src[run_idx:sig_end_idx]
    for kw in _BROADENED_CATEGORY_KWARGS:
      self.assertIn(
        kw, sig_block,
        f"run_funding_tool_calling_session signature must accept `{kw}`",
      )

  def test_initial_user_prompt_builder_accepts_new_kwargs(self) -> None:
    bp_idx = self._src.find("def _build_initial_user_prompt(")
    self.assertGreater(bp_idx, 0)
    sig_end_idx = self._src.find(") -> str:", bp_idx)
    self.assertGreater(sig_end_idx, bp_idx)
    sig_block = self._src[bp_idx:sig_end_idx]
    for kw in _BROADENED_CATEGORY_KWARGS:
      self.assertIn(
        kw, sig_block,
        f"_build_initial_user_prompt signature must accept `{kw}`",
      )

  def test_system_prompt_lists_every_failure_category(self) -> None:
    """Stage 3b broadens the system prompt to mention each failure
    category by name so GPT has full visibility into ANY cash problem."""
    sp_idx = self._src.find("SYSTEM_PROMPT: str = (")
    self.assertGreater(sp_idx, 0)
    sp_close = self._src.find('\n)\n', sp_idx)
    self.assertGreater(sp_close, sp_idx)
    sp_block = self._src[sp_idx:sp_close]
    for category in (
      "cash_buffer_violations",
      "cash_distribution_violations",
      "cash_surplus_ceiling_violations",
      "cash_contract_failures",
      "hard_rule_assessment",
    ):
      self.assertIn(
        category, sp_block,
        f"SYSTEM_PROMPT must mention `{category}` after Stage 3b broadening",
      )

  def test_system_prompt_documents_lever_to_category_mapping(self) -> None:
    """Stage 3b doctrine: the prompt must communicate which levers
    plausibly address which categories so GPT can reason about
    combined fixes rather than only buffer fills."""
    sp_idx = self._src.find("SYSTEM_PROMPT: str = (")
    self.assertGreater(sp_idx, 0)
    sp_close = self._src.find('\n)\n', sp_idx)
    sp_block = self._src[sp_idx:sp_close]
    self.assertIn(
      "Lever-to-failure-category mapping", sp_block,
      "SYSTEM_PROMPT must include a lever-to-category mapping section",
    )

  def test_initial_user_prompt_renders_each_category(self) -> None:
    """The runtime initial user prompt must render each failure
    category as its own labeled block so the GPT model sees the
    full failure picture."""
    bp_idx = self._src.find("def _build_initial_user_prompt(")
    self.assertGreater(bp_idx, 0)
    # Find the function end -- next top-level `def `.
    next_def_idx = self._src.find("\ndef ", bp_idx + 1)
    self.assertGreater(next_def_idx, bp_idx)
    fn_block = self._src[bp_idx:next_def_idx]
    for label in (
      "CASH_BUFFER_VIOLATIONS",
      "CASH_DISTRIBUTION_VIOLATIONS",
      "CASH_SURPLUS_CEILING_VIOLATIONS",
      "CASH_CONTRACT_FAILURES",
      "HARD_RULE_ASSESSMENT",
    ):
      self.assertIn(
        label, fn_block,
        f"_build_initial_user_prompt must render a `{label}` block",
      )


class OrchestratorPassesAllCategoriesTests(unittest.TestCase):
  """The cash orchestrator extracts each validator failure category
  from cash_post_validation and forwards them to the handler."""

  def setUp(self) -> None:
    self._src = _ORCHESTRATOR_INVOCATION.read_text(encoding="utf-8")

  def test_orchestrator_extracts_each_category_from_post_validation(self) -> None:
    for key in (
      "cash_distribution_violations",
      "cash_surplus_ceiling_violations",
      "cash_contract_failures",
    ):
      self.assertIn(
        f'cash_post_validation.get("{key}")',
        self._src,
        f"Orchestrator must extract `{key}` from cash_post_validation",
      )
    self.assertIn(
      'cash_post_validation.get("hard_rule_assessment")',
      self._src,
      "Orchestrator must extract `hard_rule_assessment` from cash_post_validation",
    )

  def test_orchestrator_call_passes_each_new_kwarg(self) -> None:
    call_idx = self._src.find("cash_funding_handler_result = engage_funding_handler_on_violations(")
    self.assertGreater(call_idx, 0)
    after = self._src[call_idx:call_idx + 3000]
    close_idx = after.find("\n    )")
    self.assertGreater(close_idx, 0, "Could not anchor engage_funding_handler_on_violations( ) close")
    call_block = after[:close_idx]
    for kw in _BROADENED_CATEGORY_KWARGS:
      self.assertIn(
        f"{kw}=", call_block,
        f"Orchestrator must pass `{kw}` to engage_funding_handler_on_violations",
      )

  def test_orchestrator_documents_stage_3b_broadening(self) -> None:
    """The Stage 2 trigger comment is updated to document Stage 3b's
    broadening so future readers see why the payload includes the
    additional categories."""
    self.assertIn(
      "Stage 3b -- broaden the handler's INPUT PAYLOAD",
      self._src,
      "Orchestrator must document Stage 3b's payload broadening",
    )
    self.assertIn(
      "UNCHANGED (five funding levers)",
      self._src,
      "Orchestrator must note that Stage 3b does NOT expand lever authority",
    )


class StagesOnePastPreservedTests(unittest.TestCase):
  """Sanity: Stage 3b did not accidentally revert Stages 1, 2, or 3."""

  def setUp(self) -> None:
    self._src = _ORCHESTRATOR_INVOCATION.read_text(encoding="utf-8")

  def test_stage_1_never_revert_still_in_place(self) -> None:
    self.assertNotIn(
      "final_model_input_json = copy.deepcopy(pre_cash_model_input_json)\n    final_finmo_json = copy.deepcopy(pre_cash_finmo_json)",
      self._src,
      "Stage 1 NEVER-revert change must still be in effect",
    )

  def test_stage_2_trigger_relaxation_still_in_place(self) -> None:
    self.assertNotIn(
      "and cash_buffer_violations_for_handler\n",
      self._src,
      "Stage 2 handler trigger relaxation must still be in effect",
    )

  def test_stage_3_pre_validator_rebuild_still_in_place(self) -> None:
    self.assertIn(
      "_rebuilt_pre_validation",
      self._src,
      "Stage 3 pre-validator FINMO rebuild must still be in effect",
    )
    rebuild_idx = self._src.find(
      'cash_strategy_second_pass_result["updated_finmo_json"] = _rebuilt_pre_validation'
    )
    validator_idx = self._src.find("_validate_cash_strategy_post_pass(")
    self.assertGreater(rebuild_idx, 0)
    self.assertGreater(validator_idx, 0)
    self.assertLess(
      rebuild_idx, validator_idx,
      "Stage 3 rebuild must still appear BEFORE the validator call",
    )


if __name__ == "__main__":
  unittest.main()
