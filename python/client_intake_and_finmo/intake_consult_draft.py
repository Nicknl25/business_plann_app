from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo


_ENSURE_TABLE_READY = False
_ENSURE_TABLE_LOCK = threading.Lock()
_APP_TIMEZONE = ZoneInfo("America/New_York")
_APP_TIMEZONE_NAME = "America/New_York"


def current_app_timestamp_str() -> str:
  return datetime.now(_APP_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S.%f")


def current_app_timestamp_iso() -> str:
  return datetime.now(_APP_TIMEZONE).isoformat()


def current_app_timezone_name() -> str:
  return _APP_TIMEZONE_NAME

def _table_columns(conn, table_name: str) -> Set[str]:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      SELECT COLUMN_NAME
      FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = %s
      """,
      (table_name,),
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass
  out: Set[str] = set()
  for r in rows:
    try:
      out.add(str(r[0]))
    except Exception:
      continue
  return out

def _normalize_flat_value(value: Any) -> Any:
  if isinstance(value, (dict, list)):
    return json.dumps(value, ensure_ascii=False)
  return value


def _safe_float(value: Any) -> Optional[float]:
  try:
    if value is None or value == "":
      return None
    return float(value)
  except Exception:
    return None


_ENGINE_JSON_COLUMNS = (
  "model_input_json",
  "finmo_json",
  "payroll_headcount",
  "debt_schedule",
  "planning_context_summary_json",
  "planning_run_json",
  "planning_runtime_json",
  "planning_convergence_json",
  "repair_guidance_json",
  "convergence_state_json",
  "numeric_solver_feedback_json",
  "financial_story",
)

_PLANNING_STATE_FLAT_COLUMNS = (
  "planning_run_id",
  "planning_run_status",
  "planning_stage",
  "planning_status",
  "planning_last_review_iteration",
  "planning_current_retry_count",
  "planning_current_cycle",
  "planning_detected_issue_count",
  "planning_remaining_issue_count",
  "planning_resolved_issue_count",
  "planning_tolerated_issue_count",
  "planning_iteration_pending_issue_count",
  "planning_latest_checkpoint_id",
  "planning_resume_from_checkpoint_id",
  "planning_requested_action",
  "planning_requested_action_at",
  "planning_requested_action_reason",
  "planning_latest_controller_status",
  "planning_failure_reason",
  "planning_resume_count",
  "planning_source_run_id",
  "planning_superseded_by_run_id",
  "planning_run_started_at",
  "planning_last_heartbeat_at",
  "planning_paused_at",
  "planning_stopped_at",
  "planning_run_completed_at",
)


def _parse_json_payload(raw: Any) -> Any:
  if raw is None:
    return None
  if isinstance(raw, (dict, list)):
    return raw
  try:
    return json.loads(str(raw))
  except Exception:
    return None


def _is_valid_planning_run_payload(payload: Any) -> bool:
  data = _parse_json_payload(payload)
  if not isinstance(data, dict) or not data:
    return False
  stage = str(data.get("stage") or "").strip()
  status = str(data.get("status") or "").strip()
  if not stage or not status:
    return False
  controller_state = data.get("controller_resolution_state")
  if controller_state is not None and not isinstance(controller_state, dict):
    return False
  return True


def _planning_run_flat_field_values(payload: Any) -> Dict[str, Any]:
  data = _parse_json_payload(payload)
  if not isinstance(data, dict) or not data:
    return {}
  controller_state = data.get("controller_resolution_state")
  controller = controller_state if isinstance(controller_state, dict) else {}

  def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
      return None
    try:
      return int(float(value))
    except Exception:
      return None

  last_review_iteration = controller.get("last_review_iteration")
  out = {
    "planning_run_id": str(data.get("planning_run_id") or "").strip() or None,
    "planning_run_status": str(data.get("run_status") or data.get("status") or "").strip() or None,
    "planning_stage": str(data.get("stage") or "").strip() or None,
    "planning_status": str(data.get("status") or "").strip() or None,
    "planning_last_review_iteration": _int_or_none(last_review_iteration),
    "planning_current_retry_count": _int_or_none(
      ((data.get("controller_retry_heartbeat") or {}).get("attempt_number"))
      if isinstance(data.get("controller_retry_heartbeat"), dict)
      else None
    ),
    "planning_current_cycle": (
      _int_or_none(data.get("unified_convergence_cycle_count"))
      if _int_or_none(data.get("unified_convergence_cycle_count")) is not None
      else None
    ),
    "planning_detected_issue_count": _int_or_none(controller.get("detected_issue_count")) if controller else None,
    "planning_remaining_issue_count": _int_or_none(controller.get("remaining_issue_count")) if controller else None,
    "planning_resolved_issue_count": _int_or_none(controller.get("resolved_issue_count")) if controller else None,
    "planning_tolerated_issue_count": _int_or_none(controller.get("tolerated_issue_count")) if controller else None,
    "planning_iteration_pending_issue_count": _int_or_none(controller.get("iteration_pending_issue_count")) if controller else None,
    "planning_latest_checkpoint_id": str(data.get("latest_checkpoint_id") or "").strip() or None,
    "planning_resume_from_checkpoint_id": None,
    "planning_requested_action": None,
    "planning_requested_action_at": None,
    "planning_requested_action_reason": None,
    "planning_latest_controller_status": str(controller.get("status") or "").strip() or None if controller else None,
    "planning_failure_reason": None,
    "planning_resume_count": None,
    "planning_source_run_id": None,
    "planning_superseded_by_run_id": None,
    "planning_run_started_at": None,
    "planning_last_heartbeat_at": None,
    "planning_paused_at": None,
    "planning_stopped_at": None,
    "planning_run_completed_at": None,
  }
  return out


def _planning_run_row_flat_field_values(run_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(run_row, dict) or not run_row:
    return {}
  return {
    "planning_run_id": str(run_row.get("planning_run_id") or "").strip() or None,
    "planning_run_status": str(run_row.get("run_status") or "").strip() or None,
    "planning_stage": str(run_row.get("current_stage") or "").strip() or None,
    "planning_status": str(run_row.get("current_stage_status") or "").strip() or None,
    "planning_last_review_iteration": run_row.get("current_iteration"),
    "planning_current_retry_count": run_row.get("current_retry_count"),
    "planning_current_cycle": run_row.get("current_cycle"),
    "planning_detected_issue_count": run_row.get("latest_detected_issue_count"),
    "planning_remaining_issue_count": run_row.get("latest_remaining_issue_count"),
    "planning_resolved_issue_count": run_row.get("latest_resolved_issue_count"),
    "planning_latest_checkpoint_id": str(run_row.get("latest_checkpoint_id") or "").strip() or None,
    "planning_resume_from_checkpoint_id": str(run_row.get("resume_from_checkpoint_id") or "").strip() or None,
    "planning_requested_action": str(run_row.get("requested_action") or "").strip() or None,
    "planning_requested_action_at": run_row.get("requested_action_at"),
    "planning_requested_action_reason": str(run_row.get("requested_action_reason") or "").strip() or None,
    "planning_latest_controller_status": str(run_row.get("latest_controller_status") or "").strip() or None,
    "planning_failure_reason": str(run_row.get("failure_reason") or "").strip() or None,
    "planning_resume_count": run_row.get("resume_count"),
    "planning_source_run_id": str(run_row.get("source_planning_run_id") or "").strip() or None,
    "planning_superseded_by_run_id": str(run_row.get("superseded_by_planning_run_id") or "").strip() or None,
    "planning_run_started_at": run_row.get("started_at"),
    "planning_last_heartbeat_at": run_row.get("last_heartbeat_at"),
    "planning_paused_at": run_row.get("paused_at"),
    "planning_stopped_at": run_row.get("stopped_at"),
    "planning_run_completed_at": run_row.get("completed_at"),
  }


def _compact_numeric_feedback_runtime_payload(feedback: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = _parse_json_payload(feedback)
  if not isinstance(payload, dict) or not payload:
    return {
      "has_feedback": False,
      "solver_invoked": False,
      "solver_execution_state": "",
      "quarters_with_target_misses": 0,
    }
  target_verification = payload.get("target_verification") if isinstance(payload.get("target_verification"), dict) else {}
  current_cycle_trace = payload.get("current_cycle_trace") if isinstance(payload.get("current_cycle_trace"), dict) else {}
  return {
    "has_feedback": bool(payload.get("has_feedback")),
    "feedback_source": str(payload.get("feedback_source") or "").strip() or None,
    "persistence_stage": str(payload.get("persistence_stage") or "").strip() or None,
    "execution_state": str(payload.get("execution_state") or "").strip() or None,
    "outcome_reason": str(payload.get("outcome_reason") or "").strip() or None,
    "solver_invoked": bool(payload.get("solver_invoked")),
    "solver_execution_state": str(payload.get("solver_execution_state") or "").strip() or None,
    "attempt_count": int(float(payload.get("attempt_count") or 0) if str(payload.get("attempt_count") or "").strip() else 0),
    "target_metric_names": copy.deepcopy(payload.get("target_metric_names") or []),
    "targeted_quarters": copy.deepcopy(payload.get("targeted_quarters") or []),
    "allowed_lever_ids": copy.deepcopy(payload.get("allowed_lever_ids") or []),
    "attempted_lever_families": copy.deepcopy(payload.get("attempted_lever_families") or []),
    "quarters_with_all_targets_within_tolerance": int(float(payload.get("quarters_with_all_targets_within_tolerance") or 0) if str(payload.get("quarters_with_all_targets_within_tolerance") or "").strip() else 0),
    "quarters_with_target_misses": int(float(payload.get("quarters_with_target_misses") or 0) if str(payload.get("quarters_with_target_misses") or "").strip() else 0),
    "quarters_failed": copy.deepcopy(target_verification.get("quarters_failed") or []),
    "best_objective": copy.deepcopy(payload.get("best_objective")),
    "objective_delta": copy.deepcopy(payload.get("objective_delta")),
    "current_cycle": current_cycle_trace.get("cycle"),
    "current_cycle_stage": str(current_cycle_trace.get("stage") or "").strip() or None,
    "current_cycle_status": str(current_cycle_trace.get("status") or "").strip() or None,
    "guidance_scope_quarters": copy.deepcopy(current_cycle_trace.get("guidance_scope_quarters") or []),
    "guidance_metric_count": current_cycle_trace.get("guidance_metric_count"),
    "guidance_metric_names": copy.deepcopy(current_cycle_trace.get("guidance_metric_names") or []),
    "guidance_issue_codes": copy.deepcopy(current_cycle_trace.get("guidance_issue_codes") or []),
    "guidance_lever_count": current_cycle_trace.get("guidance_lever_count"),
    "guidance_lever_ids": copy.deepcopy(current_cycle_trace.get("guidance_lever_ids") or []),
    "plan_status": str(current_cycle_trace.get("plan_status") or "").strip() or None,
    "plan_next_step": str(current_cycle_trace.get("plan_next_step") or "").strip() or None,
    "solver_ready": bool(current_cycle_trace.get("solver_ready")),
    "lever_adjustment_source": str(current_cycle_trace.get("lever_adjustment_source") or "").strip() or None,
    "explicit_lever_adjustment_count": current_cycle_trace.get("explicit_lever_adjustment_count"),
    "auto_generated_lever_adjustment_count": current_cycle_trace.get("auto_generated_lever_adjustment_count"),
    "translated_control_count": current_cycle_trace.get("translated_control_count"),
    "planned_target_quarter_count": current_cycle_trace.get("planned_target_quarter_count"),
    "planned_target_metric_names": copy.deepcopy(current_cycle_trace.get("planned_target_metric_names") or []),
    "planned_target_tolerance_metric_names": copy.deepcopy(current_cycle_trace.get("planned_target_tolerance_metric_names") or []),
    "planned_lever_ids": copy.deepcopy(current_cycle_trace.get("planned_lever_ids") or []),
    "alignment_debug_summary": copy.deepcopy(current_cycle_trace.get("alignment_debug_summary") or {}),
  }


def _compact_alignment_issue_debug_runtime(
  issue_debug_payload: Optional[List[Dict[str, Any]]],
  *,
  max_items: int = 4,
) -> List[Dict[str, Any]]:
  compact_items: List[Dict[str, Any]] = []
  for item in (issue_debug_payload or []):
    if not isinstance(item, dict):
      continue
    compact_items.append(
      {
        "issue_code": str(item.get("issue_code") or "").strip() or None,
        "closure_metric_name": str(item.get("closure_metric_name") or "").strip() or None,
        "repair_target_count": item.get("repair_target_count"),
        "selected_lever_ids": copy.deepcopy(item.get("selected_lever_ids") or []),
        "expected_metric_delta": item.get("expected_metric_delta"),
        "actual_metric_delta": item.get("actual_metric_delta"),
        "gap_reduction": item.get("gap_reduction"),
        "score_delta": item.get("score_delta"),
        "consecutive_gap_stalled_cycles": item.get("consecutive_gap_stalled_cycles"),
        "reason_issue_remains_open": str(item.get("reason_issue_remains_open") or "").strip() or None,
        "flags": copy.deepcopy(item.get("flags") or []),
      }
    )
    if len(compact_items) >= max_items:
      break
  return compact_items


def _compact_convergence_state_runtime_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  data = _parse_json_payload(payload)
  if not isinstance(data, dict) or not data:
    return {
      "has_convergence_state": False,
      "owner": "unified_convergence",
      "current_cycle": None,
      "stage": None,
      "status": None,
    }
  issue_state = data.get("issue_state") if isinstance(data.get("issue_state"), dict) else {}
  retry_state = data.get("retry_state") if isinstance(data.get("retry_state"), dict) else {}
  numeric_state = data.get("numeric_state") if isinstance(data.get("numeric_state"), dict) else {}
  business_context = data.get("business_context") if isinstance(data.get("business_context"), dict) else {}
  deterministic_numeric_guidance = (
    data.get("deterministic_numeric_guidance")
    if isinstance(data.get("deterministic_numeric_guidance"), dict)
    else {}
  )
  plan_summary = data.get("plan_summary") if isinstance(data.get("plan_summary"), dict) else {}
  cycle_debug_summary = data.get("cycle_debug_summary") if isinstance(data.get("cycle_debug_summary"), dict) else {}
  cycle_issue_debug = [
    item for item in (data.get("cycle_issue_debug") or [])
    if isinstance(item, dict)
  ]
  return {
    "has_convergence_state": True,
    "owner": str(data.get("owner") or "").strip() or "unified_convergence",
    "current_cycle": data.get("current_cycle"),
    "stage": str(data.get("stage") or "").strip() or None,
    "status": str(data.get("status") or "").strip() or None,
    "business_name": str(business_context.get("business_name") or "").strip() or None,
    "business_type": str(business_context.get("business_type") or "").strip() or None,
    "planning_mode": str(business_context.get("planning_mode") or "").strip() or None,
    "selected_cash_strategy": str(business_context.get("selected_cash_strategy") or "").strip() or None,
    "detected_issue_count": issue_state.get("detected_issue_count"),
    "remaining_issue_count": issue_state.get("remaining_issue_count"),
    "resolved_issue_count": issue_state.get("resolved_issue_count"),
    "tolerated_issue_count": issue_state.get("tolerated_issue_count"),
    "overall_completion_score_pct": issue_state.get("overall_completion_score_pct"),
    "overall_completion_grade": str(issue_state.get("overall_completion_grade") or "").strip() or None,
    "lowest_quarter_score_pct": issue_state.get("lowest_quarter_score_pct"),
    "failing_quarters": copy.deepcopy(issue_state.get("failing_quarters") or []),
    "open_issue_codes": copy.deepcopy(issue_state.get("open_issue_codes") or []),
    "tolerated_issue_codes": copy.deepcopy(issue_state.get("tolerated_issue_codes") or []),
    "failed_quarters": copy.deepcopy(retry_state.get("failed_quarters") or []),
    "failed_metrics": copy.deepcopy(retry_state.get("failed_metrics") or []),
    "progress_status": str(retry_state.get("progress_status") or "").strip() or None,
    "solver_invoked": bool(numeric_state.get("solver_invoked")),
    "solver_execution_state": str(numeric_state.get("solver_execution_state") or "").strip() or None,
    "quarters_with_target_misses": numeric_state.get("quarters_with_target_misses"),
    "target_metric_names": copy.deepcopy(numeric_state.get("target_metric_names") or []),
    "targeted_quarters": copy.deepcopy(numeric_state.get("targeted_quarters") or []),
    "numeric_guidance_metric_count": len(deterministic_numeric_guidance.get("metric_pressure_packets") or []),
    "numeric_guidance_lever_count": len(deterministic_numeric_guidance.get("lever_band_scaffold") or []),
    "numeric_guidance_scope_quarters": copy.deepcopy(deterministic_numeric_guidance.get("scope_quarters") or []),
    "alignment_debug_summary": copy.deepcopy(cycle_debug_summary),
    "alignment_issue_debug": _compact_alignment_issue_debug_runtime(cycle_issue_debug),
    "plan_status": str(plan_summary.get("status") or "").strip() or None,
    "plan_next_step": str(plan_summary.get("next_step") or "").strip() or None,
    "lever_adjustment_source": str(plan_summary.get("lever_adjustment_source") or "").strip() or None,
    "explicit_lever_adjustment_count": plan_summary.get("explicit_lever_adjustment_count"),
    "auto_generated_lever_adjustment_count": plan_summary.get("auto_generated_lever_adjustment_count"),
    "translated_control_count": plan_summary.get("translated_control_count"),
    "planned_target_quarter_count": len(plan_summary.get("targets_by_quarter") or []),
    "planned_lever_selection_count": len(plan_summary.get("lever_selection") or []),
    "planned_target_metric_names": copy.deepcopy(plan_summary.get("required_target_metric_keys") or []),
  }


def _build_convergence_state_payload(
  *,
  planning_run_json: Optional[Dict[str, Any]],
  numeric_solver_feedback_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  payload = _parse_json_payload(planning_run_json)
  feedback = _parse_json_payload(numeric_solver_feedback_json)
  planning_payload = payload if isinstance(payload, dict) else {}
  feedback_payload = feedback if isinstance(feedback, dict) else {}
  convergence_state = (
    planning_payload.get("current_cycle_convergence_packet")
    if isinstance(planning_payload.get("current_cycle_convergence_packet"), dict)
    else {}
  )
  if not convergence_state:
    controller = (
      planning_payload.get("controller_resolution_state")
      if isinstance(planning_payload.get("controller_resolution_state"), dict)
      else {}
    )
    convergence_context = (
      planning_payload.get("unified_convergence_context")
      if isinstance(planning_payload.get("unified_convergence_context"), dict)
      else {}
    )
    convergence_state = {
      "contract_version": "convergence_state_v1",
      "owner": "unified_convergence",
      "stage": str(planning_payload.get("stage") or "").strip() or None,
      "status": str(planning_payload.get("status") or "").strip() or None,
      "current_cycle": planning_payload.get("unified_convergence_cycle_count"),
      "convergence_engine_contract": copy.deepcopy(
        planning_payload.get("convergence_engine_contract") or {}
      ),
      "business_context": {
        "business_name": str(
          (((convergence_context.get("planning_context_summary") or {}) if isinstance(convergence_context.get("planning_context_summary"), dict) else {}).get("business_name"))
          or convergence_context.get("business_name")
          or ""
        ).strip() or None,
        "business_type": str(
          (((convergence_context.get("planning_context_summary") or {}) if isinstance(convergence_context.get("planning_context_summary"), dict) else {}).get("business_type"))
          or ""
        ).strip() or None,
        "planning_mode": str(planning_payload.get("planning_mode") or "").strip() or None,
        "planning_mode_reason": str(planning_payload.get("planning_mode_reason") or "").strip() or None,
        "selected_cash_strategy": str(convergence_context.get("selected_cash_strategy") or "").strip() or None,
      },
      "issue_state": {
        "controller_status": str(controller.get("status") or "").strip() or None,
        "detected_issue_count": controller.get("detected_issue_count"),
        "remaining_issue_count": controller.get("remaining_issue_count"),
        "resolved_issue_count": controller.get("resolved_issue_count"),
        "tolerated_issue_count": controller.get("tolerated_issue_count"),
        "iteration_pending_issue_count": controller.get("iteration_pending_issue_count"),
        "overall_completion_score_pct": controller.get("overall_completion_score_pct"),
        "overall_completion_grade": controller.get("overall_completion_grade"),
        "lowest_quarter_score_pct": controller.get("lowest_quarter_score_pct"),
        "failing_quarters": copy.deepcopy(controller.get("failing_quarters") or []),
        "open_issue_codes": [
          str(item.get("issue_code") or "").strip()
          for item in (controller.get("remaining_issues") or [])
          if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
        ],
        "tolerated_issue_codes": [
          str(item.get("issue_code") or "").strip()
          for item in (controller.get("tolerated_issues") or [])
          if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
        ],
      },
      "retry_state": {},
      "numeric_state": {},
    }
  if isinstance(convergence_state, dict):
    numeric_state = (
      convergence_state.get("numeric_state")
      if isinstance(convergence_state.get("numeric_state"), dict)
      else {}
    )
    if isinstance(feedback_payload, dict) and feedback_payload:
      merged_numeric = dict(numeric_state)
      merged_numeric.setdefault("solver_invoked", bool(feedback_payload.get("solver_invoked")))
      merged_numeric.setdefault(
        "solver_execution_state",
        str(feedback_payload.get("solver_execution_state") or "").strip() or None,
      )
      merged_numeric.setdefault(
        "quarters_with_target_misses",
        feedback_payload.get("quarters_with_target_misses"),
      )
      merged_numeric.setdefault(
        "target_metric_names",
        copy.deepcopy(feedback_payload.get("target_metric_names") or []),
      )
      merged_numeric.setdefault(
        "targeted_quarters",
        copy.deepcopy(feedback_payload.get("targeted_quarters") or []),
      )
      convergence_state["numeric_state"] = merged_numeric
  return convergence_state if isinstance(convergence_state, dict) else {}


def _compact_iteration_runtime_payload(iteration_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = iteration_payload if isinstance(iteration_payload, dict) else {}
  quality = payload.get("quality_assessment") if isinstance(payload.get("quality_assessment"), dict) else {}
  stall = payload.get("stall_assessment_before") if isinstance(payload.get("stall_assessment_before"), dict) else {}
  hard_rules = payload.get("hard_rule_assessment_after") if isinstance(payload.get("hard_rule_assessment_after"), dict) else {}
  retry_context = (
    payload.get("controller_retry_context")
    if isinstance(payload.get("controller_retry_context"), dict)
    else {}
  )
  issue_alignment_debug = [
    item for item in (quality.get("issue_alignment_debug") or [])
    if isinstance(item, dict)
  ]
  return {
    "cycle_index": payload.get("cycle_index"),
    "attempt_number": payload.get("attempt_number"),
    "accepted": bool(payload.get("accepted")),
    "meaningful_progress": bool(quality.get("meaningful_progress")),
    "remaining_issue_count_before": quality.get("remaining_issue_count_before"),
    "remaining_issue_count_after": quality.get("remaining_issue_count_after"),
    "resolved_issue_count_before": quality.get("resolved_issue_count_before"),
    "resolved_issue_count_after": quality.get("resolved_issue_count_after"),
    "issue_count_delta": (
      quality.get("issue_count_delta")
      if quality.get("issue_count_delta") is not None
      else quality.get("net_issue_change")
    ),
    "stall_detected": bool(stall.get("stalled")),
    "force_structural_driver_changes": bool(stall.get("force_structural_driver_changes")),
    "all_hard_rules_cleared": bool(hard_rules.get("all_hard_rules_cleared")),
    "remaining_hard_issue_count": hard_rules.get("remaining_hard_issue_count"),
    "alignment_debug_summary": copy.deepcopy(quality.get("issue_alignment_debug_summary") or {}),
    "alignment_issue_debug": _compact_alignment_issue_debug_runtime(issue_alignment_debug),
    "retry_context": {
      "progress_status": str(retry_context.get("progress_status") or "").strip() or None,
      "required_change_magnitude": str(retry_context.get("required_change_magnitude") or "").strip() or None,
      "minimum_new_lever_count": retry_context.get("minimum_new_lever_count"),
      "must_change_strategy_class": bool(retry_context.get("must_change_strategy_class")),
      "failed_quarters": copy.deepcopy(retry_context.get("failed_quarters") or []),
      "failed_metrics": copy.deepcopy(retry_context.get("failed_metrics") or []),
      "required_lever_families": copy.deepcopy(retry_context.get("required_lever_families") or []),
      "required_primary_metric_candidates": copy.deepcopy(
        retry_context.get("required_primary_metric_candidates") or []
      ),
      "last_failure_reason": str(retry_context.get("last_failure_reason") or "").strip() or None,
    },
  }


def _build_planning_runtime_payload(
  *,
  planning_run_json: Optional[Dict[str, Any]],
  numeric_solver_feedback_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  payload = _parse_json_payload(planning_run_json)
  feedback = _parse_json_payload(numeric_solver_feedback_json)
  planning_payload = payload if isinstance(payload, dict) else {}
  feedback_payload = feedback if isinstance(feedback, dict) else {}
  controller_state = (
    planning_payload.get("controller_resolution_state")
    if isinstance(planning_payload.get("controller_resolution_state"), dict)
    else {}
  )
  heartbeat = (
    planning_payload.get("controller_retry_heartbeat")
    if isinstance(planning_payload.get("controller_retry_heartbeat"), dict)
    else {}
  )
  deterministic_summary = (
    planning_payload.get("deterministic_convergence_summary")
    if isinstance(planning_payload.get("deterministic_convergence_summary"), dict)
    else {}
  )
  unified_context = (
    planning_payload.get("unified_convergence_context")
    if isinstance(planning_payload.get("unified_convergence_context"), dict)
    else {}
  )
  convergence_state = _build_convergence_state_payload(
    planning_run_json=planning_payload,
    numeric_solver_feedback_json=feedback_payload,
  )
  iteration_list = planning_payload.get("unified_convergence_iterations")
  latest_iteration = {}
  if isinstance(iteration_list, list):
    for item in reversed(iteration_list):
      if isinstance(item, dict):
        latest_iteration = item
        break
  return {
    "contract_version": "planning_runtime_v1",
    "planning_run_id": str(planning_payload.get("planning_run_id") or "").strip() or None,
    "stage": str(planning_payload.get("stage") or "").strip() or None,
    "status": str(planning_payload.get("status") or "").strip() or None,
    "run_status": str(planning_payload.get("run_status") or "").strip() or None,
    "planning_mode": str(planning_payload.get("planning_mode") or "").strip() or None,
    "planning_mode_reason": str(planning_payload.get("planning_mode_reason") or "").strip() or None,
    "controller_resolution_state": {
      "status": str(controller_state.get("status") or "").strip() or None,
      "detected_issue_count": controller_state.get("detected_issue_count"),
      "remaining_issue_count": controller_state.get("remaining_issue_count"),
      "resolved_issue_count": controller_state.get("resolved_issue_count"),
      "tolerated_issue_count": controller_state.get("tolerated_issue_count"),
      "iteration_pending_issue_count": controller_state.get("iteration_pending_issue_count"),
    },
    "unified_convergence_cycle_count": planning_payload.get("unified_convergence_cycle_count"),
    "convergence_state": _compact_convergence_state_runtime_payload(convergence_state),
    "controller_retry_heartbeat": {
      "heartbeat_at_eastern": (
        str(heartbeat.get("heartbeat_at_eastern") or "").strip()
        or str(heartbeat.get("heartbeat_at_utc") or "").strip()
        or None
      ),
      "heartbeat_timezone": str(heartbeat.get("heartbeat_timezone") or "").strip() or _APP_TIMEZONE_NAME,
      "pass_name": str(heartbeat.get("pass_name") or "").strip() or None,
      "attempt_number": heartbeat.get("attempt_number"),
      "attempt_stage": str(heartbeat.get("attempt_stage") or "").strip() or None,
      "lifecycle_status": str(heartbeat.get("lifecycle_status") or "").strip() or None,
      "solver_invoked": bool(heartbeat.get("solver_invoked")),
      "solver_execution_state": str(heartbeat.get("solver_execution_state") or "").strip() or None,
      "quarters_with_target_misses": heartbeat.get("quarters_with_target_misses"),
    },
    "latest_cycle": _compact_iteration_runtime_payload(latest_iteration),
    "numeric_feedback": _compact_numeric_feedback_runtime_payload(feedback_payload),
    "deterministic_convergence_summary": copy.deepcopy(deterministic_summary),
  }


def _build_planning_convergence_payload(
  *,
  planning_run_json: Optional[Dict[str, Any]],
  planning_runtime_json: Optional[Dict[str, Any]],
  repair_guidance_json: Optional[Dict[str, Any]],
  convergence_state_json: Optional[Dict[str, Any]],
  numeric_solver_feedback_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  planning_payload = _parse_json_payload(planning_run_json)
  runtime_payload = _parse_json_payload(planning_runtime_json)
  guidance_payload = _parse_json_payload(repair_guidance_json)
  convergence_payload = _parse_json_payload(convergence_state_json)
  feedback_payload = _parse_json_payload(numeric_solver_feedback_json)

  planning_data = planning_payload if isinstance(planning_payload, dict) else {}
  runtime_data = runtime_payload if isinstance(runtime_payload, dict) else {}
  guidance_data = guidance_payload if isinstance(guidance_payload, dict) else {}
  convergence_data = convergence_payload if isinstance(convergence_payload, dict) else {}
  feedback_data = feedback_payload if isinstance(feedback_payload, dict) else {}

  controller = (
    planning_data.get("controller_resolution_state")
    if isinstance(planning_data.get("controller_resolution_state"), dict)
    else {}
  )
  convergence_state = (
    convergence_data
    if convergence_data
    else runtime_data.get("convergence_state")
    if isinstance(runtime_data.get("convergence_state"), dict)
    else {}
  )
  issue_state = (
    convergence_state.get("issue_state")
    if isinstance(convergence_state.get("issue_state"), dict)
    else {}
  )
  retry_state = (
    convergence_state.get("retry_state")
    if isinstance(convergence_state.get("retry_state"), dict)
    else {}
  )
  numeric_state = (
    convergence_state.get("numeric_state")
    if isinstance(convergence_state.get("numeric_state"), dict)
    else {}
  )
  current_cycle_packet = (
    planning_data.get("current_cycle_convergence_packet")
    if isinstance(planning_data.get("current_cycle_convergence_packet"), dict)
    else {}
  )
  convergence_scorecard = (
    convergence_state.get("convergence_scorecard")
    if isinstance(convergence_state.get("convergence_scorecard"), dict)
    else {}
  )
  hard_rule_state = (
    convergence_state.get("hard_rule_state")
    if isinstance(convergence_state.get("hard_rule_state"), dict)
    else {}
  )
  if not hard_rule_state:
    hard_rule_state = (
      current_cycle_packet.get("hard_rule_state")
      if isinstance(current_cycle_packet.get("hard_rule_state"), dict)
      else {}
    )
  if not hard_rule_state:
    hard_rule_state = (
      planning_data.get("hard_rule_assessment")
      if isinstance(planning_data.get("hard_rule_assessment"), dict)
      else {}
    )
  if not hard_rule_state:
    hard_rule_state = (
      ((planning_data.get("unified_convergence_context") or {}) if isinstance(planning_data.get("unified_convergence_context"), dict) else {}).get("hard_rule_assessment")
      if isinstance(((planning_data.get("unified_convergence_context") or {}) if isinstance(planning_data.get("unified_convergence_context"), dict) else {}).get("hard_rule_assessment"), dict)
      else {}
    )
  iterations = [
    item for item in (planning_data.get("unified_convergence_iterations") or [])
    if isinstance(item, dict)
  ]
  latest_quality = (
    iterations[-1].get("quality_assessment")
    if iterations and isinstance(iterations[-1].get("quality_assessment"), dict)
    else {}
  )
  alignment_debug_summary = (
    latest_quality.get("issue_alignment_debug_summary")
    if isinstance(latest_quality.get("issue_alignment_debug_summary"), dict)
    else current_cycle_packet.get("cycle_debug_summary")
    if isinstance(current_cycle_packet.get("cycle_debug_summary"), dict)
    else {}
  )
  alignment_issue_debug = (
    latest_quality.get("issue_alignment_debug")
    if isinstance(latest_quality.get("issue_alignment_debug"), list)
    else current_cycle_packet.get("cycle_issue_debug")
    if isinstance(current_cycle_packet.get("cycle_issue_debug"), list)
    else []
  )
  score_delta = _safe_float(convergence_scorecard.get("score_delta"))
  if score_delta is not None:
    score_delta = int(round(score_delta))
  elif len(iterations) >= 2:
    prev_quality = iterations[-2].get("quality_assessment") if isinstance(iterations[-2].get("quality_assessment"), dict) else {}
    curr_quality = iterations[-1].get("quality_assessment") if isinstance(iterations[-1].get("quality_assessment"), dict) else {}
    prev_score = _safe_float(prev_quality.get("overall_completion_score_pct"))
    curr_score = _safe_float(curr_quality.get("overall_completion_score_pct"))
    if prev_score is not None and curr_score is not None:
      score_delta = int(round(curr_score - prev_score))

  overall_score = (
    issue_state.get("overall_completion_score_pct")
    if issue_state
    else controller.get("overall_completion_score_pct")
  )
  overall_grade = (
    issue_state.get("overall_completion_grade")
    if issue_state
    else controller.get("overall_completion_grade")
  )
  lowest_quarter_score = (
    issue_state.get("lowest_quarter_score_pct")
    if issue_state
    else controller.get("lowest_quarter_score_pct")
  )
  remaining_issue_count = (
    issue_state.get("remaining_issue_count")
    if issue_state
    else controller.get("remaining_issue_count")
  )
  remaining_hard_issue_count = int(_safe_float(hard_rule_state.get("remaining_hard_issue_count")) or 0)
  all_hard_rules_cleared = bool(hard_rule_state.get("all_hard_rules_cleared"))
  progress_status = (
    str(retry_state.get("progress_status") or "").strip()
    or str((((planning_data.get("controller_retry_heartbeat") or {}) if isinstance(planning_data.get("controller_retry_heartbeat"), dict) else {}).get("controller_retry_context") or {}).get("progress_status") or "").strip()
    or None
  )
  guidance_block = (
    guidance_data.get("deterministic_numeric_guidance")
    if isinstance(guidance_data.get("deterministic_numeric_guidance"), dict)
    else {}
  )
  return {
    "contract_version": "planning_convergence_v1",
    "planning_run_id": str(planning_data.get("planning_run_id") or "").strip() or None,
    "stage": str(planning_data.get("stage") or "").strip() or None,
    "status": str(planning_data.get("status") or "").strip() or None,
    "run_status": str(planning_data.get("run_status") or "").strip() or None,
    "current_cycle": planning_data.get("unified_convergence_cycle_count"),
    "current_retry_count": (
      ((planning_data.get("controller_retry_heartbeat") or {}) if isinstance(planning_data.get("controller_retry_heartbeat"), dict) else {}).get("attempt_number")
    ),
    "detected_issue_count": issue_state.get("detected_issue_count") if issue_state else controller.get("detected_issue_count"),
    "remaining_issue_count": remaining_issue_count,
    "resolved_issue_count": issue_state.get("resolved_issue_count") if issue_state else controller.get("resolved_issue_count"),
    "tolerated_issue_count": issue_state.get("tolerated_issue_count") if issue_state else controller.get("tolerated_issue_count"),
    "iteration_pending_issue_count": issue_state.get("iteration_pending_issue_count") if issue_state else controller.get("iteration_pending_issue_count"),
    "planning_quality_score": overall_score,
    "planning_quality_grade": str(overall_grade or "").strip() or None,
    "planning_quality_pass": bool(
      _safe_float(overall_score) is not None
      and float(_safe_float(overall_score) or 0.0) >= 80.0
      and all_hard_rules_cleared
      and remaining_hard_issue_count == 0
    ),
    "planning_remaining_hard_issue_count": remaining_hard_issue_count,
    "planning_cycle_progress_status": progress_status,
    "planning_score_delta": score_delta,
    "lowest_quarter_score_pct": lowest_quarter_score,
    "controller_overall_completion_score_pct": issue_state.get("overall_completion_score_pct"),
    "controller_overall_completion_grade": str(issue_state.get("overall_completion_grade") or "").strip() or None,
    "controller_lowest_quarter_score_pct": issue_state.get("lowest_quarter_score_pct"),
    "convergence_overall_score": convergence_scorecard.get("overall_score"),
    "convergence_score_delta": convergence_scorecard.get("score_delta"),
    "all_hard_rules_cleared": all_hard_rules_cleared,
    "failing_quarters": copy.deepcopy(issue_state.get("failing_quarters") or controller.get("failing_quarters") or []),
    "solver_invoked": bool(numeric_state.get("solver_invoked") or feedback_data.get("solver_invoked")),
    "solver_execution_state": str(
      numeric_state.get("solver_execution_state")
      or feedback_data.get("solver_execution_state")
      or ""
    ).strip() or None,
    "quarters_with_target_misses": (
      numeric_state.get("quarters_with_target_misses")
      if numeric_state
      else feedback_data.get("quarters_with_target_misses")
    ),
    "target_metric_names": copy.deepcopy(
      numeric_state.get("target_metric_names")
      if numeric_state
      else feedback_data.get("target_metric_names")
      or []
    ),
    "targeted_quarters": copy.deepcopy(
      numeric_state.get("targeted_quarters")
      if numeric_state
      else feedback_data.get("targeted_quarters")
      or []
    ),
    "repair_guidance_summary": {
      "scope_quarters": copy.deepcopy(guidance_block.get("scope_quarters") or guidance_data.get("required_target_quarters") or []),
      "metric_pressure_count": len(guidance_block.get("metric_pressure_packets") or []),
      "lever_band_count": len(guidance_block.get("lever_band_scaffold") or []),
    },
    "alignment_debug_summary": copy.deepcopy(alignment_debug_summary),
    "alignment_issue_debug": _compact_alignment_issue_debug_runtime(alignment_issue_debug),
    "current_cycle_convergence_packet": copy.deepcopy(current_cycle_packet),
    "convergence_state": _compact_convergence_state_runtime_payload(convergence_state),
    "numeric_feedback": _compact_numeric_feedback_runtime_payload(feedback_data),
  }


def _should_store_full_planning_payload(
  *,
  checkpoint_kind: str,
  run_status: str,
  has_existing_run: bool,
) -> bool:
  kind = str(checkpoint_kind or "").strip().lower()
  status = str(run_status or "").strip().lower()
  if not has_existing_run:
    return True
  if status in {"completed", "failed", "paused", "stopped"}:
    return True
  if kind in {"failure_snapshot", "run_pause", "run_stop", "run_completed", "resume_snapshot"}:
    return True
  return False


def _should_store_heavy_checkpoint_payloads(
  *,
  checkpoint_kind: str,
  run_status: str,
) -> bool:
  kind = str(checkpoint_kind or "").strip().lower()
  status = str(run_status or "").strip().lower()
  if status in {"completed", "failed", "paused", "stopped"}:
    return True
  return kind in {"failure_snapshot", "run_pause", "run_stop", "run_completed", "resume_snapshot"}


def _table_indexes(conn, table_name: str) -> Set[str]:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      SELECT DISTINCT INDEX_NAME
      FROM INFORMATION_SCHEMA.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = %s
      """,
      (table_name,),
    )
    rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass
  out: Set[str] = set()
  for r in rows:
    try:
      out.add(str(r[0]))
    except Exception:
      continue
  return out


