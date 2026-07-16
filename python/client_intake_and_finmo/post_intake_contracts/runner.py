import copy
import hashlib
import json
import math
import os
import re
import time
import calendar
import logging
import requests
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_CONVERGENCE_MAX_FOCUS_LEVERS = 12
_CONVERGENCE_MAX_FOCUS_ISSUES = 2
_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT = 1
_UNIFIED_ALLOWED_TARGET_METRIC_KEYS: Tuple[str, ...] = tuple()
_SOLVER_TARGET_METRIC_KEYS: Tuple[str, ...] = tuple()
_UNIFIED_PRIMARY_TARGET_MIN_COUNT = 1
_UNIFIED_PRIMARY_TARGET_MAX_COUNT = 6
_REQUIRED_SOLVER_TARGET_METRIC_KEYS: Tuple[str, ...] = tuple()
_RETRY_MEMORY_MAX_PRIOR_LEVER_UNIONS = 4
_RETRY_MEMORY_MAX_PRIOR_TARGET_KEYS = 4
_RETRY_MEMORY_MAX_VALIDATION_ERRORS = 3
_RETRY_MEMORY_MAX_ATTEMPT_RECORDS = 3
_PASS_RETRY_NEGLIGIBLE_IMPROVEMENT_RATIO = 0.05
R_AND_D_APPLICABILITY_LEVER_ID = "expenses::Research & Development"
R_AND_D_APPLICABILITY_POLICY_VERSION = "r_and_d_applicability_pre_forecast_v1"

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_build_prompt_from_contract,
  post_intake_direct_target_metric_for_lever,
  post_intake_direct_target_metric_names_for_levers,
  post_intake_driver_target_mapping_entry,
  post_intake_driver_target_metric_ids,
  post_intake_gpt_contract_compact_prompt_field_spec,
  post_intake_gpt_contract_errors,
  post_intake_gpt_contract_field_for_path,
  post_intake_gpt_contract_horizon_errors,
  post_intake_gpt_contract_normalize_payload,
  post_intake_gpt_contract_openai_schema,
  post_intake_gpt_contract_payload_errors,
  post_intake_gpt_contract_prompt_field_spec,
  post_intake_gpt_context_filter_payload,
  post_intake_gpt_context_rows,
  post_intake_gpt_context_request_char_budget,
  post_intake_issue_mapping_contract,
  post_intake_normalize_lever_value,
  post_intake_normalize_target_value,
  post_intake_precision_unit,
  post_intake_process_sequence_step,
  post_intake_target_precision_for_metric,
  post_intake_target_value_kind_for_metric,
  stage_planning_ramp_policy,
)
from client_intake_and_finmo.post_intake_foundation import bind_table_safe_runtime_dependencies  # type: ignore
from client_intake_and_finmo.post_intake_balance_sheet import (  # type: ignore
  balance_sheet_contextual_seed_candidate_rows,
  validate_balance_sheet_contextual_seed_payload,
)

_UNIFIED_ALLOWED_TARGET_METRIC_KEYS = tuple(post_intake_driver_target_metric_ids())
_SOLVER_TARGET_METRIC_KEYS = _UNIFIED_ALLOWED_TARGET_METRIC_KEYS
_REQUIRED_SOLVER_TARGET_METRIC_KEYS = _UNIFIED_ALLOWED_TARGET_METRIC_KEYS

def _safe_float(value: Any) -> Optional[float]:
  try:
    if value is None or value == "":
      return None
    return float(value)
  except Exception:
    return None


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


def _contract_numeric_bounds(
  *,
  contract_name: str,
  field_path: str,
  default_min: float,
  default_max: float,
) -> Tuple[float, float]:
  row = post_intake_gpt_contract_field_for_path(
    contract_name=contract_name,
    field_path=field_path,
    required=False,
  ) or {}
  minimum = _safe_float(row.get("min_value"))
  maximum = _safe_float(row.get("max_value"))
  return (
    float(minimum) if minimum is not None else float(default_min),
    float(maximum) if maximum is not None else float(default_max),
  )


_CONVERGENCE_DEFAULT_QUARTER_COUNT = _contract_forecast_quarter_count("unified_convergence_decision")
_CONVERGENCE_MAX_FOCUS_QUARTERS = _CONVERGENCE_DEFAULT_QUARTER_COUNT
_UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT = _CONVERGENCE_DEFAULT_QUARTER_COUNT


def _safe_ratio(value: Any) -> Optional[float]:
  parsed = _safe_float(value)
  if parsed is None:
    return None
  if abs(parsed) > 1.0 and abs(parsed) <= 100.0:
    return parsed / 100.0
  return parsed


def _parse_date(value: Any) -> Optional[date]:
  if isinstance(value, date) and not isinstance(value, datetime):
    return value
  if isinstance(value, datetime):
    return value.date()
  raw = str(value or "").strip()
  if not raw:
    return None
  try:
    return datetime.fromisoformat(raw).date()
  except ValueError:
    pass
  for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
    try:
      return datetime.strptime(raw, fmt).date()
    except ValueError:
      continue
  return None


def _whole_months_between(start_date: date, end_date: date) -> int:
  months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
  if end_date.day < start_date.day:
    months -= 1
  return int(months)


def _infer_business_stage(start_date_raw: Any, current_date: Optional[date] = None) -> Optional[str]:
  start_date = _parse_date(start_date_raw)
  if start_date is None:
    return None
  today = current_date or datetime.utcnow().date()
  if start_date > today:
    return "pre-revenue"
  delta_days = (today - start_date).days
  if delta_days <= 365:
    return "early-stage"
  return "operating"


def _openai_key() -> Optional[str]:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  return key or None


def _openai_model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]):
  # Routed through the shared OpenAI HTTP helper so these calls get the same
  # retry policy AND the GPT response lock (full-pipeline determinism) as
  # every other GPT call site. Same (url, headers, payload) -> response shape.
  from client_intake_and_finmo.openai_http import post_openai_with_retries  # type: ignore
  return post_openai_with_retries(
    url=url, headers=headers, payload=payload,
    timeout_seconds=180.0,
    retryable_status=(429, 500, 502, 503, 504), max_attempts=3,
  )


def _parse_responses_text(data: Dict[str, Any]) -> str:
  if not isinstance(data, dict):
    return ""
  text = data.get("output_text")
  if isinstance(text, str):
    return text
  output = data.get("output") or []
  chunks: List[str] = []
  for item in output:
    if not isinstance(item, dict):
      continue
    for part in item.get("content", []) or []:
      if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
        chunks.append(str(part.get("text") or ""))
  return "\n".join(chunk for chunk in chunks if chunk)


def _parse_responses_json_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  output = data.get("output") or [] if isinstance(data, dict) else []
  for item in output:
    if not isinstance(item, dict):
      continue
    for part in item.get("content", []) or []:
      if isinstance(part, dict) and part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
  try:
    parsed = json.loads(_parse_responses_text(data))
  except Exception:
    return None
  return parsed if isinstance(parsed, dict) else None


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  if not isinstance(dependencies, dict):
    return
  bind_table_safe_runtime_dependencies(globals(), dependencies)


def _openai_strict_json_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
  """Normalize local schemas to OpenAI strict structured-output requirements."""
  normalized = copy.deepcopy(schema if isinstance(schema, dict) else {})

  def _visit(node: Any) -> None:
    if isinstance(node, dict):
      properties = node.get("properties")
      if isinstance(properties, dict):
        node["additionalProperties"] = False
        node["required"] = list(properties.keys())
        for child in properties.values():
          _visit(child)
      items = node.get("items")
      if isinstance(items, dict):
        _visit(items)
      for key in ("anyOf", "oneOf", "allOf"):
        variants = node.get(key)
        if isinstance(variants, list):
          for variant in variants:
            _visit(variant)
    elif isinstance(node, list):
      for item in node:
        _visit(item)

  _visit(normalized)
  return normalized


def _post_intake_prompt_context_manifest(
  *,
  contract_name: str,
  include_phase: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
  """Return the SQL-approved prompt context manifest for a GPT contract."""
  return {
    str(row.get("context_key") or "").strip(): copy.deepcopy(row)
    for row in post_intake_gpt_context_rows(
      contract_name=contract_name,
      include_phase=include_phase,
      include_in_prompt=True,
    )
    if str(row.get("context_key") or "").strip()
  }


def _put_prompt_context_from_manifest(
  payload: Dict[str, Any],
  manifest: Dict[str, Dict[str, Any]],
  key: str,
  value: Any,
) -> None:
  if key in manifest:
    payload[key] = copy.deepcopy(value)


def _cap_numeric_guidance_revenue_targets_to_locked_grid(
  numeric_guidance: Optional[Dict[str, Any]],
  *,
  locked_target_fill_grid: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Keep all GPT-facing revenue target hints inside the authoritative locked grid."""
  guidance = copy.deepcopy(numeric_guidance if isinstance(numeric_guidance, dict) else {})
  grid = locked_target_fill_grid if isinstance(locked_target_fill_grid, dict) else {}
  caps_by_quarter: Dict[int, float] = {}
  for row in grid.get("rows") or []:
    if not isinstance(row, dict):
      continue
    metric_name = str(row.get("metric_name") or "").strip().lower()
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    maximum_value = _safe_float(row.get("maximum_target_value"))
    if metric_name == "revenue" and quarter_index >= 1 and maximum_value is not None:
      caps_by_quarter[quarter_index] = float(maximum_value)
  if not caps_by_quarter:
    return guidance

  target_fields = (
    "target_ceiling",
    "maximum_target_value",
    "equilibrium_target",
    "suggested_ceiling_target",
  )

  def _cap_target_payload(payload: Dict[str, Any], *, quarter_index: int, metric_name: str) -> None:
    if metric_name != "revenue" or quarter_index not in caps_by_quarter:
      return
    cap_value = float(caps_by_quarter[quarter_index])
    cap_int = int(math.floor(cap_value))
    changed = False
    for field in target_fields:
      current = _safe_float(payload.get(field))
      if current is not None and float(current) > cap_value:
        payload[field] = cap_int
        changed = True
    for field in ("target_floor", "minimum_target_value", "suggested_floor_target"):
      current = _safe_float(payload.get(field))
      if current is not None and float(current) > cap_value:
        payload[field] = cap_int
        changed = True
    zone = payload.get("acceptable_zone")
    if isinstance(zone, dict):
      maximum = _safe_float(zone.get("maximum"))
      if maximum is not None and float(maximum) > cap_value:
        zone["maximum"] = cap_int
        changed = True
      minimum = _safe_float(zone.get("minimum"))
      if minimum is not None and float(minimum) > cap_value:
        zone["minimum"] = cap_int
        changed = True
    current_value = _safe_float(payload.get("current_value"))
    if current_value is not None:
      gap = max(0.0, float(current_value) - cap_value)
      payload["gap"] = int(round(gap))
      payload["gap_abs"] = int(round(abs(gap)))
      if str(payload.get("direction_hint") or "").strip().lower() == "decrease":
        delta = min(0.0, cap_value - float(current_value))
        payload["repair_envelope"] = {
          "min_required_delta": int(round(delta)),
          "recommended_delta": int(round(delta)),
          "max_feasible_delta": int(round(delta)),
          "stage_ramp_capped": True,
        }
    if changed:
      payload["stage_ramp_cap_source"] = "locked_target_fill_grid"
      payload["stage_ramp_max_target_value"] = cap_int

  for packet in guidance.get("metric_pressure_packets") or []:
    if not isinstance(packet, dict):
      continue
    _cap_target_payload(
      packet,
      quarter_index=int(_safe_float(packet.get("quarter_index")) or 0),
      metric_name=str(packet.get("metric_name") or "").strip().lower(),
    )
  for issue_packet in guidance.get("issue_repair_packets") or []:
    if not isinstance(issue_packet, dict):
      continue
    for repair_target in issue_packet.get("repair_targets") or []:
      if not isinstance(repair_target, dict):
        continue
      _cap_target_payload(
        repair_target,
        quarter_index=int(_safe_float(repair_target.get("quarter")) or 0),
        metric_name=str(repair_target.get("metric") or "").strip().lower(),
      )
  return guidance


__all__ = [
  "_post_intake_gpt_contract_table_errors",
  "_post_intake_contract_schema",
  "_post_intake_contract_prompt_spec",
  "_normalize_post_intake_contract_payload",
  "_post_intake_contract_payload_errors",
  "_maintenance_capex_percent_schema",
  "_stage_ramp_contract_schema",
  "_rate_has_two_decimal_precision",
  "_normalize_stage_ramp_rate_for_validation",
  "_validate_stage_ramp_contract_payload",
  "_revenue_catalog_snapshot_for_starting_ppe",
  "_derive_maintenance_capex_percent_from_naics",
  "_stage_ramp_gpt_timeout_seconds",
  "_r_and_d_applicability_timeout_seconds",
  "_balance_sheet_contextual_seed_timeout_seconds",
  "_r_and_d_applicability_schema",
  "_balance_sheet_contextual_seed_schema",
  "_balance_sheet_seed_contract_row_fields",
  "_validate_r_and_d_applicability_payload",
  "_validate_balance_sheet_contextual_seed_payload",
  "_r_and_d_policy_from_model_input",
  "_r_and_d_enabled_from_model_input",
  "_model_input_r_and_d_live_values",
  "_assert_r_and_d_applicability_policy_applied",
  "_estimate_r_and_d_applicability_with_gpt",
  "_estimate_balance_sheet_contextual_seed_with_gpt",
  "_estimate_stage_ramp_contract_with_gpt",
  "build_python_stage_ramp_contract",
  "_solver_quarter_target_metrics_schema",
  "_unified_targets_by_quarter_schema",
  "_solver_target_contract_spec_payload",
  "_unified_convergence_engine_contract_payload",
  "_unified_solver_target_contract_spec_payload",
  "_build_repair_guidance_payload",
  "_capacity_support_revenue_bundle_contract_error",
  "_unified_target_values_repair_envelope_contract_error",
  "_numeric_decision_contract_error",
  "_revenue_targets_stage_ramp_contract_error",
  "_normalize_unified_decision_numeric_formatting",
  "_normalize_unified_decision_targets_to_locked_grid",
  "_unified_convergence_decision_contract_error",
  "_realism_verification_failure_payload",
  "_target_miss_verification_fallback",
  "_run_realism_verification_openai",
  "_validate_payroll_headcount_contract",
  "_normalize_retry_requirements_to_allowed_scope",
  "_table_mapped_repair_targets_for_lever",
  "_unified_primary_metric_coverage_error",
  "_solver_contract_quarter_count",
  "_remaining_horizon_quarters",
  "_normalize_primary_target_metric_names",
  "_normalize_unified_target_tolerances",
  "_default_unified_target_tolerances",
  "_solver_contract_primary_target_metric_keys",
  "_unified_required_target_metric_keys",
  "_normalize_solver_quarter_target_metrics",
  "_solver_contract_all_writable_lever_ids",
  "_solver_contract_eligible_lever_ids",
  "_derive_solver_allowed_lever_ids",
  "_action_package_solver_ready",
  "_solver_ready_touched_lever_ids",
  "_review_plan_has_solver_ready_actions",
  "_relevant_solver_target_quarters",
  "_target_verification_requires_retry",
  "_set_target_verification_controller_state",
  "_controller_retry_stage_for_attempt",
  "_flatten_quarter_targets",
  "_materially_same_target_maps",
  "_extract_pass_retry_candidate_signature",
  "_extract_result_retry_signature",
  "_required_retry_levers_for_failed_quarters",
  "_bounded_tail",
  "_compact_retry_attempt_record",
  "_compact_retry_memory_snapshot",
  "_retry_validation_correction_grid",
  "_build_pass_retry_context",
  "_pre_solver_validation_failure_diagnostics",
  "_first_contract_product_missing_periods",
  "_compact_numeric_solver_contract_for_storage",
  "_compact_retry_memory_for_storage",
  "_realism_metric_series",
  "_lever_catalog_map",
  "_relative_move_limit",
  "_translate_realism_lever_adjustment",
  "_translate_realism_output_target",
  "_extract_controller_lever_catalog",
  "_lever_usage_guidance",
  "_canonical_writable_lever_value_metadata",
  "_build_writable_lever_review_catalog",
  "_model_input_with_controller_catalog",
  "_build_numeric_solver_feedback_payload",
  "_current_cycle_numeric_trace_summary",
  "_extract_numeric_solver_feedback_for_persistence",
  "_issue_quarter_gap_contributions",
  "_build_convergence_retry_focus_packet",
  "_controller_retry_heartbeat_from_snapshot",
  "_retry_scope_quarters",
  "_retry_scope_lever_ids",
  "_build_retry_scope_payload",
  "_subset_numeric_solver_contract",
  "_evaluate_retry_improvement",
  "_build_realism_milestone_context",
  "_finmo_quarter_row_map",
  "_business_world_contract",
  "_business_age_months_at_quarter",
  "_business_stage_family",
  "_stage_ramp_grid_rows",
  "_stage_ramp_row_for_quarter",
  "_stage_ramp_pair_growth_limit",
]


def _post_intake_gpt_contract_table_errors() -> List[str]:
  try:
    return list(post_intake_gpt_contract_errors() or [])
  except Exception as exc:
    return [f"post_intake_gpt_contract_lookup_unavailable: {exc}"]

def _post_intake_contract_schema(
  contract_name: str,
  *,
  field_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
  array_item_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
  business_naics: Optional[str] = None,
) -> Dict[str, Any]:
  errors = _post_intake_gpt_contract_table_errors()
  if errors:
    raise RuntimeError(
      "post_intake_gpt_contract_lookup_invalid: "
      + "; ".join(str(item) for item in errors[:10])
    )
  try:
    schema = post_intake_gpt_contract_openai_schema(
      contract_name=contract_name,
      field_schema_overrides=field_schema_overrides,
      array_item_schema_overrides=array_item_schema_overrides,
      business_naics=business_naics,
    )
  except Exception as exc:
    raise RuntimeError(
      f"post_intake_gpt_contract_schema_failed: contract={contract_name} detail={exc}"
    ) from exc
  return _openai_strict_json_schema(schema)

def _post_intake_contract_prompt_spec(contract_name: str) -> Dict[str, Any]:
  try:
    return post_intake_gpt_contract_prompt_field_spec(contract_name)
  except Exception as exc:
    raise RuntimeError(
      f"post_intake_gpt_contract_prompt_spec_failed: contract={contract_name} detail={exc}"
    ) from exc

def _normalize_post_intake_contract_payload(
  *,
  contract_name: str,
  payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  try:
    normalized = post_intake_gpt_contract_normalize_payload(
      contract_name=contract_name,
      payload=payload if isinstance(payload, dict) else {},
    )
  except Exception as exc:
    raise RuntimeError(
      f"post_intake_gpt_contract_normalization_failed: contract={contract_name} detail={exc}"
    ) from exc
  return normalized if isinstance(normalized, dict) else {}

def _post_intake_contract_payload_errors(
  *,
  contract_name: str,
  payload: Optional[Dict[str, Any]],
) -> List[str]:
  try:
    return list(
      post_intake_gpt_contract_payload_errors(
        contract_name=contract_name,
        payload=payload if isinstance(payload, dict) else {},
      )
      or []
    )
  except Exception as exc:
    return [
      f"post_intake_gpt_contract_payload_validation_failed: contract={contract_name} detail={exc}"
    ]

def _sequence_validation_subject_path(step_key: str) -> str:
  try:
    row = post_intake_process_sequence_step(step_key, required=True) or {}
  except Exception as exc:
    raise RuntimeError(
      f"post_intake_process_sequence_lookup_unavailable: step_key={step_key} detail={exc}"
    ) from exc
  path = str(row.get("validation_subject_path") or "").strip()
  if not path:
    raise RuntimeError(
      f"post_intake_process_sequence_validation_subject_missing: step_key={step_key}"
    )
  if ";" in path:
    raise RuntimeError(
      f"post_intake_process_sequence_validation_subject_not_machine_path: step_key={step_key} path={path!r}"
    )
  return path


def _stage_ramp_validation_subject_for_step(
  *,
  step_key: str,
  candidate: Dict[str, Any],
) -> Dict[str, Any]:
  path = _sequence_validation_subject_path(step_key)
  if path == "stage_ramp_contract":
    return copy.deepcopy(candidate)
  prefix = "stage_ramp_contract."
  if not path.startswith(prefix):
    raise RuntimeError(
      "post_intake_process_sequence_validation_subject_unsupported: "
      f"step_key={step_key} path={path!r} expected_prefix={prefix!r}"
    )
  remainder = path[len(prefix):].strip()
  if not remainder or "." in remainder:
    raise RuntimeError(
      "post_intake_process_sequence_validation_subject_unsupported_nested_path: "
      f"step_key={step_key} path={path!r}"
    )
  return {
    remainder: copy.deepcopy(candidate.get(remainder)),
    "rationale": copy.deepcopy(candidate.get("rationale")),
  }

def _maintenance_capex_percent_schema(*, business_naics: Optional[str] = None) -> Dict[str, Any]:
  return _post_intake_contract_schema("maintenance_capex_percent", business_naics=business_naics)

def _stage_ramp_contract_schema(*, business_naics: Optional[str] = None) -> Dict[str, Any]:
  # Module 3 v3 — overrides for cogs_target / cogs_max / marketing_max /
  # rd_max / ga_max / lease_max were deleted in v3 because those fields
  # are now NAICS-bound at the contract row level (see Module 3 Task 3.3).
  # Keeping a hardcoded `{"type": "number", "minimum": 0, "maximum": 1}`
  # override here would silently bypass the NAICS injection.
  rate_schema = {"type": "number", "minimum": 0, "maximum": 2.5}
  margin_schema = {"type": "number", "minimum": -1, "maximum": 1}
  return _post_intake_contract_schema(
    "stage_ramp_contract",
    business_naics=business_naics,
    field_schema_overrides={
      "q": {"type": "integer", "minimum": 1, "maximum": 20},
      "rev_target": rate_schema,
      "rev_max": rate_schema,
      "rev_spike_max": rate_schema,
      "max_util": {"type": "number", "minimum": 0, "maximum": 1},
      "ni_floor": margin_schema,
    },
  )

def _rate_has_two_decimal_precision(value: Any) -> bool:
  parsed = _safe_float(value)
  if parsed is None:
    return False
  return round(float(parsed), 2) == float(parsed)

def _normalize_stage_ramp_rate_for_validation(value: Any) -> Optional[float]:
  parsed = _safe_float(value)
  if parsed is None:
    return None
  return round(float(parsed), 2)


def _validate_stage_ramp_contract_payload(
  *,
  payload: Optional[Dict[str, Any]],
  expected_stage_family: str,
  business_stage: Optional[str] = None,
  planning_mode: Optional[str] = None,
  planning_mode_reason: Optional[str] = None,
  r_and_d_enabled: bool = True,
) -> Dict[str, Any]:
  candidate = _normalize_post_intake_contract_payload(
    contract_name="stage_ramp_contract",
    payload=payload if isinstance(payload, dict) else {},
  )
  contract_errors = _post_intake_contract_payload_errors(
    contract_name="stage_ramp_contract",
    payload=candidate,
  )
  if contract_errors:
    raise RuntimeError(
      "stage_ramp_contract_table_validation_failed: "
      + "; ".join(str(item) for item in contract_errors[:20])
    )
  stage_ramp_horizon_errors = list(
    post_intake_gpt_contract_horizon_errors(
      contract_name="stage_ramp_contract",
      payload=candidate,
    )
    or []
  )
  if stage_ramp_horizon_errors:
    raise RuntimeError(
      "stage_ramp_contract_horizon_violation: "
      + "; ".join(str(item) for item in stage_ramp_horizon_errors[:20])
    )
  errors: List[str] = []
  expected_family = str(expected_stage_family or "").strip().lower() or "operational"
  normalized_stage = str(business_stage or "").strip().lower()
  policy = stage_planning_ramp_policy(
    stage_family=expected_family,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    business_stage=business_stage,
  )
  normalized_mode = str(policy.get("planning_mode") or planning_mode or "").strip().lower()
  normalized_mode_reason = str(policy.get("planning_mode_reason") or planning_mode_reason or "").strip().lower()
  explicit_distress_context = bool(policy.get("explicit_distress_context"))
  validator_rules = policy.get("validator_rules") if isinstance(policy.get("validator_rules"), dict) else {}
  allowed_postures = {
    str(item or "").strip().lower()
    for item in (policy.get("profitability_postures") or [])
    if str(item or "").strip()
  } or {"loss_allowed", "improving_losses", "near_breakeven", "positive"}
  stage_family = str(candidate.get("stage_family") or "").strip().lower()
  if stage_family != expected_family:
    errors.append(f"stage_family must be {expected_family}; received {stage_family or 'missing'}")

  utilization_high_watermark_raw = _safe_float(candidate.get("utilization_high_watermark"))
  utilization_high_watermark = _normalize_stage_ramp_rate_for_validation(
    candidate.get("utilization_high_watermark")
  )
  if (
    utilization_high_watermark_raw is None
    or float(utilization_high_watermark_raw) < 0.5
    or float(utilization_high_watermark_raw) > 0.98
  ):
    errors.append(
      f"utilization_high_watermark must be between 0.50 and 0.98; received {candidate.get('utilization_high_watermark')!r}"
    )

  raw_grid = candidate.get("quarter_ramp_grid")
  horizon_count = _contract_forecast_quarter_count("stage_ramp_contract")
  if not isinstance(raw_grid, list):
    errors.append(f"quarter_ramp_grid must be a {horizon_count}-row array")
    raw_grid = []
  if len(raw_grid) != horizon_count:
    errors.append(f"quarter_ramp_grid must contain exactly {horizon_count} rows; received {len(raw_grid)}")
  rows_by_quarter: Dict[int, Dict[str, Any]] = {}
  normalized_rows: List[Dict[str, Any]] = []
  ramp_field_aliases = {
    "quarter_index": "q",
    "revenue_qoq_target": "rev_target",
    "revenue_qoq_max": "rev_max",
    "revenue_qoq_spike_max": "rev_spike_max",
    "utilization_cap": "max_util",
    "cogs_percent_of_revenue_target": "cogs_target",
    "cogs_percent_of_revenue_max": "cogs_max",
    "marketing_percent_of_revenue_max": "marketing_max",
    "rd_percent_of_revenue_max": "rd_max",
    "g_and_a_percent_of_revenue_max": "ga_max",
    "lease_percent_of_revenue_max": "lease_max",
    "net_income_margin_floor": "ni_floor",
  }
  for item in raw_grid:
    if not isinstance(item, dict):
      errors.append("quarter_ramp_grid entries must be objects")
      continue
    quarter_index = int(_safe_float(item.get(ramp_field_aliases["quarter_index"])) or 0)
    if quarter_index < 1 or quarter_index > horizon_count:
      errors.append(f"quarter_ramp_grid has invalid q {item.get('q')!r}")
      continue
    if quarter_index in rows_by_quarter:
      errors.append(f"quarter_ramp_grid contains duplicate quarter_index {quarter_index}")
      continue
    numeric_fields = [
      "revenue_qoq_target",
      "revenue_qoq_max",
      "revenue_qoq_spike_max",
      "utilization_cap",
      "cogs_percent_of_revenue_target",
      "cogs_percent_of_revenue_max",
      "marketing_percent_of_revenue_max",
      "rd_percent_of_revenue_max",
      "g_and_a_percent_of_revenue_max",
      "lease_percent_of_revenue_max",
      "net_income_margin_floor",
    ]
    parsed: Dict[str, float] = {}
    for field in numeric_fields:
      value = _safe_float(item.get(ramp_field_aliases[field]))
      if value is None:
        errors.append(f"quarter_ramp_grid Q{quarter_index} missing {ramp_field_aliases[field]}")
        continue
      value = float(value)
      if field == "net_income_margin_floor":
        default_lower_bound = -1.0
        default_upper_bound = 1.0
      elif field == "utilization_cap" or field.endswith("_percent_of_revenue_max") or field.endswith("_percent_of_revenue_target"):
        default_lower_bound = 0.0
        default_upper_bound = 1.0
      else:
        default_lower_bound = 0.0
        default_upper_bound = 2.5
      lower_bound, upper_bound = _contract_numeric_bounds(
        contract_name="stage_ramp_contract",
        field_path=f"quarter_ramp_grid[].{ramp_field_aliases[field]}",
        default_min=default_lower_bound,
        default_max=default_upper_bound,
      )
      if value < lower_bound or value > upper_bound:
        errors.append(
          f"quarter_ramp_grid Q{quarter_index} {field} must be between {lower_bound} and {upper_bound}; received {value}"
        )
      value = round(value, 2)
      parsed[field] = value
    revenue_spike_allowed = bool(item.get("rev_spike"))
    if parsed.get("revenue_qoq_target", 0.0) > parsed.get("revenue_qoq_max", 0.0) + 1e-9:
      parsed["revenue_qoq_max"] = parsed.get("revenue_qoq_target", 0.0)
    if not revenue_spike_allowed and parsed.get("revenue_qoq_spike_max", 0.0) < parsed.get("revenue_qoq_max", 0.0) - 1e-9:
      parsed["revenue_qoq_spike_max"] = parsed.get("revenue_qoq_max", 0.0)
    if parsed.get("cogs_percent_of_revenue_target", 0.0) > parsed.get("cogs_percent_of_revenue_max", 0.0) + 1e-9:
      parsed["cogs_percent_of_revenue_max"] = parsed.get("cogs_percent_of_revenue_target", 0.0)
    if revenue_spike_allowed and parsed.get("revenue_qoq_spike_max", 0.0) < parsed.get("revenue_qoq_max", 0.0) - 1e-9:
      errors.append(f"quarter_ramp_grid Q{quarter_index} revenue_qoq_spike_max must be >= revenue_qoq_max")
    if not bool(r_and_d_enabled):
      _rd_max_received = float(parsed.get("rd_percent_of_revenue_max") or 0.0)
      if abs(_rd_max_received) > 1e-9:
        # Contract invariant: when R&D is disabled by applicability, rd_max
        # must be 0.0. GPT may return a tiny non-zero drift (e.g. 0.01)
        # intending "rounds to zero." Coerce to the contract value here —
        # the parser layer enforces the architectural invariant regardless
        # of GPT's exact output. Log so cohort-level GPT-drift is visible.
        try:
          logger.warning(
            "stage_ramp_contract_rd_max_coerced_to_zero: Q%s received %s; "
            "coerced to 0.0 (R&D disabled by applicability)",
            quarter_index, _rd_max_received,
          )
        except Exception:
          pass
        parsed["rd_percent_of_revenue_max"] = 0.0
    profitability_posture = str(item.get("posture") or "").strip().lower()
    if profitability_posture not in {"loss_allowed", "improving_losses", "near_breakeven", "positive"}:
      errors.append(
        f"quarter_ramp_grid Q{quarter_index} profitability_posture must be loss_allowed, improving_losses, near_breakeven, or positive"
      )
    elif profitability_posture not in allowed_postures:
      errors.append(
        f"quarter_ramp_grid Q{quarter_index} profitability_posture {profitability_posture!r} conflicts with stage/planning policy "
        f"{policy.get('policy_version')}: allowed={sorted(allowed_postures)}"
      )
    # Root-disease fix: operational-profitability requirements apply ONLY to
    # operational/mature stages. A startup/early (e.g. pre-revenue) business
    # running early losses is CORRECT, not a violation -- the stage is reality,
    # and a planning-mode rule (operational_requires_nonnegative_from_q1) must
    # NOT override it and crash a valid loss-tolerant startup ramp. Universal.
    if (
      expected_family in ("operational", "mature")
      and bool(validator_rules.get("operational_requires_nonnegative_from_q1"))
    ):
      if profitability_posture not in allowed_postures:
        errors.append(
          f"quarter_ramp_grid Q{quarter_index} operational stage cannot use startup loss posture {profitability_posture!r} "
          "unless planning mode explicitly indicates distress or turnaround."
        )
      if float(parsed.get("net_income_margin_floor") or 0.0) < 0.0:
        errors.append(
          f"quarter_ramp_grid Q{quarter_index} operational stage requires ni_floor >= 0.00; "
          f"received {parsed.get('net_income_margin_floor')}"
        )
    loss_allowed_latest = _safe_float(validator_rules.get("loss_allowed_latest_quarter"))
    if loss_allowed_latest is not None and quarter_index > int(loss_allowed_latest):
      if profitability_posture == "loss_allowed":
        errors.append(
          f"quarter_ramp_grid Q{quarter_index} stage/planning policy does not allow loss_allowed after Q{int(loss_allowed_latest)}."
        )
    normalized_row = {
      "quarter_index": quarter_index,
      "prior_quarter_index": quarter_index - 1 if quarter_index > 1 else 0,
      "revenue_qoq_target": round(float(parsed.get("revenue_qoq_target") or 0.0), 2),
      "revenue_qoq_max": round(float(parsed.get("revenue_qoq_max") or 0.0), 2),
      "revenue_qoq_spike_allowed": revenue_spike_allowed,
      "revenue_qoq_spike_max": round(float(parsed.get("revenue_qoq_spike_max") or 0.0), 2),
      "utilization_cap": round(float(parsed.get("utilization_cap") or 0.0), 2),
      "cogs_percent_of_revenue_target": round(float(parsed.get("cogs_percent_of_revenue_target") or 0.0), 2),
      "cogs_percent_of_revenue_max": round(float(parsed.get("cogs_percent_of_revenue_max") or 0.0), 2),
      "marketing_percent_of_revenue_max": round(float(parsed.get("marketing_percent_of_revenue_max") or 0.0), 2),
      "rd_percent_of_revenue_max": round(float(parsed.get("rd_percent_of_revenue_max") or 0.0), 2),
      "g_and_a_percent_of_revenue_max": round(float(parsed.get("g_and_a_percent_of_revenue_max") or 0.0), 2),
      "lease_percent_of_revenue_max": round(float(parsed.get("lease_percent_of_revenue_max") or 0.0), 2),
      "net_income_margin_floor": round(float(parsed.get("net_income_margin_floor") or 0.0), 2),
      "profitability_posture": profitability_posture,
    }
    rows_by_quarter[quarter_index] = normalized_row
    normalized_rows.append(normalized_row)

  missing_quarters = [quarter for quarter in range(1, horizon_count + 1) if quarter not in rows_by_quarter]
  if missing_quarters:
    errors.append(f"quarter_ramp_grid missing required quarter rows {missing_quarters}")

  normalized_rows = [rows_by_quarter[quarter] for quarter in sorted(rows_by_quarter)]
  prior_utilization_cap: Optional[float] = None
  prior_margin_floor: Optional[float] = None
  for row in normalized_rows:
    quarter_index = int(row.get("quarter_index") or 0)
    utilization_cap = float(row.get("utilization_cap") or 0.0)
    if prior_utilization_cap is not None and utilization_cap + 1e-9 < prior_utilization_cap:
      errors.append("quarter_ramp_grid utilization_cap must be non-decreasing by quarter")
    prior_utilization_cap = utilization_cap
    if quarter_index > 1:
      allowed_util_growth = (
        float(row.get("revenue_qoq_spike_max") or 0.0)
        if bool(row.get("revenue_qoq_spike_allowed"))
        else float(row.get("revenue_qoq_max") or 0.0)
      )
      previous_row = rows_by_quarter.get(quarter_index - 1) or {}
      previous_utilization_cap = float(previous_row.get("utilization_cap") or 0.0)
      if previous_utilization_cap > 0.0:
        cap_growth = (utilization_cap - previous_utilization_cap) / previous_utilization_cap
        if cap_growth > allowed_util_growth + 1e-9:
          errors.append(
            "quarter_ramp_grid utilization_cap implies revenue ramp above allowed row growth: "
            f"Q{quarter_index - 1}->Q{quarter_index} utilization_cap_growth={round(cap_growth, 6)} "
            f"allowed_growth={round(allowed_util_growth, 6)}"
          )
    margin_floor = float(row.get("net_income_margin_floor") or 0.0)
    if quarter_index >= 5 and prior_margin_floor is not None and margin_floor + 0.02 < prior_margin_floor:
      errors.append(
        "quarter_ramp_grid net_income_margin_floor must generally improve from Q5 onward; "
        f"Q{quarter_index - 1}->{quarter_index} declined from {prior_margin_floor} to {margin_floor}"
      )
    q10_min_floor = _safe_float(validator_rules.get("q10_min_net_income_margin_floor"))
    if q10_min_floor is None:
      q10_min_floor = -0.02
    if quarter_index == 10 and margin_floor < float(q10_min_floor):
      errors.append(
        f"quarter_ramp_grid Q10 net_income_margin_floor must be near breakeven (>= {q10_min_floor}); received {margin_floor}"
      )
    q11_min_floor = _safe_float(validator_rules.get("q11_to_q20_min_net_income_margin_floor"))
    if q11_min_floor is None:
      q11_min_floor = 0.0
    if quarter_index >= 11 and margin_floor < float(q11_min_floor):
      errors.append(
        f"quarter_ramp_grid Q{quarter_index} net_income_margin_floor must be >= {q11_min_floor} after Q10; received {margin_floor}"
      )
    q5_floor = _safe_float(validator_rules.get("q5_to_q20_min_net_income_margin_floor"))
    if q5_floor is not None and quarter_index >= 5 and margin_floor < float(q5_floor):
      errors.append(
        f"quarter_ramp_grid Q{quarter_index} stage/planning policy requires ni_floor >= {q5_floor} after Q4; received {margin_floor}"
      )
    if (
      expected_family in ("operational", "mature")
      and bool(validator_rules.get("operational_requires_positive_from_q5"))
      and quarter_index >= 5
    ):
      posture = str(row.get("profitability_posture") or "").strip().lower()
      if posture != "positive":
        errors.append(
          f"quarter_ramp_grid Q{quarter_index} operational stage requires positive profitability posture after Q4; received {posture or 'missing'}"
        )
    if quarter_index >= 5:
      prior_margin_floor = margin_floor

  rationale = str(candidate.get("rationale") or "").strip()
  if not rationale:
    errors.append("rationale is required so diagnostics can explain the ramp selection")

  if errors:
    raise RuntimeError("stage_ramp_contract_invalid: " + "; ".join(errors))

  live_rows = [row for row in normalized_rows if int(row.get("quarter_index") or 0) > 1]
  revenue_targets = [float(row.get("revenue_qoq_target") or 0.0) for row in live_rows]
  revenue_maxes = [float(row.get("revenue_qoq_max") or 0.0) for row in live_rows]
  revenue_spikes = [
    float(row.get("revenue_qoq_spike_max") or 0.0)
    for row in live_rows
    if bool(row.get("revenue_qoq_spike_allowed"))
  ]
  revenue_spike_window = [
    int(row.get("prior_quarter_index") or 0)
    for row in live_rows
    if bool(row.get("revenue_qoq_spike_allowed")) and int(row.get("prior_quarter_index") or 0) >= 1
  ]
  utilization_caps = {
    int(row.get("quarter_index") or 0): round(float(row.get("utilization_cap") or 0.0), 2)
    for row in normalized_rows
  }
  cost_cap_keys = [
    "cogs_percent_of_revenue_max",
    "marketing_percent_of_revenue_max",
    "rd_percent_of_revenue_max",
    "g_and_a_percent_of_revenue_max",
    "lease_percent_of_revenue_max",
  ]
  cost_cap_summary = {
    key: round(max([float(row.get(key) or 0.0) for row in normalized_rows] or [0.0]), 2)
    for key in cost_cap_keys
  }
  profitability_floor_by_quarter = {
    int(row.get("quarter_index") or 0): round(float(row.get("net_income_margin_floor") or 0.0), 2)
    for row in normalized_rows
  }
  contract = {
    "contract_version": "stage_maturity_grid_contract_gpt_v2",
    "decision_source": "gpt_pre_convergence",
    "stage_family": expected_family,
    "quarter_ramp_grid": copy.deepcopy(normalized_rows),
    "revenue_qoq_growth_target_min": round(min(revenue_targets or [0.0]), 2),
    "revenue_qoq_growth_target_max": round(max(revenue_maxes or [0.0]), 2),
    "revenue_qoq_default": round(sum(revenue_targets) / max(len(revenue_targets), 1), 2),
    "revenue_qoq_max_spike": round(max(revenue_spikes or revenue_maxes or [0.0]), 2),
    "revenue_spike_window_quarters": sorted(revenue_spike_window),
    "utilization_launch_caps_by_quarter": utilization_caps,
    "cost_maturity_caps": cost_cap_summary,
    "profitability_floor_by_quarter": profitability_floor_by_quarter,
    "max_spike_count": len(revenue_spike_window),
    "utilization_high_watermark": round(float(utilization_high_watermark or 0.0), 2),
    "capacity_support_rule": (
      "Growth above the ordinary stage band must be supported by utilization ramp while utilization is below the high-watermark "
      "or by structural capacity expansion. Once utilization is already above the high-watermark, further growth must be capacity-driven."
    ),
    "composite_revenue_formula": "sum(Capacity * Unit Price * Utilization) across revenue products",
    "composite_revenue_ramp_is_binding": True,
    "cost_maturity_ramp_is_binding": True,
    "profitability_maturity_floor_is_binding": True,
    "quarter_grid_is_binding": True,
    "deterministic_validation": True,
    "no_unchecked_growth": True,
    "rationale": rationale,
    "stage_profitability_policy": {
      **copy.deepcopy(policy),
      "business_stage": normalized_stage,
      "planning_mode": normalized_mode,
      "planning_mode_reason": normalized_mode_reason,
      "explicit_distress_context": explicit_distress_context,
    },
  }
  contract["quarter_pair_scope"] = [f"Q{idx}->Q{idx + 1}" for idx in range(1, 20)]
  return contract

def _revenue_catalog_snapshot_for_starting_ppe(ops_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  ops = ops_json if isinstance(ops_json, dict) else {}
  candidates: List[Any] = []
  for key in (
    "revenue_products",
    "revenue_model",
    "products",
    "lines_of_business",
    "lobs",
  ):
    value = ops.get(key)
    if isinstance(value, list):
      candidates.extend(value)
    elif isinstance(value, dict):
      candidates.append(value)
  snapshot: List[Dict[str, Any]] = []
  for item in candidates[:6]:
    if not isinstance(item, dict):
      continue
    entry = {
      key: item.get(key)
      for key in (
        "lob",
        "line_of_business",
        "product",
        "unit_name",
        "capacity",
        "unit_price",
        "utilization",
        "capacity_driver",
        "fulfillment_model",
      )
      if item.get(key) not in {None, ""}
    }
    if entry:
      snapshot.append(entry)
  return snapshot


def _payroll_people_staffing_context(people_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  people = people_json if isinstance(people_json, dict) else {}
  rows: List[Dict[str, Any]] = []
  for group_name in ("people", "inferred_roles"):
    raw_items = people.get(group_name)
    if not isinstance(raw_items, list):
      continue
    for item in raw_items:
      if not isinstance(item, dict):
        continue
      role_title = str(item.get("role_title") or item.get("full_name") or "").strip()
      if not role_title:
        continue
      rows.append(
        {
          "source_group": group_name,
          "role_title": role_title,
          "annual_wage": int(round(float(_safe_float(item.get("annual_wage")) or 0.0))),
          "wage_source": str(item.get("wage_source") or "").strip(),
          "months_until_hire": (
            int(round(float(_safe_float(item.get("months_until_hire")) or 0.0)))
            if item.get("months_until_hire") is not None
            else None
          ),
        }
      )
  return {
    "business_naics_6": str(people.get("business_naics_6") or "").strip(),
    "known_staffing_roles": rows[:24],
  }


# iter 19 Stage 1 (F1) — conservative fallback per doctrine.md §2.
# When the NAICS cascade has no coverage for the business, fall back to
# this value instead of raising. 0.05 (= 5% of PPE annually) is a
# defensible mid-band default across light-industrial / professional-
# services NAICS codes. The previous behavior (RuntimeError) failed two
# of the 27-draft sweep cases (Anderson & Blake, CareFirst) on a
# cohort-coverage miss that has no judgment content GPT could have
# resolved.
_MAINTENANCE_RATE_CONSERVATIVE_DEFAULT: float = 0.05
_MAINTENANCE_RATE_MIN: float = 0.02
_MAINTENANCE_RATE_MAX: float = 0.15


def _derive_maintenance_capex_percent_from_naics(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Pure-Python maintenance_rate resolver. Per doctrine.md §3 Pattern 2
  (Python proposes structure), GPT was dropped for this field in
  Module 5 Task 5.1; iter 19 Stage 1 (F1) adds a conservative-default
  fallback so cohort-coverage misses do not hard-fail the run.

  Returns the same payload shape the legacy call returned (with
  ``decision_source`` annotating which path produced the value).
  """
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  client_reported_ppe = int(round(max(0.0, float(_safe_float(financials.get("initial_assets")) or 0.0))))

  business_naics_6 = "".join(
    ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()
  )

  band: Optional[Dict[str, Any]] = None
  decision_source = "naics_cascade"
  fallback_reason: Optional[str] = None

  if not business_naics_6:
    fallback_reason = "naics_missing"
  else:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    band_candidate = post_intake_industry_baseline_for_naics(
      metric_key="maintenance_capex_percent_of_revenue",
      naics_6=business_naics_6,
    )
    if not isinstance(band_candidate, dict) or band_candidate.get("trust_flag") == "no_coverage":
      fallback_reason = "naics_no_coverage"
    else:
      band = band_candidate

  if band is not None:
    target = band.get("benchmark_target")
    if target is None:
      target = band.get("benchmark_min") or band.get("benchmark_max")
    if target is None:
      fallback_reason = "band_missing_target"
    elif float(target) <= 0.0:
      fallback_reason = "band_nonpositive"

  if fallback_reason is not None:
    target = _MAINTENANCE_RATE_CONSERVATIVE_DEFAULT
    decision_source = "conservative_default"
    band = band or {}

  raw_rate = float(target)
  clamped_rate = min(_MAINTENANCE_RATE_MAX, max(_MAINTENANCE_RATE_MIN, raw_rate))
  maintenance_capex_percent = round(clamped_rate * 100.0, 2)

  return {
    "contract_version": "maintenance_capex_percent_decision_v2",
    "decision_source": decision_source,
    "starting_ppe": client_reported_ppe,
    "starting_ppe_source": "authoritative_client_balance_sheet",
    "maintenance_capex_percent": maintenance_capex_percent,
    "maintenance_rate": round(clamped_rate, 6),
    "fallback_reason": fallback_reason,
    "naics_provenance": {
      "metric_key": band.get("metric_key") if isinstance(band, dict) else None,
      "naics_code_used": band.get("naics_code_used") if isinstance(band, dict) else None,
      "naics_level_used": band.get("naics_level_used") if isinstance(band, dict) else None,
      "data_source": band.get("data_source") if isinstance(band, dict) else None,
      "confidence_tier": band.get("confidence_tier") if isinstance(band, dict) else None,
      "trust_flag": band.get("trust_flag") if isinstance(band, dict) else None,
      "sample_size": band.get("sample_size") if isinstance(band, dict) else None,
    },
  }


# Module 5 Task 5.1 — `_estimate_maintenance_capex_percent_with_gpt` was
# DELETED entirely. The NAICS resolver gives us the same value (tighter,
# industry-typical) without a network call. The deterministic replacement
# is `_derive_maintenance_capex_percent_from_naics` above. Call sites in
# `post_intake_initial_grid/runner.py` and `intake_consult.py` were
# updated to reference the new function.

def _sequence_gpt_timeout_seconds(
  *,
  step_key: str,
  env_name: str,
  fallback: float,
  minimum: float,
  maximum: float,
) -> float:
  raw = str(os.getenv(env_name) or "").strip()
  if raw:
    try:
      return max(minimum, min(maximum, float(raw)))
    except Exception:
      pass
  try:
    step = post_intake_process_sequence_step(step_key, required=False)
    value = float((step or {}).get("timeout_seconds") or 0.0)
    if value > 0:
      return max(minimum, min(maximum, value))
  except Exception:
    pass
  return fallback


def _stage_ramp_gpt_timeout_seconds() -> float:
  return _sequence_gpt_timeout_seconds(
    step_key="stage_ramp_contract",
    env_name="STAGE_RAMP_GPT_TIMEOUT_SECONDS",
    fallback=60.0,
    minimum=15.0,
    maximum=90.0,
  )

def _r_and_d_applicability_timeout_seconds() -> float:
  return _sequence_gpt_timeout_seconds(
    step_key="r_and_d_applicability",
    env_name="R_AND_D_APPLICABILITY_GPT_TIMEOUT_SECONDS",
    fallback=20.0,
    minimum=10.0,
    maximum=45.0,
  )

def _balance_sheet_contextual_seed_timeout_seconds() -> float:
  return _sequence_gpt_timeout_seconds(
    step_key="balance_sheet_contextual_seed",
    env_name="BALANCE_SHEET_CONTEXTUAL_SEED_GPT_TIMEOUT_SECONDS",
    fallback=30.0,
    minimum=10.0,
    maximum=60.0,
  )

def _r_and_d_applicability_schema() -> Dict[str, Any]:
  return _post_intake_contract_schema(
    "r_and_d_applicability",
    field_schema_overrides={
      "rationale": {"type": "string", "minLength": 10, "maxLength": 600},
    },
  )

def _balance_sheet_contextual_seed_schema() -> Dict[str, Any]:
  return _post_intake_contract_schema(
    "balance_sheet_contextual_seed",
    field_schema_overrides={
      "rationale": {"type": "string", "minLength": 10, "maxLength": 1000},
      "balance_sheet_seed_grid[].rationale": {"type": "string", "minLength": 3, "maxLength": 600},
    },
  )

def _validate_balance_sheet_contextual_seed_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  candidate = _normalize_post_intake_contract_payload(
    contract_name="balance_sheet_contextual_seed",
    payload=payload if isinstance(payload, dict) else {},
  )
  contract_errors = _post_intake_contract_payload_errors(
    contract_name="balance_sheet_contextual_seed",
    payload=candidate,
  )
  if contract_errors:
    raise RuntimeError(
      "balance_sheet_contextual_seed_contract_invalid: "
      + "; ".join(str(item) for item in contract_errors[:10])
    )
  return validate_balance_sheet_contextual_seed_payload(candidate)

def _validate_r_and_d_applicability_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  candidate = _normalize_post_intake_contract_payload(
    contract_name="r_and_d_applicability",
    payload=payload if isinstance(payload, dict) else {},
  )
  contract_errors = _post_intake_contract_payload_errors(
    contract_name="r_and_d_applicability",
    payload=candidate,
  )
  if contract_errors:
    raise RuntimeError(
      "r_and_d_applicability_contract_invalid: "
      + "; ".join(str(item) for item in contract_errors[:10])
    )
  if not isinstance(candidate.get("r_and_d_enabled"), bool):
    raise RuntimeError(
      "r_and_d_applicability_invalid: r_and_d_enabled must be an explicit boolean before forecast."
    )
  rationale = str(candidate.get("rationale") or "").strip()
  if len(rationale) < 10:
    raise RuntimeError("r_and_d_applicability_invalid: rationale is required.")
  return {
    "contract_version": R_AND_D_APPLICABILITY_POLICY_VERSION,
    "decision_source": "gpt_pre_forecast",
    "r_and_d_enabled": bool(candidate.get("r_and_d_enabled")),
    "rationale": rationale,
  }

def _r_and_d_policy_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  policies = payload.get("derived_driver_policies") if isinstance(payload.get("derived_driver_policies"), dict) else {}
  policy = policies.get(R_AND_D_APPLICABILITY_LEVER_ID) if isinstance(policies.get(R_AND_D_APPLICABILITY_LEVER_ID), dict) else {}
  return policy if isinstance(policy, dict) else {}

def _r_and_d_enabled_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> bool:
  policy = _r_and_d_policy_from_model_input(model_input_json)
  enabled = policy.get("r_and_d_enabled")
  return bool(enabled) if isinstance(enabled, bool) else True

def _model_input_r_and_d_live_values(model_input_json: Optional[Dict[str, Any]]) -> List[float]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  for row in (sections.get("expenses") or []):
    if not isinstance(row, dict):
      continue
    if str(row.get("label") or "").strip() != "Research & Development":
      continue
    values = list(row.get("values") or [])
    return [float(_safe_float(value) or 0.0) for value in values[1:]]
  return []

def _assert_r_and_d_applicability_policy_applied(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]] = None,
  planning_result: Optional[Dict[str, Any]] = None,
  stage: str = "",
) -> None:
  policy = _r_and_d_policy_from_model_input(model_input_json)
  if not policy or not isinstance(policy.get("r_and_d_enabled"), bool):
    raise RuntimeError(
      "r_and_d_applicability_missing_before_forecast: GPT R&D applicability decision must be applied before forecast/grid."
    )
  if bool(policy.get("r_and_d_enabled")):
    return

  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  r_and_d_row = next(
    (
      row for row in (sections.get("expenses") or [])
      if isinstance(row, dict) and str(row.get("label") or "").strip() == "Research & Development"
    ),
    None,
  )
  if not isinstance(r_and_d_row, dict):
    raise RuntimeError(
      f"r_and_d_disabled_row_missing: R&D disabled but model_input row is missing at {stage or 'unknown_stage'}."
    )
  if bool(r_and_d_row.get("controller_write")):
    raise RuntimeError(
      f"r_and_d_disabled_still_controller_writable: R&D disabled but row remains editable at {stage or 'unknown_stage'}."
    )
  live_values = _model_input_r_and_d_live_values(payload)
  leaking_values = [
    {"quarter_index": idx, "value": value}
    for idx, value in enumerate(live_values, start=1)
    if abs(float(value or 0.0)) > 1e-9
  ]
  if leaking_values:
    raise RuntimeError(
      "r_and_d_disabled_live_value_leakage: "
      + json.dumps({"stage": stage, "leaking_values": leaking_values[:20]}, ensure_ascii=False)
    )
  controller_levers = payload.get("controller_write_levers") if isinstance(payload.get("controller_write_levers"), list) else []
  if any(
    isinstance(item, dict) and str(item.get("lever_id") or "").strip() == R_AND_D_APPLICABILITY_LEVER_ID
    for item in controller_levers
  ):
    raise RuntimeError(
      f"r_and_d_disabled_lever_catalog_leakage: controller_write_levers still includes R&D at {stage or 'unknown_stage'}."
    )
  lever_catalog = payload.get("lever_catalog") if isinstance(payload.get("lever_catalog"), dict) else {}
  if R_AND_D_APPLICABILITY_LEVER_ID in lever_catalog:
    raise RuntimeError(
      f"r_and_d_disabled_lever_catalog_leakage: lever_catalog still includes R&D at {stage or 'unknown_stage'}."
    )
  if isinstance(finmo_json, dict):
    leaked_finmo = [
      {
        "quarter_index": int(_safe_float(row.get("quarter_index")) or 0),
        "research_and_development": float(_safe_float(row.get("research_and_development")) or 0.0),
      }
      for row in (finmo_json.get("quarter_rows") or [])
      if isinstance(row, dict) and abs(float(_safe_float(row.get("research_and_development")) or 0.0)) > 1.0
    ]
    if leaked_finmo:
      raise RuntimeError(
        "r_and_d_disabled_finmo_leakage: "
        + json.dumps({"stage": stage, "leaking_finmo_rows": leaked_finmo[:20]}, ensure_ascii=False)
      )
  if isinstance(planning_result, dict):
    grid_rows = []
    metadata = planning_result.get("metadata") if isinstance(planning_result.get("metadata"), dict) else {}
    if isinstance(metadata.get("requested_row_ids"), list):
      grid_rows.extend(metadata.get("requested_row_ids") or [])
    grid_json = planning_result.get("grid_json") if isinstance(planning_result.get("grid_json"), dict) else {}
    for row in (grid_json.get("rows") or []):
      if isinstance(row, dict):
        grid_rows.append(str(row.get("row_id") or row.get("label") or ""))
    leaked_rows = [str(item) for item in grid_rows if "Research & Development" in str(item)]
    if leaked_rows:
      raise RuntimeError(
        "r_and_d_disabled_grid_leakage: "
        + json.dumps({"stage": stage, "leaked_rows": leaked_rows[:20]}, ensure_ascii=False)
      )

