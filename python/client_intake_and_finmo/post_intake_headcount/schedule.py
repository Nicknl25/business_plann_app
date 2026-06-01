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
      # P3.40 Contract Layer Cleanup 3/6 -- Contract 5d R-b:
      # ASSESSED + KEPT for legacy DB support. role_title +
      # full_name are schema-blessed PersonContract fields per
      # people_capability_consultant.py:94-114; role + name are
      # NOT in the current schema (no current GPT writer). The
      # 4-level fallback chain preserves staffing-row
      # generation for any legacy person-item shape in the
      # production DB that uses role/name instead of
      # role_title/full_name. PersonContract has extra='ignore'
      # tolerating legacy keys at the contract gate; this site
      # is the consumer that actually USES them. Per directive
      # Cleanup 3/6: "THE classic 'legacy data support' case
      # ... Likely keep the fallback".
      role_title = str(item.get("role_title") or item.get("full_name") or item.get("role") or item.get("name") or "").strip()
      if not role_title:
        continue
      rows.append(
        {
          "source_group": group_name,
          "position_title": role_title,
          "annual_wage": _round_currency(item.get("annual_wage")),
          "wage_source": str(item.get("wage_source") or "").strip(),
          # months_until_hire is schema-bound to inferred_roles
          # items (per consultant.py:128), NOT person items.
          # This read from person items defends against the
          # cross-shape leak hypothesis: a legacy/edit-mode
          # path that wrote months_until_hire onto a person
          # item. Per Cleanup 3/6 5d R-b: ASSESSED + KEPT for
          # legacy DB support pending audit.
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


def _compact_payroll_gpt_context(user_context: Dict[str, Any]) -> Dict[str, Any]:
  """Phase 9 P3.32 K12.1 (G-B2) — shrink Handler C's GPT context without
  dropping any field GPT consults.

  Three content compactions (compact JSON serialization is applied
  separately at the prompt-build step):
    1. oews_title_catalog[].wage_source removed — it is the constant
       'oews_median' for GPT's purposes and Python re-derives the wage
       from the exact selected title row, so GPT never needs it to pick
       a title. occ_title / occ_code / annual_wage are preserved.
    2. payroll_capacity_grid — the identical per-quarter 'rule' string is
       hoisted to a single 'payroll_capacity_grid_note'; the per-row copy
       is dropped (same text, stated once).
    3. revenue_driver_context.quarter_rows[].product_rows removed — the
       per-product capacity/unit_price/utilization decomposition is H2's
       revenue-authoring surface, not Handler C's; the per-quarter
       computed_revenue / finmo_revenue trajectory Handler C sizes
       payroll against is preserved.

  Returns the same dict (mutated in place and returned) so the caller's
  downstream filter/budget steps see the compacted form. Defensive: any
  shape mismatch leaves that field untouched.
  """
  if not isinstance(user_context, dict):
    return user_context

  catalog = user_context.get("oews_title_catalog")
  if isinstance(catalog, dict):
    cands = catalog.get("title_candidates")
    if isinstance(cands, list):
      catalog["title_candidates"] = [
        {k: v for k, v in c.items() if k != "wage_source"}
        if isinstance(c, dict) else c
        for c in cands
      ]

  grid = user_context.get("payroll_capacity_grid")
  if isinstance(grid, list) and grid:
    hoisted_rule = None
    for row in grid:
      if isinstance(row, dict) and row.get("rule"):
        hoisted_rule = row.get("rule")
        break
    if hoisted_rule is not None:
      user_context["payroll_capacity_grid_note"] = hoisted_rule
      user_context["payroll_capacity_grid"] = [
        {k: v for k, v in row.items() if k != "rule"}
        if isinstance(row, dict) else row
        for row in grid
      ]

  rdc = user_context.get("revenue_driver_context")
  if isinstance(rdc, dict):
    qrows = rdc.get("quarter_rows")
    if isinstance(qrows, list):
      rdc["quarter_rows"] = [
        {k: v for k, v in row.items() if k != "product_rows"}
        if isinstance(row, dict) else row
        for row in qrows
      ]

  return user_context


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
    # tot_emp / o_group carried so the deterministic round-1 producer can
    # weight the staffing mix by NAICS occupation employment share and
    # restrict to detailed occupations (avoid double-counting major/total
    # aggregate rows). GPT-facing context already drops wage_source via
    # _compact_payroll_gpt_context; these two are small additive fields.
    tot_emp_value = _safe_float(row.get("tot_emp"))
    candidates.append(
      {
        "occ_title": occ_title,
        "occ_code": occ_code,
        "annual_wage": _round_currency(picked),
        "wage_source": source or "oews_median",
        "o_group": str(row.get("o_group") or "").strip().lower(),
        "tot_emp": round(float(tot_emp_value), 2) if tot_emp_value is not None else None,
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


def _intake_implied_operating_intensity(
  *,
  financials: Dict[str, Any],
  year1: Dict[str, Any],
) -> Dict[str, Any]:
  """Phase 9 P3.32 K9 follow-up — surface an intake-implied
  operating-intensity signal to Handler C for class-selection context.

  Background: the K9 prompt restructure removed two pre-K9 anchoring
  elements (the "first choose" pinning framing and the medium-class
  example), making class choice equally mutable. For Skyward (which
  was stuck on high pre-K9) this was the cure. For Sunny Glaze Donuts
  (where pre-K9 GPT picked medium and converged) the open-ended
  framing moved GPT to high — operationally heavier than Sunny needs,
  pushing Q11 EBITDA below the universal-viability gate.

  Root cause: GPT lacked an explicit operating-intensity signal in
  the K9 context. The intake itself reports payroll_total_year1 and
  revenue; their ratio is a first-order signal for what class fits
  the operator's stated reality. Universal across all NAICS, every
  intake (when payroll + revenue are both present).

  Doctrine notes:
    - Intake numbers are NOT BINDING (per intake_non_binding_policy
      already in user_context).
    - The ratio is INFORMATIONAL — Handler C may still choose any
      class. Tool 2 surfaces which classes accept any specific
      target value; Tool 1 surfaces all class bounds.
    - Universal — no NAICS-specific hardcoding. Every intake that
      reports both payroll and revenue yields a ratio.
    - Returns ``None`` for the ratio when either input is
      missing/zero/non-numeric. Handler C uses operating-model
      judgment alone in that case (the pre-fix K9 behavior).

  See:
    docs/architecture/p3_32_k9_regression_sunny_glaze_donuts_
      investigation.md
  """
  intake_payroll_y1 = financials.get("payroll_total_year1")
  intake_revenue_y1 = (
    year1.get("company_revenue_total_year1")
    or year1.get("revenue_total_year1")
    or financials.get("current_revenue")
  )
  implied_payroll_pct: Optional[float] = None
  try:
    payroll_value = float(intake_payroll_y1) if intake_payroll_y1 is not None else 0.0
    revenue_value = float(intake_revenue_y1) if intake_revenue_y1 is not None else 0.0
    if revenue_value > 0.0 and payroll_value > 0.0:
      implied_payroll_pct = round(payroll_value / revenue_value, 4)
  except (TypeError, ValueError):
    implied_payroll_pct = None
  return {
    "intake_payroll_year1": intake_payroll_y1,
    "intake_revenue_year1": intake_revenue_y1,
    "implied_payroll_percent_of_revenue": implied_payroll_pct,
    "note": (
      "Computed from intake. Intake numbers are NOT BINDING (see "
      "intake_non_binding_policy in OPERATING CONTEXT). This is one "
      "signal for understanding the operator's stated operating "
      "intensity. Call find_classes_accepting_target_payroll_pct "
      "with the implied value to see which labor_intensity_class "
      "options accept it, then choose the class whose bounds match "
      "the operating model's actual labor intensity profile. For "
      "scale-ups and turnarounds the implied ratio may understate "
      "the steady-state intensity; for established operators it "
      "indicates current intensity. Universal across NAICS — same "
      "signal for every business."
    ),
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


# ---------------------------------------------------------------------------
# Round-1 deterministic payroll producer (Lineage B).
#
# Authority: docs/architecture/payroll_producer_spec.md. Python authors the
# round-1 payroll_headcount_schedule deterministically from the business's OWN
# per-quarter revenue (the dollar path); GPT later critiques the output via the
# amalgamated responder (confirm/veto/choose/other). This REPLACES
# build_pending_payroll_stub on the canonical set_payroll_schedule(contract=None)
# path. NO productivity coefficient is used to SIZE FTE — that is the Fix #2
# OQ-1 wall; revenue->FTE goes through OEWS wages, not productivity.
#
# The four confirmed values (spec Step 1) are NAMED policy defaults, not inline
# literals. Benefits reuse the existing DB policy value
# default_payroll_tax_benefits_pct (= 0.22). The rest are named module
# constants here because they are UNIVERSAL producer policy (not per-NAICS
# cohort data); promoting them into post_intake_headcount_policy_lookup is a
# deferred option if per-cohort variation is ever needed.
# ---------------------------------------------------------------------------

# OQ-2 — intensity -> capacity_labor_model map.
ROUND1_INTENSITY_TO_CAPACITY_LABOR_MODEL: Dict[str, str] = {
  "low": "system_driven",
  "medium": "hybrid",
  "high": "labor_driven",
  "expert": "expert_driven",
}
# OQ-6 — staffing-mix breadth: top-N occupations by NAICS tot_emp.
ROUND1_MIX_TOP_N = 6
# OQ-5 — per-quarter revenue source priority (finmo first, computed fallback).
ROUND1_REVENUE_SOURCE_PRIORITY = ("finmo_revenue", "computed_revenue_from_model_input")
# Part D fallback when intake cannot imply an intensity (payroll/revenue absent).
ROUND1_DEFAULT_LABOR_INTENSITY_CLASS = "medium"
# Neutral wage positioning: pay at the OEWS-resolved median, no premium. The
# multiplier is sourced from the policy tier bounds (floor.min), not a literal.
ROUND1_DEFAULT_WAGE_POSITIONING_TIER = "floor"
# Lifecycle floor: a supporting title, once active, must keep ending_fte > 0
# every quarter (lookup._validate_supporting_title_lifecycle). Tiny early-
# quarter budgets can round below this; floor to keep the schedule valid.
ROUND1_SUPPORTING_FTE_FLOOR = 0.01
# Reported-productivity fallback for the degenerate no-supporting-FTE case only
# (the contract field must be > 0); never a sizing input (Part G).
ROUND1_REPORTED_PRODUCTIVITY_FALLBACK = 1.0


def _round1_resolve_labor_intensity_class(
  *,
  policy: Dict[str, Any],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
  """Deterministically resolve labor_intensity_class (spec Part D).

  Picks the class whose payroll/revenue band midpoint is nearest the intake-
  implied payroll/revenue ratio. Falls back to the named default when intake
  does not supply both payroll and revenue. Returns (class, source_note).
  """
  bounds = policy.get("payroll_revenue_sanity_bounds") if isinstance(policy, dict) else {}
  bounds = bounds if isinstance(bounds, dict) else {}
  implied = _intake_implied_operating_intensity(
    financials=financials_json if isinstance(financials_json, dict) else {},
    year1=financials_year1_json if isinstance(financials_year1_json, dict) else {},
  ).get("implied_payroll_percent_of_revenue")
  if implied is None or not bounds:
    return ROUND1_DEFAULT_LABOR_INTENSITY_CLASS, "default_intake_silent"
  best_class: Optional[str] = None
  best_distance: Optional[float] = None
  for class_name, band in bounds.items():
    if not isinstance(band, dict):
      continue
    min_pct = _safe_float(band.get("min_pct"))
    max_pct = _safe_float(band.get("max_pct"))
    if min_pct is None or max_pct is None or max_pct < min_pct:
      continue
    midpoint = (float(min_pct) + float(max_pct)) / 2.0
    distance = abs(float(implied) - midpoint)
    if best_distance is None or distance < best_distance:
      best_distance = distance
      best_class = str(class_name).strip().lower()
  if not best_class:
    return ROUND1_DEFAULT_LABOR_INTENSITY_CLASS, "default_no_policy_bounds"
  return best_class, f"intake_implied_payroll_pct={round(float(implied), 4)}"


def author_round1_payroll_contract(
  *,
  business_facts: Optional[Dict[str, Any]] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  policy_code: str = "default",
) -> Dict[str, Any]:
  """Author a deterministic round-1 payroll_headcount_schedule CONTRACT from the
  business's own per-quarter revenue (the dollar path). See
  docs/architecture/payroll_producer_spec.md.

  Sizing chain (per quarter q): payroll_budget = revenue_q x band_midpoint;
  minus fixed key-person payroll; supporting FTE solved by inverting the
  builder's wage formula (avg_fte x wage / 4 x (1+benefits)) using the SAME
  wage path (_select_wage median + _policy_adjusted_annual_wage). Flat within
  the quarter (starting == ending) so the builder's average-based payroll
  reproduces the budget exactly. Output is shaped to pass
  validate_payroll_headcount_contract_payload.
  """
  del stage_ramp_contract  # context only at round-1; not a sizing input here
  policy = post_intake_headcount_policy_for(policy_code=policy_code) or {}
  horizon = int(policy.get("schedule_horizon_quarters") or _contract_horizon_quarters())
  benefits_pct = round(float(policy.get("default_payroll_tax_benefits_pct") or 0.22), 2)

  # --- labor intensity + percent-of-revenue midpoint (Parts D, B.4) -------
  labor_intensity_class, intensity_source = _round1_resolve_labor_intensity_class(
    policy=policy,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
  )
  from client_intake_and_finmo.post_intake_headcount.lookup import (  # type: ignore
    headcount_payroll_revenue_sanity_bounds,
  )
  band = headcount_payroll_revenue_sanity_bounds(policy, labor_intensity_class=labor_intensity_class)
  pct_mid = round((float(band["min_pct"]) + float(band["max_pct"])) / 2.0, 4)

  capacity_labor_model = ROUND1_INTENSITY_TO_CAPACITY_LABOR_MODEL.get(
    labor_intensity_class,
    ROUND1_INTENSITY_TO_CAPACITY_LABOR_MODEL[ROUND1_DEFAULT_LABOR_INTENSITY_CLASS],
  )
  wage_tiers = policy.get("wage_positioning_multiplier") if isinstance(policy.get("wage_positioning_multiplier"), dict) else {}
  floor_bounds = wage_tiers.get(ROUND1_DEFAULT_WAGE_POSITIONING_TIER) if isinstance(wage_tiers, dict) else None
  if not isinstance(floor_bounds, dict) or _safe_float(floor_bounds.get("min")) is None:
    _payroll_fail_fast(
      "payroll_round1_wage_positioning_tier_missing",
      f"policy wage_positioning_multiplier missing '{ROUND1_DEFAULT_WAGE_POSITIONING_TIER}' tier bounds.",
      stage="payroll_round1_producer",
    )
  wage_multiplier = round(float(floor_bounds.get("min")), 4)

  # --- per-quarter revenue + authored capacity (Part B.2, OQ-5) -----------
  rdc = _revenue_driver_context_from_model_input(model_input_json, finmo_json=finmo_json)
  revenue_by_q: Dict[int, float] = {}
  capacity_by_q: Dict[int, float] = {}
  for qrow in rdc.get("quarter_rows") or []:
    q = int(qrow.get("quarter_index") or 0)
    if q < 1 or q > horizon:
      continue
    revenue_value: Optional[float] = None
    for key in ROUND1_REVENUE_SOURCE_PRIORITY:
      candidate_value = qrow.get(key)
      if candidate_value is not None:
        revenue_value = float(candidate_value)
        break
    revenue_by_q[q] = max(0.0, float(revenue_value or 0.0))
    capacity_by_q[q] = sum(
      max(0.0, float((pr or {}).get("capacity_units") or 0.0))
      for pr in (qrow.get("product_rows") or [])
    )

  # --- key people: fixed payroll per quarter (builder math) (Part B.5) ----
  key_rows = _key_people_rows_from_intake(
    people_json, policy=policy, horizon=horizon,
    business_facts=business_facts, ops_json=ops_json,
  )
  key_payroll_by_q: Dict[int, int] = {q: 0 for q in range(1, horizon + 1)}
  for row in key_rows:
    q = int(row.get("quarter_index") or 0)
    if q < 1 or q > horizon:
      continue
    annual_wage = _round_currency(row.get("annual_wage"))
    row_benefits = round(float(_safe_ratio(row.get("payroll_taxes_benefits_percent")) or 0.0), 2)
    average_fte = round((float(row.get("starting_fte") or 0.0) + float(row.get("ending_fte") or 0.0)) / 2.0, 2)
    wage_cost = _round_currency((average_fte * annual_wage) / 4.0)
    taxes = _round_currency(wage_cost * row_benefits)
    key_payroll_by_q[q] += int(wage_cost + taxes)

  # --- supporting role mix from OEWS tot_emp (Part C, OQ-6) ---------------
  catalog = _oews_title_catalog_for_business(
    business_facts=business_facts, ops_json=ops_json, people_json=people_json,
  )
  candidates = [c for c in (catalog.get("title_candidates") or []) if isinstance(c, dict)]

  def _emp(candidate: Dict[str, Any]) -> float:
    value = _safe_float(candidate.get("tot_emp"))
    return float(value) if value is not None else 0.0

  def _has_wage(candidate: Dict[str, Any]) -> bool:
    return float(_round_currency(candidate.get("annual_wage"))) > 0.0

  # Prefer detailed occupations with positive tot_emp (avoid double-counting
  # major/total aggregate rows in the employment-share weights).
  pool = [c for c in candidates if c.get("o_group") == "detailed" and _emp(c) > 0.0 and _has_wage(c)]
  mix_source = "oews_tot_emp_detailed"
  if not pool:
    pool = [c for c in candidates if _has_wage(c)]
    mix_source = "oews_tot_emp_any" if any(_emp(c) > 0.0 for c in pool) else "equal_weight_no_tot_emp"
  if not pool:
    _payroll_fail_fast(
      "payroll_round1_no_supporting_titles",
      f"No usable OEWS supporting titles for naics={catalog.get('business_naics_6')}.",
      stage="payroll_round1_producer",
      details={"business_naics_6": catalog.get("business_naics_6")},
    )
  pool.sort(key=lambda c: (-_emp(c), str(c.get("occ_title") or "").lower()))
  selected = pool[: max(1, int(ROUND1_MIX_TOP_N))]
  emp_total = sum(_emp(c) for c in selected)
  if emp_total > 0.0:
    weights = [_emp(c) / emp_total for c in selected]
  else:
    weights = [1.0 / len(selected) for _ in selected]
  selected_base_wage = [int(_round_currency(c.get("annual_wage"))) for c in selected]

  # --- dollar-path FTE per title per quarter (Part B.1, B.6) --------------
  # Flat within quarter (starting == ending) so average_fte == ending and the
  # builder's average-based payroll reproduces the supporting budget exactly.
  grid: List[Dict[str, Any]] = []
  total_supporting_avg_fte = 0.0
  for q in range(1, horizon + 1):
    revenue_q = revenue_by_q.get(q, 0.0)
    supporting_budget_q = max(0.0, revenue_q * pct_mid - float(key_payroll_by_q.get(q, 0)))
    wage_iq = [
      _policy_adjusted_annual_wage(base, quarter_index=q, policy=policy, wage_positioning_multiplier=wage_multiplier)
      for base in selected_base_wage
    ]
    w_dot_wage = sum(weights[i] * float(wage_iq[i]) for i in range(len(selected)))
    if supporting_budget_q > 0.0 and w_dot_wage > 0.0:
      level_q = supporting_budget_q * 4.0 / ((1.0 + benefits_pct) * w_dot_wage)
    else:
      level_q = 0.0
    for i, candidate in enumerate(selected):
      ending = round(max(level_q * weights[i], ROUND1_SUPPORTING_FTE_FLOOR), 2)
      grid.append({
        "q": q,
        "oews_occ_title": str(candidate.get("occ_title") or "").strip(),
        "starting_fte": ending,   # flat within quarter -> avg_fte == ending
        "hires": 0.0,
        "ending_fte": ending,
        "payroll_tax_benefits_pct": benefits_pct,
      })
      total_supporting_avg_fte += ending

  # --- productivity: DERIVED / reported, never looked up (Part G) ---------
  total_capacity = sum(capacity_by_q.get(q, 0.0) for q in range(1, horizon + 1))
  if total_supporting_avg_fte > 0.0 and total_capacity > 0.0:
    productivity = round(total_capacity / total_supporting_avg_fte, 4)
  else:
    productivity = ROUND1_REPORTED_PRODUCTIVITY_FALLBACK
  if productivity <= 0.0:
    productivity = ROUND1_REPORTED_PRODUCTIVITY_FALLBACK

  rationale = (
    f"deterministic_round1_producer: per-quarter payroll budget = own revenue x "
    f"{pct_mid} ({labor_intensity_class} band midpoint, source={intensity_source}); "
    f"key-person payroll subtracted; supporting FTE solved from OEWS wages "
    f"(mix_source={mix_source}, top {len(selected)} by tot_emp); productivity "
    f"reported (capacity/FTE), not a sizing input."
  )

  return {
    "capacity_labor_model": capacity_labor_model,
    "labor_intensity_class": labor_intensity_class,
    "wage_positioning_tier": ROUND1_DEFAULT_WAGE_POSITIONING_TIER,
    "wage_positioning_multiplier": wage_multiplier,
    "capacity_units_per_supporting_fte": productivity,
    "target_payroll_percent_of_revenue": pct_mid,
    "rationale": rationale,
    "payroll_headcount_grid": grid,
  }


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
# Phase 9 P3.32 K9 — Handler C tool-calling migration (Stage B).
#
# The pre-K9 iterative refinement loop (text.format.type=json_schema
# strict, 10 rounds, per-round REPLACE-only feedback packet, K8
# enrichment buried in user-message JSON) has been deleted. Handler
# C now uses the canonical tool-calling session pattern shared with
# H2 (exhaustion), H3 (funding), H4 (stage_ramp). See
# tool_calling_session.py in this package and doctrine.md §10.4.
#
# The Layer dispatch codes below remain — the propose tool dispatcher
# imports them when translating exceptions raised by the validator
# chain into the structured tool result that goes back to GPT.
# ---------------------------------------------------------------------------

# Layer A.2 wrapper codes — those whose ``details["errors"]`` carry
# Layer A.2 token-format codes from validate_payroll_headcount_payload.
# Codes outside this set are dispatched to the Layer A.1 (verbatim) or
# Layer A.3 (economic feasibility) paths.
_PAYROLL_LAYER_A2_WRAPPER_CODES = frozenset({
  "payroll_headcount_schedule_validation_failed",
  "payroll_headcount_payload_invalid",
})

_PAYROLL_LAYER_A3_CODE = "payroll_revenue_economic_feasibility_failed"


# Phase 9 P3.32 K9 — deleted pre-K9 iterative-refinement machinery:
#   `_payroll_iterative_machinery_fail_fast`,
#   `_assert_payroll_iterative_state_intact`,
#   `_assert_payroll_iterative_budget_decoupled`,
#   `_build_payroll_iterative_feedback_packet` (incl. its K8
#     enrichment block),
#   `_PAYROLL_ITER_GPT_CALL_COUNT` contextvar,
#   `_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS` constant.
# Their roles are now expressed against the tool-calling session
# machinery in tool_calling_session.py (K8 enrichment lives in
# Tool 3's structured_failures.alternatives.accepting_classes,
# IN-LINE in the tool result). See doctrine.md §10.4.


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
  """Phase 9 P3.32 K9 — payroll tool-calling session.

  Migrated from the pre-K9 strict-mode iterative-refinement loop
  (10 rounds, per-round payload rebuild, REPLACE-only feedback
  packet, K8 enrichment buried in user-message JSON) to a
  tool-calling session matching H2/H3/H4. See
  ``tool_calling_session.run_payroll_tool_calling_session`` and
  doctrine.md §10.4.

  GPT iterates by calling three tools:
    1. ``get_payroll_revenue_sanity_bounds(class)`` — authoritative
       per-class + all-class bounds.
    2. ``find_classes_accepting_target_payroll_pct(target)`` —
       accepting + rejecting class partition for a target value.
    3. ``propose_payroll_headcount_schedule(<full contract>)`` —
       runs Layers A.1 + A.2 + A.3 and returns the validator
       outcome with K8 enrichment IN-LINE in structured_failures.

  When called from the convergence runner's payroll-repair path,
  ``previous_contract_failure`` is threaded into the initial user
  prompt as a Round-1 seed (instead of the deleted per-round
  ``previous_contract_failure`` JSON envelope).

  Budget: HARD_CAP_TOOL_CALLS=10 (flat, no two-phase). On hard cap
  without verified commit, hard-fails with
  ``payroll_tool_calling_session_exhausted`` — payroll commits must
  be validator-accepted (no best-effort fallback).

  P3.33 Phase 3 step 3b transitional shim:
    The GPT iteration loop is GONE (tool_calling_session.py deleted).
    Authoring authority belongs to the amalgamated GPT session via
    ``post_intake_amalgamated.tools.set_payroll_schedule`` (the
    canonical entry point). The amalgamated session is built in step
    5; until then this orchestrator entry returns a structurally-
    valid empty payroll payload so the pre-amalgamation pipeline
    continues to make progress. Sequence-step gating is preserved.
  """
  _assert_payroll_sequence_step(
    allowed_step_keys=["payroll_gpt_contract_request", "payroll_feasibility_repair"],
    allowed_executor_functions=[
      "estimate_payroll_headcount_schedule_with_gpt",
      "retry_payroll_headcount_schedule_from_feasibility_failure",
    ],
  )
  # P3.41 NexGen E2E iter 11 fix (option 3): the inline build-and-stamp
  # was extracted into build_pending_payroll_stub() in lookup.py so the
  # canonical amalgamated entry (set_payroll_schedule(contract=None))
  # can produce the identical stub without tripping the legacy gate
  # above. This shim keeps the gate intact for its legacy controller
  # callers; only the body delegates to the shared helper now.
  from client_intake_and_finmo.post_intake_headcount.lookup import (  # type: ignore
    build_pending_payroll_stub,
  )
  return build_pending_payroll_stub(
    draft_id=draft_id,
    client_id=client_id,
    previous_contract_failure=previous_contract_failure,
  )


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
  # Part E: capacity_units_per_supporting_fte is reported-only now (it does NOT
  # drive capacity). The old fatal "productivity must be positive" guard is
  # retired -- a missing/zero reported productivity no longer blocks the
  # (non-mutating) capacity consistency pass.
  productivity = round(float(_safe_float(schedule.get("capacity_units_per_supporting_fte")) or 0.0), 6)
  rows = _payroll_headcount_grid_rows(schedule)
  average_fte_by_quarter = _average_fte_by_quarter_from_rows(rows)
  # Part E (payroll_producer_spec.md): revenue.Capacity is the step-10 revenue
  # anchor. Payroll FTE NO LONGER overwrites capacity -- the
  # revenue -> FTE -> capacity -> revenue loop is formally broken. This function
  # is now a NON-mutating consistency pass: it MARKS the capacity rows as
  # payroll-owned (so finmo freezes them at the authored anchor and no other
  # handler rewrites them) and records an implied-vs-anchor comparison, but it
  # does NOT change any capacity value. capacity_units_per_supporting_fte is a
  # reported figure here, never a driver (Part G).
  implied_capacity_from_fte = {
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
      "Revenue Capacity rows are required so payroll FTE can be reconciled against the revenue-primary capacity anchor.",
      stage="payroll_supported_capacity_application",
    )
  anchor_capacity_by_quarter = {quarter: 0.0 for quarter in range(1, live_count + 1)}
  for row in capacity_rows:
    _stub, live_values = _row_stub_and_live_values(list(row.get("values") or []), live_count=live_count)
    for idx, value in enumerate(live_values[:live_count], start=1):
      anchor_capacity_by_quarter[idx] = round(
        anchor_capacity_by_quarter.get(idx, 0.0) + max(0.0, float(_safe_float(value) or 0.0)), 6,
      )
    # Mark payroll-owned WITHOUT changing row["values"]: capacity stays the
    # step-10 anchor. The marker preserves finmo's freeze behavior and blocks
    # other handlers from rewriting capacity; the values are untouched.
    row["controller_write"] = False
    row["derived_driver"] = "payroll_supported_capacity"
    row["payroll_supported_capacity"] = {
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "capacity_source": "revenue_primary_step10_anchor",
      "capacity_units_per_supporting_fte_reported": productivity,
      "schedule_storage_column": PAYROLL_HEADCOUNT_DRAFT_COLUMN,
    }
  next_payload.setdefault("derived_driver_policies", {})
  next_payload.setdefault("derived_driver_runtime", {})
  if isinstance(next_payload.get("derived_driver_policies"), dict):
    next_payload["derived_driver_policies"]["revenue::Capacity"] = {
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "capacity_source": "revenue_primary_step10_anchor",
      "payroll_source": PAYROLL_HEADCOUNT_SOURCE,
      "capacity_units_per_supporting_fte_reported": productivity,
    }
  if isinstance(next_payload.get("derived_driver_runtime"), dict):
    next_payload["derived_driver_runtime"]["payroll_supported_capacity"] = {
      "policy_version": PAYROLL_HEADCOUNT_POLICY_VERSION,
      "mode": "revenue_primary_consistency_check",
      "formula": "capacity is the revenue-authored step-10 anchor; payroll FTE does not overwrite it (loop broken, Part E)",
      "capacity_units_per_supporting_fte_reported": productivity,
      "anchor_capacity_by_quarter": {
        str(quarter): round(float(anchor_capacity_by_quarter.get(quarter) or 0.0), 6)
        for quarter in range(1, live_count + 1)
      },
      "implied_capacity_from_fte_by_quarter": {
        str(quarter): round(float(implied_capacity_from_fte.get(quarter) or 0.0), 6)
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
  # Part E: productivity is reported-only; no positivity requirement here.
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = sections.get("revenue") if isinstance(sections.get("revenue"), list) else []
  capacity_rows = [
    row for row in revenue_rows
    if isinstance(row, dict) and str(row.get("driver") or row.get("driver_name") or "").strip().lower() == "capacity"
  ]
  if not capacity_rows:
    return [{
      "error": "payroll_supported_capacity_rows_missing",
      "reason": "Revenue Capacity rows are required so payroll can be reconciled against the revenue-primary capacity anchor.",
    }]
  # Part E: the per-quarter capacity == sum(avg_fte) * productivity equality
  # check is GONE -- that equality WAS the revenue -> FTE -> capacity loop.
  # Capacity is now the revenue-authored step-10 anchor; we only verify the
  # STRUCTURAL marker (so finmo freezes the anchor + no handler rewrites it),
  # never that the values match an FTE-derived figure.
  unmarked_rows: List[str] = []
  for row in capacity_rows:
    if str(row.get("derived_driver") or "").strip() != "payroll_supported_capacity":
      unmarked_rows.append(str(row.get("label") or row.get("revenue_slot_key") or "Capacity").strip())
  violations: List[Dict[str, Any]] = []
  if unmarked_rows:
    violations.append({
      "error": "payroll_supported_capacity_marker_missing",
      "reason": "Capacity rows must be marked derived_driver='payroll_supported_capacity'.",
      "rows": unmarked_rows[:20],
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
      # OQ-1 (payroll_producer_spec.md Part E.3 / Part I): the productivity-nudge
      # repair lever is RETIRED. capacity_units_per_supporting_fte no longer
      # drives capacity (Part E broke the loop), so a repair that moves
      # productivity moves nothing. The lever is the dollar path: re-derive
      # supporting FTE / wage-budget from the revised per-quarter revenue. The
      # productivity-direction fields are gone -- the gpt_repair_constraints
      # builder degrades gracefully to no productivity caps/floors.
      revenue_bound_direction = "at_or_below" if too_low else "at_or_above"
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
          "current_capacity_units_per_supporting_fte_reported": productivity,
          "total_average_fte": round(float(average_fte_by_quarter.get(quarter_index) or 0.0), 6),
          "required_revenue_at_policy_bound": required_revenue_at_bound,
          "required_revenue_direction": revenue_bound_direction,
          "revenue_multiplier_to_policy_bound": revenue_multiplier_to_bound,
          "math_source": (
            "payroll / policy_bound; payroll = sum(avg_fte * wage / 4 * (1 + benefits)). "
            "Part E: capacity is the revenue-primary anchor and is NOT a repair lever; "
            "re-derive supporting FTE from the per-quarter revenue (the dollar path)."
          ),
        },
        "required_action": (
          "Re-run the deterministic dollar path (payroll_producer_spec.md Part B) against the "
          "revised per-quarter revenue: re-derive supporting FTE / wage-budget so payroll/revenue "
          "returns into the policy band. capacity_units_per_supporting_fte is NOT a lever (Part E). "
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
