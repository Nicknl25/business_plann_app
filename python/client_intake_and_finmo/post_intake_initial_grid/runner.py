"""Initial grid orchestration for post-intake planning.

This module owns the baseline -> planning mode -> ramp -> quarter-grid phase.
The API handler should call this phase and then hand the returned state to the
post-grid convergence runner.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_process_sequence_step,
)
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
  assert_post_intake_global_invariants,
)
from client_intake_and_finmo.post_intake_runtime_validation import (  # type: ignore
  run_initialize_post_intake_validation,
)
from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
  assert_post_intake_sequence_controller_authoritative,
  build_post_intake_sequence_controller,
  build_single_step_handler_registry,
)


def prepare_initial_grid_for_draft(
  *,
  conn: Any,
  draft_id: str,
  lifecycle_mode: str,
  planning_run_id: Optional[str],
  build_shared_context: Optional[Callable[..., Dict[str, Any]]],
  get_draft: Callable[..., Dict[str, Any]],
  begin_planning_run: Callable[..., Dict[str, Any]],
  persist_post_intake_execution_state: Callable[..., Dict[str, Any]],
  maybe_interrupt_planning_run: Callable[..., None],
  parse_json_dict: Callable[[Any], Dict[str, Any]],
  reset_openai_call_telemetry: Callable[[], None],
  build_planning_run_payload: Callable[..., Dict[str, Any]],
  extract_numeric_solver_feedback_for_persistence: Callable[..., Dict[str, Any]],
  build_planning_context_summary_payload: Callable[..., Dict[str, Any]],
  year1_drivers_conflict: Callable[[Optional[Dict[str, Any]], Dict[str, Any]], bool],
  compute_marketing_model_json: Callable[..., Dict[str, Any]],
  estimate_maintenance_capex_percent_with_gpt: Callable[..., Dict[str, Any]],
  safe_float: Callable[[Any], Optional[float]],
  estimate_r_and_d_applicability_with_gpt: Callable[..., Dict[str, Any]],
  r_and_d_policy_from_model_input: Callable[[Optional[Dict[str, Any]]], Dict[str, Any]],
  assert_r_and_d_applicability_policy_applied: Callable[..., None],
  estimate_balance_sheet_contextual_seed_with_gpt: Callable[..., Dict[str, Any]],
  estimate_stage_ramp_contract_with_gpt: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
  """Prepare the initial post-intake quarter grid and baseline state."""
  if build_shared_context is None:
    raise RuntimeError("build_shared_context_unavailable")
  normalized_draft_id = str(draft_id).strip()
  normalized_lifecycle_mode = str(lifecycle_mode or "start").strip().lower() or "start"
  draft = get_draft(conn, draft_id=normalized_draft_id)
  if str(draft.get("active_focus") or "").strip().lower() != "done":
    raise RuntimeError("draft_not_complete")
  sequence_trace: Dict[str, Any] = {}
  sequence_controller = build_post_intake_sequence_controller()
  sequence_trace["sequence_controller_authority"] = (
    assert_post_intake_sequence_controller_authoritative()
  )

  reset_openai_call_telemetry()
  lifecycle_start = begin_planning_run(
    conn,
    draft_id=normalized_draft_id,
    trigger_type="system_run",
    lifecycle_mode=normalized_lifecycle_mode,
    planning_run_id=planning_run_id,
  )
  active_planning_run = (
    lifecycle_start.get("planning_run")
    if isinstance(lifecycle_start.get("planning_run"), dict)
    else {}
  )
  active_planning_run_id = str(active_planning_run.get("planning_run_id") or "").strip()
  if not active_planning_run_id:
    raise RuntimeError("planning_run_start_failed")

  def _persist_validation_stage(
    *,
    stage: str,
    status: str,
    validation_payload: Optional[Dict[str, Any]] = None,
  ) -> Dict[str, Any]:
    payload = build_planning_run_payload(
      stage=stage,
      status=status,
      planning_mode="",
      planning_mode_reason="",
      prompt_file="",
      gpt_narrative="",
      gpt_grid_metadata={},
      grid_application_summary={},
    )
    payload["planning_run_id"] = active_planning_run_id
    payload["trigger_type"] = "system_run"
    payload["lifecycle_mode"] = normalized_lifecycle_mode
    payload["runtime_validation"] = copy.deepcopy(validation_payload or {})
    persisted = persist_post_intake_execution_state(
      conn,
      draft_id=normalized_draft_id,
      new_messages=[],
      planning_run_json=payload,
      numeric_solver_feedback_json=extract_numeric_solver_feedback_for_persistence(
        planning_run_payload=payload
      ),
      active_focus="done",
      status="in_progress",
      completed=False,
      checkpoint_kind="stage_snapshot",
      event_type="runtime_validation",
      event_summary=f"{stage}:{status}",
    )
    return (
      persisted.get("planning_run_json")
      if isinstance(persisted, dict) and isinstance(persisted.get("planning_run_json"), dict)
      else payload
    )

  _persist_validation_stage(
    stage="post_intake_initialize_validation_running",
    status="running",
  )
  initialize_validation = sequence_controller.execute_registered_step(
    "post_intake_initialize_validation",
    handler_registry=build_single_step_handler_registry(
      "post_intake_initialize_validation",
      run_initialize_post_intake_validation,
    ),
    runtime_context={
      "sql.lookup_tables": [
        "post_intak_mapping_lookup",
        "post_intake_cash_policy_lookup",
        "post_intake_gpt_contract_lookup",
        "post_intake_gpt_context_lookup",
        "post_intake_process_context_lookup",
        "post_intake_process_sequence_lookup",
      ],
      "post_intake_lookup_functions": [
        "post_intake_assert_required_process_sequence",
        "post_intake_process_context_lookup",
        "post_intake_process_sequence_lookup",
      ],
    },
    handler_kwargs={
      "draft_id": normalized_draft_id,
      "planning_run_id": active_planning_run_id,
    },
    isolated=False,
    allow_side_effects=True,
  )
  sequence_trace["post_intake_initialize_validation"] = copy.deepcopy(initialize_validation)
  sequence_trace["runtime_table_integrity"] = copy.deepcopy(initialize_validation.get("runtime_table_integrity") or {})
  sequence_trace["required_process_sequence"] = copy.deepcopy(initialize_validation.get("required_process_sequence") or {})
  _persist_validation_stage(
    stage="post_intake_initialize_validation_completed",
    status="completed",
    validation_payload=copy.deepcopy(initialize_validation),
  )
  from client_intake_and_finmo.financials_consultant import estimate_marketing_baseline_from_context  # type: ignore
  from client_intake_and_finmo.financials_year1 import assemble_financials_year1  # type: ignore
  from client_intake_and_finmo.finmo_bridge import (  # type: ignore
    apply_derived_driver_policies_to_model_input,
    apply_r_and_d_applicability_policy_to_model_input,
    build_python_finmo_json,
    sync_planning_state_to_finmo,
  )
  from client_intake_and_finmo.post_intake_balance_sheet import (  # type: ignore
    apply_balance_sheet_contextual_seed_to_model_input,
  )
  from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
    apply_payroll_supported_capacity_to_model_input,
    apply_payroll_headcount_payload_to_model_input,
    assert_finmo_payroll_matches_headcount_schedule,
    assert_payroll_headcount_model_input_applied,
    assert_payroll_headcount_payload_ready,
    estimate_payroll_headcount_schedule_with_gpt,
    payroll_revenue_feasibility_violations,
  )
  from client_intake_and_finmo.quarter_grid import determine_planning_mode, generate_live_quarter_grid_plan, apply_live_quarter_grid_plan  # type: ignore

  # P3.40 Contract 5 Commit 3 -- consumer-side boundary gate
  # for IntakeDraftContract (Boundary 1: INTAKE -> POST_INTAKE).
  # Validates the 8-field intake-draft JSON shape BEFORE the
  # parse_json_dict reads below (which today silently coerce
  # missing/malformed JSON to {}). Surfaces structural problems
  # as ContractViolation rather than empty plans downstream.
  # ContractViolation lands in the API handler's `except Exception
  # as exc:` catch at intake_consult.py:7377 (Div-6) -- structured
  # 500 with detail=str(exc) carrying INTAKE_DRAFT_STAGE_LABEL.
  #
  # fulfillment_json is Optional per Flag 1 (a): if the SQL column
  # is NULL, the parse_json_dict would return {} -- but we want
  # the contract to see field-absent rather than empty-dict so
  # the Optional default path matches production reality
  # (patch-system-only writes). Include the field only if the raw
  # column is non-null.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
    SIDE_CONSUMER as _IDC_SIDE_CONSUMER,
    validate_intake_draft_at_boundary,
  )
  _intake_draft_payload_for_gate: Dict[str, Any] = {
    "operating_model_json": parse_json_dict(draft.get("operating_model_json")),
    "target_market_json": parse_json_dict(draft.get("target_market_json")),
    "people_json": parse_json_dict(draft.get("people_json")),
    "financials_json": parse_json_dict(draft.get("financials_json")),
    "financials_year1_json": parse_json_dict(draft.get("financials_year1_json")),
    "marketing_model_json": parse_json_dict(draft.get("marketing_model_json")),
    "planning_context_summary_json": parse_json_dict(draft.get("planning_context_summary_json")),
  }
  _raw_fulfillment_for_gate = draft.get("fulfillment_json")
  if _raw_fulfillment_for_gate is not None:
    _intake_draft_payload_for_gate["fulfillment_json"] = parse_json_dict(
      _raw_fulfillment_for_gate
    )
  # Emit-skip per Contracts 3 + 4 consumer-side gate pattern:
  # _boundary_emitter is defined later (line ~1853) for the
  # Contract 1 + Contract 3 producer-side gates; building it
  # here for Contract 5's consumer-side gate would require
  # reordering and the diagnostic emit is best-effort anyway.
  # The gate raises ContractViolation on failure regardless.
  validate_intake_draft_at_boundary(
    _intake_draft_payload_for_gate,
    side=_IDC_SIDE_CONSUMER,
  )

  ops_json = parse_json_dict(draft.get("operating_model_json"))
  market_json = parse_json_dict(draft.get("target_market_json"))
  people_json = parse_json_dict(draft.get("people_json"))
  financials_json = parse_json_dict(draft.get("financials_json"))
  financials_year1_json = parse_json_dict(draft.get("financials_year1_json"))
  fulfillment_json = parse_json_dict(draft.get("fulfillment_json"))
  marketing_model_json = parse_json_dict(draft.get("marketing_model_json"))
  planning_context_summary_json = parse_json_dict(draft.get("planning_context_summary_json"))
  resume_checkpoint = (
    lifecycle_start.get("latest_checkpoint")
    if isinstance(lifecycle_start.get("latest_checkpoint"), dict)
    else {}
  )
  resume_checkpoint_stage = str(resume_checkpoint.get("stage") or "").strip().lower()
  resume_checkpoint_planning_payload = parse_json_dict(resume_checkpoint.get("planning_run_json"))
  resume_checkpoint_model_input_json = parse_json_dict(resume_checkpoint.get("model_input_json"))
  resume_checkpoint_finmo_json = parse_json_dict(resume_checkpoint.get("finmo_json"))
  resume_from_checkpoint_state = bool(
    normalized_lifecycle_mode == "resume"
    and isinstance(resume_checkpoint_model_input_json, dict)
    and resume_checkpoint_model_input_json
    and isinstance(resume_checkpoint_finmo_json, dict)
    and resume_checkpoint_finmo_json
    and resume_checkpoint_stage not in {"", "system_run_starting", "baseline_ready", "quarter_grid_running", "quarter_grid_ready"}
  )

  business_facts: Dict[str, Any] = {
    "name": draft.get("business_name"),
    "business_name": draft.get("business_name"),
    "address": draft.get("business_address"),
    "start_date": draft.get("business_start_date"),
    "address_street": draft.get("address_street"),
    "address_city": draft.get("address_city"),
    "address_state": draft.get("address_state"),
    "address_zip": draft.get("address_zip"),
    "address_country": draft.get("address_country"),
  }

  def _runtime_context(
    *,
    current_model_input_json: Optional[Dict[str, Any]] = None,
    current_finmo_json: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
  ) -> Dict[str, Any]:
    context = {
      "business_facts": copy.deepcopy(business_facts or {}),
      "business_type": str((ops_json or {}).get("business_type") or "").strip(),
      # P3.40 Contract Layer Cleanup 3/6 -- Contract 5b R-a:
      # ASSESSED + KEPT for legacy DB support. naics_code +
      # business_naics are NOT in the current GPT schema and
      # have ZERO current code writers (per Cleanup 3/6 reader/
      # writer audit). However, legacy production drafts that
      # pre-date the current OperatingModelJsonContract schema
      # MAY carry these keys instead of business_naics_6.
      # Contract 5b's extra='ignore' lets them pass the gate;
      # this fallback chain ensures NAICS resolution still
      # works for those legacy drafts. Removing the fallback
      # silently loses NAICS resolution on legacy data. DB
      # audit (5b R-a) would confirm whether any legacy draft
      # actually carries these keys; until then, KEEP per
      # PSL2 production-reality-wins.
      "business_naics": str(
        (people_json or {}).get("business_naics_6")
        or (ops_json or {}).get("naics_code")
        or (ops_json or {}).get("business_naics")
        or ""
      ).strip(),
      "operating_model_json": copy.deepcopy(ops_json or {}),
      "target_market_json": copy.deepcopy(market_json or {}),
      "people_json": copy.deepcopy(people_json or {}),
      "financials_json": copy.deepcopy(financials_json or {}),
      "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
      "fulfillment_json": copy.deepcopy(fulfillment_json or {}),
      "marketing_model_json": copy.deepcopy(marketing_model_json or {}),
      "planning_context_summary_json": copy.deepcopy(planning_context_summary_json or {}),
      "model_input_json": copy.deepcopy(current_model_input_json or {}),
      "finmo_json": copy.deepcopy(current_finmo_json or {}),
      "ops_context": copy.deepcopy(ops_json or {}),
      "market_context": copy.deepcopy(market_json or {}),
      "people_context": copy.deepcopy(people_json or {}),
      "financials_context": copy.deepcopy(financials_json or {}),
      "financials_year1_context": copy.deepcopy(financials_year1_json or {}),
      "marketing_context": copy.deepcopy(marketing_model_json or {}),
    }
    if isinstance(extra, dict):
      context.update(copy.deepcopy(extra))
    return context

  def _execute_sequence_step(
    step_key: str,
    handler: Callable[..., Any],
    *,
    runtime_context: Optional[Dict[str, Any]] = None,
    handler_kwargs: Optional[Dict[str, Any]] = None,
    expected_phase: str = "",
    expected_handler_key: str = "",
    required_contract_name: str = "",
    required_context_contract_name: str = "",
    required_context_include_phase: str = "",
    required_lookup_tables: Optional[list[str]] = None,
    required_horizon_rule: str = "",
  ) -> Any:
    result = sequence_controller.execute_registered_step(
      step_key,
      handler_registry=build_single_step_handler_registry(
        step_key,
        handler,
        extra_keys=[expected_handler_key],
      ),
      runtime_context=runtime_context or {},
      handler_kwargs=handler_kwargs or {},
      isolated=False,
      allow_side_effects=True,
    )
    trace_rows = sequence_controller.trace()
    if trace_rows:
      sequence_trace[step_key] = copy.deepcopy(trace_rows[-1])
    return result

  def _assert_global_invariants_via_sequence(
    step_key: str,
    *,
    model_input_payload: Dict[str, Any],
    finmo_payload: Dict[str, Any],
    payroll_headcount_payload: Dict[str, Any],
    stage: str,
  ) -> Dict[str, Any]:
    def _run_global_invariants() -> Dict[str, Any]:
      assert_post_intake_global_invariants(
        stage_ramp_contract=copy.deepcopy(stage_ramp_contract),
        model_input_json=copy.deepcopy(model_input_payload),
        finmo_json=copy.deepcopy(finmo_payload),
        stage=stage,
        payroll_headcount=copy.deepcopy(payroll_headcount_payload),
      )
      return {"status": "completed", "stage": stage}

    return _execute_sequence_step(
      step_key,
      _run_global_invariants,
      runtime_context=_runtime_context(
        current_model_input_json=model_input_payload,
        current_finmo_json=finmo_payload,
        extra={
          "stage_ramp_contract": copy.deepcopy(stage_ramp_contract or {}),
          "payroll_headcount": copy.deepcopy(payroll_headcount_payload or {}),
        },
      ),
      expected_phase="initial_grid",
      expected_handler_key="assert_post_intake_global_invariants",
      required_lookup_tables=[
        "post_intak_mapping_lookup",
        "post_intake_headcount_policy_lookup",
      ],
      required_horizon_rule="global_invariants_all_q1_to_q20",
    )

  def refresh_planning_context_summary(
    *,
    current_model_input_json: Optional[Dict[str, Any]],
    planning_mode_value: str = "",
    planning_mode_reason_value: str = "",
    prompt_file_value: str = "",
  ) -> Dict[str, Any]:
    return build_planning_context_summary_payload(
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      target_market_json=copy.deepcopy(market_json or {}),
      people_json=copy.deepcopy(people_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      financials_year1_json=copy.deepcopy(financials_year1_json or {}),
      marketing_model_json=copy.deepcopy(marketing_model_json or {}),
      model_input_json=copy.deepcopy(current_model_input_json or {}),
      planning_mode=planning_mode_value,
      planning_mode_reason=planning_mode_reason_value,
      prompt_file=prompt_file_value,
    )

  def persist_system_stage(
    *,
    stage: str,
    status: str,
    planning_mode: str = "",
    planning_mode_reason: str = "",
    prompt_file: str = "",
    gpt_narrative: str = "",
    gpt_grid_metadata: Optional[Dict[str, Any]] = None,
    grid_application_summary: Optional[Dict[str, Any]] = None,
    model_input_payload: Optional[Dict[str, Any]] = None,
    finmo_payload: Optional[Dict[str, Any]] = None,
    payroll_headcount_payload: Optional[Dict[str, Any]] = None,
  ) -> Dict[str, Any]:
    payload = build_planning_run_payload(
      stage=stage,
      status=status,
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      gpt_narrative=gpt_narrative,
      gpt_grid_metadata=copy.deepcopy(gpt_grid_metadata or {}),
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    )
    payload["planning_run_id"] = active_planning_run_id
    payload["trigger_type"] = "system_run"
    payload["lifecycle_mode"] = normalized_lifecycle_mode
    persisted = persist_post_intake_execution_state(
      conn,
      draft_id=normalized_draft_id,
      new_messages=[],
      planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
      model_input_json=model_input_payload,
      finmo_json=finmo_payload,
      payroll_headcount=payroll_headcount_payload,
      planning_run_json=payload,
      numeric_solver_feedback_json=extract_numeric_solver_feedback_for_persistence(
        planning_run_payload=payload
      ),
      active_focus="done",
      status="in_progress",
      completed=False,
      checkpoint_kind="stage_snapshot",
      event_type="stage_persisted",
      event_summary=f"{stage}:{status}",
    )
    persisted_payload = (
      persisted.get("planning_run_json")
      if isinstance(persisted, dict) and isinstance(persisted.get("planning_run_json"), dict)
      else payload
    )
    maybe_interrupt_planning_run(
      conn=conn,
      draft_id=normalized_draft_id,
      planning_run_id=active_planning_run_id,
      stage=stage,
      planning_status=status,
      planning_run_json=copy.deepcopy(persisted_payload),
      model_input_json=copy.deepcopy(model_input_payload or {}),
      finmo_json=copy.deepcopy(finmo_payload or {}),
      numeric_solver_feedback_json=extract_numeric_solver_feedback_for_persistence(
        planning_run_payload=persisted_payload
      ),
      event_summary=f"{stage}:{status}:lifecycle_gate",
    )
    return persisted_payload

  _execute_sequence_step(
    "baseline_model_input",
    lambda: {"status": "baseline_model_input_started"},
    runtime_context=_runtime_context(),
    expected_phase="pre_convergence",
    expected_handler_key="prepare_baseline_model_input",
    required_lookup_tables=[
      "post_intak_mapping_lookup",
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
    ],
    required_horizon_rule="q1_to_q20_forecast_state_excludes_stub_q0",
  )
  shared_context = _execute_sequence_step(
    "shared_context_build",
    build_shared_context,
    runtime_context=_runtime_context(),
    handler_kwargs={"conn": conn, "draft_id": normalized_draft_id},
    expected_phase="pre_convergence",
    expected_handler_key="build_shared_context",
    required_horizon_rule="build_post_intake_shared_context_from_intake_inputs",
  )
  shared_context = dict(shared_context or {})
  _execute_sequence_step(
    "ops_context_load",
    lambda: copy.deepcopy(ops_json or {}),
    runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
    expected_phase="pre_convergence",
    expected_handler_key="load_operating_model_context",
    required_horizon_rule="load_intake_operating_model_context",
  )
  _execute_sequence_step(
    "market_context_load",
    lambda: copy.deepcopy(market_json or {}),
    runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
    expected_phase="pre_convergence",
    expected_handler_key="load_target_market_context",
    required_horizon_rule="load_intake_market_context",
  )
  _execute_sequence_step(
    "people_context_load",
    lambda: copy.deepcopy(people_json or {}),
    runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
    expected_phase="pre_convergence",
    expected_handler_key="load_people_context",
    required_horizon_rule="load_intake_people_context",
  )
  _execute_sequence_step(
    "financials_context_load",
    lambda: copy.deepcopy(financials_json or {}),
    runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
    expected_phase="pre_convergence",
    expected_handler_key="load_financials_context",
    required_horizon_rule="load_intake_financials_context",
  )
  shared_context["operating_model"] = ops_json
  shared_context["target_market"] = market_json
  shared_context["people_capability"] = people_json
  shared_context["financials"] = financials_json

  base_year1 = _execute_sequence_step(
    "financials_year1_assembly",
    lambda: assemble_financials_year1(shared_context, None),
    runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
    expected_phase="pre_convergence",
    expected_handler_key="assemble_financials_year1",
    required_horizon_rule="derive_authoritative_year1_financial_context",
  )
  if year1_drivers_conflict(financials_year1_json, base_year1):
    financials_year1_json = base_year1
  else:
    financials_year1_json = _execute_sequence_step(
      "financials_year1_assembly",
      lambda: assemble_financials_year1(shared_context, financials_year1_json),
      runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
      expected_phase="pre_convergence",
      expected_handler_key="assemble_financials_year1",
      required_horizon_rule="derive_authoritative_year1_financial_context",
    )
  if isinstance(financials_year1_json, dict) and financials_year1_json:
    shared_context["financials_year1_json"] = financials_year1_json

  # Phase 9 P3.33 Phase 3 step 1 — Materialize cohort bands so the amalgamated
  # GPT session (later commits this phase) can return constraint bands inline
  # in tool responses, and so bands are auditable per run. Soft failure: this
  # is a new audit sink that no caller consumes yet; a write issue here must
  # not break a run. Later commits (when the amalgamated session reads bands)
  # will promote failures to hard.
  try:
    from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # type: ignore
      populate_cohort_bands_for_run,
    )
    _bp_target_revenue = safe_float(
      (financials_year1_json or {}).get("company_revenue_total_year1")
    ) if isinstance(financials_year1_json, dict) else None
    _bp_naics_6 = (
      "".join(ch for ch in str((ops_json or {}).get("business_naics_6") or "") if ch.isdigit())
      if isinstance(ops_json, dict) else None
    )
    _bp_stage = (
      (str((ops_json or {}).get("business_stage") or "").strip().lower() or None)
      if isinstance(ops_json, dict) else None
    )
    _bands_summary = populate_cohort_bands_for_run(
      conn,
      draft_id=normalized_draft_id,
      planning_run_id=active_planning_run_id,
      business_profile={
        "naics_6": _bp_naics_6,
        "target_annual_revenue": _bp_target_revenue,
        "stage": _bp_stage,
        "business_model": None,
      },
    )
    sequence_trace["cohort_bands_populated"] = _bands_summary
  except Exception as _cohort_bands_exc:  # noqa: BLE001 — soft sink (see above)
    sequence_trace["cohort_bands_populated"] = {"error": repr(_cohort_bands_exc)}

  # P3.40 Contract 6 Commit 3 -- Shape D producer-side gate
  # (F14 a SHIP). Placed OUTSIDE the soft try/except above so a
  # ContractViolation from F10 (zero resolved bands across all
  # 5 sections) propagates loud through intake_consult.py:7377
  # generic catch -- closes v1 §F-2 FAIL_COHORT_BANDS_MISSING
  # precondition that the soft try/except otherwise silences.
  # Gate only fires when the populator succeeded (sequence_trace
  # has a non-error summary); skipped when the soft-swallow above
  # fired (preserves the "this is a new audit sink, populator-
  # internal exceptions soft-degrade" semantic from runner.py:557).
  _ibr_bands_summary_for_gate = sequence_trace.get("cohort_bands_populated")
  if (
    isinstance(_ibr_bands_summary_for_gate, dict)
    and "error" not in _ibr_bands_summary_for_gate
  ):
    from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
      SIDE_PRODUCER as _IBR_SIDE_PRODUCER,
      validate_industry_baseline_population_summary_at_boundary,
    )
    validate_industry_baseline_population_summary_at_boundary(
      _ibr_bands_summary_for_gate, side=_IBR_SIDE_PRODUCER,
    )

  try:
    marketing_model_json = _execute_sequence_step(
      "marketing_context_build",
      compute_marketing_model_json,
      runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
      handler_kwargs={
        "conn": conn,
        "ops_json": ops_json,
        "market_json": market_json,
        "people_json": people_json,
        "financials_year1_json": financials_year1_json,
        "business_facts": business_facts,
        "existing_marketing_model_json": marketing_model_json,
        "estimate_marketing_baseline_from_context": estimate_marketing_baseline_from_context,
      },
      expected_phase="pre_convergence",
      expected_handler_key="compute_marketing_model_json",
      required_horizon_rule="derive_marketing_context_before_baseline_finmo",
    )
  except Exception as _marketing_exc:
    # C2 — record the swallowed exception so the silent fallback to
    # an empty marketing context leaves an audit trail. Marketing is
    # optional context (the baseline FINMO still builds); the
    # downstream code is robust to an empty model. But the exception
    # cause should not vanish silently.
    try:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        EventCode as _C2EventCode, PhaseCode as _C2PhaseCode,
        Status as _C2Status, safe_emit as _c2_safe_emit,
      )
      _c2_safe_emit(
        conn,
        draft_id=str(draft_id or ""),
        planning_run_id=str(active_planning_run_id or ""),
        phase=_C2PhaseCode.MIRROR_BUILD,
        event_code=_C2EventCode.MARKETING_CONTEXT_FETCH_FAILED,
        status=_C2Status.FAILED,
        diagnostic_data={
          "exception_type": type(_marketing_exc).__name__,
          "detail": str(_marketing_exc)[:480],
        },
      )
    except Exception:
      pass  # observability never breaks the pipeline
    marketing_model_json = dict(marketing_model_json or {})
  shared_context["marketing"] = marketing_model_json

  forecast_starting_ppe_decision = _execute_sequence_step(
    "maintenance_capex_percent",
    estimate_maintenance_capex_percent_with_gpt,
    runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
    handler_kwargs={
      "business_facts": business_facts,
      "ops_json": ops_json,
      "financials_json": financials_json,
      "financials_year1_json": financials_year1_json,
    },
    expected_phase="pre_convergence",
    expected_handler_key="estimate_maintenance_capex_percent_with_gpt",
    required_contract_name="maintenance_capex_percent",
    required_lookup_tables=["post_intake_gpt_contract_lookup"],
    required_horizon_rule="single_pre_convergence_decision",
  )
  forecast_starting_ppe = int(round(max(0.0, float(safe_float((financials_json or {}).get("initial_assets")) or 0.0))))
  maintenance_rate = float(safe_float(forecast_starting_ppe_decision.get("maintenance_rate")) or 0.0)
  # Module 5 Task 5.1 — DELETED legacy `< 0.02 or > 0.15` post-validation.
  # The deterministic NAICS-cascade function returns a real industry-typical
  # rate; the universal 2-15% guard rejected legitimate NAICS values for
  # capital-light services (often <2%) and capital-heavy manufacturing
  # (often >15%). The decision payload's `naics_provenance` field documents
  # where the value came from. Sanity-check positivity only.
  if maintenance_rate <= 0.0:
    raise RuntimeError(
      f"maintenance_capex_percent_maintenance_rate_nonpositive: rate={maintenance_rate!r}"
    )
  shared_context["forecast_starting_ppe_decision"] = {
    "contract_version": forecast_starting_ppe_decision.get("contract_version"),
    "decision_source": forecast_starting_ppe_decision.get("decision_source"),
    "starting_ppe": forecast_starting_ppe,
    "starting_ppe_source": "financials_json.initial_assets_authoritative_balance_sheet",
    "balance_sheet_authoritative": True,
    "maintenance_capex_percent": forecast_starting_ppe_decision.get("maintenance_capex_percent"),
    "maintenance_rate": maintenance_rate,
  }

  # Step 9b-ii — finmo_sync diagnostic emits around the baseline
  # sync call. STARTED before _execute_sequence_step; COMPLETED on
  # success; FAILED in the except path of any downstream consumer
  # of sync_result. (The _execute_sequence_step itself raises on
  # handler failure; we let that propagate.)
  from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
    EventCode as _DiagEventCode,
    PhaseCode as _DiagPhaseCode,
    Status as _DiagStatus,
    safe_emit as _diag_safe_emit,
  )
  _diag_safe_emit(
    conn,
    draft_id=str(draft_id or "").strip(),
    planning_run_id=str(active_planning_run_id or "").strip(),
    phase=_DiagPhaseCode.FINMO_SYNC,
    event_code=_DiagEventCode.FINMO_SYNC_STARTED,
    status=_DiagStatus.STARTED,
    diagnostic_data={"forecast_starting_ppe": forecast_starting_ppe,
                     "maintenance_rate": maintenance_rate},
  )
  sync_result = _execute_sequence_step(
    "baseline_finmo_sync",
    sync_planning_state_to_finmo,
    runtime_context=_runtime_context(extra={"shared_context": copy.deepcopy(shared_context)}),
    handler_kwargs={
      "finmo_path": "",
      "business_facts": business_facts,
      "ops_json": ops_json,
      "people_json": people_json,
      "financials_json": financials_json,
      "financials_year1_json": financials_year1_json,
      "marketing_model_json": marketing_model_json,
      "forecast_starting_ppe": forecast_starting_ppe,
      "maintenance_rate": maintenance_rate,
      "controller_input_seed": [],
      "forecast_quarters": [],
      "calibration_spec": None,
    },
    expected_phase="pre_convergence",
    expected_handler_key="sync_planning_state_to_finmo",
    required_horizon_rule="q1_to_q20_forecast_state_excludes_stub_q0",
  )
  # Step 9d items 16 + 17 — finmo_sync postcondition guards.
  # Item 16: the sync must yield a finmo_json dict carrying quarter
  # rows; an empty/missing finmo_json means the FINMO build silently
  # produced no output. Item 17: the required columns (quarter_index,
  # revenue, gross_profit, ebitda, ending_cash) must be present on
  # the first row so downstream consumers can read them. P3.41 NexGen
  # E2E iter 6 correction: original names (period / op_income /
  # cash_end) never matched the FINMO engine's actual output schema
  # (quarter_index / ebitda / ending_cash per FinmoQuarterResult at
  # financial_model_engine/finmo_model.py:145-199 + bridge aliases at
  # finmo_bridge.py:887-908). The guard was dead -- would have failed
  # every clean run; never fired before because no E2E reached
  # FINMO_SYNC cleanly until the iter 1-5 contract fixes unblocked
  # the path. Renaming makes the guard functional (strengthening, not
  # loosening).
  _sync_finmo = (
    sync_result.get("finmo_json") if isinstance(sync_result, dict) else None
  )
  _sync_quarter_rows = (
    (_sync_finmo or {}).get("quarter_rows")
    if isinstance(_sync_finmo, dict) else None
  )
  if not _sync_quarter_rows:
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
    )
    _rff(
      conn,
      draft_id=str(draft_id or ""),
      planning_run_id=str(active_planning_run_id or ""),
      phase=_PC.FINMO_SYNC,
      code=_FFC.FAIL_FINMO_NO_QUARTER_ROWS,
      detail=(
        f"baseline_finmo_sync produced no quarter_rows "
        f"(finmo_json type={type(_sync_finmo).__name__})"
      ),
      where="post_intake_initial_grid.runner (baseline_finmo_sync)",
    )
  _required_finmo_cols = {"quarter_index", "revenue", "gross_profit", "ebitda", "ending_cash"}
  _first_row = _sync_quarter_rows[0] if isinstance(_sync_quarter_rows, list) else None
  if not isinstance(_first_row, dict) or not _required_finmo_cols.issubset(set(_first_row.keys())):
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
    )
    _missing_cols = _required_finmo_cols - set((_first_row or {}).keys() if isinstance(_first_row, dict) else [])
    _rff(
      conn,
      draft_id=str(draft_id or ""),
      planning_run_id=str(active_planning_run_id or ""),
      phase=_PC.FINMO_SYNC,
      code=_FFC.FAIL_FINMO_SCHEMA_MISSING,
      detail=f"first quarter row missing required columns: {sorted(_missing_cols)}",
      where="post_intake_initial_grid.runner (baseline_finmo_sync schema)",
    )
  _diag_safe_emit(
    conn,
    draft_id=str(draft_id or "").strip(),
    planning_run_id=str(active_planning_run_id or "").strip(),
    phase=_DiagPhaseCode.FINMO_SYNC,
    event_code=_DiagEventCode.FINMO_SYNC_COMPLETED,
    status=_DiagStatus.COMPLETED,
    diagnostic_data={
      "model_input_present": bool(isinstance(sync_result, dict)
                                  and isinstance(sync_result.get("model_input_json"), dict)),
      "finmo_present": bool(isinstance(sync_result, dict)
                            and isinstance(sync_result.get("finmo_json"), dict)),
    },
  )
  r_and_d_applicability_decision: Dict[str, Any] = {}
  balance_sheet_contextual_seed_decision: Dict[str, Any] = {}
  if resume_from_checkpoint_state:
    model_input_json = copy.deepcopy(resume_checkpoint_model_input_json)
    finmo_json = copy.deepcopy(resume_checkpoint_finmo_json)
    r_and_d_applicability_decision = copy.deepcopy(
      r_and_d_policy_from_model_input(model_input_json)
    )
    assert_r_and_d_applicability_policy_applied(
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      stage="resume_checkpoint_loaded",
    )
    planning_context_summary_json = refresh_planning_context_summary(
      current_model_input_json=model_input_json,
    )
    persist_system_stage(
      stage="resume_checkpoint_loaded",
      status="running",
      model_input_payload=model_input_json,
      finmo_payload=finmo_json,
    )
  else:
    model_input_json = (
      sync_result.get("model_input_json")
      if isinstance(sync_result.get("model_input_json"), dict)
      else {}
    )
    finmo_json = (
      sync_result.get("finmo_json")
      if isinstance(sync_result.get("finmo_json"), dict)
      else {}
    )
    # P3.33 Phase 3 8b-fix — REPLACE the legacy
    # _execute_sequence_step pair (r_and_d_applicability + balance_
    # sheet_contextual_seed) with a single set_capex_rd_balance_seed
    # (contract=None) call. The tool's contract=None path wraps the
    # SAME deterministic Python builders the sequence steps used to
    # delegate to (estimate_r_and_d_applicability_with_gpt is pure
    # Python per P3.10; propose_balance_sheet_contextual_seed_payload
    # is the deterministic balance-sheet proposer). The apply_*
    # utilities still write each authored payload to model_input.
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_capex_rd_balance_seed import (  # type: ignore  # noqa: E501
      set_capex_rd_balance_seed,
    )
    capex_rd_seed_envelope = set_capex_rd_balance_seed(
      conn=conn,
      draft_id=str(draft_id or "").strip(),
      planning_run_id=str(active_planning_run_id or "").strip(),
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      financials_year1_json=copy.deepcopy(financials_year1_json or {}),
      model_input_json=copy.deepcopy(model_input_json or {}),
      finmo_json=copy.deepcopy(finmo_json or {}),
    )
    if not capex_rd_seed_envelope.get("accepted"):
      # Step 9d item 6 — FAIL_ROUND1_SET_TOOL_REJECTED
      # (set_capex_rd_balance_seed branch).
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
      )
      _rff(
        conn,
        draft_id=str(draft_id or ""),
        planning_run_id=str(active_planning_run_id or ""),
        phase=_PC.ROUND1_AUTHORING,
        code=_FFC.FAIL_ROUND1_SET_TOOL_REJECTED,
        detail=(
          f"set_capex_rd_balance_seed(contract=None) rejected: "
          f"violations={capex_rd_seed_envelope.get('violations')}"
        ),
        where="post_intake_initial_grid.runner (capex_rd round1)",
      )
    capex_rd_payload = capex_rd_seed_envelope.get("payload") or {}
    r_and_d_applicability_decision = (
      capex_rd_payload.get("r_and_d_applicability") or {}
    )
    balance_sheet_contextual_seed_decision = (
      capex_rd_payload.get("balance_sheet_seed") or {}
    )

    # Apply R&D toggle to model_input + rebuild finmo.
    model_input_json = apply_r_and_d_applicability_policy_to_model_input(
      copy.deepcopy(model_input_json or {}),
      r_and_d_enabled=bool(r_and_d_applicability_decision.get("r_and_d_enabled")),
      decision_source="set_capex_rd_balance_seed_round1",
      rationale=str(r_and_d_applicability_decision.get("rationale") or ""),
    )
    finmo_json = build_python_finmo_json(
      model_input_json=copy.deepcopy(model_input_json or {}),
    )
    # Step 9d item 5 — FAIL_MIRROR_FINMO_BASELINE_BUILD. The baseline
    # FINMO is the input to mirror_build's plan_state / bands lookup;
    # an empty or non-dict baseline means a malformed model_input made
    # it past r_and_d toggle, and continuing would feed the session
    # garbage state.
    if not isinstance(finmo_json, dict) or not finmo_json:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        FailFastCode, PhaseCode as _PC, raise_fail_fast,
      )
      raise_fail_fast(
        conn,
        draft_id=str(draft_id or ""), planning_run_id=str(planning_run_id or ""),
        phase=_PC.MIRROR_BUILD,
        code=FailFastCode.FAIL_MIRROR_FINMO_BASELINE_BUILD,
        detail=(
          f"build_python_finmo_json returned {type(finmo_json).__name__} "
          f"after r_and_d apply (stage=baseline_ready_before_planning_mode)"
        ),
        where="post_intake_initial_grid.runner (baseline finmo rebuild)",
      )
    shared_context["r_and_d_applicability_decision"] = {
      key: copy.deepcopy(value)
      for key, value in r_and_d_applicability_decision.items()
      if key not in {"prompt_context", "raw_openai_response"}
    }
    assert_r_and_d_applicability_policy_applied(
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      stage="baseline_ready_before_planning_mode",
    )

    # Apply balance-sheet contextual seed + rebuild finmo.
    model_input_json = apply_balance_sheet_contextual_seed_to_model_input(
      copy.deepcopy(model_input_json or {}),
      copy.deepcopy(balance_sheet_contextual_seed_decision or {}),
      live_count=20,
    )
    finmo_json = build_python_finmo_json(
      model_input_json=copy.deepcopy(model_input_json or {}),
    )
    shared_context["balance_sheet_contextual_seed_decision"] = {
      key: copy.deepcopy(value)
      for key, value in balance_sheet_contextual_seed_decision.items()
      if key not in {"prompt_context", "raw_openai_response"}
    }
    planning_context_summary_json = refresh_planning_context_summary(
      current_model_input_json=model_input_json,
    )
    if isinstance(planning_context_summary_json, dict):
      planning_context_summary_json["r_and_d_applicability"] = {
        key: copy.deepcopy(value)
        for key, value in r_and_d_applicability_decision.items()
        if key not in {"prompt_context", "raw_openai_response"}
      }
      planning_context_summary_json["balance_sheet_contextual_seed"] = {
        key: copy.deepcopy(value)
        for key, value in balance_sheet_contextual_seed_decision.items()
        if key not in {"prompt_context", "raw_openai_response"}
      }
    persist_system_stage(
      stage="balance_sheet_contextual_seed_applied",
      status="running",
      model_input_payload=model_input_json,
      finmo_payload=finmo_json,
    )

  planning_choice = _execute_sequence_step(
    "planning_mode_determination",
    determine_planning_mode,
    runtime_context=_runtime_context(
      current_model_input_json=model_input_json,
      current_finmo_json=finmo_json,
      extra={
        "balance_sheet_contextual_seed": copy.deepcopy(balance_sheet_contextual_seed_decision or {}),
        "shared_context": copy.deepcopy(shared_context),
      },
    ),
    handler_kwargs={
      "ops_json": dict(ops_json or {}),
      "target_market_json": dict(market_json or {}),
      "people_json": dict(people_json or {}),
      "financials_json": dict(financials_json or {}),
      "financials_year1_json": dict(financials_year1_json or {}),
      "fulfillment_json": dict(fulfillment_json or {}),
      "marketing_model_json": dict(marketing_model_json or {}),
      "model_input_json": copy.deepcopy(model_input_json),
      "finmo_json": copy.deepcopy(finmo_json),
      "business_facts": copy.deepcopy(business_facts or {}),
    },
    expected_phase="pre_convergence",
    expected_handler_key="determine_planning_mode",
    required_horizon_rule="single_pre_convergence_planning_mode_decision",
  )
  planning_mode = str(planning_choice.get("planning_mode") or "").strip()
  planning_mode_reason = str(planning_choice.get("planning_mode_reason") or "").strip()
  planning_context_summary_json = refresh_planning_context_summary(
    current_model_input_json=model_input_json,
    planning_mode_value=planning_mode,
    planning_mode_reason_value=planning_mode_reason,
    prompt_file_value=str(planning_choice.get("prompt_file") or "").strip(),
  )
  r_and_d_applicability_decision_for_ramp = copy.deepcopy(
    r_and_d_policy_from_model_input(model_input_json)
  )
  if (
    isinstance(r_and_d_applicability_decision_for_ramp, dict)
    and not str(r_and_d_applicability_decision_for_ramp.get("contract_version") or "").strip()
    and str(r_and_d_applicability_decision_for_ramp.get("policy_version") or "").strip()
  ):
    r_and_d_applicability_decision_for_ramp["contract_version"] = str(
      r_and_d_applicability_decision_for_ramp.get("policy_version") or ""
    ).strip()
  if isinstance(planning_context_summary_json, dict):
    planning_context_summary_json["r_and_d_applicability"] = copy.deepcopy(
      r_and_d_applicability_decision_for_ramp
    )
  # P3.33 Phase 3 8b-fix — REPLACE the legacy _execute_sequence_step
  # call for stage_ramp_contract with a direct set_stage_ramp_contract
  # (contract=None) call. The tool's contract=None path runs the same
  # Python-first builder (build_python_stage_ramp_contract +
  # robust_bound_stage_ramp_contract per step 3a) the existing handler
  # delegates to. The handler-on-validator-failure recovery path that
  # used to live behind estimate_stage_ramp_contract_with_gpt is now
  # the V1/V2 cascade tiers in the SessionDriver below.
  from client_intake_and_finmo.post_intake_amalgamated.tools.set_stage_ramp_contract import (  # type: ignore  # noqa: E501
    set_stage_ramp_contract,
  )
  stage_ramp_envelope = set_stage_ramp_contract(
    conn=conn,
    draft_id=str(draft_id or "").strip(),
    planning_run_id=str(active_planning_run_id or "").strip(),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    financials_year1_json=copy.deepcopy(financials_year1_json or {}),
    people_json=copy.deepcopy(people_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    r_and_d_applicability=copy.deepcopy(r_and_d_applicability_decision_for_ramp),
  )
  if not stage_ramp_envelope.get("accepted"):
    # Step 9d item 6 — FAIL_ROUND1_SET_TOOL_REJECTED
    # (set_stage_ramp_contract branch).
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
      FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
    )
    _rff(
      conn,
      draft_id=str(draft_id or ""),
      planning_run_id=str(active_planning_run_id or ""),
      phase=_PC.ROUND1_AUTHORING,
      code=_FFC.FAIL_ROUND1_SET_TOOL_REJECTED,
      detail=(
        f"set_stage_ramp_contract(contract=None) rejected: "
        f"violations={stage_ramp_envelope.get('violations')}"
      ),
      where="post_intake_initial_grid.runner (stage_ramp round1)",
    )
  stage_ramp_contract = stage_ramp_envelope.get("contract") or {}
  payroll_headcount_payload = None
  persist_system_stage(
    stage="stage_ramp_contract_applied",
    status="running",
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=str(planning_choice.get("prompt_file") or "").strip(),
    model_input_payload=model_input_json,
    finmo_payload=finmo_json,
  )
  shared_context["stage_ramp_contract_decision"] = {
    key: copy.deepcopy(value)
    for key, value in stage_ramp_contract.items()
    if key not in {"prompt_context", "raw_openai_response"}
  }
  if isinstance(planning_context_summary_json, dict):
    planning_context_summary_json["stage_ramp_contract"] = {
      key: copy.deepcopy(value)
      for key, value in stage_ramp_contract.items()
      if key not in {"prompt_context", "raw_openai_response"}
    }

  def _build_and_apply_payroll_schedule(
    *,
    current_model_input_json: Dict[str, Any],
    current_finmo_json: Dict[str, Any],
    stage_prefix: str,
  ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    # Phase 9 P3.11 — outer retry removed; inner GPT call now runs the
    # iterative refinement loop internally. The step_key is fixed at
    # "payroll_headcount_schedule" and the previous_contract_failure
    # parameter to the inner function was dropped (all feedback is
    # handled inside the loop).
    payroll_control_step_key = "payroll_headcount_schedule"
    payroll_runtime_context = _runtime_context(
      current_model_input_json=current_model_input_json,
      current_finmo_json=current_finmo_json,
      extra={
        "stage_ramp_contract": copy.deepcopy(stage_ramp_contract or {}),
        "planning_mode_decision": copy.deepcopy(planning_choice or {}),
        "payroll_headcount": copy.deepcopy(payroll_headcount_payload or {}),
        "payroll_context_payload": {
          "business_facts": copy.deepcopy(business_facts or {}),
          "business_type": str((ops_json or {}).get("business_type") or "").strip(),
          # P3.40 Cleanup 3/6 -- 5b R-a: ASSESSED + KEPT.
          # Mirror of the runtime_context fallback chain above
          # (same rationale: legacy DB support pending audit).
          "business_naics": str(
            (people_json or {}).get("business_naics_6")
            or (ops_json or {}).get("naics_code")
            or (ops_json or {}).get("business_naics")
            or ""
          ).strip(),
          "planning_mode": planning_mode,
          "planning_mode_reason": planning_mode_reason,
        },
      },
    )
    _execute_sequence_step(
      payroll_control_step_key,
      lambda: {
        "status": "payroll_sequence_started",
        "process_step_key": payroll_control_step_key,
      },
      runtime_context=payroll_runtime_context,
      expected_phase="initial_grid",
      expected_handler_key="estimate_payroll_headcount_schedule_with_gpt",
      required_contract_name="payroll_headcount_schedule",
      required_context_contract_name="payroll_headcount_schedule",
      required_context_include_phase="pre_convergence",
      required_lookup_tables=[
        "post_intake_gpt_contract_lookup",
        "post_intake_gpt_context_lookup",
        "post_intake_headcount_policy_lookup",
      ],
      required_horizon_rule="q1_to_q20_at_least_once",
    )
    payroll_context_payload = _execute_sequence_step(
      "payroll_context_build",
      lambda: copy.deepcopy(payroll_runtime_context.get("payroll_context_payload") or {}),
      runtime_context=payroll_runtime_context,
      expected_phase="initial_grid",
      expected_handler_key="build_payroll_headcount_context",
      required_context_contract_name="payroll_headcount_schedule",
      required_context_include_phase="pre_convergence",
      required_lookup_tables=[
        "post_intake_gpt_context_lookup",
        "post_intake_headcount_policy_lookup",
      ],
      required_horizon_rule="payroll_context_inputs_only_no_mutation",
    )
    payroll_lookup_payload = _execute_sequence_step(
      "payroll_oews_title_catalog",
      lambda: {
        "oews_title_catalog": {
          "source_table": "oews_state_wages",
          "resolved_by": "estimate_payroll_headcount_schedule_with_gpt",
          "business_naics": str(payroll_runtime_context.get("business_naics") or "").strip(),
        },
        "headcount_policy": {
          "source_table": "post_intake_headcount_policy_lookup",
        },
        "productivity_assumptions": {
          "source_table": "post_intake_headcount_policy_lookup",
          "selected_by": "payroll_headcount_schedule_contract",
        },
      },
      runtime_context={
        **payroll_runtime_context,
        "payroll_context_payload": copy.deepcopy(payroll_context_payload or {}),
      },
      expected_phase="initial_grid",
      expected_handler_key="load_payroll_oews_title_catalog",
      required_lookup_tables=["post_intake_headcount_policy_lookup"],
      required_horizon_rule="naics_filtered_oews_titles_before_gpt_selection",
    )
    # P3.33 Phase 3 8b-fix — REPLACE the legacy _execute_sequence_step
    # payroll authoring with a direct set_payroll_schedule(contract=None)
    # call. set_payroll_schedule's contract=None path now internally
    # invokes estimate_payroll_headcount_schedule_with_gpt (Handler C)
    # to author the contract, then validates + builds the payload.
    # See set_payroll_schedule.py — the tool became the canonical
    # orchestrator entry point for round-1 payroll authoring as part
    # of step 8b-fix.
    from client_intake_and_finmo.post_intake_amalgamated.tools.set_payroll_schedule import (  # type: ignore  # noqa: E501
      set_payroll_schedule,
    )
    payroll_envelope = set_payroll_schedule(
      conn=conn,
      draft_id=normalized_draft_id,
      planning_run_id=str(active_planning_run_id or "").strip(),
      contract=None,
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      people_json=copy.deepcopy(people_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      financials_year1_json=copy.deepcopy(financials_year1_json or {}),
      model_input_json=copy.deepcopy(current_model_input_json or {}),
      finmo_json=copy.deepcopy(current_finmo_json or {}),
      stage_ramp_contract=copy.deepcopy(stage_ramp_contract),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
    )
    if not payroll_envelope.get("accepted"):
      # Step 9d item 6 — FAIL_ROUND1_SET_TOOL_REJECTED
      # (set_payroll_schedule branch).
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
      )
      _rff(
        conn,
        draft_id=str(draft_id or ""),
        planning_run_id=str(active_planning_run_id or ""),
        phase=_PC.ROUND1_AUTHORING,
        code=_FFC.FAIL_ROUND1_SET_TOOL_REJECTED,
        detail=(
          f"set_payroll_schedule(contract=None) rejected: "
          f"violations={payroll_envelope.get('violations')}"
        ),
        where="post_intake_initial_grid.runner (payroll round1)",
      )
    # set_payroll_schedule returns either a built payload (when
    # builder ran on the validated contract) or the validated
    # contract envelope. The downstream pipeline consumes the
    # built payload as schedule_payload, matching the legacy shape.
    schedule_payload = (
      payroll_envelope.get("payload")
      or payroll_envelope.get("contract")
      or {}
    )
    # Step 9d item 7 — FAIL_ROUND1_PLAN_STATE_INCOMPLETE. After all
    # three round-1 set_* calls succeeded, the section payloads must
    # be non-empty so the SessionDriver can read them. Drivers are
    # NOT a round-1 section (set_drivers(anchors=None) is by-design
    # "amalgamated_session_pending"); the cascade authors them via
    # revise_drivers.
    _round1_state = {
      "capex_rd_balance_seed": bool(capex_rd_payload),
      "stage_ramp": bool(stage_ramp_contract),
      "payroll": bool(schedule_payload),
    }
    _missing_sections = [k for k, present in _round1_state.items() if not present]
    if _missing_sections:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        FailFastCode as _FFC, PhaseCode as _PC, raise_fail_fast as _rff,
      )
      _rff(
        conn,
        draft_id=str(draft_id or ""),
        planning_run_id=str(active_planning_run_id or ""),
        phase=_PC.ROUND1_AUTHORING,
        code=_FFC.FAIL_ROUND1_PLAN_STATE_INCOMPLETE,
        detail=(
          f"round-1 finished with empty sections={_missing_sections} "
          f"(expected non-empty: capex_rd_balance_seed, stage_ramp, payroll)"
        ),
        where="post_intake_initial_grid.runner (post-round1 completeness)",
      )
    # C6 — emit ROUND1_COMPLETED now that all three round-1 set_* calls
    # have succeeded and the completeness check passed. Drivers are
    # intentionally deferred to the cascade.
    try:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore  # noqa: E501
        EventCode as _C6EventCode, PhaseCode as _C6PhaseCode,
        Status as _C6Status, safe_emit as _c6_safe_emit,
      )
      _c6_safe_emit(
        conn,
        draft_id=str(draft_id or ""),
        planning_run_id=str(active_planning_run_id or ""),
        phase=_C6PhaseCode.ROUND1_AUTHORING,
        event_code=_C6EventCode.ROUND1_COMPLETED,
        status=_C6Status.COMPLETED,
        diagnostic_data={
          "sections_authored": list(_round1_state.keys()),
          "drivers_deferred": True,
        },
      )
    except Exception:
      pass
    payroll_horizon = int(
      post_intake_contract_forecast_horizon_quarter_count(
        contract_name="payroll_headcount_schedule",
      )
      or 0
    )
    if payroll_horizon <= 0:
      raise RuntimeError(
        "payroll_headcount_schedule_horizon_lookup_failed: "
        "post_intake_gpt_contract_lookup must define payroll_headcount_schedule horizon."
      )
    _execute_sequence_step(
      "payroll_contract_validation",
      assert_payroll_headcount_payload_ready,
      runtime_context={
        **payroll_runtime_context,
        "payroll_context_payload": copy.deepcopy(payroll_context_payload or {}),
        **copy.deepcopy(payroll_lookup_payload or {}),
        "payroll_headcount_contract": copy.deepcopy(schedule_payload or {}),
      },
      handler_kwargs={
        "payroll_headcount": copy.deepcopy(schedule_payload),
        "model_input_json": copy.deepcopy(current_model_input_json or {}),
        "stage": f"{stage_prefix}_payroll_headcount_schedule_built",
      },
      expected_phase="initial_grid",
      expected_handler_key="assert_payroll_headcount_payload_ready",
      required_lookup_tables=[
        "post_intake_gpt_contract_lookup",
        "post_intake_headcount_policy_lookup",
      ],
      required_horizon_rule="q1_to_q20_contract_and_oews_validation",
    )
    capacity_model_input_json = _execute_sequence_step(
      "payroll_capacity_derivation",
      apply_payroll_supported_capacity_to_model_input,
      runtime_context={
        **payroll_runtime_context,
        "payroll_headcount": copy.deepcopy(schedule_payload or {}),
        "productivity_assumptions": copy.deepcopy(
          (payroll_lookup_payload or {}).get("productivity_assumptions") or {}
        ),
      },
      handler_kwargs={
        "model_input_json": copy.deepcopy(current_model_input_json),
        "payroll_headcount": copy.deepcopy(schedule_payload),
        "live_count": payroll_horizon,
        "process_step_key": payroll_control_step_key,
        "control_action": "derive",
        "control_trigger": "payroll_headcount_changed",
      },
      expected_phase="initial_grid",
      expected_handler_key="apply_payroll_supported_capacity_to_model_input",
      required_horizon_rule="payroll_supported_capacity_derivation_q1_to_q20",
    )

    def _apply_payroll_model_input() -> Dict[str, Any]:
      next_model_input = apply_payroll_headcount_payload_to_model_input(
        copy.deepcopy(capacity_model_input_json),
        copy.deepcopy(schedule_payload),
        live_count=payroll_horizon,
        process_step_key=payroll_control_step_key,
        control_action="derive",
        control_trigger="payroll_headcount_changed",
      )
      next_model_input = apply_derived_driver_policies_to_model_input(
        copy.deepcopy(next_model_input),
      )
      assert_payroll_headcount_model_input_applied(
        copy.deepcopy(next_model_input),
        copy.deepcopy(schedule_payload),
        stage=f"{stage_prefix}_payroll_headcount_model_input_applied",
      )
      return next_model_input

    next_model_input_json = _execute_sequence_step(
      "payroll_model_input_application",
      _apply_payroll_model_input,
      runtime_context={
        **payroll_runtime_context,
        "payroll_headcount": copy.deepcopy(schedule_payload or {}),
        "capacity_outputs": {
          "source": "payroll_supported_capacity_applied",
          "model_input_path": "model_input_json.sections.revenue[Capacity]",
        },
        "model_input_json": copy.deepcopy(capacity_model_input_json or {}),
      },
      expected_phase="initial_grid",
      expected_handler_key="apply_payroll_headcount_payload_to_model_input",
      required_horizon_rule="payroll_expense_derivation_q1_to_q20",
    )

    def _rebuild_and_validate_payroll_finmo() -> Dict[str, Any]:
      next_finmo = build_python_finmo_json(model_input_json=copy.deepcopy(next_model_input_json))
      assert_finmo_payroll_matches_headcount_schedule(
        copy.deepcopy(next_finmo),
        copy.deepcopy(schedule_payload),
        stage=f"{stage_prefix}_payroll_headcount_finmo_rebuilt",
      )
      return next_finmo

    next_finmo_json = _execute_sequence_step(
      "payroll_finmo_rebuild_validation",
      _rebuild_and_validate_payroll_finmo,
      runtime_context={
        **payroll_runtime_context,
        "payroll_headcount": copy.deepcopy(schedule_payload or {}),
        "model_input_json": copy.deepcopy(next_model_input_json or {}),
      },
      expected_phase="initial_grid",
      expected_handler_key="assert_finmo_payroll_matches_headcount_schedule",
      required_horizon_rule="payroll_finmo_reconciliation_q1_to_q20",
    )
    shared_context["payroll_headcount_contract_decision"] = {
      "decision_source": "payroll_headcount_schedule.payroll_headcount_grid",
      "contract_version": schedule_payload.get("contract_version"),
      "schedule_horizon_quarters": schedule_payload.get("schedule_horizon_quarters"),
      "quarter_totals": copy.deepcopy(schedule_payload.get("quarter_totals") or []),
    }
    if isinstance(planning_context_summary_json, dict):
      planning_context_summary_json["payroll_headcount"] = {
        key: copy.deepcopy(value)
        for key, value in schedule_payload.items()
        if key in {"contract_version", "schedule_horizon_quarters", "quarter_totals"}
      }
    return schedule_payload, next_model_input_json, next_finmo_json

  def _apply_existing_payroll_authority(
    *,
    schedule_payload: Dict[str, Any],
    current_model_input_json: Dict[str, Any],
    current_finmo_json: Dict[str, Any],
    stage_prefix: str,
  ) -> tuple[Dict[str, Any], Dict[str, Any]]:
    payroll_horizon = int(
      post_intake_contract_forecast_horizon_quarter_count(
        contract_name="payroll_headcount_schedule",
      )
      or 0
    )
    if payroll_horizon <= 0:
      raise RuntimeError(
        "payroll_headcount_schedule_horizon_lookup_failed: "
        "post_intake_gpt_contract_lookup must define payroll_headcount_schedule horizon."
      )
    def _reapply_locked_payroll_outputs() -> Dict[str, Any]:
      capacity_model_input_json = apply_payroll_supported_capacity_to_model_input(
        copy.deepcopy(current_model_input_json),
        copy.deepcopy(schedule_payload),
        live_count=payroll_horizon,
      )
      next_model_input = apply_payroll_headcount_payload_to_model_input(
        copy.deepcopy(capacity_model_input_json),
        copy.deepcopy(schedule_payload),
        live_count=payroll_horizon,
      )
      next_model_input = apply_derived_driver_policies_to_model_input(
        copy.deepcopy(next_model_input),
      )
      assert_payroll_headcount_model_input_applied(
        copy.deepcopy(next_model_input),
        copy.deepcopy(schedule_payload),
        stage=f"{stage_prefix}_payroll_authority_reapplied",
      )
      next_finmo = build_python_finmo_json(model_input_json=copy.deepcopy(next_model_input))
      assert_finmo_payroll_matches_headcount_schedule(
        copy.deepcopy(next_finmo),
        copy.deepcopy(schedule_payload),
        stage=f"{stage_prefix}_payroll_authority_reapplied",
      )
      return {
        "model_input_json": next_model_input,
        "finmo_json": next_finmo,
      }

    payroll_reapply_result = _execute_sequence_step(
      "quarter_grid_reapply_locked_payroll",
      _reapply_locked_payroll_outputs,
      runtime_context=_runtime_context(
        current_model_input_json=current_model_input_json,
        current_finmo_json=current_finmo_json,
        extra={
          "payroll_headcount": copy.deepcopy(schedule_payload or {}),
          "capacity_outputs": {
            "source": "payroll_supported_capacity_applied",
            "model_input_path": "model_input_json.sections.revenue[Capacity]",
          },
        },
      ),
      expected_phase="initial_grid",
      expected_handler_key="reapply_payroll_authority_after_quarter_grid",
      required_horizon_rule="preserve_upstream_payroll_and_capacity_outputs",
    )
    next_model_input_json = copy.deepcopy(payroll_reapply_result.get("model_input_json") or {})
    next_finmo_json = copy.deepcopy(payroll_reapply_result.get("finmo_json") or {})
    return next_model_input_json, next_finmo_json

  if resume_from_checkpoint_state:
    planning_result = {
      "prompt_file": str(
        (resume_checkpoint_planning_payload or {}).get("prompt_file")
        or planning_choice.get("prompt_file")
        or ""
      ).strip(),
      "gpt_narrative": str((resume_checkpoint_planning_payload or {}).get("gpt_narrative") or "").strip(),
      "metadata": copy.deepcopy((resume_checkpoint_planning_payload or {}).get("gpt_grid_metadata") or {}),
    }
    grid_application_summary = copy.deepcopy(
      (resume_checkpoint_planning_payload or {}).get("grid_application_summary") or {}
    )
    applied_model_input_json = copy.deepcopy(model_input_json)
    applied_finmo_json = copy.deepcopy(finmo_json)
    payroll_headcount_payload, applied_model_input_json, applied_finmo_json = _build_and_apply_payroll_schedule(
      current_model_input_json=copy.deepcopy(applied_model_input_json),
      current_finmo_json=copy.deepcopy(applied_finmo_json),
      stage_prefix="resume_checkpoint",
    )
    assert_payroll_headcount_model_input_applied(
      copy.deepcopy(applied_model_input_json),
      copy.deepcopy(payroll_headcount_payload),
      stage="resume_checkpoint_ready",
    )
    assert_finmo_payroll_matches_headcount_schedule(
      copy.deepcopy(applied_finmo_json),
      copy.deepcopy(payroll_headcount_payload),
      stage="resume_checkpoint_ready",
    )
    _assert_global_invariants_via_sequence(
      "pre_quarter_grid_global_validation",
      model_input_payload=copy.deepcopy(applied_model_input_json),
      finmo_payload=copy.deepcopy(applied_finmo_json),
      payroll_headcount_payload=copy.deepcopy(payroll_headcount_payload),
      stage="resume_checkpoint_ready",
    )
    persist_system_stage(
      stage="resume_checkpoint_ready",
      status="running",
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=str(planning_result.get("prompt_file") or "").strip(),
      gpt_narrative=str(planning_result.get("gpt_narrative") or "").strip(),
      gpt_grid_metadata=copy.deepcopy(planning_result.get("metadata") or {}),
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      model_input_payload=applied_model_input_json,
      finmo_payload=applied_finmo_json,
      payroll_headcount_payload=payroll_headcount_payload,
    )
  else:
    # Phase 9 P3.11 — outer payroll_grid_rebuild_limit retry removed.
    # The inner estimate_payroll_headcount_schedule_with_gpt now runs
    # an iterative refinement loop (10 rounds) internally; one outer
    # invocation is all that's needed. Post-quarter-grid feasibility
    # violations are now hard-fail rather than retry-eligible
    # (intentional per the directive — quarter-grid disturbing payroll
    # feasibility surfaces a deeper issue that retrying papered over).
    payroll_headcount_payload, model_input_json, finmo_json = _build_and_apply_payroll_schedule(
      current_model_input_json=copy.deepcopy(model_input_json),
      current_finmo_json=copy.deepcopy(finmo_json),
      stage_prefix="pre_quarter_grid",
    )
    if True:
      _assert_global_invariants_via_sequence(
        "pre_quarter_grid_global_validation",
        model_input_payload=copy.deepcopy(model_input_json),
        finmo_payload=copy.deepcopy(finmo_json),
        payroll_headcount_payload=copy.deepcopy(payroll_headcount_payload),
        stage="pre_quarter_grid_payroll_ready",
      )
      quarter_grid_runtime_context = _runtime_context(
        current_model_input_json=model_input_json,
        current_finmo_json=finmo_json,
        extra={
          "stage_ramp_contract": copy.deepcopy(stage_ramp_contract or {}),
          "payroll_headcount": copy.deepcopy(payroll_headcount_payload or {}),
          "capacity_outputs": {
            "source": "payroll_supported_capacity_applied",
            "model_input_path": "model_input_json.sections.revenue[Capacity]",
          },
        },
      )
      _execute_sequence_step(
        "quarter_grid_generation",
        lambda: {
          "status": "quarter_grid_sequence_started",
          "source": "sql.post_intake_process_sequence_lookup",
        },
        runtime_context=quarter_grid_runtime_context,
        expected_phase="initial_grid",
        expected_handler_key="generate_live_quarter_grid_plan",
        required_contract_name="quarter_grid_probe",
        required_context_contract_name="quarter_grid_probe",
        required_context_include_phase="initial_grid",
        required_lookup_tables=[
          "post_intak_mapping_lookup",
          "post_intake_gpt_contract_lookup",
          "post_intake_gpt_context_lookup",
        ],
        required_horizon_rule="q1_to_q20_model_input_state",
      )
      quarter_grid_context_payload = _execute_sequence_step(
        "quarter_grid_context_build",
        lambda: {
          "business_facts": copy.deepcopy(business_facts or {}),
          "planning_mode": planning_mode,
          "stage_ramp_contract": copy.deepcopy(stage_ramp_contract or {}),
          "payroll_headcount": copy.deepcopy(payroll_headcount_payload or {}),
          "capacity_outputs": copy.deepcopy(quarter_grid_runtime_context.get("capacity_outputs") or {}),
        },
        runtime_context=quarter_grid_runtime_context,
        expected_phase="initial_grid",
        expected_handler_key="build_quarter_grid_context",
        required_context_contract_name="quarter_grid_probe",
        required_context_include_phase="initial_grid",
        required_lookup_tables=["post_intake_gpt_context_lookup"],
        required_horizon_rule="quarter_grid_context_inputs_only_no_mutation",
      )
      persist_system_stage(
        stage="quarter_grid_running",
        status="running",
        planning_mode=planning_mode,
        planning_mode_reason=planning_mode_reason,
        prompt_file=str(planning_choice.get("prompt_file") or "").strip(),
        model_input_payload=model_input_json,
        finmo_payload=finmo_json,
        payroll_headcount_payload=payroll_headcount_payload,
      )
      planning_result = _execute_sequence_step(
        "quarter_grid_gpt_plan",
        generate_live_quarter_grid_plan,
        runtime_context={
          **quarter_grid_runtime_context,
          "quarter_grid_context_payload": copy.deepcopy(quarter_grid_context_payload or {}),
        },
        handler_kwargs={
          "business_name": str(business_facts.get("name") or "").strip(),
          "planning_mode": planning_mode,
          "model_input_json": copy.deepcopy(model_input_json),
          "finmo_json": copy.deepcopy(finmo_json),
          "ops_json": ops_json,
          "target_market_json": market_json,
          "people_json": people_json,
          "financials_json": financials_json,
          "financials_year1_json": financials_year1_json,
          "fulfillment_json": fulfillment_json,
          "marketing_model_json": marketing_model_json,
          "realism_memo_json": parse_json_dict(draft.get("realism_memo_json")),
          "business_facts": copy.deepcopy(business_facts or {}),
          "stage_ramp_contract": copy.deepcopy(stage_ramp_contract),
        },
        expected_phase="initial_grid",
        expected_handler_key="generate_live_quarter_grid_plan",
        required_contract_name="quarter_grid_probe",
        required_context_contract_name="quarter_grid_probe",
        required_context_include_phase="initial_grid",
        required_lookup_tables=[
          "post_intake_gpt_contract_lookup",
          "post_intake_gpt_context_lookup",
        ],
        required_horizon_rule="q1_to_q20_model_input_state",
      )

      def _validate_quarter_grid_plan() -> Dict[str, Any]:
        validation_payload = (
          planning_result.get("validation")
          if isinstance(planning_result.get("validation"), dict)
          else {}
        )
        if (
          list(validation_payload.get("missing_rows") or [])
          or list(validation_payload.get("extra_rows") or [])
          or list(validation_payload.get("duplicate_rows") or [])
          or list(validation_payload.get("malformed_rows") or [])
        ):
          raise RuntimeError("planning_grid_validation_failed")
        return {
          "validated": True,
          "validation": copy.deepcopy(validation_payload),
          "grid_json": copy.deepcopy(planning_result.get("grid_json") or {}),
        }

      validated_quarter_grid_plan = _execute_sequence_step(
        "quarter_grid_validation",
        _validate_quarter_grid_plan,
        runtime_context={
          **quarter_grid_runtime_context,
          "quarter_grid_context_payload": copy.deepcopy(quarter_grid_context_payload or {}),
          "quarter_grid_plan": copy.deepcopy(planning_result or {}),
        },
        expected_phase="initial_grid",
        expected_handler_key="validate_live_quarter_grid_plan",
        required_lookup_tables=["post_intake_gpt_contract_lookup"],
        required_horizon_rule="q1_to_q20_quarter_grid_contract_validation",
      )
      persist_system_stage(
        stage="quarter_grid_ready",
        status="ready_for_grid_application",
        planning_mode=planning_mode,
        planning_mode_reason=planning_mode_reason,
        prompt_file=str(planning_result.get("prompt_file") or "").strip(),
        gpt_narrative=str(planning_result.get("gpt_narrative") or "").strip(),
        gpt_grid_metadata=copy.deepcopy(planning_result.get("metadata") or {}),
        model_input_payload=model_input_json,
        finmo_payload=finmo_json,
        payroll_headcount_payload=payroll_headcount_payload,
      )
      assert_r_and_d_applicability_policy_applied(
        model_input_json=model_input_json,
        finmo_json=finmo_json,
        planning_result=planning_result,
        stage="quarter_grid_ready",
      )
      grid_application_result = _execute_sequence_step(
        "quarter_grid_apply_model_input",
        apply_live_quarter_grid_plan,
        runtime_context={
          **quarter_grid_runtime_context,
          "quarter_grid_plan": copy.deepcopy(planning_result or {}),
          "validated_quarter_grid_plan": copy.deepcopy(validated_quarter_grid_plan or {}),
        },
        handler_kwargs={
          "baseline_model_input_json": copy.deepcopy(model_input_json),
          "grid_json": copy.deepcopy(planning_result.get("grid_json") or {}),
        },
        expected_phase="initial_grid",
        expected_handler_key="apply_live_quarter_grid_plan",
        required_horizon_rule="q1_to_q20_model_input_application",
      )
      grid_application_summary = (
        grid_application_result.get("application_summary")
        if isinstance(grid_application_result.get("application_summary"), dict)
        else {}
      )
      applied_model_input_json = (
        grid_application_result.get("applied_model_input_json")
        if isinstance(grid_application_result.get("applied_model_input_json"), dict)
        else {}
      )
      applied_finmo_json = (
        grid_application_result.get("applied_finmo_json")
        if isinstance(grid_application_result.get("applied_finmo_json"), dict)
        else {}
      )
      applied_model_input_json, applied_finmo_json = _apply_existing_payroll_authority(
        schedule_payload=copy.deepcopy(payroll_headcount_payload),
        current_model_input_json=copy.deepcopy(applied_model_input_json),
        current_finmo_json=copy.deepcopy(applied_finmo_json),
        stage_prefix="quarter_grid_applied",
      )
      assert_payroll_headcount_model_input_applied(
        copy.deepcopy(applied_model_input_json),
        copy.deepcopy(payroll_headcount_payload),
        stage="quarter_grid_applied",
      )
      assert_finmo_payroll_matches_headcount_schedule(
        copy.deepcopy(applied_finmo_json),
        copy.deepcopy(payroll_headcount_payload),
        stage="quarter_grid_applied",
      )
      assert_r_and_d_applicability_policy_applied(
        model_input_json=applied_model_input_json,
        finmo_json=applied_finmo_json,
        stage="quarter_grid_applied",
      )
      # P3.26 Site A: route payroll feasibility failures back to
      # Handler C (single-shot; Handler C's internal 10-round loop
      # IS the retry). Doctrine §6: Handler C is canonical for
      # payroll dollars; re-authoring through it preserves Mirror
      # Flavor 1 alignment across all four payroll surfaces. After
      # repair, re-run the same check; if still failing, hard-fail
      # propagates with full diagnostic.
      from client_intake_and_finmo.fail_fast.common import FailFastError  # type: ignore
      from client_intake_and_finmo.post_intake_headcount.feasibility_repair import (  # type: ignore
        is_payroll_feasibility_failure,
        route_payroll_feasibility_to_handler_c,
      )
      _live_count_for_repair = max(
        0,
        len([p for p in (applied_model_input_json.get("periods") or [])
             if isinstance(p, dict) and not bool(p.get("is_stub"))]),
      )
      try:
        _assert_global_invariants_via_sequence(
          "quarter_grid_global_validation",
          model_input_payload=copy.deepcopy(applied_model_input_json),
          finmo_payload=copy.deepcopy(applied_finmo_json),
          payroll_headcount_payload=copy.deepcopy(payroll_headcount_payload),
          stage="quarter_grid_applied",
        )
      except FailFastError as _site_a_exc:
        if not is_payroll_feasibility_failure(_site_a_exc):
          raise
        payroll_headcount_payload, applied_model_input_json, applied_finmo_json = (
          route_payroll_feasibility_to_handler_c(
            failure_code=str(getattr(_site_a_exc, "code", "") or ""),
            failure_message=str(_site_a_exc),
            failure_stage=str(getattr(_site_a_exc, "stage", "") or ""),
            failure_details=copy.deepcopy(getattr(_site_a_exc, "details", {}) or {}),
            business_facts=business_facts or {},
            ops_json=ops_json or {},
            people_json=people_json or {},
            financials_json=financials_json or {},
            financials_year1_json=financials_year1_json or {},
            planning_mode=planning_mode,
            planning_mode_reason=planning_mode_reason,
            model_input_json=applied_model_input_json,
            finmo_json=applied_finmo_json,
            payroll_headcount=payroll_headcount_payload or {},
            stage_ramp_contract=stage_ramp_contract or {},
            draft_id=normalized_draft_id,
            client_id=str(draft.get("client_id") or "").strip(),
            live_count=_live_count_for_repair,
            stage_prefix="quarter_grid_payroll_feasibility_repair",
          )
        )
        # Re-run the same check; persists hard-fail propagation if
        # Handler C's re-author still can't satisfy the policy.
        _assert_global_invariants_via_sequence(
          "quarter_grid_global_validation",
          model_input_payload=copy.deepcopy(applied_model_input_json),
          finmo_payload=copy.deepcopy(applied_finmo_json),
          payroll_headcount_payload=copy.deepcopy(payroll_headcount_payload),
          stage="quarter_grid_applied_after_feasibility_repair",
        )

  # P3.33 Phase 3 8b-fix — amalgamated restructure session.
  #
  # Round-1 authoring has produced applied_model_input_json +
  # applied_finmo_json via the four set_*(contract=None) calls earlier
  # in this function (REPLACE pattern per the step-8 design discussion
  # Q2 reframing — no _execute_sequence_step legacy authoring path
  # remains). The mirror is built AFTER round-1 with the complete
  # plan_state snapshot, then SessionDriver runs the §5 restructure
  # protocol over it: evaluate_plan classifies failures, the cascade
  # revises sections in §7.1 priority order, floor primitives
  # guarantee a committed in-bounds plan on cascade exhaustion.
  #
  # FAIL-FAST: no try/except wrapper here. driver_run_with_audit_
  # wrapper raises RuntimeError(amalgamated_session_failed_
  # catastrophically: ...) on unhandled driver exceptions; that
  # propagates through prepare_initial_grid_for_draft as a
  # planning_run failure (matching the existing initial-grid failure-
  # handling pattern). The audit row has already landed inside the
  # wrapper's best-effort log_restructure call.
  from client_intake_and_finmo.post_intake_amalgamated.mirror import (  # type: ignore  # noqa: E501
    build_mirror,
  )
  from client_intake_and_finmo.post_intake_amalgamated.protocol.session_factory import (  # type: ignore  # noqa: E501
    driver_run_with_audit_wrapper,
    make_session_driver,
  )
  amalgamated_plan_state = {
    "stage_ramp": copy.deepcopy(stage_ramp_contract or {}),
    "payroll": copy.deepcopy(payroll_headcount_payload or {}),
    "capex_rd_balance_seed": copy.deepcopy(
      (shared_context or {}).get("balance_sheet_contextual_seed_decision") or {}
    ),
    "balance_sheet": copy.deepcopy(
      (shared_context or {}).get("balance_sheet_contextual_seed_decision") or {}
    ),
    "drivers": {},
  }
  amalgamated_business_facts = copy.deepcopy(business_facts or {})
  amalgamated_mirror = build_mirror(
    conn,
    draft_id=str(draft_id or "").strip(),
    planning_run_id=str(active_planning_run_id or "").strip(),
    business_facts=amalgamated_business_facts,
    ops_json=copy.deepcopy(ops_json or {}),
    plan_state=amalgamated_plan_state,
    load_bands=True,
  )
  amalgamated_operating_context = {
    "model_input_template": copy.deepcopy(applied_model_input_json or {}),
    "build_finmo": build_python_finmo_json,
    "stage_ramp_contract": copy.deepcopy(stage_ramp_contract or {}),
  }
  amalgamated_driver = make_session_driver(
    conn=conn,
    draft_id=str(draft_id or "").strip(),
    planning_run_id=str(active_planning_run_id or "").strip(),
    mirror=amalgamated_mirror,
    operating_context=amalgamated_operating_context,
    business_facts=amalgamated_business_facts,
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    financials_year1_json=copy.deepcopy(financials_year1_json or {}),
    model_input_json=copy.deepcopy(applied_model_input_json or {}),
    finmo_json=copy.deepcopy(applied_finmo_json or {}),
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract or {}),
    build_finmo=build_python_finmo_json,
  )
  amalgamated_result = driver_run_with_audit_wrapper(
    driver=amalgamated_driver, conn=conn,
  )
  if isinstance(shared_context, dict):
    shared_context["amalgamated_session_result"] = {
      "termination_state": amalgamated_result.termination_state,
      "evaluate_plan_round_count": amalgamated_result.evaluate_plan_round_count,
      "budget_remaining": amalgamated_result.budget_remaining,
      "applied_steps": amalgamated_result.applied_steps,
      "floor_invocations": amalgamated_result.floor_invocations,
      "termination_detail": amalgamated_result.termination_detail,
    }

  # P3.40 Contract 1 Commit 3 — producer-side boundary enforcement.
  # Validate `applied_model_input_json` against FinmoModelInputContract
  # before handing it to `run_target_seeking_orchestrated_system_run`
  # (which will mutate it further via feasibility restoration and the
  # cascade). Raises ContractViolation with stage tag
  # "AMALGAMATED_SESSION→MODEL_INPUT" on shape failure; emits a
  # diagnostic event on success (MODEL_INPUT_CONTRACT_VALIDATED with
  # side="producer"). Consumer-side mirror lands at
  # `build_python_finmo_json` entry in Commit 4.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore
    SIDE_PRODUCER,
    make_boundary_emitter,
    validate_model_input_at_boundary,
  )
  _boundary_emitter = make_boundary_emitter(
    conn=conn,
    draft_id=str(draft_id or "").strip(),
    planning_run_id=str(active_planning_run_id or "").strip(),
  )
  validate_model_input_at_boundary(
    copy.deepcopy(applied_model_input_json or {}),
    side=SIDE_PRODUCER,
    emit_diagnostic_fn=_boundary_emitter,
  )

  # P3.40 Contract 3 Commit 3 -- producer-side boundary enforcement
  # for SolverInputContract (Boundary 5: MODEL_INPUT -> SOLVER).
  # Second validate call in this function: Contract 1's gate above
  # validates `applied_model_input_json` only; this gate validates
  # the disjoint set of 18 other solver-bundle fields plus
  # composing Contract 1 for applied_model_input_json + Contract 2
  # for applied_finmo_json / stage_ramp_contract / payroll_headcount.
  # Structurally clean per spec Div-2: one gate per contract, no
  # merge.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore
    validate_solver_input_at_boundary,
  )
  _solver_bundle_for_gate = {
    "draft_id": str(draft_id or "").strip(),
    "planning_run_id": str(active_planning_run_id or "").strip(),
    "business_facts": copy.deepcopy(business_facts or {}),
    "planning_context_summary_json": (
      copy.deepcopy(planning_context_summary_json or {}) or None
    ),
    "ops_json": copy.deepcopy(ops_json or {}),
    "target_market_json": copy.deepcopy(market_json or {}),
    "people_json": copy.deepcopy(people_json or {}),
    "financials_json": copy.deepcopy(financials_json or {}),
    "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
    "fulfillment_json": copy.deepcopy(fulfillment_json or {}),
    "marketing_model_json": copy.deepcopy(marketing_model_json or {}),
    "planning_mode": planning_mode,
    "planning_mode_reason": planning_mode_reason,
    "planning_result": copy.deepcopy(planning_result or {}),
    "grid_application_summary": (
      copy.deepcopy(grid_application_summary or {}) or None
    ),
    "catalog_source_model_input_json": copy.deepcopy(model_input_json),
    "applied_model_input_json": copy.deepcopy(applied_model_input_json),
    "applied_finmo_json": copy.deepcopy(applied_finmo_json),
    "stage_ramp_contract": (
      copy.deepcopy(stage_ramp_contract) if stage_ramp_contract else None
    ),
    "payroll_headcount": (
      copy.deepcopy(payroll_headcount_payload)
      if payroll_headcount_payload
      else None
    ),
  }
  validate_solver_input_at_boundary(
    _solver_bundle_for_gate,
    side=SIDE_PRODUCER,
    emit_diagnostic_fn=_boundary_emitter,
  )

  return {
    "planning_run_id": active_planning_run_id,
    "draft": copy.deepcopy(draft),
    "business_facts": copy.deepcopy(business_facts or {}),
    "planning_context_summary_json": copy.deepcopy(planning_context_summary_json or {}),
    "ops_json": copy.deepcopy(ops_json or {}),
    "target_market_json": copy.deepcopy(market_json or {}),
    "people_json": copy.deepcopy(people_json or {}),
    "financials_json": copy.deepcopy(financials_json or {}),
    "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
    "fulfillment_json": copy.deepcopy(fulfillment_json or {}),
    "marketing_model_json": copy.deepcopy(marketing_model_json or {}),
    "planning_mode": planning_mode,
    "planning_mode_reason": planning_mode_reason,
    "planning_result": copy.deepcopy(planning_result or {}),
    "grid_application_summary": copy.deepcopy(grid_application_summary or {}),
    "catalog_source_model_input_json": copy.deepcopy(model_input_json),
    "applied_model_input_json": copy.deepcopy(applied_model_input_json),
    "applied_finmo_json": copy.deepcopy(applied_finmo_json),
    "stage_ramp_contract": copy.deepcopy(stage_ramp_contract),
    "payroll_headcount": copy.deepcopy(payroll_headcount_payload),
    "post_intake_process_sequence_trace": copy.deepcopy(sequence_trace),
    "shared_context": copy.deepcopy(shared_context or {}),
  }