def _acquire_named_lock(conn, *, lock_name: str, timeout_seconds: int = 30) -> bool:
  cur = conn.cursor()
  try:
    cur.execute("SELECT GET_LOCK(%s, %s)", (str(lock_name), int(timeout_seconds)))
    row = cur.fetchone()
    try:
      value = row[0] if isinstance(row, (list, tuple)) else row
    except Exception:
      value = row
    return value == 1
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _release_named_lock(conn, *, lock_name: str) -> None:
  cur = conn.cursor()
  try:
    cur.execute("SELECT RELEASE_LOCK(%s)", (str(lock_name),))
    cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _trigger_exists(conn, *, trigger_name: str) -> bool:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      SELECT 1
      FROM INFORMATION_SCHEMA.TRIGGERS
      WHERE TRIGGER_SCHEMA = DATABASE()
        AND TRIGGER_NAME = %s
      LIMIT 1
      """,
      (str(trigger_name),),
    )
    return bool(cur.fetchone())
  finally:
    try:
      cur.close()
    except Exception:
      pass


def _ensure_completion_consistency_triggers(conn) -> None:
  cols = _table_columns(conn, "intake_consult_drafts")
  trigger_specs = {
    "trg_consistency_completion_guard_bi_v1": "INSERT",
    "trg_consistency_completion_guard_bu_v1": "UPDATE",
  }
  completion_conditions = [
    "LOWER(COALESCE(NEW.active_focus, '')) = 'done'",
    "LOWER(COALESCE(NEW.status, '')) = 'completed'",
    "NEW.completed_at IS NOT NULL",
  ]
  if "consistency_passed" in cols:
    completion_conditions.insert(0, "COALESCE(NEW.consistency_passed, 0) = 1")
  completion_predicate = "\n    OR ".join(completion_conditions)
  trigger_body = """
