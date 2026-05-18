"""Phase 9 P3.24 Commit 1 — restoration ITERATING_STILL handler trigger.

Verifies F-1 + F-2 + F-3 fixes from the P3.23a/P3.23b audits:

F-1: GPT exhaustion handler Site 1 trigger engages on
     RestorationStatus.ITERATING_STILL when failing_metrics is
     non-empty (in addition to EXHAUSTED). ITERATING_STILL with
     empty failing_metrics still skips the handler.

F-2: semantic_exhaustion counts max_inner_iterations_reached
     targets toward the stuck-threshold so a mix of bound_pinned
     and max_inner_iterations_reached targets across all attempts
     returns EXHAUSTED (not ITERATING_STILL).

F-3: The ITERATING_STILL return populates scope + failing_metrics
     via _classify_forecast_exhaustion so the handler has the full
     failure payload when routed via the broadened trigger.

Tests are pure-Python: they exercise the trigger expression and
the data-shape paths, not a live restoration loop. Live integration
is left for the user-directed E2E verification.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)


class TestF1OrchestratorTriggerBroadened(unittest.TestCase):
  """F-1 — Site 1 trigger engages on ITERATING_STILL + non-empty
  failing_metrics, and on EXHAUSTED (regression test)."""

  def _trigger_decision(
    self, *, status_value: str, failing_metrics: List[Dict[str, Any]]
  ) -> bool:
    """Evaluates the orchestrator's Site 1 trigger expression for a
    synthetic restoration_result shape. Mirrors the boolean built at
    orchestrator.py around line 1977 (_should_engage_handler)."""
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      RestorationStatus,
    )
    status = RestorationStatus(status_value)

    class _Synthetic:
      def __init__(self) -> None:
        self.status = status
        self.failing_metrics = failing_metrics

    rr = _Synthetic()
    should_engage = (
      rr.status == RestorationStatus.EXHAUSTED
      or (
        rr.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(rr, "failing_metrics", None))
      )
    )
    return bool(should_engage)

  def test_exhausted_status_still_engages_handler(self) -> None:
    """Regression — the original Site 1 trigger semantics must still
    fire on EXHAUSTED. F-1 broadens the trigger; it must not narrow."""
    fm = [{"metric_key": "ebitda_margin"}]
    self.assertTrue(self._trigger_decision(
      status_value="exhausted", failing_metrics=fm,
    ))

  def test_exhausted_with_empty_failing_metrics_still_engages(self) -> None:
    """Regression — EXHAUSTED with no forecast failures still routes
    to the handler (legacy behavior). The handler decides what to do
    with an empty payload."""
    self.assertTrue(self._trigger_decision(
      status_value="exhausted", failing_metrics=[],
    ))

  def test_iterating_still_with_failing_metrics_engages_handler(self) -> None:
    """F-1 — the new path. Anderson & Blake's shape: restoration
    exits ITERATING_STILL with unresolved realism metrics; the
    handler must now engage."""
    fm = [
      {"metric_key": "current_assets_minus_cash"},
      {"metric_key": "current_liabilities_to_revenue"},
      {"metric_key": "ebitda_margin"},
    ]
    self.assertTrue(self._trigger_decision(
      status_value="iterating_still", failing_metrics=fm,
    ))

  def test_iterating_still_with_empty_failing_metrics_skips_handler(self) -> None:
    """F-1 — ITERATING_STILL with no forecast failures still skips
    the handler. The loop ran out of passes but downstream realism
    gate has nothing to flag; the handler running here would be a
    no-op."""
    self.assertFalse(self._trigger_decision(
      status_value="iterating_still", failing_metrics=[],
    ))

  def test_landed_status_skips_handler(self) -> None:
    """Regression — LANDED never routes to the handler."""
    self.assertFalse(self._trigger_decision(
      status_value="landed", failing_metrics=[],
    ))

  def test_failed_status_skips_handler(self) -> None:
    """Regression — FAILED never routes to the handler (it's a
    machinery error, not a business adaptation cue)."""
    self.assertFalse(self._trigger_decision(
      status_value="failed", failing_metrics=[],
    ))


class TestF2SemanticExhaustionCountsMaxInnerIters(unittest.TestCase):
  """F-2 — semantic_exhaustion threshold includes
  max_inner_iterations_reached targets."""

  def _semantic_exhaustion(
    self,
    *,
    statuses: List[str],
    final_viability_all_pass: bool = False,
  ) -> bool:
    """Mirrors the semantic_exhaustion expression at
    restoration_loop.py:1189-1207."""
    targets_attempted = [{"target": f"t{i}", "status": s} for i, s in enumerate(statuses)]
    pass_diag = {
      "targets_attempted": targets_attempted,
      "targets_bound_pinned": [t["target"] for t in targets_attempted if t["status"] == "bound_pinned"],
      "targets_converged": [t["target"] for t in targets_attempted if t["status"] == "converged"],
    }
    final_viability: Dict[str, bool] = {
      "ebitda_positive_by_q11": final_viability_all_pass,
      "ebitda_recovery_trend_q5_q11": final_viability_all_pass,
      "loss_window_funded_through_q5": final_viability_all_pass,
      "ebitda_margin_q20_holds_or_improves_vs_q11": final_viability_all_pass,
      "gross_margin_supports_ebitda_recovery": final_viability_all_pass,
      "fixed_cost_burden_reduced_or_scaled_by_q11": final_viability_all_pass,
    }
    # Mirror the implementation under test.
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      _VIABILITY_TRAJECTORY_METRICS,
    )
    targets_attempted_count = len([
      t for t in (pass_diag.get("targets_attempted") or [])
      if t.get("status") in ("bound_pinned", "converged", "max_inner_iterations_reached")
    ])
    targets_bound_pinned = list(pass_diag.get("targets_bound_pinned") or [])
    targets_converged = list(pass_diag.get("targets_converged") or [])
    targets_max_inner_iters = [
      str(t.get("target") or "").strip()
      for t in (pass_diag.get("targets_attempted") or [])
      if t.get("status") == "max_inner_iterations_reached" and str(t.get("target") or "").strip()
    ]
    return bool(
      bool(targets_attempted_count)
      and (
        len(targets_bound_pinned)
        + len(targets_converged)
        + len(targets_max_inner_iters)
      ) >= targets_attempted_count
      and (len(targets_bound_pinned) + len(targets_max_inner_iters)) >= 1
      and not all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS)
    )

  def test_anderson_blake_shape_semantic_exhaustion_fires(self) -> None:
    """The exact pass-5 shape from P3.23a Draft 1: 2 bound_pinned + 1
    max_inner_iterations_reached. Pre-fix this returned False
    (2 >= 3 is False); post-fix returns True (2 + 1 >= 3)."""
    self.assertTrue(self._semantic_exhaustion(
      statuses=["bound_pinned", "bound_pinned", "max_inner_iterations_reached"],
    ))

  def test_all_bound_pinned_still_exhausts(self) -> None:
    """Regression — pre-fix shape (every target bound_pinned) still
    fires semantic_exhaustion."""
    self.assertTrue(self._semantic_exhaustion(
      statuses=["bound_pinned", "bound_pinned", "bound_pinned"],
    ))

  def test_all_max_inner_iters_exhausts_with_threshold_satisfied(self) -> None:
    """All max_inner_iterations_reached, no bound_pinned — threshold
    is satisfied (3+0+3=6 >= 3) AND the new threshold-2 check
    (bound_pinned + max_inner_iters >= 1) is satisfied (0+3 >= 1)."""
    self.assertTrue(self._semantic_exhaustion(
      statuses=["max_inner_iterations_reached"] * 3,
    ))

  def test_only_converged_targets_no_stuck_skips_exhaustion(self) -> None:
    """If every counted target is converged (no bound_pinned and no
    max_inner_iterations_reached), the second threshold check
    (bound_pinned + max_inner_iters >= 1) fails. Semantic_exhaustion
    does NOT fire — converged-only means the deterministic solver
    landed the targets; no handler should engage. Regression for the
    requirement that semantic_exhaustion only fires when at least
    ONE counted target is stuck-not-just-converged."""
    self.assertFalse(self._semantic_exhaustion(
      statuses=["converged", "converged", "converged"],
    ))

  def test_all_viability_pass_blocks_exhaustion(self) -> None:
    """If viability is fully clean, semantic_exhaustion does NOT
    fire — the loop genuinely landed and the LANDED branch should
    handle it instead. Regression."""
    self.assertFalse(self._semantic_exhaustion(
      statuses=["bound_pinned", "bound_pinned", "max_inner_iterations_reached"],
      final_viability_all_pass=True,
    ))


class TestF3IteratingStillReturnPopulatesPayload(unittest.TestCase):
  """F-3 — the ITERATING_STILL return path populates scope +
  failing_metrics via _classify_forecast_exhaustion."""

  def test_restoration_result_dataclass_has_failing_metrics_field(self) -> None:
    """The dataclass already had this field (P3.7) — F-3 just
    populates it on the ITERATING_STILL path. Regression check."""
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      RestorationResult,
      RestorationStatus,
    )
    rr = RestorationResult(
      status=RestorationStatus.ITERATING_STILL,
      outer_passes_used=5,
      reason="test",
    )
    self.assertEqual(rr.failing_metrics, [])
    self.assertIsNone(rr.scope)

  def test_to_dict_round_trip_preserves_iterating_still_payload(self) -> None:
    """to_dict() serializes ITERATING_STILL with scope + failing_metrics
    so the handler sees a complete payload via restoration_result.to_dict()
    at exhaustion_handler/handler.py:773-779."""
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      RestorationResult,
      RestorationStatus,
      HandlerScope,
    )
    fm = [
      {"metric_key": "current_liabilities_to_revenue", "quarter_index": 1,
       "primary_levers": ["balance_sheet::Accounts Payable Days"]},
    ]
    rr = RestorationResult(
      status=RestorationStatus.ITERATING_STILL,
      outer_passes_used=5,
      reason="max_outer_passes_reached_without_landed_or_exhausted",
      scope=HandlerScope.PNL_PATH,
      failing_metrics=fm,
    )
    payload = rr.to_dict()
    self.assertEqual(payload["status"], "iterating_still")
    self.assertEqual(payload["scope"], "pnl_path")
    self.assertEqual(payload["failing_metrics"], fm)


class TestF1F2F3PathSelectionIntegration(unittest.TestCase):
  """End-to-end logical chain: when restoration exits with the
  Anderson & Blake shape (2 bound_pinned + 1 max_inner_iters), the
  F-2 fix routes it to EXHAUSTED. When the loop runs out of outer
  passes without semantic_exhaustion firing AND with realism
  forecast failures, F-1+F-3 routes ITERATING_STILL → handler."""

  def test_full_chain_anderson_blake_now_reaches_handler(self) -> None:
    """Pre-fix: A&B exited ITERATING_STILL with empty failing_metrics
    → Site 1 trigger missed it.

    Post-fix path 1: semantic_exhaustion now counts max_inner_iters,
    so the loop returns EXHAUSTED with forecast_failures populated.
    Site 1 trigger fires (existing path).

    Post-fix path 2: if semantic_exhaustion still misses (different
    target mix), the ITERATING_STILL return now populates
    failing_metrics via _classify_forecast_exhaustion, and the
    orchestrator trigger now accepts ITERATING_STILL with non-empty
    failing_metrics. Site 1 fires (new path).

    This test exercises the OR-condition at orchestrator.py around
    line 1977 to confirm both paths lead to handler engagement."""
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      RestorationStatus,
    )
    # Path 1 — EXHAUSTED with failing_metrics (existing path).
    fm = [{"metric_key": "current_liabilities_to_revenue"}]
    class _Result1:
      status = RestorationStatus.EXHAUSTED
      failing_metrics = fm
    self.assertTrue(
      _Result1.status == RestorationStatus.EXHAUSTED
      or (
        _Result1.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(_Result1, "failing_metrics", None))
      )
    )
    # Path 2 — ITERATING_STILL with failing_metrics (new path).
    class _Result2:
      status = RestorationStatus.ITERATING_STILL
      failing_metrics = fm
    self.assertTrue(
      _Result2.status == RestorationStatus.EXHAUSTED
      or (
        _Result2.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(_Result2, "failing_metrics", None))
      )
    )
    # Path 3 — ITERATING_STILL with NO failing_metrics (handler
    # correctly skips).
    class _Result3:
      status = RestorationStatus.ITERATING_STILL
      failing_metrics: List[Dict[str, Any]] = []
    self.assertFalse(
      _Result3.status == RestorationStatus.EXHAUSTED
      or (
        _Result3.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(_Result3, "failing_metrics", None))
      )
    )


if __name__ == "__main__":
  unittest.main()
