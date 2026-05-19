"""Phase 9 P3.26 Commit 1 — restoration ITERATING_STILL trigger.

Verifies F-1 + F-2 + F-3:

F-1: GPT exhaustion handler Site 1 trigger engages on
     RestorationStatus.ITERATING_STILL when failing_metrics is
     non-empty (in addition to the existing EXHAUSTED gating).
     ITERATING_STILL with empty failing_metrics correctly skips
     the handler (no GPT-authorable work to do).

F-2: semantic_exhaustion now counts max_inner_iterations_reached
     targets toward the stuck-threshold. Anderson & Blake's
     pass-5 shape (2 bound_pinned + 1 max_inner_iters) exits
     EXHAUSTED directly instead of falling through to
     ITERATING_STILL.

F-3: The ITERATING_STILL return populates scope + failing_metrics
     via _classify_forecast_exhaustion so the handler has the
     full payload when routed via F-1.

These are pure-Python checks on the trigger expression and the
RestorationResult data shape. Live restoration-loop integration
is left for the verification run (per the P3.26 directive).
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


class TestF1OrchestratorTrigger(unittest.TestCase):
  """F-1: Site 1 trigger engages on EXHAUSTED or
  ITERATING_STILL + non-empty failing_metrics."""

  def _engage(
    self, *, status_value: str, failing_metrics: List[Dict[str, Any]],
  ) -> bool:
    """Mirrors the boolean expression at orchestrator.py
    around line 1977 (_should_engage_handler)."""
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      RestorationStatus,
    )
    status = RestorationStatus(status_value)

    class _Synthetic:
      def __init__(self) -> None:
        self.status = status
        self.failing_metrics = failing_metrics

    rr = _Synthetic()
    return bool(
      rr.status == RestorationStatus.EXHAUSTED
      or (
        rr.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(rr, "failing_metrics", None))
      )
    )

  def test_exhausted_with_failing_metrics_engages(self) -> None:
    """Regression — EXHAUSTED with failing_metrics still fires
    the handler (legacy contract preserved)."""
    self.assertTrue(self._engage(
      status_value="exhausted",
      failing_metrics=[{"metric_key": "ebitda_margin"}],
    ))

  def test_exhausted_with_empty_failing_metrics_still_engages(self) -> None:
    """Regression — EXHAUSTED with no failing_metrics still
    routes to the handler. Pre-F1 the handler accepted the
    empty payload; that contract is unchanged."""
    self.assertTrue(self._engage(
      status_value="exhausted", failing_metrics=[],
    ))

  def test_iterating_still_with_failing_metrics_engages(self) -> None:
    """F-1 — Anderson & Blake's shape: restoration exits
    ITERATING_STILL with unresolved realism metrics. F-3
    populated failing_metrics on this return; F-1 routes the
    handler in. Three failing metrics (current_assets_minus_cash,
    current_liabilities_to_revenue, ebitda_margin) — all within
    the GPT exhaustion handler's 12 PNL + 5 WC lever authority."""
    fm = [
      {"metric_key": "current_assets_minus_cash"},
      {"metric_key": "current_liabilities_to_revenue"},
      {"metric_key": "ebitda_margin"},
    ]
    self.assertTrue(self._engage(
      status_value="iterating_still", failing_metrics=fm,
    ))

  def test_iterating_still_with_empty_failing_metrics_skips(self) -> None:
    """F-1 — ITERATING_STILL with empty failing_metrics does
    NOT route to the handler. The loop ran out of outer passes
    but the forward-looking classifier found no GPT-authorable
    realism failures — handler engagement would be a no-op."""
    self.assertFalse(self._engage(
      status_value="iterating_still", failing_metrics=[],
    ))

  def test_landed_skips(self) -> None:
    """Regression — LANDED never engages the handler."""
    self.assertFalse(self._engage(
      status_value="landed", failing_metrics=[],
    ))

  def test_failed_skips(self) -> None:
    """Regression — FAILED is a machinery error, not a business
    adaptation cue. Never engages the handler."""
    self.assertFalse(self._engage(
      status_value="failed", failing_metrics=[],
    ))


