"""Phase 9 P3.10 iter 12 — blind-spot diagnostic instrumentation tests.

Iter 12's failure analysis revealed five blind spots:
  A) pre-finalize persist (de3de02) didn't surface in failure snapshot
  B) finalize's actual input FINMO state was opaque
  C) cash strategy's input FINMO state was opaque
  D) surplus cleanup behavior was opaque
  E) Distributions lever_bound visible only for funded quarters

This test suite validates the source-level instrumentation now exists
in the right places. End-to-end log emission is verified by the iter 13
NexGen run.
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
FINALIZE_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_runtime_validation"
  / "finalize_post_intake.py"
)
CASH_RUNNER_PATH = (
  pathlib.Path(PYTHON_ROOT)
  / "client_intake_and_finmo"
  / "post_intake_cash"
  / "runner.py"
)


class PieceAPersistFixWithReadbackTest(unittest.TestCase):
  """Piece A — direct SQL UPDATE + read-back verification + hard-fail under test mode."""

  def test_pre_finalize_persist_uses_direct_sql_update(self) -> None:
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "UPDATE intake_consult_drafts SET model_input_json=%s, finmo_json=%s WHERE draft_id=%s",
      text,
      "Piece A must use a direct SQL UPDATE that hits the same columns "
      "_persist_failed_system_run_snapshot reads from",
    )

  def test_pre_finalize_persist_does_readback_verification(self) -> None:
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "SELECT model_input_json, finmo_json FROM intake_consult_drafts WHERE draft_id=%s",
      text,
      "Piece A must SELECT back the columns it just wrote",
    )
    self.assertIn(
      "pre_finalize_persist_readback_marker_missing_in_model_input",
      text,
      "Piece A must raise on marker mismatch in model_input read-back",
    )
    self.assertIn(
      "pre_finalize_persist_readback_marker_missing_in_finmo",
      text,
      "Piece A must raise on marker mismatch in finmo read-back",
    )

  def test_pre_finalize_persist_writes_marker_into_both_payloads(self) -> None:
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "_pre_finalize_persist_marker",
      text,
      "Piece A must embed a verifiable marker in the persisted payloads",
    )
    self.assertIn(
      '"tag": "pre_finalize_persist"',
      text,
      "Marker must include a stable tag that read-back verifies",
    )

  def test_pre_finalize_persist_hard_fails_under_test_mode(self) -> None:
    text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    # Find the persist try/except block. The except block must consult
    # convergence_test_mode_enabled and re-raise.
    persist_block_start = text.find("UPDATE intake_consult_drafts SET model_input_json")
    self.assertGreater(persist_block_start, 0)
    block = text[persist_block_start: persist_block_start + 4000]
    self.assertIn("convergence_test_mode_enabled", block,
                  "except block must check test-mode")
    self.assertIn("raise", block,
                  "except block must re-raise under test mode")


class PieceBFinalizeEntryTraceTest(unittest.TestCase):
  def test_finalize_emits_finalize_input_trace_per_quarter(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "finalize_input_trace q=%s ending_cash=%s",
      text,
      "finalize_input_trace log line must be emitted per quarter",
    )
    self.assertIn(
      "for _q in range(1, 21):",
      text,
      "finalize_input_trace must iterate Q1-Q20",
    )

  def test_finalize_input_trace_uses_canonical_buffer_components(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "from client_intake_and_finmo.post_intake_cash.common import",
      text,
    )
    self.assertIn(
      "buffer_components as _common_buffer_components",
      text,
      "Piece B must use the canonical buffer_components from common.py "
      "(post-3339fd8 corrected math)",
    )

  def test_finalize_hard_fails_on_missing_quarter_row_under_test_mode(self) -> None:
    text = FINALIZE_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "finalize_input_trace_missing_quarter_row",
      text,
      "Missing quarter row must raise under test mode (no silent skip)",
    )


class PieceCCashStrategyInputTraceTest(unittest.TestCase):
  def test_cash_strategy_emits_input_trace_per_quarter(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "cash_strategy_input_trace q=%s ending_cash=%s",
      text,
      "cash_strategy_input_trace log line must be emitted per quarter",
    )
    self.assertIn(
      "for _csi_q in range(1, 21):",
      text,
      "cash_strategy_input_trace must iterate Q1-Q20",
    )

  def test_cash_strategy_input_trace_includes_debt_repayment(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "debt_repayment=%s",
      text,
      "Piece C must include current debt_repayment per quarter",
    )


class PieceDSurplusCleanupTraceTest(unittest.TestCase):
  def test_surplus_cleanup_emits_per_quarter_trace(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "surplus_cleanup_trace pass=%s q=%s surplus_amount=%s",
      text,
      "surplus_cleanup_trace must emit per (pass, quarter) with surplus amount",
    )

  def test_surplus_cleanup_trace_includes_reason_stopped(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    for reason in (
      "all_levers_at_max_residual_surplus_remains",
      "debt_paydown_max_exhausted_distributions_capped",
      "distributions_max_exhausted_debt_paydown_capped",
      "fully_deployed",
    ):
      self.assertIn(
        reason, text,
        f"surplus_cleanup_trace must classify the stopping reason ({reason})",
      )


class PieceEFullHorizonLeverBoundsTraceTest(unittest.TestCase):
  def test_lever_bounds_full_horizon_trace_emitted(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    self.assertIn(
      "cash_proposer_lever_bounds_full_horizon lever=%s q=%s",
      text,
      "Piece E must emit per-(lever, quarter) lever_bound trace",
    )

  def test_lever_bounds_full_horizon_covers_distributions_and_debt_repayment(self) -> None:
    text = CASH_RUNNER_PATH.read_text(encoding="utf-8")
    # Find the Piece E block
    piece_e_idx = text.find("cash_proposer_lever_bounds_full_horizon")
    self.assertGreater(piece_e_idx, 0)
    block = text[max(0, piece_e_idx - 500): piece_e_idx + 1500]
    self.assertIn("_CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID", block)
    self.assertIn("_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID", block)
    self.assertIn(
      "for _full_q in range(1, 21):",
      block,
      "Piece E must iterate Q1-Q20",
    )


class DiagnosticInstrumentationDoesNotChangeBehavior(unittest.TestCase):
  def test_finalize_module_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_runtime_validation import finalize_post_intake  # noqa: WPS433
    self.assertTrue(callable(finalize_post_intake.run_finalize_post_intake_validation))

  def test_orchestrator_module_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_solver import orchestrator  # noqa: WPS433
    self.assertTrue(callable(orchestrator.run_target_seeking_orchestrated_system_run))

  def test_cash_runner_module_imports_clean(self) -> None:
    from client_intake_and_finmo.post_intake_cash import runner  # noqa: WPS433
    self.assertTrue(callable(runner._run_cash_strategy_review_openai))
    self.assertTrue(callable(runner._apply_cash_policy_surplus_cleanup))


if __name__ == "__main__":
  unittest.main()
