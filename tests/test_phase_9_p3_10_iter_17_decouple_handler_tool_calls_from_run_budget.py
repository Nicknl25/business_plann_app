"""Phase 9 P3.10 iter 17 (Batch A) — decouple handler tool-call rounds
from the run-wide GPT call budget.

Pre-iter-17, every `call_gpt_responses_api_turn` invocation
(handler tool-call round) consumed one slot of the run-wide
`_GPT_CALL_BUDGET_PER_RUN = 8`. A handler engagement that needed 5
internal tool rounds therefore burned 5 of the 8 slots reserved for
regular critique calls. The handler's stated `HARD_CAP_TOOL_CALLS = 10`
authority was effectively "10 OR whatever's left of the run-wide
budget, whichever is smaller" — leading to F5 failures
(`gpt_exhaustion_handler_tool_calling_session_turn_failed:
gpt_call_budget_exhausted`) on the 27-draft sweep.

Iter 17 fix: `call_gpt_responses_api_turn` now accepts
`counts_against_run_budget: bool = True`. The handler's call site
passes False so its rounds:
  - bypass the `_budget_exhausted()` check,
  - do NOT increment `_gpt_call_count`,
  - DO still append to `_gpt_call_log` with
    `counted_against_run_budget: False` for diagnostic visibility.

This is a budget-SCOPING fix, not a budget-RAISING fix:
  - run-wide cap stays at 8 (regular critique calls)
  - handler cap stays at 10 (HARD_CAP_TOOL_CALLS)
  - separate budgets, separate concerns, no commingling.
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest.mock import patch


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


GPT_CRITIC_IO_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo" / "post_intake_solver" / "_gpt_critic_io.py"
)
TOOL_CALLING_SESSION_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo" / "post_intake_gpt_exhaustion_handler"
  / "tool_calling_session.py"
)


class _RecordGptCallFlagTest(unittest.TestCase):
  """`_record_gpt_call(..., counted_against_run_budget=False)` must
  log without incrementing the counter."""

  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_solver import _gpt_critic_io as mod  # noqa: WPS433
    self._mod = mod
    mod.reset_gpt_call_budget()

  def tearDown(self) -> None:
    self._mod.reset_gpt_call_budget()

  def test_default_increments_run_budget(self) -> None:
    self._mod._record_gpt_call("regular_critic", "python_proposer_plus_gpt_critic")
    self.assertEqual(self._mod.get_gpt_call_count(), 1)
    log = self._mod.get_gpt_call_log()
    self.assertEqual(len(log), 1)
    self.assertEqual(log[0]["counted_against_run_budget"], True)
    self.assertEqual(log[0]["call_index"], 1)

  def test_counts_against_run_budget_false_logs_without_increment(self) -> None:
    self._mod._record_gpt_call(
      "handler_round_1",
      "python_proposer_plus_gpt_critic",
      counted_against_run_budget=False,
    )
    self.assertEqual(self._mod.get_gpt_call_count(), 0)
    log = self._mod.get_gpt_call_log()
    self.assertEqual(len(log), 1)
    self.assertEqual(log[0]["counted_against_run_budget"], False)
    self.assertIsNone(log[0]["call_index"])

  def test_mixed_calls_count_only_run_budget_ones(self) -> None:
    """7 handler rounds + 4 regular critic calls -> counter = 4."""
    for i in range(7):
      self._mod._record_gpt_call(
        f"handler_round_{i+1}",
        "python_proposer_plus_gpt_critic",
        counted_against_run_budget=False,
      )
    for i in range(4):
      self._mod._record_gpt_call(
        f"regular_critic_{i+1}",
        "python_proposer_plus_gpt_critic",
      )
    self.assertEqual(self._mod.get_gpt_call_count(), 4)
    log = self._mod.get_gpt_call_log()
    self.assertEqual(len(log), 11)
    self.assertEqual(sum(1 for e in log if e["counted_against_run_budget"]), 4)
    self.assertEqual(sum(1 for e in log if not e["counted_against_run_budget"]), 7)
    # Neither cap exhausted (run-wide 8 not reached, handler cap 10 not reached)
    self.assertFalse(self._mod._budget_exhausted())


class CallGptResponsesApiTurnSignatureTest(unittest.TestCase):
  def test_signature_includes_counts_against_run_budget(self) -> None:
    import inspect
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # noqa: WPS433
      call_gpt_responses_api_turn,
    )
    sig = inspect.signature(call_gpt_responses_api_turn)
    self.assertIn("counts_against_run_budget", sig.parameters)
    param = sig.parameters["counts_against_run_budget"]
    # Default must be True (preserves behavior for unmodified callers)
    self.assertEqual(param.default, True)


class HandlerCallSiteUsesFalseTest(unittest.TestCase):
  """The single handler call site MUST pass counts_against_run_budget=False."""

  def test_handler_calls_with_false(self) -> None:
    text = TOOL_CALLING_SESSION_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "counts_against_run_budget=False",
      text,
      "tool_calling_session.py must pass counts_against_run_budget=False at the "
      "call_gpt_responses_api_turn site",
    )
    # And it must appear inside the call_gpt_responses_api_turn(...) block
    idx = text.find("call_gpt_responses_api_turn(")
    self.assertGreater(idx, 0)
    end_idx = text.find(")", idx + len("call_gpt_responses_api_turn("))
    # Find the matching closing paren — it spans multiple lines
    # so use a heuristic: the next 'turn_resp = call_gpt' OR the handler's
    # closing-block. Just check the False appears within 1000 chars.
    block = text[idx: idx + 1500]
    self.assertIn("counts_against_run_budget=False", block)


class BudgetExhaustedCheckSkippedWhenFalseTest(unittest.TestCase):
  """When counts_against_run_budget=False, the run-wide budget check is
  bypassed even if the regular budget is already at the cap."""

  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_solver import _gpt_critic_io as mod  # noqa: WPS433
    self._mod = mod
    mod.reset_gpt_call_budget()
    # Saturate the run-wide budget
    for i in range(self._mod._GPT_CALL_BUDGET_PER_RUN):
      mod._record_gpt_call(f"saturator_{i}", "python_proposer_plus_gpt_critic")
    self.assertTrue(mod._budget_exhausted())

  def tearDown(self) -> None:
    self._mod.reset_gpt_call_budget()

  def test_handler_round_bypasses_exhausted_run_budget(self) -> None:
    """Even with the run-wide budget at cap, a handler round (counts_against_run_budget=False)
    must not short-circuit to budget_exhausted."""
    # We can't actually fire an OpenAI request in unit test, but we can
    # patch _resolve_api_key to None — which is the SECOND short-circuit
    # in the function — and verify we got past the first short-circuit
    # (budget exhausted) by reaching the second.
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # noqa: WPS433
      call_gpt_responses_api_turn,
    )
    with patch.object(self._mod, "_resolve_api_key", return_value=None):
      result = call_gpt_responses_api_turn(
        consultant_name="handler_test",
        input_items=[],
        tools=None,
        response_schema=None,
        schema_name=None,
        counts_against_run_budget=False,
      )
    # Must be the no_api_key branch, NOT the budget_exhausted branch
    self.assertEqual(result["decision_source"], "python_proposer_only_no_api_key")
    self.assertNotEqual(result["decision_source"], "python_proposer_only_budget_exhausted")

  def test_regular_call_still_short_circuits_on_exhaustion(self) -> None:
    """The default counts_against_run_budget=True path must still
    short-circuit on budget exhaustion."""
    from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # noqa: WPS433
      call_gpt_responses_api_turn,
    )
    result = call_gpt_responses_api_turn(
      consultant_name="regular_test",
      input_items=[],
      tools=None,
      response_schema=None,
      schema_name=None,
    )
    self.assertEqual(result["decision_source"], "python_proposer_only_budget_exhausted")
    self.assertIn("gpt_call_budget_exhausted", result["detail"])


class RunWideBudgetUnchangedTest(unittest.TestCase):
  """The run-wide cap stays at 8; the handler cap stays at 10. Iter 17
  is a scoping fix, not a cap-raising fix."""

  def test_run_wide_budget_still_eight(self) -> None:
    from client_intake_and_finmo.post_intake_solver import _gpt_critic_io as mod  # noqa: WPS433
    self.assertEqual(mod._GPT_CALL_BUDGET_PER_RUN, 8)

  def test_handler_hard_cap_still_ten(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler import tool_calling_session as mod  # noqa: WPS433
    self.assertEqual(mod.HARD_CAP_TOOL_CALLS, 10)
    self.assertEqual(mod.MAX_TOOL_CALLS, mod.HARD_CAP_TOOL_CALLS)


class RegularCritiqueFlowUnchangedTest(unittest.TestCase):
  """`call_gpt_with_schema_or_fallback` (the regular critic path) must
  still increment the run-wide counter — iter 17 only changed the
  Responses-API path."""

  def setUp(self) -> None:
    from client_intake_and_finmo.post_intake_solver import _gpt_critic_io as mod  # noqa: WPS433
    self._mod = mod
    mod.reset_gpt_call_budget()

  def tearDown(self) -> None:
    self._mod.reset_gpt_call_budget()

  def test_regular_critic_path_call_sites_unchanged(self) -> None:
    text = GPT_CRITIC_IO_PATH.read_text(encoding="utf-8")
    # The first occurrence in call_gpt_with_schema_or_fallback (line ~241)
    # must still be the bare 2-arg form (no counts_against_run_budget kwarg).
    schema_fn_idx = text.find("def call_gpt_with_schema_or_fallback(")
    response_fn_idx = text.find("def call_gpt_responses_api_turn(")
    self.assertGreater(schema_fn_idx, 0)
    self.assertGreater(response_fn_idx, schema_fn_idx)
    schema_block = text[schema_fn_idx:response_fn_idx]
    # Inside call_gpt_with_schema_or_fallback, _record_gpt_call must NEVER
    # pass counts_against_run_budget — these calls are regular critique
    # and always count.
    record_count = schema_block.count("_record_gpt_call(consultant_name,")
    counted_kwarg_count = schema_block.count("counts_against_run_budget=")
    self.assertGreaterEqual(record_count, 5,
                            "regular-critic path should still have multiple _record_gpt_call sites")
    self.assertEqual(counted_kwarg_count, 0,
                     "regular-critic path must NOT pass counts_against_run_budget")


class CommentLeavesPaperTrailTest(unittest.TestCase):
  def test_record_gpt_call_docstring_explains_iter_17(self) -> None:
    text = GPT_CRITIC_IO_PATH.read_text(encoding="utf-8")
    # Find the _record_gpt_call definition and check its docstring mentions
    # iter 17 + the scoping intent.
    idx = text.find("def _record_gpt_call(")
    self.assertGreater(idx, 0)
    block = text[idx: idx + 1500]
    self.assertIn("counted_against_run_budget", block)
    self.assertIn("iter 17", block.lower())

  def test_handler_call_site_has_explanatory_comment(self) -> None:
    text = TOOL_CALLING_SESSION_PATH.read_text(encoding="utf-8")
    idx = text.find("counts_against_run_budget=False")
    self.assertGreater(idx, 0)
    pre_block = text[max(0, idx - 800): idx]
    self.assertIn("HARD_CAP_TOOL_CALLS", pre_block)


class ModulesImportCleanlyTest(unittest.TestCase):
  def test_critic_io_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_solver import _gpt_critic_io  # noqa: WPS433
    self.assertTrue(callable(_gpt_critic_io.call_gpt_responses_api_turn))
    self.assertTrue(callable(_gpt_critic_io._record_gpt_call))

  def test_tool_calling_session_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler import tool_calling_session  # noqa: WPS433
    self.assertTrue(hasattr(tool_calling_session, "HARD_CAP_TOOL_CALLS"))


if __name__ == "__main__":
  unittest.main()