BEGIN
  IF (
    {completion_predicate}
  ) AND (
    NEW.planning_run_json IS NULL
    OR JSON_VALID(NEW.planning_run_json) = 0
    OR JSON_EXTRACT(CAST(NEW.planning_run_json AS JSON), '$.stage') IS NULL
    OR JSON_EXTRACT(CAST(NEW.planning_run_json AS JSON), '$.status') IS NULL
  ) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'consistency_completion_requires_planning_run';
  END IF;
END
""".strip().format(completion_predicate=completion_predicate)
  cur = conn.cursor()
  try:
    for trigger_name, event_name in trigger_specs.items():
      if _trigger_exists(conn, trigger_name=trigger_name):
        continue
      cur.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE {event_name} ON intake_consult_drafts
        FOR EACH ROW
        {trigger_body}
        """
      )
    conn.commit()
  except Exception:
    try:
      conn.rollback()
    except Exception:
      pass
    raise
  finally:
    try:
      cur.close()
    except Exception:
      pass


def ensure_table(conn) -> None:
  global _ENSURE_TABLE_READY
  if _ENSURE_TABLE_READY:
    return
  with _ENSURE_TABLE_LOCK:
    if _ENSURE_TABLE_READY:
      return
    lock_name = "intake_consult_drafts_schema_bootstrap_v1"
    lock_acquired = _acquire_named_lock(conn, lock_name=lock_name, timeout_seconds=30)
    if not lock_acquired:
      raise RuntimeError("intake_consult_drafts_schema_bootstrap_lock_timeout")
    try:
      _ensure_table_inner(conn)
      _ENSURE_TABLE_READY = True
    finally:
      try:
        _release_named_lock(conn, lock_name=lock_name)
      except Exception:
        pass


