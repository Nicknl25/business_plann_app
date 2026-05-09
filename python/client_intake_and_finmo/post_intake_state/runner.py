import copy
import hashlib
import json
import math
import os
import re
import time
import calendar
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_foundation import bind_table_safe_runtime_dependencies  # type: ignore

logger = logging.getLogger(__name__)


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  if not isinstance(dependencies, dict):
    return
  bind_table_safe_runtime_dependencies(globals(), dependencies)


__all__ = [
  "_build_planning_run_payload",
  "_compact_quarter_metric_rows_for_storage",
  "_compact_writable_lever_catalog_entries",
  "_compact_numeric_feedback_for_storage",
  "_compact_unified_convergence_context_for_storage",
  "_compact_unified_convergence_decision_for_storage",
  "_compact_unified_convergence_plan_for_storage",
  "_compact_unified_convergence_result_for_storage",
  "_compact_controller_resolution_state_summary",
  "_compact_unified_convergence_iterations_for_storage",
  "_first_pass_finmo_summary",
  "_build_first_pass_handoff_payload",
  "_finmo_labeled_series",
  "_extract_open_verification_feedback",
  "_persist_post_intake_stage_state",
  "_persist_unified_convergence_state",
  "_maybe_interrupt_planning_run",
  "_minimal_controller_state_from_convergence_payloads",
  "_latest_failure_preservation_payloads",
  "_merge_terminal_failure_context",
  "_persist_failed_system_run_snapshot",
]


