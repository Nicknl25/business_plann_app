"""Retry-scope helpers for post-intake convergence."""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional

from .contracts import build_unified_convergence_contract_policy


def _safe_int(value: Any, default: int = 0) -> int:
  try:
    return int(round(float(value)))
  except Exception:
    return int(default)


def full_horizon_quarters(quarter_count: Any = None) -> List[int]:
  """Return the full forecast horizon defined by the convergence contract policy."""
  policy = build_unified_convergence_contract_policy()
  required = [
    _safe_int(item)
    for item in (policy.get("required_forecast_quarters") or [])
    if _safe_int(item) >= 1
  ]
  if required:
    return required
  count = max(1, _safe_int(quarter_count, 20) or 20)
  return list(range(1, count + 1))


def retry_scope_quarters(
  *,
  controller_retry_context: Optional[Dict[str, Any]],
  quarter_count: Any,
) -> List[int]:
  """Convergence retry scope is always the SQL-contract full horizon."""
  _ = controller_retry_context
  return full_horizon_quarters(quarter_count)


def full_horizon_retry_scope_mode() -> str:
  """Stable label for SQL-contract-backed full-horizon convergence scope."""
  policy = build_unified_convergence_contract_policy()
  target_rule = policy.get("target_grid_rule") if isinstance(policy.get("target_grid_rule"), dict) else {}
  horizon_rule = str(target_rule.get("horizon_rule") or "").strip().lower()
  if horizon_rule == "q1_to_q20_exactly_once":
    return "sql_contract_q1_to_q20_exactly_once"
  return "sql_contract_full_horizon"


def decorate_retry_scope_payload(
  payload: Optional[Dict[str, Any]],
  *,
  quarter_count: Any = None,
) -> Dict[str, Any]:
  """Attach table-backed convergence scope policy to a retry payload."""
  out = copy.deepcopy(payload if isinstance(payload, dict) else {})
  out["scope_mode"] = "full_horizon"
  out["convergence_contract_policy"] = build_unified_convergence_contract_policy()
  out["focus_quarter_selection_mode"] = full_horizon_retry_scope_mode()
  out["focus_quarters"] = full_horizon_quarters(quarter_count)
  return out


