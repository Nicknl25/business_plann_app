from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


PASS_SPECS: List[Tuple[str, str, str]] = [
  ("unified_convergence", "unified_convergence_plan", "unified_convergence_result"),
]

CONTEXT_SPECS: List[Tuple[str, str]] = [
  ("unified_convergence", "unified_convergence_context"),
]


def _looks_like_planning_payload(payload: Any) -> bool:
  if not isinstance(payload, dict):
    return False
  return (
    isinstance(payload.get("controller_resolution_state"), dict)
    or (
      "stage" in payload
      and "status" in payload
      and any(str(key).endswith("_pass_plan") or str(key).endswith("_pass_result") for key in payload.keys())
    )
  )


def _normalize_document(raw: Any) -> Dict[str, Any]:
  if not isinstance(raw, dict):
    raise RuntimeError("Expected a top-level JSON object.")
  if isinstance(raw.get("planning_run_json"), dict):
    return raw
  if isinstance(raw.get("row"), dict):
    return raw
  if isinstance(raw.get("final_planning_run"), dict):
    return {
      "planning_run_json": raw.get("final_planning_run"),
      "convergence_state_json": raw.get("final_convergence_state"),
      "numeric_solver_feedback_json": raw.get("final_numeric_solver_feedback"),
      "row": raw.get("final_snapshot") if isinstance(raw.get("final_snapshot"), dict) else {},
      "_raw": raw,
    }
  if _looks_like_planning_payload(raw):
    return {
      "planning_run_json": raw,
      "_raw": raw,
    }
  if str(raw.get("error") or "").strip():
    return {"_raw": raw}
  raise RuntimeError(
    "Expected a JSON object containing planning_run_json, row, final_planning_run, or a direct planning payload."
  )


def _load_json(path: Path) -> Dict[str, Any]:
  raw = json.loads(path.read_text(encoding="utf-8"))
  return _normalize_document(raw)


def _planning_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
  if isinstance(doc.get("planning_run_json"), dict):
    return doc["planning_run_json"]
  row = doc.get("row") if isinstance(doc.get("row"), dict) else {}
  if isinstance(row.get("planning_run_json"), dict):
    return row["planning_run_json"]
  raise RuntimeError("Could not find planning_run_json payload.")


def _row_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
  return doc.get("row") if isinstance(doc.get("row"), dict) else {}


def _raw_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
  return doc.get("_raw") if isinstance(doc.get("_raw"), dict) else doc


def _separate_feedback_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
  if isinstance(doc.get("numeric_solver_feedback_json"), dict):
    return doc["numeric_solver_feedback_json"]
  row = _row_payload(doc)
  if isinstance(row.get("numeric_solver_feedback_json"), dict):
    return row["numeric_solver_feedback_json"]
  return {}


def _convergence_state_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
  if isinstance(doc.get("convergence_state_json"), dict):
    return doc["convergence_state_json"]
  row = _row_payload(doc)
  if isinstance(row.get("convergence_state_json"), dict):
    return row["convergence_state_json"]
  return {}


def _contract(plan: Dict[str, Any]) -> Dict[str, Any]:
  return plan.get("numeric_solver_contract") if isinstance(plan.get("numeric_solver_contract"), dict) else {}