def _derive_r_and_d_applicability_from_naics(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """Phase 9 P3.10 — universal-app: there is no NAICS-2 R&D applicability
  branch. The function is retained as a deprecated no-op for backwards
  compatibility with external callers; always returns None so callers
  fall through to the universal default.
  """
  return None


def _estimate_r_and_d_applicability_with_gpt(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Phase 9 P3.10 — universal-app: R&D is a regular driver. Intake or
  cohort baselines drive the value; the realism band + GPT exhaustion
  handler handle out-of-band cases the same way they handle every other
  expense lever. There is no separate "is R&D applicable" decision.

  This function returns a constant `r_and_d_enabled=True` decision so
  the existing contract pipeline (validators, finmo_bridge policy
  applier, etc.) keeps a uniform shape without consulting GPT or any
  hardcoded archetype table.
  """
  return {
    "contract_version": "r_and_d_applicability_universal_v3",
    "decision_source": "universal_post_phase_9_p3_10",
    "r_and_d_enabled": True,
    "rationale": (
      "R&D is a universal driver post Phase 9 P3.10 NexGen iter 2. "
      "Intake / cohort baselines drive R&D %; the realism band + GPT "
      "exhaustion handler engage on out-of-band values the same way "
      "they engage for every other expense lever."
    ),
  }

def _balance_sheet_seed_candidate_prompt_rows() -> List[Dict[str, Any]]:
  prompt_rows: List[Dict[str, Any]] = []
  for row in balance_sheet_contextual_seed_candidate_rows():
    prompt_rows.append(
      {
        "lever_id": str(row.get("lever_id") or "").strip(),
        "target_driver": str(row.get("target_driver") or "").strip(),
        "value_kind": str(row.get("value_kind") or "").strip().lower(),
        "input_semantics": str(row.get("input_semantics") or "").strip().lower(),
        "business_applicability_key": str(row.get("business_applicability_key") or "").strip().lower(),
        "minimum_live_value": _safe_float(row.get("minimum_live_value")),
        "maximum_live_value": _safe_float(row.get("maximum_live_value")),
        "zero_allowed_reason_key": str(row.get("zero_allowed_reason_key") or "").strip().lower(),
        "applicability_positive_tokens": list(row.get("applicability_positive_tokens") or []),
        "applicability_negative_tokens": list(row.get("applicability_negative_tokens") or []),
        "notes": str(row.get("notes") or "").strip(),
      }
    )
  return prompt_rows

def _estimate_balance_sheet_contextual_seed_with_gpt(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Module 5 Task 5.3 — Python proposes, GPT critiques.

  Workflow:
    1. `propose_balance_sheet_contextual_seed_payload` builds the full seed
       grid deterministically from NAICS + intake anchors + applicability.
    2. The OpenAI critic receives the proposal and may return amendments
       to specific rows (e.g., flip applicable=true for a retail business
       that runs a membership program).
    3. Python applies amendments via the shared critique contract.
    4. The amended payload is normalized via the existing validator so
       downstream `apply_balance_sheet_contextual_seed_to_model_input` is
       unchanged.
    5. When GPT fails (no key, timeout, garbage response), Python's
       proposal is the safety floor — every value already has data
       provenance, so the floor is always reasonable.

  This replaces the from-scratch GPT decision with a focused critique
  step. Latency drops because the prompt is much smaller; variance drops
  because GPT can only edit, not invent.
  """
  # P3.33 Phase 3 step 3d: GPT critic deleted. Per the directive's
  # "delete the three pre_convergence scalar GPT executor functions"
  # cleanup, this entry point is now proposer-only. The amalgamated
  # session (step 5) authors balance-sheet seed amendments via
  # post_intake_amalgamated.tools.set_capex_rd_balance_seed when it
  # wants to revise the deterministic proposal; until then the
  # proposer stands as the safety floor (it already has full data
  # provenance per row).
  from client_intake_and_finmo.post_intake_balance_sheet.contextual_seed import (  # type: ignore
    propose_balance_sheet_contextual_seed_payload,
  )
  from client_intake_and_finmo.post_intake_critique import (  # type: ignore
    proposal_only_response,
  )
  proposal = propose_balance_sheet_contextual_seed_payload(
    business_facts=business_facts if isinstance(business_facts, dict) else {},
    ops_json=ops_json if isinstance(ops_json, dict) else {},
    financials_json=financials_json if isinstance(financials_json, dict) else {},
    financials_year1_json=financials_year1_json if isinstance(financials_year1_json, dict) else {},
    model_input_json=model_input_json,
  )
  response = proposal_only_response(reason="pre_convergence_gpt_critic_deleted_step_3d")
  return _finalize_balance_sheet_seed_with_critique(
    proposal=proposal, response=response, raw_openai_response=None,
  )

def _balance_sheet_seed_contract_row_fields() -> Tuple[str, ...]:
  """Grid-row field whitelist for the balance_sheet_contextual_seed contract.

  P3.41 NexGen E2E iter 7 Bug 2 fix: previous implementation referenced a
  module-level constant ``_BALANCE_SHEET_SEED_CONTRACT_ROW_FIELDS`` that
  was never defined (NameError on every clean E2E). Derived here from the
  authoritative contract schema instead of a hand-maintained parallel
  list, so the whitelist cannot drift from the contract -- same single-
  source-of-truth pattern as the seed-parity guard. Module-level cache
  via the ``_cached`` attribute keeps schema-build work out of the per-row
  hot path.

  The four metadata fields the proposer attaches (``naics_provenance``,
  ``decision_source``, ``naics_6``, ``source_of_truth``) are NOT in the
  contract schema's grid-row properties and are therefore correctly
  excluded by this derivation -- they're re-attached after validation.
  """
  cached = getattr(_balance_sheet_seed_contract_row_fields, "_cached", None)
  if cached is not None:
    return cached
  schema = _balance_sheet_contextual_seed_schema()
  grid = (
    (schema or {}).get("properties", {}).get("balance_sheet_seed_grid", {})
  )
  items = grid.get("items", {}) if isinstance(grid, dict) else {}
  properties = items.get("properties", {}) if isinstance(items, dict) else {}
  if not isinstance(properties, dict) or not properties:
    raise RuntimeError(
      "balance_sheet_contextual_seed schema is missing "
      "balance_sheet_seed_grid[].properties; cannot derive contract-row "
      "whitelist for slimming"
    )
  fields_tuple = tuple(sorted(properties.keys()))
  _balance_sheet_seed_contract_row_fields._cached = fields_tuple  # type: ignore[attr-defined]
  return fields_tuple


def _slim_balance_sheet_seed_proposal_for_contract(proposal: Dict[str, Any]) -> Dict[str, Any]:
  """Project the rich proposer payload onto the strict GPT contract shape.

  The proposer attaches metadata (`naics_provenance`, `decision_source`,
  `naics_6`, `source_of_truth`) that's useful for traceability but not part
  of the SQL-backed contract schema. The validator rejects extra fields, so
  we slim the payload before calling it. Metadata is re-attached after
  validation.
  """
  rows = proposal.get("balance_sheet_seed_grid") if isinstance(proposal, dict) else []
  contract_row_fields = _balance_sheet_seed_contract_row_fields()
  slim_rows: List[Dict[str, Any]] = []
  for row in (rows or []):
    if not isinstance(row, dict):
      continue
    slim_rows.append({field: row.get(field) for field in contract_row_fields})
  rationale = str((proposal or {}).get("rationale") or "").strip() or (
    "Python proposer built deterministic seed grid from NAICS resolver and intake anchors; "
    "GPT critic may amend specific rows."
  )
  return {
    "balance_sheet_seed_grid": slim_rows,
    "rationale": rationale,
  }


def _finalize_balance_sheet_seed_with_critique(
  *,
  proposal: Dict[str, Any],
  response: Any,
  raw_openai_response: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Apply a CritiqueResponse to the proposal and normalize via the validator.

  When the critic accepted (or rejected, the safety-floor case), the proposal
  flows straight through the validator. When amended, corrections are applied
  via the shared field-path resolver — corrections that target paths that
  don't exist are silently dropped and surfaced in `_critique_diagnostics`.

  The validator may raise if the amended payload is structurally invalid
  (e.g., out-of-bounds seed_value). When that happens we fall back to the
  raw proposal as the safety floor and log the validator failure for review.
  """
  from client_intake_and_finmo.post_intake_critique import (  # type: ignore
    apply_corrections_to_proposal,
    proposal_only_response,
  )
  slim_proposal = _slim_balance_sheet_seed_proposal_for_contract(proposal)
  amended_payload = apply_corrections_to_proposal(proposal=slim_proposal, response=response)
  critique_diagnostics = amended_payload.pop("_critique_diagnostics", None) if isinstance(amended_payload, dict) else None
  try:
    decision = _validate_balance_sheet_contextual_seed_payload(amended_payload)
  except RuntimeError as exc:
    logger.warning(
      "balance_sheet_contextual_seed_validator_rejected_amended_payload: %s; using proposal as safety floor.", exc
    )
    decision = _validate_balance_sheet_contextual_seed_payload(slim_proposal)
    if critique_diagnostics is None:
      critique_diagnostics = {
        "review_status": getattr(response, "review_status", "unknown"),
        "applied_corrections": [],
        "dropped_corrections": [],
        "critique_summary": getattr(response, "critique_summary", "") or f"validator_rejected: {exc}",
      }
    critique_diagnostics["validator_fallback"] = str(exc)
  decision["proposal"] = proposal
  decision["critique"] = critique_diagnostics or {
    "review_status": getattr(response, "review_status", "accepted"),
    "applied_corrections": [],
    "dropped_corrections": [],
    "critique_summary": getattr(response, "critique_summary", ""),
  }
  decision["raw_openai_response"] = raw_openai_response
  decision["decision_source"] = "python_proposer_plus_gpt_critic"
  return decision

# ---------------------------------------------------------------------------
# iter 19 Stage 5 — deterministic Python stage ramp builder.
#
# Per docs/architecture/doctrine.md §3 Pattern 2: GPT was previously the
# only authoring source for the stage ramp contract. The Python builder
# below uses NAICS cohort bands + stage policy + standard ramp
# templates to produce a complete, validator-compliant contract as the
# first-pass default. The stage ramp handler (post_intake_stage_ramp_
# handler) engages only when the validator rejects the Python output.
# ---------------------------------------------------------------------------


# Per-stage-family revenue QoQ growth target fallback when the NAICS
# cohort has no qoq_growth_band coverage. Conservative midpoints.
_STAGE_FAMILY_FALLBACK_QOQ_TARGET: Dict[str, float] = {
  "startup": 0.18,      # pre-revenue/early launch
  "early": 0.10,        # early stage
  "operational": 0.04,  # mature operating business
}


# Per-stage-family Q1 utilization start point.
_STAGE_FAMILY_Q1_UTILIZATION: Dict[str, float] = {
  "startup": 0.25,
  "early": 0.45,
  "operational": 0.65,
}


# Mature utilization cap (Q11 onward) — same for every family; the
# operator's stage policy already constrains the ramp shape.
_MATURE_UTILIZATION_CAP: float = 0.85


def _stage_family_q_postures(
  *,
  stage_family: str,
  validator_rules: Dict[str, Any],
  r_and_d_enabled: bool,
) -> List[str]:
  """Return the per-quarter (Q1..Q20) profitability_posture sequence
  the validator will accept for this stage family + policy."""
  if str(stage_family).lower() == "operational":
    if bool(validator_rules.get("operational_requires_positive_from_q5")):
      # First four quarters can be near_breakeven; Q5+ must be positive.
      return ["near_breakeven"] * 4 + ["positive"] * 16
    return ["positive"] * 20
  if str(stage_family).lower() == "early":
    return (
      ["improving_losses"] * 4
      + ["near_breakeven"] * 6
      + ["positive"] * 10
    )
  # startup default — loss_allowed early then improvement.
  return (
    ["loss_allowed"] * 4
    + ["improving_losses"] * 4
    + ["near_breakeven"] * 2
    + ["positive"] * 10
  )


def _stage_family_ni_floors(
  *,
  stage_family: str,
  validator_rules: Dict[str, Any],
) -> List[float]:
  """Per-quarter (Q1..Q20) net_income_margin_floor sequence honoring
  validator_rules.q10_min and q11_to_q20_min thresholds."""
  q10_min = float(_safe_float(validator_rules.get("q10_min_net_income_margin_floor")) or -0.02)
  q11_min = float(_safe_float(validator_rules.get("q11_to_q20_min_net_income_margin_floor")) or 0.0)
  q5_floor = _safe_float(validator_rules.get("q5_to_q20_min_net_income_margin_floor"))
  if str(stage_family).lower() == "operational":
    # P3.41 NexGen E2E iter 9 + audit F-J1: derive the 20-quarter floor
    # array entirely from the planning-mode policy values now resolved
    # into validator_rules at post_intake_mapping.py:2948-2964. Zero
    # hardcoded floor numbers in this branch -- all values come from
    # policy. The previous hardcode (Q1-Q4=0.0 + Q5-Q20=0.02) was
    # dead-on-arrival for operational businesses whose policy stage-
    # shift set a higher q11_q20 floor (NexGen on normalize mode:
    # q11_q20_operational=0.05 > 0.02 -> 10 violations Q11..Q20).
    #
    # Policy-key -> validator-key aliasing (per the policy resolver):
    #   floor_q1_q4  -> validator_rules["q1_to_q20_min_net_income_margin_floor"]
    #   floor_q5_q10 -> validator_rules["q5_to_q20_min_net_income_margin_floor"]
    #   floor_q11_q20-> validator_rules["q11_to_q20_min_net_income_margin_floor"]
    # The validator-side key NAMES are confusingly broad (q5_to_q20
    # actually carries the q5_q10 stage value), but the validator
    # CHECKS use the matching quarter ranges: q5_to_q20 applies Q5+,
    # q11_to_q20 applies Q11+, etc. Producer floors derived below
    # satisfy every validator floor check by construction.
    #
    # Policy-defined universal viability floor per post_intake_mapping.py:2956
    # ("q11_q20 floor binds at 0.0 for every (mode, stage)"). Used as
    # the baseline when a policy floor is absent (NOT a magic number --
    # this IS the policy doctrine, made explicit).
    universal_viability_floor = 0.0
    q1_q4_policy = _safe_float(validator_rules.get("q1_to_q20_min_net_income_margin_floor"))
    q5_q10_policy = _safe_float(validator_rules.get("q5_to_q20_min_net_income_margin_floor"))
    q11_q20_policy = _safe_float(validator_rules.get("q11_to_q20_min_net_income_margin_floor"))
    q10_min_policy = _safe_float(validator_rules.get("q10_min_net_income_margin_floor"))

    def _operational_floor_for_quarter(q: int) -> float:
      if q <= 4:
        return float(q1_q4_policy) if q1_q4_policy is not None else universal_viability_floor
      if q <= 9:
        return float(q5_q10_policy) if q5_q10_policy is not None else universal_viability_floor
      if q == 10:
        candidates: List[float] = [universal_viability_floor]
        if q5_q10_policy is not None:
          candidates.append(float(q5_q10_policy))
        if q10_min_policy is not None:
          candidates.append(float(q10_min_policy))
        return max(candidates)
      candidates = [universal_viability_floor]
      if q5_q10_policy is not None:
        candidates.append(float(q5_q10_policy))
      if q11_q20_policy is not None:
        candidates.append(float(q11_q20_policy))
      return max(candidates)

    base = [_operational_floor_for_quarter(q) for q in range(1, 21)]
    if bool(validator_rules.get("operational_requires_nonnegative_from_q1")):
      base = [max(universal_viability_floor, v) for v in base]
    return base
  # Glide from negative floor up to positive by Q11.
  floors: List[float] = []
  for q in range(1, 21):
    if q <= 4:
      floors.append(-0.10)
    elif q <= 9:
      # Linear from -0.10 to q10_min over Q5..Q10.
      progress = (q - 4) / 6.0
      floors.append(-0.10 + (q10_min - (-0.10)) * progress)
    elif q == 10:
      floors.append(q10_min)
    else:
      # Linear from q11_min to q11_min+0.05 over Q11..Q20.
      progress = (q - 11) / 9.0
      floors.append(q11_min + 0.05 * progress)
  if q5_floor is not None:
    floors = [
      max(v, float(q5_floor)) if q >= 5 else v
      for q, v in zip(range(1, 21), floors)
    ]
  return floors


def _cohort_band_target_and_max(
  *,
  metric_key: str,
  business_naics_6: str,
  default_target: float,
  default_max: float,
) -> Tuple[float, float]:
  """Resolve (target, max) from the NAICS cohort band with conservative
  defaults when coverage is missing."""
  if not business_naics_6:
    return float(default_target), float(default_max)
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    band = post_intake_industry_baseline_for_naics(
      metric_key=metric_key, naics_6=business_naics_6
    )
  except Exception:
    return float(default_target), float(default_max)
  if not isinstance(band, dict) or band.get("trust_flag") == "no_coverage":
    return float(default_target), float(default_max)
  target = band.get("benchmark_target")
  if target is None:
    target = band.get("benchmark_min") or band.get("benchmark_max")
  if target is None:
    return float(default_target), float(default_max)
  max_value = band.get("benchmark_max")
  if max_value is None or float(max_value) < float(target):
    max_value = float(target) * 1.2
  # SANE-FLOOR GUARD (systemic NAICS-mismatch fix): a resolved cohort band may
  # RAISE a ceiling above the conservative default, but must never TIGHTEN it
  # below the default. Without this, a NAICS band that fits a different segment
  # of the same code manufactures an impossibly tight ceiling — e.g. food
  # MANUFACTURING (NAICS 311811) carries rent ~1% of revenue, which becomes a
  # 1% rent ceiling for a retail donut storefront whose real rent is a healthy
  # double-digit % of revenue. The same pathology (SMB cohort resolves to a
  # mismatched-segment band and hard-applies it) also produced the empty
  # margin table and the 72% COGS target; clamp the ceiling here so the
  # garbage-low case cannot fire a fake violation.
  max_value = max(float(max_value), float(default_max))
  return float(target), float(max_value)


_STAGE_RAMP_SCHEMA_RANGES_CACHE: Dict[str, Any] = {}


def _stage_ramp_schema_field_ranges() -> Dict[str, Any]:
  """Canonical per-field (min,max) economic-envelope ranges for
  stage_ramp_contract, read from the contract field registry
  (post_intake_gpt_contract_rows) — the same source the validator
  enforces. Cached for the process."""
  if _STAGE_RAMP_SCHEMA_RANGES_CACHE:
    return _STAGE_RAMP_SCHEMA_RANGES_CACHE
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_gpt_contract_rows,
    )
    for r in post_intake_gpt_contract_rows():
      if str(r.get("contract_name")) != "stage_ramp_contract":
        continue
      fn = r.get("field_name")
      mn, mx = r.get("min_value"), r.get("max_value")
      if fn and (mn is not None or mx is not None):
        _STAGE_RAMP_SCHEMA_RANGES_CACHE[str(fn)] = (mn, mx)
  except Exception:
    pass
  return _STAGE_RAMP_SCHEMA_RANGES_CACHE


def _robust_bound(value: Any, lo: Any, hi: Any) -> Any:
  try:
    v = float(value)
  except (TypeError, ValueError):
    return value
  if lo is not None and v < float(lo):
    v = float(lo)
  if hi is not None and v > float(hi):
    v = float(hi)
  return round(v, 2)


def robust_bound_stage_ramp_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
  """Phase 9 P3.32 K13 (Fix 2 / G-B5, doctrine §10.6) — bound every
  cohort-derived stage_ramp field to the canonical economic envelope
  (the contract-registry ranges the validator enforces).

  Root cause (real data): the deterministic builder maps NAICS cohort
  ``benchmark_max`` directly onto contract cost-ratio maxes, but the raw
  cohort max encodes outliers/artifacts that exceed the economic
  envelope — cogs_max 1.0 (a distressed freight firm with COGS >=
  revenue, 4-firm cohort), marketing_max 0.53 and rd_max 0.64 (cohort
  misclassification; no real business sustains those ratios). Those
  produce a structurally invalid contract the GPT handler then cannot
  repair → B5. Bounding each field to the registry envelope is the
  robust upper bound: a distressed-firm / artifact value can never set a
  planning ceiling. This is NOT masking a data bug behind an arbitrary
  clamp — the envelope is the canonical economic range (cogs widened to
  a principled 0.97 = 3% min gross margin in the same fix), so genuine
  high-COGS sectors (trucking 0.963) are admitted while impossible
  values are rejected. Systemic across cogs/marketing/rd/ga/lease."""
  if not isinstance(contract, dict):
    return contract
  ranges = _stage_ramp_schema_field_ranges()
  if not ranges:
    return contract
  uhw = ranges.get("utilization_high_watermark")
  if uhw and "utilization_high_watermark" in contract:
    contract["utilization_high_watermark"] = _robust_bound(
      contract["utilization_high_watermark"], uhw[0], uhw[1]
    )
  grid = contract.get("quarter_ramp_grid")
  if isinstance(grid, list):
    for row in grid:
      if not isinstance(row, dict):
        continue
      for fn, (lo, hi) in ranges.items():
        if fn in row:
          row[fn] = _robust_bound(row[fn], lo, hi)
  return contract


def _clamped_utilization_curve(
  *,
  q1_util: float,
  mature_cap: float,
  rev_growth_bound: float,
) -> List[float]:
  """Phase 9 P3.32 K13 (Fix 2 cont.) — 20-quarter linear-to-mature
  utilization ramp whose per-quarter QoQ growth never exceeds
  ``rev_growth_bound`` (the rounded grid rev_max).

  The validator requires utilization_cap QoQ growth <= allowed revenue
  growth; a plain linear ramp can breach this for tight-rev_max
  (mature/operating) stages (e.g. SwiftCargo operating freight: linear
  Q1->Q2 util growth 3.08% > rev_max 3.0%) -> a second B5 cause. This
  builds the linear template but CLAMPS each step DOWN to the growth
  bound (high-rev_max stages are unchanged; tight stages ramp slightly
  slower, which is conservative). Rounding is floored when rounding up
  would breach the bound."""
  curve: List[float] = []
  prev: Optional[float] = None
  for q in range(1, 21):
    if q == 1:
      val = q1_util
    else:
      linear = (
        q1_util + (mature_cap - q1_util) * (q - 1) / 10.0
        if q <= 11 else mature_cap
      )
      target = min(mature_cap, linear)
      val = max(min(target, prev * (1.0 + rev_growth_bound)), prev)
    rounded = round(val, 2)
    if prev is not None and prev > 0 and (rounded - prev) / prev > rev_growth_bound + 1e-9:
      rounded = max(math.floor(prev * (1.0 + rev_growth_bound) * 100.0) / 100.0, prev)
    curve.append(rounded)
    prev = rounded
  return curve


def build_python_stage_ramp_contract(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  r_and_d_applicability: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Iter 19 Stage 5 — deterministic stage ramp builder. Returns a
  contract matching ``_validate_stage_ramp_contract_payload``'s shape.

  Uses:
    - NAICS cohort bands for cost ratio caps (cogs/marketing/r&d/g&a/
      lease) via ``post_intake_industry_baseline_for_naics``.
    - Stage planning policy for postures, ni_floor thresholds,
      validator rules.
    - Standard linear-to-mature template for utilization ramp.
    - QoQ growth band (when available) for revenue target/max.

  Conservative-default fallbacks when cohort coverage is missing keep
  the function total — it never raises on a cohort miss. The handler
  (post_intake_stage_ramp_handler) refines the ramp if the validator
  rejects it.
  """
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  start_date = (
    _parse_date(facts.get("start_date"))
    or _parse_date(facts.get("business_start_date"))
    or _parse_date(ops.get("business_start_date"))
    or _parse_date(ops.get("start_date"))
  )
  today = datetime.utcnow().date()
  explicit_stage = str(ops.get("business_stage") or facts.get("business_stage") or "").strip().lower()
  inferred_stage = _infer_business_stage(start_date, today) if start_date is not None else None
  stage = explicit_stage or str(inferred_stage or "").strip().lower() or "operational"
  expected_family = _business_stage_family(stage)
  business_naics_6 = "".join(
    ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()
  )

  stage_policy = stage_planning_ramp_policy(
    stage_family=expected_family,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    business_stage=stage,
    business_naics=business_naics_6 or None,
  )
  validator_rules = stage_policy.get("validator_rules") if isinstance(stage_policy.get("validator_rules"), dict) else {}

  # Revenue QoQ growth.
  qoq_band = stage_policy.get("qoq_growth_band") if isinstance(stage_policy.get("qoq_growth_band"), dict) else None
  if qoq_band and qoq_band.get("trust_flag") != "no_coverage":
    qoq_target = float(_safe_float(qoq_band.get("benchmark_target")) or _STAGE_FAMILY_FALLBACK_QOQ_TARGET.get(expected_family, 0.05))
    qoq_max = float(_safe_float(qoq_band.get("benchmark_max")) or qoq_target * 1.5)
  else:
    qoq_target = _STAGE_FAMILY_FALLBACK_QOQ_TARGET.get(expected_family, 0.05)
    qoq_max = qoq_target * 1.5
  qoq_spike_max = qoq_max * 1.3

  # Cost ratio targets + maxes from NAICS cohort with conservative
  # defaults that produce a validator-acceptable envelope when cohort
  # coverage is missing.
  cogs_target, cogs_max = _cohort_band_target_and_max(
    metric_key="cogs_percent_of_revenue",
    business_naics_6=business_naics_6,
    default_target=0.45,
    default_max=0.65,
  )
  _, marketing_max = _cohort_band_target_and_max(
    metric_key="marketing_percent_of_revenue",
    business_naics_6=business_naics_6,
    default_target=0.08,
    default_max=0.18,
  )
  _, ga_max = _cohort_band_target_and_max(
    metric_key="sga_percent_of_revenue",
    business_naics_6=business_naics_6,
    default_target=0.12,
    default_max=0.25,
  )
  _, lease_max = _cohort_band_target_and_max(
    metric_key="rent_percent_of_revenue",
    business_naics_6=business_naics_6,
    default_target=0.05,
    default_max=0.12,
  )
  rd_enabled = (
    bool(r_and_d_applicability.get("r_and_d_enabled"))
    if isinstance(r_and_d_applicability, dict) and isinstance(r_and_d_applicability.get("r_and_d_enabled"), bool)
    else True
  )
  if rd_enabled:
    _, rd_max = _cohort_band_target_and_max(
      metric_key="r_and_d_percent_of_revenue",
      business_naics_6=business_naics_6,
      default_target=0.04,
      default_max=0.10,
    )
  else:
    rd_max = 0.0

  # Utilization ramp: linear-to-mature from Q1 start to mature cap by
  # Q11, mature cap holds Q11..Q20 (validator enforces non-decreasing).
  #
  # Phase 9 P3.32 K13 (Fix 2 cont.) — the validator also requires each
  # quarter's utilization_cap QoQ growth to not exceed the allowed
  # revenue growth (rev_max); otherwise the util ramp implies revenue
  # above the contract ceiling (a second B5 cause, e.g. SwiftCargo
  # operating freight: linear Q1->Q2 util growth 3.08% > rev_max 3.0%).
  # Build the linear-to-mature template but CLAMP each step's growth to
  # qoq_max. This is clamp-DOWN-only: stages whose rev_max already
  # accommodates the linear slope are unchanged; only tight-rev_max
  # (mature/operating) stages ramp slightly slower, which is conservative
  # (lower utilization -> lower implied revenue). Rounding is floored when
  # rounding-up would breach the growth bound.
  # MANAGERIAL BANDS ARE THE RAMP'S COST AUTHORITY when present. The raw
  # cohort caps above are the FALLBACK: before the executive-manager
  # authored maturation forecasts, this grid froze raw cohort flats (COGS
  # 65% / Marketing 40% / R&D 10% held for 20 quarters) onto the Stage
  # Ramp surface -- the workbook showed a plan the manager had already
  # rejected, and the K13 floor pulled costs toward those stale targets.
  # Now each quarter's target follows the manager's fitted path and each
  # max follows the manager's per-quarter wall (killed lines -> 0).
  _si = (model_input_json or {}).get("solver_input") if isinstance(model_input_json, dict) else None
  _fb = (_si or {}).get("fitted_bands") if isinstance(_si, dict) else None
  _fw = (_si or {}).get("fitted_envelope_per_q") if isinstance(_si, dict) else None

  # THE MANAGER'S JUDGED GROWTH IS THE REVENUE AUTHORITY. rev_target is a
  # HARD MINIMUM multiplier (quarter_grid raises utilization/capacity/price
  # until composite revenue meets it), so a stage-policy target above the
  # judged rate FORCE-FEEDS growth the manager never sanctioned. When the
  # judged growth is present, rev_target per quarter follows the proposer's
  # own taper (qoq_start -> qoq_end, linear over Q2..Q20) so the minimum
  # reproduces the authored path -- a coherence floor, never an override.
  _jg = (_si or {}).get("judged_growth") if isinstance(_si, dict) else None
  _jg_qoq_by_q: Dict[int, float] = {}
  if isinstance(_jg, dict):
    try:
      _jg_start = max(0.0, float(_jg.get("qoq_start")))
      _jg_end = max(0.0, float(_jg.get("qoq_end")))
      _jg_span = 18.0  # q2 -> q20
      for _q in range(2, 21):
        _frac = (_q - 2) / _jg_span
        _jg_qoq_by_q[_q] = _jg_start * (1.0 - _frac) + _jg_end * _frac
    except (TypeError, ValueError):
      _jg_qoq_by_q = {}

  def _rev_target_for_q(q: int) -> float:
    if _jg_qoq_by_q:
      # Q1 has no prior quarter (enforcement loops start at Q2); ground its
      # vestigial target to the earliest judged rate so the validator's
      # rev_max >= rev_target self-heal cannot re-break monotonicity.
      # Floored at 0: some mature-stage policies carry a slight-decline
      # qoq_max (-0.01) that the ramp contract validator rejects outright
      # (negative rev fields are envelope violations; ramp-down is not
      # modeled) — flat is the tightest expressible ceiling.
      _fallback = _jg_qoq_by_q.get(2, qoq_target)
      return max(0.0, min(_jg_qoq_by_q.get(q, _fallback), qoq_max))
    return max(0.0, qoq_target)

  # rev_max is judged-derived too: the ramp is the ONE choke point every
  # revenue writer passes (the in-cascade executive, the solver, Phase B --
  # reconcile scales down to rev_max and the finalize validator asserts it).
  # Before this, a loose stage-policy rev_max (0.75/qtr for some families)
  # let the cascade double a firm's utilization -- ~34%/yr growth over a
  # judged 8%->4%/yr market call. The +0.03/qtr allowance above the judged
  # rate is the adaptation headroom matching the Phase B ceiling walls'
  # maximum per-quarter revenue addition (price/capacity/utilization rails
  # spread across the horizon) -- adaptation may ADD growth within honest
  # lever room, never rewrite the market judgment wholesale.
  _JUDGED_REV_MAX_HEADROOM_QOQ = 0.03

  def _rev_max_for_q(q: int) -> float:
    # rev_max must be monotonic non-decreasing per the contract validator
    # (a tapering ceiling was rejected as envelope_violation_rev_max_non_
    # monotonic), so the judged ceiling is FLAT at the judged path's peak
    # rate plus the adaptation headroom. Floored at 0: a slight-decline
    # stage-policy qoq_max (-0.01, some mature families) is rejected by
    # the ramp contract validator as envelope_violation_rev_max_negative
    # — flat is the tightest ceiling the contract can express.
    del q
    if _jg_qoq_by_q:
      return max(0.0, min(qoq_max, max(_jg_qoq_by_q.values()) + _JUDGED_REV_MAX_HEADROOM_QOQ))
    return max(0.0, qoq_max)

  def _mgr_target(metric: str, q: int, fallback: float) -> float:
    try:
      v = (( _fb or {}).get(metric) or {}).get(str(q))
      return float(v) if v is not None else float(fallback)
    except (TypeError, ValueError):
      return float(fallback)

  def _mgr_max(metric: str, q: int, fallback: float) -> float:
    try:
      v = ((( _fw or {}).get(metric) or {}).get("max") or {}).get(str(q))
      return float(v) if v is not None else float(fallback)
    except (TypeError, ValueError):
      return float(fallback)

  _mgr_bands_active = bool(_fb)

  q1_util = _STAGE_FAMILY_Q1_UTILIZATION.get(expected_family, 0.5)
  utilization_curve = _clamped_utilization_curve(
    q1_util=q1_util,
    mature_cap=_MATURE_UTILIZATION_CAP,
    # The validator compares the ROUNDED grid utilization_cap QoQ growth
    # to the ROUNDED grid rev_max; clamp to the TIGHTEST per-quarter
    # rev_max (judged-derived when present) so the util curve never
    # implies growth above the ramp ceiling.
    rev_growth_bound=round(min(_rev_max_for_q(q) for q in range(2, 21)), 2),
  )

  postures = _stage_family_q_postures(
    stage_family=expected_family,
    validator_rules=validator_rules,
    r_and_d_enabled=rd_enabled,
  )
  ni_floors = _stage_family_ni_floors(
    stage_family=expected_family,
    validator_rules=validator_rules,
  )

  quarter_ramp_grid: List[Dict[str, Any]] = []
  for q in range(1, 21):
    quarter_ramp_grid.append({
      "q": q,
      "rev_target": round(_rev_target_for_q(q), 2),
      "rev_max": round(_rev_max_for_q(q), 2),
      "rev_spike": False,
      "rev_spike_max": round(_rev_max_for_q(q), 2),
      "max_util": utilization_curve[q - 1],
      "cogs_target": round(_mgr_target("cogs_percent_of_revenue", q, cogs_target), 2),
      "cogs_max": round(_mgr_max("cogs_percent_of_revenue", q, cogs_max), 2),
      "marketing_max": round(_mgr_max("marketing_percent_of_revenue", q, marketing_max), 2),
      "rd_max": round(
        _mgr_max("r_and_d_percent_of_revenue", q, rd_max) if _mgr_bands_active else rd_max, 2,
      ),
      "ga_max": round(_mgr_max("sga_percent_of_revenue", q, ga_max), 2),
      "lease_max": round(lease_max, 2),
      "ni_floor": round(ni_floors[q - 1], 2),
      "posture": postures[q - 1],
    })

  # The validator's table schema accepts ONLY the contract-declared
  # fields (stage_family, utilization_high_watermark, quarter_ramp_
  # grid, rationale). Provenance fields (business_stage, planning_mode,
  # decision_source, r_and_d_applicability) are added by callers AFTER
  # validation accepts — see engage_stage_ramp_handler_on_validator_
  # failure in post_intake_stage_ramp_handler/handler.py.
  #
  # Phase 9 P3.32 K13 (Fix 2 / G-B5) — robust-bound the cohort-derived
  # cost-ratio maxes to the canonical economic envelope before returning,
  # so distressed-firm / cohort-artifact values (cogs 1.0, marketing
  # 0.53, rd 0.64) can never set a planning ceiling above the envelope.
  # Guarantees the deterministic builder always emits a validator-valid
  # contract (the §10.6 floor for the common range-violation B5 cause).
  return robust_bound_stage_ramp_contract({
    "stage_family": expected_family,
    "utilization_high_watermark": _MATURE_UTILIZATION_CAP,
    "quarter_ramp_grid": quarter_ramp_grid,
    "rationale": (
      f"Python-deterministic stage ramp for {expected_family} stage. "
      f"Revenue QoQ target {qoq_target:.2f}/max {qoq_max:.2f} from "
      "NAICS cohort with conservative-default fallback. Cost ratio "
      "envelopes from NAICS cohort midpoints, robust-bounded to the "
      "canonical economic envelope. Utilization ramps from "
      f"{q1_util:.2f} (Q1) to {_MATURE_UTILIZATION_CAP:.2f} (Q11+). "
      "Stage ramp handler engages if this default fails realism."
    ),
  })


def _estimate_stage_ramp_contract_with_gpt(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]] = None,
  planning_mode: str,
  planning_mode_reason: str,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  r_and_d_applicability: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  api_key = _openai_key()
  if not api_key:
    raise RuntimeError("stage_ramp_contract_openai_key_missing: OPENAI_API_KEY is not configured.")
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  people = people_json if isinstance(people_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  start_date = (
    _parse_date(facts.get("start_date"))
    or _parse_date(facts.get("business_start_date"))
    or _parse_date(ops.get("business_start_date"))
    or _parse_date(ops.get("start_date"))
  )
  today = datetime.utcnow().date()
  explicit_stage = str(ops.get("business_stage") or facts.get("business_stage") or "").strip().lower()
  inferred_stage = _infer_business_stage(start_date, today) if start_date is not None else None
  stage = explicit_stage or str(inferred_stage or "").strip().lower()
  if not stage:
    raise RuntimeError(
      "stage_ramp_contract_missing_business_stage: ops.business_stage or business_start_date is required."
    )
  expected_family = _business_stage_family(stage)
  stage_policy = stage_planning_ramp_policy(
    stage_family=expected_family,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    business_stage=stage,
  )
  rd_decision = r_and_d_applicability if isinstance(r_and_d_applicability, dict) else {}
  rd_enabled = bool(rd_decision.get("r_and_d_enabled")) if isinstance(rd_decision.get("r_and_d_enabled"), bool) else True
  rd_cost_rule = (
    "R&D applicability is enabled. Include R&D maturity caps only when the business facts make separate R&D economically natural."
    if rd_enabled
    else "R&D applicability is disabled before forecast. Set every rd_max value to 0.00 and do not treat R&D as a forecast cost."
  )
  revenue_driver_states = _model_input_revenue_driver_quarter_states(model_input_json)
  finmo_rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
  ]
  try:
    from client_intake_and_finmo.post_intake_headcount.schedule import _revenue_driver_context_from_model_input  # type: ignore
    revenue_driver_context = _revenue_driver_context_from_model_input(model_input_json, finmo_json=finmo_json)
  except Exception as exc:
    raise RuntimeError(f"stage_ramp_revenue_driver_context_failed: {exc}") from exc
  compact_ramp_contract_spec = post_intake_gpt_contract_compact_prompt_field_spec("stage_ramp_contract")
  stage_policy_context = {
    "policy_version": stage_policy.get("policy_version"),
    "stage_family": stage_policy.get("stage_family"),
    "planning_mode": stage_policy.get("planning_mode"),
    "explicit_distress_context": stage_policy.get("explicit_distress_context"),
    "profitability_postures": stage_policy.get("profitability_postures"),
    "validator_rules": stage_policy.get("validator_rules"),
  }
  user_context = {
    "contract_field_spec": compact_ramp_contract_spec,
    "required_response_shape": compact_ramp_contract_spec.get("required_response_shape"),
    "business_identity": {
      "business_name": str(facts.get("business_name") or facts.get("name") or ops.get("business_name") or "").strip(),
      "business_type": ops.get("business_type"),
      "business_stage": stage,
      "stage_family_required": expected_family,
      "business_start_date": start_date.isoformat() if start_date is not None else None,
      "business_age_months_at_run": _whole_months_between(start_date, today) if start_date is not None else None,
      "planning_mode": str(planning_mode or "").strip().lower(),
      "planning_mode_reason": str(planning_mode_reason or "").strip(),
    },
    "business_context": {
      "description": ops.get("business_description_summary") or ops.get("business_description"),
      "growth_lever": ops.get("growth_lever"),
      "capacity_driver": ops.get("capacity_driver"),
      "unit_name": ops.get("unit_name"),
      "fulfillment_summary": ops.get("fulfillment_summary") or ops.get("fulfillment_model_summary"),
      "sales_modality": ops.get("sales_modality"),
      "geographic_scope": ops.get("geographic_scope"),
      "revenue_driver_snapshot": _revenue_catalog_snapshot_for_starting_ppe(ops),
    },
    "financial_context": {
      "cash_strategy": financials.get("cash_strategy"),
      "annual_revenue": (
        year1.get("company_revenue_total_year1")
        or year1.get("revenue_total_year1")
        or financials.get("current_revenue")
      ),
      "cash_on_hand": financials.get("cash_on_hand"),
      "initial_assets": financials.get("initial_assets"),
      "total_debt_outstanding": financials.get("total_debt_outstanding"),
    },
    "r_and_d_applicability": {
      key: copy.deepcopy(value)
      for key, value in rd_decision.items()
      if key not in {"prompt_context", "raw_openai_response"}
    },
    "stage_profitability_policy": stage_policy_context,
    "revenue_driver_context": revenue_driver_context,
    "current_model_snapshot": {
      "revenue_driver_states_first_4_quarters": {
        int(key): value
        for key, value in sorted(revenue_driver_states.items())
        if int(key) <= 4
      },
      "finmo_revenue_first_4_quarters": [
        {
          "quarter_index": int(_safe_float(row.get("quarter_index")) or 0),
          "revenue": int(round(float(_safe_float(row.get("revenue")) or 0.0))),
          "net_income": int(round(float(_safe_float(row.get("net_income")) or 0.0))),
        }
        for row in finmo_rows[:4]
      ],
    },
    "r_and_d_cost_rule": rd_cost_rule,
  }
  user_context = post_intake_gpt_context_filter_payload(
    contract_name="stage_ramp_contract",
    payload=user_context,
    include_phase="pre_convergence",
  )
  system_prompt = post_intake_build_prompt_from_contract(
    "stage_ramp_contract",
    context_payload=user_context,
    include_phase="pre_convergence",
    static_instruction=(
      "You decide the business-world ramp before convergence. Use business type, stage, planning mode, "
      "balance-sheet starting reality, and the table-provided stage policy "
      "to choose realistic quarter-by-quarter revenue, utilization, cost, and profitability bounds."
    ),
    task_instruction=(
      "Return only JSON matching the SQL-backed stage_ramp_contract. Obey contract field instructions and "
      "stage_profitability_policy.validator_rules exactly. This contract owns ramp, utilization, cost caps, "
      "and profitability posture only. Do not include payroll/headcount rows; payroll_headcount_schedule is "
      "a separate contract that runs after this stage/ramp contract."
    ),
  )
  context_budget = post_intake_gpt_context_request_char_budget(
    contract_name="stage_ramp_contract",
    include_phase="pre_convergence",
    default=None,
  )
  if context_budget is not None:
    context_chars = len(json.dumps(user_context, ensure_ascii=False))
    if context_chars > int(context_budget):
      raise RuntimeError(
        f"stage_ramp_gpt_context_payload_budget_exceeded: chars={context_chars} budget={int(context_budget)}"
      )
  payload_base = {
    "model": _openai_model(),
    "temperature": 0,
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_context, ensure_ascii=False)}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "stage_ramp_contract",
        "schema": _stage_ramp_contract_schema(
          business_naics=str(ops.get("business_naics_6") or "").strip() or None,
        ),
        "strict": True,
      }
    },
  }
  ramp_timeout_seconds = _stage_ramp_gpt_timeout_seconds()
  prior_deadline = _set_active_openai_deadline(time.perf_counter() + ramp_timeout_seconds)
  raw_openai_response: Dict[str, Any] = {}
  last_contract_error = ""
  last_parsed: Dict[str, Any] = {}
  try:
    for attempt_index in range(2):
      request_context = copy.deepcopy(user_context)
      if last_contract_error:
        request_context["previous_contract_failure"] = {
          "source_of_truth": "post_intake_gpt_contract_lookup validator",
          "required_action": "Return a corrected full stage_ramp_contract. Payroll/headcount belongs only to payroll_headcount_schedule.",
          "error": last_contract_error[:6000],
          "invalid_response_excerpt": json.dumps(last_parsed, ensure_ascii=False)[:6000],
        }
      payload = copy.deepcopy(payload_base)
      payload["input"] = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "input_text", "text": json.dumps(request_context, ensure_ascii=False)}]},
      ]
      resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload=payload,
      )
      if resp.status_code >= 400:
        raise RuntimeError(f"stage_ramp_contract_openai_status: {resp.text[:1200]}")
      raw_openai_response = resp.json() if isinstance(resp.json(), dict) else {"response": resp.text[:4000]}
      parsed = _parse_responses_json_dict(raw_openai_response)
      if not isinstance(parsed, dict):
        raise RuntimeError("stage_ramp_contract_parse_failed: GPT did not return a JSON object.")
      last_parsed = copy.deepcopy(parsed)
      try:
        contract = _validate_stage_ramp_contract_payload(
          payload=parsed,
          expected_stage_family=expected_family,
          business_stage=stage,
          planning_mode=planning_mode,
          planning_mode_reason=planning_mode_reason,
          r_and_d_enabled=rd_enabled,
        )
        break
      except RuntimeError as exc:
        last_contract_error = str(exc)
        if attempt_index == 0:
          continue
        raise RuntimeError(
          "stage_ramp_contract_invalid_fail_fast: "
          f"{str(exc)}; raw_stage_ramp_response={json.dumps(parsed, ensure_ascii=False)[:8000]}"
        ) from exc
  except TimeoutError as exc:
    raise RuntimeError(
      f"stage_ramp_contract_timeout: GPT ramp selection exceeded {ramp_timeout_seconds:.0f}s before convergence."
    ) from exc
  finally:
    _set_active_openai_deadline(prior_deadline)
  contract["business_stage"] = stage
  contract["business_stage_source"] = "ops.business_stage" if explicit_stage else "business_start_date_inferred"
  contract["planning_mode"] = str(planning_mode or "").strip().lower()
  contract["planning_mode_reason"] = str(planning_mode_reason or "").strip()
  contract["r_and_d_applicability"] = {
    key: copy.deepcopy(value)
    for key, value in rd_decision.items()
    if key not in {"prompt_context", "raw_openai_response"}
  }
  contract["prompt_context"] = user_context
  contract["raw_openai_response"] = raw_openai_response
  return contract