def retry_scope_lever_ids(
  *,
  controller_retry_context: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]] = None,
  solved_model_input_json: Optional[Dict[str, Any]] = None,
  scoped_quarters: Optional[List[int]] = None,
  build_writable_lever_review_catalog: Callable[[Any], List[Dict[str, Any]]],
  deterministic_guidance_focus_issue_codes: Callable[[Any], List[str]],
  scoped_unified_allowed_lever_ids: Callable[..., List[str]],
  solver_contract_eligible_lever_ids: Callable[..., List[str]],
  max_active_issue_count: int,
  max_focus_levers: int,
) -> List[str]:
  """Return allowed convergence levers using the table-backed full-horizon scope."""
  context = controller_retry_context if isinstance(controller_retry_context, dict) else {}
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  contract_catalog_entries = [
    item
    for item in (((contract.get("writable_lever_catalog") or {}) if isinstance(contract.get("writable_lever_catalog"), dict) else {}).get("entries") or [])
    if isinstance(item, dict)
  ]
  model_catalog_entries = build_writable_lever_review_catalog(solved_model_input_json)
  catalog_entries: List[Dict[str, Any]] = []
  seen_catalog_lever_ids: set[str] = set()
  for item in contract_catalog_entries + model_catalog_entries:
    lever_id = str(item.get("lever_id") or "").strip() if isinstance(item, dict) else ""
    if not lever_id or lever_id in seen_catalog_lever_ids:
      continue
    seen_catalog_lever_ids.add(lever_id)
    catalog_entries.append(copy.deepcopy(item))
  all_catalog_lever_ids = [
    str(item.get("lever_id") or "").strip()
    for item in catalog_entries
    if str(item.get("lever_id") or "").strip()
  ]
  current_guidance_focus_issue_codes = deterministic_guidance_focus_issue_codes(
    deterministic_numeric_guidance
  )
  focus_issue_codes = [
    str(item).strip().lower()
    for item in (
      current_guidance_focus_issue_codes
      or context.get("focus_issue_codes")
      or context.get("required_open_issue_codes")
      or [
        str((item or {}).get("issue_code") or "").strip().lower()
        for item in (contract.get("issue_target_packets") or [])
        if isinstance(item, dict) and str((item or {}).get("issue_code") or "").strip()
      ]
    )
    if str(item).strip()
  ][: max(1, int(max_active_issue_count or 1))]
  guidance_scoped_ids = scoped_unified_allowed_lever_ids(
    fallback_allowed_lever_ids=all_catalog_lever_ids,
    deterministic_numeric_guidance=deterministic_numeric_guidance,
  )
  if guidance_scoped_ids:
    return guidance_scoped_ids[:max_focus_levers]
  focused_ids = [
    str(item).strip()
    for item in (context.get("required_issue_lever_ids") or [])
    if str(item).strip()
  ]
  if focused_ids:
    deduped = [lever_id for lever_id in dict.fromkeys(focused_ids) if lever_id in set(all_catalog_lever_ids)]
    if deduped:
      return deduped[:max_focus_levers]
  contract_eligible = [
    lever_id
    for lever_id in solver_contract_eligible_lever_ids(
      numeric_solver_contract=contract,
      issue_codes=focus_issue_codes,
      target_quarters=scoped_quarters,
    )
    if lever_id in set(all_catalog_lever_ids)
  ]
  if contract_eligible:
    return contract_eligible[:max_focus_levers]
  relevant = {
    str(item).strip()
    for item in (context.get("required_retry_lever_ids_for_failed_quarters") or [])
    if str(item).strip()
  }
  relevant.update(
    {
      str(item).strip()
      for item in (context.get("previous_allowed_lever_ids") or [])
      if str(item).strip()
    }
  )
  if relevant:
    return sorted(relevant)[:max_focus_levers]
  return all_catalog_lever_ids[:max_focus_levers]


def prior_attempt_delta_summary(
  prior_numeric_feedback: Optional[Dict[str, Any]],
  *,
  scoped_quarters: Optional[List[int]],
  safe_float: Callable[[Any], Optional[float]],
) -> Dict[str, Any]:
  """Compact prior numeric feedback for convergence retry prompts."""
  feedback = prior_numeric_feedback if isinstance(prior_numeric_feedback, dict) else {}
  quarter_set = {
    int(safe_float(item) or 0)
    for item in (scoped_quarters or [])
    if int(safe_float(item) or 0) >= 1
  }
  quarter_results = [
    item for item in (feedback.get("quarter_results") or [])
    if isinstance(item, dict)
    and (
      not quarter_set
      or int(safe_float(item.get("quarter_index")) or 0) in quarter_set
    )
  ]
  delta_rows: List[Dict[str, Any]] = []
  for result in quarter_results:
    quarter_index = int(safe_float(result.get("quarter_index")) or 0)
    for metric_name, metric_payload in ((result.get("target_metrics") or {}) if isinstance(result.get("target_metrics"), dict) else {}).items():
      if not isinstance(metric_payload, dict):
        continue
      delta_rows.append(
        {
          "quarter_index": quarter_index,
          "metric_name": str(metric_name or "").strip().lower(),
          "target_value": float(safe_float(metric_payload.get("target_value")) or 0.0),
          "actual_value": float(safe_float(metric_payload.get("actual_value")) or 0.0),
          "tolerance": float(safe_float(metric_payload.get("tolerance")) or 0.0),
          "residual_after_tolerance": float(safe_float(metric_payload.get("residual_after_tolerance")) or 0.0),
        }
      )
  delta_rows.sort(
    key=lambda item: (
      int(item.get("quarter_index") or 0),
      str(item.get("metric_name") or "").strip(),
    )
  )
  return {
    "attempt_count": int(safe_float(feedback.get("attempt_count")) or 0),
    "quarters_with_target_misses": int(safe_float(feedback.get("quarters_with_target_misses")) or 0),
    "scoped_target_vs_actual_deltas": delta_rows,
  }