def _ensure_table_inner(conn) -> None:
  cur = conn.cursor()
  try:
    cur.execute(
      """
      CREATE TABLE IF NOT EXISTS intake_consult_drafts (
        draft_id CHAR(32) NOT NULL PRIMARY KEY,
        client_id CHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
        active_focus VARCHAR(20) NOT NULL DEFAULT 'ops',
        ops_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        market_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        people_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        financials_confirmed TINYINT(1) NOT NULL DEFAULT 0,
        business_name VARCHAR(255) NULL,
        business_address LONGTEXT NULL,
        address_street VARCHAR(255) NULL,
        address_city VARCHAR(255) NULL,
        address_state VARCHAR(255) NULL,
        address_zip VARCHAR(50) NULL,
        address_country VARCHAR(255) NULL,
        business_start_date VARCHAR(50) NULL,
        messages_json LONGTEXT NULL,
        operating_model_json LONGTEXT NULL,
        target_market_json LONGTEXT NULL,
        people_json LONGTEXT NULL,
        financials_json LONGTEXT NULL,
        marketing_model_json LONGTEXT NULL,
        marketing_schedule_json LONGTEXT NULL,
        financials_year1_json LONGTEXT NULL,
        realism_memo_json LONGTEXT NULL,
        model_input_json LONGTEXT NULL,
        finmo_json LONGTEXT NULL,
        payroll_headcount LONGTEXT NULL,
        debt_schedule LONGTEXT NULL,
        planning_context_summary_json LONGTEXT NULL,
        planning_run_json LONGTEXT NULL,
        planning_runtime_json LONGTEXT NULL,
        planning_convergence_json LONGTEXT NULL,
        repair_guidance_json LONGTEXT NULL,
        convergence_state_json LONGTEXT NULL,
        numeric_solver_feedback_json LONGTEXT NULL,
        financial_story LONGTEXT NULL,
        planning_run_id CHAR(32) NULL,
        planning_run_status VARCHAR(32) NULL,
        planning_stage VARCHAR(64) NULL,
        planning_status VARCHAR(32) NULL,
        planning_last_review_iteration INT NULL,
        planning_current_retry_count INT NULL,
        planning_current_cycle INT NULL,
        planning_detected_issue_count INT NULL,
        planning_remaining_issue_count INT NULL,
        planning_resolved_issue_count INT NULL,
        planning_tolerated_issue_count INT NULL,
        planning_iteration_pending_issue_count INT NULL,
        planning_latest_checkpoint_id CHAR(32) NULL,
        planning_resume_from_checkpoint_id CHAR(32) NULL,
        planning_requested_action VARCHAR(32) NULL,
        planning_requested_action_at DATETIME(6) NULL,
        planning_requested_action_reason LONGTEXT NULL,
        planning_latest_controller_status VARCHAR(64) NULL,
        planning_failure_reason LONGTEXT NULL,
        planning_resume_count INT NULL,
        planning_source_run_id CHAR(32) NULL,
        planning_superseded_by_run_id CHAR(32) NULL,
        planning_run_started_at DATETIME(6) NULL,
        planning_last_heartbeat_at DATETIME(6) NULL,
        planning_paused_at DATETIME(6) NULL,
        planning_stopped_at DATETIME(6) NULL,
        planning_run_completed_at DATETIME(6) NULL,
        pending_ops_milestone_json LONGTEXT NULL,
        fulfillment_json JSON NULL,
        ops_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        market_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        people_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        financials_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        completed_at DATETIME(6) NULL,
        submitted_at DATETIME(6) NULL,
        intake_submission_id BIGINT UNSIGNED NULL,
        UNIQUE KEY uniq_client_id (client_id),
        KEY idx_status (status),
        KEY idx_active_focus (active_focus),
        KEY idx_updated_at (updated_at)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
      """
    )
  finally:
    try:
      cur.close()
    except Exception:
      pass

  cur = conn.cursor()
  try:
    cur.execute(
      """
      CREATE TABLE IF NOT EXISTS planning_runs (
        planning_run_id CHAR(32) NOT NULL PRIMARY KEY,
        draft_id CHAR(32) NOT NULL,
        client_id CHAR(20) NOT NULL,
        run_status VARCHAR(32) NOT NULL,
        current_stage VARCHAR(64) NULL,
        current_stage_status VARCHAR(32) NULL,
        current_iteration INT NULL,
        current_retry_count INT NULL,
        current_cycle INT NULL,
        latest_detected_issue_count INT NULL,
        latest_remaining_issue_count INT NULL,
        latest_resolved_issue_count INT NULL,
        latest_checkpoint_id CHAR(32) NULL,
        resume_from_checkpoint_id CHAR(32) NULL,
        source_planning_run_id CHAR(32) NULL,
        superseded_by_planning_run_id CHAR(32) NULL,
        requested_action VARCHAR(32) NULL,
        requested_action_at DATETIME(6) NULL,
        requested_action_reason LONGTEXT NULL,
        latest_controller_status VARCHAR(64) NULL,
        failure_reason LONGTEXT NULL,
        trigger_type VARCHAR(32) NULL,
        resume_count INT NOT NULL DEFAULT 0,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        started_at DATETIME(6) NOT NULL,
        last_heartbeat_at DATETIME(6) NULL,
        paused_at DATETIME(6) NULL,
        stopped_at DATETIME(6) NULL,
        completed_at DATETIME(6) NULL,
        acceptance_verdict_json LONGTEXT NULL,
        KEY idx_planning_runs_draft_id (draft_id),
        KEY idx_planning_runs_client_id (client_id),
        KEY idx_planning_runs_run_status (run_status),
        KEY idx_planning_runs_current_stage (current_stage),
        KEY idx_planning_runs_last_heartbeat_at (last_heartbeat_at),
        KEY idx_planning_runs_draft_status (draft_id, run_status),
        KEY idx_planning_runs_draft_started_at (draft_id, started_at),
        KEY idx_planning_runs_requested_action (requested_action),
        KEY idx_planning_runs_source_run (source_planning_run_id)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
      """
    )
    cur.execute(
      """
      CREATE TABLE IF NOT EXISTS planning_run_checkpoints (
        checkpoint_id CHAR(32) NOT NULL PRIMARY KEY,
        planning_run_id CHAR(32) NOT NULL,
        draft_id CHAR(32) NOT NULL,
        client_id CHAR(20) NOT NULL,
        stage VARCHAR(64) NULL,
        stage_status VARCHAR(32) NULL,
        iteration INT NULL,
        retry_count INT NULL,
        cycle INT NULL,
        checkpoint_kind VARCHAR(32) NOT NULL,
        controller_resolution_state_json LONGTEXT NULL,
        planning_run_json LONGTEXT NULL,
        planning_convergence_json LONGTEXT NULL,
        repair_guidance_json LONGTEXT NULL,
        convergence_state_json LONGTEXT NULL,
        numeric_solver_feedback_json LONGTEXT NULL,
        financial_story LONGTEXT NULL,
        model_input_json LONGTEXT NULL,
        finmo_json LONGTEXT NULL,
        realism_memo_json LONGTEXT NULL,
        diagnostics_json LONGTEXT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        KEY idx_planning_run_checkpoints_run_created (planning_run_id, created_at),
        KEY idx_planning_run_checkpoints_draft_created (draft_id, created_at),
        KEY idx_planning_run_checkpoints_kind (checkpoint_kind),
        KEY idx_planning_run_checkpoints_stage (stage)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
      """
    )
    cur.execute(
      """
      CREATE TABLE IF NOT EXISTS planning_stage_events (
        event_id CHAR(32) NOT NULL PRIMARY KEY,
        planning_run_id CHAR(32) NOT NULL,
        draft_id CHAR(32) NOT NULL,
        client_id CHAR(20) NOT NULL,
        stage VARCHAR(64) NULL,
        stage_status VARCHAR(32) NULL,
        iteration INT NULL,
        retry_count INT NULL,
        cycle INT NULL,
        event_type VARCHAR(64) NOT NULL,
        event_summary LONGTEXT NULL,
        event_payload_json LONGTEXT NULL,
        created_at DATETIME(6) NOT NULL,
        KEY idx_planning_stage_events_run_created (planning_run_id, created_at),
        KEY idx_planning_stage_events_draft_created (draft_id, created_at),
        KEY idx_planning_stage_events_event_type (event_type),
        KEY idx_planning_stage_events_stage (stage)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
      """
    )
  finally:
    try:
      cur.close()
    except Exception:
      pass

  # Older deployments may have created the table without newer columns.
  cols = _table_columns(conn, "intake_consult_drafts")
  alterations: list[str] = []
  if "active_focus" not in cols:
    alterations.append("ADD COLUMN active_focus VARCHAR(20) NOT NULL DEFAULT 'ops'")
  if "ops_confirmed" not in cols:
    alterations.append("ADD COLUMN ops_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "market_confirmed" not in cols:
    alterations.append("ADD COLUMN market_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "people_confirmed" not in cols:
    alterations.append("ADD COLUMN people_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "financials_confirmed" not in cols:
    alterations.append("ADD COLUMN financials_confirmed TINYINT(1) NOT NULL DEFAULT 0")
  if "business_name" not in cols:
    alterations.append("ADD COLUMN business_name VARCHAR(255) NULL")
  if "business_address" not in cols:
    alterations.append("ADD COLUMN business_address LONGTEXT NULL")
  if "address_street" not in cols:
    alterations.append("ADD COLUMN address_street VARCHAR(255) NULL")
  if "address_city" not in cols:
    alterations.append("ADD COLUMN address_city VARCHAR(255) NULL")
  if "address_state" not in cols:
    alterations.append("ADD COLUMN address_state VARCHAR(255) NULL")
  if "address_zip" not in cols:
    alterations.append("ADD COLUMN address_zip VARCHAR(50) NULL")
  if "address_country" not in cols:
    alterations.append("ADD COLUMN address_country VARCHAR(255) NULL")
  if "business_start_date" not in cols:
    alterations.append("ADD COLUMN business_start_date VARCHAR(50) NULL")
  if "target_market_json" not in cols:
    alterations.append("ADD COLUMN target_market_json LONGTEXT NULL")
  if "people_json" not in cols:
    alterations.append("ADD COLUMN people_json LONGTEXT NULL")
  if "financials_json" not in cols:
    alterations.append("ADD COLUMN financials_json LONGTEXT NULL")
  if "marketing_model_json" not in cols:
    alterations.append("ADD COLUMN marketing_model_json LONGTEXT NULL")
  # R-MKTG-03: the settled marketing percent DECOMPOSED into customers, new
  # customers and CAC. Its own column rather than a key inside finmo_json,
  # because it is not finmo output and because R31 pins finmo_json's digest -
  # a new key there would move a golden for a payload the engine never reads.
  if "marketing_schedule_json" not in cols:
    alterations.append("ADD COLUMN marketing_schedule_json LONGTEXT NULL")
  if "financials_year1_json" not in cols:
    alterations.append("ADD COLUMN financials_year1_json LONGTEXT NULL")
  if "realism_memo_json" not in cols:
    alterations.append("ADD COLUMN realism_memo_json LONGTEXT NULL")
  if "model_input_json" not in cols:
    alterations.append("ADD COLUMN model_input_json LONGTEXT NULL")
  if "finmo_json" not in cols:
    alterations.append("ADD COLUMN finmo_json LONGTEXT NULL")
  if "payroll_headcount" not in cols:
    alterations.append("ADD COLUMN payroll_headcount LONGTEXT NULL")
  if "debt_schedule" not in cols:
    alterations.append("ADD COLUMN debt_schedule LONGTEXT NULL")
  if "planning_context_summary_json" not in cols:
    alterations.append("ADD COLUMN planning_context_summary_json LONGTEXT NULL")
  if "planning_run_json" not in cols:
    alterations.append("ADD COLUMN planning_run_json LONGTEXT NULL")
  if "planning_runtime_json" not in cols:
    alterations.append("ADD COLUMN planning_runtime_json LONGTEXT NULL")
  if "planning_convergence_json" not in cols:
    alterations.append("ADD COLUMN planning_convergence_json LONGTEXT NULL")
  if "repair_guidance_json" not in cols:
    alterations.append("ADD COLUMN repair_guidance_json LONGTEXT NULL")
  if "convergence_state_json" not in cols:
    alterations.append("ADD COLUMN convergence_state_json LONGTEXT NULL")
  if "numeric_solver_feedback_json" not in cols:
    alterations.append("ADD COLUMN numeric_solver_feedback_json LONGTEXT NULL")
  if "financial_story" not in cols:
    alterations.append("ADD COLUMN financial_story LONGTEXT NULL")
  if "planning_run_id" not in cols:
    alterations.append("ADD COLUMN planning_run_id CHAR(32) NULL")
  if "planning_run_status" not in cols:
    alterations.append("ADD COLUMN planning_run_status VARCHAR(32) NULL")
  if "planning_stage" not in cols:
    alterations.append("ADD COLUMN planning_stage VARCHAR(64) NULL")
  if "planning_status" not in cols:
    alterations.append("ADD COLUMN planning_status VARCHAR(32) NULL")
  if "planning_last_review_iteration" not in cols:
    alterations.append("ADD COLUMN planning_last_review_iteration INT NULL")
  if "planning_current_retry_count" not in cols:
    alterations.append("ADD COLUMN planning_current_retry_count INT NULL")
  if "planning_current_cycle" not in cols:
    alterations.append("ADD COLUMN planning_current_cycle INT NULL")
  if "planning_detected_issue_count" not in cols:
    alterations.append("ADD COLUMN planning_detected_issue_count INT NULL")
  if "planning_remaining_issue_count" not in cols:
    alterations.append("ADD COLUMN planning_remaining_issue_count INT NULL")
  if "planning_resolved_issue_count" not in cols:
    alterations.append("ADD COLUMN planning_resolved_issue_count INT NULL")
  if "planning_tolerated_issue_count" not in cols:
    alterations.append("ADD COLUMN planning_tolerated_issue_count INT NULL")
  if "planning_iteration_pending_issue_count" not in cols:
    alterations.append("ADD COLUMN planning_iteration_pending_issue_count INT NULL")
  if "planning_latest_checkpoint_id" not in cols:
    alterations.append("ADD COLUMN planning_latest_checkpoint_id CHAR(32) NULL")
  if "planning_resume_from_checkpoint_id" not in cols:
    alterations.append("ADD COLUMN planning_resume_from_checkpoint_id CHAR(32) NULL")
  if "planning_requested_action" not in cols:
    alterations.append("ADD COLUMN planning_requested_action VARCHAR(32) NULL")
  if "planning_requested_action_at" not in cols:
    alterations.append("ADD COLUMN planning_requested_action_at DATETIME(6) NULL")
  if "planning_requested_action_reason" not in cols:
    alterations.append("ADD COLUMN planning_requested_action_reason LONGTEXT NULL")
  if "planning_latest_controller_status" not in cols:
    alterations.append("ADD COLUMN planning_latest_controller_status VARCHAR(64) NULL")
  if "planning_failure_reason" not in cols:
    alterations.append("ADD COLUMN planning_failure_reason LONGTEXT NULL")
  if "planning_resume_count" not in cols:
    alterations.append("ADD COLUMN planning_resume_count INT NULL")
  if "planning_source_run_id" not in cols:
    alterations.append("ADD COLUMN planning_source_run_id CHAR(32) NULL")
  if "planning_superseded_by_run_id" not in cols:
    alterations.append("ADD COLUMN planning_superseded_by_run_id CHAR(32) NULL")
  if "planning_run_started_at" not in cols:
    alterations.append("ADD COLUMN planning_run_started_at DATETIME(6) NULL")
  if "planning_last_heartbeat_at" not in cols:
    alterations.append("ADD COLUMN planning_last_heartbeat_at DATETIME(6) NULL")
  if "planning_paused_at" not in cols:
    alterations.append("ADD COLUMN planning_paused_at DATETIME(6) NULL")
  if "planning_stopped_at" not in cols:
    alterations.append("ADD COLUMN planning_stopped_at DATETIME(6) NULL")
  if "planning_run_completed_at" not in cols:
    alterations.append("ADD COLUMN planning_run_completed_at DATETIME(6) NULL")
  if "pending_ops_milestone_json" not in cols:
    alterations.append("ADD COLUMN pending_ops_milestone_json LONGTEXT NULL")
  if "fulfillment_json" not in cols:
    alterations.append("ADD COLUMN fulfillment_json JSON NULL")
  if "ops_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN ops_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")
  if "market_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN market_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")
  if "people_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN people_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")
  if "financials_finalize_proposed" not in cols:
    alterations.append("ADD COLUMN financials_finalize_proposed TINYINT(1) NOT NULL DEFAULT 0")

  cleanup_drop_columns = (
    "finmo_path",
  )
  if alterations or any(column in cols for column in cleanup_drop_columns):
    cur2 = conn.cursor()
    try:
      for alter in alterations:
        cur2.execute(f"ALTER TABLE intake_consult_drafts {alter}")
      refreshed_cols = _table_columns(conn, "intake_consult_drafts")
      for column in cleanup_drop_columns:
        if column in refreshed_cols:
          cur2.execute(f"ALTER TABLE intake_consult_drafts DROP COLUMN {column}")
      conn.commit()
    except Exception:
      # Best-effort: ignore if ALTER fails due to permissions or race.
      try:
        conn.rollback()
      except Exception:
        pass
    finally:
      try:
        cur2.close()
      except Exception:
        pass

  planning_runs_cols = _table_columns(conn, "planning_runs")
  planning_runs_indexes = _table_indexes(conn, "planning_runs")
  planning_runs_alters: list[str] = []
  if "planning_run_id" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN planning_run_id CHAR(32) NOT NULL PRIMARY KEY FIRST")
  if "draft_id" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN draft_id CHAR(32) NOT NULL")
  if "client_id" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN client_id CHAR(20) NOT NULL")
  if "run_status" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN run_status VARCHAR(32) NOT NULL DEFAULT 'queued'")
  if "current_stage" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN current_stage VARCHAR(64) NULL")
  if "current_stage_status" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN current_stage_status VARCHAR(32) NULL")
  if "current_iteration" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN current_iteration INT NULL")
  if "current_retry_count" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN current_retry_count INT NULL")
  if "current_cycle" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN current_cycle INT NULL")
  if "latest_detected_issue_count" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN latest_detected_issue_count INT NULL")
  if "latest_remaining_issue_count" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN latest_remaining_issue_count INT NULL")
  if "latest_resolved_issue_count" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN latest_resolved_issue_count INT NULL")
  if "latest_checkpoint_id" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN latest_checkpoint_id CHAR(32) NULL")
  if "resume_from_checkpoint_id" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN resume_from_checkpoint_id CHAR(32) NULL")
  if "source_planning_run_id" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN source_planning_run_id CHAR(32) NULL")
  if "superseded_by_planning_run_id" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN superseded_by_planning_run_id CHAR(32) NULL")
  if "requested_action" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN requested_action VARCHAR(32) NULL")
  if "requested_action_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN requested_action_at DATETIME(6) NULL")
  if "requested_action_reason" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN requested_action_reason LONGTEXT NULL")
  if "latest_controller_status" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN latest_controller_status VARCHAR(64) NULL")
  if "failure_reason" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN failure_reason LONGTEXT NULL")
  if "trigger_type" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN trigger_type VARCHAR(32) NULL")
  if "resume_count" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN resume_count INT NOT NULL DEFAULT 0")
  if "created_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN created_at DATETIME(6) NOT NULL")
  if "updated_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN updated_at DATETIME(6) NOT NULL")
  if "started_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN started_at DATETIME(6) NOT NULL")
  if "last_heartbeat_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN last_heartbeat_at DATETIME(6) NULL")
  if "paused_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN paused_at DATETIME(6) NULL")
  if "stopped_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN stopped_at DATETIME(6) NULL")
  if "completed_at" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN completed_at DATETIME(6) NULL")
  if "plan_confidence" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN plan_confidence VARCHAR(64) NULL")
  if "cascade_landed_tier" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN cascade_landed_tier TINYINT NULL")
  if "cascade_tiers_attempted_json" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN cascade_tiers_attempted_json LONGTEXT NULL")
  if "acceptance_verdict_json" not in planning_runs_cols:
    planning_runs_alters.append("ADD COLUMN acceptance_verdict_json LONGTEXT NULL")
  if "idx_planning_runs_draft_id" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_draft_id (draft_id)")
  if "idx_planning_runs_client_id" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_client_id (client_id)")
  if "idx_planning_runs_run_status" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_run_status (run_status)")
  if "idx_planning_runs_current_stage" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_current_stage (current_stage)")
  if "idx_planning_runs_last_heartbeat_at" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_last_heartbeat_at (last_heartbeat_at)")
  if "idx_planning_runs_draft_status" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_draft_status (draft_id, run_status)")
  if "idx_planning_runs_draft_started_at" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_draft_started_at (draft_id, started_at)")
  if "idx_planning_runs_requested_action" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_requested_action (requested_action)")
  if "idx_planning_runs_source_run" not in planning_runs_indexes:
    planning_runs_alters.append("ADD KEY idx_planning_runs_source_run (source_planning_run_id)")

  checkpoint_cols = _table_columns(conn, "planning_run_checkpoints")
  checkpoint_indexes = _table_indexes(conn, "planning_run_checkpoints")
  checkpoint_alters: list[str] = []
  if "checkpoint_id" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN checkpoint_id CHAR(32) NOT NULL PRIMARY KEY FIRST")
  if "planning_run_id" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN planning_run_id CHAR(32) NOT NULL")
  if "draft_id" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN draft_id CHAR(32) NOT NULL")
  if "client_id" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN client_id CHAR(20) NOT NULL")
  if "stage" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN stage VARCHAR(64) NULL")
  if "stage_status" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN stage_status VARCHAR(32) NULL")
  if "iteration" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN iteration INT NULL")
  if "retry_count" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN retry_count INT NULL")
  if "cycle" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN cycle INT NULL")
  if "checkpoint_kind" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN checkpoint_kind VARCHAR(32) NOT NULL DEFAULT 'stage_checkpoint'")
  if "controller_resolution_state_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN controller_resolution_state_json LONGTEXT NULL")
  if "planning_run_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN planning_run_json LONGTEXT NULL")
  if "planning_convergence_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN planning_convergence_json LONGTEXT NULL")
  if "repair_guidance_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN repair_guidance_json LONGTEXT NULL")
  if "numeric_solver_feedback_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN numeric_solver_feedback_json LONGTEXT NULL")
  if "convergence_state_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN convergence_state_json LONGTEXT NULL")
  if "financial_story" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN financial_story LONGTEXT NULL")
  if "model_input_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN model_input_json LONGTEXT NULL")
  if "finmo_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN finmo_json LONGTEXT NULL")
  if "realism_memo_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN realism_memo_json LONGTEXT NULL")
  if "diagnostics_json" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN diagnostics_json LONGTEXT NULL")
  if "created_at" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN created_at DATETIME(6) NOT NULL")
  if "updated_at" not in checkpoint_cols:
    checkpoint_alters.append("ADD COLUMN updated_at DATETIME(6) NOT NULL")
  if "idx_planning_run_checkpoints_run_created" not in checkpoint_indexes:
    checkpoint_alters.append("ADD KEY idx_planning_run_checkpoints_run_created (planning_run_id, created_at)")
  if "idx_planning_run_checkpoints_draft_created" not in checkpoint_indexes:
    checkpoint_alters.append("ADD KEY idx_planning_run_checkpoints_draft_created (draft_id, created_at)")
  if "idx_planning_run_checkpoints_kind" not in checkpoint_indexes:
    checkpoint_alters.append("ADD KEY idx_planning_run_checkpoints_kind (checkpoint_kind)")
  if "idx_planning_run_checkpoints_stage" not in checkpoint_indexes:
    checkpoint_alters.append("ADD KEY idx_planning_run_checkpoints_stage (stage)")

  event_cols = _table_columns(conn, "planning_stage_events")
  event_indexes = _table_indexes(conn, "planning_stage_events")
  event_alters: list[str] = []
  if "event_id" not in event_cols:
    event_alters.append("ADD COLUMN event_id CHAR(32) NOT NULL PRIMARY KEY FIRST")
  if "planning_run_id" not in event_cols:
    event_alters.append("ADD COLUMN planning_run_id CHAR(32) NOT NULL")
  if "draft_id" not in event_cols:
    event_alters.append("ADD COLUMN draft_id CHAR(32) NOT NULL")
  if "client_id" not in event_cols:
    event_alters.append("ADD COLUMN client_id CHAR(20) NOT NULL")
  if "stage" not in event_cols:
    event_alters.append("ADD COLUMN stage VARCHAR(64) NULL")
  if "stage_status" not in event_cols:
    event_alters.append("ADD COLUMN stage_status VARCHAR(32) NULL")
  if "iteration" not in event_cols:
    event_alters.append("ADD COLUMN iteration INT NULL")
  if "retry_count" not in event_cols:
    event_alters.append("ADD COLUMN retry_count INT NULL")
  if "cycle" not in event_cols:
    event_alters.append("ADD COLUMN cycle INT NULL")
  if "event_type" not in event_cols:
    event_alters.append("ADD COLUMN event_type VARCHAR(64) NOT NULL DEFAULT 'run_event'")
  if "event_summary" not in event_cols:
    event_alters.append("ADD COLUMN event_summary LONGTEXT NULL")
  if "event_payload_json" not in event_cols:
    event_alters.append("ADD COLUMN event_payload_json LONGTEXT NULL")
  if "created_at" not in event_cols:
    event_alters.append("ADD COLUMN created_at DATETIME(6) NOT NULL")
  if "idx_planning_stage_events_run_created" not in event_indexes:
    event_alters.append("ADD KEY idx_planning_stage_events_run_created (planning_run_id, created_at)")
  if "idx_planning_stage_events_draft_created" not in event_indexes:
    event_alters.append("ADD KEY idx_planning_stage_events_draft_created (draft_id, created_at)")
  if "idx_planning_stage_events_event_type" not in event_indexes:
    event_alters.append("ADD KEY idx_planning_stage_events_event_type (event_type)")
  if "idx_planning_stage_events_stage" not in event_indexes:
    event_alters.append("ADD KEY idx_planning_stage_events_stage (stage)")

  if planning_runs_alters or checkpoint_alters or event_alters:
    cur3 = conn.cursor()
    try:
      for alter in planning_runs_alters:
        cur3.execute(f"ALTER TABLE planning_runs {alter}")
      for alter in checkpoint_alters:
        cur3.execute(f"ALTER TABLE planning_run_checkpoints {alter}")
      for alter in event_alters:
        cur3.execute(f"ALTER TABLE planning_stage_events {alter}")
      conn.commit()
    except Exception:
      try:
        conn.rollback()
      except Exception:
        pass
    finally:
      try:
        cur3.close()
      except Exception:
        pass

  _ensure_completion_consistency_triggers(conn)


