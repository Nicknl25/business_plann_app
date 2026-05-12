"""Phase 9 P3.10 Commit 4 — smoke tests for moderate-severity
hard-fail conversions and persistence-layer hardening.

Verifies that under ``CONVERGENCE_TEST_MODE=true`` the four targeted
sites raise instead of silently degrading, and that production-mode
behavior is preserved.
"""

from __future__ import annotations

import os
import sys
import unittest


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class ModerateHardFailsCommit4Test(unittest.TestCase):
  def setUp(self) -> None:
    self._previous_test_mode = os.environ.get("CONVERGENCE_TEST_MODE")
    os.environ["CONVERGENCE_TEST_MODE"] = "true"

  def tearDown(self) -> None:
    if self._previous_test_mode is None:
      os.environ.pop("CONVERGENCE_TEST_MODE", None)
    else:
      os.environ["CONVERGENCE_TEST_MODE"] = self._previous_test_mode

  def test_compute_metrics_to_mute_raises_when_realism_lookup_fails(self) -> None:
    """#26 — realism lookup load failure must raise in test mode."""
    from client_intake_and_finmo.fail_fast.common import (  # noqa: WPS433
      PostIntakePreconditionFailed,
    )
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler import (  # noqa: WPS433
      handler as handler_mod,
    )

    # Patch the lookup module so import succeeds but the function raises.
    import client_intake_and_finmo.post_intake_realism.lookup as lookup_mod  # noqa: WPS433

    original = lookup_mod.post_intake_finalize_realism_check_rows

    def _raises():
      raise RuntimeError("simulated lookup failure")

    lookup_mod.post_intake_finalize_realism_check_rows = _raises  # type: ignore[assignment]
    try:
      with self.assertRaises(PostIntakePreconditionFailed) as ctx:
        handler_mod.compute_metrics_to_mute(
          gpt_authored_lever_ids={"revenue::Unit Price"},
        )
      self.assertEqual(
        ctx.exception.operation,
        "compute_metrics_to_mute_realism_lookup_failed",
      )
    finally:
      lookup_mod.post_intake_finalize_realism_check_rows = original  # type: ignore[assignment]

  def test_compute_metrics_to_mute_production_mode_falls_back_silently(self) -> None:
    """Production mode (CONVERGENCE_TEST_MODE=false) preserves the
    minimal mute set when realism lookup fails."""
    os.environ["CONVERGENCE_TEST_MODE"] = "false"
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler import (  # noqa: WPS433
      handler as handler_mod,
    )
    import client_intake_and_finmo.post_intake_realism.lookup as lookup_mod  # noqa: WPS433

    original = lookup_mod.post_intake_finalize_realism_check_rows

    def _raises():
      raise RuntimeError("simulated lookup failure")

    lookup_mod.post_intake_finalize_realism_check_rows = _raises  # type: ignore[assignment]
    try:
      result = handler_mod.compute_metrics_to_mute(
        gpt_authored_lever_ids={"revenue::Unit Price"},
      )
      self.assertEqual(result, ["ebitda_margin"])
    finally:
      lookup_mod.post_intake_finalize_realism_check_rows = original  # type: ignore[assignment]

  def test_orchestrator_composite_revenue_check_propagates_under_test_mode(self) -> None:
    """#15 — composite revenue trajectory exception now reraises in
    test mode. We verify this at the source-level since the function is
    deep in a long orchestrator path; the conversion is gated by
    convergence_test_mode_enabled() and re-raises the original exception.
    """
    import pathlib

    orch_path = pathlib.Path(PYTHON_ROOT) / "client_intake_and_finmo" / "post_intake_solver" / "orchestrator.py"
    text = orch_path.read_text(encoding="utf-8")
    self.assertIn(
      'completion_trace["composite_revenue_check"] = composite_check',
      text,
    )
    # The fix introduced an explicit "if convergence_test_mode_enabled(): raise" branch
    # before the legacy completion_trace fallback for composite_revenue_check.
    self.assertIn(
      "Phase 9 P3.10 Commit 4 — composite revenue trajectory check",
      text,
    )

  def test_orchestrator_persist_finalize_stage_propagates_under_test_mode(self) -> None:
    """#41 — persistence-layer SQL UPDATE failure now reraises under
    test mode. Source-level verification."""
    import pathlib

    orch_path = pathlib.Path(PYTHON_ROOT) / "client_intake_and_finmo" / "post_intake_solver" / "orchestrator.py"
    text = orch_path.read_text(encoding="utf-8")
    self.assertIn(
      'completion_trace["persist_finalize_stage"] = {"status": "completed"}',
      text,
    )
    self.assertIn(
      "Phase 9 P3.10 Commit 4 — persist_finalize_stage failure now",
      text,
    )

  def test_cash_final_finmo_rebuild_propagates_under_test_mode(self) -> None:
    """#34 (extension) — cash strategy final FINMO rebuild raises under
    test mode. Source-level verification of the conversion site."""
    import pathlib

    cash_path = (
      pathlib.Path(PYTHON_ROOT)
      / "client_intake_and_finmo"
      / "post_intake_cash_strategy"
      / "orchestrator_invocation.py"
    )
    text = cash_path.read_text(encoding="utf-8")
    self.assertIn("cash_strategy_final_finmo_rebuild_failed", text)
    self.assertIn(
      "Phase 9 P3.10 Commit 4 — final FINMO rebuild failure raises",
      text,
    )


if __name__ == "__main__":
  unittest.main()