def build_retry_scope_payload(
  *,
  controller_retry_context: Optional[Dict[str, Any]],
  prior_numeric_feedback: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  solved_model_input_json: Optional[Dict[str, Any]],
  solved_finmo_json: Optional[Dict[str, Any]],
  safe_float: Callable[[Any], Optional[float]],
  quarter_count_from_model_input: Callable[[Any], int],
  deterministic_guidance_focus_issue_codes: Callable[[Any], List[str]],
  retry_scope_lever_ids_fn: Callable[..., List[str]],
  solved_lever_value_map: Callable[[Any], Dict[str, Any]],
  build_writable_lever_review_catalog: Callable[[Any], List[Dict[str, Any]]],
  finmo_rows_for_quarters: Callable[[Any, List[int]], List[Dict[str, Any]]],
  compact_quarter_metric_rows_for_storage: Callable[[Any], Any],
  compact_writable_lever_catalog_entries: Callable[[Any], Any],
  subset_lever_value_map: Callable[..., Dict[str, Any]],
  max_active_issue_count: int,
) -> Dict[str, Any]:
  """Build the full-horizon retry payload for convergence."""
  context = controller_retry_context if isinstance(controller_retry_context, dict) else {}
  quarter_count = quarter_count_from_model_input(solved_model_input_json)
  current_guidance_focus_issue_codes = deterministic_guidance_focus_issue_codes(
    deterministic_numeric_guidance
  )
  focus_issue_codes = [
    str(item).strip().lower()
    for item in (
      current_guidance_focus_issue_codes
      or context.get("focus_issue_codes")
      or context.get("required_open_issue_codes")
      or [
        str((item or {}).get("issue_code") or "").strip().lower()
        for item in (((numeric_solver_contract or {}).get("issue_target_packets") or []))
        if isinstance(item, dict) and str((item or {}).get("issue_code") or "").strip()
      ]
    )
    if str(item).strip()
  ][:max_active_issue_count]
  scoped_quarters = retry_scope_quarters(
    controller_retry_context=context,
    quarter_count=quarter_count,
  )
  guidance_scope_quarters = [
    int(safe_float(item) or 0)
    for item in (((deterministic_numeric_guidance or {}) if isinstance(deterministic_numeric_guidance, dict) else {}).get("scope_quarters") or [])
    if int(safe_float(item) or 0) >= 1
  ]
  if guidance_scope_quarters:
    scoped_quarters = retry_scope_quarters(
      controller_retry_context=context,
      quarter_count=quarter_count,
    )
  scoped_lever_ids = retry_scope_lever_ids_fn(
    controller_retry_context={
      **copy.deepcopy(context),
      "focus_issue_codes": copy.deepcopy(focus_issue_codes),
    },
    numeric_solver_contract=numeric_solver_contract,
    deterministic_numeric_guidance=deterministic_numeric_guidance,
    solved_model_input_json=solved_model_input_json,
    scoped_quarters=scoped_quarters,
  )
  lever_value_map = solved_lever_value_map(solved_model_input_json)
  contract_catalog_entries = [
    item
    for item in ((((numeric_solver_contract or {}).get("writable_lever_catalog") or {}) if isinstance((numeric_solver_contract or {}).get("writable_lever_catalog"), dict) else {}).get("entries") or [])
    if isinstance(item, dict)
  ]
  model_catalog_entries = build_writable_lever_review_catalog(solved_model_input_json)
  full_catalog_entries: List[Dict[str, Any]] = []
  seen_catalog_lever_ids: set[str] = set()
  for item in contract_catalog_entries + model_catalog_entries:
    lever_id = str(item.get("lever_id") or "").strip() if isinstance(item, dict) else ""
    if not lever_id or lever_id in seen_catalog_lever_ids:
      continue
    seen_catalog_lever_ids.add(lever_id)
    full_catalog_entries.append(copy.deepcopy(item))
  scoped_catalog_entries = [
    copy.deepcopy(item)
    for item in full_catalog_entries
    if str(item.get("lever_id") or "").strip() in set(scoped_lever_ids)
  ]
  scoped_finmo_rows = finmo_rows_for_quarters(
    solved_finmo_json,
    scoped_quarters,
  )
  scoped_model_payload: Dict[str, Any] = {
    "retry_scope": "full_horizon",
    "quarter_indexes": copy.deepcopy(scoped_quarters),
    "lever_ids": copy.deepcopy(scoped_lever_ids),
    "lever_current_values": subset_lever_value_map(
      lever_value_map,
      scoped_lever_ids,
      scoped_quarters,
    ),
  }
  payload = {
    "scope_mode": "full_horizon",
    "focus_issue_codes": copy.deepcopy(focus_issue_codes),
    "scoped_quarters": copy.deepcopy(scoped_quarters),
    "scoped_lever_ids": copy.deepcopy(scoped_lever_ids),
    "finmo_quarter_rows": compact_quarter_metric_rows_for_storage(copy.deepcopy(scoped_finmo_rows)),
    "lever_catalog_entries": compact_writable_lever_catalog_entries(copy.deepcopy(scoped_catalog_entries)),
    "lever_current_values": subset_lever_value_map(lever_value_map, scoped_lever_ids, scoped_quarters),
    "model_input_payload": copy.deepcopy(scoped_model_payload),
    "prior_attempt_summary": prior_attempt_delta_summary(
      prior_numeric_feedback,
      scoped_quarters=scoped_quarters,
      safe_float=safe_float,
    ),
  }
  return decorate_retry_scope_payload(payload, quarter_count=quarter_count)


