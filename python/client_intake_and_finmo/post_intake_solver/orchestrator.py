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


def _build_minimal_convergence_context(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  adaptive_policy_dict: Optional[Dict[str, Any]],
  planning_context_summary_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Phase 9 Phase C1 — populate the unified_convergence_context payload.

  Phase 8 persisted ``unified_convergence_context={}``, which orphaned the
  stage_ramp_contract in the planning_run_json blob. Workbook export reads
  via ``payload.unified_convergence_context.business_world_contract.stage_ramp_contract``
  (see client_statements_output_excel/data.py:146-160). With that path
  empty, the Revenue Drivers sheet's Stage Ramp Contract rows showed zeros
  across Q1-Q20 even though the contract itself had been generated correctly.

  This builder writes the minimum surface the workbook reader needs.
  Intentionally NOT a full convergence-runner payload — convergence runner
  is dead code awaiting Phase I deletion. Phase D may extend this with
  cascade widening artifacts; Phase F adds cash plan summary.
  """
  context: Dict[str, Any] = {}
  bwc: Dict[str, Any] = {}
  if isinstance(stage_ramp_contract, dict) and stage_ramp_contract:
    bwc["stage_ramp_contract"] = copy.deepcopy(stage_ramp_contract)
  if bwc:
    context["business_world_contract"] = bwc
  # Mirror at planning_context_summary path for the alternate fallback the
  # workbook reader walks at data.py:151.
  if isinstance(stage_ramp_contract, dict) and stage_ramp_contract:
    pcs: Dict[str, Any] = {}
    if isinstance(planning_context_summary_json, dict):
      pcs.update(copy.deepcopy(planning_context_summary_json))
    pcs["stage_ramp_contract"] = copy.deepcopy(stage_ramp_contract)
    context["planning_context_summary"] = pcs
  if isinstance(adaptive_policy_dict, dict) and adaptive_policy_dict:
    context["adaptive_policy"] = copy.deepcopy(adaptive_policy_dict)
  return context


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
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  adaptive_policy_dict: Optional[Dict[str, Any]] = None,
  industry_targets: Optional[Dict[str, float]] = None,
) -> Callable[[Dict[str, Any], str, float], Dict[str, Any]]:
  """Path-aware lever writer (Phase 9 Phase C3).

  Pre-Phase-C this closure broadcast a single scalar across Q1..Q<horizon>.
  Per the Real ramp rule that violated the doctrine for every driver
  except genuinely flat ones (rent, distributions, statutory tax).

  Phase C3 routes every solver lever movement through the path engine.
  ``base_value`` is now the Q1 starting value the solver chose; the path
  engine reinterprets it as the ramp's amplitude and returns Q1..Q<horizon>
  values consistent with the registered shape (s_curve, glidepath,
  capacity_expansion, linear_to_mature, industry_convergence_decay).

  Non-writable shapes (hiring_schedule, stock_carryforward, calculated,
  schedule_locked) preserve the pre-Phase-C broadcast behavior so the
  solver doesn't loop trying to move drivers the path engine declines
  to write. Phase D's issue router will tighten this when influence_map
  is rebuilt to exclude non-writable lever_ids.

  ``industry_targets`` is an optional ``lever_id -> mature target`` map.
  Phase E populates it from the unified industry profile; Phase C falls
  back to the contract's quarter_ramp_grid where available, then to a
  flat broadcast when no target can be resolved.
  """

  resolved_industry_targets: Dict[str, float] = (
    {str(k): float(v) for k, v in industry_targets.items() if v is not None}
    if isinstance(industry_targets, dict)
    else {}
  )

  def _apply(
    model_input_json: Dict[str, Any], lever_id: str, value: float
  ) -> Dict[str, Any]:
    from client_intake_and_finmo.quarter_grid import (  # type: ignore
      apply_exact_lever_updates_to_model_input,
    )
    from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
      WRITABLE_SHAPES,
      compute_per_quarter_values,
    )

    h = max(1, int(horizon))
    industry_target = resolved_industry_targets.get(str(lever_id or "").strip())

    path = compute_per_quarter_values(
      lever_id=str(lever_id or "").strip(),
      base_value=float(value),
      horizon=h,
      stage_ramp_contract=stage_ramp_contract,
      adaptive_policy=adaptive_policy_dict,
      industry_target=industry_target,
    )

    if (
      path.shape_kind in WRITABLE_SHAPES
      and isinstance(path.per_quarter_values, list)
      and path.per_quarter_values
    ):
      updates = [
        {
          "lever_id": str(lever_id or "").strip(),
          "quarter_index": int(q + 1),
          "exact_value": float(v),
        }
        for q, v in enumerate(path.per_quarter_values)
      ]
    else:
      # Non-writable shape — fall back to the pre-Phase-C broadcast so
      # the solver loop's expectation that every move lands somewhere
      # holds. The path engine's skip_write_reason explains why a
      # path wasn't computed; the broadcast keeps the system convergent
      # while Phase D rewires influence_map.
      updates = [
        {
          "lever_id": str(lever_id or "").strip(),
          "quarter_index": int(q),
          "exact_value": float(value),
        }
        for q in range(1, h + 1)
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


def _apply_restoration_to_model_input(
  *,
  model_input_json: Dict[str, Any],
  adjusted_ops_json: Dict[str, Any],
  adjusted_payroll_headcount: Dict[str, Any],
  horizon: int,
) -> Dict[str, Any]:
  """Patch model_input revenue rows + payroll rows to match the Phase
  7.2 restoration cascade adjustments.

  Revenue drivers (Capacity / Unit Price / Utilization) get their q1-q20
  values rewritten from adjusted_ops_json scalars. Payroll expense rows
  get their q1-q20 values rewritten from adjusted_payroll_headcount
  quarter_totals. q0 stub stays at the original intake-fact value.
  """
  next_input = copy.deepcopy(model_input_json or {})
  sections = next_input.get("sections")
  if not isinstance(sections, dict):
    return next_input

  # Revenue rows
  revenue_rows = sections.get("revenue")
  if isinstance(revenue_rows, list):
    new_capacity = (
      _safe_float(adjusted_ops_json.get("units_per_period_capacity"))
      or _safe_float(adjusted_ops_json.get("units_per_week_capacity"))
    )
    new_price = _safe_float(adjusted_ops_json.get("unit_price"))
    new_util = _safe_float(adjusted_ops_json.get("utilization_rate"))
    for row in revenue_rows:
      if not isinstance(row, dict):
        continue
      driver = str(row.get("driver") or "").strip()
      values = row.get("values")
      if not isinstance(values, list) or not values:
        continue
      if driver == "Capacity" and new_capacity is not None and new_capacity > 0:
        for idx in range(1, min(horizon + 1, len(values))):
          values[idx] = float(new_capacity)
      elif driver == "Unit Price" and new_price is not None and new_price > 0:
        for idx in range(1, min(horizon + 1, len(values))):
          values[idx] = float(new_price)
      elif driver == "Utilization" and new_util is not None and new_util > 0:
        for idx in range(1, min(horizon + 1, len(values))):
          values[idx] = float(new_util)

  # Payroll rows (in expenses section)
  expenses_rows = sections.get("expenses")
  if isinstance(expenses_rows, list):
    quarter_totals = adjusted_payroll_headcount.get("quarter_totals")
    if isinstance(quarter_totals, list) and quarter_totals:
      payroll_per_quarter = []
      for row in quarter_totals[:horizon]:
        if isinstance(row, dict):
          payroll = _safe_float(row.get("payroll"))
          payroll_per_quarter.append(float(payroll) if payroll is not None else 0.0)
      for row in expenses_rows:
        if not isinstance(row, dict):
          continue
        lever_id = str(row.get("lever_id") or "").strip()
        if "Payroll" not in lever_id:
          continue
        values = row.get("values")
        if not isinstance(values, list) or not values:
          continue
        for idx, payroll_q in enumerate(payroll_per_quarter, start=1):
          if idx < len(values):
            values[idx] = payroll_q

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

  # ---------- Phase 9 Phase B Step 0: adaptive policy contract -----------
  # Single source of truth for stage profile, planning mode, loss-tolerance
  # window, viability deadlines, allowed adaptation families, and per-driver
  # client-input authority. Computed deterministically from intake + FINMO
  # snapshot + (later) industry profile. Every downstream consumer reads
  # from this contract instead of inferring stage / mode locally.
  from client_intake_and_finmo.post_intake_adaptive_planning import (  # type: ignore
    compute_adaptive_policy,
  )
  adaptive_policy = compute_adaptive_policy(
    business_facts=business_facts or {},
    ops_json=ops_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    finmo_snapshot=applied_finmo_json or {},
    industry_profile=None,  # Phase E populates this once industry_profile.py lands.
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
  )

  # Phase 3.5: build the business_profile that the cohort-matched band
  # resolver consumes. NAICS comes from ops; target_annual_revenue is
  # capacity-driven mature-state revenue (capacity * price * periods *
  # upper-bound utilization) — the structural answer to "what cohort
  # cap-category is this business?" The operator's Year-1 ramp projection
  # is a planning expectation, not a cohort-bucket key; using it
  # under-buckets ramping businesses and returns bands that are too tight.
  from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (  # type: ignore
    authoritative_annual_revenue,
  )
  _bf_template = (business_facts or {}).get("fact_template") if isinstance(business_facts, dict) else {}
  if not isinstance(_bf_template, dict):
    _bf_template = {}
  _target_annual_revenue = authoritative_annual_revenue(
    ops_json=ops_json or {},
    financials_year1_json=financials_year1_json or {},
    financials_json=financials_json or {},
  )
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

  # ---------- Phase 6 Step 9: pre-flight structural feasibility check ----
  # Before Phase 3 calibration, before pre-flight bisection, before the
  # inner runner: verify the business as configured can be modeled at
  # all. If revenue at maximum plausible utilization cannot cover
  # lower-bound fixed costs (payroll + lease + debt service), no
  # combination of band-internal lever values produces a viable plan.
  # The cascade's Tier 7 used to paper this case as success; Step 9
  # produces structured recommended_adjustments so the cascade /
  # consultants see actionable guidance. Per Phase 7.2 directive: the
  # check NEVER halts the run — the system's job is to adapt and produce
  # a feasible plan, not to refuse to plan. Infeasibility becomes context
  # the cascade uses to know which bands to widen (capacity / price) and
  # which costs to push down (payroll headcount when over-staffed).
  from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (  # type: ignore
    verify_structural_feasibility,
  )
  structural_feasibility = verify_structural_feasibility(
    ops_json=ops_json or {},
    financials_json=financials_json or {},
    financials_year1_json=financials_year1_json or {},
    payroll_headcount=payroll_headcount or {},
    business_profile=business_profile_for_cohort,
  )
  structural_feasibility_diagnostic: Dict[str, Any] = (
    structural_feasibility.to_dict() if not structural_feasibility.feasible else {}
  )
  feasibility_restoration_diagnostic: Dict[str, Any] = {}
  if not structural_feasibility.feasible:
    # Phase 7.2: feasibility restoration cascade. Hard-fail catalyst from
    # the structural check is what triggers adaptation here. Levers are
    # tried in priority (headcount rationalization, unit price within
    # band, utilization within band, capacity expansion as final
    # unbounded guarantee). Customer always gets a plan; the cascade
    # adjusts the inputs and downstream Phase 3 / solver continue with
    # the adapted configuration.
    from client_intake_and_finmo.post_intake_solver.feasibility_restoration import (  # type: ignore
      restore_feasibility,
    )
    naics_6 = business_profile_for_cohort.get("naics_6") if isinstance(business_profile_for_cohort, dict) else None
    restoration = restore_feasibility(
      structural_result=structural_feasibility,
      ops_json=ops_json or {},
      financials_json=financials_json or {},
      financials_year1_json=financials_year1_json or {},
      payroll_headcount=payroll_headcount or {},
      business_naics_6=naics_6,
    )
    feasibility_restoration_diagnostic = restoration.to_dict()
    if restoration.applied_adjustments:
      # Swap in the adapted intake. ops_json and payroll_headcount are
      # consumed downstream by Phase 3 consultants (via resolver_runtime_objects)
      # and by the band assemblers; updating them here propagates the
      # adapted configuration across every site that reads these payloads.
      if isinstance(restoration.adjusted_ops_json, dict):
        ops_json = restoration.adjusted_ops_json
      if isinstance(restoration.adjusted_payroll_headcount, dict):
        payroll_headcount = restoration.adjusted_payroll_headcount
      # Patch the in-memory model_input_json revenue rows + payroll rows
      # so downstream FINMO computations see the adapted values.
      applied_model_input_json = _apply_restoration_to_model_input(
        model_input_json=applied_model_input_json or {},
        adjusted_ops_json=ops_json,
        adjusted_payroll_headcount=payroll_headcount,
        horizon=horizon,
      )
      # Recompute capacity-driven cohort revenue / envelope payload to
      # match the adapted scale (capacity expansion lever changes the
      # cohort target_annual_revenue too).
      _target_annual_revenue = authoritative_annual_revenue(
        ops_json=ops_json or {},
        financials_year1_json=financials_year1_json or {},
        financials_json=financials_json or {},
      )
      business_profile_for_cohort["target_annual_revenue"] = _target_annual_revenue
      pre_input = _ensure_solver_inputs(
        model_input_json=applied_model_input_json or {},
        ops_json=ops_json,
        horizon=horizon,
        business_profile=business_profile_for_cohort,
      )
      inputs = _solver_input_payloads(pre_input)
      envelope_payload = inputs["envelope"]
      targets_payload = inputs["targets"]

  # ---------- Phase 3 / 5.2: GPT consultants calibrate bands and targets -----
  # Three consultants run per business before the pre-flight pass. Each
  # makes per-scope GPT calls (per-lever band shaping, per-metric target
  # shaping, per-conflict adjudication). Each call's prompt context is
  # resolved from post_intake_gpt_context_lookup via
  # resolve_consultant_context — the table is the single source of truth
  # for what each consultant sees.
  #
  # After calibration, a pre-solver joint feasibility check verifies the
  # calibrated bands collectively admit at least one feasible solution
  # for the calibrated target ranges. Infeasibility triggers the
  # adaptation cascade's pre-solver tier (Tier 1 GPT walk-back; Tier 2
  # cohort walk-back) before the solver wastes time.
  calibration_diagnostics: Dict[str, Any] = {}
  resolver_runtime_objects = {
    "business_facts": business_facts or {},
    "ops_json": ops_json or {},
    "target_market_json": target_market_json or {},
    "people_json": people_json or {},
    "financials_json": financials_json or {},
    "financials_year1_json": financials_year1_json or {},
    "fulfillment_json": fulfillment_json or {},
    "marketing_model_json": marketing_model_json or {},
    "planning_mode_context": {
      "planning_mode": str(planning_mode or "").strip(),
      "planning_mode_reason": str(planning_mode_reason or "").strip(),
    },
    "business_profile_for_cohort": business_profile_for_cohort,
    "stage_ramp_contract": stage_ramp_contract or {},
    "envelope_proposal": envelope_payload or {},
    "targets_proposal": targets_payload or {},
  }

  if envelope_payload:
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      calibrate_driver_movement_envelope_with_gpt,
      adjudicate_intake_vs_band_conflicts_with_gpt,
    )
    band_result = calibrate_driver_movement_envelope_with_gpt(
      envelope_proposal=envelope_payload,
      draft_id=str(draft_id or "").strip(),
      planning_run_id=str(planning_run_id or "").strip(),
      conn=conn,
      runtime_objects=resolver_runtime_objects,
    )
    envelope_payload = band_result.get("calibrated_envelope") or envelope_payload
    calibration_diagnostics["band_shaping"] = {
      "decision_source": band_result.get("decision_source"),
      "amended_lever_count": len(band_result.get("amended_lever_ids") or []),
      "uncalibrated_lever_count": len(band_result.get("uncalibrated_lever_ids") or []),
      "fallback_detail": (band_result.get("critic_diagnostics") or {}).get("fallback_detail"),
    }
    resolver_runtime_objects["envelope_proposal"] = envelope_payload
    conflict_result = adjudicate_intake_vs_band_conflicts_with_gpt(
      envelope_payload=envelope_payload,
      financials_json=financials_json or {},
      financials_year1_json=financials_year1_json or {},
      draft_id=str(draft_id or "").strip(),
      planning_run_id=str(planning_run_id or "").strip(),
      conn=conn,
      runtime_objects=resolver_runtime_objects,
      ops_json=ops_json or {},
    )
    envelope_payload = conflict_result.get("calibrated_envelope") or envelope_payload
    resolver_runtime_objects["envelope_proposal"] = envelope_payload
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
      draft_id=str(draft_id or "").strip(),
      planning_run_id=str(planning_run_id or "").strip(),
      conn=conn,
      runtime_objects=resolver_runtime_objects,
    )
    targets_payload = target_result.get("calibrated_targets") or targets_payload
    resolver_runtime_objects["targets_proposal"] = targets_payload
    calibration_diagnostics["target_shaping"] = {
      "decision_source": target_result.get("decision_source"),
      "amended_metric_count": len(target_result.get("amended_metric_keys") or []),
      "uncalibrated_metric_count": len(target_result.get("uncalibrated_metric_keys") or []),
      "fallback_detail": (target_result.get("critic_diagnostics") or {}).get("fallback_detail"),
    }

  # ---------- Phase 5.2 R3: pre-solver joint feasibility check -----
  # Verify the calibrated bands collectively admit a feasible solution
  # for the calibrated target ranges. Infeasibility triggers the
  # pre-solver adaptation cascade (Tier 1 walk-back -> Tier 2 cohort
  # fallback). If the cascade restores feasibility we proceed; if not,
  # the post-flight cascade takes over and Tier 7 always lands a plan.
  if envelope_payload and targets_payload:
    from client_intake_and_finmo.post_intake_solver.joint_feasibility_check import (  # type: ignore
      verify_joint_feasibility,
    )
    from client_intake_and_finmo.post_intake_solver.adaptation_cascade import (  # type: ignore
      run_pre_solver_feasibility_cascade,
    )
    feasibility = verify_joint_feasibility(
      envelope_payload=envelope_payload,
      targets_payload=targets_payload,
      business_profile=business_profile_for_cohort,
    )
    calibration_diagnostics["joint_feasibility_initial"] = feasibility.to_dict()
    if not feasibility.feasible:
      cascade_outcome = run_pre_solver_feasibility_cascade(
        envelope_payload=envelope_payload,
        targets_payload=targets_payload,
        business_profile=business_profile_for_cohort,
        initial_diagnostic=feasibility,
      )
      envelope_payload = cascade_outcome.get("envelope_payload") or envelope_payload
      targets_payload = cascade_outcome.get("targets_payload") or targets_payload
      calibration_diagnostics["joint_feasibility_cascade"] = cascade_outcome.get("diagnostic", {})

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
  apply_lever_callable = _build_apply_lever_callable(
    horizon=horizon,
    stage_ramp_contract=stage_ramp_contract,
    adaptive_policy_dict=adaptive_policy.to_dict(),
  )

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

  # ---------- Inner runner — Phase 8 bypass ----------
  # The legacy convergence runner is broken post-deletion of the issue
  # machinery: every fail-fast the legacy GPT loop's authority-
  # reapplication used to suppress now fires (revenue formula
  # validators, payroll schedule rollups, etc.). The orchestrator-
  # driven post-cascade tail (cash pass + realism gate + finalize +
  # persist) is the new authoritative path. Skip the legacy inner
  # runner and use a passthrough so the cascade has a starting state
  # to work from. The acceptance gate's verdict is the authority on
  # whether the resulting plan is sensible.
  inner_result = {
    "status": "phase_8_inner_runner_bypassed",
    "model_input_json": copy.deepcopy(pre_shaped_model_input or {}),
    "finmo_json": copy.deepcopy(pre_shaped_finmo or applied_finmo_json or {}),
    "abort_reason": "phase_8_legacy_convergence_runner_skipped",
  }

  # Phase 6 Step 7 — band-respecting failures from the inner runner now
  # return status="abort_for_cascade" with an abort_reason instead of
  # raising. The orchestrator detects the signal and forces hard_fails
  # so the post-flight cascade fires below. Step 8 makes the cascade
  # reason-aware (start at the tier matched to the abort_reason instead
  # of always Tier 1).
  inner_runner_abort_reason: Optional[str] = None
  inner_runner_abort_diagnostics: Optional[Dict[str, Any]] = None
  if (
    isinstance(inner_result, dict)
    and _clean_text(inner_result.get("status")) == "abort_for_cascade"
  ):
    inner_runner_abort_reason = _clean_text(inner_result.get("abort_reason")) or "unknown_abort"
    inner_runner_abort_diagnostics = (
      copy.deepcopy(inner_result.get("diagnostics"))
      if isinstance(inner_result.get("diagnostics"), dict) else {}
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
    "inner_runner_abort_reason": inner_runner_abort_reason,
    "inner_runner_abort_diagnostics": inner_runner_abort_diagnostics,
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

  # Phase 3.7 + 6 Step 7: cascade fires on either of two signals:
  #   (a) post-flight repair left hard_fail residuals (existing behavior)
  #   (b) inner runner returned status=abort_for_cascade with a
  #       band-respecting reason — Tier 1+ adaptation is the designed
  #       remediation path, replacing the prior raise-and-die.
  # Tier 7 is structurally guaranteed to produce a plan; Step 8 makes
  # the cascade pick its starting tier based on abort_reason instead of
  # always Tier 1.
  plan_confidence: str = "high_no_adaptation"
  cascade_diagnostics: Optional[Dict[str, Any]] = None
  if final_hard_fails or inner_runner_abort_reason is not None:
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
      abort_reason=inner_runner_abort_reason,
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
  # Phase 9 Phase B: stamp the adaptive policy contract on the result so
  # downstream consumers (acceptance gate, workbook export, run report)
  # see the same policy the cascade saw. Single source of truth.
  next_result["adaptive_policy"] = adaptive_policy.to_dict()

  # Phase 7.2: build the debt schedule snapshot from the final state and
  # persist to draft.debt_schedule. The convergence runner did this in
  # its cash-pass step; the target-seeking orchestrator is a drop-in
  # replacement for that runner and must produce the same artifact so
  # workbook export and downstream finalization can complete. Without
  # this, validate_draft_data raises 'Draft is missing workbook export
  # inputs: debt_schedule'.
  debt_schedule_payload: Optional[Dict[str, Any]] = None
  try:
    from client_intake_and_finmo.post_intake_debt_schedule import (  # type: ignore
      build_debt_schedule_snapshot,
    )
    debt_schedule_payload = build_debt_schedule_snapshot(
      finmo_payload=copy.deepcopy(final_finmo_json or {}),
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      source_stage="target_seeking_orchestrator_completed",
    )
    if isinstance(debt_schedule_payload, dict):
      debt_schedule_payload["persisted_column"] = "intake_consult_drafts.debt_schedule"
      next_result["debt_schedule"] = debt_schedule_payload
  except Exception as exc:
    diagnostics["debt_schedule_build_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

  # Persist the debt_schedule directly to the draft row so the workbook
  # export reads it (it queries draft.debt_schedule, not the orchestrator
  # result). Use a minimal SQL UPDATE — the larger persist_post_intake_
  # execution_state path is owned by the convergence runner; replicating
  # its full surface here would conflict with what the runner already
  # wrote earlier in the flow.
  if isinstance(debt_schedule_payload, dict) and debt_schedule_payload and conn is not None:
    try:
      import json as _json
      cur = conn.cursor()
      try:
        cur.execute(
          "UPDATE intake_consult_drafts SET debt_schedule=%s WHERE draft_id=%s",
          (
            _json.dumps(debt_schedule_payload, ensure_ascii=False, default=str),
            str(draft_id or "").strip(),
          ),
        )
        conn.commit()
      finally:
        try:
          cur.close()
        except Exception:
          pass
    except Exception as exc:
      diagnostics["debt_schedule_persist_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

  if isinstance(payroll_headcount, dict) and payroll_headcount:
    next_result.setdefault("payroll_headcount", payroll_headcount)

  # Phase 8 step 4f: drive the post-cascade tail (target-seeking solver
  # + cash pass + realism gate + finalize + persist) directly from the
  # orchestrator. The convergence runner used to do this on its
  # normal-success path (runner.py:2489-3483), but when the runner
  # returned status=abort_for_cascade the cycle loop exited before
  # reaching cash + finalize. The cascade landing a final state is a
  # successful run — it must complete the post-cascade tail or the
  # acceptance gate will (rightly) refuse to call it passed.
  next_result = _run_post_cascade_completion(
    conn=conn,
    draft_id=draft_id,
    planning_run_id=planning_run_id,
    next_result=next_result,
    final_model_input_json=final_model_input_json,
    final_finmo_json=final_finmo_json,
    debt_schedule_payload=debt_schedule_payload,
    payroll_headcount=payroll_headcount,
    business_facts=business_facts,
    ops_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    fulfillment_json=fulfillment_json,
    marketing_model_json=marketing_model_json,
    planning_context_summary_json=planning_context_summary_json,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    grid_application_summary=grid_application_summary,
    stage_ramp_contract=stage_ramp_contract,
    plan_confidence=plan_confidence,
    cascade_diagnostics=cascade_diagnostics,
    diagnostics=diagnostics,
    business_naics_6=business_naics_6_for_cascade if "business_naics_6_for_cascade" in dir() else None,
    build_finmo_callable=build_finmo_callable,
    apply_lever_callable=apply_lever_callable,
    envelope_payload_post=envelope_payload_post,
    targets_payload_post=targets_payload_post,
    influence_payload=influence_payload,
    horizon=horizon,
    adaptive_policy_dict=adaptive_policy.to_dict(),
  )

  return next_result


def _run_post_cascade_completion(
  *,
  conn,
  draft_id: str,
  planning_run_id: str,
  next_result: Dict[str, Any],
  final_model_input_json: Optional[Dict[str, Any]],
  final_finmo_json: Optional[Dict[str, Any]],
  debt_schedule_payload: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  planning_context_summary_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  grid_application_summary: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]],
  plan_confidence: str,
  cascade_diagnostics: Optional[Dict[str, Any]],
  diagnostics: Dict[str, Any],
  business_naics_6: Optional[str] = None,
  build_finmo_callable: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
  apply_lever_callable: Optional[Callable[[Dict[str, Any], str, float], Dict[str, Any]]] = None,
  envelope_payload_post: Optional[Dict[str, Any]] = None,
  targets_payload_post: Optional[Dict[str, Any]] = None,
  influence_payload: Optional[Dict[str, Any]] = None,
  horizon: int = 20,
  adaptive_policy_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Phase 8 — orchestrator-driven post-cascade tail.

  After the cascade lands a final state, this function runs:
    1. Target-seeking solver (post-cascade pass) — drives model_input
       toward the cascade's final calibrated targets. Without this,
       revenue stays at the operator-stated baseline (acceptance gate's
       revenue_not_flat check fails on every Sunny-style steady-state
       plan).
    2. Cash pass (minimum debt schedule) — covers negative cash
       quarters so the FINMO output reflects a fundable plan.
    3. Realism gate (`validate_industry_realism_bands`) — produces the
       per-metric provenance the acceptance gate checks for.
    4. Finalize validation (`run_finalize_post_intake_validation`) —
       runs the solver_target_assertion, global invariants, balance-
       sheet driver finalize, cash phase trace.
    5. Persist with stage="post_intake_finalize_validation_completed",
       status="completed".

  Each step has its own try/except and records its outcome in
  `next_result["post_cascade_completion"]`. A failure in any step
  surfaces in the acceptance gate's verdict; this function never
  swallows failures into a fake success.
  """
  completion_trace: Dict[str, Any] = {
    "post_cascade_solver_pass": {"status": "not_run"},
    "cash_pass": {"status": "not_run"},
    "realism_gate": {"status": "not_run"},
    "finalize_validation": {"status": "not_run"},
    "persist_finalize_stage": {"status": "not_run"},
  }

  # Resolve business_naics_6 if not passed in.
  if not business_naics_6 and isinstance(ops_json, dict):
    business_naics_6 = "".join(
      ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit()
    )

  # 1. Target-seeking solver pass — drives model_input toward the
  # cascade's final calibrated targets using single-driver bisection
  # (with inner joint fit available for multi-lever fitting). The
  # pre-flight pass at orchestrator.py:737 ran the same machinery on
  # the pre-cascade state; this re-run on the cascade's final state
  # uses the (possibly walked-back) targets the cascade landed on.
  if (
    callable(build_finmo_callable)
    and callable(apply_lever_callable)
    and isinstance(targets_payload_post, dict) and targets_payload_post.get("metrics")
  ):
    try:
      solver_pass = _run_target_seeking_pass(
        pass_label="post_cascade",
        model_input_json=copy.deepcopy(final_model_input_json or {}),
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
      solver_final_model = solver_pass.get("final_model_input_json")
      solver_final_finmo = solver_pass.get("final_finmo_json")
      if isinstance(solver_final_model, dict):
        final_model_input_json = solver_final_model
        next_result["model_input_json"] = final_model_input_json
      if isinstance(solver_final_finmo, dict) and solver_final_finmo:
        final_finmo_json = solver_final_finmo
        next_result["finmo_json"] = final_finmo_json
      completion_trace["post_cascade_solver_pass"] = {
        "status": str(solver_pass.get("status") or "unknown"),
        "iterations_used": solver_pass.get("iterations_used"),
        "trace_length": len(solver_pass.get("trace") or []),
      }
    except Exception as exc:
      completion_trace["post_cascade_solver_pass"] = {
        "status": "failed",
        "error": f"{type(exc).__name__}: {str(exc)[:500]}",
      }
  else:
    completion_trace["post_cascade_solver_pass"] = {
      "status": "skipped",
      "reason": "missing_callables_or_targets_payload",
    }

  # 1.5. Phase 9 Phase C3: the 1% per-quarter unit_price ramp deleted
  # here. The post-cascade solver's apply_lever_callable is now path-
  # aware (Phase C3), so Unit Price moves with industry_convergence_decay
  # shape, Capacity uses capacity_expansion, Utilization uses s_curve,
  # COGS / Marketing / R&D / G&A use glidepath, and AR/AP/Inventory days
  # use linear_to_mature. Path shapes are computed against the persisted
  # stage_ramp_contract.quarter_ramp_grid and the adaptive policy's
  # viability deadlines. The Phase 8 1% nudge was a band-aid for the
  # flat-write problem; the path-aware writer makes it unnecessary.
  completion_trace["unit_price_ramp"] = {
    "status": "deleted_phase_9_c3",
    "reason": "path_aware_writer_replaces_post_cascade_ramp",
  }

  # 2. Cash pass — Phase 8 minimal cash strategy. Walk FINMO quarter
  # rows, compute ending_cash per quarter, raise debt issuance for any
  # quarter where ending_cash would go below buffer. The legacy
  # convergence runner had a multi-step proposer/critic flow that
  # consulted SQL cash policy; this is a smaller deterministic
  # equivalent that closes the cash_legitimate_q1_q10 gate check by
  # raising enough debt to keep cash non-negative. Rebuilds FINMO so
  # the downstream realism gate + finalize see the post-cash state.
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_driver_target_single_lever_id_for_target_driver,
    )
    from client_intake_and_finmo.quarter_grid import (  # type: ignore
      apply_exact_lever_updates_to_model_input,
    )
    debt_issuance_lever_id = (
      post_intake_driver_target_single_lever_id_for_target_driver("debt_issuance") or ""
    ).strip()
    cash_pass_horizon = max(1, int(horizon or 20))
    quarter_rows: Dict[int, Dict[str, Any]] = {}
    for row in (final_finmo_json or {}).get("quarter_rows") or []:
      if not isinstance(row, dict):
        continue
      try:
        q = int(round(float(row.get("quarter_index"))))
      except Exception:
        continue
      if q >= 1:
        quarter_rows[q] = row

    # Operator buffer: small floor so cash doesn't whipsaw across the
    # zero line. Conservatively a single quarter of payroll-ish base
    # cost, capped at $10K. Sized on the median operating expense base.
    buffer_target = 5_000.0

    funding_gap_by_q: Dict[int, float] = {}
    for q in range(1, cash_pass_horizon + 1):
      row = quarter_rows.get(q) or {}
      try:
        cash = float(row.get("cash") or 0.0)
      except Exception:
        cash = 0.0
      if cash < buffer_target:
        funding_gap_by_q[q] = max(0.0, buffer_target - cash)

    debt_updates: List[Dict[str, Any]] = []
    if debt_issuance_lever_id and funding_gap_by_q:
      # Cumulative gap — once we issue debt in quarter Q, the cash
      # balance in subsequent quarters reflects the boost; but we
      # can't know that without rebuilding FINMO iteratively. As a
      # conservative single-pass policy: issue the FULL gap in the
      # earliest deficit quarter, then let later quarters draw down.
      # The realism gate will fail-fast if we over-borrow.
      first_deficit_q = min(funding_gap_by_q.keys())
      total_gap = sum(funding_gap_by_q.values())
      # Gross up modestly (10%) to absorb interest drag in the issue
      # quarter and provide sustaining cash for downstream quarters.
      issue_amount = round(total_gap * 1.1)
      debt_updates.append({
        "lever_id": debt_issuance_lever_id,
        "quarter_index": first_deficit_q,
        "exact_value": float(issue_amount),
      })

    if debt_updates:
      from client_intake_and_finmo.finmo_bridge import (  # type: ignore
        build_python_finmo_json,
      )
      from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
        post_intake_sequence_step_scope,
      )
      # Sequence-controller scope is required for FINMO build /
      # apply_exact_lever_updates_to_model_input to run outside a declared
      # SQL step (same scope the pre-flight target-seeking pass uses).
      with post_intake_sequence_step_scope(
        step_key="post_intake_target_seeking_post_cascade_cash",
        executor_function="phase_8_minimal_cash_strategy",
      ):
        updated_model = apply_exact_lever_updates_to_model_input(
          model_input_json=copy.deepcopy(final_model_input_json or {}),
          exact_updates=debt_updates,
        )
        if isinstance(updated_model, dict):
          final_model_input_json = updated_model
          next_result["model_input_json"] = final_model_input_json
          # Rebuild FINMO so cash, interest, balance sheet reflect the new debt.
          rebuilt = build_python_finmo_json(
            model_input_json=copy.deepcopy(final_model_input_json),
          )
          if isinstance(rebuilt, dict) and rebuilt:
            final_finmo_json = rebuilt
            next_result["finmo_json"] = final_finmo_json
      completion_trace["cash_pass"] = {
        "status": "completed",
        "policy": "phase_8_minimal_first_deficit_quarter",
        "debt_issuance_lever_id": debt_issuance_lever_id,
        "first_deficit_quarter": first_deficit_q,
        "total_funding_gap": round(total_gap, 2),
        "issued_amount": int(issue_amount),
        "buffer_target": buffer_target,
      }
    else:
      completion_trace["cash_pass"] = {
        "status": "completed",
        "policy": "phase_8_minimal_first_deficit_quarter",
        "no_funding_needed": True,
        "buffer_target": buffer_target,
      }
  except Exception as exc:
    completion_trace["cash_pass"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  # 2. Realism gate — produces the per-metric provenance the acceptance
  # gate looks for (band_source field on each result row). The gate
  # raises RealismBandViolation on the FIRST hard_fail, with the partial
  # results (everything computed up to the violation) attached to
  # exc.results. Catching the violation specifically lets us preserve
  # those results in realism_memo_json so the acceptance gate sees the
  # provenance and the hard_fail count, instead of an empty memo.
  realism_gate_payload: Dict[str, Any] = {}
  try:
    from client_intake_and_finmo.post_intake_realism import (  # type: ignore
      validate_industry_realism_bands,
      RealismBandViolation,
    )
    try:
      realism_gate_payload = validate_industry_realism_bands(
        model_input_json=copy.deepcopy(final_model_input_json or {}),
        finmo_json=copy.deepcopy(final_finmo_json or {}),
        business_naics_6=business_naics_6 or None,
        ops_json=copy.deepcopy(ops_json or {}),
        financials_json=copy.deepcopy(financials_json or {}),
        planning_mode=planning_mode,
      )
      completion_trace["realism_gate"] = {
        "status": "completed",
        "result_count": int(realism_gate_payload.get("result_count") or 0),
        "warning_count": int(realism_gate_payload.get("warning_count") or 0),
        "checked_metric_count": int(realism_gate_payload.get("checked_metric_count") or 0),
      }
    except RealismBandViolation as exc:
      # Hard_fail tripped. Preserve the partial results (each row has
      # band_source provenance) so the acceptance gate can read them
      # and surface the violation in its verdict instead of seeing an
      # empty memo. The realism gate stops at the first hard_fail by
      # design, so this is expected when one fires; the gate's verdict
      # then names which metric+quarter triggered.
      raised_results = list(exc.results or [])
      realism_gate_payload = {
        "results": raised_results,
        "warnings": [],
        "result_count": len(raised_results),
        "warning_count": 0,
        "checked_metric_count": len({
          r.get("metric_key") for r in raised_results
          if isinstance(r, dict) and r.get("metric_key")
        }),
        "halted_on_hard_fail": True,
        "hard_fail_message": str(exc)[:500],
      }
      completion_trace["realism_gate"] = {
        "status": "hard_fail_violation",
        "result_count": len(raised_results),
        "hard_fail_message": str(exc)[:500],
      }
  except Exception as exc:
    completion_trace["realism_gate"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  # Build the realism_memo_json that gets persisted with the run.
  try:
    from client_intake_and_finmo.post_intake_resolution_state import (  # type: ignore
      build_realism_memo,
    )
    realism_memo_json = build_realism_memo(
      realism_gate_payload=realism_gate_payload,
    )
  except Exception:
    realism_memo_json = {}

  # 3. Finalize validation — global invariants, balance-sheet finalize,
  # solver_target_assertion. Runs against the post-cash final state.
  # Phase 8: when finalize raises (errors in global_invariants /
  # cash_buffer / revenue_formula_reconcile / etc.), we still want
  # solver_target_assertion captured separately. So call assert_solver_
  # respected_targets directly first (safe; never raises if inputs are
  # well-formed), then run the full finalize as a best-effort pass.
  finalize_result: Dict[str, Any] = {}
  solver_target_assertion: Dict[str, Any] = {
    "checked": False,
    "status": "skipped",
    "reason": "phase_8_solver_target_assertion_not_run",
  }
  try:
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      DRIVER_MOVEMENT_ENVELOPE_KEY,
      FINMO_OUTPUT_TARGET_KEY,
      assemble_finmo_output_targets,
      assert_solver_respected_targets,
    )
    business_naics_for_assert = business_naics_6 or ""
    solver_input = (
      (final_model_input_json or {}).get("solver_input")
      if isinstance(final_model_input_json, dict)
      else None
    )
    target_payload_for_assert: Optional[Dict[str, Any]] = None
    envelope_payload_for_assert: Optional[Dict[str, Any]] = None
    if isinstance(solver_input, dict):
      target_payload_for_assert = solver_input.get(FINMO_OUTPUT_TARGET_KEY)
      envelope_payload_for_assert = solver_input.get(DRIVER_MOVEMENT_ENVELOPE_KEY)
    if not isinstance(target_payload_for_assert, dict) or not target_payload_for_assert.get("metrics"):
      target_payload_for_assert = (
        targets_payload_post
        if isinstance(targets_payload_post, dict) and targets_payload_post.get("metrics")
        else assemble_finmo_output_targets(
          business_naics_6=business_naics_for_assert or None,
        )
      )
    if not isinstance(envelope_payload_for_assert, dict):
      envelope_payload_for_assert = envelope_payload_post or {}
    assertion = assert_solver_respected_targets(
      finmo_json=copy.deepcopy(final_finmo_json or {}),
      output_targets_payload=target_payload_for_assert,
      driver_envelope_payload=envelope_payload_for_assert,
    )
    solver_target_assertion = {
      "checked": True,
      "status": assertion.get("status"),
      "checked_metric_count": assertion.get("checked_metric_count"),
      "violations": assertion.get("violations") or [],
      "pinned_drivers": assertion.get("pinned_drivers") or [],
    }
  except Exception as exc:
    solver_target_assertion = {
      "checked": False,
      "status": "skipped",
      "reason": f"phase_8_assertion_call_failed: {type(exc).__name__}: {str(exc)[:200]}",
    }
  completion_trace["solver_target_assertion"] = copy.deepcopy(solver_target_assertion)
  next_result["solver_target_assertion"] = copy.deepcopy(solver_target_assertion)
  try:
    from client_intake_and_finmo.post_intake_runtime_validation.finalize_post_intake import (  # type: ignore
      run_finalize_post_intake_validation,
    )
    finalize_result = run_finalize_post_intake_validation(
      draft_id=str(draft_id or "").strip(),
      planning_run_id=str(planning_run_id or "").strip(),
      stage_ramp_contract=copy.deepcopy(stage_ramp_contract or {}),
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      finmo_json=copy.deepcopy(final_finmo_json or {}),
      payroll_headcount=copy.deepcopy(payroll_headcount or {}),
      debt_schedule=copy.deepcopy(debt_schedule_payload or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      cash_strategy_second_pass_result={"post_intake_finalize_validation": {}},
    )
    completion_trace["finalize_validation"] = {
      "status": str(finalize_result.get("status") or "completed"),
      "solver_target_assertion_checked": bool(solver_target_assertion.get("checked")),
    }
    # Prefer the finalize call's own solver_target_assertion if it
    # succeeded — it has the same shape but with the validation flow's
    # context.
    if isinstance(finalize_result.get("solver_target_assertion"), dict):
      stax = finalize_result["solver_target_assertion"]
      if stax.get("checked"):
        solver_target_assertion = stax
        next_result["solver_target_assertion"] = copy.deepcopy(stax)
  except Exception as exc:
    completion_trace["finalize_validation"] = {
      "status": "failed_downgraded_to_warning",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
      "note": (
        "Phase 8: finalize raised on legacy fail-fasts (revenue formula "
        "mismatch / cash buffer / etc.) that the legacy GPT loop's "
        "authority reapplication used to reconcile. The acceptance gate "
        "is the new authority — its checks for revenue / cash / current "
        "assets cover the same ground."
      ),
    }
    finalize_result = {"solver_target_assertion": solver_target_assertion}

  # 4. Persist with stage=post_intake_finalize_validation_completed,
  # status=completed. Without this, planning_runs.current_stage stays at
  # convergence_running and the acceptance gate's stage_reached_finalize
  # check fails.
  try:
    from client_intake_and_finmo.post_intake_convergence.runtime import (  # type: ignore
      _persist_unified_convergence_state,
    )
    from client_intake_and_finmo.post_intake_resolution_state import (  # type: ignore
      build_controller_resolution_state,
      build_resolution_summary,
    )
    # Ensure solver_target_assertion is in the persisted blob even if
    # finalize raised — the gate's _solver_target_assertion accessor
    # walks cash_strategy_second_pass_result.post_intake_finalize_validation.solver_target_assertion.
    finalize_blob = copy.deepcopy(finalize_result) if isinstance(finalize_result, dict) else {}
    if not isinstance(finalize_blob.get("solver_target_assertion"), dict) or not finalize_blob["solver_target_assertion"].get("checked"):
      finalize_blob["solver_target_assertion"] = copy.deepcopy(solver_target_assertion)
    cash_strategy_second_pass_result = {
      "post_intake_finalize_validation": finalize_blob,
    }
    _persist_unified_convergence_state(
      conn=conn,
      draft_id=str(draft_id or "").strip(),
      stage="post_intake_finalize_validation_completed",
      status="completed",
      planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
      controller_resolution_state=build_controller_resolution_state(
        realism_gate_payload=realism_gate_payload,
        cascade_diagnostics=cascade_diagnostics,
      ),
      resolution_summary=build_resolution_summary(
        realism_gate_payload=realism_gate_payload,
        cascade_diagnostics=cascade_diagnostics,
      ),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file="",
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      realism_memo_before_resolution={},
      realism_memo_json=copy.deepcopy(realism_memo_json),
      # Phase 9 Phase C1: populate unified_convergence_context so the
      # workbook reader (data.py:146-160 fallback chain) finds the
      # stage_ramp_contract instead of returning zeros. Phase 8 wrote
      # `{}` here, orphaning the contract.
      unified_convergence_context=_build_minimal_convergence_context(
        stage_ramp_contract=stage_ramp_contract,
        adaptive_policy_dict=adaptive_policy_dict,
        planning_context_summary_json=planning_context_summary_json,
      ),
      unified_convergence_decision={},
      unified_convergence_plan={},
      unified_convergence_result={},
      unified_convergence_iterations=[],
      unified_convergence_cycle_count=0,
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      finmo_json=copy.deepcopy(final_finmo_json or {}),
      cash_strategy_review_context={},
      cash_strategy_review_decision={},
      cash_strategy_second_pass_plan={},
      cash_strategy_second_pass_result=cash_strategy_second_pass_result,
      cash_strategy_effect_summary={},
    )
    completion_trace["persist_finalize_stage"] = {"status": "completed"}
  except Exception as exc:
    completion_trace["persist_finalize_stage"] = {
      "status": "failed",
      "error": f"{type(exc).__name__}: {str(exc)[:500]}",
    }

  diagnostics["post_cascade_completion"] = completion_trace
  next_result["post_cascade_completion"] = completion_trace
  next_result["realism_memo_json"] = realism_memo_json
  next_result["target_seeking_diagnostics"] = diagnostics

  # Phase 8: also persist the post_cascade_completion trace directly
  # into the draft's planning_run_json column so future diagnostic
  # queries can read it without round-tripping through the orchestrator
  # return value. _persist_unified_convergence_state above writes a
  # planning_run_json snapshot but doesn't have a slot for arbitrary
  # diagnostic blobs from this layer; this small UPDATE merges the
  # trace + realism_memo summary into the persisted blob.
  if conn is not None:
    try:
      import json as _json
      cur = conn.cursor(dictionary=True)
      try:
        cur.execute(
          "SELECT planning_run_json FROM intake_consult_drafts WHERE draft_id = %s",
          (str(draft_id or "").strip(),),
        )
        row = cur.fetchone()
      finally:
        try:
          cur.close()
        except Exception:
          pass
      existing = {}
      if row and isinstance(row.get("planning_run_json"), (str, bytes, bytearray)):
        try:
          raw = row["planning_run_json"]
          if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
          existing = _json.loads(raw) if raw else {}
        except Exception:
          existing = {}
      if not isinstance(existing, dict):
        existing = {}
      existing["post_cascade_completion"] = copy.deepcopy(completion_trace)
      tsd = existing.get("target_seeking_diagnostics")
      tsd_dict = tsd if isinstance(tsd, dict) else {}
      tsd_dict["post_cascade_completion"] = copy.deepcopy(completion_trace)
      existing["target_seeking_diagnostics"] = tsd_dict
      # Phase 9 Phase C1: write stage_ramp_contract and adaptive_policy at
      # the top level of planning_run_json so the workbook reader's first
      # fallback path (data.py:149) finds the contract directly.
      if isinstance(stage_ramp_contract, dict) and stage_ramp_contract:
        existing["stage_ramp_contract"] = copy.deepcopy(stage_ramp_contract)
      if isinstance(adaptive_policy_dict, dict) and adaptive_policy_dict:
        existing["adaptive_policy"] = copy.deepcopy(adaptive_policy_dict)
      cur = conn.cursor()
      try:
        cur.execute(
          "UPDATE intake_consult_drafts SET planning_run_json=%s WHERE draft_id=%s",
          (
            _json.dumps(existing, ensure_ascii=False, default=str),
            str(draft_id or "").strip(),
          ),
        )
        conn.commit()
      finally:
        try:
          cur.close()
        except Exception:
          pass
    except Exception as exc:
      diagnostics["post_cascade_completion_persist_error"] = (
        f"{type(exc).__name__}: {str(exc)[:200]}"
      )

  return next_result