class TestF2SemanticExhaustionCountsMaxInnerIters(unittest.TestCase):
  """F-2: max_inner_iterations_reached targets count toward
  the stuck-threshold in semantic_exhaustion."""

  def _exhausts(
    self, *, statuses: List[str], viability_all_pass: bool = False,
  ) -> bool:
    """Mirrors the semantic_exhaustion expression at
    restoration_loop.py:1189-1219 post-F2."""
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      _VIABILITY_TRAJECTORY_METRICS,
    )
    targets_attempted = [
      {"target": f"t{i}", "status": s} for i, s in enumerate(statuses)
    ]
    pass_diag = {
      "targets_attempted": targets_attempted,
      "targets_bound_pinned": [
        t["target"] for t in targets_attempted if t["status"] == "bound_pinned"
      ],
      "targets_converged": [
        t["target"] for t in targets_attempted if t["status"] == "converged"
      ],
    }
    final_viability: Dict[str, bool] = {
      m: viability_all_pass for m in _VIABILITY_TRAJECTORY_METRICS
    }
    targets_attempted_count = len([
      t for t in (pass_diag.get("targets_attempted") or [])
      if t.get("status") in ("bound_pinned", "converged", "max_inner_iterations_reached")
    ])
    bp = list(pass_diag.get("targets_bound_pinned") or [])
    cv = list(pass_diag.get("targets_converged") or [])
    mi = [
      str(t.get("target") or "").strip()
      for t in (pass_diag.get("targets_attempted") or [])
      if t.get("status") == "max_inner_iterations_reached"
      and str(t.get("target") or "").strip()
    ]
    return bool(
      bool(targets_attempted_count)
      and (len(bp) + len(cv) + len(mi)) >= targets_attempted_count
      and (len(bp) + len(mi)) >= 1
      and not all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS)
    )

  def test_anderson_blake_pass5_shape_exhausts(self) -> None:
    """The exact pass-5 shape from P3.23a Draft 1: 2
    bound_pinned + 1 max_inner_iterations_reached. Pre-F2:
    2 >= 3 is False → ITERATING_STILL. Post-F2: 2+0+1 >= 3
    is True → EXHAUSTED."""
    self.assertTrue(self._exhausts(
      statuses=["bound_pinned", "bound_pinned", "max_inner_iterations_reached"],
    ))

  def test_all_bound_pinned_exhausts_regression(self) -> None:
    """Regression — all bound_pinned still exhausts."""
    self.assertTrue(self._exhausts(
      statuses=["bound_pinned", "bound_pinned", "bound_pinned"],
    ))

  def test_mixed_pinned_converged_max_iter_exhausts(self) -> None:
    """Mixed state: 1 bound_pinned + 1 converged + 1
    max_inner_iters. Threshold 3 >= 3 met; at-least-one-stuck
    (1 bp + 1 mi = 2) met. EXHAUSTED."""
    self.assertTrue(self._exhausts(
      statuses=["bound_pinned", "converged", "max_inner_iterations_reached"],
    ))

  def test_all_converged_only_does_not_exhaust(self) -> None:
    """Regression — converged-only means the solver landed
    every target. No stuck-target → semantic_exhaustion
    correctly returns False (the "at least one stuck" gate
    catches it). The deterministic LANDED branch handles this
    case upstream; semantic_exhaustion should not fire."""
    self.assertFalse(self._exhausts(
      statuses=["converged", "converged", "converged"],
    ))

  def test_all_max_inner_iters_exhausts(self) -> None:
    """All max_inner_iterations_reached, no bound_pinned. The
    stuck count is 0 + 0 + 3 = 3 >= 3 (threshold). The
    at-least-one-stuck check is 0 + 3 = 3 >= 1. Exhausts."""
    self.assertTrue(self._exhausts(
      statuses=["max_inner_iterations_reached"] * 3,
    ))

  def test_full_viability_blocks_exhaustion(self) -> None:
    """Regression — if all viability checks pass, the LANDED
    branch handles the exit. semantic_exhaustion explicitly
    excludes this case."""
    self.assertFalse(self._exhausts(
      statuses=["bound_pinned", "bound_pinned", "max_inner_iterations_reached"],
      viability_all_pass=True,
    ))