def subset_numeric_solver_contract(
  *,
  numeric_solver_contract: Optional[Dict[str, Any]],
  retry_scope_payload: Optional[Dict[str, Any]],
  solver_contract_quarter_count: Callable[[Any], int],
) -> Dict[str, Any]:
  """Force solver contracts to the SQL-backed convergence horizon."""
  contract = copy.deepcopy(numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {})
  _ = retry_scope_payload
  quarter_count = solver_contract_quarter_count(contract) or 20
  contract["required_target_quarters"] = full_horizon_quarters(quarter_count)
  contract["scope_mode"] = "full_horizon"
  return contract


def evaluate_retry_improvement(
  *,
  previous_result_signature: Optional[Dict[str, Any]],
  current_result_signature: Optional[Dict[str, Any]],
  safe_float: Callable[[Any], Optional[float]],
  negligible_improvement_ratio: float,
) -> Dict[str, Any]:
  """Assess whether a convergence retry produced meaningful numeric progress."""
  previous = previous_result_signature if isinstance(previous_result_signature, dict) else {}
  current = current_result_signature if isinstance(current_result_signature, dict) else {}
  previous_residual = float(safe_float(previous.get("total_residual_after_tolerance")) or 0.0)
  current_residual = float(safe_float(current.get("total_residual_after_tolerance")) or 0.0)
  improvement = float(previous_residual - current_residual)
  improvement_ratio = (
    float(improvement / previous_residual)
    if previous_residual > 1e-9
    else 1.0
  )
  previous_failed_metric_count = int(safe_float(previous.get("failed_metric_count")) or 0)
  current_failed_metric_count = int(safe_float(current.get("failed_metric_count")) or 0)
  previous_failed_quarter_count = int(safe_float(previous.get("quarters_with_target_misses")) or 0)
  current_failed_quarter_count = int(safe_float(current.get("quarters_with_target_misses")) or 0)
  negligible = bool(
    previous_residual > 1e-9
    and improvement_ratio < float(negligible_improvement_ratio)
    and current_failed_metric_count >= previous_failed_metric_count
    and current_failed_quarter_count >= previous_failed_quarter_count
  )
  return {
    "previous_total_residual_after_tolerance": float(previous_residual),
    "current_total_residual_after_tolerance": float(current_residual),
    "residual_improvement": float(improvement),
    "residual_improvement_ratio": float(improvement_ratio),
    "previous_failed_metric_count": previous_failed_metric_count,
    "current_failed_metric_count": current_failed_metric_count,
    "previous_failed_quarter_count": previous_failed_quarter_count,
    "current_failed_quarter_count": current_failed_quarter_count,
    "negligible_improvement": negligible,
  }
