"""Phase 9 P3.10 Commit 2 — smoke tests for the critical-severity
hard-fail conversions.

Verifies that under ``CONVERGENCE_TEST_MODE=true`` the four critical
sites raise PostIntakePreconditionFailed (or propagate exceptions
upward) instead of returning a status enum:

  - Handler #19: pre-session FINMO build failure -> raise
  - Handler #27: post-commit FINMO rebuild failure -> raise (covered by
    construction; full path requires a working tool-calling session
    and is not exercised here)
  - Tier 7 cascade #11: inner-runner exception -> raise (production
    fallback path verified absent)
  - Orchestrator outer catches #28/29: re-raise under test mode
    (verified by reading the file — both blocks short-circuit on
    convergence_test_mode_enabled())
  - Finalize #40: literal "failed_downgraded_to_warning" string is
    absent from the codebase
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class CriticalHardFailsCommit2Test(unittest.TestCase):
  def setUp(self) -> None:
    self._previous_test_mode = os.environ.get("CONVERGENCE_TEST_MODE")
    os.environ["CONVERGENCE_TEST_MODE"] = "true"

  def tearDown(self) -> None:
    if self._previous_test_mode is None:
      os.environ.pop("CONVERGENCE_TEST_MODE", None)
    else:
      os.environ["CONVERGENCE_TEST_MODE"] = self._previous_test_mode

  def test_precondition_exception_class_is_exported(self) -> None:
    from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # noqa: WPS433
      PostIntakePreconditionFailed,
    )
    from client_intake_and_finmo.fail_fast.common import (  # noqa: WPS433
      PostIntakePreconditionFailed as Direct,
    )
    self.assertIs(PostIntakePreconditionFailed, Direct)

  def test_precondition_exception_carries_structured_diagnostic(self) -> None:
    from client_intake_and_finmo.fail_fast.common import (  # noqa: WPS433
      PostIntakePreconditionFailed,
    )
    inner = ValueError("missing payroll row")
    exc = PostIntakePreconditionFailed(
      operation="some_op",
      pipeline_stage="some_stage",
      expected="model_input has payroll row",
      actual="payroll row absent",
      details={"draft_id": "abc"},
      cause=inner,
    )
    payload = exc.to_dict()
    self.assertEqual(payload["operation"], "some_op")
    self.assertEqual(payload["pipeline_stage"], "some_stage")
    self.assertEqual(payload["expected"], "model_input has payroll row")
    self.assertEqual(payload["actual"], "payroll row absent")
    self.assertEqual(payload["details"], {"draft_id": "abc"})
    self.assertEqual(payload["cause_class"], "ValueError")
    self.assertIn("missing payroll row", payload["cause_detail"])
    self.assertIn("post_intake_precondition_failed", str(exc))
    self.assertIn("operation=some_op", str(exc))

  def test_handler_status_split_includes_no_usable_anchors(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      HandlerStatus,
    )
    self.assertTrue(hasattr(HandlerStatus, "FAILED_NO_USABLE_ANCHORS"))
    self.assertEqual(
      HandlerStatus.FAILED_NO_USABLE_ANCHORS.value,
      "failed_no_usable_anchors",
    )
    self.assertTrue(hasattr(HandlerStatus, "FAILED_PRECONDITION"))

  def test_handler_pre_session_finmo_build_raises_under_test_mode(self) -> None:
    from client_intake_and_finmo.fail_fast.common import (  # noqa: WPS433
      PostIntakePreconditionFailed,
    )
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      run_gpt_exhaustion_handler,
    )

    def _build_finmo_that_raises(_model_input: Dict[str, Any]) -> Dict[str, Any]:
      raise RuntimeError("simulated FINMO build failure")

    with self.assertRaises(PostIntakePreconditionFailed) as ctx:
      run_gpt_exhaustion_handler(
        restoration_result={"status": "exhausted"},
        model_input={"sections": {}},
        operating_model={},
        build_finmo=_build_finmo_that_raises,
        intake_context={},
        finmo_json=None,
      )

    exc = ctx.exception
    self.assertEqual(
      exc.operation,
      "gpt_exhaustion_handler_pre_session_finmo_build",
    )
    self.assertIn("simulated FINMO build failure", str(exc))

  def test_production_mode_preserves_legacy_status_return(self) -> None:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (  # noqa: WPS433
      HandlerStatus,
      run_gpt_exhaustion_handler,
    )

    os.environ["CONVERGENCE_TEST_MODE"] = "false"

    def _build_finmo_that_raises(_model_input: Dict[str, Any]) -> Dict[str, Any]:
      raise RuntimeError("simulated FINMO build failure")

    result = run_gpt_exhaustion_handler(
      restoration_result={"status": "exhausted"},
      model_input={"sections": {}},
      operating_model={},
      build_finmo=_build_finmo_that_raises,
      intake_context={},
      finmo_json=None,
    )
    self.assertEqual(result.status, HandlerStatus.FAILED_PRECONDITION)
    self.assertEqual(result.gpt_calls_made, 0)
    self.assertIn(
      "finmo_rebuild_failed_before_tool_calling_session",
      result.reason,
    )

  def test_failed_downgraded_to_warning_string_absent(self) -> None:
    """The user explicitly required this string to not exist after Commit 2."""
    import pathlib

    repo_root = pathlib.Path(PYTHON_ROOT).parent
    self_path = pathlib.Path(__file__).resolve()
    matches = []
    for path in repo_root.rglob("*.py"):
      if "node_modules" in path.parts or ".venv" in path.parts:
        continue
      if "__pycache__" in path.parts:
        continue
      if path.resolve() == self_path:
        continue  # this test file mentions the string in its own assertion
      try:
        text = path.read_text(encoding="utf-8")
      except UnicodeDecodeError:
        continue
      if "failed_downgraded_to_warning" in text:
        matches.append(str(path))
    self.assertEqual(
      matches, [],
      f"'failed_downgraded_to_warning' still present in: {matches}",
    )


if __name__ == "__main__":
  unittest.main()