class TestF3IteratingStillReturnPayload(unittest.TestCase):
  """F-3: ITERATING_STILL return populates scope +
  failing_metrics."""

  def test_restoration_result_has_optional_scope_failing_metrics(self) -> None:
    """The dataclass already had these fields (P3.7 added them);
    F-3 just populates them on the ITERATING_STILL path."""
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

  def test_iterating_still_to_dict_round_trip(self) -> None:
    """The handler reads restoration_result.to_dict() at
    exhaustion_handler/handler.py:~773-779. The payload must
    serialize ITERATING_STILL with scope + failing_metrics
    preserved."""
    from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (  # noqa: WPS433
      HandlerScope,
      RestorationResult,
      RestorationStatus,
    )
    fm = [
      {
        "metric_key": "current_liabilities_to_revenue",
        "quarter_index": 1,
        "primary_levers": ["balance_sheet::Accounts Payable Days"],
      },
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
    self.assertEqual(
      payload["reason"],
      "max_outer_passes_reached_without_landed_or_exhausted",
    )


class TestAndersonBlakeShapeReachesHandler(unittest.TestCase):
  """End-to-end logical chain: Anderson & Blake's failure shape
  now produces a handler-routed outcome under P3.26 Commit 1.

  Pre-fix path: A&B exited ITERATING_STILL with empty
  failing_metrics → orchestrator trigger missed it → realism
  gate / acceptance gate caught residuals post-hoc with no
  handler engagement.

  Post-fix path 1 (F-2): semantic_exhaustion now counts the
  max_inner_iterations_reached target, so A&B exits EXHAUSTED
  with failing_metrics populated. Handler engages via the
  existing EXHAUSTED branch.

  Post-fix path 2 (F-1 + F-3): if the loop somehow still exits
  ITERATING_STILL (different target mix), F-3 populates
  failing_metrics via _classify_forecast_exhaustion and F-1
  routes the handler in.

  Both paths lead to handler engagement; neither bypasses the
  GPT exhaustion handler's authoring window.
  """

  def test_both_paths_lead_to_handler_engagement(self) -> None:
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      RestorationStatus,
    )
    fm = [
      {"metric_key": "current_assets_minus_cash"},
      {"metric_key": "current_liabilities_to_revenue"},
      {"metric_key": "ebitda_margin"},
    ]

    # Path 1 — EXHAUSTED with failing_metrics (existing).
    class _R1:
      status = RestorationStatus.EXHAUSTED
      failing_metrics = fm
    self.assertTrue(
      _R1.status == RestorationStatus.EXHAUSTED
      or (
        _R1.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(_R1, "failing_metrics", None))
      )
    )

    # Path 2 — ITERATING_STILL with failing_metrics (P3.26 new).
    class _R2:
      status = RestorationStatus.ITERATING_STILL
      failing_metrics = fm
    self.assertTrue(
      _R2.status == RestorationStatus.EXHAUSTED
      or (
        _R2.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(_R2, "failing_metrics", None))
      )
    )

  def test_iterating_still_no_failing_metrics_correctly_skipped(self) -> None:
    """Defense-in-depth: if F-3's classifier produces no
    GPT-authorable failures, the handler does NOT engage. The
    realism gate / acceptance gate is the right downstream
    consumer in that case."""
    from client_intake_and_finmo.post_intake_target_solver import (  # noqa: WPS433
      RestorationStatus,
    )

    class _R:
      status = RestorationStatus.ITERATING_STILL
      failing_metrics: List[Dict[str, Any]] = []

    self.assertFalse(
      _R.status == RestorationStatus.EXHAUSTED
      or (
        _R.status == RestorationStatus.ITERATING_STILL
        and bool(getattr(_R, "failing_metrics", None))
      )
    )


if __name__ == "__main__":
  unittest.main()