def _build_planning_run_payload(
  *,
  stage: str,
  status: str,
  controller_resolution_state: Optional[Dict[str, Any]] = None,
  resolution_summary: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  planning_mode_reason: Optional[str] = None,
  prompt_file: Optional[str] = None,
  gpt_narrative: Optional[str] = None,
  gpt_grid_metadata: Optional[Dict[str, Any]] = None,
  grid_application_summary: Optional[Dict[str, Any]] = None,
  realism_memo_before_resolution: Optional[Dict[str, Any]] = None,
  unified_convergence_verification: Optional[Dict[str, Any]] = None,
  first_pass_handoff: Optional[Dict[str, Any]] = None,
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  cash_strategy_effect_summary: Optional[Dict[str, Any]] = None,
  debt_schedule: Optional[Dict[str, Any]] = None,
  unified_convergence_context: Optional[Dict[str, Any]] = None,
  unified_convergence_decision: Optional[Dict[str, Any]] = None,
  unified_convergence_plan: Optional[Dict[str, Any]] = None,
  unified_convergence_result: Optional[Dict[str, Any]] = None,
  unified_convergence_iterations: Optional[List[Dict[str, Any]]] = None,
  unified_convergence_cycle_count: Optional[int] = None,
  diagnostics_snapshot: Optional[Dict[str, Any]] = None,
  controller_retry_heartbeat: Optional[Dict[str, Any]] = None,
  numeric_execution_boundary: Optional[Dict[str, Any]] = None,
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.numeric_execution import build_numeric_execution_boundary_payload, build_numeric_solver_contract  # type: ignore
  except Exception:
    from numeric_execution import build_numeric_execution_boundary_payload, build_numeric_solver_contract  # type: ignore
  controller_state = copy.deepcopy(controller_resolution_state or {})
  unified_iteration_list = _compact_unified_convergence_iterations_for_storage(
    copy.deepcopy(unified_convergence_iterations or [])
  )
  unified_context_payload = _compact_unified_convergence_context_for_storage(
    copy.deepcopy(unified_convergence_context or {})
  )
  convergence_iteration_list = copy.deepcopy(unified_iteration_list or [])
  convergence_context_payload = copy.deepcopy(unified_context_payload or {})
  effective_cycle_count = (
    int(unified_convergence_cycle_count)
    if unified_convergence_cycle_count is not None
    else None
  )
  latest_convergence_iteration = (
    convergence_iteration_list[-1]
    if convergence_iteration_list and isinstance(convergence_iteration_list[-1], dict)
    else {}
  )
  latest_quality_assessment = (
    latest_convergence_iteration.get("quality_assessment")
    if isinstance(latest_convergence_iteration.get("quality_assessment"), dict)
    else {}
  )
  latest_stall_assessment = (
    latest_convergence_iteration.get("stall_assessment_before")
    if isinstance(latest_convergence_iteration.get("stall_assessment_before"), dict)
    else {}
  )
  latest_hard_rule_assessment = (
    latest_convergence_iteration.get("hard_rule_assessment_after")
    if isinstance(latest_convergence_iteration.get("hard_rule_assessment_after"), dict)
    else (
      convergence_context_payload.get("hard_rule_assessment")
      if isinstance(convergence_context_payload.get("hard_rule_assessment"), dict)
      else {}
    )
  )
  remaining_issue_count = int(_safe_float(controller_state.get("remaining_issue_count")) or 0)
  detected_issue_count = int(_safe_float(controller_state.get("detected_issue_count")) or 0)
  resolved_issue_count = int(_safe_float(controller_state.get("resolved_issue_count")) or 0)
  iteration_pending_issue_count = int(_safe_float(controller_state.get("iteration_pending_issue_count")) or 0)
  all_cleared = bool(controller_state.get("all_cleared"))
  remaining_hard_issue_count = int(
    _safe_float(latest_hard_rule_assessment.get("remaining_hard_issue_count")) or 0
  )
  all_hard_rules_cleared = bool(latest_hard_rule_assessment.get("all_hard_rules_cleared"))
  final_stage_name = str(stage or "").strip() or "pending"
  final_status_name = str(status or "").strip() or "pending"
  deterministic_convergence_summary = {
    "contract_version": "deterministic_convergence_summary_v1",
    "convergence_engine_contract": _unified_convergence_engine_contract_payload(),
    "stage": final_stage_name,
    "status": final_status_name,
    "controller_status": str(controller_state.get("status") or "").strip() or None,
    "detected_issue_count": detected_issue_count,
    "remaining_issue_count": remaining_issue_count,
    "resolved_issue_count": resolved_issue_count,
    "iteration_pending_issue_count": iteration_pending_issue_count,
    "tolerated_issue_count": int(_safe_float(controller_state.get("tolerated_issue_count")) or 0),
    "all_cleared": all_cleared,
    "overall_completion_score_pct": int(_safe_float(controller_state.get("overall_completion_score_pct")) or 0),
    "overall_completion_grade": str(controller_state.get("overall_completion_grade") or "").strip() or "D",
    "lowest_quarter_score_pct": int(_safe_float(controller_state.get("lowest_quarter_score_pct")) or 0),
    "failing_quarters": copy.deepcopy(controller_state.get("failing_quarters") or []),
    "convergence_cycle_count": int(effective_cycle_count or 0) if effective_cycle_count is not None else len(convergence_iteration_list),
    "remaining_hard_issue_count": remaining_hard_issue_count,
    "hard_rule_assessment": copy.deepcopy(latest_hard_rule_assessment),
    "latest_quality_assessment": copy.deepcopy(latest_quality_assessment),
    "latest_stall_assessment": copy.deepcopy(latest_stall_assessment),
    "latest_hard_rule_assessment": copy.deepcopy(latest_hard_rule_assessment),
    "controller_retry_heartbeat": copy.deepcopy(controller_retry_heartbeat or {}),
    "terminal_acceptance_gate": {
      "stage_is_terminal_converged": final_stage_name in {"convergence_completed", "cash_pass_completed"},
      "stage_is_convergence_completed": final_stage_name in {"convergence_completed", "cash_pass_completed"},
      "status_is_completed": final_status_name == "completed",
      "all_cleared": all_cleared,
      "remaining_issue_count_zero": remaining_issue_count == 0,
      "remaining_hard_issue_count_zero": remaining_hard_issue_count == 0,
      "hard_rules_cleared": all_hard_rules_cleared,
      "last_cycle_accepted": (
        bool(latest_convergence_iteration.get("accepted"))
        if latest_convergence_iteration
        else None
      ),
    },
  }
  current_cycle_convergence_packet = _build_current_cycle_convergence_packet(
    stage=final_stage_name,
    status=final_status_name,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_context_summary=copy.deepcopy(
      ((unified_convergence_context or {}) if isinstance(unified_convergence_context, dict) else {}).get("planning_context_summary") or {}
    ),
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    controller_resolution_state=copy.deepcopy(controller_state),
    controller_retry_context=copy.deepcopy(
      (controller_retry_heartbeat.get("controller_retry_context") if isinstance(controller_retry_heartbeat, dict) else {}) or {}
    ),
    prior_numeric_feedback=copy.deepcopy(
      ((unified_convergence_context or {}) if isinstance(unified_convergence_context, dict) else {}).get("prior_numeric_solver_feedback") or {}
    ),
    unified_convergence_decision=copy.deepcopy(unified_convergence_decision or {}),
    unified_convergence_plan=copy.deepcopy(unified_convergence_plan or {}),
    unified_convergence_result=copy.deepcopy(unified_convergence_result or {}),
    unified_convergence_cycle_count=effective_cycle_count,
    cycle_debug=copy.deepcopy(latest_quality_assessment or {}),
  )

  payload: Dict[str, Any] = {
    "contract_version": "planning_run_v1",
    "convergence_engine_contract": _unified_convergence_engine_contract_payload(),
    "stage": final_stage_name,
    "status": final_status_name,
    "controller_resolution_state": controller_state,
    "resolution_summary": copy.deepcopy(resolution_summary or {}),
    "planning_mode": str(planning_mode or "").strip() or None,
    "planning_mode_reason": str(planning_mode_reason or "").strip() or None,
    "prompt_file": str(prompt_file or "").strip() or None,
    "gpt_narrative": str(gpt_narrative or "").strip() or None,
    "gpt_grid_metadata": copy.deepcopy(gpt_grid_metadata or {}),
    "grid_application_summary": copy.deepcopy(grid_application_summary or {}),
    "realism_memo_before_resolution": copy.deepcopy(realism_memo_before_resolution or {}),
    "unified_convergence_verification": copy.deepcopy(unified_convergence_verification or {}),
    "first_pass_handoff": copy.deepcopy(first_pass_handoff or {}),
    "cash_strategy_review_context": copy.deepcopy(cash_strategy_review_context or {}),
    "cash_strategy_review_decision": copy.deepcopy(cash_strategy_review_decision or {}),
    "cash_strategy_second_pass_plan": copy.deepcopy(cash_strategy_second_pass_plan or {}),
    "cash_strategy_second_pass_result": copy.deepcopy(cash_strategy_second_pass_result or {}),
    "cash_strategy_effect_summary": copy.deepcopy(cash_strategy_effect_summary or {}),
    "debt_schedule": copy.deepcopy(debt_schedule or {}),
    "unified_convergence_context": convergence_context_payload,
    "unified_convergence_decision": _compact_unified_convergence_decision_for_storage(
      copy.deepcopy(unified_convergence_decision or {})
    ),
    "unified_convergence_plan": _compact_unified_convergence_plan_for_storage(
      copy.deepcopy(unified_convergence_plan or {})
    ),
    "unified_convergence_result": _compact_unified_convergence_result_for_storage(
      copy.deepcopy(unified_convergence_result or {})
    ),
    "unified_convergence_iterations": convergence_iteration_list,
    "unified_convergence_cycle_count": int(effective_cycle_count or 0) if effective_cycle_count is not None else None,
    "diagnostics_snapshot": copy.deepcopy(diagnostics_snapshot or {}),
    "controller_retry_heartbeat": copy.deepcopy(controller_retry_heartbeat or {}),
    "deterministic_convergence_summary": deterministic_convergence_summary,
    "current_cycle_convergence_packet": current_cycle_convergence_packet,
    "unified_convergence_heartbeat": (
      copy.deepcopy(controller_retry_heartbeat or {})
      if str(((controller_retry_heartbeat or {}).get("pass_name") or "")).strip().lower() == "unified_convergence"
      else {}
    ),
    "numeric_execution_boundary": copy.deepcopy(
      numeric_execution_boundary
      if isinstance(numeric_execution_boundary, dict)
      else build_numeric_execution_boundary_payload()
    ),
    "numeric_solver_contract": copy.deepcopy(
      _compact_numeric_solver_contract_for_storage(
        numeric_solver_contract
        if isinstance(numeric_solver_contract, dict)
        else build_numeric_solver_contract()
      )
    ),
  }
  return payload

def _compact_quarter_metric_rows_for_storage(rows: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
  keep_keys = (
    "quarter_index",
    "date",
    "revenue",
    "cost_of_goods_sold",
    "cogs",
    "gross_profit",
    "marketing",
    "research_and_development",
    "lease_rent",
    "ebitda",
    "general_and_administrative",
    "g_and_a",
    "net_income",
    "ending_cash",
    "operating_cash_flow",
    "financing_cash_flow",
    "current_assets",
    "current_liabilities",
    "ppe",
    "payroll",
    "capital_expenditures",
    "long_term_debt",
    "owners_capital",
    "other_equity",
    "distributions",
  )
  compact_rows: List[Dict[str, Any]] = []
  for row in (rows or []):
    if not isinstance(row, dict):
      continue
    compact_rows.append({key: copy.deepcopy(row.get(key)) for key in keep_keys if key in row})
  return compact_rows

def _compact_writable_lever_catalog_entries(entries: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
  compact_entries: List[Dict[str, Any]] = []
  for entry in (entries or []):
    if not isinstance(entry, dict):
      continue
    lever_id = str(entry.get("lever_id") or "").strip()
    if not lever_id:
      continue
    compact_entries.append(
      {
        "lever_id": lever_id,
        "lever_family": str(lever_id.split("::", 1)[0] or "").strip(),
        "label": str(
          entry.get("row_label")
          or entry.get("label")
          or entry.get("name")
          or lever_id
        ).strip(),
        "value_kind": str(entry.get("value_kind") or entry.get("value_type") or "").strip(),
      }
    )
  return compact_entries

def _compact_numeric_feedback_for_storage(feedback: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = feedback if isinstance(feedback, dict) else {}
  compact = {
    "execution_state": str(payload.get("execution_state") or "").strip(),
    "outcome_reason": str(payload.get("outcome_reason") or "").strip(),
    "solver_invoked": bool(payload.get("solver_invoked")),
    "solver_execution_state": str(payload.get("solver_execution_state") or "").strip(),
    "attempt_count": int(_safe_float(payload.get("attempt_count")) or 0),
    "target_metric_names": copy.deepcopy(payload.get("target_metric_names") or []),
    "targeted_quarters": copy.deepcopy(payload.get("targeted_quarters") or []),
    "allowed_lever_ids": copy.deepcopy(payload.get("allowed_lever_ids") or []),
    "attempted_lever_families": copy.deepcopy(payload.get("attempted_lever_families") or []),
    "best_objective": copy.deepcopy(payload.get("best_objective")),
    "baseline_objective": copy.deepcopy(payload.get("baseline_objective")),
    "objective_delta": copy.deepcopy(payload.get("objective_delta")),
    "quarters_with_all_targets_within_tolerance": int(_safe_float(payload.get("quarters_with_all_targets_within_tolerance")) or 0),
    "quarters_with_target_misses": int(_safe_float(payload.get("quarters_with_target_misses")) or 0),
    "target_verification": copy.deepcopy(payload.get("target_verification") or {}),
    "quarter_fit_summary": copy.deepcopy(payload.get("quarter_fit_summary") or []),
  }
  if isinstance(payload.get("current_cycle_trace"), dict):
    compact["current_cycle_trace"] = copy.deepcopy(payload.get("current_cycle_trace") or {})
  return compact

def _compact_unified_convergence_context_for_storage(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = copy.deepcopy(context if isinstance(context, dict) else {})
  payload.pop("current_model_input_json", None)
  payload.pop("current_finmo_json", None)
  payload.pop("current_finmo_quarter_rows", None)
  payload["controller_resolution_state"] = _compact_controller_resolution_state_summary(
    payload.get("controller_resolution_state")
  )
  payload["horizon_quarter_metrics"] = _compact_quarter_metric_rows_for_storage(
    payload.get("horizon_quarter_metrics") or []
  )
  writable_catalog = payload.get("writable_lever_catalog") if isinstance(payload.get("writable_lever_catalog"), dict) else {}
  payload["writable_lever_catalog"] = {
    **copy.deepcopy(writable_catalog),
    "entries": _compact_writable_lever_catalog_entries(writable_catalog.get("entries") or []),
  }
  payload["numeric_solver_contract"] = _compact_numeric_solver_contract_for_storage(
    payload.get("numeric_solver_contract") if isinstance(payload.get("numeric_solver_contract"), dict) else {}
  )
  payload["prior_numeric_solver_feedback"] = _compact_numeric_feedback_for_storage(
    payload.get("prior_numeric_solver_feedback") if isinstance(payload.get("prior_numeric_solver_feedback"), dict) else {}
  )
  return payload

def _compact_unified_convergence_decision_for_storage(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  decision_payload = copy.deepcopy(payload if isinstance(payload, dict) else {})
  decision = decision_payload.get("decision") if isinstance(decision_payload.get("decision"), dict) else {}
  compact_decision = {
    "strategy_class": str(decision.get("strategy_class") or "").strip(),
    "change_type": str(decision.get("change_type") or "").strip(),
    "progress_expectation": str(decision.get("progress_expectation") or "").strip(),
    "retry_reason": str(decision.get("retry_reason") or "").strip(),
    "primary_target_metric_names": copy.deepcopy(decision.get("primary_target_metric_names") or []),
    "lever_selection": copy.deepcopy(decision.get("lever_selection") or []),
    "target_quarter_count": len(_normalize_solver_quarter_target_metrics(decision.get("targets_by_quarter") or [])),
    "target_tolerance_metric_names": [
      str(item.get("metric_name") or "").strip()
      for item in _normalize_unified_target_tolerances(decision.get("target_tolerances") or [])
      if str(item.get("metric_name") or "").strip()
    ],
  }
  decision_payload["decision"] = compact_decision
  return decision_payload

def _compact_unified_convergence_plan_for_storage(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  plan = copy.deepcopy(payload if isinstance(payload, dict) else {})
  translated_packages = []
  for item in (plan.get("translated_action_packages") or []):
    if not isinstance(item, dict):
      continue
    translated_packages.append(
      {
        "action_id": str(item.get("action_id") or "").strip(),
        "business_move": str(item.get("business_move") or "").strip(),
        "timing_start_q": copy.deepcopy(item.get("timing_start_q")),
        "timing_end_q": copy.deepcopy(item.get("timing_end_q")),
        "solver_allowed_lever_ids": copy.deepcopy(item.get("solver_allowed_lever_ids") or []),
        "required_target_metric_keys": copy.deepcopy(item.get("required_target_metric_keys") or []),
        "translated_control_count": len(item.get("translated_controls") or []),
      }
    )
  plan["translated_action_packages"] = translated_packages
  plan["targets_by_quarter"] = [
    {
      "quarter_index": copy.deepcopy(item.get("quarter_index")),
      "metric_names": [
        str(metric.get("metric_name") or "").strip()
        for metric in ((item.get("metric_targets") or []) if isinstance(item.get("metric_targets"), list) else [])
        if isinstance(metric, dict) and str(metric.get("metric_name") or "").strip()
      ],
    }
    for item in _normalize_solver_quarter_target_metrics(plan.get("targets_by_quarter") or [])
    if isinstance(item, dict)
  ]
  plan["lever_adjustment_source"] = str(plan.get("lever_adjustment_source") or "").strip()
  plan["explicit_lever_adjustment_count"] = int(_safe_float(plan.get("explicit_lever_adjustment_count")) or 0)
  plan["auto_generated_lever_adjustment_count"] = int(_safe_float(plan.get("auto_generated_lever_adjustment_count")) or 0)
  plan["translated_control_count"] = int(_safe_float(plan.get("translated_control_count")) or 0)
  plan["deterministic_guidance_metric_count"] = int(_safe_float(plan.get("deterministic_guidance_metric_count")) or 0)
  plan["deterministic_guidance_lever_count"] = int(_safe_float(plan.get("deterministic_guidance_lever_count")) or 0)
  return plan

def _compact_unified_convergence_result_for_storage(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  result = copy.deepcopy(payload if isinstance(payload, dict) else {})
  result["decision"] = _compact_unified_convergence_decision_for_storage(
    result.get("decision") if isinstance(result.get("decision"), dict) else {}
  )
  result["plan"] = _compact_unified_convergence_plan_for_storage(
    result.get("plan") if isinstance(result.get("plan"), dict) else {}
  )
  raw_result = result.get("result") if isinstance(result.get("result"), dict) else {}
  compact_result = {
    "status": str(raw_result.get("status") or "").strip(),
    "target_verification": copy.deepcopy(raw_result.get("target_verification") or {}),
  }
  if isinstance(raw_result.get("result"), dict):
    compact_result["result"] = _compact_numeric_feedback_for_storage(raw_result.get("result"))
  result["result"] = compact_result
  result.pop("updated_model_input_json", None)
  result.pop("updated_finmo_json", None)
  return result

def _compact_controller_resolution_state_summary(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = state if isinstance(state, dict) else {}
  return {
    "status": str(payload.get("status") or "").strip(),
    "remaining_issue_count": int(_safe_float(payload.get("remaining_issue_count")) or 0),
    "resolved_issue_count": int(_safe_float(payload.get("resolved_issue_count")) or 0),
    "tolerated_issue_count": int(_safe_float(payload.get("tolerated_issue_count")) or 0),
    "overall_completion_score_pct": int(_safe_float(payload.get("overall_completion_score_pct")) or 0),
    "overall_completion_grade": str(payload.get("overall_completion_grade") or "").strip() or "D",
    "lowest_quarter_score_pct": int(_safe_float(payload.get("lowest_quarter_score_pct")) or 0),
    "failing_quarters": copy.deepcopy(payload.get("failing_quarters") or []),
    "remaining_issue_codes": [
      str(item.get("issue_code") or "").strip()
      for item in (payload.get("remaining_issues") or [])
      if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
    ],
    "resolved_issue_codes": [
      str(item.get("issue_code") or "").strip()
      for item in (payload.get("resolved_issues") or [])
      if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
    ],
    "tolerated_issue_codes": [
      str(item.get("issue_code") or "").strip()
      for item in (payload.get("tolerated_issues") or [])
      if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
    ],
  }

def _compact_unified_convergence_iterations_for_storage(
  iterations: Optional[List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
  compact_iterations: List[Dict[str, Any]] = []
  for item in (iterations or []):
    if not isinstance(item, dict):
      continue
    compact_iterations.append(
      {
        "cycle": copy.deepcopy(item.get("cycle")),
        "accepted": bool(item.get("accepted")),
        "stall_assessment_before": copy.deepcopy(item.get("stall_assessment_before") or {}),
        "quality_assessment": copy.deepcopy(item.get("quality_assessment") or {}),
        "hard_rule_assessment_before": copy.deepcopy(item.get("hard_rule_assessment_before") or {}),
        "hard_rule_assessment_after": copy.deepcopy(item.get("hard_rule_assessment_after") or {}),
        "decision": (
          _compact_unified_convergence_decision_for_storage(item.get("decision"))
          if isinstance(item.get("decision"), dict)
          else {}
        ),
        "plan": (
          _compact_unified_convergence_plan_for_storage(item.get("plan"))
          if isinstance(item.get("plan"), dict)
          else {}
        ),
        "result": (
          _compact_unified_convergence_result_for_storage(item.get("result"))
          if isinstance(item.get("result"), dict)
          else {}
        ),
        "retry_memory": _compact_retry_memory_for_storage(item.get("retry_memory")),
        "validation_error": copy.deepcopy(item.get("validation_error") or {}),
        "controller_resolution_state_before": _compact_controller_resolution_state_summary(
          item.get("controller_resolution_state_before")
        ),
        "controller_resolution_state_after": _compact_controller_resolution_state_summary(
          item.get("controller_resolution_state_after")
        ),
      }
    )
  return compact_iterations

def _first_pass_finmo_summary(finmo_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  quarter_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  live_rows = [row for row in quarter_rows if int(float(row.get("quarter_index") or 0)) >= 1]
  if not live_rows:
    return {}

  def _row_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
      "quarter_index": int(float(row.get("quarter_index") or 0)),
      "year": row.get("year"),
      "quarter": row.get("quarter"),
      "date": row.get("date"),
      "revenue": _safe_float(row.get("revenue")),
      "ebitda": _safe_float(row.get("ebitda")),
      "net_income": _safe_float(row.get("net_income")),
      "ending_cash": _safe_float(row.get("ending_cash")),
      "total_assets": _safe_float(row.get("total_assets")),
      "total_liabilities_and_equity": _safe_float(row.get("total_liabilities_and_equity")),
    }

  cash_values = [_safe_float(row.get("ending_cash")) or 0.0 for row in live_rows]
  return {
    "quarter_count": len(live_rows),
    "first_quarter": _row_metrics(live_rows[0]),
    "last_quarter": _row_metrics(live_rows[-1]),
    "cash_peak": max(cash_values) if cash_values else 0.0,
    "cash_trough": min(cash_values) if cash_values else 0.0,
  }

def _build_first_pass_handoff_payload(
  *,
  draft_id: str,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]],
  applied_model_input_json: Optional[Dict[str, Any]],
  applied_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  business = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  model_input = applied_model_input_json if isinstance(applied_model_input_json, dict) else {}
  finmo = applied_finmo_json if isinstance(applied_finmo_json, dict) else {}
  periods = [item for item in (model_input.get("periods") or []) if isinstance(item, dict)]
  return {
    "contract_version": "first_pass_handoff_v1",
    "status": "ready",
    "handoff_role": "baseline_for_cash_strategy_review",
    "draft_id": str(draft_id or "").strip(),
    "planning_mode": str(planning_mode or "").strip(),
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "prompt_file": str(prompt_file or "").strip(),
    "business_snapshot": {
      "business_name": str(business.get("name") or business.get("business_name") or "").strip(),
      "business_type": str(ops.get("business_type") or "").strip(),
      "business_stage": str(ops.get("business_stage") or "").strip(),
      "cash_strategy": str(financials.get("cash_strategy") or "").strip(),
      "forecast_quarter_count": _quarter_count_from_model_input(model_input),
    },
    "artifacts": {
      "applied_model_input_persisted": bool(model_input),
      "applied_finmo_persisted": bool(finmo),
      "draft_fields": ["model_input_json", "finmo_json"],
    },
    "grid_application_summary": copy.deepcopy(grid_application_summary or {}),
    "finmo_summary": _first_pass_finmo_summary(finmo),
    "ready_for_cash_strategy_review": True,
  }

def _finmo_labeled_series(
  finmo_payload: Optional[Dict[str, Any]],
  *,
  section_key: str,
  label: str,
) -> List[float]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  rows = [row for row in (finmo_obj.get(section_key) or []) if isinstance(row, dict)]
  for row in rows:
    if str(row.get("label") or "").strip() != str(label or "").strip():
      continue
    return [float(_safe_float(item) or 0.0) for item in (row.get("values") or [])]
  return []

def _extract_open_verification_feedback(
  verification_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  verification = (
    verification_payload.get("verification")
    if isinstance(verification_payload, dict) and isinstance(verification_payload.get("verification"), dict)
    else {}
  )
  if not verification:
    return {}
  issue_results = [item for item in (verification.get("issue_results") or []) if isinstance(item, dict)]
  open_issue_results = [
    {
      "issue_code": str(item.get("issue_code") or "").strip(),
      "status": str(verifier_resolution.get("verifier_status") or "").strip(),
      "remaining_issue_materiality": str(
        verifier_resolution.get("remaining_issue_materiality") or ""
      ).strip(),
      "remaining_issue_severity_score": int(
        verifier_resolution.get("remaining_issue_severity_score") or 0
      ),
      "verification_reason": str(item.get("verification_reason") or "").strip(),
      "remaining_problem_quarters": copy.deepcopy(
        verifier_resolution.get("remaining_problem_quarters") or []
      ),
      "next_required_lever_ids": copy.deepcopy(
        verifier_resolution.get("next_required_lever_ids") or []
      ),
      "observed_improvement_summary": str(item.get("observed_improvement_summary") or "").strip(),
    }
    for item in issue_results
    for verifier_resolution in [_controller_resolution_from_verification_issue(item)]
    if str(verifier_resolution.get("verifier_status") or "").strip().lower() != "resolved"
  ]
  if not open_issue_results:
    return {}
  return {
    "overall_assessment": str(verification.get("overall_assessment") or "").strip(),
    "executive_summary": str(verification.get("executive_summary") or "").strip(),
    "open_issue_results": open_issue_results,
  }

def _persist_post_intake_stage_state(
  *,
  conn,
  draft_id: str,
  stage: str,
  status: str,
  planning_context_summary_json: Optional[Dict[str, Any]] = None,
  controller_resolution_state: Optional[Dict[str, Any]] = None,
  resolution_summary: Optional[Dict[str, Any]] = None,
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]] = None,
  realism_memo_before_resolution: Optional[Dict[str, Any]] = None,
  unified_convergence_verification: Optional[Dict[str, Any]] = None,
  first_pass_handoff: Optional[Dict[str, Any]] = None,
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  cash_strategy_effect_summary: Optional[Dict[str, Any]] = None,
  unified_convergence_context: Optional[Dict[str, Any]] = None,
  unified_convergence_decision: Optional[Dict[str, Any]] = None,
  unified_convergence_plan: Optional[Dict[str, Any]] = None,
  unified_convergence_result: Optional[Dict[str, Any]] = None,
  unified_convergence_iterations: Optional[List[Dict[str, Any]]] = None,
  unified_convergence_cycle_count: Optional[int] = None,
  diagnostics_snapshot: Optional[Dict[str, Any]] = None,
  realism_memo_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  numeric_execution_boundary: Optional[Dict[str, Any]] = None,
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
  controller_retry_heartbeat: Optional[Dict[str, Any]] = None,
  explicit_numeric_feedback_candidates: Optional[List[tuple[str, Optional[Dict[str, Any]]]]] = None,
) -> Dict[str, Any]:
  persisted_realism_memo = _build_persisted_realism_memo_payload(
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    working_memo=copy.deepcopy(realism_memo_json),
  )
  payload = _build_planning_run_payload(
    stage=stage,
    status=status,
    controller_resolution_state=copy.deepcopy(controller_resolution_state or {}),
    resolution_summary=copy.deepcopy(resolution_summary or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution or {}),
    unified_convergence_verification=copy.deepcopy(unified_convergence_verification or {}),
    first_pass_handoff=copy.deepcopy(first_pass_handoff or {}),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context or {}),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision or {}),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan or {}),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result or {}),
    cash_strategy_effect_summary=copy.deepcopy(cash_strategy_effect_summary or {}),
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    unified_convergence_decision=copy.deepcopy(unified_convergence_decision or {}),
    unified_convergence_plan=copy.deepcopy(unified_convergence_plan or {}),
    unified_convergence_result=copy.deepcopy(unified_convergence_result or {}),
    unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations or []),
    unified_convergence_cycle_count=unified_convergence_cycle_count,
    diagnostics_snapshot=copy.deepcopy(diagnostics_snapshot or {}),
    controller_retry_heartbeat=copy.deepcopy(controller_retry_heartbeat or {}),
    numeric_execution_boundary=copy.deepcopy(numeric_execution_boundary)
    if isinstance(numeric_execution_boundary, dict)
    else None,
    numeric_solver_contract=copy.deepcopy(numeric_solver_contract)
    if isinstance(numeric_solver_contract, dict)
    else None,
  )
  extracted_numeric_feedback = _extract_numeric_solver_feedback_for_persistence(
    planning_run_payload=payload,
    explicit_candidates=copy.deepcopy(explicit_numeric_feedback_candidates or []),
  )
  retry_context_for_guidance = (
    (controller_retry_heartbeat.get("controller_retry_context") if isinstance(controller_retry_heartbeat, dict) else {})
    if isinstance((controller_retry_heartbeat or {}).get("controller_retry_context"), dict)
    else {}
  )
  repair_guidance_payload = _build_repair_guidance_payload(
    draft_id=str(draft_id).strip(),
    stage=stage,
    status=str(payload.get("status") or status).strip() or status,
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_mode_prompt_file=prompt_file,
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    controller_resolution_state=copy.deepcopy(controller_resolution_state or {}),
    controller_retry_context=copy.deepcopy(retry_context_for_guidance),
    prior_numeric_feedback=copy.deepcopy(extracted_numeric_feedback),
    unified_convergence_cycle_count=unified_convergence_cycle_count,
  )
  persisted = persist_post_intake_execution_state(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    realism_memo_json=copy.deepcopy(persisted_realism_memo),
    planning_run_json=copy.deepcopy(payload),
    repair_guidance_json=copy.deepcopy(repair_guidance_payload),
    numeric_solver_feedback_json=copy.deepcopy(extracted_numeric_feedback),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    active_focus="done",
    status="in_progress",
    completed=False,
    checkpoint_kind="stage_snapshot",
    event_type="stage_persisted",
    event_summary=f"{stage}:{str(payload.get('status') or status).strip()}",
  )
  persisted_payload = (
    persisted.get("planning_run_json")
    if isinstance(persisted, dict) and isinstance(persisted.get("planning_run_json"), dict)
    else payload
  )
  return persisted_payload

def _persist_unified_convergence_state(
  *,
  conn,
  draft_id: str,
  stage: str,
  status: str,
  planning_context_summary_json: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  resolution_summary: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]],
  realism_memo_before_resolution: Optional[Dict[str, Any]],
  realism_memo_json: Optional[Dict[str, Any]],
  unified_convergence_context: Optional[Dict[str, Any]],
  unified_convergence_decision: Optional[Dict[str, Any]],
  unified_convergence_plan: Optional[Dict[str, Any]],
  unified_convergence_result: Optional[Dict[str, Any]],
  unified_convergence_iterations: Optional[List[Dict[str, Any]]],
  unified_convergence_cycle_count: Optional[int],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  cash_strategy_effect_summary: Optional[Dict[str, Any]] = None,
  controller_retry_heartbeat: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return _persist_post_intake_stage_state(
    conn=conn,
    draft_id=str(draft_id).strip(),
    stage=stage,
    status=status,
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    controller_resolution_state=copy.deepcopy(controller_resolution_state or {}),
    resolution_summary=copy.deepcopy(resolution_summary or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution or {}),
    realism_memo_json=copy.deepcopy(realism_memo_json or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    unified_convergence_decision=copy.deepcopy(unified_convergence_decision or {}),
    unified_convergence_plan=copy.deepcopy(unified_convergence_plan or {}),
    unified_convergence_result=copy.deepcopy(unified_convergence_result or {}),
    unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations or []),
    unified_convergence_cycle_count=unified_convergence_cycle_count,
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context or {}),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision or {}),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan or {}),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result or {}),
    cash_strategy_effect_summary=copy.deepcopy(cash_strategy_effect_summary or {}),
    controller_retry_heartbeat=copy.deepcopy(controller_retry_heartbeat or {}),
    explicit_numeric_feedback_candidates=[
      ("unified_convergence_result", unified_convergence_result),
      ("cash_strategy_second_pass_result", cash_strategy_second_pass_result),
    ],
  )

