"""Module 2 Task 2.5 — solver direct-fit priority.

Verifies the May 2 COGS bug is structurally fixed by running the algebraic
one-dimensional fit BEFORE the GPT-anchor evaluation when the task is
single-lever / single-target / single-quarter / direct mapping.

Approach: monkey-patch `_evaluate_quarter_objective` with a deterministic
linear-in-driver fake so the test does not depend on a full FINMO calc. The
fake exposes a known algebraic answer (`exact_value = target / revenue`)
that any correct solver path must find.

The "lucky anchor" scenario: anchor is *just barely* within tolerance, so
the OLD code's anchor-first path would short-circuit and return the lucky
value. The NEW code's algebraic-first path returns the exact ratio.

Run: `.venv\\Scripts\\python.exe "Test Files\\test_solver_direct_fit_priority.py"`
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Tuple

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PY = os.path.join(_ROOT, "python")
if _PY not in sys.path:
  sys.path.insert(0, _PY)

from client_intake_and_finmo import numeric_solver as _solver  # noqa: E402


_RESULTS: List[Tuple[str, bool, str]] = []


def _run(name: str, fn: Callable[[], None]) -> None:
  try:
    fn()
    _RESULTS.append((name, True, ""))
    print(f"  PASS  {name}")
  except AssertionError as exc:
    _RESULTS.append((name, False, str(exc)))
    print(f"  FAIL  {name}: {exc}")
  except Exception as exc:
    _RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
    print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    traceback.print_exc()


# --------------------------------------------------------------------------
# Fake FINMO calc: actual_value = vector[0] * revenue (linear in COGS ratio).
# Tolerance is _metric_tolerance default for "cogs".
# --------------------------------------------------------------------------


_FAKE_REVENUE = 1_000_000.0


def _make_fake_evaluate(*, revenue: float = _FAKE_REVENUE) -> Callable[..., Tuple[float, Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
  def _fake(
    *,
    base_model_input_json: Dict[str, Any],
    quarter_index: int,
    variable_specs: List[Dict[str, Any]],
    vector: List[float],
    target_metrics: Dict[str, float],
    tolerance_overrides: Dict[str, Any] = None,
    deadline_checker=None,
  ) -> Tuple[float, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    metric_name, target_value = next(iter(target_metrics.items()))
    actual = float(vector[0]) * float(revenue)
    tolerance = _solver._metric_tolerance(  # type: ignore[attr-defined]
      metric_name,
      float(target_value),
      tolerance_override=(tolerance_overrides or {}).get(str(metric_name).strip().lower()),
    )
    residual = max(abs(actual - float(target_value)) - tolerance, 0.0)
    score = (residual / max(tolerance, 1.0)) ** 2
    spec = variable_specs[0]
    scale = max(abs(float(spec.get("max_value") or 0.0) - float(spec.get("min_value") or 0.0)), 1.0)
    score += 0.08 * (((float(vector[0]) - float(spec.get("anchor_value") or 0.0)) / scale) ** 2)
    metrics = {
      metric_name: {
        "target_value": float(target_value),
        "actual_value": float(actual),
        "tolerance": float(tolerance),
        "absolute_difference": float(abs(actual - float(target_value))),
        "residual_after_tolerance": float(residual),
      }
    }
    return float(score), {"sections": {"expenses": []}}, {"quarter_rows": []}, metrics
  return _fake


def _patch_solver_internals() -> Callable[[], None]:
  original = _solver._evaluate_quarter_objective  # type: ignore[attr-defined]
  _solver._evaluate_quarter_objective = _make_fake_evaluate()  # type: ignore[assignment]
  # Also stub `_load_numeric_apply_helpers` since it tries to import the FINMO
  # apply helper at module load. The fake never actually invokes it.
  original_load = _solver._load_numeric_apply_helpers  # type: ignore[attr-defined]
  _solver._load_numeric_apply_helpers = lambda: (lambda **kwargs: kwargs.get("model_input_json"), lambda **kwargs: {"quarter_rows": []})  # type: ignore[assignment]

  def restore() -> None:
    _solver._evaluate_quarter_objective = original  # type: ignore[assignment]
    _solver._load_numeric_apply_helpers = original_load  # type: ignore[assignment]
  return restore


# --------------------------------------------------------------------------
# Solver-input builders.
# --------------------------------------------------------------------------


def _model_input_with_cogs(*, baseline_ratio: float = 0.50) -> Dict[str, Any]:
  # 21 entries: stub + 20 quarters, all set to baseline_ratio.
  return {
    "sections": {
      "expenses": [
        {
          "lever_id": "expenses::Cost of Goods Sold",
          "label": "Cost of Goods Sold",
          "values": [baseline_ratio] * 21,
          "controller_write": True,
        }
      ],
      "revenue": [],
      "balance_sheet": [],
      "schedules": {"rows": []},
    }
  }


def _review_plan_for_cogs(
  *,
  target_cogs: float,
  anchor_ratio: float,
  baseline_ratio: float = 0.50,
) -> Dict[str, Any]:
  # `baseline_value` MUST be supplied — `_guidance_map` infers direction from
  # the anchor-vs-baseline comparison, and downstream `_build_variable_specs`
  # uses that direction to clamp the lower/upper bound. Without it the solver
  # would receive a "direction=increase" signal that pinches the search
  # window to [anchor, ...], excluding the algebraic answer.
  return {
    "translated_action_packages": [
      {
        "action_id": "test_action_cogs_q1",
        "solver_allowed_lever_ids": ["expenses::Cost of Goods Sold"],
        "required_target_metric_keys": ["cogs"],
        "target_tolerances": [],
        "quarter_target_metrics": [
          {"quarter_index": 1, "cogs": float(target_cogs)},
        ],
        "translated_updates": [
          {
            "lever_id": "expenses::Cost of Goods Sold",
            "quarter_index": 1,
            "control_mode": "exact",
            "exact_value": float(anchor_ratio),
            "baseline_value": float(baseline_ratio),
          }
        ],
      }
    ]
  }


def _solver_contract() -> Dict[str, Any]:
  return {
    "pass_name": "unified_convergence",
    "writable_lever_catalog": {"entries": [{"lever_id": "expenses::Cost of Goods Sold"}]},
    "issue_target_packets": [],
    "solver_settings": {"aggressiveness": "moderate"},
  }


def _run_solver(*, target_cogs: float, anchor_ratio: float, baseline_ratio: float = 0.50) -> Dict[str, Any]:
  return _solver.solve_review_plan(
    model_input_json=_model_input_with_cogs(baseline_ratio=baseline_ratio),
    review_plan=_review_plan_for_cogs(target_cogs=target_cogs, anchor_ratio=anchor_ratio),
    numeric_solver_contract=_solver_contract(),
    fallback_exact_updates=[],
  )


# --------------------------------------------------------------------------
# Tests.
# --------------------------------------------------------------------------


def test_algebraic_path_fires_when_one_lever_one_target_one_quarter() -> None:
  # Target cogs = $300,000 → algebraic answer = 0.30. Anchor at 0.305 is
  # within tolerance ($6,000) but NOT the exact answer. With the fix, the
  # algebraic path runs first and returns 0.30.
  restore = _patch_solver_internals()
  try:
    result = _run_solver(target_cogs=300_000.0, anchor_ratio=0.305)
  finally:
    restore()
  attempts = result.get("attempts") or []
  assert attempts, "no attempts recorded"
  attempt = attempts[0]
  assert attempt.get("algebraic_path_attempted") is True, attempt
  assert attempt.get("algebraic_path_result_code") == "direct_fit", attempt
  assert "direct_algebraic_one_dim_fit" in attempt.get("message", ""), attempt
  exact_updates = result.get("exact_updates") or []
  assert exact_updates, "no exact_updates"
  found_value = exact_updates[0].get("exact_value")
  assert abs(float(found_value) - 0.30) < 1e-3, (
    f"expected algebraic answer ~0.30, got {found_value}"
  )


def test_algebraic_path_returns_exact_not_lucky_anchor() -> None:
  # The whole point of the May 2 fix: even when the anchor is "good enough"
  # to pass tolerance, the algebraic path takes precedence and returns the
  # zero-residual value.
  restore = _patch_solver_internals()
  try:
    result = _run_solver(target_cogs=388_000.0, anchor_ratio=0.395)  # anchor close
  finally:
    restore()
  exact_updates = result.get("exact_updates") or []
  found_value = float((exact_updates[0] or {}).get("exact_value") or 0.0)
  # Algebraic answer = 388_000 / 1_000_000 = 0.388
  assert abs(found_value - 0.388) < 1e-3, (
    f"algebraic answer should be 0.388, got {found_value} — lucky anchor escape hatch?"
  )
  attempt = (result.get("attempts") or [{}])[0]
  assert attempt.get("algebraic_path_result_code") == "direct_fit", attempt


def test_algebraic_telemetry_records_probe_oob_when_target_outside_bounds() -> None:
  # Target = $1,500,000. Bounds via _default_move_band cap the cogs ratio
  # well below 1.5 → algebraic answer would be > max bound, so algebra
  # records probe_oob.
  restore = _patch_solver_internals()
  try:
    result = _run_solver(target_cogs=1_500_000.0, anchor_ratio=0.95)
  finally:
    restore()
  attempt = (result.get("attempts") or [{}])[0]
  assert attempt.get("algebraic_path_attempted") is True, attempt
  # The algebraic answer is 1.5 (out of [low, high]). Result code is
  # probe_oob OR did_not_close_tolerance (depending on default bounds);
  # either way it is NOT direct_fit.
  assert attempt.get("algebraic_path_result_code") != "direct_fit", attempt


def test_multi_lever_skips_algebraic_path() -> None:
  # When the task has 2 levers, the algebraic one-dim path should not fire.
  restore = _patch_solver_internals()
  try:
    review_plan = {
      "translated_action_packages": [
        {
          "action_id": "test_multi_lever",
          "solver_allowed_lever_ids": [
            "expenses::Cost of Goods Sold",
            "expenses::Marketing",
          ],
          "required_target_metric_keys": ["cogs"],
          "quarter_target_metrics": [{"quarter_index": 1, "cogs": 300_000.0}],
        }
      ]
    }
    model_input = _model_input_with_cogs()
    model_input["sections"]["expenses"].append({
      "lever_id": "expenses::Marketing",
      "label": "Marketing",
      "values": [0.05] * 21,
      "controller_write": True,
    })
    result = _solver.solve_review_plan(
      model_input_json=model_input,
      review_plan=review_plan,
      numeric_solver_contract=_solver_contract(),
      fallback_exact_updates=[],
    )
  finally:
    restore()
  attempt = (result.get("attempts") or [{}])[0]
  # Algebraic path should be SKIPPED (not_applicable) for multi-lever tasks.
  assert attempt.get("algebraic_path_attempted") is False, attempt
  assert attempt.get("algebraic_path_result_code") == "not_applicable", attempt


def test_attempt_telemetry_includes_algebraic_fields() -> None:
  restore = _patch_solver_internals()
  try:
    result = _run_solver(target_cogs=400_000.0, anchor_ratio=0.42)
  finally:
    restore()
  attempt = (result.get("attempts") or [{}])[0]
  for key in ("algebraic_path_attempted", "algebraic_path_result_code"):
    assert key in attempt, f"attempt missing {key}: {attempt.keys()}"


# --------------------------------------------------------------------------
# Run.
# --------------------------------------------------------------------------


def main() -> int:
  print("running test_solver_direct_fit_priority.py")
  print("-" * 70)
  tests = [
    ("algebraic_path_fires_for_one_dim_task", test_algebraic_path_fires_when_one_lever_one_target_one_quarter),
    ("algebraic_path_returns_exact_not_lucky_anchor", test_algebraic_path_returns_exact_not_lucky_anchor),
    ("probe_oob_recorded_when_target_outside_bounds", test_algebraic_telemetry_records_probe_oob_when_target_outside_bounds),
    ("multi_lever_skips_algebraic_path", test_multi_lever_skips_algebraic_path),
    ("attempt_telemetry_includes_algebraic_fields", test_attempt_telemetry_includes_algebraic_fields),
  ]
  for name, fn in tests:
    _run(name, fn)
  print("-" * 70)
  passed = sum(1 for _, ok, _ in _RESULTS if ok)
  failed = [(n, why) for n, ok, why in _RESULTS if not ok]
  print(f"{passed}/{len(_RESULTS)} passed")
  if failed:
    print("FAILURES:")
    for name, why in failed:
      print(f"  {name}: {why}")
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