def _solver_quarter_target_metrics_schema(
  *,
  allowed_metric_keys: Optional[List[str]] = None,
  required_metric_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
  metric_keys = list(
    allowed_metric_keys
    if isinstance(allowed_metric_keys, list) and allowed_metric_keys
    else _SOLVER_TARGET_METRIC_KEYS
  )
  required_keys = [
    str(item).strip()
    for item in (
      required_metric_keys
      if isinstance(required_metric_keys, list)
      else _REQUIRED_SOLVER_TARGET_METRIC_KEYS
    )
    if str(item).strip()
  ]
  return {
    "type": "array",
    "minItems": 1,
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "quarter_index": {"type": "integer", "minimum": 1, "maximum": 20},
        **{metric_name: {"type": "integer"} for metric_name in metric_keys},
      },
      "required": ["quarter_index", *required_keys],
    },
  }

def _unified_targets_by_quarter_schema(
  allowed_metric_names: Optional[List[str]] = None,
  allowed_target_values: Optional[List[int]] = None,
  locked_target_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  metric_enum = list(allowed_metric_names or _UNIFIED_ALLOWED_TARGET_METRIC_KEYS) or [""]
  locked_rows = [row for row in (locked_target_rows or []) if isinstance(row, dict)]
  locked_options_by_quarter: Dict[int, List[Dict[str, Any]]] = {}
  for row in locked_rows:
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    metric_name = str(row.get("metric_name") or "").strip().lower()
    target_value = _safe_float(row.get("recommended_target_value"))
    if quarter_index < 1 or not metric_name or target_value is None:
      continue
    if metric_name not in metric_enum:
      continue
    locked_options_by_quarter.setdefault(quarter_index, []).append(
      {
        "metric_name": metric_name,
        "target_value": int(round(float(target_value))),
      }
    )
  if locked_options_by_quarter:
    quarter_item_options: List[Dict[str, Any]] = []
    for quarter_index in sorted(locked_options_by_quarter.keys()):
      metric_item_options = [
        {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "metric_name": {"type": "string", "enum": [str(option.get("metric_name") or "")]},
            "target_value": {"type": "integer", "enum": [int(option.get("target_value") or 0)]},
          },
          "required": ["metric_name", "target_value"],
        }
        for option in sorted(
          locked_options_by_quarter.get(quarter_index) or [],
          key=lambda item: str(item.get("metric_name") or ""),
        )
      ]
      if not metric_item_options:
        continue
      quarter_item_options.append(
        {
          "type": "object",
          "additionalProperties": False,
          "properties": {
            "quarter_index": {"type": "integer", "enum": [int(quarter_index)]},
            "metric_targets": {
              "type": "array",
              "minItems": _UNIFIED_PRIMARY_TARGET_MIN_COUNT,
              "maxItems": _UNIFIED_PRIMARY_TARGET_MAX_COUNT,
              "items": {"anyOf": metric_item_options},
            },
          },
          "required": ["quarter_index", "metric_targets"],
        }
      )
    if quarter_item_options:
      return {
        "type": "array",
        "minItems": 1,
        "items": {"anyOf": quarter_item_options},
      }
  target_value_schema: Dict[str, Any] = {"type": "integer"}
  normalized_allowed_values = sorted(
    {
      int(round(float(value)))
      for value in (allowed_target_values or [])
      if _safe_float(value) is not None
    }
  )
  if normalized_allowed_values:
    target_value_schema = {"type": "integer", "enum": normalized_allowed_values}
  return {
    "type": "array",
    "minItems": 1,
    "items": {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "quarter_index": {"type": "integer", "minimum": 1, "maximum": 20},
        "metric_targets": {
          "type": "array",
          "minItems": _UNIFIED_PRIMARY_TARGET_MIN_COUNT,
          "maxItems": _UNIFIED_PRIMARY_TARGET_MAX_COUNT,
          "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
              "metric_name": {"type": "string", "enum": metric_enum},
              "target_value": target_value_schema,
            },
            "required": ["metric_name", "target_value"],
          },
        },
      },
      "required": ["quarter_index", "metric_targets"],
    },
  }

