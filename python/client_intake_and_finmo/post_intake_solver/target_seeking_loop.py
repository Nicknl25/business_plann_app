"""Target-Seeking Solver Loop — Phase 2 module 4.

Drives a model_input toward the FINMO output target ranges by tweaking
drivers within their movement envelopes. Layered ON TOP of the existing
issue-code infrastructure (numeric_solver.py, post_intake_convergence) —
this is an additional outer loop, not a replacement for the inner fitting
engine. The existing scipy/issue-code paths remain valid; they become a
subset of the gap-closing actions this loop can choose from.

Design summary (per Phase 2 directive "How the Solver Should Work"):
  1. Compute current FINMO from current drivers (call build_python_finmo_json).
  2. For each output target, compute deviation from target range. If all in
     range, return.
  3. Identify the worst-deviating output, then identify which drivers most
     influence that output (consult driver_influence_map).
  4. For each candidate driver, check its movement envelope. Pick the driver
     with the most movement room toward closing the gap.
  5. Tweak the chosen driver within its envelope; if schedule-locked,
     request the schedule recompute via schedule_tweak. Recompute FINMO.
  6. Loop. If after a configurable number of iterations no in-envelope
     combination lands all outputs in range, fail with a structured
     diagnostic naming the failed target, the pinned drivers, and the
     residual deviation.

This module deliberately stays compact. The heavy fitting math (gradient,
multi-lever joint optimization) is delegated to numeric_solver.solve_review_plan
when the trivial single-lever bisection is insufficient. Phase 3 may add a
GPT prioritization consultant call when ambiguous.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple


_DEFAULT_MAX_ITERATIONS = 24
_DEFAULT_NUMERIC_TOLERANCE = 1e-6


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


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _produced_metric_value(
  finmo_json: Dict[str, Any],
  metric_key: str,
  quarter_aggregation: str,
  quarter_index_1: int,
) -> Optional[float]:
  if quarter_aggregation == "per_quarter":
    rows = finmo_json.get("quarter_rows") if isinstance(finmo_json, dict) else None
    if not isinstance(rows, list) or quarter_index_1 < 1 or quarter_index_1 > len(rows):
      return None
    row = rows[quarter_index_1 - 1]
    if isinstance(row, dict):
      return _safe_float(row.get(metric_key))
    return None
  aggregate = _safe_float((finmo_json.get("year_one_summary") or {}).get(metric_key))
  if aggregate is None:
    aggregate = _safe_float((finmo_json.get("aggregates") or {}).get(metric_key))
  return aggregate


def _residual(value: float, lo: Optional[float], hi: Optional[float]) -> float:
  if lo is not None and value < float(lo):
    return float(value) - float(lo)
  if hi is not None and value > float(hi):
    return float(value) - float(hi)
  return 0.0


def _worst_deviation(
  *,
  finmo_json: Dict[str, Any],
  output_targets_payload: Dict[str, Any],
  numeric_tolerance: float,
) -> Optional[Dict[str, Any]]:
  worst: Optional[Dict[str, Any]] = None
  for metric_key, target_row in (output_targets_payload.get("metrics") or {}).items():
    if not isinstance(target_row, dict):
      continue
    target_min = _safe_float(target_row.get("target_min"))
    target_max = _safe_float(target_row.get("target_max"))
    if target_min is None and target_max is None:
      continue
    quarter_aggregation = _clean_text(target_row.get("quarter_aggregation")) or "per_quarter"
    quarters = (
      list(range(1, len((finmo_json or {}).get("quarter_rows") or []) + 1))
      if quarter_aggregation == "per_quarter"
      else [1]
    )
    for q in quarters:
      produced = _produced_metric_value(finmo_json, metric_key, quarter_aggregation, q)
      if produced is None:
        continue
      residual = _residual(float(produced), target_min, target_max)
      if abs(residual) <= numeric_tolerance:
        continue
      severity = abs(residual)
      if worst is None or severity > worst["severity"]:
        worst = {
          "metric_key": metric_key,
          "quarter_index": q if quarter_aggregation == "per_quarter" else None,
          "quarter_aggregation": quarter_aggregation,
          "produced": float(produced),
          "target_min": target_min,
          "target_max": target_max,
          "residual": residual,
          "severity": severity,
          "gate_kind": _clean_text(target_row.get("gate_kind")) or "warn",
          "target_row": copy.deepcopy(target_row),
        }
  return worst


def _candidate_lever_with_room(
  *,
  influence_entry: Dict[str, Any],
  envelope_payload: Dict[str, Any],
  desired_direction: str,
  current_lever_values: Dict[str, float],
) -> Optional[Dict[str, Any]]:
  drivers = envelope_payload.get("drivers") if isinstance(envelope_payload.get("drivers"), dict) else {}
  best: Optional[Dict[str, Any]] = None
  for candidate in (influence_entry.get("candidate_levers") or []):
    if not isinstance(candidate, dict):
      continue
    lever_id = _clean_text(candidate.get("lever_id"))
    envelope = drivers.get(lever_id) if isinstance(drivers, dict) else None
    if not isinstance(envelope, dict) or not envelope.get("applicable"):
      continue
    mn = _safe_float(envelope.get("min_allowed"))
    mx = _safe_float(envelope.get("max_allowed"))
    cur = current_lever_values.get(lever_id)
    if cur is None:
      cur = _safe_float(envelope.get("default_value"))
    if cur is None or mn is None or mx is None:
      continue
    sign_hint = _clean_text(candidate.get("sign_hint")).lower()
    room = 0.0
    if desired_direction == "increase":
      if sign_hint == "decrease":
        room = max(0.0, cur - mn)
      else:
        room = max(0.0, mx - cur)
    elif desired_direction == "decrease":
      if sign_hint == "decrease":
        room = max(0.0, mx - cur)
      else:
        room = max(0.0, cur - mn)
    else:
      room = max(0.0, mx - cur, cur - mn)
    score = room
    if best is None or score > best["room"]:
      best = {
        "lever_id": lever_id,
        "min_allowed": mn,
        "max_allowed": mx,
        "current_value": cur,
        "sign_hint": sign_hint,
        "schedule_locked": bool(envelope.get("schedule_locked")),
        "room": room,
        "priority": int(candidate.get("priority") or 99),
      }
  return best


def _direction_to_close_gap(residual: float) -> str:
  if residual < 0:
    return "increase"
  if residual > 0:
    return "decrease"
  return "either"


def run_target_seeking_solver(
  *,
  model_input_json: Dict[str, Any],
  build_finmo_callable: Callable[[Dict[str, Any]], Dict[str, Any]],
  apply_lever_value_callable: Callable[[Dict[str, Any], str, float], Dict[str, Any]],
  output_targets_payload: Optional[Dict[str, Any]] = None,
  driver_envelope_payload: Optional[Dict[str, Any]] = None,
  influence_map_payload: Optional[Dict[str, Any]] = None,
  max_iterations: int = _DEFAULT_MAX_ITERATIONS,
  numeric_tolerance: float = _DEFAULT_NUMERIC_TOLERANCE,
  inner_joint_fit_callable: Optional[
    Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
  ] = None,
  inner_joint_fit_after_iterations: int = 6,
) -> Dict[str, Any]:
  """Run the target-seeking outer loop.

  Args:
    model_input_json: starting model_input. Must already have driver values
      for Q1-Q20 (envelope defaults applied during finmo_bridge build).
    build_finmo_callable: f(model_input_json) -> finmo_json. Typically
      finmo_bridge.build_python_finmo_json or a closure over it.
    apply_lever_value_callable: f(model_input_json, lever_id, value) ->
      next_model_input_json. Typically a wrapper over
      quarter_grid.apply_exact_lever_updates_to_model_input that writes the
      value to all 20 forecast quarters.
    output_targets_payload: pre-assembled FINMO output targets. When None,
      the assembler runs.
    driver_envelope_payload: pre-assembled driver movement envelope. When
      None, the assembler runs.
    influence_map_payload: pre-assembled influence map. When None, the
      builder runs.

  Returns:
    {
      "status": "converged" | "max_iterations_reached" | "stuck_pinned",
      "iterations_used": int,
      "trace": [
        {"iteration", "worst_metric", "chosen_lever", "old_value",
         "new_value", "residual_before", "residual_after"},
        ...
      ],
      "final_model_input_json": <dict>,
      "final_finmo_json": <dict>,
    }
  """
  if output_targets_payload is None or driver_envelope_payload is None or influence_map_payload is None:
    naics_6 = ""
    ops_section = (model_input_json or {}).get("ops") if isinstance(model_input_json, dict) else None
    if isinstance(ops_section, dict):
      naics_6 = "".join(ch for ch in str(ops_section.get("business_naics_6") or "") if ch.isdigit())
    if not naics_6 and isinstance(model_input_json, dict):
      naics_6 = "".join(ch for ch in str(model_input_json.get("business_naics_6") or "") if ch.isdigit())
    from client_intake_and_finmo.post_intake_solver import (  # local import to avoid cycle
      assemble_driver_movement_envelope,
      assemble_finmo_output_targets,
      driver_influence_map,
    )
    if output_targets_payload is None:
      output_targets_payload = assemble_finmo_output_targets(business_naics_6=naics_6 or None)
    if driver_envelope_payload is None:
      driver_envelope_payload = assemble_driver_movement_envelope(business_naics_6=naics_6 or None)
    if influence_map_payload is None:
      influence_map_payload = driver_influence_map()

  state_input = copy.deepcopy(model_input_json)
  trace: List[Dict[str, Any]] = []
  final_finmo: Dict[str, Any] = {}
  iterations_used = 0
  pinned_keys: set[Tuple[str, str]] = set()
  iterations_since_progress = 0
  last_severity: Optional[float] = None
  inner_invocations = 0

  for iteration in range(1, int(max(1, max_iterations)) + 1):
    iterations_used = iteration
    final_finmo = build_finmo_callable(state_input)
    worst = _worst_deviation(
      finmo_json=final_finmo,
      output_targets_payload=output_targets_payload,
      numeric_tolerance=numeric_tolerance,
    )
    if worst is None:
      return {
        "status": "converged",
        "iterations_used": iterations_used,
        "trace": trace,
        "inner_invocations": inner_invocations,
        "final_model_input_json": state_input,
        "final_finmo_json": final_finmo,
      }
    influence_entry = (influence_map_payload.get("metrics") or {}).get(worst["metric_key"]) or {}
    if not influence_entry.get("candidate_levers"):
      return {
        "status": "no_candidate_levers",
        "iterations_used": iterations_used,
        "trace": trace,
        "worst_unresolved": worst,
        "inner_invocations": inner_invocations,
        "final_model_input_json": state_input,
        "final_finmo_json": final_finmo,
      }
    desired_direction = _direction_to_close_gap(worst["residual"])
    current_lever_values: Dict[str, float] = {}
    for section in ("revenue", "expenses", "balance_sheet"):
      for row in (((state_input.get("sections") or {}).get(section) or [])):
        if not isinstance(row, dict):
          continue
        lever_id = _clean_text(row.get("lever_id"))
        if not lever_id:
          continue
        values = row.get("values") or []
        if isinstance(values, list) and len(values) >= 2:
          current_lever_values[lever_id] = _safe_float(values[1]) or 0.0
    pick = _candidate_lever_with_room(
      influence_entry=influence_entry,
      envelope_payload=driver_envelope_payload,
      desired_direction=desired_direction,
      current_lever_values=current_lever_values,
    )
    # Track progress against severity. Stagnation after a configurable
    # number of iterations triggers the inner-joint-fit adapter (if the
    # caller supplied one) so the outer loop can delegate gap-closing to
    # the existing scipy/issue-code solver for joint multi-lever fitting.
    if last_severity is None or worst["severity"] < last_severity - numeric_tolerance:
      iterations_since_progress = 0
    else:
      iterations_since_progress += 1
    last_severity = worst["severity"]
    invoke_inner = (
      inner_joint_fit_callable is not None
      and iterations_since_progress >= max(1, int(inner_joint_fit_after_iterations))
    )
    if invoke_inner:
      try:
        inner_result = inner_joint_fit_callable(state_input, worst)
      except Exception as exc:
        # Phase 9 P3.10 Commit 3 — under test mode the inner-runner
        # exception must propagate. Previously: status string masquerading
        # as "no_progress" let the outer loop spin to max_iterations and
        # return a status dict with no surfaced root cause.
        from client_intake_and_finmo.fail_fast.common import (  # type: ignore
          PostIntakePreconditionFailed,
          convergence_test_mode_enabled,
        )
        if convergence_test_mode_enabled():
          raise PostIntakePreconditionFailed(
            operation="target_seeking_loop_inner_joint_fit_raised",
            pipeline_stage="post_intake_target_seeking_loop",
            expected="inner_joint_fit_callable returns a dict",
            actual=f"{type(exc).__name__}: {str(exc)[:200]}",
            details={
              "iteration": int(iteration),
              "worst_metric": worst.get("metric_key"),
              "worst_quarter_index": worst.get("quarter_index"),
              "inner_invocation_count": int(inner_invocations),
            },
            cause=exc,
          ) from exc
        inner_result = {"status": "inner_joint_fit_raised", "detail": str(exc)}
      inner_invocations += 1
      if isinstance(inner_result, dict) and isinstance(inner_result.get("model_input_json"), dict):
        state_input = inner_result["model_input_json"]
        trace.append({
          "iteration": iteration,
          "worst_metric": worst["metric_key"],
          "worst_quarter_index": worst.get("quarter_index"),
          "worst_residual_before": worst["residual"],
          "chosen_tool": "inner_joint_fit_adapter",
          "inner_status": _clean_text(inner_result.get("status")) or "completed",
          "inner_invocation": inner_invocations,
        })
        iterations_since_progress = 0
        last_severity = None
        continue
      else:
        trace.append({
          "iteration": iteration,
          "worst_metric": worst["metric_key"],
          "chosen_tool": "inner_joint_fit_adapter",
          "inner_status": "no_progress",
          "inner_detail": (inner_result or {}).get("detail") if isinstance(inner_result, dict) else None,
        })

    if pick is None or pick.get("room", 0.0) <= numeric_tolerance:
      return {
        "status": "stuck_pinned",
        "iterations_used": iterations_used,
        "trace": trace,
        "worst_unresolved": worst,
        "inner_invocations": inner_invocations,
        "final_model_input_json": state_input,
        "final_finmo_json": final_finmo,
      }
    if (pick["lever_id"], desired_direction) in pinned_keys:
      return {
        "status": "stuck_pinned",
        "iterations_used": iterations_used,
        "trace": trace,
        "worst_unresolved": worst,
        "inner_invocations": inner_invocations,
        "final_model_input_json": state_input,
        "final_finmo_json": final_finmo,
      }
    sign = -1.0 if pick.get("sign_hint") == "decrease" else 1.0
    if desired_direction == "decrease":
      sign = -sign
    step = float(pick["room"]) * 0.5  # take half the available room each iteration
    new_value = float(pick["current_value"]) + sign * step
    new_value = max(float(pick["min_allowed"]), min(float(pick["max_allowed"]), new_value))
    if abs(new_value - float(pick["current_value"])) <= numeric_tolerance:
      pinned_keys.add((pick["lever_id"], desired_direction))
      continue
    state_input = apply_lever_value_callable(state_input, pick["lever_id"], new_value)
    trace.append({
      "iteration": iteration,
      "worst_metric": worst["metric_key"],
      "worst_quarter_index": worst.get("quarter_index"),
      "worst_residual_before": worst["residual"],
      "chosen_lever": pick["lever_id"],
      "schedule_locked": bool(pick.get("schedule_locked")),
      "old_value": round(float(pick["current_value"]), 6),
      "new_value": round(float(new_value), 6),
      "envelope_min": round(float(pick["min_allowed"]), 6),
      "envelope_max": round(float(pick["max_allowed"]), 6),
      "desired_direction": desired_direction,
      "sign_hint": pick.get("sign_hint"),
    })

  return {
    "status": "max_iterations_reached",
    "iterations_used": iterations_used,
    "trace": trace,
    "inner_invocations": inner_invocations,
    "final_model_input_json": state_input,
    "final_finmo_json": final_finmo,
  }
