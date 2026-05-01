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
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from client_intake_and_finmo.post_intake_mapping import (
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_compact_mapping_lookup_for_levers,
  post_intake_concrete_issue_lever_ids_from_catalog,
  post_intake_direct_target_metric_for_lever,
  post_intake_direct_target_metric_names_for_levers,
  post_intake_driver_target_lever_allowed_for_issue,
  post_intake_driver_target_mapping_entry,
  post_intake_driver_target_mapping_errors,
  post_intake_driver_target_metric_ids,
  post_intake_issue_candidate_lever_ids,
  post_intake_issue_codes,
  post_intake_issue_codes_for_phase,
  post_intake_issue_has_phase,
  post_intake_issue_mapping_contract,
  post_intake_target_metric_names_for_issue,
  post_intake_target_value_kind_for_metric,
)
from client_intake_and_finmo.post_intake_issues import detection as _issue_detection

logger = logging.getLogger(__name__)

_CONVERGENCE_ISSUE_PASS_SCORE_PCT = 80
_CONVERGENCE_ISSUE_WARN_SCORE_PCT = 70
_CONVERGENCE_STRONG_SCORE_PCT = 90
_CONVERGENCE_DEFAULT_QUARTER_COUNT = 20
_CONVERGENCE_MAX_FOCUS_ISSUES = 2
_CONVERGENCE_MAX_FOCUS_QUARTERS = _CONVERGENCE_DEFAULT_QUARTER_COUNT
_CONVERGENCE_MAX_FOCUS_LEVER_FAMILIES = 3
_CONVERGENCE_MAX_FOCUS_LEVERS = 12
_CONVERGENCE_MAX_FOCUS_DRIVER_PATHS = 12
_CONVERGENCE_MAX_FOCUS_METRICS_PER_ISSUE = 2
_CONVERGENCE_PROMPT_METRIC_PACKET_LIMIT = 10
_CONVERGENCE_PROMPT_LEVER_PACKET_LIMIT = 12
_UNIFIED_ACCOUNTING_EQUATION_TOLERANCE = 1.0
_UNIFIED_CATASTROPHIC_LIQUIDITY_FLOOR = -250000.0
_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT = 1
_UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT = 20
_UNIFIED_ALLOWED_TARGET_METRIC_KEYS: Tuple[str, ...] = tuple()
R_AND_D_APPLICABILITY_LEVER_ID = "expenses::Research & Development"
_CASH_PASS_OWNED_ISSUE_CODES = set(post_intake_issue_codes_for_phase("cash_pass"))
_REMAINING_HORIZON_ISSUE_CODES = set(
  post_intake_issue_codes_for_phase("convergence", targeting_allowed=True)
)
_ISSUE_CODE_REGISTRY: Dict[str, Dict[str, Any]] = {
  code: {"title": code}
  for code in post_intake_issue_codes()
}


def _contract_forecast_quarter_count(contract_name: Any = "unified_convergence_decision") -> int:
  count = int(
    post_intake_contract_forecast_horizon_quarter_count(
      contract_name=contract_name,
    )
    or 0
  )
  if count <= 0:
    raise RuntimeError(
      "post_intake_contract_horizon_missing: "
      "post_intake_gpt_contract_lookup must define a positive forecast horizon."
    )
  return count


def _local_safe_int(value: Any) -> int:
  try:
    return int(round(float(value)))
  except Exception:
    return 0


def _assert_issue_quarter_in_contract_horizon(
  *,
  quarter_index: Any,
  issue_code: Any,
  source: str,
  quarter_count: Optional[int] = None,
) -> int:
  parsed = _local_safe_int(quarter_index)
  horizon_count = max(
    1,
    int(quarter_count or _contract_forecast_quarter_count()),
  )
  if parsed < 1 or parsed > horizon_count:
    raise RuntimeError(
      "issue_detection_quarter_out_of_contract_horizon: "
      + json.dumps(
        {
          "issue_code": str(issue_code or "").strip().lower(),
          "quarter_index": parsed,
          "allowed_quarters": list(range(1, horizon_count + 1)),
          "source": str(source or "").strip(),
          "contract_table": "post_intake_gpt_contract_lookup",
          "detail": "Forecast horizon excludes stub Q0; issue detection must not emit Q0 or Q21+.",
        },
        ensure_ascii=False,
      )
    )
  return parsed


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  if not isinstance(dependencies, dict):
    return
  globals().update({
    key: value
    for key, value in dependencies.items()
    if key != "bind_runtime_dependencies"
  })
  _issue_detection.bind_runtime_dependencies(globals())


__all__ = [
  "_financial_story_issue_codes",
  "_issue_registry_entry",
  "_is_known_post_intake_issue_code",
  "_canonical_issue_title",
  "_touched_lever_ids_from_result",
  "_touched_issue_codes_from_result",
  "_normalized_issue_records",
  "_issue_ledger_key",
  "_core_issue_record",
  "_merge_issue_identity_fields",
  "_normalize_realism_verifier_status",
  "_normalize_realism_materiality",
  "_normalize_realism_remaining_quarters",
  "_normalize_realism_lever_ids",
  "_issue_requires_remaining_horizon_scope",
  "_is_cash_pass_owned_issue_code",
  "_is_retired_convergence_issue_record",
  "_filter_cash_pass_owned_issue_records",
  "_remaining_horizon_issue_quarters",
  "_safe_int_in_range",
  "_completion_grade_letter",
  "_safe_divide",
  "_quarter_phase_label",
  "_issue_detail_blob",
  "_zone_repair_geometry",
  "_build_issue_metric_spec",
  "_table_target_currency_metric_spec",
  "_table_target_metric_id_set",
  "_is_table_target_metric_name",
  "_cost_structure_direct_metric_specs_for_quarter",
  "_issue_metric_specs_for_quarter",
  "_issue_metric_specs_for_record",
  "_issue_is_hard_issue",
  "_synthetic_controller_issue_completion_snapshot",
  "_controller_issue_completion_snapshot",
  "_controller_issue_public_record",
  "_build_controller_issue_grade_summary",
  "_convergence_completion_policy_payload",
  "_metric_direction_hint",
  "_severity_minimum_change_pct",
  "_deterministic_lever_bound_value",
  "_metric_equilibrium_target",
  "_metric_target_zone",
  "_issue_impact_weight",
  "_issue_priority_map",
  "_lever_catalog_entry_text",
  "_lever_catalog_entry_matches",
  "_repair_path_type_for_lever",
  "_driver_path_delta_bounds",
  "_repair_metric_delta_bounds",
  "_quarter_days_in_period",
  "_quarter_row_cost_of_goods_sold",
  "_quarter_row_operating_cost_base",
  "_component_delta_to_lever_delta",
  "_driver_target_conversion_context",
  "_metric_target_bounds_constrained_by_driver_scaffold",
  "_spillover_flags_for_metric",
  "_build_convergence_scorecard",
  "_repair_aware_issue_packets",
  "_sample_evenly_spaced_entries",
  "_driver_path_sort_key",
  "_select_focus_driver_paths",
  "_compact_driver_paths_for_prompt",
  "_compact_repair_targets_for_prompt",
  "_compact_repair_envelope_packets_for_prompt",
  "_compact_issue_packets_for_prompt",
  "_compact_numeric_guidance_for_prompt",
  "_unified_target_fill_grid",
  "_locked_targets_by_quarter_response_template",
  "_unified_lever_control_fill_grid",
  "_lever_contract_precision_kind",
  "_full_horizon_model_input_repair_contract",
  "_model_input_repair_cell_schema",
  "_normalize_model_input_repair_cell_value",
  "_validate_and_normalize_model_input_repair_cells",
  "_exact_updates_from_model_input_repair_cells",
  "_convergence_issue_mapping_gate",
  "_compact_current_cycle_packet_for_prompt",
  "_lever_priority_tier",
  "_ordered_quarters_by_preference",
  "_build_unified_numeric_guidance_packet",
  "_controller_resolution_from_verification_issue",
  "_iteration_decision_from_issue_record",
  "_clone_issue_status_records",
  "_controller_issue_effective_status",
  "_controller_issue_is_blocking",
  "_issue_needs_iteration",
  "_normalize_issue_record_to_controller_truth",
  "_refresh_issue_status_records_from_scan",
  "_issue_keys_from_status_records",
  "_issue_keys_requiring_iteration",
  "_filter_issue_status_records",
  "_build_realism_planner_issue_state",
  "_active_issue_codes_from_planner_issue_state",
  "_build_controller_resolution_state_from_issue_ledger",
  "_controller_state_issue_status_records",
  "_controller_state_issue_summaries",
  "_build_strategy_resolved_issue_constraints",
  "_build_strategy_recheck_context_payload",
  "_compact_model_input_for_verification",
  "_build_realism_pass_consistency_context_payload",
  "_build_persisted_realism_memo_payload",
  "_compact_issue_codes",
  "_compact_realism_memo_for_trace",
  "_compact_resolution_summary_for_trace",
  "_sanitize_realism_iteration_trace",
  "_build_resolution_summary_from_issue_ledger",
  "_build_realism_memo_from_issue_ledger",
  "_apply_realism_verification_to_issue_status_records",
  "_merge_new_scan_detected_issues",
  "_issue_severity_label_from_score",
  "_numeric_solver_contract_issue_packet_map",
  "_numeric_solver_contract_baseline_quarter_map",
  "_build_deterministic_issue_packets",
  "_build_issue_packets_from_issue_ledger",
  "_numeric_adjust_actions_contract_error",
  "_normalize_unified_mapped_repair_targets",
  "_declared_mapped_target_metric_names",
  "_repair_target_direct_target_metric_names",
  "_merge_required_target_tolerances",
  "_augment_solver_quarter_target_metrics",
  "_issue_packet_mapped_driver_lever_ids",
  "_deterministic_guidance_focus_issue_codes",
  "_issue_packet_declared_target_metric_names",
  "_table_issue_candidate_lever_ids",
  "_raise_p_and_l_flatline_if_needed",
  "_build_capacity_support_issue_status_records",
  "_p_and_l_flatline_signals",
  "_build_p_and_l_flatline_issue_status_records",
  "_build_stage_maturity_cost_structure_issue_status_records",
]


