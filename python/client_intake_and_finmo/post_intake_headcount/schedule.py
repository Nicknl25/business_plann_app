from __future__ import annotations

import json
import os
import time
import requests
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

from client_intake_and_finmo.intake_submission import get_mysql_connection  # type: ignore
from client_intake_and_finmo.people_roles import (  # type: ignore
  _fetch_oews_rows_with_fallback,
  _get_naics_from_business_type,
  _normalize_state_abbrev,
  _select_wage,
)
from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_build_prompt_from_contract,
  post_intake_assert_process_object_control,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_gpt_contract_horizon_errors,
  post_intake_gpt_contract_normalize_payload,
  post_intake_gpt_contract_openai_schema,
  post_intake_gpt_contract_payload_errors,
  post_intake_gpt_context_filter_payload,
  post_intake_gpt_context_request_char_budget,
  post_intake_payroll_feasibility_mapping,
  post_intake_process_sequence_step,
)
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
  post_intake_fail_fast_raise,
)
from .lookup import (
  PAYROLL_HEADCOUNT_DRAFT_COLUMN,
  headcount_payroll_revenue_sanity_bounds,
  headcount_wage_positioning_options,
  post_intake_headcount_policy_for,
  validate_payroll_headcount_payload,
)


PAYROLL_HEADCOUNT_SOURCE = "headcount_schedule_derived"
PAYROLL_HEADCOUNT_POLICY_VERSION = "payroll_headcount_schedule_policy_v1"
PAYROLL_HEADCOUNT_LEVER_ID = "expenses::Payroll"
PAYROLL_HEADCOUNT_CONTRACT_NAME = "payroll_headcount_schedule"


def _assert_payroll_sequence_step(
  *,
  allowed_step_keys: Sequence[str],
  allowed_executor_functions: Sequence[str],
) -> Dict[str, Any]:
  from client_intake_and_finmo.post_intake_sequence import (  # type: ignore
    assert_post_intake_sequence_controller_active,
  )
  return assert_post_intake_sequence_controller_active(
    allowed_step_keys=allowed_step_keys,
    allowed_executor_functions=allowed_executor_functions,
  )


