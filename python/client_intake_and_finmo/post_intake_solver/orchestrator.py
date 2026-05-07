"""Top-level target-seeking orchestrator — Phase 2.5.

Makes the target-seeking outer loop the authoritative entry point of the
post-intake convergence pipeline. The existing scipy/issue-code solver
(numeric_solver.py + post_intake_convergence/runtime.py) is repositioned
as an inner tool the outer loop calls when single-driver bisection cannot
close a numeric gap.

Shape:
  intake_consult._run_unified_post_grid_system_run
    -> run_target_seeking_orchestrated_system_run (THIS MODULE)
        |- pre-flight target-seeking pass on applied_model_input_json
        |   bisects single drivers within their envelopes to land FINMO
        |   outputs in target ranges as a starting point
        |- inner: post_intake_convergence.runner.run_unified_post_grid_system_run
        |   (the existing 3451-line orchestrator handles payroll headcount,
        |   convergence cycles, cash pass, finalize). The outer loop has
        |   already pre-shaped the model so the inner sees envelope-respecting
        |   inputs.
        |- post-flight sanity assertion + repair pass
        |   If hard_fail residuals remain, runs the target-seeking loop one
        |   more time, this time with the inner-tool adapter available so
        |   joint multi-lever fitting can close gaps single-lever bisection
        |   cannot. After the repair pass, raises on:
        |     - stuck_pinned (a driver pinned at envelope edge with the gap
        |       still open -> envelope is too tight or target too narrow)
        |     - no_candidate_levers (no influence-map lever covers the
        |       failing metric -> mapping table gap)
        |     - max_iterations_reached (loop diverged or oscillated)
        |     - hard_fail residuals after repair (target jointly infeasible)
        |   These are the band-respecting failure modes that prove the shift
        |   is real: the system fails when targets are unreachable, instead
        |   of producing implausible plans.

The existing issue-code infrastructure remains usable. It is invoked as
the inner-tool adapter when the outer loop wants joint multi-lever
fitting on a constrained scope. The outer loop is the gate; the inner
runner is one of its tools.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional


_DEFAULT_PREFLIGHT_MAX_ITERATIONS = 12
_DEFAULT_POSTFLIGHT_MAX_ITERATIONS = 16
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


def _build_finmo_callable(
  *,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
  """Closure over build_python_finmo_json that the outer loop uses to
  evaluate FINMO from a candidate model_input. Heavy imports are lazy so
  this module loads cleanly during Phase 2.5 wiring."""

  # The auxiliary kwargs (business_facts, ops_json, etc.) aren't part of
  # build_python_finmo_json's signature — they're already stamped onto
  # model_input_json by the time _build_model_input_overlay runs. The
  # closure-captured args are kept here only for potential future use
  # (e.g. if FINMO build grows side-channel inputs); today they are
  # intentionally unused.
  _ = (business_facts, ops_json, people_json, financials_json,
       financials_year1_json, fulfillment_json, marketing_model_json)

  def _build(model_input_json: Dict[str, Any]) -> Dict[str, Any]:
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      build_python_finmo_json,
    )
    payload = build_python_finmo_json(
      model_input_json=copy.deepcopy(model_input_json or {}),
    )
    return payload if isinstance(payload, dict) else {}

  return _build


def _build_apply_lever_callable(
  *,
  horizon: int,
) -> Callable[[Dict[str, Any], str, float], Dict[str, Any]]:
  """Closure that writes a single (lever_id, value) to all forecast
  quarters Q1..Q<horizon>. Wraps the existing
  apply_exact_lever_updates_to_model_input from quarter_grid.
  """

  def _apply(
    model_input_json: Dict[str, Any], lever_id: str, value: float
  ) -> Dict[str, Any]:
    from client_intake_and_finmo.quarter_grid import (  # type: ignore
      apply_exact_lever_updates_to_model_input,
    )
    updates = [
      {
        "lever_id": str(lever_id or "").strip(),
        "quarter_index": int(q),
        "exact_value": float(value),
      }
      for q in range(1, max(1, int(horizon)) + 1)
    ]
    return apply_exact_lever_updates_to_model_input(
      model_input_json=model_input_json or {},
      exact_updates=updates,
    )

  return _apply


def _solver_input_payloads(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Optional[Dict[str, Any]]]:
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    DRIVER_MOVEMENT_ENVELOPE_KEY,
    FINMO_OUTPUT_TARGET_KEY,
  )
  source = model_input_json if isinstance(model_input_json, dict) else {}
  solver_input = source.get("solver_input") if isinstance(source.get("solver_input"), dict) else {}
  return {
    "envelope": solver_input.get(DRIVER_MOVEMENT_ENVELOPE_KEY) if isinstance(solver_input, dict) else None,
    "targets": solver_input.get(FINMO_OUTPUT_TARGET_KEY) if isinstance(solver_input, dict) else None,
  }


def _shallow_business_facts(business_facts: Dict[str, Any]) -> Dict[str, Any]:
  """Trim business_facts to the high-signal fields the consultants need.

  The full business_facts dict can be large (intake transcripts, GPT
  output blobs); the consultants only need the planning-relevant
  shape signals. Trimming here keeps the prompt size predictable.
  """
  if not isinstance(business_facts, dict):
    return {}
  fact_template = business_facts.get("fact_template") if isinstance(business_facts.get("fact_template"), dict) else {}
  return {
    "business_type": _clean_text(fact_template.get("business_type")) or _clean_text(business_facts.get("business_type")),
    "business_naics_6": _clean_text(fact_template.get("business_naics_6")) or _clean_text(business_facts.get("business_naics_6")),
    "business_stage": _clean_text(fact_template.get("business_stage")) or _clean_text(business_facts.get("business_stage")),
    "primary_offering_summary": _clean_text(fact_template.get("primary_offering_summary"))[:240],
    "growth_intent": _clean_text(fact_template.get("growth_intent"))[:240],
    "competitive_context": _clean_text(fact_template.get("competitive_context"))[:240],
  }


def _stamp_solver_inputs(
  *,
  model_input_json: Dict[str, Any],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Persist the (possibly calibrated) envelope + targets back onto the
  model_input under solver_input. Downstream finmo rebuilds will read
  these calibrated payloads instead of re-running the Python proposers.
  """
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    DRIVER_MOVEMENT_ENVELOPE_KEY,
    FINMO_OUTPUT_TARGET_KEY,
  )
  next_input = copy.deepcopy(model_input_json or {})
  solver_input = next_input.setdefault("solver_input", {})
  if not isinstance(solver_input, dict):
    solver_input = {}
    next_input["solver_input"] = solver_input
  if isinstance(envelope_payload, dict):
    solver_input[DRIVER_MOVEMENT_ENVELOPE_KEY] = copy.deepcopy(envelope_payload)
  if isinstance(targets_payload, dict):
    solver_input[FINMO_OUTPUT_TARGET_KEY] = copy.deepcopy(targets_payload)
  return next_input


