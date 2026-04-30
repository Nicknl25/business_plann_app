"""Initial grid orchestration for post-intake planning.

This module owns the baseline -> planning mode -> ramp -> quarter-grid phase.
The API handler should call this phase and then hand the returned state to the
post-grid convergence runner.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional


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
  r_and_d_policy_version: str,
  assert_r_and_d_applicability_policy_applied: Callable[..., None],
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

  try:
    from financials_consultant import estimate_marketing_baseline_from_context  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_consultant import estimate_marketing_baseline_from_context  # type: ignore
  try:
    from financials_year1 import assemble_financials_year1  # type: ignore
  except Exception:
    from client_intake_and_finmo.financials_year1 import assemble_financials_year1  # type: ignore
  try:
    from finmo_bridge import (  # type: ignore
      apply_r_and_d_applicability_policy_to_model_input,
      build_python_finmo_json,
      sync_planning_state_to_finmo,
    )
  except Exception:
    from client_intake_and_finmo.finmo_bridge import (  # type: ignore
      apply_r_and_d_applicability_policy_to_model_input,
      build_python_finmo_json,
      sync_planning_state_to_finmo,
    )
  try:
    from quarter_grid import determine_planning_mode, generate_live_quarter_grid_plan, apply_live_quarter_grid_plan  # type: ignore
  except Exception:
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

  shared_context = build_shared_context(conn, draft_id=normalized_draft_id)
  shared_context = dict(shared_context or {})
  shared_context["operating_model"] = ops_json
  shared_context["target_market"] = market_json
  shared_context["people_capability"] = people_json
  shared_context["financials"] = financials_json

  base_year1 = assemble_financials_year1(shared_context, None)
  if year1_drivers_conflict(financials_year1_json, base_year1):
    financials_year1_json = base_year1
  else:
    financials_year1_json = assemble_financials_year1(shared_context, financials_year1_json)
  if isinstance(financials_year1_json, dict) and financials_year1_json:
    shared_context["financials_year1_json"] = financials_year1_json

  try:
    marketing_model_json = compute_marketing_model_json(
      conn=conn,
      ops_json=ops_json,
      market_json=market_json,
      people_json=people_json,
      financials_year1_json=financials_year1_json,
      business_facts=business_facts,
      existing_marketing_model_json=marketing_model_json,
      estimate_marketing_baseline_from_context=estimate_marketing_baseline_from_context,
    )
  except Exception:
    marketing_model_json = dict(marketing_model_json or {})
  shared_context["marketing"] = marketing_model_json

  forecast_starting_ppe_decision = estimate_maintenance_capex_percent_with_gpt(
    business_facts=business_facts,
    ops_json=ops_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
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

  sync_result = sync_planning_state_to_finmo(
    finmo_path="",
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    forecast_starting_ppe=forecast_starting_ppe,
    maintenance_rate=maintenance_rate,
    controller_input_seed=[],
    forecast_quarters=[],
    calibration_spec=None,
  )
  if resume_from_checkpoint_state:
    model_input_json = copy.deepcopy(resume_checkpoint_model_input_json)
    finmo_json = copy.deepcopy(resume_checkpoint_finmo_json)
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
    r_and_d_applicability_decision = estimate_r_and_d_applicability_with_gpt(
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      financials_year1_json=copy.deepcopy(financials_year1_json or {}),
      model_input_json=copy.deepcopy(model_input_json or {}),
    )
    model_input_json = apply_r_and_d_applicability_policy_to_model_input(
      copy.deepcopy(model_input_json or {}),
      r_and_d_enabled=bool(r_and_d_applicability_decision.get("r_and_d_enabled")),
      decision_source="gpt_pre_forecast",
      rationale=str(r_and_d_applicability_decision.get("rationale") or ""),
    )
    finmo_json = build_python_finmo_json(model_input_json=copy.deepcopy(model_input_json))
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
    planning_context_summary_json = refresh_planning_context_summary(
      current_model_input_json=model_input_json,
    )
    if isinstance(planning_context_summary_json, dict):
      planning_context_summary_json["r_and_d_applicability"] = {
        key: copy.deepcopy(value)
        for key, value in r_and_d_applicability_decision.items()
        if key not in {"prompt_context", "raw_openai_response"}
      }
    persist_system_stage(
      stage="baseline_ready",
      status="running",
      model_input_payload=model_input_json,
      finmo_payload=finmo_json,
    )

  planning_choice = determine_planning_mode(
    ops_json=dict(ops_json or {}),
    target_market_json=dict(market_json or {}),
    people_json=dict(people_json or {}),
    financials_json=dict(financials_json or {}),
    financials_year1_json=dict(financials_year1_json or {}),
    fulfillment_json=dict(fulfillment_json or {}),
    marketing_model_json=dict(marketing_model_json or {}),
    model_input_json=copy.deepcopy(model_input_json),
    finmo_json=copy.deepcopy(finmo_json),
    business_facts=copy.deepcopy(business_facts or {}),
  )
  planning_mode = str(planning_choice.get("planning_mode") or "").strip()
  planning_mode_reason = str(planning_choice.get("planning_mode_reason") or "").strip()
  planning_context_summary_json = refresh_planning_context_summary(
    current_model_input_json=model_input_json,
    planning_mode_value=planning_mode,
    planning_mode_reason_value=planning_mode_reason,
    prompt_file_value=str(planning_choice.get("prompt_file") or "").strip(),
  )
  r_and_d_applicability_decision_for_ramp = {
    **copy.deepcopy(r_and_d_policy_from_model_input(model_input_json)),
    "contract_version": r_and_d_policy_version,
  }
  if isinstance(planning_context_summary_json, dict):
    planning_context_summary_json["r_and_d_applicability"] = copy.deepcopy(
      r_and_d_applicability_decision_for_ramp
    )
  stage_ramp_contract = estimate_stage_ramp_contract_with_gpt(
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    financials_year1_json=copy.deepcopy(financials_year1_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    r_and_d_applicability=copy.deepcopy(r_and_d_applicability_decision_for_ramp),
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
    )
  else:
    persist_system_stage(
      stage="quarter_grid_running",
      status="running",
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=str(planning_choice.get("prompt_file") or "").strip(),
      model_input_payload=model_input_json,
      finmo_payload=finmo_json,
    )
    planning_result = generate_live_quarter_grid_plan(
      business_name=str(business_facts.get("name") or "").strip(),
      planning_mode=planning_mode,
      model_input_json=copy.deepcopy(model_input_json),
      finmo_json=copy.deepcopy(finmo_json),
      ops_json=ops_json,
      target_market_json=market_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      fulfillment_json=fulfillment_json,
      marketing_model_json=marketing_model_json,
      realism_memo_json=parse_json_dict(draft.get("realism_memo_json")),
      business_facts=copy.deepcopy(business_facts or {}),
      stage_ramp_contract=copy.deepcopy(stage_ramp_contract),
    )
    validation = planning_result.get("validation") if isinstance(planning_result.get("validation"), dict) else {}
    if (
      list(validation.get("missing_rows") or [])
      or list(validation.get("extra_rows") or [])
      or list(validation.get("duplicate_rows") or [])
      or list(validation.get("malformed_rows") or [])
    ):
      raise RuntimeError("planning_grid_validation_failed")
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
    )
    assert_r_and_d_applicability_policy_applied(
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      planning_result=planning_result,
      stage="quarter_grid_ready",
    )
    grid_application_result = apply_live_quarter_grid_plan(
      baseline_model_input_json=copy.deepcopy(model_input_json),
      grid_json=copy.deepcopy(planning_result.get("grid_json") or {}),
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
    assert_r_and_d_applicability_policy_applied(
      model_input_json=applied_model_input_json,
      finmo_json=applied_finmo_json,
      stage="quarter_grid_applied",
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
    "shared_context": copy.deepcopy(shared_context or {}),
  }
