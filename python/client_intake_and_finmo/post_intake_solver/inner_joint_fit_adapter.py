"""Inner-tool adapter — Phase 2.5.

Bridges the target-seeking outer loop to the existing scipy/issue-code
solver in numeric_solver.solve_review_plan. The outer loop calls the
adapter when single-driver bisection has stagnated and a joint multi-
lever fit is needed to close a numeric gap on the worst-deviating output.

Contract:
  callable signature: (model_input_json, worst_unresolved) -> {status, model_input_json, ...}

The adapter:
  1. Takes the worst-unresolved metric from the outer loop and looks up
     the candidate levers from the influence map.
  2. Constructs a minimal numeric_solver_contract scoped to those levers
     and the failing quarter range. Reads lever bounds from the
     driver_movement_envelope so the inner solver respects the same
     envelopes as the outer loop.
  3. Builds a one-quarter review_plan referencing the worst quarter (or
     all quarters when the metric is year_one_aggregate).
  4. Invokes solve_review_plan, applies the resulting exact_updates to
     the model_input, and returns the next state.

The adapter is deliberately thin. The heavy fitting math stays in
numeric_solver.solve_review_plan; this module just translates the outer
loop's "close this gap" intent into the inner solver's contract shape.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Dict, List, Optional


_DEFAULT_INNER_DEADLINE_SECONDS = 8.0


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _candidate_levers_for_metric(
  *,
  metric_key: str,
  influence_map_payload: Optional[Dict[str, Any]],
  envelope_payload: Optional[Dict[str, Any]],
) -> List[str]:
  if not isinstance(influence_map_payload, dict):
    return []
  metrics = influence_map_payload.get("metrics") or {}
  entry = metrics.get(metric_key) if isinstance(metrics, dict) else None
  if not isinstance(entry, dict):
    return []
  drivers = (envelope_payload or {}).get("drivers") if isinstance(envelope_payload, dict) else {}
  applicable_unlocked: List[str] = []
  for candidate in (entry.get("candidate_levers") or []):
    if not isinstance(candidate, dict):
      continue
    lever_id = _clean_text(candidate.get("lever_id"))
    if not lever_id:
      continue
    envelope = drivers.get(lever_id) if isinstance(drivers, dict) else None
    if not isinstance(envelope, dict):
      continue
    if not envelope.get("applicable"):
      continue
    if envelope.get("schedule_locked"):
      # Schedule-locked levers move via schedule_tweak, not the inner
      # numeric_solver. Skip them in the inner contract.
      continue
    applicable_unlocked.append(lever_id)
  return applicable_unlocked


def _quarter_indices_for_metric(
  *,
  worst_unresolved: Dict[str, Any],
  horizon: int,
) -> List[int]:
  q = worst_unresolved.get("quarter_index")
  if isinstance(q, int) and q >= 1:
    return [int(q)]
  aggregation = _clean_text(worst_unresolved.get("quarter_aggregation"))
  if aggregation == "year_one_aggregate":
    return [1, 2, 3, 4]
  if aggregation == "horizon_average":
    return list(range(1, max(1, int(horizon)) + 1))
  return [1]


def _build_review_plan(
  *,
  worst_unresolved: Dict[str, Any],
  candidate_levers: List[str],
  horizon: int,
) -> Dict[str, Any]:
  quarters = _quarter_indices_for_metric(worst_unresolved=worst_unresolved, horizon=horizon)
  metric_key = _clean_text(worst_unresolved.get("metric_key"))
  rows = []
  for q in quarters:
    rows.append({
      "quarter_index": int(q),
      "allowed_lever_ids": list(candidate_levers),
      "source_action_ids": [f"target_seeking_outer_loop:{metric_key}@q{q}"],
      "missing_required_metrics": [],
      "solver_ready": True,
      "target_metrics": [metric_key] if metric_key else [],
    })
  return {
    "contract_version": "review_plan_target_seeking_inner_v1",
    "decision_source": "target_seeking_outer_loop",
    "metric_key": metric_key,
    "quarter_rows": rows,
  }


def _lever_bounds_from_envelope(
  *,
  candidate_levers: List[str],
  envelope_payload: Optional[Dict[str, Any]],
  quarter_indices: List[int],
) -> Dict[str, Any]:
  """Translate the outer-loop driver_movement_envelope into the lever_bounds
  shape numeric_solver.solve_review_plan expects.
  """
  drivers = (envelope_payload or {}).get("drivers") if isinstance(envelope_payload, dict) else {}
  bounds: Dict[str, List[Dict[str, Any]]] = {}
  if not isinstance(drivers, dict):
    return {"lever_bounds": bounds}
  for lever_id in candidate_levers:
    envelope = drivers.get(lever_id)
    if not isinstance(envelope, dict):
      continue
    mn = _safe_float(envelope.get("min_allowed"))
    mx = _safe_float(envelope.get("max_allowed"))
    default_value = _safe_float(envelope.get("default_value"))
    if mn is None or mx is None:
      continue
    bounds[lever_id] = [
      {
        "quarter_index": int(q),
        "min_value": float(mn),
        "max_value": float(mx),
        "default_value": float(default_value) if default_value is not None else None,
        "value_kind": _clean_text(envelope.get("value_kind")),
      }
      for q in quarter_indices
    ]
  return {"lever_bounds": bounds}


def _build_numeric_solver_contract(
  *,
  candidate_levers: List[str],
  worst_unresolved: Dict[str, Any],
  envelope_payload: Optional[Dict[str, Any]],
  horizon: int,
  deadline_seconds: float,
) -> Dict[str, Any]:
  quarter_indices = _quarter_indices_for_metric(worst_unresolved=worst_unresolved, horizon=horizon)
  lever_bounds = _lever_bounds_from_envelope(
    candidate_levers=candidate_levers,
    envelope_payload=envelope_payload,
    quarter_indices=quarter_indices,
  )
  metric_key = _clean_text(worst_unresolved.get("metric_key"))
  target_min = worst_unresolved.get("target_min")
  target_max = worst_unresolved.get("target_max")
  return {
    "contract_version": "numeric_solver_contract_target_seeking_inner_v1",
    "pass_name": "target_seeking_inner",
    "runtime_deadline_monotonic": time.monotonic() + float(deadline_seconds),
    "decision_source": "target_seeking_outer_loop",
    "metric_targets": [
      {
        "metric_key": metric_key,
        "quarter_indices": quarter_indices,
        "target_min": target_min,
        "target_max": target_max,
      }
    ],
    "lever_bounds": lever_bounds.get("lever_bounds") or {},
    "allowed_lever_ids": list(candidate_levers),
    "horizon": int(horizon),
  }


def build_inner_joint_fit_adapter(
  *,
  influence_map_payload: Optional[Dict[str, Any]],
  envelope_payload: Optional[Dict[str, Any]],
  horizon: int,
  deadline_seconds: float = _DEFAULT_INNER_DEADLINE_SECONDS,
) -> Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]:
  """Build the closure the outer loop calls for joint multi-lever fitting.

  The returned callable has signature (model_input_json, worst_unresolved)
  and returns {status, model_input_json, applied_updates, attempts, detail}.
  """

  def _adapter(
    model_input_json: Dict[str, Any], worst_unresolved: Dict[str, Any]
  ) -> Dict[str, Any]:
    metric_key = _clean_text(worst_unresolved.get("metric_key"))
    candidate_levers = _candidate_levers_for_metric(
      metric_key=metric_key,
      influence_map_payload=influence_map_payload,
      envelope_payload=envelope_payload,
    )
    if not candidate_levers:
      return {
        "status": "no_unlocked_candidate_levers",
        "metric_key": metric_key,
        "model_input_json": None,
        "detail": (
          "all influence-map candidates are schedule-locked or marked "
          "not_applicable; outer loop must use schedule_tweak path"
        ),
      }
    review_plan = _build_review_plan(
      worst_unresolved=worst_unresolved,
      candidate_levers=candidate_levers,
      horizon=horizon,
    )
    contract = _build_numeric_solver_contract(
      candidate_levers=candidate_levers,
      worst_unresolved=worst_unresolved,
      envelope_payload=envelope_payload,
      horizon=horizon,
      deadline_seconds=deadline_seconds,
    )
    try:
      from client_intake_and_finmo.numeric_solver import solve_review_plan  # type: ignore
    except Exception as exc:
      return {
        "status": "numeric_solver_import_failed",
        "metric_key": metric_key,
        "model_input_json": None,
        "detail": str(exc),
      }
    try:
      inner_result = solve_review_plan(
        model_input_json=copy.deepcopy(model_input_json or {}),
        review_plan=review_plan,
        numeric_solver_contract=contract,
        fallback_exact_updates=[],
      )
    except Exception as exc:
      return {
        "status": "numeric_solver_raised",
        "metric_key": metric_key,
        "model_input_json": None,
        "detail": str(exc),
      }
    if not isinstance(inner_result, dict):
      return {
        "status": "numeric_solver_invalid_result",
        "metric_key": metric_key,
        "model_input_json": None,
      }
    exact_updates = inner_result.get("exact_updates") or []
    if not exact_updates:
      return {
        "status": "no_exact_updates_produced",
        "metric_key": metric_key,
        "model_input_json": None,
        "attempts": inner_result.get("attempts"),
      }
    try:
      from client_intake_and_finmo.quarter_grid import (  # type: ignore
        apply_exact_lever_updates_to_model_input,
      )
      next_input = apply_exact_lever_updates_to_model_input(
        model_input_json=copy.deepcopy(model_input_json or {}),
        exact_updates=exact_updates,
      )
    except Exception as exc:
      return {
        "status": "exact_update_apply_failed",
        "metric_key": metric_key,
        "model_input_json": None,
        "detail": str(exc),
      }
    return {
      "status": "ok",
      "metric_key": metric_key,
      "candidate_levers": candidate_levers,
      "model_input_json": next_input,
      "applied_updates": exact_updates,
      "attempts": inner_result.get("attempts"),
      "outcome": inner_result.get("outcome"),
    }

  return _adapter