def _maybe_interrupt_planning_run(
  *,
  conn,
  draft_id: str,
  planning_run_id: Optional[str],
  stage: str,
  planning_status: str,
  planning_run_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  realism_memo_json: Optional[Dict[str, Any]] = None,
  numeric_solver_feedback_json: Optional[Dict[str, Any]] = None,
  event_summary: str = "",
) -> None:
  run_id = str(planning_run_id or "").strip()
  if not run_id:
    return
  run_row = get_planning_run(conn, planning_run_id=run_id)
  if not isinstance(run_row, dict):
    return
  action = str(run_row.get("requested_action") or "").strip().lower()
  if action not in {"pause", "stop"}:
    return
  lifecycle_status = "paused" if action == "pause" else "stopped"
  payload = copy.deepcopy(planning_run_json if isinstance(planning_run_json, dict) else {})
  payload["planning_run_id"] = run_id
  payload["stage"] = str(stage or payload.get("stage") or "").strip() or None
  payload["status"] = lifecycle_status
  payload["lifecycle_interrupt"] = {
    "action": action,
    "requested_action_at": str(run_row.get("requested_action_at") or "").strip(),
    "requested_action_reason": str(run_row.get("requested_action_reason") or "").strip(),
    "interrupted_stage": str(stage or "").strip(),
    "interrupted_status": str(planning_status or "").strip(),
  }
  persist_post_intake_execution_state(
    conn,
    draft_id=str(draft_id).strip(),
    planning_run_json=payload,
    numeric_solver_feedback_json=copy.deepcopy(numeric_solver_feedback_json or {}),
    realism_memo_json=copy.deepcopy(realism_memo_json or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    new_messages=[],
    active_focus="done",
    status=lifecycle_status,
    completed=False,
    checkpoint_kind=f"run_{action}",
    event_type=f"run_{lifecycle_status}",
    event_summary=str(event_summary or "").strip() or f"{stage}:{lifecycle_status}",
  )
  clear_planning_run_action(conn, planning_run_id=run_id, run_status=lifecycle_status)
  raise PlanningRunLifecycleInterrupt(
    action=action,
    planning_run_id=run_id,
    detail=f"planning_run_{lifecycle_status}",
  )

def _minimal_controller_state_from_convergence_payloads(
  *,
  planning_convergence_payload: Optional[Dict[str, Any]],
  convergence_state_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  planning_payload = (
    planning_convergence_payload
    if isinstance(planning_convergence_payload, dict)
    else {}
  )
  convergence_payload = (
    convergence_state_payload
    if isinstance(convergence_state_payload, dict)
    else {}
  )
  issue_state = (
    convergence_payload.get("issue_state")
    if isinstance(convergence_payload.get("issue_state"), dict)
    else {}
  )
  hard_rule_state = (
    convergence_payload.get("hard_rule_state")
    if isinstance(convergence_payload.get("hard_rule_state"), dict)
    else {}
  )
  controller_status = str(
    issue_state.get("controller_status")
    or planning_payload.get("controller_status")
    or ""
  ).strip() or None
  remaining_issue_count = _safe_float(
    issue_state.get("remaining_issue_count")
    if issue_state.get("remaining_issue_count") is not None
    else planning_payload.get("remaining_issue_count")
  )
  all_cleared = bool(
    controller_status == "all_cleared"
    or (remaining_issue_count is not None and remaining_issue_count <= 0.0)
  )
  return {
    "status": controller_status,
    "all_cleared": all_cleared,
    "detected_issue_count": (
      int(_safe_float(issue_state.get("detected_issue_count")) or 0)
      if issue_state.get("detected_issue_count") is not None
      else planning_payload.get("detected_issue_count")
    ),
    "remaining_issue_count": (
      int(_safe_float(remaining_issue_count) or 0)
      if remaining_issue_count is not None
      else None
    ),
    "resolved_issue_count": (
      int(_safe_float(issue_state.get("resolved_issue_count")) or 0)
      if issue_state.get("resolved_issue_count") is not None
      else planning_payload.get("resolved_issue_count")
    ),
    "tolerated_issue_count": (
      int(_safe_float(issue_state.get("tolerated_issue_count")) or 0)
      if issue_state.get("tolerated_issue_count") is not None
      else planning_payload.get("tolerated_issue_count")
    ),
    "iteration_pending_issue_count": (
      int(_safe_float(issue_state.get("iteration_pending_issue_count")) or 0)
      if issue_state.get("iteration_pending_issue_count") is not None
      else planning_payload.get("iteration_pending_issue_count")
    ),
    "overall_completion_score_pct": issue_state.get("overall_completion_score_pct"),
    "overall_completion_grade": issue_state.get("overall_completion_grade"),
    "lowest_quarter_score_pct": issue_state.get("lowest_quarter_score_pct"),
    "failing_quarters": copy.deepcopy(issue_state.get("failing_quarters") or []),
    "remaining_hard_issue_count": (
      int(_safe_float(hard_rule_state.get("remaining_hard_issue_count")) or 0)
      if hard_rule_state.get("remaining_hard_issue_count") is not None
      else None
    ),
  }

def _latest_failure_preservation_payloads(
  *,
  conn,
  draft_id: str,
  planning_run_id: Optional[str] = None,
) -> Dict[str, Any]:
  draft = get_draft(conn, draft_id=str(draft_id).strip())
  latest_checkpoint = None
  run_id = str(planning_run_id or "").strip()
  if not run_id:
    latest_checkpoint = get_latest_planning_run_checkpoint(
      conn,
      draft_id=str(draft_id).strip(),
    )
    run_id = str((latest_checkpoint or {}).get("planning_run_id") or "").strip()
  candidate_checkpoints: List[Dict[str, Any]] = []
  if run_id:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        """
        SELECT checkpoint_id, checkpoint_kind, planning_convergence_json, convergence_state_json, created_at
        FROM planning_run_checkpoints
        WHERE planning_run_id = %s
        ORDER BY created_at DESC
        LIMIT 12
        """,
        (run_id,),
      )
      candidate_checkpoints = [
        row for row in (cur.fetchall() or [])
        if isinstance(row, dict)
      ]
    finally:
      try:
        cur.close()
      except Exception:
        pass
  if candidate_checkpoints:
    latest_checkpoint = candidate_checkpoints[0]
  elif latest_checkpoint is None:
    latest_checkpoint = get_latest_planning_run_checkpoint(
      conn,
      planning_run_id=run_id or None,
      draft_id=str(draft_id).strip(),
    )
  candidate_rows = []
  for row in candidate_checkpoints:
    candidate_rows.append(row)
  if isinstance(latest_checkpoint, dict) and latest_checkpoint not in candidate_rows:
    candidate_rows.append(latest_checkpoint)
  if isinstance(draft, dict):
    candidate_rows.append(draft)

  preserved_planning_convergence: Dict[str, Any] = {}
  preserved_convergence_state: Dict[str, Any] = {}
  source_kind: Optional[str] = None
  source_checkpoint_id: Optional[str] = None
  for row in candidate_rows:
    planning_convergence_payload = _parse_json_dict(row.get("planning_convergence_json"))
    convergence_payload = _parse_json_dict(row.get("convergence_state_json"))
    issue_state = (
      convergence_payload.get("issue_state")
      if isinstance(convergence_payload.get("issue_state"), dict)
      else {}
    )
    has_counts = any(
      issue_state.get(key) is not None
      for key in (
        "remaining_issue_count",
        "resolved_issue_count",
        "tolerated_issue_count",
        "overall_completion_score_pct",
      )
    )
    if planning_convergence_payload or convergence_payload or has_counts:
      preserved_planning_convergence = copy.deepcopy(planning_convergence_payload)
      preserved_convergence_state = copy.deepcopy(convergence_payload)
      source_kind = "checkpoint" if row is not draft else "draft"
      source_checkpoint_id = str(row.get("checkpoint_id") or "").strip() or None
      if has_counts:
        break

  return {
    "planning_convergence_json": preserved_planning_convergence,
    "convergence_state_json": preserved_convergence_state,
    "source_kind": source_kind,
    "source_checkpoint_id": source_checkpoint_id,
  }

def _merge_terminal_failure_context(
  *,
  planning_convergence_payload: Optional[Dict[str, Any]],
  convergence_state_payload: Optional[Dict[str, Any]],
  current_stage: str,
  detail: str,
  source_kind: Optional[str] = None,
  source_checkpoint_id: Optional[str] = None,
  failure_diagnostics: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], bool]:
  planning_payload = (
    copy.deepcopy(planning_convergence_payload)
    if isinstance(planning_convergence_payload, dict)
    else {}
  )
  convergence_payload = (
    copy.deepcopy(convergence_state_payload)
    if isinstance(convergence_state_payload, dict)
    else {}
  )
  controller_state = _minimal_controller_state_from_convergence_payloads(
    planning_convergence_payload=planning_payload,
    convergence_state_payload=convergence_payload,
  )
  previous_controller_all_cleared = bool(controller_state.get("all_cleared"))
  if str(detail or "").strip():
    controller_state["status"] = "terminal_failure"
    controller_state["display_status"] = "terminal failure"
    controller_state["all_cleared"] = False
    controller_state["hard_cleared"] = False
    controller_state["previous_controller_all_cleared_before_terminal_failure"] = previous_controller_all_cleared
    controller_state["terminal_failure_detail"] = str(detail or "").strip()
    controller_state["remaining_hard_issue_count"] = max(
      1,
      int(_safe_float(controller_state.get("remaining_hard_issue_count")) or 0),
    )
  terminal_failure_after_all_cleared = False
  failure_context = {
    "failure_reason": str(detail or "").strip() or None,
    "failed_stage": str(current_stage or "").strip() or None,
    "source_kind": str(source_kind or "").strip() or None,
    "source_checkpoint_id": str(source_checkpoint_id or "").strip() or None,
    "preserved_last_known_good_state": bool(planning_payload or convergence_payload),
    "terminal_failure_after_all_cleared": terminal_failure_after_all_cleared,
    "previous_controller_all_cleared_before_terminal_failure": previous_controller_all_cleared,
  }
  if isinstance(failure_diagnostics, dict) and failure_diagnostics:
    failure_context["failure_diagnostics"] = copy.deepcopy(failure_diagnostics)
  planning_payload["status"] = "failed"
  planning_payload["run_status"] = "failed"
  planning_payload["failure_reason"] = str(detail or "").strip() or None
  planning_payload["terminal_failure_context"] = copy.deepcopy(failure_context)
  if convergence_payload:
    convergence_payload["status"] = "failed"
    convergence_payload["stage"] = str(current_stage or "").strip() or None
    convergence_payload["failure_reason"] = str(detail or "").strip() or None
    convergence_payload["terminal_failure_context"] = copy.deepcopy(failure_context)
  return planning_payload, convergence_payload, controller_state, terminal_failure_after_all_cleared