def _financial_story_issue_codes(controller_resolution_state: Optional[Dict[str, Any]]) -> List[str]:
  controller = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  codes: List[str] = []
  for item in (controller.get("remaining_issues") or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if issue_code and issue_code not in codes:
      codes.append(issue_code)
  return codes

def _issue_registry_entry(issue_code: Any) -> Dict[str, Any]:
  return _ISSUE_CODE_REGISTRY.get(str(issue_code or "").strip().lower(), {})

def _is_known_post_intake_issue_code(issue_code: Any) -> bool:
  return str(issue_code or "").strip().lower() in _ISSUE_CODE_REGISTRY

def _canonical_issue_title(issue_code: Any, fallback: Any) -> str:
  entry = _issue_registry_entry(issue_code)
  title = str(entry.get("title") or "").strip()
  if title:
    return title
  return str(fallback or "").strip()

def _touched_lever_ids_from_result(result_payload: Optional[Dict[str, Any]]) -> List[str]:
  result = result_payload if isinstance(result_payload, dict) else {}
  ids: List[str] = []
  for item in (result.get("applied_updates") or []):
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if lever_id and lever_id not in ids:
      ids.append(lever_id)
  return ids

def _touched_issue_codes_from_result(result_payload: Optional[Dict[str, Any]]) -> List[str]:
  result = result_payload if isinstance(result_payload, dict) else {}
  codes: List[str] = []
  for item in (result.get("applied_updates") or []):
    if not isinstance(item, dict):
      continue
    for raw_code in (item.get("issue_codes") or []):
      issue_code = str(raw_code or "").strip().lower()
      if issue_code and issue_code not in codes:
        codes.append(issue_code)
  return codes

def _normalized_issue_records(items: Any) -> List[Dict[str, str]]:
  out: List[Dict[str, str]] = []
  for item in (items or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    issue = str(item.get("issue") or "").strip()
    detail = str(item.get("detail") or "").strip()
    if not issue_code or not issue or not detail:
      continue
    if not _is_known_post_intake_issue_code(issue_code):
      continue
    record: Dict[str, str] = {"issue": issue, "detail": detail}
    record["issue_code"] = issue_code
    out.append(record)
  return out

def _issue_ledger_key(item: Dict[str, Any]) -> str:
  issue_code = str(item.get("issue_code") or "").strip().lower()
  return f"code::{issue_code}" if issue_code else ""

def _core_issue_record(item: Dict[str, Any]) -> Dict[str, str]:
  issue_code = str(item.get("issue_code") or "").strip().lower()
  record: Dict[str, str] = {
    "issue": _canonical_issue_title(issue_code, item.get("issue")),
    "detail": str(item.get("detail") or "").strip(),
  }
  if issue_code:
    record["issue_code"] = issue_code
  return record

def _merge_issue_identity_fields(
  existing: Dict[str, Any],
  incoming: Dict[str, Any],
) -> Dict[str, Any]:
  merged = copy.deepcopy(existing if isinstance(existing, dict) else {})
  incoming_core = _core_issue_record(incoming if isinstance(incoming, dict) else {})
  incoming_code = str(incoming_core.get("issue_code") or "").strip().lower()
  if incoming_code and not str(merged.get("issue_code") or "").strip():
    merged["issue_code"] = incoming_code
  canonical_title = _canonical_issue_title(incoming_code, incoming_core.get("issue"))
  if canonical_title:
    merged["issue"] = canonical_title
  if incoming_core.get("detail") and not str(merged.get("detail") or "").strip():
    merged["detail"] = incoming_core["detail"]
  for key in (
    "metric_debug",
    "business_world_contract",
    "coherence_failure_signals",
    "business_stage",
    "business_age_months",
    "planning_mode",
  ):
    if key in incoming:
      merged[key] = copy.deepcopy(incoming.get(key))
  return merged

def _normalize_realism_verifier_status(value: Any) -> str:
  status = str(value or "").strip().lower()
  if status in {"resolved", "partially_resolved", "not_resolved"}:
    return status
  return "not_resolved"

def _normalize_realism_materiality(value: Any) -> str:
  materiality = str(value or "").strip().lower()
  if materiality in {"immaterial", "material"}:
    return materiality
  return "material"

def _normalize_realism_remaining_quarters(value: Any) -> List[int]:
  return [
    int(_safe_float(q) or 0)
    for q in (value or [])
    if int(_safe_float(q) or 0) >= 1
  ]

def _normalize_realism_lever_ids(value: Any) -> List[str]:
  return [
    str(lever_id or "").strip()
    for lever_id in (value or [])
    if str(lever_id or "").strip()
  ]

def _issue_requires_remaining_horizon_scope(issue_code: Any) -> bool:
  code = str(issue_code or "").strip().lower()
  if not code:
    return False
  return post_intake_issue_has_phase(code, "convergence")

def _is_cash_pass_owned_issue_code(issue_code: Any) -> bool:
  code = str(issue_code or "").strip().lower()
  if not code:
    return False
  return post_intake_issue_has_phase(code, "cash_pass")

def _is_retired_convergence_issue_record(record: Optional[Dict[str, Any]]) -> bool:
  item = record if isinstance(record, dict) else {}
  issue_code = str(item.get("issue_code") or "").strip().lower()
  if _is_cash_pass_owned_issue_code(issue_code):
    return True
  if issue_code != "cost_structure_mismatch":
    return False
  detail_blob = _issue_detail_blob(item)
  legacy_capex_terms = (
    "capex",
    "capital expenditure",
    "capital expenditures",
    "ppe",
    "asset footprint",
    "equipment",
    "maintenance-like",
    "investment",
  )
  return any(term in detail_blob for term in legacy_capex_terms)

def _filter_cash_pass_owned_issue_records(
  issue_status_records: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  return [
    copy.deepcopy(item)
    for item in (issue_status_records or [])
    if isinstance(item, dict)
    and not _is_cash_pass_owned_issue_code(item.get("issue_code"))
  ]

def _remaining_horizon_issue_quarters(
  *,
  issue_code: Any,
  base_quarters: Optional[List[int]],
  quarter_count: int,
) -> List[int]:
  horizon_count = max(1, int(quarter_count or _contract_forecast_quarter_count()))
  for item in (base_quarters or []):
    parsed = int(_safe_float(item) or 0)
    if parsed < 1:
      continue
    _assert_issue_quarter_in_contract_horizon(
      quarter_index=parsed,
      issue_code=issue_code,
      source="remaining_horizon_issue_quarters.base_quarters",
      quarter_count=horizon_count,
    )
  normalized = sorted(
    {
      int(_safe_float(item) or 0)
      for item in (base_quarters or [])
      if 1 <= int(_safe_float(item) or 0) <= horizon_count
    }
  )
  if not normalized:
    normalized = list(range(1, horizon_count + 1))
  if not _issue_requires_remaining_horizon_scope(issue_code):
    return normalized
  anchor_quarter = min(normalized or [1])
  return list(range(anchor_quarter, horizon_count + 1))

def _safe_int_in_range(value: Any, *, default: int, minimum: int, maximum: int) -> int:
  parsed = _safe_float(value)
  if parsed is None:
    return default
  bounded = int(round(parsed))
  return max(minimum, min(maximum, bounded))

def _completion_grade_letter(score_pct: Any) -> str:
  score = max(0, min(100, int(_safe_float(score_pct) or 0)))
  if score >= _CONVERGENCE_STRONG_SCORE_PCT:
    return "A"
  if score >= _CONVERGENCE_ISSUE_PASS_SCORE_PCT:
    return "B"
  if score >= _CONVERGENCE_ISSUE_WARN_SCORE_PCT:
    return "C"
  return "D"

def _safe_divide(numerator: Any, denominator: Any) -> Optional[float]:
  left = _safe_float(numerator)
  right = _safe_float(denominator)
  if left is None or right is None or abs(float(right)) <= 1e-9:
    return None
  return float(left) / float(right)

def _quarter_phase_label(quarter_index: Any) -> str:
  quarter = int(_safe_float(quarter_index) or 0)
  if quarter <= 4:
    return "early"
  if quarter <= 8:
    return "mid"
  return "late"

def _issue_detail_blob(record: Optional[Dict[str, Any]]) -> str:
  item = record if isinstance(record, dict) else {}
  return " ".join(
    part
    for part in (
      str(item.get("issue") or "").strip(),
      str(item.get("detail") or "").strip(),
      str(item.get("root_cause") or "").strip(),
      str(item.get("verification_reason") or "").strip(),
    )
    if part
  ).strip().lower()

def _zone_repair_geometry(
  actual_value: Any,
  *,
  target_floor: Any = None,
  target_ceiling: Any = None,
  score_scale: Any = None,
  preferred_direction: Any = None,
) -> Dict[str, Any]:
  actual = _safe_float(actual_value)
  if actual is None:
    return {}
  floor_value = _safe_float(target_floor)
  ceiling_value = _safe_float(target_ceiling)
  if floor_value is not None and ceiling_value is not None and float(floor_value) > float(ceiling_value):
    floor_value, ceiling_value = ceiling_value, floor_value
  direction_hint = str(preferred_direction or "").strip().lower()
  if direction_hint not in {"increase", "decrease"}:
    direction_hint = "hold"
  boundary_value = float(actual)
  gap_signed = 0.0
  within_boundary = True
  if floor_value is not None and float(actual) < float(floor_value) - 1e-9:
    direction_hint = "increase"
    boundary_value = float(floor_value)
    gap_signed = float(actual) - float(floor_value)
    within_boundary = False
  elif ceiling_value is not None and float(actual) > float(ceiling_value) + 1e-9:
    direction_hint = "decrease"
    boundary_value = float(ceiling_value)
    gap_signed = float(actual) - float(ceiling_value)
    within_boundary = False
  gap_abs = abs(float(gap_signed))
  scale_hint = max(
    abs(float(_safe_float(score_scale) or 0.0)),
    abs(float(ceiling_value or 0.0) - float(floor_value or 0.0)),
    1e-9,
  )
  if within_boundary:
    score_pct = 100.0
    min_required_delta = 0.0
    recommended_delta = 0.0
    max_feasible_delta = 0.0
  else:
    score_pct = max(0.0, 100.0 - min(100.0, (gap_abs / max(scale_hint, 1e-9)) * 100.0))
    min_required_delta = float(boundary_value - float(actual))
    recommended_delta = float(min_required_delta * 1.25)
    max_feasible_delta = float(min_required_delta * 2.0)
  return {
    "direction_hint": direction_hint,
    "target_floor": float(floor_value) if floor_value is not None else None,
    "target_ceiling": float(ceiling_value) if ceiling_value is not None else None,
    "acceptable_zone": {
      "minimum": float(floor_value) if floor_value is not None else None,
      "maximum": float(ceiling_value) if ceiling_value is not None else None,
    },
    "boundary_value": float(boundary_value),
    "gap": float(gap_signed),
    "gap_abs": float(gap_abs),
    "score_scale": float(scale_hint),
    "score_pct": float(score_pct),
    "within_boundary": bool(within_boundary),
    "repair_envelope": {
      "min_required_delta": float(min_required_delta),
      "recommended_delta": float(recommended_delta),
      "max_feasible_delta": float(max_feasible_delta),
    },
  }

def _build_issue_metric_spec(
  metric_name: str,
  *,
  actual_value: Any,
  target_floor: Any = None,
  target_ceiling: Any = None,
  score_scale: Any = None,
  source_metric_names: Optional[List[str]] = None,
  metric_definition: str = "",
  unit_kind: str = "ratio",
) -> Optional[Dict[str, Any]]:
  actual = _safe_float(actual_value)
  if actual is None:
    return None
  geometry = _zone_repair_geometry(
    actual,
    target_floor=target_floor,
    target_ceiling=target_ceiling,
    score_scale=score_scale,
  )
  if not geometry:
    return None
  return {
    "metric_name": str(metric_name or "").strip().lower(),
    "actual_value": float(actual),
    "target_floor": geometry.get("target_floor"),
    "target_ceiling": geometry.get("target_ceiling"),
    "acceptable_zone": copy.deepcopy(geometry.get("acceptable_zone") or {}),
    "boundary_value": _safe_float(geometry.get("boundary_value")),
    "direction_hint": str(geometry.get("direction_hint") or "").strip(),
    "gap": _safe_float(geometry.get("gap")),
    "gap_abs": float(_safe_float(geometry.get("gap_abs")) or 0.0),
    "score_pct": max(0.0, min(100.0, float(_safe_float(geometry.get("score_pct")) or 0.0))),
    "score_scale": float(_safe_float(geometry.get("score_scale")) or 0.0),
    "repair_envelope": copy.deepcopy(geometry.get("repair_envelope") or {}),
    "within_boundary": bool(geometry.get("within_boundary")),
    "source_metric_names": [
      str(item).strip().lower()
      for item in (source_metric_names or [])
      if str(item).strip()
    ],
    "metric_definition": str(metric_definition or "").strip(),
    "unit_kind": str(unit_kind or "").strip().lower() or "ratio",
  }

def _table_target_currency_metric_spec(
  metric_name: str,
  *,
  actual_value: Any,
  target_floor: Any = None,
  target_ceiling: Any = None,
  score_scale: Any = None,
  source_metric_names: Optional[List[str]] = None,
  metric_definition: str = "",
) -> Optional[Dict[str, Any]]:
  metric = str(metric_name or "").strip().lower()
  if not _is_table_target_metric_name(metric):
    return None
  return _build_issue_metric_spec(
    metric,
    actual_value=actual_value,
    target_floor=target_floor,
    target_ceiling=target_ceiling,
    score_scale=score_scale,
    source_metric_names=source_metric_names,
    metric_definition=metric_definition,
    unit_kind="currency",
  )

def _table_target_metric_id_set() -> set[str]:
  return {
    str(item or "").strip().lower()
    for item in post_intake_driver_target_metric_ids(phase=None)
    if str(item or "").strip()
  }

def _is_table_target_metric_name(metric_name: Any) -> bool:
  return str(metric_name or "").strip().lower() in _table_target_metric_id_set()

def _issue_allowed_target_metric_names(issue_code: Any, *, phase: str) -> set[str]:
  return {
    str(item or "").strip().lower()
    for item in post_intake_target_metric_names_for_issue(issue_code, phase=phase)
    if str(item or "").strip()
  }

def _issue_metric_specs_for_record(
  record: Optional[Dict[str, Any]],
  *,
  current_finmo_json: Optional[Dict[str, Any]],
  quarter_count: int,
) -> List[Dict[str, Any]]:
  item = record if isinstance(record, dict) else {}
  issue_code = str(item.get("issue_code") or "").strip().lower()
  if not issue_code or not isinstance(current_finmo_json, dict):
    return []
  horizon_count = max(1, int(quarter_count or _contract_forecast_quarter_count()))
  explicit_specs: List[Dict[str, Any]] = []
  for spec in (item.get("metric_debug") or []):
    if (
      not isinstance(spec, dict)
      or not str(spec.get("metric_name") or "").strip()
      or not _is_table_target_metric_name(spec.get("metric_name"))
    ):
      continue
    quarter_index = _assert_issue_quarter_in_contract_horizon(
      quarter_index=spec.get("quarter_index"),
      issue_code=issue_code,
      source="issue_record.metric_debug",
      quarter_count=horizon_count,
    )
    normalized_spec = copy.deepcopy(spec)
    normalized_spec["quarter_index"] = int(quarter_index)
    explicit_specs.append(normalized_spec)
  if explicit_specs:
    return explicit_specs
  finmo_rows = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in ((current_finmo_json.get("quarter_rows") or []) if isinstance(current_finmo_json.get("quarter_rows"), list) else [])
    if isinstance(row, dict) and 1 <= int(_safe_float(row.get("quarter_index")) or 0) <= horizon_count
  }
  relevant_quarters = sorted(
    {
      int(_safe_float(entry) or 0)
      for entry in (_normalize_realism_remaining_quarters(item.get("remaining_problem_quarters")) or [])
      if int(_safe_float(entry) or 0) >= 1
    }
  )
  for quarter_index in relevant_quarters:
    _assert_issue_quarter_in_contract_horizon(
      quarter_index=quarter_index,
      issue_code=issue_code,
      source="issue_record.remaining_problem_quarters",
      quarter_count=horizon_count,
    )
  if relevant_quarters:
    relevant_quarters = _remaining_horizon_issue_quarters(
      issue_code=issue_code,
      base_quarters=relevant_quarters,
      quarter_count=horizon_count,
    )
  if not relevant_quarters:
    fallback_quarters = sorted(finmo_rows.keys()) or list(range(1, horizon_count + 1))
    if _issue_requires_remaining_horizon_scope(issue_code):
      relevant_quarters = _remaining_horizon_issue_quarters(
        issue_code=issue_code,
        base_quarters=fallback_quarters,
        quarter_count=horizon_count,
      )
    else:
      relevant_quarters = fallback_quarters[: max(1, min(_CONVERGENCE_MAX_FOCUS_QUARTERS, horizon_count))]
  if not relevant_quarters:
    if _issue_requires_remaining_horizon_scope(issue_code):
      relevant_quarters = _remaining_horizon_issue_quarters(
        issue_code=issue_code,
        base_quarters=[],
        quarter_count=horizon_count,
      )
    else:
      relevant_quarters = list(range(1, horizon_count + 1))[: _CONVERGENCE_MAX_FOCUS_QUARTERS]
  metric_specs: List[Dict[str, Any]] = []
  quarter_spec_map: Dict[int, List[Dict[str, Any]]] = {}
  for quarter_index in relevant_quarters:
    specs = _issue_metric_specs_for_quarter(
      issue_code=issue_code,
      quarter_index=quarter_index,
      quarter_row=finmo_rows.get(quarter_index) or {},
    )
    if not specs:
      continue
    specs.sort(
      key=lambda spec: (
        bool(spec.get("within_boundary")),
        -float(_safe_float(spec.get("gap_abs")) or 0.0),
        str(spec.get("metric_name") or "").strip(),
      )
    )
    selected_specs = specs[: _CONVERGENCE_MAX_FOCUS_METRICS_PER_ISSUE]
    quarter_spec_map[quarter_index] = selected_specs
  if not quarter_spec_map:
    return []
  failing_quarters = [
    quarter_index
    for quarter_index, specs in sorted(quarter_spec_map.items())
    if any(not bool(spec.get("within_boundary")) for spec in specs)
  ]
  if _issue_requires_remaining_horizon_scope(issue_code):
    focused_quarters = failing_quarters or sorted(quarter_spec_map.keys())
  else:
    focused_quarters = (failing_quarters or sorted(quarter_spec_map.keys()))[: _CONVERGENCE_MAX_FOCUS_QUARTERS]
  for quarter_index in focused_quarters:
    for spec in (quarter_spec_map.get(quarter_index) or []):
      enriched_spec = copy.deepcopy(spec)
      enriched_spec["quarter_index"] = int(quarter_index)
      metric_specs.append(enriched_spec)
  return metric_specs

def _issue_is_hard_issue(
  record: Optional[Dict[str, Any]],
  *,
  metric_specs: Optional[List[Dict[str, Any]]] = None,
) -> bool:
  item = record if isinstance(record, dict) else {}
  issue_code = str(item.get("issue_code") or "").strip().lower()
  detail_blob = _issue_detail_blob(item)
  if issue_code in {"accounting_integrity_failure", "structural_impossibility"}:
    return True
  if "accounting" in detail_blob and ("integrity" in detail_blob or "equation" in detail_blob):
    return True
  if "structural impossib" in detail_blob:
    return True
  return False

def _issue_mapping_contract_or_fail(
  issue_code: Any,
  *,
  phase: Any = "convergence",
  require_mapping: bool = True,
) -> Dict[str, Any]:
  code = str(issue_code or "").strip().lower()
  if not code:
    return {}
  if code in {"accounting_integrity_failure", "structural_impossibility"}:
    return {
      "issue_code": code,
      "mapping_source": "hard_gate_no_repair_mapping",
      "candidate_lever_ids": [],
      "next_required_lever_ids": [],
      "target_metric_names": [],
      "metric_targets": [],
      "mapping_rows": [],
    }
  if _is_cash_pass_owned_issue_code(code):
    phase = "cash_pass"
  contract = post_intake_issue_mapping_contract(
    code,
    phase=phase,
    require=require_mapping,
  )
  if require_mapping and not (contract.get("candidate_lever_ids") or []):
    raise RuntimeError(
      "post_intake_issue_detection_mapping_required: "
      f"{code} has no issue-to-driver mapping in post_intak_mapping_lookup."
    )
  if require_mapping and not (contract.get("target_metric_names") or contract.get("metric_targets") or []):
    raise RuntimeError(
      "post_intake_issue_detection_target_mapping_required: "
      f"{code} has no issue-to-target mapping in post_intak_mapping_lookup."
    )
  return contract

def _synthetic_controller_issue_completion_snapshot(
  item: Optional[Dict[str, Any]],
  *,
  quarter_count: int = _CONVERGENCE_DEFAULT_QUARTER_COUNT,
) -> Dict[str, Any]:
  record = item if isinstance(item, dict) else {}
  total_quarters = max(1, int(_safe_float(quarter_count) or _CONVERGENCE_DEFAULT_QUARTER_COUNT))
  verifier_status = _normalize_realism_verifier_status(record.get("verifier_status"))
  materiality = _normalize_realism_materiality(record.get("remaining_issue_materiality"))
  severity = _safe_int_in_range(
    record.get("remaining_issue_severity_score"),
    default=100 if verifier_status == "not_resolved" else 50,
    minimum=0,
    maximum=100,
  )
  remaining_quarters = _normalize_realism_remaining_quarters(record.get("remaining_problem_quarters"))
  next_levers = _normalize_realism_lever_ids(record.get("next_required_lever_ids"))
  issue_code = str(record.get("issue_code") or "").strip().lower()
  affected_quarters = (
    remaining_quarters
    if remaining_quarters
    else list(range(1, total_quarters + 1))
    if verifier_status != "resolved"
    else []
  )
  affected_set = set(affected_quarters)
  if verifier_status == "resolved":
    completion_score_pct = 100
  else:
    completion_score_pct = max(0, 100 - severity)
    if verifier_status == "partially_resolved":
      completion_score_pct = min(100, completion_score_pct + 5)
    if materiality == "immaterial":
      completion_score_pct = min(100, completion_score_pct + 10)
    if not next_levers:
      completion_score_pct = min(100, completion_score_pct + 5)
    if verifier_status == "not_resolved" and not remaining_quarters:
      completion_score_pct = max(0, completion_score_pct - 10)
  completion_score_pct = max(0, min(100, int(round(completion_score_pct))))
  quarter_scores = [
    {
      "quarter_index": quarter_index,
      "score_pct": completion_score_pct if quarter_index in affected_set else 100,
      "counts_toward_issue": quarter_index in affected_set,
    }
    for quarter_index in range(1, total_quarters + 1)
  ]
  lowest_affected_score_pct = (
    min(
      int(_safe_float(entry.get("score_pct")) or 0)
      for entry in quarter_scores
      if entry.get("counts_toward_issue")
    )
    if affected_quarters
    else 100
  )
  average_relevant_score_pct = lowest_affected_score_pct if affected_quarters else 100
  meets_pass_threshold = lowest_affected_score_pct >= _CONVERGENCE_ISSUE_PASS_SCORE_PCT
  effective_status = (
    "resolved"
    if verifier_status == "resolved"
    else "tolerated"
    if meets_pass_threshold
    else "open"
  )
  return {
    "issue_code": issue_code,
    "verifier_status": verifier_status,
    "effective_status": effective_status,
    "blocking": effective_status == "open",
    "remaining_issue_materiality": materiality,
    "remaining_issue_severity_score": severity,
    "completion_score_pct": completion_score_pct,
    "average_relevant_score_pct": average_relevant_score_pct,
    "completion_grade": _completion_grade_letter(completion_score_pct),
    "pass_threshold_pct": _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
    "warn_threshold_pct": _CONVERGENCE_ISSUE_WARN_SCORE_PCT,
    "affected_quarters": affected_quarters,
    "relevant_quarters": copy.deepcopy(affected_quarters),
    "quarter_scores": quarter_scores,
    "lowest_affected_score_pct": lowest_affected_score_pct,
    "lowest_relevant_score_pct": lowest_affected_score_pct,
    "aggregate_gap_abs": None,
    "aggregate_gap": None,
    "hard_issue": False,
    "metric_debug": [],
    "next_required_lever_ids": next_levers,
    "closure_reasons": [],
  }

def _controller_issue_completion_snapshot(
  item: Optional[Dict[str, Any]],
  *,
  quarter_count: int = _CONVERGENCE_DEFAULT_QUARTER_COUNT,
  current_finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  record = item if isinstance(item, dict) else {}
  total_quarters = max(1, int(_safe_float(quarter_count) or _CONVERGENCE_DEFAULT_QUARTER_COUNT))
  verifier_status = _normalize_realism_verifier_status(record.get("verifier_status"))
  materiality = _normalize_realism_materiality(record.get("remaining_issue_materiality"))
  severity = _safe_int_in_range(
    record.get("remaining_issue_severity_score"),
    default=100 if verifier_status == "not_resolved" else 50,
    minimum=0,
    maximum=100,
  )
  next_levers = _normalize_realism_lever_ids(record.get("next_required_lever_ids"))
  metric_specs = _issue_metric_specs_for_record(
    record,
    current_finmo_json=current_finmo_json,
    quarter_count=total_quarters,
  )
  if not metric_specs:
    return _synthetic_controller_issue_completion_snapshot(
      record,
      quarter_count=total_quarters,
    )

  relevant_quarters = sorted(
    {
      int(_safe_float(spec.get("quarter_index")) or 0)
      for spec in metric_specs
      if int(_safe_float(spec.get("quarter_index")) or 0) >= 1
    }
  )
  quarter_score_map: Dict[int, List[float]] = {}
  for spec in metric_specs:
    quarter_index = int(_safe_float(spec.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    quarter_score_map.setdefault(quarter_index, []).append(float(_safe_float(spec.get("score_pct")) or 0.0))
  quarter_scores = []
  for quarter_index in range(1, total_quarters + 1):
    scores = quarter_score_map.get(quarter_index) or []
    counts_toward_issue = quarter_index in set(relevant_quarters)
    quarter_score = int(round(sum(scores) / len(scores))) if scores else (100 if not counts_toward_issue else 0)
    quarter_scores.append(
      {
        "quarter_index": quarter_index,
        "score_pct": quarter_score if counts_toward_issue else 100,
        "counts_toward_issue": counts_toward_issue,
      }
    )
  relevant_scores = [
    int(_safe_float(entry.get("score_pct")) or 0)
    for entry in quarter_scores
    if entry.get("counts_toward_issue")
  ]
  average_relevant_score_pct = (
    int(round(sum(relevant_scores) / len(relevant_scores)))
    if relevant_scores
    else 100
  )
  lowest_relevant_score_pct = min(relevant_scores) if relevant_scores else 100
  hard_issue = _issue_is_hard_issue(record, metric_specs=metric_specs)
  aggregate_gap = float(
    sum(
      float(_safe_float(spec.get("gap")) or 0.0)
      for spec in metric_specs
    )
  )
  aggregate_gap_abs = float(
    sum(
      abs(float(_safe_float(spec.get("gap")) or 0.0))
      for spec in metric_specs
    )
  )
  closure_reasons: List[str] = []
  if hard_issue and any(not bool(spec.get("within_boundary")) for spec in metric_specs):
    closure_reasons.append("hard_issue_any_failed_quarter_keeps_issue_open")
  if lowest_relevant_score_pct < _CONVERGENCE_ISSUE_WARN_SCORE_PCT:
    closure_reasons.append("quarter_floor_not_met")
  if average_relevant_score_pct < _CONVERGENCE_ISSUE_PASS_SCORE_PCT:
    closure_reasons.append("average_issue_score_below_closure_threshold")
  all_metric_specs_within_boundary = all(bool(spec.get("within_boundary")) for spec in metric_specs)
  if verifier_status == "resolved":
    effective_status = "resolved"
  elif hard_issue:
    effective_status = (
      "resolved"
      if all_metric_specs_within_boundary
      else "open"
    )
  elif all_metric_specs_within_boundary:
    effective_status = "resolved"
  elif (
    lowest_relevant_score_pct >= _CONVERGENCE_ISSUE_WARN_SCORE_PCT
    and average_relevant_score_pct >= _CONVERGENCE_ISSUE_PASS_SCORE_PCT
  ):
    effective_status = "tolerated"
  else:
    effective_status = "open"
  completion_score_pct = average_relevant_score_pct
  return {
    "issue_code": str(record.get("issue_code") or "").strip().lower(),
    "verifier_status": verifier_status,
    "effective_status": effective_status,
    "blocking": effective_status == "open",
    "remaining_issue_materiality": materiality,
    "remaining_issue_severity_score": severity,
    "completion_score_pct": completion_score_pct,
    "average_relevant_score_pct": average_relevant_score_pct,
    "completion_grade": _completion_grade_letter(completion_score_pct),
    "pass_threshold_pct": _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
    "warn_threshold_pct": _CONVERGENCE_ISSUE_WARN_SCORE_PCT,
    "affected_quarters": copy.deepcopy(relevant_quarters),
    "relevant_quarters": copy.deepcopy(relevant_quarters),
    "quarter_scores": quarter_scores,
    "lowest_affected_score_pct": lowest_relevant_score_pct,
    "lowest_relevant_score_pct": lowest_relevant_score_pct,
    "aggregate_gap": aggregate_gap,
    "aggregate_gap_abs": aggregate_gap_abs,
    "hard_issue": hard_issue,
    "metric_debug": copy.deepcopy(metric_specs),
    "next_required_lever_ids": next_levers,
    "closure_reasons": closure_reasons,
  }

def _controller_issue_public_record(
  item: Optional[Dict[str, Any]],
  *,
  quarter_count: int = _CONVERGENCE_DEFAULT_QUARTER_COUNT,
  current_finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  record = item if isinstance(item, dict) else {}
  public_record: Dict[str, Any] = _core_issue_record(record)
  snapshot = _controller_issue_completion_snapshot(
    record,
    quarter_count=quarter_count,
    current_finmo_json=current_finmo_json,
  )
  public_record["verifier_status"] = snapshot.get("verifier_status")
  public_record["effective_status"] = snapshot.get("effective_status")
  public_record["completion_score_pct"] = snapshot.get("completion_score_pct")
  public_record["average_relevant_score_pct"] = snapshot.get("average_relevant_score_pct")
  public_record["lowest_relevant_score_pct"] = snapshot.get("lowest_relevant_score_pct")
  public_record["completion_grade"] = snapshot.get("completion_grade")
  public_record["pass_threshold_pct"] = snapshot.get("pass_threshold_pct")
  public_record["remaining_issue_materiality"] = snapshot.get("remaining_issue_materiality")
  public_record["remaining_issue_severity_score"] = snapshot.get("remaining_issue_severity_score")
  public_record["remaining_problem_quarters"] = copy.deepcopy(snapshot.get("affected_quarters") or [])
  public_record["relevant_quarters"] = copy.deepcopy(snapshot.get("relevant_quarters") or [])
  public_record["aggregate_gap"] = _safe_float(snapshot.get("aggregate_gap"))
  public_record["aggregate_gap_abs"] = _safe_float(snapshot.get("aggregate_gap_abs"))
  public_record["hard_issue"] = bool(snapshot.get("hard_issue"))
  public_record["closure_reasons"] = copy.deepcopy(snapshot.get("closure_reasons") or [])
  public_record["metric_debug"] = copy.deepcopy(snapshot.get("metric_debug") or [])
  public_record["next_required_lever_ids"] = copy.deepcopy(snapshot.get("next_required_lever_ids") or [])
  return public_record

def _build_controller_issue_grade_summary(
  issue_status_records: Optional[List[Dict[str, Any]]],
  *,
  quarter_count: int = _CONVERGENCE_DEFAULT_QUARTER_COUNT,
  current_finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  total_quarters = max(1, int(_safe_float(quarter_count) or _CONVERGENCE_DEFAULT_QUARTER_COUNT))
  quarter_scores: Dict[int, int] = {
    quarter_index: 100
    for quarter_index in range(1, total_quarters + 1)
  }
  quarter_issue_codes: Dict[int, List[str]] = {
    quarter_index: []
    for quarter_index in range(1, total_quarters + 1)
  }
  issue_scores: List[int] = []

  for item in _clone_issue_status_records(issue_status_records):
    snapshot = _controller_issue_completion_snapshot(
      item,
      quarter_count=total_quarters,
      current_finmo_json=current_finmo_json,
    )
    issue_scores.append(int(snapshot.get("completion_score_pct") or 0))
    issue_code = str(snapshot.get("issue_code") or "").strip().lower()
    for entry in (snapshot.get("quarter_scores") or []):
      if not isinstance(entry, dict) or not entry.get("counts_toward_issue"):
        continue
      quarter_index = int(_safe_float(entry.get("quarter_index")) or 0)
      if quarter_index < 1 or quarter_index > total_quarters:
        continue
      score_pct = max(0, min(100, int(_safe_float(entry.get("score_pct")) or 0)))
      quarter_scores[quarter_index] = min(quarter_scores.get(quarter_index, 100), score_pct)
      if issue_code and issue_code not in quarter_issue_codes[quarter_index]:
        quarter_issue_codes[quarter_index].append(issue_code)

  quarter_scorecard = [
    {
      "quarter_index": quarter_index,
      "score_pct": quarter_scores[quarter_index],
      "grade": _completion_grade_letter(quarter_scores[quarter_index]),
      "issue_codes": copy.deepcopy(quarter_issue_codes[quarter_index]),
      "passes_threshold": quarter_scores[quarter_index] >= _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
    }
    for quarter_index in range(1, total_quarters + 1)
  ]
  failing_quarters = [
    int(entry.get("quarter_index") or 0)
    for entry in quarter_scorecard
    if int(_safe_float(entry.get("score_pct")) or 0) < _CONVERGENCE_ISSUE_PASS_SCORE_PCT
  ]
  lowest_quarter_score_pct = min(quarter_scores.values()) if quarter_scores else 100
  average_issue_score_pct = (
    int(round(sum(issue_scores) / len(issue_scores)))
    if issue_scores
    else 100
  )
  overall_completion_score_pct = int(
    round(
      (average_issue_score_pct * _CONVERGENCE_OVERALL_SCORE_ISSUE_WEIGHT)
      + (lowest_quarter_score_pct * _CONVERGENCE_OVERALL_SCORE_LOWEST_QUARTER_WEIGHT)
    )
  )
  overall_completion_score_pct = max(0, min(100, overall_completion_score_pct))
  return {
    "contract_version": "controller_issue_grade_summary_v1",
    "grade_pass_threshold_pct": _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
    "grade_warn_threshold_pct": _CONVERGENCE_ISSUE_WARN_SCORE_PCT,
    "overall_completion_score_pct": overall_completion_score_pct,
    "overall_completion_grade": _completion_grade_letter(overall_completion_score_pct),
    "average_issue_score_pct": average_issue_score_pct,
    "lowest_quarter_score_pct": lowest_quarter_score_pct,
    "lowest_quarter_grade": _completion_grade_letter(lowest_quarter_score_pct),
    "passing_quarter_count": total_quarters - len(failing_quarters),
    "failing_quarter_count": len(failing_quarters),
    "failing_quarters": failing_quarters,
    "quarter_scorecard": quarter_scorecard,
  }

def _convergence_completion_policy_payload() -> Dict[str, Any]:
  return {
    "contract_version": "convergence_completion_policy_v1",
    "issue_pass_threshold_pct": _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
    "warn_threshold_pct": _CONVERGENCE_ISSUE_WARN_SCORE_PCT,
    "strong_threshold_pct": _CONVERGENCE_STRONG_SCORE_PCT,
    "quarter_hard_floor_rule": (
      "Only relevant quarters count. Non-hard issues stay open if any relevant quarter scores below the quarter floor."
    ),
    "practical_rule": (
      "The system is aiming for viable forecasting realism, not fake precision. Graded issues can close when each relevant quarter clears the floor and the issue-average score clears the closure threshold."
    ),
  }

def _metric_direction_hint(
  metric_name: Any,
  *,
  issue_code: Any = None,
  current_value: Any = None,
) -> str:
  metric = str(metric_name or "").strip().lower()
  issue = str(issue_code or "").strip().lower()

  issue_metric_overrides = {
    ("cost_structure_mismatch", "marketing"): "decrease",
    ("cost_structure_mismatch", "cogs"): "decrease",
    ("cost_structure_mismatch", "cost_of_goods_sold"): "decrease",
    ("cost_structure_mismatch", "research_and_development"): "decrease",
    ("cost_structure_mismatch", "lease_rent"): "decrease",
    ("cost_structure_mismatch", "g_and_a"): "decrease",
  }
  override = issue_metric_overrides.get((issue, metric))
  if override:
    return override

  if metric in {
    "revenue",
    "gross_profit",
    "ebitda",
    "net_income",
    "ending_cash",
    "operating_cash_flow",
    "current_assets",
    "ppe",
    "owners_capital",
    "other_equity",
  }:
    return "increase"
  if metric in {
    "current_liabilities",
    "total_liabilities",
    "g_and_a",
    "lease_rent",
    "capital_expenditures",
    "distributions",
  }:
    return "decrease"
  return "either"

def _severity_minimum_change_pct(severity_score: Any) -> float:
  severity = int(_safe_float(severity_score) or 0)
  if severity >= 85:
    return 0.35
  if severity >= 60:
    return 0.20
  return 0.10

def _deterministic_lever_bound_value(
  *,
  lever_id: str,
  raw_value: float,
  ratio_like_value: bool,
  bound_side: str,
) -> float:
  value = float(raw_value)
  if ratio_like_value:
    return round(value, 2)
  if str(lever_id or "").strip().lower().endswith("::unit price"):
    increment = 25.0
    if str(bound_side or "").strip().lower() == "min":
      return int(math.floor(value / increment) * increment)
    return int(math.ceil(value / increment) * increment)
  return int(round(value))

def _metric_equilibrium_target(
  metric_name: Any,
  current_value: Any,
  direction_hint: str,
  *,
  minimum_absolute_change: Optional[float] = None,
) -> Optional[float]:
  metric = str(metric_name or "").strip().lower()
  value = float(_safe_float(current_value) or 0.0)
  minimum_change = float(_safe_float(minimum_absolute_change) or 0.0)
  if metric in {"ending_cash", "ebitda", "net_income", "operating_cash_flow"}:
    if direction_hint == "increase" and value < 0:
      return 0.0
  if metric in {"current_liabilities", "total_liabilities"}:
    if direction_hint == "decrease" and value > 0:
      return 0.0
  if direction_hint == "increase" and minimum_change > 0:
    return value + minimum_change
  if direction_hint == "decrease" and minimum_change > 0:
    return value - minimum_change
  return None

def _metric_target_zone(
  *,
  metric_name: Any,
  current_value: Any,
  direction_hint: str,
  equilibrium_target: Optional[float],
  minimum_absolute_change: Optional[float],
) -> Dict[str, Any]:
  metric = str(metric_name or "").strip().lower()
  current = float(_safe_float(current_value) or 0.0)
  minimum_change = max(float(_safe_float(minimum_absolute_change) or 0.0), 1.0)
  zone_padding = max(minimum_change * 0.35, 1.0)
  target_floor: Optional[float] = None
  target_ceiling: Optional[float] = None
  gap: Optional[float] = None
  min_required_delta: Optional[float] = None
  recommended_delta: Optional[float] = None
  max_feasible_delta: Optional[float] = None

  if direction_hint == "increase":
    target_floor = float(equilibrium_target) if equilibrium_target is not None else current + minimum_change
    if metric in {"ending_cash", "ebitda", "net_income", "operating_cash_flow"}:
      target_floor = max(target_floor, 0.0)
    target_ceiling = target_floor + zone_padding
    gap = current - target_floor
    min_required_delta = max(target_floor - current, 0.0)
    recommended_delta = max(min_required_delta * 1.25, minimum_change)
    max_feasible_delta = max(recommended_delta * 2.0, min_required_delta * 1.75, minimum_change * 2.5)
  elif direction_hint == "decrease":
    target_ceiling = float(equilibrium_target) if equilibrium_target is not None else current - minimum_change
    target_floor = target_ceiling - zone_padding
    gap = current - target_ceiling
    min_required_delta = min(target_ceiling - current, 0.0)
    recommended_delta = min(min_required_delta * 1.25, -minimum_change)
    max_feasible_delta = min(recommended_delta * 2.0, min_required_delta * 1.75, -minimum_change * 2.5)
  else:
    anchor = float(equilibrium_target) if equilibrium_target is not None else current
    target_floor = anchor - zone_padding
    target_ceiling = anchor + zone_padding
    gap = current - anchor
    min_required_delta = anchor - current
    recommended_delta = min_required_delta * 1.2 if abs(min_required_delta) > 0 else 0.0
    max_feasible_delta = recommended_delta * 2.0 if abs(recommended_delta) > 0 else zone_padding

  return {
    "target_floor": float(target_floor) if target_floor is not None else None,
    "target_ceiling": float(target_ceiling) if target_ceiling is not None else None,
    "acceptable_zone": {
      "minimum": float(min(target_floor, target_ceiling))
      if target_floor is not None and target_ceiling is not None
      else None,
      "maximum": float(max(target_floor, target_ceiling))
      if target_floor is not None and target_ceiling is not None
      else None,
    },
    "gap": float(gap) if gap is not None else None,
    "repair_envelope": {
      "min_required_delta": float(min_required_delta) if min_required_delta is not None else None,
      "recommended_delta": float(recommended_delta) if recommended_delta is not None else None,
      "max_feasible_delta": float(max_feasible_delta) if max_feasible_delta is not None else None,
    },
  }

def _issue_impact_weight(severity_score: Any) -> int:
  severity = max(0.0, min(100.0, float(_safe_float(severity_score) or 0.0)))
  return max(1, min(5, int(round(severity / 20.0)) or 1))

def _issue_priority_map(issue_packets: Optional[List[Dict[str, Any]]]) -> Dict[str, int]:
  ranked_packets = [
    item for item in (issue_packets or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  ranked_packets.sort(
    key=lambda item: (
      -int(_safe_float(item.get("remaining_issue_severity_score")) or 0),
      str(item.get("issue_code") or "").strip().lower(),
    )
  )
  priority_map: Dict[str, int] = {}
  for index, packet in enumerate(ranked_packets, start=1):
    issue_code = str(packet.get("issue_code") or "").strip().lower()
    if issue_code and issue_code not in priority_map:
      priority_map[issue_code] = index
  return priority_map

def _lever_catalog_entry_text(entry: Optional[Dict[str, Any]]) -> str:
  item = entry if isinstance(entry, dict) else {}
  return " ".join(
    str(part or "").strip().lower()
    for part in (
      item.get("lever_id"),
      item.get("section"),
      item.get("label"),
      item.get("label_path"),
      item.get("driver"),
      item.get("input_semantics"),
      item.get("accounting_role"),
    )
    if str(part or "").strip()
  ).strip()

def _lever_catalog_entry_matches(entry: Optional[Dict[str, Any]], terms: List[str]) -> bool:
  haystack = _lever_catalog_entry_text(entry)
  return any(str(term or "").strip().lower() in haystack for term in (terms or []) if str(term or "").strip())

def _repair_path_type_for_lever(
  *,
  metric_name: Any,
  lever_id: Any,
  accounting_role: Any = None,
  source_metric_names: Optional[List[str]] = None,
) -> Tuple[str, str]:
  metric = str(metric_name or "").strip().lower()
  direct_target_metric = str(post_intake_direct_target_metric_for_lever(lever_id) or "").strip().lower()
  if metric and direct_target_metric and metric == direct_target_metric:
    return "direct", "high"
  return "unmapped", "none"

def _driver_path_delta_bounds(
  *,
  direction_hint: str,
  baseline_value: Any,
  suggested_min_value: Any,
  suggested_max_value: Any,
) -> Tuple[Optional[float], Optional[float]]:
  baseline = float(_safe_float(baseline_value) or 0.0)
  minimum_value = _safe_float(suggested_min_value)
  maximum_value = _safe_float(suggested_max_value)
  if minimum_value is None or maximum_value is None:
    return None, None
  delta_a = float(minimum_value) - baseline
  delta_b = float(maximum_value) - baseline
  deltas = [delta_a, delta_b]
  if direction_hint == "increase":
    positive = sorted([delta for delta in deltas if delta > 0])
    if not positive:
      return None, None
    return float(positive[0]), float(positive[-1])
  if direction_hint == "decrease":
    negative = sorted([delta for delta in deltas if delta < 0], reverse=True)
    if not negative:
      return None, None
    return float(negative[0]), float(negative[-1])
  return float(min(deltas)), float(max(deltas))

def _repair_metric_delta_bounds(
  *,
  repair_envelope: Optional[Dict[str, Any]],
  path_type: str,
  efficiency: str,
) -> Tuple[Optional[float], Optional[float]]:
  envelope = repair_envelope if isinstance(repair_envelope, dict) else {}
  min_required = _safe_float(envelope.get("min_required_delta"))
  recommended = _safe_float(envelope.get("recommended_delta"))
  max_feasible = _safe_float(envelope.get("max_feasible_delta"))
  anchor_min = min_required if min_required is not None else recommended
  anchor_max = max_feasible if max_feasible is not None else recommended
  if anchor_min is None and anchor_max is None:
    return None, None

  scale_min = 1.0
  scale_max = 1.0
  if path_type != "direct":
    if efficiency == "medium":
      scale_min = 1.15
      scale_max = 1.5
    else:
      scale_min = 1.35
      scale_max = 2.0

  min_delta = float(anchor_min * scale_min) if anchor_min is not None else None
  max_delta = float(anchor_max * scale_max) if anchor_max is not None else None
  return min_delta, max_delta

def _quarter_days_in_period(quarter_row: Optional[Dict[str, Any]]) -> float:
  row = quarter_row if isinstance(quarter_row, dict) else {}
  return max(1.0, float(_safe_float(row.get("days_in_quarter")) or 90.0))

def _quarter_row_cost_of_goods_sold(quarter_row: Optional[Dict[str, Any]]) -> float:
  row = quarter_row if isinstance(quarter_row, dict) else {}
  explicit_cogs = _safe_float(row.get("cogs"))
  if explicit_cogs is not None:
    return float(explicit_cogs)
  revenue = float(_safe_float(row.get("revenue")) or 0.0)
  gross_profit = float(_safe_float(row.get("gross_profit")) or 0.0)
  return max(0.0, revenue - gross_profit)

def _quarter_row_operating_cost_base(quarter_row: Optional[Dict[str, Any]]) -> float:
  row = quarter_row if isinstance(quarter_row, dict) else {}
  return (
    float(_safe_float(row.get("marketing")) or 0.0)
    + float(_safe_float(row.get("research_and_development")) or 0.0)
    + float(_safe_float(row.get("lease_rent")) or 0.0)
    + float(_safe_float(row.get("payroll")) or 0.0)
    + float(_safe_float(row.get("g_and_a")) or 0.0)
  )

def _component_delta_to_lever_delta(
  *,
  lever_id: Any,
  lever_entry: Optional[Dict[str, Any]],
  component_delta: Any,
  quarter_row: Optional[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[str], Optional[str], Optional[str]]:
  entry = lever_entry if isinstance(lever_entry, dict) else {}
  lever = str(lever_id or "").strip().lower()
  semantics = str(entry.get("input_semantics") or "").strip().lower()
  row = quarter_row if isinstance(quarter_row, dict) else {}
  component_value = _safe_float(component_delta)
  if component_value is None:
    return None, None, None, None
  days_in_period = _quarter_days_in_period(row)
  revenue = max(abs(float(_safe_float(row.get("revenue")) or 0.0)), 1.0)
  cogs = max(abs(_quarter_row_cost_of_goods_sold(row)), 1.0)
  opex_base = max(abs(_quarter_row_operating_cost_base(row)), 1.0)
  current_liabilities = float(_safe_float(row.get("current_liabilities")) or 0.0)
  total_liabilities = float(_safe_float(row.get("total_liabilities")) or 0.0)
  long_term_debt = max(
    abs(float(_safe_float(row.get("long_term_debt")) or 0.0)),
    abs(total_liabilities - current_liabilities),
    1.0,
  )
  if semantics == "days":
    if "accounts receivable" in lever:
      return float(component_value * days_in_period / revenue), "days", "days_to_accounts_receivable", "high"
    if "inventory" in lever:
      return float(component_value * days_in_period / cogs), "days", "days_to_inventory", "high"
    if "accounts payable" in lever:
      return float(component_value * days_in_period / opex_base), "days", "days_to_accounts_payable", "high"
  if semantics == "percent_of_revenue":
    return float(component_value / revenue), "percent_of_revenue", "ratio_to_revenue_component", "high"
  if semantics == "percent_of_long_term_debt":
    return float(component_value / long_term_debt), "percent_of_long_term_debt", "ratio_to_long_term_debt_component", "high"
  unit = str(entry.get("input_semantics") or entry.get("value_kind") or "input_units").strip().lower() or "input_units"
  return float(component_value), unit, "currency_component", "high"

def _driver_target_conversion_context(
  *,
  lever_id: Any,
  lever_entry: Optional[Dict[str, Any]],
  target_metric_name: Any,
  quarter_row: Optional[Dict[str, Any]],
  actual_metric_value: Any,
  target_floor: Any,
  target_ceiling: Any,
) -> Dict[str, Any]:
  lever = str(lever_id or "").strip()
  metric = str(target_metric_name or "").strip().lower()
  if not lever or not metric:
    return {}
  entry = lever_entry if isinstance(lever_entry, dict) else {}
  mapping_entry = post_intake_driver_target_mapping_entry(lever) or {}
  row = quarter_row if isinstance(quarter_row, dict) else {}
  value_kind = str(entry.get("value_kind") or "").strip().lower()
  input_semantics = str(entry.get("input_semantics") or "").strip().lower()
  driver_unit = input_semantics or value_kind or "input_units"
  actual_value = _safe_float(actual_metric_value)
  floor_value = _safe_float(target_floor)
  ceiling_value = _safe_float(target_ceiling)

  def _rounded(value: Optional[float], *, ratio_like: bool) -> Optional[float]:
    if value is None:
      return None
    return (
      round(float(value), 2)
      if ratio_like
      else int(round(float(value)))
    )

  denominator: Optional[float] = None
  conversion_formula = None
  ratio_like_driver = value_kind == "ratio" or "percent_of_" in input_semantics
  if input_semantics == "percent_of_revenue":
    denominator = _safe_float(row.get("revenue"))
    conversion_formula = "driver_value = finmo_target_value / revenue"
  elif input_semantics == "percent_of_long_term_debt":
    denominator = _safe_float(row.get("long_term_debt"))
    conversion_formula = "driver_value = finmo_target_value / long_term_debt"
  elif input_semantics == "days":
    days_in_period = _quarter_days_in_period(row)
    denominator_metric = None
    if "accounts receivable" in lever.lower():
      denominator = _safe_float(row.get("revenue"))
      conversion_formula = "driver_value_days = finmo_target_value * days_in_quarter / revenue"
      denominator_metric = "revenue"
    elif "inventory" in lever.lower():
      denominator = _quarter_row_cost_of_goods_sold(row)
      conversion_formula = "driver_value_days = finmo_target_value * days_in_quarter / cogs"
      denominator_metric = "cogs"
    elif "accounts payable" in lever.lower():
      denominator = _quarter_row_operating_cost_base(row)
      conversion_formula = "driver_value_days = finmo_target_value * days_in_quarter / operating_cost_base"
      denominator_metric = "operating_cost_base"
    if denominator is not None and abs(float(denominator)) > 1e-9:
      scale = float(days_in_period) / float(denominator)
      return {
        "contract_version": "driver_target_conversion_v1",
        "lever_id": lever,
        "target_metric_name": metric,
        "target_metric_unit": "currency",
        "driver_target": str(mapping_entry.get("target_driver") or "").strip() or None,
        "driver_value_unit": driver_unit,
        "return_value_in": "driver_units",
        "do_not_return_target_dollars_as_lever_value": True,
        "conversion_formula": conversion_formula,
        "denominator_metric": denominator_metric,
        "denominator_value": int(round(float(denominator))),
        "current_target_value": _rounded(actual_value, ratio_like=False),
        "current_driver_equivalent": _rounded(actual_value * scale if actual_value is not None else None, ratio_like=False),
        "target_floor_value": _rounded(floor_value, ratio_like=False),
        "target_ceiling_value": _rounded(ceiling_value, ratio_like=False),
        "target_floor_driver_equivalent": _rounded(floor_value * scale if floor_value is not None else None, ratio_like=False),
        "target_ceiling_driver_equivalent": _rounded(ceiling_value * scale if ceiling_value is not None else None, ratio_like=False),
      }
    return {}
  elif input_semantics in {"quarter_currency", "debt_new_borrowing", "debt_scheduled_repayment", "capital_expenditures_cash", "capital_lease_principal_repayments", "capital_lease_additions_noncash"}:
    return {
      "contract_version": "driver_target_conversion_v1",
      "lever_id": lever,
      "target_metric_name": metric,
      "target_metric_unit": "currency",
      "driver_target": str(mapping_entry.get("target_driver") or "").strip() or None,
      "driver_value_unit": driver_unit,
      "return_value_in": "driver_units",
      "conversion_formula": "driver_value = finmo_target_value",
      "current_target_value": _rounded(actual_value, ratio_like=False),
      "current_driver_equivalent": _rounded(actual_value, ratio_like=False),
      "target_floor_value": _rounded(floor_value, ratio_like=False),
      "target_ceiling_value": _rounded(ceiling_value, ratio_like=False),
      "target_floor_driver_equivalent": _rounded(floor_value, ratio_like=False),
      "target_ceiling_driver_equivalent": _rounded(ceiling_value, ratio_like=False),
    }

  if denominator is None or abs(float(denominator)) <= 1e-9:
    return {}
  return {
    "contract_version": "driver_target_conversion_v1",
    "lever_id": lever,
    "target_metric_name": metric,
    "target_metric_unit": "currency",
    "driver_target": str(mapping_entry.get("target_driver") or "").strip() or None,
    "driver_value_unit": driver_unit,
    "return_value_in": "driver_units",
    "do_not_return_target_dollars_as_lever_value": bool(ratio_like_driver),
    "conversion_formula": conversion_formula,
    "denominator_value": int(round(float(denominator))),
    "current_target_value": _rounded(actual_value, ratio_like=False),
    "current_driver_equivalent": _rounded(
      actual_value / float(denominator) if actual_value is not None else None,
      ratio_like=ratio_like_driver,
    ),
    "target_floor_value": _rounded(floor_value, ratio_like=False),
    "target_ceiling_value": _rounded(ceiling_value, ratio_like=False),
    "target_floor_driver_equivalent": _rounded(
      floor_value / float(denominator) if floor_value is not None else None,
      ratio_like=ratio_like_driver,
    ),
    "target_ceiling_driver_equivalent": _rounded(
      ceiling_value / float(denominator) if ceiling_value is not None else None,
      ratio_like=ratio_like_driver,
    ),
  }

def _metric_target_bounds_constrained_by_driver_scaffold(
  *,
  direction_hint: str,
  actual_metric_value: Any,
  target_floor: Any,
  target_ceiling: Any,
  repair_envelope: Optional[Dict[str, Any]],
  driver_paths: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
  feasible_mins: List[float] = []
  feasible_maxs: List[float] = []
  for path in (driver_paths or []):
    if not isinstance(path, dict):
      continue
    conversion = path.get("driver_target_conversion")
    if not isinstance(conversion, dict):
      continue
    driver_min = _safe_float(path.get("suggested_min_value"))
    driver_max = _safe_float(path.get("suggested_max_value"))
    if driver_min is None or driver_max is None:
      continue
    formula = str(conversion.get("conversion_formula") or "").strip().lower()
    denominator = _safe_float(conversion.get("denominator_value"))
    metric_min = None
    metric_max = None
    if formula == "driver_value = finmo_target_value":
      metric_min = float(driver_min)
      metric_max = float(driver_max)
    elif denominator is not None and abs(float(denominator)) > 1e-9:
      if formula in {
        "driver_value = finmo_target_value / revenue",
        "driver_value = finmo_target_value / long_term_debt",
      }:
        metric_min = float(driver_min) * float(denominator)
        metric_max = float(driver_max) * float(denominator)
      elif formula in {
        "driver_value_days = finmo_target_value * days_in_quarter / revenue",
        "driver_value_days = finmo_target_value * days_in_quarter / cogs",
        "driver_value_days = finmo_target_value * days_in_quarter / operating_cost_base",
      }:
        floor_value = _safe_float(conversion.get("target_floor_value"))
        floor_driver = _safe_float(conversion.get("target_floor_driver_equivalent"))
        ceiling_value = _safe_float(conversion.get("target_ceiling_value"))
        ceiling_driver = _safe_float(conversion.get("target_ceiling_driver_equivalent"))
        scale = None
        if floor_value is not None and floor_driver is not None and abs(float(floor_value)) > 1e-9:
          scale = float(floor_driver) / float(floor_value)
        elif ceiling_value is not None and ceiling_driver is not None and abs(float(ceiling_value)) > 1e-9:
          scale = float(ceiling_driver) / float(ceiling_value)
        if scale is not None and abs(scale) > 1e-12:
          metric_min = float(driver_min) / float(scale)
          metric_max = float(driver_max) / float(scale)
    if metric_min is None or metric_max is None:
      continue
    feasible_mins.append(min(float(metric_min), float(metric_max)))
    feasible_maxs.append(max(float(metric_min), float(metric_max)))

  if not feasible_mins or not feasible_maxs:
    return {
      "target_floor": _safe_float(target_floor),
      "target_ceiling": _safe_float(target_ceiling),
      "repair_envelope": copy.deepcopy(repair_envelope or {}),
      "feasibility_adjusted": False,
    }

  feasible_min = min(feasible_mins)
  feasible_max = max(feasible_maxs)
  floor_value = _safe_float(target_floor)
  ceiling_value = _safe_float(target_ceiling)
  direction = str(direction_hint or "").strip().lower()
  adjusted = False

  if direction == "decrease":
    if ceiling_value is not None and ceiling_value < feasible_min:
      ceiling_value = feasible_min
      adjusted = True
    if ceiling_value is not None and ceiling_value > feasible_max:
      ceiling_value = feasible_max
      adjusted = True
    if floor_value is not None and floor_value < feasible_min:
      floor_value = feasible_min
      adjusted = True
  elif direction == "increase":
    if floor_value is not None and floor_value > feasible_max:
      floor_value = feasible_max
      adjusted = True
    if floor_value is not None and floor_value < feasible_min:
      floor_value = feasible_min
      adjusted = True
    if ceiling_value is not None and ceiling_value > feasible_max:
      ceiling_value = feasible_max
      adjusted = True
  else:
    if floor_value is not None:
      clamped_floor = min(max(float(floor_value), feasible_min), feasible_max)
      adjusted = adjusted or abs(clamped_floor - float(floor_value)) > 1e-9
      floor_value = clamped_floor
    if ceiling_value is not None:
      clamped_ceiling = min(max(float(ceiling_value), feasible_min), feasible_max)
      adjusted = adjusted or abs(clamped_ceiling - float(ceiling_value)) > 1e-9
      ceiling_value = clamped_ceiling

  if floor_value is not None and ceiling_value is not None and floor_value > ceiling_value:
    if direction == "increase":
      ceiling_value = floor_value
    else:
      floor_value = ceiling_value
    adjusted = True

  actual_value = _safe_float(actual_metric_value)
  next_repair_envelope = copy.deepcopy(repair_envelope or {})
  if adjusted and actual_value is not None:
    if direction == "decrease" and ceiling_value is not None:
      delta = float(ceiling_value) - float(actual_value)
      next_repair_envelope["min_required_delta"] = delta
      next_repair_envelope["recommended_delta"] = delta
      next_repair_envelope["max_feasible_delta"] = delta
    elif direction == "increase" and floor_value is not None:
      delta = float(floor_value) - float(actual_value)
      next_repair_envelope["min_required_delta"] = delta
      next_repair_envelope["recommended_delta"] = delta
      next_repair_envelope["max_feasible_delta"] = delta

  return {
    "target_floor": floor_value,
    "target_ceiling": ceiling_value,
    "repair_envelope": next_repair_envelope,
    "feasibility_adjusted": adjusted,
    "feasible_metric_min": feasible_min,
    "feasible_metric_max": feasible_max,
  }

def _spillover_flags_for_metric(
  *,
  issue_code: Any,
  metric_name: Any,
  direction_hint: str,
  driver_paths: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
  metric = str(metric_name or "").strip().lower()
  flags: List[str] = []
  if metric == "payroll" and direction_hint == "increase":
    flags.append("Higher payroll reduces EBITDA and cash if not offset elsewhere.")
  if metric == "capital_expenditures" and direction_hint == "increase":
    flags.append("Higher capex weakens near-term cash and may increase financing needs.")
  if metric in {"marketing", "marketing_percent_of_revenue"} and direction_hint == "decrease":
    flags.append("Reducing marketing can weaken growth and future revenue conversion.")
  if metric == "ending_cash":
    flags.append("Cash repair through financing can improve liquidity while worsening leverage or dilution.")
  if metric == "revenue" and direction_hint == "increase":
    flags.append("Aggressive revenue lifts can break staffing, marketing, and working-capital realism.")
  for path in (driver_paths or []):
    family = str(path.get("lever_family") or "").strip().lower()
    if family in {"balance_sheet", "schedules"}:
      note = "Financing and schedule moves can help cash fast but may worsen leverage, dilution, or future fixed obligations."
      if note not in flags:
        flags.append(note)
    if family == "revenue":
      note = "Revenue-side repairs can improve margin and cash but may require matching operating support."
      if note not in flags:
        flags.append(note)
  return flags[:3]

def _build_convergence_scorecard(
  *,
  controller_resolution_state: Optional[Dict[str, Any]],
  controller_retry_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  retry_context = controller_retry_context if isinstance(controller_retry_context, dict) else {}
  current_score = int(_safe_float(controller_state.get("overall_completion_score_pct")) or 0)
  previous_score_raw = _safe_float(retry_context.get("previous_overall_completion_score_pct"))
  previous_score = int(previous_score_raw) if previous_score_raw is not None else None
  score_delta = int(current_score - previous_score) if previous_score is not None else None
  return {
    "overall_score": current_score,
    "grade": str(controller_state.get("overall_completion_grade") or "").strip() or _completion_grade_letter(current_score),
    "previous_score": previous_score,
    "previous_grade": str(retry_context.get("previous_overall_completion_grade") or "").strip() or None,
    "score_delta": score_delta,
    "lowest_quarter_score": int(_safe_float(controller_state.get("lowest_quarter_score_pct")) or 0),
    "pass_threshold": int(_safe_float(controller_state.get("grade_pass_threshold_pct")) or _CONVERGENCE_ISSUE_PASS_SCORE_PCT),
    "quarter_floor": _CONVERGENCE_ISSUE_WARN_SCORE_PCT,
    "progress_status": str(retry_context.get("progress_status") or "").strip() or None,
    "remaining_issue_count": int(_safe_float(controller_state.get("remaining_issue_count")) or 0),
    "resolved_issue_count": int(_safe_float(controller_state.get("resolved_issue_count")) or 0),
    "tolerated_issue_count": int(_safe_float(controller_state.get("tolerated_issue_count")) or 0),
    "failing_quarters": copy.deepcopy(controller_state.get("failing_quarters") or []),
  }

def _repair_aware_issue_packets(
  *,
  issue_packets: Optional[List[Dict[str, Any]]],
  numeric_guidance_packet: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  packets = [
    copy.deepcopy(item)
    for item in (issue_packets or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  guidance = numeric_guidance_packet if isinstance(numeric_guidance_packet, dict) else {}
  repair_map = {
    str(item.get("issue_code") or "").strip().lower(): copy.deepcopy(item)
    for item in (guidance.get("issue_repair_packets") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  }
  enhanced_packets: List[Dict[str, Any]] = []
  for packet in packets:
    issue_code = str(packet.get("issue_code") or "").strip().lower()
    repair_packet = repair_map.get(issue_code) or {}
    enhanced_packet = copy.deepcopy(packet)
    if repair_packet:
      enhanced_packet["priority"] = repair_packet.get("priority")
      enhanced_packet["priority_rank"] = repair_packet.get("priority_rank")
      enhanced_packet["impact_weight"] = repair_packet.get("impact_weight")
      enhanced_packet["closure_threshold_pct"] = repair_packet.get("closure_threshold_pct")
      enhanced_packet["quarter_floor_pct"] = repair_packet.get("quarter_floor_pct")
      enhanced_packet["repair_targets"] = copy.deepcopy(repair_packet.get("repair_targets") or [])
      enhanced_packet["summary"] = str(
        repair_packet.get("summary")
        or enhanced_packet.get("summary")
        or enhanced_packet.get("issue_summary")
        or enhanced_packet.get("issue")
        or ""
      ).strip()
      enhanced_packet["root_cause"] = str(
        repair_packet.get("root_cause")
        or enhanced_packet.get("root_cause")
        or enhanced_packet.get("detail")
        or ""
      ).strip()
      mapped_candidate_lever_ids = _issue_packet_mapped_driver_lever_ids(repair_packet)
      if mapped_candidate_lever_ids:
        enhanced_packet["candidate_lever_ids"] = copy.deepcopy(mapped_candidate_lever_ids)
        enhanced_packet["next_required_lever_ids"] = copy.deepcopy(mapped_candidate_lever_ids)
      metric_targets = _issue_packet_declared_target_metric_names(repair_packet)
      if metric_targets:
        enhanced_packet["metric_targets"] = copy.deepcopy(metric_targets)
    enhanced_packets.append(enhanced_packet)
  enhanced_packets.sort(
    key=lambda item: (
      int(_safe_float(item.get("priority_rank")) or 9999),
      -int(_safe_float(item.get("remaining_issue_severity_score")) or 0),
      str(item.get("issue_code") or "").strip().lower(),
    )
  )
  return enhanced_packets

def _sample_evenly_spaced_entries(
  entries: Optional[List[Dict[str, Any]]],
  *,
  max_items: int,
) -> List[Dict[str, Any]]:
  items = [copy.deepcopy(item) for item in (entries or []) if isinstance(item, dict)]
  if len(items) <= max_items:
    return items
  sample_indexes = {
    int(round(index * (len(items) - 1) / max(1, max_items - 1)))
    for index in range(max_items)
  }
  return [copy.deepcopy(items[index]) for index in sorted(sample_indexes)]

def _driver_path_sort_key(path: Optional[Dict[str, Any]]) -> Tuple[int, int, int, str]:
  item = path if isinstance(path, dict) else {}
  efficiency = str(item.get("efficiency") or "").strip().lower()
  path_type = str(item.get("path_type") or "").strip().lower()
  efficiency_rank = {
    "high": 0,
    "medium": 1,
    "low": 2,
  }.get(efficiency, 3)
  path_type_rank = 0 if path_type == "direct" else 1
  return (
    efficiency_rank,
    path_type_rank,
    int(_safe_float(item.get("priority_rank")) or 9999),
    str(item.get("lever") or "").strip().lower(),
  )

def _select_focus_driver_paths(
  driver_paths: Optional[List[Dict[str, Any]]],
  *,
  max_paths: int = 3,
) -> List[Dict[str, Any]]:
  ordered = [
    copy.deepcopy(item)
    for item in sorted(
      [path for path in (driver_paths or []) if isinstance(path, dict)],
      key=_driver_path_sort_key,
    )
  ]
  if len(ordered) <= max_paths:
    return ordered

  selected: List[Dict[str, Any]] = []
  seen_levers: set[str] = set()
  seen_families: set[str] = set()
  seen_path_types: set[str] = set()

  def _take(entry: Dict[str, Any]) -> bool:
    lever_id = str(entry.get("lever") or "").strip()
    if not lever_id or lever_id in seen_levers:
      return False
    selected.append(copy.deepcopy(entry))
    seen_levers.add(lever_id)
    family = str(entry.get("lever_family") or "").strip().lower()
    if family:
      seen_families.add(family)
    path_type = str(entry.get("path_type") or "").strip().lower()
    if path_type:
      seen_path_types.add(path_type)
    return True

  for item in ordered:
    if len(selected) >= max_paths:
      break
    if (
      str(item.get("path_type") or "").strip().lower() == "direct"
      and str(item.get("efficiency") or "").strip().lower() == "high"
    ):
      _take(item)

  for item in ordered:
    if len(selected) >= max_paths:
      break
    family = str(item.get("lever_family") or "").strip().lower()
    if family and family in seen_families:
      continue
    _take(item)

  for item in ordered:
    if len(selected) >= max_paths:
      break
    path_type = str(item.get("path_type") or "").strip().lower()
    if path_type and path_type in seen_path_types:
      continue
    _take(item)

  for item in ordered:
    if len(selected) >= max_paths:
      break
    _take(item)
  return selected

def _compact_driver_paths_for_prompt(
  driver_paths: Optional[List[Dict[str, Any]]],
  *,
  max_paths: int = 3,
) -> List[Dict[str, Any]]:
  compact_paths: List[Dict[str, Any]] = []
  for item in _select_focus_driver_paths(driver_paths, max_paths=max_paths):
    delta_unit = str(item.get("delta_unit") or "").strip().lower()
    ratio_like_delta = delta_unit in {"ratio", "percent", "percent_of_revenue", "margin", "percent_of_long_term_debt"}
    integer_like_delta = delta_unit in {"currency", "quarter_currency", "day_count", "count", "integer"}
    min_delta_raw = _safe_float(item.get("min_delta"))
    max_delta_raw = _safe_float(item.get("max_delta"))
    compact_paths.append(
      {
        "lever": str(item.get("lever") or "").strip(),
        "lever_family": str(item.get("lever_family") or "").strip(),
        "path_type": str(item.get("path_type") or "").strip(),
        "efficiency": str(item.get("efficiency") or "").strip(),
        "priority_rank": int(_safe_float(item.get("priority_rank")) or 0) or None,
        "min_delta": (
          round(float(min_delta_raw), 2)
          if ratio_like_delta and min_delta_raw is not None
          else int(round(float(min_delta_raw)))
          if integer_like_delta and min_delta_raw is not None
          else min_delta_raw
        ),
        "max_delta": (
          round(float(max_delta_raw), 2)
          if ratio_like_delta and max_delta_raw is not None
          else int(round(float(max_delta_raw)))
          if integer_like_delta and max_delta_raw is not None
          else max_delta_raw
        ),
        "delta_unit": str(item.get("delta_unit") or "").strip() or None,
        "metric_min_delta": _safe_float(item.get("metric_min_delta")),
        "metric_max_delta": _safe_float(item.get("metric_max_delta")),
        "translation_basis": str(item.get("translation_basis") or "").strip() or None,
        "translation_confidence": str(item.get("translation_confidence") or "").strip() or None,
        "target_driver": str(item.get("target_driver") or "").strip() or None,
        "driver_value_unit": str(item.get("driver_value_unit") or "").strip() or None,
        "return_value_in": str(item.get("return_value_in") or "").strip() or None,
        "driver_target_conversion": copy.deepcopy(item.get("driver_target_conversion") or {}),
      }
    )
  return compact_paths

def _compact_repair_targets_for_prompt(
  repair_targets: Optional[List[Dict[str, Any]]],
  *,
  max_per_metric: int = 6,
) -> List[Dict[str, Any]]:
  grouped: Dict[str, List[Dict[str, Any]]] = {}
  for item in (repair_targets or []):
    if not isinstance(item, dict):
      continue
    metric = str(item.get("metric") or "").strip().lower() or "unknown_metric"
    grouped.setdefault(metric, []).append(copy.deepcopy(item))
  compact_targets: List[Dict[str, Any]] = []
  for metric_name, items in grouped.items():
    ordered = sorted(
      items,
      key=lambda item: (
        int(_safe_float(item.get("quarter")) or 0),
        str(item.get("metric") or "").strip().lower(),
      ),
    )
    for item in _sample_evenly_spaced_entries(ordered, max_items=max_per_metric):
      compact_targets.append(
        {
          "quarter": int(_safe_float(item.get("quarter")) or 0),
          "metric": metric_name,
          "direction": str(item.get("direction") or "").strip(),
          "actual_value": _safe_float(item.get("actual_value")),
          "target_floor": _safe_float(item.get("target_floor")),
          "target_ceiling": _safe_float(item.get("target_ceiling")),
          "gap": _safe_float(item.get("gap")),
          "source_metric_names": copy.deepcopy(item.get("source_metric_names") or []),
          "metric_targets": copy.deepcopy(item.get("metric_targets") or []),
          "business_world_signal_reasons": copy.deepcopy(item.get("business_world_signal_reasons") or []),
          "repair_envelope": copy.deepcopy(item.get("repair_envelope") or {}),
          "driver_paths": _compact_driver_paths_for_prompt(item.get("driver_paths") or []),
          "spillover_flags": copy.deepcopy((item.get("spillover_flags") or [])[:2]),
        }
      )
  compact_targets.sort(
    key=lambda item: (
      int(_safe_float(item.get("quarter")) or 0),
      str(item.get("metric") or "").strip(),
    )
  )
  return compact_targets

def _compact_repair_envelope_packets_for_prompt(
  issue_packets: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  compact_packets: List[Dict[str, Any]] = []
  ordered_packets = sorted(
    [
      item for item in (issue_packets or [])
      if isinstance(item, dict)
    ],
    key=lambda item: (
      int(_safe_float(item.get("priority_rank")) or 9999),
      -int(_safe_float(item.get("severity_score")) or 0),
      str(item.get("issue_code") or "").strip().lower(),
    ),
  )[:_CONVERGENCE_MAX_FOCUS_ISSUES]
  for item in ordered_packets:
    if not isinstance(item, dict):
      continue
    compact_packets.append(
      {
        "issue_code": str(item.get("issue_code") or "").strip(),
        "priority_rank": int(_safe_float(item.get("priority_rank")) or 0) or None,
        "severity": str(item.get("severity") or "").strip(),
        "impact_weight": int(_safe_float(item.get("impact_weight")) or 0) or None,
        "affected_quarters": copy.deepcopy(item.get("affected_quarters") or []),
        "summary": str(item.get("summary") or "").strip(),
        "root_cause": str(item.get("root_cause") or "").strip(),
        "closure_threshold_pct": int(_safe_float(item.get("closure_threshold_pct")) or _CONVERGENCE_ISSUE_PASS_SCORE_PCT),
        "quarter_floor_pct": int(_safe_float(item.get("quarter_floor_pct")) or _CONVERGENCE_ISSUE_WARN_SCORE_PCT),
        "metric_targets": copy.deepcopy(item.get("metric_targets") or []),
        "repair_targets": _compact_repair_targets_for_prompt(item.get("repair_targets") or []),
      }
    )
  return compact_packets

def _compact_issue_packets_for_prompt(
  issue_packets: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  compact_packets: List[Dict[str, Any]] = []
  ordered_packets = sorted(
    [
      item for item in (issue_packets or [])
      if isinstance(item, dict)
    ],
    key=lambda item: (
      int(_safe_float(item.get("priority_rank")) or 9999),
      -int(_safe_float(item.get("remaining_issue_severity_score")) or 0),
      str(item.get("issue_code") or "").strip().lower(),
    ),
  )[:_CONVERGENCE_MAX_FOCUS_ISSUES]
  for item in ordered_packets:
    if not isinstance(item, dict):
      continue
    compact_packets.append(
      {
        "issue_code": str(item.get("issue_code") or "").strip(),
        "priority_rank": int(_safe_float(item.get("priority_rank")) or 0) or None,
        "severity": str(item.get("severity") or "").strip(),
        "impact_weight": int(_safe_float(item.get("impact_weight")) or 0) or None,
        "summary": str(
          item.get("summary")
          or item.get("issue_summary")
          or item.get("issue")
          or ""
        ).strip(),
        "root_cause": str(item.get("root_cause") or item.get("detail") or "").strip(),
        "affected_quarters": copy.deepcopy(item.get("affected_quarters") or item.get("remaining_problem_quarters") or []),
        "metric_targets": copy.deepcopy(item.get("metric_targets") or []),
        "candidate_lever_ids": copy.deepcopy((item.get("candidate_lever_ids") or [])[:8]),
        "closure_threshold_pct": int(_safe_float(item.get("closure_threshold_pct")) or _CONVERGENCE_ISSUE_PASS_SCORE_PCT),
        "quarter_floor_pct": int(_safe_float(item.get("quarter_floor_pct")) or _CONVERGENCE_ISSUE_WARN_SCORE_PCT),
        "repair_target_count": len(item.get("repair_targets") or []),
        "repair_targets": _compact_repair_targets_for_prompt(item.get("repair_targets") or []),
      }
    )
  return compact_packets

def _compact_numeric_guidance_for_prompt(
  numeric_guidance_packet: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  guidance = numeric_guidance_packet if isinstance(numeric_guidance_packet, dict) else {}
  metric_packets = [
    item for item in (guidance.get("metric_pressure_packets") or [])
    if isinstance(item, dict)
  ]
  compact_metric_packets = []
  for item in _sample_evenly_spaced_entries(
    sorted(
      metric_packets,
      key=lambda packet: (
        int(_safe_float(packet.get("priority_rank")) or 9999),
        int(_safe_float(packet.get("quarter_index")) or 0),
        str(packet.get("metric_name") or "").strip(),
      ),
    ),
    max_items=_CONVERGENCE_PROMPT_METRIC_PACKET_LIMIT,
  ):
    unit_kind = str(item.get("unit_kind") or "").strip().lower()
    ratio_like_metric = unit_kind in {"ratio", "percent", "percent_of_revenue", "margin"}
    current_value_raw = _safe_float(item.get("current_value"))
    target_floor_raw = _safe_float(item.get("target_floor"))
    target_ceiling_raw = _safe_float(item.get("target_ceiling"))
    gap_raw = _safe_float(item.get("gap"))
    compact_metric_packets.append(
      {
        "issue_code": str(item.get("issue_code") or "").strip(),
        "priority_rank": int(_safe_float(item.get("priority_rank")) or 0) or None,
        "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
        "metric_name": str(item.get("metric_name") or "").strip(),
        "direction_hint": str(item.get("direction_hint") or "").strip(),
        "current_value": (
          round(float(current_value_raw), 2)
          if ratio_like_metric and current_value_raw is not None
          else int(round(float(current_value_raw)))
          if current_value_raw is not None
          else None
        ),
        "target_floor": (
          round(float(target_floor_raw), 2)
          if ratio_like_metric and target_floor_raw is not None
          else int(round(float(target_floor_raw)))
          if target_floor_raw is not None
          else None
        ),
        "target_ceiling": (
          round(float(target_ceiling_raw), 2)
          if ratio_like_metric and target_ceiling_raw is not None
          else int(round(float(target_ceiling_raw)))
          if target_ceiling_raw is not None
          else None
        ),
        "gap": (
          round(float(gap_raw), 2)
          if ratio_like_metric and gap_raw is not None
          else int(round(float(gap_raw)))
          if gap_raw is not None
          else None
        ),
        "repair_envelope": copy.deepcopy(item.get("repair_envelope") or {}),
        "driver_paths": _compact_driver_paths_for_prompt(item.get("driver_paths") or [], max_paths=2),
        "spillover_flags": copy.deepcopy((item.get("spillover_flags") or [])[:2]),
      }
    )
  lever_entries = [
    item for item in (guidance.get("lever_band_scaffold") or [])
    if isinstance(item, dict)
  ]
  compact_lever_entries: List[Dict[str, Any]] = []
  for item in _sample_evenly_spaced_entries(
    sorted(
      lever_entries,
      key=lambda entry: (
        int(_safe_float(entry.get("priority_rank")) or 9999),
        str(entry.get("lever_id") or "").strip(),
      ),
    ),
    max_items=_CONVERGENCE_PROMPT_LEVER_PACKET_LIMIT,
  ):
    lever_id = str(item.get("lever_id") or "").strip()
    canonical_value_meta = _canonical_writable_lever_value_metadata(
      lever_id=lever_id,
      value_kind=item.get("value_kind"),
      input_semantics=item.get("input_semantics"),
    )
    value_kind = str(canonical_value_meta.get("value_kind") or "").strip().lower()
    input_semantics = str(canonical_value_meta.get("input_semantics") or "").strip().lower()
    ratio_like_value = value_kind == "ratio" or "percent_of_" in input_semantics
    suggested_min_raw = _safe_float(item.get("suggested_min_value"))
    suggested_max_raw = _safe_float(item.get("suggested_max_value"))
    compact_lever_entries.append(
      {
        "lever_id": lever_id,
        "lever_family": str(item.get("lever_family") or "").strip(),
        "priority_rank": int(_safe_float(item.get("priority_rank")) or 0) or None,
        "priority_tier": str(item.get("priority_tier") or "").strip(),
        "direction_hint": str(item.get("direction_hint") or "").strip(),
        "numeric_precision_rule": (
          "ratio_like_driver_two_decimals_only; use 0.02 or 0.03, never 0.025"
          if ratio_like_value
          else "currency_driver_integer_only"
        ),
        "suggested_min_value": (
          round(float(suggested_min_raw), 2)
          if ratio_like_value and suggested_min_raw is not None
          else int(round(float(suggested_min_raw)))
          if suggested_min_raw is not None
          else None
        ),
        "suggested_max_value": (
          round(float(suggested_max_raw), 2)
          if ratio_like_value and suggested_max_raw is not None
          else int(round(float(suggested_max_raw)))
          if suggested_max_raw is not None
          else None
        ),
        "covered_issue_codes": copy.deepcopy(item.get("covered_issue_codes") or []),
        "covered_metric_names": copy.deepcopy(item.get("covered_metric_names") or []),
      }
    )
  compact_mapping_lookup = post_intake_compact_mapping_lookup_for_levers(
    str(item.get("lever_id") or "").strip()
    for item in compact_lever_entries
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  )
  return {
    "contract_version": str(guidance.get("contract_version") or "").strip(),
    "completion_policy": copy.deepcopy(guidance.get("completion_policy") or {}),
    "scope_quarters": copy.deepcopy(guidance.get("scope_quarters") or []),
    "guidance_coverage_summary": copy.deepcopy(guidance.get("guidance_coverage_summary") or {}),
    "metric_pressure_packets": compact_metric_packets,
    "lever_band_scaffold": compact_lever_entries,
    "issue_repair_packets": _compact_issue_packets_for_prompt(
      guidance.get("issue_repair_packets") or []
    ),
    "lever_allowed_mapped_repair_targets": _lever_allowed_mapped_repair_targets(guidance),
    "driver_target_mapping_lookup": compact_mapping_lookup,
  }

def _unified_target_fill_grid(
  *,
  required_target_quarters: Optional[List[int]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  baseline_finmo_rows: Optional[List[Dict[str, Any]]] = None,
  business_world_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  world_contract = business_world_contract if isinstance(business_world_contract, dict) else {}
  stage_ramp_contract = (
    world_contract.get("stage_ramp_contract")
    if isinstance(world_contract.get("stage_ramp_contract"), dict)
    else {}
  )
  quarters = [
    int(_safe_float(item) or 0)
    for item in (
      required_target_quarters
      or guidance.get("scope_quarters")
      or []
    )
    if int(_safe_float(item) or 0) >= 1
  ]
  quarters = list(dict.fromkeys(quarters))
  allowed_metrics: List[str] = []
  for item in (guidance.get("driver_target_mapping_lookup") or []):
    if not isinstance(item, dict):
      continue
    metric_name = str(item.get("target_metric_name") or "").strip().lower()
    if metric_name and metric_name in _UNIFIED_ALLOWED_TARGET_METRIC_KEYS and metric_name not in allowed_metrics:
      allowed_metrics.append(metric_name)
  for item in (guidance.get("metric_pressure_packets") or []):
    if not isinstance(item, dict):
      continue
    metric_name = str(item.get("metric_name") or "").strip().lower()
    if metric_name and metric_name in _UNIFIED_ALLOWED_TARGET_METRIC_KEYS and metric_name not in allowed_metrics:
      allowed_metrics.append(metric_name)
  baseline_by_quarter = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in (baseline_finmo_rows or [])
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  }
  revenue_target_state_by_quarter: Dict[int, float] = {
    quarter_index: max(0.0, float(_safe_float(row.get("revenue")) or 0.0))
    for quarter_index, row in baseline_by_quarter.items()
    if quarter_index >= 1
  }
  stage_ramp_state: Dict[str, Any] = {"spike_count_used": 0}
  repair_bounds_by_key: Dict[Tuple[int, str], Dict[str, Any]] = {}
  for issue_packet in (guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    for repair_target in (issue_packet.get("repair_targets") or []):
      if not isinstance(repair_target, dict):
        continue
      quarter_index = int(_safe_float(repair_target.get("quarter")) or 0)
      metric_name = str(repair_target.get("metric") or "").strip().lower()
      if quarter_index < 1 or not metric_name:
        continue
      key = (quarter_index, metric_name)
      existing = repair_bounds_by_key.get(key) or {}
      floor_value = _safe_float(repair_target.get("target_floor") or repair_target.get("minimum_target_value"))
      ceiling_value = _safe_float(repair_target.get("target_ceiling") or repair_target.get("maximum_target_value"))
      existing_floor = _safe_float(existing.get("minimum_target_value"))
      existing_ceiling = _safe_float(existing.get("maximum_target_value"))
      repair_bounds_by_key[key] = {
        "minimum_target_value": (
          max(float(existing_floor), float(floor_value))
          if existing_floor is not None and floor_value is not None
          else (float(floor_value) if floor_value is not None else existing.get("minimum_target_value"))
        ),
        "maximum_target_value": (
          min(float(existing_ceiling), float(ceiling_value))
          if existing_ceiling is not None and ceiling_value is not None
          else (float(ceiling_value) if ceiling_value is not None else existing.get("maximum_target_value"))
        ),
        "direction_hint": str(repair_target.get("direction") or existing.get("direction_hint") or "").strip().lower() or None,
      }
  rows: List[Dict[str, Any]] = []

  def _target_display_value(value: Any, *, metric_name: str, bound_side: str = "") -> Any:
    parsed = _safe_float(value)
    if parsed is None:
      return None
    target_kind = post_intake_target_value_kind_for_metric(metric_name, phase="convergence") or "number"
    if target_kind == "currency" or target_kind == "count" or target_kind == "day_count":
      if bound_side == "minimum":
        return int(math.ceil(float(parsed)))
      if bound_side == "maximum":
        return int(math.floor(float(parsed)))
      return int(round(float(parsed)))
    if target_kind == "ratio":
      return round(float(parsed), 2)
    return float(parsed)

  for quarter in quarters:
    baseline = baseline_by_quarter.get(quarter) or {}
    for metric_name in allowed_metrics:
      current_value = _safe_float(baseline.get(metric_name))
      repair_bounds = repair_bounds_by_key.get((quarter, metric_name)) or {}
      minimum_target_value = _safe_float(repair_bounds.get("minimum_target_value"))
      maximum_target_value = _safe_float(repair_bounds.get("maximum_target_value"))
      direction_hint = str(repair_bounds.get("direction_hint") or "").strip().lower()
      recommended_target_value: Optional[float] = None
      if direction_hint == "decrease" and maximum_target_value is not None:
        recommended_target_value = float(maximum_target_value)
      elif direction_hint == "increase" and minimum_target_value is not None:
        recommended_target_value = float(minimum_target_value)
      elif current_value is not None:
        recommended_target_value = float(current_value)
      if metric_name == "revenue":
        previous_revenue = _safe_float(revenue_target_state_by_quarter.get(quarter - 1))
        if previous_revenue is not None and previous_revenue > 0.0 and quarter > 1:
          limit = _stage_ramp_revenue_growth_limit_for_target(
            stage_ramp_contract=stage_ramp_contract,
            quarter_index=quarter,
            spike_count_used=int(_safe_float(stage_ramp_state.get("spike_count_used")) or 0),
          )
          if bool(limit.get("applies")):
            ordinary_growth_max = float(_safe_float(limit.get("ordinary_growth_max")) or 0.0)
            allowed_growth = float(_safe_float(limit.get("allowed_growth")) or ordinary_growth_max)
            max_revenue = float(math.floor(max(0.0, float(previous_revenue) * (1.0 + allowed_growth))))
            if minimum_target_value is not None and float(minimum_target_value) > max_revenue:
              minimum_target_value = max_revenue
            if maximum_target_value is not None and float(maximum_target_value) > max_revenue:
              maximum_target_value = max_revenue
            if recommended_target_value is not None and float(recommended_target_value) > max_revenue:
              recommended_target_value = max_revenue
            chosen_revenue = (
              float(recommended_target_value)
              if recommended_target_value is not None
              else float(current_value)
              if current_value is not None
              else None
            )
            if chosen_revenue is not None:
              growth = (float(chosen_revenue) - float(previous_revenue)) / max(float(previous_revenue), 1e-9)
              if bool(limit.get("spike_available")) and growth > ordinary_growth_max + 1e-9:
                stage_ramp_state["spike_count_used"] = int(_safe_float(stage_ramp_state.get("spike_count_used")) or 0) + 1
        if recommended_target_value is not None:
          revenue_target_state_by_quarter[quarter] = max(0.0, float(recommended_target_value))
        elif current_value is not None:
          revenue_target_state_by_quarter[quarter] = max(0.0, float(current_value))
      rows.append(
        {
          "quarter_index": quarter,
          "metric_name": metric_name,
          "target_value_kind": post_intake_target_value_kind_for_metric(metric_name, phase="convergence") or None,
          "current_value": _target_display_value(current_value, metric_name=metric_name),
          "minimum_target_value": _target_display_value(
            minimum_target_value,
            metric_name=metric_name,
            bound_side="minimum",
          ),
          "maximum_target_value": _target_display_value(
            maximum_target_value,
            metric_name=metric_name,
            bound_side="maximum",
          ),
          "recommended_target_value": _target_display_value(
            recommended_target_value,
            metric_name=metric_name,
            bound_side=(
              "minimum"
              if direction_hint == "increase"
              else "maximum"
              if direction_hint == "decrease"
              else ""
            ),
          ),
          "target_value_copy_rule": (
            "copy recommended_target_value exactly; do not pretty-round above maximum_target_value or below minimum_target_value"
            if recommended_target_value is not None
            else "choose an integer inside the min/max envelope"
          ),
          "direction_hint": direction_hint or None,
          "target_value": None,
        }
      )
  return {
    "contract_version": "unified_convergence_locked_target_fill_grid_v1",
    "grid_rule": (
      "GPT may only choose primary_target_metric_names from allowed_target_metric_names and may only fill targets "
      "for required_target_quarters. When a row has recommended_target_value, copy it exactly into target_value."
    ),
    "required_target_quarters": copy.deepcopy(quarters),
    "allowed_target_metric_names": copy.deepcopy(allowed_metrics),
    "rows": rows,
  }

def _locked_targets_by_quarter_response_template(
  locked_target_fill_grid: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  grid = locked_target_fill_grid if isinstance(locked_target_fill_grid, dict) else {}
  rows_by_quarter: Dict[int, List[Dict[str, Any]]] = {}
  for row in (grid.get("rows") or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    metric_name = str(row.get("metric_name") or "").strip().lower()
    target_value = _safe_float(row.get("recommended_target_value"))
    if quarter_index < 1 or not metric_name or target_value is None:
      continue
    rows_by_quarter.setdefault(quarter_index, []).append(
      {
        "metric_name": metric_name,
        "target_value": int(round(float(target_value))),
      }
    )
  return [
    {
      "quarter_index": quarter_index,
      "metric_targets": sorted(
        rows_by_quarter.get(quarter_index) or [],
        key=lambda item: str(item.get("metric_name") or ""),
      ),
    }
    for quarter_index in sorted(rows_by_quarter.keys())
  ]

def _unified_lever_control_fill_grid(
  *,
  allowed_lever_ids: Optional[List[str]],
  target_quarters: Optional[List[int]],
  baseline_map: Optional[Dict[str, List[float]]],
  full_horizon_quarter_count: int,
  deterministic_numeric_guidance: Optional[Dict[str, Any]] = None,
  business_world_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  normalized_target_quarters = [
    int(_safe_float(item) or 0)
    for item in (target_quarters or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  normalized_target_quarters = list(dict.fromkeys(normalized_target_quarters))
  first_target_quarter = min(normalized_target_quarters or [1])
  horizon_count = max(1, int(full_horizon_quarter_count or _CONVERGENCE_DEFAULT_QUARTER_COUNT))
  baseline_values = baseline_map if isinstance(baseline_map, dict) else {}
  allowed_mapping_by_lever = _lever_allowed_mapped_repair_targets(
    deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  )
  guidance_scaffold_rows = (
    (deterministic_numeric_guidance or {}).get("lever_band_scaffold") or []
    if isinstance(deterministic_numeric_guidance, dict)
    else []
  )
  scaffold_by_lever = {
    str(item.get("lever_id") or "").strip(): item
    for item in guidance_scaffold_rows
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  }
  world_contract = business_world_contract if isinstance(business_world_contract, dict) else {}
  stage_ramp_contract = (
    world_contract.get("stage_ramp_contract")
    if isinstance(world_contract.get("stage_ramp_contract"), dict)
    else {}
  )
  stage_ramp_rule = {}
  if stage_ramp_contract:
    stage_ramp_rule = {
      "applies_to": "composite_revenue_and_gpt_selected_payroll_headcount_schedule",
      "composite_revenue_formula": "sum(Capacity * Unit Price * Utilization) across all product rows",
      "ordinary_revenue_qoq_max": _safe_float(stage_ramp_contract.get("revenue_qoq_growth_target_max")),
      "revenue_qoq_spike_max": _safe_float(stage_ramp_contract.get("revenue_qoq_max_spike")),
      "spike_from_quarters": copy.deepcopy(stage_ramp_contract.get("revenue_spike_window_quarters") or []),
      "max_spike_count": int(_safe_float(stage_ramp_contract.get("max_spike_count")) or 0),
      "quarter_ramp_grid": copy.deepcopy(_stage_ramp_grid_rows(stage_ramp_contract)),
      "grid_rule": "Q1 is an active forecast-quarter row. For Q2-Q20, use quarter_ramp_grid row quarter_index=N as the hard revenue QoQ boundary from Q(N-1) into QN. Payroll is calculated from the separate SQL-backed payroll_headcount_schedule and is not a writable repair lever.",
      "rule": (
        "When selecting revenue levers, the combined product revenue path created by all Capacity, Unit Price, "
        "and Utilization trajectories must stay inside this ramp contract. Payroll remains Python-calculated from the persisted "
        "payroll headcount schedule."
      ),
    }
  rows: List[Dict[str, Any]] = []
  for lever_id in [
    str(item or "").strip()
    for item in (allowed_lever_ids or [])
    if str(item or "").strip()
  ]:
    mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
    target_metric_name = post_intake_direct_target_metric_for_lever(lever_id)
    scaffold_entry = scaffold_by_lever.get(lever_id) or {}
    canonical_value_meta = _canonical_writable_lever_value_metadata(
      lever_id=lever_id,
      value_kind=scaffold_entry.get("value_kind"),
      input_semantics=scaffold_entry.get("input_semantics"),
    )
    value_kind = str(canonical_value_meta.get("value_kind") or "").strip().lower()
    input_semantics = str(canonical_value_meta.get("input_semantics") or "").strip().lower()
    ratio_like_value = value_kind == "ratio" or "percent_of_" in input_semantics
    suggested_min_raw = _safe_float(scaffold_entry.get("suggested_min_value"))
    suggested_max_raw = _safe_float(scaffold_entry.get("suggested_max_value"))
    suggested_min_value = (
      round(float(suggested_min_raw), 2)
      if ratio_like_value and suggested_min_raw is not None
      else int(round(float(suggested_min_raw)))
      if suggested_min_raw is not None
      else None
    )
    suggested_max_value = (
      round(float(suggested_max_raw), 2)
      if ratio_like_value and suggested_max_raw is not None
      else int(round(float(suggested_max_raw)))
      if suggested_max_raw is not None
      else None
    )
    required_quarters = copy.deepcopy(normalized_target_quarters)
    values = [
      float(_safe_float(value) or 0.0)
      for value in (baseline_values.get(lever_id) or [])
    ]
    rows.append(
      {
        "lever_id": lever_id,
        "direct_target_metric_name": target_metric_name,
        "target_driver": str(mapping_entry.get("target_driver") or "").strip() or None,
        "driver_value_unit": str(input_semantics or value_kind or "").strip() or None,
        "return_value_in": "driver_units",
        "driver_value_rule": "Fill exact_value/min_value/max_value in model-input driver units, not financial target dollars.",
        "numeric_precision_rule": (
          "ratio_like_driver_two_decimals_only; use 0.02 or 0.03, never 0.025"
          if ratio_like_value
          else "currency_driver_integer_only"
        ),
        "suggested_min_value": suggested_min_value,
        "suggested_max_value": suggested_max_value,
        "required_control_quarters": copy.deepcopy(required_quarters),
        "lever_adjustment_template": {
          "lever_id": lever_id,
          "value_mode": "band",
          "exact_value": None,
          "min_value": suggested_min_value,
          "max_value": suggested_max_value,
          "timing_start_q": min(required_quarters) if required_quarters else None,
          "timing_end_q": max(required_quarters) if required_quarters else None,
          "control_quarters_to_fill": copy.deepcopy(required_quarters),
          "values_to_fill": [
            "value_mode",
            "timing_start_q",
            "timing_end_q",
            "exact_value_or_min_value_and_max_value_already_prefilled_from_locked_bounds",
            "shape_type_or_trajectory_values_when_required",
          ],
        },
        "current_values": {
          str(quarter): (
            round(float(values[quarter - 1]), 2)
            if ratio_like_value and 0 <= quarter - 1 < len(values)
            else int(round(float(values[quarter - 1])))
            if 0 <= quarter - 1 < len(values)
            else None
          )
          for quarter in required_quarters
        },
        "stage_ramp_rule": copy.deepcopy(stage_ramp_rule) if target_metric_name == "revenue" and stage_ramp_rule else {},
      }
    )
  return {
    "contract_version": "unified_convergence_locked_lever_control_fill_grid_v1",
    "grid_rule": (
      "If GPT selects a lever, fill the corresponding full_horizon_model_input_repair_contract editable cells only. "
      "Do not fill legacy lever_adjustments; Python derives issue/target mapping from the SQL mapping lookup."
    ),
    "stage_ramp_rule": copy.deepcopy(stage_ramp_rule),
    "rows": rows,
  }

def _lever_contract_precision_kind(
  *,
  lever_id: Any,
  value_kind: Any = "",
  input_semantics: Any = "",
  numeric_precision_rule: Any = "",
) -> str:
  lever = str(lever_id or "").strip()
  canonical = _canonical_writable_lever_value_metadata(
    lever_id=lever,
    value_kind=value_kind,
    input_semantics=input_semantics,
  )
  kind = str(canonical.get("value_kind") or value_kind or "").strip().lower()
  semantics = str(canonical.get("input_semantics") or input_semantics or "").strip().lower()
  precision_rule = str(numeric_precision_rule or "").strip().lower()
  if (
    kind == "ratio"
    or "percent_of_" in semantics
    or semantics in {"utilization_ratio", "interest_rate"}
    or "ratio_like" in precision_rule
  ):
    return "ratio_2dp"
  return "integer"

def _table_backed_metric_target_for_quarter(
  *,
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  metric_name: Any,
  quarter_index: int,
) -> Dict[str, Any]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  metric = str(metric_name or "").strip().lower()
  if not metric or quarter_index < 1:
    return {}

  def _target_from_values(payload: Dict[str, Any]) -> Optional[float]:
    direction = str(payload.get("direction") or payload.get("direction_hint") or "").strip().lower()
    floor_value = _safe_float(
      payload.get("target_floor")
      if payload.get("target_floor") is not None
      else payload.get("minimum_target_value")
      if payload.get("minimum_target_value") is not None
      else payload.get("suggested_floor_target")
    )
    ceiling_value = _safe_float(
      payload.get("target_ceiling")
      if payload.get("target_ceiling") is not None
      else payload.get("maximum_target_value")
      if payload.get("maximum_target_value") is not None
      else payload.get("suggested_ceiling_target")
    )
    equilibrium_value = _safe_float(payload.get("equilibrium_target"))
    if direction == "decrease" and ceiling_value is not None:
      return float(ceiling_value)
    if direction == "increase" and floor_value is not None:
      return float(floor_value)
    if equilibrium_value is not None:
      return float(equilibrium_value)
    if ceiling_value is not None:
      return float(ceiling_value)
    if floor_value is not None:
      return float(floor_value)
    return None

  for issue_packet in (guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    for repair_target in (issue_packet.get("repair_targets") or []):
      if not isinstance(repair_target, dict):
        continue
      if int(_safe_float(repair_target.get("quarter")) or 0) != int(quarter_index):
        continue
      if str(repair_target.get("metric") or "").strip().lower() != metric:
        continue
      target_value = _target_from_values(repair_target)
      if target_value is None:
        continue
      return {
        "metric_name": metric,
        "quarter_index": int(quarter_index),
        "target_value": float(target_value),
        "direction_hint": str(repair_target.get("direction") or "").strip().lower() or None,
        "issue_code": str(issue_packet.get("issue_code") or "").strip().lower() or None,
        "source": "issue_repair_packets",
      }

  for pressure_packet in (guidance.get("metric_pressure_packets") or []):
    if not isinstance(pressure_packet, dict):
      continue
    if int(_safe_float(pressure_packet.get("quarter_index")) or 0) != int(quarter_index):
      continue
    if str(pressure_packet.get("metric_name") or "").strip().lower() != metric:
      continue
    target_value = _target_from_values(pressure_packet)
    if target_value is None:
      continue
    return {
      "metric_name": metric,
      "quarter_index": int(quarter_index),
      "target_value": float(target_value),
      "direction_hint": str(pressure_packet.get("direction_hint") or "").strip().lower() or None,
      "issue_code": str(pressure_packet.get("issue_code") or "").strip().lower() or None,
      "source": "metric_pressure_packets",
    }
  return {}

def _stage_ramp_revenue_growth_limit_for_target(
  *,
  stage_ramp_contract: Optional[Dict[str, Any]],
  quarter_index: int,
  spike_count_used: int,
) -> Dict[str, Any]:
  contract = stage_ramp_contract if isinstance(stage_ramp_contract, dict) else {}
  target_quarter = int(quarter_index or 0)
  if target_quarter <= 1:
    return {"applies": False}
  row = {}
  for candidate in (contract.get("quarter_ramp_grid") or []):
    if not isinstance(candidate, dict):
      continue
    if int(_safe_float(candidate.get("quarter_index")) or 0) == target_quarter:
      row = candidate
      break
  if not row:
    return {"applies": False}
  ordinary_max = max(0.0, float(_safe_float(row.get("revenue_qoq_max")) or 0.0))
  spike_allowed = bool(row.get("revenue_qoq_spike_allowed"))
  spike_max = max(ordinary_max, float(_safe_float(row.get("revenue_qoq_spike_max")) or ordinary_max))
  max_spike_count = max(0, int(_safe_float(contract.get("max_spike_count")) or 0))
  spike_available = bool(spike_allowed and int(spike_count_used or 0) < max_spike_count)
  return {
    "applies": True,
    "quarter_index": target_quarter,
    "ordinary_growth_max": ordinary_max,
    "spike_growth_max": spike_max,
    "allowed_growth": spike_max if spike_available else ordinary_max,
    "spike_available": spike_available,
    "ramp_grid_row": copy.deepcopy(row),
  }

def _stage_ramp_constrain_revenue_metric_spec(
  *,
  spec: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]],
  revenue_target_state_by_quarter: Dict[int, float],
  stage_ramp_state: Dict[str, Any],
) -> Dict[str, Any]:
  next_spec = copy.deepcopy(spec if isinstance(spec, dict) else {})
  if str(next_spec.get("metric_name") or "").strip().lower() != "revenue":
    return next_spec
  quarter_index = int(_safe_float(next_spec.get("quarter_index")) or 0)
  if quarter_index < 1:
    return next_spec
  actual_value = _safe_float(next_spec.get("actual_value"))
  target_floor = _safe_float(next_spec.get("target_floor"))
  target_ceiling = _safe_float(next_spec.get("target_ceiling"))
  direction_hint = str(next_spec.get("direction_hint") or "").strip().lower()
  previous_revenue = _safe_float(revenue_target_state_by_quarter.get(quarter_index - 1))
  if previous_revenue is not None and previous_revenue > 0.0 and direction_hint == "increase":
    limit = _stage_ramp_revenue_growth_limit_for_target(
      stage_ramp_contract=stage_ramp_contract,
      quarter_index=quarter_index,
      spike_count_used=int(_safe_float(stage_ramp_state.get("spike_count_used")) or 0),
    )
    if bool(limit.get("applies")):
      ordinary_growth_max = float(_safe_float(limit.get("ordinary_growth_max")) or 0.0)
      allowed_growth = float(_safe_float(limit.get("allowed_growth")) or ordinary_growth_max)
      max_revenue = float(math.floor(max(0.0, float(previous_revenue) * (1.0 + allowed_growth))))
      if target_floor is not None and float(target_floor) > max_revenue:
        target_floor = max_revenue
        next_spec["target_floor"] = float(target_floor)
        next_spec["minimum_target_value"] = float(target_floor)
      if target_ceiling is not None and float(target_ceiling) > max_revenue:
        target_ceiling = max_revenue
        next_spec["target_ceiling"] = float(target_ceiling)
        next_spec["maximum_target_value"] = float(target_ceiling)
      boundary_value = _safe_float(next_spec.get("boundary_value"))
      if boundary_value is not None and float(boundary_value) > max_revenue:
        next_spec["boundary_value"] = float(max_revenue)
      chosen_target = target_floor if target_floor is not None else target_ceiling
      if chosen_target is not None:
        growth = (float(chosen_target) - float(previous_revenue)) / max(float(previous_revenue), 1e-9)
        if bool(limit.get("spike_available")) and growth > ordinary_growth_max + 1e-9:
          stage_ramp_state["spike_count_used"] = int(_safe_float(stage_ramp_state.get("spike_count_used")) or 0) + 1
        next_spec["stage_ramp_target_cap"] = {
          "source": "gpt_stage_ramp_contract",
          "quarter_index": quarter_index,
          "previous_revenue": int(round(float(previous_revenue))),
          "allowed_growth": round(float(allowed_growth), 6),
          "max_revenue": int(round(float(max_revenue))),
        }
  chosen_target = (
    target_floor
    if direction_hint == "increase" and target_floor is not None
    else target_ceiling
    if direction_hint == "decrease" and target_ceiling is not None
    else target_floor
    if target_floor is not None
    else target_ceiling
  )
  if chosen_target is not None:
    revenue_target_state_by_quarter[quarter_index] = max(0.0, float(chosen_target))
    if actual_value is not None:
      if direction_hint == "increase":
        next_gap = max(0.0, float(chosen_target) - float(actual_value))
      elif direction_hint == "decrease":
        next_gap = max(0.0, float(actual_value) - float(chosen_target))
      else:
        next_gap = abs(float(chosen_target) - float(actual_value))
      next_spec["gap"] = float(next_gap)
      next_spec["gap_abs"] = abs(float(next_gap))
  elif actual_value is not None:
    revenue_target_state_by_quarter[quarter_index] = max(0.0, float(actual_value))
  if target_floor is not None or target_ceiling is not None:
    next_spec["acceptable_zone"] = {
      "minimum": float(target_floor) if target_floor is not None else None,
      "maximum": float(target_ceiling) if target_ceiling is not None else None,
    }
    repair_envelope = copy.deepcopy(next_spec.get("repair_envelope") or {})
    current = float(actual_value) if actual_value is not None else float(chosen_target or 0.0)
    if direction_hint == "increase" and target_floor is not None:
      delta = max(0.0, float(target_floor) - current)
      repair_envelope["min_required_delta"] = delta
      repair_envelope["recommended_delta"] = delta
      repair_envelope["max_feasible_delta"] = delta
    elif direction_hint == "decrease" and target_ceiling is not None:
      delta = min(0.0, float(target_ceiling) - current)
      repair_envelope["min_required_delta"] = delta
      repair_envelope["recommended_delta"] = delta
      repair_envelope["max_feasible_delta"] = delta
    next_spec["repair_envelope"] = repair_envelope
  return next_spec

def _baseline_revenue_from_formula_levers(
  *,
  baseline_values_by_lever: Dict[str, List[float]],
  quarter_index: int,
) -> float:
  groups: Dict[str, Dict[str, float]] = {}
  for lever_id, values in (baseline_values_by_lever or {}).items():
    lever = str(lever_id or "").strip()
    if not lever or not isinstance(values, list):
      continue
    mapping_entry = post_intake_driver_target_mapping_entry(lever) or {}
    if str(mapping_entry.get("target_metric_name") or "").strip().lower() != "revenue":
      continue
    if str(mapping_entry.get("driver_bundle") or "").strip().lower() != "revenue_formula_bundle":
      continue
    target_driver = str(mapping_entry.get("target_driver") or "").strip().lower()
    if target_driver not in {"capacity", "unit_price", "utilization"}:
      continue
    if not (0 <= int(quarter_index) - 1 < len(values)):
      continue
    value = _safe_float(values[int(quarter_index) - 1])
    if value is None:
      continue
    group_key = lever.rsplit("::", 1)[0]
    groups.setdefault(group_key, {})[target_driver] = max(0.0, float(value))
  revenue = 0.0
  for drivers in groups.values():
    if all(driver in drivers for driver in ("capacity", "unit_price", "utilization")):
      revenue += (
        float(drivers.get("capacity") or 0.0)
        * float(drivers.get("unit_price") or 0.0)
        * float(drivers.get("utilization") or 0.0)
      )
  return max(0.0, float(revenue))

def _stage_ramp_capped_revenue_targets_by_quarter(
  *,
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  business_world_contract: Optional[Dict[str, Any]],
  baseline_values_by_lever: Dict[str, List[float]],
  horizon_count: int,
) -> Dict[int, float]:
  world_contract = business_world_contract if isinstance(business_world_contract, dict) else {}
  stage_ramp_contract = (
    world_contract.get("stage_ramp_contract")
    if isinstance(world_contract.get("stage_ramp_contract"), dict)
    else {}
  )
  capped_targets: Dict[int, float] = {}
  spike_state: Dict[str, Any] = {"spike_count_used": 0}
  previous_revenue: Optional[float] = None
  for quarter_index in range(1, max(1, int(horizon_count or 1)) + 1):
    current_revenue = _baseline_revenue_from_formula_levers(
      baseline_values_by_lever=baseline_values_by_lever,
      quarter_index=quarter_index,
    )
    target_payload = _table_backed_metric_target_for_quarter(
      deterministic_numeric_guidance=deterministic_numeric_guidance,
      metric_name="revenue",
      quarter_index=quarter_index,
    )
    raw_target = _safe_float(target_payload.get("target_value"))
    target_revenue = max(0.0, float(raw_target if raw_target is not None else current_revenue))
    if previous_revenue is not None and previous_revenue > 0.0 and target_revenue > previous_revenue:
      limit = _stage_ramp_revenue_growth_limit_for_target(
        stage_ramp_contract=stage_ramp_contract,
        quarter_index=quarter_index,
        spike_count_used=int(_safe_float(spike_state.get("spike_count_used")) or 0),
      )
      if bool(limit.get("applies")):
        ordinary_growth_max = float(_safe_float(limit.get("ordinary_growth_max")) or 0.0)
        allowed_growth = float(_safe_float(limit.get("allowed_growth")) or ordinary_growth_max)
        max_revenue = float(math.floor(max(0.0, float(previous_revenue) * (1.0 + allowed_growth))))
        if target_revenue > max_revenue:
          target_revenue = max_revenue
        growth = (float(target_revenue) - float(previous_revenue)) / max(float(previous_revenue), 1e-9)
        if bool(limit.get("spike_available")) and growth > ordinary_growth_max + 1e-9:
          spike_state["spike_count_used"] = int(_safe_float(spike_state.get("spike_count_used")) or 0) + 1
    capped_targets[quarter_index] = max(0.0, float(target_revenue))
    previous_revenue = capped_targets[quarter_index]
  return capped_targets

def _table_backed_formula_driver_cell_bounds(
  *,
  lever_id: str,
  quarter_index: int,
  current_value: Optional[float],
  min_value: Optional[float],
  max_value: Optional[float],
  baseline_values_by_lever: Dict[str, List[float]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  revenue_target_caps_by_quarter: Optional[Dict[int, float]] = None,
) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
  mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
  target_metric = str(mapping_entry.get("target_metric_name") or "").strip().lower()
  driver_bundle = str(mapping_entry.get("driver_bundle") or "").strip().lower()
  target_driver = str(mapping_entry.get("target_driver") or "").strip().lower()
  if target_metric != "revenue" or driver_bundle != "revenue_formula_bundle":
    return min_value, max_value, {}
  if target_driver not in {"capacity", "unit_price", "utilization"}:
    return min_value, max_value, {}
  target_payload = _table_backed_metric_target_for_quarter(
    deterministic_numeric_guidance=deterministic_numeric_guidance,
    metric_name=target_metric,
    quarter_index=quarter_index,
  )
  target_value = _safe_float(target_payload.get("target_value"))
  if target_value is None:
    return min_value, max_value, {}
  capped_target_value = _safe_float((revenue_target_caps_by_quarter or {}).get(int(quarter_index)))
  target_cap_source = None
  if capped_target_value is not None and float(target_value) > float(capped_target_value):
    target_value = float(capped_target_value)
    target_cap_source = "stage_ramp_contract"

  group_prefix = str(lever_id).rsplit("::", 1)[0]
  driver_levers: Dict[str, str] = {}
  for candidate_lever in baseline_values_by_lever.keys():
    if not str(candidate_lever).startswith(group_prefix + "::"):
      continue
    candidate_mapping = post_intake_driver_target_mapping_entry(candidate_lever) or {}
    if str(candidate_mapping.get("target_metric_name") or "").strip().lower() != target_metric:
      continue
    if str(candidate_mapping.get("driver_bundle") or "").strip().lower() != driver_bundle:
      continue
    candidate_driver = str(candidate_mapping.get("target_driver") or "").strip().lower()
    if candidate_driver in {"capacity", "unit_price", "utilization"}:
      driver_levers[candidate_driver] = str(candidate_lever)
  if not all(driver in driver_levers for driver in ("capacity", "unit_price", "utilization")):
    return min_value, max_value, {
      "envelope_basis": "sql_mapping_formula_target",
      "formula": "revenue = Capacity * Unit Price * Utilization",
      "status": "incomplete_mapping_bundle",
      "missing_drivers": [
        driver for driver in ("capacity", "unit_price", "utilization")
        if driver not in driver_levers
      ],
    }

  def _baseline(driver: str) -> Optional[float]:
    values = baseline_values_by_lever.get(driver_levers[driver]) or []
    if 0 <= quarter_index - 1 < len(values):
      return _safe_float(values[quarter_index - 1])
    return None

  companion_values = {
    "capacity": _baseline("capacity"),
    "unit_price": _baseline("unit_price"),
    "utilization": _baseline("utilization"),
  }
  denominator = 1.0
  for driver, value in companion_values.items():
    if driver == target_driver:
      continue
    parsed = _safe_float(value)
    if parsed is None or float(parsed) <= 0:
      return min_value, max_value, {
        "envelope_basis": "sql_mapping_formula_target",
        "formula": "revenue = Capacity * Unit Price * Utilization",
        "status": "invalid_formula_denominator",
        "target_driver": target_driver,
        "companion_driver_values": copy.deepcopy(companion_values),
      }
    denominator *= float(parsed)
  required_driver_value = max(0.0, float(target_value) / max(float(denominator), 1e-9))
  current_revenue = (
    float(companion_values["capacity"] or 0.0)
    * float(companion_values["unit_price"] or 0.0)
    * float(companion_values["utilization"] or 0.0)
  )
  direction = str(target_payload.get("direction_hint") or "").strip().lower()
  adjusted_min = min_value
  adjusted_max = max_value
  current_float = _safe_float(current_value)
  if direction == "decrease" or float(target_value) < current_revenue:
    adjusted_min = min(float(adjusted_min), float(required_driver_value)) if adjusted_min is not None else float(required_driver_value)
    if current_float is not None:
      adjusted_max = min(float(adjusted_max), float(current_float)) if adjusted_max is not None else float(current_float)
  elif direction == "increase":
    adjusted_max = max(float(adjusted_max), float(required_driver_value)) if adjusted_max is not None else float(required_driver_value)
    if current_float is not None:
      adjusted_min = max(float(adjusted_min), float(current_float)) if adjusted_min is not None else float(current_float)
  else:
    adjusted_min = min(float(adjusted_min), float(required_driver_value)) if adjusted_min is not None else float(required_driver_value)
    adjusted_max = max(float(adjusted_max), float(required_driver_value)) if adjusted_max is not None else float(required_driver_value)

  # For formula-backed metrics, the mapping-table formula is authoritative over
  # generic relative movement bands. A generic band may narrow the move, but it
  # must never exclude the driver value required to make the mapped formula target
  # mathematically reachable.
  if adjusted_min is None or float(adjusted_min) > float(required_driver_value):
    adjusted_min = float(required_driver_value)
  if adjusted_max is None or float(adjusted_max) < float(required_driver_value):
    adjusted_max = float(required_driver_value)

  adjusted_min = max(0.0, float(adjusted_min)) if adjusted_min is not None else None
  adjusted_max = max(0.0, float(adjusted_max)) if adjusted_max is not None else None
  if target_driver == "utilization":
    adjusted_min = min(1.0, max(0.0, float(adjusted_min))) if adjusted_min is not None else None
    adjusted_max = min(1.0, max(0.0, float(adjusted_max))) if adjusted_max is not None else None
  if adjusted_min is not None and adjusted_max is not None and adjusted_min > adjusted_max:
    adjusted_min, adjusted_max = adjusted_max, adjusted_min
  return adjusted_min, adjusted_max, {
    "envelope_basis": "sql_mapping_formula_target",
    "formula": "revenue = Capacity * Unit Price * Utilization",
    "mapping_table": "post_intak_mapping_lookup",
    "target_metric_name": target_metric,
    "target_driver": target_driver,
    "target_value": int(round(float(target_value))),
    "target_cap_source": target_cap_source,
    "direction_hint": direction or None,
    "required_driver_value_if_companions_unchanged": (
      round(float(required_driver_value), 2)
      if target_driver == "utilization"
      else int(round(float(required_driver_value)))
    ),
    "companion_driver_values": {
      key: round(float(value), 6) if value is not None else None
      for key, value in companion_values.items()
    },
  }

def _table_backed_formula_envelope_feasibility_errors(
  *,
  rows: List[Dict[str, Any]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  horizon_count: int,
) -> List[str]:
  errors: List[str] = []
  rows_by_quarter_group: Dict[Tuple[int, str], Dict[str, Dict[str, Any]]] = {}
  for row in rows:
    if not isinstance(row, dict) or str(row.get("edit_status") or "") != "editable":
      continue
    lever_id = str(row.get("lever_id") or "").strip()
    mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
    if str(mapping_entry.get("target_metric_name") or "").strip().lower() != "revenue":
      continue
    if str(mapping_entry.get("driver_bundle") or "").strip().lower() != "revenue_formula_bundle":
      continue
    target_driver = str(mapping_entry.get("target_driver") or "").strip().lower()
    if target_driver not in {"capacity", "unit_price", "utilization"}:
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    group_key = str(lever_id).rsplit("::", 1)[0]
    if quarter_index < 1 or not group_key:
      continue
    rows_by_quarter_group.setdefault((quarter_index, group_key), {})[target_driver] = row
  for quarter_index in range(1, max(1, int(horizon_count or 1)) + 1):
    target_payload = _table_backed_metric_target_for_quarter(
      deterministic_numeric_guidance=deterministic_numeric_guidance,
      metric_name="revenue",
      quarter_index=quarter_index,
    )
    target_value = _safe_float(target_payload.get("target_value"))
    if target_value is None:
      continue
    revenue_min = 0.0
    revenue_max = 0.0
    complete_group_count = 0
    for (_row_quarter, group_key), driver_rows in rows_by_quarter_group.items():
      if _row_quarter != quarter_index:
        continue
      if not all(driver in driver_rows for driver in ("capacity", "unit_price", "utilization")):
        continue
      group_min = 1.0
      group_max = 1.0
      for driver in ("capacity", "unit_price", "utilization"):
        row = driver_rows[driver]
        min_value = _safe_float(row.get("min_value"))
        max_value = _safe_float(row.get("max_value"))
        if min_value is None or max_value is None:
          group_min = 0.0
          group_max = -1.0
          break
        group_min *= max(0.0, float(min(min_value, max_value)))
        group_max *= max(0.0, float(max(min_value, max_value)))
      if group_max >= 0.0:
        revenue_min += float(group_min)
        revenue_max += float(group_max)
        complete_group_count += 1
    if complete_group_count <= 0:
      continue
    tolerance = max(1.0, abs(float(target_value)) * 0.05)
    if float(target_value) < revenue_min - tolerance or float(target_value) > revenue_max + tolerance:
      errors.append(
        "formula_envelope_impossible: "
        + json.dumps(
          {
            "quarter_index": quarter_index,
            "metric_name": "revenue",
            "target_value": int(round(float(target_value))),
            "envelope_min_revenue": int(round(float(revenue_min))),
            "envelope_max_revenue": int(round(float(revenue_max))),
            "mapping_table": "post_intak_mapping_lookup",
            "formula": "revenue = Capacity * Unit Price * Utilization",
            "detail": "Driver cell bounds generated from the mapping table cannot produce the mapped revenue target.",
          },
          ensure_ascii=False,
        )
      )
  return errors

def _full_horizon_model_input_repair_contract(
  *,
  model_input_json: Optional[Dict[str, Any]],
  locked_lever_control_fill_grid: Optional[Dict[str, Any]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  allowed_lever_ids: Optional[List[str]],
  quarter_count: Optional[int] = None,
  business_world_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  grid = locked_lever_control_fill_grid if isinstance(locked_lever_control_fill_grid, dict) else {}
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  allowed_set = {
    str(item or "").strip()
    for item in (allowed_lever_ids or [])
    if str(item or "").strip()
  }
  horizon_count = max(
    1,
    min(
      _CONVERGENCE_DEFAULT_QUARTER_COUNT,
      int(quarter_count or _quarter_count_from_model_input(model_input) or _CONVERGENCE_DEFAULT_QUARTER_COUNT),
    ),
  )
  baseline_values_by_lever = _solved_lever_value_map(model_input)
  revenue_target_caps_by_quarter = _stage_ramp_capped_revenue_targets_by_quarter(
    deterministic_numeric_guidance=guidance,
    business_world_contract=copy.deepcopy(business_world_contract or {}),
    baseline_values_by_lever=baseline_values_by_lever,
    horizon_count=horizon_count,
  )
  catalog_entry_by_lever = _lever_review_catalog_entry_map(_build_writable_lever_review_catalog(model_input))
  grid_rows_by_lever = {
    str(item.get("lever_id") or "").strip(): copy.deepcopy(item)
    for item in (grid.get("rows") or [])
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  }
  allowed_mapping_by_lever = _lever_allowed_mapped_repair_targets(guidance)
  rows: List[Dict[str, Any]] = []
  required_cell_ids: List[str] = []
  editable_lever_ids: List[str] = []
  for lever_id in [
    str(item or "").strip()
    for item in (allowed_lever_ids or [])
    if str(item or "").strip()
  ]:
    mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
    if not mapping_entry:
      continue
    control_owner = str(mapping_entry.get("control_owner") or "").strip().lower()
    grid_row = grid_rows_by_lever.get(lever_id) or {}
    catalog_entry = catalog_entry_by_lever.get(lever_id) or {}
    value_kind = str(catalog_entry.get("value_kind") or grid_row.get("value_kind") or "").strip()
    input_semantics = str(catalog_entry.get("input_semantics") or grid_row.get("driver_value_unit") or "").strip()
    precision_kind = _lever_contract_precision_kind(
      lever_id=lever_id,
      value_kind=value_kind,
      input_semantics=input_semantics,
      numeric_precision_rule=grid_row.get("numeric_precision_rule"),
    )
    suggested_min = _safe_float(grid_row.get("suggested_min_value"))
    suggested_max = _safe_float(grid_row.get("suggested_max_value"))
    if suggested_min is not None and suggested_max is not None and suggested_min > suggested_max:
      suggested_min, suggested_max = suggested_max, suggested_min
    locked_reason = ""
    edit_status = "editable"
    if lever_id not in allowed_set:
      edit_status = "locked"
      locked_reason = "lever is outside this cycle's deterministic allowed lever set"
    elif control_owner != "gpt_editable":
      edit_status = "derived"
      locked_reason = f"lever is owned by {control_owner or 'non_gpt'} policy, not GPT convergence"
    elif suggested_min is None or suggested_max is None:
      edit_status = "locked"
      locked_reason = "missing deterministic min/max driver bounds"
    if edit_status == "editable":
      editable_lever_ids.append(lever_id)
    current_values = baseline_values_by_lever.get(lever_id) or []
    issue_codes = sorted(
      {
        str(item.get("issue_code") or "").strip().lower()
        for item in (allowed_mapping_by_lever.get(lever_id) or [])
        if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
      }
    )
    issue_target_metrics = sorted(
      {
        str(item.get("target_metric_name") or "").strip().lower()
        for item in (allowed_mapping_by_lever.get(lever_id) or [])
        if isinstance(item, dict) and str(item.get("target_metric_name") or "").strip()
      }
    )
    issue_target_quarters = sorted(
      {
        int(_safe_float(quarter) or 0)
        for item in (allowed_mapping_by_lever.get(lever_id) or [])
        if isinstance(item, dict)
        for quarter in (item.get("target_quarters") or [])
        if int(_safe_float(quarter) or 0) >= 1
      }
    )
    for quarter_index in range(1, horizon_count + 1):
      current_value = (
        _safe_float(current_values[quarter_index - 1])
        if 0 <= quarter_index - 1 < len(current_values)
        else None
      )
      min_value = suggested_min
      max_value = suggested_max
      direction_hint = str(grid_row.get("direction_hint") or "").strip().lower()
      max_relative_change = max(0.0, float(_safe_float(grid_row.get("max_relative_change")) or 0.0))
      if current_value is not None and direction_hint in {"decrease", "increase"}:
        current_float = float(current_value)
        if direction_hint == "decrease":
          if max_value is None or float(max_value) > current_float:
            max_value = current_float
          if min_value is None or float(min_value) >= float(max_value):
            move_scale = max(max_relative_change, 0.35)
            min_value = current_float - max(abs(current_float) * move_scale, 1.0)
          if value_kind == "ratio" or "percent_of_" in input_semantics:
            min_value = max(0.0, float(min_value))
          else:
            min_value = max(0.0, float(min_value))
        elif direction_hint == "increase":
          if min_value is None or float(min_value) < current_float:
            min_value = current_float
          if max_value is None or float(max_value) <= float(min_value):
            move_scale = max(max_relative_change, 0.35)
            max_value = current_float + max(abs(current_float) * move_scale, 1.0)
      formula_envelope = {}
      min_value, max_value, formula_envelope = _table_backed_formula_driver_cell_bounds(
        lever_id=lever_id,
        quarter_index=quarter_index,
        current_value=current_value,
        min_value=min_value,
        max_value=max_value,
        baseline_values_by_lever=baseline_values_by_lever,
        deterministic_numeric_guidance=guidance,
        revenue_target_caps_by_quarter=revenue_target_caps_by_quarter,
      )
      if precision_kind == "ratio_2dp":
        display_current = round(float(current_value), 2) if current_value is not None else None
        display_min = round(float(min_value), 2) if min_value is not None else None
        display_max = round(float(max_value), 2) if max_value is not None else None
      else:
        display_current = int(round(float(current_value))) if current_value is not None else None
        display_min = int(round(float(min_value))) if min_value is not None else None
        display_max = int(round(float(max_value))) if max_value is not None else None
      cell_id = f"{lever_id}|Q{quarter_index}"
      if edit_status == "editable":
        required_cell_ids.append(cell_id)
      rows.append(
        {
          "cell_id": cell_id,
          "lever_id": lever_id,
          "quarter_index": quarter_index,
          "edit_status": edit_status,
          "locked_reason": locked_reason,
          "current_value": display_current,
          "min_value": display_min,
          "max_value": display_max,
          "value_kind": value_kind,
          "input_semantics": input_semantics,
          "numeric_precision_rule": (
            "ratio_or_percent_must_use_at_most_2_decimals"
            if precision_kind == "ratio_2dp"
            else "currency_or_count_must_be_integer"
          ),
          "target_driver": str(mapping_entry.get("target_driver") or "").strip(),
          "target_metric_name": str(mapping_entry.get("target_metric_name") or "").strip().lower(),
          "financial_model_field": str(mapping_entry.get("financial_model_field") or "").strip(),
          "impact_type": str(mapping_entry.get("impact_type") or "").strip().lower(),
          "mapped_repair_targets": copy.deepcopy(allowed_mapping_by_lever.get(lever_id) or []),
          "issue_codes": copy.deepcopy(issue_codes),
          "issue_target_metrics": copy.deepcopy(issue_target_metrics),
          "issue_target_quarters": copy.deepcopy(issue_target_quarters),
          "formula_envelope": copy.deepcopy(formula_envelope) if formula_envelope else None,
        }
      )
  formula_feasibility_errors = _table_backed_formula_envelope_feasibility_errors(
    rows=rows,
    deterministic_numeric_guidance=guidance,
    horizon_count=horizon_count,
  )
  if formula_feasibility_errors:
    raise RuntimeError(
      "post_intake_formula_driver_envelope_invalid: "
      + "; ".join(formula_feasibility_errors[:10])
    )
  return {
    "contract_version": _FULL_HORIZON_MODEL_INPUT_REPAIR_CONTRACT_VERSION,
    "state_rule": "model_input_json Q1-Q20 is the only mutable truth; finmo_json is rebuilt from model_input_json after cells are applied",
    "horizon_quarters": list(range(1, horizon_count + 1)),
    "cell_rule": "GPT may return values only for editable_cells. Locked and derived cells are read-only.",
    "required_response_rule": "Return exactly one model_input_repair_cells item for every required_editable_cell_id.",
    "editable_lever_ids": copy.deepcopy(editable_lever_ids),
    "required_editable_cell_ids": copy.deepcopy(required_cell_ids),
    "editable_cell_count": len(required_cell_ids),
    "envelope_source": "table_backed_formula_driver_envelope",
    "formula_envelope_policy": {
      "mapping_table": "post_intak_mapping_lookup",
      "rule": "Formula-backed target metrics derive driver cell envelopes from SQL mapping bundles before GPT sees the repair contract.",
    },
    "editable_cells": [copy.deepcopy(row) for row in rows if row.get("edit_status") == "editable"],
    "locked_cells": [copy.deepcopy(row) for row in rows if row.get("edit_status") != "editable"],
  }

def _model_input_repair_cell_schema(
  allowed_cell_ids: Optional[List[str]],
  allowed_lever_ids: Optional[List[str]],
  allowed_quarters: Optional[List[int]],
) -> Dict[str, Any]:
  cell_ids = [str(item).strip() for item in (allowed_cell_ids or []) if str(item).strip()]
  lever_ids = [str(item).strip() for item in (allowed_lever_ids or []) if str(item).strip()]
  quarters = [
    int(_safe_float(item) or 0)
    for item in (allowed_quarters or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  return {
    "type": "array",
    "minItems": len(cell_ids) if cell_ids else 0,
    "maxItems": len(cell_ids) if cell_ids else 0,
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "cell_id": {"type": "string", "enum": cell_ids or [""]},
        "lever_id": {"type": "string", "enum": lever_ids or [""]},
        "quarter_index": {"type": "integer", "enum": quarters or [1]},
        "value": {"type": "number"},
        "rationale": {"type": "string"},
      },
      "required": [
        "cell_id",
        "lever_id",
        "quarter_index",
        "value",
        "rationale",
      ],
    },
  }

def _normalize_model_input_repair_cell_value(
  *,
  value: Any,
  contract_cell: Dict[str, Any],
) -> Tuple[Optional[float], Optional[str]]:
  numeric_value = _safe_float(value)
  if numeric_value is None:
    return None, "value must be numeric"
  precision_rule = str(contract_cell.get("numeric_precision_rule") or "").strip().lower()
  if "2_decimals" in precision_rule:
    normalized = round(float(numeric_value), 2)
    if abs(float(numeric_value) - float(normalized)) > 0.0050001:
      return None, (
        "ratio/percent value has more than formatting-level decimal drift; "
        f"received={numeric_value}, normalized={normalized}"
      )
    return float(normalized), None
  normalized_int = int(round(float(numeric_value)))
  if abs(float(numeric_value) - float(normalized_int)) > 0.5000001:
    return None, (
      "currency/count value has more than formatting-level integer drift; "
      f"received={numeric_value}, normalized={normalized_int}"
    )
  return float(normalized_int), None

def _validate_and_normalize_model_input_repair_cells(
  *,
  parsed: Optional[Dict[str, Any]],
  full_horizon_model_input_repair_contract: Optional[Dict[str, Any]],
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  contract = (
    full_horizon_model_input_repair_contract
    if isinstance(full_horizon_model_input_repair_contract, dict)
    else {}
  )
  required_ids = [
    str(item).strip()
    for item in (contract.get("required_editable_cell_ids") or [])
    if str(item).strip()
  ]
  cells = [item for item in (decision.get("model_input_repair_cells") or []) if isinstance(item, dict)]
  editable_lookup = {
    str(item.get("cell_id") or "").strip(): item
    for item in (contract.get("editable_cells") or [])
    if isinstance(item, dict) and str(item.get("cell_id") or "").strip()
  }
  if len(cells) != len(required_ids):
    return (
      "model_input_repair_cells must contain exactly one row for every required_editable_cell_id. "
      f"required_count={len(required_ids)}, provided_count={len(cells)}."
    )
  seen_ids: set[str] = set()
  selected_levers = {
    str(item or "").strip()
    for item in (decision.get("lever_selection") or [])
    if str(item or "").strip()
  }
  for cell in cells:
    cell_id = str(cell.get("cell_id") or "").strip()
    if not cell_id:
      return "model_input_repair_cells contains a row with missing cell_id."
    if cell_id in seen_ids:
      return f"model_input_repair_cells contains duplicate cell_id {cell_id}."
    seen_ids.add(cell_id)
    contract_cell = editable_lookup.get(cell_id)
    if not isinstance(contract_cell, dict) or not contract_cell:
      return f"model_input_repair_cells contains non-editable or unknown cell_id {cell_id}."
    lever_id = str(cell.get("lever_id") or "").strip()
    expected_lever_id = str(contract_cell.get("lever_id") or "").strip()
    if lever_id != expected_lever_id:
      return f"{cell_id} lever_id mismatch. expected={expected_lever_id}, received={lever_id}."
    if selected_levers and lever_id not in selected_levers:
      return f"{cell_id} lever_id {lever_id} must also appear in lever_selection."
    quarter_index = int(_safe_float(cell.get("quarter_index")) or 0)
    expected_quarter = int(_safe_float(contract_cell.get("quarter_index")) or 0)
    if quarter_index != expected_quarter:
      return f"{cell_id} quarter_index mismatch. expected={expected_quarter}, received={quarter_index}."
    normalized_value, normalization_error = _normalize_model_input_repair_cell_value(
      value=cell.get("value"),
      contract_cell=contract_cell,
    )
    if normalization_error:
      return f"{cell_id} invalid value format. {normalization_error}."
    minimum = _safe_float(contract_cell.get("min_value"))
    maximum = _safe_float(contract_cell.get("max_value"))
    if minimum is not None and normalized_value is not None and normalized_value < float(minimum):
      return (
        f"{cell_id} value is below deterministic min_value. "
        f"value={normalized_value}, min_value={minimum}."
      )
    if maximum is not None and normalized_value is not None and normalized_value > float(maximum):
      return (
        f"{cell_id} value is above deterministic max_value. "
        f"value={normalized_value}, max_value={maximum}."
      )
    cell["value"] = (
      round(float(normalized_value), 2)
      if "2_decimals" in str(contract_cell.get("numeric_precision_rule") or "").strip().lower()
      else int(round(float(normalized_value)))
    )
  missing_ids = [cell_id for cell_id in required_ids if cell_id not in seen_ids]
  extra_ids = [cell_id for cell_id in seen_ids if cell_id not in set(required_ids)]
  if missing_ids or extra_ids:
    return (
      "model_input_repair_cells must exactly match required_editable_cell_ids. "
      f"missing={missing_ids[:20]}, extra={extra_ids[:20]}."
    )
  return None

def _exact_updates_from_model_input_repair_cells(
  *,
  model_input_repair_cells: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  updates: List[Dict[str, Any]] = []
  for cell in [item for item in (model_input_repair_cells or []) if isinstance(item, dict)]:
    lever_id = str(cell.get("lever_id") or "").strip()
    quarter_index = int(_safe_float(cell.get("quarter_index")) or 0)
    value = _safe_float(cell.get("value"))
    if not lever_id or quarter_index < 1 or value is None:
      continue
    updates.append(
      {
        "lever_id": lever_id,
        "quarter_index": quarter_index,
        "exact_value": float(value),
        "source_cell_id": str(cell.get("cell_id") or "").strip(),
      }
    )
  return updates

def _convergence_issue_mapping_gate(
  *,
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  full_horizon_model_input_repair_contract: Optional[Dict[str, Any]],
  active_issue_count: int = 0,
) -> Dict[str, Any]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  contract = (
    full_horizon_model_input_repair_contract
    if isinstance(full_horizon_model_input_repair_contract, dict)
    else {}
  )
  issue_packets = [
    copy.deepcopy(item)
    for item in (guidance.get("issue_repair_packets") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  editable_cells = [
    copy.deepcopy(item)
    for item in (contract.get("editable_cells") or [])
    if isinstance(item, dict)
    and str(item.get("lever_id") or "").strip()
    and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  editable_by_lever_quarter = {
    (
      str(item.get("lever_id") or "").strip(),
      int(_safe_float(item.get("quarter_index")) or 0),
    ): copy.deepcopy(item)
    for item in editable_cells
  }
  editable_lever_ids = {
    str(item.get("lever_id") or "").strip()
    for item in editable_cells
    if str(item.get("lever_id") or "").strip()
  }
  contract_horizon_quarters = {
    int(_safe_float(item) or 0)
    for item in (contract.get("horizon_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  }
  if not contract_horizon_quarters:
    contract_horizon_quarters = set(range(1, _contract_forecast_quarter_count() + 1))
  max_contract_quarter = max(contract_horizon_quarters or {0})
  errors: List[Dict[str, Any]] = []
  issue_summaries: List[Dict[str, Any]] = []
  if int(active_issue_count or 0) > 0 and not issue_packets:
    errors.append(
      {
        "error": "issue_detection_unmapped_repair_path",
        "issue_code": None,
        "reason": (
          "Convergence has active non-cash issues but deterministic_numeric_guidance.issue_repair_packets is empty."
        ),
        "expected": "Each active issue must produce at least one table-backed repair packet before GPT is called.",
      }
    )
  for issue_packet in issue_packets:
    issue_code = str(issue_packet.get("issue_code") or "").strip().lower()
    repair_targets = [
      copy.deepcopy(item)
      for item in (issue_packet.get("repair_targets") or [])
      if isinstance(item, dict)
    ]
    issue_actionable_cell_ids: List[str] = []
    issue_mapped_lever_ids: List[str] = []
    issue_target_metrics: List[str] = []
    if not repair_targets:
      errors.append(
        {
          "error": "issue_detection_unmapped_repair_path",
          "issue_code": issue_code,
          "reason": "Issue packet has no repair_targets.",
          "expected": "Issue packet must map to direct table-backed target metrics and driver paths.",
        }
      )
    for repair_target in repair_targets:
      quarter_index = int(_safe_float(repair_target.get("quarter")) or 0)
      target_metric_name = str(repair_target.get("metric") or "").strip().lower()
      if quarter_index < 1 or quarter_index not in contract_horizon_quarters:
        errors.append(
          {
            "error": "issue_detection_quarter_out_of_contract_horizon",
            "issue_code": issue_code,
            "target_metric_name": target_metric_name,
            "quarter_index": quarter_index or None,
            "allowed_quarters": sorted(contract_horizon_quarters),
            "contract_table": "post_intake_gpt_contract_lookup",
            "reason": "Issue repair target references a quarter outside the table-backed forecast horizon. Stub Q0 is not a forecast quarter.",
            "expected": f"Issue detection must emit only Q1-Q{max_contract_quarter} repair targets.",
          }
        )
        continue
      if target_metric_name and target_metric_name not in issue_target_metrics:
        issue_target_metrics.append(target_metric_name)
      driver_paths = [
        copy.deepcopy(item)
        for item in (repair_target.get("driver_paths") or [])
        if isinstance(item, dict) and str(item.get("lever") or "").strip()
      ]
      mapped_driver_paths: List[Dict[str, Any]] = []
      for driver_path in driver_paths:
        lever_id = str(driver_path.get("lever") or "").strip()
        mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
        mapped_target_metric = str(mapping_entry.get("target_metric_name") or "").strip().lower()
        if not mapping_entry:
          errors.append(
            {
              "error": "issue_detection_unmapped_repair_path",
              "issue_code": issue_code,
              "lever_id": lever_id,
              "target_metric_name": target_metric_name,
              "quarter_index": quarter_index or None,
              "reason": "Driver path lever has no row in SQL post_intak_mapping_lookup.",
              "expected": "Every repair driver path must be a deterministic mapping-table lever.",
            }
          )
          continue
        if target_metric_name and mapped_target_metric != target_metric_name:
          errors.append(
            {
              "error": "issue_detection_mapping_target_mismatch",
              "issue_code": issue_code,
              "lever_id": lever_id,
              "target_metric_name": target_metric_name,
              "mapped_target_metric_name": mapped_target_metric,
              "quarter_index": quarter_index or None,
              "reason": "Driver path target metric does not match the lever's direct mapping-table target.",
              "expected": "Issue repair targets must use the exact target metric owned by the mapped lever.",
            }
          )
          continue
        mapped_driver_paths.append(copy.deepcopy(driver_path))
        if lever_id not in issue_mapped_lever_ids:
          issue_mapped_lever_ids.append(lever_id)
        if lever_id not in editable_lever_ids:
          errors.append(
            {
              "error": "issue_detection_no_editable_model_input_cells",
              "issue_code": issue_code,
              "lever_id": lever_id,
              "target_metric_name": target_metric_name,
              "quarter_index": quarter_index or None,
              "reason": "Mapped lever is not present in the full-horizon editable model-input cell grid.",
              "expected": "Every active issue must expose editable model_input_json cells for at least one mapped lever.",
            }
          )
          continue
        if quarter_index >= 1:
          editable_cell = editable_by_lever_quarter.get((lever_id, quarter_index))
          if not isinstance(editable_cell, dict) or not editable_cell:
            errors.append(
              {
                "error": "issue_detection_no_editable_model_input_cell_for_quarter",
                "issue_code": issue_code,
                "lever_id": lever_id,
                "target_metric_name": target_metric_name,
                "quarter_index": quarter_index,
                "reason": "Mapped lever has no editable model_input_json cell for the issue quarter.",
                "expected": "Issue quarter must connect to an editable full-horizon model-input cell.",
              }
            )
          else:
            cell_id = str(editable_cell.get("cell_id") or "").strip()
            if cell_id and cell_id not in issue_actionable_cell_ids:
              issue_actionable_cell_ids.append(cell_id)
      if not mapped_driver_paths:
        errors.append(
          {
            "error": "issue_detection_unmapped_repair_path",
            "issue_code": issue_code,
            "target_metric_name": target_metric_name,
            "quarter_index": quarter_index or None,
            "reason": "Repair target has no table-backed driver paths.",
            "expected": "Each repair target must map to at least one direct table-backed model-input lever.",
          }
        )
    if repair_targets and not issue_actionable_cell_ids:
      errors.append(
        {
          "error": "issue_detection_no_actionable_model_input_cells",
          "issue_code": issue_code,
          "target_metric_names": copy.deepcopy(issue_target_metrics),
          "mapped_lever_ids": copy.deepcopy(issue_mapped_lever_ids),
          "reason": "Issue has repair targets but none resolve to editable full-horizon model-input cells.",
          "expected": "Active convergence issues must be actionable through the mapping table and model_input_json cell grid.",
        }
      )
    issue_summaries.append(
      {
        "issue_code": issue_code,
        "target_metric_names": copy.deepcopy(issue_target_metrics),
        "mapped_lever_ids": copy.deepcopy(issue_mapped_lever_ids),
        "actionable_cell_count": len(issue_actionable_cell_ids),
        "sample_actionable_cell_ids": copy.deepcopy(issue_actionable_cell_ids[:12]),
      }
    )
  return {
    "contract_version": "convergence_issue_mapping_gate_v1",
    "status": "failed" if errors else "passed",
    "active_issue_count": int(active_issue_count or 0),
    "issue_packet_count": len(issue_packets),
    "editable_cell_count": len(editable_cells),
    "issue_summaries": issue_summaries,
    "errors": errors,
  }

def _compact_current_cycle_packet_for_prompt(
  current_cycle_packet: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  packet = current_cycle_packet if isinstance(current_cycle_packet, dict) else {}
  issue_state = packet.get("issue_state") if isinstance(packet.get("issue_state"), dict) else {}
  retry_state = packet.get("retry_state") if isinstance(packet.get("retry_state"), dict) else {}
  numeric_state = packet.get("numeric_state") if isinstance(packet.get("numeric_state"), dict) else {}
  return {
    "contract_version": str(packet.get("contract_version") or "").strip(),
    "owner": str(packet.get("owner") or "").strip(),
    "stage": str(packet.get("stage") or "").strip() or None,
    "status": str(packet.get("status") or "").strip() or None,
    "current_cycle": int(_safe_float(packet.get("current_cycle")) or 0) or None,
    "business_context": copy.deepcopy(packet.get("business_context") or {}),
    "issue_state": {
      "controller_status": str(issue_state.get("controller_status") or "").strip() or None,
      "detected_issue_count": int(_safe_float(issue_state.get("detected_issue_count")) or 0),
      "remaining_issue_count": int(_safe_float(issue_state.get("remaining_issue_count")) or 0),
      "resolved_issue_count": int(_safe_float(issue_state.get("resolved_issue_count")) or 0),
      "tolerated_issue_count": int(_safe_float(issue_state.get("tolerated_issue_count")) or 0),
      "open_issue_codes": copy.deepcopy(issue_state.get("open_issue_codes") or []),
      "failing_quarters": copy.deepcopy(issue_state.get("failing_quarters") or []),
    },
    "retry_state": {
      "progress_status": str(retry_state.get("progress_status") or "").strip() or None,
      "failed_quarters": copy.deepcopy(retry_state.get("failed_quarters") or []),
      "required_open_issue_codes": copy.deepcopy(retry_state.get("required_open_issue_codes") or []),
      "minimum_primary_metric_coverage_count": int(
        _safe_float(retry_state.get("minimum_primary_metric_coverage_count")) or 0
      ) or None,
    },
    "numeric_state": {
      "solver_invoked": bool(numeric_state.get("solver_invoked")),
      "solver_execution_state": str(numeric_state.get("solver_execution_state") or "").strip() or None,
      "execution_state": str(numeric_state.get("execution_state") or "").strip() or None,
      "target_metric_names": copy.deepcopy(numeric_state.get("target_metric_names") or []),
      "quarters_with_target_misses": int(_safe_float(numeric_state.get("quarters_with_target_misses")) or 0),
    },
    "convergence_scorecard": copy.deepcopy(packet.get("convergence_scorecard") or {}),
  }

def _lever_priority_tier(priority_score: Any) -> str:
  score = float(_safe_float(priority_score) or 0.0)
  if score >= 140:
    return "primary"
  if score >= 100:
    return "secondary"
  return "supporting"

def _ordered_quarters_by_preference(
  quarters: Optional[List[int]],
  preferred_quarters: Optional[List[int]],
) -> List[int]:
  normalized = [
    int(_safe_float(item) or 0)
    for item in (quarters or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  preferred = [
    int(_safe_float(item) or 0)
    for item in (preferred_quarters or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  ordered: List[int] = []
  for quarter_index in preferred:
    if quarter_index in normalized and quarter_index not in ordered:
      ordered.append(quarter_index)
  for quarter_index in normalized:
    if quarter_index not in ordered:
      ordered.append(quarter_index)
  return ordered

def _build_unified_numeric_guidance_packet(
  *,
  controller_resolution_state: Optional[Dict[str, Any]],
  controller_retry_context: Optional[Dict[str, Any]],
  unified_convergence_context: Optional[Dict[str, Any]],
  quarter_count: int = _CONVERGENCE_DEFAULT_QUARTER_COUNT,
) -> Dict[str, Any]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  retry_context = controller_retry_context if isinstance(controller_retry_context, dict) else {}
  convergence_context = unified_convergence_context if isinstance(unified_convergence_context, dict) else {}
  all_issue_packets = [
    item
    for item in (convergence_context.get("deterministic_issue_packets") or [])
    if isinstance(item, dict)
  ]
  remaining_issue_records = [
    copy.deepcopy(item)
    for item in (controller_state.get("remaining_issues") or [])
    if isinstance(item, dict)
    and str(item.get("issue_code") or "").strip()
    and not _is_cash_pass_owned_issue_code(item.get("issue_code"))
  ]
  issue_record_map = {
    str(item.get("issue_code") or "").strip().lower(): copy.deepcopy(item)
    for item in remaining_issue_records
    if str(item.get("issue_code") or "").strip()
  }
  focus_issue_codes = [
    str(item).strip().lower()
    for item in (
      retry_context.get("focus_issue_codes")
      or retry_context.get("required_open_issue_codes")
      or []
    )
    if str(item).strip()
  ]
  if not focus_issue_codes:
    focus_issue_codes = [
      str(item.get("issue_code") or "").strip().lower()
      for item in sorted(
        remaining_issue_records,
        key=lambda item: (
          int(_safe_float(item.get("priority_rank")) or 9999),
          -int(_safe_float(item.get("remaining_issue_severity_score")) or 0),
          str(item.get("issue_code") or "").strip().lower(),
        ),
      )[:_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT]
      if str(item.get("issue_code") or "").strip()
      and not _is_cash_pass_owned_issue_code(item.get("issue_code"))
    ]
  focus_issue_codes = list(dict.fromkeys(focus_issue_codes))[:_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT]
  focus_issue_code_set = set(focus_issue_codes)
  focus_requires_remaining_horizon_scope = any(
    _issue_requires_remaining_horizon_scope(issue_code)
    for issue_code in focus_issue_codes
  )
  issue_packets = [
    item for item in all_issue_packets
    if str(item.get("issue_code") or "").strip().lower() in focus_issue_code_set
  ]
  issue_priority_map = _issue_priority_map(issue_packets or all_issue_packets)
  finmo_json = (
    convergence_context.get("current_finmo_json")
    if isinstance(convergence_context.get("current_finmo_json"), dict)
    else {}
  )
  finmo_rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or [])
    if isinstance(row, dict)
  ]
  finmo_row_map = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in finmo_rows
    if int(_safe_float(row.get("quarter_index")) or 0) >= 1
  }
  model_input_json = (
    convergence_context.get("current_model_input_json")
    if isinstance(convergence_context.get("current_model_input_json"), dict)
    else {}
  )
  numeric_solver_contract = (
    convergence_context.get("numeric_solver_contract")
    if isinstance(convergence_context.get("numeric_solver_contract"), dict)
    else {}
  )
  allowed_primary_target_metric_names = [
    str(metric_name).strip().lower()
    for metric_name in (
      numeric_solver_contract.get("allowed_target_metric_ids")
      or numeric_solver_contract.get("recommended_primary_target_metric_keys")
      or []
    )
    if str(metric_name).strip()
  ]
  lever_catalog_entries = _build_writable_lever_review_catalog(model_input_json)
  mapping_errors = post_intake_driver_target_mapping_errors(
    str(item.get("lever_id") or "").strip()
    for item in lever_catalog_entries
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  )
  if mapping_errors:
    raise RuntimeError(
      "post_intake_driver_target_mapping_invalid: " + "; ".join(mapping_errors)
    )
  lever_catalog_map = {
    str(item.get("lever_id") or "").strip(): copy.deepcopy(item)
    for item in lever_catalog_entries
    if str(item.get("lever_id") or "").strip()
  }
  lever_value_map = _solved_lever_value_map(model_input_json)
  issue_scope_quarters: List[int] = []
  issue_packet_scope_map = {
    str(item.get("issue_code") or "").strip().lower(): copy.deepcopy(item)
    for item in issue_packets
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  }
  actionable_scope_quarters_by_issue: Dict[str, List[int]] = {}
  for issue_code in focus_issue_codes:
    issue_packet = issue_packet_scope_map.get(issue_code) or {}
    live_issue_record = issue_record_map.get(issue_code) or {}
    target_metrics = {
      str(item).strip().lower()
      for item in (issue_packet.get("metric_targets") or [])
      if str(item).strip()
    }
    metric_specs = [
      copy.deepcopy(spec)
      for spec in (live_issue_record.get("metric_debug") or [])
      if isinstance(spec, dict)
    ]
    if not metric_specs and live_issue_record:
      metric_specs = _issue_metric_specs_for_record(
        live_issue_record,
        current_finmo_json=copy.deepcopy(finmo_json),
        quarter_count=max(1, int(quarter_count or _CONVERGENCE_DEFAULT_QUARTER_COUNT)),
      )
    actionable_quarters: List[int] = []
    for spec in metric_specs:
      spec_metric_name = str(spec.get("metric_name") or "").strip().lower()
      if target_metrics and spec_metric_name not in target_metrics:
        continue
      has_boundary = _safe_float(spec.get("target_floor")) is not None or _safe_float(spec.get("target_ceiling")) is not None
      gap_abs = abs(float(_safe_float(spec.get("gap_abs")) or 0.0))
      if not has_boundary or (bool(spec.get("within_boundary")) and gap_abs <= 1e-9):
        continue
      quarter_index = int(_safe_float(spec.get("quarter_index")) or 0)
      if 1 <= quarter_index <= max(1, int(quarter_count or 1)) and quarter_index not in actionable_quarters:
        actionable_quarters.append(quarter_index)
    if not actionable_quarters:
      for quarter in (
        live_issue_record.get("remaining_problem_quarters")
        or live_issue_record.get("relevant_quarters")
        or live_issue_record.get("affected_quarters")
        or issue_packet.get("remaining_problem_quarters")
        or issue_packet.get("relevant_quarters")
        or issue_packet.get("affected_quarters")
        or []
      ):
        quarter_index = int(_safe_float(quarter) or 0)
        if 1 <= quarter_index <= max(1, int(quarter_count or 1)) and quarter_index not in actionable_quarters:
          actionable_quarters.append(quarter_index)
    if _issue_requires_remaining_horizon_scope(issue_code):
      # Remaining-horizon issues must expose every affected live quarter. The
      # SQL contract table owns the final Q1-Q20 response shape.
      remaining_horizon_quarters: List[int] = []
      for quarter in (
        live_issue_record.get("remaining_problem_quarters")
        or live_issue_record.get("relevant_quarters")
        or live_issue_record.get("affected_quarters")
        or issue_packet.get("remaining_problem_quarters")
        or issue_packet.get("relevant_quarters")
        or issue_packet.get("affected_quarters")
        or []
      ):
        quarter_index = int(_safe_float(quarter) or 0)
        if 1 <= quarter_index <= max(1, int(quarter_count or 1)) and quarter_index not in remaining_horizon_quarters:
          remaining_horizon_quarters.append(quarter_index)
      for repair_target in (issue_packet.get("repair_targets") or []):
        if not isinstance(repair_target, dict):
          continue
        quarter_index = int(_safe_float(repair_target.get("quarter")) or 0)
        if 1 <= quarter_index <= max(1, int(quarter_count or 1)) and quarter_index not in remaining_horizon_quarters:
          remaining_horizon_quarters.append(quarter_index)
      for quarter_index in sorted(remaining_horizon_quarters):
        if quarter_index not in actionable_quarters:
          actionable_quarters.append(quarter_index)
    actionable_scope_quarters_by_issue[issue_code] = sorted(actionable_quarters)
  preferred_scope_quarters = _retry_scope_quarters(
    controller_retry_context=retry_context,
    quarter_count=quarter_count,
  )
  for issue_code in focus_issue_codes:
    issue_quarters = _ordered_quarters_by_preference(
      actionable_scope_quarters_by_issue.get(issue_code) or [],
      preferred_scope_quarters,
    )
    if issue_quarters and issue_quarters[0] not in issue_scope_quarters:
      issue_scope_quarters.append(issue_quarters[0])
    if len(issue_scope_quarters) >= _UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT:
      break
  for issue_code in focus_issue_codes:
    for quarter_index in _ordered_quarters_by_preference(
      actionable_scope_quarters_by_issue.get(issue_code) or [],
      preferred_scope_quarters,
    ):
      quarter_index = int(_safe_float(quarter_index) or 0)
      if (
        1 <= quarter_index <= max(1, int(quarter_count or 1))
        and quarter_index not in issue_scope_quarters
      ):
        issue_scope_quarters.append(quarter_index)
      if len(issue_scope_quarters) >= _UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT:
        break
    if len(issue_scope_quarters) >= _UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT:
      break
  if issue_scope_quarters:
    scoped_quarters = sorted(
      {
        int(_safe_float(item) or 0)
        for item in issue_scope_quarters
        if int(_safe_float(item) or 0) >= 1
      }
    )
  else:
    scoped_quarters = _retry_scope_quarters(
      controller_retry_context=retry_context,
      quarter_count=quarter_count,
    )
  if not scoped_quarters:
    scoped_quarters = list(range(1, max(1, int(quarter_count or _CONVERGENCE_DEFAULT_QUARTER_COUNT)) + 1))
  scoped_quarters = list(range(1, max(1, int(quarter_count or _CONVERGENCE_DEFAULT_QUARTER_COUNT)) + 1))
  scoped_quarter_set = set(scoped_quarters)

  metric_pressure_packets: List[Dict[str, Any]] = []
  issue_repair_packet_map: Dict[str, Dict[str, Any]] = {}
  candidate_lever_ids: List[str] = []
  per_lever_severity: Dict[str, int] = {}
  per_lever_issue_codes: Dict[str, List[str]] = {}
  per_lever_metric_names: Dict[str, List[str]] = {}
  per_lever_source_metrics: Dict[str, List[str]] = {}
  issue_direct_metric_spec_map: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
  business_world_contract = (
    convergence_context.get("business_world_contract")
    if isinstance(convergence_context.get("business_world_contract"), dict)
    else {}
  )
  stage_ramp_contract_for_targets = (
    business_world_contract.get("stage_ramp_contract")
    if isinstance(business_world_contract.get("stage_ramp_contract"), dict)
    else {}
  )
  stage_ramp_revenue_target_state_by_quarter: Dict[int, float] = {
    int(quarter_index): max(0.0, float(_safe_float(row.get("revenue")) or 0.0))
    for quarter_index, row in finmo_row_map.items()
    if int(quarter_index) >= 1
  }
  stage_ramp_target_state: Dict[str, Any] = {"spike_count_used": 0}
  retry_required_lever_ids = {
    str(item).strip()
    for item in (retry_context.get("required_issue_lever_ids") or [])
    if str(item).strip()
  }
  issue_packet_map = {
    str(item.get("issue_code") or "").strip().lower(): copy.deepcopy(item)
    for item in issue_packets
    if str(item.get("issue_code") or "").strip()
  }
  focus_records = [
    issue_record_map.get(issue_code) or {}
    for issue_code in focus_issue_codes
    if issue_record_map.get(issue_code)
  ]
  for issue_record in focus_records:
    issue_code = str(issue_record.get("issue_code") or "").strip().lower()
    if not issue_code or _is_cash_pass_owned_issue_code(issue_code):
      continue
    issue_packet = issue_packet_map.get(issue_code) or {}
    severity_score = int(
      _safe_float(issue_record.get("remaining_issue_severity_score"))
      or _safe_float(issue_packet.get("remaining_issue_severity_score"))
      or 0
    )
    severity_label = _issue_severity_label_from_score(severity_score)
    issue_priority = int(issue_priority_map.get(issue_code) or 0)
    metric_specs = copy.deepcopy(issue_record.get("metric_debug") or [])
    if not metric_specs:
      metric_specs = _issue_metric_specs_for_record(
        issue_record,
        current_finmo_json=copy.deepcopy(finmo_json),
        quarter_count=max(1, int(quarter_count or _CONVERGENCE_DEFAULT_QUARTER_COUNT)),
      )
    metric_specs = [
      copy.deepcopy(spec)
      for spec in metric_specs
      if isinstance(spec, dict)
      and str(spec.get("metric_name") or "").strip()
    ]
    scoped_metric_specs = [
      copy.deepcopy(spec)
      for spec in metric_specs
      if (
        not scoped_quarter_set
        or int(_safe_float(spec.get("quarter_index")) or 0) in scoped_quarter_set
      )
    ]
    if scoped_quarter_set and not scoped_metric_specs:
      continue
    metric_specs = scoped_metric_specs or metric_specs
    metric_specs.sort(
      key=lambda spec: (
        int(_safe_float(spec.get("quarter_index")) or 0),
        bool(spec.get("within_boundary")),
        -float(_safe_float(spec.get("gap_abs")) or 0.0),
        str(spec.get("metric_name") or "").strip(),
      )
    )
    affected_quarters = list(
      dict.fromkeys(
        [
          int(_safe_float(spec.get("quarter_index")) or 0)
          for spec in metric_specs
          if int(_safe_float(spec.get("quarter_index")) or 0) >= 1
        ]
      )
    )
    if not _issue_requires_remaining_horizon_scope(issue_code):
      affected_quarters = affected_quarters[:_CONVERGENCE_MAX_FOCUS_QUARTERS]
    effective_quarters = [quarter for quarter in affected_quarters if quarter in scoped_quarter_set] or affected_quarters or scoped_quarters
    metric_summary_map: Dict[str, Dict[str, Any]] = {}
    for spec in metric_specs:
      metric_name = str(spec.get("metric_name") or "").strip().lower()
      if not metric_name:
        continue
      summary = metric_summary_map.setdefault(
        metric_name,
        {
          "metric_name": metric_name,
          "gap_abs": 0.0,
          "score_values": [],
        },
      )
      summary["gap_abs"] = float(summary.get("gap_abs") or 0.0) + abs(float(_safe_float(spec.get("gap")) or 0.0))
      summary.setdefault("score_values", []).append(float(_safe_float(spec.get("score_pct")) or 0.0))
    ordered_metric_summaries = []
    for summary in metric_summary_map.values():
      score_values = [
        float(_safe_float(item) or 0.0)
        for item in (summary.get("score_values") or [])
      ]
      ordered_metric_summaries.append(
        {
          "metric_name": str(summary.get("metric_name") or "").strip().lower(),
          "gap_abs": float(_safe_float(summary.get("gap_abs")) or 0.0),
          "average_score_pct": (
            float(sum(score_values) / max(len(score_values), 1))
            if score_values
            else 100.0
          ),
        }
      )
    selected_metric_summary = (
      sorted(
        ordered_metric_summaries,
        key=lambda item: (
          float(_safe_float(item.get("average_score_pct")) or 0.0),
          -float(_safe_float(item.get("gap_abs")) or 0.0),
          str(item.get("metric_name") or "").strip(),
        ),
      )[0]
      if ordered_metric_summaries
      else {}
    )
    candidate_lever_pool: List[str] = []
    table_allowed_concrete_lever_ids = post_intake_concrete_issue_lever_ids_from_catalog(
      issue_code,
      [
        str(item.get("lever_id") or "").strip()
        for item in lever_catalog_entries
        if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
      ],
      phase="convergence",
    )
    for lever_id in table_allowed_concrete_lever_ids:
      if (
        lever_id
        and post_intake_driver_target_lever_allowed_for_issue(
          lever_id,
          issue_code,
          phase="convergence",
        )
        and lever_id not in candidate_lever_pool
      ):
        candidate_lever_pool.append(lever_id)
    actionable_metric_names_from_specs = [
      str(spec.get("metric_name") or "").strip().lower()
      for spec in metric_specs
      if isinstance(spec, dict)
      and str(spec.get("metric_name") or "").strip()
      and (
        not bool(spec.get("within_boundary"))
        or abs(float(_safe_float(spec.get("gap_abs")) or 0.0)) > 1e-9
      )
    ]
    candidate_lever_pool = [
      lever_id
      for lever_id in candidate_lever_pool
      if (
        not actionable_metric_names_from_specs
        or str(post_intake_direct_target_metric_for_lever(lever_id) or "").strip().lower()
        in set(actionable_metric_names_from_specs)
      )
    ]
    if not candidate_lever_pool:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_levers: "
        f"{issue_code} has no table-backed candidate levers in the numeric solver contract."
      )
    candidate_target_metric_names = post_intake_direct_target_metric_names_for_levers(
      candidate_lever_pool
    )
    candidate_target_metric_name_set = set(candidate_target_metric_names)
    issue_packet_metric_targets = [
      str(item).strip().lower()
      for item in [
        *_issue_packet_declared_target_metric_names(issue_packet),
        *candidate_target_metric_names,
      ]
      if str(item).strip()
      and (
        str(item).strip().lower() in candidate_target_metric_name_set
        or
        not allowed_primary_target_metric_names
        or str(item).strip().lower() in set(allowed_primary_target_metric_names)
      )
    ]
    if not issue_packet_metric_targets:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_targets: "
        f"{issue_code} has no table-backed target metrics from mapped candidate levers."
      )
    actionable_issue_metric_targets: List[str] = []
    for spec in metric_specs:
      spec_metric_name = str(spec.get("metric_name") or "").strip().lower()
      if spec_metric_name not in set(issue_packet_metric_targets):
        continue
      gap_abs = abs(float(_safe_float(spec.get("gap_abs")) or 0.0))
      within_boundary = bool(spec.get("within_boundary"))
      has_boundary = _safe_float(spec.get("target_floor")) is not None or _safe_float(spec.get("target_ceiling")) is not None
      if (gap_abs > 1e-9 or not within_boundary) and has_boundary and spec_metric_name not in actionable_issue_metric_targets:
        actionable_issue_metric_targets.append(spec_metric_name)
    if not actionable_issue_metric_targets:
      raise RuntimeError(
        "post_intake_issue_has_no_actionable_table_target: "
        f"{issue_code} is active but has no out-of-bound table-backed target metric."
      )
    actionable_metric_set = set(actionable_issue_metric_targets)
    narrowed_candidate_lever_pool = [
      lever_id
      for lever_id in candidate_lever_pool
      if str(post_intake_direct_target_metric_for_lever(lever_id) or "").strip().lower()
      in actionable_metric_set
    ]
    if narrowed_candidate_lever_pool:
      candidate_lever_pool = list(dict.fromkeys(narrowed_candidate_lever_pool))
    metric_targets = copy.deepcopy(actionable_issue_metric_targets)
    selected_metric_name = metric_targets[0]
    selected_metric_summary = {
      "metric_name": selected_metric_name,
      "mapping_source": "post_intak_mapping_lookup",
    }
    root_cause = str(
      issue_packet.get("root_cause")
      or issue_record.get("detail")
      or issue_packet.get("detail")
      or ""
    ).strip()
    if not root_cause and metric_specs:
      root_cause = str(metric_specs[0].get("metric_definition") or "").strip()
    issue_repair_packet_map[issue_code] = {
      "issue_code": issue_code,
      "priority": issue_priority or None,
      "priority_rank": issue_priority or None,
      "severity": severity_label,
      "severity_score": severity_score,
      "impact_weight": _issue_impact_weight(severity_score),
      "affected_quarters": copy.deepcopy(effective_quarters),
      "summary": str(
        issue_packet.get("summary")
        or issue_packet.get("issue_summary")
        or issue_record.get("issue")
        or issue_packet.get("issue")
        or _canonical_issue_title(issue_code, issue_code)
      ).strip(),
      "root_cause": root_cause,
      "closure_threshold_pct": _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
      "quarter_floor_pct": _CONVERGENCE_ISSUE_WARN_SCORE_PCT,
      "candidate_lever_ids": copy.deepcopy(candidate_lever_pool),
      "selected_metric_name": selected_metric_name,
      "selected_metric_summary": copy.deepcopy(selected_metric_summary),
      "metric_targets": [],
      "repair_targets": [],
    }
    for lever_id in candidate_lever_pool:
      if lever_id not in candidate_lever_ids:
        candidate_lever_ids.append(lever_id)
      per_lever_severity[lever_id] = max(per_lever_severity.get(lever_id, 0), severity_score)
      if issue_code and issue_code not in (per_lever_issue_codes.get(lever_id) or []):
        per_lever_issue_codes.setdefault(lever_id, []).append(issue_code)
      for metric_name in metric_targets:
        if metric_name and metric_name not in (per_lever_metric_names.get(lever_id) or []):
          per_lever_metric_names.setdefault(lever_id, []).append(metric_name)
      for source_metric_name in [
        str(item).strip().lower()
        for spec in metric_specs
        for item in (spec.get("source_metric_names") or [])
        if str(item).strip()
      ]:
        if source_metric_name not in (per_lever_source_metrics.get(lever_id) or []):
          per_lever_source_metrics.setdefault(lever_id, []).append(source_metric_name)
    issue_metric_targets = copy.deepcopy(actionable_issue_metric_targets)
    issue_repair_packet_map[issue_code]["metric_targets"] = copy.deepcopy(
      issue_metric_targets
    )
    for spec in metric_specs:
      spec = _stage_ramp_constrain_revenue_metric_spec(
        spec=copy.deepcopy(spec),
        stage_ramp_contract=stage_ramp_contract_for_targets,
        revenue_target_state_by_quarter=stage_ramp_revenue_target_state_by_quarter,
        stage_ramp_state=stage_ramp_target_state,
      )
      quarter_index = int(_safe_float(spec.get("quarter_index")) or 0)
      if quarter_index < 1 or quarter_index not in effective_quarters:
        continue
      spec_metric_name = str(spec.get("metric_name") or "").strip().lower()
      if spec_metric_name in set(issue_metric_targets):
        spec_key = (issue_code, quarter_index, spec_metric_name)
        existing_spec = issue_direct_metric_spec_map.get(spec_key)
        if isinstance(existing_spec, dict):
          existing_actionable = (
            not bool(existing_spec.get("within_boundary"))
            or abs(float(_safe_float(existing_spec.get("gap_abs")) or 0.0)) > 1e-9
          )
          current_actionable = (
            not bool(spec.get("within_boundary"))
            or abs(float(_safe_float(spec.get("gap_abs")) or 0.0)) > 1e-9
          )
          existing_gap_abs = abs(float(_safe_float(existing_spec.get("gap_abs")) or 0.0))
          current_gap_abs = abs(float(_safe_float(spec.get("gap_abs")) or 0.0))
          if current_actionable and (not existing_actionable or current_gap_abs > existing_gap_abs):
            issue_direct_metric_spec_map[spec_key] = copy.deepcopy(spec)
        else:
          issue_direct_metric_spec_map[spec_key] = copy.deepcopy(spec)
      direction_hint = str(spec.get("direction_hint") or "").strip().lower() or "hold"
      repair_envelope = copy.deepcopy(spec.get("repair_envelope") or {})
      minimum_absolute_change = abs(float(_safe_float(repair_envelope.get("min_required_delta")) or 0.0))
      unit_kind = str(spec.get("unit_kind") or "").strip().lower() or "ratio"
      ratio_like_metric = unit_kind in {"ratio", "percent", "percent_of_revenue", "margin"}
      actual_value = _safe_float(spec.get("actual_value"))
      boundary_value = _safe_float(spec.get("boundary_value"))
      target_floor = _safe_float(spec.get("target_floor"))
      target_ceiling = _safe_float(spec.get("target_ceiling"))
      gap_value = _safe_float(spec.get("gap"))
      gap_abs_value = _safe_float(spec.get("gap_abs"))
      metric_pressure_packets.append(
        {
          "issue_code": issue_code,
          "issue_summary": str(issue_repair_packet_map[issue_code].get("summary") or "").strip(),
          "root_cause": str(issue_repair_packet_map[issue_code].get("root_cause") or "").strip(),
          "priority_rank": issue_priority or None,
          "impact_weight": _issue_impact_weight(severity_score),
          "quarter_index": quarter_index,
          "metric_name": str(spec.get("metric_name") or "").strip().lower(),
          "metric_definition": str(spec.get("metric_definition") or "").strip(),
          "source_metric_names": copy.deepcopy(spec.get("source_metric_names") or []),
          "unit_kind": unit_kind,
          "severity_score": severity_score,
          "severity": severity_label,
          "current_value": (
            round(float(actual_value), 2)
            if ratio_like_metric and actual_value is not None
            else int(round(float(actual_value)))
            if actual_value is not None
            else None
          ),
          "direction_hint": direction_hint,
          "minimum_change_pct": None,
          "minimum_absolute_change": minimum_absolute_change,
          "equilibrium_target": (
            round(float(boundary_value), 2)
            if ratio_like_metric and boundary_value is not None
            else int(round(float(boundary_value)))
            if boundary_value is not None
            else None
          ),
          "suggested_floor_target": (
            round(float(target_floor), 2)
            if ratio_like_metric and target_floor is not None
            else int(round(float(target_floor)))
            if target_floor is not None
            else None
          ),
          "suggested_ceiling_target": (
            round(float(target_ceiling), 2)
            if ratio_like_metric and target_ceiling is not None
            else int(round(float(target_ceiling)))
            if target_ceiling is not None
            else None
          ),
          "minimum_target_value": (
            round(float(target_floor), 2)
            if ratio_like_metric and target_floor is not None
            else int(round(float(target_floor)))
            if target_floor is not None
            else None
          ),
          "maximum_target_value": (
            round(float(target_ceiling), 2)
            if ratio_like_metric and target_ceiling is not None
            else int(round(float(target_ceiling)))
            if target_ceiling is not None
            else None
          ),
          "target_floor": (
            round(float(target_floor), 2)
            if ratio_like_metric and target_floor is not None
            else int(round(float(target_floor)))
            if target_floor is not None
            else None
          ),
          "target_ceiling": (
            round(float(target_ceiling), 2)
            if ratio_like_metric and target_ceiling is not None
            else int(round(float(target_ceiling)))
            if target_ceiling is not None
            else None
          ),
          "acceptable_zone": copy.deepcopy(spec.get("acceptable_zone") or {}),
          "gap": (
            round(float(gap_value), 2)
            if ratio_like_metric and gap_value is not None
            else int(round(float(gap_value)))
            if gap_value is not None
            else None
          ),
          "gap_abs": (
            round(float(gap_abs_value), 2)
            if ratio_like_metric and gap_abs_value is not None
            else int(round(float(gap_abs_value)))
            if gap_abs_value is not None
            else None
          ),
          "repair_envelope": repair_envelope,
          "candidate_lever_ids": copy.deepcopy(candidate_lever_pool),
          "closure_threshold_pct": _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
          "quarter_floor_pct": _CONVERGENCE_ISSUE_WARN_SCORE_PCT,
        }
      )

  if not candidate_lever_ids and focus_issue_codes:
    raise RuntimeError(
      "post_intake_driver_target_mapping_missing_active_issue_levers: "
      + ", ".join(focus_issue_codes)
      + " have no table-backed convergence levers. Add mappings to post_intak_mapping_lookup or disable the issue."
    )

  ranked_lever_entries: List[Dict[str, Any]] = []
  for lever_id in candidate_lever_ids:
    values = lever_value_map.get(lever_id) or []
    if not values:
      continue
    catalog_entry = lever_catalog_map.get(lever_id) or {}
    family = _lever_family_from_lever_id(lever_id)
    severity_score = max(per_lever_severity.get(lever_id, 0), 60 if lever_id in retry_required_lever_ids else 0)
    max_relative_change = _severity_minimum_change_pct(severity_score)
    start_q = min(scoped_quarters) if scoped_quarters else 1
    end_q = max(scoped_quarters) if scoped_quarters else max(1, quarter_count)
    baseline_window = _baseline_window_summary(values, start_q=start_q, end_q=end_q)
    baseline_value = float(_safe_float(baseline_window.get("value_end")) or 0.0)
    value_kind = str(catalog_entry.get("value_kind") or "").strip().lower()
    input_semantics = str(catalog_entry.get("input_semantics") or "").strip().lower()
    ratio_like_value = value_kind == "ratio" or "percent_of_" in input_semantics
    move_limit = _relative_move_limit(
      baseline_value=baseline_value,
      max_relative_change=max_relative_change,
      value_kind=str(catalog_entry.get("value_kind") or "").strip(),
      input_semantics=str(catalog_entry.get("input_semantics") or "").strip(),
    )
    guidance = _lever_usage_guidance(lever_id)
    mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
    issue_codes = copy.deepcopy(per_lever_issue_codes.get(lever_id) or [])
    metric_names = copy.deepcopy(per_lever_metric_names.get(lever_id) or [])
    source_metric_names = copy.deepcopy(per_lever_source_metrics.get(lever_id) or [])
    issue_coverage_count = len(issue_codes)
    direction_vote_counts: Dict[str, int] = {}
    for pressure_packet in metric_pressure_packets:
      if str(pressure_packet.get("issue_code") or "").strip().lower() not in set(issue_codes or []):
        continue
      vote = str(pressure_packet.get("direction_hint") or "").strip().lower() or "hold"
      if metric_names and str(pressure_packet.get("metric_name") or "").strip().lower() not in set(metric_names):
        continue
      direction_vote_counts[vote] = int(direction_vote_counts.get(vote) or 0) + 1
    non_either_direction_votes = {
      key: value
      for key, value in direction_vote_counts.items()
      if key in {"increase", "decrease", "hold"} and int(value or 0) > 0
    }
    if len(non_either_direction_votes) == 1:
      preferred_direction_hint = next(iter(non_either_direction_votes.keys()))
    elif len(non_either_direction_votes) > 1:
      preferred_direction_hint = "mixed"
    else:
      preferred_direction_hint = "either"
    priority_score = float(severity_score)
    lever_lower = str(lever_id or "").strip().lower()
    role = str(
      catalog_entry.get("accounting_role")
      or guidance.get("accounting_role")
      or ""
    ).strip()
    alignment_bonus = 0.0
    for metric_name in metric_names:
      path_type, efficiency = _repair_path_type_for_lever(
        metric_name=metric_name,
        lever_id=lever_id,
        accounting_role=role,
        source_metric_names=source_metric_names,
      )
      if path_type != "direct":
        continue
      if efficiency == "high":
        alignment_bonus = max(alignment_bonus, 28.0)
      elif efficiency == "medium":
        alignment_bonus = max(alignment_bonus, 18.0)
      else:
        alignment_bonus = max(alignment_bonus, 10.0)
    if lever_id in retry_required_lever_ids:
      priority_score += 30.0
    priority_score += float(issue_coverage_count * 10)
    priority_score += alignment_bonus
    ranked_lever_entries.append(
      {
        "lever_id": lever_id,
        "lever_family": family,
        "section": str(catalog_entry.get("section") or "").strip(),
        "label_path": str(catalog_entry.get("label_path") or "").strip(),
        "driver": str(catalog_entry.get("driver") or "").strip(),
        "target_driver": str(mapping_entry.get("target_driver") or "").strip(),
        "direct_target_metric_name": str(mapping_entry.get("target_metric_name") or "").strip(),
        "value_kind": str(catalog_entry.get("value_kind") or "").strip(),
        "input_semantics": str(catalog_entry.get("input_semantics") or "").strip(),
        "timing_start_q": start_q,
        "timing_end_q": end_q,
        "baseline_window": copy.deepcopy(baseline_window),
        "value_mode_hint": "band",
        "direction_hint": preferred_direction_hint,
        "direction_vote_counts": copy.deepcopy(direction_vote_counts),
        "max_relative_change": float(max_relative_change),
        "baseline_value": (
          round(float(baseline_value), 2)
          if ratio_like_value
          else int(round(float(baseline_value)))
        ),
        "suggested_min_value": _deterministic_lever_bound_value(
          lever_id=lever_id,
          raw_value=float(baseline_value - move_limit),
          ratio_like_value=ratio_like_value,
          bound_side="min",
        ),
        "suggested_max_value": _deterministic_lever_bound_value(
          lever_id=lever_id,
          raw_value=float(baseline_value + move_limit),
          ratio_like_value=ratio_like_value,
          bound_side="max",
        ),
        "accounting_role": str(guidance.get("accounting_role") or "").strip(),
        "preferred_uses": copy.deepcopy(guidance.get("preferred_uses") or []),
        "forbidden_uses": copy.deepcopy(guidance.get("forbidden_uses") or []),
        "covered_issue_codes": issue_codes,
        "covered_metric_names": metric_names,
        "covered_source_metric_names": source_metric_names,
        "issue_coverage_count": issue_coverage_count,
        "priority_score": priority_score,
        "priority_tier": _lever_priority_tier(priority_score),
        "direct_retry_requirement": bool(lever_id in retry_required_lever_ids),
      }
    )

  ranked_lever_entries.sort(
    key=lambda item: (
      -float(_safe_float(item.get("priority_score")) or 0.0),
      str(item.get("lever_id") or "").strip(),
    )
  )
  selected_families: List[str] = []
  lever_band_scaffold: List[Dict[str, Any]] = []
  rank_index = 0
  def _append_ranked_item(item: Dict[str, Any], *, enforce_family_limit: bool) -> bool:
    nonlocal rank_index
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      return False
    if any(str(existing.get("lever_id") or "").strip() == lever_id for existing in lever_band_scaffold):
      return False
    family = str(item.get("lever_family") or "").strip().lower() or (
      f"__ungrouped__::{str(item.get('lever_id') or '').strip().lower()}"
    )
    if enforce_family_limit and family not in selected_families and len(selected_families) >= _CONVERGENCE_MAX_FOCUS_LEVER_FAMILIES:
      return False
    if family not in selected_families:
      selected_families.append(family)
    rank_index += 1
    ranked_item = copy.deepcopy(item)
    ranked_item["priority_rank"] = rank_index
    lever_band_scaffold.append(ranked_item)
    return True

  for issue_code in focus_issue_codes:
    issue_packet = issue_repair_packet_map.get(issue_code) or {}
    selected_metric_name = str(issue_packet.get("selected_metric_name") or "").strip().lower()
    issue_direct_items: List[Dict[str, Any]] = []
    issue_table_items: List[Dict[str, Any]] = []
    for item in ranked_lever_entries:
      covered_issue_codes = {
        str(code or "").strip().lower()
        for code in (item.get("covered_issue_codes") or [])
        if str(code or "").strip()
      }
      if issue_code not in covered_issue_codes:
        continue
      issue_table_items.append(item)
      if selected_metric_name:
        path_type, _efficiency = _repair_path_type_for_lever(
          metric_name=selected_metric_name,
          lever_id=item.get("lever_id"),
          accounting_role=item.get("accounting_role"),
          source_metric_names=item.get("covered_source_metric_names") or [],
        )
        if str(path_type or "").strip().lower() == "direct":
          issue_direct_items.append(item)
    for item in (issue_direct_items or issue_table_items):
      if _append_ranked_item(item, enforce_family_limit=False):
        break
      if len(lever_band_scaffold) >= _CONVERGENCE_MAX_FOCUS_LEVERS:
        break
    if len(lever_band_scaffold) >= _CONVERGENCE_MAX_FOCUS_LEVERS:
      break
  for item in ranked_lever_entries:
    _append_ranked_item(item, enforce_family_limit=True)
    if len(lever_band_scaffold) >= _CONVERGENCE_MAX_FOCUS_LEVERS:
      break

  lever_scaffold_map = {
    str(item.get("lever_id") or "").strip(): copy.deepcopy(item)
    for item in lever_band_scaffold
    if str(item.get("lever_id") or "").strip()
  }
  enriched_metric_pressure_packets: List[Dict[str, Any]] = []
  translation_failures: List[Dict[str, Any]] = []
  metric_pressure_packets = []
  for issue_code, issue_repair_packet in issue_repair_packet_map.items():
    if not isinstance(issue_repair_packet, dict):
      continue
    target_metric_names = [
      str(item).strip().lower()
      for item in (issue_repair_packet.get("metric_targets") or [])
      if str(item).strip()
    ]
    issue_candidate_lever_ids = [
      str(item).strip()
      for item in (issue_repair_packet.get("candidate_lever_ids") or [])
      if str(item).strip()
    ]
    for quarter_index in [
      int(_safe_float(item) or 0)
      for item in (issue_repair_packet.get("affected_quarters") or scoped_quarters)
      if int(_safe_float(item) or 0) >= 1
    ]:
      for target_metric_name in target_metric_names:
        direct_metric_spec = copy.deepcopy(
          issue_direct_metric_spec_map.get((issue_code, quarter_index, target_metric_name)) or {}
        )
        direct_actual_value = _safe_float(direct_metric_spec.get("actual_value"))
        direct_target_floor = _safe_float(direct_metric_spec.get("target_floor"))
        direct_target_ceiling = _safe_float(direct_metric_spec.get("target_ceiling"))
        direct_boundary_value = _safe_float(direct_metric_spec.get("boundary_value"))
        direct_gap_value = _safe_float(direct_metric_spec.get("gap"))
        direct_gap_abs_value = _safe_float(direct_metric_spec.get("gap_abs"))
        direct_repair_envelope = copy.deepcopy(direct_metric_spec.get("repair_envelope") or {})
        direct_direction_hint = str(direct_metric_spec.get("direction_hint") or "").strip().lower()
        actual_metric_value = (
          direct_actual_value
          if direct_actual_value is not None
          else _safe_float((finmo_row_map.get(quarter_index) or {}).get(target_metric_name))
        )
        driver_paths: List[Dict[str, Any]] = []
        for lever_id in issue_candidate_lever_ids:
          if post_intake_direct_target_metric_for_lever(lever_id) != target_metric_name:
            continue
          lever_entry = copy.deepcopy(lever_scaffold_map.get(lever_id) or {})
          conversion_context = _driver_target_conversion_context(
            lever_id=lever_id,
            lever_entry=lever_entry,
            target_metric_name=target_metric_name,
            quarter_row=finmo_row_map.get(quarter_index) or {},
            actual_metric_value=actual_metric_value,
            target_floor=direct_target_floor,
            target_ceiling=direct_target_ceiling,
          )
          mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
          driver_paths.append(
            {
              "lever": lever_id,
              "lever_family": str((lever_entry or {}).get("lever_family") or _lever_family_from_lever_id(lever_id) or "").strip(),
              "path_type": "direct",
              "efficiency": "high",
              "priority_rank": int(_safe_float((lever_entry or {}).get("priority_rank")) or 0) or None,
              "priority_tier": str((lever_entry or {}).get("priority_tier") or "").strip() or None,
              "translation_basis": "post_intak_mapping_lookup",
              "translation_confidence": "deterministic",
              "baseline_value": (lever_entry or {}).get("baseline_value"),
              "suggested_min_value": (lever_entry or {}).get("suggested_min_value"),
              "suggested_max_value": (lever_entry or {}).get("suggested_max_value"),
              "preferred_uses": copy.deepcopy((lever_entry or {}).get("preferred_uses") or []),
              "target_driver": str(mapping_entry.get("target_driver") or "").strip() or None,
              "driver_value_unit": str((lever_entry or {}).get("input_semantics") or (lever_entry or {}).get("value_kind") or "").strip() or None,
              "return_value_in": "driver_units",
              "driver_target_conversion": copy.deepcopy(conversion_context),
            }
          )
        if not driver_paths:
          raise RuntimeError(
            "post_intake_driver_target_mapping_missing_driver_path: "
            f"{issue_code} target {target_metric_name} has no candidate lever mapped by the table."
          )
        feasible_target_bounds = _metric_target_bounds_constrained_by_driver_scaffold(
          direction_hint=direct_direction_hint,
          actual_metric_value=actual_metric_value,
          target_floor=direct_target_floor,
          target_ceiling=direct_target_ceiling,
          repair_envelope=direct_repair_envelope,
          driver_paths=driver_paths,
        )
        direct_target_floor = _safe_float(feasible_target_bounds.get("target_floor"))
        direct_target_ceiling = _safe_float(feasible_target_bounds.get("target_ceiling"))
        direct_repair_envelope = copy.deepcopy(feasible_target_bounds.get("repair_envelope") or direct_repair_envelope)
        if actual_metric_value is not None:
          if direct_direction_hint == "decrease" and direct_target_ceiling is not None:
            direct_gap_value = max(0.0, float(actual_metric_value) - float(direct_target_ceiling))
          elif direct_direction_hint == "increase" and direct_target_floor is not None:
            direct_gap_value = max(0.0, float(direct_target_floor) - float(actual_metric_value))
          direct_gap_abs_value = abs(float(_safe_float(direct_gap_value) or 0.0))
        acceptable_zone = copy.deepcopy(direct_metric_spec.get("acceptable_zone") or {})
        if direct_target_floor is not None or direct_target_ceiling is not None:
          acceptable_zone = {
            "minimum": direct_target_floor,
            "maximum": direct_target_ceiling,
          }
        pressure_packet = {
          "issue_code": issue_code,
          "issue_summary": str(issue_repair_packet.get("summary") or "").strip(),
          "root_cause": str(issue_repair_packet.get("root_cause") or "").strip(),
          "priority_rank": issue_repair_packet.get("priority_rank"),
          "impact_weight": issue_repair_packet.get("impact_weight"),
          "quarter_index": quarter_index,
          "metric_name": target_metric_name,
          "metric_definition": "Direct table-backed solver target from SQL post_intak_mapping_lookup.",
          "source_metric_names": [target_metric_name],
          "unit_kind": "currency",
          "severity_score": issue_repair_packet.get("severity_score"),
          "severity": issue_repair_packet.get("severity"),
          "current_value": int(round(float(actual_metric_value))) if actual_metric_value is not None else None,
          "direction_hint": direct_direction_hint or "solve_to_declared_target",
          "minimum_change_pct": None,
          "minimum_absolute_change": None,
          "equilibrium_target": int(round(float(direct_boundary_value))) if direct_boundary_value is not None else None,
          "suggested_floor_target": None,
          "suggested_ceiling_target": None,
          "minimum_target_value": int(round(float(direct_target_floor))) if direct_target_floor is not None else None,
          "maximum_target_value": int(round(float(direct_target_ceiling))) if direct_target_ceiling is not None else None,
          "target_floor": int(round(float(direct_target_floor))) if direct_target_floor is not None else None,
          "target_ceiling": int(round(float(direct_target_ceiling))) if direct_target_ceiling is not None else None,
          "acceptable_zone": copy.deepcopy(acceptable_zone),
          "gap": int(round(float(direct_gap_value))) if direct_gap_value is not None else None,
          "gap_abs": int(round(float(direct_gap_abs_value))) if direct_gap_abs_value is not None else None,
          "repair_envelope": copy.deepcopy(direct_repair_envelope),
          "candidate_lever_ids": copy.deepcopy(issue_candidate_lever_ids),
          "driver_paths": copy.deepcopy(driver_paths),
          "prompt_driver_paths": copy.deepcopy(driver_paths[:_CONVERGENCE_MAX_FOCUS_DRIVER_PATHS]),
          "driver_target_conversion_grid": [
            copy.deepcopy(path.get("driver_target_conversion"))
            for path in driver_paths
            if isinstance(path.get("driver_target_conversion"), dict)
            and path.get("driver_target_conversion")
          ],
          "spillover_flags": [],
          "mapping_source": "post_intak_mapping_lookup",
          "driver_feasibility_bounds": copy.deepcopy(feasible_target_bounds),
        }
        enriched_metric_pressure_packets.append(pressure_packet)
        issue_repair_packet["repair_targets"].append(
          {
            "quarter": quarter_index,
            "metric": target_metric_name,
            "direction": direct_direction_hint or "solve_to_declared_target",
            "actual_value": actual_metric_value,
            "target_floor": direct_target_floor,
            "target_ceiling": direct_target_ceiling,
            "acceptable_zone": copy.deepcopy(acceptable_zone),
            "gap": direct_gap_value,
            "source_metric_names": [target_metric_name],
            "metric_targets": [target_metric_name],
            "business_world_signal_reasons": copy.deepcopy(
              direct_metric_spec.get("business_world_signal_reasons") or []
            ),
            "repair_envelope": copy.deepcopy(direct_repair_envelope),
            "driver_paths": copy.deepcopy(driver_paths),
            "prompt_driver_paths": copy.deepcopy(driver_paths[:_CONVERGENCE_MAX_FOCUS_DRIVER_PATHS]),
            "driver_target_conversion_grid": [
              copy.deepcopy(path.get("driver_target_conversion"))
              for path in driver_paths
              if isinstance(path.get("driver_target_conversion"), dict)
              and path.get("driver_target_conversion")
            ],
            "spillover_flags": [],
            "driver_feasibility_bounds": copy.deepcopy(feasible_target_bounds),
          }
        )
  missing_issue_target_mappings = [
    {
      "issue_code": issue_code,
      "candidate_lever_ids": copy.deepcopy(packet.get("candidate_lever_ids") or []),
    }
    for issue_code, packet in issue_repair_packet_map.items()
    if issue_code
    and (packet.get("candidate_lever_ids") or [])
    and not (_issue_packet_declared_target_metric_names(packet) or [])
  ]
  if missing_issue_target_mappings:
    raise RuntimeError(
      "post_intake_driver_target_mapping_missing_issue_targets: "
      + "; ".join(
        f"{item['issue_code']} -> {item['candidate_lever_ids']}"
        for item in missing_issue_target_mappings
      )
    )

  issue_repair_packets = [
    copy.deepcopy(item)
    for item in sorted(
      issue_repair_packet_map.values(),
      key=lambda packet: (
        int(_safe_float(packet.get("priority_rank")) or 9999),
        str(packet.get("issue_code") or "").strip(),
      ),
    )
  ]
  for issue_packet in issue_repair_packets:
    mapped_candidate_lever_ids = _issue_packet_mapped_driver_lever_ids(issue_packet)
    issue_packet["candidate_lever_ids"] = copy.deepcopy(mapped_candidate_lever_ids)

  metric_pressure_with_equilibrium_target_count = sum(
    1
    for item in enriched_metric_pressure_packets
    if _safe_float(item.get("equilibrium_target")) is not None
  )
  metric_pressure_with_target_band_count = sum(
    1
    for item in enriched_metric_pressure_packets
    if _safe_float(item.get("minimum_target_value")) is not None
    and _safe_float(item.get("maximum_target_value")) is not None
  )
  translated_driver_path_count = sum(
    1
    for item in enriched_metric_pressure_packets
    for path in (item.get("driver_paths") or [])
    if _safe_float((path or {}).get("min_delta")) is not None
    or _safe_float((path or {}).get("max_delta")) is not None
  )
  translated_bound_packets = {
    "lever_band_scaffold": copy.deepcopy(lever_band_scaffold),
    "metric_pressure_packets": copy.deepcopy(enriched_metric_pressure_packets),
    "issue_repair_packets": copy.deepcopy(issue_repair_packets),
    "translation_failures": [],
  }
  lever_band_scaffold = copy.deepcopy(
    translated_bound_packets.get("lever_band_scaffold") or []
  )
  enriched_metric_pressure_packets = copy.deepcopy(
    translated_bound_packets.get("metric_pressure_packets") or []
  )
  issue_repair_packets = copy.deepcopy(
    translated_bound_packets.get("issue_repair_packets") or []
  )
  translation_failures.extend(
    [
      copy.deepcopy(item)
      for item in (translated_bound_packets.get("translation_failures") or [])
      if isinstance(item, dict)
    ]
  )

  return {
    "contract_version": "unified_numeric_guidance_v3",
    "completion_policy": _convergence_completion_policy_payload(),
    "scope_quarters": copy.deepcopy(scoped_quarters),
    "guidance_coverage_summary": {
      "metric_pressure_count": len(enriched_metric_pressure_packets),
      "metric_pressure_with_equilibrium_target_count": metric_pressure_with_equilibrium_target_count,
      "metric_pressure_with_target_band_count": metric_pressure_with_target_band_count,
      "lever_band_count": len(lever_band_scaffold),
      "lever_band_with_value_range_count": len(lever_band_scaffold),
      "translated_driver_path_count": translated_driver_path_count,
      "translation_failure_count": len(translation_failures),
      "issue_repair_packet_count": len(issue_repair_packets),
      "focus_issue_codes": copy.deepcopy(focus_issue_codes),
    },
    "metric_pressure_packets": enriched_metric_pressure_packets,
    "lever_band_scaffold": lever_band_scaffold,
    "issue_repair_packets": issue_repair_packets,
    "translation_failures": copy.deepcopy(translation_failures),
    "convergence_scorecard": _build_convergence_scorecard(
      controller_resolution_state=controller_state,
      controller_retry_context=retry_context,
    ),
  }

def _controller_resolution_from_verification_issue(
  issue_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  result = issue_result if isinstance(issue_result, dict) else {}
  verifier_status = _normalize_realism_verifier_status(result.get("status"))
  remaining_issue_materiality = _normalize_realism_materiality(
    result.get("remaining_issue_materiality")
    if result.get("remaining_issue_materiality") is not None
    else result.get("residual_materiality")
  )
  remaining_issue_severity_score = _safe_int_in_range(
    result.get("remaining_issue_severity_score")
    if result.get("remaining_issue_severity_score") is not None
    else result.get("residual_severity_score"),
    default=100 if verifier_status == "not_resolved" else 50,
    minimum=0,
    maximum=100,
  )
  remaining_problem_quarters = _normalize_realism_remaining_quarters(
    result.get("remaining_problem_quarters")
  )
  next_required_lever_ids = _normalize_realism_lever_ids(
    result.get("next_required_lever_ids")
  )

  return {
    "verifier_status": verifier_status,
    "remaining_issue_materiality": remaining_issue_materiality,
    "remaining_issue_severity_score": remaining_issue_severity_score,
    "remaining_problem_quarters": remaining_problem_quarters,
    "next_required_lever_ids": next_required_lever_ids,
  }

def _iteration_decision_from_issue_record(
  item: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  record = item if isinstance(item, dict) else {}
  completion_snapshot = _controller_issue_completion_snapshot(record)
  completion_score_pct = int(_safe_float(completion_snapshot.get("completion_score_pct")) or 0)

  if str(completion_snapshot.get("effective_status") or "").strip().lower() == "resolved":
    return {
      "iteration_decision": "no_further_iteration_needed",
      "iteration_needed": False,
      "iteration_reason": "Verifier marked the issue resolved.",
    }

  if str(completion_snapshot.get("effective_status") or "").strip().lower() == "tolerated":
    return {
      "iteration_decision": "no_further_iteration_needed",
      "iteration_needed": False,
      "iteration_reason": (
        "Deterministic quarter-aware scoring marked the issue resolved enough to close: "
        f"{completion_score_pct}% completion meets the {_CONVERGENCE_ISSUE_PASS_SCORE_PCT}% pass threshold."
      ),
    }

  return {
    "iteration_decision": "continue_iteration",
    "iteration_needed": True,
    "iteration_reason": (
      "Verifier indicates the issue remains unresolved or below the deterministic completion threshold "
      f"({completion_score_pct}% < {_CONVERGENCE_ISSUE_PASS_SCORE_PCT}%)."
    ),
  }

def _clone_issue_status_records(issue_status_records: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
  return [
    _normalize_issue_record_to_controller_truth(item)
    for item in (issue_status_records or [])
    if isinstance(item, dict)
    and _is_known_post_intake_issue_code(item.get("issue_code"))
  ]

def _controller_issue_effective_status(item: Optional[Dict[str, Any]]) -> str:
  record = item if isinstance(item, dict) else {}
  cached_status = str(record.get("effective_status") or "").strip().lower()
  if cached_status in {"open", "resolved", "tolerated"}:
    return cached_status
  return str(_controller_issue_completion_snapshot(record).get("effective_status") or "open").strip().lower() or "open"

def _controller_issue_is_blocking(item: Optional[Dict[str, Any]]) -> bool:
  record = item if isinstance(item, dict) else {}
  return _controller_issue_effective_status(record) == "open"

def _issue_needs_iteration(item: Optional[Dict[str, Any]]) -> bool:
  record = item if isinstance(item, dict) else {}
  if isinstance(record.get("iteration_needed"), bool):
    return bool(record.get("iteration_needed"))
  return bool(_iteration_decision_from_issue_record(record).get("iteration_needed"))

def _normalize_issue_record_to_controller_truth(
  item: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  record = copy.deepcopy(item if isinstance(item, dict) else {})
  record["verifier_status"] = _normalize_realism_verifier_status(record.get("verifier_status"))
  iteration_decision = _iteration_decision_from_issue_record(record)
  issue_code = str(record.get("issue_code") or "").strip().lower()
  mapping_contract = _issue_mapping_contract_or_fail(
    issue_code,
    phase="cash_pass" if _is_cash_pass_owned_issue_code(issue_code) else "convergence",
    require_mapping=not _issue_is_hard_issue(record),
  )
  if mapping_contract:
    record["mapping_source"] = mapping_contract.get("mapping_source") or "post_intak_mapping_lookup"
    record["next_required_lever_ids"] = copy.deepcopy(mapping_contract.get("next_required_lever_ids") or [])
    record["candidate_lever_ids"] = copy.deepcopy(mapping_contract.get("candidate_lever_ids") or [])
    record["metric_targets"] = copy.deepcopy(mapping_contract.get("metric_targets") or [])
    record["target_metric_names"] = copy.deepcopy(mapping_contract.get("target_metric_names") or [])
    record["mapping_rows"] = copy.deepcopy(mapping_contract.get("mapping_rows") or [])
  record["status_source"] = "verifier_status"
  record["iteration_decision"] = str(iteration_decision.get("iteration_decision") or "").strip()
  record["iteration_needed"] = bool(iteration_decision.get("iteration_needed"))
  record["iteration_reason"] = str(iteration_decision.get("iteration_reason") or "").strip()
  record.pop("controller_status", None)
  record.pop("controller_blocking", None)
  record.pop("controller_resolution", None)
  record.pop("controller_close_reason", None)
  record.pop("status", None)
  record.pop("resolved_iteration", None)
  return record

def _refresh_issue_status_records_from_scan(
  *,
  existing_issue_status_records: Optional[List[Dict[str, Any]]],
  scanned_issue_status_records: Optional[List[Dict[str, Any]]],
  iteration: int,
) -> List[Dict[str, Any]]:
  existing_by_key: Dict[str, Dict[str, Any]] = {}
  scanned_by_key: Dict[str, Dict[str, Any]] = {}
  order: List[str] = []

  for item in _clone_issue_status_records(existing_issue_status_records):
    key = _issue_ledger_key(item)
    if not key or key in existing_by_key:
      continue
    existing_by_key[key] = copy.deepcopy(item)
    order.append(key)

  for item in _clone_issue_status_records(scanned_issue_status_records):
    key = _issue_ledger_key(item)
    if not key or key in scanned_by_key:
      continue
    scanned_by_key[key] = copy.deepcopy(item)
    if key not in order:
      order.append(key)

  refreshed: List[Dict[str, Any]] = []
  for key in order:
    existing = copy.deepcopy(existing_by_key.get(key) or {})
    scanned = copy.deepcopy(scanned_by_key.get(key) or {})
    if scanned:
      merged = _merge_issue_identity_fields(existing, scanned)
      if str(scanned.get("detail") or "").strip():
        merged["detail"] = str(scanned.get("detail") or "").strip()
      if str(scanned.get("candidate_kind") or "").strip():
        merged["candidate_kind"] = str(scanned.get("candidate_kind") or "").strip()
      first_detected_iteration = int(
        _safe_float(
          existing.get("first_detected_iteration")
          if existing.get("first_detected_iteration") is not None
          else scanned.get("first_detected_iteration")
        ) or iteration
      )
      merged["first_detected_iteration"] = max(1, first_detected_iteration)
      merged["last_seen_iteration"] = int(iteration)
      merged["verifier_status"] = "not_resolved"
      merged["remaining_issue_materiality"] = "material"
      merged["remaining_issue_severity_score"] = max(
        1,
        int(_safe_float(existing.get("remaining_issue_severity_score")) or 100),
      )
      refreshed.append(_normalize_issue_record_to_controller_truth(merged))
      continue

    if not existing:
      continue

    merged = copy.deepcopy(existing)
    if _controller_issue_is_blocking(merged):
      merged["verifier_status"] = "resolved"
      merged["remaining_issue_materiality"] = "immaterial"
      merged["remaining_issue_severity_score"] = 0
      merged["remaining_problem_quarters"] = []
      merged["next_required_lever_ids"] = []
      merged["verification_reason"] = (
        "Post-realism full-horizon scan no longer detected this issue, so the shaping stage "
        "is handing it forward as resolved."
      )
      merged["last_seen_iteration"] = int(iteration)
    refreshed.append(_normalize_issue_record_to_controller_truth(merged))

  return refreshed

def _issue_keys_from_status_records(
  issue_status_records: Optional[List[Dict[str, Any]]],
  *,
  status_filter: Optional[str] = None,
) -> List[str]:
  keys: List[str] = []
  for item in (issue_status_records or []):
    if not isinstance(item, dict):
      continue
    normalized = _normalize_issue_record_to_controller_truth(item)
    if status_filter:
      wanted = str(status_filter).strip().lower()
      if wanted == "open" and not _controller_issue_is_blocking(normalized):
        continue
      if wanted == "resolved" and _controller_issue_is_blocking(normalized):
        continue
      if wanted not in {"open", "resolved"} and _controller_issue_effective_status(normalized) != wanted:
        continue
    key = _issue_ledger_key(normalized)
    if key:
      keys.append(key)
  return keys

def _issue_keys_requiring_iteration(
  issue_status_records: Optional[List[Dict[str, Any]]],
) -> List[str]:
  keys: List[str] = []
  for item in (issue_status_records or []):
    if not isinstance(item, dict):
      continue
    normalized = _normalize_issue_record_to_controller_truth(item)
    if not _issue_needs_iteration(normalized):
      continue
    key = _issue_ledger_key(normalized)
    if key:
      keys.append(key)
  return keys

def _filter_issue_status_records(
  issue_status_records: Optional[List[Dict[str, Any]]],
  issue_keys: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
  normalized_records = [
    _normalize_issue_record_to_controller_truth(item)
    for item in (issue_status_records or [])
    if isinstance(item, dict)
    and not _is_retired_convergence_issue_record(item)
  ]
  if not issue_keys:
    return normalized_records
  allowed = {str(item).strip() for item in issue_keys if str(item).strip()}
  return [
    copy.deepcopy(item)
    for item in normalized_records
    if _issue_ledger_key(item) in allowed
  ]


def _build_realism_planner_issue_state(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  issue_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
  filtered_records = _filter_issue_status_records(issue_status_records, issue_keys)
  planner_issue_records: List[Dict[str, Any]] = []
  for item in filtered_records:
    issue_code = str(item.get("issue_code") or "").strip()
    if not issue_code:
      continue
    planner_issue_records.append(
      {
        "issue_code": issue_code,
        "issue": str(
          item.get("issue") or _canonical_issue_title(issue_code, "") or issue_code
        ).strip(),
        "detail": str(item.get("detail") or "").strip(),
        "remaining_issue_materiality": str(
          item.get("remaining_issue_materiality") or ""
        ).strip().lower(),
        "remaining_problem_quarters": _normalize_realism_remaining_quarters(
          item.get("remaining_problem_quarters")
        ),
        "remaining_issue_severity_score": _safe_int_in_range(
          item.get("remaining_issue_severity_score"),
          default=0,
          minimum=0,
          maximum=100,
        ),
        "next_required_lever_ids": _normalize_realism_lever_ids(
          item.get("next_required_lever_ids")
        ),
      }
    )
  return {
    "contract_version": "realism_planner_issue_state_v2",
    "issue_count": len(planner_issue_records),
    "issue_status_records": planner_issue_records,
  }

def _active_issue_codes_from_planner_issue_state(
  planner_issue_state: Optional[Dict[str, Any]],
) -> List[str]:
  codes: List[str] = []
  seen: Set[str] = set()
  for item in ((planner_issue_state or {}).get("issue_status_records") or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if not issue_code or issue_code in seen:
      continue
    seen.add(issue_code)
    codes.append(issue_code)
  return codes

def _build_controller_resolution_state_from_issue_ledger(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  iteration: int,
  verification_payload: Optional[Dict[str, Any]] = None,
  issue_keys: Optional[List[str]] = None,
  current_finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  filtered_records = _filter_issue_status_records(issue_status_records, issue_keys)
  full_records = _clone_issue_status_records(_filter_issue_status_records(issue_status_records, None))
  detected_records = filtered_records if issue_keys else full_records
  detected_issues = [
    _controller_issue_public_record(
      item,
      current_finmo_json=current_finmo_json,
    )
    for item in detected_records
  ]
  resolved_issues = [
    _controller_issue_public_record(
      item,
      current_finmo_json=current_finmo_json,
    )
    for item in filtered_records
    if str(
      _controller_issue_completion_snapshot(
        item,
        current_finmo_json=current_finmo_json,
      ).get("effective_status")
      or ""
    ).strip().lower() == "resolved"
  ]
  tolerated_issues = [
    _controller_issue_public_record(
      item,
      current_finmo_json=current_finmo_json,
    )
    for item in filtered_records
    if str(
      _controller_issue_completion_snapshot(
        item,
        current_finmo_json=current_finmo_json,
      ).get("effective_status")
      or ""
    ).strip().lower() == "tolerated"
  ]
  remaining_issues = [
    _controller_issue_public_record(
      item,
      current_finmo_json=current_finmo_json,
    )
    for item in filtered_records
    if bool(
      _controller_issue_completion_snapshot(
        item,
        current_finmo_json=current_finmo_json,
      ).get("blocking")
    )
  ]
  iteration_pending_issues = [
    _controller_issue_public_record(
      item,
      current_finmo_json=current_finmo_json,
    )
    for item in filtered_records
    if _issue_needs_iteration(item)
  ]
  issue_progress_snapshots = [
    _controller_issue_public_record(
      item,
      current_finmo_json=current_finmo_json,
    )
    for item in filtered_records
  ]
  grade_summary = _build_controller_issue_grade_summary(
    filtered_records,
    current_finmo_json=current_finmo_json,
  )
  verification = (
    verification_payload.get("verification")
    if isinstance(verification_payload, dict) and isinstance(verification_payload.get("verification"), dict)
    else {}
  )
  status = "all_cleared" if not remaining_issues else "issues_remaining"
  return {
    "contract_version": "controller_resolution_state_v3",
    "owner": "controller",
    "source_of_truth": "issue_status_records.verifier_status+deterministic_completion_scoring",
    "status": status,
    "display_status": "all cleared" if not remaining_issues else "issues remaining",
    "all_cleared": not remaining_issues,
    "hard_cleared": not remaining_issues and int(grade_summary.get("lowest_quarter_score_pct") or 0) >= _CONVERGENCE_ISSUE_PASS_SCORE_PCT,
    "detected_issue_count": len(detected_issues),
    "remaining_issue_count": len(remaining_issues),
    "resolved_issue_count": len(resolved_issues),
    "tolerated_issue_count": len(tolerated_issues),
    "iteration_pending_issue_count": len(iteration_pending_issues),
    "detected_issues": detected_issues,
    "remaining_issues": remaining_issues,
    "resolved_issues": resolved_issues,
    "tolerated_issues": tolerated_issues,
    "iteration_pending_issues": iteration_pending_issues,
    "issue_progress_snapshots": issue_progress_snapshots,
    "issue_status_records": _clone_issue_status_records(filtered_records),
    "last_review_iteration": int(iteration),
    "grade_pass_threshold_pct": int(grade_summary.get("grade_pass_threshold_pct") or _CONVERGENCE_ISSUE_PASS_SCORE_PCT),
    "overall_completion_score_pct": int(grade_summary.get("overall_completion_score_pct") or 0),
    "overall_completion_grade": str(grade_summary.get("overall_completion_grade") or "").strip() or "D",
    "average_issue_score_pct": int(grade_summary.get("average_issue_score_pct") or 0),
    "lowest_quarter_score_pct": int(grade_summary.get("lowest_quarter_score_pct") or 0),
    "lowest_quarter_grade": str(grade_summary.get("lowest_quarter_grade") or "").strip() or "D",
    "failing_quarter_count": int(grade_summary.get("failing_quarter_count") or 0),
    "failing_quarters": copy.deepcopy(grade_summary.get("failing_quarters") or []),
    "quarter_scorecard": copy.deepcopy(grade_summary.get("quarter_scorecard") or []),
    "verification_summary": {
      "overall_assessment": str(verification.get("overall_assessment") or "").strip(),
      "executive_summary": str(verification.get("executive_summary") or "").strip(),
    },
  }

def _controller_state_issue_status_records(
  controller_resolution_state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  return _clone_issue_status_records(controller_state.get("issue_status_records"))

def _controller_state_issue_summaries(
  controller_resolution_state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  if (
    isinstance(controller_state.get("detected_issues"), list)
    and isinstance(controller_state.get("remaining_issues"), list)
    and isinstance(controller_state.get("resolved_issues"), list)
    and isinstance(controller_state.get("tolerated_issues"), list)
  ):
    return {
      "detected_issue_count": int(_safe_float(controller_state.get("detected_issue_count")) or len(controller_state.get("detected_issues") or [])),
      "remaining_issue_count": int(_safe_float(controller_state.get("remaining_issue_count")) or len(controller_state.get("remaining_issues") or [])),
      "resolved_issue_count": int(_safe_float(controller_state.get("resolved_issue_count")) or len(controller_state.get("resolved_issues") or [])),
      "tolerated_issue_count": int(_safe_float(controller_state.get("tolerated_issue_count")) or len(controller_state.get("tolerated_issues") or [])),
      "overall_completion_score_pct": int(_safe_float(controller_state.get("overall_completion_score_pct")) or 0),
      "overall_completion_grade": str(controller_state.get("overall_completion_grade") or "").strip() or "D",
      "lowest_quarter_score_pct": int(_safe_float(controller_state.get("lowest_quarter_score_pct")) or 0),
      "failing_quarters": copy.deepcopy(controller_state.get("failing_quarters") or []),
      "detected_issues": copy.deepcopy(controller_state.get("detected_issues") or []),
      "remaining_issues": copy.deepcopy(controller_state.get("remaining_issues") or []),
      "resolved_issues": copy.deepcopy(controller_state.get("resolved_issues") or []),
      "tolerated_issues": copy.deepcopy(controller_state.get("tolerated_issues") or []),
      "issue_progress_snapshots": copy.deepcopy(controller_state.get("issue_progress_snapshots") or []),
    }
  records = _controller_state_issue_status_records(controller_state)
  detected_issues = [_controller_issue_public_record(item) for item in records]
  remaining_issues = [_controller_issue_public_record(item) for item in records if _controller_issue_is_blocking(item)]
  resolved_issues = [_controller_issue_public_record(item) for item in records if _controller_issue_effective_status(item) == "resolved"]
  tolerated_issues = [_controller_issue_public_record(item) for item in records if _controller_issue_effective_status(item) == "tolerated"]
  grade_summary = _build_controller_issue_grade_summary(records)
  return {
    "detected_issue_count": len(detected_issues),
    "remaining_issue_count": len(remaining_issues),
    "resolved_issue_count": len(resolved_issues),
    "tolerated_issue_count": len(tolerated_issues),
    "overall_completion_score_pct": int(grade_summary.get("overall_completion_score_pct") or 0),
    "overall_completion_grade": str(grade_summary.get("overall_completion_grade") or "").strip() or "D",
    "lowest_quarter_score_pct": int(grade_summary.get("lowest_quarter_score_pct") or 0),
    "failing_quarters": copy.deepcopy(grade_summary.get("failing_quarters") or []),
    "detected_issues": detected_issues,
    "remaining_issues": remaining_issues,
    "resolved_issues": resolved_issues,
    "tolerated_issues": tolerated_issues,
    "issue_progress_snapshots": copy.deepcopy(detected_issues),
  }

def _build_strategy_resolved_issue_constraints(
  issue_status_records: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  constraints: List[Dict[str, Any]] = []
  seen: set[str] = set()
  for item in _clone_issue_status_records(issue_status_records):
    if _controller_issue_is_blocking(item):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if not issue_code or issue_code in seen:
      continue
    seen.add(issue_code)
    constraints.append(
      {
        "issue_code": issue_code,
        "issue": str(item.get("issue") or _canonical_issue_title(issue_code, "") or issue_code).strip(),
        "detail": str(item.get("detail") or "").strip(),
        "verifier_status": str(item.get("verifier_status") or "").strip().lower() or "resolved",
        "preservation_priority": "strong_constraint",
        "preservation_rule": (
          "Preserve this resolved fix by default during strategy. "
          "Do not materially worsen it unless the improvement elsewhere is clearly larger "
          "and the tradeoff is explicitly explained."
        ),
      }
    )
  return constraints

def _build_strategy_recheck_context_payload(
  *,
  baseline_issue_status_records: Optional[List[Dict[str, Any]]],
  baseline_model_input_json: Optional[Dict[str, Any]],
  baseline_finmo_json: Optional[Dict[str, Any]],
  second_pass_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  baseline_records: List[Dict[str, Any]] = []
  baseline_resolved_issue_codes: List[str] = []
  baseline_open_issue_codes: List[str] = []
  for item in _clone_issue_status_records(baseline_issue_status_records):
    normalized = _normalize_issue_record_to_controller_truth(item)
    issue_code = str(normalized.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    baseline_records.append(
      {
        "issue_code": issue_code,
        "issue": str(
          normalized.get("issue") or _canonical_issue_title(issue_code, "") or issue_code
        ).strip(),
        "detail": str(normalized.get("detail") or "").strip(),
        "verifier_status": str(normalized.get("verifier_status") or "").strip().lower(),
        "remaining_issue_materiality": str(
          normalized.get("remaining_issue_materiality") or ""
        ).strip().lower(),
        "remaining_issue_severity_score": int(
          _safe_float(normalized.get("remaining_issue_severity_score")) or 0
        ),
        "remaining_problem_quarters": _normalize_realism_remaining_quarters(
          normalized.get("remaining_problem_quarters")
        ),
        "next_required_lever_ids": _normalize_realism_lever_ids(
          normalized.get("next_required_lever_ids")
        ),
        "iteration_needed": bool(normalized.get("iteration_needed")),
      }
    )
    if _controller_issue_is_blocking(normalized):
      baseline_open_issue_codes.append(issue_code)
    else:
      baseline_resolved_issue_codes.append(issue_code)

  return {
    "recheck_mode": "post_strategy_baseline_preserving",
    "baseline_issue_status_records": baseline_records,
    "baseline_resolved_issue_codes": baseline_resolved_issue_codes,
    "baseline_open_issue_codes": baseline_open_issue_codes,
    "strategy_changed_lever_ids": _touched_lever_ids_from_result(second_pass_result),
    "strategy_changed_issue_codes": _touched_issue_codes_from_result(second_pass_result),
    "baseline_resolved_model_input_json": _compact_model_input_for_verification(
      baseline_model_input_json
    ),
    "baseline_resolved_finmo_quarter_rows": _compact_quarter_metric_rows_for_storage(
      [
        row
        for row in (((baseline_finmo_json or {}) if isinstance(baseline_finmo_json, dict) else {}).get("quarter_rows") or [])
        if isinstance(row, dict)
      ]
    ),
  }

def _compact_model_input_for_verification(
  model_input_json: Optional[Dict[str, Any]],
  *,
  lever_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
  lever_id_set = {
    str(item or "").strip()
    for item in (lever_ids or [])
    if str(item or "").strip()
  }
  lever_values = _solved_lever_value_map(model_input_json)
  compact_values: Dict[str, List[Any]] = {}
  for lever_id in sorted(lever_values.keys()):
    if lever_id_set and lever_id not in lever_id_set:
      continue
    compact_values[lever_id] = [
      int(round(float(value)))
      for value in (lever_values.get(lever_id) or [])[:20]
    ]
  return {
    "storage_mode": "compact_verification_context",
    "lever_ids": sorted(compact_values.keys()),
    "lever_values_by_quarter": compact_values,
  }

def _build_realism_pass_consistency_context_payload(
  *,
  phase: str,
  prior_issue_status_records: Optional[List[Dict[str, Any]]],
  baseline_model_input_json: Optional[Dict[str, Any]],
  baseline_finmo_json: Optional[Dict[str, Any]],
  result_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  prior_records: List[Dict[str, Any]] = []
  prior_resolved_issue_codes: List[str] = []
  prior_open_issue_codes: List[str] = []
  for item in _clone_issue_status_records(prior_issue_status_records):
    normalized = _normalize_issue_record_to_controller_truth(item)
    issue_code = str(normalized.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    prior_records.append(
      {
        "issue_code": issue_code,
        "issue": str(
          normalized.get("issue") or _canonical_issue_title(issue_code, "") or issue_code
        ).strip(),
        "detail": str(normalized.get("detail") or "").strip(),
        "verifier_status": str(normalized.get("verifier_status") or "").strip().lower(),
        "remaining_issue_materiality": str(
          normalized.get("remaining_issue_materiality") or ""
        ).strip().lower(),
        "remaining_issue_severity_score": int(
          _safe_float(normalized.get("remaining_issue_severity_score")) or 0
        ),
        "remaining_problem_quarters": _normalize_realism_remaining_quarters(
          normalized.get("remaining_problem_quarters")
        ),
        "next_required_lever_ids": _normalize_realism_lever_ids(
          normalized.get("next_required_lever_ids")
        ),
      }
    )
    if _controller_issue_is_blocking(normalized):
      prior_open_issue_codes.append(issue_code)
    else:
      prior_resolved_issue_codes.append(issue_code)

  return {
    "phase": str(phase or "").strip().lower(),
    "prior_issue_status_records": prior_records,
    "prior_resolved_issue_codes": prior_resolved_issue_codes,
    "prior_open_issue_codes": prior_open_issue_codes,
    "changed_lever_ids": _touched_lever_ids_from_result(result_payload),
    "changed_issue_codes": _touched_issue_codes_from_result(result_payload),
    "baseline_model_input_json": _compact_model_input_for_verification(
      baseline_model_input_json
    ),
    "baseline_finmo_quarter_rows": _compact_quarter_metric_rows_for_storage(
      [
        row
        for row in (((baseline_finmo_json or {}) if isinstance(baseline_finmo_json, dict) else {}).get("quarter_rows") or [])
        if isinstance(row, dict)
      ]
    ),
  }

def _build_persisted_realism_memo_payload(
  *,
  controller_resolution_state: Optional[Dict[str, Any]],
  working_memo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  memo = working_memo if isinstance(working_memo, dict) else {}
  verification_summary = (
    memo.get("verification_summary")
    if isinstance(memo.get("verification_summary"), dict)
    else controller_state.get("verification_summary")
  )
  return {
    "contract_version": "realism_memo_storage_v3",
    "owner": "controller",
    "storage_mode": "non_canonical",
    "state_source": "planning_run_json.controller_resolution_state",
    "last_review_iteration": int(
      _safe_float(controller_state.get("last_review_iteration") or memo.get("last_review_iteration")) or 0
    ),
    "verification_summary": copy.deepcopy(verification_summary or {}),
  }

def _compact_issue_codes(items: Any) -> List[str]:
  codes: List[str] = []
  for item in (items or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if issue_code and issue_code not in codes:
      codes.append(issue_code)
  return codes

def _compact_realism_memo_for_trace(memo: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  memo_obj = memo if isinstance(memo, dict) else {}
  remaining_issues = [
    item for item in ((memo_obj.get("remaining_issues") or memo_obj.get("issues") or []))
    if isinstance(item, dict)
  ]
  resolved_issues = [item for item in (memo_obj.get("resolved_issues") or []) if isinstance(item, dict)]
  detected_issues = [
    item for item in ((memo_obj.get("detected_issues") or memo_obj.get("issues") or []))
    if isinstance(item, dict)
  ]
  return {
    "status": str(memo_obj.get("status") or "").strip(),
    "remaining_issue_count": len(remaining_issues),
    "resolved_issue_count": len(resolved_issues),
    "detected_issue_count": len(detected_issues) if detected_issues else len(remaining_issues),
    "remaining_issue_codes": _compact_issue_codes(remaining_issues),
    "resolved_issue_codes": _compact_issue_codes(resolved_issues),
    "detected_issue_codes": _compact_issue_codes(detected_issues if detected_issues else remaining_issues),
    "last_review_iteration": int(_safe_float(memo_obj.get("last_review_iteration")) or 0),
  }

def _compact_resolution_summary_for_trace(summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  summary_obj = summary if isinstance(summary, dict) else {}
  remaining = [item for item in (summary_obj.get("remaining_violations") or []) if isinstance(item, dict)]
  resolved = [item for item in (summary_obj.get("resolved_violations") or []) if isinstance(item, dict)]
  baseline = [item for item in (summary_obj.get("baseline_violations") or []) if isinstance(item, dict)]
  tolerated = [item for item in (summary_obj.get("tolerated_violations") or []) if isinstance(item, dict)]
  return {
    "status": str(summary_obj.get("status") or "").strip(),
    "all_cleared": bool(summary_obj.get("all_cleared")),
    "hard_cleared": bool(summary_obj.get("hard_cleared")),
    "remaining_issue_count": len(remaining),
    "resolved_issue_count": len(resolved),
    "tolerated_issue_count": len(tolerated),
    "baseline_issue_count": len(baseline),
    "remaining_issue_codes": _compact_issue_codes(remaining),
    "resolved_issue_codes": _compact_issue_codes(resolved),
    "tolerated_issue_codes": _compact_issue_codes(tolerated),
    "baseline_issue_codes": _compact_issue_codes(baseline),
  }

def _sanitize_realism_iteration_trace(
  iterations: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
  sanitized: List[Dict[str, Any]] = []
  for item in (iterations or []):
    if not isinstance(item, dict):
      continue
    entry = copy.deepcopy(item)
    if isinstance(entry.get("memo_before"), dict):
      entry["memo_before"] = _compact_realism_memo_for_trace(entry.get("memo_before"))
    if isinstance(entry.get("memo_after"), dict):
      entry["memo_after"] = _compact_realism_memo_for_trace(entry.get("memo_after"))
    fresh_issue_candidates = []
    for candidate in (entry.get("fresh_issue_candidates") or []):
      if not isinstance(candidate, dict):
        continue
      candidate_payload = {
        "issue_code": str(candidate.get("issue_code") or "").strip().lower(),
        "issue": str(candidate.get("issue") or "").strip(),
        "candidate_kind": str(candidate.get("candidate_kind") or "").strip(),
      }
      if candidate_payload["issue_code"] or candidate_payload["issue"] or candidate_payload["candidate_kind"]:
        fresh_issue_candidates.append(candidate_payload)
    if "fresh_issue_candidates" in entry:
      entry["fresh_issue_candidates"] = fresh_issue_candidates
    sanitized.append(entry)
  return sanitized

def _build_resolution_summary_from_issue_ledger(
  *,
  before_memo: Optional[Dict[str, Any]],
  issue_status_records: Optional[List[Dict[str, Any]]],
  verification_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del before_memo
  controller_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(issue_status_records),
    iteration=0,
    verification_payload=copy.deepcopy(verification_payload),
  )
  return {
    "status": str(controller_state.get("status") or "").strip(),
    "display_status": str(controller_state.get("display_status") or "").strip(),
    "baseline_violations": copy.deepcopy(controller_state.get("detected_issues") or []),
    "resolved_violations": copy.deepcopy(controller_state.get("resolved_issues") or []),
    "tolerated_violations": copy.deepcopy(controller_state.get("tolerated_issues") or []),
    "remaining_violations": copy.deepcopy(controller_state.get("remaining_issues") or []),
    "remaining_blocking_violations": copy.deepcopy(controller_state.get("remaining_issues") or []),
    "all_cleared": bool(controller_state.get("all_cleared")),
    "hard_cleared": bool(controller_state.get("hard_cleared")),
    "verification_executive_summary": str(
      ((controller_state.get("verification_summary") or {}) if isinstance(controller_state.get("verification_summary"), dict) else {}).get("executive_summary") or ""
    ).strip(),
  }

def _build_realism_memo_from_issue_ledger(
  *,
  before_memo: Optional[Dict[str, Any]],
  issue_status_records: Optional[List[Dict[str, Any]]],
  resolution_summary: Optional[Dict[str, Any]],
  iteration: int,
  verification_payload: Optional[Dict[str, Any]] = None,
  issue_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
  del before_memo
  controller_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(issue_status_records),
    iteration=iteration,
    verification_payload=copy.deepcopy(verification_payload),
    issue_keys=copy.deepcopy(issue_keys),
  )
  remaining_issues = copy.deepcopy(controller_state.get("remaining_issues") or [])
  return {
    "owner": "controller",
    "status": "resolved" if not remaining_issues else "ready",
    "issues": copy.deepcopy(remaining_issues),
    "detected_issues": copy.deepcopy(controller_state.get("detected_issues") or []),
    "resolved_issues": copy.deepcopy(controller_state.get("resolved_issues") or []),
    "remaining_issues": copy.deepcopy(remaining_issues),
    "last_review_iteration": int(controller_state.get("last_review_iteration") or iteration),
    "verification_summary": copy.deepcopy(controller_state.get("verification_summary") or {}),
  }

def _apply_realism_verification_to_issue_status_records(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  verification_payload: Optional[Dict[str, Any]],
  iteration: int,
  allowed_issue_keys: Optional[List[str]] = None,
  allow_new_records: bool = True,
) -> List[Dict[str, Any]]:
  base_records = {
    _issue_ledger_key(item): _normalize_issue_record_to_controller_truth(item)
    for item in (issue_status_records or [])
    if isinstance(item, dict) and _issue_ledger_key(item)
  }
  verification = (
    verification_payload.get("verification")
    if isinstance(verification_payload, dict) and isinstance(verification_payload.get("verification"), dict)
    else {}
  )
  if not verification:
    return [
      _normalize_issue_record_to_controller_truth(item)
      for item in (issue_status_records or [])
      if isinstance(item, dict)
    ]

  allowed = {str(item).strip() for item in (allowed_issue_keys or []) if str(item).strip()}
  issue_results = [item for item in (verification.get("issue_results") or []) if isinstance(item, dict)]
  records_by_key: Dict[str, Dict[str, Any]] = {}
  order: List[str] = []
  for item in issue_results:
    code = str(item.get("issue_code") or "").strip().lower()
    issue = str(item.get("issue") or code).strip()
    key = _issue_ledger_key({"issue_code": code})
    if not key:
      continue
    if allowed and key not in allowed:
      continue
    existing = copy.deepcopy(base_records.get(key) or {})
    if not existing and not allow_new_records:
      continue
    verification_reason = str(item.get("verification_reason") or "").strip()
    verifier_resolution = _controller_resolution_from_verification_issue(item)
    if not existing:
      existing = {
        "issue": issue or code,
        "detail": "",
        "first_detected_iteration": int(iteration),
      }
    if key not in records_by_key:
      order.append(key)
    if code:
      existing["issue_code"] = code
    if issue:
      existing["issue"] = issue
    if str(item.get("detail") or "").strip():
      existing["detail"] = str(item.get("detail") or "").strip()
    if int(_safe_float(existing.get("first_detected_iteration")) or 0) <= 0:
      existing["first_detected_iteration"] = int(iteration)
    existing["last_seen_iteration"] = int(iteration)
    existing["verifier_status"] = str(verifier_resolution.get("verifier_status") or "").strip()
    existing["remaining_issue_materiality"] = str(
      verifier_resolution.get("remaining_issue_materiality") or ""
    ).strip()
    existing["remaining_issue_severity_score"] = int(
      verifier_resolution.get("remaining_issue_severity_score") or 0
    )
    existing["verification_reason"] = verification_reason
    existing["remaining_problem_quarters"] = copy.deepcopy(
      verifier_resolution.get("remaining_problem_quarters") or []
    )
    existing["next_required_lever_ids"] = copy.deepcopy(
      verifier_resolution.get("next_required_lever_ids") or []
    )
    existing["observed_improvement_summary"] = str(item.get("observed_improvement_summary") or "").strip()
    records_by_key[key] = existing

  out: List[Dict[str, Any]] = []
  for key in order:
    record = records_by_key.get(key)
    if isinstance(record, dict):
      out.append(_normalize_issue_record_to_controller_truth(record))
  return out

def _merge_new_scan_detected_issues(
  *,
  existing_issue_status_records: Optional[List[Dict[str, Any]]],
  scanned_issue_status_records: Optional[List[Dict[str, Any]]],
  iteration: int,
) -> List[Dict[str, Any]]:
  out = _clone_issue_status_records(existing_issue_status_records)
  index_by_key = {
    _issue_ledger_key(item): idx
    for idx, item in enumerate(out)
    if isinstance(item, dict) and _issue_ledger_key(item)
  }
  for item in _clone_issue_status_records(scanned_issue_status_records):
    key = _issue_ledger_key(item)
    if not key:
      continue
    if key in index_by_key:
      existing = copy.deepcopy(out[index_by_key[key]])
      merged = _merge_issue_identity_fields(existing, item)
      if str(item.get("detail") or "").strip():
        merged["detail"] = str(item.get("detail") or "").strip()
      if str(item.get("candidate_kind") or "").strip():
        merged["candidate_kind"] = str(item.get("candidate_kind") or "").strip()
      merged["last_seen_iteration"] = int(iteration)
      merged["verifier_status"] = "not_resolved"
      merged["remaining_issue_materiality"] = str(item.get("remaining_issue_materiality") or "material").strip() or "material"
      merged["remaining_issue_severity_score"] = max(
        1,
        int(_safe_float(item.get("remaining_issue_severity_score")) or _safe_float(existing.get("remaining_issue_severity_score")) or 100),
      )
      merged["remaining_problem_quarters"] = copy.deepcopy(item.get("remaining_problem_quarters") or [])
      merged["next_required_lever_ids"] = copy.deepcopy(item.get("next_required_lever_ids") or [])
      out[index_by_key[key]] = _normalize_issue_record_to_controller_truth(merged)
      continue
    merged = _normalize_issue_record_to_controller_truth(item)
    first_detected_iteration = int(
      _safe_float(merged.get("first_detected_iteration")) or iteration
    )
    merged["first_detected_iteration"] = max(1, first_detected_iteration)
    merged["last_seen_iteration"] = int(iteration)
    out.append(merged)
    index_by_key[key] = len(out) - 1
  return [_normalize_issue_record_to_controller_truth(item) for item in out if isinstance(item, dict)]

def _issue_severity_label_from_score(score: Any) -> str:
  severity_score = int(_safe_float(score) or 0)
  if severity_score >= 85:
    return "high"
  if severity_score >= 60:
    return "medium"
  return "low"

def _numeric_solver_contract_issue_packet_map(
  numeric_solver_contract: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  issue_packet_map: Dict[str, Dict[str, Any]] = {}
  for item in (contract.get("issue_target_packets") or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    issue_packet_map[issue_code] = copy.deepcopy(item)
  return issue_packet_map

def _numeric_solver_contract_baseline_quarter_map(
  numeric_solver_contract: Optional[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  baseline_map: Dict[int, Dict[str, Any]] = {}
  for item in (contract.get("baseline_quarter_metrics") or []):
    if not isinstance(item, dict):
      continue
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    baseline_map[quarter_index] = copy.deepcopy(item)
  return baseline_map

def _build_deterministic_issue_packets(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
  prior_decision_payload: Optional[Dict[str, Any]] = None,
  current_finmo_json: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  prior_decision = prior_decision_payload if isinstance(prior_decision_payload, dict) else {}
  prior_packets = (
    prior_decision.get("decision", {}).get("issue_packets")
    if isinstance(prior_decision.get("decision"), dict)
    else []
  )
  prior_packet_map: Dict[str, Dict[str, Any]] = {}
  for item in (prior_packets or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    if issue_code:
      prior_packet_map[issue_code] = copy.deepcopy(item)

  issue_record_map: Dict[str, Dict[str, Any]] = {}
  issue_order: List[str] = []
  for item in _clone_issue_status_records(issue_status_records):
    normalized = _normalize_issue_record_to_controller_truth(item)
    issue_code = str(normalized.get("issue_code") or "").strip().lower()
    if not issue_code or _is_cash_pass_owned_issue_code(issue_code):
      continue
    if issue_code not in issue_order:
      issue_order.append(issue_code)
    issue_record_map[issue_code] = copy.deepcopy(normalized)

  contract_issue_packet_map = _numeric_solver_contract_issue_packet_map(numeric_solver_contract)
  baseline_quarter_map = _numeric_solver_contract_baseline_quarter_map(numeric_solver_contract)
  contract_writable_catalog_entries = []
  writable_catalog = (
    (numeric_solver_contract or {}).get("writable_lever_catalog")
    if isinstance((numeric_solver_contract or {}).get("writable_lever_catalog"), dict)
    else {}
  )
  contract_writable_catalog_entries = [
    copy.deepcopy(item)
    for item in (writable_catalog.get("entries") or [])
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  ]

  for issue_code in contract_issue_packet_map.keys():
    if issue_code not in issue_order:
      issue_order.append(issue_code)
  for issue_code in prior_packet_map.keys():
    if _is_cash_pass_owned_issue_code(issue_code):
      continue
    if issue_code not in issue_order:
      issue_order.append(issue_code)

  quarter_count = _contract_forecast_quarter_count()
  packets: List[Dict[str, Any]] = []
  for issue_code in issue_order:
    record = issue_record_map.get(issue_code) or {}
    contract_packet = contract_issue_packet_map.get(issue_code) or {}
    prior_packet = prior_packet_map.get(issue_code) or {}
    if not contract_packet:
      record_candidate_lever_ids = _table_issue_candidate_lever_ids(
        issue_record=record,
        contract_packet={},
        prior_packet=prior_packet,
        catalog_entries=contract_writable_catalog_entries,
      )
      record_metric_targets = post_intake_direct_target_metric_names_for_levers(
        record_candidate_lever_ids
      )
      if record_candidate_lever_ids and record_metric_targets:
        contract_packet = {
          "issue_code": issue_code,
          "candidate_lever_ids": copy.deepcopy(record_candidate_lever_ids),
          "next_required_lever_ids": copy.deepcopy(record_candidate_lever_ids),
          "metric_targets": copy.deepcopy(record_metric_targets),
          "remaining_problem_quarters": copy.deepcopy(
            record.get("remaining_problem_quarters")
            or record.get("relevant_quarters")
            or record.get("affected_quarters")
            or []
          ),
          "solver_objective": "solve_issue_through_explicit_table_backed_driver_targets",
          "mapping_source": "post_intak_mapping_lookup",
        }
      elif contract_issue_packet_map:
        continue
    if not contract_packet:
      available_contract_issue_codes = sorted(contract_issue_packet_map.keys())
      available_prior_issue_codes = sorted(prior_packet_map.keys())
      record_status = str(record.get("verifier_status") or "").strip().lower()
      record_effective_status = str(record.get("effective_status") or "").strip().lower()
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_contract: "
        f"{issue_code} is present in convergence but has no table-backed numeric solver contract packet. "
        f"record_status={record_status or 'unknown'}; "
        f"record_effective_status={record_effective_status or 'unknown'}; "
        f"available_contract_issue_codes={available_contract_issue_codes}; "
        f"available_prior_issue_codes={available_prior_issue_codes}"
      )
    issue_title = str(
      record.get("issue")
      or prior_packet.get("issue")
      or prior_packet.get("issue_summary")
      or _canonical_issue_title(issue_code, "")
      or issue_code
    ).strip()
    detail = str(record.get("detail") or prior_packet.get("detail") or "").strip()
    severity_score = int(
      _safe_float(record.get("remaining_issue_severity_score"))
      or _safe_float(contract_packet.get("remaining_issue_severity_score"))
      or 0
    )
    if severity_score <= 0:
      severity_score = 75
    metric_specs = _issue_metric_specs_for_record(
      record,
      current_finmo_json=copy.deepcopy(current_finmo_json if isinstance(current_finmo_json, dict) else {}),
      quarter_count=max(1, int(quarter_count or _CONVERGENCE_DEFAULT_QUARTER_COUNT)),
    )
    affected_quarters = sorted(
      {
        int(_safe_float(item) or 0)
        for item in (
          [
            int(_safe_float(spec.get("quarter_index")) or 0)
            for spec in (metric_specs or [])
            if int(_safe_float(spec.get("quarter_index")) or 0) >= 1
          ]
          or _normalize_realism_remaining_quarters(record.get("remaining_problem_quarters"))
          or contract_packet.get("remaining_problem_quarters")
          or prior_packet.get("affected_quarters")
          or []
        )
        if int(_safe_float(item) or 0) >= 1
      }
    )
    candidate_lever_ids: List[str] = []
    for lever_id in _table_issue_candidate_lever_ids(
      issue_record=record,
      contract_packet=contract_packet,
      prior_packet=prior_packet,
      catalog_entries=contract_writable_catalog_entries,
    ):
      if lever_id and lever_id not in candidate_lever_ids:
        candidate_lever_ids.append(lever_id)
    metric_targets = [
      str(item).strip()
      for item in post_intake_direct_target_metric_names_for_levers(candidate_lever_ids)
      if str(item).strip()
    ]
    metric_targets = list(dict.fromkeys(metric_targets))
    if not metric_targets:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_targets: "
        f"{issue_code} has no table-backed target metrics from mapped candidate levers."
      )
    evidence_points: List[Dict[str, Any]] = []
    metric_spec_by_quarter: Dict[int, List[Dict[str, Any]]] = {}
    for spec in metric_specs:
      quarter_index = int(_safe_float(spec.get("quarter_index")) or 0)
      if quarter_index < 1:
        continue
      metric_spec_by_quarter.setdefault(quarter_index, []).append(copy.deepcopy(spec))
    for quarter_index in affected_quarters:
      baseline_metrics = baseline_quarter_map.get(quarter_index) or {}
      quarter_specs = metric_spec_by_quarter.get(quarter_index) or []
      metric_spec = quarter_specs[0] if quarter_specs else {}
      metric_name = str(
        next(
          (
            metric
            for metric in metric_targets
            if _safe_float((baseline_metrics or {}).get(metric)) is not None
          ),
          metric_targets[0],
        )
      ).strip().lower()
      observed_value = (
        float(_safe_float((baseline_metrics or {}).get(metric_name)) or 0.0)
      )
      problem_statement = str(metric_spec.get("metric_definition") or "").strip()
      if not problem_statement:
        problem_statement = (
          f"{issue_title} remains materially open in quarter {quarter_index} and still requires an operationally credible fix."
        )
      evidence_points.append(
        {
          "quarter_index": quarter_index,
          "metric_name": metric_name,
          "observed_value": observed_value,
          "problem_statement": problem_statement,
        }
      )
    if not evidence_points:
      evidence_points.append(
        {
          "quarter_index": 1,
          "metric_name": metric_targets[0],
          "observed_value": 0.0,
          "problem_statement": (
            f"{issue_title} remains materially open and still requires a quantified, model-backed fix."
          ),
        }
      )
    success_criteria = [
      f"{metric_name} is explicitly targeted and solved through the mapped model-input driver path."
      for metric_name in metric_targets[:4]
    ]
    disallowed_fix_patterns = [
      "Do not rely on explanation-only justification without actual model changes.",
      "Do not leave the issue open in later quarters after improving only the early horizon.",
    ]
    for item in (prior_packet.get("disallowed_fix_patterns") or []):
      text = str(item or "").strip()
      if text and text not in disallowed_fix_patterns:
        disallowed_fix_patterns.append(text)
    packets.append(
      {
        "issue_code": issue_code,
        "issue": issue_title,
        "detail": detail,
        "issue_summary": issue_title,
        "severity": _issue_severity_label_from_score(severity_score),
        "root_cause": (
          str((metric_specs[0] if metric_specs else {}).get("metric_definition") or "").strip()
          or detail
          or issue_title
        ),
        "affected_quarters": affected_quarters or [1],
        "evidence_points": evidence_points,
        "candidate_lever_ids": candidate_lever_ids,
        "required_fix_shape": str(
          contract_packet.get("solver_objective")
          or prior_packet.get("required_fix_shape")
          or "align_issue_to_viable_quarter_shape"
        ).strip(),
        "success_criteria": success_criteria,
        "disallowed_fix_patterns": disallowed_fix_patterns,
        "remaining_issue_materiality": str(
          record.get("remaining_issue_materiality")
          or contract_packet.get("remaining_issue_materiality")
          or "material"
        ).strip().lower(),
        "remaining_issue_severity_score": severity_score,
        "remaining_problem_quarters": affected_quarters,
        "relevant_quarters": affected_quarters,
        "next_required_lever_ids": candidate_lever_ids,
        "metric_targets": metric_targets,
        "solver_objective": str(contract_packet.get("solver_objective") or "").strip(),
      }
    )
  return packets

def _build_issue_packets_from_issue_ledger(
  *,
  issue_status_records: Optional[List[Dict[str, Any]]],
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
  prior_decision_payload: Optional[Dict[str, Any]] = None,
  current_finmo_json: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  return _build_deterministic_issue_packets(
    issue_status_records=issue_status_records,
    numeric_solver_contract=numeric_solver_contract,
    prior_decision_payload=prior_decision_payload,
    current_finmo_json=current_finmo_json,
  )

def _numeric_adjust_actions_contract_error(
  *,
  recommended_actions: Optional[List[Dict[str, Any]]],
  action_quarter_mode: str,
  require_issue_codes: bool = False,
  required_target_quarters: Optional[List[int]] = None,
  default_required_metric_keys: Optional[List[str]] = None,
) -> Optional[str]:
  normalized_actions = [item for item in (recommended_actions or []) if isinstance(item, dict)]
  required_quarters = sorted(
    {
      int(_safe_float(item) or 0)
      for item in (required_target_quarters or [])
      if int(_safe_float(item) or 0) >= 1
    }
  )
  table_required_metric_keys = [
    str(item).strip()
    for item in (
      default_required_metric_keys
      if isinstance(default_required_metric_keys, list)
      else _REQUIRED_SOLVER_TARGET_METRIC_KEYS
    )
    if str(item).strip()
  ]
  if not normalized_actions:
    return "At least one recommended_action is required for an adjust decision."
  all_metric_quarters: set[int] = set()
  for action in normalized_actions:
    action_id = str(action.get("action_id") or "").strip() or "action"
    if require_issue_codes:
      issue_codes = [
        str(item or "").strip()
        for item in (action.get("issue_codes") or [])
        if str(item or "").strip()
      ]
      if not issue_codes:
        return f"{action_id} must include non-empty issue_codes."
    allowed_levers = [
      str(item or "").strip()
      for item in (action.get("solver_allowed_lever_ids") or [])
      if str(item or "").strip()
    ]
    if not allowed_levers:
      return f"{action_id} must include non-empty solver_allowed_lever_ids."
    quarter_target_metrics = [item for item in (action.get("quarter_target_metrics") or []) if isinstance(item, dict)]
    if not quarter_target_metrics:
      return f"{action_id} must include quarter_target_metrics."
    action_required_metric_keys = _normalize_primary_target_metric_names(
      action.get("required_target_metric_keys") or []
    )
    if not action_required_metric_keys:
      action_required_metric_keys = copy.deepcopy(table_required_metric_keys)
    metric_quarter_set = {
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in quarter_target_metrics
      if int(_safe_float(item.get("quarter_index")) or 0) >= 1
    }
    if action_quarter_mode == "target_quarters":
      expected_quarter_set = {
        int(_safe_float(q) or 0)
        for q in (action.get("target_quarters") or [])
        if int(_safe_float(q) or 0) >= 1
      }
      if not expected_quarter_set:
        return f"{action_id} must include non-empty target_quarters."
      if metric_quarter_set != expected_quarter_set:
        return (
          f"{action_id} target_quarters and quarter_target_metrics quarter_index set must match exactly. "
          f"target_quarters={sorted(expected_quarter_set)}, quarter_target_metrics={sorted(metric_quarter_set)}."
        )
    else:
      start_q = int(_safe_float(action.get("timing_start_q")) or 0)
      end_q = int(_safe_float(action.get("timing_end_q")) or 0)
      if start_q < 1 or end_q < start_q:
        return f"{action_id} must include a valid timing_start_q/timing_end_q window."
      expected_quarter_set = set(range(start_q, end_q + 1))
      if metric_quarter_set != expected_quarter_set:
        return (
          f"{action_id} timing window and quarter_target_metrics quarter_index set must match exactly. "
          f"timing_window={sorted(expected_quarter_set)}, quarter_target_metrics={sorted(metric_quarter_set)}."
        )
    all_metric_quarters.update(metric_quarter_set)
    for item in quarter_target_metrics:
      quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
      if quarter_index < 1:
        return f"{action_id} quarter_target_metrics contained an invalid quarter_index."
      for metric_name in action_required_metric_keys:
        metric_value = _safe_float(item.get(metric_name))
        if metric_value is None:
          return (
            f"{action_id} quarter_target_metrics for Q{quarter_index} is missing a numeric value for {metric_name}. "
            "All required target lines must be preset numerically for every targeted quarter."
          )
        if float(metric_value) != float(int(round(float(metric_value)))):
          return (
            f"{action_id} quarter_target_metrics for Q{quarter_index} metric {metric_name} must be a whole-dollar integer value. "
            f"received={metric_value}."
          )
  if required_quarters:
    missing_required_quarters = [quarter for quarter in required_quarters if quarter not in all_metric_quarters]
    if missing_required_quarters:
      return (
        "Recommended actions did not provide full required quarter coverage. "
        f"Missing quarter_target_metrics for quarters {missing_required_quarters}."
      )
  return None

def _normalize_unified_mapped_repair_targets(raw_targets: Any) -> List[Dict[str, Any]]:
  normalized: List[Dict[str, Any]] = []
  seen: set[Tuple[str, str, Tuple[int, ...]]] = set()
  for item in (raw_targets or []):
    if not isinstance(item, dict):
      continue
    issue_code = str(item.get("issue_code") or "").strip().lower()
    target_metric_name = str(item.get("target_metric_name") or "").strip().lower()
    target_quarters = sorted(
      {
        int(_safe_float(quarter) or 0)
        for quarter in (item.get("target_quarters") or [])
        if int(_safe_float(quarter) or 0) >= 1
      }
    )
    if not issue_code or not target_metric_name or not target_quarters:
      continue
    mapping_key = (issue_code, target_metric_name, tuple(target_quarters))
    if mapping_key in seen:
      continue
    seen.add(mapping_key)
    normalized.append(
      {
        "issue_code": issue_code,
        "target_metric_name": target_metric_name,
        "target_quarters": copy.deepcopy(target_quarters),
      }
    )
  return normalized

def _declared_mapped_target_metric_names(
  lever_adjustments: Any,
) -> List[str]:
  out: List[str] = []
  for adjustment in (lever_adjustments or []):
    if not isinstance(adjustment, dict):
      continue
    for mapping in _normalize_unified_mapped_repair_targets(
      adjustment.get("mapped_repair_targets") or []
    ):
      metric_name = str(mapping.get("target_metric_name") or "").strip().lower()
      if metric_name and metric_name in _UNIFIED_ALLOWED_TARGET_METRIC_KEYS and metric_name not in out:
        out.append(metric_name)
  return out

def _repair_target_direct_target_metric_names(
  repair_target: Optional[Dict[str, Any]],
) -> List[str]:
  item = repair_target if isinstance(repair_target, dict) else {}
  lever_ids = [
    str((driver_path or {}).get("lever") or "").strip()
    for driver_path in (item.get("driver_paths") or [])
    if isinstance(driver_path, dict) and str((driver_path or {}).get("lever") or "").strip()
  ]
  return post_intake_direct_target_metric_names_for_levers(lever_ids)

def _merge_required_target_tolerances(
  raw_tolerances: Any,
  required_metric_names: Any,
) -> List[Dict[str, Any]]:
  merged = _normalize_unified_target_tolerances(raw_tolerances)
  existing_metric_names = {
    str(item.get("metric_name") or "").strip().lower()
    for item in merged
    if isinstance(item, dict) and str(item.get("metric_name") or "").strip()
  }
  for item in _default_unified_target_tolerances(required_metric_names):
    metric_name = str(item.get("metric_name") or "").strip().lower()
    if metric_name and metric_name not in existing_metric_names:
      merged.append(copy.deepcopy(item))
      existing_metric_names.add(metric_name)
  merged.sort(key=lambda item: str(item.get("metric_name") or "").strip().lower())
  return merged

def _augment_solver_quarter_target_metrics(
  *,
  raw_targets: Any,
  required_metric_names: Any,
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
  required_target_quarters: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
  normalized_targets = _normalize_solver_quarter_target_metrics(raw_targets)
  _ = _normalize_primary_target_metric_names(required_metric_names)
  _ = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else None
  _ = copy.deepcopy(required_target_quarters or [])
  return normalized_targets

def _issue_packet_mapped_driver_lever_ids(
  issue_packet: Optional[Dict[str, Any]],
) -> List[str]:
  packet = issue_packet if isinstance(issue_packet, dict) else {}
  ordered_lever_ids: List[str] = []
  for repair_target in (packet.get("repair_targets") or []):
    if not isinstance(repair_target, dict):
      continue
    for driver_path in (repair_target.get("driver_paths") or []):
      if not isinstance(driver_path, dict):
        continue
      lever_id = str(driver_path.get("lever") or "").strip()
      if lever_id and lever_id not in ordered_lever_ids:
        ordered_lever_ids.append(lever_id)
  return ordered_lever_ids

def _deterministic_guidance_focus_issue_codes(
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
) -> List[str]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  ordered_issue_codes: List[str] = []
  for issue_packet in (guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    issue_code = str(issue_packet.get("issue_code") or "").strip().lower()
    if issue_code and issue_code not in ordered_issue_codes:
      ordered_issue_codes.append(issue_code)
    if len(ordered_issue_codes) >= _CONVERGENCE_MAX_FOCUS_ISSUES:
      break
  return ordered_issue_codes

def _issue_packet_declared_target_metric_names(
  issue_packet: Optional[Dict[str, Any]],
) -> List[str]:
  packet = issue_packet if isinstance(issue_packet, dict) else {}
  ordered_metric_names: List[str] = []
  allowed_primary_metrics = set(_UNIFIED_ALLOWED_TARGET_METRIC_KEYS)
  issue_code = str(packet.get("issue_code") or "").strip().lower()
  for metric_name in post_intake_target_metric_names_for_issue(
    issue_code,
    phase="cash_pass" if _is_cash_pass_owned_issue_code(issue_code) else "convergence",
  ):
    if metric_name and metric_name in allowed_primary_metrics and metric_name not in ordered_metric_names:
      ordered_metric_names.append(metric_name)
  for repair_target in (packet.get("repair_targets") or []):
    if not isinstance(repair_target, dict):
      continue
    for metric_name in _repair_target_direct_target_metric_names(repair_target):
      if metric_name and metric_name in allowed_primary_metrics and metric_name not in ordered_metric_names:
        ordered_metric_names.append(metric_name)
  if ordered_metric_names:
    return ordered_metric_names
  return ordered_metric_names

def _table_issue_candidate_lever_ids(
  *,
  issue_record: Optional[Dict[str, Any]] = None,
  contract_packet: Optional[Dict[str, Any]] = None,
  prior_packet: Optional[Dict[str, Any]] = None,
  catalog_entries: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
  record = issue_record if isinstance(issue_record, dict) else {}
  contract = contract_packet if isinstance(contract_packet, dict) else {}
  prior = prior_packet if isinstance(prior_packet, dict) else {}
  issue_code = str(
    contract.get("issue_code")
    or prior.get("issue_code")
    or record.get("issue_code")
    or ""
  ).strip().lower()
  if issue_code:
    catalog_lever_ids = [
      str(item.get("lever_id") or "").strip()
      for item in (catalog_entries or [])
      if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
    ]
    if catalog_lever_ids:
      return post_intake_concrete_issue_lever_ids_from_catalog(
        issue_code,
        catalog_lever_ids,
        phase="convergence",
      )
    return post_intake_issue_candidate_lever_ids(issue_code, phase="convergence")
  return []

from client_intake_and_finmo.post_intake_issues.detection import (  # noqa: E402,F401
  _build_capacity_support_issue_status_records,
  _build_p_and_l_flatline_issue_status_records,
  _build_stage_maturity_cost_structure_issue_status_records,
  _cost_structure_direct_metric_specs_for_quarter,
  _issue_metric_specs_for_quarter,
  _p_and_l_flatline_signals,
  _raise_p_and_l_flatline_if_needed,
)