def _solver_target_contract_spec_payload() -> Dict[str, Any]:
  return {
    "contract_version": "quarter_solver_target_contract_v1",
    "target_quarter_scope": "full_horizon_quarter_specific",
    "required_target_metric_keys": list(_REQUIRED_SOLVER_TARGET_METRIC_KEYS),
    "required_action_fields": [
      "solver_allowed_lever_ids",
      "quarter_target_metrics",
    ],
    "optional_action_fields": [],
    "rules": [
      "If recommendation_mode is 'adjust', recommended_actions must not be empty.",
      "Each adjust action must include allowed model-input levers.",
      "Each adjust action must include quarter_target_metrics for every targeted quarter.",
      "Each quarter_target_metrics item must conform to the target precision defined in post_intak_mapping_lookup.",
      "All numeric formatting is normalized only through the SQL mapping lookup precision metadata.",
      "All driver changes must be expressed through model_input_repair_cells. No alternate adjustment structure is accepted.",
    ],
  }

def _unified_convergence_engine_contract_payload() -> Dict[str, Any]:
  return {
    "contract_version": "unified_convergence_engine_contract_v1",
    "active_solver_owner": "unified_convergence",
    "context_modules": [
      "unified_convergence",
      "cash_strategy",
      "hard_rules",
    ],
    "solver_execution_rule": "solver_must_run_for_every_valid_attempt",
    "pre_execution_hard_blocks": [
      "malformed_payload",
      "missing_required_coverage",
      "unauthorized_levers",
      "broken_contract_shape",
    ],
    "post_execution_governance": [
      "issue_count_delta",
      "severity_delta",
      "hard_rule_delta",
      "constraint_pass_fail",
      "regression_detection",
    ],
  }

def _unified_solver_target_contract_spec_payload() -> Dict[str, Any]:
  return {
    "contract_version": "unified_convergence_target_contract_v1",
    "target_quarter_scope": "full_20_quarter_horizon",
    "allowed_target_metric_keys": list(_UNIFIED_ALLOWED_TARGET_METRIC_KEYS),
    "required_primary_target_metric_count_min": int(_UNIFIED_PRIMARY_TARGET_MIN_COUNT),
    "required_primary_target_metric_count_max": int(_UNIFIED_PRIMARY_TARGET_MAX_COUNT),
    "required_response_fields": [
      "strategy_class",
      "change_type",
      "progress_expectation",
      "strategy_rationale",
      "retry_reason",
      "lever_selection",
      "primary_target_metric_names",
      "targets_by_quarter",
      "target_tolerances",
      "model_input_repair_cells",
    ],
    "rules": [
      "Return one holistic convergence strategy for the current cycle.",
      "Use only editable lever ids surfaced by the SQL-backed full_horizon_model_input_repair_contract.",
      "Treat planning mode, cash strategy, realism, business type, and business model as simultaneous context, not separate stages.",
      "Provide only direct primary target metric names backed by the mapping table; everything else remains a guardrail checked after execution.",
      "For unified convergence, provide quarter-specific numeric targets for every live quarter in required_target_quarters.",
      "targets_by_quarter must exactly match locked_target_fill_grid.required_target_quarters; do not include extra quarters.",
      "primary_target_metric_names must be chosen only from locked_target_fill_grid.allowed_target_metric_names.",
      "Each targets_by_quarter row must fill exactly the selected primary_target_metric_names and no extra metrics.",
      "targets_by_quarter must use metric_targets entries shaped as {metric_name, target_value}.",
      "Provide target_tolerances for every chosen primary target metric so Python can enforce materiality-aware fit, not fake perfection.",
      "Use repair_envelope_packets and full_horizon_model_input_repair_contract as the table-approved pressure and cell-edit surface.",
      "model_input_repair_cells is the execution contract; fill every required editable model-input cell exactly.",
      "Every chosen primary target metric must appear in every targeted quarter row.",
      "Every targeted quarter must be explicitly present in targets_by_quarter.",
      "Python will not fill missing model-input cells, metrics, or targets. Incomplete output will fail.",
      "Prefer band mode unless the business is already close enough that exact placement is clearly warranted.",
      "Keep the plan inside the table-approved full Q1-Q20 convergence context; do not rely on legacy retry-scope packets.",
      "Do not return maintain or explanation-only output while active issues remain.",
      "Retry discipline is enforced after execution; focus on producing the best valid cycle package.",
      "Intake values are not binding. Realism and viability win over intake except for legitimate beginning-balance stub values.",
    ],
  }

def _build_repair_guidance_payload(
  *,
  draft_id: str,
  stage: str,
  status: str,
  planning_context_summary_json: Optional[Dict[str, Any]],
  planning_mode: Optional[str],
  planning_mode_reason: Optional[str],
  planning_mode_prompt_file: str,
  unified_convergence_context: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  controller_retry_context: Optional[Dict[str, Any]] = None,
  prior_numeric_feedback: Optional[Dict[str, Any]] = None,
  unified_convergence_cycle_count: Optional[int] = None,
) -> Dict[str, Any]:
  planning_context_summary = (
    planning_context_summary_json if isinstance(planning_context_summary_json, dict) else {}
  )
  convergence_context = (
    unified_convergence_context if isinstance(unified_convergence_context, dict) else {}
  )
  controller_state = (
    controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  )
  retry_context = (
    controller_retry_context if isinstance(controller_retry_context, dict) else {}
  )
  if not convergence_context and not controller_state and not retry_context:
    return {}
  selected_cash_strategy = _resolved_cash_strategy(
    planning_context_summary,
    convergence_context,
  )
  full_numeric_solver_contract = copy.deepcopy(
    convergence_context.get("numeric_solver_contract")
    if isinstance(convergence_context.get("numeric_solver_contract"), dict)
    else {}
  )
  effective_prior_numeric_feedback = copy.deepcopy(
    prior_numeric_feedback if isinstance(prior_numeric_feedback, dict) else {}
  )
  current_finmo_json = (
    convergence_context.get("current_finmo_json")
    if isinstance(convergence_context.get("current_finmo_json"), dict)
    else {}
  )
  current_finmo_rows = [
    row
    for row in ((current_finmo_json.get("quarter_rows") or []) if isinstance(current_finmo_json, dict) else [])
    if isinstance(row, dict)
  ]
  current_cycle_convergence_packet = _build_current_cycle_convergence_packet(
    stage=stage,
    status=status,
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    planning_context_summary=copy.deepcopy(planning_context_summary),
    unified_convergence_context=copy.deepcopy(convergence_context),
    controller_resolution_state=copy.deepcopy(controller_state),
    controller_retry_context=copy.deepcopy(retry_context),
    prior_numeric_feedback=copy.deepcopy(effective_prior_numeric_feedback),
    unified_convergence_decision=None,
    unified_convergence_plan=None,
    unified_convergence_result=None,
    unified_convergence_cycle_count=unified_convergence_cycle_count,
  )
  current_cycle_deterministic_numeric_guidance = copy.deepcopy(
    (current_cycle_convergence_packet.get("deterministic_numeric_guidance") if isinstance(current_cycle_convergence_packet, dict) else {})
    or {}
  )
  raw_retry_scope_payload = _build_retry_scope_payload(
    controller_retry_context=copy.deepcopy(retry_context),
    prior_numeric_feedback=copy.deepcopy(effective_prior_numeric_feedback),
    numeric_solver_contract=copy.deepcopy(full_numeric_solver_contract),
    deterministic_numeric_guidance=copy.deepcopy(current_cycle_deterministic_numeric_guidance),
    solved_model_input_json=copy.deepcopy(convergence_context.get("current_model_input_json") or {}),
    solved_finmo_json=copy.deepcopy(current_finmo_json),
  )
  retry_scope_payload = copy.deepcopy(raw_retry_scope_payload)
  scoped_numeric_solver_contract = _subset_numeric_solver_contract(
    numeric_solver_contract=copy.deepcopy(full_numeric_solver_contract),
    retry_scope_payload=copy.deepcopy(retry_scope_payload),
  )
  fallback_writable_catalog = (
    convergence_context.get("writable_lever_catalog")
    if isinstance(convergence_context.get("writable_lever_catalog"), dict)
    else {}
  )
  scoped_lever_catalog = copy.deepcopy(
    retry_scope_payload.get("lever_catalog_entries")
    or (fallback_writable_catalog.get("entries") or [])
  )
  scoped_lever_values = copy.deepcopy(
    retry_scope_payload.get("lever_current_values")
    or _solved_lever_value_map(convergence_context.get("current_model_input_json"))
  )
  scoped_model_payload = copy.deepcopy(
    retry_scope_payload.get("model_input_payload")
    or {
      "retry_scope": "full_horizon",
      "quarter_indexes": copy.deepcopy(retry_scope_payload.get("scoped_quarters") or []),
      "lever_ids": copy.deepcopy(
        (((scoped_numeric_solver_contract or {}).get("writable_lever_catalog") or {}).get("lever_ids") or [])
      ),
      "lever_current_values": copy.deepcopy(scoped_lever_values),
    }
  )
  scoped_finmo_rows = copy.deepcopy(
    retry_scope_payload.get("finmo_quarter_rows") or current_finmo_rows
  )
  required_target_quarters = copy.deepcopy(retry_scope_payload.get("scoped_quarters") or [])
  full_prompt_numeric_guidance = copy.deepcopy(current_cycle_deterministic_numeric_guidance)
  prompt_safe_numeric_guidance = _compact_numeric_guidance_for_prompt(
    copy.deepcopy(full_prompt_numeric_guidance)
  )
  locked_target_fill_grid = _unified_target_fill_grid(
    required_target_quarters=copy.deepcopy(required_target_quarters),
    deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
    baseline_finmo_rows=copy.deepcopy(scoped_finmo_rows),
    business_world_contract=copy.deepcopy(convergence_context.get("business_world_contract") or {}),
  )
  prompt_safe_numeric_guidance = _cap_numeric_guidance_revenue_targets_to_locked_grid(
    prompt_safe_numeric_guidance,
    locked_target_fill_grid=locked_target_fill_grid,
  )
  full_prompt_numeric_guidance = _cap_numeric_guidance_revenue_targets_to_locked_grid(
    full_prompt_numeric_guidance,
    locked_target_fill_grid=locked_target_fill_grid,
  )
  locked_target_fill_grid = _unified_target_fill_grid(
    required_target_quarters=copy.deepcopy(required_target_quarters),
    deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
    baseline_finmo_rows=copy.deepcopy(scoped_finmo_rows),
    business_world_contract=copy.deepcopy(convergence_context.get("business_world_contract") or {}),
  )
  locked_lever_control_fill_grid = _unified_lever_control_fill_grid(
    allowed_lever_ids=copy.deepcopy(
      ((scoped_numeric_solver_contract.get("writable_lever_catalog") or {}) if isinstance(scoped_numeric_solver_contract.get("writable_lever_catalog"), dict) else {}).get("lever_ids")
      or []
    ),
    target_quarters=copy.deepcopy(required_target_quarters),
    baseline_map=_solved_lever_value_map(convergence_context.get("current_model_input_json")),
    full_horizon_quarter_count=_quarter_count_from_model_input(convergence_context.get("current_model_input_json")),
    deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
    business_world_contract=copy.deepcopy(convergence_context.get("business_world_contract") or {}),
  )
  prompt_safe_retry_packet = {
    "issues_remaining": int(_safe_float(retry_context.get("issues_remaining")) or 0),
    "failed_quarters": copy.deepcopy(retry_context.get("failed_quarters") or []),
    "failed_metrics": copy.deepcopy(retry_context.get("failed_metrics") or []),
    "previous_levers_used": copy.deepcopy(
      retry_context.get("previous_levers_used")
      or retry_context.get("previous_allowed_lever_ids")
      or []
    ),
    "progress_status": str(retry_context.get("progress_status") or "").strip(),
    "last_failure_reason": str(retry_context.get("last_failure_reason") or "").strip(),
    "required_open_issue_codes": copy.deepcopy(retry_context.get("required_open_issue_codes") or []),
    "required_primary_metric_candidates": copy.deepcopy(
      retry_context.get("required_primary_metric_candidates") or []
    ),
    "required_issue_lever_ids": copy.deepcopy(retry_context.get("required_issue_lever_ids") or []),
    "minimum_primary_metric_coverage_count": int(
      _safe_float(retry_context.get("minimum_primary_metric_coverage_count")) or 0
    ),
    "issue_coverage_requirements": copy.deepcopy(
      retry_context.get("issue_coverage_requirements") or []
    ),
    "constraints": copy.deepcopy(retry_context.get("constraints") or []),
    "validation_correction_grid": _retry_validation_correction_grid(retry_context),
  }
  prompt_safe_numeric_feedback = {
    "execution_state": str(effective_prior_numeric_feedback.get("execution_state") or "").strip(),
    "outcome_reason": str(effective_prior_numeric_feedback.get("outcome_reason") or "").strip(),
    "solver_invoked": bool(effective_prior_numeric_feedback.get("solver_invoked")),
    "solver_execution_state": str(effective_prior_numeric_feedback.get("solver_execution_state") or "").strip(),
    "quarters_with_all_targets_within_tolerance": int(
      _safe_float(effective_prior_numeric_feedback.get("quarters_with_all_targets_within_tolerance")) or 0
    ),
    "quarters_with_target_misses": int(
      _safe_float(effective_prior_numeric_feedback.get("quarters_with_target_misses")) or 0
    ),
    "target_metric_names": copy.deepcopy(effective_prior_numeric_feedback.get("target_metric_names") or []),
    "targeted_quarters": copy.deepcopy(effective_prior_numeric_feedback.get("targeted_quarters") or []),
    "allowed_lever_ids": copy.deepcopy(effective_prior_numeric_feedback.get("allowed_lever_ids") or []),
    "attempted_lever_families": copy.deepcopy(
      effective_prior_numeric_feedback.get("attempted_lever_families") or []
    ),
    "target_verification": copy.deepcopy(effective_prior_numeric_feedback.get("target_verification") or {}),
    "quarter_fit_summary": copy.deepcopy(effective_prior_numeric_feedback.get("quarter_fit_summary") or []),
  }
  compact_solver_contract = _compact_numeric_solver_contract_for_storage(
    copy.deepcopy(scoped_numeric_solver_contract)
  )
  prompt_safe_numeric_solver_contract = {
    "contract_version": str(compact_solver_contract.get("contract_version") or "").strip(),
    "pass_name": str(compact_solver_contract.get("pass_name") or "").strip(),
    "contract_scope": str(compact_solver_contract.get("contract_scope") or "").strip(),
    "planning_mode_profile": copy.deepcopy(compact_solver_contract.get("planning_mode_profile") or {}),
    "selected_cash_strategy": str(compact_solver_contract.get("selected_cash_strategy") or "").strip(),
    "active_issue_count": int(_safe_float(compact_solver_contract.get("active_issue_count")) or 0),
    "issue_target_packets": copy.deepcopy(compact_solver_contract.get("issue_target_packets") or []),
    "solver_settings": copy.deepcopy(compact_solver_contract.get("solver_settings") or {}),
  }
  repair_aware_issue_packets = _repair_aware_issue_packets(
    issue_packets=copy.deepcopy(convergence_context.get("deterministic_issue_packets") or []),
    numeric_guidance_packet=copy.deepcopy(full_prompt_numeric_guidance),
  )
  prompt_repair_issue_packets_all = _compact_issue_packets_for_prompt(
    copy.deepcopy(repair_aware_issue_packets)
  )
  prompt_repair_envelope_packets_all = _compact_repair_envelope_packets_for_prompt(
    copy.deepcopy(full_prompt_numeric_guidance.get("issue_repair_packets") or [])
  )
  aligned_focus_issue_codes = list(
    dict.fromkeys(
      [
        str((item or {}).get("issue_code") or "").strip().lower()
        for item in (full_prompt_numeric_guidance.get("issue_repair_packets") or [])
        if isinstance(item, dict) and str((item or {}).get("issue_code") or "").strip()
      ]
      or [
        str((item or {}).get("issue_code") or "").strip().lower()
        for item in (prompt_repair_issue_packets_all or [])
        if isinstance(item, dict) and str((item or {}).get("issue_code") or "").strip()
      ]
      or [
        str((item or {}).get("issue_code") or "").strip().lower()
        for item in (full_prompt_numeric_guidance.get("metric_pressure_packets") or [])
        if isinstance(item, dict) and str((item or {}).get("issue_code") or "").strip()
      ]
    )
  )[:_CONVERGENCE_MAX_FOCUS_ISSUES]
  aligned_issue_code_set = set(aligned_focus_issue_codes)
  prompt_repair_issue_packets = [
    copy.deepcopy(item)
    for item in (
      prompt_repair_issue_packets_all
      if not aligned_issue_code_set
      else [
        packet
        for packet in (prompt_repair_issue_packets_all or [])
        if isinstance(packet, dict)
        and str(packet.get("issue_code") or "").strip().lower() in aligned_issue_code_set
      ]
    )
  ]
  prompt_repair_envelope_packets = [
    copy.deepcopy(item)
    for item in (
      prompt_repair_envelope_packets_all
      if not aligned_issue_code_set
      else [
        packet
        for packet in (prompt_repair_envelope_packets_all or [])
        if isinstance(packet, dict)
        and str(packet.get("issue_code") or "").strip().lower() in aligned_issue_code_set
      ]
    )
  ]
  aligned_lever_ids: List[str] = []
  for item in (full_prompt_numeric_guidance.get("lever_band_scaffold") or []):
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id or lever_id in aligned_lever_ids:
      continue
    covered_issue_codes = {
      str(code or "").strip().lower()
      for code in (item.get("covered_issue_codes") or [])
      if str(code or "").strip()
    }
    if aligned_issue_code_set and covered_issue_codes and covered_issue_codes.isdisjoint(aligned_issue_code_set):
      continue
    aligned_lever_ids.append(lever_id)
    if len(aligned_lever_ids) >= _CONVERGENCE_MAX_FOCUS_LEVERS:
      break
  if not aligned_lever_ids:
    aligned_lever_ids = [
      lever_id
      for lever_id in _solver_contract_eligible_lever_ids(
        numeric_solver_contract=scoped_numeric_solver_contract,
        issue_codes=aligned_focus_issue_codes,
        target_quarters=required_target_quarters,
      )
      if str(lever_id or "").strip()
    ][:_CONVERGENCE_MAX_FOCUS_LEVERS]
  if aligned_focus_issue_codes:
    aligned_issue_packets = [
      copy.deepcopy(item)
      for item in (full_prompt_numeric_guidance.get("issue_repair_packets") or [])
      if isinstance(item, dict)
      and str(item.get("issue_code") or "").strip().lower() in aligned_issue_code_set
    ]
    if aligned_issue_packets:
      scoped_numeric_solver_contract["issue_target_packets"] = copy.deepcopy(aligned_issue_packets)
      scoped_numeric_solver_contract["active_issue_count"] = len(aligned_issue_packets)
  allowed_primary_target_metric_names = [
    str(metric_name).strip().lower()
    for metric_name in (
      scoped_numeric_solver_contract.get("allowed_target_metric_ids")
      or full_numeric_solver_contract.get("allowed_target_metric_ids")
      or []
    )
    if str(metric_name).strip()
  ]
  focused_primary_target_metric_keys = [
    str(metric_name).strip().lower()
    for metric_name in (
      metric_name
      for packet in (prompt_repair_envelope_packets or [])
      if isinstance(packet, dict)
      for metric_name in (packet.get("metric_targets") or [])
    )
    if str(metric_name).strip()
    and (
      not allowed_primary_target_metric_names
      or str(metric_name).strip().lower() in allowed_primary_target_metric_names
    )
  ]
  focused_primary_target_metric_keys = list(dict.fromkeys(focused_primary_target_metric_keys))
  if len(focused_primary_target_metric_keys) < _UNIFIED_PRIMARY_TARGET_MIN_COUNT:
    for metric_name in (
      str(item).strip().lower()
      for item in (
        scoped_numeric_solver_contract.get("recommended_primary_target_metric_keys")
        or full_numeric_solver_contract.get("recommended_primary_target_metric_keys")
        or []
      )
      if str(item).strip()
    ):
      if (
        metric_name not in focused_primary_target_metric_keys
        and (
          not allowed_primary_target_metric_names
          or metric_name in allowed_primary_target_metric_names
        )
      ):
        focused_primary_target_metric_keys.append(metric_name)
      if len(focused_primary_target_metric_keys) >= _UNIFIED_PRIMARY_TARGET_MIN_COUNT:
        break
  if focused_primary_target_metric_keys:
    scoped_numeric_solver_contract["recommended_primary_target_metric_keys"] = copy.deepcopy(
      focused_primary_target_metric_keys[:_UNIFIED_PRIMARY_TARGET_MAX_COUNT]
    )
  required_driver_path_lever_ids: List[str] = []
  for issue_packet in (full_prompt_numeric_guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    issue_code = str(issue_packet.get("issue_code") or "").strip().lower()
    if aligned_issue_code_set and issue_code not in aligned_issue_code_set:
      continue
    for repair_target in (issue_packet.get("repair_targets") or []):
      if not isinstance(repair_target, dict):
        continue
      for driver_path in (repair_target.get("driver_paths") or []):
        if not isinstance(driver_path, dict):
          continue
        lever_id = str(driver_path.get("lever") or "").strip()
        if lever_id and lever_id not in required_driver_path_lever_ids:
          required_driver_path_lever_ids.append(lever_id)
  for lever_id in required_driver_path_lever_ids:
    if lever_id not in aligned_lever_ids:
      aligned_lever_ids.append(lever_id)
  if aligned_lever_ids:
    aligned_lever_set = set(aligned_lever_ids)
    if isinstance(scoped_numeric_solver_contract.get("writable_lever_catalog"), dict):
      scoped_numeric_solver_contract["writable_lever_catalog"] = {
        **copy.deepcopy(scoped_numeric_solver_contract.get("writable_lever_catalog") or {}),
        "entries": [
          copy.deepcopy(item)
          for item in (((scoped_numeric_solver_contract.get("writable_lever_catalog") or {}).get("entries") or []))
          if isinstance(item, dict) and str(item.get("lever_id") or "").strip() in aligned_lever_set
        ],
        "lever_ids": copy.deepcopy(aligned_lever_ids),
      }
    scoped_numeric_solver_contract["allowed_lever_ids"] = copy.deepcopy(aligned_lever_ids)
    scoped_lever_catalog = [
      copy.deepcopy(item)
      for item in (scoped_lever_catalog or [])
      if isinstance(item, dict) and str(item.get("lever_id") or "").strip() in aligned_lever_set
    ]
    scoped_model_payload["lever_ids"] = copy.deepcopy(aligned_lever_ids)
  prompt_safe_retry_packet = _normalize_retry_requirements_to_allowed_scope(
    retry_context=prompt_safe_retry_packet,
    allowed_lever_ids=aligned_lever_ids or (((scoped_numeric_solver_contract or {}).get("writable_lever_catalog") or {}).get("lever_ids") or []),
  )
  if not (prompt_safe_retry_packet.get("required_open_issue_codes") or []) and aligned_focus_issue_codes:
    prompt_safe_retry_packet["required_open_issue_codes"] = copy.deepcopy(aligned_focus_issue_codes)
  if not (prompt_safe_retry_packet.get("issue_coverage_requirements") or []) and prompt_repair_envelope_packets:
    prompt_safe_retry_packet["issue_coverage_requirements"] = [
      {
        "issue_code": str(packet.get("issue_code") or "").strip().lower(),
        "metric_candidates": copy.deepcopy(packet.get("metric_targets") or []),
      }
      for packet in (prompt_repair_envelope_packets or [])
      if isinstance(packet, dict) and str(packet.get("issue_code") or "").strip()
    ]
  if not (prompt_safe_retry_packet.get("required_primary_metric_candidates") or []) and focused_primary_target_metric_keys:
    prompt_safe_retry_packet["required_primary_metric_candidates"] = copy.deepcopy(
      focused_primary_target_metric_keys[:_UNIFIED_PRIMARY_TARGET_MAX_COUNT]
    )
  if not int(_safe_float(prompt_safe_retry_packet.get("minimum_primary_metric_coverage_count")) or 0) and focused_primary_target_metric_keys:
    prompt_safe_retry_packet["minimum_primary_metric_coverage_count"] = min(
      3,
      len(focused_primary_target_metric_keys),
    )
  if not (prompt_safe_retry_packet.get("required_issue_lever_ids") or []) and aligned_lever_ids:
    prompt_safe_retry_packet["required_issue_lever_ids"] = copy.deepcopy(aligned_lever_ids)
  prompt_safe_retry_packet = _normalize_retry_requirements_to_allowed_scope(
    retry_context=prompt_safe_retry_packet,
    allowed_lever_ids=aligned_lever_ids or (((scoped_numeric_solver_contract or {}).get("writable_lever_catalog") or {}).get("lever_ids") or []),
  )
  compact_solver_contract = _compact_numeric_solver_contract_for_storage(
    copy.deepcopy(scoped_numeric_solver_contract)
  )
  prompt_safe_numeric_solver_contract = {
    "contract_version": str(compact_solver_contract.get("contract_version") or "").strip(),
    "pass_name": str(compact_solver_contract.get("pass_name") or "").strip(),
    "contract_scope": str(compact_solver_contract.get("contract_scope") or "").strip(),
    "planning_mode_profile": copy.deepcopy(compact_solver_contract.get("planning_mode_profile") or {}),
    "selected_cash_strategy": str(compact_solver_contract.get("selected_cash_strategy") or "").strip(),
    "active_issue_count": int(_safe_float(compact_solver_contract.get("active_issue_count")) or 0),
    "issue_target_packets": copy.deepcopy(compact_solver_contract.get("issue_target_packets") or []),
    "solver_settings": copy.deepcopy(compact_solver_contract.get("solver_settings") or {}),
  }
  convergence_scorecard = _build_convergence_scorecard(
    controller_resolution_state=copy.deepcopy(controller_state),
    controller_retry_context=copy.deepcopy(retry_context),
  )
  prompt_safe_current_cycle_packet = _compact_current_cycle_packet_for_prompt(
    copy.deepcopy(current_cycle_convergence_packet)
  )
  prompt_safe_current_cycle_packet["convergence_scorecard"] = copy.deepcopy(convergence_scorecard)
  full_horizon_model_input_repair_contract = _full_horizon_model_input_repair_contract(
    model_input_json=copy.deepcopy(convergence_context.get("current_model_input_json") or {}),
    locked_lever_control_fill_grid=copy.deepcopy(locked_lever_control_fill_grid),
    deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
    allowed_lever_ids=copy.deepcopy(
      (((scoped_numeric_solver_contract or {}).get("writable_lever_catalog") or {}) if isinstance((scoped_numeric_solver_contract or {}).get("writable_lever_catalog"), dict) else {}).get("lever_ids")
      or []
    ),
    quarter_count=_quarter_count_from_model_input(convergence_context.get("current_model_input_json")),
    business_world_contract=copy.deepcopy(convergence_context.get("business_world_contract") or {}),
  )
  issue_mapping_gate = _convergence_issue_mapping_gate(
    deterministic_numeric_guidance=copy.deepcopy(prompt_safe_numeric_guidance),
    full_horizon_model_input_repair_contract=copy.deepcopy(full_horizon_model_input_repair_contract),
    active_issue_count=int(_safe_float(prompt_safe_numeric_solver_contract.get("active_issue_count")) or 0),
  )
  convergence_contract_policy = build_unified_convergence_contract_policy()
  prompt_context_manifest = _post_intake_prompt_context_manifest(
    contract_name="unified_convergence_decision",
    include_phase="planner",
  )
  payload: Dict[str, Any] = {}
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "contract_version", "repair_guidance_v1")
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "packet_role", "unified_convergence_repair_guidance")
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "draft_id", str(draft_id or "").strip())
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "business_name",
    str(
      planning_context_summary.get("business_name")
      or convergence_context.get("business_name")
      or ""
    ).strip(),
  )
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "convergence_engine_contract",
    _unified_convergence_engine_contract_payload(),
  )
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "convergence_contract_policy",
    convergence_contract_policy,
  )
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "planning_mode_context",
    _build_planning_mode_context(
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=planning_mode_prompt_file,
    ),
  )
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "business_world_contract",
    convergence_context.get("business_world_contract") or {},
  )
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "selected_cash_strategy", selected_cash_strategy)
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "convergence_scorecard", convergence_scorecard)
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "repair_envelope_packets", prompt_repair_envelope_packets)
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "retry_packet", prompt_safe_retry_packet)
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "required_target_quarters", required_target_quarters)
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "locked_target_fill_grid", locked_target_fill_grid)
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "locked_targets_by_quarter_response_template",
    _locked_targets_by_quarter_response_template(locked_target_fill_grid),
  )
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "full_horizon_model_input_repair_contract",
    full_horizon_model_input_repair_contract,
  )
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "issue_mapping_gate", issue_mapping_gate)
  _put_prompt_context_from_manifest(payload, prompt_context_manifest, "prior_numeric_solver_feedback", prompt_safe_numeric_feedback)
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "recommended_primary_target_metric_keys",
    (scoped_numeric_solver_contract or {}).get("recommended_primary_target_metric_keys") or [],
  )
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "planner_model_input_packet",
    {
      "retry_scope": copy.deepcopy(scoped_model_payload.get("retry_scope")),
      "quarter_indexes": copy.deepcopy(scoped_model_payload.get("quarter_indexes") or []),
      "lever_ids": copy.deepcopy(scoped_model_payload.get("lever_ids") or []),
    },
  )
  diagnostic_payload_size_summary = {
    "estimated_chars": len(json.dumps(payload, ensure_ascii=False)),
    "included_context_keys": sorted(payload.keys()),
    "focused_issue_count": len(prompt_repair_envelope_packets or []),
    "focused_quarter_count": len(required_target_quarters or []),
    "focused_lever_count": len(
      (((full_horizon_model_input_repair_contract or {}).get("editable_lever_ids") or []))
    ),
    "source_of_truth": "sql.post_intake_gpt_context_lookup",
  }
  _put_prompt_context_from_manifest(
    payload,
    prompt_context_manifest,
    "payload_size_summary",
    diagnostic_payload_size_summary,
  )
  return post_intake_gpt_context_filter_payload(
    contract_name="unified_convergence_decision",
    include_phase="planner",
    payload=payload,
  )

