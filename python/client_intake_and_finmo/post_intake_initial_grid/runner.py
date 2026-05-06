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
  except Exception:
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
  if maintenance_rate < 0.02 or maintenance_rate > 0.15:
    raise RuntimeError(
      f"maintenance_capex_percent_maintenance_rate_invalid: GPT returned invalid maintenance_rate={maintenance_rate!r}; expected 0.02 <= rate <= 0.15."
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
    r_and_d_applicability_decision = _execute_sequence_step(
      "r_and_d_applicability",
      estimate_r_and_d_applicability_with_gpt,
      runtime_context=_runtime_context(
        current_model_input_json=model_input_json,
        current_finmo_json=finmo_json,
        extra={"shared_context": copy.deepcopy(shared_context)},
      ),
      handler_kwargs={
        "business_facts": copy.deepcopy(business_facts or {}),
        "ops_json": copy.deepcopy(ops_json or {}),
        "financials_json": copy.deepcopy(financials_json or {}),
        "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
        "model_input_json": copy.deepcopy(model_input_json or {}),
      },
      expected_phase="pre_convergence",
      expected_handler_key="estimate_r_and_d_applicability_with_gpt",
      required_contract_name="r_and_d_applicability",
      required_lookup_tables=["post_intake_gpt_contract_lookup"],
      required_horizon_rule="single_pre_convergence_toggle",
    )
    def _apply_r_and_d_policy() -> Dict[str, Any]:
      next_model_input = apply_r_and_d_applicability_policy_to_model_input(
        copy.deepcopy(model_input_json or {}),
        r_and_d_enabled=bool(r_and_d_applicability_decision.get("r_and_d_enabled")),
        decision_source="gpt_pre_forecast",
        rationale=str(r_and_d_applicability_decision.get("rationale") or ""),
      )
      return {
        "model_input_json": next_model_input,
        "finmo_json": build_python_finmo_json(model_input_json=copy.deepcopy(next_model_input)),
      }

    r_and_d_policy_result = _execute_sequence_step(
      "r_and_d_policy_application",
      _apply_r_and_d_policy,
      runtime_context=_runtime_context(
        current_model_input_json=model_input_json,
        current_finmo_json=finmo_json,
        extra={
          "r_and_d_applicability": copy.deepcopy(r_and_d_applicability_decision or {}),
          "shared_context": copy.deepcopy(shared_context),
        },
      ),
      expected_phase="pre_convergence",
      expected_handler_key="apply_r_and_d_applicability_policy_to_model_input",
      required_horizon_rule="apply_single_pre_convergence_r_and_d_toggle",
    )
    model_input_json = copy.deepcopy(r_and_d_policy_result.get("model_input_json") or {})
    finmo_json = copy.deepcopy(r_and_d_policy_result.get("finmo_json") or {})
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
    balance_sheet_contextual_seed_decision = _execute_sequence_step(
      "balance_sheet_contextual_seed",
      estimate_balance_sheet_contextual_seed_with_gpt,
      runtime_context=_runtime_context(
        current_model_input_json=model_input_json,
        current_finmo_json=finmo_json,
        extra={
          "r_and_d_applicability": copy.deepcopy(r_and_d_applicability_decision or {}),
          "shared_context": copy.deepcopy(shared_context),
        },
      ),
      handler_kwargs={
        "business_facts": copy.deepcopy(business_facts or {}),
        "ops_json": copy.deepcopy(ops_json or {}),
        "financials_json": copy.deepcopy(financials_json or {}),
        "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
        "model_input_json": copy.deepcopy(model_input_json or {}),
        "finmo_json": copy.deepcopy(finmo_json or {}),
      },
      expected_phase="pre_convergence",
      expected_handler_key="estimate_balance_sheet_contextual_seed_with_gpt",
      required_contract_name="balance_sheet_contextual_seed",
      required_context_contract_name="balance_sheet_contextual_seed",
      required_context_include_phase="pre_convergence",
      required_lookup_tables=[
        "post_intak_mapping_lookup",
        "post_intake_gpt_contract_lookup",
        "post_intake_gpt_context_lookup",
      ],
      required_horizon_rule="single_pre_convergence_balance_sheet_driver_seed",
    )

    def _apply_balance_sheet_seed() -> Dict[str, Any]:
      next_model_input = apply_balance_sheet_contextual_seed_to_model_input(
        copy.deepcopy(model_input_json or {}),
        copy.deepcopy(balance_sheet_contextual_seed_decision or {}),
        live_count=20,
      )
      return {
        "model_input_json": next_model_input,
        "finmo_json": build_python_finmo_json(model_input_json=copy.deepcopy(next_model_input)),
      }

    balance_sheet_seed_result = _execute_sequence_step(
      "balance_sheet_seed_application",
      _apply_balance_sheet_seed,
      runtime_context=_runtime_context(
        current_model_input_json=model_input_json,
        current_finmo_json=finmo_json,
        extra={
          "balance_sheet_contextual_seed": copy.deepcopy(balance_sheet_contextual_seed_decision or {}),
          "shared_context": copy.deepcopy(shared_context),
        },
      ),
      expected_phase="pre_convergence",
      expected_handler_key="apply_balance_sheet_contextual_seed_to_model_input",
      required_horizon_rule="apply_balance_sheet_contextual_seed_to_model_input",
    )
    model_input_json = copy.deepcopy(balance_sheet_seed_result.get("model_input_json") or {})
    finmo_json = copy.deepcopy(balance_sheet_seed_result.get("finmo_json") or {})
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
  stage_ramp_contract = _execute_sequence_step(
    "stage_ramp_contract",
    estimate_stage_ramp_contract_with_gpt,
    runtime_context=_runtime_context(
      current_model_input_json=model_input_json,
      current_finmo_json=finmo_json,
      extra={
        "r_and_d_applicability": copy.deepcopy(r_and_d_applicability_decision_for_ramp),
        "balance_sheet_contextual_seed": copy.deepcopy(balance_sheet_contextual_seed_decision or {}),
        "planning_mode_decision": copy.deepcopy(planning_choice or {}),
        "shared_context": copy.deepcopy(shared_context),
      },
    ),
    handler_kwargs={
      "business_facts": copy.deepcopy(business_facts or {}),
      "ops_json": copy.deepcopy(ops_json or {}),
      "people_json": copy.deepcopy(people_json or {}),
      "financials_json": copy.deepcopy(financials_json or {}),
      "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
      "planning_mode": planning_mode,
      "planning_mode_reason": planning_mode_reason,
      "model_input_json": copy.deepcopy(model_input_json or {}),
      "finmo_json": copy.deepcopy(finmo_json or {}),
      "r_and_d_applicability": copy.deepcopy(r_and_d_applicability_decision_for_ramp),
    },
    expected_phase="pre_convergence",
    expected_handler_key="estimate_stage_ramp_contract_with_gpt",
    required_contract_name="stage_ramp_contract",
    required_context_contract_name="stage_ramp_contract",
    required_context_include_phase="pre_convergence",
    required_lookup_tables=[
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
    ],
    required_horizon_rule="q1_to_q20_exactly_once",
  )
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
    previous_contract_failure: Optional[Dict[str, Any]] = None,
  ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    payroll_control_step_key = (
      "payroll_feasibility_repair"
      if isinstance(previous_contract_failure, dict) and previous_contract_failure
      else "payroll_headcount_schedule"
    )
    payroll_runtime_context = _runtime_context(
      current_model_input_json=current_model_input_json,
      current_finmo_json=current_finmo_json,
      extra={
        "stage_ramp_contract": copy.deepcopy(stage_ramp_contract or {}),
        "planning_mode_decision": copy.deepcopy(planning_choice or {}),
        "previous_contract_failure": copy.deepcopy(previous_contract_failure or {}),
        "payroll_headcount": copy.deepcopy(payroll_headcount_payload or {}),
        "payroll_context_payload": {
          "business_facts": copy.deepcopy(business_facts or {}),
          "business_type": str((ops_json or {}).get("business_type") or "").strip(),
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
      expected_handler_key=(
        "retry_payroll_headcount_schedule_from_feasibility_failure"
        if payroll_control_step_key == "payroll_feasibility_repair"
        else "estimate_payroll_headcount_schedule_with_gpt"
      ),
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
    schedule_payload = _execute_sequence_step(
      "payroll_gpt_contract_request",
      estimate_payroll_headcount_schedule_with_gpt,
      runtime_context={
        **payroll_runtime_context,
        "payroll_context_payload": copy.deepcopy(payroll_context_payload or {}),
        **copy.deepcopy(payroll_lookup_payload or {}),
      },
      handler_kwargs={
        "business_facts": copy.deepcopy(business_facts or {}),
        "ops_json": copy.deepcopy(ops_json or {}),
        "people_json": copy.deepcopy(people_json or {}),
        "financials_json": copy.deepcopy(financials_json or {}),
        "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
        "planning_mode": planning_mode,
        "planning_mode_reason": planning_mode_reason,
        "model_input_json": copy.deepcopy(current_model_input_json or {}),
        "finmo_json": copy.deepcopy(current_finmo_json or {}),
        "stage_ramp_contract": copy.deepcopy(stage_ramp_contract),
        "draft_id": normalized_draft_id,
        "client_id": str(draft.get("client_id") or "").strip(),
        "previous_contract_failure": copy.deepcopy(previous_contract_failure or {}),
      },
      expected_phase="initial_grid",
      expected_handler_key="estimate_payroll_headcount_schedule_with_gpt",
      required_contract_name="payroll_headcount_schedule",
      required_context_contract_name="payroll_headcount_schedule",
      required_context_include_phase="pre_convergence",
      required_lookup_tables=[
        "post_intake_gpt_contract_lookup",
        "post_intake_gpt_context_lookup",
      ],
      required_horizon_rule="q1_to_q20_oews_title_fte_contract",
    )
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
    payroll_feasibility_failure: Dict[str, Any] = {}
    payroll_sequence_row = post_intake_process_sequence_step("payroll_headcount_schedule", required=True) or {}
    payroll_grid_rebuild_limit = max(1, int(payroll_sequence_row.get("max_attempts") or 1))
    for payroll_grid_attempt in range(1, payroll_grid_rebuild_limit + 1):
      payroll_headcount_payload, model_input_json, finmo_json = _build_and_apply_payroll_schedule(
        current_model_input_json=copy.deepcopy(model_input_json),
        current_finmo_json=copy.deepcopy(finmo_json),
        stage_prefix="pre_quarter_grid",
        previous_contract_failure=copy.deepcopy(payroll_feasibility_failure),
      )
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
      try:
        _assert_global_invariants_via_sequence(
          "quarter_grid_global_validation",
          model_input_payload=copy.deepcopy(applied_model_input_json),
          finmo_payload=copy.deepcopy(applied_finmo_json),
          payroll_headcount_payload=copy.deepcopy(payroll_headcount_payload),
          stage="quarter_grid_applied",
        )
        break
      except Exception as exc:
        failure_text = str(exc)
        if (
          payroll_grid_attempt < payroll_grid_rebuild_limit
          and (
            "payroll_revenue_economic_feasibility_failed" in failure_text
            or "payroll_stage_profitability_feasibility_failed" in failure_text
          )
        ):
          payroll_violation_rows = payroll_revenue_feasibility_violations(
            payroll_headcount=copy.deepcopy(payroll_headcount_payload),
            finmo_json=copy.deepcopy(applied_finmo_json),
          )
          payroll_feasibility_failure = {
            "error": failure_text[:6000],
            "attempt": payroll_grid_attempt,
            "failed_state_source": "quarter_grid_applied_model_input_and_finmo",
            "payroll_revenue_feasibility_violations": copy.deepcopy(payroll_violation_rows[:20]),
            "required_rebuild": (
              "Rebuild payroll_headcount_schedule from GPT's OEWS role/FTE/productivity contract, "
              "then rederive payroll-supported Capacity, rerun quarter-grid revenue drivers, and rebuild FINMO."
            ),
          }
          model_input_json = copy.deepcopy(applied_model_input_json)
          finmo_json = copy.deepcopy(applied_finmo_json)
          continue
        raise

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