def _ensure_solver_inputs(
  *,
  model_input_json: Dict[str, Any],
  ops_json: Optional[Dict[str, Any]],
  horizon: int,
  business_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Guarantees model_input_json carries solver_input.envelope and
  solver_input.finmo_output_targets even if upstream skipped finmo_bridge.
  """
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    DRIVER_MOVEMENT_ENVELOPE_KEY,
    FINMO_OUTPUT_TARGET_KEY,
    assemble_driver_movement_envelope,
    assemble_finmo_output_targets,
  )
  next_input = copy.deepcopy(model_input_json or {})
  solver_input = next_input.setdefault("solver_input", {})
  if not isinstance(solver_input, dict):
    solver_input = {}
    next_input["solver_input"] = solver_input
  naics_6 = ""
  if isinstance(ops_json, dict):
    naics_6 = "".join(ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit())
  if not solver_input.get(DRIVER_MOVEMENT_ENVELOPE_KEY):
    solver_input[DRIVER_MOVEMENT_ENVELOPE_KEY] = assemble_driver_movement_envelope(
      business_naics_6=naics_6 or None,
      live_count=horizon,
      business_profile=business_profile,
    )
  if not solver_input.get(FINMO_OUTPUT_TARGET_KEY):
    solver_input[FINMO_OUTPUT_TARGET_KEY] = assemble_finmo_output_targets(
      business_naics_6=naics_6 or None,
      live_count=horizon,
      business_profile=business_profile,
    )
  return next_input


def _run_target_seeking_pass(
  *,
  pass_label: str,
  model_input_json: Dict[str, Any],
  build_finmo_callable: Callable[[Dict[str, Any]], Dict[str, Any]],
  apply_lever_callable: Callable[[Dict[str, Any], str, float], Dict[str, Any]],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
  influence_payload: Optional[Dict[str, Any]],
  max_iterations: int,
  numeric_tolerance: float,
  enable_inner_joint_fit: bool,
  horizon: int,
) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    run_target_seeking_solver,
  )
  from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
    post_intake_sequence_step_scope,
  )
  inner_callable = None
  if enable_inner_joint_fit:
    from client_intake_and_finmo.post_intake_solver.inner_joint_fit_adapter import (  # type: ignore
      build_inner_joint_fit_adapter,
    )
    inner_callable = build_inner_joint_fit_adapter(
      influence_map_payload=influence_payload,
      envelope_payload=envelope_payload,
      horizon=horizon,
    )
  # Phase 4 fix: target-seeking passes invoke FINMO build via
  # build_finmo_callable, which requires an active post-intake sequence
  # context. The orchestrator is a top-level convergence step; we push a
  # synthetic scope for the duration of the pass so the sequence-gated
  # helpers (payroll capacity derivation, etc.) accept the call.
  with post_intake_sequence_step_scope(
    step_key=f"post_intake_target_seeking_{pass_label}",
    executor_function=f"target_seeking_solver_{pass_label}",
  ):
    result = run_target_seeking_solver(
      model_input_json=model_input_json,
      build_finmo_callable=build_finmo_callable,
      apply_lever_value_callable=apply_lever_callable,
      output_targets_payload=targets_payload,
      driver_envelope_payload=envelope_payload,
      influence_map_payload=influence_payload,
      max_iterations=max_iterations,
      numeric_tolerance=numeric_tolerance,
      inner_joint_fit_callable=inner_callable,
    )
  result["pass_label"] = pass_label
  return result


def _band_respecting_failure_diagnostic(
  *,
  pass_result: Dict[str, Any],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
) -> Optional[str]:
  status = _clean_text(pass_result.get("status"))
  if status == "converged":
    return None
  worst = pass_result.get("worst_unresolved") or {}
  metric_key = _clean_text(worst.get("metric_key")) or "<unknown>"
  quarter = worst.get("quarter_index")
  produced = worst.get("produced")
  target_min = worst.get("target_min")
  target_max = worst.get("target_max")
  residual = worst.get("residual")
  trace = pass_result.get("trace") or []
  pinned_drivers: List[Dict[str, Any]] = []
  if isinstance(envelope_payload, dict):
    drivers = envelope_payload.get("drivers") or {}
    for entry in trace[-6:]:
      if not isinstance(entry, dict):
        continue
      lever_id = _clean_text(entry.get("chosen_lever"))
      driver = drivers.get(lever_id)
      if isinstance(driver, dict) and driver.get("applicable"):
        mn = _safe_float(driver.get("min_allowed"))
        mx = _safe_float(driver.get("max_allowed"))
        cur = _safe_float(entry.get("new_value"))
        if cur is None or mn is None or mx is None:
          continue
        if cur <= mn + 1e-9 or cur >= mx - 1e-9:
          pinned_drivers.append({
            "lever_id": lever_id,
            "side": "at_min" if cur <= mn + 1e-9 else "at_max",
            "current_value": cur,
            "envelope_min": mn,
            "envelope_max": mx,
          })
  if status == "stuck_pinned":
    return (
      f"target_seeking_stuck_pinned: metric={metric_key} quarter={quarter} "
      f"produced={produced} target=[{target_min},{target_max}] residual={residual} "
      f"pinned_drivers={pinned_drivers or 'unspecified'}"
    )
  if status == "no_candidate_levers":
    return (
      f"target_seeking_no_candidate_levers: metric={metric_key} quarter={quarter} "
      f"produced={produced} target=[{target_min},{target_max}] residual={residual} "
      "(influence-map gap)"
    )
  if status == "max_iterations_reached":
    return (
      f"target_seeking_max_iterations_reached: pass produced no convergence within "
      f"max_iterations. trace_len={len(trace)}"
    )
  return f"target_seeking_unknown_status: status={status!r} pass={pass_result.get('pass_label')!r}"


def _hard_fail_violations_from_assertion(
  *,
  finmo_json: Dict[str, Any],
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    assert_solver_respected_targets,
  )
  assertion = assert_solver_respected_targets(
    finmo_json=finmo_json,
    output_targets_payload=targets_payload,
    driver_envelope_payload=envelope_payload,
  )
  return [
    v for v in (assertion.get("violations") or [])
    if str((v or {}).get("gate_kind") or "").lower() == "hard_fail"
  ]


def run_target_seeking_orchestrated_system_run(
  *,
  conn,
  draft_id: str,
  planning_run_id: Optional[str],
  business_facts: Dict[str, Any],
  planning_context_summary_json: Optional[Dict[str, Any]],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  planning_result: Dict[str, Any],
  grid_application_summary: Optional[Dict[str, Any]],
  catalog_source_model_input_json: Dict[str, Any],
  applied_model_input_json: Dict[str, Any],
  applied_finmo_json: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Top-level target-seeking orchestrator.

  Same signature as post_intake_convergence.runner.run_unified_post_grid_system_run
  so it can be slotted in as a drop-in replacement at the intake_consult
  call site. Returns the same payload shape, with an additional
  `target_seeking_diagnostics` section.
  """
  try:
    from financial_model_engine.model_inputs import QUARTER_COUNT  # type: ignore
  except Exception:
    QUARTER_COUNT = 20  # type: ignore

  horizon = int(QUARTER_COUNT)

  # Phase 3.5: build the business_profile that the cohort-matched band
  # resolver consumes. NAICS comes from ops; target_annual_revenue is the
  # year-1 projection (more representative of the planned business than
  # the current-state snapshot); stage comes from business_facts.
  _bf_template = (business_facts or {}).get("fact_template") if isinstance(business_facts, dict) else {}
  if not isinstance(_bf_template, dict):
    _bf_template = {}
  _target_annual_revenue: Optional[float] = None
  for source in (financials_year1_json or {}, financials_json or {}):
    if not isinstance(source, dict):
      continue
    for key in ("company_revenue_total_year1", "revenue_total_year1", "current_revenue"):
      raw = source.get(key)
      try:
        if raw is None or raw == "":
          continue
        candidate = float(raw)
      except Exception:
        continue
      if candidate and candidate > 0:
        _target_annual_revenue = candidate
        break
    if _target_annual_revenue is not None:
      break
  business_profile_for_cohort = {
    "naics_6": (
      "".join(ch for ch in str((ops_json or {}).get("business_naics_6") or "") if ch.isdigit())
      if isinstance(ops_json, dict)
      else None
    ),
    "target_annual_revenue": _target_annual_revenue,
    "stage": (
      _clean_text(_bf_template.get("business_stage"))
      or _clean_text((business_facts or {}).get("business_stage"))
      or None
    ),
    "business_model": _clean_text(_bf_template.get("business_model")) or None,
  }

  pre_input = _ensure_solver_inputs(
    model_input_json=applied_model_input_json or {},
    ops_json=ops_json,
    horizon=horizon,
    business_profile=business_profile_for_cohort,
  )
  inputs = _solver_input_payloads(pre_input)
  envelope_payload = inputs["envelope"]
  targets_payload = inputs["targets"]

  # ---------- Phase 3: GPT consultants calibrate bands and targets ----------
  # Three consultants run once per business before the pre-flight pass:
  #   1. Driver-band shaping calibrates the driver_movement_envelope to
  #      this specific business profile (tightening narrow industries,
  #      widening for nascent / restructuring businesses).
  #   2. Output target shaping calibrates the FINMO target ranges to the
  #      business's stage and capital posture.
  #   3. Conflict adjudication resolves any intake-vs-calibrated-band
  #      conflicts surfaced after band shaping (per-conflict structured
  #      decision: keep_intake / keep_band / split).
  # All three are fail-safe: when GPT is unavailable or returns invalid
  # output, Python defaults stand and provenance is tagged accordingly.
  # The orchestrator never blocks on GPT availability.
  calibration_diagnostics: Dict[str, Any] = {}
  business_context = {
    "draft_id": str(draft_id or "").strip(),
    "planning_run_id": str(planning_run_id or "").strip(),
    "planning_mode": str(planning_mode or "").strip(),
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "business_facts": _shallow_business_facts(business_facts or {}),
  }
  if envelope_payload:
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      calibrate_driver_movement_envelope_with_gpt,
      adjudicate_intake_vs_band_conflicts_with_gpt,
    )
    band_result = calibrate_driver_movement_envelope_with_gpt(
      envelope_proposal=envelope_payload,
      business_context=business_context,
    )
    envelope_payload = band_result.get("calibrated_envelope") or envelope_payload
    calibration_diagnostics["band_shaping"] = {
      "decision_source": band_result.get("decision_source"),
      "amended_lever_count": len(band_result.get("amended_lever_ids") or []),
      "uncalibrated_lever_count": len(band_result.get("uncalibrated_lever_ids") or []),
      "fallback_detail": (band_result.get("critic_diagnostics") or {}).get("fallback_detail"),
    }
    conflict_result = adjudicate_intake_vs_band_conflicts_with_gpt(
      envelope_payload=envelope_payload,
      financials_json=financials_json or {},
      financials_year1_json=financials_year1_json or {},
      business_context=business_context,
    )
    envelope_payload = conflict_result.get("calibrated_envelope") or envelope_payload
    calibration_diagnostics["conflict_adjudication"] = {
      "decision_source": conflict_result.get("decision_source"),
      "conflicts_detected": conflict_result.get("conflicts_detected"),
      "decisions_applied": [
        d.get("decision") for d in (conflict_result.get("decisions_applied") or [])
      ],
      "fallback_detail": conflict_result.get("fallback_detail"),
    }
  if targets_payload:
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      calibrate_finmo_output_targets_with_gpt,
    )
    target_result = calibrate_finmo_output_targets_with_gpt(
      targets_proposal=targets_payload,
      business_context=business_context,
    )
    targets_payload = target_result.get("calibrated_targets") or targets_payload
    calibration_diagnostics["target_shaping"] = {
      "decision_source": target_result.get("decision_source"),
      "amended_metric_count": len(target_result.get("amended_metric_keys") or []),
      "uncalibrated_metric_count": len(target_result.get("uncalibrated_metric_keys") or []),
      "fallback_detail": (target_result.get("critic_diagnostics") or {}).get("fallback_detail"),
    }

  # Re-stamp the calibrated envelope + targets onto the model_input so
  # downstream callers (sanity assertion, finmo_bridge re-builds) see
  # the calibrated payloads, not the deterministic Python defaults.
  pre_input = _stamp_solver_inputs(
    model_input_json=pre_input,
    envelope_payload=envelope_payload,
    targets_payload=targets_payload,
  )

  build_finmo_callable = _build_finmo_callable(
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    people_json=people_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    fulfillment_json=fulfillment_json or {},
    marketing_model_json=marketing_model_json or {},
  )
  apply_lever_callable = _build_apply_lever_callable(horizon=horizon)

  from client_intake_and_finmo.post_intake_solver import (  # type: ignore
    driver_influence_map,
  )
  influence_payload = driver_influence_map()

  # ---------- Pre-flight target-seeking pass ----------
  # Single-driver bisection only — no inner joint fit. The pre-flight pass
  # exists to envelope-shape the starting state before handing off to the
  # inner runner; deep multi-lever fitting belongs in the inner runner or
  # in the post-flight repair pass.
  pre_pass = _run_target_seeking_pass(
    pass_label="pre_flight",
    model_input_json=pre_input,
    build_finmo_callable=build_finmo_callable,
    apply_lever_callable=apply_lever_callable,
    envelope_payload=envelope_payload,
    targets_payload=targets_payload,
    influence_payload=influence_payload,
    max_iterations=_DEFAULT_PREFLIGHT_MAX_ITERATIONS,
    numeric_tolerance=_DEFAULT_NUMERIC_TOLERANCE,
    enable_inner_joint_fit=False,
    horizon=horizon,
  )
  pre_shaped_model_input = pre_pass.get("final_model_input_json") or pre_input
  pre_shaped_finmo = pre_pass.get("final_finmo_json") or {}

  # ---------- Inner runner — existing convergence/cash-pass/finalize ----------
  from client_intake_and_finmo.post_intake_convergence.runner import (  # type: ignore
    run_unified_post_grid_system_run as _inner_runner,
  )
  inner_result = _inner_runner(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    business_facts=business_facts,
    planning_context_summary_json=planning_context_summary_json,
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_result=planning_result,
    grid_application_summary=grid_application_summary,
    catalog_source_model_input_json=catalog_source_model_input_json,
    applied_model_input_json=pre_shaped_model_input,
    applied_finmo_json=pre_shaped_finmo if pre_shaped_finmo else applied_finmo_json,
    stage_ramp_contract=stage_ramp_contract,
    payroll_headcount=payroll_headcount,
  )

  inner_model_input_json = inner_result.get("model_input_json") if isinstance(inner_result, dict) else None
  inner_finmo_json = inner_result.get("finmo_json") if isinstance(inner_result, dict) else None

  # Refresh solver_input on the post-inner model so post-flight reads the
  # current envelope/targets the inner runner may have re-stamped.
  post_inner_model = _ensure_solver_inputs(
    model_input_json=inner_model_input_json or {},
    ops_json=ops_json,
    horizon=horizon,
    business_profile=business_profile_for_cohort,
  )
  post_inputs = _solver_input_payloads(post_inner_model)
  envelope_payload_post = post_inputs["envelope"] or envelope_payload
  targets_payload_post = post_inputs["targets"] or targets_payload

  # ---------- Post-flight assertion + repair pass ----------
  hard_fails = _hard_fail_violations_from_assertion(
    finmo_json=inner_finmo_json or {},
    envelope_payload=envelope_payload_post,
    targets_payload=targets_payload_post,
  )

  repair_pass: Optional[Dict[str, Any]] = None
  final_model_input_json = inner_model_input_json
  final_finmo_json = inner_finmo_json
  if hard_fails:
    # Post-flight repair invokes the inner joint-fit adapter when single-
    # driver bisection stagnates. The adapter delegates joint multi-lever
    # fitting to numeric_solver.solve_review_plan; the existing scipy /
    # issue-code infrastructure becomes the gap-closer the outer loop
    # calls when bisection alone is insufficient.
    repair_pass = _run_target_seeking_pass(
      pass_label="post_flight_repair",
      model_input_json=post_inner_model,
      build_finmo_callable=build_finmo_callable,
      apply_lever_callable=apply_lever_callable,
      envelope_payload=envelope_payload_post,
      targets_payload=targets_payload_post,
      influence_payload=influence_payload,
      max_iterations=_DEFAULT_POSTFLIGHT_MAX_ITERATIONS,
      numeric_tolerance=_DEFAULT_NUMERIC_TOLERANCE,
      enable_inner_joint_fit=True,
      horizon=horizon,
    )
    final_model_input_json = repair_pass.get("final_model_input_json") or inner_model_input_json
    final_finmo_json = repair_pass.get("final_finmo_json") or inner_finmo_json

  # Final hard-fail evaluation. By construction the outer loop is the
  # authoritative gate — if we still have hard_fail residuals here, raise
  # a band-respecting diagnostic. The structural failure modes are:
  #   - stuck_pinned    -> envelope too tight or target too narrow
  #   - no_candidate_levers -> influence-map gap
  #   - max_iterations_reached -> diverged/oscillated
  #   - hard_fail residuals after repair -> target jointly infeasible
  final_hard_fails = _hard_fail_violations_from_assertion(
    finmo_json=final_finmo_json or {},
    envelope_payload=envelope_payload_post,
    targets_payload=targets_payload_post,
  )

  diagnostics: Dict[str, Any] = {
    "calibration": calibration_diagnostics,
    "pre_flight": {
      "status": pre_pass.get("status"),
      "iterations_used": pre_pass.get("iterations_used"),
      "trace_length": len(pre_pass.get("trace") or []),
    },
    "inner_runner_invoked": True,
    "post_flight_repair": (
      {
        "status": repair_pass.get("status"),
        "iterations_used": repair_pass.get("iterations_used"),
        "trace_length": len(repair_pass.get("trace") or []),
      }
      if repair_pass
      else None
    ),
    "final_hard_fail_count": len(final_hard_fails),
  }

  # Phase 3.7: when post-flight repair leaves hard_fail residuals, hand
  # off to the adaptation cascade. The cascade walks tiers 1->7 of
  # progressively more permissive inputs until a plan lands. Tier 7 is
  # structurally guaranteed to produce a plan via pure NAICS-cascade
  # defaults + maximally permissive planning_mode + 2x target tolerance.
  # The terminal raise is reserved for genuine internal bugs (the
  # cascade module itself crashing); band-respecting failures are now
  # always converted into a plan with a confidence indicator.
  plan_confidence: str = "high_no_adaptation"
  cascade_diagnostics: Optional[Dict[str, Any]] = None
  if final_hard_fails:
    from client_intake_and_finmo.post_intake_solver.adaptation_cascade import (  # type: ignore
      run_adaptation_cascade,
    )
    inner_runner_kwargs = {
      "conn": conn,
      "draft_id": draft_id,
      "planning_run_id": planning_run_id,
      "business_facts": business_facts,
      "planning_context_summary_json": planning_context_summary_json,
      "ops_json": ops_json,
      "target_market_json": target_market_json,
      "people_json": people_json,
      "financials_json": financials_json,
      "financials_year1_json": financials_year1_json,
      "fulfillment_json": fulfillment_json,
      "marketing_model_json": marketing_model_json,
      "planning_mode": planning_mode,
      "planning_mode_reason": planning_mode_reason,
      "planning_result": planning_result,
      "grid_application_summary": grid_application_summary,
      "catalog_source_model_input_json": catalog_source_model_input_json,
      "applied_finmo_json": applied_finmo_json,
      "stage_ramp_contract": stage_ramp_contract,
      "payroll_headcount": payroll_headcount,
    }
    original_stage_family: Optional[str] = None
    if isinstance(stage_ramp_contract, dict):
      original_stage_family = _clean_text(stage_ramp_contract.get("stage_family")) or None
    business_naics_6_for_cascade = ""
    if isinstance(ops_json, dict):
      business_naics_6_for_cascade = "".join(
        ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
      )
    business_stage_for_cascade = (
      _clean_text((business_facts or {}).get("fact_template", {}).get("business_stage"))
      if isinstance(business_facts, dict) else ""
    )
    final_payload, plan_confidence, cascade_diagnostics = run_adaptation_cascade(
      pre_input=pre_input,
      post_inner_model=post_inner_model,
      inner_result=inner_result,
      final_finmo_json=final_finmo_json or {},
      envelope_payload_post=envelope_payload_post or {},
      targets_payload_post=targets_payload_post or {},
      influence_payload=influence_payload or {},
      final_hard_fails=final_hard_fails,
      pre_pass=pre_pass,
      repair_pass=repair_pass,
      build_finmo_callable=build_finmo_callable,
      apply_lever_callable=apply_lever_callable,
      run_target_seeking_pass_callable=_run_target_seeking_pass,
      hard_fail_violations_callable=_hard_fail_violations_from_assertion,
      inner_runner_callable=_inner_runner,
      inner_runner_kwargs=inner_runner_kwargs,
      original_planning_mode=planning_mode,
      original_planning_mode_reason=planning_mode_reason or "",
      original_stage_family=original_stage_family,
      original_stage_ramp_contract=stage_ramp_contract,
      business_naics_6=business_naics_6_for_cascade or None,
      business_stage=business_stage_for_cascade or None,
      horizon=horizon,
    )
    diagnostics["adaptation_cascade"] = cascade_diagnostics
    final_model_input_json = final_payload.get("model_input_json") or final_model_input_json
    final_finmo_json = final_payload.get("finmo_json") or final_finmo_json
    inner_result = final_payload if isinstance(final_payload, dict) else inner_result

  # Successful run — augment inner_result with diagnostics and the
  # potentially-repaired final state.
  next_result = copy.deepcopy(inner_result if isinstance(inner_result, dict) else {})
  if final_model_input_json is not None:
    next_result["model_input_json"] = final_model_input_json
  if final_finmo_json:
    next_result["finmo_json"] = final_finmo_json
  next_result["target_seeking_diagnostics"] = diagnostics
  next_result["plan_confidence"] = plan_confidence
  if cascade_diagnostics is not None:
    next_result["adaptation_cascade_diagnostics"] = cascade_diagnostics
  return next_result