def _capacity_support_revenue_bundle_contract_error(
  *,
  lever_selection: Optional[List[str]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
) -> Optional[str]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  selected = {
    str(item or "").strip()
    for item in (lever_selection or [])
    if str(item or "").strip()
  }
  required_revenue_levers: List[str] = []
  ramp_issue_active = False
  for issue_packet in (guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    issue_code = str(issue_packet.get("issue_code") or "").strip().lower()
    if issue_code != "capacity_support_mismatch":
      continue
    for repair_target in (issue_packet.get("repair_targets") or []):
      if not isinstance(repair_target, dict):
        continue
      metric_name = str(repair_target.get("metric") or "").strip().lower()
      direction = str(repair_target.get("direction") or "").strip().lower()
      if metric_name != "revenue":
        continue
      # Stage/ramp repairs often require coordinated capacity, utilization, and price
      # movement across adjacent quarters. A single revenue lever can appear valid but
      # leave the actual revenue path unchanged or directionally incoherent.
      if direction in {"increase", "decrease", "solve_to_declared_target", "either"}:
        ramp_issue_active = True
      for driver_path in (repair_target.get("driver_paths") or []):
        if not isinstance(driver_path, dict):
          continue
        lever_id = str(driver_path.get("lever") or "").strip()
        if not lever_id:
          continue
        mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
        target_metric = str(mapping_entry.get("target_metric_name") or "").strip().lower()
        driver_bundle = str(mapping_entry.get("driver_bundle") or "").strip().lower()
        if target_metric == "revenue" and driver_bundle == "revenue_formula_bundle":
          if lever_id not in required_revenue_levers:
            required_revenue_levers.append(lever_id)
  if not ramp_issue_active or len(required_revenue_levers) < 2:
    return None
  missing = [lever_id for lever_id in required_revenue_levers if lever_id not in selected]
  if not missing:
    return None
  return (
    "capacity_support_mismatch revenue ramp repair must select the complete direct revenue "
    "driver bundle from the mapping table so Capacity, Unit Price, and Utilization can move together. "
    f"missing_required_revenue_levers={missing}; required_revenue_levers={required_revenue_levers}; "
    f"selected_levers={sorted(selected)}."
  )

def _unified_target_values_repair_envelope_contract_error(
  *,
  targets_by_quarter: Optional[List[Dict[str, Any]]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
) -> Optional[str]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  bounds_by_key: Dict[Tuple[int, str], Dict[str, Any]] = {}
  for issue_packet in (guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    issue_code = str(issue_packet.get("issue_code") or "").strip().lower()
    for repair_target in (issue_packet.get("repair_targets") or []):
      if not isinstance(repair_target, dict):
        continue
      quarter_index = int(_safe_float(repair_target.get("quarter")) or 0)
      metric_name = str(repair_target.get("metric") or "").strip().lower()
      if quarter_index < 1 or not metric_name:
        continue
      key = (quarter_index, metric_name)
      floor_value = _safe_float(repair_target.get("target_floor") or repair_target.get("minimum_target_value"))
      ceiling_value = _safe_float(repair_target.get("target_ceiling") or repair_target.get("maximum_target_value"))
      existing = bounds_by_key.get(key) or {}
      existing_floor = _safe_float(existing.get("minimum_target_value"))
      existing_ceiling = _safe_float(existing.get("maximum_target_value"))
      bounds_by_key[key] = {
        "issue_code": issue_code or existing.get("issue_code"),
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
  for row in (targets_by_quarter or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    for metric_name, raw_value in row.items():
      metric_key = str(metric_name or "").strip().lower()
      if metric_key == "quarter_index":
        continue
      target_value = _safe_float(raw_value)
      if target_value is None:
        continue
      bounds = bounds_by_key.get((quarter_index, metric_key))
      if not isinstance(bounds, dict) or not bounds:
        continue
      floor_value = _safe_float(bounds.get("minimum_target_value"))
      ceiling_value = _safe_float(bounds.get("maximum_target_value"))
      target_value_norm = float(post_intake_normalize_target_value(metric_key, target_value, phase="convergence"))
      floor_value_norm = (
        float(post_intake_normalize_target_value(metric_key, floor_value, phase="convergence", bound_side="minimum"))
        if floor_value is not None
        else None
      )
      ceiling_value_norm = (
        float(post_intake_normalize_target_value(metric_key, ceiling_value, phase="convergence", bound_side="maximum"))
        if ceiling_value is not None
        else None
      )
      target_precision = post_intake_target_precision_for_metric(metric_key, phase="convergence")
      precision_unit = post_intake_precision_unit(target_precision)
      if floor_value_norm is not None and target_value_norm < floor_value_norm:
        if precision_unit > 0.0 and abs(float(floor_value_norm) - float(target_value_norm)) <= precision_unit + 1e-9:
          continue
        return (
          "target_value_outside_deterministic_repair_envelope: "
          f"Q{quarter_index} {metric_key} target_value={target_value_norm} "
          f"is below minimum_target_value={floor_value_norm} for issue "
          f"{bounds.get('issue_code') or 'unknown'}; direction={bounds.get('direction_hint') or 'unknown'}. "
          "GPT must choose targets inside Python's explicit repair envelope; Python will not treat current-value holds as progress."
        )
      if ceiling_value_norm is not None and target_value_norm > ceiling_value_norm:
        if precision_unit > 0.0 and abs(float(target_value_norm) - float(ceiling_value_norm)) <= precision_unit + 1e-9:
          continue
        return (
          "target_value_outside_deterministic_repair_envelope: "
          f"Q{quarter_index} {metric_key} target_value={target_value_norm} "
          f"exceeds maximum_target_value={ceiling_value_norm} for issue "
          f"{bounds.get('issue_code') or 'unknown'}; direction={bounds.get('direction_hint') or 'unknown'}. "
          "GPT must choose targets inside Python's explicit repair envelope; Python will not treat current-value holds as progress."
        )
  return None

def _numeric_decision_contract_error(
  *,
  parsed: Optional[Dict[str, Any]],
  action_quarter_mode: str,
  required_target_quarters: Optional[List[int]] = None,
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  recommendation_mode = str(decision.get("recommendation_mode") or "").strip().lower()
  recommended_actions = [item for item in (decision.get("recommended_actions") or []) if isinstance(item, dict)]
  if recommendation_mode not in {"maintain", "adjust"}:
    return "recommendation_mode must be either 'maintain' or 'adjust'."
  if recommendation_mode == "maintain":
    if recommended_actions:
      return "recommendation_mode='maintain' must not include recommended_actions."
    return None
  return _numeric_adjust_actions_contract_error(
    recommended_actions=recommended_actions,
    action_quarter_mode=action_quarter_mode,
    require_issue_codes=False,
    required_target_quarters=required_target_quarters,
  )

def _revenue_targets_stage_ramp_contract_error(
  *,
  targets_by_quarter: Optional[List[Dict[str, Any]]],
  baseline_finmo_rows: Optional[List[Dict[str, Any]]],
  business_world_contract: Optional[Dict[str, Any]],
) -> Optional[str]:
  contract = business_world_contract if isinstance(business_world_contract, dict) else {}
  stage_ramp_contract = (
    contract.get("stage_ramp_contract")
    if isinstance(contract.get("stage_ramp_contract"), dict)
    else {}
  )
  if not stage_ramp_contract:
    return None
  revenue_by_quarter: Dict[int, float] = {}
  for row in baseline_finmo_rows or []:
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or _safe_float(row.get("quarter")) or 0)
    revenue = _safe_float(row.get("revenue"))
    if quarter_index >= 1 and revenue is not None:
      revenue_by_quarter[quarter_index] = max(0.0, float(revenue))
  target_rows = [
    row for row in (targets_by_quarter or [])
    if isinstance(row, dict) and _safe_float(row.get("revenue")) is not None
  ]
  if not target_rows:
    return None
  spike_count = 0
  for row in sorted(target_rows, key=lambda item: int(_safe_float(item.get("quarter_index")) or 0)):
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    target_revenue = float(_safe_float(row.get("revenue")) or 0.0)
    if quarter_index < 1:
      continue
    previous_revenue = revenue_by_quarter.get(quarter_index - 1)
    if previous_revenue is not None and previous_revenue > 0.0 and target_revenue > previous_revenue:
      growth = (target_revenue - previous_revenue) / previous_revenue
      pair_limit = _stage_ramp_pair_growth_limit(
        stage_ramp_contract,
        from_quarter=quarter_index - 1,
        metric_prefix="revenue",
        spike_count_used=spike_count,
      )
      ordinary_growth_max = float(_safe_float(pair_limit.get("ordinary_growth_max")) or 0.0)
      allowed_growth = float(_safe_float(pair_limit.get("allowed_growth")) or ordinary_growth_max)
      max_allowed_revenue = float(math.floor(max(0.0, float(previous_revenue) * (1.0 + allowed_growth))))
      if target_revenue > max_allowed_revenue:
        row_summary = pair_limit.get("ramp_grid_row") if isinstance(pair_limit.get("ramp_grid_row"), dict) else {}
        return (
          "stage_ramp_contract_revenue_target_violation: "
          f"Q{quarter_index - 1}->Q{quarter_index} target revenue growth {round(growth, 6)} "
          f"exceeds allowed {round(allowed_growth, 6)} from GPT quarter_ramp_grid. "
          f"previous_revenue={round(previous_revenue, 2)}, target_revenue={round(target_revenue, 2)}, "
          f"max_allowed_revenue={int(round(max_allowed_revenue))}, "
          f"business_stage={contract.get('business_stage')}, planning_mode={contract.get('planning_mode')}, "
          f"ramp_grid_row={row_summary}. "
          "Repair targets_by_quarter and the revenue-driver trajectory so the stage ramp grid is satisfied before solver."
        )
      if bool(pair_limit.get("spike_available")) and growth > ordinary_growth_max:
        spike_count += 1
    revenue_by_quarter[quarter_index] = target_revenue
  return None

def _normalize_unified_decision_numeric_formatting(
  *,
  parsed: Optional[Dict[str, Any]],
  lever_value_kind_by_id: Optional[Dict[str, str]],
) -> None:
  decision = parsed if isinstance(parsed, dict) else {}
  value_kind_by_id = lever_value_kind_by_id if isinstance(lever_value_kind_by_id, dict) else {}

  def _normalize_value(value: Any, *, ratio_like: bool, integer_like: bool) -> Any:
    number = _safe_float(value)
    if number is None:
      return value
    if ratio_like:
      return round(float(number), 2)
    if integer_like:
      return int(round(float(number)))
    return value

  for row in (decision.get("targets_by_quarter") or []):
    if not isinstance(row, dict):
      continue
    for metric_target in (row.get("metric_targets") or []):
      if not isinstance(metric_target, dict):
        continue
      metric_name = str(metric_target.get("metric_name") or "").strip().lower()
      target_value = _safe_float(metric_target.get("target_value"))
      if metric_name and target_value is not None:
        metric_target["target_value"] = post_intake_normalize_target_value(
          metric_name,
          target_value,
          phase="convergence",
        )

  for tolerance in (decision.get("target_tolerances") or []):
    if not isinstance(tolerance, dict):
      continue
    relative_tolerance = _safe_float(tolerance.get("relative_tolerance_pct"))
    if relative_tolerance is not None:
      tolerance["relative_tolerance_pct"] = round(float(relative_tolerance), 2)
    absolute_tolerance = _safe_float(tolerance.get("absolute_tolerance"))
    if absolute_tolerance is not None:
      tolerance["absolute_tolerance"] = int(round(float(absolute_tolerance)))

def _normalize_unified_decision_targets_to_locked_grid(
  *,
  parsed: Optional[Dict[str, Any]],
  target_fill_grid: Optional[Dict[str, Any]],
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  grid = target_fill_grid if isinstance(target_fill_grid, dict) else {}

  bounds_by_key: Dict[Tuple[int, str], Dict[str, Any]] = {}
  for row in (grid.get("rows") or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    metric_name = str(row.get("metric_name") or "").strip().lower()
    if quarter_index < 1 or not metric_name:
      continue
    bounds_by_key[(quarter_index, metric_name)] = {
      "minimum_target_value": _safe_float(row.get("minimum_target_value")),
      "maximum_target_value": _safe_float(row.get("maximum_target_value")),
      "recommended_target_value": _safe_float(row.get("recommended_target_value")),
      "target_value_kind": str(row.get("target_value_kind") or "").strip().lower(),
    }
  if not bounds_by_key:
    return None
  selected_metric_names = [
    str(item or "").strip().lower()
    for item in (decision.get("primary_target_metric_names") or [])
    if str(item or "").strip()
  ]
  selected_metric_names = list(dict.fromkeys(selected_metric_names))
  if selected_metric_names:
    target_rows = decision.get("targets_by_quarter")
    if not isinstance(target_rows, list):
      target_rows = []
      decision["targets_by_quarter"] = target_rows
    target_rows_by_quarter: Dict[int, Dict[str, Any]] = {}
    for target_row in target_rows:
      if not isinstance(target_row, dict):
        continue
      quarter_index = int(_safe_float(target_row.get("quarter_index")) or 0)
      if quarter_index >= 1 and quarter_index not in target_rows_by_quarter:
        target_rows_by_quarter[quarter_index] = target_row
    required_quarters = [
      int(_safe_float(item) or 0)
      for item in (grid.get("required_target_quarters") or [])
      if int(_safe_float(item) or 0) >= 1
    ]
    if not required_quarters:
      required_quarters = sorted({quarter for quarter, _metric in bounds_by_key.keys() if quarter >= 1})
    for quarter_index in required_quarters:
      if quarter_index in target_rows_by_quarter:
        continue
      target_row = {"quarter_index": quarter_index, "metric_targets": []}
      target_rows.append(target_row)
      target_rows_by_quarter[quarter_index] = target_row
    for quarter_index, target_row in target_rows_by_quarter.items():
      metric_targets = target_row.get("metric_targets")
      if not isinstance(metric_targets, list):
        metric_targets = []
        target_row["metric_targets"] = metric_targets
      existing_metric_targets: Dict[str, Dict[str, Any]] = {}
      for metric_target in metric_targets:
        if not isinstance(metric_target, dict):
          continue
        metric_name = str(metric_target.get("metric_name") or "").strip().lower()
        if metric_name and metric_name not in existing_metric_targets:
          existing_metric_targets[metric_name] = metric_target
      for metric_name in selected_metric_names:
        bounds = bounds_by_key.get((quarter_index, metric_name))
        if not isinstance(bounds, dict):
          continue
        recommended_value = _safe_float(bounds.get("recommended_target_value"))
        if recommended_value is None:
          continue
        target_value = post_intake_normalize_target_value(
          metric_name,
          recommended_value,
          phase="convergence",
          bound_side=(
            "minimum"
            if str(bounds.get("direction_hint") or "").strip().lower() == "increase"
            else "maximum"
            if str(bounds.get("direction_hint") or "").strip().lower() == "decrease"
            else ""
          ),
        )
        metric_target = existing_metric_targets.get(metric_name)
        if not isinstance(metric_target, dict):
          metric_targets.append(
            {
              "metric_name": metric_name,
              "target_value": target_value,
              "target_value_source": "locked_target_fill_grid",
            }
          )
          continue
        if _safe_float(metric_target.get("target_value")) is None:
          metric_target["target_value"] = target_value
          metric_target["target_value_source"] = "locked_target_fill_grid"
  for target_row in (decision.get("targets_by_quarter") or []):
    if not isinstance(target_row, dict):
      continue
    quarter_index = int(_safe_float(target_row.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    for metric_target in (target_row.get("metric_targets") or []):
      if not isinstance(metric_target, dict):
        continue
      metric_name = str(metric_target.get("metric_name") or "").strip().lower()
      target_value = _safe_float(metric_target.get("target_value"))
      if not metric_name or target_value is None:
        continue
      bounds = bounds_by_key.get((quarter_index, metric_name))
      if not isinstance(bounds, dict):
        metric_target["target_value"] = post_intake_normalize_target_value(
          metric_name,
          target_value,
          phase="convergence",
        )
        continue
      adjusted_value = float(target_value)
      minimum_value = _safe_float(bounds.get("minimum_target_value"))
      maximum_value = _safe_float(bounds.get("maximum_target_value"))
      recommended_value = _safe_float(bounds.get("recommended_target_value"))
      target_precision = post_intake_target_precision_for_metric(metric_name, phase="convergence")
      precision_unit = post_intake_precision_unit(target_precision)
      if recommended_value is not None:
        metric_target["target_value"] = post_intake_normalize_target_value(
          metric_name,
          recommended_value,
          phase="convergence",
        )
        continue
      bound_side = ""
      if minimum_value is not None and adjusted_value < float(minimum_value):
        drift = abs(float(minimum_value) - adjusted_value)
        if precision_unit <= 0.0 or drift > precision_unit + 1e-9:
          return (
            "targets_by_quarter target_value is materially below the locked deterministic target envelope. "
            f"Q{quarter_index} {metric_name} target_value={target_value} "
            f"minimum_target_value={minimum_value} "
            f"table_precision_unit={precision_unit}. "
            "Python only normalizes table-defined formatting drift; it does not clamp material GPT decisions."
          )
        adjusted_value = float(minimum_value)
        bound_side = "minimum"
      if maximum_value is not None and adjusted_value > float(maximum_value):
        drift = abs(adjusted_value - float(maximum_value))
        if precision_unit <= 0.0 or drift > precision_unit + 1e-9:
          return (
            "targets_by_quarter target_value is materially above the locked deterministic target envelope. "
            f"Q{quarter_index} {metric_name} target_value={target_value} "
            f"maximum_target_value={maximum_value} "
            f"table_precision_unit={precision_unit}. "
            "Python only normalizes table-defined formatting drift; it does not clamp material GPT decisions."
          )
        adjusted_value = float(maximum_value)
        bound_side = "maximum"
      metric_target["target_value"] = post_intake_normalize_target_value(
        metric_name,
        adjusted_value,
        phase="convergence",
        bound_side=bound_side,
      )
  return None

def _normalize_revenue_targets_to_stage_ramp_currency_caps(
  *,
  parsed: Optional[Dict[str, Any]],
  baseline_finmo_rows: Optional[List[Dict[str, Any]]],
  business_world_contract: Optional[Dict[str, Any]],
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  contract = business_world_contract if isinstance(business_world_contract, dict) else {}
  stage_ramp_contract = (
    contract.get("stage_ramp_contract")
    if isinstance(contract.get("stage_ramp_contract"), dict)
    else {}
  )
  if not stage_ramp_contract:
    return None
  revenue_by_quarter: Dict[int, float] = {}
  for row in baseline_finmo_rows or []:
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or _safe_float(row.get("quarter")) or 0)
    revenue = _safe_float(row.get("revenue"))
    if quarter_index >= 1 and revenue is not None:
      revenue_by_quarter[quarter_index] = max(0.0, float(revenue))
  target_rows = [
    row for row in (decision.get("targets_by_quarter") or [])
    if isinstance(row, dict)
  ]
  spike_count = 0
  for row in sorted(target_rows, key=lambda item: int(_safe_float(item.get("quarter_index")) or 0)):
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    revenue_targets = [
      item for item in (row.get("metric_targets") or [])
      if isinstance(item, dict)
      and str(item.get("metric_name") or "").strip().lower() == "revenue"
      and _safe_float(item.get("target_value")) is not None
    ]
    if not revenue_targets:
      continue
    metric_target = revenue_targets[0]
    target_revenue = float(_safe_float(metric_target.get("target_value")) or 0.0)
    previous_revenue = revenue_by_quarter.get(quarter_index - 1)
    if previous_revenue is not None and previous_revenue > 0.0 and target_revenue > previous_revenue:
      pair_limit = _stage_ramp_pair_growth_limit(
        stage_ramp_contract,
        from_quarter=quarter_index - 1,
        metric_prefix="revenue",
        spike_count_used=spike_count,
      )
      ordinary_growth_max = float(_safe_float(pair_limit.get("ordinary_growth_max")) or 0.0)
      allowed_growth = float(_safe_float(pair_limit.get("allowed_growth")) or ordinary_growth_max)
      max_allowed_revenue = float(math.floor(max(0.0, float(previous_revenue) * (1.0 + allowed_growth))))
      if target_revenue > max_allowed_revenue:
        drift = target_revenue - max_allowed_revenue
        precision_unit = post_intake_precision_unit(
          post_intake_target_precision_for_metric("revenue", phase="convergence")
        )
        if precision_unit <= 0.0 or drift > precision_unit + 1e-9:
          return (
            "stage_ramp_contract_revenue_target_violation: "
            f"Q{quarter_index - 1}->Q{quarter_index} target revenue exceeds the table precision ramp cap by {drift}. "
            f"previous_revenue={int(round(previous_revenue))}, target_revenue={int(round(target_revenue))}, "
            f"max_allowed_revenue={int(round(max_allowed_revenue))}. "
            "Python only normalizes table-defined formatting drift, not material GPT decisions."
          )
        target_revenue = max_allowed_revenue
        metric_target["target_value"] = post_intake_normalize_target_value(
          "revenue",
          target_revenue,
          phase="convergence",
        )
      growth = (float(target_revenue) - float(previous_revenue)) / max(float(previous_revenue), 1e-9)
      if bool(pair_limit.get("spike_available")) and growth > ordinary_growth_max:
        spike_count += 1
    revenue_by_quarter[quarter_index] = max(0.0, float(target_revenue))
  return None

def _unified_convergence_decision_contract_error(
  *,
  parsed: Optional[Dict[str, Any]],
  required_target_quarters: Optional[List[int]] = None,
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
  deterministic_numeric_guidance: Optional[Dict[str, Any]] = None,
  controller_retry_context: Optional[Dict[str, Any]] = None,
  baseline_map: Optional[Dict[str, List[float]]] = None,
  baseline_finmo_rows: Optional[List[Dict[str, Any]]] = None,
  business_world_contract: Optional[Dict[str, Any]] = None,
  full_horizon_quarter_count: Optional[int] = None,
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  table_horizon_errors = validate_unified_convergence_contract_horizon(decision)
  if table_horizon_errors:
    return (
      "post_intake_contract_horizon_violation: "
      + "; ".join(str(item) for item in table_horizon_errors[:20])
    )
  retry_context = controller_retry_context if isinstance(controller_retry_context, dict) else {}
  writable_catalog = (
    (numeric_solver_contract or {}).get("writable_lever_catalog")
    if isinstance((numeric_solver_contract or {}).get("writable_lever_catalog"), dict)
    else {}
  )
  lever_value_kind_by_id: Dict[str, str] = {}
  for entry in (writable_catalog.get("entries") or []):
    if not isinstance(entry, dict):
      continue
    lever_id = str(entry.get("lever_id") or "").strip()
    if not lever_id:
      continue
    lever_value_kind_by_id[lever_id] = str(
      entry.get("value_kind")
      or entry.get("value_type")
      or entry.get("input_semantics")
      or ""
    ).strip().lower()
  _normalize_unified_decision_numeric_formatting(
    parsed=decision,
    lever_value_kind_by_id=lever_value_kind_by_id,
  )
  target_fill_grid = _unified_target_fill_grid(
    required_target_quarters=copy.deepcopy(required_target_quarters),
    deterministic_numeric_guidance=copy.deepcopy(deterministic_numeric_guidance or {}),
    baseline_finmo_rows=copy.deepcopy(baseline_finmo_rows or []),
    business_world_contract=copy.deepcopy(business_world_contract or {}),
  )
  # The locked target grid is table-backed contract structure. Apply it before
  # stage-ramp validation so stale/freeform target values cannot create an
  # avoidable retry loop ahead of the table-owned exact target rows.
  target_grid_normalization_error = _normalize_unified_decision_targets_to_locked_grid(
    parsed=decision,
    target_fill_grid=copy.deepcopy(target_fill_grid),
  )
  if target_grid_normalization_error:
    return target_grid_normalization_error
  stage_ramp_currency_cap_error = _normalize_revenue_targets_to_stage_ramp_currency_caps(
    parsed=decision,
    baseline_finmo_rows=copy.deepcopy(baseline_finmo_rows or []),
    business_world_contract=copy.deepcopy(business_world_contract or {}),
  )
  if stage_ramp_currency_cap_error:
    return stage_ramp_currency_cap_error
  strategy_class = str(decision.get("strategy_class") or "").strip()
  if not strategy_class:
    return "strategy_class is required for unified convergence."
  change_type = str(decision.get("change_type") or "").strip().lower()
  if not change_type:
    return "change_type is required for unified convergence."
  progress_expectation = str(decision.get("progress_expectation") or "").strip().lower()
  if not progress_expectation:
    return "progress_expectation is required for unified convergence."
  strategy_rationale = str(decision.get("strategy_rationale") or "").strip()
  if not strategy_rationale:
    return "strategy_rationale is required for unified convergence."
  lever_selection = [
    str(item or "").strip()
    for item in (decision.get("lever_selection") or [])
    if str(item or "").strip()
  ]
  if not lever_selection:
    return "lever_selection must include at least one authorized writable lever id."
  unmapped_lever_selection = [
    lever_id
    for lever_id in lever_selection
    if not post_intake_driver_target_mapping_entry(lever_id)
  ]
  if unmapped_lever_selection:
    return (
      "lever_selection contains lever ids with no direct driver-target mapping table entry: "
      f"{unmapped_lever_selection}."
    )
  revenue_bundle_error = _capacity_support_revenue_bundle_contract_error(
    lever_selection=copy.deepcopy(lever_selection),
    deterministic_numeric_guidance=copy.deepcopy(
      deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
    ),
  )
  if revenue_bundle_error:
    return revenue_bundle_error
  has_model_input_repair_cells = bool(
    [item for item in (decision.get("model_input_repair_cells") or []) if isinstance(item, dict)]
  )
  if lever_selection and not has_model_input_repair_cells:
    return (
      "Every selected lever must be represented by explicit full-horizon model_input_repair_cells. "
      "Missing model-input cell coverage for selected levers: "
      f"{lever_selection}."
    )
  primary_target_metric_names = _unified_required_target_metric_keys(
    decision_payload=decision,
    numeric_solver_contract=numeric_solver_contract,
  )
  grid_allowed_metric_set = {
    str(item or "").strip().lower()
    for item in (target_fill_grid.get("allowed_target_metric_names") or [])
    if str(item or "").strip()
  }
  raw_primary_metric_names = [
    str(item or "").strip().lower()
    for item in (decision.get("primary_target_metric_names") or [])
    if str(item or "").strip()
  ]
  if grid_allowed_metric_set:
    outside_grid_metrics = [
      metric_name for metric_name in raw_primary_metric_names
      if metric_name not in grid_allowed_metric_set
    ]
    if outside_grid_metrics:
      return (
        "primary_target_metric_names must be chosen only from locked_target_fill_grid.allowed_target_metric_names. "
        f"outside_grid_metrics={outside_grid_metrics}, allowed={sorted(grid_allowed_metric_set)}."
      )
  if len(primary_target_metric_names) < _UNIFIED_PRIMARY_TARGET_MIN_COUNT:
    return (
      f"primary_target_metric_names must include at least {_UNIFIED_PRIMARY_TARGET_MIN_COUNT} "
      "authorized metric ids."
    )
  if len(primary_target_metric_names) > _UNIFIED_PRIMARY_TARGET_MAX_COUNT:
    return (
      f"primary_target_metric_names must include no more than {_UNIFIED_PRIMARY_TARGET_MAX_COUNT} "
      "authorized metric ids."
    )
  for tolerance in [item for item in (decision.get("target_tolerances") or []) if isinstance(item, dict)]:
    metric_name = str(tolerance.get("metric_name") or "").strip().lower() or "unknown"
    relative_tolerance_pct = _safe_float(tolerance.get("relative_tolerance_pct"))
    absolute_tolerance = _safe_float(tolerance.get("absolute_tolerance"))
    if relative_tolerance_pct is not None and round(float(relative_tolerance_pct), 2) != float(relative_tolerance_pct):
      return (
        f"target_tolerances metric {metric_name} relative_tolerance_pct must use at most 2 decimal places. "
        f"received={relative_tolerance_pct}."
      )
    target_precision = post_intake_target_precision_for_metric(metric_name, phase="convergence")
    normalized_absolute_tolerance = (
      post_intake_normalize_target_value(metric_name, absolute_tolerance, phase="convergence")
      if absolute_tolerance is not None
      else None
    )
    precision_unit = post_intake_precision_unit(target_precision)
    if (
      absolute_tolerance is not None
      and normalized_absolute_tolerance is not None
      and abs(float(absolute_tolerance) - float(normalized_absolute_tolerance)) > max(precision_unit / 2.0, 1e-9)
    ):
      return (
        f"target_tolerances metric {metric_name} absolute_tolerance violates SQL mapping precision. "
        f"received={absolute_tolerance}, normalized={normalized_absolute_tolerance}, precision={target_precision}."
      )
  normalized_tolerances = _merge_required_target_tolerances(
    decision.get("target_tolerances") or [],
    primary_target_metric_names,
  )
  targets_by_quarter = _augment_solver_quarter_target_metrics(
    raw_targets=decision.get("targets_by_quarter"),
    required_metric_names=primary_target_metric_names,
    numeric_solver_contract=copy.deepcopy(numeric_solver_contract),
    required_target_quarters=copy.deepcopy(required_target_quarters),
  )
  if not targets_by_quarter:
    return "targets_by_quarter must include numeric quarter targets for the current cycle."
  ramp_contract_error = _revenue_targets_stage_ramp_contract_error(
    targets_by_quarter=copy.deepcopy(targets_by_quarter),
    baseline_finmo_rows=copy.deepcopy(baseline_finmo_rows or []),
    business_world_contract=copy.deepcopy(business_world_contract or {}),
  )
  if ramp_contract_error:
    return ramp_contract_error
  repair_envelope_contract_error = _unified_target_values_repair_envelope_contract_error(
    targets_by_quarter=copy.deepcopy(targets_by_quarter),
    deterministic_numeric_guidance=copy.deepcopy(
      deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
    ),
  )
  if repair_envelope_contract_error:
    return repair_envelope_contract_error
  target_quarters = sorted(
    {
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in targets_by_quarter
      if int(_safe_float(item.get("quarter_index")) or 0) >= 1
    }
  )
  effective_required_target_quarters = sorted(
    {
      int(_safe_float(item) or 0)
      for item in (required_target_quarters or [])
      if int(_safe_float(item) or 0) >= 1
    }
  )
  if effective_required_target_quarters and target_quarters != effective_required_target_quarters:
    extra_target_quarters = [
      quarter for quarter in target_quarters
      if quarter not in set(effective_required_target_quarters)
    ]
    missing_required_quarters = [
      quarter for quarter in effective_required_target_quarters
      if quarter not in set(target_quarters)
    ]
    return (
      "targets_by_quarter must exactly match the deterministic full-horizon required_target_quarters. "
      f"required_target_quarters={effective_required_target_quarters}, "
      f"provided_target_quarters={target_quarters}, "
      f"extra_target_quarters={extra_target_quarters}, "
      f"missing_required_quarters={missing_required_quarters}."
    )
  primary_metric_set = set(primary_target_metric_names)
  for target_row in targets_by_quarter:
    quarter_index = int(_safe_float(target_row.get("quarter_index")) or 0)
    row_metric_set = {
      str(metric_name or "").strip().lower()
      for metric_name in target_row.keys()
      if str(metric_name or "").strip().lower() != "quarter_index"
      and _safe_float(target_row.get(metric_name)) is not None
    }
    if row_metric_set != primary_metric_set:
      return (
        "Each targets_by_quarter row must fill exactly the selected primary_target_metric_names and no extra metrics. "
        f"Q{quarter_index} row_metrics={sorted(row_metric_set)}, primary_target_metric_names={sorted(primary_metric_set)}."
      )
  synthetic_action = {
    "action_id": "unified_cycle",
    "target_quarters": target_quarters,
    "solver_allowed_lever_ids": lever_selection,
    "required_target_metric_keys": copy.deepcopy(primary_target_metric_names),
    "quarter_target_metrics": targets_by_quarter,
  }
  numeric_contract_error = _numeric_adjust_actions_contract_error(
    recommended_actions=[synthetic_action],
    action_quarter_mode="target_quarters",
    require_issue_codes=False,
    required_target_quarters=effective_required_target_quarters,
    default_required_metric_keys=copy.deepcopy(primary_target_metric_names),
  )
  if numeric_contract_error:
    return numeric_contract_error
  sql_derived_issue_metric_coverage: Dict[str, set[str]] = {}
  sql_derived_issue_quarter_coverage: Dict[str, set[int]] = {}
  for lever_id in lever_selection:
    for mapping in _table_mapped_repair_targets_for_lever(
      lever_id=lever_id,
      deterministic_numeric_guidance=copy.deepcopy(
        deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
      ),
      primary_target_metric_names=copy.deepcopy(primary_target_metric_names),
      targeted_quarters=copy.deepcopy(target_quarters),
    ):
      issue_code = str(mapping.get("issue_code") or "").strip().lower()
      metric_name = str(mapping.get("target_metric_name") or "").strip().lower()
      if not issue_code:
        continue
      if metric_name:
        sql_derived_issue_metric_coverage.setdefault(issue_code, set()).add(metric_name)
      for quarter_index in (
        int(_safe_float(item) or 0)
        for item in (mapping.get("target_quarters") or [])
      ):
        if quarter_index >= 1:
          sql_derived_issue_quarter_coverage.setdefault(issue_code, set()).add(int(quarter_index))
  for requirement in [item for item in (retry_context.get("issue_coverage_requirements") or []) if isinstance(item, dict)]:
    issue_code = str(requirement.get("issue_code") or "").strip().lower()
    metric_candidates = {
      str(item or "").strip().lower()
      for item in (requirement.get("metric_candidates") or [])
      if str(item or "").strip()
    }
    if metric_candidates and not any(metric_name in metric_candidates for metric_name in primary_target_metric_names):
      return (
        "Unified convergence requires direct target coverage for each open issue. "
        f"Issue {str(requirement.get('issue_code') or '').strip() or 'unknown'} has no covered primary metric."
      )
    if metric_candidates and not (sql_derived_issue_metric_coverage.get(issue_code) or set()) & metric_candidates:
      return (
        "Unified convergence requires each open issue to have a SQL-mapped selected lever, not just broad metric overlap. "
        f"Issue {str(requirement.get('issue_code') or '').strip() or 'unknown'} has no selected mapping-table lever covering {sorted(metric_candidates)}."
      )
    relevant_quarters = {
      int(_safe_float(item) or 0)
      for item in (
        requirement.get("affected_quarters")
        or requirement.get("relevant_quarters")
        or []
      )
      if int(_safe_float(item) or 0) >= 1
    }
    if relevant_quarters and not ((sql_derived_issue_quarter_coverage.get(issue_code) or set()) & relevant_quarters):
      return (
        "Unified convergence requires selected mapping-table levers to cover the issue's active quarters. "
        f"Issue {str(requirement.get('issue_code') or '').strip() or 'unknown'} has no SQL-derived mapped quarter overlap with {sorted(relevant_quarters)}."
      )
  return None

def _realism_verification_failure_payload(
  *,
  prompt_file: str,
  status: str,
  detail: str = "",
) -> Dict[str, Any]:
  return {
    "contract_version": "unified_convergence_verification_v1",
    "status": status,
    "prompt_file": prompt_file,
    "verification_status": "not_completed",
    "detail": str(detail or "").strip(),
    "verification": {},
  }

def _target_miss_verification_fallback(
  *,
  phase: str,
  reason: str,
  last_verification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  fallback = (
    copy.deepcopy(last_verification)
    if isinstance(last_verification, dict) and last_verification
    else _realism_verification_failure_payload(
      prompt_file="client_intake_and_finmo/prompts/unified_convergence/verifier.md",
      status="skipped_infeasible_target_miss",
      detail=str(reason or "").strip(),
    )
  )
  if not isinstance(fallback, dict):
    fallback = _realism_verification_failure_payload(
      prompt_file="client_intake_and_finmo/prompts/unified_convergence/verifier.md",
      status="skipped_infeasible_target_miss",
      detail=str(reason or "").strip(),
    )
  fallback["target_verification_gate"] = {
    "controller_state": "infeasible",
    "phase": str(phase or "").strip() or "unknown",
    "reason": str(reason or "").strip() or "Target verification could not proceed because the numeric pass exhausted its retry budget.",
  }
  return fallback

def _run_realism_verification_openai(
  *,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  planning_mode_prompt_file: str,
  protected_resolved_issue_constraints: Optional[List[Dict[str, Any]]] = None,
  strategy_recheck_context: Optional[Dict[str, Any]] = None,
  realism_pass_consistency_context: Optional[Dict[str, Any]] = None,
  realism_memo_before_resolution: Dict[str, Any],
  unified_convergence_decision: Dict[str, Any],
  unified_convergence_plan: Dict[str, Any],
  unified_convergence_result: Dict[str, Any],
  updated_model_input_json: Dict[str, Any],
  updated_finmo_json: Dict[str, Any],
) -> Dict[str, Any]:
  """Module 5 Task 5.6 — Python proposes per-issue verdicts; GPT critiques.

  Workflow:
    1. `propose_realism_verification_payload` walks each issue_packet
       (from the plan/decision/result) and derives a deterministic
       per-issue verdict from `applied_updates`:
         - resolved: every affected quarter saw an applied lever change
         - improved: some affected quarters were touched
         - stalled: no candidate lever was touched
    2. The OpenAI critic receives the proposal and may amend specific
       per-issue verdicts (e.g., flip "improved" → "resolved" when the
       residual gap is judged acceptable).
    3. Python applies amendments via the shared critique contract.
    4. When GPT fails (no key, timeout, garbage), Python's verdicts
       stand as the safety floor — every verdict has data provenance
       back to the convergence result.
  """
  prompt_file = "client_intake_and_finmo/prompts/unified_convergence/verifier.md"
  decision_payload = (
    unified_convergence_decision.get("decision")
    if isinstance(unified_convergence_decision.get("decision"), dict)
    else {}
  )
  plan_issue_packets = (
    unified_convergence_plan.get("issue_packets")
    if isinstance(unified_convergence_plan.get("issue_packets"), list)
    else []
  )
  deterministic_issue_packets = (
    unified_convergence_decision.get("deterministic_issue_packets")
    if isinstance(unified_convergence_decision.get("deterministic_issue_packets"), list)
    else []
  )
  issue_packets = [
    item
    for item in (
      plan_issue_packets
      or deterministic_issue_packets
      or (decision_payload.get("issue_packets") or [])
    )
    if isinstance(item, dict)
  ]
  if not issue_packets:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_missing_issue_packets",
      detail="No issue packets were available for realism verification.",
    )

  # ----- Step 1: build the Python verification proposal deterministically. -----
  from client_intake_and_finmo.post_intake_realism.verification_proposer import (  # type: ignore
    propose_realism_verification_payload,
  )
  from client_intake_and_finmo.post_intake_critique import (  # type: ignore
    CRITIQUE_CONTRACT_SCHEMA,
    CritiqueResponse,
    apply_corrections_to_proposal,
    proposal_only_response,
  )
  applied_updates_for_proposal = [
    item for item in ((unified_convergence_result or {}).get("applied_updates") or []) if isinstance(item, dict)
  ]
  proposal = propose_realism_verification_payload(
    issue_packets=issue_packets,
    applied_updates=applied_updates_for_proposal,
    realism_memo_before_resolution=realism_memo_before_resolution,
  )
  proposer_diagnostics = proposal.pop("_proposer_diagnostics", {}) if isinstance(proposal, dict) else {}
  contract_proposal = _normalize_post_intake_contract_payload(
    contract_name="unified_convergence_verification",
    payload=proposal,
  )
  proposal_contract_errors = _post_intake_contract_payload_errors(
    contract_name="unified_convergence_verification",
    payload=contract_proposal,
  )
  if proposal_contract_errors:
    return _realism_verification_failure_payload(
      prompt_file=prompt_file,
      status="failed_proposer_invalid_contract",
      detail=(
        "Python verification proposer produced an invalid payload — this is a Python bug, "
        "not a GPT failure. " + "; ".join(str(item) for item in proposal_contract_errors[:5])
      ),
    )

  api_key = _openai_key()
  if not api_key:
    return {
      "contract_version": "unified_convergence_verification_v1",
      "status": "completed",
      "prompt_file": prompt_file,
      "verification_status": "completed",
      "detail": "OPENAI_API_KEY is not configured; Python proposal stands as the safety floor.",
      "decision_source": "python_proposer_only",
      "proposer_diagnostics": copy.deepcopy(proposer_diagnostics),
      "verification": contract_proposal,
    }

  # ----- Step 2: invoke the GPT critic with the proposal as input. -----
  compact_issue_packets = _compact_issue_packets_for_prompt(issue_packets)
  lever_catalog = _build_writable_lever_review_catalog(updated_model_input_json)
  allowed_lever_ids = [str(item.get("lever_id") or "").strip() for item in lever_catalog if str(item.get("lever_id") or "").strip()]
  touched_lever_ids = sorted(
    {
      str(item.get("lever_id") or "").strip()
      for item in applied_updates_for_proposal
      if str(item.get("lever_id") or "").strip()
    }
  )
  memo_before = realism_memo_before_resolution if isinstance(realism_memo_before_resolution, dict) else {}
  compact_realism_memo_before = {
    "status": str(memo_before.get("status") or "").strip(),
    "remaining_issue_count": int(_safe_float(memo_before.get("remaining_issue_count")) or 0),
    "resolved_issue_count": int(_safe_float(memo_before.get("resolved_issue_count")) or 0),
    "tolerated_issue_count": int(_safe_float(memo_before.get("tolerated_issue_count")) or 0),
    "issue_packets": copy.deepcopy(compact_issue_packets),
  }
  proposal_for_critic = {
    "overall_assessment": contract_proposal.get("overall_assessment"),
    "executive_summary": contract_proposal.get("executive_summary"),
    "issue_results": copy.deepcopy(contract_proposal.get("issue_results") or []),
  }
  critic_context = {
    "proposal": proposal_for_critic,
    "proposer_diagnostics": proposer_diagnostics,
    "issue_packets": compact_issue_packets,
    "applied_updates": copy.deepcopy(applied_updates_for_proposal),
    "touched_lever_ids": touched_lever_ids,
    "realism_memo_before_resolution": compact_realism_memo_before,
    "business_summary": {
      "business_name": str((business_facts or {}).get("name") or (business_facts or {}).get("business_name") or "").strip(),
      "draft_id": str(draft_id or "").strip(),
      "planning_mode": str(planning_mode or "").strip(),
      "planning_mode_reason": str(planning_mode_reason or "").strip(),
    },
    "contract_enums": {
      "overall_assessment": ["all_resolved", "partially_resolved", "not_resolved"],
      "issue_status": ["resolved", "partially_resolved", "not_resolved"],
      "remaining_issue_materiality": ["immaterial", "material"],
      "remaining_issue_severity_score": "integer 0-100",
      "remaining_problem_quarters": "array of strings like 'Q3'",
    },
    "review_instructions": [
      "You are reviewing Python-derived per-issue verdicts for a convergence pass.",
      "Accept the proposal when each issue's verdict is reasonable given the applied_updates.",
      "Amend ONLY when domain judgment overrides the deterministic heuristic — e.g., 'partially_resolved' should be 'resolved' because the residual gap is acceptable for THIS business.",
      "Use ONLY the enum values shown in contract_enums. Any other string will be rejected by the contract validator.",
      "field_path uses bracket notation, e.g. issue_results[0].status or issue_results[2].observed_improvement_summary.",
      "Only edit fields that already exist in the proposal. Do not add or remove issue_results entries.",
      "Reject only if the proposal is structurally unusable; Python's verdicts will then stand as the safety floor.",
    ],
  }
  critic_schema = _openai_strict_json_schema(CRITIQUE_CONTRACT_SCHEMA)
  payload_base = {
    "model": _openai_model(),
    "temperature": 0,
    "text": {
      "format": {
        "type": "json_schema",
        "name": "unified_convergence_verification_critique",
        "schema": critic_schema,
        "strict": True,
      }
    },
  }
  system_prompt = (
    "You are reviewing Python-built per-issue verdicts for a convergence pass. Python is the engineer "
    "(it derived each verdict from applied_updates and issue affected_quarters); you are the consultant. "
    "Return review_status=accepted when verdicts are reasonable. Return review_status=amended with "
    "surgical corrections when domain judgment overrides the heuristic. Return review_status=rejected "
    "only when the structure is unusable; in that case, Python falls back to the proposal as the safety "
    "floor. Output only JSON conforming to the critique schema."
  )
  raw_openai_response: Optional[Dict[str, Any]] = None
  try:
    payload = copy.deepcopy(payload_base)
    payload["input"] = [
      {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(critic_context, ensure_ascii=False)}]},
    ]
    resp = _post_openai(
      url="https://api.openai.com/v1/responses",
      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
      payload=payload,
    )
    if resp.status_code >= 400:
      logger.warning(
        "realism_verification_critic_http_error: status=%s body=%s",
        resp.status_code, resp.text[:500],
      )
      response = proposal_only_response(reason=f"critic_http_status_{resp.status_code}")
    else:
      raw_openai_response = resp.json() if isinstance(resp.json(), dict) else {"response": resp.text[:4000]}
      parsed_critique = _parse_responses_json_dict(raw_openai_response)
      try:
        response = CritiqueResponse.from_payload(parsed_critique)
      except RuntimeError as exc:
        logger.warning("realism_verification_critic_invalid_payload: %s", exc)
        response = proposal_only_response(reason=f"critic_invalid_payload: {exc}")
  except Exception as exc:
    logger.warning("realism_verification_critic_unexpected_error: %s", exc)
    response = proposal_only_response(reason=f"critic_unexpected_error: {exc}")

  # ----- Step 3: apply critic corrections to the proposal. -----
  amended = apply_corrections_to_proposal(proposal=proposal_for_critic, response=response)
  critique_diagnostics = amended.pop("_critique_diagnostics", None) if isinstance(amended, dict) else None
  amended_for_validation = {
    "overall_assessment": amended.get("overall_assessment") or contract_proposal.get("overall_assessment"),
    "executive_summary": amended.get("executive_summary") or contract_proposal.get("executive_summary"),
    "issue_results": amended.get("issue_results") or contract_proposal.get("issue_results") or [],
  }
  amended_for_validation = _normalize_post_intake_contract_payload(
    contract_name="unified_convergence_verification",
    payload=amended_for_validation,
  )
  table_contract_errors = _post_intake_contract_payload_errors(
    contract_name="unified_convergence_verification",
    payload=amended_for_validation,
  )
  if table_contract_errors:
    logger.warning(
      "realism_verification_critic_amended_invalid: %s; falling back to Python proposal as safety floor.",
      "; ".join(str(item) for item in table_contract_errors[:5]),
    )
    return {
      "contract_version": "unified_convergence_verification_v1",
      "status": "completed",
      "prompt_file": prompt_file,
      "verification_status": "completed",
      "detail": (
        "Critic amendments produced an invalid contract; Python proposal stands. "
        + "; ".join(str(item) for item in table_contract_errors[:3])
      ),
      "decision_source": "python_proposer_with_critic_fallback",
      "proposer_diagnostics": copy.deepcopy(proposer_diagnostics),
      "critique_diagnostics": copy.deepcopy(critique_diagnostics or {}),
      "raw_openai_response": copy.deepcopy(raw_openai_response or {}),
      "verification": copy.deepcopy(contract_proposal),
    }
  decision_source = (
    "python_proposer_plus_gpt_critic_amended"
    if response.review_status == "amended"
    else "python_proposer_plus_gpt_critic_accepted"
  )
  return {
    "contract_version": "unified_convergence_verification_v1",
    "status": "completed",
    "prompt_file": prompt_file,
    "verification_status": "completed",
    "detail": "",
    "decision_source": decision_source,
    "proposer_diagnostics": copy.deepcopy(proposer_diagnostics),
    "critique_diagnostics": copy.deepcopy(critique_diagnostics or {}),
    "raw_openai_response": copy.deepcopy(raw_openai_response or {}),
    "critique_summary": getattr(response, "critique_summary", "") or "",
    "verification": amended_for_validation,
  }

def _validate_payroll_headcount_contract(
  *,
  model_input_json: Optional[Dict[str, Any]],
  business_world_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_headcount import validate_payroll_headcount_contract  # type: ignore

  return validate_payroll_headcount_contract(
    model_input_json=model_input_json,
    business_world_contract=business_world_contract,
  )

def _normalize_retry_requirements_to_allowed_scope(
  *,
  retry_context: Optional[Dict[str, Any]],
  allowed_lever_ids: Optional[List[str]],
) -> Dict[str, Any]:
  context = copy.deepcopy(retry_context if isinstance(retry_context, dict) else {})
  allowed_ids = [
    str(item).strip()
    for item in (allowed_lever_ids or [])
    if str(item).strip()
  ]
  if not allowed_ids:
    return context
  allowed_set = set(allowed_ids)

  context["required_issue_lever_ids"] = [
    lever_id
    for lever_id in (
      str(item).strip()
      for item in (context.get("required_issue_lever_ids") or [])
      if str(item).strip()
    )
    if lever_id in allowed_set
  ]
  normalized_issue_requirements: List[Dict[str, Any]] = []
  for requirement in (context.get("issue_coverage_requirements") or []):
    if not isinstance(requirement, dict):
      continue
    normalized_issue_requirements.append(copy.deepcopy(requirement))
  context["issue_coverage_requirements"] = normalized_issue_requirements
  return context

def _table_mapped_repair_targets_for_lever(
  *,
  lever_id: str,
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  primary_target_metric_names: Optional[List[str]],
  targeted_quarters: Optional[List[int]],
) -> List[Dict[str, Any]]:
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  selected_primary_metrics = {
    str(metric or "").strip().lower()
    for metric in (primary_target_metric_names or [])
    if str(metric or "").strip()
  }
  direct_target_metric_name = post_intake_direct_target_metric_for_lever(lever_id)
  if not direct_target_metric_name or (
    selected_primary_metrics and direct_target_metric_name not in selected_primary_metrics
  ):
    return []
  targeted_quarter_set = {
    int(_safe_float(quarter) or 0)
    for quarter in (targeted_quarters or [])
    if int(_safe_float(quarter) or 0) >= 1
  }
  mapping_quarters: Dict[Tuple[str, str], set[int]] = {}
  for issue_packet in (guidance.get("issue_repair_packets") or []):
    if not isinstance(issue_packet, dict):
      continue
    issue_code = str(issue_packet.get("issue_code") or "").strip().lower()
    if not issue_code:
      continue
    for repair_target in (issue_packet.get("repair_targets") or []):
      if not isinstance(repair_target, dict):
        continue
      quarter = int(_safe_float(repair_target.get("quarter")) or 0)
      if quarter < 1:
        continue
      if targeted_quarter_set and quarter not in targeted_quarter_set:
        continue
      has_matching_path = any(
        isinstance(driver_path, dict)
        and str(driver_path.get("lever") or "").strip() == lever_id
        for driver_path in (repair_target.get("driver_paths") or [])
      )
      if not has_matching_path:
        continue
      mapping_quarters.setdefault((issue_code, direct_target_metric_name), set()).add(quarter)
  mappings: List[Dict[str, Any]] = []
  for issue_code, target_metric_name in sorted(mapping_quarters.keys()):
    mappings.append(
      {
        "issue_code": issue_code,
        "target_metric_name": target_metric_name,
        "target_quarters": sorted(mapping_quarters[(issue_code, target_metric_name)]),
      }
    )
  return mappings

def _unified_primary_metric_coverage_error(
  *,
  parsed: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
  controller_retry_context: Optional[Dict[str, Any]],
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  retry_context = controller_retry_context if isinstance(controller_retry_context, dict) else {}
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  primary_target_metric_names = _normalize_primary_target_metric_names(
    decision.get("primary_target_metric_names") or []
  )
  allowed_target_metric_names = set(
    _normalize_primary_target_metric_names(
      contract.get("allowed_target_metric_ids")
      or contract.get("recommended_primary_target_metric_keys")
      or []
    )
  )
  required_metric_names: List[str] = []
  for requirement in (retry_context.get("issue_coverage_requirements") or []):
    if not isinstance(requirement, dict):
      continue
    metric_candidates = _normalize_primary_target_metric_names(
      requirement.get("metric_candidates") or []
    )
    if not metric_candidates:
      continue
    if any(metric_name in metric_candidates for metric_name in primary_target_metric_names):
      continue
    chosen_metric_name = next(
      (
        metric_name
        for metric_name in metric_candidates
        if not allowed_target_metric_names or metric_name in allowed_target_metric_names
      ),
      None,
    )
    if chosen_metric_name and chosen_metric_name not in required_metric_names:
      required_metric_names.append(chosen_metric_name)
  if required_metric_names:
    return (
      "primary_target_metric_names is missing required direct issue coverage for: "
      f"{required_metric_names}."
    )
  return None

def _solver_contract_quarter_count(
  numeric_solver_contract: Optional[Dict[str, Any]],
) -> int:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  quarter_candidates: List[int] = []
  for item in (contract.get("required_target_quarters") or []):
    quarter_value = int(_safe_float(item) or 0)
    if quarter_value >= 1:
      quarter_candidates.append(quarter_value)
  for item in (contract.get("quarter_target_grid") or []):
    if not isinstance(item, dict):
      continue
    quarter_value = int(_safe_float(item.get("quarter_index")) or 0)
    if quarter_value >= 1:
      quarter_candidates.append(quarter_value)
  writable_catalog = (
    contract.get("writable_lever_catalog")
    if isinstance(contract.get("writable_lever_catalog"), dict)
    else {}
  )
  for entry in (writable_catalog.get("entries") or []):
    if not isinstance(entry, dict):
      continue
    for item in (entry.get("valid_quarter_indices") or []):
      quarter_value = int(_safe_float(item) or 0)
      if quarter_value >= 1:
        quarter_candidates.append(quarter_value)
  return max(quarter_candidates or [20])

def _remaining_horizon_quarters(
  *,
  start_quarter: Any,
  quarter_count: int,
) -> List[int]:
  start_q = int(_safe_float(start_quarter) or 0)
  if start_q < 1:
    return []
  return list(range(start_q, max(start_q, int(quarter_count or 20)) + 1))

def _normalize_primary_target_metric_names(raw_metric_names: Any) -> List[str]:
  out: List[str] = []
  allowed = set(_UNIFIED_ALLOWED_TARGET_METRIC_KEYS)
  for item in (raw_metric_names or []):
    metric_name = str(item or "").strip().lower()
    if not metric_name or metric_name not in allowed or metric_name in out:
      continue
    out.append(metric_name)
  return out

def _normalize_unified_target_tolerances(raw_tolerances: Any) -> List[Dict[str, Any]]:
  allowed = set(_UNIFIED_ALLOWED_TARGET_METRIC_KEYS)
  deduped: Dict[str, Dict[str, Any]] = {}
  for item in (raw_tolerances or []):
    if not isinstance(item, dict):
      continue
    metric_name = str(item.get("metric_name") or "").strip().lower()
    if not metric_name or metric_name not in allowed:
      continue
    relative_tolerance_pct = _safe_float(item.get("relative_tolerance_pct"))
    absolute_tolerance = _safe_float(item.get("absolute_tolerance"))
    tolerance_reason = str(item.get("tolerance_reason") or "").strip()
    if relative_tolerance_pct is None and absolute_tolerance is None:
      continue
    deduped[metric_name] = {
      "metric_name": metric_name,
      "relative_tolerance_pct": (
        round(float(max(0.0, relative_tolerance_pct)), 2)
        if relative_tolerance_pct is not None
        else None
      ),
      "absolute_tolerance": (
        int(round(float(max(0.0, absolute_tolerance))))
        if absolute_tolerance is not None
        else None
      ),
      "tolerance_reason": tolerance_reason,
    }
  return [copy.deepcopy(deduped[key]) for key in sorted(deduped.keys())]

def _default_unified_target_tolerances(metric_names: Any) -> List[Dict[str, Any]]:
  normalized_metric_names = _normalize_primary_target_metric_names(metric_names)
  out: List[Dict[str, Any]] = []
  for metric_name in normalized_metric_names:
    out.append(
      {
        "metric_name": metric_name,
        "relative_tolerance_pct": 5.00,
        "absolute_tolerance": 1000,
        "tolerance_reason": "Default tolerance for direct mapping-table target metrics.",
      }
    )
  return out

def _solver_contract_primary_target_metric_keys(
  numeric_solver_contract: Optional[Dict[str, Any]],
) -> List[str]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  keys = _normalize_primary_target_metric_names(
    contract.get("recommended_primary_target_metric_keys") or []
  )
  return keys[:_UNIFIED_PRIMARY_TARGET_MAX_COUNT]

def _unified_required_target_metric_keys(
  *,
  decision_payload: Optional[Dict[str, Any]] = None,
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
) -> List[str]:
  decision = decision_payload if isinstance(decision_payload, dict) else {}
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  allowed_keys = set(
    _normalize_primary_target_metric_names(
      contract.get("allowed_target_metric_ids")
      or contract.get("recommended_primary_target_metric_keys")
      or []
    )
  )
  keys = _normalize_primary_target_metric_names(
    decision.get("primary_target_metric_names") or []
  )
  return [
    key
    for key in keys
    if not allowed_keys or key in allowed_keys
  ][:_UNIFIED_PRIMARY_TARGET_MAX_COUNT]

def _normalize_solver_quarter_target_metrics(raw_targets: Any) -> List[Dict[str, Any]]:
  normalized: List[Dict[str, Any]] = []
  horizon_count = _contract_forecast_quarter_count("unified_convergence_decision")
  for item in (raw_targets or []):
    if not isinstance(item, dict):
      continue
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    if quarter_index < 1 or quarter_index > horizon_count:
      continue
    payload: Dict[str, Any] = {"quarter_index": quarter_index}
    metric_targets = [entry for entry in (item.get("metric_targets") or []) if isinstance(entry, dict)]
    if metric_targets:
      for entry in metric_targets:
        metric_name = str(entry.get("metric_name") or "").strip().lower()
        if metric_name not in _SOLVER_TARGET_METRIC_KEYS:
          continue
        metric_value = _safe_float(entry.get("target_value"))
        if metric_value is not None:
          payload[metric_name] = int(round(float(metric_value)))
    else:
      for metric_name in _SOLVER_TARGET_METRIC_KEYS:
        metric_value = _safe_float(item.get(metric_name))
        if metric_value is not None:
          payload[metric_name] = int(round(float(metric_value)))
    if len(payload) > 1:
      normalized.append(payload)
  normalized.sort(key=lambda item: int(item.get("quarter_index") or 0))
  deduped: Dict[int, Dict[str, Any]] = {}
  for item in normalized:
    deduped[int(item.get("quarter_index") or 0)] = copy.deepcopy(item)
  return [deduped[key] for key in sorted(deduped.keys())]

def _solver_contract_all_writable_lever_ids(
  numeric_solver_contract: Optional[Dict[str, Any]],
) -> List[str]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  catalog = (
    contract.get("writable_lever_catalog")
    if isinstance(contract.get("writable_lever_catalog"), dict)
    else {}
  )
  lever_ids: List[str] = []
  for item in (catalog.get("lever_ids") or []):
    lever_id = str(item or "").strip()
    if lever_id and lever_id not in lever_ids:
      lever_ids.append(lever_id)
  return lever_ids

def _solver_contract_eligible_lever_ids(
  *,
  numeric_solver_contract: Optional[Dict[str, Any]],
  issue_codes: Optional[List[str]] = None,
  target_quarters: Optional[List[int]] = None,
) -> List[str]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  all_writable = _solver_contract_all_writable_lever_ids(contract)
  if all_writable:
    return all_writable
  eligible: List[str] = []
  issue_code_set = {
    str(item or "").strip().lower()
    for item in (issue_codes or [])
    if str(item or "").strip()
  }
  target_quarter_set = {
    int(_safe_float(item) or 0)
    for item in (target_quarters or [])
    if int(_safe_float(item) or 0) >= 1
  }
  issue_packet_map = _numeric_solver_contract_issue_packet_map(contract)
  for issue_code in issue_code_set:
    for lever_id in (issue_packet_map.get(issue_code) or {}).get("next_required_lever_ids") or []:
      lever = str(lever_id or "").strip()
      if lever and lever not in eligible:
        eligible.append(lever)
  for item in (contract.get("quarter_target_grid") or []):
    if not isinstance(item, dict):
      continue
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    if target_quarter_set and quarter_index not in target_quarter_set:
      continue
    if issue_code_set:
      driving_issue_codes = {
        str(code or "").strip().lower()
        for code in (item.get("driving_issue_codes") or [])
        if str(code or "").strip()
      }
      if driving_issue_codes and driving_issue_codes.isdisjoint(issue_code_set):
        continue
    for lever_id in (item.get("required_lever_ids") or []):
      lever = str(lever_id or "").strip()
      if lever and lever not in eligible:
        eligible.append(lever)
  if eligible:
    return eligible
  return []

def _derive_solver_allowed_lever_ids(
  *,
  action: Dict[str, Any],
  translated_controls: Optional[List[Dict[str, Any]]] = None,
  translated_updates: Optional[List[Dict[str, Any]]] = None,
  eligible_lever_ids: Optional[List[str]] = None,
) -> List[str]:
  out: List[str] = []
  for item in (action.get("solver_allowed_lever_ids") or []):
    lever = str(item).strip()
    if lever and lever not in out:
      out.append(lever)
  for item in (translated_controls or []):
    lever = str((item or {}).get("lever_id") or "").strip()
    if lever and lever not in out:
      out.append(lever)
  for item in (translated_updates or []):
    lever = str((item or {}).get("lever_id") or "").strip()
    if lever and lever not in out:
      out.append(lever)
  eligible = [
    str(item or "").strip()
    for item in (eligible_lever_ids or [])
    if str(item or "").strip()
  ]
  if not eligible:
    return out
  filtered = [lever for lever in out if lever in eligible]
  return filtered or eligible

def _action_package_solver_ready(action_package: Optional[Dict[str, Any]]) -> bool:
  action = action_package if isinstance(action_package, dict) else {}
  allowed_lever_ids = [
    str(item or "").strip()
    for item in (action.get("solver_allowed_lever_ids") or [])
    if str(item or "").strip()
  ]
  quarter_target_metrics = [
    item for item in (action.get("quarter_target_metrics") or [])
    if isinstance(item, dict)
  ]
  return bool(allowed_lever_ids and quarter_target_metrics)

def _solver_ready_touched_lever_ids(
  translated_action_packages: Optional[List[Dict[str, Any]]],
) -> List[str]:
  out: List[str] = []
  for action in [item for item in (translated_action_packages or []) if isinstance(item, dict)]:
    if not _action_package_solver_ready(action):
      continue
    for lever_id in (action.get("solver_allowed_lever_ids") or []):
      lever = str(lever_id or "").strip()
      if lever and lever not in out:
        out.append(lever)
  return out

def _review_plan_has_solver_ready_actions(review_plan: Optional[Dict[str, Any]]) -> bool:
  return any(
    _action_package_solver_ready(action)
    for action in ((review_plan or {}).get("translated_action_packages") or [])
    if isinstance(action, dict)
  )

def _relevant_solver_target_quarters(
  numeric_solver_contract: Optional[Dict[str, Any]],
) -> List[int]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  explicit_quarters = sorted(
    {
      int(_safe_float(item) or 0)
      for item in (contract.get("required_target_quarters") or [])
      if int(_safe_float(item) or 0) >= 1
    }
  )
  if explicit_quarters:
    return explicit_quarters
  if str(contract.get("pass_name") or "").strip().lower() == "unified_convergence":
    target_grid_quarters = sorted(
      {
        int(_safe_float(item.get("quarter_index")) or 0)
        for item in (contract.get("quarter_target_grid") or [])
        if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
      }
    )
    if target_grid_quarters:
      return target_grid_quarters
    baseline_quarters = sorted(
      {
        int(_safe_float(item.get("quarter_index")) or 0)
        for item in (contract.get("baseline_quarter_metrics") or [])
        if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
      }
    )
    if baseline_quarters:
      return baseline_quarters
    return list(range(1, _contract_forecast_quarter_count() + 1))
  quarters = sorted(
    {
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in (contract.get("quarter_target_grid") or [])
      if (
        isinstance(item, dict)
        and int(_safe_float(item.get("quarter_index")) or 0) >= 1
        and (
          (item.get("target_metric_groups") or [])
          or (item.get("driving_issue_codes") or [])
          or (item.get("required_lever_ids") or [])
        )
      )
    }
  )
  return quarters

def _target_verification_requires_retry(
  result_payload: Optional[Dict[str, Any]],
) -> bool:
  payload = result_payload if isinstance(result_payload, dict) else {}
  target_verification = (
    payload.get("target_verification")
    if isinstance(payload.get("target_verification"), dict)
    else {}
  )
  return str(target_verification.get("controller_state") or "").strip().lower() == "retry_required"

def _set_target_verification_controller_state(
  result_payload: Optional[Dict[str, Any]],
  *,
  controller_state: str,
  reason: str,
) -> None:
  if not isinstance(result_payload, dict):
    return
  target_verification = (
    result_payload.get("target_verification")
    if isinstance(result_payload.get("target_verification"), dict)
    else {}
  )
  updated = copy.deepcopy(target_verification)
  updated["controller_state"] = str(controller_state or "").strip()
  updated["controller_reason"] = str(reason or "").strip()
  result_payload["target_verification"] = updated

def _controller_retry_stage_for_attempt(attempt_number: int) -> str:
  del attempt_number
  return "adaptive"

def _flatten_quarter_targets(review_plan: Optional[Dict[str, Any]]) -> Dict[str, float]:
  flattened: Dict[str, float] = {}
  for action in ((review_plan or {}).get("translated_action_packages") or []):
    if not isinstance(action, dict):
      continue
    for item in (action.get("quarter_target_metrics") or []):
      if not isinstance(item, dict):
        continue
      quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
      if quarter_index < 1:
        continue
      for metric_name, raw_value in item.items():
        if str(metric_name or "").strip().lower() == "quarter_index":
          continue
        numeric_value = _safe_float(raw_value)
        if numeric_value is None:
          continue
        flattened[f"q{quarter_index}:{str(metric_name or '').strip().lower()}"] = float(numeric_value)
  return flattened

def _materially_same_target_maps(
  current_targets: Optional[Dict[str, float]],
  prior_targets: Optional[Dict[str, float]],
) -> bool:
  current = current_targets if isinstance(current_targets, dict) else {}
  prior = prior_targets if isinstance(prior_targets, dict) else {}
  if set(current.keys()) != set(prior.keys()):
    return False
  for key in current.keys():
    current_value = float(_safe_float(current.get(key)) or 0.0)
    prior_value = float(_safe_float(prior.get(key)) or 0.0)
    tolerance = max(100.0, abs(prior_value) * 0.01)
    if abs(current_value - prior_value) > tolerance:
      return False
  return True

def _extract_pass_retry_candidate_signature(
  review_plan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  translated_actions = [
    item
    for item in ((review_plan or {}).get("translated_action_packages") or [])
    if isinstance(item, dict)
  ]
  lever_sets: List[List[str]] = []
  all_levers: List[str] = []
  control_sections: List[str] = []
  lever_control_direction_scores: Dict[str, int] = {}
  lever_control_summaries: List[Dict[str, Any]] = []
  for action in translated_actions:
    current_levers = sorted(
      {
        str(item.get("lever_id") or "").strip()
        for item in (action.get("translated_controls") or [])
        if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
      }
    )
    lever_sets.append(current_levers)
    all_levers.extend(current_levers)
    control_sections.extend(
      [
        str(item.get("section") or "").strip().lower()
        for item in (action.get("translated_controls") or [])
        if isinstance(item, dict) and str(item.get("section") or "").strip()
      ]
    )
    for control in (action.get("translated_controls") or []):
      if not isinstance(control, dict):
        continue
      lever_id = str(control.get("lever_id") or "").strip()
      if not lever_id:
        continue
      direction = str(control.get("direction") or "").strip().lower()
      direction_score = 0
      if direction == "increase":
        direction_score = 1
      elif direction == "decrease":
        direction_score = -1
      lever_control_direction_scores[lever_id] = int(
        lever_control_direction_scores.get(lever_id, 0) + direction_score
      )
      lever_control_summaries.append(
        {
          "lever_id": lever_id,
          "direction": direction,
          "control_mode": str(control.get("control_mode") or "").strip().lower() or None,
          "timing_start_q": int(_safe_float(control.get("timing_start_q")) or 0) or None,
          "timing_end_q": int(_safe_float(control.get("timing_end_q")) or 0) or None,
        }
      )
  unique_levers = sorted({item for item in all_levers if item})
  unique_sections = sorted({item for item in control_sections if item})
  flattened_targets = _flatten_quarter_targets(review_plan)
  targeted_quarters = sorted(
    {
      int(str(key).split(":", 1)[0].replace("q", "").strip())
      for key in flattened_targets.keys()
      if str(key).startswith("q") and ":" in str(key)
    }
  )
  target_metric_names = sorted(
    {
      str(key).split(":", 1)[1].strip().lower()
      for key in flattened_targets.keys()
      if ":" in str(key)
    }
  )
  return {
    "action_count": len(translated_actions),
    "focus_issue_codes": copy.deepcopy(
      [
        str(item).strip().lower()
        for item in (
          (review_plan or {}).get("focus_issue_codes")
          if isinstance((review_plan or {}).get("focus_issue_codes"), list)
          else [
            str(item.get("issue_code") or "").strip().lower()
            for item in (
              ((review_plan or {}).get("numeric_solver_contract") or {}).get("issue_target_packets")
              if isinstance(((review_plan or {}).get("numeric_solver_contract") or {}).get("issue_target_packets"), list)
              else []
            )
            if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
          ]
        )
        if str(item).strip()
      ]
    ),
    "lever_sets": copy.deepcopy(lever_sets),
    "lever_set_union": copy.deepcopy(unique_levers),
    "lever_set_union_key": "|".join(unique_levers),
    "control_sections": copy.deepcopy(unique_sections),
    "targeted_quarters": copy.deepcopy(targeted_quarters),
    "target_metric_names": copy.deepcopy(target_metric_names),
    "quarter_targets": copy.deepcopy(flattened_targets),
    "quarter_target_key": json.dumps(flattened_targets, sort_keys=True),
    "lever_control_directions": {
      lever_id: (
        "increase"
        if score > 0
        else "decrease"
        if score < 0
        else "hold"
      )
      for lever_id, score in sorted(lever_control_direction_scores.items())
      if str(lever_id).strip()
    },
    "lever_control_summaries": copy.deepcopy(lever_control_summaries),
  }

def _extract_result_retry_signature(
  result_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  payload = result_payload if isinstance(result_payload, dict) else {}
  execution_outcome = (
    payload.get("numeric_execution_outcome")
    if isinstance(payload.get("numeric_execution_outcome"), dict)
    else {}
  )
  quarter_fit_summary = [
    item for item in (execution_outcome.get("quarter_fit_summary") or []) if isinstance(item, dict)
  ]
  quarter_results = [
    item for item in (execution_outcome.get("quarter_results") or []) if isinstance(item, dict)
  ]
  failed_quarters = sorted(
    {
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in quarter_fit_summary
      if int(_safe_float(item.get("quarter_index")) or 0) >= 1
      and not bool(item.get("within_tolerance_all_targets"))
    }
  )
  failed_metrics: List[str] = []
  residual_total = 0.0
  for item in quarter_results:
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    target_metrics = item.get("target_metrics") if isinstance(item.get("target_metrics"), dict) else {}
    for metric_name, metric_payload in target_metrics.items():
      if not isinstance(metric_payload, dict):
        continue
      residual = float(_safe_float(metric_payload.get("residual_after_tolerance")) or 0.0)
      residual_total += residual
      if residual > 1e-9 and quarter_index >= 1:
        failed_metrics.append(f"q{quarter_index}:{str(metric_name or '').strip().lower()}")
  return {
    "failed_quarters": copy.deepcopy(failed_quarters),
    "failed_metrics": sorted(set(failed_metrics)),
    "failed_metric_count": len(set(failed_metrics)),
    "total_residual_after_tolerance": float(residual_total),
    "quarters_with_target_misses": int(
      _safe_float(execution_outcome.get("quarters_with_target_misses")) or len(failed_quarters)
    ),
    "quarters_with_all_targets_within_tolerance": int(
      _safe_float(execution_outcome.get("quarters_with_all_targets_within_tolerance")) or 0
    ),
    "objective_delta": float(_safe_float(execution_outcome.get("objective_delta")) or 0.0),
  }

def _required_retry_levers_for_failed_quarters(
  numeric_solver_contract: Optional[Dict[str, Any]],
  failed_quarters: Optional[List[int]],
) -> List[str]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  failed_quarter_set = {
    int(_safe_float(item) or 0)
    for item in (failed_quarters or [])
    if int(_safe_float(item) or 0) >= 1
  }
  required: List[str] = []
  for item in (contract.get("quarter_target_grid") or []):
    if not isinstance(item, dict):
      continue
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    if quarter_index < 1 or quarter_index not in failed_quarter_set:
      continue
    for lever_id in (item.get("required_lever_ids") or []):
      lever = str(lever_id or "").strip()
      if lever and lever not in required:
        required.append(lever)
  return sorted(required)

def _bounded_tail(items: Any, max_items: int) -> List[Any]:
  normalized = list(items or [])
  if max_items <= 0:
    return []
  if len(normalized) <= max_items:
    return normalized
  return normalized[-max_items:]

def _compact_retry_attempt_record(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = record if isinstance(record, dict) else {}
  controller_context = (
    payload.get("controller_retry_context")
    if isinstance(payload.get("controller_retry_context"), dict)
    else {}
  )
  candidate_signature = (
    payload.get("candidate_signature")
    if isinstance(payload.get("candidate_signature"), dict)
    else {}
  )
  result_signature = (
    payload.get("result_signature")
    if isinstance(payload.get("result_signature"), dict)
    else {}
  )
  rejection = payload.get("rejection") if isinstance(payload.get("rejection"), dict) else {}
  improvement_summary = (
    payload.get("improvement_summary")
    if isinstance(payload.get("improvement_summary"), dict)
    else {}
  )
  return {
    "attempt_number": int(_safe_float(payload.get("attempt_number")) or 0),
    "attempt_stage": str(payload.get("attempt_stage") or "").strip(),
    "status": str(payload.get("status") or "").strip(),
    "controller_retry_context": {
      "pass_name": str(controller_context.get("pass_name") or "").strip(),
      "pass_label": str(controller_context.get("pass_label") or "").strip(),
      "attempt_number": int(_safe_float(controller_context.get("attempt_number")) or 0),
      "attempt_stage": str(controller_context.get("attempt_stage") or "").strip(),
      "previous_attempt_count": int(_safe_float(controller_context.get("previous_attempt_count")) or 0),
      "issues_remaining": int(_safe_float(controller_context.get("issues_remaining")) or 0),
      "progress_status": str(controller_context.get("progress_status") or "").strip(),
      "last_failure_reason": str(controller_context.get("last_failure_reason") or "").strip(),
      "required_open_issue_codes": copy.deepcopy(controller_context.get("required_open_issue_codes") or []),
      "required_primary_metric_candidates": copy.deepcopy(
        controller_context.get("required_primary_metric_candidates") or []
      ),
      "minimum_primary_metric_coverage_count": int(
        _safe_float(controller_context.get("minimum_primary_metric_coverage_count")) or 0
      ),
    },
    "candidate_signature": {
      "lever_set_union": copy.deepcopy(candidate_signature.get("lever_set_union") or []),
      "targeted_quarters": copy.deepcopy(candidate_signature.get("targeted_quarters") or []),
      "target_metric_names": copy.deepcopy(candidate_signature.get("target_metric_names") or []),
      "quarter_target_key": str(candidate_signature.get("quarter_target_key") or "").strip(),
      "control_sections": copy.deepcopy(candidate_signature.get("control_sections") or []),
    },
    "result_signature": {
      "failed_quarters": copy.deepcopy(result_signature.get("failed_quarters") or []),
      "failed_metrics": copy.deepcopy(result_signature.get("failed_metrics") or []),
      "total_residual_after_tolerance": float(
        _safe_float(result_signature.get("total_residual_after_tolerance")) or 0.0
      ),
    },
    "rejection": {
      "reason_code": str(rejection.get("reason_code") or "").strip(),
      "reason": str(rejection.get("reason") or "").strip(),
    },
    "improvement_summary": copy.deepcopy(improvement_summary),
  }

def _compact_retry_memory_snapshot(retry_memory: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  memory = retry_memory if isinstance(retry_memory, dict) else {}
  return {
    "completed_attempt_count": int(_safe_float(memory.get("completed_attempt_count")) or 0),
    "prior_lever_unions": copy.deepcopy(
      _bounded_tail(memory.get("prior_lever_unions") or [], _RETRY_MEMORY_MAX_PRIOR_LEVER_UNIONS)
    ),
    "prior_target_keys": copy.deepcopy(
      _bounded_tail(memory.get("prior_target_keys") or [], _RETRY_MEMORY_MAX_PRIOR_TARGET_KEYS)
    ),
    "latest_candidate_signature": copy.deepcopy(memory.get("latest_candidate_signature") or {}),
    "latest_result_signature": copy.deepcopy(memory.get("latest_result_signature") or {}),
    "latest_improvement_summary": copy.deepcopy(memory.get("latest_improvement_summary") or {}),
    "latest_validation_error": copy.deepcopy(memory.get("latest_validation_error") or {}),
    "recent_validation_errors": copy.deepcopy(
      _bounded_tail(memory.get("recent_validation_errors") or [], _RETRY_MEMORY_MAX_VALIDATION_ERRORS)
    ),
    "prior_controller_state_summary": copy.deepcopy(memory.get("prior_controller_state_summary") or {}),
    "latest_controller_state_summary": copy.deepcopy(memory.get("latest_controller_state_summary") or {}),
    "attempt_records": [
      _compact_retry_attempt_record(item)
      for item in _bounded_tail(memory.get("attempt_records") or [], _RETRY_MEMORY_MAX_ATTEMPT_RECORDS)
      if isinstance(item, dict)
    ],
  }

def _retry_validation_correction_grid(retry_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  context = retry_context if isinstance(retry_context, dict) else {}
  latest_error = (
    context.get("latest_validation_error")
    if isinstance(context.get("latest_validation_error"), dict)
    else {}
  )
  recent_errors = [
    item for item in (context.get("recent_validation_errors") or [])
    if isinstance(item, dict)
  ]
  reason_text = " ".join(
    str(item.get("reason") or "").strip()
    for item in [latest_error, *recent_errors]
    if str(item.get("reason") or "").strip()
  )
  corrections: List[Dict[str, Any]] = []
  for match in re.finditer(
    r"(?P<lever_id>[^:;]+::[^:;]+::[^:;]+): value (?P<value>[-+]?\d+(?:\.\d+)?) is outside deterministic bounds \[(?P<min>[-+]?\d+(?:\.\d+)?),\s*(?P<max>[-+]?\d+(?:\.\d+)?)\]",
    reason_text,
  ):
    lever_id = str(match.group("lever_id") or "").strip()
    if not lever_id:
      continue
    corrections.append(
      {
        "error": "lever_value_outside_locked_grid_bounds",
        "lever_id": lever_id,
        "rejected_value": _safe_float(match.group("value")),
        "min_allowed": _safe_float(match.group("min")),
        "max_allowed": _safe_float(match.group("max")),
        "required_fix": (
          "If this lever is selected again, every exact_value, min_value, max_value, "
          "values, and trajectory_values entry must stay inside min_allowed/max_allowed."
        ),
      }
    )
  return {
    "contract_version": "retry_validation_correction_grid_v1",
    "rows": corrections,
  }

def _build_pass_retry_context(
  *,
  pass_name: str,
  pass_label: str,
  attempt_number: int,
  max_attempts: int,
  retry_memory: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  memory = _compact_retry_memory_snapshot(retry_memory)
  previous_result = (
    memory.get("latest_result_signature")
    if isinstance(memory.get("latest_result_signature"), dict)
    else {}
  )
  previous_candidate = (
    memory.get("latest_candidate_signature")
    if isinstance(memory.get("latest_candidate_signature"), dict)
    else {}
  )
  latest_validation_error = (
    memory.get("latest_validation_error")
    if isinstance(memory.get("latest_validation_error"), dict)
    else {}
  )
  recent_validation_errors = [
    item
    for item in (memory.get("recent_validation_errors") or [])
    if isinstance(item, dict)
  ]
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  writable_entries = [
    item
    for item in ((((contract.get("writable_lever_catalog") or {}) if isinstance(contract.get("writable_lever_catalog"), dict) else {}).get("entries") or []))
    if isinstance(item, dict)
  ]
  all_writable_lever_ids = [
    str(item.get("lever_id") or "").strip()
    for item in writable_entries
    if str(item.get("lever_id") or "").strip()
  ]
  previous_allowed_lever_ids = copy.deepcopy(previous_candidate.get("lever_set_union") or [])
  expansion_candidate_lever_ids = [
    lever_id
    for lever_id in all_writable_lever_ids
    if lever_id and lever_id not in set(previous_allowed_lever_ids)
  ]
  base_instruction = (
    "If this pass is retrying, use the prior result telemetry to change the business move in a meaningful way. "
    "You are not being asked to satisfy a stage ladder. You are being asked to produce a better full-business package."
  )
  latest_validation_reason = str(latest_validation_error.get("reason") or "").strip()
  latest_validation_reason_code = str(latest_validation_error.get("reason_code") or "").strip()
  if latest_validation_reason:
    base_instruction += (
      f" The prior planner package was rejected by Python before solver execution for "
      f"{latest_validation_reason_code or 'retry_discipline'}: {latest_validation_reason}"
    )
  return {
    "pass_name": str(pass_name or "").strip(),
    "pass_label": str(pass_label or "").strip(),
    "attempt_number": int(attempt_number or 1),
    "attempt_stage": _controller_retry_stage_for_attempt(attempt_number),
    "max_attempts": int(max_attempts or 1),
    "previous_attempt_count": int(_safe_float(memory.get("completed_attempt_count")) or 0),
    "prior_lever_unions": copy.deepcopy(memory.get("prior_lever_unions") or []),
    "prior_target_keys": copy.deepcopy(memory.get("prior_target_keys") or []),
    "previous_failed_quarters": copy.deepcopy(previous_result.get("failed_quarters") or []),
    "previous_failed_metrics": copy.deepcopy(previous_result.get("failed_metrics") or []),
    "previous_total_residual_after_tolerance": float(
      _safe_float(previous_result.get("total_residual_after_tolerance")) or 0.0
    ),
    "previous_allowed_lever_ids": previous_allowed_lever_ids,
    "all_writable_lever_ids": all_writable_lever_ids,
    "expansion_candidate_lever_ids": expansion_candidate_lever_ids,
    "required_retry_lever_ids_for_failed_quarters": _required_retry_levers_for_failed_quarters(
      numeric_solver_contract,
      previous_result.get("failed_quarters") or [],
    ),
    "latest_validation_error": copy.deepcopy(latest_validation_error),
    "latest_validation_reason_code": latest_validation_reason_code,
    "recent_validation_errors": copy.deepcopy(recent_validation_errors[-3:]),
    "controller_retry_rules": {
      "execution_first": True,
      "post_execution_progress_governs": True,
      "focused_cycle_scope": True,
      "use_authorized_levers_only": True,
      "target_coverage_must_match_required_scope": True,
    },
    "instruction": base_instruction,
  }

def _pre_solver_validation_failure_diagnostics(
  *,
  unified_convergence_plan: Optional[Dict[str, Any]],
  validation_error: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  plan = unified_convergence_plan if isinstance(unified_convergence_plan, dict) else {}
  error = validation_error if isinstance(validation_error, dict) else {}
  pre_solver_validation = (
    plan.get("pre_solver_validation")
    if isinstance(plan.get("pre_solver_validation"), dict)
    else {
      "stage": "pre_solver_validation",
      "status": "failed",
      "flags": [str(error.get("reason_code") or "pre_solver_validation_failed").strip()],
      "errors": [
        {
          "error": str(error.get("reason_code") or "pre_solver_validation_failed").strip(),
          "reason": str(error.get("reason") or "").strip(),
          "validation_category": "planner_contract",
        }
      ],
    }
  )
  return {
    "failure_stage": "pre_solver_validation",
    "failure_reason": str(error.get("reason_code") or "pre_solver_validation_failed").strip(),
    "solver_invoked": False,
    "validation_error": copy.deepcopy(error),
    "pre_solver_validation": copy.deepcopy(pre_solver_validation),
    "planner_status": str(plan.get("status") or "").strip() or None,
    "planner_next_step": str(plan.get("next_step") or "").strip() or None,
    "selected_cash_strategy": str(plan.get("selected_cash_strategy") or "").strip() or None,
    "active_issue_count": (
      int(_safe_float((plan.get("numeric_solver_contract") or {}).get("active_issue_count")) or 0)
      if isinstance(plan.get("numeric_solver_contract"), dict)
      else None
    ),
  }

def _first_contract_product_missing_periods(obj: Any) -> Optional[Dict[str, Any]]:
  if not isinstance(obj, dict):
    return None
  lob_models = obj.get("lob_models")
  if isinstance(lob_models, list):
    for lob in lob_models:
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product in products:
        if not isinstance(product, dict):
          continue
        if str(product.get("unit_cadence") or "").strip().lower() != "contract":
          continue
        if _is_missing_number_value(product.get("operating_periods_per_year")):
          return product
    return None
  if str(obj.get("unit_cadence") or "").strip().lower() != "contract":
    return None
  if _is_missing_number_value(obj.get("operating_periods_per_year")):
    return obj
  return None

def _compact_numeric_solver_contract_for_storage(contract: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = copy.deepcopy(contract if isinstance(contract, dict) else {})
  issue_packets = []
  for item in (payload.get("issue_target_packets") or []):
    if not isinstance(item, dict):
      continue
    next_required_lever_ids = [
      str(lever_id).strip()
      for lever_id in (
        item.get("next_required_lever_ids")
        or item.get("candidate_lever_ids")
        or [
          path.get("lever")
          for repair_target in (item.get("repair_targets") or [])
          if isinstance(repair_target, dict)
          for path in (repair_target.get("driver_paths") or [])
          if isinstance(path, dict) and str(path.get("lever") or "").strip()
        ]
      )
      if str(lever_id).strip()
    ]
    metric_targets = [
      str(metric_name).strip()
      for metric_name in (
        item.get("metric_targets")
        or post_intake_direct_target_metric_names_for_levers(next_required_lever_ids)
      )
      if str(metric_name).strip()
    ]
    issue_packets.append(
      {
        "issue_code": str(item.get("issue_code") or "").strip(),
        "remaining_issue_materiality": copy.deepcopy(item.get("remaining_issue_materiality")),
        "remaining_issue_severity_score": copy.deepcopy(item.get("remaining_issue_severity_score")),
        "remaining_problem_quarters": copy.deepcopy(
          item.get("remaining_problem_quarters")
          or item.get("affected_quarters")
          or []
        ),
        "metric_targets": copy.deepcopy(item.get("metric_targets") or metric_targets),
        "next_required_lever_ids": copy.deepcopy(next_required_lever_ids),
        "solver_objective": copy.deepcopy(
          item.get("solver_objective")
          or item.get("root_cause")
          or item.get("summary")
        ),
      }
    )
  quarter_grid = []
  for item in (payload.get("quarter_target_grid") or []):
    if not isinstance(item, dict):
      continue
    quarter_grid.append(
      {
        "quarter_index": copy.deepcopy(item.get("quarter_index")),
        "target_metric_groups": copy.deepcopy(item.get("target_metric_groups") or []),
        "driving_issue_codes": copy.deepcopy(item.get("driving_issue_codes") or []),
        "required_lever_ids": copy.deepcopy(item.get("required_lever_ids") or []),
      }
    )
  writable_catalog = payload.get("writable_lever_catalog") if isinstance(payload.get("writable_lever_catalog"), dict) else {}
  payload["issue_target_packets"] = issue_packets
  payload["quarter_target_grid"] = quarter_grid
  payload["writable_lever_catalog"] = {
    **copy.deepcopy(writable_catalog),
    "entries": _compact_writable_lever_catalog_entries(writable_catalog.get("entries") or []),
  }
  return payload

def _compact_retry_memory_for_storage(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  retry_memory = payload if isinstance(payload, dict) else {}
  return {
    "attempt_count": int(_safe_float(retry_memory.get("attempt_count")) or 0),
    "latest_validation_error": copy.deepcopy(retry_memory.get("latest_validation_error") or {}),
    "latest_candidate_signature": copy.deepcopy(retry_memory.get("latest_candidate_signature") or {}),
    "latest_result_signature": copy.deepcopy(retry_memory.get("latest_result_signature") or {}),
    "recent_validation_errors": copy.deepcopy((retry_memory.get("recent_validation_errors") or [])[-5:]),
  }

def _realism_metric_series(
  finmo_payload: Optional[Dict[str, Any]],
  *,
  metric: str,
) -> List[float]:
  metric_norm = str(metric or "").strip().lower().replace(" ", "_")
  metric_key_map = {
    "revenue": "revenue",
    "ebitda": "ebitda",
    "cash": "ending_cash",
    "net_income": "net_income",
  }
  key = metric_key_map.get(metric_norm, metric_norm)
  series: List[float] = []
  for row in _cash_review_quarter_metrics(finmo_payload):
    series.append(float(_safe_float(row.get(key)) or 0.0))
  return series

def _lever_catalog_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
  out: Dict[str, Dict[str, Any]] = {}
  for item in _build_writable_lever_review_catalog(model_input_json):
    lever_id = str(item.get("lever_id") or "").strip()
    if lever_id:
      out[lever_id] = dict(item)
  return out

def _relative_move_limit(
  *,
  baseline_value: float,
  max_relative_change: float,
  value_kind: str,
  input_semantics: str,
) -> float:
  baseline_abs = abs(float(baseline_value or 0.0))
  max_rel = max(0.0, min(1.0, float(max_relative_change or 0.0)))
  value_kind_norm = str(value_kind or "").strip().lower()
  semantics_norm = str(input_semantics or "").strip().lower()
  if value_kind_norm == "ratio":
    anchor = max(baseline_abs, 0.05)
    return min(0.5, anchor * max_rel)
  if value_kind_norm == "day_count":
    anchor = max(baseline_abs, 5.0)
    return max(1.0, anchor * max_rel)
  if "percent_of_revenue" in semantics_norm or "percent_of_long_term_debt" in semantics_norm:
    anchor = max(baseline_abs, 0.05)
    return min(0.5, anchor * max_rel)
  anchor = max(baseline_abs, 1.0)
  return anchor * max_rel

def _translate_realism_lever_adjustment(
  *,
  adjustment: Dict[str, Any],
  baseline_map: Dict[str, List[float]],
  lever_catalog_map: Dict[str, Dict[str, Any]],
  quarter_count: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
  lever_id = str(adjustment.get("lever_id") or "").strip()
  if not lever_id:
    return None, "missing lever_id"
  baseline_values = baseline_map.get(lever_id)
  if not baseline_values:
    return None, f"unknown lever_id {lever_id}"
  quarter_index = int(_safe_float(adjustment.get("quarter_index")) or 0)
  if quarter_index < 1 or quarter_index > max(1, int(quarter_count or 0)):
    return None, f"{lever_id} has invalid quarter_index {quarter_index or 'missing'}"
  direction = str(adjustment.get("direction") or "").strip().lower()
  if direction not in {"increase", "decrease", "either", "hold"}:
    return None, f"{lever_id} has unsupported direction {direction or 'missing'}"
  max_relative_change = _safe_float(adjustment.get("max_relative_change"))
  if max_relative_change is None:
    return None, f"{lever_id} missing max_relative_change"
  max_relative_change = max(0.0, min(1.0, float(max_relative_change)))
  meta = lever_catalog_map.get(lever_id) or {}
  baseline_window = _baseline_window_summary(baseline_values, start_q=quarter_index, end_q=quarter_index)
  baseline_value = float(_safe_float(baseline_window.get("value_end")) or 0.0)
  move_limit = _relative_move_limit(
    baseline_value=baseline_value,
    max_relative_change=max_relative_change,
    value_kind=str(meta.get("value_kind") or "").strip(),
    input_semantics=str(meta.get("input_semantics") or "").strip(),
  )
  if direction == "hold":
    min_value = baseline_value - move_limit
    max_value = baseline_value + move_limit
  elif direction == "increase":
    min_value = baseline_value
    max_value = baseline_value + move_limit
  elif direction == "decrease":
    min_value = baseline_value - move_limit
    max_value = baseline_value
  else:
    min_value = baseline_value - move_limit
    max_value = baseline_value + move_limit
  value_kind = str(meta.get("value_kind") or "").strip().lower()
  input_semantics = str(meta.get("input_semantics") or "").strip().lower()
  translated_min_raw = float(min(min_value, max_value))
  translated_max_raw = float(max(min_value, max_value))
  translated_min_value = post_intake_normalize_lever_value(
    lever_id,
    translated_min_raw,
    bound_side="minimum",
  )
  translated_max_value = post_intake_normalize_lever_value(
    lever_id,
    translated_max_raw,
    bound_side="maximum",
  )

  translated = {
    "lever_id": lever_id,
    "section": str(adjustment.get("section") or meta.get("section") or "").strip(),
    "direction": direction,
    "control_mode": "band",
    "quarter_index": quarter_index,
    "baseline_window": baseline_window,
    "business_reason": str(adjustment.get("business_reason") or "").strip(),
    "linked_action_effect": str(adjustment.get("linked_action_effect") or "").strip(),
    "mapped_repair_targets": _normalize_unified_mapped_repair_targets(
      adjustment.get("mapped_repair_targets") or []
    ),
    "max_relative_change": max_relative_change,
    "exact_value": None,
    "min_value": translated_min_value,
    "max_value": translated_max_value,
  }
  return translated, None

def _translate_realism_output_target(
  *,
  target: Dict[str, Any],
  finmo_json: Optional[Dict[str, Any]],
  quarter_count: int,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
  metric = str(target.get("metric") or "").strip()
  if not metric:
    return [], "missing target metric"
  quarter_index = int(_safe_float(target.get("quarter_index")) or 0)
  if quarter_index < 1 or quarter_index > max(1, int(quarter_count or 0)):
    return [], f"{metric} has invalid quarter_index {quarter_index or 'missing'}"
  direction = str(target.get("direction") or "").strip().lower()
  if direction not in {"increase", "decrease", "hold"}:
    return [], f"{metric} has unsupported direction {direction or 'missing'}"
  min_relative_change = _safe_float(target.get("min_relative_change"))
  max_relative_change = _safe_float(target.get("max_relative_change"))
  if min_relative_change is None or max_relative_change is None:
    return [], f"{metric} missing min_relative_change or max_relative_change"
  low_rel = max(0.0, min(1.0, float(min(min_relative_change, max_relative_change))))
  high_rel = max(0.0, min(1.0, float(max(min_relative_change, max_relative_change))))
  baseline_series = _realism_metric_series(finmo_json, metric=metric)
  if not baseline_series:
    return [], f"{metric} has no baseline series"

  base_value = float(_safe_float(baseline_series[quarter_index - 1]) or 0.0)
  scale = max(abs(base_value), 1.0)
  if direction == "increase":
    min_value = base_value + (low_rel * scale)
    max_value = base_value + (high_rel * scale)
  elif direction == "decrease":
    min_value = base_value - (high_rel * scale)
    max_value = base_value - (low_rel * scale)
  else:
    min_value = base_value - (high_rel * scale)
    max_value = base_value + (high_rel * scale)
  return (
    [
      {
        "metric": metric,
        "quarter_index": quarter_index,
        "direction": direction,
        "baseline_value": int(round(base_value)),
        "min_value": int(round(float(min(min_value, max_value)))),
        "max_value": int(round(float(max(min_value, max_value)))),
        "business_reason": str(target.get("business_reason") or "").strip(),
      }
    ],
    None,
  )

def _extract_controller_lever_catalog(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  direct = [
    item
    for item in (model_input.get("controller_write_levers") or [])
    if isinstance(item, dict)
    and bool(item.get("controller_write", True))
    and str(item.get("lever_id") or "").strip()
    and str(item.get("lever_id") or "").strip() != "expenses::Payroll"
  ]
  if direct:
    return direct
  lever_catalog = model_input.get("lever_catalog") if isinstance(model_input.get("lever_catalog"), dict) else {}
  return [
    item
    for item in lever_catalog.values()
    if isinstance(item, dict)
    and bool(item.get("controller_write", True))
    and str(item.get("lever_id") or "").strip()
    and str(item.get("lever_id") or "").strip() != "expenses::Payroll"
  ]

def _lever_usage_guidance(lever_id: str) -> Dict[str, Any]:
  mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
  driver_category = str(mapping_entry.get("driver_category") or "").strip().lower()
  target_driver = str(mapping_entry.get("target_driver") or "").strip().lower()
  target_metric_name = str(mapping_entry.get("target_metric_name") or "").strip().lower()
  if not driver_category and not target_driver and not target_metric_name:
    return {}
  role_parts = [item for item in (driver_category, target_driver or target_metric_name) if item]
  return {
    "accounting_role": "_".join(role_parts),
    "preferred_uses": [],
    "forbidden_uses": [],
  }

def _canonical_writable_lever_value_metadata(
  *,
  lever_id: Any,
  value_kind: Any,
  input_semantics: Any,
) -> Dict[str, str]:
  mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
  table_value_kind = str(mapping_entry.get("value_kind") or "").strip()
  table_input_semantics = str(mapping_entry.get("input_semantics") or "").strip()
  if table_value_kind or table_input_semantics:
    return {
      "value_kind": table_value_kind,
      "input_semantics": table_input_semantics,
    }
  return {
    "value_kind": str(value_kind or "").strip(),
    "input_semantics": str(input_semantics or "").strip(),
  }

def _build_writable_lever_review_catalog(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  review_catalog: List[Dict[str, Any]] = []
  for item in _extract_controller_lever_catalog(model_input_json):
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    mapping_entry = post_intake_driver_target_mapping_entry(lever_id) or {}
    if not mapping_entry:
      raise RuntimeError(
        f"post_intake_driver_target_mapping_missing_lever_catalog_entry: {lever_id}"
      )
    guidance = _lever_usage_guidance(lever_id)
    canonical_value_meta = _canonical_writable_lever_value_metadata(
      lever_id=lever_id,
      value_kind=item.get("value_kind"),
      input_semantics=item.get("input_semantics"),
    )
    review_catalog.append(
      {
        "lever_id": lever_id,
        "section": str(item.get("section") or "").strip(),
        "label_path": str(item.get("label_path") or "").strip(),
        "driver": str(item.get("driver") or item.get("label") or "").strip(),
        "lob": str(item.get("lob") or "").strip(),
        "product": str(item.get("product") or "").strip(),
        "value_kind": str(canonical_value_meta.get("value_kind") or "").strip(),
        "input_semantics": str(canonical_value_meta.get("input_semantics") or "").strip(),
        "post_intake_phase": str(mapping_entry.get("post_intake_phase") or "").strip(),
        "control_owner": str(mapping_entry.get("control_owner") or "").strip(),
        "driver_bundle": str(mapping_entry.get("driver_bundle") or "").strip(),
        "cash_strategy_role": str(mapping_entry.get("cash_strategy_role") or "").strip(),
        "targeting_allowed": bool(mapping_entry.get("targeting_allowed")),
        "diagnostic_only": bool(mapping_entry.get("diagnostic_only")),
        "accounting_role": str(guidance.get("accounting_role") or "").strip(),
        "preferred_uses": [str(v).strip() for v in (guidance.get("preferred_uses") or []) if str(v).strip()],
        "forbidden_uses": [str(v).strip() for v in (guidance.get("forbidden_uses") or []) if str(v).strip()],
      }
    )
  return review_catalog

def _model_input_with_controller_catalog(
  *,
  model_input_json: Optional[Dict[str, Any]],
  catalog_source_model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  current = copy.deepcopy(model_input_json or {}) if isinstance(model_input_json, dict) else {}
  source = catalog_source_model_input_json if isinstance(catalog_source_model_input_json, dict) else {}
  if not current:
    current = {}
  if isinstance(source.get("canonical_lever_vocabulary"), str) and not str(current.get("canonical_lever_vocabulary") or "").strip():
    current["canonical_lever_vocabulary"] = str(source.get("canonical_lever_vocabulary") or "").strip()
  if isinstance(source.get("lever_catalog"), dict) and not isinstance(current.get("lever_catalog"), dict):
    current["lever_catalog"] = copy.deepcopy(source.get("lever_catalog") or {})
  if not _extract_controller_lever_catalog(current):
    source_catalog = _extract_controller_lever_catalog(source)
    if source_catalog:
      current["controller_write_levers"] = copy.deepcopy(source_catalog)
  return current

def _build_numeric_solver_feedback_payload(
  result_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  payload = result_payload if isinstance(result_payload, dict) else {}
  execution_plan = payload.get("numeric_execution_plan") if isinstance(payload.get("numeric_execution_plan"), dict) else {}
  execution_outcome = payload.get("numeric_execution_outcome") if isinstance(payload.get("numeric_execution_outcome"), dict) else {}
  solver_result = payload.get("numeric_solver_result") if isinstance(payload.get("numeric_solver_result"), dict) else {}
  target_verification = payload.get("target_verification") if isinstance(payload.get("target_verification"), dict) else {}
  raw_attempts = payload.get("numeric_execution_attempts") if isinstance(payload.get("numeric_execution_attempts"), list) else []
  attempts: List[Dict[str, Any]] = []
  for item in raw_attempts:
    if not isinstance(item, dict):
      continue
    attempts.append(
      {
        "attempt_index": int(_safe_float(item.get("attempt_index")) or 0),
        "quarter_index": int(_safe_float(item.get("quarter_index")) or 0) if _safe_float(item.get("quarter_index")) is not None else None,
        "optimizer_converged": (
          bool(item.get("optimizer_converged"))
          if "optimizer_converged" in item
          else (bool(item.get("success")) if "success" in item else None)
        ),
        "objective_value": _safe_float(item.get("objective_value")),
        "objective_improvement": _safe_float(item.get("objective_improvement")),
        "lever_families": [
          str(v).strip()
          for v in (item.get("lever_families") or [])
          if str(v).strip()
        ],
        "message": str(item.get("message") or "").strip(),
      }
    )
  outcome_status = str(
    execution_outcome.get("execution_state")
    or solver_result.get("execution_state")
    or execution_outcome.get("status")
    or solver_result.get("status")
    or ""
  ).strip()
  feedback = {
    "has_feedback": bool(payload),
    "numeric_executor": str(payload.get("numeric_executor") or "").strip(),
    "solver_phase_status": str(payload.get("solver_phase_status") or "").strip(),
    "telemetry_only": True,
    "attempt_budget": int(_safe_float(execution_plan.get("attempt_budget")) or 0),
    "attempt_count": len(attempts),
    "attempts": attempts,
    "quarter_results": copy.deepcopy(execution_outcome.get("quarter_results") or (solver_result.get("quarter_results") or [])),
    "quarter_fit_summary": copy.deepcopy(execution_outcome.get("quarter_fit_summary") or []),
    "targeted_quarters": [
      int(_safe_float(item) or 0)
      for item in (execution_plan.get("targeted_quarters") or [])
      if int(_safe_float(item) or 0) >= 1
    ],
    "target_metric_names": [
      str(item).strip()
      for item in (execution_plan.get("target_metric_names") or [])
      if str(item).strip()
    ],
    "allowed_lever_ids": [
      str(item).strip()
      for item in (execution_plan.get("allowed_lever_ids") or [])
      if str(item).strip()
    ],
    "required_target_metric_keys": [
      str(item).strip()
      for item in (execution_plan.get("required_target_metric_keys") or [])
      if str(item).strip()
    ],
    "target_tolerances": copy.deepcopy(execution_plan.get("target_tolerances") or []),
    "quarter_target_payloads": copy.deepcopy(execution_plan.get("quarter_target_payloads") or []),
    "execution_state": outcome_status,
    "outcome_reason": str(execution_outcome.get("reason") or (solver_result.get("outcome") or {}).get("reason") or "").strip(),
    "attempted_lever_families": [
      str(item).strip()
      for item in (execution_outcome.get("attempted_lever_families") or [])
      if str(item).strip()
    ],
    "best_objective": _safe_float(execution_outcome.get("best_objective")),
    "baseline_objective": _safe_float(execution_outcome.get("baseline_objective")),
    "objective_delta": _safe_float(execution_outcome.get("objective_delta")),
    "quarters_with_all_targets_within_tolerance": int(
      _safe_float(execution_outcome.get("quarters_with_all_targets_within_tolerance")) or 0
    ),
    "quarters_with_target_misses": int(
      _safe_float(execution_outcome.get("quarters_with_target_misses")) or 0
    ),
    "solver_invoked": bool(
      solver_result.get("solver_invoked")
      if "solver_invoked" in solver_result
      else solver_result.get("used_solver")
    ),
    "solver_execution_state": str(
      solver_result.get("execution_state") or solver_result.get("status") or ""
    ).strip(),
    "target_verification": copy.deepcopy(target_verification),
  }
  feedback["next_pass_guidance"] = (
    "Treat this as raw numeric telemetry only. The verifier/controller issue state is the only authority on whether the prior pass actually worked. "
    "Use quarter_fit_summary, quarters_with_target_misses, required_target_metric_keys, and quarter_target_payloads to see exactly which quarter-level targets were or were not hit within tolerance. "
    "If the same issue codes remain open, do not assume the prior numeric attempt worked just because the objective moved; consider a different quarter target package or a different lever set than the one already attempted."
  )
  return feedback

def _current_cycle_numeric_trace_summary(
  planning_run_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  payload = planning_run_payload if isinstance(planning_run_payload, dict) else {}
  current_cycle_packet = (
    payload.get("current_cycle_convergence_packet")
    if isinstance(payload.get("current_cycle_convergence_packet"), dict)
    else {}
  )
  if not current_cycle_packet:
    return {}
  deterministic_numeric_guidance = (
    current_cycle_packet.get("deterministic_numeric_guidance")
    if isinstance(current_cycle_packet.get("deterministic_numeric_guidance"), dict)
    else {}
  )
  plan_summary = (
    current_cycle_packet.get("plan_summary")
    if isinstance(current_cycle_packet.get("plan_summary"), dict)
    else {}
  )
  decision_summary = (
    current_cycle_packet.get("decision_summary")
    if isinstance(current_cycle_packet.get("decision_summary"), dict)
    else {}
  )
  guidance_metric_names: List[str] = []
  guidance_issue_codes: List[str] = []
  for item in (deterministic_numeric_guidance.get("metric_pressure_packets") or []):
    if not isinstance(item, dict):
      continue
    metric_name = str(item.get("metric_name") or "").strip()
    issue_code = str(item.get("issue_code") or "").strip()
    if metric_name and metric_name not in guidance_metric_names:
      guidance_metric_names.append(metric_name)
    if issue_code and issue_code not in guidance_issue_codes:
      guidance_issue_codes.append(issue_code)
  guidance_lever_ids = [
    str(item.get("lever_id") or "").strip()
    for item in (deterministic_numeric_guidance.get("lever_band_scaffold") or [])
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  ]
  decision_payload = (
    decision_summary.get("decision")
    if isinstance(decision_summary.get("decision"), dict)
    else {}
  )
  planned_target_metric_names = [
    str(item).strip()
    for item in (decision_payload.get("primary_target_metric_names") or [])
    if str(item).strip()
  ]
  planned_lever_ids = [
    str(item).strip()
    for item in (decision_payload.get("lever_selection") or [])
    if str(item).strip()
  ]
  planned_target_tolerance_metric_names = [
    str(item).strip()
    for item in (decision_payload.get("target_tolerance_metric_names") or [])
    if str(item).strip()
  ]
  cycle_debug_summary = (
    current_cycle_packet.get("cycle_debug_summary")
    if isinstance(current_cycle_packet.get("cycle_debug_summary"), dict)
    else {}
  )
  return {
    "contract_version": "current_cycle_numeric_trace_v1",
    "cycle": copy.deepcopy(current_cycle_packet.get("current_cycle")),
    "stage": str(current_cycle_packet.get("stage") or "").strip() or None,
    "status": str(current_cycle_packet.get("status") or "").strip() or None,
    "guidance_scope_quarters": copy.deepcopy(
      deterministic_numeric_guidance.get("scope_quarters") or []
    ),
    "guidance_metric_count": len(deterministic_numeric_guidance.get("metric_pressure_packets") or []),
    "guidance_metric_names": guidance_metric_names,
    "guidance_issue_codes": guidance_issue_codes,
    "guidance_lever_count": len(guidance_lever_ids),
    "guidance_lever_ids": guidance_lever_ids[:24],
    "plan_status": str(plan_summary.get("status") or "").strip() or None,
    "plan_next_step": str(plan_summary.get("next_step") or "").strip() or None,
    "driver_edit_source": str(plan_summary.get("driver_edit_source") or "").strip() or None,
    "model_input_repair_lever_count": int(
      _safe_float(plan_summary.get("model_input_repair_lever_count")) or 0
    ),
    "translated_control_count": int(
      _safe_float(plan_summary.get("translated_control_count")) or 0
    ),
    "planned_target_quarter_count": len(plan_summary.get("targets_by_quarter") or []),
    "planned_target_metric_names": planned_target_metric_names,
    "planned_target_tolerance_metric_names": planned_target_tolerance_metric_names,
    "planned_lever_ids": planned_lever_ids,
    "alignment_debug_summary": copy.deepcopy(cycle_debug_summary),
    "solver_ready": bool(
      str(plan_summary.get("status") or "").strip() == "ready"
      and int(_safe_float(plan_summary.get("translated_control_count")) or 0) > 0
      and len(plan_summary.get("targets_by_quarter") or []) > 0
    ),
  }

def _extract_numeric_solver_feedback_for_persistence(
  *,
  planning_run_payload: Optional[Dict[str, Any]] = None,
  explicit_candidates: Optional[List[tuple[str, Optional[Dict[str, Any]]]]] = None,
) -> Dict[str, Any]:
  payload = planning_run_payload if isinstance(planning_run_payload, dict) else {}
  stage = str(payload.get("stage") or "").strip()
  current_cycle_trace = _current_cycle_numeric_trace_summary(payload)
  deterministic_convergence_summary = (
    payload.get("deterministic_convergence_summary")
    if isinstance(payload.get("deterministic_convergence_summary"), dict)
    else {}
  )
  candidates: List[tuple[str, Optional[Dict[str, Any]]]] = list(explicit_candidates or [])
  if payload:
    candidates.extend(
      [
        ("unified_convergence_result", payload.get("unified_convergence_result")),
      ]
    )
    if not current_cycle_trace:
      candidates.append(("grid_application_summary", payload.get("grid_application_summary")))
  for source_name, candidate in candidates:
    if not isinstance(candidate, dict):
      continue
    feedback = _build_numeric_solver_feedback_payload(copy.deepcopy(candidate))
    if feedback.get("has_feedback"):
      feedback = _compact_numeric_feedback_for_storage(feedback)
      feedback["has_feedback"] = True
      feedback["persistence_stage"] = stage or None
      feedback["feedback_source"] = str(source_name).strip() or None
      if current_cycle_trace:
        feedback["current_cycle_trace"] = copy.deepcopy(current_cycle_trace)
      if deterministic_convergence_summary:
        feedback["deterministic_convergence_summary"] = copy.deepcopy(deterministic_convergence_summary)
      return feedback
  response = {
    "persistence_stage": stage or None,
    "feedback_source": None,
    "has_feedback": False,
    "deterministic_convergence_summary": copy.deepcopy(deterministic_convergence_summary),
  }
  if current_cycle_trace:
    response["current_cycle_trace"] = copy.deepcopy(current_cycle_trace)
  return response

def _issue_quarter_gap_contributions(
  issue_record: Optional[Dict[str, Any]],
  *,
  max_quarters: Optional[int] = None,
) -> List[Dict[str, Any]]:
  record = issue_record if isinstance(issue_record, dict) else {}
  relevant_quarters = _normalize_realism_remaining_quarters(
    record.get("relevant_quarters")
    if record.get("relevant_quarters") is not None
    else record.get("remaining_problem_quarters")
  )
  relevant_quarter_set = {
    int(_safe_float(item) or 0)
    for item in relevant_quarters
    if int(_safe_float(item) or 0) >= 1
  }
  metric_specs = [
    item
    for item in (record.get("metric_debug") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  quarter_gap_abs_map: Dict[int, float] = {}
  quarter_score_map: Dict[int, List[float]] = {}
  for spec in metric_specs:
    quarter_index = int(_safe_float(spec.get("quarter_index")) or 0)
    if quarter_index < 1 or (relevant_quarter_set and quarter_index not in relevant_quarter_set):
      continue
    gap_abs = _safe_float(spec.get("gap_abs"))
    if gap_abs is None:
      gap_abs = abs(float(_safe_float(spec.get("gap")) or 0.0))
    quarter_gap_abs_map[quarter_index] = float(quarter_gap_abs_map.get(quarter_index, 0.0) + abs(float(gap_abs or 0.0)))
    score_pct = _safe_float(spec.get("score_pct"))
    if score_pct is not None:
      quarter_score_map.setdefault(quarter_index, []).append(float(score_pct))

  if not quarter_gap_abs_map and relevant_quarter_set:
    aggregate_gap_abs = float(_safe_float(record.get("aggregate_gap_abs")) or 0.0)
    per_quarter_gap_abs = (
      float(aggregate_gap_abs / max(len(relevant_quarter_set), 1))
      if aggregate_gap_abs > 0.0
      else 0.0
    )
    for quarter_index in sorted(relevant_quarter_set):
      quarter_gap_abs_map[quarter_index] = per_quarter_gap_abs

  ordered_quarters = sorted(set(relevant_quarter_set) | set(quarter_gap_abs_map.keys()))
  total_gap_abs = float(sum(float(value or 0.0) for value in quarter_gap_abs_map.values()))
  contributions: List[Dict[str, Any]] = []
  for quarter_index in ordered_quarters:
    gap_abs = float(quarter_gap_abs_map.get(quarter_index, 0.0))
    quarter_scores = quarter_score_map.get(quarter_index) or []
    contributions.append(
      {
        "quarter_index": int(quarter_index),
        "gap_abs": gap_abs,
        "gap_contribution_pct": (
          float((gap_abs / total_gap_abs) * 100.0)
          if total_gap_abs > 1e-9
          else 0.0
        ),
        "average_score_pct": (
          float(sum(quarter_scores) / len(quarter_scores))
          if quarter_scores
          else None
        ),
        "lowest_score_pct": (
          float(min(quarter_scores))
          if quarter_scores
          else None
        ),
      }
    )

  contributions.sort(
    key=lambda item: (
      -float(_safe_float(item.get("gap_contribution_pct")) or 0.0),
      -float(_safe_float(item.get("gap_abs")) or 0.0),
      float(_safe_float(item.get("lowest_score_pct")) or 100.0),
      int(_safe_float(item.get("quarter_index")) or 0),
    )
  )
  if max_quarters is not None:
    return copy.deepcopy(contributions[: max(0, int(max_quarters or 0))])
  return copy.deepcopy(contributions)

def _build_convergence_retry_focus_packet(
  *,
  attempt_number: int,
  controller_resolution_state: Optional[Dict[str, Any]],
  latest_quality_assessment: Optional[Dict[str, Any]],
  stall_assessment: Optional[Dict[str, Any]],
  retry_memory: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
  prior_numeric_feedback: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  quality = latest_quality_assessment if isinstance(latest_quality_assessment, dict) else {}
  stall = stall_assessment if isinstance(stall_assessment, dict) else {}
  memory = retry_memory if isinstance(retry_memory, dict) else {}
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  feedback = prior_numeric_feedback if isinstance(prior_numeric_feedback, dict) else {}

  open_issue_records = [
    item
    for item in (
      (state.get("remaining_issues") or [])
      if isinstance(state.get("remaining_issues"), list)
      else []
    )
    if isinstance(item, dict)
    and not _is_cash_pass_owned_issue_code(item.get("issue_code"))
  ]
  if not open_issue_records:
    open_issue_records = [
      item
      for item in _controller_state_issue_status_records(state)
      if isinstance(item, dict)
      and _controller_issue_is_blocking(item)
      and not _is_cash_pass_owned_issue_code(item.get("issue_code"))
    ]
  open_issue_records.sort(
    key=lambda item: (
      -int(_safe_float(item.get("remaining_issue_severity_score")) or 0),
      str(item.get("issue_code") or "").strip().lower(),
    )
  )
  focus_issue_records = open_issue_records[:_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT]
  issue_packet_map = _numeric_solver_contract_issue_packet_map(contract)
  previous_candidate = (
    memory.get("latest_candidate_signature")
    if isinstance(memory.get("latest_candidate_signature"), dict)
    else {}
  )
  previous_lever_ids = [
    str(item).strip()
    for item in (previous_candidate.get("lever_set_union") or [])
    if str(item).strip()
  ]
  previous_lever_families = sorted(
    {
      _lever_family_from_lever_id(item)
      for item in previous_lever_ids
      if _lever_family_from_lever_id(item)
    }
  )
  attempted_lever_families = sorted(
    {
      str(item).strip().lower()
      for item in (feedback.get("attempted_lever_families") or [])
      if str(item).strip()
    }
  )
  previous_attempted_families = sorted(
    {
      *attempted_lever_families,
      *previous_lever_families,
    }
  )
  failed_quarters = sorted(
    {
      int(_safe_float(item) or 0)
      for item in (
        (
          (feedback.get("target_verification") if isinstance(feedback.get("target_verification"), dict) else {})
          .get("quarters_failed")
          or []
        )
      )
      if int(_safe_float(item) or 0) >= 1
    }
  )
  issue_coverage_requirements: List[Dict[str, Any]] = []
  required_primary_metric_candidates: List[str] = []
  required_issue_lever_ids: List[str] = []
  required_open_issue_codes: List[str] = []
  focus_quarters: List[int] = []
  focus_quarter_details: List[Dict[str, Any]] = []
  remaining_horizon_focus_active = False
  allowed_target_metric_names = [
    str(item).strip().lower()
    for item in (contract.get("allowed_target_metric_ids") or [])
    if str(item).strip()
  ]
  for record in focus_issue_records:
    issue_code = str(record.get("issue_code") or "").strip().lower()
    if not issue_code or _is_cash_pass_owned_issue_code(issue_code):
      continue
    required_open_issue_codes.append(issue_code)
    contract_packet = issue_packet_map.get(issue_code) or {}
    mapping_contract = post_intake_issue_mapping_contract(
      issue_code,
      phase="convergence",
      allowed_target_metric_names=allowed_target_metric_names,
    )
    lever_ids = [
      str(item).strip()
      for item in (mapping_contract.get("candidate_lever_ids") or [])
      if str(item).strip()
    ]
    candidate_target_metric_names = [
      str(item).strip().lower()
      for item in (mapping_contract.get("target_metric_names") or [])
      if str(item).strip()
    ]
    candidate_target_metric_name_set = set(candidate_target_metric_names)
    metric_candidates = [
      *_issue_packet_declared_target_metric_names(contract_packet),
      *candidate_target_metric_names,
    ]
    metric_candidates = [
      str(metric_name).strip().lower()
      for metric_name in (metric_candidates or [])
      if str(metric_name).strip()
      and (
        str(metric_name).strip().lower() in candidate_target_metric_name_set
        or
        not allowed_target_metric_names
        or str(metric_name).strip().lower() in set(allowed_target_metric_names)
      )
    ]
    if not metric_candidates:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_targets: "
        f"{issue_code} has no direct target metrics from mapped candidate levers."
      )
    metric_candidates = metric_candidates[:_UNIFIED_PRIMARY_TARGET_MAX_COUNT]
    lever_ids = lever_ids[:_CONVERGENCE_MAX_FOCUS_LEVERS]
    relevant_quarters = sorted(
      {
        int(_safe_float(item) or 0)
        for item in (
          _normalize_realism_remaining_quarters(
            record.get("relevant_quarters")
            if record.get("relevant_quarters") is not None
            else record.get("remaining_problem_quarters")
          )
          or contract_packet.get("remaining_problem_quarters")
          or []
        )
        if int(_safe_float(item) or 0) >= 1
      }
    )
    if relevant_quarters:
      relevant_quarters = _remaining_horizon_issue_quarters(
        issue_code=issue_code,
        base_quarters=relevant_quarters,
        quarter_count=_contract_forecast_quarter_count(),
      )
    full_horizon_issue = _issue_requires_remaining_horizon_scope(issue_code)
    remaining_horizon_focus_active = remaining_horizon_focus_active or full_horizon_issue
    quarter_gap_contributions = _issue_quarter_gap_contributions(
      record,
      max_quarters=max(
        _CONVERGENCE_MAX_FOCUS_QUARTERS,
        len(relevant_quarters),
      ),
    )
    if not quarter_gap_contributions and relevant_quarters:
      quarter_gap_contributions = [
        {
          "quarter_index": int(quarter_index),
          "gap_abs": 0.0,
          "gap_contribution_pct": 0.0,
          "average_score_pct": None,
          "lowest_score_pct": None,
        }
        for quarter_index in relevant_quarters
      ]
    affected_quarters = [
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in quarter_gap_contributions
      if int(_safe_float(item.get("quarter_index")) or 0) >= 1
    ]
    for quarter_entry in quarter_gap_contributions:
      quarter_index = int(_safe_float(quarter_entry.get("quarter_index")) or 0)
      if quarter_index < 1:
        continue
      focus_quarter_details.append(
        {
          "issue_code": issue_code,
          "issue_priority_rank": len(required_open_issue_codes),
          "issue_severity_score": int(_safe_float(record.get("remaining_issue_severity_score")) or 0),
          "quarter_index": quarter_index,
          "gap_abs": float(_safe_float(quarter_entry.get("gap_abs")) or 0.0),
          "gap_contribution_pct": float(_safe_float(quarter_entry.get("gap_contribution_pct")) or 0.0),
          "average_score_pct": _safe_float(quarter_entry.get("average_score_pct")),
          "lowest_score_pct": _safe_float(quarter_entry.get("lowest_score_pct")),
        }
      )
    issue_coverage_requirements.append(
      {
        "issue_code": issue_code,
        "severity_score": int(_safe_float(record.get("remaining_issue_severity_score")) or 0),
        "relevant_quarters": copy.deepcopy(relevant_quarters),
        "affected_quarters": affected_quarters,
        "quarter_gap_contributions": copy.deepcopy(
          quarter_gap_contributions
        ),
        "metric_candidates": copy.deepcopy(metric_candidates),
        "required_lever_ids": copy.deepcopy(lever_ids),
        "solver_objective": str(contract_packet.get("solver_objective") or "").strip(),
      }
    )
    for metric_name in metric_candidates:
      if metric_name not in required_primary_metric_candidates:
        required_primary_metric_candidates.append(metric_name)
    for lever_id in lever_ids:
      if lever_id not in required_issue_lever_ids:
        required_issue_lever_ids.append(lever_id)

  focus_quarter_details.sort(
    key=lambda item: (
      int(_safe_float(item.get("issue_priority_rank")) or 9999),
      -float(_safe_float(item.get("gap_contribution_pct")) or 0.0),
      -float(_safe_float(item.get("gap_abs")) or 0.0),
      float(_safe_float(item.get("lowest_score_pct")) or 100.0),
      int(_safe_float(item.get("quarter_index")) or 0),
    )
  )
  for quarter_entry in focus_quarter_details:
    quarter_index = int(_safe_float(quarter_entry.get("quarter_index")) or 0)
    if quarter_index < 1 or quarter_index in focus_quarters:
      continue
    focus_quarters.append(quarter_index)
    if len(focus_quarters) >= _UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT:
      break

  required_primary_metric_candidates = required_primary_metric_candidates[:_UNIFIED_PRIMARY_TARGET_MAX_COUNT]

  before_remaining = int(_safe_float(quality.get("remaining_issue_count_before")) or 0)
  after_remaining = int(_safe_float(quality.get("remaining_issue_count_after")) or before_remaining)
  issue_count_change = int(after_remaining - before_remaining)
  meaningful_progress = bool(quality.get("meaningful_progress"))
  if attempt_number <= 1 or not quality:
    progress_status = "initial"
  elif bool(quality.get("issue_count_regressed")) and not meaningful_progress:
    progress_status = "regressed"
  elif not meaningful_progress:
    progress_status = "flat"
  else:
    progress_status = "improved"

  structural_issue_pressure = bool(stall.get("force_structural_driver_changes")) or progress_status in {"flat", "regressed"}
  minimum_primary_metric_coverage_count = min(
    len(required_primary_metric_candidates),
    max(1, min(3, len(issue_coverage_requirements) + 1)),
  )

  quarter_count = _contract_forecast_quarter_count()
  full_horizon_quarters = convergence_full_horizon_quarters(quarter_count)
  return {
    "progress_status": progress_status,
    "meaningful_progress_rule": (
      "Accepted progress means one of the following must happen: remaining_issue_count decreases, "
      "or the focused closure-metric gap shrinks, or the focused issue score improves beyond the "
      "configured threshold. Positive gap improvement must persist even before score thresholds are reached."
    ),
    "minimum_primary_metric_coverage_count": int(minimum_primary_metric_coverage_count),
    "required_open_issue_codes": copy.deepcopy(required_open_issue_codes),
    "required_failed_quarters": copy.deepcopy(failed_quarters),
    "focus_issue_codes": copy.deepcopy(required_open_issue_codes),
    "focus_quarters": copy.deepcopy(full_horizon_quarters),
    "focus_quarter_selection_mode": convergence_full_horizon_retry_scope_mode(),
    "focus_quarter_details": copy.deepcopy(focus_quarter_details[:_UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT]),
    "required_primary_metric_candidates": copy.deepcopy(required_primary_metric_candidates),
    "required_issue_lever_ids": copy.deepcopy(required_issue_lever_ids),
    "issue_coverage_requirements": copy.deepcopy(issue_coverage_requirements),
    "previous_attempted_lever_families": copy.deepcopy(previous_attempted_families),
    "last_failure_reason": (
      "remaining_issue_count_regressed"
      if progress_status == "regressed"
      else "remaining_issue_count_flat"
      if progress_status == "flat"
      else ""
    ),
    "convergence_contract_policy": build_unified_convergence_contract_policy(),
    "constraints": unified_convergence_contract_constraints(
      [
        "meaningful progress can come from issue-count reduction, gap reduction, or score improvement",
        "cover each still-open issue with a direct mapped primary target row",
      ]
    ),
    "instruction": (
      "The next cycle must satisfy the SQL-backed convergence contract policy using direct mapped target rows."
    ),
  }

def _controller_retry_heartbeat_from_snapshot(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = snapshot if isinstance(snapshot, dict) else {}
  context = payload.get("controller_retry_context") if isinstance(payload.get("controller_retry_context"), dict) else {}
  candidate_signature = payload.get("candidate_signature") if isinstance(payload.get("candidate_signature"), dict) else {}
  validation_error = payload.get("validation_error") if isinstance(payload.get("validation_error"), dict) else {}
  decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
  plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
  result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
  retry_memory = payload.get("retry_memory") if isinstance(payload.get("retry_memory"), dict) else {}
  numeric_feedback = _build_numeric_solver_feedback_payload(copy.deepcopy(result))
  return {
    "heartbeat_at_eastern": current_app_timestamp_iso(),
    "heartbeat_timezone": current_app_timezone_name(),
    "pass_name": str(context.get("pass_name") or "").strip(),
    "pass_label": str(context.get("pass_label") or "").strip(),
    "attempt_number": int(_safe_float(payload.get("attempt_number")) or 0),
    "attempt_stage": str(payload.get("attempt_stage") or context.get("attempt_stage") or "").strip(),
    "lifecycle_status": str(payload.get("status") or "").strip(),
    "max_attempts": int(_safe_float(context.get("max_attempts")) or 0),
    "previous_attempt_count": int(_safe_float(context.get("previous_attempt_count")) or 0),
    "decision_status": str(decision.get("status") or "").strip(),
    "plan_status": str(plan.get("status") or "").strip(),
    "result_status": str(result.get("status") or "").strip(),
    "candidate_lever_count": len(candidate_signature.get("lever_set_union") or []),
    "candidate_target_quarter_count": len(candidate_signature.get("targeted_quarters") or []),
    "candidate_target_metric_count": len(candidate_signature.get("target_metric_names") or []),
    "failed_quarters": copy.deepcopy(
      (
        numeric_feedback.get("target_verification")
        if isinstance(numeric_feedback.get("target_verification"), dict)
        else {}
      ).get("quarters_failed")
      or []
    ),
    "solver_invoked": bool(numeric_feedback.get("solver_invoked")),
    "solver_execution_state": str(numeric_feedback.get("solver_execution_state") or "").strip(),
    "quarters_with_target_misses": int(_safe_float(numeric_feedback.get("quarters_with_target_misses")) or 0),
    "attempt_count": int(_safe_float(numeric_feedback.get("attempt_count")) or 0),
    "validation_error": copy.deepcopy(validation_error or {}),
    "latest_improvement_summary": copy.deepcopy(retry_memory.get("latest_improvement_summary") or {}),
  }

def _retry_scope_quarters(
  *,
  controller_retry_context: Optional[Dict[str, Any]],
  quarter_count: int,
) -> List[int]:
  return convergence_retry_scope_quarters(
    controller_retry_context=controller_retry_context,
    quarter_count=quarter_count,
  )

def _retry_scope_lever_ids(
  *,
  controller_retry_context: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]] = None,
  solved_model_input_json: Optional[Dict[str, Any]] = None,
  scoped_quarters: Optional[List[int]] = None,
) -> List[str]:
  return convergence_retry_scope_lever_ids(
    controller_retry_context=controller_retry_context,
    numeric_solver_contract=numeric_solver_contract,
    deterministic_numeric_guidance=deterministic_numeric_guidance,
    solved_model_input_json=solved_model_input_json,
    scoped_quarters=scoped_quarters,
    build_writable_lever_review_catalog=_build_writable_lever_review_catalog,
    deterministic_guidance_focus_issue_codes=_deterministic_guidance_focus_issue_codes,
    scoped_unified_allowed_lever_ids=_scoped_unified_allowed_lever_ids,
    solver_contract_eligible_lever_ids=_solver_contract_eligible_lever_ids,
    max_active_issue_count=_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT,
    max_focus_levers=_CONVERGENCE_MAX_FOCUS_LEVERS,
  )

def _build_retry_scope_payload(
  # C4 audit (cloud Claude remediation): this helper IS live in the
  # new pipeline. Called from _build_repair_guidance_payload at line
  # 2554; the repair guidance is used by _persist_post_intake_stage_state
  # which is the persistence path for the orchestrator's
  # _run_post_cascade_completion (see the call-chain comment at
  # post_intake_convergence/runtime.py::_build_current_cycle_convergence_packet).
  *,
  controller_retry_context: Optional[Dict[str, Any]],
  prior_numeric_feedback: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
  solved_model_input_json: Optional[Dict[str, Any]],
  solved_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  return convergence_build_retry_scope_payload(
    controller_retry_context=controller_retry_context,
    prior_numeric_feedback=prior_numeric_feedback,
    numeric_solver_contract=numeric_solver_contract,
    deterministic_numeric_guidance=deterministic_numeric_guidance,
    solved_model_input_json=solved_model_input_json,
    solved_finmo_json=solved_finmo_json,
    safe_float=_safe_float,
    quarter_count_from_model_input=_quarter_count_from_model_input,
    deterministic_guidance_focus_issue_codes=_deterministic_guidance_focus_issue_codes,
    retry_scope_lever_ids_fn=_retry_scope_lever_ids,
    solved_lever_value_map=_solved_lever_value_map,
    build_writable_lever_review_catalog=_build_writable_lever_review_catalog,
    finmo_rows_for_quarters=_finmo_rows_for_quarters,
    compact_quarter_metric_rows_for_storage=_compact_quarter_metric_rows_for_storage,
    compact_writable_lever_catalog_entries=_compact_writable_lever_catalog_entries,
    subset_lever_value_map=_subset_lever_value_map,
    max_active_issue_count=_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT,
  )

def _subset_numeric_solver_contract(
  # C4 audit (cloud Claude remediation): live helper called from
  # _build_repair_guidance_payload at line 2563. See the call-chain
  # comment at post_intake_convergence/runtime.py::
  # _build_current_cycle_convergence_packet for the full
  # orchestrator → state runner → contracts runner trace.
  *,
  numeric_solver_contract: Optional[Dict[str, Any]],
  retry_scope_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  return convergence_subset_numeric_solver_contract(
    numeric_solver_contract=numeric_solver_contract,
    retry_scope_payload=retry_scope_payload,
    solver_contract_quarter_count=_solver_contract_quarter_count,
  )

def _evaluate_retry_improvement(
  *,
  previous_result_signature: Optional[Dict[str, Any]],
  current_result_signature: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  return convergence_evaluate_retry_improvement(
    previous_result_signature=previous_result_signature,
    current_result_signature=current_result_signature,
    safe_float=_safe_float,
    negligible_improvement_ratio=_PASS_RETRY_NEGLIGIBLE_IMPROVEMENT_RATIO,
  )

def _build_realism_milestone_context(
  ops_json: Dict[str, Any],
  solved_model_input_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  milestones = _parse_milestones((ops_json or {}).get("milestones"))
  if not milestones:
    return []

  periods = [
    item
    for item in ((solved_model_input_json or {}).get("periods") or [])
    if isinstance(item, dict)
  ]
  max_quarter_index = max(
    [int(_safe_float(item.get("quarter")) or 0) for item in periods if int(_safe_float(item.get("quarter")) or 0) > 0] or [20]
  )
  milestone_context: List[Dict[str, Any]] = []

  for milestone in milestones:
    if not isinstance(milestone, dict):
      continue
    description = str(milestone.get("description") or "").strip()
    timing = str(milestone.get("timing") or "").strip()
    months_max = _safe_int(milestone.get("timing_months_max"))
    target_quarter_index: Optional[int] = None
    if months_max is not None and months_max > 0:
      target_quarter_index = max(1, min(max_quarter_index, int(math.ceil(float(months_max) / 3.0))))
    target_period = next(
      (
        item for item in periods
        if target_quarter_index is not None
        and int(_safe_float(item.get("quarter")) or 0) == target_quarter_index
      ),
      {},
    )
    milestone_context.append(
      {
        "description": description,
        "timing": timing,
        "timing_months_max": months_max,
        "target_quarter_index": target_quarter_index,
        "target_period_date": str(target_period.get("date") or "").strip(),
        "target_period_column": str(target_period.get("column_letter") or "").strip(),
        "is_binding_future_intent": bool(description and (timing or months_max is not None)),
      }
    )
  return milestone_context

def _finmo_quarter_row_map(finmo_json: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
  finmo = finmo_json if isinstance(finmo_json, dict) else {}
  return {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in (finmo.get("quarter_rows") or [])
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  }

def _business_world_contract(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  planning_mode: Any,
  planning_mode_reason: Any = "",
  current_date: Optional[date] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  mode = str(planning_mode or "").strip().lower()
  if not mode:
    raise RuntimeError(
      "business_world_contract_missing_planning_mode: planning_mode is required before post-intake convergence."
    )
  start_date = (
    _parse_date(facts.get("start_date"))
    or _parse_date(facts.get("business_start_date"))
    or _parse_date(ops.get("business_start_date"))
    or _parse_date(ops.get("start_date"))
  )
  today = current_date or datetime.utcnow().date()
  explicit_stage = str(ops.get("business_stage") or facts.get("business_stage") or "").strip().lower()
  inferred_stage = _infer_business_stage(start_date, today) if start_date is not None else None
  stage = explicit_stage or str(inferred_stage or "").strip().lower()
  if not stage:
    raise RuntimeError(
      "business_world_contract_missing_business_stage: ops.business_stage or a parseable business_start_date is required before post-intake convergence."
    )
  business_age_months = _whole_months_between(start_date, today) if start_date is not None else None
  if not isinstance(stage_ramp_contract, dict) or not stage_ramp_contract:
    raise RuntimeError(
      "business_world_contract_missing_gpt_stage_ramp_contract: GPT stage ramp contract is required before post-intake planning."
    )
  resolved_stage_ramp_contract = copy.deepcopy(stage_ramp_contract)
  return {
    "contract_version": "business_world_contract_v1",
    "business_stage": stage,
    "stage_family": resolved_stage_ramp_contract.get("stage_family"),
    "business_stage_source": "ops.business_stage" if explicit_stage else "business_start_date_inferred",
    "business_start_date": start_date.isoformat() if start_date is not None else None,
    "business_age_months_at_run": business_age_months,
    "planning_mode": mode,
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "mode_prompt_text": _planning_mode_prompt_text(mode),
    "stage_ramp_contract": copy.deepcopy(resolved_stage_ramp_contract),
    "profitability_maturity_month": 30,
    "rule_summary": (
      "Planning mode is the canonical operating posture. Business stage and age are binding lifecycle limiters. "
      "The GPT-selected stage maturity grid is binding before convergence: revenue, utilization, payroll headcount schedule, cost-ratio caps, "
      "and profitability posture must mature together. Negative net income may be stage-appropriate early, but chronic "
      "mature losses or late losses caused by unsupported operating economics are not coherent."
    ),
  }

def _business_age_months_at_quarter(contract: Dict[str, Any], quarter_index: int) -> Optional[int]:
  base_age = _safe_float(contract.get("business_age_months_at_run"))
  if base_age is None:
    return None
  return int(round(float(base_age))) + max(0, int(quarter_index or 0)) * 3

def _business_stage_family(stage: Any) -> str:
  normalized = str(stage or "").strip().lower().replace("_", "-")
  if normalized in {"pre-revenue", "pre revenue", "startup", "start-up", "new", "launch"}:
    return "startup"
  if normalized in {"early", "early-stage", "early stage", "growth"}:
    return "early"
  return "operational"

def _stage_ramp_grid_rows(contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = contract if isinstance(contract, dict) else {}
  raw_rows = payload.get("quarter_ramp_grid")
  if isinstance(raw_rows, list) and raw_rows:
    rows = [copy.deepcopy(row) for row in raw_rows if isinstance(row, dict)]
  else:
    raise RuntimeError(
      "stage_ramp_contract_missing_quarter_grid: GPT stage ramp contract must include quarter_ramp_grid."
    )
  rows_by_quarter: Dict[int, Dict[str, Any]] = {}
  for row in rows:
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if 1 <= quarter_index <= 20 and quarter_index not in rows_by_quarter:
      normalized = copy.deepcopy(row)
      normalized["quarter_index"] = quarter_index
      normalized["prior_quarter_index"] = quarter_index - 1 if quarter_index > 1 else 0
      rows_by_quarter[quarter_index] = normalized
  return [rows_by_quarter[quarter] for quarter in sorted(rows_by_quarter)]

def _stage_ramp_row_for_quarter(
  contract: Optional[Dict[str, Any]],
  quarter_index: int,
) -> Dict[str, Any]:
  target_quarter = int(quarter_index or 0)
  for row in _stage_ramp_grid_rows(contract):
    if int(_safe_float(row.get("quarter_index")) or 0) == target_quarter:
      return row
  return {}

def _stage_ramp_pair_growth_limit(
  contract: Optional[Dict[str, Any]],
  *,
  from_quarter: int,
  metric_prefix: str = "revenue",
  spike_count_used: int = 0,
) -> Dict[str, Any]:
  target_quarter = int(from_quarter or 0) + 1
  row = _stage_ramp_row_for_quarter(contract, target_quarter)
  prefix = str(metric_prefix or "revenue").strip().lower()
  ordinary_max = float(_safe_float(row.get(f"{prefix}_qoq_max")) or 0.0)
  spike_allowed = bool(row.get(f"{prefix}_qoq_spike_allowed"))
  spike_max = float(_safe_float(row.get(f"{prefix}_qoq_spike_max")) or ordinary_max)
  max_spike_count = int(_safe_float((contract or {}).get("max_spike_count")) or 0)
  spike_available = bool(
    target_quarter > 1
    and spike_allowed
    and spike_count_used < max(max_spike_count, 0)
    and spike_max >= ordinary_max
  )
  allowed_growth = spike_max if spike_available else ordinary_max
  return {
    "from_quarter": int(from_quarter or 0),
    "to_quarter": target_quarter,
    "ordinary_growth_max": ordinary_max,
    "spike_growth_max": spike_max,
    "spike_allowed_for_pair": spike_allowed,
    "spike_available": spike_available,
    "allowed_growth": allowed_growth,
    "ramp_grid_row": copy.deepcopy(row),
  }