def _payroll_fail_fast(
  code: str,
  message: str = "",
  *,
  stage: str = "",
  details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return post_intake_fail_fast_raise(
    code,
    message,
    stage=stage or "payroll_headcount",
    details=details,
  )


def _contract_horizon_quarters() -> int:
  count = int(
    post_intake_contract_forecast_horizon_quarter_count(
      contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    )
    or 0
  )
  if count <= 0:
    _payroll_fail_fast(
      "payroll_headcount_contract_horizon_missing",
      "post_intake_gpt_contract_lookup must define a positive payroll horizon.",
      stage="payroll_headcount_contract_horizon",
    )
    return 0
  return count


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


def _safe_ratio(value: Any) -> Optional[float]:
  parsed = _safe_float(value)
  if parsed is None:
    return None
  if abs(parsed) > 1.0 and abs(parsed) <= 100.0:
    return parsed / 100.0
  return parsed


def _round_currency(value: Any) -> int:
  return int(round(float(_safe_float(value) or 0.0)))


def _clean_key(value: Any) -> str:
  return str(value or "").strip().lower()


def _policy_list(policy: Dict[str, Any], key: str) -> List[str]:
  return [
    _clean_key(item)
    for item in (policy.get(key) or [])
    if _clean_key(item)
  ]


def _title_match_tokens(value: Any) -> List[str]:
  text = str(value or "").lower()
  cleaned = "".join(ch if ch.isalnum() else " " for ch in text)
  stopwords = {
    "and",
    "the",
    "of",
    "for",
    "to",
    "a",
    "an",
    "all",
    "other",
    "except",
    "chief",
    "officer",
  }
  return [
    token
    for token in cleaned.split()
    if len(token) >= 3 and token not in stopwords
  ]


def _title_contains(candidate_title: str, expected: str) -> bool:
  return expected.lower() in str(candidate_title or "").strip().lower()


def _payroll_contract_capacity_assumptions(
  payroll_headcount_contract: Optional[Dict[str, Any]],
  *,
  policy: Dict[str, Any],
) -> Dict[str, Any]:
  payload = payroll_headcount_contract if isinstance(payroll_headcount_contract, dict) else {}
  labor_model = _clean_key(payload.get("capacity_labor_model"))
  intensity = _clean_key(payload.get("labor_intensity_class"))
  wage_tier = _clean_key(payload.get("wage_positioning_tier"))
  wage_multiplier = round(float(_safe_float(payload.get("wage_positioning_multiplier")) or 0.0), 4)
  productivity = round(float(_safe_float(payload.get("capacity_units_per_supporting_fte")) or 0.0), 4)
  allowed_labor_models = set(_policy_list(policy, "capacity_labor_model_values"))
  allowed_intensities = set(_policy_list(policy, "labor_intensity_class_values"))
  wage_multipliers = policy.get("wage_positioning_multiplier")
  if not isinstance(wage_multipliers, dict):
    wage_multipliers = {}
  allowed_wage_tiers = {_clean_key(key) for key in wage_multipliers.keys() if _clean_key(key)}
  errors: List[str] = []
  if allowed_labor_models and labor_model not in allowed_labor_models:
    errors.append(f"capacity_labor_model={labor_model or 'missing'} not in post_intake_headcount_policy_lookup")
  if allowed_intensities and intensity not in allowed_intensities:
    errors.append(f"labor_intensity_class={intensity or 'missing'} not in post_intake_headcount_policy_lookup")
  if allowed_wage_tiers and wage_tier not in allowed_wage_tiers:
    errors.append(f"wage_positioning_tier={wage_tier or 'missing'} not in post_intake_headcount_policy_lookup")
  tier_bounds = wage_multipliers.get(wage_tier) if isinstance(wage_multipliers, dict) else None
  if wage_multiplier <= 0.0:
    errors.append("wage_positioning_multiplier missing; GPT must provide exact multiplier inside selected tier bounds")
  elif isinstance(tier_bounds, dict):
    min_wage_multiplier = round(float(tier_bounds.get("min") or 0.0), 4)
    max_wage_multiplier = round(float(tier_bounds.get("max") or 0.0), 4)
    if wage_multiplier < min_wage_multiplier or wage_multiplier > max_wage_multiplier:
      errors.append(
        "wage_positioning_multiplier outside post_intake_headcount_policy_lookup tier bounds "
        f"({wage_multiplier} not between {min_wage_multiplier} and {max_wage_multiplier} for tier={wage_tier})"
      )
  elif wage_tier:
    errors.append(f"wage_positioning_multiplier bounds missing for tier={wage_tier}")
  if productivity <= 0.0:
    errors.append("capacity_units_per_supporting_fte must be a positive GPT-selected productivity assumption")
  if errors:
    _payroll_fail_fast(
      "payroll_headcount_capacity_assumptions_invalid",
      "; ".join(errors),
      stage="payroll_headcount_capacity_assumptions",
      details={
        "capacity_labor_model": labor_model,
        "labor_intensity_class": intensity,
        "wage_positioning_tier": wage_tier,
        "wage_positioning_multiplier": wage_multiplier,
        "capacity_units_per_supporting_fte": productivity,
        "policy_source": "post_intake_headcount_policy_lookup",
        "capacity_productivity_validation_rule": "positive_gpt_selected_assumption; reasonableness is checked by GPT target_payroll_percent_of_revenue sanity bounds",
        "selected_wage_positioning_bounds": tier_bounds,
      },
    )
  return {
    "capacity_labor_model": labor_model,
    "labor_intensity_class": intensity,
    "wage_positioning_tier": wage_tier,
    "capacity_units_per_supporting_fte": productivity,
    "wage_positioning_multiplier": wage_multiplier,
  }


def _annual_wage_inflation_factor(*, quarter_index: int, policy: Dict[str, Any]) -> float:
  annual_rate = round(float(policy.get("annual_wage_inflation_rate") or 0.0), 4)
  year_offset = max(0, (int(quarter_index or 1) - 1) // 4)
  return round(float((1.0 + annual_rate) ** year_offset), 6)


def _policy_adjusted_annual_wage(
  base_annual_wage: Any,
  *,
  quarter_index: int,
  policy: Dict[str, Any],
  wage_positioning_multiplier: float = 1.0,
) -> int:
  base = _round_currency(base_annual_wage)
  if base <= 0:
    return 0
  inflation = _annual_wage_inflation_factor(quarter_index=quarter_index, policy=policy)
  return _round_currency(base * max(1.0, float(wage_positioning_multiplier or 1.0)) * inflation)


def _row_stub_and_live_values(values: Sequence[Any], *, live_count: int) -> Tuple[float, List[float]]:
  normalized = [round(_safe_float(item) or 0.0, 6) for item in (values or [])]
  if len(normalized) >= live_count + 1:
    stub_value = float(normalized[0])
    live_values = list(normalized[1:live_count + 1])
  else:
    stub_value = 0.0
    live_values = list(normalized[:live_count])
  if len(live_values) < live_count:
    live_values.extend([0.0 for _ in range(live_count - len(live_values))])
  return stub_value, live_values[:live_count]


def _compose_period_values(*, stub_value: float, live_values: Sequence[Any]) -> List[float]:
  return [
    round(_safe_float(stub_value) or 0.0, 6),
    *[round(_safe_float(item) or 0.0, 6) for item in (live_values or [])],
  ]


def payroll_row_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  for row in (sections.get("expenses") or []):
    if isinstance(row, dict) and str(row.get("label") or "").strip() == "Payroll":
      return row
  return None


def _live_count_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> int:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  periods = payload.get("periods") if isinstance(payload.get("periods"), list) else []
  live_count = len([item for item in periods if isinstance(item, dict) and not bool(item.get("is_stub"))])
  return live_count or _contract_horizon_quarters()


def _schedule_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  runtime = payload.get("derived_driver_runtime") if isinstance(payload.get("derived_driver_runtime"), dict) else {}
  runtime_entry = runtime.get(PAYROLL_HEADCOUNT_LEVER_ID) if isinstance(runtime.get(PAYROLL_HEADCOUNT_LEVER_ID), dict) else {}
  schedule = runtime_entry.get("payroll_headcount") if isinstance(runtime_entry.get("payroll_headcount"), dict) else {}
  if schedule:
    return deepcopy(schedule)
  policies = payload.get("derived_driver_policies") if isinstance(payload.get("derived_driver_policies"), dict) else {}
  policy_entry = policies.get(PAYROLL_HEADCOUNT_LEVER_ID) if isinstance(policies.get(PAYROLL_HEADCOUNT_LEVER_ID), dict) else {}
  policy_schedule = policy_entry.get("payroll_headcount") if isinstance(policy_entry.get("payroll_headcount"), dict) else {}
  return deepcopy(policy_schedule or {})


def default_payroll_headcount_policy(
  *,
  financials_json: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del financials_json, ops_json
  policy = post_intake_headcount_policy_for("default")
  return {
    "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
    "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
    "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
    "driver_basis": "headcount_schedule",
    "lookup_function": "post_intake_headcount_policy_for",
    "policy": deepcopy(policy or {}),
  }


def normalized_payroll_headcount_policy(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  schedule = _schedule_from_model_input(model_input_json)
  policy = default_payroll_headcount_policy()
  policy["payroll_headcount"] = deepcopy(schedule)
  policy["schedule_present"] = bool(schedule)
  return policy


def apply_payroll_headcount_policy_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  *,
  live_count: int,
  require_schedule: bool = False,
) -> Dict[str, Any]:
  payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  schedule = _schedule_from_model_input(payload)
  if not schedule:
    if require_schedule:
      _payroll_fail_fast(
        "payroll_headcount_policy_schedule_missing",
        "payroll_headcount_policy_schedule_missing: "
        "derived payroll policy application requires payroll_headcount in derived_driver_runtime or derived_driver_policies.",
        stage="payroll_headcount_policy_application",
      )
    return payload
  capacity_payload = apply_payroll_supported_capacity_to_model_input(
    payload,
    schedule,
    live_count=live_count,
    process_step_key="payroll_headcount_schedule",
    control_action="derive",
    control_trigger="payroll_headcount_changed",
  )
  return apply_payroll_headcount_payload_to_model_input(
    capacity_payload,
    schedule,
    live_count=live_count,
    process_step_key="payroll_headcount_schedule",
    control_action="derive",
    control_trigger="payroll_headcount_changed",
  )


def validate_payroll_headcount_contract(
  *,
  model_input_json: Optional[Dict[str, Any]],
  business_world_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del business_world_contract
  schedule = _schedule_from_model_input(model_input_json)
  return validate_payroll_headcount_model_input_contract(
    model_input_json=deepcopy(model_input_json if isinstance(model_input_json, dict) else {}),
    payroll_headcount=schedule if schedule else None,
  )


def _payroll_headcount_grid_rows(payroll_headcount_contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = payroll_headcount_contract if isinstance(payroll_headcount_contract, dict) else {}
  raw_rows = payload.get("payroll_headcount_grid")
  if not isinstance(raw_rows, list):
    raw_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
  rows_by_key: Dict[Tuple[int, str, str, str], Dict[str, Any]] = {}
  for item in raw_rows:
    if not isinstance(item, dict):
      continue
    quarter_index = int(round(float(_safe_float(item.get("q") or item.get("quarter_index")) or 0.0)))
    horizon = _contract_horizon_quarters()
    if quarter_index < 1 or quarter_index > horizon:
      continue
    starting_fte = round(max(0.0, float(_safe_float(item.get("starting_fte")) or 0.0)), 2)
    ending_fte = round(max(0.0, float(_safe_float(item.get("ending_fte")) or 0.0)), 2)
    hires = round(max(0.0, float(_safe_float(item.get("hires")) or 0.0)), 2)
    derived_hires = round(max(0.0, ending_fte - starting_fte), 2)
    if abs((starting_fte + hires) - ending_fte) > 0.01 and ending_fte + 0.01 >= starting_fte:
      hires = derived_hires
    benefits_raw = item.get("payroll_tax_benefits_pct")
    if benefits_raw is None:
      benefits_raw = item.get("payroll_taxes_benefits_percent")
    payroll_tax_benefits_pct = round(max(0.0, float(_safe_ratio(benefits_raw) or 0.0)), 2)
    staffing_class = str(item.get("staffing_class") or "supporting_staff").strip() or "supporting_staff"
    oews_occ_title = str(item.get("oews_occ_title") or item.get("oews_matched_title") or "").strip()
    position_title = str(item.get("position_title") or oews_occ_title or item.get("person_name") or "").strip()
    class_key = staffing_class.lower()
    person_key = str(item.get("person_name") or "").strip().lower()
    title_key = (oews_occ_title or position_title).lower()
    if (quarter_index, class_key, title_key, person_key) in rows_by_key:
      _payroll_fail_fast(
        "payroll_headcount_duplicate_oews_title_quarter",
        f"Duplicate payroll row for Q{quarter_index} title '{oews_occ_title or position_title}'.",
        stage="payroll_headcount_grid_parse",
        details={"quarter_index": quarter_index, "oews_occ_title": oews_occ_title, "position_title": position_title},
      )
    parsed_row = {
      "quarter_index": quarter_index,
      "staffing_class": staffing_class,
      "position_title": position_title or oews_occ_title,
      "oews_occ_title": oews_occ_title,
      "starting_fte": starting_fte,
      "hires": hires,
      "ending_fte": ending_fte,
      "payroll_taxes_benefits_percent": payroll_tax_benefits_pct,
    }
    if item.get("annual_wage") is not None or item.get("avg_annual_wage") is not None:
      parsed_row["annual_wage"] = _round_currency(item.get("annual_wage") or item.get("avg_annual_wage"))
    for text_field in ("person_name", "wage_source", "wage_source_code", "oews_occ_code", "oews_matched_title", "oews_match_basis"):
      if item.get(text_field) is not None:
        parsed_row[text_field] = str(item.get(text_field) or "").strip()
    rows_by_key[(quarter_index, class_key, title_key, person_key)] = parsed_row
  parsed_rows = [
    rows_by_key[key]
    for key in sorted(rows_by_key.keys(), key=lambda item: (item[0], item[1], item[2], item[3]))
  ]
  return _normalize_mechanical_fte_continuity(parsed_rows)


def _normalize_mechanical_fte_continuity(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  """Derive mechanical starting/hires continuity while preserving GPT ending FTE."""
  normalized: List[Dict[str, Any]] = []
  prior_ending_by_title: Dict[str, float] = {}
  for source_row in sorted(
    rows,
    key=lambda row: (
      int(row.get("quarter_index") or 0),
      str(row.get("staffing_class") or "supporting_staff").lower(),
      _title_key(row.get("oews_occ_title") or row.get("position_title") or row.get("person_name")),
    ),
  ):
    row = deepcopy(source_row)
    quarter_index = int(row.get("quarter_index") or 0)
    staffing_class = str(row.get("staffing_class") or "supporting_staff").strip().lower() or "supporting_staff"
    if staffing_class == "key_person":
      title_identity = _title_key(row.get("person_name") or row.get("position_title"))
    else:
      title_identity = _title_key(row.get("oews_occ_title") or row.get("position_title"))
    continuity_key = f"{staffing_class}::{title_identity}"
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    if quarter_index == 1 and starting_fte <= 0.0 and ending_fte > 0.0:
      starting_fte = ending_fte
      row["starting_fte"] = starting_fte
      row["hires"] = 0.0
    if quarter_index > 1 and continuity_key in prior_ending_by_title:
      prior_ending = round(float(prior_ending_by_title.get(continuity_key) or 0.0), 2)
      if ending_fte + 0.01 >= prior_ending:
        starting_fte = prior_ending
        row["starting_fte"] = starting_fte
        row["hires"] = round(max(0.0, ending_fte - starting_fte), 2)
    else:
      hires = round(float(row.get("hires") or 0.0), 2)
      if abs((starting_fte + hires) - ending_fte) > 0.01 and ending_fte + 0.01 >= starting_fte:
        row["hires"] = round(max(0.0, ending_fte - starting_fte), 2)
    prior_ending_by_title[continuity_key] = ending_fte
    normalized.append(row)
  return normalized


def _openai_key() -> Optional[str]:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  return key or None


def _openai_model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _payroll_process_sequence_settings(*, step_key: Any = "") -> Dict[str, Any]:
  resolved_step_key = str(step_key or "").strip() or "payroll_headcount_schedule"
  try:
    sequence_row = post_intake_process_sequence_step(resolved_step_key, required=True) or {}
  except Exception as exc:
    if resolved_step_key != "payroll_headcount_schedule":
      sequence_row = post_intake_process_sequence_step("payroll_headcount_schedule", required=True) or {}
      resolved_step_key = "payroll_headcount_schedule"
    else:
      _payroll_fail_fast(
        "payroll_headcount_process_sequence_lookup_failed",
        f"{resolved_step_key} process sequence lookup failed: {exc}",
        stage="payroll_headcount_process_sequence",
      )
      sequence_row = {}
  timeout_seconds = _safe_float(sequence_row.get("timeout_seconds"))
  if timeout_seconds is None or timeout_seconds <= 0:
    timeout_seconds = 180.0
  attempts_raw = _safe_float(sequence_row.get("max_attempts"))
  max_attempts = int(attempts_raw or 1)
  if max_attempts < 1:
    max_attempts = 1
  if max_attempts > 5:
    max_attempts = 5
  return {
    "timeout_seconds": float(timeout_seconds),
    "max_attempts": max_attempts,
    "source_table": "post_intake_process_sequence_lookup",
    "step_key": resolved_step_key,
  }


def _payroll_repair_trigger_from_failure(previous_contract_failure: Optional[Dict[str, Any]]) -> str:
  if not isinstance(previous_contract_failure, dict) or not previous_contract_failure:
    return "initial_build"
  failure_text = json.dumps(previous_contract_failure, ensure_ascii=False, default=str).lower()
  if "payroll_stage_profitability_feasibility_failed" in failure_text:
    return "payroll_stage_profitability_feasibility_failed"
  return "payroll_revenue_economic_feasibility_failed"


def _compact_payroll_failure_for_gpt(
  failure: Optional[Dict[str, Any]],
  *,
  max_violations: int = 8,
) -> Dict[str, Any]:
  source = failure if isinstance(failure, dict) else {}
  if not source:
    return {}

  def _compact_violation(item: Any) -> Dict[str, Any]:
    row = item if isinstance(item, dict) else {}
    compact = {
      key: deepcopy(row.get(key))
      for key in (
        "error",
        "quarter_index",
        "revenue",
        "payroll",
        "payroll_percent_of_revenue",
        "labor_intensity_class",
        "policy_min_pct",
        "policy_max_pct",
        "effective_min_pct_with_tolerance",
        "effective_max_pct_with_tolerance",
        "repair_rule_key",
        "previous_revenue",
        "current_revenue",
        "previous_payroll",
        "current_payroll",
        "rule",
      )
      if row.get(key) is not None
    }
    if isinstance(row.get("deterministic_driver_math"), dict):
      compact["deterministic_driver_math"] = deepcopy(row.get("deterministic_driver_math"))
    if row.get("required_action"):
      compact["required_action"] = str(row.get("required_action") or "")[:700]
    return compact

  compact_failure = {
    key: deepcopy(source.get(key))
    for key in ("attempt", "failed_state_source", "required_rebuild")
    if source.get(key) is not None
  }
  if source.get("error"):
    compact_failure["error"] = str(source.get("error") or "")[:3000]
  violation_rows = (
    source.get("payroll_revenue_feasibility_violations")
    if isinstance(source.get("payroll_revenue_feasibility_violations"), list)
    else (source.get("violations") if isinstance(source.get("violations"), list) else [])
  )
  if violation_rows:
    compact_failure["violation_count"] = len(violation_rows)
    compact_failure["violations"] = [
      _compact_violation(item)
      for item in violation_rows[: max(1, int(max_violations or 1))]
      if isinstance(item, dict)
    ]
    productivity_caps: List[Dict[str, Any]] = []
    productivity_floors: List[Dict[str, Any]] = []
    for item in violation_rows:
      if not isinstance(item, dict):
        continue
      math_payload = item.get("deterministic_driver_math")
      if not isinstance(math_payload, dict):
        continue
      target = _safe_float(math_payload.get("safe_capacity_units_per_supporting_fte_target_with_buffer"))
      direction = str(math_payload.get("required_capacity_units_per_supporting_fte_direction") or "").strip()
      if target is None or target <= 0.0 or direction not in {"at_or_below", "at_or_above"}:
        continue
      target_row = {
        "quarter_index": item.get("quarter_index"),
        "payroll_percent_of_revenue": item.get("payroll_percent_of_revenue"),
        "safe_capacity_units_per_supporting_fte_target_with_buffer": round(float(target), 6),
        "required_capacity_units_per_supporting_fte_direction": direction,
      }
      if direction == "at_or_below":
        productivity_caps.append(target_row)
      else:
        productivity_floors.append(target_row)
    repair_constraints: Dict[str, Any] = {
      "source_of_truth": "post_intake_headcount_policy_lookup + payroll_revenue_feasibility_violations.deterministic_driver_math",
      "rule": (
        "Apply these all-quarter bounds as hard repair constraints. Directional movement alone is not enough; "
        "the corrected schedule must satisfy every violating quarter after Python rebuilds payroll-supported capacity and FINMO."
      ),
    }
    if productivity_caps:
      most_restrictive_cap = min(
        productivity_caps,
        key=lambda row: float(row.get("safe_capacity_units_per_supporting_fte_target_with_buffer") or 0.0),
      )
      hard_cap = float(most_restrictive_cap.get("safe_capacity_units_per_supporting_fte_target_with_buffer") or 0.0)
      repair_constraints["capacity_units_per_supporting_fte_must_be_at_or_below"] = round(hard_cap, 6)
      repair_constraints["recommended_capacity_units_per_supporting_fte_or_lower"] = round(max(0.0001, hard_cap * 0.90), 6)
      repair_constraints["most_restrictive_cap_quarter"] = most_restrictive_cap
      repair_constraints["cap_violation_count"] = len(productivity_caps)
      repair_constraints["cap_instruction"] = (
        "Payroll/revenue is too low. Choose capacity_units_per_supporting_fte at or below the hard cap, "
        "preferably at or below the recommended value when changing OEWS title, FTE, benefits, wage tier, or wage multiplier. "
        "Do not round upward to a nearby convenient value."
      )
    if productivity_floors:
      most_restrictive_floor = max(
        productivity_floors,
        key=lambda row: float(row.get("safe_capacity_units_per_supporting_fte_target_with_buffer") or 0.0),
      )
      hard_floor = float(most_restrictive_floor.get("safe_capacity_units_per_supporting_fte_target_with_buffer") or 0.0)
      repair_constraints["capacity_units_per_supporting_fte_must_be_at_or_above"] = round(hard_floor, 6)
      repair_constraints["recommended_capacity_units_per_supporting_fte_or_higher"] = round(hard_floor * 1.10, 6)
      repair_constraints["most_restrictive_floor_quarter"] = most_restrictive_floor
      repair_constraints["floor_violation_count"] = len(productivity_floors)
      repair_constraints["floor_instruction"] = (
        "Payroll/revenue is too high. Choose capacity_units_per_supporting_fte at or above the hard floor, "
        "preferably at or above the recommended value when changing OEWS title, FTE, benefits, wage tier, or wage multiplier. "
        "Do not round downward to a nearby convenient value."
      )
    if len(repair_constraints) > 2:
      compact_failure["gpt_repair_constraints"] = repair_constraints
    compact_failure["lookup_rule_reference"] = (
      "Use payroll_feasibility_mapping.rows[].repair_direction_rules from sql.post_intak_mapping_lookup; "
      "mapping rules are provided once in the main context and are not repeated per violation."
    )
  details = source.get("details") if isinstance(source.get("details"), dict) else {}
  if details and details is not source:
    nested = _compact_payroll_failure_for_gpt(details, max_violations=max_violations)
    if nested:
      compact_failure["details"] = nested
  return compact_failure


def _post_openai(
  *,
  url: str,
  headers: Dict[str, str],
  payload: Dict[str, Any],
  timeout_seconds: float,
):
  read_timeout = max(10.0, float(timeout_seconds or 180.0))
  return requests.post(url, headers=headers, json=payload, timeout=(10, read_timeout))


def _parse_responses_json_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  outputs = data.get("output")
  if isinstance(outputs, list):
    for item in outputs:
      if not isinstance(item, dict):
        continue
      for content in item.get("content") or []:
        if not isinstance(content, dict):
          continue
        text = content.get("text")
        if isinstance(text, str) and text.strip():
          try:
            parsed = json.loads(text)
          except Exception:
            continue
          if isinstance(parsed, dict):
            return parsed
  text = data.get("output_text")
  if isinstance(text, str) and text.strip():
    try:
      parsed = json.loads(text)
      return parsed if isinstance(parsed, dict) else None
    except Exception:
      return None
  return None


def _people_staffing_context(people_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  people = people_json if isinstance(people_json, dict) else {}
  rows: List[Dict[str, Any]] = []
  for group_name in ("people",):
    raw_items = people.get(group_name)
    if not isinstance(raw_items, list):
      continue
    for item in raw_items:
      if not isinstance(item, dict):
        continue
      role_title = str(item.get("role_title") or item.get("full_name") or item.get("role") or item.get("name") or "").strip()
      if not role_title:
        continue
      rows.append(
        {
          "source_group": group_name,
          "position_title": role_title,
          "annual_wage": _round_currency(item.get("annual_wage")),
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
    "key_people_from_intake": rows[:32],
    "supporting_staff_instruction": (
      "Key people are injected by Python from intake and use their intake/OEWS wage. "
      "GPT chooses exact supporting-staff OEWS titles from the NAICS oews_title_catalog and provides FTE only. "
      "Python resolves wages and calculates payroll."
    ),
  }


def _business_type_from_context(
  *,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
) -> str:
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  return str(
    ops.get("business_type")
    or facts.get("business_type")
    or facts.get("industry")
    or facts.get("business_description")
    or ""
  ).strip()


def _business_stage_from_context(
  *,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
) -> str:
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  return str(ops.get("business_stage") or facts.get("business_stage") or "").strip()


def _key_people_rows_from_intake(
  people_json: Optional[Dict[str, Any]],
  *,
  policy: Dict[str, Any],
  horizon: int,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  people = _people_json_with_resolved_key_person_wages(
    people_json,
    policy=policy,
    business_facts=business_facts,
    ops_json=ops_json,
  )
  raw_people = people.get("people") if isinstance(people.get("people"), list) else []
  default_benefits = round(float(policy.get("default_payroll_tax_benefits_pct") or 0.22), 2)
  rows: List[Dict[str, Any]] = []
  for person_index, person in enumerate(raw_people):
    if not isinstance(person, dict):
      continue
    role_title = str(person.get("role_title") or person.get("role") or person.get("title") or "").strip()
    person_name = str(person.get("full_name") or person.get("name") or "").strip() or f"key_person_{person_index + 1}"
    label = role_title or person_name or f"key_person_{person_index + 1}"
    annual_wage = _round_currency(person.get("annual_wage"))
    if annual_wage <= 0:
      _payroll_fail_fast(
        "payroll_headcount_key_person_wage_missing",
        f"Key person '{label}' is missing a positive intake/OEWS annual_wage.",
        stage="payroll_headcount_key_people",
        details={"person_index": person_index, "person": person},
      )
    wage_source = str(person.get("wage_source") or "intake_oews_key_person").strip() or "intake_oews_key_person"
    oews_occ_title = str(person.get("matched_occ_title") or person.get("oews_matched_title") or "").strip()
    for quarter_index in range(1, horizon + 1):
      quarter_annual_wage = _policy_adjusted_annual_wage(
        annual_wage,
        quarter_index=quarter_index,
        policy=policy,
        wage_positioning_multiplier=1.0,
      )
      rows.append(
        {
          "quarter_index": quarter_index,
          "staffing_class": "key_person",
          "position_title": role_title or label,
          "person_name": person_name,
          "starting_fte": 1.0,
          "hires": 0.0,
          "ending_fte": 1.0,
          "annual_wage": quarter_annual_wage,
          "base_annual_wage": annual_wage,
          "wage_source": wage_source,
          "wage_source_code": str(person.get("wage_source_code") or "").strip(),
          "oews_occ_title": oews_occ_title,
          "oews_matched_title": oews_occ_title,
          "oews_match_basis": "intake_key_person",
          "payroll_taxes_benefits_percent": default_benefits,
        }
      )
  return rows


def _oews_rows_for_business(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  people = people_json if isinstance(people_json, dict) else {}
  business_type = _business_type_from_context(business_facts=business_facts, ops_json=ops_json)
  naics_6 = str(
    people.get("business_naics_6")
    or ops.get("business_naics_6")
    or ops.get("naics_code")
    or ops.get("naics_6")
    or facts.get("business_naics_6")
    or facts.get("naics_code")
    or facts.get("naics_6")
    or ""
  ).strip()
  conn = get_mysql_connection()
  try:
    if not naics_6:
      naics_6 = str(_get_naics_from_business_type(conn, business_type) or "").strip()
    state_abbrev = (
      _normalize_state_abbrev(
        facts.get("address_state") or ops.get("address_state") or facts.get("state") or ops.get("state"),
        facts.get("address") or ops.get("address") or facts.get("business_address") or ops.get("business_address"),
      )
      or "US"
    )
    rows = _fetch_oews_rows_with_fallback(conn, state_abbrev=state_abbrev, naics_value=naics_6) if naics_6 else []
    if not rows and state_abbrev != "US" and naics_6:
      rows = _fetch_oews_rows_with_fallback(conn, state_abbrev="US", naics_value=naics_6)
  finally:
    try:
      conn.close()
    except Exception:
      pass
  return rows, naics_6


def _oews_title_catalog_from_rows(
  rows: Sequence[Dict[str, Any]],
  *,
  naics_6: str,
  max_items: Optional[int] = None,
) -> Dict[str, Any]:
  candidates: List[Dict[str, Any]] = []
  seen_titles: set[str] = set()
  for row in rows:
    occ_title = str(row.get("occ_title") or "").strip()
    occ_code = str(row.get("occ_code") or "").strip()
    normalized_title = occ_title.lower()
    if not occ_title or normalized_title == "all occupations" or normalized_title in seen_titles:
      continue
    picked, source = _select_wage(row, False)
    if picked is None:
      continue
    seen_titles.add(normalized_title)
    candidates.append(
      {
        "occ_title": occ_title,
        "occ_code": occ_code,
        "annual_wage": _round_currency(picked),
        "wage_source": source or "oews_median",
      }
    )
  candidates.sort(key=lambda item: (str(item.get("occ_code") or ""), str(item.get("occ_title") or "").lower()))
  return {
    "source_table": "oews_state_wages",
    "business_naics_6": str(naics_6 or "").strip(),
    "selection_rule": (
      "GPT must choose oews_occ_title exactly from title_candidates[].occ_title. "
      "Python uses the exact selected OEWS title row for wage math; there is no abstract role family/category layer."
    ),
    "candidate_count": len(candidates),
    "title_candidates": candidates if max_items is None else candidates[:max(1, int(max_items or 0))],
  }


def _oews_title_catalog_for_business(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  rows, naics_6 = _oews_rows_for_business(
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
  )
  catalog = _oews_title_catalog_from_rows(
    rows,
    naics_6=naics_6,
    max_items=None,
  )
  if not catalog.get("business_naics_6"):
    _payroll_fail_fast(
      "payroll_headcount_oews_naics_missing",
      "Payroll supporting-staff OEWS title selection requires business_naics_6 before GPT creates the headcount schedule.",
      stage="payroll_headcount_oews_title_catalog",
    )
  if not catalog.get("title_candidates"):
    _payroll_fail_fast(
      "payroll_headcount_oews_catalog_empty",
      f"No OEWS title candidates found for naics={catalog.get('business_naics_6')}.",
      stage="payroll_headcount_oews_title_catalog",
      details={"business_naics_6": catalog.get("business_naics_6")},
    )
  return catalog


def _key_person_title_preferences(role_title: str, notes: str) -> List[str]:
  text = f"{role_title} {notes}".lower()
  preferences: List[str] = []
  if "cfo" in text or "financial officer" in text or "finance" in text or "financial" in text:
    preferences.extend(["Financial Managers", "Business and Financial Operations Occupations"])
  if "ceo" in text or "chief executive" in text or "founder" in text or "president" in text:
    preferences.extend(["Chief Executives", "General and Operations Managers"])
  if "coo" in text or "operating officer" in text or "operations" in text:
    preferences.extend(["General and Operations Managers", "Transportation, Storage, and Distribution Managers"])
  if "technology" in text or "technical" in text or "cto" in text or "information" in text:
    preferences.extend(["Computer and Information Systems Managers"])
  if "marketing" in text:
    preferences.extend(["Marketing Managers", "Advertising, Marketing, Promotions, Public Relations, and Sales Managers"])
  if "sales" in text:
    preferences.extend(["Sales Managers", "Marketing and Sales Managers"])
  if "human resources" in text or "people officer" in text or "hr" in text:
    preferences.extend(["Human Resources Managers"])
  if "legal" in text or "counsel" in text or "lawyer" in text:
    preferences.extend(["Lawyers", "Legal Occupations"])
  deduped: List[str] = []
  seen: set[str] = set()
  for item in preferences:
    key = item.lower()
    if key in seen:
      continue
    seen.add(key)
    deduped.append(item)
  return deduped


def _resolve_key_person_oews_wage(
  person: Dict[str, Any],
  *,
  oews_rows: Sequence[Dict[str, Any]],
  catalog: Dict[str, Any],
  min_wage: int,
) -> Optional[Dict[str, Any]]:
  role_title = str(person.get("role_title") or person.get("role") or person.get("title") or "").strip()
  notes = str(
    person.get("primary_responsibilities")
    or person.get("paragraph")
    or person.get("relevant_background")
    or ""
  ).strip()
  requested_titles = [
    str(person.get("matched_occ_title") or "").strip(),
    str(person.get("oews_matched_title") or "").strip(),
    role_title,
  ]
  requested_titles.extend(_key_person_title_preferences(role_title, notes))
  title_candidates = [
    item
    for item in (catalog.get("title_candidates") or [])
    if isinstance(item, dict) and str(item.get("occ_title") or "").strip()
  ]
  rows_by_title = {
    str(row.get("occ_title") or "").strip(): row
    for row in oews_rows
    if str(row.get("occ_title") or "").strip()
  }

  def resolve_exact_or_contains(expected_title: str) -> Optional[Dict[str, Any]]:
    expected = str(expected_title or "").strip()
    if not expected:
      return None
    for candidate in title_candidates:
      candidate_title = str(candidate.get("occ_title") or "").strip()
      if candidate_title.lower() == expected.lower() or _title_contains(candidate_title, expected):
        row = rows_by_title.get(candidate_title)
        if not row:
          continue
        picked, source = _select_wage(row, False)
        wage = _round_currency(picked)
        if wage >= min_wage:
          return {
            "annual_wage": wage,
            "wage_source": f"oews_key_person:{source or 'oews_median'}",
            "matched_occ_title": candidate_title,
            "matched_occ_code": str(row.get("occ_code") or candidate.get("occ_code") or "").strip(),
            "match_basis": f"key_person_title_preference:{expected}",
          }
    return None

  for requested_title in requested_titles:
    resolved = resolve_exact_or_contains(requested_title)
    if resolved:
      return resolved

  role_tokens = set(_title_match_tokens(f"{role_title} {notes}"))
  if not role_tokens:
    return None
  best: Optional[Dict[str, Any]] = None
  best_score = 0
  for candidate in title_candidates:
    candidate_title = str(candidate.get("occ_title") or "").strip()
    candidate_tokens = set(_title_match_tokens(candidate_title))
    score = len(role_tokens.intersection(candidate_tokens))
    if score <= best_score:
      continue
    row = rows_by_title.get(candidate_title)
    if not row:
      continue
    picked, source = _select_wage(row, False)
    wage = _round_currency(picked)
    if wage < min_wage:
      continue
    best_score = score
    best = {
      "annual_wage": wage,
      "wage_source": f"oews_key_person:{source or 'oews_median'}",
      "matched_occ_title": candidate_title,
      "matched_occ_code": str(row.get("occ_code") or candidate.get("occ_code") or "").strip(),
      "match_basis": f"key_person_token_overlap:{score}",
    }
  return best if best_score >= 2 else None


def _people_json_with_resolved_key_person_wages(
  people_json: Optional[Dict[str, Any]],
  *,
  policy: Dict[str, Any],
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  people = deepcopy(people_json) if isinstance(people_json, dict) else {}
  raw_people = people.get("people") if isinstance(people.get("people"), list) else []
  if not raw_people:
    return people
  unresolved_indexes = [
    idx
    for idx, person in enumerate(raw_people)
    if isinstance(person, dict) and _round_currency(person.get("annual_wage")) <= 0
  ]
  if not unresolved_indexes:
    return people
  min_wage = _round_currency(policy.get("min_annual_wage") or 25000)
  oews_rows, naics_6 = _oews_rows_for_business(
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people,
  )
  catalog = _oews_title_catalog_from_rows(
    oews_rows,
    naics_6=naics_6,
    max_items=max(1, len(oews_rows)),
  )
  if not catalog.get("title_candidates"):
    _payroll_fail_fast(
      "payroll_headcount_key_person_oews_catalog_empty",
      "Key-person payroll wages cannot be resolved because the NAICS OEWS title catalog is empty.",
      stage="payroll_headcount_key_people_preflight",
      details={
        "business_naics_6": naics_6,
        "source_table": "oews_state_wages",
      },
    )
  for idx in unresolved_indexes:
    person = raw_people[idx]
    if not isinstance(person, dict):
      continue
    resolved = _resolve_key_person_oews_wage(
      person,
      oews_rows=oews_rows,
      catalog=catalog,
      min_wage=min_wage,
    )
    if not resolved:
      label = str(person.get("role_title") or person.get("full_name") or f"key_person_{idx + 1}").strip()
      _payroll_fail_fast(
        "payroll_headcount_key_person_wage_missing",
        f"Key person '{label}' is missing a positive wage and could not be resolved to an exact OEWS title.",
        stage="payroll_headcount_key_people_preflight",
        details={
          "person_index": idx,
          "person": person,
          "business_naics_6": naics_6,
          "candidate_count": catalog.get("candidate_count"),
          "source_table": "oews_state_wages",
          "required_action": (
            "Provide a positive annual_wage or an OEWS-resolvable role_title/oews_matched_title before "
            "the payroll_headcount_schedule GPT step spends runtime."
          ),
        },
      )
    person["annual_wage"] = resolved["annual_wage"]
    person["wage_source"] = resolved["wage_source"]
    person["matched_occ_title"] = resolved["matched_occ_title"]
    person["oews_matched_title"] = resolved["matched_occ_title"]
    person["wage_source_code"] = resolved.get("matched_occ_code", "")
    person["oews_match_basis"] = resolved.get("match_basis", "key_person_oews_resolution")
  people["people"] = raw_people
  return people


def _resolve_supporting_staff_wages(
  rows: Sequence[Dict[str, Any]],
  *,
  policy: Dict[str, Any],
  capacity_assumptions: Dict[str, Any],
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  oews_rows, naics_6 = _oews_rows_for_business(
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
  )
  min_wage = _round_currency(policy.get("min_annual_wage") or 25000)
  catalog = _oews_title_catalog_from_rows(
    oews_rows,
    naics_6=naics_6,
    max_items=max(1, len(oews_rows)),
  )
  catalog_by_title = {
    str(item.get("occ_title") or "").strip(): item
    for item in catalog.get("title_candidates") or []
    if str(item.get("occ_title") or "").strip()
  }
  if not catalog_by_title:
    _payroll_fail_fast(
      "payroll_headcount_oews_catalog_empty",
      f"No OEWS title candidates found for naics={naics_6}.",
      stage="payroll_headcount_wage_resolution",
      details={"business_naics_6": naics_6},
    )
  wage_cache: Dict[str, Dict[str, Any]] = {}
  resolved_rows: List[Dict[str, Any]] = []
  for row in rows:
    declared_oews_title = str(row.get("oews_occ_title") or "").strip()
    position_title = str(row.get("position_title") or declared_oews_title or "").strip()
    cache_key = declared_oews_title.lower()
    wage_info = wage_cache.get(cache_key)
    if wage_info is None:
      matched_title = declared_oews_title
      annual_wage: Optional[int] = None
      wage_source = ""
      matched_row = None
      if not declared_oews_title:
        _payroll_fail_fast(
          "payroll_headcount_oews_title_missing",
          "Every supporting-staff payroll row must include oews_occ_title from the full NAICS OEWS title catalog.",
          stage="payroll_headcount_wage_resolution",
          details={"position_title": position_title, "business_naics_6": naics_6},
        )
      if declared_oews_title not in catalog_by_title:
        _payroll_fail_fast(
          "payroll_headcount_oews_title_not_in_catalog",
          f"Selected oews_occ_title='{declared_oews_title}' is not in the full NAICS OEWS title catalog.",
          stage="payroll_headcount_wage_resolution",
          details={
            "position_title": position_title,
            "oews_occ_title": declared_oews_title,
            "business_naics_6": naics_6,
          },
        )
      if declared_oews_title:
        for oews_row in oews_rows:
          if str(oews_row.get("occ_title") or "").strip() == declared_oews_title:
            matched_row = oews_row
            break
      if matched_row:
        picked, picked_source = _select_wage(matched_row, False)
        if picked is not None:
          annual_wage = _round_currency(picked)
          wage_source = f"oews_title_catalog:{picked_source or 'oews_median'}"
      if annual_wage is None:
        _payroll_fail_fast(
          "payroll_headcount_oews_wage_missing",
          f"Selected oews_occ_title='{declared_oews_title}' has no positive OEWS wage available.",
          stage="payroll_headcount_wage_resolution",
          details={
            "position_title": position_title,
            "oews_occ_title": declared_oews_title,
            "business_naics_6": naics_6,
            "wage_rule": "OEWS title catalog is required; no policy default wage fallback exists.",
          },
        )
      if annual_wage < min_wage:
        _payroll_fail_fast(
          "payroll_headcount_resolved_wage_below_policy_floor",
          f"Selected oews_occ_title='{declared_oews_title}' resolved annual_wage={annual_wage}; min={min_wage}.",
          stage="payroll_headcount_wage_resolution",
          details={
            "position_title": position_title,
            "annual_wage": annual_wage,
            "min_annual_wage": min_wage,
            "wage_source": wage_source,
            "business_naics_6": naics_6,
          },
        )
      wage_info = {
        "base_annual_wage": annual_wage,
        "wage_source": wage_source,
        "wage_source_code": naics_6,
        "oews_occ_code": str((matched_row or {}).get("occ_code") or ""),
        "oews_matched_title": matched_title,
        "oews_match_basis": "exact_oews_title_catalog_selection",
      }
      wage_cache[cache_key] = wage_info
    quarter_index = int(row.get("quarter_index") or 0)
    adjusted_annual_wage = _policy_adjusted_annual_wage(
      wage_info.get("base_annual_wage"),
      quarter_index=quarter_index,
      policy=policy,
      wage_positioning_multiplier=float(capacity_assumptions.get("wage_positioning_multiplier") or 1.0),
    )
    resolved_rows.append(
      {
        **deepcopy(row),
        "staffing_class": "supporting_staff",
        "position_title": str(wage_info.get("oews_matched_title") or position_title or ""),
        "oews_occ_title": str(wage_info.get("oews_matched_title") or ""),
        "annual_wage": int(adjusted_annual_wage),
        "base_annual_wage": int(wage_info["base_annual_wage"]),
        "wage_positioning_tier": str(capacity_assumptions.get("wage_positioning_tier") or ""),
        "wage_positioning_multiplier": float(capacity_assumptions.get("wage_positioning_multiplier") or 1.0),
        "annual_wage_inflation_rate": float(policy.get("annual_wage_inflation_rate") or 0.0),
        "wage_source": str(wage_info["wage_source"]),
        "wage_source_code": str(wage_info.get("wage_source_code") or ""),
        "oews_occ_code": str(wage_info.get("oews_occ_code") or ""),
        "oews_matched_title": str(wage_info.get("oews_matched_title") or ""),
        "oews_match_basis": str(wage_info.get("oews_match_basis") or ""),
      }
    )
  return resolved_rows


def _title_key(value: Any) -> str:
  return str(value or "").strip().lower()


def _quarter_title_counts(rows: Sequence[Dict[str, Any]]) -> Dict[int, int]:
  counts: Dict[int, int] = {}
  for row in rows:
    if str(row.get("staffing_class") or "supporting_staff").strip().lower() == "key_person":
      continue
    quarter_index = int(row.get("quarter_index") or 0)
    counts[quarter_index] = int(counts.get(quarter_index) or 0) + 1
  return counts


def _validate_supporting_title_lifecycle(
  rows: Sequence[Dict[str, Any]],
  *,
  horizon: int,
) -> None:
  rows_by_title: Dict[str, Dict[int, Dict[str, Any]]] = {}
  title_labels: Dict[str, str] = {}
  for row in rows:
    staffing_class = str(row.get("staffing_class") or "supporting_staff").strip().lower() or "supporting_staff"
    if staffing_class == "key_person":
      continue
    oews_title = str(row.get("oews_occ_title") or row.get("oews_matched_title") or "").strip()
    if not oews_title:
      continue
    title_key = oews_title.lower()
    title_labels[title_key] = oews_title
    quarter_index = int(row.get("quarter_index") or 0)
    if 1 <= quarter_index <= horizon:
      rows_by_title.setdefault(title_key, {})[quarter_index] = row

  for title_key, quarter_rows in rows_by_title.items():
    label = title_labels.get(title_key) or title_key
    active_quarters: List[int] = []
    for quarter_index, row in sorted(quarter_rows.items()):
      starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
      hires = round(float(row.get("hires") or 0.0), 2)
      ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
      if max(starting_fte, hires, ending_fte) > 0.0:
        active_quarters.append(quarter_index)
    if not active_quarters:
      _payroll_fail_fast(
        "payroll_headcount_dead_support_title",
        (
          f"OEWS title '{label}' appears in payroll_headcount_grid but has zero FTE in every quarter. "
          "GPT must either assign positive FTE to every selected OEWS title or remove that title from "
          "the selected payroll schedule."
        ),
        stage="payroll_headcount_title_lifecycle",
        details={
          "oews_occ_title": label,
          "horizon": horizon,
          "required_action": (
            "Return the full Q1-Q20 payroll_headcount_grid with positive starting_fte/ending_fte "
            "for this selected title in at least one quarter, or omit the title entirely if it was not selected."
          ),
        },
      )
    first_active = min(active_quarters)
    for quarter_index in range(first_active, horizon + 1):
      row = quarter_rows.get(quarter_index)
      if not isinstance(row, dict):
        _payroll_fail_fast(
          "payroll_headcount_support_title_missing_after_start",
          f"OEWS title '{label}' starts in Q{first_active} but has no row in Q{quarter_index}.",
          stage="payroll_headcount_title_lifecycle",
          details={"oews_occ_title": label, "first_active_quarter": first_active, "missing_quarter": quarter_index},
        )
      ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
      if ending_fte <= 0.0:
        _payroll_fail_fast(
          "payroll_headcount_support_title_stops_after_start",
          f"OEWS title '{label}' starts in Q{first_active} but ending_fte is zero in Q{quarter_index}.",
          stage="payroll_headcount_title_lifecycle",
          details={"oews_occ_title": label, "first_active_quarter": first_active, "violating_quarter": quarter_index},
        )


def _validate_payroll_title_rows(
  rows: Sequence[Dict[str, Any]],
  *,
  policy: Dict[str, Any],
  require_annual_wage: bool = True,
) -> None:
  horizon = _contract_horizon_quarters()
  quarters = {int(row.get("quarter_index") or 0) for row in rows}
  if quarters != set(range(1, horizon + 1)):
    missing = sorted(set(range(1, horizon + 1)) - quarters)
    extra = sorted(quarter for quarter in quarters if quarter < 1 or quarter > horizon)
    _payroll_fail_fast(
      "payroll_headcount_contract_missing_full_horizon",
      f"payroll_headcount_grid must include at least one OEWS-title/FTE row for every Q1-Q{horizon}; missing={missing} extra={extra}.",
      stage="payroll_headcount_title_row_validation",
      details={"missing": missing, "extra": extra, "horizon": horizon},
    )
  max_title_rows = int(policy.get("max_oews_title_rows_per_quarter") or 20)
  for quarter_index, count in _quarter_title_counts(rows).items():
    if count > max_title_rows:
      _payroll_fail_fast(
        "payroll_headcount_contract_too_many_title_rows",
        f"Q{quarter_index} has {count} OEWS title rows; max={max_title_rows} from post_intake_headcount_policy_lookup.",
        stage="payroll_headcount_title_row_validation",
        details={"quarter_index": quarter_index, "row_count": count, "max_oews_title_rows": max_title_rows},
      )
  _validate_supporting_title_lifecycle(rows, horizon=horizon)
  min_benefits = round(float(policy.get("min_payroll_tax_benefits_pct") or 0.12), 2)
  max_benefits = round(float(policy.get("max_payroll_tax_benefits_pct") or 0.35), 2)
  min_annual_wage = _round_currency(policy.get("min_annual_wage") or 25000)
  previous_by_title: Dict[str, float] = {}
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    staffing_class = str(row.get("staffing_class") or "supporting_staff").lower()
    title_label = str(row.get("position_title") or row.get("oews_occ_title") or row.get("person_name") or "").strip()
    if staffing_class == "key_person":
      title_identity = _title_key(row.get("person_name") or title_label)
    else:
      title_identity = _title_key(row.get("oews_occ_title"))
      if not title_identity:
        _payroll_fail_fast(
          "payroll_headcount_oews_title_missing",
          f"Q{quarter_index} supporting-staff row must include exact oews_occ_title.",
          stage="payroll_headcount_title_row_validation",
        )
    continuity_key = f"{staffing_class}::{title_identity}"
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    hires = round(float(row.get("hires") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    if quarter_index > 1 and continuity_key in previous_by_title and abs(starting_fte - previous_by_title[continuity_key]) > 0.01:
      prior_ending_fte = previous_by_title[continuity_key]
      _payroll_fail_fast(
        "payroll_headcount_contract_continuity_failed",
        f"Q{quarter_index} {title_label or title_identity} starting_fte must equal prior quarter ending_fte.",
        stage="payroll_headcount_title_row_validation",
        details={
          "quarter_index": quarter_index,
          "title": title_label or title_identity,
          "starting_fte": starting_fte,
          "prior_quarter_ending_fte": prior_ending_fte,
          "required_starting_fte": prior_ending_fte,
          "ending_fte": ending_fte,
          "hires": hires,
          "required_hires_if_ending_kept": round(max(0.0, ending_fte - prior_ending_fte), 2),
          "required_action": (
            "For this same OEWS title and quarter, set starting_fte equal to the prior quarter ending_fte. "
            "Put the increase in hires so starting_fte + hires = ending_fte. Do not make starting_fte jump."
          ),
        },
      )
    if abs((starting_fte + hires) - ending_fte) > 0.01:
      _payroll_fail_fast(
        "payroll_headcount_contract_math_failed",
        f"Q{quarter_index} {title_label or title_identity} starting_fte + hires must equal ending_fte.",
        stage="payroll_headcount_title_row_validation",
        details={
          "quarter_index": quarter_index,
          "title": title_label or title_identity,
          "starting_fte": starting_fte,
          "hires": hires,
          "ending_fte": ending_fte,
          "required_hires": round(max(0.0, ending_fte - starting_fte), 2),
          "required_action": "Set hires so starting_fte + hires exactly equals ending_fte for this row.",
        },
      )
    benefits_pct = round(float(_safe_ratio(row.get("payroll_taxes_benefits_percent")) or 0.0), 2)
    if benefits_pct < min_benefits or benefits_pct > max_benefits:
      _payroll_fail_fast(
        "payroll_headcount_schedule_benefits_invalid",
        f"Q{quarter_index} {title_label or title_identity} payroll_taxes_benefits_percent must be {min_benefits:.2f}-{max_benefits:.2f} per post_intake_headcount_policy_lookup.",
        stage="payroll_headcount_title_row_validation",
      )
    annual_wage = _round_currency(row.get("annual_wage"))
    if require_annual_wage and annual_wage <= 0:
      _payroll_fail_fast(
        "payroll_headcount_schedule_wage_missing",
        f"Q{quarter_index} {title_label or title_identity} annual_wage must be resolved by the payroll schedule builder.",
        stage="payroll_headcount_title_row_validation",
      )
    if require_annual_wage and annual_wage < min_annual_wage:
      _payroll_fail_fast(
        "payroll_headcount_schedule_wage_below_policy_floor",
        f"Q{quarter_index} {title_label or title_identity} annual_wage={annual_wage}; min={min_annual_wage} from post_intake_headcount_policy_lookup.",
        stage="payroll_headcount_title_row_validation",
      )
    previous_by_title[continuity_key] = ending_fte


def _business_context_text_for_payroll(
  *,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
) -> str:
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  parts = [
    facts.get("business_name"),
    facts.get("business_type"),
    facts.get("industry"),
    facts.get("business_description"),
    ops.get("business_type"),
    ops.get("business_description"),
    ops.get("business_description_summary"),
    ops.get("fulfillment_summary"),
    ops.get("fulfillment_model_summary"),
    ops.get("growth_lever"),
    ops.get("capacity_driver"),
    ops.get("unit_name"),
  ]
  return " ".join(str(item or "").lower() for item in parts if str(item or "").strip())


def _average_fte_by_quarter_from_rows(rows: Sequence[Dict[str, Any]]) -> Dict[int, float]:
  totals: Dict[int, float] = {}
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    if quarter_index <= 0:
      continue
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    totals[quarter_index] = round(float(totals.get(quarter_index) or 0.0) + ((starting_fte + ending_fte) / 2.0), 2)
  return totals


def _payroll_capacity_guardrails(
  *,
  model_input_json: Optional[Dict[str, Any]],
  policy: Dict[str, Any],
  payroll_headcount_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del payroll_headcount_contract
  horizon = _contract_horizon_quarters()
  revenue_driver_context = _revenue_driver_context_from_model_input(model_input_json)
  quarter_rows: List[Dict[str, Any]] = []
  for item in revenue_driver_context.get("quarter_rows") or []:
    if not isinstance(item, dict):
      continue
    quarter_index = int(item.get("quarter_index") or 0)
    if quarter_index < 1 or quarter_index > horizon:
      continue
    products = [product for product in (item.get("product_rows") or []) if isinstance(product, dict)]
    total_capacity = round(sum(float(product.get("capacity_units") or 0.0) for product in products), 2)
    weighted_capacity = sum(max(0.0, float(product.get("capacity_units") or 0.0)) for product in products)
    weighted_utilization = (
      round(
        sum(
          max(0.0, float(product.get("capacity_units") or 0.0))
          * max(0.0, float(product.get("utilization") or 0.0))
          for product in products
        )
        / weighted_capacity,
        4,
      )
      if weighted_capacity > 0
      else 0.0
    )
    quarter_rows.append(
      {
        "quarter_index": quarter_index,
        "total_structural_capacity_units": total_capacity,
        "weighted_utilization": weighted_utilization,
        "computed_revenue_from_model_input": int(item.get("computed_revenue_from_model_input") or 0),
        "product_rows": products,
      }
    )
  return {
    "source_table": "post_intake_headcount_policy_lookup",
    "headcount_economic_basis": str(policy.get("headcount_economic_basis") or "capacity_units_per_supporting_fte"),
    "min_capacity_coverage_ratio": round(float(policy.get("min_capacity_coverage_ratio") or 1.0), 4),
    "payroll_revenue_sanity_bounds": deepcopy(policy.get("payroll_revenue_sanity_bounds") or {}),
    "payroll_trend_rules": deepcopy(policy.get("payroll_trend_rules") or {}),
    "wage_positioning_multiplier_bounds": deepcopy(policy.get("wage_positioning_multiplier") or {}),
    "utilization_pressure_threshold": round(float(policy.get("utilization_pressure_threshold") or 0.85), 4),
    "rule": (
      "GPT must choose capacity_labor_model/labor_intensity_class, wage_positioning_tier, "
      "wage_positioning_multiplier from SQL policy options, plus a positive business-specific capacity_units_per_supporting_fte. "
      "Python then uses payroll FTE as the causal capacity envelope; revenue can only be supported by that capacity."
    ),
    "quarter_rows": quarter_rows,
  }


def _payroll_decision_options_from_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
  """Compact SQL-rendered options GPT chooses from; no Python business defaults."""
  wage_options = headcount_wage_positioning_options(policy)
  sanity_bounds = deepcopy(policy.get("payroll_revenue_sanity_bounds") or {})
  if not wage_options:
    _payroll_fail_fast(
      "payroll_headcount_wage_positioning_options_missing",
      "post_intake_headcount_policy_lookup must provide wage positioning option rows.",
      stage="payroll_headcount_policy_options",
      details={"policy_source": "post_intake_headcount_policy_lookup.wage_positioning_multiplier"},
    )
  return {
    "source_table": "post_intake_headcount_policy_lookup",
    "selection_rule": (
      "GPT chooses capacity_labor_model, labor_intensity_class, a positive business-specific "
      "capacity_units_per_supporting_fte assumption, one wage_positioning_options row, "
      "and one target payroll percent inside payroll_revenue_sanity_bounds as business context. "
      "Python validates mechanical FTE continuity and uses FTE times productivity as the revenue capacity envelope; "
      "Python also validates payroll/revenue economic feasibility against the table sanity bounds after deriving supported capacity; "
      "it never substitutes defaults."
    ),
    "capacity_labor_model_values": deepcopy(policy.get("capacity_labor_model_values") or []),
    "labor_intensity_class_values": deepcopy(policy.get("labor_intensity_class_values") or []),
    "capacity_units_per_supporting_fte_rule": "positive GPT-selected capacity productivity assumption; not bounded by universal capacity-per-FTE reasonableness ranges",
    "wage_positioning_options": wage_options,
    "payroll_revenue_sanity_bounds": sanity_bounds,
    "payroll_tax_benefits_percent_bounds": {
      "min": round(float(policy.get("min_payroll_tax_benefits_pct") or 0.0), 4),
      "max": round(float(policy.get("max_payroll_tax_benefits_pct") or 0.0), 4),
    },
    "annual_wage_inflation_rate": round(float(policy.get("annual_wage_inflation_rate") or 0.0), 4),
  }


def _supporting_staff_guardrails_for_gpt(
  guardrails: Dict[str, Any],
  *,
  people_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  people = people_json if isinstance(people_json, dict) else {}
  key_people_count = len([item for item in (people.get("people") or []) if isinstance(item, dict)])
  out = deepcopy(guardrails if isinstance(guardrails, dict) else {})
  out["key_people_injected_by_python"] = key_people_count
  out["rule"] = (
    "GPT provides supporting-staff FTE only. Python injects key people from intake, "
    "then derives supported Capacity from total average FTE and GPT's capacity_units_per_supporting_fte."
  )
  adjusted_rows: List[Dict[str, Any]] = []
  for item in out.get("quarter_rows") or []:
    if not isinstance(item, dict):
      continue
    row = deepcopy(item)
    row["key_people_average_fte_injected_by_python"] = float(key_people_count)
    adjusted_rows.append(row)
  out["quarter_rows"] = adjusted_rows
  return out


def _payroll_capacity_grid_for_gpt(
  supporting_staff_guardrails: Dict[str, Any],
  *,
  horizon: int,
) -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  for item in supporting_staff_guardrails.get("quarter_rows") or []:
    if not isinstance(item, dict):
      continue
    quarter_index = int(item.get("quarter_index") or 0)
    if quarter_index < 1 or quarter_index > horizon:
      continue
    rows.append(
      {
        "q": quarter_index,
        "total_structural_capacity_units": round(float(item.get("total_structural_capacity_units") or 0.0), 2),
        "weighted_utilization": round(float(item.get("weighted_utilization") or 0.0), 4),
        "key_people_average_fte_injected_by_python": round(
          float(item.get("key_people_average_fte_injected_by_python") or 0.0),
          2,
        ),
        "computed_revenue_from_model_input": int(round(float(item.get("computed_revenue_from_model_input") or 0.0))),
        "rule": (
          "Context only. GPT selects the OEWS title mix, productivity assumption, and FTE ramp using "
          "business judgment. Python will derive payroll-supported capacity from the returned FTE; "
          "revenue is constrained by that derived capacity and this grid is not a demand floor."
        ),
      }
    )
  rows = sorted(rows, key=lambda row: int(row.get("q") or 0))
  expected = list(range(1, horizon + 1))
  actual = [int(row.get("q") or 0) for row in rows]
  if actual != expected:
    _payroll_fail_fast(
      "payroll_capacity_grid_incomplete",
      (
        "payroll_capacity_grid must contain exactly Q1-Q20 from "
        "post_intake_headcount_policy_lookup before GPT is called."
      ),
      stage="payroll_headcount_contract_request",
      details={"expected_quarters": expected, "actual_quarters": actual},
    )
  return rows


def _payroll_capacity_guardrail_summary_for_gpt(guardrails: Dict[str, Any]) -> Dict[str, Any]:
  return {
    "source_table": guardrails.get("source_table"),
    "headcount_economic_basis": guardrails.get("headcount_economic_basis"),
    "min_capacity_coverage_ratio": guardrails.get("min_capacity_coverage_ratio"),
    "utilization_pressure_threshold": guardrails.get("utilization_pressure_threshold"),
    "rule": guardrails.get("rule"),
    "quarter_grid_context_key": "payroll_capacity_grid",
  }


def _compact_stage_ramp_contract_for_payroll(stage_ramp_contract: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  source = stage_ramp_contract if isinstance(stage_ramp_contract, dict) else {}
  compact: Dict[str, Any] = {}
  for key, value in source.items():
    if key in {"prompt_context", "raw_openai_response"}:
      continue
    if isinstance(value, list):
      rows: List[Dict[str, Any]] = []
      for item in value[:20]:
        if not isinstance(item, dict):
          continue
        rows.append(
          {
            out_key: item.get(out_key)
            for out_key in (
              "q",
              "quarter_index",
              "revenue_growth_pct",
              "revenue_growth_percent",
              "utilization",
              "capacity",
              "planning_stage",
              "business_stage",
            )
            if out_key in item
          }
        )
      if rows:
        compact[key] = rows
      continue
    if isinstance(value, dict):
      compact[key] = {
        out_key: child
        for out_key, child in value.items()
        if not isinstance(child, (dict, list))
      }
      continue
    compact[key] = value
  return compact


def validate_payroll_headcount_contract_payload(
  payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  candidate = post_intake_gpt_contract_normalize_payload(
    contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    payload=payload if isinstance(payload, dict) else {},
  )
  contract_errors = post_intake_gpt_contract_payload_errors(
    contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    payload=candidate,
  )
  if contract_errors:
    _payroll_fail_fast(
      "payroll_headcount_contract_table_validation_failed",
      "; ".join(str(item) for item in contract_errors[:20]),
      stage="payroll_headcount_contract_payload",
      details={"errors": contract_errors[:20]},
    )
  horizon_errors = post_intake_gpt_contract_horizon_errors(
    contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    payload=candidate,
  )
  if horizon_errors:
    _payroll_fail_fast(
      "payroll_headcount_contract_horizon_violation",
      "; ".join(str(item) for item in horizon_errors[:20]),
      stage="payroll_headcount_contract_payload",
      details={"errors": horizon_errors[:20]},
    )
  policy = post_intake_headcount_policy_for("default")
  capacity_assumptions = _payroll_contract_capacity_assumptions(candidate, policy=policy)
  rows = _payroll_headcount_grid_rows(candidate)
  _validate_payroll_title_rows(rows, policy=policy, require_annual_wage=False)
  rationale = str(candidate.get("rationale") or "").strip()
  if not rationale:
    _payroll_fail_fast(
      "payroll_headcount_contract_rationale_missing",
      "payroll_headcount contract rationale is required.",
      stage="payroll_headcount_contract_payload",
    )
  required_decision_source = str(
    (policy or {}).get("required_decision_source")
    or "payroll_headcount_schedule.payroll_headcount_grid"
  ).strip()
  return {
    "contract_version": "payroll_headcount_schedule_gpt_v1",
    "decision_source": required_decision_source,
    "capacity_labor_model": capacity_assumptions["capacity_labor_model"],
    "labor_intensity_class": capacity_assumptions["labor_intensity_class"],
    "wage_positioning_tier": capacity_assumptions["wage_positioning_tier"],
    "wage_positioning_multiplier": capacity_assumptions["wage_positioning_multiplier"],
    "capacity_units_per_supporting_fte": capacity_assumptions["capacity_units_per_supporting_fte"],
    "target_payroll_percent_of_revenue": round(float(_safe_ratio(candidate.get("target_payroll_percent_of_revenue")) or 0.0), 4),
    "payroll_headcount_grid": rows,
    "rationale": rationale,
  }


def _build_payroll_headcount_payload_from_contract(
  payroll_headcount_contract: Optional[Dict[str, Any]],
  *,
  draft_id: Any = "",
  client_id: Any = "",
  policy_code: Any = "default",
  model_input_json: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  policy = post_intake_headcount_policy_for(policy_code=policy_code)
  horizon = int((policy or {}).get("schedule_horizon_quarters") or 0)
  contract_horizon = _contract_horizon_quarters()
  if horizon != contract_horizon:
    _payroll_fail_fast(
      "payroll_headcount_policy_invalid",
      f"schedule_horizon_quarters must be {contract_horizon}",
      stage="payroll_headcount_payload_build",
      details={"policy_horizon": horizon, "contract_horizon": contract_horizon},
    )
  supporting_rows = _payroll_headcount_grid_rows(payroll_headcount_contract)
  capacity_assumptions = _payroll_contract_capacity_assumptions(payroll_headcount_contract, policy=policy)
  _validate_payroll_title_rows(supporting_rows, policy=policy, require_annual_wage=False)
  key_people_rows = _key_people_rows_from_intake(
    people_json,
    policy=policy,
    horizon=horizon,
    business_facts=business_facts,
    ops_json=ops_json,
  )
  resolved_supporting_rows = _resolve_supporting_staff_wages(
    supporting_rows,
    policy=policy,
    capacity_assumptions=capacity_assumptions,
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
  )
  rows = [
    *key_people_rows,
    *resolved_supporting_rows,
  ]
  _validate_payroll_title_rows(rows, policy=policy, require_annual_wage=True)
  normalized_rows: List[Dict[str, Any]] = []
  quarter_totals_by_index: Dict[int, Dict[str, Any]] = {
    quarter: {"quarter_index": quarter, "ending_fte": 0.0, "payroll": 0}
    for quarter in range(1, horizon + 1)
  }
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    hires = round(float(row.get("hires") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    annual_wage = _round_currency(row.get("annual_wage"))
    if annual_wage <= 0:
      _payroll_fail_fast(
        "payroll_headcount_schedule_wage_invalid",
        f"Q{quarter_index} annual_wage must be > 0.",
        stage="payroll_headcount_payload_build",
        details={"quarter_index": quarter_index, "annual_wage": annual_wage},
      )
    benefits_pct = round(float(_safe_ratio(row.get("payroll_taxes_benefits_percent")) or 0.0), 2)
    average_fte = round((starting_fte + ending_fte) / 2.0, 2)
    quarterly_wage_cost = _round_currency((average_fte * annual_wage) / 4.0)
    quarterly_taxes_benefits = _round_currency(quarterly_wage_cost * benefits_pct)
    total_quarterly_payroll = int(quarterly_wage_cost + quarterly_taxes_benefits)
    schedule_row = {
      **deepcopy(row),
      "staffing_class": str(row.get("staffing_class") or "supporting_staff").strip() or "supporting_staff",
      "average_fte": average_fte,
      "annual_wage": annual_wage,
      "payroll_taxes_benefits_percent": benefits_pct,
      "quarterly_wage_cost": quarterly_wage_cost,
      "quarterly_taxes_benefits": quarterly_taxes_benefits,
      "total_quarterly_payroll": total_quarterly_payroll,
    }
    normalized_rows.append(schedule_row)
    quarter_total = quarter_totals_by_index[quarter_index]
    quarter_total["ending_fte"] = round(float(quarter_total.get("ending_fte") or 0.0) + ending_fte, 2)
    quarter_total["payroll"] = int(quarter_total.get("payroll") or 0) + total_quarterly_payroll
  quarter_totals = [quarter_totals_by_index[quarter] for quarter in range(1, horizon + 1)]
  payload = {
    "contract_version": str((policy or {}).get("schedule_contract_version") or "payroll_headcount_schedule_v1"),
    "decision_source": str((policy or {}).get("required_decision_source") or "payroll_headcount_schedule.payroll_headcount_grid"),
    "draft_id": str(draft_id or "").strip(),
    "client_id": str(client_id or "").strip(),
    "policy_code": str(policy_code or "default").strip().lower() or "default",
    "source_table": "intake_consult_drafts",
    "source_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    "schedule_horizon_quarters": horizon,
    "headcount_economic_basis": str(policy.get("headcount_economic_basis") or "capacity_units_per_supporting_fte"),
    "capacity_labor_model": capacity_assumptions["capacity_labor_model"],
    "labor_intensity_class": capacity_assumptions["labor_intensity_class"],
    "wage_positioning_tier": capacity_assumptions["wage_positioning_tier"],
    "wage_positioning_multiplier": capacity_assumptions["wage_positioning_multiplier"],
    "capacity_units_per_supporting_fte": capacity_assumptions["capacity_units_per_supporting_fte"],
    "target_payroll_percent_of_revenue": round(float(_safe_ratio((payroll_headcount_contract or {}).get("target_payroll_percent_of_revenue")) or 0.0), 4),
    "rows": normalized_rows,
    "quarter_totals": quarter_totals,
  }
  validation_errors = validate_payroll_headcount_payload(payload, policy_code=policy_code)
  if validation_errors:
    _payroll_fail_fast(
      "payroll_headcount_schedule_validation_failed",
      "; ".join(validation_errors[:20]),
      stage="payroll_headcount_payload_build",
      details={"errors": validation_errors[:20]},
    )
  return payload


def build_payroll_headcount_payload_from_contract(
  payroll_headcount_contract: Optional[Dict[str, Any]],
  *,
  draft_id: Any = "",
  client_id: Any = "",
  policy_code: Any = "default",
  model_input_json: Optional[Dict[str, Any]] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  payload = payroll_headcount_contract if isinstance(payroll_headcount_contract, dict) else {}
  try:
    sequence_row = post_intake_process_sequence_step("payroll_headcount_schedule", required=True) or {}
  except Exception as exc:
    _payroll_fail_fast(
      "payroll_headcount_process_sequence_lookup_failed",
      str(exc),
      stage="payroll_headcount_process_sequence",
    )
    sequence_row = {}
  validation_subject_path = str(sequence_row.get("validation_subject_path") or "").strip()
  if validation_subject_path != "payroll_headcount_schedule.payroll_headcount_grid":
    _payroll_fail_fast(
      "payroll_headcount_process_sequence_validation_subject_mismatch",
      "payroll_headcount_process_sequence_validation_subject_mismatch: "
      f"expected=payroll_headcount_schedule.payroll_headcount_grid actual={validation_subject_path or 'missing'}",
      stage="payroll_headcount_process_sequence",
    )
  input_object_path = str(sequence_row.get("input_object_path") or "").strip()
  if "stage_ramp_contract.payroll_headcount_grid" in input_object_path:
    _payroll_fail_fast(
      "payroll_headcount_process_sequence_legacy_stage_ramp_input",
      "payroll_headcount_process_sequence_legacy_stage_ramp_input: payroll cannot be sourced from stage_ramp_contract.",
      stage="payroll_headcount_process_sequence",
    )
  if not isinstance(payload.get("payroll_headcount_grid"), list):
    _payroll_fail_fast(
      "payroll_headcount_grid_missing_from_payroll_contract",
      "payroll_headcount_grid_missing_from_payroll_contract: "
      "payroll_headcount_schedule must include payroll_headcount_grid from post_intake_gpt_contract_lookup.",
      stage="payroll_headcount_schedule_contract",
    )
  return _build_payroll_headcount_payload_from_contract(
    payload,
    draft_id=draft_id,
    client_id=client_id,
    policy_code=policy_code,
    model_input_json=model_input_json,
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=people_json,
  )


def _assert_payroll_contract_economic_feasible_for_retry(
  *,
  payroll_headcount: Dict[str, Any],
  model_input_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  """Validate GPT's payroll productivity/FTE contract before leaving payroll retry scope."""
  from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore

  horizon = int(payroll_headcount.get("schedule_horizon_quarters") or _contract_horizon_quarters())
  capacity_model_input_json = apply_payroll_supported_capacity_to_model_input(
    deepcopy(model_input_json if isinstance(model_input_json, dict) else {}),
    deepcopy(payroll_headcount),
    live_count=horizon,
  )
  payroll_model_input_json = apply_payroll_headcount_payload_to_model_input(
    deepcopy(capacity_model_input_json),
    deepcopy(payroll_headcount),
    live_count=horizon,
  )
  projected_finmo_json = build_python_finmo_json(model_input_json=deepcopy(payroll_model_input_json))
  violations = payroll_revenue_feasibility_violations(
    payroll_headcount=deepcopy(payroll_headcount),
    finmo_json=deepcopy(projected_finmo_json),
  )
  if violations:
    _payroll_fail_fast(
      "payroll_revenue_economic_feasibility_failed",
      (
        "GPT payroll_headcount_schedule is mechanically valid but economically infeasible against "
        "post_intake_headcount_policy_lookup payroll/revenue sanity bounds after payroll-supported capacity is applied."
      ),
      stage=stage,
      details={
        "violations": violations[:20],
        "capacity_units_per_supporting_fte": payroll_headcount.get("capacity_units_per_supporting_fte"),
        "labor_intensity_class": payroll_headcount.get("labor_intensity_class"),
        "target_payroll_percent_of_revenue": payroll_headcount.get("target_payroll_percent_of_revenue"),
        "required_action": (
          "GPT must revise the OEWS title FTE ramp, labor intensity class, wage positioning, or "
          "capacity_units_per_supporting_fte so FTE creates enough payroll-supported revenue capacity. "
          "Python will not clip payroll or revenue."
        ),
      },
    )


# ---------------------------------------------------------------------------
# Phase 9 P3.11 — Payroll iterative refinement constants + machinery
# fail-fast helpers.
#
# The 10-round hard cap on payroll GPT iterations. Sequential GPT
# calls in a feedback loop until validators accept or the cap fires.
# Equivalent in spirit to the funding / stage-ramp handler tool-call
# budgets (HARD_CAP_TOOL_CALLS = 10) but the payroll pattern is
# direct GPT iteration (no tool-calling session), matching the
# convergence pattern documented in doctrine.md §6.
# ---------------------------------------------------------------------------

_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS: int = 10

# Contextvar tracks the per-loop GPT call count for round-count-drift
# detection (machinery fail-fast invariant #2).
import contextvars as _payroll_contextvars  # noqa: E402

_PAYROLL_ITER_GPT_CALL_COUNT: "_payroll_contextvars.ContextVar[Optional[int]]" = (
  _payroll_contextvars.ContextVar(
    "payroll_iterative_refinement_gpt_call_count",
    default=None,
  )
)

# Layer A.2 wrapper codes — those whose ``details["errors"]`` carry
# Layer A.2 token-format codes from validate_payroll_headcount_payload.
# Codes outside this set are dispatched to the Layer A.1 (verbatim) or
# Layer A.3 (economic feasibility) paths.
_PAYROLL_LAYER_A2_WRAPPER_CODES = frozenset({
  "payroll_headcount_schedule_validation_failed",
  "payroll_headcount_payload_invalid",
})

_PAYROLL_LAYER_A3_CODE = "payroll_revenue_economic_feasibility_failed"


def _payroll_iterative_machinery_fail_fast(
  operation: str,
  message: str,
  details: Optional[Dict[str, Any]] = None,
) -> None:
  """Hard-stop on a payroll-iterative-refinement machinery
  malfunction. Distinct from :func:`_payroll_fail_fast` (which fires
  on validator/business-logic failures). Machinery fail-fasts name
  the specific broken component so an engineer can fix the
  iteration infrastructure itself.
  """
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
  )
  raise PostIntakePreconditionFailed(
    operation=str(operation or "").strip() or "payroll_iterative_refinement_machinery_violation",
    pipeline_stage="payroll_iterative_refinement",
    expected="payroll iterative-refinement machinery intact",
    actual=str(message or "").strip()[:600],
    details=details or {},
  )


def _assert_payroll_iterative_state_intact(
  *,
  round_n: int,
  user_context: Any,
  payload_base: Any,
) -> None:
  """Invariant #3: state corruption check between rounds. Every
  retry round must enter with a well-formed context and payload base.
  """
  if not isinstance(user_context, dict) or not user_context:
    _payroll_iterative_machinery_fail_fast(
      "payroll_iterative_refinement_state_corruption",
      f"round {round_n} entered with malformed user_context",
      details={
        "round_n": int(round_n),
        "user_context_type": type(user_context).__name__,
      },
    )
  if not isinstance(payload_base, dict) or "text" not in payload_base:
    _payroll_iterative_machinery_fail_fast(
      "payroll_iterative_refinement_state_corruption",
      f"round {round_n} entered with malformed payload_base",
      details={
        "round_n": int(round_n),
        "payload_base_type": type(payload_base).__name__,
        "payload_base_keys": (
          sorted(payload_base.keys()) if isinstance(payload_base, dict) else None
        ),
      },
    )


def _assert_payroll_iterative_budget_decoupled(*, round_n: int) -> None:
  """Invariant #6: budget decoupling. The payroll iterative loop uses
  ``_post_openai`` directly, which does not consume the run-wide GPT
  call budget. If a future refactor routes the call through
  ``call_gpt_responses_api_turn`` without ``counts_against_run_budget=
  False``, the run-wide budget would be commingled. This guard fires
  early on the unsupported configuration so the malfunction surfaces
  at the iteration scope, not silently downstream.

  The check is structural: there must be a non-None contextvar value
  before the call (set by the loop entry), guaranteeing the call is
  bounded by this loop's hard cap rather than the run-wide budget.
  """
  count = _PAYROLL_ITER_GPT_CALL_COUNT.get()
  if count is None:
    _payroll_iterative_machinery_fail_fast(
      "payroll_iterative_refinement_budget_decoupling_violation",
      (
        f"round {round_n} reached the GPT call site without the "
        "payroll iterative scope's contextvar set. The loop's "
        "hard cap is the only bound on these calls; without the "
        "contextvar, a refactor could leak the call onto the "
        "run-wide GPT budget."
      ),
      details={"round_n": int(round_n)},
    )


def _build_payroll_iterative_feedback_packet(
  *,
  exc: BaseException,
  parsed: Optional[Dict[str, Any]],
  round_n: int,
) -> Dict[str, Any]:
  """Dispatch by exception code → one of three feedback paths.

  Class A — Layer A.2 token codes via translator (raises on unmatched
              per the translator's fail-fast invariant).
  Class B — verbatim Layer A.1 contract-table prose errors.
  Class C — Layer A.3 economic feasibility via the existing
              ``_compact_payroll_failure_for_gpt`` mechanism.
  """
  details_raw = getattr(exc, "details", {})
  details = details_raw if isinstance(details_raw, dict) else {}
  exc_code = str(getattr(exc, "code", "") or "").strip()
  exc_message = str(exc) or ""
  # The parsed dict may have been mutated by the success path before
  # the exception fired — it may now contain raw_openai_response /
  # prompt_context which would introduce a circular reference (the
  # raw_openai_response wraps the same parsed dict). Strip those
  # before dumping; the excerpt is for GPT's prompt only, not for
  # storage.
  if isinstance(parsed, dict):
    excerpt_source = {
      k: v for k, v in parsed.items()
      if k not in {"raw_openai_response", "prompt_context"}
    }
    try:
      invalid_excerpt = json.dumps(excerpt_source, ensure_ascii=False, default=str)[:6000]
    except Exception:
      invalid_excerpt = ""
  else:
    invalid_excerpt = ""

  if exc_code == _PAYROLL_LAYER_A3_CODE:
    compact_source: Dict[str, Any] = {
      "error": exc_message,
      "violations": details.get("violations") or [],
    }
    for key, value in details.items():
      if key != "violations":
        compact_source[key] = value
    return {
      "feedback_class": "economic_feasibility",
      "round_n": int(round_n),
      "error": exc_message[:6000],
      "compacted_violations": _compact_payroll_failure_for_gpt(compact_source),
      "invalid_response_excerpt": invalid_excerpt,
    }

  if exc_code in _PAYROLL_LAYER_A2_WRAPPER_CODES:
    from client_intake_and_finmo.post_intake_headcount.payroll_validator_translator import (  # type: ignore
      translate_payroll_validator_codes,
    )
    codes = details.get("errors") or []
    translated = translate_payroll_validator_codes(codes)
    # Invariant #4: translator output well-formed. The translator
    # itself raises on malformation; this is the post-call guard at
    # the iteration boundary.
    if not isinstance(translated, dict) or "structured_failures" not in translated:
      _payroll_iterative_machinery_fail_fast(
        "payroll_validator_translator_malformed_output",
        "translator returned malformed result",
        details={"translated_type": type(translated).__name__},
      )
    if codes and not translated.get("structured_failures"):
      _payroll_iterative_machinery_fail_fast(
        "payroll_validator_translator_malformed_output",
        (
          f"translator returned empty structured_failures despite "
          f"{len(codes)} input code(s); iteration cannot refine"
        ),
        details={"input_codes": list(codes)[:10]},
      )
    return {
      "feedback_class": "schedule_validation",
      "round_n": int(round_n),
      "error": exc_message[:6000],
      "translated_failures": translated["structured_failures"],
      "invalid_response_excerpt": invalid_excerpt,
    }

  # Class B — verbatim contract-table errors. Layer A.1 prose codes
  # land here (and any other non-A.2/A.3 FailFastError raised by the
  # validation chain). GPT sees the prose strings as-is.
  raw_errors = details.get("errors") or []
  contract_table_errors = [str(item)[:500] for item in raw_errors][:20] or [
    exc_message[:500]
  ]
  return {
    "feedback_class": "contract_table",
    "round_n": int(round_n),
    "error": exc_message[:6000],
    "contract_table_errors": contract_table_errors,
    "exc_code": exc_code,
    "invalid_response_excerpt": invalid_excerpt,
  }


def estimate_payroll_headcount_schedule_with_gpt(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
  draft_id: Any = "",
  client_id: Any = "",
  previous_contract_failure: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Phase 9 P3.11 — payroll iterative refinement.

  The function runs up to ``_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS = 10``
  sequential GPT rounds. Each round validates the parsed contract
  via Layers A.1 + A.2 + A.3; on failure, the structured feedback
  packet is dispatched by exception class and threaded into the next
  round's ``previous_contract_failure``. The outer
  ``payroll_grid_rebuild_limit`` retry loop in initial_grid is
  removed — initial_grid runs are pure new authoring.

  When called from the convergence runner's payroll-repair path,
  ``previous_contract_failure`` carries the downstream-detected
  failure context (e.g., post-quarter-grid feasibility violation).
  When set, the loop seeds Round 1 with that context before
  invoking GPT.

  Machinery fail-fasts (7 invariants) protect the iteration mechanics:
  see ``_payroll_iterative_machinery_fail_fast`` and the
  ``_assert_payroll_iterative_*`` helpers above.
  """
  _assert_payroll_sequence_step(
    allowed_step_keys=["payroll_gpt_contract_request", "payroll_feasibility_repair"],
    allowed_executor_functions=[
      "estimate_payroll_headcount_schedule_with_gpt",
      "retry_payroll_headcount_schedule_from_feasibility_failure",
    ],
  )
  # P3.21 Part 2 housekeeping -- import the structured machinery
  # exception in function scope so the iteration loop's
  # `except PostIntakePreconditionFailed: raise` can route machinery
  # violations past the GPT-retry catch.
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
  )
  api_key = _openai_key()
  if not api_key:
    _payroll_fail_fast(
      "payroll_headcount_contract_openai_key_missing",
      "OPENAI_API_KEY is not configured.",
      stage="payroll_headcount_contract_request",
    )
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  policy = post_intake_headcount_policy_for("default")
  resolved_people_json = _people_json_with_resolved_key_person_wages(
    people_json,
    policy=policy,
    business_facts=business_facts,
    ops_json=ops_json,
  )
  finmo_rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
  ]
  payroll_capacity_guardrails = _payroll_capacity_guardrails(
    model_input_json=model_input_json,
    policy=policy or {},
  )
  payroll_supporting_staff_guardrails = _supporting_staff_guardrails_for_gpt(
    payroll_capacity_guardrails,
    people_json=resolved_people_json,
  )
  horizon = _contract_horizon_quarters()
  payroll_capacity_grid = _payroll_capacity_grid_for_gpt(
    payroll_supporting_staff_guardrails,
    horizon=horizon,
  )
  oews_title_catalog = _oews_title_catalog_for_business(
    business_facts=business_facts,
    ops_json=ops_json,
    people_json=resolved_people_json,
  )
  payroll_decision_options = _payroll_decision_options_from_policy(policy or {})
  payroll_feasibility_mapping = post_intake_payroll_feasibility_mapping()
  user_context = {
    "business_identity": {
      "business_name": str(facts.get("business_name") or facts.get("name") or ops.get("business_name") or "").strip(),
      "business_type": ops.get("business_type"),
      "business_stage": ops.get("business_stage") or facts.get("business_stage"),
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
    },
    "people_staffing_context": _people_staffing_context(resolved_people_json),
    "oews_title_catalog": oews_title_catalog,
    "financial_context": {
      "annual_revenue": (
        year1.get("company_revenue_total_year1")
        or year1.get("revenue_total_year1")
        or financials.get("current_revenue")
      ),
      "client_reported_current_num_employees": financials.get("current_num_employees"),
      "client_reported_payroll_total_year1": financials.get("payroll_total_year1"),
      "client_reported_owner_compensation": financials.get("owner_compensation"),
    },
    "stage_ramp_contract": _compact_stage_ramp_contract_for_payroll(stage_ramp_contract),
    "payroll_decision_options": payroll_decision_options,
    "payroll_feasibility_mapping": payroll_feasibility_mapping,
    "payroll_headcount_policy": {
      "source_table": "post_intake_headcount_policy_lookup",
      "policy_code": (policy or {}).get("policy_code"),
      "schedule_contract_version": (policy or {}).get("schedule_contract_version"),
      "schedule_horizon_quarters": (policy or {}).get("schedule_horizon_quarters"),
      "model_input_driver": (policy or {}).get("model_input_driver"),
      "headcount_economic_basis": (policy or {}).get("headcount_economic_basis"),
      "generic_oews_fallback_allowed": (policy or {}).get("generic_oews_fallback_allowed"),
      "salary_basis": (policy or {}).get("salary_basis"),
      "max_oews_title_rows_per_quarter": (policy or {}).get("max_oews_title_rows_per_quarter"),
      "currency_rounding": (policy or {}).get("currency_rounding"),
      "ratio_rounding": (policy or {}).get("ratio_rounding"),
      "notes": (policy or {}).get("notes"),
    },
    "payroll_capacity_guardrails": _payroll_capacity_guardrail_summary_for_gpt(payroll_supporting_staff_guardrails),
    "payroll_capacity_grid": payroll_capacity_grid,
    "revenue_driver_context": _revenue_driver_context_from_model_input(model_input_json, finmo_json=finmo_json),
    "current_model_snapshot": {
      "finmo_revenue_and_payroll_first_4_quarters": [
        {
          "quarter_index": int(_safe_float(row.get("quarter_index")) or 0),
          "revenue": int(round(float(_safe_float(row.get("revenue")) or 0.0))),
          "payroll": int(round(float(_safe_float(row.get("payroll")) or 0.0))),
        }
        for row in finmo_rows[:4]
      ],
    },
  }
  # Context filtering + budget guard run once. Per-round context is
  # rebuilt from the filtered base + the round's previous_contract_
  # failure feedback.
  user_context = post_intake_gpt_context_filter_payload(
    contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    payload=user_context,
    include_phase="pre_convergence",
  )
  context_budget = post_intake_gpt_context_request_char_budget(
    contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    include_phase="pre_convergence",
    default=None,
  )
  if context_budget is not None:
    context_chars = len(json.dumps(user_context, ensure_ascii=False))
    if context_chars > int(context_budget):
      _payroll_fail_fast(
        "payroll_headcount_gpt_context_payload_budget_exceeded",
        f"chars={context_chars} budget={int(context_budget)}",
        stage="payroll_headcount_contract_request",
      )
  payload_base = {
    "model": _openai_model(),
    "temperature": 0,
    "text": {
      "format": {
        "type": "json_schema",
        "name": PAYROLL_HEADCOUNT_CONTRACT_NAME,
        "schema": post_intake_gpt_contract_openai_schema(
          contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
          business_naics=str((ops_json or {}).get("business_naics_6") or "").strip() or None,
        ),
        "strict": True,
      }
    },
  }
  sequence_settings = _payroll_process_sequence_settings(
    step_key="payroll_gpt_contract_request",
  )
  timeout_seconds = float(sequence_settings.get("timeout_seconds") or 180.0)
  post_intake_assert_process_object_control(
    step_key="payroll_headcount_schedule",
    object_name="payroll_headcount",
    action="build",
    owner="gpt",
    # Phase 9 P3.13 Sunny fix #1 — trigger must be from the SQL
    # post_intake_process_sequence_lookup allowed_triggers list. The
    # original P3.11 rewrite used "initial_payroll_authoring" which
    # is not a registered trigger; sequence-controller rejected it.
    trigger="initial_build",
  )

  # ---- Phase 9 P3.11 — iterative refinement loop ---------------------------
  #
  # Up to ``_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS`` (10) sequential GPT
  # calls in a feedback loop. On each round we run the same three
  # validators (A.1 contract → A.2 build/payload → A.3 economic
  # feasibility); on failure the feedback packet is built per
  # exception class and threaded into the next round.
  total_start = time.perf_counter()
  # Seed the loop's failure feedback from any externally-supplied
  # previous_contract_failure (convergence-time payroll-repair calls
  # pass a downstream-detected failure context that should seed
  # Round 1's prompt). When called fresh from initial_grid, this is
  # always None and Round 1 has no prior failure context.
  last_failure_packet: Optional[Dict[str, Any]] = None
  if isinstance(previous_contract_failure, dict) and previous_contract_failure:
    last_failure_packet = {
      "feedback_class": "external_caller_seed",
      "round_n": 0,
      "error": str(previous_contract_failure.get("error") or "")[:6000],
      "compacted_violations": _compact_payroll_failure_for_gpt(previous_contract_failure),
      "invalid_response_excerpt": "",
    }
  last_parsed: Dict[str, Any] = {}
  last_exc_code: str = ""
  last_exc_message: str = ""
  raw_openai_response: Dict[str, Any] = {}

  iter_token = _PAYROLL_ITER_GPT_CALL_COUNT.set(0)
  try:
    for round_n in range(1, _PAYROLL_ITERATIVE_HARD_CAP_ROUNDS + 1):
      # Invariant #3: state corruption between rounds.
      _assert_payroll_iterative_state_intact(
        round_n=round_n,
        user_context=user_context,
        payload_base=payload_base,
      )

      # Total-budget cycle guard preserved from the prior implementation.
      elapsed_before_attempt = time.perf_counter() - total_start
      remaining_seconds = max(0.0, timeout_seconds - elapsed_before_attempt)
      if remaining_seconds < 15.0:
        _payroll_fail_fast(
          "payroll_headcount_contract_timeout",
          f"GPT headcount schedule exceeded total {timeout_seconds:.0f}s payroll cycle budget before convergence.",
          stage="payroll_headcount_contract_request",
          details={
            "round_n": round_n,
            "hard_cap_rounds": _PAYROLL_ITERATIVE_HARD_CAP_ROUNDS,
            "elapsed_seconds": round(float(elapsed_before_attempt), 2),
            "timeout_seconds": timeout_seconds,
            "source_table": sequence_settings.get("source_table"),
            "step_key": sequence_settings.get("step_key"),
          },
        )

      # Build this round's request context. The base ``user_context``
      # is unchanged across rounds; only ``previous_contract_failure``
      # carries the feedback from the previous round.
      request_context = deepcopy(user_context)
      if last_failure_packet is not None:
        request_context["previous_contract_failure"] = {
          "source_of_truth": "post_intake_headcount_policy_lookup + payroll_headcount_schedule validators (A.1/A.2/A.3)",
          "required_action": (
            "Return a corrected full payroll_headcount_schedule. The "
            "structured failures below name the specific fields and "
            "constraints that tripped. Revise ONLY the fields named in "
            "the failures; keep all other fields unchanged unless a "
            "structural cascade is required. The iterative refinement "
            f"system gives you up to {_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS} "
            "total rounds; this is round "
            f"{int(last_failure_packet.get('round_n') or (round_n - 1))} of "
            f"{_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS}. Choose "
            "capacity_labor_model/labor_intensity_class from "
            "payroll_decision_options. For payroll/revenue feasibility "
            "failures, read payroll_feasibility_mapping.rows[]."
            "repair_direction_rules from sql.post_intak_mapping_lookup "
            "and apply those directions exactly. Select every "
            "oews_occ_title exactly from the full NAICS oews_title_"
            "catalog.title_candidates."
          ),
          **last_failure_packet,
        }

      system_prompt = post_intake_build_prompt_from_contract(
        PAYROLL_HEADCOUNT_CONTRACT_NAME,
        context_payload=request_context,
        include_phase="pre_convergence",
        static_instruction=(
          "Decide the payroll headcount schedule using business judgment inside the SQL-defined "
          "payroll_headcount_schedule contract. GPT only supplies selected OEWS titles and FTE rows. "
          "Python injects key people from intake, resolves wages from the selected OEWS catalog title, calculates payroll dollars, "
          "applies table-backed wage positioning and 3 percent annual wage inflation, "
          "and validates the final schedule against post_intake_headcount_policy_lookup."
        ),
        task_instruction=(
          "Return only JSON matching payroll_headcount_schedule. Use the stage_ramp_contract as context, "
          "but do not change ramp. First choose capacity_labor_model, labor_intensity_class, wage_positioning_tier, "
          "wage_positioning_multiplier, target_payroll_percent_of_revenue, and capacity_units_per_supporting_fte "
          "from payroll_decision_options where enumerated, with capacity_units_per_supporting_fte as GPT's positive business-specific productivity assumption. "
          "Do not infer hidden defaults: every root payroll assumption is GPT business judgment selected inside the SQL-rendered option rows. "
          "Then output supporting-staff oews_occ_title, starting_fte, hires, ending_fte, and benefits percent only. "
          "Each oews_occ_title must be an exact occ_title from the full NAICS oews_title_catalog.title_candidates. "
          "Do not invent abstract staffing families, staffing categories, aliases, or non-OEWS staffing buckets. "
          "Only include OEWS titles that carry FTE at some point in the 20-quarter schedule; once a title starts, it must continue through Q20. "
          "A payroll_headcount_grid row means the title is actually hired; do not include hypothetical, placeholder, unused, or zero-FTE roles. "
          "For every oews_occ_title you include, at least one quarter must have starting_fte or ending_fte greater than 0. "
          "If prior failure says a title had zero FTE in every quarter, fix it by assigning real FTE to that same selected business role or by choosing a different real hired title with positive FTE; never return another all-zero title. "
          "If prior failure involves payroll/revenue feasibility, use payroll_feasibility_mapping from sql.post_intak_mapping_lookup "
          "for the allowed direction of payroll, capacity, price, utilization, and productivity movements. "
          "When previous_contract_failure includes gpt_repair_constraints, treat its capacity_units_per_supporting_fte "
          "cap or floor as binding across all violating quarters and choose the recommended value or more conservative. "
          "Use the OEWS titles needed to operate the business; one catch-all staffing bucket is invalid. "
          "Do not provide wages and do not include key people; Python owns those. "
          "Use payroll_capacity_grid as operating context only. Do not force FTE to a hard capacity demand floor; "
          "Python will derive payroll-supported Capacity from average FTE and capacity_units_per_supporting_fte, "
          "then revenue will be constrained by that supported Capacity. "
          "For title continuity, Qn starting_fte must equal that same title's Q(n-1) ending_fte; increases belong in hires, not starting_fte jumps. "
          "Your business decision is the exact OEWS title set and each title's Q1-Q20 starting_fte, hires, and ending_fte schedule. "
          "target_payroll_percent_of_revenue is a decimal in [min_pct, max_pct] for the chosen labor_intensity_class (e.g., for medium intensity the band is 0.10..0.55). Example: 0.45 means 45 percent of revenue. Do NOT emit 45 (which would be 4500 percent) and do NOT emit 0.045 (which would be 4.5 percent). "
          "target_payroll_percent_of_revenue is context, but payroll_revenue_sanity_bounds from the headcount policy table are a real feasibility check; do not staff by clipping payroll to a percentage. "
          "Payroll FTE creates supported capacity, and supported capacity constrains revenue. "
          "ITERATIVE REFINEMENT: If your initial plan fails validation, you will receive structured failures naming the field, the actual value, the required range, and the failure category. Revise ONLY the fields named in the failures; keep all other fields unchanged unless a cascade is required. You have up to "
          f"{_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS} total rounds."
        ),
      )
      payload = deepcopy(payload_base)
      payload["input"] = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "input_text", "text": json.dumps(request_context, ensure_ascii=False)}]},
      ]

      # Invariant #6: budget decoupling guard. Fires if the contextvar
      # is None (loop bypassed) — defensive against future refactors
      # that bypass the iterative scope.
      _assert_payroll_iterative_budget_decoupled(round_n=round_n)
      # Invariant #2: round count drift. Increment counter, verify
      # invariant holds (one GPT call per round, counter monotonic).
      pre_call_count = _PAYROLL_ITER_GPT_CALL_COUNT.get()
      if pre_call_count != round_n - 1:
        _payroll_iterative_machinery_fail_fast(
          "payroll_iterative_refinement_round_count_drift",
          f"round_n={round_n} but gpt_call_count was {pre_call_count} pre-call",
          details={"round_n": round_n, "gpt_call_count": pre_call_count},
        )

      resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload=payload,
        timeout_seconds=remaining_seconds,
      )
      _PAYROLL_ITER_GPT_CALL_COUNT.set(pre_call_count + 1)

      total_elapsed = time.perf_counter() - total_start
      if total_elapsed > timeout_seconds:
        _payroll_fail_fast(
          "payroll_headcount_contract_timeout",
          f"GPT headcount schedule exceeded total {timeout_seconds:.0f}s payroll cycle budget; elapsed={total_elapsed:.2f}s.",
          stage="payroll_headcount_contract_request",
          details={
            "round_n": round_n,
            "elapsed_seconds": round(float(total_elapsed), 2),
            "timeout_seconds": timeout_seconds,
            "source_table": sequence_settings.get("source_table"),
            "step_key": sequence_settings.get("step_key"),
          },
        )
      if resp.status_code >= 400:
        _payroll_fail_fast(
          "payroll_headcount_contract_openai_status",
          resp.text[:1200],
          stage="payroll_headcount_contract_request",
        )
      raw_openai_response = resp.json() if isinstance(resp.json(), dict) else {"response": resp.text[:4000]}
      parsed = _parse_responses_json_dict(raw_openai_response)
      if not isinstance(parsed, dict):
        # Invariant #5: parse failure stays as the existing
        # _payroll_fail_fast (preserved per directive). Build a
        # parse-feedback packet so the next round sees the failure.
        last_exc_code = "payroll_headcount_contract_parse_failed"
        last_exc_message = "GPT did not return a JSON object."
        last_failure_packet = {
          "feedback_class": "parse_failure",
          "round_n": round_n,
          "error": last_exc_message,
          "invalid_response_excerpt": str(raw_openai_response)[:6000],
        }
        if round_n < _PAYROLL_ITERATIVE_HARD_CAP_ROUNDS:
          continue
        _payroll_fail_fast(
          "payroll_headcount_contract_parse_failed",
          "GPT did not return a JSON object across all iterative refinement rounds.",
          stage="payroll_headcount_contract_response",
          details={
            "rounds_used": round_n,
            "hard_cap_rounds": _PAYROLL_ITERATIVE_HARD_CAP_ROUNDS,
          },
        )

      last_parsed = deepcopy(parsed)
      try:
        contract = validate_payroll_headcount_contract_payload(parsed)
        contract["prompt_context"] = request_context
        contract["raw_openai_response"] = raw_openai_response
        schedule_payload = build_payroll_headcount_payload_from_contract(
          contract,
          draft_id=draft_id,
          client_id=client_id,
          model_input_json=model_input_json,
          business_facts=business_facts,
          ops_json=ops_json,
          people_json=resolved_people_json,
        )
        _assert_payroll_contract_economic_feasible_for_retry(
          payroll_headcount=deepcopy(schedule_payload),
          model_input_json=deepcopy(model_input_json),
          stage="payroll_headcount_contract_economic_feasibility",
        )
        return schedule_payload
      except PostIntakePreconditionFailed:
        # P3.21 Part 2 housekeeping -- machinery violations (e.g., the
        # validator-translator's `payroll_validator_translator_
        # unmatched_code` raised from validate_payroll_headcount_
        # contract_payload's translation layer) are NOT GPT-fixable
        # and must NOT be routed through GPT retry. Re-raise
        # immediately so the diagnostic propagates with its
        # PostIntakePreconditionFailed structure intact, instead of
        # being coalesced into the iteration's residual
        # last_exc_message text.
        raise
      except RuntimeError as exc:
        last_exc_code = str(getattr(exc, "code", "") or "")
        last_exc_message = str(exc) or ""
        last_failure_packet = _build_payroll_iterative_feedback_packet(
          exc=exc,
          parsed=parsed,
          round_n=round_n,
        )
        # Continue to next round.
  finally:
    _PAYROLL_ITER_GPT_CALL_COUNT.reset(iter_token)

  # Exhausted hard cap with residual failure. Hard-fail with the
  # specific residual diagnostic per the directive.
  _payroll_fail_fast(
    "payroll_iterative_refinement_exhausted",
    (
      f"Payroll iterative refinement did not produce a validator-accepted "
      f"schedule in {_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS} rounds. "
      f"Final round failure: {last_exc_code}: {last_exc_message[:1200]}"
    ),
    stage="payroll_headcount_iterative_refinement",
    details={
      "rounds_used": _PAYROLL_ITERATIVE_HARD_CAP_ROUNDS,
      "hard_cap_rounds": _PAYROLL_ITERATIVE_HARD_CAP_ROUNDS,
      "final_failure_code": last_exc_code,
      "final_failure_message": last_exc_message[:3000],
      "final_failure_packet": last_failure_packet,
      "raw_payroll_headcount_response": last_parsed,
    },
  )
  return {}


def _live_series(values: Any, *, horizon: int) -> List[float]:
  raw_values = list(values or []) if isinstance(values, list) else []
  if len(raw_values) >= horizon + 1:
    raw_values = raw_values[1:horizon + 1]
  else:
    raw_values = raw_values[:horizon]
  out = [round(float(_safe_float(item) or 0.0), 6) for item in raw_values]
  if len(out) < horizon:
    out.extend([0.0 for _ in range(horizon - len(out))])
  return out[:horizon]


def _revenue_driver_context_from_model_input(
  model_input_json: Optional[Dict[str, Any]],
  *,
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  horizon = _contract_horizon_quarters()
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  slot_rows: Dict[str, Dict[str, Any]] = {}
  for row in revenue_rows:
    slot_key = str(row.get("revenue_slot_key") or row.get("lever_id") or "").strip()
    driver = str(row.get("driver") or "").strip().lower()
    if not slot_key or driver not in {"capacity", "unit price", "utilization"}:
      continue
    slot = slot_rows.setdefault(
      slot_key,
      {
        "slot_key": slot_key,
        "lob": row.get("lob"),
        "product": row.get("product"),
        "unit_name": row.get("product") or row.get("unit_name"),
        "drivers": {},
      },
    )
    slot["drivers"][driver] = {
      "lever_id": row.get("lever_id"),
      "input_semantics": row.get("input_semantics"),
      "values": _live_series(row.get("values"), horizon=horizon),
    }
  finmo_revenue_by_q: Dict[int, int] = {}
  for row in ((finmo_json or {}).get("quarter_rows") or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(round(float(_safe_float(row.get("quarter_index")) or 0.0)))
    if 1 <= quarter_index <= horizon:
      finmo_revenue_by_q[quarter_index] = int(round(float(_safe_float(row.get("revenue")) or 0.0)))
  quarter_rows: List[Dict[str, Any]] = []
  for quarter_index in range(1, horizon + 1):
    product_rows: List[Dict[str, Any]] = []
    computed_revenue = 0
    for slot in slot_rows.values():
      drivers = slot.get("drivers") if isinstance(slot.get("drivers"), dict) else {}
      capacity = float(((drivers.get("capacity") or {}).get("values") or [0.0] * horizon)[quarter_index - 1] or 0.0)
      unit_price = float(((drivers.get("unit price") or {}).get("values") or [0.0] * horizon)[quarter_index - 1] or 0.0)
      utilization = float(((drivers.get("utilization") or {}).get("values") or [0.0] * horizon)[quarter_index - 1] or 0.0)
      revenue = int(round(capacity * unit_price * utilization))
      computed_revenue += revenue
      product_rows.append(
        {
          "slot_key": slot.get("slot_key"),
          "lob": slot.get("lob"),
          "product": slot.get("product"),
          "capacity_units": int(round(capacity)),
          "unit_price": round(unit_price, 2),
          "utilization": round(utilization, 2),
          "revenue": revenue,
        }
      )
    quarter_rows.append(
      {
        "quarter_index": quarter_index,
        "computed_revenue_from_model_input": computed_revenue,
        "finmo_revenue": finmo_revenue_by_q.get(quarter_index),
        "product_rows": product_rows,
      }
    )
  return {
    "horizon_quarters": horizon,
    "formula": "sum(Capacity * Unit Price * Utilization)",
    "source": "model_input.sections.revenue table-backed drivers",
    "quarter_rows": quarter_rows,
  }


def _payroll_totals_by_quarter_from_rows(rows: Sequence[Dict[str, Any]]) -> Dict[int, int]:
  totals: Dict[int, int] = {}
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    annual_wage = _round_currency(row.get("annual_wage"))
    benefits_pct = round(float(_safe_ratio(row.get("payroll_taxes_benefits_percent")) or 0.0), 2)
    average_fte = round((starting_fte + ending_fte) / 2.0, 2)
    quarterly_wage_cost = _round_currency((average_fte * annual_wage) / 4.0)
    quarterly_taxes_benefits = _round_currency(quarterly_wage_cost * benefits_pct)
    totals[quarter_index] = int(totals.get(quarter_index) or 0) + int(quarterly_wage_cost + quarterly_taxes_benefits)
  return totals


def _enforce_forward_fte_continuity(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  normalized: List[Dict[str, Any]] = []
  prior_ending_by_title: Dict[str, float] = {}
  for source_row in sorted(
    [deepcopy(row) for row in rows if isinstance(row, dict)],
    key=lambda row: (
      int(row.get("quarter_index") or 0),
      str(row.get("staffing_class") or "supporting_staff").lower(),
      _title_key(row.get("oews_occ_title") or row.get("position_title") or row.get("person_name")),
    ),
  ):
    row = deepcopy(source_row)
    quarter_index = int(row.get("quarter_index") or 0)
    staffing_class = str(row.get("staffing_class") or "supporting_staff").strip().lower() or "supporting_staff"
    title_identity = (
      _title_key(row.get("person_name") or row.get("position_title"))
      if staffing_class == "key_person"
      else _title_key(row.get("oews_occ_title") or row.get("position_title"))
    )
    continuity_key = f"{staffing_class}::{title_identity}"
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    if quarter_index == 1 and starting_fte <= 0.0 and ending_fte > 0.0:
      starting_fte = ending_fte
    if quarter_index > 1 and continuity_key in prior_ending_by_title:
      starting_fte = round(float(prior_ending_by_title.get(continuity_key) or 0.0), 2)
      ending_fte = round(max(ending_fte, starting_fte), 2)
    row["starting_fte"] = starting_fte
    row["ending_fte"] = ending_fte
    row["hires"] = round(max(0.0, ending_fte - starting_fte), 2)
    prior_ending_by_title[continuity_key] = ending_fte
    normalized.append(row)
  return normalized


def _validate_quarter_totals_match_title_rows(
  schedule: Dict[str, Any],
  *,
  rows: Sequence[Dict[str, Any]],
) -> None:
  horizon = _contract_horizon_quarters()
  calculated = _payroll_totals_by_quarter_from_rows(rows)
  totals_by_quarter = {
    int(item.get("quarter_index") or 0): int(round(float(_safe_float(item.get("payroll")) or 0.0)))
    for item in (schedule.get("quarter_totals") or [])
    if isinstance(item, dict)
  }
  for quarter_index in range(1, horizon + 1):
    expected = int(calculated.get(quarter_index) or 0)
    provided = int(totals_by_quarter.get(quarter_index) or 0)
    if expected != provided:
      _payroll_fail_fast(
        "payroll_headcount_quarter_total_mismatch",
        f"Q{quarter_index} quarter_totals.payroll={provided} calculated_from_title_rows={expected}. "
        "Payroll schedule quarter_totals must be a deterministic rollup of rows.",
        stage="payroll_headcount_quarter_total_rollup",
        details={"quarter_index": quarter_index, "provided": provided, "expected": expected},
      )


def apply_payroll_headcount_payload_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  live_count: int,
  process_step_key: str = "payroll_headcount_schedule",
  control_action: str = "derive",
  control_trigger: str = "payroll_headcount_changed",
) -> Dict[str, Any]:
  _assert_payroll_sequence_step(
    allowed_step_keys=[],
    allowed_executor_functions=[],
  )
  post_intake_assert_process_object_control(
    step_key=process_step_key,
    object_name="model_input.expenses.Payroll",
    action=control_action,
    owner="python",
    trigger=control_trigger,
  )
  next_payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule:
    # iter 19 Stage 3 correction — when no payroll schedule was
    # authored upstream (truly no-payroll business), the writeback is
    # a no-op. The Payroll expense lever in model_input is already
    # zero by default; writing zeros to a zero lever produces no
    # change. The pre-cash gate's
    # _assert_pre_cash_gate_contract_levers_written (added in Stage 3)
    # catches the bug case where a schedule WAS authored upstream but
    # the writeback was skipped; the diagnostic surfaces there, not
    # here. Logged at INFO for orchestration traceability.
    import logging as _logging
    _logging.getLogger(__name__).info(
      "apply_payroll_headcount_payload_to_model_input no-op: empty "
      "payload (no payroll contract authored upstream)."
    )
    return next_payload
  validation_errors = validate_payroll_headcount_payload(schedule)
  if validation_errors:
    _payroll_fail_fast(
      "payroll_headcount_schedule_validation_failed",
      "; ".join(validation_errors[:20]),
      stage="payroll_headcount_model_input_application",
      details={"errors": validation_errors[:20]},
    )
  schedule_rows = _payroll_headcount_grid_rows(schedule)
  _validate_quarter_totals_match_title_rows(schedule, rows=schedule_rows)
  if isinstance(next_payload.get("controller_write_levers"), list):
    next_payload["controller_write_levers"] = [
      deepcopy(item)
      for item in (next_payload.get("controller_write_levers") or [])
      if isinstance(item, dict) and str(item.get("lever_id") or "").strip() != PAYROLL_HEADCOUNT_LEVER_ID
    ]
  if isinstance(next_payload.get("lever_catalog"), dict):
    lever_catalog = deepcopy(next_payload.get("lever_catalog") or {})
    lever_catalog.pop(PAYROLL_HEADCOUNT_LEVER_ID, None)
    next_payload["lever_catalog"] = lever_catalog
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  expense_rows = [row for row in (sections.get("expenses") or []) if isinstance(row, dict)]
  payroll_row = next((row for row in expense_rows if str(row.get("label") or "").strip() == "Payroll"), None)
  if not isinstance(payroll_row, dict):
    _payroll_fail_fast(
      "payroll_row_missing",
      "model_input.sections.expenses must include Payroll for headcount schedule application.",
      stage="payroll_headcount_model_input_application",
    )
    return next_payload
  values = list(payroll_row.get("values") or [])
  stub_value, _existing_live_values = _row_stub_and_live_values(values, live_count=live_count)
  totals_by_quarter = {
    int(item.get("quarter_index") or 0): int(round(float(_safe_float(item.get("payroll")) or 0.0)))
    for item in (schedule.get("quarter_totals") or [])
    if isinstance(item, dict)
  }
  expected_quarters = set(range(1, live_count + 1))
  if set(totals_by_quarter.keys()) & expected_quarters != expected_quarters:
    _payroll_fail_fast(
      "payroll_headcount_schedule_missing_live_quarters",
      "payroll_headcount quarter_totals must cover every live forecast quarter.",
      stage="payroll_headcount_model_input_application",
      details={
        "missing": sorted(expected_quarters - set(totals_by_quarter.keys())),
        "live_count": live_count,
      },
    )
  derived_live_values = [float(totals_by_quarter[quarter]) for quarter in range(1, live_count + 1)]
  payroll_row["controller_write"] = False
  payroll_row["derived_driver"] = PAYROLL_HEADCOUNT_SOURCE
  payroll_row["payroll_headcount_schedule"] = {
    "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
    "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
    "driver_basis": "headcount_schedule",
    "headcount_economic_basis": str(schedule.get("headcount_economic_basis") or "capacity_units_per_supporting_fte"),
    "capacity_labor_model": schedule.get("capacity_labor_model"),
    "labor_intensity_class": schedule.get("labor_intensity_class"),
    "wage_positioning_tier": schedule.get("wage_positioning_tier"),
    "capacity_units_per_supporting_fte": schedule.get("capacity_units_per_supporting_fte"),
    "schedule_storage_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    "schedule_contract_version": schedule.get("contract_version"),
    "schedule_horizon_quarters": schedule.get("schedule_horizon_quarters"),
    "quarter_totals": deepcopy(schedule.get("quarter_totals") or []),
  }
  payroll_row["values"] = _compose_period_values(stub_value=stub_value, live_values=derived_live_values)
  next_payload.setdefault("derived_driver_policies", {})
  next_payload.setdefault("derived_driver_runtime", {})
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"][PAYROLL_HEADCOUNT_LEVER_ID] = {
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "driver_basis": "headcount_schedule",
      "headcount_economic_basis": str(schedule.get("headcount_economic_basis") or "capacity_units_per_supporting_fte"),
      "capacity_labor_model": schedule.get("capacity_labor_model"),
      "labor_intensity_class": schedule.get("labor_intensity_class"),
      "wage_positioning_tier": schedule.get("wage_positioning_tier"),
      "capacity_units_per_supporting_fte": schedule.get("capacity_units_per_supporting_fte"),
      "schedule_storage_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
      "schedule_contract_version": schedule.get("contract_version"),
      "schedule_horizon_quarters": schedule.get("schedule_horizon_quarters"),
    }
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"][PAYROLL_HEADCOUNT_LEVER_ID] = {
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "driver_basis": "headcount_schedule",
      "payroll_headcount": deepcopy(schedule),
      "quarter_totals": deepcopy(schedule.get("quarter_totals") or []),
    }
  return next_payload


def apply_payroll_supported_capacity_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  live_count: int,
  process_step_key: str = "payroll_headcount_schedule",
  control_action: str = "derive",
  control_trigger: str = "payroll_headcount_changed",
) -> Dict[str, Any]:
  """Use payroll FTE as the causal capacity envelope for revenue drivers."""
  _assert_payroll_sequence_step(
    allowed_step_keys=[],
    allowed_executor_functions=[],
  )
  post_intake_assert_process_object_control(
    step_key=process_step_key,
    object_name="model_input.revenue.Capacity",
    action=control_action,
    owner="python",
    trigger=control_trigger,
  )
  next_payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule:
    # iter 19 Stage 3 correction — no payroll schedule authored = no
    # payroll-supported capacity envelope to derive. Revenue capacity
    # rows remain at their existing values. See sibling no-op in
    # apply_payroll_headcount_payload_to_model_input above.
    import logging as _logging
    _logging.getLogger(__name__).info(
      "apply_payroll_supported_capacity_to_model_input no-op: empty "
      "payload (no payroll contract authored upstream)."
    )
    return next_payload
  productivity = round(float(_safe_float(schedule.get("capacity_units_per_supporting_fte")) or 0.0), 6)
  if productivity <= 0.0:
    _payroll_fail_fast(
      "payroll_supported_capacity_productivity_missing",
      "Payroll-supported capacity requires positive capacity_units_per_supporting_fte selected in payroll_headcount.",
      stage="payroll_supported_capacity_application",
    )
  rows = _payroll_headcount_grid_rows(schedule)
  average_fte_by_quarter = _average_fte_by_quarter_from_rows(rows)
  supported_capacity = {
    quarter: round(float(average_fte_by_quarter.get(quarter) or 0.0) * productivity, 6)
    for quarter in range(1, live_count + 1)
  }
  sections = next_payload.get("sections") if isinstance(next_payload.get("sections"), dict) else {}
  revenue_rows = sections.get("revenue") if isinstance(sections.get("revenue"), list) else []
  capacity_rows = [
    row for row in revenue_rows
    if isinstance(row, dict) and str(row.get("driver") or row.get("driver_name") or "").strip().lower() == "capacity"
  ]
  if not capacity_rows:
    _payroll_fail_fast(
      "payroll_supported_capacity_rows_missing",
      "Revenue Capacity rows are required so payroll FTE can define the supported capacity envelope.",
      stage="payroll_supported_capacity_application",
    )
  current_totals = {quarter: 0.0 for quarter in range(1, live_count + 1)}
  row_live_values: List[Tuple[Dict[str, Any], float, List[float]]] = []
  for row in capacity_rows:
    values = list(row.get("values") or [])
    _stub, live_values = _row_stub_and_live_values(values, live_count=live_count)
    padded = list(live_values[:live_count])
    if len(padded) < live_count:
      padded.extend([0.0 for _ in range(live_count - len(padded))])
    row_total = round(sum(max(0.0, float(value or 0.0)) for value in padded), 6)
    row_live_values.append((row, row_total, padded))
    for idx, value in enumerate(padded, start=1):
      current_totals[idx] = round(current_totals.get(idx, 0.0) + max(0.0, float(value or 0.0)), 6)
  equal_weight = round(1.0 / max(1, len(capacity_rows)), 6)
  for row, row_total, live_values in row_live_values:
    values = list(row.get("values") or [])
    stub_value, _existing_live = _row_stub_and_live_values(values, live_count=live_count)
    next_live_values: List[float] = []
    for quarter_index, current_value in enumerate(live_values, start=1):
      total_capacity = round(float(current_totals.get(quarter_index) or 0.0), 6)
      if total_capacity > 0.0:
        weight = max(0.0, float(current_value or 0.0)) / total_capacity
      elif row_total > 0.0:
        weight = max(0.0, float(current_value or 0.0)) / row_total
      else:
        weight = equal_weight
      next_live_values.append(round(float(supported_capacity[quarter_index]) * float(weight), 6))
    row["values"] = _compose_period_values(stub_value=stub_value, live_values=next_live_values)
    row["controller_write"] = False
    row["derived_driver"] = "payroll_supported_capacity"
    row["payroll_supported_capacity"] = {
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "capacity_source": "payroll_fte_times_capacity_units_per_supporting_fte",
      "capacity_units_per_supporting_fte": productivity,
      "schedule_storage_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    }
  next_payload.setdefault("derived_driver_policies", {})
  next_payload.setdefault("derived_driver_runtime", {})
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"]["revenue::Capacity"] = {
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "capacity_source": "payroll_supported_capacity",
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "capacity_units_per_supporting_fte": productivity,
    }
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"]["payroll_supported_capacity"] = {
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "formula": "total_average_fte * capacity_units_per_supporting_fte",
      "capacity_units_per_supporting_fte": productivity,
      "total_average_fte_by_quarter": {
        str(quarter): round(float(average_fte_by_quarter.get(quarter) or 0.0), 6)
        for quarter in range(1, live_count + 1)
      },
      "supported_capacity_by_quarter": {
        str(quarter): round(float(supported_capacity.get(quarter) or 0.0), 6)
        for quarter in range(1, live_count + 1)
      },
    }
  return next_payload


def _payroll_supported_capacity_model_input_violations(
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> List[Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  productivity = round(float(_safe_float(schedule.get("capacity_units_per_supporting_fte")) or 0.0), 6)
  if productivity <= 0.0:
    return [{
      "error": "payroll_supported_capacity_productivity_missing",
      "reason": "capacity_units_per_supporting_fte must be positive before payroll can support revenue capacity.",
    }]
  rows = _payroll_headcount_grid_rows(schedule)
  average_fte_by_quarter = _average_fte_by_quarter_from_rows(rows)
  expected_by_quarter = {
    quarter: round(float(average_fte_by_quarter.get(quarter) or 0.0) * productivity, 6)
    for quarter in range(1, live_count + 1)
  }
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = sections.get("revenue") if isinstance(sections.get("revenue"), list) else []
  capacity_rows = [
    row for row in revenue_rows
    if isinstance(row, dict) and str(row.get("driver") or row.get("driver_name") or "").strip().lower() == "capacity"
  ]
  if not capacity_rows:
    return [{
      "error": "payroll_supported_capacity_rows_missing",
      "reason": "Revenue Capacity rows are required so payroll FTE can define the supported capacity envelope.",
    }]
  actual_by_quarter = {quarter: 0.0 for quarter in range(1, live_count + 1)}
  unmarked_rows: List[str] = []
  for row in capacity_rows:
    if str(row.get("derived_driver") or "").strip() != "payroll_supported_capacity":
      unmarked_rows.append(str(row.get("label") or row.get("revenue_slot_key") or "Capacity").strip())
    _stub, live_values = _row_stub_and_live_values(row.get("values") or [], live_count=live_count)
    for quarter_index, value in enumerate(live_values[:live_count], start=1):
      actual_by_quarter[quarter_index] = round(
        float(actual_by_quarter.get(quarter_index) or 0.0) + max(0.0, float(_safe_float(value) or 0.0)),
        6,
      )
  violations: List[Dict[str, Any]] = []
  if unmarked_rows:
    violations.append({
      "error": "payroll_supported_capacity_marker_missing",
      "reason": "Capacity rows must be marked derived_driver='payroll_supported_capacity'.",
      "rows": unmarked_rows[:20],
    })
  for quarter_index in range(1, live_count + 1):
    expected = round(float(expected_by_quarter.get(quarter_index) or 0.0), 6)
    actual = round(float(actual_by_quarter.get(quarter_index) or 0.0), 6)
    tolerance = max(0.01, abs(expected) * 0.0001)
    if abs(actual - expected) > tolerance:
      violations.append({
        "error": "payroll_supported_capacity_mismatch",
        "quarter_index": quarter_index,
        "expected_capacity": expected,
        "actual_capacity": actual,
        "delta": round(actual - expected, 6),
        "formula": "sum(payroll_average_fte) * capacity_units_per_supporting_fte",
      })
  return violations


def assert_payroll_headcount_payload_ready(
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  model_input_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule:
    _payroll_fail_fast(
      "payroll_headcount_payload_missing",
      "post-intake payroll must originate from payroll_headcount_schedule.payroll_headcount_grid.",
      stage=stage,
    )
    return
  validation_errors = validate_payroll_headcount_payload(schedule)
  if validation_errors:
    _payroll_fail_fast(
      "payroll_headcount_payload_invalid",
      "; ".join(validation_errors[:20]),
      stage=stage,
      details={"errors": validation_errors[:20]},
    )
  rows = _payroll_headcount_grid_rows(schedule)
  policy = post_intake_headcount_policy_for("default")
  _validate_payroll_title_rows(rows, policy=policy)
  _validate_quarter_totals_match_title_rows(schedule, rows=rows)


def assert_payroll_headcount_model_input_applied(
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  stage: str,
) -> None:
  validation = validate_payroll_headcount_model_input_contract(
    model_input_json=deepcopy(model_input_json if isinstance(model_input_json, dict) else {}),
    payroll_headcount=deepcopy(payroll_headcount if isinstance(payroll_headcount, dict) else None),
  )
  details = [item for item in (validation.get("details") or []) if isinstance(item, dict)]
  if details:
    _payroll_fail_fast(
      "payroll_headcount_model_input_not_applied",
      "; ".join(str(item.get("reason") or item.get("error") or item) for item in details[:10]),
      stage=stage,
      details={"validation_details": details[:10]},
    )
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  current_row = payroll_row_from_model_input(payload)
  live_count = max(
    0,
    len([item for item in (payload.get("periods") or []) if isinstance(item, dict) and not bool(item.get("is_stub"))])
    or (len(list((current_row or {}).get("values") or [])) - 1 if isinstance(current_row, dict) else 0),
  )
  capacity_violations = _payroll_supported_capacity_model_input_violations(
    payload,
    payroll_headcount,
    live_count=live_count,
  )
  if capacity_violations:
    _payroll_fail_fast(
      "payroll_supported_capacity_model_input_not_applied",
      "Revenue Capacity must equal payroll-supported capacity before FINMO can be accepted.",
      stage=stage,
      details={"validation_details": capacity_violations[:20]},
    )


def assert_finmo_payroll_matches_headcount_schedule(
  finmo_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  stage: str,
) -> None:
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  assert_payroll_headcount_payload_ready(
    schedule,
    model_input_json=None,
    stage=f"{stage}_finmo_schedule",
  )
  totals_by_quarter = {
    int(item.get("quarter_index") or 0): int(round(float(_safe_float(item.get("payroll")) or 0.0)))
    for item in (schedule.get("quarter_totals") or [])
    if isinstance(item, dict)
  }
  finmo_rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or [])
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  ]
  if not finmo_rows:
    _payroll_fail_fast(
      "payroll_headcount_finmo_rows_missing",
      "FINMO quarter_rows are missing; payroll cannot be reconciled to the headcount schedule.",
      stage=stage,
    )
    return
  for row in finmo_rows:
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    expected = int(totals_by_quarter.get(quarter_index) or 0)
    actual = int(round(float(_safe_float(row.get("payroll")) or 0.0)))
    if expected != actual:
      _payroll_fail_fast(
        "payroll_headcount_finmo_mismatch",
        f"Q{quarter_index} finmo_payroll={actual} schedule_payroll={expected}.",
        stage=stage,
        details={"quarter_index": quarter_index, "finmo_payroll": actual, "schedule_payroll": expected},
      )


def payroll_revenue_feasibility_violations(
  *,
  payroll_headcount: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  policy_code: Any = "default",
) -> List[Dict[str, Any]]:
  """Return table-backed payroll/revenue feasibility violations.

  This is not a cap on payroll or revenue. It is a coherence test: if the
  relationship is outside the headcount policy range, upstream drivers must be
  recomputed instead of clipping either output.
  """
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  rows = finmo_json.get("quarter_rows") if isinstance(finmo_json, dict) and isinstance(finmo_json.get("quarter_rows"), list) else []
  if not schedule or not rows:
    return []
  try:
    feasibility_mapping = post_intake_payroll_feasibility_mapping()
  except Exception as exc:
    return [{
      "error": "payroll_feasibility_mapping_missing",
      "reason": str(exc),
      "policy_source": "post_intak_mapping_lookup.repair_direction_rules_json",
      "required_action": "Initialize/repair the SQL mapping table before payroll can choose directional movements.",
    }]
  mapping_rows = feasibility_mapping.get("rows") if isinstance(feasibility_mapping, dict) else []
  mapping_direction_rules = [
    {
      "lever_id": str(item.get("lever_id") or ""),
      "repair_direction_rules": deepcopy(item.get("repair_direction_rules") or {}),
    }
    for item in (mapping_rows if isinstance(mapping_rows, list) else [])
    if isinstance(item, dict)
  ]
  policy = post_intake_headcount_policy_for(policy_code=policy_code)
  intensity = _clean_key(schedule.get("labor_intensity_class"))
  try:
    bounds = headcount_payroll_revenue_sanity_bounds(policy or {}, labor_intensity_class=intensity)
  except Exception as exc:
    return [{
      "error": "payroll_revenue_sanity_lookup_failed",
      "reason": str(exc),
      "policy_source": "post_intake_headcount_policy_lookup.payroll_revenue_sanity_bounds_json",
      "labor_intensity_class": intensity or "missing",
    }]
  min_pct = round(float(bounds.get("min_pct") or 0.0), 6)
  max_pct = round(float(bounds.get("max_pct") or 0.0), 6)
  tolerance_pct = max(0.0, float(policy.get("payroll_revenue_sanity_tolerance_pct") or 0.03))
  relative_tolerance = max(0.0, float(policy.get("payroll_revenue_sanity_relative_tolerance") or 0.20))
  min_allowed = max(0.0, min_pct - max(tolerance_pct, min_pct * relative_tolerance))
  max_allowed = max_pct + max(tolerance_pct, max_pct * relative_tolerance)
  trend_rules = policy.get("payroll_trend_rules") if isinstance(policy.get("payroll_trend_rules"), dict) else {}
  ordered_rows = sorted(
    [row for row in rows if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1],
    key=lambda row: int(_safe_float(row.get("quarter_index")) or 0),
  )
  productivity = round(float(_safe_float(schedule.get("capacity_units_per_supporting_fte")) or 0.0), 6)
  average_fte_by_quarter = _average_fte_by_quarter_from_rows(_payroll_headcount_grid_rows(schedule))
  violations: List[Dict[str, Any]] = []
  previous_revenue: Optional[float] = None
  previous_payroll: Optional[float] = None
  for row in ordered_rows:
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    revenue = float(_safe_float(row.get("revenue")) or 0.0)
    payroll = float(_safe_float(row.get("payroll")) or 0.0)
    if revenue <= 0.0:
      previous_revenue = revenue
      previous_payroll = payroll
      continue
    ratio = payroll / revenue
    if ratio < min_allowed or ratio > max_allowed:
      too_low = ratio < min_allowed
      required_revenue_at_bound = (
        round(float(payroll) / float(min_allowed), 2)
        if too_low and min_allowed > 0.0
        else round(float(payroll) / float(max_allowed), 2)
        if max_allowed > 0.0
        else None
      )
      revenue_multiplier_to_bound = (
        round(float(required_revenue_at_bound) / float(revenue), 6)
        if required_revenue_at_bound is not None and revenue > 0.0
        else None
      )
      implied_productivity_at_bound = (
        round(float(productivity) * float(revenue_multiplier_to_bound), 6)
        if revenue_multiplier_to_bound is not None and productivity > 0.0
        else None
      )
      if too_low:
        revenue_bound_direction = "at_or_below"
        productivity_bound_direction = "at_or_below"
        safe_productivity_target = (
          round(float(implied_productivity_at_bound) * 0.98, 6)
          if implied_productivity_at_bound is not None
          else None
        )
        productivity_target_instruction = (
          "Payroll/revenue is too low. If FTE, price, and utilization are unchanged, "
          "capacity_units_per_supporting_fte must be less than or equal to the implied bound; "
          "choosing slightly above the bound remains infeasible."
        )
      else:
        revenue_bound_direction = "at_or_above"
        productivity_bound_direction = "at_or_above"
        safe_productivity_target = (
          round(float(implied_productivity_at_bound) * 1.02, 6)
          if implied_productivity_at_bound is not None
          else None
        )
        productivity_target_instruction = (
          "Payroll/revenue is too high. If FTE, price, and utilization are unchanged, "
          "capacity_units_per_supporting_fte must be greater than or equal to the implied bound; "
          "choosing slightly below the bound remains infeasible."
        )
      violations.append({
        "error": "payroll_revenue_economic_feasibility_failed",
        "quarter_index": quarter_index,
        "revenue": int(round(revenue)),
        "payroll": int(round(payroll)),
        "payroll_percent_of_revenue": round(float(ratio), 6),
        "labor_intensity_class": intensity,
        "policy_min_pct": min_pct,
        "policy_max_pct": max_pct,
        "effective_min_pct_with_tolerance": round(float(min_allowed), 6),
        "effective_max_pct_with_tolerance": round(float(max_allowed), 6),
        "policy_source": "post_intake_headcount_policy_lookup.payroll_revenue_sanity_bounds_json",
        "repair_rule_key": "payroll_revenue_ratio_low" if too_low else "payroll_revenue_ratio_high",
        "mapping_direction_rules": deepcopy(mapping_direction_rules),
        "deterministic_driver_math": {
          "current_capacity_units_per_supporting_fte": productivity,
          "total_average_fte": round(float(average_fte_by_quarter.get(quarter_index) or 0.0), 6),
          "required_revenue_at_policy_bound": required_revenue_at_bound,
          "required_revenue_direction": revenue_bound_direction,
          "revenue_multiplier_to_policy_bound": revenue_multiplier_to_bound,
          "implied_capacity_units_per_supporting_fte_if_price_utilization_and_fte_unchanged": implied_productivity_at_bound,
          "required_capacity_units_per_supporting_fte_direction": productivity_bound_direction,
          "safe_capacity_units_per_supporting_fte_target_with_buffer": safe_productivity_target,
          "target_instruction": productivity_target_instruction,
          "math_source": "payroll / policy_bound; payroll_supported_revenue scales linearly with capacity_units_per_supporting_fte when FTE, unit price, and utilization are unchanged",
        },
        "required_action": (
          "Read mapping_direction_rules from sql.post_intak_mapping_lookup, recompute allowed upstream drivers, "
          "use deterministic_driver_math.required_capacity_units_per_supporting_fte_direction as the binding quantitative target when price/utilization/FTE are unchanged, "
          "then rebuild payroll-supported capacity, revenue, payroll, and FINMO. "
          "Do not clip payroll or revenue."
        ),
      })
    if (
      bool(trend_rules.get("payroll_dollars_cannot_decline_when_revenue_increases"))
      and previous_revenue is not None
      and previous_payroll is not None
      and revenue > previous_revenue * 1.01
      and payroll < previous_payroll * 0.99
    ):
      violations.append({
        "error": "payroll_revenue_trend_rule_failed",
        "quarter_index": quarter_index,
        "previous_revenue": int(round(previous_revenue)),
        "current_revenue": int(round(revenue)),
        "previous_payroll": int(round(previous_payroll)),
        "current_payroll": int(round(payroll)),
        "rule": "payroll_dollars_cannot_decline_when_revenue_increases",
        "policy_source": "post_intake_headcount_policy_lookup.payroll_trend_rules_json",
        "required_action": (
          "Recompute staffing/productivity/ramp drivers so payroll and revenue move coherently. "
          "Do not patch the output row."
        ),
      })
    previous_revenue = revenue
    previous_payroll = payroll
  return violations


def assert_payroll_revenue_feasibility(
  *,
  payroll_headcount: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  stage_key = str(stage or "").strip().lower()
  if "pre_quarter_grid" in stage_key:
    return
  violations = payroll_revenue_feasibility_violations(
    payroll_headcount=payroll_headcount,
    finmo_json=finmo_json,
  )
  if violations:
    _payroll_fail_fast(
      "payroll_revenue_economic_feasibility_failed",
      "Payroll/revenue economics are outside the table-backed headcount policy range; recompute drivers instead of clipping outputs.",
      stage=stage,
      details={
        "violation_count": len(violations),
        "violations": violations[:20],
        "golden_rule": (
          "Payroll must be enforced through driver recomputation under the operational headcount policy lookup, "
          "not by hard caps or post-hoc output patching."
        ),
      },
    )


def validate_payroll_headcount_model_input_contract(
  *,
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  current_row = payroll_row_from_model_input(payload)
  details: List[Dict[str, Any]] = []
  if not isinstance(current_row, dict):
    return {
      "status": "failed",
      "details": [{
        "error": "payroll_row_missing",
        "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
        "quarter": 0,
        "reason": "Model input is missing the Payroll row in sections.expenses.",
        "validation_category": "payroll_headcount_schedule",
      }],
      "current_runtime": {},
      "expected_runtime": {},
    }
  live_count = max(
    0,
    len([item for item in (payload.get("periods") or []) if isinstance(item, dict) and not bool(item.get("is_stub"))])
    or (len(list(current_row.get("values") or [])) - 1 if len(list(current_row.get("values") or [])) >= 1 else 0),
  )
  current_runtime = ((payload.get("derived_driver_runtime") or {}).get(PAYROLL_HEADCOUNT_LEVER_ID)) if isinstance(payload.get("derived_driver_runtime"), dict) else {}
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule and isinstance(current_runtime, dict):
    schedule = current_runtime.get("payroll_headcount") if isinstance(current_runtime.get("payroll_headcount"), dict) else {}
  schedule_payload_errors: List[str] = []
  if not schedule:
    details.append({
      "error": "payroll_headcount_schedule_missing",
      "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
      "quarter": 0,
      "reason": "Payroll must be backed by intake_consult_drafts.payroll_headcount / derived_driver_runtime payroll_headcount.",
      "validation_category": "payroll_headcount_schedule",
    })
  else:
    schedule_payload_errors = validate_payroll_headcount_payload(schedule)
    for error in schedule_payload_errors:
      details.append({
        "error": error,
        "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
        "quarter": 0,
        "reason": "Payroll headcount schedule failed schedule validation.",
        "validation_category": "payroll_headcount_schedule",
      })
    if not schedule_payload_errors:
      _payroll_headcount_grid_rows(schedule)
  if bool(current_row.get("controller_write", True)):
    details.append({
      "error": "payroll_row_should_not_be_writable",
      "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
      "quarter": 0,
      "reason": "Payroll must not be controller-writable once payroll is headcount-schedule-derived.",
      "validation_category": "payroll_headcount_schedule",
    })
  if str(current_row.get("derived_driver") or "").strip() != PAYROLL_HEADCOUNT_SOURCE:
    details.append({
      "error": "payroll_row_missing_headcount_derived_driver_marker",
      "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
      "quarter": 0,
      "reason": f"Payroll row must be marked with derived_driver='{PAYROLL_HEADCOUNT_SOURCE}'.",
      "validation_category": "payroll_headcount_schedule",
    })
  if schedule and not schedule_payload_errors:
    capacity_violations = _payroll_supported_capacity_model_input_violations(
      payload,
      schedule,
      live_count=live_count,
    )
    for violation in capacity_violations:
      details.append({
        "error": str(violation.get("error") or "payroll_supported_capacity_mismatch"),
        "lever_id": "revenue::Capacity",
        "quarter": int(violation.get("quarter_index") or 0),
        "reason": json.dumps(violation, ensure_ascii=False, default=str),
        "validation_category": "payroll_supported_capacity",
      })
    current_values = list(current_row.get("values") or [])
    totals_by_quarter = {
      int(item.get("quarter_index") or 0): int(round(float(_safe_float(item.get("payroll")) or 0.0)))
      for item in (schedule.get("quarter_totals") or [])
      if isinstance(item, dict)
    }
    missing_quarters = [
      quarter_index
      for quarter_index in range(1, live_count + 1)
      if quarter_index not in totals_by_quarter
    ]
    if missing_quarters:
      details.append({
        "error": "payroll_headcount_schedule_missing_live_quarters",
        "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
        "quarter": int(missing_quarters[0] or 0),
        "reason": "Payroll headcount schedule quarter_totals must cover every live forecast quarter.",
        "validation_category": "payroll_headcount_schedule",
        "missing_quarters": missing_quarters[:20],
      })
    elif len(current_values) < live_count + 1:
      details.append({
        "error": "payroll_headcount_schedule_missing_full_horizon",
        "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
        "quarter": live_count,
        "reason": "Payroll model-input row must include stub plus every live forecast quarter.",
        "validation_category": "payroll_headcount_schedule",
        "expected_value_count": live_count + 1,
        "actual_value_count": len(current_values),
      })
    else:
      _stub_value, current_live_values = _row_stub_and_live_values(current_values, live_count=live_count)
      for quarter_index in range(1, live_count + 1):
        current_value = _safe_float(current_live_values[quarter_index - 1])
        expected_value = _safe_float(totals_by_quarter.get(quarter_index))
        if current_value is None or expected_value is None or int(round(float(current_value))) != int(round(float(expected_value))):
          details.append({
            "error": "payroll_values_not_headcount_schedule_derived",
            "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
            "quarter": quarter_index,
            "previous_value": expected_value,
            "current_value": current_value,
            "reason": "Payroll forecast values must equal the persisted payroll_headcount quarter totals.",
            "validation_category": "payroll_headcount_schedule",
          })
          break
  return {
    "status": "failed" if details else "passed",
    "details": deepcopy(details),
    "current_runtime": deepcopy(current_runtime) if isinstance(current_runtime, dict) else {},
    "expected_runtime": deepcopy((schedule or {})),
  }