def _persist_failed_system_run_snapshot(
  *,
  conn,
  draft_id: str,
  detail: str,
  active_run: Optional[Dict[str, Any]] = None,
  failure_diagnostics: Optional[Dict[str, Any]] = None,
  failure_details: Optional[Dict[str, Any]] = None,
) -> None:
  draft = get_draft(conn, draft_id=str(draft_id).strip())
  planning_run_payload = _parse_json_dict(draft.get("planning_run_json"))
  planning_runtime_payload = _parse_json_dict(draft.get("planning_runtime_json"))
  numeric_solver_feedback_payload = _parse_json_dict(draft.get("numeric_solver_feedback_json"))
  model_input_payload = _parse_json_dict(draft.get("model_input_json"))
  finmo_payload = _parse_json_dict(draft.get("finmo_json"))
  if not isinstance(planning_run_payload, dict):
    planning_run_payload = {}
  active_run_row = active_run if isinstance(active_run, dict) else {}
  current_stage = str(
    active_run_row.get("current_stage")
    or planning_run_payload.get("stage")
    or "system_run_failed"
  ).strip() or "system_run_failed"
  planning_run_id = str(
    active_run_row.get("planning_run_id")
    or planning_run_payload.get("planning_run_id")
    or ""
  ).strip()
  preserved_payloads = _latest_failure_preservation_payloads(
    conn=conn,
    draft_id=str(draft_id).strip(),
    planning_run_id=planning_run_id or None,
  )
  preserved_planning_convergence, preserved_convergence_state, preserved_controller_state, terminal_failure_after_all_cleared = _merge_terminal_failure_context(
    planning_convergence_payload=copy.deepcopy(preserved_payloads.get("planning_convergence_json") or {}),
    convergence_state_payload=copy.deepcopy(preserved_payloads.get("convergence_state_json") or {}),
    current_stage=current_stage,
    detail=str(detail or "").strip(),
    source_kind=str(preserved_payloads.get("source_kind") or "").strip() or None,
    source_checkpoint_id=str(preserved_payloads.get("source_checkpoint_id") or "").strip() or None,
    failure_diagnostics=copy.deepcopy(failure_diagnostics if isinstance(failure_diagnostics, dict) else {}),
  )
  planning_run_payload["stage"] = current_stage
  planning_run_payload["status"] = "failed"
  planning_run_payload["run_status"] = "failed"
  planning_run_payload["failure_reason"] = (
    f"terminal_failure_after_all_cleared: {str(detail or '').strip()}"
    if terminal_failure_after_all_cleared
    else str(detail or "").strip()
  )
  if planning_run_id:
    planning_run_payload["planning_run_id"] = planning_run_id
  if preserved_controller_state:
    planning_run_payload["controller_resolution_state"] = copy.deepcopy(preserved_controller_state)
  planning_run_payload["terminal_failure_context"] = {
    "terminal_failure_after_all_cleared": terminal_failure_after_all_cleared,
    "source_kind": str(preserved_payloads.get("source_kind") or "").strip() or None,
    "source_checkpoint_id": str(preserved_payloads.get("source_checkpoint_id") or "").strip() or None,
    "preserved_last_known_good_state": bool(preserved_planning_convergence or preserved_convergence_state),
  }
  if isinstance(failure_diagnostics, dict) and failure_diagnostics:
    planning_run_payload["terminal_failure_context"]["failure_diagnostics"] = copy.deepcopy(
      failure_diagnostics
    )
    planning_run_payload["cash_strategy_failure_diagnostics"] = copy.deepcopy(
      failure_diagnostics
    )
  # FailFastError carries `details` — per-violation structured data
  # (violations, expected/actual, the specific rows that failed). Persist
  # them on the planning_run failure snapshot so post-mortem analysis
  # never requires re-running with ad-hoc instrumentation.
  if isinstance(failure_details, dict) and failure_details:
    planning_run_payload["terminal_failure_context"]["fail_fast_details"] = copy.deepcopy(
      failure_details
    )
  persist_post_intake_execution_state(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    model_input_json=model_input_payload if isinstance(model_input_payload, dict) else None,
    finmo_json=finmo_payload if isinstance(finmo_payload, dict) else None,
    planning_run_json=copy.deepcopy(planning_run_payload),
    planning_runtime_json=(
      copy.deepcopy(planning_runtime_payload)
      if isinstance(planning_runtime_payload, dict)
      else None
    ),
    planning_convergence_json=copy.deepcopy(preserved_planning_convergence),
    convergence_state_json=copy.deepcopy(preserved_convergence_state),
    numeric_solver_feedback_json=(
      copy.deepcopy(numeric_solver_feedback_payload)
      if isinstance(numeric_solver_feedback_payload, dict)
      else None
    ),
    active_focus="done",
    status="failed",
    completed=False,
    checkpoint_kind="failure_snapshot",
    event_type="system_run_failed",
    event_summary=f"{current_stage}:failed",
  )
