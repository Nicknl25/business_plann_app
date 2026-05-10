"""Phase 9 P3.5 — Iteration loop + deterministic snap-into-place.

Called by handler_runtime.execute_handler when Q11 EBITDA does not
converge to the GPT Call 1 anchor after Call 2.

Iteration discipline:
  - Up to MAX_ITERATIONS=3 fresh GPT calls.
  - GPT keeps the Call 1 EBITDA anchor stable across all iterations
    (handler tells it so in every iteration prompt). Drivers only
    are updated each iteration.
  - Each iteration carries cumulative diagnostic: prior driver
    summaries, FINMO Q11 actuals, gaps, and the Q11 line-item
    breakdown so GPT can reason about which lever needs movement.

Snap-into-place (after 3 failed iterations):
  - Use the existing post_intake_target_solver.solve_for_target with
    EBITDA margin as the target metric.
  - Build target_ramp from {Q1=current, Q11=GPT_anchor_q11,
    Q20=GPT_anchor_q20} interpolated linearly.
  - Per-driver bounds: ±15% around GPT's most-recent driver values.
    Lets the deterministic algebra nudge drivers without overriding
    GPT's strategic decisions.
  - If snap-in lands within ±15% bounds AND Q11 within tolerance =>
    LANDED_SNAP. If snap-in lands within bounds but not Q11 tolerance
    => LANDED_PARTIAL with diagnostic.

Realism flags to mute (per-draft, per-metric — not global) are
identified at the end of this routine. Phase 4 may refine the
selection logic; the runtime contract here is "any metric whose
primary_levers include any GPT-authored driver, and which had a
hard_fail in the restoration loop's exhaustion diagnostic, is muted
for this draft." Phase 4 finalizes the wiring.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.handler import (
  HandlerResult,
  HandlerStatus,
  TOLERANCE_BPS,
  MAX_ITERATIONS,
  SNAP_IN_DRIVER_TOLERANCE,
  HORIZON_QUARTERS,
  GPT_AUTHORED_LEVER_IDS,
  _DRIVER_KEY_TO_LEVER_ID,
  _q11_ebitda_margin,
  _q11_line_items,
  _write_gpt_authored_per_quarter_values,
  interpolate_three_anchors,
)
from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.prompts import (
  SYSTEM_PROMPT,
  CALL_2_RESPONSE_SCHEMA,
  build_iteration_user_prompt,
)
from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.validators import (
  validate_call_2,
)


logger = logging.getLogger(__name__)


# Snap-in tolerance read from handler.py's SNAP_IN_DRIVER_TOLERANCE so
# changes to the constant propagate uniformly. Per Phase 9 P3.5
# tuning: ±20% (was ±15%) — gives the deterministic solver enough
# room to close gaps up to ~10pp on EBITDA margin without departing
# from GPT's strategic anchor choice.
_SNAP_IN_LOWER_FRAC = 1.0 - float(SNAP_IN_DRIVER_TOLERANCE)
_SNAP_IN_UPPER_FRAC = 1.0 + float(SNAP_IN_DRIVER_TOLERANCE)


def _gpt_call_iteration(
  *,
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  call_1_output: Dict[str, Any],
  most_recent_drivers: Dict[str, Any],
  iteration_number: int,
  finmo_q11_actual: float,
  q11_line_items: Dict[str, float],
  iteration_history: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], int, Optional[str], str]:
  """Run a single iteration GPT call. Retry once on validation failure
  with the validation error in-prompt. Returns
  (parsed_or_None, calls_used, last_error, last_decision_source).
  """
  from client_intake_and_finmo.post_intake_solver._gpt_critic_io import (  # type: ignore
    call_gpt_with_schema_or_fallback,
  )
  prompt = build_iteration_user_prompt(
    operating_model=operating_model,
    q1_state=q1_state,
    call_1_output=call_1_output,
    most_recent_drivers=most_recent_drivers,
    iteration_number=iteration_number,
    max_iterations=MAX_ITERATIONS,
    finmo_q11_actual=finmo_q11_actual,
    q11_line_items=q11_line_items,
    iteration_history=iteration_history,
  )
  resp = call_gpt_with_schema_or_fallback(
    consultant_name=f"post_intake_gpt_exhaustion_handler_iter_{iteration_number}",
    system_prompt=SYSTEM_PROMPT,
    user_context={"prompt": prompt},
    response_schema=CALL_2_RESPONSE_SCHEMA,
    schema_name=f"post_intake_gpt_exhaustion_handler_iter_{iteration_number}",
  )
  parsed = resp.get("parsed") if isinstance(resp, dict) else None
  decision = resp.get("decision_source") if isinstance(resp, dict) else "unknown"
  ok, err = validate_call_2(parsed)
  if ok:
    return parsed, 1, None, decision

  # Single retry with validation error.
  retry_prompt = build_iteration_user_prompt(
    operating_model=operating_model,
    q1_state=q1_state,
    call_1_output=call_1_output,
    most_recent_drivers=most_recent_drivers,
    iteration_number=iteration_number,
    max_iterations=MAX_ITERATIONS,
    finmo_q11_actual=finmo_q11_actual,
    q11_line_items=q11_line_items,
    iteration_history=iteration_history,
    validation_error=err,
  )
  resp2 = call_gpt_with_schema_or_fallback(
    consultant_name=f"post_intake_gpt_exhaustion_handler_iter_{iteration_number}_retry",
    system_prompt=SYSTEM_PROMPT,
    user_context={"prompt": retry_prompt},
    response_schema=CALL_2_RESPONSE_SCHEMA,
    schema_name=f"post_intake_gpt_exhaustion_handler_iter_{iteration_number}_retry",
  )
  parsed2 = resp2.get("parsed") if isinstance(resp2, dict) else None
  decision2 = resp2.get("decision_source") if isinstance(resp2, dict) else "unknown"
  ok2, err2 = validate_call_2(parsed2)
  if ok2:
    return parsed2, 2, None, decision2
  return None, 2, err2 or err, decision2 or decision


def _summarize_drivers(driver_anchors: Dict[str, Any]) -> str:
  """One-line summary used in iteration history blocks."""
  parts: List[str] = []
  for k, v in (driver_anchors or {}).items():
    if not isinstance(v, dict):
      continue
    q1 = v.get("q1")
    q11 = v.get("q11")
    q20 = v.get("q20")
    parts.append(f"{k}={q1}/{q11}/{q20}")
  return ", ".join(parts)


def _snap_into_place(
  *,
  call_1_output: Dict[str, Any],
  most_recent_drivers: Dict[str, Any],
  q1_state: Dict[str, Any],
  q20_target: float,
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  intake_context: Dict[str, Any],
) -> Dict[str, Any]:
  """Use the existing target solver to nudge drivers within ±15% of
  GPT's anchored values to land Q11 EBITDA = GPT's anchor.

  Returns a diagnostic dict carrying:
    snap_status: 'converged' | 'bound_pinned' | 'no_attempt'
    final_q11_ebitda_margin: float
    target_ramp_q1_q11_q20: [float, float, float]
    drivers_at_bounds: dict[lever_id, 'lower'|'upper']
  """
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    DriverBound,
    SolverStatus,
    solve_for_target,
    _find_rows_for_lever,
  )

  # Build the EBITDA target ramp from GPT's Q11 / Q20 anchors and
  # the CURRENT Q1 EBITDA margin (read from a fresh FINMO build, not
  # the stale q1_state captured at handler entry — handler iterations
  # will have moved Q1 EBITDA away from the operator-baseline that
  # q1_state captured). Using stale q1_em produced a target_ramp Q1
  # at the operator-baseline value (e.g., -1.014 for Sunny), telling
  # the solver "keep Q1 at -101%" — which traps allocation away from
  # Q11 where the residual lives.
  pre_snap_finmo = build_finmo(copy.deepcopy(model_input))
  q1_em = 0.0
  for row in (pre_snap_finmo or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi == 1:
      rev = float(row.get("revenue") or 0.0)
      if rev > 0:
        q1_em = float(row.get("ebitda") or 0.0) / rev
      break
  q11_target = float((call_1_output or {}).get("ebitda_anchors", {}).get("q11", 0.0))
  target_ramp = interpolate_three_anchors(
    q1=q1_em, q11=q11_target, q20=float(q20_target), horizon=HORIZON_QUARTERS,
  )

  # Detect labor-driven capacity. Skip Capacity in snap-in writes for
  # rows with derived_driver=payroll_supported_capacity — same rule as
  # the handler's writer. Without this, snap-in writes Capacity values
  # that may diverge from FINMO's payroll-derived capacity, violating
  # the revenue_driver_formula_contract on rebuild.
  capacity_rows_for_detect = _find_rows_for_lever(
    model_input or {}, "revenue::Capacity"
  )
  capacity_is_payroll_supported = any(
    str(r.get("derived_driver") or "").strip() == "payroll_supported_capacity"
    or isinstance(r.get("payroll_supported_capacity"), dict)
    for r in (capacity_rows_for_detect or [])
  )

  # Build per-driver bounds = ±15% around GPT's most-recent values.
  # Use the Q11 anchor as the anchor reference for the ±15% range
  # (mid-trajectory, where the binding constraint lives).
  driver_bounds: Dict[str, DriverBound] = {}
  driver_kind_for_lever = _driver_kind_lookup()
  for driver_key, lever_id in _DRIVER_KEY_TO_LEVER_ID.items():
    if lever_id == "revenue::Capacity" and capacity_is_payroll_supported:
      # Same skip rule as the handler's writer.
      continue
    triple = (most_recent_drivers or {}).get(driver_key)
    if not isinstance(triple, dict):
      continue
    try:
      anchor_q11 = float(triple.get("q11"))
    except Exception:
      continue
    if anchor_q11 <= 0:
      # Defer: bound math doesn't make sense around zero.
      continue
    lower = anchor_q11 * _SNAP_IN_LOWER_FRAC
    upper = anchor_q11 * _SNAP_IN_UPPER_FRAC
    driver_kind = driver_kind_for_lever.get(lever_id, "unknown")
    if driver_kind == "unknown":
      continue
    driver_bounds[lever_id] = DriverBound(
      lower=float(lower),
      upper=float(upper),
      driver_kind=driver_kind,
      bound_source="snap_in_around_gpt_anchor_plus_minus_15pct",
    )

  if not driver_bounds:
    return {
      "snap_status": "no_attempt",
      "reason": "no_resolvable_driver_bounds",
      "final_q11_ebitda_margin": _q11_ebitda_margin(build_finmo(copy.deepcopy(model_input))),
      "target_ramp_q1_q11_q20": [target_ramp[0], target_ramp[10], target_ramp[-1]],
      "drivers_at_bounds": {},
    }

  try:
    result = solve_for_target(
      target_metric="ebitda_margin",
      target_ramp=target_ramp,
      driver_lever_ids=list(driver_bounds.keys()),
      driver_bounds=driver_bounds,
      model_input=model_input,
      build_finmo=build_finmo,
      horizon=HORIZON_QUARTERS,
    )
  except Exception as exc:
    return {
      "snap_status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:200]}",
      "final_q11_ebitda_margin": _q11_ebitda_margin(build_finmo(copy.deepcopy(model_input))),
      "target_ramp_q1_q11_q20": [target_ramp[0], target_ramp[10], target_ramp[-1]],
      "drivers_at_bounds": {},
    }

  final_finmo = build_finmo(copy.deepcopy(model_input))
  final_q11 = _q11_ebitda_margin(final_finmo or {})
  status_value = (
    result.status.value if hasattr(result.status, "value") else str(result.status)
  )
  return {
    "snap_status": status_value,
    "inner_iterations": result.inner_iterations_used,
    "final_q11_ebitda_margin": final_q11,
    "target_ramp_q1_q11_q20": [target_ramp[0], target_ramp[10], target_ramp[-1]],
    "drivers_at_bounds": dict(result.drivers_at_bounds),
    "drivers_moved_keys": list((result.drivers_moved or {}).keys()),
  }


def _driver_kind_lookup() -> Dict[str, str]:
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _driver_kind_for_lever,
  )
  return {lid: _driver_kind_for_lever(lid) for lid in GPT_AUTHORED_LEVER_IDS}


def iterate_and_snap(
  *,
  starting_provenance: Dict[str, Any],
  starting_call_count: int,
  call_1_output: Dict[str, Any],
  most_recent_drivers: Dict[str, Any],
  operating_model: Dict[str, Any],
  q1_state: Dict[str, Any],
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  intake_context: Dict[str, Any],
  exhaustion_diagnostic: Dict[str, Any],
  q20_target: float,
) -> HandlerResult:
  """Iteration loop (up to MAX_ITERATIONS) + snap-into-place fallback.

  Mutates ``model_input`` in place. Returns a HandlerResult with the
  full call / iteration / snap-in provenance trail.
  """
  provenance = dict(starting_provenance)
  q11_target = float((call_1_output or {}).get("ebitda_anchors", {}).get("q11", 0.0))
  tolerance_decimal = float(TOLERANCE_BPS) / 10000.0
  iteration_history: List[Dict[str, Any]] = []
  gpt_calls_made = int(starting_call_count)
  current_drivers: Dict[str, Any] = dict(most_recent_drivers or {})

  iteration_records: List[Dict[str, Any]] = []
  iterations_used = 0

  for iteration_number in range(1, MAX_ITERATIONS + 1):
    # Measure current Q11 and check convergence BEFORE asking GPT to
    # adjust again — the iteration loop is "iterate UNTIL converged".
    finmo_now = build_finmo(copy.deepcopy(model_input))
    q11_now = _q11_ebitda_margin(finmo_now or {})
    iteration_history.append({
      "iteration_number": iteration_number - 1 if iteration_number > 1 else 0,
      "driver_summary": _summarize_drivers(current_drivers),
      "finmo_q11_actual": q11_now,
      "gap": (
        abs(q11_target - float(q11_now)) if q11_now is not None else None
      ),
    })
    # Phase 9 P3.5 — convergence requires BOTH:
    #   (a) within-tolerance: |gpt_target_q11 - finmo_q11| <= 50bps
    #   (b) gate-threshold met: finmo_q11 >= 0.0 (universal viability
    #       doctrine — the realism gate's strict ebitda_positive_by_q11
    #       check must also pass)
    # GPT can correctly anchor Q11 = 0.0 (binding viability constraint)
    # and FINMO can drift down by tens of bps. Without (b) the handler
    # would report LANDED while the gate fails. The iteration / snap-in
    # paths below close the residual.
    within_tolerance = (
      q11_now is not None
      and abs(q11_target - float(q11_now)) <= tolerance_decimal
    )
    gate_threshold_met = q11_now is not None and float(q11_now) >= 0.0
    if within_tolerance and gate_threshold_met:
      provenance["iterations"] = iteration_records
      return HandlerResult(
        status=HandlerStatus.LANDED_ITERATED if iterations_used > 0 else HandlerStatus.LANDED_GPT,
        gpt_calls_made=gpt_calls_made,
        iterations_used=iterations_used,
        q11_ebitda_target=q11_target,
        q11_ebitda_actual=float(q11_now),
        provenance=provenance,
        realism_flags_to_mute=_realism_metrics_to_mute(exhaustion_diagnostic),
        reason="converged_within_tolerance_and_gate_threshold",
      )

    line_items = _q11_line_items(finmo_now or {})

    parsed, calls_used, err, decision = _gpt_call_iteration(
      operating_model=operating_model,
      q1_state=q1_state,
      call_1_output=call_1_output,
      most_recent_drivers=current_drivers,
      iteration_number=iteration_number,
      finmo_q11_actual=float(q11_now) if q11_now is not None else 0.0,
      q11_line_items=line_items,
      iteration_history=iteration_history,
    )
    gpt_calls_made += calls_used
    iterations_used += 1
    iteration_record = {
      "iteration_number": iteration_number,
      "calls_used": calls_used,
      "decision_source": decision,
      "schema_valid": parsed is not None,
      "schema_error": err,
      "pre_iteration_q11_ebitda_margin": q11_now,
    }

    if not parsed:
      iteration_record["status"] = "abort_to_snap_in_invalid_schema"
      iteration_records.append(iteration_record)
      break

    new_drivers = (parsed or {}).get("driver_anchors") or {}
    write_summary = _write_gpt_authored_per_quarter_values(
      model_input=model_input,
      driver_anchors=new_drivers,
      provenance_tag=f"gpt_iteration_{iteration_number}_drivers",
    )
    current_drivers = new_drivers
    iteration_record["driver_anchors_q1_q11_q20"] = {
      k: {"q1": (v or {}).get("q1"), "q11": (v or {}).get("q11"), "q20": (v or {}).get("q20")}
      for k, v in (new_drivers or {}).items()
      if isinstance(v, dict)
    }
    iteration_record["write_summary"] = write_summary
    iteration_records.append(iteration_record)

  # 3 iterations done — final convergence check (dual condition).
  finmo_final = build_finmo(copy.deepcopy(model_input))
  q11_final = _q11_ebitda_margin(finmo_final or {})
  provenance["iterations"] = iteration_records
  provenance["post_iterations_q11_ebitda_margin"] = q11_final

  final_within_tolerance = (
    q11_final is not None
    and abs(q11_target - float(q11_final)) <= tolerance_decimal
  )
  final_gate_threshold_met = (
    q11_final is not None and float(q11_final) >= 0.0
  )
  if final_within_tolerance and final_gate_threshold_met:
    return HandlerResult(
      status=HandlerStatus.LANDED_ITERATED,
      gpt_calls_made=gpt_calls_made,
      iterations_used=iterations_used,
      q11_ebitda_target=q11_target,
      q11_ebitda_actual=float(q11_final),
      provenance=provenance,
      realism_flags_to_mute=_realism_metrics_to_mute(exhaustion_diagnostic),
      reason="converged_after_iteration_and_gate_threshold",
    )

  # Snap-in fallback. Closes the residual gap deterministically when
  # the GPT iteration loop didn't reach BOTH within-tolerance AND
  # gate-threshold-met. Common path: iterations got within 50bps of
  # target but FINMO Q11 sits a few bps below 0; snap-in nudges
  # drivers within ±15% of GPT anchors to push it positive.
  snap_diag = _snap_into_place(
    call_1_output=call_1_output,
    most_recent_drivers=current_drivers,
    q1_state=q1_state,
    q20_target=q20_target,
    model_input=model_input,
    build_finmo=build_finmo,
    intake_context=intake_context,
  )
  provenance["snap_in"] = snap_diag
  q11_after_snap = snap_diag.get("final_q11_ebitda_margin")

  snap_within_tolerance = (
    q11_after_snap is not None
    and abs(q11_target - float(q11_after_snap)) <= tolerance_decimal
  )
  snap_gate_threshold_met = (
    q11_after_snap is not None and float(q11_after_snap) >= 0.0
  )
  if snap_within_tolerance and snap_gate_threshold_met:
    return HandlerResult(
      status=HandlerStatus.LANDED_SNAP,
      gpt_calls_made=gpt_calls_made,
      iterations_used=iterations_used,
      q11_ebitda_target=q11_target,
      q11_ebitda_actual=float(q11_after_snap),
      provenance=provenance,
      realism_flags_to_mute=_realism_metrics_to_mute(exhaustion_diagnostic),
      reason="snap_in_landed_within_tolerance_and_gate_threshold",
    )

  # Snap-in fell short (rare). Return LANDED_PARTIAL so the plan still
  # gets persisted with Q11 close to but not exactly at GPT's target
  # OR not strictly above zero. Diagnostic captures which condition
  # was the missed one for downstream debugging.
  return HandlerResult(
    status=HandlerStatus.LANDED_PARTIAL,
    gpt_calls_made=gpt_calls_made,
    iterations_used=iterations_used,
    q11_ebitda_target=q11_target,
    q11_ebitda_actual=(
      float(q11_after_snap) if q11_after_snap is not None else None
    ),
    provenance=provenance,
    realism_flags_to_mute=_realism_metrics_to_mute(exhaustion_diagnostic),
    reason=(
      "snap_in_did_not_reach_convergence_persisting_partial: "
      f"within_tolerance={snap_within_tolerance} "
      f"gate_threshold_met={snap_gate_threshold_met} "
      f"q11_after_snap={q11_after_snap}"
    ),
  )


def _realism_metrics_to_mute(
  exhaustion_diagnostic: Dict[str, Any]
) -> List[str]:
  """Phase 4 — determine which realism metrics to mute for THIS draft.

  A metric is muted iff:
    1. It is one of the realism gate's checked metrics AND its
       primary_levers include any GPT-authored driver
       (GPT_AUTHORED_LEVER_IDS), OR
    2. It is the universal viability metric ``ebitda_margin``
       (always muted post-exhaustion because GPT authored the EBITDA
       trajectory itself).

  We inspect the realism config's primary_levers for each metric and
  cross-check against GPT_AUTHORED_LEVER_IDS. Universal viability
  trajectory checks (ebitda_positive_by_q11, ebitda_recovery_trend_q5_q11,
  loss_window_funded_through_q5, no_post_recovery_relapse_q11_q20,
  gross_margin_supports_ebitda_recovery,
  fixed_cost_burden_reduced_or_scaled_by_q11) STAY ACTIVE — they
  evaluate against FINMO outputs (revenue, EBITDA dollar amounts), not
  driver values. They MUST still pass for the verdict.

  Per-draft only — metric definitions in lookup.py stay unchanged.
  """
  to_mute: List[str] = ["ebitda_margin"]
  gpt_authored = set(GPT_AUTHORED_LEVER_IDS)

  # Trajectory checks (universal viability) — never muted.
  _UNIVERSAL_VIABILITY_TRAJECTORY_METRICS = {
    "ebitda_positive_by_q11",
    "ebitda_recovery_trend_q5_q11",
    "loss_window_funded_through_q5",
    "no_post_recovery_relapse_q11_q20",
    "gross_margin_supports_ebitda_recovery",
    "fixed_cost_burden_reduced_or_scaled_by_q11",
  }

  try:
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    rows = post_intake_finalize_realism_check_rows() or []
  except Exception:
    rows = []

  for row in rows:
    if not isinstance(row, dict):
      continue
    metric_key = str(row.get("metric_key") or "").strip()
    if not metric_key or metric_key in to_mute:
      continue
    if metric_key in _UNIVERSAL_VIABILITY_TRAJECTORY_METRICS:
      continue
    if not bool(row.get("active", True)):
      continue
    primary_levers = row.get("primary_levers") or []
    if not isinstance(primary_levers, (list, tuple)):
      continue
    if any(str(p or "").strip() in gpt_authored for p in primary_levers):
      to_mute.append(metric_key)

  return to_mute
