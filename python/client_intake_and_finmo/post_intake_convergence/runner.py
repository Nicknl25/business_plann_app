"""Unified post-grid convergence runner.

This file owns the convergence loop body. The API handler binds the existing
runtime helpers once and then calls this module as the convergence phase owner.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_mapping import (
  post_intake_assert_required_process_sequence,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_process_step_context,
)

_CYCLE_DEADLINE_GUARD_SECONDS = 8.0
_PLANNER_GPT_MAX_SECONDS = 75.0
_PLAN_BUILDER_MAX_SECONDS = 35.0
_VERIFICATION_GPT_MAX_SECONDS = 45.0


def _contract_forecast_quarter_count() -> int:
  try:
    return max(
      1,
      int(
        post_intake_contract_forecast_horizon_quarter_count(
          contract_name="unified_convergence_decision",
        )
        or 0
      ),
    )
  except Exception:
    return 20


def _bounded_cycle_deadline(cycle_deadline: float, max_seconds: float) -> float:
  """Keep each subcall inside the total 180s cycle budget with a return guard."""
  now = time.perf_counter()
  guarded_cycle_deadline = float(cycle_deadline) - float(_CYCLE_DEADLINE_GUARD_SECONDS)
  return min(guarded_cycle_deadline, now + max(1.0, float(max_seconds)))


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  """Bind handler/runtime helpers used by the extracted convergence loop."""
  globals().update(dependencies or {})


def _reset_non_productive_cycle_tracker(retry_memory: Dict[str, Any]) -> None:
  """Reset retry-loop stall memory after a solver-ready cycle is accepted."""
  if not isinstance(retry_memory, dict):
    return
  retry_memory["non_productive_cycle_tracker"] = {
    "consecutive_non_productive_cycles": 0,
    "repeated_same_pattern": False,
    "repeated_failure_pattern": "",
    "last_known_state": {},
  }
  retry_memory["recent_validation_errors"] = []


def _hard_rule_failure_count(assessment: Optional[Dict[str, Any]]) -> int:
  payload = assessment if isinstance(assessment, dict) else {}
  if bool(payload.get("all_hard_rules_cleared")) or bool(payload.get("all_cleared")):
    return 0
  for key in ("failed_count", "violation_count", "failure_count", "open_violation_count"):
    value = _safe_float(payload.get(key))
    if value is not None:
      return max(0, int(round(float(value))))
  count = 0
  for key in ("failures", "violations", "remaining_violations", "failed_rules"):
    value = payload.get(key)
    if isinstance(value, list):
      count += len(value)
  return count


def _controller_issue_records(state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = state if isinstance(state, dict) else {}
  candidates: List[Any] = [
    payload.get("remaining_issues"),
    payload.get("detected_issues"),
    (
      (payload.get("current_issue_summaries") or {}).get("detected_issues")
      if isinstance(payload.get("current_issue_summaries"), dict)
      else None
    ),
  ]
  records: List[Dict[str, Any]] = []
  for candidate in candidates:
    if isinstance(candidate, list) and candidate:
      records = [item for item in candidate if isinstance(item, dict)]
      if records:
        break
  return records


def _controller_issue_gap_summary(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  records = _controller_issue_records(state)
  total_gap_abs = 0.0
  total_severity = 0.0
  issue_count_with_gap = 0
  issue_codes: List[str] = []
  by_issue: Dict[str, Dict[str, Any]] = {}
  for record in records:
    code = str(record.get("issue_code") or record.get("issue") or "").strip().lower()
    if code:
      issue_codes.append(code)
    gap_value = _safe_float(record.get("aggregate_gap_abs"))
    if gap_value is None:
      metric_gaps = [
        abs(float(_safe_float(spec.get("gap_abs")) or 0.0))
        for spec in (record.get("metric_debug") or [])
        if isinstance(spec, dict)
      ]
      gap_value = sum(metric_gaps) if metric_gaps else None
    severity_value = _safe_float(record.get("remaining_issue_severity_score"))
    if severity_value is None:
      severity_value = _safe_float(record.get("severity_score"))
    if gap_value is not None:
      gap_float = abs(float(gap_value))
      total_gap_abs += gap_float
      issue_count_with_gap += 1
    else:
      gap_float = 0.0
    severity_float = max(0.0, float(severity_value or 0.0))
    total_severity += severity_float
    if code:
      by_issue[code] = {
        "gap_abs": gap_float,
        "severity_score": severity_float,
      }
  return {
    "issue_codes": sorted(set(issue_codes)),
    "issue_count_with_gap": issue_count_with_gap,
    "total_gap_abs": total_gap_abs,
    "total_severity_score": total_severity,
    "by_issue": by_issue,
  }


def _issue_gap_materially_improved(
  *,
  before_summary: Dict[str, Any],
  after_summary: Dict[str, Any],
) -> bool:
  before_gap = float(_safe_float(before_summary.get("total_gap_abs")) or 0.0)
  after_gap = float(_safe_float(after_summary.get("total_gap_abs")) or 0.0)
  if before_gap <= 0.0:
    return False
  gap_delta = before_gap - after_gap
  if gap_delta <= 0.0:
    return False
  # A cycle is productive when it materially shrinks the table-backed issue
  # diagnostic, even if the issue needs another cycle to fully clear.
  return gap_delta >= max(1000.0, before_gap * 0.02)


def _build_unified_cycle_quality_assessment(
  *,
  before_controller_resolution_state: Dict[str, Any],
  before_hard_rule_assessment: Dict[str, Any],
  after_controller_resolution_state: Dict[str, Any],
  after_hard_rule_assessment: Dict[str, Any],
  before_finmo_json: Dict[str, Any],
  after_finmo_json: Dict[str, Any],
  result_payload: Dict[str, Any],
  before_numeric_guidance_packet: Dict[str, Any],
  candidate_signature: Dict[str, Any],
  prior_quality_assessment: Dict[str, Any],
) -> Dict[str, Any]:
  """Decide whether a convergence cycle made durable progress worth keeping."""
  del before_finmo_json, after_finmo_json, before_numeric_guidance_packet, prior_quality_assessment
  before_state = before_controller_resolution_state if isinstance(before_controller_resolution_state, dict) else {}
  after_state = after_controller_resolution_state if isinstance(after_controller_resolution_state, dict) else {}
  before_remaining = int(_safe_float(before_state.get("remaining_issue_count")) or 0)
  after_remaining = int(_safe_float(after_state.get("remaining_issue_count")) or 0)
  before_resolved = int(_safe_float(before_state.get("resolved_issue_count")) or 0)
  after_resolved = int(_safe_float(after_state.get("resolved_issue_count")) or 0)
  before_score = float(_safe_float(before_state.get("overall_completion_score_pct")) or 0.0)
  after_score = float(_safe_float(after_state.get("overall_completion_score_pct")) or 0.0)
  before_hard_failures = _hard_rule_failure_count(before_hard_rule_assessment)
  after_hard_failures = _hard_rule_failure_count(after_hard_rule_assessment)
  before_issue_gap_summary = _controller_issue_gap_summary(before_state)
  after_issue_gap_summary = _controller_issue_gap_summary(after_state)
  issue_count_improved = after_remaining < before_remaining
  resolved_count_improved = after_resolved > before_resolved
  score_improved = after_score >= before_score + 1.0
  issue_gap_improved = _issue_gap_materially_improved(
    before_summary=before_issue_gap_summary,
    after_summary=after_issue_gap_summary,
  )
  hard_rules_improved = after_hard_failures < before_hard_failures
  hard_rules_worsened = after_hard_failures > before_hard_failures
  issue_count_regressed = after_remaining > before_remaining
  all_cleared = bool(after_state.get("all_cleared")) and after_hard_failures == 0
  meaningful_progress = bool(
    all_cleared
    or issue_count_improved
    or resolved_count_improved
    or hard_rules_improved
    or score_improved
    or issue_gap_improved
  )
  reject_attempt = bool(
    issue_count_regressed
    or hard_rules_worsened
    or not meaningful_progress
  )
  accepted = not reject_attempt
  return {
    "status": "accepted" if accepted else "rejected_no_meaningful_progress",
    "accepted": accepted,
    "reject_attempt": reject_attempt,
    "meaningful_progress": meaningful_progress,
    "no_progress": not meaningful_progress,
    "remaining_issue_count_before": before_remaining,
    "remaining_issue_count_after": after_remaining,
    "resolved_issue_count_before": before_resolved,
    "resolved_issue_count_after": after_resolved,
    "overall_completion_score_pct_before": before_score,
    "overall_completion_score_pct_after": after_score,
    "hard_rule_failure_count_before": before_hard_failures,
    "hard_rule_failure_count_after": after_hard_failures,
    "issue_count_improved": issue_count_improved,
    "issue_count_regressed": issue_count_regressed,
    "resolved_count_improved": resolved_count_improved,
    "score_improved": score_improved,
    "issue_gap_improved": issue_gap_improved,
    "issue_gap_abs_before": before_issue_gap_summary.get("total_gap_abs"),
    "issue_gap_abs_after": after_issue_gap_summary.get("total_gap_abs"),
    "issue_gap_summary_before": before_issue_gap_summary,
    "issue_gap_summary_after": after_issue_gap_summary,
    "hard_rules_improved": hard_rules_improved,
    "hard_rules_worsened": hard_rules_worsened,
    "all_cleared": all_cleared,
    "worsened_without_compensating_improvement": bool((issue_count_regressed or hard_rules_worsened) and not meaningful_progress),
    "solver_invoked": bool((result_payload or {}).get("solver_invoked", True)),
    "candidate_signature": candidate_signature if isinstance(candidate_signature, dict) else {},
    "open_issue_codes_before": [
      str(item.get("issue_code") or "").strip().lower()
      for item in (before_state.get("remaining_issues") or [])
      if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
    ],
    "open_issue_codes_after": [
      str(item.get("issue_code") or "").strip().lower()
      for item in (after_state.get("remaining_issues") or [])
      if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
    ],
  }

def _run_unified_post_grid_system_run(
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
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.numeric_execution import build_numeric_solver_contract  # type: ignore
  except Exception:
    from numeric_execution import build_numeric_solver_contract  # type: ignore

  active_planning_run_id = str(planning_run_id or "").strip()
  prompt_file = str(planning_result.get("prompt_file") or "").strip()
  final_model_input_json = _model_input_with_controller_catalog(
    model_input_json=copy.deepcopy(applied_model_input_json or {}),
    catalog_source_model_input_json=copy.deepcopy(catalog_source_model_input_json or {}),
  )
  if not isinstance(stage_ramp_contract, dict) or not stage_ramp_contract:
    raise RuntimeError(
      "stage_ramp_contract_missing_before_convergence: GPT stage ramp contract must be generated before post-intake convergence."
    )
  process_sequence_trace: Dict[str, Any] = {}
  process_sequence_trace["required_process_sequence"] = post_intake_assert_required_process_sequence()
  process_sequence_trace["issue_detection"] = post_intake_process_step_context(
    step_key="issue_detection",
    expected_phase="convergence",
    expected_handler_key="detect_post_intake_issues",
    required_lookup_tables=["post_intak_mapping_lookup", "post_intake_gpt_contract_lookup"],
    required_horizon_rule="scan_all_q1_to_q20",
  )
  process_sequence_trace["unified_convergence_decision"] = post_intake_process_step_context(
    step_key="unified_convergence_decision",
    expected_phase="convergence",
    expected_handler_key="run_unified_convergence_cycle",
    required_contract_name="unified_convergence_decision",
    required_context_contract_name="unified_convergence_decision",
    required_context_include_phase="planner",
    required_lookup_tables=[
      "post_intak_mapping_lookup",
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
    ],
    required_horizon_rule="q1_to_q20_model_input_repair_cells",
  )
  final_finmo_json = copy.deepcopy(applied_finmo_json or {})
  realism_memo_before_resolution = {
    "contract_version": "post_intake_deterministic_issue_detection_v1",
    "status": "ready",
    "source_of_truth": "deterministic_table_backed_issue_detectors",
    "issues": [],
    "remaining_issues": [],
  }
  capacity_support_issue_ledger = _build_capacity_support_issue_status_records(
    finmo_json=copy.deepcopy(final_finmo_json),
    iteration=0,
  )
  flatline_issue_ledger = _build_p_and_l_flatline_issue_status_records(
    model_input_json=copy.deepcopy(final_model_input_json),
    finmo_json=copy.deepcopy(final_finmo_json),
    iteration=0,
  )
  stage_maturity_issue_ledger = _build_stage_maturity_cost_structure_issue_status_records(
    model_input_json=copy.deepcopy(final_model_input_json),
    finmo_json=copy.deepcopy(final_finmo_json),
    stage_ramp_contract=copy.deepcopy(stage_ramp_contract),
    iteration=0,
  )
  realism_issue_ledger = _refresh_issue_status_records_from_scan(
    existing_issue_status_records=[],
    scanned_issue_status_records=(
      copy.deepcopy(capacity_support_issue_ledger)
      + copy.deepcopy(flatline_issue_ledger)
      + copy.deepcopy(stage_maturity_issue_ledger)
    ),
    iteration=0,
  )
  resolution_summary = _build_resolution_summary_from_issue_ledger(
    before_memo=copy.deepcopy(realism_memo_before_resolution),
    issue_status_records=copy.deepcopy(realism_issue_ledger),
  )
  realism_memo_json = _build_realism_memo_from_issue_ledger(
    before_memo=copy.deepcopy(realism_memo_before_resolution),
    issue_status_records=copy.deepcopy(realism_issue_ledger),
    resolution_summary=copy.deepcopy(resolution_summary),
    iteration=0,
  )
  controller_resolution_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(realism_issue_ledger),
    iteration=0,
    current_finmo_json=copy.deepcopy(final_finmo_json),
  )
  protected_resolved_issue_constraints = _build_strategy_resolved_issue_constraints(
    copy.deepcopy(realism_issue_ledger)
  )
  prior_numeric_feedback = _build_numeric_solver_feedback_payload(
    copy.deepcopy(grid_application_summary if isinstance(grid_application_summary, dict) else {})
  )
  unified_convergence_iterations: List[Dict[str, Any]] = []
  unified_convergence_cycle_count = 0
  unified_convergence_decision: Dict[str, Any] = {}
  unified_convergence_plan: Dict[str, Any] = {}
  unified_convergence_result: Dict[str, Any] = {}
  cash_strategy_review_context: Dict[str, Any] = {}
  cash_strategy_review_decision: Dict[str, Any] = {}
  cash_strategy_second_pass_plan: Dict[str, Any] = {}
  cash_strategy_second_pass_result: Dict[str, Any] = {}
  cash_strategy_effect_summary: Dict[str, Any] = {}
  latest_quality_assessment: Dict[str, Any] = {}
  consecutive_no_progress_cycles = 0
  retry_memory: Dict[str, Any] = {
    "completed_attempt_count": 0,
    "prior_lever_unions": [],
    "prior_target_keys": [],
    "latest_candidate_signature": {},
    "latest_result_signature": {},
    "latest_improvement_summary": {},
    "latest_validation_error": {},
    "recent_validation_errors": [],
    "attempt_records": [],
    "prior_controller_state_summary": {},
    "latest_controller_state_summary": {
      "overall_completion_score_pct": int(_safe_float(controller_resolution_state.get("overall_completion_score_pct")) or 0),
      "overall_completion_grade": str(controller_resolution_state.get("overall_completion_grade") or "").strip() or "D",
      "lowest_quarter_score_pct": int(_safe_float(controller_resolution_state.get("lowest_quarter_score_pct")) or 0),
      "remaining_issue_count": int(_safe_float(controller_resolution_state.get("remaining_issue_count")) or 0),
      "resolved_issue_count": int(_safe_float(controller_resolution_state.get("resolved_issue_count")) or 0),
      "tolerated_issue_count": int(_safe_float(controller_resolution_state.get("tolerated_issue_count")) or 0),
    },
  }

  def _rebuild_unified_context() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    next_context = _build_unified_convergence_context_payload(
      draft_id=str(draft_id).strip(),
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      current_model_input_json=copy.deepcopy(final_model_input_json),
      current_finmo_json=copy.deepcopy(final_finmo_json),
      controller_resolution_state=copy.deepcopy(controller_resolution_state),
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      protected_resolved_issue_constraints=copy.deepcopy(protected_resolved_issue_constraints),
      prior_numeric_feedback=copy.deepcopy(prior_numeric_feedback),
      stage_ramp_contract=copy.deepcopy(stage_ramp_contract),
    )
    next_hard_rules = (
      next_context.get("hard_rule_assessment")
      if isinstance(next_context.get("hard_rule_assessment"), dict)
      else {}
    )
    next_context["cycle_stall_assessment"] = _build_unified_cycle_stall_assessment(
      consecutive_no_progress_cycles=consecutive_no_progress_cycles,
      latest_quality_assessment=latest_quality_assessment,
    )
    return next_context, copy.deepcopy(next_hard_rules)

  unified_convergence_context, hard_rule_assessment = _rebuild_unified_context()
  _persist_unified_convergence_state(
    conn=conn,
    draft_id=str(draft_id).strip(),
    stage="convergence_running",
    status="running",
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    resolution_summary=copy.deepcopy(resolution_summary),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution),
    realism_memo_json=copy.deepcopy(realism_memo_json),
    unified_convergence_context=copy.deepcopy(unified_convergence_context),
    unified_convergence_decision={},
    unified_convergence_plan={},
    unified_convergence_result={},
    unified_convergence_iterations=[],
    unified_convergence_cycle_count=0,
    model_input_json=copy.deepcopy(final_model_input_json),
    finmo_json=copy.deepcopy(final_finmo_json),
  )
  _maybe_interrupt_planning_run(
    conn=conn,
    draft_id=str(draft_id).strip(),
    planning_run_id=active_planning_run_id,
    stage="convergence_running",
    planning_status="running",
    model_input_json=copy.deepcopy(final_model_input_json),
    finmo_json=copy.deepcopy(final_finmo_json),
    realism_memo_json=copy.deepcopy(realism_memo_json),
    event_summary="convergence:stage_gate",
  )

  while (
    not bool(controller_resolution_state.get("all_cleared"))
    or not bool(hard_rule_assessment.get("all_hard_rules_cleared"))
  ):
    if (
      bool(controller_resolution_state.get("all_cleared"))
      and _hard_rules_can_defer_to_cash_strategy(hard_rule_assessment)
    ):
      break
    unified_convergence_cycle_count += 1
    if unified_convergence_cycle_count > _UNIFIED_CONVERGENCE_MAX_CYCLES:
      raise RuntimeError("unified_convergence_unresolved_after_max_cycles")
    cycle_started_at = time.perf_counter()
    cycle_deadline = cycle_started_at + float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS)
    cycle_timing: Dict[str, Any] = {
      "cycle": int(unified_convergence_cycle_count),
      "cycle_wall_clock_timeout_seconds": float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS),
      "cycle_timing_policy": "fail_if_total_cycle_elapsed_exceeds_180_seconds",
      "started_at_monotonic": float(cycle_started_at),
      "deadline_monotonic": float(cycle_deadline),
      "phase_timings": [],
    }
    phase_started_at = cycle_started_at
    previous_cycle_openai_deadline = _set_active_openai_deadline(cycle_deadline)

    baseline_model_input_json = copy.deepcopy(final_model_input_json)
    baseline_finmo_json = copy.deepcopy(final_finmo_json)
    baseline_issue_ledger = copy.deepcopy(realism_issue_ledger)
    baseline_controller_resolution_state = copy.deepcopy(controller_resolution_state)
    baseline_realism_memo_json = copy.deepcopy(realism_memo_json)
    baseline_resolution_summary = copy.deepcopy(resolution_summary)
    hard_rule_assessment_before = copy.deepcopy(hard_rule_assessment)
    stall_assessment = _build_unified_cycle_stall_assessment(
      consecutive_no_progress_cycles=consecutive_no_progress_cycles,
      latest_quality_assessment=latest_quality_assessment,
    )
    retry_focus_packet = _build_convergence_retry_focus_packet(
      attempt_number=unified_convergence_cycle_count,
      controller_resolution_state=copy.deepcopy(controller_resolution_state),
      latest_quality_assessment=copy.deepcopy(latest_quality_assessment),
      stall_assessment=copy.deepcopy(stall_assessment),
      retry_memory=copy.deepcopy(retry_memory),
      numeric_solver_contract=copy.deepcopy((unified_convergence_context or {}).get("numeric_solver_contract") or {}),
      prior_numeric_feedback=copy.deepcopy(prior_numeric_feedback),
    )
    controller_retry_context = _build_pass_retry_context(
      pass_name="unified_convergence",
      pass_label="Unified Convergence",
      attempt_number=unified_convergence_cycle_count,
      max_attempts=_UNIFIED_CONVERGENCE_MAX_CYCLES,
      retry_memory=copy.deepcopy(retry_memory),
      numeric_solver_contract=copy.deepcopy((unified_convergence_context or {}).get("numeric_solver_contract") or {}),
    )
    controller_retry_context.update(copy.deepcopy(stall_assessment))
    controller_retry_context["issues_remaining"] = int(_safe_float(controller_resolution_state.get("remaining_issue_count")) or 0)
    controller_retry_context["failed_quarters"] = copy.deepcopy(
      (
        (prior_numeric_feedback.get("target_verification") if isinstance(prior_numeric_feedback.get("target_verification"), dict) else {})
        .get("quarters_failed")
        or []
      )
    )
    controller_retry_context["failed_metrics"] = copy.deepcopy(
      (
        (prior_numeric_feedback.get("quarter_fit_summary") or [])
        if isinstance(prior_numeric_feedback, dict)
        else []
      )
    )
    controller_retry_context["previous_levers_used"] = copy.deepcopy(
      (retry_memory.get("latest_candidate_signature") or {}).get("lever_set_union") or []
    )
    controller_retry_context["focus_issue_codes"] = copy.deepcopy(
      retry_focus_packet.get("focus_issue_codes")
      or retry_focus_packet.get("required_open_issue_codes")
      or []
    )
    controller_retry_context["focus_quarters"] = copy.deepcopy(
      retry_focus_packet.get("focus_quarters")
      or retry_focus_packet.get("required_failed_quarters")
      or []
    )
    controller_retry_context["progress_status"] = str(
      retry_focus_packet.get("progress_status")
      or (
        "regressed" if bool(latest_quality_assessment.get("worsened_without_compensating_improvement"))
        else "stalled" if bool(stall_assessment.get("stalled"))
        else "initial" if unified_convergence_cycle_count == 1
        else "improved"
      )
    ).strip()
    previous_controller_summary = (
      retry_memory.get("prior_controller_state_summary")
      if isinstance(retry_memory.get("prior_controller_state_summary"), dict)
      else {}
    )
    latest_controller_summary = (
      retry_memory.get("latest_controller_state_summary")
      if isinstance(retry_memory.get("latest_controller_state_summary"), dict)
      else {}
    )
    controller_retry_context["previous_overall_completion_score_pct"] = _safe_float(
      previous_controller_summary.get("overall_completion_score_pct")
    )
    controller_retry_context["previous_overall_completion_grade"] = str(
      previous_controller_summary.get("overall_completion_grade") or ""
    ).strip()
    controller_retry_context["latest_overall_completion_score_pct"] = int(
      _safe_float(latest_controller_summary.get("overall_completion_score_pct")) or 0
    )
    controller_retry_context["latest_overall_completion_grade"] = str(
      latest_controller_summary.get("overall_completion_grade") or ""
    ).strip() or "D"
    controller_retry_context["last_failure_reason"] = str(
      retry_focus_packet.get("last_failure_reason")
      or (retry_memory.get("latest_validation_error") or {}).get("reason")
      or ("post_execution_regression_or_no_progress" if bool(latest_quality_assessment.get("reject_attempt")) else "")
    ).strip()
    controller_retry_context["constraints"] = unified_convergence_contract_constraints(
      [
        "remaining_issue_count must converge to zero",
        "accounting must hold",
        "hard rules must hold",
        "use only authorized levers",
        *copy.deepcopy(retry_focus_packet.get("constraints") or []),
      ]
    )
    controller_retry_context["required_open_issue_codes"] = copy.deepcopy(
      retry_focus_packet.get("required_open_issue_codes") or []
    )
    controller_retry_context["required_primary_metric_candidates"] = copy.deepcopy(
      retry_focus_packet.get("required_primary_metric_candidates") or []
    )
    controller_retry_context["required_issue_lever_ids"] = copy.deepcopy(
      retry_focus_packet.get("required_issue_lever_ids") or []
    )
    controller_retry_context["minimum_primary_metric_coverage_count"] = int(
      _safe_float(retry_focus_packet.get("minimum_primary_metric_coverage_count")) or 0
    )
    controller_retry_context["issue_coverage_requirements"] = copy.deepcopy(
      retry_focus_packet.get("issue_coverage_requirements") or []
    )
    planner_snapshot = {
      "attempt_number": unified_convergence_cycle_count,
      "attempt_stage": _controller_retry_stage_for_attempt(unified_convergence_cycle_count),
      "status": "planner_running",
      "decision": copy.deepcopy(unified_convergence_decision),
      "plan": copy.deepcopy(unified_convergence_plan),
      "result": copy.deepcopy(unified_convergence_result),
      "retry_memory": _compact_retry_memory_snapshot(retry_memory),
      "working_model_input_json": copy.deepcopy(final_model_input_json),
      "working_finmo_json": copy.deepcopy(final_finmo_json),
      "controller_retry_context": copy.deepcopy(controller_retry_context),
      "candidate_signature": {},
      "validation_error": None,
    }
    _persist_unified_convergence_state(
      conn=conn,
      draft_id=str(draft_id).strip(),
      stage="convergence_running",
      status="running",
      planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
      controller_resolution_state=copy.deepcopy(controller_resolution_state),
      resolution_summary=copy.deepcopy(resolution_summary),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution),
      realism_memo_json=copy.deepcopy(realism_memo_json),
      unified_convergence_context=copy.deepcopy(unified_convergence_context),
      unified_convergence_decision=copy.deepcopy(unified_convergence_decision),
      unified_convergence_plan=copy.deepcopy(unified_convergence_plan),
      unified_convergence_result=copy.deepcopy(unified_convergence_result),
      unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations),
      unified_convergence_cycle_count=unified_convergence_cycle_count,
      model_input_json=copy.deepcopy(final_model_input_json),
      finmo_json=copy.deepcopy(final_finmo_json),
      controller_retry_heartbeat=_controller_retry_heartbeat_from_snapshot(planner_snapshot),
    )
    _maybe_interrupt_planning_run(
      conn=conn,
      draft_id=str(draft_id).strip(),
      planning_run_id=active_planning_run_id,
      stage="convergence_running",
      planning_status="running",
      model_input_json=copy.deepcopy(final_model_input_json),
      finmo_json=copy.deepcopy(final_finmo_json),
      realism_memo_json=copy.deepcopy(realism_memo_json),
      event_summary=f"convergence:cycle_{unified_convergence_cycle_count}_planner_gate",
    )
    _mark_unified_convergence_cycle_phase(
      cycle_timing=cycle_timing,
      cycle_started_at=cycle_started_at,
      phase_name="contract_build_and_planner_gate",
      phase_started_at=phase_started_at,
      detail="Built retry context, persisted planner heartbeat, and prepared planner call.",
    )
    _raise_unified_convergence_cycle_timeout_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="contract_build_and_planner_gate",
      cycle_timing=cycle_timing,
    )

    _raise_unified_convergence_stage_budget_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="planner_gpt_start",
      minimum_remaining_seconds=_CYCLE_DEADLINE_GUARD_SECONDS + 5.0,
      detail="Planner GPT call cannot start without enough cycle budget to return before the 180s wall.",
      cycle_timing=cycle_timing,
    )
    phase_started_at = time.perf_counter()
    previous_openai_deadline = _set_active_openai_deadline(
      _bounded_cycle_deadline(cycle_deadline, _PLANNER_GPT_MAX_SECONDS)
    )
    try:
      unified_convergence_decision = _run_unified_convergence_openai(
        draft_id=str(draft_id).strip(),
        planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
        planning_mode=planning_mode,
        planning_mode_reason=planning_mode_reason,
        planning_mode_prompt_file=prompt_file,
        unified_convergence_context=copy.deepcopy(unified_convergence_context),
        prior_numeric_feedback=copy.deepcopy(prior_numeric_feedback),
        controller_retry_context=copy.deepcopy(controller_retry_context),
      )
    finally:
      _set_active_openai_deadline(previous_openai_deadline)
    _mark_unified_convergence_cycle_phase(
      cycle_timing=cycle_timing,
      cycle_started_at=cycle_started_at,
      phase_name="planner_gpt_and_contract_validation",
      phase_started_at=phase_started_at,
      detail=str((unified_convergence_decision or {}).get("status") or "").strip(),
    )
    cycle_timing["planner_elapsed_seconds"] = round(time.perf_counter() - cycle_started_at, 3)
    _raise_unified_convergence_cycle_timeout_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="planner",
      detail=str((unified_convergence_decision or {}).get("detail") or "").strip(),
      cycle_timing=cycle_timing,
    )
    _raise_unified_convergence_stage_budget_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="plan_builder_start",
      minimum_remaining_seconds=_CYCLE_DEADLINE_GUARD_SECONDS + 5.0,
      detail="Plan builder cannot start without enough cycle budget to return before the 180s wall.",
      cycle_timing=cycle_timing,
    )
    phase_started_at = time.perf_counter()
    cycle_numeric_guidance_packet = _build_unified_numeric_guidance_packet(
      controller_resolution_state=copy.deepcopy(baseline_controller_resolution_state),
      controller_retry_context=copy.deepcopy(controller_retry_context),
      unified_convergence_context=copy.deepcopy(unified_convergence_context),
      quarter_count=_contract_forecast_quarter_count(),
    )
    previous_openai_deadline = _set_active_openai_deadline(
      _bounded_cycle_deadline(cycle_deadline, _PLAN_BUILDER_MAX_SECONDS)
    )
    try:
      _raise_unified_convergence_cycle_timeout_if_needed(
        cycle=unified_convergence_cycle_count,
        cycle_started_at=cycle_started_at,
        stage="plan_builder_start",
        cycle_timing=cycle_timing,
      )
      unified_convergence_plan = _build_unified_convergence_pass_plan(
        draft_id=str(draft_id).strip(),
        business_facts=copy.deepcopy(business_facts or {}),
        planning_mode=planning_mode,
        planning_mode_reason=planning_mode_reason,
        review_decision_payload=copy.deepcopy(unified_convergence_decision),
        solved_model_input_json=copy.deepcopy(final_model_input_json),
        solved_finmo_json=copy.deepcopy(final_finmo_json),
        ops_json=copy.deepcopy(ops_json or {}),
        people_json=copy.deepcopy(people_json or {}),
        financials_json=copy.deepcopy(financials_json or {}),
        financials_year1_json=copy.deepcopy(financials_year1_json or {}),
        marketing_model_json=copy.deepcopy(marketing_model_json or {}),
        numeric_solver_contract=copy.deepcopy((unified_convergence_context or {}).get("numeric_solver_contract") or {}),
        deterministic_numeric_guidance=copy.deepcopy(cycle_numeric_guidance_packet),
        stage_ramp_contract=copy.deepcopy(stage_ramp_contract),
      )
    finally:
      _set_active_openai_deadline(previous_openai_deadline)
    _mark_unified_convergence_cycle_phase(
      cycle_timing=cycle_timing,
      cycle_started_at=cycle_started_at,
      phase_name="plan_builder_and_presolver_validation",
      phase_started_at=phase_started_at,
      detail=str((unified_convergence_plan or {}).get("status") or "").strip(),
    )
    cycle_timing["plan_builder_elapsed_seconds"] = round(time.perf_counter() - cycle_started_at, 3)
    _raise_unified_convergence_cycle_timeout_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="plan_builder",
      detail=str((unified_convergence_plan or {}).get("next_step") or "").strip(),
      cycle_timing=cycle_timing,
    )
    decision_status = str((unified_convergence_decision or {}).get("status") or "").strip()
    plan_status = str((unified_convergence_plan or {}).get("status") or "").strip()
    plan_solver_contract = (
      unified_convergence_plan.get("numeric_solver_contract")
      if isinstance(unified_convergence_plan.get("numeric_solver_contract"), dict)
      else {}
    )
    plan_active_issue_count = int(_safe_float(plan_solver_contract.get("active_issue_count")) or 0)
    candidate_signature = _extract_pass_retry_candidate_signature(unified_convergence_plan)
    validation_error = None
    if decision_status and decision_status != "completed":
      planner_detail = str((unified_convergence_decision or {}).get("detail") or "").strip()
      validation_error = {
        "rejected": True,
        "reason_code": "planner_not_completed",
        "reason": (
          f"Unified convergence planner did not complete successfully: {decision_status}."
          + (f" Detail: {planner_detail}" if planner_detail else "")
        ),
      }
    elif plan_status == "skipped_review_not_completed" and plan_active_issue_count > 0:
      validation_error = {
        "rejected": True,
        "reason_code": "broken_contract_shape",
        "reason": "Planner review did not complete, so target-driven execution cannot start for an active-issue cycle.",
      }
    elif plan_status != "ready" and plan_active_issue_count > 0:
      validation_error = {
        "rejected": True,
        "reason_code": "broken_contract_shape",
        "reason": (
          "Planner did not provide a valid authorized target-and-lever contract for the active-issue cycle. "
          "Unified convergence now requires explicit GPT-authored solver-ready lever controls."
        ),
      }

    if validation_error:
      diagnostics = _pre_solver_validation_failure_diagnostics(
        unified_convergence_plan=copy.deepcopy(unified_convergence_plan),
        validation_error=copy.deepcopy(validation_error),
      )
      diagnostics["solver_invoked"] = False
      diagnostics["cycle"] = int(unified_convergence_cycle_count)
      diagnostics["planner_plan_status"] = str(plan_status or "").strip() or None
      diagnostics["validation_error"] = copy.deepcopy(validation_error)
      diagnostics["timing"] = {
        **copy.deepcopy(cycle_timing),
        "total_elapsed_seconds": round(time.perf_counter() - cycle_started_at, 3),
      }
      critical_payroll_fail_flags = {
        str(item).strip()
        for item in (
          (
            (diagnostics.get("pre_solver_validation") if isinstance(diagnostics.get("pre_solver_validation"), dict) else {})
            .get("flags")
            or []
          )
        )
        if str(item).strip()
      } & _PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS
      if _convergence_test_mode_enabled() and critical_payroll_fail_flags:
        raise StructuredSystemRunFailure(
          detail=_structured_system_run_failure_detail(
            diagnostics=diagnostics,
            fallback="payroll_validation_failed",
          ),
          diagnostics=copy.deepcopy(diagnostics),
        )
      if _convergence_test_mode_enabled():
        raise StructuredSystemRunFailure(
          detail=_structured_system_run_failure_detail(
            diagnostics=diagnostics,
            fallback="solver_not_invoked",
          ),
          diagnostics=copy.deepcopy(diagnostics),
        )
      non_productive_tracker = _update_non_productive_cycle_tracker(
        retry_memory=retry_memory,
        diagnostics=diagnostics,
        controller_resolution_state=baseline_controller_resolution_state,
      )
      progress_failure_diagnostics = _build_convergence_progress_failure_diagnostics(
        cycles_attempted=unified_convergence_cycle_count,
        last_known_state=non_productive_tracker.get("last_known_state"),
        repeated_failure_pattern=non_productive_tracker.get("repeated_failure_pattern"),
        planner_plan_status=plan_status,
      )
      diagnostics["non_productive_cycle_tracker"] = copy.deepcopy(non_productive_tracker)
      progress_failure_diagnostics["validation_error"] = copy.deepcopy(validation_error)
      progress_failure_diagnostics["pre_solver_validation"] = copy.deepcopy(
        diagnostics.get("pre_solver_validation") or {}
      )
      retry_memory["latest_validation_error"] = copy.deepcopy(validation_error)
      retry_memory["recent_validation_errors"] = _bounded_tail(
        list(retry_memory.get("recent_validation_errors") or []) + [
        {
          "attempt_number": unified_convergence_cycle_count,
          "attempt_stage": _controller_retry_stage_for_attempt(unified_convergence_cycle_count),
          "reason_code": str(validation_error.get("reason_code") or "").strip(),
          "reason": str(validation_error.get("reason") or "").strip(),
        }
      ],
        _RETRY_MEMORY_MAX_VALIDATION_ERRORS,
      )
      if (
        _convergence_test_mode_enabled()
        and bool(non_productive_tracker.get("repeated_same_pattern"))
        and isinstance((diagnostics.get("pre_solver_validation") or {}), dict)
        and (
          (diagnostics.get("pre_solver_validation") or {}).get("errors")
          or (diagnostics.get("pre_solver_validation") or {}).get("flags")
        )
      ):
        raise StructuredSystemRunFailure(
          detail="no_meaningful_progress",
          diagnostics=progress_failure_diagnostics,
        )
      if (
        _convergence_test_mode_enabled()
        and int(_safe_float(non_productive_tracker.get("consecutive_non_productive_cycles")) or 0)
        >= _CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT
      ):
        raise StructuredSystemRunFailure(
          detail="no_meaningful_progress",
          diagnostics=progress_failure_diagnostics,
        )
      retry_memory["attempt_records"] = _bounded_tail(
        list(retry_memory.get("attempt_records") or []) + [
        {
          "attempt_number": unified_convergence_cycle_count,
          "attempt_stage": _controller_retry_stage_for_attempt(unified_convergence_cycle_count),
          "status": "rejected_before_solver",
          "controller_retry_context": copy.deepcopy(controller_retry_context),
          "candidate_signature": copy.deepcopy(candidate_signature),
          "rejection": copy.deepcopy(validation_error),
        }
      ],
        _RETRY_MEMORY_MAX_ATTEMPT_RECORDS,
      )
      unified_convergence_result = {
        "contract_version": "unified_convergence_result_v1",
        "status": "retry_rejected_before_solver",
        "target_verification": {
          "controller_state": "retry_required",
          "controller_reason": str(validation_error.get("reason") or "").strip(),
        },
      }
      latest_quality_assessment = {
        "accepted": False,
        "reject_attempt": True,
        "no_progress": True,
      }
      consecutive_no_progress_cycles += 1
      cycle_timing["total_elapsed_seconds"] = round(time.perf_counter() - cycle_started_at, 3)
      unified_convergence_context, hard_rule_assessment = _rebuild_unified_context()
      unified_convergence_iterations.append(
        {
          "cycle": unified_convergence_cycle_count,
          "accepted": False,
          "cycle_timing": copy.deepcopy(cycle_timing),
          "decision": copy.deepcopy(unified_convergence_decision),
          "plan": copy.deepcopy(unified_convergence_plan),
          "result": copy.deepcopy(unified_convergence_result),
          "retry_memory": _compact_retry_memory_snapshot(retry_memory),
          "validation_error": copy.deepcopy(validation_error),
          "controller_resolution_state_before": copy.deepcopy(baseline_controller_resolution_state),
          "controller_resolution_state_after": copy.deepcopy(controller_resolution_state),
        }
      )
      _persist_unified_convergence_state(
        conn=conn,
        draft_id=str(draft_id).strip(),
        stage="convergence_running",
        status="running",
        planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
        controller_resolution_state=copy.deepcopy(controller_resolution_state),
        resolution_summary=copy.deepcopy(resolution_summary),
        planning_mode=planning_mode,
        planning_mode_reason=planning_mode_reason,
        prompt_file=prompt_file,
        grid_application_summary=copy.deepcopy(grid_application_summary or {}),
        realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution),
        realism_memo_json=copy.deepcopy(realism_memo_json),
        unified_convergence_context=copy.deepcopy(unified_convergence_context),
        unified_convergence_decision=copy.deepcopy(unified_convergence_decision),
        unified_convergence_plan=copy.deepcopy(unified_convergence_plan),
        unified_convergence_result=copy.deepcopy(unified_convergence_result),
        unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations),
        unified_convergence_cycle_count=unified_convergence_cycle_count,
        model_input_json=copy.deepcopy(final_model_input_json),
        finmo_json=copy.deepcopy(final_finmo_json),
      )
      _raise_unified_convergence_cycle_timeout_if_needed(
        cycle=unified_convergence_cycle_count,
        cycle_started_at=cycle_started_at,
        stage="pre_solver_validation_failure",
        detail=str(validation_error.get("reason") or validation_error.get("reason_code") or "").strip(),
        cycle_timing=cycle_timing,
      )
      _set_active_openai_deadline(previous_cycle_openai_deadline)
      continue

    _reset_non_productive_cycle_tracker(retry_memory)
    _raise_unified_convergence_stage_budget_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="solver_application_start",
      minimum_remaining_seconds=_CYCLE_DEADLINE_GUARD_SECONDS + 5.0,
      detail="Solver/application cannot start without enough cycle budget to return before the 180s wall.",
      cycle_timing=cycle_timing,
    )
    phase_started_at = time.perf_counter()
    unified_convergence_result = _apply_followup_exact_updates(
      review_plan=copy.deepcopy(unified_convergence_plan),
      current_model_input_json=copy.deepcopy(final_model_input_json),
      contract_version="unified_convergence_result_v1",
      solver_deadline_monotonic=cycle_deadline,
    )
    _mark_unified_convergence_cycle_phase(
      cycle_timing=cycle_timing,
      cycle_started_at=cycle_started_at,
      phase_name="apply_model_input_and_rebuild_finmo",
      phase_started_at=phase_started_at,
      detail=str((unified_convergence_result or {}).get("status") or "").strip(),
    )
    cycle_timing["solver_application_elapsed_seconds"] = round(time.perf_counter() - cycle_started_at, 3)
    _raise_unified_convergence_cycle_timeout_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="solver_application",
      detail=str((unified_convergence_result or {}).get("status") or "").strip(),
      cycle_timing=cycle_timing,
    )
    result_signature = _extract_result_retry_signature(unified_convergence_result)
    previous_result_signature = (
      retry_memory.get("latest_result_signature")
      if isinstance(retry_memory.get("latest_result_signature"), dict)
      else {}
    )
    improvement_summary = _evaluate_retry_improvement(
      previous_result_signature=copy.deepcopy(previous_result_signature),
      current_result_signature=copy.deepcopy(result_signature),
    )
    retry_memory["completed_attempt_count"] = int(unified_convergence_cycle_count)
    retry_memory["prior_lever_unions"] = _bounded_tail(
      list(retry_memory.get("prior_lever_unions") or []) + [
        copy.deepcopy(candidate_signature.get("lever_set_union") or [])
      ],
      _RETRY_MEMORY_MAX_PRIOR_LEVER_UNIONS,
    )
    retry_memory["prior_target_keys"] = _bounded_tail(
      list(retry_memory.get("prior_target_keys") or []) + [
        str(candidate_signature.get("quarter_target_key") or "")
      ],
      _RETRY_MEMORY_MAX_PRIOR_TARGET_KEYS,
    )
    retry_memory["latest_candidate_signature"] = copy.deepcopy(candidate_signature)
    retry_memory["latest_result_signature"] = copy.deepcopy(result_signature)
    retry_memory["latest_improvement_summary"] = copy.deepcopy(improvement_summary)
    retry_memory["latest_validation_error"] = {}
    retry_memory["attempt_records"] = _bounded_tail(
      list(retry_memory.get("attempt_records") or []) + [
      {
        "attempt_number": unified_convergence_cycle_count,
        "attempt_stage": _controller_retry_stage_for_attempt(unified_convergence_cycle_count),
        "status": str(unified_convergence_result.get("status") or "").strip(),
        "controller_retry_context": copy.deepcopy(controller_retry_context),
        "candidate_signature": copy.deepcopy(candidate_signature),
        "result_signature": copy.deepcopy(result_signature),
        "improvement_summary": copy.deepcopy(improvement_summary),
      }
      ],
      _RETRY_MEMORY_MAX_ATTEMPT_RECORDS,
    )
    prior_numeric_feedback = _build_numeric_solver_feedback_payload(copy.deepcopy(unified_convergence_result))
    final_model_input_json = _model_input_with_controller_catalog(
      model_input_json=copy.deepcopy(unified_convergence_result.get("updated_model_input_json") or {}),
      catalog_source_model_input_json=copy.deepcopy(catalog_source_model_input_json or {}),
    )
    final_finmo_json = copy.deepcopy(unified_convergence_result.get("updated_finmo_json") or {})

    post_solver_business_world_contract = _business_world_contract(
      business_facts=copy.deepcopy(business_facts or {}),
      ops_json=copy.deepcopy(ops_json or {}),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      stage_ramp_contract=copy.deepcopy(stage_ramp_contract)
      if isinstance(stage_ramp_contract, dict)
      else None,
    )
    post_solver_payroll_validation = _validate_payroll_headcount_contract(
      model_input_json=copy.deepcopy(final_model_input_json or {}),
      business_world_contract=copy.deepcopy(post_solver_business_world_contract),
    )
    post_solver_payroll_errors = [
      copy.deepcopy(item)
      for item in (post_solver_payroll_validation.get("details") or [])
      if isinstance(item, dict)
    ]
    if post_solver_payroll_errors:
      first_payroll_error = post_solver_payroll_errors[0]
      diagnostics = {
        "failure_stage": "post_solver_validation",
        "failure_reason": str(first_payroll_error.get("error") or "").strip() or "payroll_validation_failed",
        "lever": "expenses::Payroll",
        "solver_invoked": True,
        "cycle": int(unified_convergence_cycle_count),
        "timing": {
          **copy.deepcopy(cycle_timing),
          "total_elapsed_seconds": round(time.perf_counter() - cycle_started_at, 3),
        },
        "validation_context": {
          "convergence_test_mode": _convergence_test_mode_enabled(),
          "planner_plan_status": str(plan_status or "").strip() or None,
          "focus_issue_codes": copy.deepcopy(controller_retry_context.get("focus_issue_codes") or []),
          "lever_selection": copy.deepcopy((unified_convergence_plan or {}).get("lever_selection") or []),
          "payroll_headcount_validation": copy.deepcopy(post_solver_payroll_validation),
          "numeric_solver_result": copy.deepcopy(unified_convergence_result.get("numeric_solver_result") or {}),
          "target_verification": copy.deepcopy(unified_convergence_result.get("target_verification") or {}),
        },
        "pre_solver_validation": {
          "stage": "post_solver_validation",
          "status": "failed",
          "flags": list(
            dict.fromkeys(
              [
                "payroll_headcount_failed",
                *[
                  str(item.get("error") or "").strip()
                  for item in post_solver_payroll_errors
                  if str(item.get("error") or "").strip()
                ],
              ]
            )
          ),
          "errors": copy.deepcopy(post_solver_payroll_errors),
        },
      }
      unified_convergence_result["post_solver_validation"] = copy.deepcopy(diagnostics)
      raise StructuredSystemRunFailure(
        detail=_structured_system_run_failure_detail(
          diagnostics=diagnostics,
          fallback="payroll_validation_failed",
        ),
        diagnostics=diagnostics,
      )

    target_miss_count = int(_safe_float(unified_convergence_result.get("quarters_with_target_misses")) or 0)
    result_status_text = str(unified_convergence_result.get("status") or "").strip().lower()
    if _convergence_test_mode_enabled() and (
      target_miss_count > 0 or "target_miss" in result_status_text
    ):
      diagnostics = {
        "failure_stage": "post_solver_validation",
        "failure_reason": "solver_target_miss_before_verification",
        "solver_invoked": True,
        "cycle": int(unified_convergence_cycle_count),
        "timing": {
          **copy.deepcopy(cycle_timing),
          "total_elapsed_seconds": round(time.perf_counter() - cycle_started_at, 3),
        },
        "validation_error": {
          "rejected": True,
          "reason_code": "solver_target_miss_before_verification",
          "reason": (
            "Numeric solver did not meet the GPT-authored target contract, "
            "so OpenAI verification was skipped to preserve the cycle time invariant."
          ),
        },
        "pre_solver_validation": {
          "stage": "post_solver_validation",
          "status": "failed",
          "flags": ["solver_target_miss_before_verification"],
          "errors": [
            {
              "error": "solver_target_miss_before_verification",
              "reason": "Solver target misses must be fixed before realism verification is invoked.",
              "target_metric_names": copy.deepcopy(unified_convergence_result.get("target_metric_names") or []),
              "targeted_quarters": copy.deepcopy(unified_convergence_result.get("targeted_quarters") or []),
              "quarter_fit_summary": copy.deepcopy(unified_convergence_result.get("quarter_fit_summary") or []),
            }
          ],
        },
        "numeric_solver_result": copy.deepcopy(unified_convergence_result.get("numeric_solver_result") or {}),
        "target_verification": copy.deepcopy(unified_convergence_result.get("target_verification") or {}),
        "result_summary": {
          "status": str(unified_convergence_result.get("status") or "").strip(),
          "quarters_with_target_misses": target_miss_count,
          "quarters_with_all_targets_within_tolerance": int(
            _safe_float(unified_convergence_result.get("quarters_with_all_targets_within_tolerance")) or 0
          ),
          "quarter_fit_summary": copy.deepcopy(unified_convergence_result.get("quarter_fit_summary") or []),
        },
      }
      raise StructuredSystemRunFailure(
        detail=_structured_system_run_failure_detail(
          diagnostics=diagnostics,
          fallback="solver_target_miss_before_verification",
        ),
        diagnostics=diagnostics,
      )

    next_iteration = max(
      1,
      int(_safe_float(baseline_controller_resolution_state.get("last_review_iteration")) or 0) + 1,
    )
    verification_numeric_solver_contract = copy.deepcopy(
      (unified_convergence_decision or {}).get("numeric_solver_contract")
      if isinstance((unified_convergence_decision or {}).get("numeric_solver_contract"), dict)
      else (unified_convergence_plan or {}).get("numeric_solver_contract")
      if isinstance((unified_convergence_plan or {}).get("numeric_solver_contract"), dict)
      else (unified_convergence_context or {}).get("numeric_solver_contract")
      if isinstance((unified_convergence_context or {}).get("numeric_solver_contract"), dict)
      else {}
    )
    verification_issue_packets = _build_issue_packets_from_issue_ledger(
      issue_status_records=copy.deepcopy(baseline_issue_ledger),
      numeric_solver_contract=copy.deepcopy(verification_numeric_solver_contract),
      prior_decision_payload=copy.deepcopy(unified_convergence_decision or {}),
      current_finmo_json=copy.deepcopy(final_finmo_json),
    )
    verification_allowed_issue_keys = [
      _issue_ledger_key(item)
      for item in (baseline_issue_ledger or [])
      if isinstance(item, dict) and _issue_ledger_key(item)
    ]
    realism_pass_consistency_context = _build_realism_pass_consistency_context_payload(
      phase="unified_convergence",
      prior_issue_status_records=copy.deepcopy(baseline_issue_ledger),
      baseline_model_input_json=copy.deepcopy(baseline_model_input_json),
      baseline_finmo_json=copy.deepcopy(baseline_finmo_json),
      result_payload=copy.deepcopy(unified_convergence_result),
    )
    _raise_unified_convergence_stage_budget_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="verification_start",
      minimum_remaining_seconds=45.0,
      detail=str((unified_convergence_result or {}).get("status") or "").strip(),
      cycle_timing=cycle_timing,
    )
    phase_started_at = time.perf_counter()
    previous_openai_deadline = _set_active_openai_deadline(
      _bounded_cycle_deadline(cycle_deadline, _VERIFICATION_GPT_MAX_SECONDS)
    )
    try:
      unified_convergence_verification = _run_realism_verification_openai(
        draft_id=str(draft_id).strip(),
        business_facts=copy.deepcopy(business_facts or {}),
        ops_json=copy.deepcopy(ops_json or {}),
        planning_mode=planning_mode,
        planning_mode_reason=planning_mode_reason,
        planning_mode_prompt_file=prompt_file,
        protected_resolved_issue_constraints=copy.deepcopy(protected_resolved_issue_constraints),
        realism_pass_consistency_context=copy.deepcopy(realism_pass_consistency_context),
        realism_memo_before_resolution=copy.deepcopy(baseline_realism_memo_json),
        unified_convergence_decision={
          "decision": {
            "issue_packets": copy.deepcopy(verification_issue_packets),
          },
          "deterministic_issue_packets": copy.deepcopy(verification_issue_packets),
        },
        unified_convergence_plan={
          "issue_packets": copy.deepcopy(verification_issue_packets),
          "strategy_class": str((unified_convergence_plan or {}).get("strategy_class") or "").strip(),
          "change_type": str((unified_convergence_plan or {}).get("change_type") or "").strip(),
          "progress_expectation": str((unified_convergence_plan or {}).get("progress_expectation") or "").strip(),
          "strategy_rationale": str((unified_convergence_plan or {}).get("strategy_rationale") or "").strip(),
          "retry_reason": str((unified_convergence_plan or {}).get("retry_reason") or "").strip(),
          "lever_selection": copy.deepcopy((unified_convergence_plan or {}).get("lever_selection") or []),
          "target_tolerances": copy.deepcopy((unified_convergence_plan or {}).get("target_tolerances") or []),
          "targets_by_quarter": copy.deepcopy((unified_convergence_plan or {}).get("targets_by_quarter") or []),
          "translated_action_packages": copy.deepcopy((unified_convergence_plan or {}).get("translated_action_packages") or []),
        },
        unified_convergence_result=copy.deepcopy(unified_convergence_result),
        updated_model_input_json=copy.deepcopy(final_model_input_json),
        updated_finmo_json=copy.deepcopy(final_finmo_json),
      )
    finally:
      _set_active_openai_deadline(previous_openai_deadline)
    _mark_unified_convergence_cycle_phase(
      cycle_timing=cycle_timing,
      cycle_started_at=cycle_started_at,
      phase_name="verification_gpt_and_rescan",
      phase_started_at=phase_started_at,
      detail=str((unified_convergence_verification or {}).get("status") or "").strip(),
    )
    cycle_timing["verification_elapsed_seconds"] = round(time.perf_counter() - cycle_started_at, 3)
    _raise_unified_convergence_cycle_timeout_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="verification",
      detail=str((unified_convergence_verification or {}).get("detail") or "").strip(),
      cycle_timing=cycle_timing,
    )
    unified_convergence_result["verification"] = copy.deepcopy(unified_convergence_verification)
    verification_status = str((unified_convergence_verification or {}).get("status") or "").strip()
    if verification_status == "completed":
      verified_issue_ledger = _apply_realism_verification_to_issue_status_records(
        issue_status_records=copy.deepcopy(baseline_issue_ledger),
        verification_payload=copy.deepcopy(unified_convergence_verification),
        iteration=next_iteration,
        allowed_issue_keys=copy.deepcopy(verification_allowed_issue_keys),
        allow_new_records=False,
      )
      scan_memo = {
        "contract_version": "post_intake_deterministic_issue_detection_v1",
        "status": "ready",
        "source_of_truth": "deterministic_table_backed_issue_detectors",
        "issues": [],
        "remaining_issues": [],
      }
      capacity_support_scan_issue_set = _build_capacity_support_issue_status_records(
        finmo_json=copy.deepcopy(final_finmo_json),
        iteration=next_iteration,
      )
      flatline_scan_issue_set = _build_p_and_l_flatline_issue_status_records(
        model_input_json=copy.deepcopy(final_model_input_json),
        finmo_json=copy.deepcopy(final_finmo_json),
        iteration=next_iteration,
      )
      stage_maturity_scan_issue_set = _build_stage_maturity_cost_structure_issue_status_records(
        model_input_json=copy.deepcopy(final_model_input_json),
        finmo_json=copy.deepcopy(final_finmo_json),
        stage_ramp_contract=copy.deepcopy(stage_ramp_contract),
        iteration=next_iteration,
      )
      scan_issue_set = _refresh_issue_status_records_from_scan(
        existing_issue_status_records=[],
        scanned_issue_status_records=(
          copy.deepcopy(capacity_support_scan_issue_set)
          + copy.deepcopy(flatline_scan_issue_set)
          + copy.deepcopy(stage_maturity_scan_issue_set)
        ),
        iteration=next_iteration,
      )
      realism_issue_ledger = _merge_new_scan_detected_issues(
        existing_issue_status_records=copy.deepcopy(verified_issue_ledger),
        scanned_issue_status_records=copy.deepcopy(scan_issue_set),
        iteration=next_iteration,
      )
      resolution_summary = _build_resolution_summary_from_issue_ledger(
        before_memo=copy.deepcopy(scan_memo),
        issue_status_records=copy.deepcopy(realism_issue_ledger),
      )
      realism_memo_json = _build_realism_memo_from_issue_ledger(
        before_memo=copy.deepcopy(scan_memo),
        issue_status_records=copy.deepcopy(realism_issue_ledger),
        resolution_summary=copy.deepcopy(resolution_summary),
        iteration=next_iteration,
      )
      controller_resolution_state = _build_controller_resolution_state_from_issue_ledger(
        issue_status_records=copy.deepcopy(realism_issue_ledger),
        iteration=next_iteration,
        current_finmo_json=copy.deepcopy(final_finmo_json),
      )
      protected_resolved_issue_constraints = _build_strategy_resolved_issue_constraints(
        copy.deepcopy(realism_issue_ledger)
      )
      unified_convergence_context, after_hard_rule_assessment = _rebuild_unified_context()
      quality_assessment = _build_unified_cycle_quality_assessment(
        before_controller_resolution_state=copy.deepcopy(baseline_controller_resolution_state),
        before_hard_rule_assessment=copy.deepcopy(hard_rule_assessment_before),
        after_controller_resolution_state=copy.deepcopy(controller_resolution_state),
        after_hard_rule_assessment=copy.deepcopy(after_hard_rule_assessment),
        before_finmo_json=copy.deepcopy(baseline_finmo_json),
        after_finmo_json=copy.deepcopy(final_finmo_json),
        result_payload=copy.deepcopy(unified_convergence_result),
        before_numeric_guidance_packet=copy.deepcopy(cycle_numeric_guidance_packet),
        candidate_signature=copy.deepcopy(candidate_signature),
        prior_quality_assessment=copy.deepcopy(latest_quality_assessment),
      )
    else:
      after_hard_rule_assessment = copy.deepcopy(hard_rule_assessment_before)
      quality_assessment = {
        "accepted": False,
        "reject_attempt": True,
        "no_progress": True,
        "verification_failed": True,
        "verification_status": verification_status,
        "verification_detail": str((unified_convergence_verification or {}).get("detail") or "").strip(),
        "remaining_issue_count_before": int(_safe_float(baseline_controller_resolution_state.get("remaining_issue_count")) or 0),
        "remaining_issue_count_after": int(_safe_float(baseline_controller_resolution_state.get("remaining_issue_count")) or 0),
        "resolved_issue_count_before": int(_safe_float(baseline_controller_resolution_state.get("resolved_issue_count")) or 0),
        "resolved_issue_count_after": int(_safe_float(baseline_controller_resolution_state.get("resolved_issue_count")) or 0),
        "open_issue_codes_before": copy.deepcopy(
          [
            str(item.get("issue_code") or "").strip().lower()
            for item in (baseline_controller_resolution_state.get("remaining_issues") or [])
            if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
          ]
        ),
        "open_issue_codes_after": copy.deepcopy(
          [
            str(item.get("issue_code") or "").strip().lower()
            for item in (baseline_controller_resolution_state.get("remaining_issues") or [])
            if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
          ]
        ),
      }
    accepted_attempt = bool(quality_assessment.get("accepted"))
    latest_quality_assessment = copy.deepcopy(quality_assessment)
    if accepted_attempt:
      retry_memory["prior_controller_state_summary"] = copy.deepcopy(
        retry_memory.get("latest_controller_state_summary") or {}
      )
      retry_memory["latest_controller_state_summary"] = {
        "overall_completion_score_pct": int(_safe_float(controller_resolution_state.get("overall_completion_score_pct")) or 0),
        "overall_completion_grade": str(controller_resolution_state.get("overall_completion_grade") or "").strip() or "D",
        "lowest_quarter_score_pct": int(_safe_float(controller_resolution_state.get("lowest_quarter_score_pct")) or 0),
        "remaining_issue_count": int(_safe_float(controller_resolution_state.get("remaining_issue_count")) or 0),
        "resolved_issue_count": int(_safe_float(controller_resolution_state.get("resolved_issue_count")) or 0),
        "tolerated_issue_count": int(_safe_float(controller_resolution_state.get("tolerated_issue_count")) or 0),
      }
      hard_rule_assessment = copy.deepcopy(after_hard_rule_assessment)
      if bool(controller_resolution_state.get("all_cleared")) or bool(quality_assessment.get("meaningful_progress")):
        consecutive_no_progress_cycles = 0
      else:
        consecutive_no_progress_cycles += 1
    else:
      final_model_input_json = copy.deepcopy(baseline_model_input_json)
      final_finmo_json = copy.deepcopy(baseline_finmo_json)
      realism_issue_ledger = copy.deepcopy(baseline_issue_ledger)
      controller_resolution_state = copy.deepcopy(baseline_controller_resolution_state)
      realism_memo_json = copy.deepcopy(baseline_realism_memo_json)
      resolution_summary = copy.deepcopy(baseline_resolution_summary)
      unified_convergence_context, hard_rule_assessment = _rebuild_unified_context()
      consecutive_no_progress_cycles += 1
    unified_convergence_context["cycle_stall_assessment"] = _build_unified_cycle_stall_assessment(
      consecutive_no_progress_cycles=consecutive_no_progress_cycles,
      latest_quality_assessment=latest_quality_assessment,
    )
    unified_convergence_iterations.append(
      {
        "cycle": unified_convergence_cycle_count,
        "accepted": accepted_attempt,
        "cycle_timing": {
          **copy.deepcopy(cycle_timing),
          "total_elapsed_seconds": round(time.perf_counter() - cycle_started_at, 3),
        },
        "stall_assessment_before": copy.deepcopy(stall_assessment),
        "quality_assessment": copy.deepcopy(quality_assessment),
        "hard_rule_assessment_before": copy.deepcopy(hard_rule_assessment_before),
        "hard_rule_assessment_after": copy.deepcopy(hard_rule_assessment),
        "decision": copy.deepcopy(unified_convergence_decision),
        "plan": copy.deepcopy(unified_convergence_plan),
        "result": copy.deepcopy(unified_convergence_result),
        "retry_memory": _compact_retry_memory_snapshot(retry_memory),
        "controller_resolution_state_before": copy.deepcopy(baseline_controller_resolution_state),
        "controller_resolution_state_after": copy.deepcopy(controller_resolution_state),
      }
    )
    _persist_unified_convergence_state(
      conn=conn,
      draft_id=str(draft_id).strip(),
      stage="convergence_running",
      status="running",
      planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
      controller_resolution_state=copy.deepcopy(controller_resolution_state),
      resolution_summary=copy.deepcopy(resolution_summary),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution),
      realism_memo_json=copy.deepcopy(realism_memo_json),
      unified_convergence_context=copy.deepcopy(unified_convergence_context),
      unified_convergence_decision=copy.deepcopy(unified_convergence_decision),
      unified_convergence_plan=copy.deepcopy(unified_convergence_plan),
      unified_convergence_result=copy.deepcopy(unified_convergence_result),
      unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations),
      unified_convergence_cycle_count=unified_convergence_cycle_count,
      model_input_json=copy.deepcopy(final_model_input_json),
      finmo_json=copy.deepcopy(final_finmo_json),
    )
    if (
      _convergence_test_mode_enabled()
      and int(consecutive_no_progress_cycles or 0) >= _CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT
      and not bool(quality_assessment.get("meaningful_progress"))
      and not bool(controller_resolution_state.get("all_cleared"))
    ):
      raise StructuredSystemRunFailure(
        detail="no_meaningful_progress",
        diagnostics=_build_convergence_progress_failure_diagnostics(
          cycles_attempted=unified_convergence_cycle_count,
          last_known_state={
            "remaining_issue_count": int(_safe_float(controller_resolution_state.get("remaining_issue_count")) or 0),
            "resolved_issue_count": int(_safe_float(controller_resolution_state.get("resolved_issue_count")) or 0),
            "tolerated_issue_count": int(_safe_float(controller_resolution_state.get("tolerated_issue_count")) or 0),
          },
          repeated_failure_pattern={
            "planner_status": plan_status,
            "solver_invoked": bool(unified_convergence_result.get("solver_invoked")),
            "invalid_levers": [],
            "pre_solver_validation_flags": copy.deepcopy(
              (
                (unified_convergence_plan.get("pre_solver_validation") if isinstance(unified_convergence_plan.get("pre_solver_validation"), dict) else {})
                .get("flags")
                or []
              )
            ),
          },
          planner_plan_status=plan_status,
        ),
      )
    _raise_unified_convergence_cycle_timeout_if_needed(
      cycle=unified_convergence_cycle_count,
      cycle_started_at=cycle_started_at,
      stage="cycle_complete",
      detail=str((quality_assessment or {}).get("status") or "").strip(),
      cycle_timing=cycle_timing,
    )
    _set_active_openai_deadline(previous_cycle_openai_deadline)
    _handle_convergence_test_mode_failure(quality_assessment)

  # Convergence-cycle deadlines must not leak into the post-convergence cash
  # phase. Cash has its own validation/fail-fast gates; inheriting the last
  # cycle's nearly expired OpenAI deadline turns a cleared convergence run into
  # a false terminal timeout.
  _set_active_openai_deadline(None)

  pre_cash_model_input_json = copy.deepcopy(final_model_input_json)
  pre_cash_finmo_json = copy.deepcopy(final_finmo_json)
  pre_cash_issue_ledger = copy.deepcopy(realism_issue_ledger)
  pre_cash_resolution_summary = copy.deepcopy(resolution_summary)
  pre_cash_realism_memo_json = copy.deepcopy(realism_memo_json)
  pre_cash_controller_resolution_state = copy.deepcopy(controller_resolution_state)
  pre_cash_hard_rule_assessment = copy.deepcopy(hard_rule_assessment)
  process_sequence_trace["cash_minimum_debt_schedule"] = post_intake_process_step_context(
    step_key="cash_minimum_debt_schedule",
    expected_phase="cash_pass",
    expected_handler_key="apply_cash_pass_minimum_debt_schedule",
    required_lookup_tables=["post_intake_cash_policy_lookup", "post_intak_mapping_lookup"],
    required_horizon_rule="q1_to_q20_debt_schedule",
  )
  process_sequence_trace["cash_strategy_review"] = post_intake_process_step_context(
    step_key="cash_strategy_review",
    expected_phase="cash_pass",
    expected_handler_key="run_cash_strategy_review",
    required_contract_name="cash_strategy_review",
    required_context_contract_name="cash_strategy_review",
    required_context_include_phase="cash_pass",
    required_lookup_tables=[
      "post_intake_cash_policy_lookup",
      "post_intak_mapping_lookup",
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
    ],
    required_horizon_rule="cash_gap_rows_subset_validation_all_q1_to_q20",
  )
  process_sequence_trace["cash_pass_validation"] = post_intake_process_step_context(
    step_key="cash_pass_validation",
    expected_phase="cash_pass",
    expected_handler_key="validate_cash_pass",
    required_lookup_tables=["post_intake_cash_policy_lookup", "post_intak_mapping_lookup"],
    required_horizon_rule="validate_all_q1_to_q20",
  )
  cash_pass_phase_contract = _cash_pass_phase_contract(financials_json=copy.deepcopy(financials_json or {}))
  cash_pass_phase_trace = _new_cash_pass_phase_trace(cash_pass_phase_contract)
  pre_cash_debt_schedule_seed = _apply_cash_pass_minimum_debt_schedule(
    cash_strategy_result={
      "updated_model_input_json": copy.deepcopy(pre_cash_model_input_json),
      "updated_finmo_json": copy.deepcopy(pre_cash_finmo_json),
      "applied_updates": [],
    },
    financials_json=copy.deepcopy(financials_json or {}),
  )
  pre_cash_model_input_json = copy.deepcopy(
    pre_cash_debt_schedule_seed.get("updated_model_input_json")
    if isinstance(pre_cash_debt_schedule_seed.get("updated_model_input_json"), dict)
    else pre_cash_model_input_json
  )
  pre_cash_finmo_json = copy.deepcopy(
    pre_cash_debt_schedule_seed.get("updated_finmo_json")
    if isinstance(pre_cash_debt_schedule_seed.get("updated_finmo_json"), dict)
    else pre_cash_finmo_json
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_debt_schedule_seed",
    model_input_json=copy.deepcopy(pre_cash_model_input_json),
    finmo_json=copy.deepcopy(pre_cash_finmo_json),
    detail="Applied SQL cash-policy minimum debt schedule before cash review context.",
  )
  pre_cash_debt_semantics_seed = _apply_cash_pass_short_term_debt_current_portion(
    cash_strategy_result={
      "updated_model_input_json": copy.deepcopy(pre_cash_model_input_json),
      "updated_finmo_json": copy.deepcopy(pre_cash_finmo_json),
      "applied_updates": copy.deepcopy(pre_cash_debt_schedule_seed.get("applied_updates") or []),
    }
  )
  pre_cash_model_input_json = copy.deepcopy(
    pre_cash_debt_semantics_seed.get("updated_model_input_json")
    if isinstance(pre_cash_debt_semantics_seed.get("updated_model_input_json"), dict)
    else pre_cash_model_input_json
  )
  pre_cash_finmo_json = copy.deepcopy(
    pre_cash_debt_semantics_seed.get("updated_finmo_json")
    if isinstance(pre_cash_debt_semantics_seed.get("updated_finmo_json"), dict)
    else pre_cash_finmo_json
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_short_term_debt_seed",
    model_input_json=copy.deepcopy(pre_cash_model_input_json),
    finmo_json=copy.deepcopy(pre_cash_finmo_json),
    detail="Applied current portion debt seed before cash review context.",
  )

  def _persist_cash_pass_stage(
    *,
    stage: str,
    status: str = "running",
    cash_controller_resolution_state: Optional[Dict[str, Any]] = None,
    cash_strategy_review_context_payload: Optional[Dict[str, Any]] = None,
    cash_strategy_review_decision_payload: Optional[Dict[str, Any]] = None,
    cash_strategy_second_pass_plan_payload: Optional[Dict[str, Any]] = None,
    cash_strategy_second_pass_result_payload: Optional[Dict[str, Any]] = None,
    model_input_payload: Optional[Dict[str, Any]] = None,
    finmo_payload: Optional[Dict[str, Any]] = None,
  ) -> None:
    _persist_unified_convergence_state(
      conn=conn,
      draft_id=str(draft_id).strip(),
      stage=stage,
      status=status,
      planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
      controller_resolution_state=copy.deepcopy(cash_controller_resolution_state or pre_cash_controller_resolution_state or {}),
      resolution_summary=copy.deepcopy(pre_cash_resolution_summary or {}),
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
      grid_application_summary=copy.deepcopy(grid_application_summary or {}),
      realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution),
      realism_memo_json=copy.deepcopy(pre_cash_realism_memo_json or {}),
      cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context_payload or {}),
      cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision_payload or {}),
      cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan_payload or {}),
      cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result_payload or {}),
      unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
      unified_convergence_decision=copy.deepcopy(unified_convergence_decision or {}),
      unified_convergence_plan=copy.deepcopy(unified_convergence_plan or {}),
      unified_convergence_result=copy.deepcopy(unified_convergence_result or {}),
      unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations),
      unified_convergence_cycle_count=unified_convergence_cycle_count,
      model_input_json=copy.deepcopy(model_input_payload or pre_cash_model_input_json or {}),
      finmo_json=copy.deepcopy(finmo_payload or pre_cash_finmo_json or {}),
    )

  cash_strategy_review_context = _build_cash_strategy_review_context_payload(
    draft_id=str(draft_id).strip(),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    solved_model_input_json=copy.deepcopy(pre_cash_model_input_json),
    solved_finmo_json=copy.deepcopy(pre_cash_finmo_json),
    controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
    prior_numeric_feedback=copy.deepcopy(prior_numeric_feedback),
  )
  cash_strategy_review_context["cash_pass_phase_contract"] = copy.deepcopy(cash_pass_phase_contract)
  cash_strategy_review_context["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_review_context_build",
    model_input_json=copy.deepcopy(pre_cash_model_input_json),
    finmo_json=copy.deepcopy(pre_cash_finmo_json),
    detail="Built full 20Q cash strategy review context from SQL cash policy and mapping lookups.",
  )
  cash_strategy_review_context["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_pass_review_controller_state = _build_cash_pass_controller_resolution_state(
    phase="cash_pass_review_running",
    base_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
  )
  _persist_cash_pass_stage(
    stage="cash_pass_review_running",
    cash_controller_resolution_state=copy.deepcopy(cash_pass_review_controller_state),
    cash_strategy_review_context_payload=copy.deepcopy(cash_strategy_review_context),
  )
  cash_strategy_review_decision = _run_cash_strategy_review_openai(
    draft_id=str(draft_id).strip(),
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_mode_prompt_file=prompt_file,
    first_pass_handoff={},
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    solved_model_input_json=copy.deepcopy(pre_cash_model_input_json),
    solved_finmo_json=copy.deepcopy(pre_cash_finmo_json),
    prior_numeric_feedback=copy.deepcopy(prior_numeric_feedback),
    controller_retry_context={},
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_gpt_review",
    detail="Cash strategy GPT review returned a response for the SQL contract-backed grid.",
  )
  cash_strategy_review_context["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  if isinstance(cash_strategy_review_decision, dict):
    cash_strategy_review_decision["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_review_failure_flags = _cash_strategy_fail_flags_from_review_payload(cash_strategy_review_decision)
  review_payload_with_context = copy.deepcopy(cash_strategy_review_decision)
  review_payload_with_context["cash_strategy_review_context"] = copy.deepcopy(cash_strategy_review_context)
  review_payload_with_context["numeric_solver_contract"] = copy.deepcopy(
    cash_strategy_review_context.get("numeric_solver_contract")
    if isinstance(cash_strategy_review_context.get("numeric_solver_contract"), dict)
    else {}
  )
  if cash_review_failure_flags:
    cash_pass_failed_controller_state = _build_cash_pass_controller_resolution_state(
      phase="cash_pass_failed",
      base_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
      cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
      cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
    )
    _persist_cash_pass_stage(
      stage="cash_pass_failed",
      status="failed",
      cash_controller_resolution_state=copy.deepcopy(cash_pass_failed_controller_state),
      cash_strategy_review_context_payload=copy.deepcopy(cash_strategy_review_context),
      cash_strategy_review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
    )
    _handle_cash_strategy_test_mode_failure(
      _build_cash_strategy_test_failure_payload(
        review_payload=copy.deepcopy(cash_strategy_review_decision),
        before_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
        after_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
        extra_flags=copy.deepcopy(cash_review_failure_flags),
        detail=str(cash_strategy_review_decision.get("detail") or "").strip() or "cash_strategy_review_failed",
      )
    )
  cash_pass_plan_controller_state = _build_cash_pass_controller_resolution_state(
    phase="cash_pass_plan_running",
    base_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
  )
  _persist_cash_pass_stage(
    stage="cash_pass_plan_running",
    cash_controller_resolution_state=copy.deepcopy(cash_pass_plan_controller_state),
    cash_strategy_review_context_payload=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
  )
  cash_strategy_second_pass_plan = _build_cash_strategy_second_pass_plan(
    review_decision_payload=copy.deepcopy(review_payload_with_context),
    solved_model_input_json=copy.deepcopy(pre_cash_model_input_json),
    financials_json=copy.deepcopy(financials_json or {}),
    numeric_solver_contract=copy.deepcopy(
      cash_strategy_review_context.get("numeric_solver_contract")
      if isinstance(cash_strategy_review_context.get("numeric_solver_contract"), dict)
      else {}
    ),
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_translation_plan",
    detail="Translated cash GPT decision into exact mapped model-input update plan.",
  )
  cash_strategy_second_pass_plan["cash_pass_phase_contract"] = copy.deepcopy(cash_pass_phase_contract)
  cash_strategy_second_pass_plan["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_plan_fail_flags = [
    str(item).strip()
    for item in (cash_strategy_second_pass_plan.get("translation_fail_flags") or [])
    if str(item).strip() in _CASH_STRATEGY_TEST_MODE_FAIL_FLAGS
  ]
  if cash_plan_fail_flags:
    cash_pass_failed_controller_state = _build_cash_pass_controller_resolution_state(
      phase="cash_pass_failed",
      base_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
      cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
      cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
      cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    )
    _persist_cash_pass_stage(
      stage="cash_pass_failed",
      status="failed",
      cash_controller_resolution_state=copy.deepcopy(cash_pass_failed_controller_state),
      cash_strategy_review_context_payload=copy.deepcopy(cash_strategy_review_context),
      cash_strategy_review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
      cash_strategy_second_pass_plan_payload=copy.deepcopy(cash_strategy_second_pass_plan),
    )
    _handle_cash_strategy_test_mode_failure(
      _build_cash_strategy_test_failure_payload(
        review_payload=copy.deepcopy(cash_strategy_review_decision),
        plan_payload=copy.deepcopy(cash_strategy_second_pass_plan),
        before_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
        after_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
        extra_flags=copy.deepcopy(cash_plan_fail_flags),
        detail="cash_strategy_second_pass_plan_failed",
      )
    )
  cash_pass_application_controller_state = _build_cash_pass_controller_resolution_state(
    phase="cash_pass_application_running",
    base_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
  )
  _persist_cash_pass_stage(
    stage="cash_pass_application_running",
    cash_controller_resolution_state=copy.deepcopy(cash_pass_application_controller_state),
    cash_strategy_review_context_payload=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
    cash_strategy_second_pass_plan_payload=copy.deepcopy(cash_strategy_second_pass_plan),
  )
  cash_strategy_second_pass_result = _apply_cash_strategy_exact_updates(
    review_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    current_model_input_json=copy.deepcopy(pre_cash_model_input_json),
    current_finmo_json=copy.deepcopy(pre_cash_finmo_json),
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_apply_exact_updates",
    model_input_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {}),
    finmo_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {}),
    detail="Applied cash strategy exact updates and rebuilt FINMO.",
  )
  cash_strategy_second_pass_result["cash_pass_phase_contract"] = copy.deepcopy(cash_pass_phase_contract)
  cash_strategy_second_pass_result["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_strategy_second_pass_result = _apply_cash_pass_minimum_debt_schedule(
    cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result),
    financials_json=copy.deepcopy(financials_json or {}),
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_debt_schedule_rebuild",
    model_input_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {}),
    finmo_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {}),
    detail="Reapplied SQL cash-policy minimum debt schedule floor after cash strategy updates.",
  )
  cash_strategy_second_pass_result["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_strategy_second_pass_result = _apply_cash_pass_short_term_debt_current_portion(
    cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result)
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_short_term_debt_current_portion",
    model_input_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {}),
    finmo_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {}),
    detail="Applied post-cash current portion debt semantics and rebuilt FINMO.",
  )
  cash_strategy_second_pass_result["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_strategy_second_pass_result = _apply_cash_policy_surplus_cleanup(
    cash_strategy_result=copy.deepcopy(cash_strategy_second_pass_result),
    financials_json=copy.deepcopy(financials_json or {}),
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_surplus_cleanup",
    model_input_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {}),
    finmo_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {}),
    detail="Applied deterministic SQL cash policy surplus cleanup and rebuilt FINMO.",
  )
  cash_strategy_second_pass_result["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_validation_iteration = max(
    int(_safe_float(pre_cash_controller_resolution_state.get("last_review_iteration")) or unified_convergence_cycle_count),
    unified_convergence_cycle_count,
  ) + 1
  cash_post_validation = _validate_cash_strategy_post_pass(
    ops_json=copy.deepcopy(ops_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    baseline_issue_ledger=copy.deepcopy(pre_cash_issue_ledger),
    candidate_model_input_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {}),
    candidate_finmo_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {}),
    iteration=cash_validation_iteration,
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_post_validation",
    model_input_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {}),
    finmo_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {}),
    detail="Ran cash post-pass validation against the post-action state.",
  )
  cash_strategy_second_pass_result["post_validation"] = copy.deepcopy(cash_post_validation)
  cash_strategy_second_pass_result["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  cash_pass_validation_controller_state = _build_cash_pass_controller_resolution_state(
    phase="cash_pass_validation_running",
    base_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
    cash_post_validation=copy.deepcopy(cash_post_validation),
  )
  _persist_cash_pass_stage(
    stage="cash_pass_validation_running",
    cash_controller_resolution_state=copy.deepcopy(cash_pass_validation_controller_state),
    cash_strategy_review_context_payload=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
    cash_strategy_second_pass_plan_payload=copy.deepcopy(cash_strategy_second_pass_plan),
    cash_strategy_second_pass_result_payload=copy.deepcopy(cash_strategy_second_pass_result),
    model_input_payload=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or pre_cash_model_input_json),
    finmo_payload=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or pre_cash_finmo_json),
  )
  post_validation_fail_flags = [
    str(item).strip()
    for item in (cash_post_validation.get("failed_rule_codes") or [])
    if str(item).strip() in _CASH_STRATEGY_TEST_MODE_FAIL_FLAGS
  ]
  if post_validation_fail_flags:
    cash_strategy_second_pass_result["fail_flags"] = list(
      dict.fromkeys(
        [
          *[
            str(item).strip()
            for item in (cash_strategy_second_pass_result.get("fail_flags") or [])
            if str(item).strip()
          ],
          *post_validation_fail_flags,
        ]
      )
    )
  if bool(cash_post_validation.get("keep_changes")):
    final_model_input_json = _model_input_with_controller_catalog(
      model_input_json=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or {}),
      catalog_source_model_input_json=copy.deepcopy(catalog_source_model_input_json or {}),
    )
    final_finmo_json = copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or {})
    realism_issue_ledger = copy.deepcopy(cash_post_validation.get("issue_ledger") or [])
    resolution_summary = copy.deepcopy(cash_post_validation.get("resolution_summary") or {})
    realism_memo_json = copy.deepcopy(cash_post_validation.get("realism_memo_json") or {})
    controller_resolution_state = copy.deepcopy(cash_post_validation.get("controller_resolution_state") or {})
    hard_rule_assessment = copy.deepcopy(cash_post_validation.get("hard_rule_assessment") or {})
  else:
    final_model_input_json = copy.deepcopy(pre_cash_model_input_json)
    final_finmo_json = copy.deepcopy(pre_cash_finmo_json)
    realism_issue_ledger = copy.deepcopy(pre_cash_issue_ledger)
    resolution_summary = copy.deepcopy(pre_cash_resolution_summary)
    realism_memo_json = copy.deepcopy(pre_cash_realism_memo_json)
    controller_resolution_state = copy.deepcopy(pre_cash_controller_resolution_state)
    hard_rule_assessment = copy.deepcopy(pre_cash_hard_rule_assessment)
    cash_strategy_second_pass_result["status"] = "reverted_post_validation"
    cash_strategy_second_pass_result["final_model_source"] = "converged_model_reverted"
  cash_strategy_result_fail_flags = [
    str(item).strip()
    for item in (cash_strategy_second_pass_result.get("fail_flags") or [])
    if str(item).strip() in _CASH_STRATEGY_TEST_MODE_FAIL_FLAGS
  ]
  if cash_strategy_result_fail_flags:
    cash_pass_failed_controller_state = _build_cash_pass_controller_resolution_state(
      phase="cash_pass_failed",
      base_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
      cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
      cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
      cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
      cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
      cash_post_validation=copy.deepcopy(cash_post_validation),
    )
    _persist_cash_pass_stage(
      stage="cash_pass_failed",
      status="failed",
      cash_controller_resolution_state=copy.deepcopy(cash_pass_failed_controller_state),
      cash_strategy_review_context_payload=copy.deepcopy(cash_strategy_review_context),
      cash_strategy_review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
      cash_strategy_second_pass_plan_payload=copy.deepcopy(cash_strategy_second_pass_plan),
      cash_strategy_second_pass_result_payload=copy.deepcopy(cash_strategy_second_pass_result),
      model_input_payload=copy.deepcopy(cash_strategy_second_pass_result.get("updated_model_input_json") or final_model_input_json),
      finmo_payload=copy.deepcopy(cash_strategy_second_pass_result.get("updated_finmo_json") or final_finmo_json),
    )
    _handle_cash_strategy_test_mode_failure(
      _build_cash_strategy_test_failure_payload(
        review_payload=copy.deepcopy(cash_strategy_review_decision),
        plan_payload=copy.deepcopy(cash_strategy_second_pass_plan),
        result_payload=copy.deepcopy(cash_strategy_second_pass_result),
        before_controller_resolution_state=copy.deepcopy(pre_cash_controller_resolution_state),
        after_controller_resolution_state=copy.deepcopy(
          cash_post_validation.get("controller_resolution_state")
          if isinstance(cash_post_validation.get("controller_resolution_state"), dict)
          else pre_cash_controller_resolution_state
        ),
        extra_flags=copy.deepcopy(cash_strategy_result_fail_flags),
        detail="cash_strategy_second_pass_execution_failed",
      )
    )
  from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
  final_finmo_json = build_python_finmo_json(model_input_json=copy.deepcopy(final_model_input_json))
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_final_finmo_rebuild",
    model_input_json=copy.deepcopy(final_model_input_json),
    finmo_json=copy.deepcopy(final_finmo_json),
    detail="Rebuilt final FINMO from final model_input_json before hard cash gate.",
  )
  cash_strategy_second_pass_result["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  _raise_cash_pass_unresolved_liquidity_if_needed(
    financials_json=copy.deepcopy(financials_json or {}),
    final_model_input_json=copy.deepcopy(final_model_input_json),
    final_finmo_json=copy.deepcopy(final_finmo_json),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
  )
  cash_pass_phase_trace = _record_cash_pass_phase(
    cash_pass_phase_trace,
    cash_pass_phase_contract,
    "cash_final_liquidity_gate",
    model_input_json=copy.deepcopy(final_model_input_json),
    finmo_json=copy.deepcopy(final_finmo_json),
    detail="Final hard liquidity gate passed across all live quarters.",
  )
  _assert_cash_pass_phase_trace_complete(cash_pass_phase_trace, cash_pass_phase_contract)
  cash_strategy_second_pass_result["cash_pass_phase_trace"] = copy.deepcopy(cash_pass_phase_trace)
  process_sequence_trace["final_hard_gates"] = post_intake_process_step_context(
    step_key="final_hard_gates",
    expected_phase="final_validation",
    expected_handler_key="validate_final_post_intake_state",
    required_lookup_tables=[
      "post_intak_mapping_lookup",
      "post_intake_cash_policy_lookup",
      "post_intake_gpt_contract_lookup",
      "post_intake_gpt_context_lookup",
    ],
    required_horizon_rule="validate_all_q1_to_q20",
  )
  _raise_p_and_l_flatline_if_needed(
    final_model_input_json=copy.deepcopy(final_model_input_json),
    final_finmo_json=copy.deepcopy(final_finmo_json),
    stage="post_cash_pass_final",
  )
  final_debt_schedule_payload = _cash_strategy_debt_schedule_snapshot(
    finmo_payload=copy.deepcopy(final_finmo_json),
    model_input_json=copy.deepcopy(final_model_input_json),
  )
  if isinstance(final_debt_schedule_payload, dict):
    final_debt_schedule_payload["selected_cash_strategy"] = _resolved_cash_strategy(financials_json)
    final_debt_schedule_payload["source_stage"] = "cash_pass_completed"
    final_debt_schedule_payload["persisted_column"] = "intake_consult_drafts.debt_schedule"
  cash_strategy_effect_summary = _build_cash_strategy_effect_summary(
    financials_json=copy.deepcopy(financials_json or {}),
    review_decision_payload=copy.deepcopy(cash_strategy_review_decision),
    second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
    first_pass_finmo_json=copy.deepcopy(pre_cash_finmo_json),
    final_finmo_json=copy.deepcopy(final_finmo_json),
  )

  diagnostics_snapshot = {
    "contract_version": "planning_diagnostics_snapshot_v3",
    "baseline_model_input_json": copy.deepcopy(catalog_source_model_input_json or {}),
    "grid_applied_model_input_json": copy.deepcopy(applied_model_input_json or {}),
    "grid_applied_finmo_json": copy.deepcopy(applied_finmo_json or {}),
    "final_model_input_json": copy.deepcopy(final_model_input_json),
    "final_finmo_json": copy.deepcopy(final_finmo_json),
    "unified_convergence_iterations": copy.deepcopy(unified_convergence_iterations),
    "cash_strategy_review_context": copy.deepcopy(cash_strategy_review_context),
    "cash_strategy_review_decision": copy.deepcopy(cash_strategy_review_decision),
    "cash_strategy_second_pass_plan": copy.deepcopy(cash_strategy_second_pass_plan),
    "cash_strategy_second_pass_result": copy.deepcopy(cash_strategy_second_pass_result),
    "cash_strategy_effect_summary": copy.deepcopy(cash_strategy_effect_summary),
    "debt_schedule": copy.deepcopy(final_debt_schedule_payload),
    "post_intake_process_sequence_trace": copy.deepcopy(process_sequence_trace),
    "cost_telemetry": _openai_call_telemetry_snapshot(),
  }
  next_planning_run_json = _build_planning_run_payload(
    stage="cash_pass_completed",
    status="completed",
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    resolution_summary=copy.deepcopy(resolution_summary),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    gpt_narrative=str(planning_result.get("gpt_narrative") or "").strip(),
    gpt_grid_metadata=copy.deepcopy(planning_result.get("metadata") or {}),
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution),
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result),
    cash_strategy_effect_summary=copy.deepcopy(cash_strategy_effect_summary),
    debt_schedule=copy.deepcopy(final_debt_schedule_payload),
    unified_convergence_context=copy.deepcopy(unified_convergence_context),
    unified_convergence_decision=copy.deepcopy(unified_convergence_decision),
    unified_convergence_plan=copy.deepcopy(unified_convergence_plan),
    unified_convergence_result=copy.deepcopy(unified_convergence_result),
    unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations),
    unified_convergence_cycle_count=unified_convergence_cycle_count,
    diagnostics_snapshot=copy.deepcopy(diagnostics_snapshot),
    numeric_solver_contract=build_numeric_solver_contract(
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      selected_cash_strategy=_resolved_cash_strategy(financials_json),
      issue_status_records=_controller_state_issue_status_records(controller_resolution_state),
      writable_lever_catalog=_build_writable_lever_review_catalog(final_model_input_json),
      current_model_input_json=copy.deepcopy(final_model_input_json or {}),
      current_finmo_json=copy.deepcopy(final_finmo_json or {}),
      pass_name="final_system_state",
      contract_scope="planning_run_snapshot",
    ),
  )
  next_planning_run_json["planning_run_id"] = active_planning_run_id
  next_planning_run_json["trigger_type"] = "system_run"
  next_planning_run_json["lifecycle_mode"] = "start"
  persisted_realism_memo = _build_persisted_realism_memo_payload(
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    working_memo=copy.deepcopy(realism_memo_json),
  )
  financial_story_payload = _build_financial_story_payload(
    business_facts=copy.deepcopy(business_facts or {}),
    ops_json=copy.deepcopy(ops_json or {}),
    target_market_json=copy.deepcopy(target_market_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    current_finmo_json=copy.deepcopy(final_finmo_json or {}),
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    hard_rule_assessment=copy.deepcopy(hard_rule_assessment),
  )
  persisted_completion = persist_post_intake_execution_state(
    conn,
    draft_id=str(draft_id).strip(),
    new_messages=[],
    operating_model_json=ops_json,
    target_market_json=target_market_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    realism_memo_json=persisted_realism_memo,
    fulfillment_json=fulfillment_json,
    model_input_json=final_model_input_json,
    finmo_json=final_finmo_json,
    debt_schedule=copy.deepcopy(final_debt_schedule_payload),
    planning_run_json=next_planning_run_json,
    numeric_solver_feedback_json=_extract_numeric_solver_feedback_for_persistence(
      planning_run_payload=next_planning_run_json,
      explicit_candidates=[
        ("unified_convergence_result", unified_convergence_result),
        ("cash_strategy_second_pass_result", cash_strategy_second_pass_result),
      ],
    ),
    financial_story=copy.deepcopy(financial_story_payload),
    active_focus="done",
    business_facts=business_facts,
    status="completed",
    completed=True,
    checkpoint_kind="run_complete",
    event_type="run_completed",
    event_summary="cash_pass_completed:completed",
  )
  if isinstance(persisted_completion, dict) and isinstance(persisted_completion.get("planning_run_json"), dict):
    next_planning_run_json = copy.deepcopy(persisted_completion.get("planning_run_json") or next_planning_run_json)
  return {
    "draft_id": str(draft_id).strip(),
    "planning_context_summary_json": copy.deepcopy(planning_context_summary_json or {}),
    "planning_run_json": next_planning_run_json,
    "planning_runtime_json": (
      copy.deepcopy(persisted_completion.get("planning_runtime_json"))
      if isinstance(persisted_completion, dict) and isinstance(persisted_completion.get("planning_runtime_json"), dict)
      else {}
    ),
    "numeric_solver_feedback_json": _extract_numeric_solver_feedback_for_persistence(
      planning_run_payload=next_planning_run_json,
      explicit_candidates=[
        ("unified_convergence_result", unified_convergence_result),
        ("cash_strategy_second_pass_result", cash_strategy_second_pass_result),
      ],
    ),
    "financial_story": (
      copy.deepcopy(persisted_completion.get("financial_story"))
      if isinstance(persisted_completion, dict) and isinstance(persisted_completion.get("financial_story"), dict)
      else copy.deepcopy(financial_story_payload)
    ),
    "realism_memo_json": persisted_realism_memo,
    "model_input_json": final_model_input_json,
    "finmo_json": final_finmo_json,
    "debt_schedule": copy.deepcopy(final_debt_schedule_payload),
  }



run_unified_post_grid_system_run = _run_unified_post_grid_system_run