def _packages(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
  return [item for item in (plan.get("translated_action_packages") or []) if isinstance(item, dict)]


def _active_issue_count_from_context(context: Dict[str, Any]) -> int:
  issue_summaries = (
    context.get("current_issue_summaries")
    if isinstance(context.get("current_issue_summaries"), dict)
    else {}
  )
  remaining = issue_summaries.get("remaining_issue_count")
  if remaining is not None:
    try:
      return int(remaining)
    except Exception:
      return 0
  records = [
    item for item in (context.get("issue_status_records") or [])
    if isinstance(item, dict) and str(item.get("verifier_status") or "").strip().lower() != "resolved"
  ]
  return len(records)


def _check_context(name: str, context: Dict[str, Any]) -> List[str]:
  errors: List[str] = []
  if not context:
    return errors

  if not isinstance(context.get("numeric_solver_contract"), dict):
    errors.append(f"{name}: numeric_solver_contract was missing from context.")

  if not isinstance(context.get("deterministic_issue_packets"), list):
    errors.append(f"{name}: deterministic_issue_packets was missing from context.")
  elif _active_issue_count_from_context(context) > 0 and not (context.get("deterministic_issue_packets") or []):
    errors.append(f"{name}: active issues existed but deterministic_issue_packets was empty.")

  contract = context.get("numeric_solver_contract") if isinstance(context.get("numeric_solver_contract"), dict) else {}
  quarter_target_grid = [
    item for item in (contract.get("quarter_target_grid") or [])
    if isinstance(item, dict)
  ]
  if _active_issue_count_from_context(context) > 0 and not quarter_target_grid:
    errors.append(f"{name}: active issues existed but numeric_solver_contract.quarter_target_grid was empty.")

  return errors


def _check_pass(name: str, plan: Dict[str, Any], result: Dict[str, Any]) -> List[str]:
  errors: List[str] = []
  contract = _contract(plan)
  active_issue_count = int(contract.get("active_issue_count") or 0)
  packages = _packages(plan)
  if active_issue_count <= 0:
    return errors

  if not packages:
    errors.append(f"{name}: active issues existed but translated_action_packages was empty.")

  for idx, package in enumerate(packages, start=1):
    allowed = [str(item).strip() for item in (package.get("solver_allowed_lever_ids") or []) if str(item).strip()]
    targets = [item for item in (package.get("quarter_target_metrics") or []) if isinstance(item, dict)]
    if not allowed:
      errors.append(f"{name}: package {idx} missing solver_allowed_lever_ids.")
    if not targets:
      errors.append(f"{name}: package {idx} missing quarter_target_metrics.")

  numeric_plan = result.get("numeric_execution_plan") if isinstance(result.get("numeric_execution_plan"), dict) else {}
  targeted_quarters = [int(item) for item in (numeric_plan.get("targeted_quarters") or []) if int(item) >= 1]
  allowed_levers = [str(item).strip() for item in (numeric_plan.get("allowed_lever_ids") or []) if str(item).strip()]
  if not targeted_quarters:
    errors.append(f"{name}: numeric_execution_plan.targeted_quarters was empty on an active-issue pass.")
  if not allowed_levers:
    errors.append(f"{name}: numeric_execution_plan.allowed_lever_ids was empty on an active-issue pass.")

  applied_update_count = int(result.get("applied_update_count") or 0)
  if applied_update_count <= 0:
    errors.append(f"{name}: pass completed with zero applied updates on an active-issue pass.")

  solver_result = result.get("numeric_solver_result") if isinstance(result.get("numeric_solver_result"), dict) else {}
  if "used_solver" in solver_result or "status" in solver_result:
    errors.append(f"{name}: legacy solver judgment keys still present in numeric_solver_result.")

  for attempt in [item for item in (solver_result.get("attempts") or []) if isinstance(item, dict)]:
    if "success" in attempt:
      errors.append(f"{name}: legacy attempt.success key still present in numeric_solver_result.attempts.")
      break

  return errors


def _check_realism_trace(planning: Dict[str, Any]) -> List[str]:
  errors: List[str] = []
  retired_payload_keys = [
    "initial_restructure_context",
    "initial_restructure_pass_plan",
    "initial_restructure_pass_result",
    "realism_resolution_plan",
    "realism_resolution_result",
    "realism_resolution_iterations",
    "cash_strategy_review_context",
    "cash_strategy_second_pass_plan",
    "cash_strategy_second_pass_result",
    "final_stabilizer_context",
    "final_stabilizer_pass_plan",
    "final_stabilizer_pass_result",
    "final_guarantee_context",
    "final_guarantee_iterations",
  ]
  for key in retired_payload_keys:
    value = planning.get(key)
    if isinstance(value, dict) and value:
      errors.append(f"{key} should be empty after the unified convergence cutover.")
    elif isinstance(value, list) and value:
      errors.append(f"{key} should be empty after the unified convergence cutover.")
  return errors


def _check_terminal_state(
  planning: Dict[str, Any],
  row: Dict[str, Any],
  convergence_state: Dict[str, Any],
  separate_feedback: Dict[str, Any],
) -> List[str]:
  errors: List[str] = []

  if str(planning.get("stage") or "").strip() != "convergence_completed":
    errors.append("planning_run_json.stage did not reach convergence_completed.")
  if str(planning.get("status") or "").strip() != "completed":
    errors.append("planning_run_json.status was not completed.")

  if row:
    if str(row.get("status") or "").strip().lower() != "completed":
      errors.append("draft row status was not completed.")
    if str(row.get("planning_stage") or "").strip() != "convergence_completed":
      errors.append("draft row planning_stage did not reach convergence_completed.")
    if str(row.get("planning_status") or "").strip() != "completed":
      errors.append("draft row planning_status was not completed.")

  controller = planning.get("controller_resolution_state") if isinstance(planning.get("controller_resolution_state"), dict) else {}
  if not controller:
    errors.append("controller_resolution_state was missing from planning_run_json.")
    return errors

  if not bool(controller.get("all_cleared")):
    errors.append("controller_resolution_state.all_cleared was not true at completion.")
  if int(controller.get("remaining_issue_count") or 0) != 0:
    errors.append("controller_resolution_state.remaining_issue_count was not 0 at completion.")
  if str(controller.get("status") or "").strip() != "all_cleared":
    errors.append("controller_resolution_state.status was not all_cleared at completion.")

  if not convergence_state:
    errors.append("separate convergence_state_json payload was missing.")
  else:
    if str(convergence_state.get("owner") or "").strip() != "unified_convergence":
      errors.append("convergence_state_json.owner was not unified_convergence.")
    if str(convergence_state.get("stage") or "").strip() != "convergence_completed":
      errors.append("convergence_state_json.stage did not reach convergence_completed.")
    if str(convergence_state.get("status") or "").strip() != "completed":
      errors.append("convergence_state_json.status was not completed.")
    issue_state = (
      convergence_state.get("issue_state")
      if isinstance(convergence_state.get("issue_state"), dict)
      else {}
    )
    if not issue_state:
      errors.append("convergence_state_json.issue_state was missing.")
    else:
      if int(issue_state.get("remaining_issue_count") or 0) != 0:
        errors.append("convergence_state_json.issue_state.remaining_issue_count was not 0.")
      if str(issue_state.get("controller_status") or "").strip() not in {"all_cleared", ""}:
        errors.append("convergence_state_json.issue_state.controller_status was not all_cleared.")
      if int(issue_state.get("overall_completion_score_pct") or 0) < 80:
        errors.append("convergence_state_json.issue_state.overall_completion_score_pct was below 80.")
    hard_rule_state = (
      convergence_state.get("hard_rule_state")
      if isinstance(convergence_state.get("hard_rule_state"), dict)
      else {}
    )
    if not hard_rule_state:
      errors.append("convergence_state_json.hard_rule_state was missing.")
    else:
      if not bool(hard_rule_state.get("all_hard_rules_cleared")):
        errors.append("convergence_state_json.hard_rule_state.all_hard_rules_cleared was not true.")
      if int(hard_rule_state.get("remaining_hard_issue_count") or 0) != 0:
        errors.append("convergence_state_json.hard_rule_state.remaining_hard_issue_count was not 0.")

  unified_iterations = [
    item for item in (planning.get("unified_convergence_iterations") or [])
    if isinstance(item, dict)
  ]
  unified_cycle_count = int(planning.get("unified_convergence_cycle_count") or 0)
  if unified_cycle_count != len(unified_iterations):
    errors.append("unified_convergence_cycle_count did not match unified_convergence_iterations length.")
  if not unified_iterations:
    errors.append("unified_convergence_iterations was empty.")
  else:
    last_iteration = unified_iterations[-1]
    if not bool(last_iteration.get("accepted")):
      errors.append("last unified_convergence iteration was not accepted.")
    after_state = (
      last_iteration.get("controller_resolution_state_after")
      if isinstance(last_iteration.get("controller_resolution_state_after"), dict)
      else {}
    )
    if not bool(after_state.get("all_cleared")):
      errors.append("last unified_convergence controller_resolution_state_after was not all_cleared.")
    if int(after_state.get("remaining_issue_count") or 0) != 0:
      errors.append("last unified_convergence controller_resolution_state_after.remaining_issue_count was not 0.")

  unified_context = planning.get("unified_convergence_context") if isinstance(planning.get("unified_convergence_context"), dict) else {}
  hard_rule_context = (
    ((unified_context.get("context_modules") or {}).get("hard_rules"))
    if isinstance((unified_context.get("context_modules") or {}).get("hard_rules"), dict)
    else {}
  )
  hard_rule_assessment = (
    hard_rule_context.get("hard_rule_assessment")
    if isinstance(hard_rule_context.get("hard_rule_assessment"), dict)
    else {}
  )
  if not hard_rule_assessment:
    errors.append("unified_convergence_context.context_modules.hard_rules.hard_rule_assessment was missing.")
  else:
    if not bool(hard_rule_assessment.get("all_hard_rules_cleared")):
      errors.append("unified_convergence_context.context_modules.hard_rules.hard_rule_assessment.all_hard_rules_cleared was not true.")

  convergence_summary = (
    planning.get("deterministic_convergence_summary")
    if isinstance(planning.get("deterministic_convergence_summary"), dict)
    else {}
  )
  if not convergence_summary:
    errors.append("planning_run_json.deterministic_convergence_summary was missing.")
  else:
    terminal_gate = (
      convergence_summary.get("terminal_acceptance_gate")
      if isinstance(convergence_summary.get("terminal_acceptance_gate"), dict)
      else {}
    )
    if not terminal_gate:
      errors.append("planning_run_json.deterministic_convergence_summary.terminal_acceptance_gate was missing.")
    else:
      required_true_flags = (
        "stage_is_convergence_completed",
        "status_is_completed",
        "all_cleared",
        "remaining_issue_count_zero",
        "remaining_hard_issue_count_zero",
        "hard_rules_cleared",
        "last_cycle_accepted",
      )
      for flag in required_true_flags:
        if not bool(terminal_gate.get(flag)):
          errors.append(
            "planning_run_json.deterministic_convergence_summary.terminal_acceptance_gate."
            + f"{flag} was not true."
          )

  if not separate_feedback:
    errors.append("separate numeric_solver_feedback_json payload was missing.")
  else:
    if str(separate_feedback.get("persistence_stage") or "").strip() not in {"convergence_completed", "convergence_running", "done"}:
      errors.append("numeric_solver_feedback_json.persistence_stage did not reflect terminal planning state.")
    feedback_convergence_summary = (
      separate_feedback.get("deterministic_convergence_summary")
      if isinstance(separate_feedback.get("deterministic_convergence_summary"), dict)
      else {}
    )
    if not feedback_convergence_summary:
      errors.append("numeric_solver_feedback_json.deterministic_convergence_summary was missing.")
    current_cycle_trace = (
      separate_feedback.get("current_cycle_trace")
      if isinstance(separate_feedback.get("current_cycle_trace"), dict)
      else {}
    )
    if not current_cycle_trace:
      errors.append("numeric_solver_feedback_json.current_cycle_trace was missing.")
    else:
      if current_cycle_trace.get("guidance_metric_count") is None:
        errors.append("numeric_solver_feedback_json.current_cycle_trace.guidance_metric_count was missing.")
      if current_cycle_trace.get("guidance_lever_count") is None:
        errors.append("numeric_solver_feedback_json.current_cycle_trace.guidance_lever_count was missing.")
      if current_cycle_trace.get("planned_target_quarter_count") is None:
        errors.append("numeric_solver_feedback_json.current_cycle_trace.planned_target_quarter_count was missing.")

  return errors


def _check_failed_run_payload(raw: Dict[str, Any]) -> List[str]:
  errors: List[str] = []
  error_code = str(raw.get("error") or "").strip()
  if not error_code:
    return errors
  detail = str(raw.get("detail") or "").strip()
  errors.append(
    "input artifact already represented a failed system run"
    + (f" ({error_code}: {detail})" if detail else f" ({error_code})")
  )
  return errors


def _check_monitor_artifact_consistency(
  raw: Dict[str, Any],
  planning: Dict[str, Any],
  row: Dict[str, Any],
) -> List[str]:
  errors: List[str] = []
  final_run_row = raw.get("final_planning_run_row") if isinstance(raw.get("final_planning_run_row"), dict) else {}
  final_checkpoint = raw.get("final_latest_checkpoint") if isinstance(raw.get("final_latest_checkpoint"), dict) else {}
  final_events = [item for item in (raw.get("final_recent_stage_events") or []) if isinstance(item, dict)]
  final_convergence_state = raw.get("final_convergence_state") if isinstance(raw.get("final_convergence_state"), dict) else {}
  if not raw.get("event") == "final_row" and not final_run_row and not final_checkpoint and not final_events:
    return errors

  if not final_run_row:
    errors.append("monitor artifact was missing final_planning_run_row.")
    return errors
  if not final_convergence_state:
    errors.append("monitor artifact was missing final_convergence_state.")

  monitor_planning_run_id = str(raw.get("planning_run_id") or "").strip()
  run_row_planning_run_id = str(final_run_row.get("planning_run_id") or "").strip()
  row_planning_run_id = str(row.get("planning_run_id") or "").strip()
  planning_payload_run_id = str(planning.get("planning_run_id") or "").strip()

  if not run_row_planning_run_id:
    errors.append("final_planning_run_row.planning_run_id was missing.")
  if monitor_planning_run_id and run_row_planning_run_id and monitor_planning_run_id != run_row_planning_run_id:
    errors.append("monitor artifact planning_run_id did not match final_planning_run_row.planning_run_id.")
  if row_planning_run_id and run_row_planning_run_id and row_planning_run_id != run_row_planning_run_id:
    errors.append("draft row planning_run_id did not match final_planning_run_row.planning_run_id.")
  if planning_payload_run_id and run_row_planning_run_id and planning_payload_run_id != run_row_planning_run_id:
    errors.append("planning_run_json.planning_run_id did not match final_planning_run_row.planning_run_id.")

  if str(final_run_row.get("run_status") or "").strip().lower() != "completed":
    errors.append("final_planning_run_row.run_status was not completed.")
  if str(final_run_row.get("current_stage") or "").strip() != "convergence_completed":
    errors.append("final_planning_run_row.current_stage did not reach convergence_completed.")
  if str(final_run_row.get("current_stage_status") or "").strip() != "completed":
    errors.append("final_planning_run_row.current_stage_status was not completed.")

  latest_checkpoint_id = str(final_run_row.get("latest_checkpoint_id") or "").strip()
  if not latest_checkpoint_id:
    errors.append("final_planning_run_row.latest_checkpoint_id was missing.")

  if not final_checkpoint:
    errors.append("monitor artifact was missing final_latest_checkpoint.")
  else:
    checkpoint_id = str(final_checkpoint.get("checkpoint_id") or "").strip()
    if latest_checkpoint_id and checkpoint_id and latest_checkpoint_id != checkpoint_id:
      errors.append("final_planning_run_row.latest_checkpoint_id did not match final_latest_checkpoint.checkpoint_id.")
    if run_row_planning_run_id and str(final_checkpoint.get("planning_run_id") or "").strip() != run_row_planning_run_id:
      errors.append("final_latest_checkpoint.planning_run_id did not match final_planning_run_row.planning_run_id.")
    if str(final_checkpoint.get("stage") or "").strip() != "convergence_completed":
      errors.append("final_latest_checkpoint.stage did not reach convergence_completed.")
    if str(final_checkpoint.get("stage_status") or "").strip() != "completed":
      errors.append("final_latest_checkpoint.stage_status was not completed.")
    if str(final_checkpoint.get("checkpoint_kind") or "").strip() != "run_complete":
      errors.append("final_latest_checkpoint.checkpoint_kind was not run_complete.")

  if not final_events:
    errors.append("monitor artifact was missing final_recent_stage_events.")
  else:
    event_types = {str(item.get("event_type") or "").strip() for item in final_events if str(item.get("event_type") or "").strip()}
    if "run_completed" not in event_types:
      errors.append("final_recent_stage_events did not include a run_completed event.")
    if run_row_planning_run_id:
      mismatched_event = next(
        (
          item for item in final_events
          if str(item.get("planning_run_id") or "").strip()
          and str(item.get("planning_run_id") or "").strip() != run_row_planning_run_id
        ),
        None,
      )
      if mismatched_event:
        errors.append("one or more final_recent_stage_events rows had a different planning_run_id than final_planning_run_row.")

  return errors


def _check_monitor_health_summary(raw: Dict[str, Any]) -> List[str]:
  errors: List[str] = []
  summary = raw.get("final_monitor_health_summary") if isinstance(raw.get("final_monitor_health_summary"), dict) else {}
  if not raw.get("event") == "final_row" and not summary:
    return errors
  if not summary:
    errors.append("monitor artifact was missing final_monitor_health_summary.")
    return errors

  if str(summary.get("contract_version") or "").strip() != "monitor_health_summary_v1":
    errors.append("final_monitor_health_summary.contract_version was not monitor_health_summary_v1.")
  if not bool(summary.get("heartbeat_present")):
    errors.append("final_monitor_health_summary.heartbeat_present was not true.")
  if not bool(summary.get("checkpoint_present")):
    errors.append("final_monitor_health_summary.checkpoint_present was not true.")
  if not bool(summary.get("recent_events_present")):
    errors.append("final_monitor_health_summary.recent_events_present was not true.")
  if not bool(summary.get("run_completed_event_seen")):
    errors.append("final_monitor_health_summary.run_completed_event_seen was not true.")
  if not bool(summary.get("completed_cleanly")):
    errors.append("final_monitor_health_summary.completed_cleanly was not true.")
  if str(summary.get("latest_draft_stage") or "").strip() != "convergence_completed":
    errors.append("final_monitor_health_summary.latest_draft_stage did not reach convergence_completed.")
  if str(summary.get("latest_run_stage") or "").strip() != "convergence_completed":
    errors.append("final_monitor_health_summary.latest_run_stage did not reach convergence_completed.")
  if str(summary.get("latest_run_status") or "").strip().lower() != "completed":
    errors.append("final_monitor_health_summary.latest_run_status was not completed.")

  return errors


def validate_loaded_document(doc: Dict[str, Any]) -> List[str]:
  normalized = _normalize_document(doc)
  raw = _raw_payload(normalized)
  if str(raw.get("error") or "").strip():
    return _check_failed_run_payload(raw)

  planning = _planning_payload(normalized)
  row = _row_payload(normalized)
  convergence_state = _convergence_state_payload(normalized)
  separate_feedback = _separate_feedback_payload(normalized)

  errors: List[str] = []
  errors.extend(_check_terminal_state(planning, row, convergence_state, separate_feedback))
  errors.extend(_check_monitor_artifact_consistency(raw, planning, row))
  errors.extend(_check_monitor_health_summary(raw))
  errors.extend(_check_realism_trace(planning))

  for context_name, context_key in CONTEXT_SPECS:
    context = planning.get(context_key) if isinstance(planning.get(context_key), dict) else {}
    if not context:
      continue
    errors.extend(_check_context(context_name, context))

  for pass_name, plan_key, result_key in PASS_SPECS:
    plan = planning.get(plan_key) if isinstance(planning.get(plan_key), dict) else {}
    result = planning.get(result_key) if isinstance(planning.get(result_key), dict) else {}
    if not plan and not result:
      continue
    errors.extend(_check_pass(pass_name, plan, result))

  return errors


def validate_path(path: Path) -> List[str]:
  return validate_loaded_document(_load_json(path))


def main(argv: List[str]) -> int:
  if len(argv) != 2:
    print("Usage: validate_numeric_cutover.py <json-file>")
    return 2

  path = Path(argv[1])
  errors = validate_path(path)

  if errors:
    print("CUTOVER VALIDATION FAILED")
    for item in errors:
      print(f"- {item}")
    return 1

  print("CUTOVER VALIDATION PASSED")
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))