def create_draft(conn, *, client_id: str) -> Dict[str, Any]:
  ensure_table(conn)
  draft_id = uuid.uuid4().hex
  now = current_app_timestamp_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      INSERT INTO intake_consult_drafts
        (draft_id, client_id, status, messages_json, created_at, updated_at)
      VALUES
        (%s, %s, 'in_progress', %s, %s, %s)
      """,
      (draft_id, client_id, json.dumps([], ensure_ascii=False), now, now),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return {
    "draft_id": draft_id,
    "client_id": client_id,
    "status": "in_progress",
  }


def get_draft(conn, *, draft_id: str) -> Dict[str, Any]:
  ensure_table(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      "SELECT * FROM intake_consult_drafts WHERE draft_id = %s LIMIT 1",
      (draft_id,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not row or not isinstance(row, dict):
    raise RuntimeError(f"Consult draft not found for draft_id={draft_id!r}")
  return row


def get_draft_runtime_row(conn, *, draft_id: str) -> Dict[str, Any]:
  ensure_table(conn)
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT draft_id, client_id, status, active_focus,
             planning_context_summary_json, planning_run_json, planning_runtime_json, planning_convergence_json, repair_guidance_json, convergence_state_json, numeric_solver_feedback_json, financial_story,
             planning_run_id, planning_run_status, planning_stage, planning_status,
             planning_last_review_iteration, planning_current_retry_count, planning_current_cycle,
             planning_detected_issue_count, planning_remaining_issue_count, planning_resolved_issue_count,
             planning_tolerated_issue_count, planning_iteration_pending_issue_count,
             planning_latest_checkpoint_id, planning_resume_from_checkpoint_id,
             planning_requested_action, planning_requested_action_at, planning_requested_action_reason,
             planning_latest_controller_status, planning_failure_reason, planning_resume_count,
             planning_source_run_id, planning_superseded_by_run_id, planning_run_started_at,
             planning_last_heartbeat_at, planning_paused_at, planning_stopped_at, planning_run_completed_at
      FROM intake_consult_drafts
      WHERE draft_id = %s
      LIMIT 1
      """,
      (draft_id,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  if not row or not isinstance(row, dict):
    raise RuntimeError(f"Consult draft not found for draft_id={draft_id!r}")
  return row


def _parse_messages(raw: Any) -> List[Dict[str, str]]:
  if raw is None:
    return []
  if isinstance(raw, list):
    return [m for m in raw if isinstance(m, dict)]
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return []
  if isinstance(parsed, list):
    return [m for m in parsed if isinstance(m, dict)]
  return []


def _parse_json_object(raw: Any) -> Dict[str, Any]:
  if raw is None:
    return {}
  if isinstance(raw, dict):
    return raw
  try:
    parsed = json.loads(str(raw))
  except Exception:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _render_messages_for_storage(
  *,
  row: Dict[str, Any],
  messages: List[Dict[str, str]],
  operating_model_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  realism_memo_json: Optional[Dict[str, Any]] = None,
  planning_run_json: Optional[Dict[str, Any]] = None,
  numeric_solver_feedback_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
  debt_schedule: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
  try:
    from fact_templates import render_fact_template, sanitize_fact_template  # type: ignore
  except Exception:
    return messages

  latest_business_facts: Dict[str, Any] = {
    "name": row.get("business_name"),
    "address": row.get("business_address"),
    "address_street": row.get("address_street"),
    "address_city": row.get("address_city"),
    "address_state": row.get("address_state"),
    "address_zip": row.get("address_zip"),
    "address_country": row.get("address_country"),
    "start_date": row.get("business_start_date"),
  }
  if isinstance(business_facts, dict):
    for key, value in business_facts.items():
      if key in latest_business_facts:
        latest_business_facts[key] = value

  shared_context: Dict[str, Any] = {
    "operating_model": operating_model_json if operating_model_json is not None else _parse_json_object(row.get("operating_model_json")),
    "target_market": target_market_json if target_market_json is not None else _parse_json_object(row.get("target_market_json")),
    "people_capability": people_json if people_json is not None else _parse_json_object(row.get("people_json")),
    "financials": financials_json if financials_json is not None else _parse_json_object(row.get("financials_json")),
    "marketing": marketing_model_json if marketing_model_json is not None else _parse_json_object(row.get("marketing_model_json")),
    "financials_year1_json": (
      financials_year1_json if financials_year1_json is not None else _parse_json_object(row.get("financials_year1_json"))
    ),
    "realism_memo_json": (
      realism_memo_json if realism_memo_json is not None else _parse_json_object(row.get("realism_memo_json"))
    ),
    "model_input_json": (
      model_input_json if model_input_json is not None else _parse_json_object(row.get("model_input_json"))
    ),
    "finmo_json": (
      finmo_json if finmo_json is not None else _parse_json_object(row.get("finmo_json"))
    ),
    "payroll_headcount": (
      payroll_headcount if payroll_headcount is not None else _parse_json_object(row.get("payroll_headcount"))
    ),
    "debt_schedule": (
      debt_schedule if debt_schedule is not None else _parse_json_object(row.get("debt_schedule"))
    ),
    "planning_run": (
      planning_run_json
      if planning_run_json is not None
      else _parse_json_object(row.get("planning_run_json"))
    ),
  }

  rendered_messages: List[Dict[str, str]] = []
  for message in messages:
    if not isinstance(message, dict):
      continue
    role = str(message.get("role") or "").strip()
    content = str(message.get("content") or "")
    rendered = content
    if role == "assistant" and content:
      try:
        rendered = render_fact_template(
          content,
          shared_context=shared_context,
          business_facts=latest_business_facts,
        )
      except Exception:
        rendered = content
      rendered = sanitize_fact_template(str(rendered or ""))
    rendered_message = dict(message)
    rendered_message["content"] = rendered
    rendered_messages.append(rendered_message)
  return rendered_messages


# Client-facing transcript text never says "Year 1" - internally everything is
# still the Year-1 model, but assistant wording is naturalized at the single
# persistence choke point so no prompt drift can leak the phrase to the client.
_YEAR_ONE_PREPOSITION_RE = re.compile(r"\b(for|in|during|over|across)\s+year[ -]1\b", re.IGNORECASE)
_YEAR_ONE_ADJECTIVE_RE = re.compile(r"\byear[ -]1\b", re.IGNORECASE)


def _naturalize_year_one_text(text: str) -> str:
  value = str(text or "")
  if not value:
    return value
  value = _YEAR_ONE_PREPOSITION_RE.sub(lambda m: f"{m.group(1)} the first year", value)
  value = _YEAR_ONE_ADJECTIVE_RE.sub("first-year", value)
  return value


# Mojibake tripwire (CW-009 F3): five financials stage-acks stored with
# nested cp1252<->utf8 corruption. ROOT CAUSE FOUND AND FIXED: the ack
# builders' source literals themselves were corrupted (scripted edits
# through a cp1252 console pipe, one layer per bad edit pass) - repaired
# in place. This guard stays as defense-in-depth at the persist choke
# point: it deterministically unwinds any recurrence and logs LOUDLY so
# a new corruption source is localized immediately (tripwire firing =
# corruption upstream of persist; client-facing corruption with a silent
# tripwire = DB write/read hop).
_MOJIBAKE_SIGNATURES = ("Ã", "â€")  # utf8-as-cp1252 misreads: 'Ã' at depth>=1
                                     # for accented chars, 'â€' for the
                                     # curly-quote/dash family at depth 1


def _looks_mojibake(value: str) -> bool:
  return any(sig in value for sig in _MOJIBAKE_SIGNATURES)


def _unwind_mojibake(text: str) -> str:
  value = str(text or "")
  if not _looks_mojibake(value):
    return value
  for _ in range(10):
    candidate = None
    # cp1252 first (the usual Windows hop); latin-1 fallback for the five
    # bytes cp1252 leaves unmapped (0x81 0x8D 0x8F 0x90 0x9D).
    for codec in ("cp1252", "latin-1"):
      try:
        candidate = value.encode(codec, errors="strict").decode("utf-8", errors="strict")
        break
      except (UnicodeEncodeError, UnicodeDecodeError):
        continue
    if candidate is None or candidate == value:
      break
    value = candidate
    if not _looks_mojibake(value):
      break
  return value


def _naturalize_assistant_messages(new_messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
  naturalized: List[Dict[str, str]] = []
  for message in new_messages or []:
    if isinstance(message, dict) and str(message.get("role") or "") == "assistant":
      message = dict(message)
      content = _naturalize_year_one_text(str(message.get("content") or ""))
      if _looks_mojibake(content):
        repaired = _unwind_mojibake(content)
        if repaired != content:
          try:
            import logging

            logging.getLogger("api").warning(
              "MOJIBAKE_TRIPWIRE: assistant message arrived corrupted at persist "
              "(unwound %d->%d chars): %r",
              len(content), len(repaired), content[:80],
            )
          except Exception:
            pass
          content = repaired
      message["content"] = content
    naturalized.append(message)
  return naturalized


def append_messages(
  conn,
  *,
  draft_id: str,
  new_messages: List[Dict[str, str]],
  status: Optional[str] = None,
  operating_model_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  realism_memo_json: Optional[Dict[str, Any]] = None,
  planning_context_summary_json: Optional[Dict[str, Any]] = None,
  planning_run_json: Optional[Dict[str, Any]] = None,
  planning_runtime_json: Optional[Dict[str, Any]] = None,
  planning_convergence_json: Optional[Dict[str, Any]] = None,
  repair_guidance_json: Optional[Dict[str, Any]] = None,
  convergence_state_json: Optional[Dict[str, Any]] = None,
  numeric_solver_feedback_json: Optional[Dict[str, Any]] = None,
  financial_story: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
  debt_schedule: Optional[Dict[str, Any]] = None,
  pending_ops_milestone_json: Optional[Any] = None,
  fulfillment_json: Optional[Dict[str, Any]] = None,
  active_focus: Optional[str] = None,
  confirmations: Optional[Dict[str, bool]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  flat_fields: Optional[Dict[str, Any]] = None,
  completed: bool = False,
  commit: bool = True,
) -> Dict[str, Any]:
  write_messages_json = bool(new_messages)
  row = (
    get_draft(conn, draft_id=draft_id)
    if write_messages_json or (completed and planning_run_json is None)
    else get_draft_runtime_row(conn, draft_id=draft_id)
  )
  if completed or str(active_focus or "").strip().lower() == "done" or str(status or "").strip().lower() == "completed":
    payload = (
      planning_run_json
      if planning_run_json is not None
      else _parse_json_payload(row.get("planning_run_json"))
    )
    if not _is_valid_planning_run_payload(payload):
      raise RuntimeError("completion_requires_planning_run")
  existing_messages = _parse_messages(row.get("messages_json")) if write_messages_json else []
  messages = list(existing_messages)
  if new_messages:
    messages.extend(_naturalize_assistant_messages(new_messages))
    messages = _render_messages_for_storage(
      row=row,
      messages=messages,
      operating_model_json=operating_model_json,
      target_market_json=target_market_json,
      people_json=people_json,
      financials_json=financials_json,
      marketing_model_json=marketing_model_json,
      financials_year1_json=financials_year1_json,
      realism_memo_json=realism_memo_json,
      planning_run_json=planning_run_json,
      numeric_solver_feedback_json=numeric_solver_feedback_json,
      model_input_json=model_input_json,
      finmo_json=finmo_json,
      payroll_headcount=payroll_headcount,
      debt_schedule=debt_schedule,
      business_facts=business_facts,
    )

  now = current_app_timestamp_str()
  set_parts = ["updated_at = %s"]
  values: List[Any] = [now]
  if write_messages_json:
    set_parts.insert(0, "messages_json = %s")
    values.insert(0, json.dumps(messages, ensure_ascii=False))

  if status:
    set_parts.append("status = %s")
    values.append(status)
    # If we are reopening a previously completed consult (e.g. an edit after the
    # completion), clear completed_at so the UI does not treat it as
    # "done" while the model is being refined.
    if str(status).strip().lower() == "in_progress":
      set_parts.append("completed_at = NULL")

  if operating_model_json is not None:
    set_parts.append("operating_model_json = %s")
    values.append(json.dumps(operating_model_json, ensure_ascii=False))

  if target_market_json is not None:
    set_parts.append("target_market_json = %s")
    values.append(json.dumps(target_market_json, ensure_ascii=False))

  if people_json is not None:
    set_parts.append("people_json = %s")
    values.append(json.dumps(people_json, ensure_ascii=False))

  if financials_json is not None:
    set_parts.append("financials_json = %s")
    values.append(json.dumps(financials_json, ensure_ascii=False))

  if marketing_model_json is not None:
    set_parts.append("marketing_model_json = %s")
    values.append(json.dumps(marketing_model_json, ensure_ascii=False))

  if financials_year1_json is not None:
    set_parts.append("financials_year1_json = %s")
    values.append(json.dumps(financials_year1_json, ensure_ascii=False))

  if model_input_json is not None:
    set_parts.append("model_input_json = %s")
    values.append(json.dumps(model_input_json, ensure_ascii=False))

  if finmo_json is not None:
    set_parts.append("finmo_json = %s")
    values.append(json.dumps(finmo_json, ensure_ascii=False))

  if payroll_headcount is not None:
    set_parts.append("payroll_headcount = %s")
    values.append(json.dumps(payroll_headcount, ensure_ascii=False))

  if debt_schedule is not None:
    set_parts.append("debt_schedule = %s")
    values.append(json.dumps(debt_schedule, ensure_ascii=False))

  if realism_memo_json is not None:
    set_parts.append("realism_memo_json = %s")
    values.append(json.dumps(realism_memo_json, ensure_ascii=False))

  if planning_context_summary_json is not None:
    set_parts.append("planning_context_summary_json = %s")
    values.append(json.dumps(planning_context_summary_json, ensure_ascii=False))

  if planning_run_json is not None:
    set_parts.append("planning_run_json = %s")
    values.append(json.dumps(planning_run_json, ensure_ascii=False))
    for key, value in _planning_run_flat_field_values(planning_run_json).items():
      if key not in _PLANNING_STATE_FLAT_COLUMNS:
        continue
      set_parts.append(f"{key} = %s")
      values.append(value)

  if planning_runtime_json is not None:
    set_parts.append("planning_runtime_json = %s")
    values.append(json.dumps(planning_runtime_json, ensure_ascii=False))

  if planning_convergence_json is not None:
    set_parts.append("planning_convergence_json = %s")
    values.append(json.dumps(planning_convergence_json, ensure_ascii=False))

  if repair_guidance_json is not None:
    set_parts.append("repair_guidance_json = %s")
    values.append(json.dumps(repair_guidance_json, ensure_ascii=False))

  if convergence_state_json is not None:
    set_parts.append("convergence_state_json = %s")
    values.append(json.dumps(convergence_state_json, ensure_ascii=False))

  if numeric_solver_feedback_json is not None:
    set_parts.append("numeric_solver_feedback_json = %s")
    values.append(json.dumps(numeric_solver_feedback_json, ensure_ascii=False))

  if financial_story is not None:
    set_parts.append("financial_story = %s")
    values.append(json.dumps(financial_story, ensure_ascii=False))

  if pending_ops_milestone_json is not None:
    set_parts.append("pending_ops_milestone_json = %s")
    values.append(json.dumps(pending_ops_milestone_json, ensure_ascii=False))

  if fulfillment_json is not None:
    set_parts.append("fulfillment_json = %s")
    values.append(json.dumps(fulfillment_json, ensure_ascii=False))

  if active_focus is not None:
    set_parts.append("active_focus = %s")
    values.append(str(active_focus).strip() or "ops")

  if confirmations:
    for key, col in (
      ("ops", "ops_confirmed"),
      ("market", "market_confirmed"),
      ("people", "people_confirmed"),
      ("financials", "financials_confirmed"),
    ):
      if key in confirmations:
        set_parts.append(f"{col} = %s")
        values.append(1 if confirmations[key] else 0)

  if business_facts:
    if "name" in business_facts:
      set_parts.append("business_name = %s")
      values.append(str(business_facts.get("name") or "").strip() or None)
    if "address" in business_facts:
      set_parts.append("business_address = %s")
      values.append(str(business_facts.get("address") or "").strip() or None)
    if "address_street" in business_facts:
      set_parts.append("address_street = %s")
      values.append(str(business_facts.get("address_street") or "").strip() or None)
    if "address_city" in business_facts:
      set_parts.append("address_city = %s")
      values.append(str(business_facts.get("address_city") or "").strip() or None)
    if "address_state" in business_facts:
      set_parts.append("address_state = %s")
      values.append(str(business_facts.get("address_state") or "").strip() or None)
    if "address_zip" in business_facts:
      set_parts.append("address_zip = %s")
      values.append(str(business_facts.get("address_zip") or "").strip() or None)
    if "address_country" in business_facts:
      set_parts.append("address_country = %s")
      values.append(str(business_facts.get("address_country") or "").strip() or None)
    if "start_date" in business_facts:
      set_parts.append("business_start_date = %s")
      values.append(str(business_facts.get("start_date") or "").strip() or None)

  if flat_fields:
    reserved = {
      "draft_id",
      "client_id",
      "status",
      "active_focus",
      "ops_confirmed",
      "market_confirmed",
      "people_confirmed",
      "financials_confirmed",
      "business_name",
      "business_address",
      "address_street",
      "address_city",
      "address_state",
      "address_zip",
      "address_country",
      "business_start_date",
      "messages_json",
      "operating_model_json",
      "target_market_json",
      "people_json",
      "financials_json",
      "marketing_model_json",
      "financials_year1_json",
      "realism_memo_json",
      "model_input_json",
      "finmo_json",
      "payroll_headcount",
      "debt_schedule",
      "planning_context_summary_json",
      "planning_run_json",
      "planning_runtime_json",
      "planning_convergence_json",
      "repair_guidance_json",
      "convergence_state_json",
      "numeric_solver_feedback_json",
      "financial_story",
      "pending_ops_milestone_json",
      "fulfillment_json",
      "created_at",
      "updated_at",
      "completed_at",
      "submitted_at",
      "intake_submission_id",
    }
    cols = _table_columns(conn, "intake_consult_drafts")
    for key, raw_val in flat_fields.items():
      if key in reserved:
        continue
      if key not in cols:
        continue
      set_parts.append(f"`{key}` = %s")
      values.append(_normalize_flat_value(raw_val))

  if completed:
    set_parts.append("completed_at = %s")
    values.append(now)

  values.append(draft_id)
  sql = "UPDATE intake_consult_drafts SET " + ", ".join(set_parts) + " WHERE draft_id = %s"

  cur = conn.cursor()
  try:
    cur.execute(sql, values)
    if commit:
      conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass

  return {"draft_id": draft_id, "client_id": row.get("client_id"), "messages": messages}


def _latest_planning_run(conn, *, draft_id: str, active_only: bool = False) -> Optional[Dict[str, Any]]:
  ensure_table(conn)
  cur = conn.cursor(dictionary=True)
  try:
    if active_only:
      cur.execute(
        """
        SELECT *
        FROM planning_runs
        WHERE draft_id = %s
          AND run_status IN ('queued', 'running', 'paused')
        ORDER BY updated_at DESC, started_at DESC
        LIMIT 1
        """,
        (str(draft_id).strip(),),
      )
    else:
      cur.execute(
        """
        SELECT *
        FROM planning_runs
        WHERE draft_id = %s
        ORDER BY updated_at DESC, started_at DESC
        LIMIT 1
        """,
        (str(draft_id).strip(),),
      )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return row if isinstance(row, dict) else None


def get_planning_run(
  conn,
  *,
  planning_run_id: Optional[str] = None,
  draft_id: Optional[str] = None,
  active_only: bool = False,
) -> Optional[Dict[str, Any]]:
  ensure_table(conn)
  run_id = str(planning_run_id or "").strip()
  if run_id:
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        """
        SELECT *
        FROM planning_runs
        WHERE planning_run_id = %s
        LIMIT 1
        """,
        (run_id,),
      )
      row = cur.fetchone()
    finally:
      try:
        cur.close()
      except Exception:
        pass
    return row if isinstance(row, dict) else None
  draft_key = str(draft_id or "").strip()
  if not draft_key:
    return None
  return _latest_planning_run(conn, draft_id=draft_key, active_only=active_only)


def get_latest_planning_run_checkpoint(
  conn,
  *,
  planning_run_id: Optional[str] = None,
  draft_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
  ensure_table(conn)
  run_id = str(planning_run_id or "").strip()
  if not run_id:
    run_row = get_planning_run(conn, draft_id=draft_id, active_only=False)
    run_id = str((run_row or {}).get("planning_run_id") or "").strip()
  if not run_id:
    return None
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT *
      FROM planning_run_checkpoints
      WHERE planning_run_id = %s
      ORDER BY created_at DESC
      LIMIT 1
      """,
      (run_id,),
    )
    row = cur.fetchone()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  return row if isinstance(row, dict) else None


def begin_planning_run(
  conn,
  *,
  draft_id: str,
  trigger_type: str = "system_run",
  lifecycle_mode: str = "start",
  planning_run_id: Optional[str] = None,
  source_planning_run_id: Optional[str] = None,
) -> Dict[str, Any]:
  ensure_table(conn)
  draft = get_draft(conn, draft_id=str(draft_id).strip())
  client_id = str(draft.get("client_id") or "").strip()
  if not client_id:
    raise RuntimeError("begin_planning_run_requires_client_id")

  mode = str(lifecycle_mode or "start").strip().lower() or "start"
  requested_run_id = str(planning_run_id or "").strip()
  source_run_id = str(source_planning_run_id or "").strip()
  active_run = _latest_planning_run(conn, draft_id=str(draft_id).strip(), active_only=True)
  latest_run = _latest_planning_run(conn, draft_id=str(draft_id).strip(), active_only=False)
  now = current_app_timestamp_str()

  if mode in {"start", "rerun"} and active_run:
    raise RuntimeError(
      f"planning_run_already_active:{str(active_run.get('planning_run_id') or '').strip()}"
    )

  if mode == "resume":
    target_run = get_planning_run(conn, planning_run_id=requested_run_id) if requested_run_id else None
    if target_run is None:
      latest_candidate = latest_run if isinstance(latest_run, dict) else None
      if latest_candidate and str(latest_candidate.get("run_status") or "").strip().lower() in {"paused", "stopped"}:
        target_run = latest_candidate
    if not isinstance(target_run, dict):
      raise RuntimeError("planning_run_resume_target_not_found")
    checkpoint = get_latest_planning_run_checkpoint(
      conn,
      planning_run_id=str(target_run.get("planning_run_id") or "").strip(),
    )
    checkpoint_id = str((checkpoint or {}).get("checkpoint_id") or "").strip() or None
    cur = conn.cursor()
    try:
      cur.execute(
        """
        UPDATE planning_runs
        SET run_status = %s,
            current_stage_status = %s,
            resume_from_checkpoint_id = %s,
            requested_action = NULL,
            requested_action_at = NULL,
            requested_action_reason = NULL,
            resume_count = COALESCE(resume_count, 0) + 1,
            updated_at = %s,
            last_heartbeat_at = %s,
            paused_at = NULL,
            stopped_at = NULL,
            completed_at = NULL
        WHERE planning_run_id = %s
        """,
        (
          "running",
          "resuming",
          checkpoint_id,
          now,
          now,
          str(target_run.get("planning_run_id") or "").strip(),
        ),
      )
      conn.commit()
    finally:
      try:
        cur.close()
      except Exception:
        pass
    resumed = get_planning_run(
      conn,
      planning_run_id=str(target_run.get("planning_run_id") or "").strip(),
    )
    mirror_planning_run_state_to_draft(
      conn,
      draft_id=str(draft_id).strip(),
      planning_run_row=copy.deepcopy(resumed if isinstance(resumed, dict) else target_run),
      status="in_progress",
      commit=True,
    )
    return {
      "planning_run": resumed if isinstance(resumed, dict) else target_run,
      "latest_checkpoint": checkpoint if isinstance(checkpoint, dict) else None,
      "lifecycle_mode": mode,
    }

  new_run_id = requested_run_id or uuid.uuid4().hex
  source_run = get_planning_run(conn, planning_run_id=source_run_id) if source_run_id else latest_run
  source_run_key = str((source_run or {}).get("planning_run_id") or "").strip() or None
  resume_from_checkpoint_id = None
  if mode == "rerun" and source_run_key:
    source_checkpoint = get_latest_planning_run_checkpoint(conn, planning_run_id=source_run_key)
    resume_from_checkpoint_id = str((source_checkpoint or {}).get("checkpoint_id") or "").strip() or None
  cur = conn.cursor()
  try:
    cur.execute(
      """
      INSERT INTO planning_runs (
        planning_run_id, draft_id, client_id, run_status, current_stage, current_stage_status,
        current_iteration, current_retry_count, current_cycle, latest_detected_issue_count,
        latest_remaining_issue_count, latest_resolved_issue_count, latest_checkpoint_id,
        resume_from_checkpoint_id, source_planning_run_id, superseded_by_planning_run_id,
        requested_action, requested_action_at, requested_action_reason, latest_controller_status,
        failure_reason, trigger_type, resume_count, created_at, updated_at, started_at,
        last_heartbeat_at, paused_at, stopped_at, completed_at
      ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s
      )
      """,
      (
        new_run_id,
        str(draft_id).strip(),
        client_id,
        "running",
        "system_run_starting",
        "running",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        resume_from_checkpoint_id,
        source_run_key,
        None,
        None,
        None,
        None,
        None,
        None,
        str(trigger_type or "system_run").strip() or "system_run",
        0,
        now,
        now,
        now,
        now,
        None,
        None,
        None,
      ),
    )
    if mode == "rerun" and source_run_key:
      cur.execute(
        """
        UPDATE planning_runs
        SET superseded_by_planning_run_id = %s,
            updated_at = %s
        WHERE planning_run_id = %s
        """,
        (
          new_run_id,
          now,
          source_run_key,
        ),
      )
    cur.execute(
      """
      INSERT INTO planning_stage_events (
        event_id, planning_run_id, draft_id, client_id, stage, stage_status,
        iteration, retry_count, cycle, event_type, event_summary, event_payload_json, created_at
      ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
      )
      """,
      (
        uuid.uuid4().hex,
        new_run_id,
        str(draft_id).strip(),
        client_id,
        "system_run_starting",
        "running",
        None,
        None,
        None,
        "run_started" if mode == "start" else "run_rerun_started",
        f"{mode}:system_run_starting",
        json.dumps(
          {
            "lifecycle_mode": mode,
            "trigger_type": str(trigger_type or "system_run").strip() or "system_run",
            "source_planning_run_id": source_run_key,
            "resume_from_checkpoint_id": resume_from_checkpoint_id,
          },
          ensure_ascii=False,
        ),
        now,
      ),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  started = get_planning_run(conn, planning_run_id=new_run_id)
  mirror_planning_run_state_to_draft(
    conn,
    draft_id=str(draft_id).strip(),
    planning_run_row=copy.deepcopy(started if isinstance(started, dict) else {"planning_run_id": new_run_id}),
    status="in_progress",
    commit=True,
  )
  return {
    "planning_run": started if isinstance(started, dict) else {"planning_run_id": new_run_id},
    "latest_checkpoint": None,
    "lifecycle_mode": mode,
  }


def request_planning_run_action(
  conn,
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  action: str,
  reason: str = "",
) -> Dict[str, Any]:
  ensure_table(conn)
  normalized_action = str(action or "").strip().lower()
  if normalized_action not in {"pause", "stop"}:
    raise RuntimeError("unsupported_planning_run_action")
  run_row = get_planning_run(
    conn,
    planning_run_id=planning_run_id,
    draft_id=draft_id,
    active_only=not str(planning_run_id or "").strip(),
  )
  if not isinstance(run_row, dict):
    raise RuntimeError("planning_run_not_found_for_action")
  run_id = str(run_row.get("planning_run_id") or "").strip()
  now = current_app_timestamp_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      UPDATE planning_runs
      SET requested_action = %s,
          requested_action_at = %s,
          requested_action_reason = %s,
          updated_at = %s
      WHERE planning_run_id = %s
      """,
      (
        normalized_action,
        now,
        str(reason or "").strip() or None,
        now,
        run_id,
      ),
    )
    cur.execute(
      """
      INSERT INTO planning_stage_events (
        event_id, planning_run_id, draft_id, client_id, stage, stage_status,
        iteration, retry_count, cycle, event_type, event_summary, event_payload_json, created_at
      ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
      )
      """,
      (
        uuid.uuid4().hex,
        run_id,
        str(run_row.get("draft_id") or "").strip(),
        str(run_row.get("client_id") or "").strip(),
        str(run_row.get("current_stage") or "").strip() or None,
        str(run_row.get("current_stage_status") or "").strip() or None,
        run_row.get("current_iteration"),
        run_row.get("current_retry_count"),
        run_row.get("current_cycle"),
        f"run_{normalized_action}_requested",
        f"{normalized_action}_requested",
        json.dumps(
          {
            "requested_action": normalized_action,
            "requested_action_reason": str(reason or "").strip(),
          },
          ensure_ascii=False,
        ),
        now,
      ),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  updated = get_planning_run(conn, planning_run_id=run_id)
  mirror_planning_run_state_to_draft(
    conn,
    draft_id=str((updated or run_row).get("draft_id") or "").strip(),
    planning_run_row=copy.deepcopy(updated if isinstance(updated, dict) else run_row),
    commit=True,
  )
  return updated if isinstance(updated, dict) else run_row


def clear_planning_run_action(
  conn,
  *,
  planning_run_id: str,
  run_status: Optional[str] = None,
  failure_reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
  ensure_table(conn)
  run_id = str(planning_run_id or "").strip()
  if not run_id:
    return None
  target_status = str(run_status or "").strip().lower()
  now = current_app_timestamp_str()
  set_parts = [
    "requested_action = NULL",
    "requested_action_at = NULL",
    "requested_action_reason = NULL",
    "updated_at = %s",
  ]
  values: List[Any] = [now]
  if target_status in {"paused", "stopped", "running", "failed", "completed"}:
    set_parts.append("run_status = %s")
    values.append(target_status)
    set_parts.append("current_stage_status = %s")
    values.append(target_status)
  if str(failure_reason or "").strip():
    set_parts.append("failure_reason = %s")
    values.append(str(failure_reason or "").strip())
  if target_status == "paused":
    set_parts.append("paused_at = %s")
    values.append(now)
  elif target_status == "stopped":
    set_parts.append("stopped_at = %s")
    values.append(now)
  elif target_status == "failed":
    set_parts.append("completed_at = %s")
    values.append(now)
  values.append(run_id)
  cur = conn.cursor()
  try:
    cur.execute(
      f"UPDATE planning_runs SET {', '.join(set_parts)} WHERE planning_run_id = %s",
      tuple(values),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
  updated = get_planning_run(conn, planning_run_id=run_id)
  if isinstance(updated, dict):
    mirror_planning_run_state_to_draft(
      conn,
      draft_id=str(updated.get("draft_id") or "").strip(),
      planning_run_row=copy.deepcopy(updated),
      status=(
        "completed"
        if target_status == "completed"
        else "failed"
        if target_status == "failed"
        else "in_progress"
        if target_status in {"running", "paused", "stopped"}
        else None
      ),
      commit=True,
    )
  return updated


def mirror_planning_run_state_to_draft(
  conn,
  *,
  draft_id: str,
  planning_run_row: Optional[Dict[str, Any]] = None,
  planning_run_json: Optional[Dict[str, Any]] = None,
  status: Optional[str] = None,
  commit: bool = True,
) -> Dict[str, Any]:
  ensure_table(conn)
  merged_flat_fields: Dict[str, Any] = {}
  merged_flat_fields.update(_planning_run_flat_field_values(planning_run_json))
  merged_flat_fields.update(_planning_run_row_flat_field_values(planning_run_row))
  return append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    planning_run_json=planning_run_json,
    status=status,
    flat_fields=merged_flat_fields,
    commit=commit,
  )


def _planning_run_counts_from_payload(planning_run_json: Optional[Dict[str, Any]]) -> Dict[str, Optional[int]]:
  flat = _planning_run_flat_field_values(planning_run_json or {})
  return {
    "detected": flat.get("planning_detected_issue_count"),
    "remaining": flat.get("planning_remaining_issue_count"),
    "resolved": flat.get("planning_resolved_issue_count"),
    "iteration": flat.get("planning_last_review_iteration"),
  }


# The only stage at which a payload-level "completed" status may mean the
# RUN is complete. Intermediate stage snapshots also persist status
# "completed" (meaning that STAGE finished), and before CW-009 those
# leaked into planning_runs.run_status - a live run read 'completed' at
# the initialize-validation boundary, the watcher believed it, finalized
# vitals, and stopped observing a run that was minutes from done.
_TERMINAL_RUN_STAGES = {"post_intake_finalize_validation_completed"}


def _derive_execution_run_status(
  *,
  planning_run_json: Optional[Dict[str, Any]],
  draft_status: Optional[str],
  completed: bool,
) -> str:
  if completed:
    return "completed"
  payload = planning_run_json if isinstance(planning_run_json, dict) else {}
  planning_status = str(payload.get("status") or "").strip().lower()
  payload_stage = str(payload.get("stage") or "").strip().lower()
  raw_status = str(draft_status or "").strip().lower()
  if planning_status == "completed" and payload_stage in _TERMINAL_RUN_STAGES:
    return "completed"
  if raw_status == "completed":
    return "completed"
  if raw_status in {"failed", "error"}:
    return "failed"
  if raw_status in {"paused", "stopped"}:
    return raw_status
  if raw_status == "submitted":
    return "completed"
  return "running"


def _default_checkpoint_kind(*, completed: bool, status: Optional[str], stage: str) -> str:
  if completed or str(status or "").strip().lower() == "completed":
    return "run_complete"
  if stage:
    return "stage_snapshot"
  return "state_snapshot"


def _default_event_type(*, completed: bool, status: Optional[str], stage: str) -> str:
  if completed or str(status or "").strip().lower() == "completed":
    return "run_completed"
  if stage:
    return "stage_persisted"
  return "state_persisted"


def persist_post_intake_execution_state(
  conn,
  *,
  draft_id: str,
  operating_model_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  fulfillment_json: Optional[Dict[str, Any]] = None,
  planning_context_summary_json: Optional[Dict[str, Any]] = None,
  planning_run_json: Optional[Dict[str, Any]] = None,
  planning_runtime_json: Optional[Dict[str, Any]] = None,
  planning_convergence_json: Optional[Dict[str, Any]] = None,
  repair_guidance_json: Optional[Dict[str, Any]] = None,
  convergence_state_json: Optional[Dict[str, Any]] = None,
  numeric_solver_feedback_json: Optional[Dict[str, Any]] = None,
  financial_story: Optional[Dict[str, Any]] = None,
  realism_memo_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
  debt_schedule: Optional[Dict[str, Any]] = None,
  new_messages: Optional[List[Dict[str, str]]] = None,
  active_focus: Optional[str] = "done",
  status: Optional[str] = "in_progress",
  business_facts: Optional[Dict[str, Any]] = None,
  completed: bool = False,
  checkpoint_kind: Optional[str] = None,
  event_type: Optional[str] = None,
  event_summary: Optional[str] = None,
) -> Dict[str, Any]:
  ensure_table(conn)
  row = get_draft_runtime_row(conn, draft_id=str(draft_id).strip())
  client_id = str(row.get("client_id") or "").strip()
  if not client_id:
    raise RuntimeError("persist_post_intake_execution_state_requires_client_id")

  payload = copy_payload = (
    json.loads(json.dumps(planning_run_json, ensure_ascii=False))
    if isinstance(planning_run_json, dict)
    else {}
  )
  stage = str(copy_payload.get("stage") or "").strip()
  planning_status = str(copy_payload.get("status") or "").strip()
  counts = _planning_run_counts_from_payload(copy_payload if copy_payload else None)
  current_iteration = counts.get("iteration")
  current_cycle = None
  try:
    current_cycle = int(float(copy_payload.get("unified_convergence_cycle_count")))
  except Exception:
    current_cycle = None
  heartbeat = copy_payload.get("controller_retry_heartbeat")
  current_retry_count = None
  if isinstance(heartbeat, dict):
    try:
      current_retry_count = int(float(heartbeat.get("attempt_number")))
    except Exception:
      current_retry_count = None

  run_status = _derive_execution_run_status(
    planning_run_json=copy_payload if copy_payload else None,
    draft_status=status,
    completed=completed,
  )

  existing_run_id = str(copy_payload.get("planning_run_id") or "").strip()
  latest_active_run = _latest_planning_run(conn, draft_id=str(draft_id).strip(), active_only=True)
  latest_any_run = _latest_planning_run(conn, draft_id=str(draft_id).strip(), active_only=False)
  run_row = None
  if existing_run_id:
    run_row = latest_active_run if latest_active_run and str(latest_active_run.get("planning_run_id") or "").strip() == existing_run_id else None
    if run_row is None and latest_any_run and str(latest_any_run.get("planning_run_id") or "").strip() == existing_run_id:
      run_row = latest_any_run
  if run_row is None:
    if run_status == "completed" and latest_active_run:
      run_row = latest_active_run
    elif latest_active_run:
      run_row = latest_active_run

  now = current_app_timestamp_str()
  planning_run_id = str((run_row or {}).get("planning_run_id") or "").strip() or uuid.uuid4().hex
  checkpoint_id = uuid.uuid4().hex
  event_id = uuid.uuid4().hex

  if isinstance(copy_payload, dict):
    copy_payload["planning_run_id"] = planning_run_id
    copy_payload["latest_checkpoint_id"] = checkpoint_id
    copy_payload["run_status"] = run_status

  checkpoint_kind_value = str(checkpoint_kind or "").strip() or _default_checkpoint_kind(
    completed=completed,
    status=planning_status or status,
    stage=stage,
  )
  event_type_value = str(event_type or "").strip() or _default_event_type(
    completed=completed,
    status=planning_status or status,
    stage=stage,
  )
  event_summary_value = str(event_summary or "").strip() or (
    f"{stage or 'planning'}:{planning_status or status or run_status}"
  )

  projected_run_row: Dict[str, Any] = {}
  if isinstance(run_row, dict):
    projected_run_row.update(copy.deepcopy(run_row))
  projected_run_row.update(
    {
      "planning_run_id": planning_run_id,
      "draft_id": str(draft_id).strip(),
      "client_id": client_id,
      "run_status": run_status,
      "current_stage": stage or None,
      "current_stage_status": planning_status or status or None,
      "current_iteration": current_iteration,
      "current_retry_count": current_retry_count,
      "current_cycle": current_cycle,
      "latest_detected_issue_count": counts.get("detected"),
      "latest_remaining_issue_count": counts.get("remaining"),
      "latest_resolved_issue_count": counts.get("resolved"),
      "latest_checkpoint_id": checkpoint_id,
      "latest_controller_status": (
        str((copy_payload.get("controller_resolution_state") or {}).get("status") or "").strip() or None
        if isinstance(copy_payload.get("controller_resolution_state"), dict)
        else None
      ),
      "failure_reason": str(copy_payload.get("failure_reason") or "").strip() or None,
      "updated_at": now,
      "last_heartbeat_at": now,
      "completed_at": now if run_status == "completed" else None,
    }
  )

  runtime_payload = (
    json.loads(json.dumps(planning_runtime_json, ensure_ascii=False))
    if isinstance(planning_runtime_json, dict)
    else _build_planning_runtime_payload(
      planning_run_json=copy_payload if copy_payload else planning_run_json,
      numeric_solver_feedback_json=numeric_solver_feedback_json,
    )
  )
  repair_guidance_payload = (
    json.loads(json.dumps(repair_guidance_json, ensure_ascii=False))
    if isinstance(repair_guidance_json, dict)
    else {}
  )
  convergence_payload = (
    json.loads(json.dumps(convergence_state_json, ensure_ascii=False))
    if isinstance(convergence_state_json, dict)
    else _build_convergence_state_payload(
      planning_run_json=copy_payload if copy_payload else planning_run_json,
      numeric_solver_feedback_json=numeric_solver_feedback_json,
    )
  )
  planning_convergence_payload = (
    json.loads(json.dumps(planning_convergence_json, ensure_ascii=False))
    if isinstance(planning_convergence_json, dict)
    else _build_planning_convergence_payload(
      planning_run_json=copy_payload if copy_payload else planning_run_json,
      planning_runtime_json=runtime_payload,
      repair_guidance_json=copy.deepcopy(repair_guidance_payload),
      convergence_state_json=copy.deepcopy(convergence_payload),
      numeric_solver_feedback_json=numeric_solver_feedback_json,
    )
  )
  store_full_planning_payload = _should_store_full_planning_payload(
    checkpoint_kind=checkpoint_kind_value,
    run_status=run_status,
    has_existing_run=bool(run_row),
  )
  planning_payload_for_draft = copy.deepcopy(copy_payload) if store_full_planning_payload and copy_payload else None
  store_heavy_checkpoint_payloads = _should_store_heavy_checkpoint_payloads(
    checkpoint_kind=checkpoint_kind_value,
    run_status=run_status,
  )
  numeric_feedback_for_draft = _compact_numeric_feedback_runtime_payload(numeric_solver_feedback_json)
  financial_story_payload = (
    json.loads(json.dumps(financial_story, ensure_ascii=False))
    if isinstance(financial_story, dict)
    else None
  )

  append_messages(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=list(new_messages or []),
    operating_model_json=operating_model_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    marketing_model_json=marketing_model_json,
    financials_year1_json=financials_year1_json,
    realism_memo_json=realism_memo_json,
    planning_context_summary_json=planning_context_summary_json,
    planning_run_json=planning_payload_for_draft,
    planning_runtime_json=copy.deepcopy(runtime_payload),
    planning_convergence_json=copy.deepcopy(planning_convergence_payload),
    repair_guidance_json=copy.deepcopy(repair_guidance_payload),
    convergence_state_json=copy.deepcopy(convergence_payload),
    numeric_solver_feedback_json=copy.deepcopy(numeric_feedback_for_draft),
    financial_story=copy.deepcopy(financial_story_payload),
    fulfillment_json=fulfillment_json,
    model_input_json=model_input_json,
    finmo_json=finmo_json,
    payroll_headcount=payroll_headcount,
    debt_schedule=debt_schedule,
    active_focus=active_focus,
    status=status,
    business_facts=business_facts,
    flat_fields={
      **_planning_run_flat_field_values(copy_payload if copy_payload else planning_run_json),
      **_planning_run_row_flat_field_values(projected_run_row),
    },
    completed=completed,
    commit=False,
  )

  cur = conn.cursor()
  try:
    if run_row:
      cur.execute(
        """
        UPDATE planning_runs
        SET run_status = %s,
            current_stage = %s,
            current_stage_status = %s,
            current_iteration = %s,
            current_retry_count = %s,
            current_cycle = %s,
            latest_detected_issue_count = %s,
            latest_remaining_issue_count = %s,
            latest_resolved_issue_count = %s,
            latest_checkpoint_id = %s,
            latest_controller_status = %s,
            failure_reason = %s,
            updated_at = %s,
            last_heartbeat_at = %s,
            completed_at = %s
        WHERE planning_run_id = %s
        """,
        (
          run_status,
          stage or None,
          planning_status or status or None,
          current_iteration,
          current_retry_count,
          current_cycle,
          counts.get("detected"),
          counts.get("remaining"),
          counts.get("resolved"),
          checkpoint_id,
          str((copy_payload.get("controller_resolution_state") or {}).get("status") or "").strip() or None
          if isinstance(copy_payload.get("controller_resolution_state"), dict)
          else None,
          str(copy_payload.get("failure_reason") or "").strip() or None,
          now,
          now,
          now if run_status == "completed" else None,
          planning_run_id,
        ),
      )
    else:
      cur.execute(
        """
        INSERT INTO planning_runs (
          planning_run_id, draft_id, client_id, run_status, current_stage, current_stage_status,
          current_iteration, current_retry_count, current_cycle, latest_detected_issue_count,
          latest_remaining_issue_count, latest_resolved_issue_count, latest_checkpoint_id,
          resume_from_checkpoint_id, latest_controller_status, failure_reason, trigger_type,
          created_at, updated_at, started_at, last_heartbeat_at, completed_at
        ) VALUES (
          %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s,
          %s, %s, %s,
          %s, %s, %s, %s,
          %s, %s, %s, %s, %s
        )
        """,
        (
          planning_run_id,
          str(draft_id).strip(),
          client_id,
          run_status,
          stage or None,
          planning_status or status or None,
          current_iteration,
          current_retry_count,
          current_cycle,
          counts.get("detected"),
          counts.get("remaining"),
          counts.get("resolved"),
          checkpoint_id,
          None,
          str((copy_payload.get("controller_resolution_state") or {}).get("status") or "").strip() or None
          if isinstance(copy_payload.get("controller_resolution_state"), dict)
          else None,
          str(copy_payload.get("failure_reason") or "").strip() or None,
          "system_run",
          now,
          now,
          now,
          now,
          now if run_status == "completed" else None,
        ),
      )

    cur.execute(
      """
      INSERT INTO planning_run_checkpoints (
        checkpoint_id, planning_run_id, draft_id, client_id, stage, stage_status,
        iteration, retry_count, cycle, checkpoint_kind, controller_resolution_state_json,
        planning_run_json, planning_convergence_json, repair_guidance_json, convergence_state_json, numeric_solver_feedback_json, financial_story, model_input_json, finmo_json,
        realism_memo_json, diagnostics_json, created_at, updated_at
      ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s
      )
      """,
      (
        checkpoint_id,
        planning_run_id,
        str(draft_id).strip(),
        client_id,
        stage or None,
        planning_status or status or None,
        current_iteration,
        current_retry_count,
        current_cycle,
        checkpoint_kind_value,
        json.dumps(copy_payload.get("controller_resolution_state"), ensure_ascii=False)
        if isinstance(copy_payload.get("controller_resolution_state"), dict)
        else None,
        json.dumps(copy_payload, ensure_ascii=False)
        if store_heavy_checkpoint_payloads and isinstance(copy_payload, dict) and copy_payload
        else None,
        json.dumps(planning_convergence_payload, ensure_ascii=False)
        if isinstance(planning_convergence_payload, dict) and planning_convergence_payload
        else None,
        json.dumps(repair_guidance_payload, ensure_ascii=False)
        if isinstance(repair_guidance_payload, dict) and repair_guidance_payload
        else None,
        json.dumps(convergence_payload, ensure_ascii=False)
        if isinstance(convergence_payload, dict) and convergence_payload
        else None,
        json.dumps(numeric_feedback_for_draft, ensure_ascii=False)
        if store_heavy_checkpoint_payloads and isinstance(numeric_feedback_for_draft, dict) and numeric_feedback_for_draft
        else None,
        json.dumps(financial_story_payload, ensure_ascii=False)
        if isinstance(financial_story_payload, dict) and financial_story_payload
        else None,
        json.dumps(model_input_json, ensure_ascii=False)
        if store_heavy_checkpoint_payloads and isinstance(model_input_json, dict)
        else None,
        json.dumps(finmo_json, ensure_ascii=False)
        if store_heavy_checkpoint_payloads and isinstance(finmo_json, dict)
        else None,
        json.dumps(realism_memo_json, ensure_ascii=False)
        if store_heavy_checkpoint_payloads and isinstance(realism_memo_json, dict)
        else None,
        json.dumps((copy_payload.get("diagnostics_snapshot") if isinstance(copy_payload.get("diagnostics_snapshot"), dict) else {}), ensure_ascii=False)
        if isinstance(copy_payload, dict) and copy_payload.get("diagnostics_snapshot") is not None
        else None,
        now,
        now,
      ),
    )

    cur.execute(
      """
      INSERT INTO planning_stage_events (
        event_id, planning_run_id, draft_id, client_id, stage, stage_status,
        iteration, retry_count, cycle, event_type, event_summary, event_payload_json, created_at
      ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
      )
      """,
      (
        event_id,
        planning_run_id,
        str(draft_id).strip(),
        client_id,
        stage or None,
        planning_status or status or None,
        current_iteration,
        current_retry_count,
        current_cycle,
        event_type_value,
        event_summary_value,
        json.dumps(
          {
            "checkpoint_id": checkpoint_id,
            "run_status": run_status,
            "stage": stage,
            "status": planning_status or status,
            "remaining_issue_count": counts.get("remaining"),
            "resolved_issue_count": counts.get("resolved"),
            "detected_issue_count": counts.get("detected"),
            "planning_runtime_json": runtime_payload,
            "planning_convergence_json": planning_convergence_payload,
            "repair_guidance_json": repair_guidance_payload,
            "convergence_state_json": convergence_payload,
            "financial_story": financial_story_payload,
          },
          ensure_ascii=False,
        ),
        now,
      ),
    )
    conn.commit()
  except Exception:
    try:
      conn.rollback()
    except Exception:
      pass
    raise
  finally:
    try:
      cur.close()
    except Exception:
      pass

  return {
    "planning_run_id": planning_run_id,
    "checkpoint_id": checkpoint_id,
    "event_id": event_id,
    "run_status": run_status,
    "planning_context_summary_json": copy.deepcopy(planning_context_summary_json or {}),
    "planning_run_json": copy_payload if copy_payload else planning_run_json,
    "planning_runtime_json": runtime_payload,
    "planning_convergence_json": planning_convergence_payload,
    "repair_guidance_json": repair_guidance_payload,
    "convergence_state_json": convergence_payload,
    "financial_story": financial_story_payload,
    "debt_schedule": copy.deepcopy(debt_schedule or {}),
  }


_PLAN_CONFIDENCE_TO_TIER = {
  "high_no_adaptation": 0,
  "medium_gpt_band_relaxation": 1,
  "medium_cohort_fallback": 2,
  "low_target_tolerance_widened": 3,
  "low_supplementary_levers_used": 4,
  "low_planning_mode_shifted": 5,
  "low_stage_family_widened": 6,
  "generic_fallback_no_calibration": 7,
}


def persist_adaptation_cascade_outcome(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  plan_confidence: Optional[str],
  cascade_diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Phase 3.8 — persist orchestrator plan_confidence + cascade diagnostics.

  UPDATEs planning_runs (plan_confidence, cascade_landed_tier,
  cascade_tiers_attempted_json) and emits one planning_stage_events row
  with event_type='adaptation_cascade_completed' when cascade_diagnostics
  is non-None and the landed tier > 0. Tier 0 (no adaptation) skips the
  event INSERT.
  """
  pr_id = str(planning_run_id or "").strip()
  d_id = str(draft_id or "").strip()
  conf = str(plan_confidence or "").strip() or None
  if not pr_id:
    return {"persisted": False, "reason": "missing_planning_run_id"}
  ensure_table(conn)
  diag = cascade_diagnostics if isinstance(cascade_diagnostics, dict) else None
  tier: Optional[int] = None
  if diag is not None:
    raw = diag.get("tier_landed")
    try:
      if raw is not None:
        tier = int(raw)
    except Exception:
      tier = None
  if tier is None and conf:
    tier = _PLAN_CONFIDENCE_TO_TIER.get(conf)
  attempts_json: Optional[str] = None
  if diag is not None and isinstance(diag.get("tier_attempts"), list):
    attempts_json = json.dumps(
      [
        {
          "tier": x.get("tier"), "tier_name": x.get("tier_name"),
          "attempted": bool(x.get("attempted")), "success": bool(x.get("success")),
          "skip_reason": x.get("skip_reason"),
          "residual_hard_fail_count": x.get("residual_hard_fail_count"),
        }
        for x in diag["tier_attempts"] if isinstance(x, dict)
      ],
      ensure_ascii=False,
    )
  now = current_app_timestamp_str()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute("SELECT client_id FROM planning_runs WHERE planning_run_id = %s", (pr_id,))
    row = cur.fetchone()
    client_id = str((row or {}).get("client_id") or "").strip()
  finally:
    try: cur.close()
    except Exception: pass
  cur = conn.cursor()
  event_emitted = False
  try:
    cur.execute(
      """
      UPDATE planning_runs
      SET plan_confidence = %s, cascade_landed_tier = %s,
          cascade_tiers_attempted_json = %s, updated_at = %s
      WHERE planning_run_id = %s
      """,
      (conf, tier, attempts_json, now, pr_id),
    )
    if diag is not None and tier is not None and int(tier) > 0 and client_id:
      cur.execute(
        """
        INSERT INTO planning_stage_events (
          event_id, planning_run_id, draft_id, client_id, stage, stage_status,
          iteration, retry_count, cycle, event_type, event_summary, event_payload_json, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
          uuid.uuid4().hex, pr_id, d_id, client_id,
          "post_intake_finalize", "completed", None, None, None,
          "adaptation_cascade_completed", conf,
          json.dumps(diag, ensure_ascii=False), now,
        ),
      )
      event_emitted = True
    conn.commit()
  except Exception:
    try: conn.rollback()
    except Exception: pass
    raise
  finally:
    try: cur.close()
    except Exception: pass
  return {
    "persisted": True, "planning_run_id": pr_id,
    "plan_confidence": conf, "cascade_landed_tier": tier,
    "cascade_event_emitted": event_emitted,
  }


def mark_submitted(
  conn,
  *,
  draft_id: str,
  intake_submission_id: int,
) -> None:
  now = current_app_timestamp_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      UPDATE intake_consult_drafts
      SET status = 'submitted',
          submitted_at = %s,
          intake_submission_id = %s,
          updated_at = %s
      WHERE draft_id = %s
        AND (intake_submission_id IS NULL)
      """,
      (now, int(intake_submission_id), now, draft_id),
    )
    if getattr(cur, "rowcount", 0) == 0:
      raise RuntimeError("Draft already submitted or missing.")
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass


def reopen_draft(conn, *, draft_id: str) -> None:
  """
  Reopen a completed consult for continued conversation and refinement.
  Keeps messages_json intact but clears operating_model_json and completed_at.
  """
  ensure_table(conn)
  now = current_app_timestamp_str()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      UPDATE intake_consult_drafts
      SET status = 'in_progress',
          operating_model_json = NULL,
          completed_at = NULL,
          updated_at = %s
      WHERE draft_id = %s
        AND status = 'completed'
      """,
      (now, draft_id),
    )
    conn.commit()
  finally:
    try:
      cur.close()
    except Exception:
      pass
