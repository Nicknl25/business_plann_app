from __future__ import annotations

import os
import threading
import copy
import hashlib
import json
import math
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


from client_intake_and_finmo.intake_submission import get_mysql_connection
from client_intake_and_finmo.post_intake_driver_formulas import (  # type: ignore
  formula_contract_for_mapping_row,
  formula_metadata_errors,
  mapping_formula_defaults,
)


_MAPPING_TABLE_NAME = "post_intak_mapping_lookup"
_CASH_POLICY_TABLE_NAME = "post_intake_cash_policy_lookup"
_GPT_CONTRACT_TABLE_NAME = "post_intake_gpt_contract_lookup"
_GPT_CONTEXT_TABLE_NAME = "post_intake_gpt_context_lookup"
_PROCESS_SEQUENCE_TABLE_NAME = "post_intake_process_sequence_lookup"
_PROCESS_CONTEXT_TABLE_NAME = "post_intake_process_context_lookup"
_LOOKUP_SNAPSHOT_TABLE_NAME = "post_intake_lookup_table_snapshot"
_GOLDEN_BASELINE_NAME = "post_intake_golden_f949316"
_FINMO_ROW_PREFIX = "finmo_json.quarter_rows[*]."
_REVENUE_PATTERN_PREFIX = "revenue::*::*::"
_ENSURE_MAPPING_TABLE_READY = False
_ENSURE_CASH_POLICY_TABLE_READY = False
_ENSURE_GPT_CONTRACT_TABLE_READY = False
_ENSURE_GPT_CONTEXT_TABLE_READY = False
_ENSURE_PROCESS_SEQUENCE_TABLE_READY = False
_ENSURE_PROCESS_CONTEXT_TABLE_READY = False
_ENSURE_LOOKUP_SNAPSHOT_TABLE_READY = False
_ENSURE_MAPPING_TABLE_LOCK = threading.Lock()
_ENSURE_CASH_POLICY_TABLE_LOCK = threading.Lock()
_ENSURE_GPT_CONTRACT_TABLE_LOCK = threading.Lock()
_ENSURE_GPT_CONTEXT_TABLE_LOCK = threading.Lock()
_ENSURE_PROCESS_SEQUENCE_TABLE_LOCK = threading.Lock()
_ENSURE_PROCESS_CONTEXT_TABLE_LOCK = threading.Lock()
_ENSURE_LOOKUP_SNAPSHOT_TABLE_LOCK = threading.Lock()
_POST_INTAKE_PLANNING_MODES = {"turnaround", "normalize", "rebalance"}


_DEFAULT_CASH_POLICY_ROWS: List[Dict[str, Any]] = [
  {
    "cash_strategy": "shareholder_return",
    "debt_position": "low_debt",
    "debt_to_equity_min": 0.00,
    "debt_to_equity_max": 0.50,
    "cash_floor_months": 1.00,
    "cash_ceiling_months": 1.25,
    "distribution_weight": 0.90,
    "debt_paydown_weight": 0.10,
    "retain_weight": 0.00,
    "policy_label": "Prioritize shareholder payouts while making token debt progress.",
  },
  {
    "cash_strategy": "shareholder_return",
    "debt_position": "healthy_debt",
    "debt_to_equity_min": 0.50,
    "debt_to_equity_max": 1.00,
    "cash_floor_months": 1.00,
    "cash_ceiling_months": 1.25,
    "distribution_weight": 0.75,
    "debt_paydown_weight": 0.25,
    "retain_weight": 0.00,
    "policy_label": "Return most surplus while reducing leverage at a measured pace.",
  },
  {
    "cash_strategy": "shareholder_return",
    "debt_position": "high_debt",
    "debt_to_equity_min": 1.00,
    "debt_to_equity_max": 999.00,
    "cash_floor_months": 1.00,
    "cash_ceiling_months": 1.25,
    "distribution_weight": 0.60,
    "debt_paydown_weight": 0.40,
    "retain_weight": 0.00,
    "policy_label": "Still return cash, but materially reduce excessive leverage.",
  },
  {
    "cash_strategy": "balanced",
    "debt_position": "low_debt",
    "debt_to_equity_min": 0.00,
    "debt_to_equity_max": 0.50,
    "cash_floor_months": 1.50,
    "cash_ceiling_months": 2.00,
    "distribution_weight": 0.50,
    "debt_paydown_weight": 0.50,
    "retain_weight": 0.00,
    "policy_label": "Split excess cash between shareholder return and debt discipline.",
  },
  {
    "cash_strategy": "balanced",
    "debt_position": "healthy_debt",
    "debt_to_equity_min": 0.50,
    "debt_to_equity_max": 1.00,
    "cash_floor_months": 1.50,
    "cash_ceiling_months": 2.00,
    "distribution_weight": 0.40,
    "debt_paydown_weight": 0.60,
    "retain_weight": 0.00,
    "policy_label": "Lean toward debt paydown while preserving modest shareholder return.",
  },
  {
    "cash_strategy": "balanced",
    "debt_position": "high_debt",
    "debt_to_equity_min": 1.00,
    "debt_to_equity_max": 999.00,
    "cash_floor_months": 1.50,
    "cash_ceiling_months": 2.00,
    "distribution_weight": 0.20,
    "debt_paydown_weight": 0.80,
    "retain_weight": 0.00,
    "policy_label": "Prioritize deleveraging while allowing limited shareholder return.",
  },
  {
    "cash_strategy": "preserve_cash",
    "debt_position": "low_debt",
    "debt_to_equity_min": 0.00,
    "debt_to_equity_max": 0.50,
    "cash_floor_months": 2.00,
    "cash_ceiling_months": 3.00,
    "distribution_weight": 1.00,
    "debt_paydown_weight": 0.00,
    "retain_weight": 0.00,
    "policy_label": "Retain the larger preserve-cash cushion, then distribute surplus above the ceiling.",
  },
  {
    "cash_strategy": "preserve_cash",
    "debt_position": "healthy_debt",
    "debt_to_equity_min": 0.50,
    "debt_to_equity_max": 1.00,
    "cash_floor_months": 2.00,
    "cash_ceiling_months": 3.00,
    "distribution_weight": 0.25,
    "debt_paydown_weight": 0.75,
    "retain_weight": 0.00,
    "policy_label": "Keep the preserve-cash cushion, then use surplus mostly for debt paydown with modest payouts.",
  },
  {
    "cash_strategy": "preserve_cash",
    "debt_position": "high_debt",
    "debt_to_equity_min": 1.00,
    "debt_to_equity_max": 999.00,
    "cash_floor_months": 2.00,
    "cash_ceiling_months": 3.00,
    "distribution_weight": 0.00,
    "debt_paydown_weight": 1.00,
    "retain_weight": 0.00,
    "policy_label": "No shareholder payouts; use surplus above the preserve-cash ceiling to deleverage.",
  },
]


_DEFAULT_CASH_DEBT_SCHEDULE_POLICY: Dict[str, Any] = {
  "debt_schedule_method": "amortizing_remaining_balance",
  "debt_schedule_required": True,
  "debt_schedule_horizon_quarters": 20,
  "debt_minimum_payment_frequency": "quarterly",
  "debt_min_principal_source_priority": [
    "financials.annual_principal_payment",
    "financials.other_monthly_debt_payments_minus_annual_interest_payment",
    "policy.amortizing_remaining_balance_over_contract_horizon",
  ],
  "debt_extra_paydown_policy": "cash_strategy_surplus_only",
  "debt_interest_rate_source_required": "sba_loan_7a_raw",
  "debt_interest_rate_fallback_allowed": False,
  "debt_schedule_notes": (
    "Python owns contractual minimum debt service through an amortizing quarter-by-quarter debt schedule. "
    "Cash strategy may add extra principal paydown above the scheduled minimum, but may not skip required "
    "minimum principal while debt is outstanding."
  ),
}


_DEFAULT_CASH_PASS_PHASE_SEQUENCE: List[Dict[str, Any]] = [
  {
    "phase_code": "cash_debt_schedule_seed",
    "phase_order": 5,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "minimum_debt_schedule_seeded",
    "notes": "Call post_intake_debt_schedule to apply the SQL cash-policy amortizing debt schedule before cash review so scheduled principal is not optional.",
  },
  {
    "phase_code": "cash_short_term_debt_seed",
    "phase_order": 10,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "seed_short_term_debt_current_portion",
    "notes": "Call post_intake_debt_schedule to normalize current debt portion semantics before building the cash review envelope.",
  },
  {
    "phase_code": "cash_review_context_build",
    "phase_order": 20,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": False,
    "validation_gate": "full_20q_cash_envelope_built",
    "notes": "Build the full 20-quarter cash envelope, strategy policy, debt snapshot, and bounded cash lever grid.",
  },
  {
    "phase_code": "cash_gpt_review",
    "phase_order": 30,
    "phase_owner": "gpt",
    "required": True,
    "requires_finmo_rebuild_after": False,
    "validation_gate": "cash_strategy_review_contract_valid",
    "notes": "GPT fills only the cash strategy decision contract generated from SQL contract lookup rows.",
  },
  {
    "phase_code": "cash_translation_plan",
    "phase_order": 40,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": False,
    "validation_gate": "cash_adjustments_translated_to_model_input_updates",
    "notes": "Translate GPT funding and policy decisions into exact mapped model-input driver updates.",
  },
  {
    "phase_code": "cash_apply_exact_updates",
    "phase_order": 50,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "cash_updates_applied_and_finmo_rebuilt",
    "notes": "Apply cash strategy exact updates to model_input_json and rebuild FINMO.",
  },
  {
    "phase_code": "cash_debt_schedule_rebuild",
    "phase_order": 55,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "minimum_debt_schedule_floor_preserved_after_cash_updates",
    "notes": "Rebuild through post_intake_debt_schedule after cash strategy updates so new debt layers onto existing debt and scheduled principal is preserved.",
  },
  {
    "phase_code": "cash_short_term_debt_current_portion",
    "phase_order": 60,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "short_term_debt_current_portion_applied",
    "notes": "Apply current portion of long-term debt through post_intake_debt_schedule after cash updates and rebuild FINMO.",
  },
  {
    "phase_code": "cash_surplus_cleanup",
    "phase_order": 70,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "surplus_above_policy_ceiling_deployed",
    "notes": "Deploy residual surplus above the SQL cash policy ceiling using mapped cash levers.",
  },
  {
    "phase_code": "cash_post_validation",
    "phase_order": 80,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": False,
    "validation_gate": "cash_post_pass_validation",
    "notes": "Validate cash-pass-owned issues and hard cash rules on the post-action state.",
  },
  {
    "phase_code": "cash_final_finmo_rebuild",
    "phase_order": 90,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "fresh_final_finmo_from_model_input",
    "notes": "Rebuild FINMO from final model_input_json before terminal hard gates.",
  },
  {
    "phase_code": "cash_final_liquidity_gate",
    "phase_order": 100,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": False,
    "validation_gate": "ending_cash_gte_required_buffer_all_20q",
    "notes": "Hard fail if any live quarter remains below the required cash buffer.",
  },
]


def _json_dumps_value(value: Any) -> str:
  return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _json_value(value: Any, default: Any = None) -> Any:
  if isinstance(value, (dict, list)):
    return copy.deepcopy(value)
  raw = str(value or "").strip()
  if not raw:
    return copy.deepcopy(default)
  try:
    parsed = json.loads(raw)
  except Exception:
    return copy.deepcopy(default)
  return parsed


def _gpt_contract_row(
  contract_name: str,
  grid_name: str,
  field_path: str,
  field_name: str,
  field_type: str,
  *,
  required: bool = True,
  strict_required: Optional[bool] = None,
  allow_null: bool = False,
  allow_empty: bool = False,
  is_array_item: bool = False,
  parent_field_path: str = "",
  json_schema_type: str = "",
  min_value: Optional[float] = None,
  max_value: Optional[float] = None,
  # Module 3 Task 3.1 — NAICS-baseline bound injection. When
  # `naics_baseline_metric_key` is set, the contract field's runtime
  # `min_value`/`max_value` are populated from the NAICS resolver cascade
  # at prompt-build time. Static `min_value`/`max_value` (above) become the
  # mapping-table outer envelope when `mapping_table_outer_envelope=True`,
  # so the static bound is the absolute hard cap and NAICS narrows inside.
  naics_baseline_metric_key: str = "",
  naics_baseline_band_kind: str = "",  # 'min_target_max' | 'target_only'
  naics_baseline_min_quantile: Optional[float] = None,
  naics_baseline_max_quantile: Optional[float] = None,
  mapping_table_outer_envelope: bool = True,
  min_items: Optional[int] = None,
  max_items: Optional[int] = None,
  item_contract_grid_name: str = "",
  additional_properties_allowed: bool = False,
  gpt_owned: bool = True,
  python_owned: bool = False,
  editable: bool = True,
  must_match_lookup: Optional[bool] = None,
  contract_phase: str = "",
  horizon_rule: str = "",
  normalization_kind: str = "none",
  rounding_kind: str = "",
  decimal_places: Optional[int] = None,
  validation_kind: str = "schema_only",
  lookup_source: str = "none",
  enum_values: Optional[List[str]] = None,
  allowed_aliases: Optional[List[str]] = None,
  prompt_required_instruction: str = "",
  prompt_label: str = "",
  failure_code: str = "",
  notes: str = "",
) -> Dict[str, Any]:
  normalized_type = str(field_type or "").strip().lower()
  normalized_normalizer = str(normalization_kind or "").strip().lower() or "none"
  resolved_rounding_kind = str(rounding_kind or "").strip().lower()
  resolved_decimal_places = decimal_places
  if not resolved_rounding_kind:
    if normalized_type == "integer_currency" or normalized_normalizer == "integer_currency":
      resolved_rounding_kind = "nearest_dollar"
      resolved_decimal_places = 0 if resolved_decimal_places is None else resolved_decimal_places
    elif normalized_type == "ratio_2dp" or normalized_normalizer == "ratio_2dp":
      resolved_rounding_kind = "nearest_decimal"
      resolved_decimal_places = 2 if resolved_decimal_places is None else resolved_decimal_places
    elif normalized_type in {"integer", "integer_or_negative_one"} or normalized_normalizer == "integer":
      resolved_rounding_kind = "nearest_integer"
      resolved_decimal_places = 0 if resolved_decimal_places is None else resolved_decimal_places
    else:
      resolved_rounding_kind = "none"
  resolved_json_schema_type = str(json_schema_type or "").strip().lower()
  if not resolved_json_schema_type:
    if normalized_type in {"integer", "integer_currency", "integer_or_negative_one"}:
      resolved_json_schema_type = "integer"
    elif normalized_type in {"number", "ratio_2dp"}:
      resolved_json_schema_type = "number"
    elif normalized_type == "boolean":
      resolved_json_schema_type = "boolean"
    elif normalized_type == "array":
      resolved_json_schema_type = "array"
    elif normalized_type == "object":
      resolved_json_schema_type = "object"
    else:
      resolved_json_schema_type = "string"
  resolved_must_match_lookup = must_match_lookup
  if resolved_must_match_lookup is None:
    resolved_must_match_lookup = bool(str(lookup_source or "").strip().lower() not in {"", "none"})
  resolved_strict_required = required if strict_required is None else strict_required
  resolved_failure_code = str(failure_code or "").strip().lower()
  if not resolved_failure_code:
    safe_path = str(field_path or "").strip().lower().replace("[]", "").replace(".", "_")
    resolved_failure_code = f"{str(contract_name or '').strip().lower()}_{safe_path}_contract_invalid"
  return {
    "contract_name": contract_name,
    "grid_name": grid_name,
    "field_path": field_path,
    "field_name": field_name,
    "field_type": field_type,
    "required": required,
    "strict_required": bool(resolved_strict_required),
    "allow_null": allow_null,
    "allow_empty": allow_empty,
    "is_array_item": is_array_item,
    "parent_field_path": parent_field_path,
    "json_schema_type": resolved_json_schema_type,
    "min_value": min_value,
    "max_value": max_value,
    "naics_baseline_metric_key": naics_baseline_metric_key or "",
    "naics_baseline_band_kind": naics_baseline_band_kind or "",
    "naics_baseline_min_quantile": naics_baseline_min_quantile,
    "naics_baseline_max_quantile": naics_baseline_max_quantile,
    "mapping_table_outer_envelope": bool(mapping_table_outer_envelope),
    "min_items": min_items,
    "max_items": max_items,
    "item_contract_grid_name": item_contract_grid_name,
    "additional_properties_allowed": additional_properties_allowed,
    "gpt_owned": gpt_owned,
    "python_owned": python_owned,
    "editable": editable,
    "must_match_lookup": bool(resolved_must_match_lookup),
    "contract_phase": contract_phase,
    "horizon_rule": horizon_rule,
    "normalization_kind": normalization_kind,
    "rounding_kind": resolved_rounding_kind,
    "decimal_places": resolved_decimal_places,
    "validation_kind": validation_kind,
    "lookup_source": lookup_source,
    "enum_values": enum_values or [],
    "allowed_aliases": allowed_aliases or [],
    "prompt_required_instruction": prompt_required_instruction,
    "prompt_label": prompt_label,
    "failure_code": resolved_failure_code,
    "notes": notes,
  }


def _gpt_context_row(
  contract_name: str,
  context_key: str,
  *,
  context_group: str = "",
  source_kind: str = "runtime",
  source_path: str = "",
  transform_kind: str = "copy",
  include_phase: str = "planner",
  required: bool = True,
  include_in_prompt: bool = True,
  max_items: Optional[int] = None,
  max_chars: Optional[int] = None,
  failure_code: str = "",
  notes: str = "",
) -> Dict[str, Any]:
  normalized_contract = str(contract_name or "").strip().lower()
  normalized_key = str(context_key or "").strip()
  normalized_failure = str(failure_code or "").strip().lower()
  if not normalized_failure:
    safe_key = normalized_key.lower().replace(".", "_").replace("[]", "").replace("-", "_")
    normalized_failure = f"{normalized_contract}_{safe_key}_context_invalid"
  return {
    "contract_name": normalized_contract,
    "context_key": normalized_key,
    "context_group": context_group,
    "source_kind": source_kind,
    "source_path": source_path,
    "transform_kind": transform_kind,
    "include_phase": include_phase,
    "required": bool(required),
    "include_in_prompt": bool(include_in_prompt),
    "max_items": max_items,
    "max_chars": max_chars,
    "failure_code": normalized_failure,
    "notes": notes,
  }


def _process_sequence_context_keys_from_paths(value: Any) -> List[str]:
  raw = str(value or "").strip()
  if not raw:
    return []
  ordered: List[str] = []
  for token in re.split(r"[;,]", raw):
    key = str(token or "").strip()
    if not key:
      continue
    key = re.sub(r"\s+", "_", key)
    if key and key not in ordered:
      ordered.append(key)
  return ordered


def _process_sequence_path(
  *,
  phase: str,
  step_key: str,
  parent_step_key: str = "",
) -> str:
  parent = str(parent_step_key or "").strip().lower()
  key = str(step_key or "").strip().lower()
  if parent:
    return f"{parent}.{key}"
  return f"{str(phase or '').strip().lower()}.{key}".strip(".")


def _process_sequence_row(
  phase: str,
  step_order: int,
  step_key: str,
  handler_key: str,
  *,
  contract_name: str = "",
  context_contract_name: str = "",
  context_include_phase: str = "",
  required_lookup_tables: Optional[List[str]] = None,
  horizon_rule: str = "",
  timeout_seconds: Optional[float] = None,
  max_attempts: Optional[int] = None,
  required: bool = True,
  enabled: bool = True,
  fail_fast_code: str = "",
  python_role: str = "",
  python_timing: str = "",
  python_action: str = "",
  input_object_path: str = "",
  output_object_path: str = "",
  validation_subject_path: str = "",
  parent_step_key: str = "",
  step_kind: str = "process",
  hierarchy_level: Optional[int] = None,
  sequence_path: str = "",
  executor_function: str = "",
  required_context_keys: Optional[List[str]] = None,
  produced_output_keys: Optional[List[str]] = None,
  output_storage: Optional[List[Dict[str, Any]]] = None,
  recompute_triggers: Optional[List[Dict[str, Any]]] = None,
  output_finality: str = "stage_final_no_downstream_mutation",
  object_controls: Optional[List[Dict[str, Any]]] = None,
  notes: str = "",
) -> Dict[str, Any]:
  resolved_input_path = input_object_path or f"{step_key}.input"
  resolved_output_path = output_object_path or f"{step_key}.output"
  resolved_required_context_keys = list(
    required_context_keys
    if required_context_keys is not None
    else _process_sequence_context_keys_from_paths(resolved_input_path)
  )
  resolved_produced_outputs = list(
    produced_output_keys
    if produced_output_keys is not None
    else _process_sequence_context_keys_from_paths(resolved_output_path)
  )
  normalized_parent = str(parent_step_key or "").strip().lower()
  resolved_hierarchy_level = (
    int(hierarchy_level)
    if hierarchy_level is not None
    else (2 if normalized_parent else 1)
  )
  return {
    "phase": phase,
    "step_order": int(step_order),
    "step_key": step_key,
    "handler_key": handler_key,
    "parent_step_key": normalized_parent,
    "step_kind": step_kind or "process",
    "hierarchy_level": resolved_hierarchy_level,
    "sequence_path": sequence_path or _process_sequence_path(
      phase=phase,
      step_key=step_key,
      parent_step_key=normalized_parent,
    ),
    "executor_function": executor_function or handler_key,
    "contract_name": contract_name,
    "context_contract_name": context_contract_name,
    "context_include_phase": context_include_phase,
    "required_context_keys": resolved_required_context_keys,
    "produced_output_keys": resolved_produced_outputs,
    "output_storage": copy.deepcopy(output_storage or []),
    "recompute_triggers": copy.deepcopy(recompute_triggers or []),
    "output_finality": output_finality or "stage_final_no_downstream_mutation",
    "required_lookup_tables": list(required_lookup_tables or []),
    "horizon_rule": horizon_rule,
    "timeout_seconds": timeout_seconds,
    "max_attempts": max_attempts,
    "required": bool(required),
    "enabled": bool(enabled),
    "fail_fast_code": fail_fast_code or f"{step_key}_sequence_violation",
    "python_role": python_role or "deterministic_step_executor",
    "python_timing": python_timing or phase,
    "python_action": python_action or notes or f"Execute {handler_key} for {step_key}.",
    "input_object_path": resolved_input_path,
    "output_object_path": resolved_output_path,
    "validation_subject_path": validation_subject_path or resolved_output_path,
    "object_controls": copy.deepcopy(object_controls or []),
    "notes": notes,
  }


def _process_context_row(
  step_key: str,
  context_key: str,
  *,
  context_domain: str = "",
  source_kind: str = "runtime_context",
  source_path: str = "",
  transform_kind: str = "copy",
  required: bool = True,
  immutable_input: bool = True,
  notes: str = "",
) -> Dict[str, Any]:
  return {
    "step_key": step_key,
    "context_key": context_key,
    "context_domain": context_domain,
    "source_kind": source_kind,
    "source_path": source_path or context_key,
    "transform_kind": transform_kind,
    "required": bool(required),
    "immutable_input": bool(immutable_input),
    "notes": notes,
  }


_DEFAULT_PROCESS_SEQUENCE_ROWS: List[Dict[str, Any]] = [
  _process_sequence_row(
    "runtime_validation",
    1,
    "post_intake_initialize_validation",
    "run_initialize_post_intake_validation",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _CASH_POLICY_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
      _PROCESS_CONTEXT_TABLE_NAME,
      "post_intake_headcount_policy_lookup",
      _PROCESS_SEQUENCE_TABLE_NAME,
    ],
    horizon_rule="validate_lookup_machine_before_post_intake",
    fail_fast_code="post_intake_sequence_initialize_validation_missing",
    python_role="production_runtime_gate",
    python_timing="after_planning_run_start_before_post_intake",
    python_action=(
      "Validate lookup tables, lookup functions, process sequence rows, GPT contracts, "
      "context contracts, cash policy, headcount policy, and mapping formulas before post-intake begins."
    ),
    input_object_path="sql.lookup_tables; post_intake_lookup_functions",
    output_object_path="planning_run_json.runtime_validation.post_intake_initialize_validation",
    validation_subject_path="post_intake_runtime_validation.initialize",
    notes="Production initialize gate. Post-intake must not start if deterministic lookup infrastructure is invalid.",
  ),
  _process_sequence_row(
    "pre_convergence",
    5,
    "realism_memo_review",
    "generate_realism_memo_payload_safe",
    contract_name="realism_memo",
    context_contract_name="realism_memo",
    context_include_phase="reviewer",
    required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME, _GPT_CONTEXT_TABLE_NAME, _MAPPING_TABLE_NAME],
    horizon_rule="pre_grid_issue_memo_from_table_contract",
    timeout_seconds=60,
    max_attempts=2,
    fail_fast_code="post_intake_sequence_realism_memo_contract_missing",
    required_context_keys=["operating_model_json", "financials_json", "model_input_json", "finmo_json"],
    notes="Optional pre-grid realism memo must use SQL contract/context tables when invoked.",
  ),
  _process_sequence_row(
    "pre_convergence",
    10,
    "baseline_model_input",
    "prepare_baseline_model_input",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    horizon_rule="q1_to_q20_forecast_state_excludes_stub_q0",
    fail_fast_code="post_intake_sequence_baseline_contract_missing",
    required_context_keys=[
      "business_facts",
      "operating_model_json",
      "target_market_json",
      "people_json",
      "financials_json",
      "financials_year1_json",
      "marketing_model_json",
    ],
    notes="Builds the initial model_input/finmo state. Stub Q0 remains historical; forecast horizon is Q1-Q20.",
  ),
  _process_sequence_row(
    "pre_convergence",
    20,
    "maintenance_capex_percent",
    "estimate_maintenance_capex_percent_with_gpt",
    contract_name="maintenance_capex_percent",
    required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME],
    horizon_rule="single_pre_convergence_decision",
    timeout_seconds=30,
    max_attempts=1,
    fail_fast_code="post_intake_sequence_maintenance_capex_contract_missing",
    required_context_keys=["business_facts", "operating_model_json", "financials_json", "financials_year1_json"],
    notes="GPT decides one maintenance capex percent; Python applies it deterministically.",
  ),
  _process_sequence_row(
    "pre_convergence",
    30,
    "r_and_d_applicability",
    "estimate_r_and_d_applicability_with_gpt",
    contract_name="r_and_d_applicability",
    required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME],
    horizon_rule="single_pre_convergence_toggle",
    timeout_seconds=20,
    max_attempts=1,
    fail_fast_code="post_intake_sequence_rd_contract_missing",
    required_context_keys=["business_facts", "operating_model_json", "financials_json", "financials_year1_json", "model_input_json"],
    notes="GPT selects R&D on/off before forecast generation; Python enforces the toggle.",
  ),
  _process_sequence_row(
    "pre_convergence",
    40,
    "balance_sheet_contextual_seed",
    "estimate_balance_sheet_contextual_seed_with_gpt",
    contract_name="balance_sheet_contextual_seed",
    context_contract_name="balance_sheet_contextual_seed",
    context_include_phase="pre_convergence",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    horizon_rule="single_pre_convergence_balance_sheet_driver_seed",
    timeout_seconds=30,
    max_attempts=1,
    fail_fast_code="post_intake_sequence_balance_sheet_seed_contract_missing",
    python_role="contract_request_and_validation",
    python_timing="pre_convergence_before_stage_ramp",
    python_action=(
      "Call GPT once for business-context-specific balance-sheet driver seed values, "
      "then Python applies those values to mapped model_input rows. Mapping defaults are guardrails only."
    ),
    input_object_path="business_facts, operating_model_json, financials_json, model_input_json, finmo_json, post_intak_mapping_lookup",
    output_object_path="balance_sheet_contextual_seed; model_input_json.sections.balance_sheet",
    validation_subject_path="balance_sheet_contextual_seed.balance_sheet_seed_grid",
    notes="Omitted balance-sheet drivers are seeded from business context/type through a SQL-backed contract, not universal hardcoded defaults.",
  ),
  _process_sequence_row(
    "pre_convergence",
    50,
    "planning_mode_determination",
    "determine_planning_mode",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _PROCESS_CONTEXT_TABLE_NAME,
    ],
    required_context_keys=[
      "business_facts",
      "operating_model_json",
      "financials_json",
      "financials_year1_json",
      "model_input_json",
      "finmo_json",
      "planning_context_summary_json",
    ],
    horizon_rule="single_pre_convergence_planning_mode_decision",
    fail_fast_code="post_intake_sequence_planning_mode_missing",
    output_storage=[
      {
        "output_key": "planning_mode_decision",
        "storage_kind": "planning_run_json",
        "storage_path": "planning_run_json.planning_mode",
        "final_for_stage": True,
      },
    ],
    notes="Determine normalize/rebalance/turnaround mode from explicit intake and derived forecast context before stage-ramp selection.",
  ),
  _process_sequence_row(
    "pre_convergence",
    55,
    "stage_ramp_contract",
    "estimate_stage_ramp_contract_with_gpt",
    contract_name="stage_ramp_contract",
    context_contract_name="stage_ramp_contract",
    context_include_phase="pre_convergence",
    required_lookup_tables=[
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    horizon_rule="q1_to_q20_exactly_once",
    timeout_seconds=90,
    max_attempts=1,
    fail_fast_code="post_intake_sequence_stage_ramp_contract_missing",
    python_role="contract_request_and_validation",
    python_timing="pre_convergence_before_initial_grid",
    python_action=(
      "Build table-filtered context, call GPT for the stage_ramp_contract, "
      "then validate the 20-quarter stage/ramp contract. Payroll is a separate contract."
    ),
    input_object_path="business_facts, operating_model_json, people_json, financials_json, model_input_json, finmo_json, r_and_d_applicability",
    output_object_path="stage_ramp_contract",
    validation_subject_path="stage_ramp_contract",
    notes="GPT supplies only the 20-quarter revenue/utilization/cost/profitability ramp before convergence. Payroll is handled by payroll_headcount_schedule.",
  ),
  _process_sequence_row(
    "initial_grid",
    60,
    "payroll_headcount_schedule",
    "estimate_payroll_headcount_schedule_with_gpt",
    contract_name="payroll_headcount_schedule",
    context_contract_name="payroll_headcount_schedule",
    context_include_phase="pre_convergence",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
      "post_intake_headcount_policy_lookup",
      _PROCESS_SEQUENCE_TABLE_NAME,
      _PROCESS_CONTEXT_TABLE_NAME,
    ],
    required_context_keys=[
      "business_facts",
      "business_type",
      "business_naics",
      "operating_model_json",
      "people_json",
      "financials_json",
      "financials_year1_json",
      "model_input_json",
      "finmo_json",
      "stage_ramp_contract",
      "oews_title_catalog",
      "headcount_policy",
      "productivity_assumptions",
      "payroll_economic_guardrails",
      "revenue_drivers",
    ],
    output_storage=[
      {
        "output_key": "payroll_headcount",
        "storage_kind": "draft_domain_column",
        "storage_path": "intake_consult_drafts.payroll_headcount",
        "final_for_stage": True,
      },
      {
        "output_key": "model_input.expenses.Payroll",
        "storage_kind": "domain_json_path",
        "storage_path": "model_input_json.sections.expenses[Payroll]",
        "final_for_stage": True,
      },
      {
        "output_key": "model_input.revenue.Capacity",
        "storage_kind": "domain_json_path",
        "storage_path": "model_input_json.sections.revenue[Capacity]",
        "final_for_stage": True,
      },
    ],
    recompute_triggers=[
      {
        "downstream_step_key": "quarter_grid_generation",
        "trigger": "payroll_supported_capacity_required_change",
        "recompute_from_step_key": "payroll_headcount_schedule",
      }
    ],
    horizon_rule="q1_to_q20_at_least_once",
    timeout_seconds=180,
    max_attempts=3,
    fail_fast_code="post_intake_sequence_headcount_contract_missing",
    python_role="contract_request_and_schedule_builder",
    python_timing="after_stage_ramp_before_quarter_grid_and_convergence",
    python_action=(
      "Call GPT for the independent payroll_headcount_schedule contract, validate it through "
      "post_intake_headcount_policy_lookup, calculate and persist the Payroll model-input schedule, "
      "and derive revenue Capacity from payroll-supported FTE before the quarter grid runs."
    ),
    input_object_path="business_facts, operating_model_json, people_json, financials_json, model_input_json, finmo_json, stage_ramp_contract",
    output_object_path="intake_consult_drafts.payroll_headcount; model_input_json.sections.expenses[Payroll]; model_input_json.sections.revenue[Capacity]",
    validation_subject_path="payroll_headcount_schedule.payroll_headcount_grid",
    object_controls=[
      {
        "object_name": "payroll_headcount",
        "owner": "gpt",
        "allowed_actions": ["build", "rebuild"],
        "allowed_triggers": ["initial_build", "payroll_revenue_economic_feasibility_failed", "payroll_stage_profitability_feasibility_failed"],
        "writes": ["intake_consult_drafts.payroll_headcount"],
      },
      {
        "object_name": "model_input.expenses.Payroll",
        "owner": "python",
        "allowed_actions": ["derive", "build", "rebuild"],
        "allowed_triggers": ["initial_build", "payroll_headcount_changed", "payroll_revenue_economic_feasibility_failed"],
        "writes": ["model_input_json.sections.expenses[Payroll]"],
      },
      {
        "object_name": "model_input.revenue.Capacity",
        "owner": "python",
        "allowed_actions": ["derive", "build", "rebuild"],
        "allowed_triggers": ["initial_build", "payroll_headcount_changed", "payroll_revenue_economic_feasibility_failed"],
        "writes": ["model_input_json.sections.revenue[Capacity]"],
        "source_object": "payroll_headcount",
      },
      {
        "object_name": "finmo_json",
        "owner": "python",
        "allowed_actions": ["rebuild"],
        "allowed_triggers": ["model_input_changed"],
        "writes": ["finmo_json.quarter_rows"],
      },
    ],
    notes="Payroll is not part of stage_ramp_contract. GPT chooses OEWS titles, productivity, and FTE. Python derives payroll-supported Capacity from that FTE before the quarter grid, and revenue is constrained by that capacity.",
  ),
  _process_sequence_row(
    "initial_grid",
    65,
    "payroll_feasibility_repair",
    "retry_payroll_headcount_schedule_from_feasibility_failure",
    parent_step_key="payroll_headcount_schedule",
    step_kind="subprocess",
    contract_name="payroll_headcount_schedule",
    context_contract_name="payroll_headcount_schedule",
    context_include_phase="pre_convergence",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
      "post_intake_headcount_policy_lookup",
      _PROCESS_SEQUENCE_TABLE_NAME,
      _PROCESS_CONTEXT_TABLE_NAME,
    ],
    required_context_keys=[
      "previous_contract_failure",
      "payroll_feasibility_mapping",
      "model_input_json",
      "finmo_json",
      "payroll_headcount",
      "headcount_policy",
      "payroll_economic_guardrails",
      "revenue_drivers",
    ],
    output_storage=[
      {
        "output_key": "payroll_headcount",
        "storage_kind": "draft_domain_column",
        "storage_path": "intake_consult_drafts.payroll_headcount",
        "final_for_stage": True,
        "recompute_of_step_key": "payroll_headcount_schedule",
      },
      {
        "output_key": "model_input.expenses.Payroll",
        "storage_kind": "domain_json_path",
        "storage_path": "model_input_json.sections.expenses[Payroll]",
        "final_for_stage": True,
        "recompute_of_step_key": "payroll_headcount_schedule",
      },
      {
        "output_key": "model_input.revenue.Capacity",
        "storage_kind": "domain_json_path",
        "storage_path": "model_input_json.sections.revenue[Capacity]",
        "final_for_stage": True,
        "recompute_of_step_key": "payroll_headcount_schedule",
      },
    ],
    recompute_triggers=[
      {
        "downstream_step_key": "quarter_grid_generation",
        "trigger": "payroll_revenue_economic_feasibility_failed",
        "recompute_from_step_key": "payroll_feasibility_repair",
      }
    ],
    horizon_rule="q1_to_q20_at_least_once",
    timeout_seconds=180,
    max_attempts=3,
    fail_fast_code="post_intake_sequence_payroll_feasibility_repair_missing",
    python_role="table_driven_retry_gateway",
    python_timing="after_payroll_or_quarter_grid_feasibility_failure_before_retry",
    python_action=(
      "Read repair_direction_rules_json from post_intak_mapping_lookup and retry the payroll_headcount_schedule "
      "contract with the exact SQL-backed lever directions instead of inline causal guesses."
    ),
    input_object_path="previous_contract_failure; payroll_feasibility_mapping; model_input_json; finmo_json",
    output_object_path="intake_consult_drafts.payroll_headcount; model_input_json.sections.expenses[Payroll]; model_input_json.sections.revenue[Capacity]",
    validation_subject_path="payroll_revenue_feasibility_violations",
    object_controls=[
      {
        "object_name": "payroll_headcount",
        "owner": "gpt",
        "allowed_actions": ["rebuild"],
        "allowed_triggers": ["payroll_revenue_economic_feasibility_failed", "payroll_stage_profitability_feasibility_failed"],
        "requires_context": ["payroll_feasibility_mapping"],
      },
      {
        "object_name": "model_input.expenses.Payroll",
        "owner": "python",
        "allowed_actions": ["derive", "rebuild"],
        "allowed_triggers": ["payroll_headcount_changed", "payroll_revenue_economic_feasibility_failed"],
      },
      {
        "object_name": "model_input.revenue.Capacity",
        "owner": "python",
        "allowed_actions": ["derive", "rebuild"],
        "allowed_triggers": ["payroll_headcount_changed", "payroll_revenue_economic_feasibility_failed"],
        "source_object": "payroll_headcount",
      },
      {
        "object_name": "finmo_json",
        "owner": "python",
        "allowed_actions": ["rebuild"],
        "allowed_triggers": ["model_input_changed"],
      },
    ],
    notes="Payroll feasibility repair is sequence-governed. GPT must read mapping-table movement rules for payroll/revenue violations.",
  ),
  _process_sequence_row(
    "initial_grid",
    70,
    "quarter_grid_generation",
    "generate_live_quarter_grid_plan",
    contract_name="quarter_grid_probe",
    context_contract_name="quarter_grid_probe",
    context_include_phase="initial_grid",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
      _PROCESS_CONTEXT_TABLE_NAME,
    ],
    required_context_keys=[
      "business_facts",
      "business_type",
      "operating_model_json",
      "target_market_json",
      "people_json",
      "financials_json",
      "financials_year1_json",
      "fulfillment_json",
      "marketing_model_json",
      "model_input_json",
      "finmo_json",
      "stage_ramp_contract",
      "payroll_headcount",
      "revenue_drivers",
      "capacity_outputs",
    ],
    output_storage=[
      {
        "output_key": "quarter_grid_plan",
        "storage_kind": "planning_run_json",
        "storage_path": "planning_run_json.grid_json",
        "final_for_stage": True,
      },
      {
        "output_key": "model_input_json",
        "storage_kind": "draft_domain_column",
        "storage_path": "intake_consult_drafts.model_input_json",
        "final_for_stage": True,
      },
      {
        "output_key": "finmo_json",
        "storage_kind": "draft_domain_column",
        "storage_path": "intake_consult_drafts.finmo_json",
        "final_for_stage": True,
      },
    ],
    horizon_rule="q1_to_q20_model_input_state",
    fail_fast_code="post_intake_sequence_quarter_grid_contract_missing",
    object_controls=[
      {
        "object_name": "model_input.revenue.Capacity",
        "owner": "python",
        "allowed_actions": ["read_only", "preserve"],
        "allowed_triggers": ["payroll_supported_capacity_applied"],
        "forbidden_actions": ["gpt_edit", "overwrite"],
        "reason": "Capacity is payroll-supported before quarter-grid. Quarter-grid may read it but must not own it.",
      },
      {
        "object_name": "model_input.revenue.Unit Price",
        "owner": "gpt",
        "allowed_actions": ["build", "rebuild"],
        "allowed_triggers": ["quarter_grid_generation", "payroll_supported_capacity_applied"],
      },
      {
        "object_name": "model_input.revenue.Utilization",
        "owner": "gpt",
        "allowed_actions": ["build", "rebuild"],
        "allowed_triggers": ["quarter_grid_generation", "payroll_supported_capacity_applied"],
      },
      {
        "object_name": "finmo_json",
        "owner": "python",
        "allowed_actions": ["rebuild"],
        "allowed_triggers": ["model_input_changed"],
      },
    ],
    notes="Initial 20-quarter model_input grid uses quarter_grid_probe after payroll-supported Capacity is applied; quarter-grid may not own payroll-supported Capacity rows.",
  ),
  _process_sequence_row(
    "convergence",
    80,
    "issue_detection",
    "detect_post_intake_issues",
    required_lookup_tables=[_MAPPING_TABLE_NAME, _GPT_CONTRACT_TABLE_NAME],
    required_context_keys=["stage_ramp_contract", "model_input_json", "finmo_json", "payroll_headcount", "revenue_drivers"],
    horizon_rule="scan_all_q1_to_q20",
    fail_fast_code="post_intake_sequence_issue_detection_mapping_missing",
    notes="Issue detection may only produce issues with direct mapping-table repair paths or hard gates.",
  ),
  _process_sequence_row(
    "convergence",
    90,
    "unified_convergence_decision",
    "run_unified_convergence_cycle",
    contract_name="unified_convergence_decision",
    context_contract_name="unified_convergence_decision",
    context_include_phase="planner",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    horizon_rule="q1_to_q20_model_input_repair_cells",
    timeout_seconds=240,
    max_attempts=10,
    fail_fast_code="post_intake_sequence_unified_convergence_contract_missing",
    required_context_keys=[
      "issue_ledger",
      "repair_scope",
      "numeric_guidance_packet",
      "writable_lever_catalog",
      "stage_ramp_contract",
      "model_input_json",
      "finmo_json",
      "payroll_headcount",
    ],
    notes="Convergence GPT sees table-approved planner context and fills only the full-horizon model-input repair contract.",
  ),
  _process_sequence_row(
    "convergence",
    90,
    "unified_convergence_retry",
    "run_unified_convergence_contract_retry",
    contract_name="unified_convergence_decision",
    context_contract_name="unified_convergence_decision",
    context_include_phase="planner_retry",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    horizon_rule="q1_to_q20_model_input_repair_cells",
    timeout_seconds=180,
    max_attempts=1,
    fail_fast_code="post_intake_sequence_unified_convergence_retry_contract_missing",
    required_context_keys=[
      "previous_contract_failure",
      "issue_ledger",
      "repair_scope",
      "numeric_guidance_packet",
      "writable_lever_catalog",
      "model_input_json",
      "finmo_json",
    ],
    notes="Contract repair uses a compact planner_retry context slice, not original-plus-retry legacy payloads.",
  ),
  _process_sequence_row(
    "cash_pass",
    100,
    "cash_minimum_debt_schedule",
    "apply_cash_pass_minimum_debt_schedule",
    required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME],
    required_context_keys=["financials_json", "model_input_json", "finmo_json", "cash_policy", "debt_schedule_policy"],
    horizon_rule="q1_to_q20_debt_schedule",
    fail_fast_code="post_intake_sequence_cash_debt_schedule_policy_missing",
    notes="Debt schedule semantics come from post_intake_debt_schedule, cash policy lookup, and mapping-table financing levers.",
  ),
  _process_sequence_row(
    "cash_pass",
    110,
    "cash_strategy_review",
    "run_cash_strategy_review",
    contract_name="cash_strategy_review",
    context_contract_name="cash_strategy_review",
    context_include_phase="cash_pass",
    required_lookup_tables=[
      _CASH_POLICY_TABLE_NAME,
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    horizon_rule="cash_gap_rows_subset_validation_all_q1_to_q20",
    timeout_seconds=90,
    max_attempts=1,
    fail_fast_code="post_intake_sequence_cash_strategy_contract_missing",
    required_context_keys=[
      "financials_json",
      "model_input_json",
      "finmo_json",
      "cash_policy",
      "debt_schedule",
    ],
    notes="Parent cash review marker starts the sequenced cash pass; nested context-build step produces cash_envelope and liquidity_violation_grid before the GPT review step consumes them.",
  ),
  _process_sequence_row(
    "cash_pass",
    120,
    "cash_pass_validation",
    "validate_cash_pass",
    required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME],
    required_context_keys=["model_input_json", "finmo_json", "cash_policy", "cash_strategy_second_pass_result", "debt_schedule"],
    horizon_rule="validate_all_q1_to_q20",
    fail_fast_code="post_intake_sequence_cash_validation_policy_missing",
    notes="Hard cash viability gate and cash policy validation after cash actions are applied.",
  ),
  _process_sequence_row(
    "final_validation",
    130,
    "final_hard_gates",
    "validate_final_post_intake_state",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _CASH_POLICY_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    required_context_keys=[
      "stage_ramp_contract",
      "model_input_json",
      "finmo_json",
      "payroll_headcount",
      "debt_schedule",
      "financials_json",
      "cash_strategy_second_pass_result",
    ],
    horizon_rule="validate_all_q1_to_q20",
    fail_fast_code="post_intake_sequence_final_validation_missing",
    notes="Final table-backed hard gates before a run can complete.",
  ),
  _process_sequence_row(
    "runtime_validation",
    140,
    "post_intake_finalize_validation",
    "run_finalize_post_intake_validation",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _CASH_POLICY_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
      _PROCESS_CONTEXT_TABLE_NAME,
      "post_intake_headcount_policy_lookup",
      _PROCESS_SEQUENCE_TABLE_NAME,
    ],
    horizon_rule="validate_lookup_machine_after_post_intake",
    fail_fast_code="post_intake_sequence_finalize_validation_missing",
    python_role="production_runtime_gate",
    python_timing="after_cash_pass_before_completion",
    python_action=(
      "Validate final model_input_json, finmo_json, payroll schedule, debt schedule, cash phase trace, "
      "global invariants, and mapping formula application before a run can be marked completed."
    ),
    input_object_path="final_model_input_json; final_finmo_json; payroll_headcount; debt_schedule; cash_strategy_second_pass_result",
    output_object_path="planning_run_json.runtime_validation.post_intake_finalize_validation",
    validation_subject_path="post_intake_runtime_validation.finalize",
    notes="Production finalize gate. Completion is blocked unless final outputs obey the table-backed contracts.",
  ),
]


_DEFAULT_PROCESS_SEQUENCE_ROWS.extend(
  [
    _process_sequence_row(
      "pre_convergence",
      10,
      "shared_context_build",
      "build_shared_context",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["business_facts", "operating_model_json", "target_market_json", "people_json", "financials_json"],
      produced_output_keys=["shared_context"],
      output_storage=[{"output_key": "shared_context", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="build_post_intake_shared_context_from_intake_inputs",
      fail_fast_code="post_intake_sequence_shared_context_failed",
      python_action="Build the shared context from the completed intake row before downstream derived facts are assembled.",
    ),
    _process_sequence_row(
      "pre_convergence",
      11,
      "ops_context_load",
      "load_operating_model_context",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["operating_model_json", "business_facts"],
      produced_output_keys=["ops_context"],
      output_storage=[{"output_key": "ops_context", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="load_intake_operating_model_context",
      fail_fast_code="post_intake_sequence_ops_context_missing",
      python_action="Load the operating model intake facts into the process context before baseline model construction.",
    ),
    _process_sequence_row(
      "pre_convergence",
      12,
      "market_context_load",
      "load_target_market_context",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["target_market_json", "business_facts"],
      produced_output_keys=["market_context"],
      output_storage=[{"output_key": "market_context", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="load_intake_market_context",
      fail_fast_code="post_intake_sequence_market_context_missing",
      python_action="Load target market intake facts into the process context before baseline model construction.",
    ),
    _process_sequence_row(
      "pre_convergence",
      13,
      "people_context_load",
      "load_people_context",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["people_json", "business_facts"],
      produced_output_keys=["people_context"],
      output_storage=[{"output_key": "people_context", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="load_intake_people_context",
      fail_fast_code="post_intake_sequence_people_context_missing",
      python_action="Load people/staffing intake facts into the process context before payroll and baseline model construction.",
    ),
    _process_sequence_row(
      "pre_convergence",
      14,
      "financials_context_load",
      "load_financials_context",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["financials_json", "business_facts"],
      produced_output_keys=["financials_context"],
      output_storage=[{"output_key": "financials_context", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="load_intake_financials_context",
      fail_fast_code="post_intake_sequence_financials_context_missing",
      python_action="Load financial intake facts into the process context before year-one assembly and baseline model construction.",
    ),
    _process_sequence_row(
      "pre_convergence",
      15,
      "financials_year1_assembly",
      "assemble_financials_year1",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["ops_context", "market_context", "people_context", "financials_context", "financials_year1_json"],
      produced_output_keys=["financials_year1_json", "financials_year1_context"],
      output_storage=[{"output_key": "financials_year1_context", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="derive_authoritative_year1_financial_context",
      fail_fast_code="post_intake_sequence_financials_year1_assembly_failed",
      python_action="Assemble authoritative year-one financial context from intake and shared context.",
    ),
    _process_sequence_row(
      "pre_convergence",
      16,
      "marketing_context_build",
      "compute_marketing_model_json",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["ops_context", "market_context", "people_context", "financials_year1_context", "business_facts"],
      produced_output_keys=["marketing_model_json", "marketing_context"],
      output_storage=[{"output_key": "marketing_context", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="derive_marketing_context_before_baseline_finmo",
      fail_fast_code="post_intake_sequence_marketing_context_failed",
      python_action="Compute or preserve marketing model context before baseline FINMO synchronization.",
    ),
    _process_sequence_row(
      "pre_convergence",
      17,
      "baseline_finmo_sync",
      "sync_planning_state_to_finmo",
      parent_step_key="baseline_model_input",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=[
        "business_facts",
        "operating_model_json",
        "people_json",
        "financials_json",
        "financials_year1_json",
        "marketing_model_json",
      ],
      produced_output_keys=["model_input_json", "finmo_json"],
      output_storage=[
        {"output_key": "model_input_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.model_input_json", "final_for_stage": True},
        {"output_key": "finmo_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.finmo_json", "final_for_stage": True},
      ],
      horizon_rule="q1_to_q20_forecast_state_excludes_stub_q0",
      fail_fast_code="post_intake_sequence_baseline_finmo_sync_failed",
      python_action="Synchronize post-intake intake facts into baseline model_input_json and finmo_json.",
    ),
    _process_sequence_row(
      "pre_convergence",
      35,
      "r_and_d_policy_application",
      "apply_r_and_d_applicability_policy_to_model_input",
      parent_step_key="r_and_d_applicability",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["r_and_d_applicability", "model_input_json", "finmo_json"],
      produced_output_keys=["model_input_json", "finmo_json"],
      output_storage=[
        {"output_key": "model_input_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.model_input_json", "final_for_stage": True},
        {"output_key": "finmo_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.finmo_json", "final_for_stage": True},
      ],
      horizon_rule="apply_single_pre_convergence_r_and_d_toggle",
      fail_fast_code="post_intake_sequence_rd_policy_application_failed",
      python_action="Apply the R&D applicability decision to model_input_json and rebuild FINMO.",
    ),
    _process_sequence_row(
      "pre_convergence",
      45,
      "balance_sheet_seed_application",
      "apply_balance_sheet_contextual_seed_to_model_input",
      parent_step_key="balance_sheet_contextual_seed",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["balance_sheet_contextual_seed", "model_input_json", "finmo_json"],
      produced_output_keys=["model_input_json", "finmo_json"],
      output_storage=[
        {"output_key": "model_input_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.model_input_json", "final_for_stage": True},
        {"output_key": "finmo_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.finmo_json", "final_for_stage": True},
      ],
      horizon_rule="apply_balance_sheet_contextual_seed_to_model_input",
      fail_fast_code="post_intake_sequence_balance_sheet_seed_application_failed",
      python_action="Apply the validated balance-sheet contextual seed to mapped model-input rows and rebuild FINMO.",
    ),
    _process_sequence_row(
      "initial_grid",
      61,
      "payroll_context_build",
      "build_payroll_headcount_context",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      context_contract_name="payroll_headcount_schedule",
      context_include_phase="pre_convergence",
      required_lookup_tables=[_GPT_CONTEXT_TABLE_NAME, "post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=[
        "business_facts",
        "business_type",
        "business_naics",
        "operating_model_json",
        "people_json",
        "financials_json",
        "financials_year1_json",
        "model_input_json",
        "finmo_json",
        "stage_ramp_contract",
      ],
      produced_output_keys=["payroll_context_payload"],
      output_storage=[{"output_key": "payroll_context_payload", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="payroll_context_inputs_only_no_mutation",
      fail_fast_code="post_intake_sequence_payroll_context_missing",
      python_action="Build the payroll-specific process context from immutable intake inputs and current derived forecast facts.",
      notes="Payroll context is an input package, not mutable state.",
    ),
    _process_sequence_row(
      "initial_grid",
      62,
      "payroll_oews_title_catalog",
      "load_payroll_oews_title_catalog",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      required_lookup_tables=["post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["business_naics", "business_type", "people_json"],
      produced_output_keys=["oews_title_catalog", "headcount_policy", "productivity_assumptions"],
      output_storage=[{"output_key": "oews_title_catalog", "storage_kind": "sql_lookup_result", "storage_path": "oews_state_wages", "final_for_stage": True}],
      horizon_rule="naics_filtered_oews_titles_before_gpt_selection",
      fail_fast_code="post_intake_sequence_payroll_oews_catalog_missing",
      python_action="Load the NAICS/OEWS title catalog, wage policy, and productivity assumptions before GPT selects titles and FTE.",
      notes="GPT may choose only from this table-backed title context.",
    ),
    _process_sequence_row(
      "initial_grid",
      63,
      "payroll_gpt_contract_request",
      "estimate_payroll_headcount_schedule_with_gpt",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      contract_name="payroll_headcount_schedule",
      context_contract_name="payroll_headcount_schedule",
      context_include_phase="pre_convergence",
      required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME, _GPT_CONTEXT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=[
        "payroll_context_payload",
        "oews_title_catalog",
        "headcount_policy",
        "productivity_assumptions",
        "payroll_economic_guardrails",
        "revenue_drivers",
      ],
      produced_output_keys=["payroll_headcount_contract"],
      output_storage=[{"output_key": "payroll_headcount_contract", "storage_kind": "gpt_contract_payload", "final_for_stage": True}],
      horizon_rule="q1_to_q20_oews_title_fte_contract",
      timeout_seconds=180,
      max_attempts=3,
      fail_fast_code="post_intake_sequence_payroll_gpt_contract_missing",
      python_action="Request and receive only the table-defined payroll_headcount_schedule contract.",
    ),
    _process_sequence_row(
      "initial_grid",
      64,
      "payroll_contract_validation",
      "assert_payroll_headcount_payload_ready",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME, "post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["payroll_headcount_contract", "model_input_json", "headcount_policy", "oews_title_catalog"],
      produced_output_keys=["payroll_headcount"],
      output_storage=[{"output_key": "payroll_headcount", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.payroll_headcount", "final_for_stage": True}],
      horizon_rule="q1_to_q20_contract_and_oews_validation",
      fail_fast_code="post_intake_sequence_payroll_contract_validation_failed",
      python_action="Validate the payroll contract mechanically before any model-input writes occur.",
    ),
    _process_sequence_row(
      "initial_grid",
      66,
      "payroll_capacity_derivation",
      "apply_payroll_supported_capacity_to_model_input",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_SEQUENCE_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["payroll_headcount", "model_input_json", "productivity_assumptions", "revenue_drivers"],
      produced_output_keys=["model_input.revenue.Capacity", "capacity_outputs"],
      output_storage=[{"output_key": "model_input.revenue.Capacity", "storage_kind": "domain_json_path", "storage_path": "model_input_json.sections.revenue[Capacity]", "final_for_stage": True}],
      horizon_rule="payroll_supported_capacity_derivation_q1_to_q20",
      fail_fast_code="post_intake_sequence_payroll_capacity_derivation_failed",
      python_action="Derive payroll-supported Capacity from final payroll headcount; downstream steps may read but not overwrite it.",
    ),
    _process_sequence_row(
      "initial_grid",
      67,
      "payroll_model_input_application",
      "apply_payroll_headcount_payload_to_model_input",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_SEQUENCE_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["payroll_headcount", "model_input_json", "capacity_outputs"],
      produced_output_keys=["model_input.expenses.Payroll", "model_input_json"],
      output_storage=[{"output_key": "model_input.expenses.Payroll", "storage_kind": "domain_json_path", "storage_path": "model_input_json.sections.expenses[Payroll]", "final_for_stage": True}],
      horizon_rule="payroll_expense_derivation_q1_to_q20",
      fail_fast_code="post_intake_sequence_payroll_model_input_application_failed",
      python_action="Write payroll expense rows from the validated schedule after capacity has been derived.",
    ),
    _process_sequence_row(
      "initial_grid",
      68,
      "payroll_finmo_rebuild_validation",
      "assert_finmo_payroll_matches_headcount_schedule",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["payroll_headcount", "model_input_json", "finmo_json"],
      produced_output_keys=["finmo_json"],
      output_storage=[{"output_key": "finmo_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.finmo_json", "final_for_stage": True}],
      horizon_rule="payroll_finmo_reconciliation_q1_to_q20",
      fail_fast_code="post_intake_sequence_payroll_finmo_validation_failed",
      python_action="Rebuild FINMO from payroll-updated model_input_json and validate payroll reconciliation.",
    ),
    _process_sequence_row(
      "initial_grid",
      69,
      "pre_quarter_grid_global_validation",
      "assert_post_intake_global_invariants",
      parent_step_key="payroll_headcount_schedule",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, "post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["stage_ramp_contract", "model_input_json", "finmo_json", "payroll_headcount"],
      produced_output_keys=["pre_quarter_grid_global_validation"],
      output_storage=[{"output_key": "pre_quarter_grid_global_validation", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="pre_quarter_grid_global_invariants_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_pre_quarter_grid_global_validation_failed",
      python_action="Validate payroll-ready model_input_json and FINMO through the sequence controller before quarter-grid generation.",
    ),
    _process_sequence_row(
      "initial_grid",
      71,
      "quarter_grid_context_build",
      "build_quarter_grid_context",
      parent_step_key="quarter_grid_generation",
      step_kind="subprocess",
      context_contract_name="quarter_grid_probe",
      context_include_phase="initial_grid",
      required_lookup_tables=[_GPT_CONTEXT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=[
        "business_facts",
        "operating_model_json",
        "target_market_json",
        "people_json",
        "financials_json",
        "financials_year1_json",
        "fulfillment_json",
        "marketing_model_json",
        "model_input_json",
        "finmo_json",
        "stage_ramp_contract",
        "payroll_headcount",
        "capacity_outputs",
      ],
      produced_output_keys=["quarter_grid_context_payload"],
      output_storage=[{"output_key": "quarter_grid_context_payload", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="quarter_grid_context_inputs_only_no_mutation",
      fail_fast_code="post_intake_sequence_quarter_grid_context_missing",
      python_action="Build the quarter-grid process context from final payroll/capacity outputs and intake facts.",
    ),
    _process_sequence_row(
      "initial_grid",
      72,
      "quarter_grid_gpt_plan",
      "generate_live_quarter_grid_plan",
      parent_step_key="quarter_grid_generation",
      step_kind="subprocess",
      contract_name="quarter_grid_probe",
      context_contract_name="quarter_grid_probe",
      context_include_phase="initial_grid",
      required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME, _GPT_CONTEXT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["quarter_grid_context_payload", "stage_ramp_contract", "payroll_headcount", "model_input_json", "finmo_json"],
      produced_output_keys=["quarter_grid_plan"],
      output_storage=[{"output_key": "quarter_grid_plan", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.grid_json", "final_for_stage": True}],
      horizon_rule="q1_to_q20_model_input_state",
      fail_fast_code="post_intake_sequence_quarter_grid_plan_failed",
      python_action="Generate the live quarter-grid plan from final upstream context.",
    ),
    _process_sequence_row(
      "initial_grid",
      73,
      "quarter_grid_validation",
      "validate_live_quarter_grid_plan",
      parent_step_key="quarter_grid_generation",
      step_kind="subprocess",
      required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["quarter_grid_plan", "stage_ramp_contract", "model_input_json"],
      produced_output_keys=["validated_quarter_grid_plan"],
      output_storage=[{"output_key": "validated_quarter_grid_plan", "storage_kind": "in_memory_stage_context", "final_for_stage": True}],
      horizon_rule="q1_to_q20_quarter_grid_contract_validation",
      fail_fast_code="post_intake_sequence_quarter_grid_validation_failed",
      python_action="Validate quarter-grid rows before model-input application.",
    ),
    _process_sequence_row(
      "initial_grid",
      74,
      "quarter_grid_apply_model_input",
      "apply_live_quarter_grid_plan",
      parent_step_key="quarter_grid_generation",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_SEQUENCE_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["validated_quarter_grid_plan", "model_input_json", "payroll_headcount", "capacity_outputs"],
      produced_output_keys=["model_input_json", "finmo_json"],
      output_storage=[
        {"output_key": "model_input_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.model_input_json", "final_for_stage": True},
        {"output_key": "finmo_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.finmo_json", "final_for_stage": True},
      ],
      recompute_triggers=[
        {
          "downstream_step_key": "issue_detection",
          "trigger": "quarter_grid_requires_capacity_change",
          "recompute_from_step_key": "payroll_headcount_schedule",
        }
      ],
      horizon_rule="q1_to_q20_model_input_application",
      fail_fast_code="post_intake_sequence_quarter_grid_application_failed",
      python_action="Apply the validated quarter-grid plan while preserving final upstream capacity/payroll outputs.",
    ),
    _process_sequence_row(
      "initial_grid",
      75,
      "quarter_grid_reapply_locked_payroll",
      "reapply_payroll_authority_after_quarter_grid",
      parent_step_key="quarter_grid_generation",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_SEQUENCE_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["payroll_headcount", "model_input_json", "finmo_json"],
      produced_output_keys=["model_input.expenses.Payroll", "model_input.revenue.Capacity", "finmo_json"],
      output_storage=[
        {
          "output_key": "model_input.expenses.Payroll",
          "storage_kind": "domain_json_path",
          "storage_path": "model_input_json.sections.expenses[Payroll]",
          "final_for_stage": True,
          "preserves_upstream_output": True,
        },
        {
          "output_key": "model_input.revenue.Capacity",
          "storage_kind": "domain_json_path",
          "storage_path": "model_input_json.sections.revenue[Capacity]",
          "final_for_stage": True,
          "preserves_upstream_output": True,
        },
      ],
      horizon_rule="preserve_upstream_payroll_and_capacity_outputs",
      fail_fast_code="post_intake_sequence_quarter_grid_payroll_lock_failed",
      python_action="Reapply payroll-owned outputs after grid application so quarter-grid cannot mutate them.",
    ),
    _process_sequence_row(
      "initial_grid",
      76,
      "quarter_grid_global_validation",
      "assert_post_intake_global_invariants",
      parent_step_key="quarter_grid_generation",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, "post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["stage_ramp_contract", "model_input_json", "finmo_json", "payroll_headcount"],
      produced_output_keys=["quarter_grid_global_validation"],
      output_storage=[{"output_key": "quarter_grid_global_validation", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="quarter_grid_global_invariants_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_quarter_grid_global_validation_failed",
      python_action="Validate quarter-grid outputs after payroll authority is reapplied, with no direct validator bypass.",
    ),
    _process_sequence_row(
      "convergence",
      81,
      "issue_repair_scope_build",
      "build_post_intake_issue_repair_scope",
      parent_step_key="issue_detection",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["model_input_json", "finmo_json", "stage_ramp_contract", "payroll_headcount"],
      produced_output_keys=["issue_ledger", "repair_scope"],
      output_storage=[{"output_key": "issue_ledger", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.controller_resolution_state.detected_issues", "final_for_stage": True}],
      horizon_rule="scan_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_issue_repair_scope_failed",
      python_action="Detect issues and bind each issue to table-approved repair levers before GPT planning.",
    ),
    _process_sequence_row(
      "convergence",
      91,
      "unified_convergence_context_build",
      "build_unified_convergence_context",
      parent_step_key="unified_convergence_decision",
      step_kind="subprocess",
      context_contract_name="unified_convergence_decision",
      context_include_phase="planner",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _GPT_CONTEXT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["issue_ledger", "repair_scope", "model_input_json", "finmo_json", "payroll_headcount", "stage_ramp_contract"],
      produced_output_keys=["unified_convergence_context"],
      output_storage=[{"output_key": "unified_convergence_context", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.unified_convergence_context", "final_for_stage": True}],
      horizon_rule="q1_to_q20_model_input_repair_cells",
      fail_fast_code="post_intake_sequence_unified_context_failed",
      python_action="Build the table-filtered convergence context from issue and model-input facts.",
    ),
    _process_sequence_row(
      "convergence",
      92,
      "unified_convergence_gpt_decision",
      "run_unified_convergence_cycle",
      parent_step_key="unified_convergence_decision",
      step_kind="subprocess",
      contract_name="unified_convergence_decision",
      context_contract_name="unified_convergence_decision",
      context_include_phase="planner",
      required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME, _GPT_CONTEXT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["unified_convergence_context", "numeric_guidance_packet", "writable_lever_catalog"],
      produced_output_keys=["unified_convergence_decision"],
      output_storage=[{"output_key": "unified_convergence_decision", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.unified_convergence_decision", "final_for_stage": True}],
      horizon_rule="q1_to_q20_model_input_repair_cells",
      timeout_seconds=240,
      max_attempts=10,
      fail_fast_code="post_intake_sequence_unified_gpt_decision_failed",
      python_action="Request the table-defined convergence decision contract.",
    ),
    _process_sequence_row(
      "convergence",
      93,
      "unified_convergence_plan_translation",
      "translate_unified_convergence_decision_to_updates",
      parent_step_key="unified_convergence_decision",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["unified_convergence_decision", "model_input_json", "repair_scope"],
      produced_output_keys=["unified_convergence_plan"],
      output_storage=[{"output_key": "unified_convergence_plan", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.unified_convergence_plan", "final_for_stage": True}],
      horizon_rule="mapped_model_input_update_plan_only",
      fail_fast_code="post_intake_sequence_unified_plan_translation_failed",
      python_action="Translate the GPT decision into exact mapped model-input updates.",
    ),
    _process_sequence_row(
      "convergence",
      94,
      "unified_convergence_apply_updates",
      "apply_unified_convergence_updates",
      parent_step_key="unified_convergence_decision",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_SEQUENCE_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["unified_convergence_plan", "model_input_json", "finmo_json", "payroll_headcount"],
      produced_output_keys=["model_input_json", "finmo_json"],
      output_storage=[
        {"output_key": "model_input_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.model_input_json", "final_for_stage": True},
        {"output_key": "finmo_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.finmo_json", "final_for_stage": True},
      ],
      horizon_rule="apply_mapped_repair_updates_and_rebuild_finmo",
      fail_fast_code="post_intake_sequence_unified_apply_updates_failed",
      python_action="Apply mapped updates and rebuild FINMO; upstream final outputs require recompute triggers rather than direct mutation.",
    ),
    _process_sequence_row(
      "convergence",
      95,
      "unified_convergence_verify_progress",
      "verify_unified_convergence_progress",
      parent_step_key="unified_convergence_decision",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["issue_ledger", "model_input_json", "finmo_json", "unified_convergence_plan"],
      produced_output_keys=["controller_resolution_state", "resolution_summary"],
      output_storage=[{"output_key": "controller_resolution_state", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.controller_resolution_state", "final_for_stage": True}],
      horizon_rule="validate_convergence_progress_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_unified_progress_verification_failed",
      python_action="Verify that the convergence cycle materially improved or cleared table-backed issues.",
    ),
    _process_sequence_row(
      "convergence",
      96,
      "post_convergence_global_validation",
      "assert_post_intake_global_invariants",
      parent_step_key="unified_convergence_decision",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, "post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["stage_ramp_contract", "model_input_json", "finmo_json", "payroll_headcount"],
      produced_output_keys=["post_convergence_global_validation"],
      output_storage=[{"output_key": "post_convergence_global_validation", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="post_convergence_global_invariants_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_post_convergence_global_validation_failed",
      python_action="Validate the converged state through the sequence controller before cash execution starts.",
    ),
    _process_sequence_row(
      "cash_pass",
      101,
      "cash_debt_schedule_seed",
      "apply_cash_pass_minimum_debt_schedule",
      parent_step_key="cash_minimum_debt_schedule",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["financials_json", "model_input_json", "finmo_json", "cash_policy", "debt_schedule_policy"],
      produced_output_keys=["debt_schedule", "model_input_json", "finmo_json"],
      output_storage=[
        {
          "output_key": "debt_schedule",
          "storage_kind": "draft_domain_column",
          "storage_path": "intake_consult_drafts.debt_schedule",
          "final_for_stage": True,
        }
      ],
      horizon_rule="q1_to_q20_debt_schedule",
      fail_fast_code="post_intake_sequence_cash_debt_seed_failed",
      python_action="Seed the minimum debt schedule before cash review.",
    ),
    _process_sequence_row(
      "cash_pass",
      102,
      "cash_short_term_debt_seed",
      "seed_cash_short_term_debt_current_portion",
      parent_step_key="cash_minimum_debt_schedule",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["debt_schedule", "model_input_json", "finmo_json", "cash_policy"],
      produced_output_keys=["model_input_json", "finmo_json"],
      horizon_rule="short_term_debt_current_portion_before_cash_review",
      fail_fast_code="post_intake_sequence_cash_short_term_debt_seed_failed",
      python_action="Normalize short-term debt/current-portion semantics before building the cash envelope.",
    ),
    _process_sequence_row(
      "cash_pass",
      111,
      "cash_review_context_build",
      "build_cash_strategy_review_context",
      parent_step_key="cash_strategy_review",
      step_kind="subprocess",
      context_contract_name="cash_strategy_review",
      context_include_phase="cash_pass",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _GPT_CONTEXT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["financials_json", "model_input_json", "finmo_json", "cash_policy", "debt_schedule", "controller_resolution_state"],
      produced_output_keys=["cash_strategy_review_context", "cash_envelope", "liquidity_violation_grid"],
      output_storage=[{"output_key": "cash_strategy_review_context", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.cash_strategy_review_context", "final_for_stage": True}],
      horizon_rule="cash_gap_rows_subset_validation_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_cash_review_context_failed",
      python_action="Build the cash review context envelope from the current FINMO and cash policy.",
    ),
    _process_sequence_row(
      "cash_pass",
      112,
      "cash_gpt_review",
      "run_cash_strategy_review",
      parent_step_key="cash_strategy_review",
      step_kind="subprocess",
      contract_name="cash_strategy_review",
      context_contract_name="cash_strategy_review",
      context_include_phase="cash_pass",
      required_lookup_tables=[_GPT_CONTRACT_TABLE_NAME, _GPT_CONTEXT_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["cash_strategy_review_context", "cash_policy", "cash_envelope", "liquidity_violation_grid", "debt_schedule"],
      produced_output_keys=["cash_strategy_review_decision"],
      output_storage=[{"output_key": "cash_strategy_review_decision", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.cash_strategy_review_decision", "final_for_stage": True}],
      horizon_rule="cash_gap_rows_subset_validation_all_q1_to_q20",
      timeout_seconds=90,
      max_attempts=1,
      fail_fast_code="post_intake_sequence_cash_gpt_review_failed",
      python_action="Request the table-defined cash strategy contract.",
    ),
    _process_sequence_row(
      "cash_pass",
      113,
      "cash_translation_plan",
      "translate_cash_strategy_decision_to_updates",
      parent_step_key="cash_strategy_review",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["cash_strategy_review_decision", "cash_strategy_review_context", "model_input_json", "finmo_json"],
      produced_output_keys=["cash_strategy_second_pass_plan"],
      output_storage=[{"output_key": "cash_strategy_second_pass_plan", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.cash_strategy_second_pass_plan", "final_for_stage": True}],
      horizon_rule="mapped_cash_update_plan_only",
      fail_fast_code="post_intake_sequence_cash_translation_failed",
      python_action="Translate the cash decision into exact mapped updates.",
    ),
    _process_sequence_row(
      "cash_pass",
      114,
      "cash_apply_exact_updates",
      "apply_cash_strategy_exact_updates",
      parent_step_key="cash_strategy_review",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_SEQUENCE_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["cash_strategy_second_pass_plan", "model_input_json", "finmo_json"],
      produced_output_keys=["model_input_json", "finmo_json", "cash_strategy_second_pass_result"],
      output_storage=[{"output_key": "cash_strategy_second_pass_result", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.cash_strategy_second_pass_result", "final_for_stage": True}],
      horizon_rule="apply_cash_updates_and_rebuild_finmo",
      fail_fast_code="post_intake_sequence_cash_apply_updates_failed",
      python_action="Apply the exact mapped cash updates and rebuild FINMO.",
    ),
    _process_sequence_row(
      "cash_pass",
      115,
      "cash_debt_schedule_rebuild",
      "rebuild_cash_debt_schedule_after_updates",
      parent_step_key="cash_strategy_review",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["cash_strategy_second_pass_result", "debt_schedule", "model_input_json", "finmo_json", "cash_policy"],
      produced_output_keys=["debt_schedule", "model_input_json", "finmo_json"],
      output_storage=[
        {
          "output_key": "debt_schedule",
          "storage_kind": "draft_domain_column",
          "storage_path": "intake_consult_drafts.debt_schedule",
          "final_for_stage": True,
          "recompute_of_step_key": "cash_debt_schedule_seed",
        }
      ],
      horizon_rule="minimum_debt_schedule_floor_preserved_after_cash_updates",
      fail_fast_code="post_intake_sequence_cash_debt_rebuild_failed",
      python_action="Rebuild the debt schedule after cash strategy changes while preserving required minimum principal.",
    ),
    _process_sequence_row(
      "cash_pass",
      116,
      "cash_short_term_debt_current_portion",
      "apply_cash_short_term_debt_current_portion",
      parent_step_key="cash_strategy_review",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["debt_schedule", "model_input_json", "finmo_json"],
      produced_output_keys=["model_input_json", "finmo_json"],
      horizon_rule="short_term_debt_current_portion_applied_after_cash_updates",
      fail_fast_code="post_intake_sequence_cash_current_portion_failed",
      python_action="Apply the current portion of long-term debt after cash updates.",
    ),
    _process_sequence_row(
      "cash_pass",
      117,
      "cash_surplus_cleanup",
      "deploy_cash_surplus_above_policy_ceiling",
      parent_step_key="cash_strategy_review",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["cash_policy", "model_input_json", "finmo_json", "cash_strategy_second_pass_result"],
      produced_output_keys=["model_input_json", "finmo_json", "cash_strategy_second_pass_result"],
      horizon_rule="surplus_above_policy_ceiling_deployed",
      fail_fast_code="post_intake_sequence_cash_surplus_cleanup_failed",
      python_action="Deploy residual surplus above the policy ceiling through mapped cash levers.",
    ),
    _process_sequence_row(
      "cash_pass",
      121,
      "cash_post_validation",
      "validate_cash_pass",
      parent_step_key="cash_pass_validation",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["cash_strategy_second_pass_result", "model_input_json", "finmo_json", "cash_policy", "debt_schedule"],
      produced_output_keys=["cash_post_validation", "controller_resolution_state"],
      output_storage=[{"output_key": "cash_post_validation", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.cash_strategy_second_pass_result.cash_post_validation", "final_for_stage": True}],
      horizon_rule="cash_post_pass_validation_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_cash_post_validation_failed",
      python_action="Validate post-cash-pass state before final hard gates.",
    ),
    _process_sequence_row(
      "final_validation",
      131,
      "cash_final_finmo_rebuild",
      "build_python_finmo_json",
      parent_step_key="final_hard_gates",
      step_kind="subprocess",
      required_lookup_tables=[_PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["model_input_json", "cash_strategy_second_pass_result"],
      produced_output_keys=["finmo_json"],
      output_storage=[{"output_key": "finmo_json", "storage_kind": "draft_domain_column", "storage_path": "intake_consult_drafts.finmo_json", "final_for_stage": True}],
      horizon_rule="fresh_final_finmo_from_model_input",
      fail_fast_code="post_intake_sequence_final_finmo_rebuild_failed",
      python_action="Rebuild final FINMO directly from final model_input_json before hard gates.",
    ),
    _process_sequence_row(
      "final_validation",
      132,
      "cash_final_liquidity_gate",
      "assert_post_intake_cash_buffer_integrity",
      parent_step_key="final_hard_gates",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["financials_json", "model_input_json", "finmo_json", "cash_policy"],
      produced_output_keys=["cash_liquidity_gate"],
      output_storage=[{"output_key": "cash_liquidity_gate", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="ending_cash_gte_required_buffer_all_20q",
      fail_fast_code="post_intake_sequence_final_liquidity_gate_failed",
      python_action="Hard fail unless ending cash meets the required buffer in every live quarter.",
    ),
    _process_sequence_row(
      "final_validation",
      133,
      "final_stage_ramp_revenue_limit_check",
      "apply_stage_ramp_revenue_driver_limits",
      parent_step_key="final_hard_gates",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["stage_ramp_contract", "model_input_json", "finmo_json"],
      produced_output_keys=["model_input_json", "finmo_json", "stage_ramp_revenue_limit_repair"],
      output_storage=[{"output_key": "stage_ramp_revenue_limit_repair", "storage_kind": "planning_run_json", "storage_path": "planning_run_json.cash_strategy_second_pass_result.stage_ramp_revenue_limit_repair", "final_for_stage": True}],
      horizon_rule="final_revenue_within_stage_ramp_max_path",
      fail_fast_code="post_intake_sequence_final_revenue_limit_failed",
      python_action="Ensure final revenue remains inside the stage-ramp max path through mapped revenue drivers.",
    ),
    _process_sequence_row(
      "final_validation",
      134,
      "final_global_validation",
      "assert_post_intake_global_invariants",
      parent_step_key="final_hard_gates",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _CASH_POLICY_TABLE_NAME, "post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["stage_ramp_contract", "model_input_json", "finmo_json", "payroll_headcount", "debt_schedule", "financials_json"],
      produced_output_keys=["final_global_validation"],
      output_storage=[{"output_key": "final_global_validation", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="final_global_invariants_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_final_global_validation_failed",
      python_action="Run final global invariants as a declared final-validation process, including cash-buffer enforcement.",
    ),
    _process_sequence_row(
      "runtime_validation",
      141,
      "finalize_mapping_integrity",
      "assert_post_intake_mapping_formula_application_integrity",
      parent_step_key="post_intake_finalize_validation",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["model_input_json", "finmo_json"],
      produced_output_keys=["finalize_mapping_integrity"],
      output_storage=[{"output_key": "finalize_mapping_integrity", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="validate_mapping_formula_application_q1_to_q20",
      fail_fast_code="post_intake_sequence_finalize_mapping_integrity_failed",
      python_action="Validate formula metadata and application in the completed model.",
    ),
    _process_sequence_row(
      "runtime_validation",
      142,
      "finalize_payroll_reconciliation",
      "assert_finmo_payroll_matches_headcount_schedule",
      parent_step_key="post_intake_finalize_validation",
      step_kind="subprocess",
      required_lookup_tables=["post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["payroll_headcount", "model_input_json", "finmo_json"],
      produced_output_keys=["finalize_payroll_reconciliation"],
      output_storage=[{"output_key": "finalize_payroll_reconciliation", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="payroll_schedule_reconciliation_q1_to_q20",
      fail_fast_code="post_intake_sequence_finalize_payroll_failed",
      python_action="Validate final payroll schedule, model_input payroll rows, and FINMO payroll.",
    ),
    _process_sequence_row(
      "runtime_validation",
      143,
      "finalize_debt_reconciliation",
      "assert_finmo_matches_debt_schedule",
      parent_step_key="post_intake_finalize_validation",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["debt_schedule", "finmo_json"],
      produced_output_keys=["finalize_debt_reconciliation"],
      output_storage=[{"output_key": "finalize_debt_reconciliation", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="debt_schedule_reconciliation_q1_to_q20",
      fail_fast_code="post_intake_sequence_finalize_debt_failed",
      python_action="Validate final debt schedule against FINMO.",
    ),
    _process_sequence_row(
      "runtime_validation",
      144,
      "finalize_cash_phase_trace",
      "assert_cash_phase_trace_complete",
      parent_step_key="post_intake_finalize_validation",
      step_kind="subprocess",
      required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["cash_strategy_second_pass_result", "cash_policy"],
      produced_output_keys=["finalize_cash_phase_trace"],
      output_storage=[{"output_key": "finalize_cash_phase_trace", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="cash_phase_trace_complete",
      fail_fast_code="post_intake_sequence_finalize_cash_trace_failed",
      python_action="Validate that every required cash-pass substep completed in order.",
    ),
    _process_sequence_row(
      "runtime_validation",
      145,
      "finalize_global_invariants",
      "assert_post_intake_global_invariants",
      parent_step_key="post_intake_finalize_validation",
      step_kind="subprocess",
      required_lookup_tables=[_MAPPING_TABLE_NAME, _CASH_POLICY_TABLE_NAME, "post_intake_headcount_policy_lookup", _PROCESS_CONTEXT_TABLE_NAME],
      required_context_keys=["stage_ramp_contract", "model_input_json", "finmo_json", "payroll_headcount", "debt_schedule", "financials_json"],
      produced_output_keys=["finalize_global_invariants"],
      output_storage=[{"output_key": "finalize_global_invariants", "storage_kind": "validation_result", "final_for_stage": True}],
      horizon_rule="finalize_global_invariants_all_q1_to_q20",
      fail_fast_code="post_intake_sequence_finalize_global_invariants_failed",
      python_action="Re-run final global invariants during runtime finalize through the declared sequence step.",
    ),
  ]
)


_PROCESS_CONTEXT_KEY_DEFAULTS: Dict[str, Dict[str, Any]] = {
  "business_facts": {"context_domain": "intake", "source_kind": "runtime_context", "source_path": "business_facts"},
  "business_type": {"context_domain": "intake", "source_kind": "derived_fact", "source_path": "operating_model_json.business_type"},
  "business_naics": {"context_domain": "intake", "source_kind": "derived_fact", "source_path": "people_json.business_naics_6"},
  "operating_model_json": {"context_domain": "intake", "source_kind": "draft_column", "source_path": "operating_model_json"},
  "ops_context": {"context_domain": "ops", "source_kind": "domain_output", "source_path": "ops_context"},
  "target_market_json": {"context_domain": "intake", "source_kind": "draft_column", "source_path": "target_market_json"},
  "market_context": {"context_domain": "market", "source_kind": "domain_output", "source_path": "market_context"},
  "people_json": {"context_domain": "intake", "source_kind": "draft_column", "source_path": "people_json"},
  "people_context": {"context_domain": "people", "source_kind": "domain_output", "source_path": "people_context"},
  "financials_json": {"context_domain": "intake", "source_kind": "draft_column", "source_path": "financials_json"},
  "financials_context": {"context_domain": "financials", "source_kind": "domain_output", "source_path": "financials_context"},
  "financials_year1_json": {"context_domain": "derived_fact", "source_kind": "runtime_context", "source_path": "financials_year1_json"},
  "financials_year1_context": {"context_domain": "financials", "source_kind": "domain_output", "source_path": "financials_year1_context"},
  "fulfillment_json": {"context_domain": "intake", "source_kind": "draft_column", "source_path": "fulfillment_json"},
  "marketing_model_json": {"context_domain": "derived_fact", "source_kind": "runtime_context", "source_path": "marketing_model_json"},
  "marketing_context": {"context_domain": "marketing", "source_kind": "domain_output", "source_path": "marketing_context"},
  "planning_context_summary_json": {"context_domain": "planning", "source_kind": "runtime_context", "source_path": "planning_context_summary_json"},
  "planning_mode_decision": {"context_domain": "planning", "source_kind": "domain_output", "source_path": "planning_mode_decision"},
  "shared_context": {"context_domain": "planning", "source_kind": "domain_output", "source_path": "shared_context"},
  "model_input_json": {"context_domain": "financial_model", "source_kind": "domain_output", "source_path": "model_input_json"},
  "final_model_input_json": {"context_domain": "financial_model", "source_kind": "domain_output", "source_path": "model_input_json"},
  "finmo_json": {"context_domain": "financial_model", "source_kind": "domain_output", "source_path": "finmo_json"},
  "final_finmo_json": {"context_domain": "financial_model", "source_kind": "domain_output", "source_path": "finmo_json"},
  "stage_ramp_contract": {"context_domain": "contract", "source_kind": "domain_output", "source_path": "stage_ramp_contract"},
  "r_and_d_applicability": {"context_domain": "contract", "source_kind": "domain_output", "source_path": "r_and_d_applicability"},
  "balance_sheet_contextual_seed": {"context_domain": "balance_sheet", "source_kind": "domain_output", "source_path": "balance_sheet_contextual_seed"},
  "post_intak_mapping_lookup": {"context_domain": "mapping", "source_kind": "sql_lookup", "source_path": "post_intak_mapping_lookup"},
  "payroll_context_payload": {"context_domain": "payroll", "source_kind": "domain_output", "source_path": "payroll_context_payload"},
  "payroll_headcount_contract": {"context_domain": "payroll", "source_kind": "domain_output", "source_path": "payroll_headcount_contract"},
  "payroll_headcount": {"context_domain": "payroll", "source_kind": "domain_output", "source_path": "payroll_headcount"},
  "oews_title_catalog": {"context_domain": "payroll", "source_kind": "sql_lookup", "source_path": "oews_state_wages"},
  "headcount_policy": {"context_domain": "payroll", "source_kind": "sql_lookup", "source_path": "post_intake_headcount_policy_lookup"},
  "productivity_assumptions": {"context_domain": "payroll", "source_kind": "sql_lookup", "source_path": "post_intake_headcount_policy_lookup.productivity_assumptions"},
  "payroll_economic_guardrails": {"context_domain": "payroll", "source_kind": "sql_lookup", "source_path": "post_intake_headcount_policy_lookup.economic_guardrails"},
  "payroll_feasibility_mapping": {"context_domain": "payroll", "source_kind": "sql_lookup", "source_path": "post_intak_mapping_lookup.repair_direction_rules_json"},
  "previous_contract_failure": {"context_domain": "retry", "source_kind": "runtime_context", "source_path": "previous_contract_failure"},
  "revenue_drivers": {"context_domain": "revenue", "source_kind": "derived_fact", "source_path": "model_input_json.sections.revenue"},
  "capacity_outputs": {"context_domain": "revenue", "source_kind": "domain_output", "source_path": "capacity_outputs"},
  "quarter_grid_context_payload": {"context_domain": "quarter_grid", "source_kind": "domain_output", "source_path": "quarter_grid_context_payload"},
  "quarter_grid_plan": {"context_domain": "quarter_grid", "source_kind": "domain_output", "source_path": "quarter_grid_plan"},
  "validated_quarter_grid_plan": {"context_domain": "quarter_grid", "source_kind": "domain_output", "source_path": "validated_quarter_grid_plan"},
  "issue_ledger": {"context_domain": "convergence", "source_kind": "domain_output", "source_path": "issue_ledger"},
  "repair_scope": {"context_domain": "convergence", "source_kind": "domain_output", "source_path": "repair_scope"},
  "unified_convergence_context": {"context_domain": "convergence", "source_kind": "domain_output", "source_path": "unified_convergence_context"},
  "unified_convergence_decision": {"context_domain": "convergence", "source_kind": "domain_output", "source_path": "unified_convergence_decision"},
  "unified_convergence_plan": {"context_domain": "convergence", "source_kind": "domain_output", "source_path": "unified_convergence_plan"},
  "numeric_guidance_packet": {"context_domain": "convergence", "source_kind": "runtime_context", "source_path": "numeric_guidance_packet"},
  "writable_lever_catalog": {"context_domain": "convergence", "source_kind": "runtime_context", "source_path": "writable_lever_catalog"},
  "controller_resolution_state": {"context_domain": "convergence", "source_kind": "domain_output", "source_path": "controller_resolution_state"},
  "resolution_summary": {"context_domain": "convergence", "source_kind": "domain_output", "source_path": "resolution_summary"},
  "financials_json": {"context_domain": "intake", "source_kind": "draft_column", "source_path": "financials_json"},
  "cash_policy": {"context_domain": "cash", "source_kind": "sql_lookup", "source_path": "post_intake_cash_policy_lookup"},
  "debt_schedule_policy": {"context_domain": "cash", "source_kind": "sql_lookup", "source_path": "post_intake_cash_policy_lookup.debt_schedule_policy"},
  "debt_schedule": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "debt_schedule"},
  "cash_strategy_review_context": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "cash_strategy_review_context"},
  "cash_envelope": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "cash_envelope"},
  "liquidity_violation_grid": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "liquidity_violation_grid"},
  "cash_strategy_review_decision": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "cash_strategy_review_decision"},
  "cash_strategy_second_pass_plan": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "cash_strategy_second_pass_plan"},
  "cash_strategy_second_pass_result": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "cash_strategy_second_pass_result"},
  "cash_post_validation": {"context_domain": "cash", "source_kind": "domain_output", "source_path": "cash_post_validation"},
  "cash_liquidity_gate": {"context_domain": "cash", "source_kind": "validation_result", "source_path": "cash_liquidity_gate"},
  "stage_ramp_revenue_limit_repair": {"context_domain": "final_validation", "source_kind": "domain_output", "source_path": "stage_ramp_revenue_limit_repair"},
}


def _default_process_context_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  seen: Set[tuple[str, str]] = set()
  for sequence_row in _DEFAULT_PROCESS_SEQUENCE_ROWS:
    step_key = str(sequence_row.get("step_key") or "").strip().lower()
    if not step_key:
      continue
    for context_key in sequence_row.get("required_context_keys") or []:
      normalized_key = str(context_key or "").strip()
      if not normalized_key:
        continue
      dedupe_key = (step_key, normalized_key)
      if dedupe_key in seen:
        continue
      seen.add(dedupe_key)
      defaults = copy.deepcopy(_PROCESS_CONTEXT_KEY_DEFAULTS.get(normalized_key) or {})
      rows.append(
        _process_context_row(
          step_key,
          normalized_key,
          context_domain=str(defaults.get("context_domain") or "process_input").strip(),
          source_kind=str(defaults.get("source_kind") or "runtime_context").strip(),
          source_path=str(defaults.get("source_path") or normalized_key).strip(),
          transform_kind=str(defaults.get("transform_kind") or "copy").strip(),
          required=True,
          immutable_input=True,
          notes=(
            "Process input declared by sql.post_intake_process_sequence_lookup.required_context_keys_json. "
            "Context rows define inputs only; process outputs must be written to their domain storage."
          ),
        )
      )
  return rows


_DEFAULT_PROCESS_CONTEXT_ROWS: List[Dict[str, Any]] = _default_process_context_rows()


_STAGE_RAMP_GRID_FIELDS: List[Dict[str, Any]] = [
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].q", "q", "integer", is_array_item=True, parent_field_path="quarter_ramp_grid", horizon_rule="q1_to_q20_exactly_once", validation_kind="quarter_index_1_to_20", allowed_aliases=["quarter_index"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].rev_target", "rev_target", "ratio_2dp", is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["revenue_qoq_target"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].rev_max", "rev_max", "ratio_2dp", is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["revenue_qoq_max"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].rev_spike", "rev_spike", "boolean", is_array_item=True, parent_field_path="quarter_ramp_grid"),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].rev_spike_max", "rev_spike_max", "ratio_2dp", is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["revenue_qoq_spike_max"]),
  _gpt_contract_row(
    "stage_ramp_contract",
    "quarter_ramp_grid",
    "quarter_ramp_grid[].max_util",
    "max_util",
    "ratio_2dp",
    is_array_item=True,
    parent_field_path="quarter_ramp_grid",
    normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric",
    allowed_aliases=["utilization_cap"],
    prompt_required_instruction="Utilization cap must be non-decreasing. For Q2-Q20, utilization-cap growth cannot exceed that row's allowed revenue growth: use rev_spike_max when rev_spike=true, otherwise use rev_max.",
  ),
  # Module 3 v3 Task 3.3 — stage_ramp_contract cost-cap fields are now
  # NAICS-bound. Static (min, max) is the mapping outer envelope; the
  # NAICS cascade narrows inside. When `business_naics` is supplied at
  # prompt-build time, GPT receives an industry-typical band; without
  # NAICS the static envelope still applies.
  _gpt_contract_row(
    "stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].cogs_target", "cogs_target", "ratio_2dp",
    min_value=0.05, max_value=0.90,
    naics_baseline_metric_key="cogs_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric", allowed_aliases=["cogs_percent_of_revenue_target"],
  ),
  _gpt_contract_row(
    "stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].cogs_max", "cogs_max", "ratio_2dp",
    min_value=0.20, max_value=0.95,
    naics_baseline_metric_key="cogs_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric", allowed_aliases=["cogs_percent_of_revenue_max"],
  ),
  _gpt_contract_row(
    "stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].marketing_max", "marketing_max", "ratio_2dp",
    min_value=0.00, max_value=0.40,
    naics_baseline_metric_key="marketing_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric", allowed_aliases=["marketing_percent_of_revenue_max"],
  ),
  _gpt_contract_row(
    "stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].rd_max", "rd_max", "ratio_2dp",
    min_value=0.00, max_value=0.50,
    naics_baseline_metric_key="r_and_d_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric", allowed_aliases=["rd_percent_of_revenue_max"],
  ),
  _gpt_contract_row(
    "stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].ga_max", "ga_max", "ratio_2dp",
    min_value=0.00, max_value=0.60,
    naics_baseline_metric_key="sga_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric", allowed_aliases=["g_and_a_percent_of_revenue_max"],
  ),
  _gpt_contract_row(
    "stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].lease_max", "lease_max", "ratio_2dp",
    min_value=0.00, max_value=0.50,
    naics_baseline_metric_key="rent_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric", allowed_aliases=["lease_percent_of_revenue_max"],
  ),
  _gpt_contract_row(
    "stage_ramp_contract",
    "quarter_ramp_grid",
    "quarter_ramp_grid[].ni_floor",
    "ni_floor",
    "ratio_2dp",
    min_value=-0.25,
    max_value=0.15,
    is_array_item=True,
    parent_field_path="quarter_ramp_grid",
    normalization_kind="ratio_2dp",
    validation_kind="stage_ramp_numeric",
    allowed_aliases=["net_income_margin_floor"],
    prompt_required_instruction="Net-income margin floor must obey stage_profitability_policy.validator_rules exactly. If q5_to_q20_min_net_income_margin_floor is present, every Q5-Q20 ni_floor must be at least that value.",
  ),
  _gpt_contract_row(
    "stage_ramp_contract",
    "quarter_ramp_grid",
    "quarter_ramp_grid[].posture",
    "posture",
    "enum",
    is_array_item=True,
    parent_field_path="quarter_ramp_grid",
    validation_kind="enum",
    enum_values=["loss_allowed", "improving_losses", "near_breakeven", "positive"],
    allowed_aliases=["profitability_posture"],
    prompt_required_instruction="Profitability posture must be one of the stage_profitability_policy.profitability_postures values. If operational_requires_positive_from_q5 is true, every Q5-Q20 posture must be positive.",
  ),
]

_PAYROLL_HEADCOUNT_GRID_FIELDS: List[Dict[str, Any]] = [
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].q", "q", "integer", is_array_item=True, parent_field_path="payroll_headcount_grid", horizon_rule="q1_to_q20_exactly_once", validation_kind="quarter_index_1_to_20", allowed_aliases=["quarter_index"]),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].oews_occ_title", "oews_occ_title", "string", is_array_item=True, parent_field_path="payroll_headcount_grid", validation_kind="payroll_oews_catalog_member", lookup_source="oews_title_catalog", prompt_label="OEWS occupation title", prompt_required_instruction="Must be one exact occ_title from the full NAICS oews_title_catalog.title_candidates. GPT chooses the OEWS titles it wants to hire and FTE by quarter; Python uses the exact selected OEWS row for wage lookup and payroll math. Do not invent staffing families, staffing categories, aliases, or non-OEWS staffing buckets."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].starting_fte", "starting_fte", "number", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0, max_value=100000, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="Starting FTE", prompt_required_instruction="Used with ending_fte to calculate average_fte=(starting_fte+ending_fte)/2. GPT owns the FTE ramp; Python derives supported Capacity from the resulting average FTE."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].hires", "hires", "number", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0, max_value=100000, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="FTE hires/additions", prompt_required_instruction="Mechanical FTE addition in the quarter. If ending_fte is greater than starting_fte, hires should equal ending_fte - starting_fte. Python may normalize this arithmetic field from the selected FTE levels; GPT owns the starting/ending FTE decision."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].ending_fte", "ending_fte", "number", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0, max_value=100000, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="Ending FTE", prompt_required_instruction="Ending FTE is GPT's staffing decision for the exact OEWS title and quarter. Keep OEWS title continuity after hiring starts; Python uses starting/ending average FTE to derive supported Capacity."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].payroll_tax_benefits_pct", "payroll_tax_benefits_pct", "ratio_2dp", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0.12, max_value=0.35, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="Payroll taxes and benefits percent", prompt_required_instruction="Must stay inside post_intake_headcount_policy_lookup min/max benefits burden. Do not use 0.00 for employees."),
]

_BALANCE_SHEET_CONTEXTUAL_SEED_GRID_FIELDS: List[Dict[str, Any]] = [
  _gpt_contract_row("balance_sheet_contextual_seed", "balance_sheet_seed_grid", "balance_sheet_seed_grid[].lever_id", "lever_id", "string", is_array_item=True, parent_field_path="balance_sheet_seed_grid", validation_kind="mapping_table_member", lookup_source="post_intak_mapping_lookup", prompt_required_instruction="Use one exact balance-sheet lever_id from the supplied mapping-backed seed_candidates. Do not invent rows."),
  _gpt_contract_row("balance_sheet_contextual_seed", "balance_sheet_seed_grid", "balance_sheet_seed_grid[].applicable", "applicable", "boolean", is_array_item=True, parent_field_path="balance_sheet_seed_grid", validation_kind="boolean", prompt_required_instruction="True only when the business context/type should carry this balance-sheet driver in the forecast."),
  _gpt_contract_row("balance_sheet_contextual_seed", "balance_sheet_seed_grid", "balance_sheet_seed_grid[].seed_value", "seed_value", "number", is_array_item=True, parent_field_path="balance_sheet_seed_grid", min_value=0.00, max_value=365.00, normalization_kind="ratio_2dp", validation_kind="balance_sheet_contextual_seed", lookup_source="post_intak_mapping_lookup", prompt_required_instruction="Business-specific seed value. For day-count rows, return days. For ratio rows, return decimal ratio like 0.05 for 5%. Do not use universal defaults; decide from business type/context and mapping bounds."),
  _gpt_contract_row("balance_sheet_contextual_seed", "balance_sheet_seed_grid", "balance_sheet_seed_grid[].value_kind", "value_kind", "enum", is_array_item=True, parent_field_path="balance_sheet_seed_grid", validation_kind="enum", enum_values=["day_count", "ratio"], prompt_required_instruction="Must match the mapping row value_kind."),
  _gpt_contract_row("balance_sheet_contextual_seed", "balance_sheet_seed_grid", "balance_sheet_seed_grid[].rationale", "rationale", "string", is_array_item=True, parent_field_path="balance_sheet_seed_grid", prompt_required_instruction="Brief business-context reason for applicability and seed level."),
]


_DEFAULT_GPT_CONTRACT_ROWS: List[Dict[str, Any]] = [
  # Module 3 Task 3.3 — maintenance capex bound is now NAICS-driven via the
  # `maintenance_capex_percent_of_revenue` resolver cascade. The previous
  # hardcoded 2.00-15.00 universal range was a 2-15% catch-all that did not
  # reflect industry reality (capital-light services and capital-heavy
  # manufacturing should not share the same bound). Static `min_value`/
  # `max_value` are intentionally omitted; with `naics_baseline_metric_key`
  # set, prompt-build time fills them in from the cascade. Both
  # `mapping_table_outer_envelope` and the static fallback are inactive
  # because there is no longer a meaningful universal-business range.
  _gpt_contract_row(
    "maintenance_capex_percent",
    "root",
    "maintenance_capex_percent",
    "maintenance_capex_percent",
    "ratio_2dp",
    naics_baseline_metric_key="maintenance_capex_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    mapping_table_outer_envelope=False,
    normalization_kind="ratio_2dp",
    validation_kind="maintenance_capex_percent_range",
    contract_phase="pre_forecast",
  ),
  _gpt_contract_row(
    "balance_sheet_contextual_seed",
    "root",
    "balance_sheet_seed_grid",
    "balance_sheet_seed_grid",
    "array",
    min_items=1,
    max_items=12,
    item_contract_grid_name="balance_sheet_seed_grid",
    validation_kind="balance_sheet_contextual_seed",
    lookup_source="post_intak_mapping_lookup",
    prompt_required_instruction="Return one row for every supplied seed_candidate. Python validates completeness against sql.post_intak_mapping_lookup; missing rows fail fast.",
  ),
  _gpt_contract_row("balance_sheet_contextual_seed", "root", "rationale", "rationale", "string"),
  *_BALANCE_SHEET_CONTEXTUAL_SEED_GRID_FIELDS,
  _gpt_contract_row("stage_ramp_contract", "root", "stage_family", "stage_family", "enum", validation_kind="enum", enum_values=["startup", "early", "operational"]),
  _gpt_contract_row("stage_ramp_contract", "root", "utilization_high_watermark", "utilization_high_watermark", "ratio_2dp", min_value=0.50, max_value=0.98, normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric"),
  _gpt_contract_row(
    "stage_ramp_contract",
    "root",
    "quarter_ramp_grid",
    "quarter_ramp_grid",
    "array",
    min_items=20,
    max_items=20,
    item_contract_grid_name="quarter_ramp_grid",
    horizon_rule="q1_to_q20_exactly_once",
    validation_kind="required_20q_grid",
    prompt_required_instruction="Provide exactly one stage-ramp row for each forecast quarter Q1 through Q20. The ramp GPT decides the values; Python validates the full 20-quarter grid from this contract table.",
  ),
  _gpt_contract_row("stage_ramp_contract", "root", "rationale", "rationale", "string"),
  *_STAGE_RAMP_GRID_FIELDS,
  _gpt_contract_row(
    "payroll_headcount_schedule",
    "root",
    "payroll_headcount_grid",
    "payroll_headcount_grid",
    "array",
    min_items=20,
    max_items=400,
    item_contract_grid_name="payroll_headcount_grid",
    horizon_rule="q1_to_q20_at_least_once",
    validation_kind="payroll_headcount_schedule",
    lookup_source="post_intake_headcount_policy_lookup",
    prompt_required_instruction="Provide active supporting-staff OEWS-title/FTE rows for every forecast quarter Q1 through Q20. GPT picks exact oews_occ_title rows from the full NAICS oews_title_catalog.title_candidates and states starting_fte, hires, ending_fte, and benefits percent for that title. Do not provide wages and do not include key people; Python injects key people from intake, resolves wages through the selected OEWS row, applies wage positioning and inflation from post_intake_headcount_policy_lookup, calculates payroll dollars, derives payroll-supported Capacity from average FTE, and stores intake_consult_drafts.payroll_headcount. If an OEWS title has no FTE in all 20 quarters, omit it. Once an OEWS title starts, keep it active through Q20. Staffing families and categories are deleted from the active payroll contract.",
  ),
  _gpt_contract_row("payroll_headcount_schedule", "root", "capacity_labor_model", "capacity_labor_model", "enum", validation_kind="enum", enum_values=["labor_driven", "hybrid", "system_driven", "expert_driven"], lookup_source="post_intake_headcount_policy_lookup", prompt_required_instruction="Choose one capacity labor model from post_intake_headcount_policy_lookup.capacity_labor_model_values. This is business judgment; Python validates it."),
  _gpt_contract_row("payroll_headcount_schedule", "root", "labor_intensity_class", "labor_intensity_class", "enum", validation_kind="enum", enum_values=["low", "medium", "high", "expert"], lookup_source="post_intake_headcount_policy_lookup", prompt_required_instruction="Choose one labor intensity class from post_intake_headcount_policy_lookup.labor_intensity_class_values."),
  _gpt_contract_row("payroll_headcount_schedule", "root", "wage_positioning_tier", "wage_positioning_tier", "enum", validation_kind="enum", enum_values=["floor", "market", "premium", "specialized"], lookup_source="post_intake_headcount_policy_lookup", prompt_required_instruction="Choose one wage positioning tier from post_intake_headcount_policy_lookup. OEWS is the wage floor; GPT must also provide the exact wage_positioning_multiplier inside this tier's table-backed bounds."),
  _gpt_contract_row("payroll_headcount_schedule", "root", "wage_positioning_multiplier", "wage_positioning_multiplier", "number", min_value=1.0, max_value=3.0, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_required_instruction="Business-judgment wage multiplier applied to OEWS wages. Must be inside post_intake_headcount_policy_lookup.wage_positioning_multiplier bounds for the selected wage_positioning_tier. Python applies this exact multiplier; Python does not choose a default."),
  _gpt_contract_row("payroll_headcount_schedule", "root", "capacity_units_per_supporting_fte", "capacity_units_per_supporting_fte", "number", min_value=0.0001, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_required_instruction="Business-specific productivity judgment: how many structural capacity units one supporting FTE can support per quarter. Python multiplies this by payroll FTE to derive supported Capacity. Python does not reject it using fake universal capacity-per-FTE reasonableness bounds. Do not use revenue-per-employee."),
  # Module 3 v3 Task 3.3 — target_payroll_percent_of_revenue is NAICS-bound.
  # The mapping outer envelope (0.01-0.90) covers all labor-intensity
  # classes; NAICS narrows to the industry-typical band. Crucially, this
  # remains a REASONABLENESS TARGET only — Python does NOT clip payroll to
  # match revenue (Golden Rule preservation). The realism gate at finalize
  # checks the produced payroll/revenue ratio independently.
  _gpt_contract_row(
    "payroll_headcount_schedule", "root", "target_payroll_percent_of_revenue", "target_payroll_percent_of_revenue", "ratio_2dp",
    min_value=0.01, max_value=0.90,
    naics_baseline_metric_key="payroll_percent_of_revenue",
    naics_baseline_band_kind="min_target_max",
    normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule",
    lookup_source="post_intake_headcount_policy_lookup",
    prompt_required_instruction="Business-judgment sanity target for final payroll as a percent of revenue. This does not drive payroll math or force FTE. Python uses it as reasonableness context for GPT's own contract assumptions.",
  ),
  _gpt_contract_row("payroll_headcount_schedule", "root", "rationale", "rationale", "string"),
  *_PAYROLL_HEADCOUNT_GRID_FIELDS,
  _gpt_contract_row("r_and_d_applicability", "root", "r_and_d_enabled", "r_and_d_enabled", "boolean", validation_kind="boolean"),
  _gpt_contract_row("r_and_d_applicability", "root", "rationale", "rationale", "string"),
  _gpt_contract_row("unified_convergence_decision", "root", "strategy_class", "strategy_class", "string"),
  _gpt_contract_row("unified_convergence_decision", "root", "change_type", "change_type", "string"),
  _gpt_contract_row("unified_convergence_decision", "root", "progress_expectation", "progress_expectation", "string"),
  _gpt_contract_row("unified_convergence_decision", "root", "strategy_rationale", "strategy_rationale", "string"),
  _gpt_contract_row("unified_convergence_decision", "root", "retry_reason", "retry_reason", "string", allow_empty=True),
  _gpt_contract_row("unified_convergence_decision", "root", "lever_selection", "lever_selection", "array", min_items=1, validation_kind="mapping_table_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("unified_convergence_decision", "root", "primary_target_metric_names", "primary_target_metric_names", "array", validation_kind="mapping_table_target_metric_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row(
    "unified_convergence_decision",
    "root",
    "targets_by_quarter",
    "targets_by_quarter",
    "array",
    min_items=20,
    max_items=20,
    item_contract_grid_name="targets_by_quarter",
    horizon_rule="q1_to_q20_exactly_once",
    validation_kind="required_20q_grid",
    prompt_required_instruction="Convergence decisions must provide exactly one targets_by_quarter row for every forecast quarter Q1 through Q20. No partial horizon, focus-window, or single-quarter target set is valid.",
  ),
  _gpt_contract_row("unified_convergence_decision", "root", "target_tolerances", "target_tolerances", "array", item_contract_grid_name="target_tolerances", validation_kind="target_tolerance_grid"),
  _gpt_contract_row(
    "unified_convergence_decision",
    "root",
    "model_input_repair_cells",
    "model_input_repair_cells",
    "array",
    item_contract_grid_name="model_input_repair_cells",
    horizon_rule="q1_to_q20_editable_cells",
    validation_kind="locked_grid_cell_member",
    prompt_required_instruction="Convergence may only change locked editable model_input cells, but the editable-cell contract must cover the full Q1 through Q20 state.",
  ),
  _gpt_contract_row("unified_convergence_decision", "targets_by_quarter", "targets_by_quarter[].quarter_index", "quarter_index", "integer", is_array_item=True, parent_field_path="targets_by_quarter", validation_kind="quarter_index_1_to_20"),
  _gpt_contract_row("unified_convergence_decision", "targets_by_quarter", "targets_by_quarter[].metric_targets", "metric_targets", "array", is_array_item=True, parent_field_path="targets_by_quarter", item_contract_grid_name="metric_targets", validation_kind="mapping_table_target_metric_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("unified_convergence_decision", "metric_targets", "metric_targets[].metric_name", "metric_name", "string", is_array_item=True, parent_field_path="metric_targets", validation_kind="mapping_table_target_metric_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("unified_convergence_decision", "metric_targets", "metric_targets[].target_value", "target_value", "integer_currency", is_array_item=True, parent_field_path="metric_targets", normalization_kind="integer_currency"),
  _gpt_contract_row("unified_convergence_decision", "target_tolerances", "target_tolerances[].metric_name", "metric_name", "string", is_array_item=True, parent_field_path="target_tolerances", validation_kind="mapping_table_target_metric_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("unified_convergence_decision", "target_tolerances", "target_tolerances[].relative_tolerance_pct", "relative_tolerance_pct", "number", is_array_item=True, parent_field_path="target_tolerances", allow_null=True, normalization_kind="ratio_2dp"),
  _gpt_contract_row("unified_convergence_decision", "target_tolerances", "target_tolerances[].absolute_tolerance", "absolute_tolerance", "integer_currency", is_array_item=True, parent_field_path="target_tolerances", allow_null=True, normalization_kind="integer_currency"),
  _gpt_contract_row("unified_convergence_decision", "target_tolerances", "target_tolerances[].tolerance_reason", "tolerance_reason", "string", is_array_item=True, parent_field_path="target_tolerances"),
  _gpt_contract_row("unified_convergence_decision", "model_input_repair_cells", "model_input_repair_cells[].cell_id", "cell_id", "string", is_array_item=True, parent_field_path="model_input_repair_cells", validation_kind="locked_grid_cell_member"),
  _gpt_contract_row("unified_convergence_decision", "model_input_repair_cells", "model_input_repair_cells[].lever_id", "lever_id", "string", is_array_item=True, parent_field_path="model_input_repair_cells", validation_kind="mapping_table_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("unified_convergence_decision", "model_input_repair_cells", "model_input_repair_cells[].quarter_index", "quarter_index", "integer", is_array_item=True, parent_field_path="model_input_repair_cells", validation_kind="quarter_index_1_to_20"),
  _gpt_contract_row("unified_convergence_decision", "model_input_repair_cells", "model_input_repair_cells[].value", "value", "number", is_array_item=True, parent_field_path="model_input_repair_cells", normalization_kind="field_type_numeric_contract"),
  _gpt_contract_row("unified_convergence_decision", "model_input_repair_cells", "model_input_repair_cells[].rationale", "rationale", "string", is_array_item=True, parent_field_path="model_input_repair_cells"),
  _gpt_contract_row("cash_strategy_review", "root", "recommendation_mode", "recommendation_mode", "enum", validation_kind="enum", enum_values=["maintain", "adjust"]),
  _gpt_contract_row("cash_strategy_review", "root", "executive_summary", "executive_summary", "string"),
  _gpt_contract_row("cash_strategy_review", "root", "capital_posture_summary", "capital_posture_summary", "string"),
  _gpt_contract_row("cash_strategy_review", "root", "funding_mix_summary", "funding_mix_summary", "string"),
  _gpt_contract_row("cash_strategy_review", "root", "confidence", "confidence", "enum", validation_kind="enum", enum_values=["low", "medium", "high"]),
  _gpt_contract_row(
    "cash_strategy_review",
    "root",
    "quarter_funding_plan",
    "quarter_funding_plan",
    "array",
    item_contract_grid_name="quarter_funding_plan",
    horizon_rule="q1_to_q20_required_funding_rows",
    validation_kind="cash_policy_grid",
    lookup_source="post_intake_cash_policy_lookup",
    prompt_required_instruction="Cash GPT only fills quarters with required funding gaps; validation still evaluates the full Q1 through Q20 cash horizon.",
  ),
  _gpt_contract_row(
    "cash_strategy_review",
    "root",
    "recommended_adjustments",
    "recommended_adjustments",
    "array",
    item_contract_grid_name="recommended_adjustments",
    horizon_rule="q1_to_q20_cash_review_rows",
    validation_kind="cash_adjustment_grid",
    lookup_source="post_intak_mapping_lookup",
    prompt_required_instruction="Cash adjustment rows may be a Q1 through Q20 subset, and every row must use cash-authorized mapping-table levers only.",
  ),
  _gpt_contract_row("cash_strategy_review", "recommended_adjustments", "recommended_adjustments[].lever_id", "lever_id", "string", is_array_item=True, parent_field_path="recommended_adjustments", validation_kind="cash_adjustment_lever_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("cash_strategy_review", "recommended_adjustments", "recommended_adjustments[].timing_start_q", "timing_start_q", "integer", is_array_item=True, parent_field_path="recommended_adjustments", validation_kind="quarter_index_1_to_20"),
  _gpt_contract_row("cash_strategy_review", "recommended_adjustments", "recommended_adjustments[].timing_end_q", "timing_end_q", "integer", is_array_item=True, parent_field_path="recommended_adjustments", validation_kind="quarter_index_1_to_20"),
  _gpt_contract_row("cash_strategy_review", "recommended_adjustments", "recommended_adjustments[].exact_value", "exact_value", "integer_currency", is_array_item=True, parent_field_path="recommended_adjustments", normalization_kind="integer_currency"),
  _gpt_contract_row("cash_strategy_review", "recommended_adjustments", "recommended_adjustments[].business_reason", "business_reason", "string", is_array_item=True, parent_field_path="recommended_adjustments"),
  _gpt_contract_row("cash_strategy_review", "quarter_funding_plan", "quarter_funding_plan[].quarter_index", "quarter_index", "integer", is_array_item=True, parent_field_path="quarter_funding_plan", validation_kind="quarter_index_1_to_20"),
  _gpt_contract_row("cash_strategy_review", "quarter_funding_plan", "quarter_funding_plan[].required_funding_gap", "required_funding_gap", "integer_currency", is_array_item=True, parent_field_path="quarter_funding_plan", normalization_kind="integer_currency"),
  _gpt_contract_row("cash_strategy_review", "quarter_funding_plan", "quarter_funding_plan[].expected_buffer", "expected_buffer", "integer_currency", is_array_item=True, parent_field_path="quarter_funding_plan", normalization_kind="integer_currency"),
  _gpt_contract_row("cash_strategy_review", "quarter_funding_plan", "quarter_funding_plan[].expected_ending_cash_after_actions", "expected_ending_cash_after_actions", "integer_currency", is_array_item=True, parent_field_path="quarter_funding_plan", normalization_kind="integer_currency"),
  _gpt_contract_row("cash_strategy_review", "quarter_funding_plan", "quarter_funding_plan[].funding_sources", "funding_sources", "array", is_array_item=True, parent_field_path="quarter_funding_plan", min_items=1, max_items=1, item_contract_grid_name="funding_sources", validation_kind="cash_funding_source_grid", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("cash_strategy_review", "quarter_funding_plan", "quarter_funding_plan[].business_reason", "business_reason", "string", is_array_item=True, parent_field_path="quarter_funding_plan"),
  _gpt_contract_row("cash_strategy_review", "funding_sources", "funding_sources[].lever_id", "lever_id", "string", is_array_item=True, parent_field_path="funding_sources", validation_kind="cash_funding_lever_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("cash_strategy_review", "funding_sources", "funding_sources[].amount", "amount", "integer_currency", is_array_item=True, parent_field_path="funding_sources", normalization_kind="integer_currency"),
  _gpt_contract_row("quarter_grid_probe", "root", "summary", "summary", "string", contract_phase="initial_grid"),
  _gpt_contract_row(
    "quarter_grid_probe",
    "root",
    "rows",
    "rows",
    "array",
    min_items=1,
    item_contract_grid_name="rows",
    contract_phase="initial_grid",
    horizon_rule="q1_to_q20_model_input_state",
    validation_kind="quarter_grid_probe_rows",
    lookup_source="post_intak_mapping_lookup",
    prompt_required_instruction="Return only the requested row_ids in this batch. Each row must include exactly one value for every forecast quarter Q1 through Q20.",
  ),
  _gpt_contract_row("quarter_grid_probe", "rows", "rows[].row_id", "row_id", "string", is_array_item=True, parent_field_path="rows", validation_kind="quarter_grid_allowed_row_id", must_match_lookup=False, notes="Runtime schema override supplies the allowed row_id enum for the current requested batch."),
  _gpt_contract_row("quarter_grid_probe", "rows", "rows[].row_type", "row_type", "enum", is_array_item=True, parent_field_path="rows", validation_kind="enum", enum_values=["lever", "output"]),
  _gpt_contract_row(
    "quarter_grid_probe",
    "rows",
    "rows[].quarter_values",
    "quarter_values",
    "array",
    is_array_item=True,
    parent_field_path="rows",
    min_items=20,
    max_items=20,
    item_contract_grid_name="quarter_values",
    horizon_rule="q1_to_q20_exactly_once",
    validation_kind="required_20q_grid",
  ),
  _gpt_contract_row("quarter_grid_probe", "quarter_values", "quarter_values[].quarter_index", "quarter_index", "integer", is_array_item=True, parent_field_path="quarter_values", min_value=1, max_value=20, horizon_rule="q1_to_q20_exactly_once", validation_kind="quarter_index_1_to_20"),
  _gpt_contract_row("quarter_grid_probe", "quarter_values", "quarter_values[].value", "value", "number", is_array_item=True, parent_field_path="quarter_values", normalization_kind="field_type_numeric_contract", validation_kind="quarter_grid_cell_value"),
  _gpt_contract_row("realism_memo", "root", "status", "status", "enum", contract_phase="post_intake_realism_memo", validation_kind="enum", enum_values=["ready"]),
  _gpt_contract_row(
    "realism_memo",
    "root",
    "issues",
    "issues",
    "array",
    max_items=4,
    item_contract_grid_name="issues",
    contract_phase="post_intake_realism_memo",
    validation_kind="realism_memo_issue_grid",
    prompt_required_instruction="Return at most four issue rows. Only use issue codes represented in the table-backed issue/mapping system.",
  ),
  _gpt_contract_row("realism_memo", "issues", "issues[].issue_code", "issue_code", "enum", is_array_item=True, parent_field_path="issues", validation_kind="enum", enum_values=["capacity_support_mismatch", "p_and_l_flatline", "cost_structure_mismatch"], lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("realism_memo", "issues", "issues[].issue", "issue", "string", is_array_item=True, parent_field_path="issues"),
  _gpt_contract_row("realism_memo", "issues", "issues[].detail", "detail", "string", is_array_item=True, parent_field_path="issues"),
  _gpt_contract_row("unified_convergence_verification", "root", "overall_assessment", "overall_assessment", "enum", validation_kind="enum", enum_values=["all_resolved", "partially_resolved", "not_resolved"]),
  _gpt_contract_row("unified_convergence_verification", "root", "executive_summary", "executive_summary", "string"),
  _gpt_contract_row("unified_convergence_verification", "root", "issue_results", "issue_results", "array", min_items=1, item_contract_grid_name="issue_results"),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].issue_code", "issue_code", "string", is_array_item=True, parent_field_path="issue_results"),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].status", "status", "enum", is_array_item=True, parent_field_path="issue_results", validation_kind="enum", enum_values=["resolved", "partially_resolved", "not_resolved"]),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].remaining_issue_materiality", "remaining_issue_materiality", "enum", is_array_item=True, parent_field_path="issue_results", validation_kind="enum", enum_values=["immaterial", "material"]),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].remaining_issue_severity_score", "remaining_issue_severity_score", "integer", is_array_item=True, parent_field_path="issue_results", min_value=0, max_value=100),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].verification_reason", "verification_reason", "string", is_array_item=True, parent_field_path="issue_results"),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].remaining_problem_quarters", "remaining_problem_quarters", "array", is_array_item=True, parent_field_path="issue_results", horizon_rule="q1_to_q20_subset"),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].next_required_lever_ids", "next_required_lever_ids", "array", is_array_item=True, parent_field_path="issue_results", validation_kind="mapping_table_member", lookup_source="post_intak_mapping_lookup"),
  _gpt_contract_row("unified_convergence_verification", "issue_results", "issue_results[].observed_improvement_summary", "observed_improvement_summary", "string", is_array_item=True, parent_field_path="issue_results"),
]


_DEFAULT_GPT_CONTEXT_ROWS: List[Dict[str, Any]] = [
  _gpt_context_row(
    "unified_convergence_decision",
    "__openai_request_budget__",
    context_group="budget",
    source_kind="policy",
    transform_kind="request_char_budget",
    include_phase="planner",
    required=True,
    include_in_prompt=False,
    max_chars=220000,
    failure_code="unified_convergence_gpt_context_payload_budget_exceeded",
    notes="Hard pre-OpenAI request budget. This prevents large strict convergence payloads from burning the full cycle timeout.",
  ),
  _gpt_context_row("unified_convergence_decision", "contract_version", context_group="identity", include_phase="planner"),
  _gpt_context_row("unified_convergence_decision", "packet_role", context_group="identity", include_phase="planner"),
  _gpt_context_row("unified_convergence_decision", "draft_id", context_group="identity", include_phase="planner"),
  _gpt_context_row("unified_convergence_decision", "business_name", context_group="identity", include_phase="planner"),
  _gpt_context_row("unified_convergence_decision", "convergence_engine_contract", context_group="contract", include_phase="planner"),
  _gpt_context_row("unified_convergence_decision", "convergence_contract_policy", context_group="contract", include_phase="planner"),
  _gpt_context_row("unified_convergence_decision", "planning_mode_context", context_group="business_world", include_phase="planner"),
  _gpt_context_row(
    "unified_convergence_decision",
    "business_world_contract",
    context_group="business_world",
    include_phase="planner",
    transform_kind="compact_business_world_contract",
    notes="Compact stage, planning-mode, ramp, and derived-driver policy context used by convergence. This is table-approved context, not a freeform legacy packet.",
  ),
  _gpt_context_row("unified_convergence_decision", "selected_cash_strategy", context_group="business_world", include_phase="planner"),
  _gpt_context_row("unified_convergence_decision", "convergence_scorecard", context_group="diagnostics", include_phase="planner", required=False),
  _gpt_context_row(
    "unified_convergence_decision",
    "repair_envelope_packets",
    context_group="issues",
    include_phase="planner",
    transform_kind="compact_issue_repair_envelope",
    max_items=4,
  ),
  _gpt_context_row("unified_convergence_decision", "retry_packet", context_group="retry", include_phase="planner", required=False),
  _gpt_context_row("unified_convergence_decision", "repair_contract_violation", context_group="retry", include_phase="planner", required=False),
  _gpt_context_row(
    "unified_convergence_decision",
    "invalid_response_to_repair",
    context_group="retry",
    include_phase="planner",
    required=False,
    transform_kind="compact_invalid_response_to_repair",
    notes="Retry context must include only compact invalid response diagnostics, not the full malformed GPT payload.",
  ),
  _gpt_context_row("unified_convergence_decision", "issue_coverage_requirements", context_group="retry", include_phase="planner", required=False),
  _gpt_context_row("unified_convergence_decision", "contract_repair_instruction", context_group="retry", include_phase="planner", required=False),
  _gpt_context_row("unified_convergence_decision", "required_target_quarters", context_group="horizon", include_phase="planner", max_items=20),
  _gpt_context_row(
    "unified_convergence_decision",
    "locked_target_fill_grid",
    context_group="locked_grid",
    include_phase="planner",
    transform_kind="compact_locked_target_fill_grid",
  ),
  _gpt_context_row("unified_convergence_decision", "locked_targets_by_quarter_response_template", context_group="locked_grid", include_phase="planner"),
  _gpt_context_row(
    "unified_convergence_decision",
    "full_horizon_model_input_repair_contract",
    context_group="locked_grid",
    include_phase="planner",
    transform_kind="compact_full_horizon_repair_contract",
    max_items=240,
    notes="Authoritative full-horizon editable cell contract. Runtime compacts rows but keeps every required editable cell.",
  ),
  _gpt_context_row("unified_convergence_decision", "issue_mapping_gate", context_group="mapping", include_phase="planner"),
  _gpt_context_row(
    "unified_convergence_decision",
    "prior_numeric_solver_feedback",
    context_group="feedback",
    include_phase="planner",
    required=False,
    transform_kind="compact_numeric_solver_feedback",
  ),
  _gpt_context_row("unified_convergence_decision", "recommended_primary_target_metric_keys", context_group="solver", include_phase="planner", required=False),
  _gpt_context_row("unified_convergence_decision", "planner_model_input_packet", context_group="model_input", include_phase="planner"),
  _gpt_context_row(
    "unified_convergence_decision",
    "gpt_contract_field_spec",
    context_group="contract",
    include_phase="planner",
    required=False,
    include_in_prompt=False,
    notes="The strict OpenAI schema and SQL contract table are authoritative; do not duplicate the full field spec into the prompt payload.",
  ),
  _gpt_context_row("unified_convergence_decision", "payload_size_summary", context_group="diagnostics", include_phase="planner", required=False, include_in_prompt=False),

  _gpt_context_row(
    "unified_convergence_decision",
    "__openai_request_budget__",
    context_group="budget",
    source_kind="policy",
    transform_kind="request_char_budget",
    include_phase="planner_retry",
    required=True,
    include_in_prompt=False,
    max_chars=170000,
    failure_code="unified_convergence_retry_gpt_context_payload_budget_exceeded",
    notes="Retry must be compact enough to correct malformed contracts inside the 180-second cycle. The full initial planner prompt is intentionally not reused for retry.",
  ),
  _gpt_context_row("unified_convergence_decision", "repair_contract_violation", context_group="retry", include_phase="planner_retry"),
  _gpt_context_row("unified_convergence_decision", "required_target_quarters", context_group="horizon", include_phase="planner_retry", max_items=20),
  _gpt_context_row(
    "unified_convergence_decision",
    "locked_target_fill_grid",
    context_group="locked_grid",
    include_phase="planner_retry",
    transform_kind="compact_locked_target_fill_grid",
  ),
  _gpt_context_row(
    "unified_convergence_decision",
    "full_horizon_model_input_repair_contract",
    context_group="locked_grid",
    include_phase="planner_retry",
    transform_kind="compact_full_horizon_repair_contract",
    max_items=240,
  ),
  _gpt_context_row("unified_convergence_decision", "recommended_primary_target_metric_keys", context_group="solver", include_phase="planner_retry", required=False),
  _gpt_context_row(
    "unified_convergence_decision",
    "invalid_response_to_repair",
    context_group="retry",
    include_phase="planner_retry",
    required=False,
    transform_kind="compact_invalid_response_to_repair",
    notes="Retry context must include only compact invalid response diagnostics, not the full malformed GPT payload.",
  ),
  _gpt_context_row("unified_convergence_decision", "issue_coverage_requirements", context_group="retry", include_phase="planner_retry", required=False),
  _gpt_context_row("unified_convergence_decision", "business_world_contract", context_group="business_world", include_phase="planner_retry"),
  _gpt_context_row("unified_convergence_decision", "contract_repair_instruction", context_group="retry", include_phase="planner_retry"),

  _gpt_context_row(
    "stage_ramp_contract",
    "__openai_request_budget__",
    context_group="budget",
    source_kind="policy",
    transform_kind="request_char_budget",
    include_phase="pre_convergence",
    include_in_prompt=False,
    max_chars=180000,
    failure_code="stage_ramp_gpt_context_payload_budget_exceeded",
  ),
  _gpt_context_row("stage_ramp_contract", "business_identity", context_group="business_world", include_phase="pre_convergence"),
  _gpt_context_row("stage_ramp_contract", "business_context", context_group="business_world", include_phase="pre_convergence"),
  _gpt_context_row("stage_ramp_contract", "financial_context", context_group="financials", include_phase="pre_convergence"),
  _gpt_context_row("stage_ramp_contract", "r_and_d_applicability", context_group="policy", include_phase="pre_convergence"),
  _gpt_context_row("stage_ramp_contract", "stage_profitability_policy", context_group="policy", include_phase="pre_convergence"),
  _gpt_context_row("stage_ramp_contract", "revenue_driver_context", context_group="model_input", include_phase="pre_convergence"),
  _gpt_context_row("stage_ramp_contract", "current_model_snapshot", context_group="model_input", include_phase="pre_convergence"),
  _gpt_context_row("stage_ramp_contract", "previous_contract_failure", context_group="retry", include_phase="pre_convergence", required=False, notes="Only present on a pre-convergence contract retry. Contains the table-backed validation failure and invalid response excerpt so GPT can correct its own decision without Python mutating it."),
  _gpt_context_row(
    "stage_ramp_contract",
    "contract_field_spec",
    context_group="contract",
    include_phase="pre_convergence",
    required=False,
    include_in_prompt=False,
    notes="The stage-ramp prompt is rendered directly from the SQL contract table; do not duplicate the field spec into the user payload.",
  ),
  _gpt_context_row(
    "stage_ramp_contract",
    "required_response_shape",
    context_group="contract",
    include_phase="pre_convergence",
    required=False,
    include_in_prompt=False,
    notes="The strict OpenAI schema and rendered contract prompt already define the response shape.",
  ),

  _gpt_context_row(
    "balance_sheet_contextual_seed",
    "__openai_request_budget__",
    context_group="budget",
    source_kind="policy",
    transform_kind="request_char_budget",
    include_phase="pre_convergence",
    include_in_prompt=False,
    max_chars=80000,
    failure_code="balance_sheet_contextual_seed_gpt_context_payload_budget_exceeded",
  ),
  _gpt_context_row("balance_sheet_contextual_seed", "business_identity", context_group="business_world", include_phase="pre_convergence"),
  _gpt_context_row("balance_sheet_contextual_seed", "business_context", context_group="business_world", include_phase="pre_convergence"),
  _gpt_context_row("balance_sheet_contextual_seed", "financial_context", context_group="financials", include_phase="pre_convergence"),
  _gpt_context_row("balance_sheet_contextual_seed", "seed_candidates", context_group="mapping", source_kind="sql_lookup", source_path="post_intak_mapping_lookup.balance_sheet_contextual_seed_candidates", include_phase="pre_convergence", notes="Rows Python requires GPT to decide from business context/type. Mapping defaults are not used as numeric fallbacks."),
  _gpt_context_row("balance_sheet_contextual_seed", "current_model_snapshot", context_group="model_input", include_phase="pre_convergence", required=False),
  _gpt_context_row("balance_sheet_contextual_seed", "hard_rules", context_group="contract", include_phase="pre_convergence"),

  _gpt_context_row(
    "payroll_headcount_schedule",
    "__openai_request_budget__",
    context_group="budget",
    source_kind="policy",
    transform_kind="request_char_budget",
    include_phase="pre_convergence",
    include_in_prompt=False,
    max_chars=120000,
    failure_code="payroll_headcount_gpt_context_payload_budget_exceeded",
  ),
  _gpt_context_row("payroll_headcount_schedule", "business_identity", context_group="business_world", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "business_context", context_group="business_world", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "people_staffing_context", context_group="business_world", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "oews_title_catalog", context_group="wage_title_lookup", source_kind="python_derived_from_oews", source_path="oews_state_wages via business_naics_6", include_phase="pre_convergence", notes="Python builds the full NAICS OEWS title catalog before GPT chooses supporting-staff rows. GPT must select oews_occ_title values from title_candidates[].occ_title exactly. Staffing families and categories are not part of the active payroll contract."),
  _gpt_context_row("payroll_headcount_schedule", "financial_context", context_group="financials", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "stage_ramp_contract", context_group="policy", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "payroll_decision_options", context_group="policy", source_kind="sql_lookup", source_path="post_intake_headcount_policy_lookup.capacity_labor_model_values + labor_intensity_class_values + wage_positioning_multiplier + payroll_revenue_sanity_bounds", include_phase="pre_convergence", notes="Compact table-rendered option rows GPT must choose from. GPT owns the payroll business judgment and positive capacity productivity assumption; Python validates exact choices and does not substitute defaults."),
  _gpt_context_row("payroll_headcount_schedule", "payroll_feasibility_mapping", context_group="mapping", source_kind="sql_lookup", source_path="post_intak_mapping_lookup.repair_direction_rules_json", include_phase="pre_convergence", notes="Table-backed lever direction rules for payroll/revenue feasibility. GPT must use these rows to decide directional movement and must not invent causal direction."),
  _gpt_context_row("payroll_headcount_schedule", "payroll_headcount_policy", context_group="policy", source_kind="sql_lookup", source_path="post_intake_headcount_policy_lookup.default", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "payroll_capacity_guardrails", context_group="policy", source_kind="python_derived_from_sql_lookup", source_path="post_intake_headcount_policy_lookup.default + model_input_json revenue drivers", include_phase="pre_convergence", notes="Legacy context key retained for contract compatibility; content is context only. GPT chooses productivity and FTE. Python derives supported Capacity from payroll FTE and does not validate FTE against a pre-existing capacity demand floor."),
  _gpt_context_row("payroll_headcount_schedule", "payroll_capacity_grid", context_group="policy", source_kind="python_derived_from_sql_lookup", source_path="post_intake_headcount_policy_lookup.default + model_input_json capacity/utilization", include_phase="pre_convergence", max_items=20, notes="Q1-Q20 capacity/utilization context for payroll business judgment. This is not a staffing floor; payroll FTE is the causal source of supported Capacity."),
  _gpt_context_row("payroll_headcount_schedule", "current_model_snapshot", context_group="model_input", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "revenue_driver_context", context_group="model_input", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "previous_contract_failure", context_group="retry", include_phase="pre_convergence", required=False, notes="Only present on payroll schedule retry. Contains the table-backed validation failure and invalid response excerpt so GPT corrects its staffing schedule without Python mutating it."),
  _gpt_context_row("payroll_headcount_schedule", "contract_field_spec", context_group="contract", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "required_response_shape", context_group="contract", include_phase="pre_convergence"),

  _gpt_context_row(
    "cash_strategy_review",
    "__openai_request_budget__",
    context_group="budget",
    source_kind="policy",
    transform_kind="request_char_budget",
    include_phase="cash_pass",
    include_in_prompt=False,
    max_chars=260000,
    failure_code="cash_strategy_gpt_context_payload_budget_exceeded",
  ),
  _gpt_context_row("cash_strategy_review", "cash_policy", context_group="cash_policy", include_phase="cash_pass", required=False),
  _gpt_context_row("cash_strategy_review", "cash_envelope", context_group="cash_envelope", include_phase="cash_pass", required=False),
  _gpt_context_row("cash_strategy_review", "liquidity_violation_grid", context_group="cash_envelope", include_phase="cash_pass", required=False),
  _gpt_context_row("cash_strategy_review", "debt_schedule_summary", context_group="debt_schedule", include_phase="cash_pass", required=False),
  _gpt_context_row("cash_strategy_review", "funding_action_cells", context_group="locked_grid", include_phase="cash_pass", required=False),
  _gpt_context_row("cash_strategy_review", "gpt_contract_field_spec", context_group="contract", include_phase="cash_pass", required=False),

  _gpt_context_row("quarter_grid_probe", "planning_mode", context_group="business_world", include_phase="initial_grid", required=False),
  _gpt_context_row("quarter_grid_probe", "use_real_strategy_prompt", context_group="prompt_policy", include_phase="initial_grid", required=False),
  _gpt_context_row("quarter_grid_probe", "realism_memo_present", context_group="diagnostics", include_phase="initial_grid", required=False),
  _gpt_context_row("quarter_grid_probe", "allowed_row_ids", context_group="locked_grid", include_phase="initial_grid", required=False, max_items=250),
  _gpt_context_row("quarter_grid_probe", "quarter_grid_horizon", context_group="horizon", include_phase="initial_grid", required=False),

  _gpt_context_row("realism_memo", "ops_json", context_group="business_world", include_phase="reviewer", required=False, max_chars=20000),
  _gpt_context_row("realism_memo", "financials_json", context_group="financials", include_phase="reviewer", required=False, max_chars=20000),
  _gpt_context_row("realism_memo", "solved_model_input_json", context_group="model_input", include_phase="reviewer", required=False, max_chars=80000),
  _gpt_context_row("realism_memo", "solved_finmo_json", context_group="finmo", include_phase="reviewer", required=False, max_chars=80000),
]


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _clean_bool(value: Any, *, default: bool = False) -> bool:
  if isinstance(value, bool):
    return value
  if value is not None and not isinstance(value, str):
    try:
      numeric = float(value)
      if numeric == 0.0:
        return False
      if numeric == 1.0:
        return True
    except Exception:
      pass
  raw = _clean_text(value).lower()
  if not raw:
    return bool(default)
  if raw in {"0", "false", "no", "n", "inactive", "disabled"}:
    return False
  return raw in {"1", "true", "yes", "y", "active"}


def _split_tokens(value: Any) -> List[str]:
  raw = _clean_text(value).lower()
  if not raw:
    return []
  normalized = raw.replace(";", "|").replace(",", "|")
  return [item.strip() for item in normalized.split("|") if item.strip()]


def _json_list(value: Any) -> List[str]:
  if isinstance(value, list):
    return [_clean_text(item) for item in value if _clean_text(item)]
  raw = _clean_text(value)
  if not raw:
    return []
  try:
    parsed = json.loads(raw)
  except Exception:
    return _split_tokens(raw)
  if not isinstance(parsed, list):
    return []
  return [_clean_text(item) for item in parsed if _clean_text(item)]


def _json_dumps_list(value: Any) -> str:
  return json.dumps(_json_list(value), ensure_ascii=True, separators=(",", ":"))


def stage_planning_ramp_policy(
  *,
  stage_family: Any,
  planning_mode: Any,
  planning_mode_reason: Any = "",
  business_stage: Any = "",
  business_naics: Any = None,
) -> Dict[str, Any]:
  """Deterministic lifecycle policy shared by ramp GPT, validation, and quarter-grid.

  Module 2 Task 2.6 — when `business_naics` is supplied, the policy payload
  carries NAICS-cascaded `qoq_growth_band` metadata for downstream consumers.

  Module 3 v3 status of the legacy hardcodes that used to live here:

  - The hardcoded "2 to 15" maintenance-capex prose bound was DELETED in v1
    (Module 3 Task 3.3) — the gpt_contract_lookup row now carries
    `naics_baseline_metric_key="maintenance_capex_percent_of_revenue"` and
    the prompt-build pipeline injects the NAICS band per business.

  - The hardcoded universal cost-ratio caps on `stage_ramp_contract`
    (cogs_target/cogs_max/marketing_max/rd_max/ga_max/lease_max — the
    `{"type": "number", "minimum": 0, "maximum": 1}` field-schema overrides
    in `_stage_ramp_contract_schema`) were DELETED in v3. Those fields are
    now NAICS-bound at the contract row level via Module 3 Task 3.3.

  - The hardcoded `target_payroll_percent_of_revenue` bound (0.01..0.90)
    on `payroll_headcount_schedule` is still the mapping outer envelope
    but a `naics_baseline_metric_key="payroll_percent_of_revenue"` row was
    added in v3, so prompt-build narrows it to the NAICS band when
    `business_naics` flows through to the schema build.

  - `early_revenue_share_ceiling_of_late_run_rate` (Q1-Q4 fractions like
    {Q1: 0.25, Q2: 0.40, Q3: 0.60, Q4: 0.80}) STAYS in this function. They
    are NOT a universal-business hardcode in the same sense as the cost
    bounds above — they're hand-calibrated stage-shape guidance for the
    quarter-grid prompt context (revenue as a share of late-horizon
    run-rate). The NAICS qoq metric (`startup_qoq_growth_typical` etc.)
    measures employment growth via Census BDS, which does not translate
    cleanly to "share of late run rate" via a closed-form formula:
    applying `Qn_share = 1/(1+qoq)^(20-n)` to BDS values produces share
    fractions in the 1-5% range for startups (BDS startup employment
    qoq is ~50%) — far tighter than is operationally realistic.
    Replacing these fractions with NAICS-derived values needs either a
    different upstream metric (revenue ramp shape per NAICS-and-stage) or
    an empirical recalibration. Documented as a future module's work.
  """
  family = _clean_text(stage_family).lower() or "operational"
  raw_mode = _clean_text(planning_mode).lower()
  mode = raw_mode if raw_mode in _POST_INTAKE_PLANNING_MODES else "turnaround"
  reason = _clean_text(planning_mode_reason).lower()
  normalized_stage = _clean_text(business_stage).lower()
  distress_tokens = ("distress", "rescue", "insolven", "survival", "turnaround")
  explicit_distress_context = bool(
    mode == "turnaround"
    or any(token in reason for token in distress_tokens)
  )

  # Module 2 Task 2.6 — pull the NAICS-typical QoQ growth band when caller
  # supplied a NAICS code. Falls through silently to None when the resolver
  # is unavailable (e.g., during table-init paths) or the cascade returns
  # no_coverage.
  qoq_metric_key = {
    "startup": "startup_qoq_growth_typical",
    "early": "early_qoq_growth_typical",
  }.get(family, "mature_qoq_growth_typical")
  qoq_growth_band: Optional[Dict[str, Any]] = None
  naics_clean = _clean_text(business_naics)
  if naics_clean:
    try:
      from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
        post_intake_industry_baseline_for_naics,
      )
      qoq_growth_band = post_intake_industry_baseline_for_naics(
        metric_key=qoq_metric_key, naics_6=naics_clean
      )
    except Exception:
      qoq_growth_band = None

  policy: Dict[str, Any] = {
    "policy_version": "stage_planning_ramp_policy_v1",
    "business_stage": normalized_stage,
    "stage_family": family,
    "planning_mode": mode,
    "planning_mode_reason": reason,
    "explicit_distress_context": explicit_distress_context,
    "profitability_postures": ["loss_allowed", "improving_losses", "near_breakeven", "positive"],
    "stage_rules": [],
    "validator_rules": {
      "q10_min_net_income_margin_floor": -0.02,
      "q11_to_q20_min_net_income_margin_floor": 0.0,
    },
    # Module 2 Task 2.6 — NAICS metadata for downstream consumers.
    "naics_qoq_metric_key": qoq_metric_key,
    "naics_level_used": (qoq_growth_band or {}).get("naics_level_used"),
    "confidence_tier_used": (qoq_growth_band or {}).get("confidence_tier"),
    "qoq_growth_band": (
      {
        "metric_key": qoq_growth_band.get("metric_key"),
        "benchmark_min": qoq_growth_band.get("benchmark_min"),
        "benchmark_target": qoq_growth_band.get("benchmark_target"),
        "benchmark_max": qoq_growth_band.get("benchmark_max"),
        "data_source": qoq_growth_band.get("data_source"),
        "trust_flag": qoq_growth_band.get("trust_flag"),
      }
      if isinstance(qoq_growth_band, dict)
      else None
    ),
  }

  if family == "startup":
    policy["stage_rules"] = [
      "Pre-revenue is a binding lifecycle state, not descriptive background.",
      "Q1-Q4 must read like launch and ramp, not a mature operating run-rate.",
      "Do not start Q1 at or near the late-horizon revenue, utilization, or capacity run-rate.",
      "Capacity may exist ahead of demand, but revenue should come from staged utilization and price realization rather than instant full-scale operations.",
      "Revenue, utilization, capacity, staffing support, capex, and profitability must ramp together.",
      "Because Payroll is calculated through the GPT-selected headcount schedule, revenue, utilization, capacity, and staffed FTE must stay coherent.",
      "Early losses or modest profitability may be realistic; instant mature profitability is not the goal.",
    ]
    policy["early_revenue_share_ceiling_of_late_run_rate"] = {
      "Q1": 0.25,
      "Q2": 0.40,
      "Q3": 0.60,
      "Q4": 0.80,
    }
  elif family == "early":
    policy["stage_rules"] = [
      "Early-stage is a binding lifecycle state, not descriptive background.",
      "Q1-Q4 should still show a ramp and absorption curve.",
      "Do not jump immediately to a mature run-rate without operating evidence.",
      "Losses may be acceptable early if funded and improving.",
      "Loss_allowed posture is not acceptable after Q8; by then losses must be improving or better.",
    ]
    policy["early_revenue_share_ceiling_of_late_run_rate"] = {
      "Q1": 0.55,
      "Q2": 0.70,
      "Q3": 0.85,
    }
    policy["validator_rules"]["loss_allowed_latest_quarter"] = 8
  elif explicit_distress_context:
    policy["stage_rules"] = [
      "Treat the business as already operating but in turnaround/distress posture.",
      "Losses may exist early, but they must improve under the ramp contract rather than persist as an unresolved mature loss state.",
      "Do not model a mature company as a launch-stage startup; operational scale already exists even when profitability is damaged.",
      "Capacity expansion must be supported by operating recovery and stage reality.",
    ]
    policy["validator_rules"]["operational_distress_allows_early_losses"] = True
  else:
    policy["profitability_postures"] = ["near_breakeven", "positive"]
    policy["stage_rules"] = [
      "Treat the business as already operating unless facts contradict that.",
      "Avoid fantasy resets; mature operating losses are not acceptable without explicit turnaround/distress planning mode.",
      "The operating path should generally begin near breakeven or profitable; do not model an established company like a startup launch.",
      "By Q5 the plan must use a positive profitability posture.",
      "Capacity expansion must be supported by operating earnings and stage reality.",
    ]
    policy["validator_rules"].update(
      {
        "operational_requires_nonnegative_from_q1": True,
        "operational_requires_positive_from_q5": True,
        "q1_to_q20_min_net_income_margin_floor": 0.0,
        "q5_to_q20_min_net_income_margin_floor": 0.02,
      }
    )
  return policy


def _normalized_metric_id_from_field(financial_model_field: Any) -> str:
  field = _clean_text(financial_model_field)
  if not field.startswith(_FINMO_ROW_PREFIX):
    return ""
  metric_name = field[len(_FINMO_ROW_PREFIX):].strip().lower()
  return metric_name


def _default_target_value_kind(financial_model_field: Any) -> str:
  metric_name = _normalized_metric_id_from_field(financial_model_field)
  if not metric_name:
    return "number"
  if metric_name.endswith("_days") or metric_name in {"days_in_quarter"}:
    return "day_count"
  if metric_name.endswith("_rate") or metric_name.endswith("_ratio") or metric_name.endswith("_margin"):
    return "ratio"
  return "currency"


def _default_precision_for_value_kind(value_kind: Any) -> Dict[str, Any]:
  kind = _clean_text(value_kind).lower()
  if kind in {"currency", "quarter_currency", "money", "count", "day_count", "integer"}:
    return {
      "rounding_kind": "nearest_integer",
      "decimal_places": 0,
      "precision_unit": 1.0,
    }
  if kind in {"ratio", "percentage", "percent", "rate", "interest_rate"}:
    return {
      "rounding_kind": "nearest_decimal",
      "decimal_places": 2,
      "precision_unit": 0.01,
    }
  return {
    "rounding_kind": "none",
    "decimal_places": None,
    "precision_unit": 0.0,
  }


def _normalize_precision_metadata(
  *,
  value_kind: Any,
  rounding_kind: Any = "",
  decimal_places: Any = None,
) -> Dict[str, Any]:
  default = _default_precision_for_value_kind(value_kind)
  resolved_rounding = _clean_text(rounding_kind).lower() or str(default.get("rounding_kind") or "none")
  resolved_decimal_places: Optional[int]
  try:
    resolved_decimal_places = (
      int(decimal_places)
      if decimal_places is not None and str(decimal_places).strip() != ""
      else default.get("decimal_places")
    )
  except Exception:
    resolved_decimal_places = default.get("decimal_places")
  if resolved_rounding in {"nearest_integer", "nearest_dollar"}:
    resolved_decimal_places = 0
  if resolved_rounding == "nearest_decimal" and resolved_decimal_places is None:
    resolved_decimal_places = 2
  if resolved_rounding == "none":
    resolved_decimal_places = None
  precision_unit = 0.0
  if resolved_rounding in {"nearest_integer", "nearest_dollar"}:
    precision_unit = 1.0
  elif resolved_rounding == "nearest_decimal" and resolved_decimal_places is not None:
    precision_unit = float(10 ** (-int(resolved_decimal_places)))
  return {
    "value_kind": _clean_text(value_kind).lower(),
    "rounding_kind": resolved_rounding,
    "decimal_places": resolved_decimal_places,
    "precision_unit": precision_unit,
  }


def _round_by_precision_metadata(
  value: Any,
  *,
  precision: Dict[str, Any],
  bound_side: str = "",
) -> Any:
  try:
    numeric = float(value)
  except Exception:
    return value
  rounding_kind = _clean_text(precision.get("rounding_kind")).lower()
  decimal_places = precision.get("decimal_places")
  normalized_bound_side = _clean_text(bound_side).lower()
  if rounding_kind in {"nearest_integer", "nearest_dollar"}:
    if normalized_bound_side == "minimum":
      return int(math.ceil(numeric))
    if normalized_bound_side == "maximum":
      return int(math.floor(numeric))
    return int(round(numeric))
  if rounding_kind == "nearest_decimal" and decimal_places is not None:
    return round(numeric, int(decimal_places))
  return float(numeric)


def _normalized_lookup_key(lever_id: Any) -> str:
  raw = _clean_text(lever_id)
  if raw.startswith("revenue::"):
    if raw.endswith("::Capacity"):
      return f"{_REVENUE_PATTERN_PREFIX}Capacity"
    if raw.endswith("::Unit Price"):
      return f"{_REVENUE_PATTERN_PREFIX}Unit Price"
    if raw.endswith("::Utilization"):
      return f"{_REVENUE_PATTERN_PREFIX}Utilization"
  return raw


def _payroll_feasibility_repair_direction_rules(lever_id: Any) -> Dict[str, Any]:
  normalized = _normalized_lookup_key(lever_id)
  source = f"sql.{_MAPPING_TABLE_NAME}.repair_direction_rules_json"
  if normalized in {
    f"{_REVENUE_PATTERN_PREFIX}Capacity",
    f"{_REVENUE_PATTERN_PREFIX}Unit Price",
    f"{_REVENUE_PATTERN_PREFIX}Utilization",
  }:
    driver = normalized.rsplit("::", 1)[-1].lower().replace(" ", "_")
    return {
      "source_of_truth": source,
      "payroll_revenue_ratio_high": {
        "direction": "increase",
        "reason": "Increasing this revenue driver increases supported revenue and lowers payroll percent of revenue.",
        "driver_field": driver,
        "allowed_when": "driver is editable or derived from payroll-supported capacity",
      },
      "payroll_revenue_ratio_low": {
        "direction": "decrease",
        "reason": "Decreasing this revenue driver lowers supported revenue and raises payroll percent of revenue.",
        "driver_field": driver,
        "allowed_when": "driver is editable or derived from payroll-supported capacity",
      },
      "forbidden_moves": [
        {
          "issue": "payroll_revenue_ratio_high",
          "direction": "decrease",
          "reason": "Decreasing this driver makes payroll percent of revenue worse.",
        },
      ],
    }
  if normalized == "expenses::Payroll":
    return {
      "source_of_truth": source,
      "payroll_revenue_ratio_high": {
        "direction": "decrease_or_increase_supported_revenue",
        "method": "recompute payroll_headcount_schedule through OEWS title mix, FTE ramp, wage positioning, or capacity productivity; do not edit the Payroll row directly.",
        "contract_fields": {
          "capacity_units_per_supporting_fte": {
            "preferred_direction_when_price_and_utilization_unchanged": "increase",
            "forbidden_direction": "decrease",
            "reason": "Higher productivity increases payroll-supported capacity and revenue; lowering productivity makes a high payroll/revenue ratio worse.",
          },
          "supporting_staff_fte": {
            "direction": "decrease_only_if_operationally_plausible",
            "reason": "FTE may fall only when role mix and supported capacity remain coherent.",
          },
          "wage_positioning_multiplier": {
            "direction": "decrease_only_within_selected_table_tier_or_select_lower_valid_tier",
            "reason": "Wage positioning affects payroll dollars but must remain inside headcount policy options.",
          },
        },
      },
      "payroll_revenue_ratio_low": {
        "direction": "increase_payroll_or_decrease_supported_revenue",
        "method": "recompute payroll_headcount_schedule through OEWS title mix, FTE ramp, wage positioning, or capacity productivity; do not edit the Payroll row directly.",
        "contract_fields": {
          "capacity_units_per_supporting_fte": {
            "preferred_direction_when_price_and_utilization_unchanged": "decrease",
            "reason": "Lower productivity reduces supported capacity and revenue, raising payroll percent of revenue.",
          },
          "supporting_staff_fte": {
            "direction": "increase",
            "reason": "Additional staffing raises payroll and supported capacity when the business requires more labor.",
          },
        },
      },
      "forbidden_moves": [
        {
          "issue": "payroll_revenue_ratio_high",
          "field": "capacity_units_per_supporting_fte",
          "direction": "decrease",
          "reason": "This reduces supported capacity and supported revenue, making payroll/revenue economics worse.",
        },
        {
          "issue": "any",
          "field": "model_input_json.sections.expenses[Payroll]",
          "direction": "direct_edit",
          "reason": "Payroll is python_derived from the payroll_headcount schedule and must not be patched directly.",
        },
      ],
    }
  return {}


def _ensure_env_loaded() -> None:
  if os.getenv("MYSQL_HOST") and os.getenv("MYSQL_USER") and (os.getenv("MYSQL_DB") or os.getenv("MYSQL_DATABASE")):
    return
  env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
  if not os.path.exists(env_path):
    return
  try:
    with open(env_path, "r", encoding="utf-8") as handle:
      for line in handle:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
          continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
  except Exception:
    return


def _ensure_mapping_lookup_table(conn) -> None:
  global _ENSURE_MAPPING_TABLE_READY
  if _ENSURE_MAPPING_TABLE_READY:
    return
  with _ENSURE_MAPPING_TABLE_LOCK:
    if _ENSURE_MAPPING_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MAPPING_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          lever_id VARCHAR(255) NOT NULL,
          driver_category VARCHAR(64) NOT NULL,
          target_driver VARCHAR(128) NOT NULL,
          model_input_field LONGTEXT NOT NULL,
          financial_model_field VARCHAR(255) NOT NULL,
          impact_type VARCHAR(32) NOT NULL,
          post_intake_issue_codes LONGTEXT NULL,
          post_intake_phase VARCHAR(32) NOT NULL,
          control_owner VARCHAR(32) NOT NULL,
          value_kind VARCHAR(32) NOT NULL,
          target_value_kind VARCHAR(32) NOT NULL DEFAULT 'currency',
          value_rounding_kind VARCHAR(64) NOT NULL DEFAULT 'none',
          value_decimal_places INT NULL,
          target_rounding_kind VARCHAR(64) NOT NULL DEFAULT 'none',
          target_decimal_places INT NULL,
          input_semantics VARCHAR(64) NOT NULL,
          driver_bundle VARCHAR(64) NULL,
          cash_strategy_role VARCHAR(64) NULL,
          targeting_allowed TINYINT(1) NOT NULL DEFAULT 0,
          diagnostic_only TINYINT(1) NOT NULL DEFAULT 0,
          tolerance_allowed TINYINT(1) NOT NULL DEFAULT 1,
          non_tolerable_issue_codes LONGTEXT NULL,
          repair_direction_rules_json LONGTEXT NULL,
          seed_source_paths_json LONGTEXT NULL,
          seed_formula_key VARCHAR(128) NOT NULL DEFAULT 'none',
          finmo_formula_key VARCHAR(128) NOT NULL DEFAULT 'none',
          validation_formula_key VARCHAR(128) NOT NULL DEFAULT 'semantic_presence_only',
          required_when_key VARCHAR(128) NOT NULL DEFAULT 'always',
          business_applicability_key VARCHAR(128) NOT NULL DEFAULT 'always',
          applicability_positive_tokens_json LONGTEXT NULL,
          applicability_negative_tokens_json LONGTEXT NULL,
          forecast_presence_rule_key VARCHAR(128) NOT NULL DEFAULT 'nonnegative_driver',
          zero_allowed_reason_key VARCHAR(128) NOT NULL DEFAULT 'not_applicable_or_table_optional',
          missing_seed_default_value DOUBLE NULL,
          minimum_live_value DOUBLE NULL,
          maximum_live_value DOUBLE NULL,
          allow_zero TINYINT(1) NOT NULL DEFAULT 1,
          formula_status VARCHAR(32) NOT NULL DEFAULT 'active',
          mapping_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intak_mapping_lookup_lever (lever_id),
          KEY idx_post_intak_mapping_lookup_target_driver (target_driver),
          KEY idx_post_intak_mapping_lookup_phase (post_intake_phase),
          KEY idx_post_intak_mapping_lookup_status (mapping_status),
          KEY idx_post_intak_mapping_lookup_cash_role (cash_strategy_role)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      try:
        cur.execute(
          f"""
          ALTER TABLE {_MAPPING_TABLE_NAME}
          ADD COLUMN target_value_kind VARCHAR(32) NOT NULL DEFAULT 'currency'
          AFTER value_kind
          """
        )
      except Exception:
        pass
      for column_sql in [
        "ADD COLUMN value_rounding_kind VARCHAR(64) NOT NULL DEFAULT 'none' AFTER target_value_kind",
        "ADD COLUMN value_decimal_places INT NULL AFTER value_rounding_kind",
        "ADD COLUMN target_rounding_kind VARCHAR(64) NOT NULL DEFAULT 'none' AFTER value_decimal_places",
        "ADD COLUMN target_decimal_places INT NULL AFTER target_rounding_kind",
        "ADD COLUMN tolerance_allowed TINYINT(1) NOT NULL DEFAULT 1 AFTER diagnostic_only",
        "ADD COLUMN non_tolerable_issue_codes LONGTEXT NULL AFTER tolerance_allowed",
        "ADD COLUMN repair_direction_rules_json LONGTEXT NULL AFTER non_tolerable_issue_codes",
        "ADD COLUMN seed_source_paths_json LONGTEXT NULL AFTER repair_direction_rules_json",
        "ADD COLUMN seed_formula_key VARCHAR(128) NOT NULL DEFAULT 'none' AFTER seed_source_paths_json",
        "ADD COLUMN finmo_formula_key VARCHAR(128) NOT NULL DEFAULT 'none' AFTER seed_formula_key",
        "ADD COLUMN validation_formula_key VARCHAR(128) NOT NULL DEFAULT 'semantic_presence_only' AFTER finmo_formula_key",
        "ADD COLUMN required_when_key VARCHAR(128) NOT NULL DEFAULT 'always' AFTER validation_formula_key",
        "ADD COLUMN business_applicability_key VARCHAR(128) NOT NULL DEFAULT 'always' AFTER required_when_key",
        "ADD COLUMN applicability_positive_tokens_json LONGTEXT NULL AFTER business_applicability_key",
        "ADD COLUMN applicability_negative_tokens_json LONGTEXT NULL AFTER applicability_positive_tokens_json",
        "ADD COLUMN forecast_presence_rule_key VARCHAR(128) NOT NULL DEFAULT 'nonnegative_driver' AFTER business_applicability_key",
        "ADD COLUMN zero_allowed_reason_key VARCHAR(128) NOT NULL DEFAULT 'not_applicable_or_table_optional' AFTER forecast_presence_rule_key",
        "ADD COLUMN missing_seed_default_value DOUBLE NULL AFTER zero_allowed_reason_key",
        "ADD COLUMN minimum_live_value DOUBLE NULL AFTER missing_seed_default_value",
        "ADD COLUMN maximum_live_value DOUBLE NULL AFTER minimum_live_value",
        "ADD COLUMN allow_zero TINYINT(1) NOT NULL DEFAULT 1 AFTER minimum_live_value",
        "ADD COLUMN formula_status VARCHAR(32) NOT NULL DEFAULT 'active' AFTER allow_zero",
      ]:
        try:
          cur.execute(
            f"""
            ALTER TABLE {_MAPPING_TABLE_NAME}
            {column_sql}
            """
          )
        except Exception:
          pass
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET target_value_kind = 'currency'
        WHERE target_value_kind IS NULL OR target_value_kind = ''
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET
          value_rounding_kind = CASE
            WHEN LOWER(value_kind) IN ('currency', 'quarter_currency', 'money', 'count', 'day_count', 'integer') THEN 'nearest_integer'
            WHEN LOWER(value_kind) IN ('ratio', 'percentage', 'percent', 'rate', 'interest_rate') THEN 'nearest_decimal'
            ELSE 'none'
          END,
          value_decimal_places = CASE
            WHEN LOWER(value_kind) IN ('currency', 'quarter_currency', 'money', 'count', 'day_count', 'integer') THEN 0
            WHEN LOWER(value_kind) IN ('ratio', 'percentage', 'percent', 'rate', 'interest_rate') THEN 2
            ELSE NULL
          END
        WHERE value_rounding_kind IS NULL OR value_rounding_kind = '' OR value_rounding_kind = 'none'
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET
          target_rounding_kind = CASE
            WHEN LOWER(target_value_kind) IN ('currency', 'quarter_currency', 'money', 'count', 'day_count', 'integer') THEN 'nearest_integer'
            WHEN LOWER(target_value_kind) IN ('ratio', 'percentage', 'percent', 'rate', 'interest_rate') THEN 'nearest_decimal'
            ELSE 'none'
          END,
          target_decimal_places = CASE
            WHEN LOWER(target_value_kind) IN ('currency', 'quarter_currency', 'money', 'count', 'day_count', 'integer') THEN 0
            WHEN LOWER(target_value_kind) IN ('ratio', 'percentage', 'percent', 'rate', 'interest_rate') THEN 2
            ELSE NULL
          END
        WHERE target_rounding_kind IS NULL OR target_rounding_kind = '' OR target_rounding_kind = 'none'
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET tolerance_allowed = 1,
            non_tolerable_issue_codes = 'p_and_l_flatline'
        WHERE post_intake_issue_codes LIKE '%p_and_l_flatline%'
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET
          seed_formula_key = CASE
            WHEN LOWER(COALESCE(driver_bundle, '')) = 'revenue_formula_bundle' THEN 'runtime_revenue_driver_from_stage_ramp'
            WHEN LOWER(input_semantics) = 'percent_of_revenue' THEN 'annual_source_value_divided_by_annual_revenue'
            WHEN LOWER(input_semantics) = 'quarter_currency' THEN 'runtime_quarter_currency_direct'
            WHEN LOWER(input_semantics) = 'interest_rate' THEN 'python_derived_schedule'
            WHEN LOWER(input_semantics) IN ('percent_of_prior_ppe', 'percent_of_pre_tax_income') THEN 'python_derived_schedule'
            WHEN LOWER(input_semantics) IN ('days', 'percent_of_long_term_debt') THEN 'cash_strategy_schedule'
            WHEN LOWER(control_owner) = 'cash_pass' THEN 'cash_strategy_schedule'
            WHEN LOWER(control_owner) = 'python_derived' THEN 'python_derived_schedule'
            ELSE seed_formula_key
          END,
          finmo_formula_key = CASE
            WHEN LOWER(COALESCE(driver_bundle, '')) = 'revenue_formula_bundle' THEN 'finmo_revenue_equals_capacity_price_utilization_bundle'
            WHEN LOWER(input_semantics) = 'percent_of_revenue' THEN 'revenue_times_model_input_ratio'
            WHEN LOWER(input_semantics) = 'quarter_currency' THEN 'finmo_direct_quarter_currency'
            WHEN LOWER(input_semantics) = 'interest_rate' THEN 'finmo_debt_schedule_interest'
            WHEN LOWER(input_semantics) = 'percent_of_prior_ppe' THEN 'finmo_prior_ppe_times_model_input_ratio'
            WHEN LOWER(input_semantics) = 'days' THEN 'finmo_working_capital_days'
            WHEN LOWER(control_owner) = 'cash_pass' THEN 'finmo_cash_strategy_driver'
            WHEN LOWER(control_owner) = 'python_derived' THEN 'finmo_python_derived_schedule'
            ELSE finmo_formula_key
          END,
          validation_formula_key = CASE
            WHEN LOWER(COALESCE(driver_bundle, '')) = 'revenue_formula_bundle' THEN 'finmo_revenue_equals_capacity_price_utilization_bundle'
            WHEN LOWER(input_semantics) = 'percent_of_revenue' THEN 'finmo_equals_revenue_times_model_input_ratio'
            WHEN LOWER(input_semantics) = 'quarter_currency' THEN 'finmo_equals_model_input_value'
            WHEN LOWER(input_semantics) = 'days' THEN 'finmo_working_capital_days'
            WHEN LOWER(input_semantics) = 'percent_of_long_term_debt' THEN 'finmo_short_term_debt_percent_of_ltd'
            WHEN LOWER(control_owner) = 'python_derived' THEN 'schedule_marker_validation'
            ELSE validation_formula_key
          END,
          required_when_key = CASE
            WHEN LOWER(input_semantics) = 'percent_of_revenue' THEN 'revenue_positive'
            WHEN LOWER(input_semantics) = 'interest_rate' THEN 'debt_outstanding'
            WHEN LOWER(input_semantics) = 'percent_of_prior_ppe' THEN 'prior_ppe_positive'
            WHEN LOWER(input_semantics) = 'days' THEN 'business_applicable'
            WHEN LOWER(input_semantics) = 'percent_of_long_term_debt' THEN 'debt_policy_or_existing_debt'
            WHEN LOWER(control_owner) = 'cash_pass' THEN 'cash_strategy_requires'
            ELSE required_when_key
          END,
          business_applicability_key = CASE
            WHEN lever_id = 'balance_sheet::Accounts Receivable Days' THEN 'revenue_positive_ar_applicable'
            WHEN lever_id = 'balance_sheet::Accounts Payable Days' THEN 'operating_expense_positive_ap_applicable'
            WHEN lever_id = 'balance_sheet::Inventory Days' THEN 'inventory_business_or_seed'
            WHEN lever_id = 'balance_sheet::Prepaid Expenses (% of Revenue)' THEN 'revenue_positive_prepaid_applicable'
            WHEN lever_id = 'balance_sheet::Deferred Revenue (% of Revenue)' THEN 'deferred_revenue_business'
            WHEN lever_id = 'balance_sheet::Short Term Debt (% of LTD)' THEN 'debt_policy_or_existing_debt'
            WHEN LOWER(COALESCE(driver_bundle, '')) = 'revenue_formula_bundle' THEN 'revenue_positive'
            WHEN LOWER(input_semantics) = 'percent_of_revenue' THEN 'revenue_positive'
            WHEN LOWER(control_owner) = 'cash_pass' THEN 'cash_strategy_requires'
            ELSE business_applicability_key
          END,
          forecast_presence_rule_key = CASE
            WHEN lever_id IN (
              'balance_sheet::Accounts Receivable Days',
              'balance_sheet::Accounts Payable Days',
              'balance_sheet::Inventory Days',
              'balance_sheet::Deferred Revenue (% of Revenue)'
            ) THEN 'positive_driver_when_applicable'
            WHEN lever_id = 'balance_sheet::Prepaid Expenses (% of Revenue)' THEN 'positive_driver_when_applicable'
            WHEN lever_id = 'balance_sheet::Short Term Debt (% of LTD)' THEN 'schedule_reconciles_when_applicable'
            WHEN LOWER(COALESCE(driver_bundle, '')) = 'revenue_formula_bundle' THEN 'positive_driver_when_applicable'
            WHEN LOWER(control_owner) IN ('cash_pass', 'python_derived') THEN 'schedule_reconciles_when_applicable'
            ELSE forecast_presence_rule_key
          END,
          zero_allowed_reason_key = CASE
            WHEN lever_id = 'balance_sheet::Accounts Receivable Days' THEN 'revenue_not_positive'
            WHEN lever_id = 'balance_sheet::Accounts Payable Days' THEN 'no_vendor_payables_model'
            WHEN lever_id = 'balance_sheet::Inventory Days' THEN 'inventory_not_applicable'
            WHEN lever_id = 'balance_sheet::Prepaid Expenses (% of Revenue)' THEN 'revenue_not_positive'
            WHEN lever_id = 'balance_sheet::Deferred Revenue (% of Revenue)' THEN 'no_upfront_or_deferred_revenue_model'
            WHEN lever_id = 'balance_sheet::Short Term Debt (% of LTD)' THEN 'no_debt_policy_or_existing_debt'
            ELSE zero_allowed_reason_key
          END,
          missing_seed_default_value = CASE
            WHEN lever_id IN (
              'balance_sheet::Accounts Receivable Days',
              'balance_sheet::Accounts Payable Days',
              'balance_sheet::Inventory Days',
              'balance_sheet::Prepaid Expenses (% of Revenue)',
              'balance_sheet::Deferred Revenue (% of Revenue)',
              'balance_sheet::Short Term Debt (% of LTD)'
            ) THEN NULL
            ELSE missing_seed_default_value
          END,
          minimum_live_value = CASE
            WHEN lever_id = 'balance_sheet::Accounts Receivable Days' THEN 1.0
            WHEN lever_id = 'balance_sheet::Accounts Payable Days' THEN 1.0
            WHEN lever_id = 'balance_sheet::Inventory Days' THEN 1.0
            WHEN lever_id = 'balance_sheet::Prepaid Expenses (% of Revenue)' THEN 0.01
            WHEN lever_id = 'balance_sheet::Deferred Revenue (% of Revenue)' THEN 0.01
            WHEN lever_id = 'balance_sheet::Short Term Debt (% of LTD)' THEN 0.0
            ELSE minimum_live_value
          END,
          maximum_live_value = CASE
            WHEN lever_id = 'balance_sheet::Accounts Receivable Days' THEN 90.0
            WHEN lever_id = 'balance_sheet::Accounts Payable Days' THEN 90.0
            WHEN lever_id = 'balance_sheet::Inventory Days' THEN 180.0
            WHEN lever_id = 'balance_sheet::Prepaid Expenses (% of Revenue)' THEN 0.20
            WHEN lever_id = 'balance_sheet::Deferred Revenue (% of Revenue)' THEN 0.75
            WHEN lever_id = 'balance_sheet::Short Term Debt (% of LTD)' THEN 1.0
            ELSE maximum_live_value
          END,
          formula_status = 'active'
        WHERE mapping_status = 'active'
        """
      )
      cur.execute(
        f"""
        INSERT INTO {_MAPPING_TABLE_NAME} (
          lever_id,
          driver_category,
          target_driver,
          model_input_field,
          financial_model_field,
          impact_type,
          post_intake_issue_codes,
          post_intake_phase,
          control_owner,
          value_kind,
          target_value_kind,
          value_rounding_kind,
          value_decimal_places,
          target_rounding_kind,
          target_decimal_places,
          input_semantics,
          driver_bundle,
          targeting_allowed,
          diagnostic_only,
          tolerance_allowed,
          non_tolerable_issue_codes,
          repair_direction_rules_json,
          seed_formula_key,
          finmo_formula_key,
          validation_formula_key,
          required_when_key,
          business_applicability_key,
          forecast_presence_rule_key,
          zero_allowed_reason_key,
          allow_zero,
          formula_status,
          mapping_status,
          notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', 'active', %s)
        ON DUPLICATE KEY UPDATE
          driver_category = VALUES(driver_category),
          target_driver = VALUES(target_driver),
          model_input_field = VALUES(model_input_field),
          financial_model_field = VALUES(financial_model_field),
          impact_type = VALUES(impact_type),
          post_intake_issue_codes = VALUES(post_intake_issue_codes),
          post_intake_phase = VALUES(post_intake_phase),
          control_owner = VALUES(control_owner),
          value_kind = VALUES(value_kind),
          target_value_kind = VALUES(target_value_kind),
          input_semantics = VALUES(input_semantics),
          driver_bundle = VALUES(driver_bundle),
          targeting_allowed = VALUES(targeting_allowed),
          diagnostic_only = VALUES(diagnostic_only),
          tolerance_allowed = VALUES(tolerance_allowed),
          non_tolerable_issue_codes = VALUES(non_tolerable_issue_codes),
          repair_direction_rules_json = VALUES(repair_direction_rules_json),
          seed_formula_key = VALUES(seed_formula_key),
          finmo_formula_key = VALUES(finmo_formula_key),
          validation_formula_key = VALUES(validation_formula_key),
          required_when_key = VALUES(required_when_key),
          business_applicability_key = VALUES(business_applicability_key),
          forecast_presence_rule_key = VALUES(forecast_presence_rule_key),
          zero_allowed_reason_key = VALUES(zero_allowed_reason_key),
          allow_zero = VALUES(allow_zero),
          formula_status = VALUES(formula_status),
          mapping_status = VALUES(mapping_status),
          notes = VALUES(notes)
        """,
        (
          "expenses::Payroll",
          "payroll_schedule",
          "payroll",
          "model_input_json.sections.expenses[Payroll]",
          "finmo_json.quarter_rows[*].payroll",
          "derived",
          "cost_structure_mismatch|p_and_l_flatline",
          "convergence",
          "python_derived",
          "quarter_currency",
          "currency",
          "nearest_integer",
          0,
          "nearest_integer",
          0,
          "quarter_currency",
          "payroll_headcount_schedule",
          0,
          1,
          0,
          "cost_structure_mismatch",
          _json_dumps_value(_payroll_feasibility_repair_direction_rules("expenses::Payroll")),
          "python_derived_schedule",
          "finmo_python_derived_schedule",
          "schedule_marker_validation",
          "business_applicable",
          "revenue_positive",
          "schedule_reconciles_when_applicable",
          "payroll_not_applicable",
          0,
          "Payroll is derived from payroll_headcount_schedule. Directional repair rules live here so GPT sees the causal movement contract through SQL mapping.",
        ),
      )
      for lever_id in [
        f"{_REVENUE_PATTERN_PREFIX}Capacity",
        f"{_REVENUE_PATTERN_PREFIX}Unit Price",
        f"{_REVENUE_PATTERN_PREFIX}Utilization",
      ]:
        cur.execute(
          f"""
          UPDATE {_MAPPING_TABLE_NAME}
          SET
            post_intake_issue_codes = CASE
              WHEN post_intake_issue_codes IS NULL OR TRIM(post_intake_issue_codes) = ''
                THEN 'capacity_support_mismatch|p_and_l_flatline|cost_structure_mismatch'
              WHEN CONCAT('|', post_intake_issue_codes, '|') NOT LIKE '%|cost_structure_mismatch|%'
                THEN CONCAT(post_intake_issue_codes, '|cost_structure_mismatch')
              ELSE post_intake_issue_codes
            END,
            non_tolerable_issue_codes = CASE
              WHEN non_tolerable_issue_codes IS NULL OR TRIM(non_tolerable_issue_codes) = ''
                THEN 'cost_structure_mismatch'
              WHEN CONCAT('|', non_tolerable_issue_codes, '|') NOT LIKE '%|cost_structure_mismatch|%'
                THEN CONCAT(non_tolerable_issue_codes, '|cost_structure_mismatch')
              ELSE non_tolerable_issue_codes
            END,
            repair_direction_rules_json = %s
          WHERE lever_id = %s
          """,
          (
            _json_dumps_value(_payroll_feasibility_repair_direction_rules(lever_id)),
            lever_id,
          ),
        )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET non_tolerable_issue_codes = CASE
          WHEN non_tolerable_issue_codes IS NULL OR TRIM(non_tolerable_issue_codes) = ''
            THEN 'cost_structure_mismatch'
          WHEN CONCAT('|', non_tolerable_issue_codes, '|') NOT LIKE '%|cost_structure_mismatch|%'
            THEN CONCAT(non_tolerable_issue_codes, '|cost_structure_mismatch')
          ELSE non_tolerable_issue_codes
        END
        WHERE CONCAT('|', COALESCE(post_intake_issue_codes, ''), '|') LIKE '%|cost_structure_mismatch|%'
        """
      )
      for lever_id, positive_tokens, negative_tokens in [
        (
          "balance_sheet::Inventory Days",
          [
            "inventory",
            "retail",
            "boutique",
            "shop",
            "store",
            "physical goods",
            "merchandise",
            "wholesale",
            "resale",
            "stock",
            "warehouse",
            "shelf",
          ],
          [
            "software",
            "saas",
            "digital product",
            "consulting",
            "service business",
            "professional service",
            "subscription software",
          ],
        ),
        (
          "balance_sheet::Deferred Revenue (% of Revenue)",
          [
            "subscription",
            "membership",
            "retainer",
            "deposit",
            "prepaid",
            "advance payment",
            "upfront",
            "annual contract",
          ],
          [],
        ),
        (
          "balance_sheet::Accounts Payable Days",
          [],
          [
            "no vendors",
            "no supplier credit",
            "pay vendors immediately",
          ],
        ),
      ]:
        cur.execute(
          f"""
          UPDATE {_MAPPING_TABLE_NAME}
          SET applicability_positive_tokens_json = %s,
              applicability_negative_tokens_json = %s
          WHERE lever_id = %s
          """,
          (
            _json_dumps_value(positive_tokens),
            _json_dumps_value(negative_tokens),
            lever_id,
          ),
        )
      for lever_id, source_paths, allow_zero in [
        ("expenses::Cost of Goods Sold", ["financials.current_cogs", "financials.cogs", "financials.cogs_absolute"], 1),
        ("expenses::Marketing", ["financials.marketing_total_year1", "financials.marketing_expense", "financials.marketing"], 0),
        ("expenses::Research & Development", ["financials.r_and_d_total_year1", "financials.research_and_development"], 1),
        ("expenses::General & Administrative", ["financials.other_opex_absolute", "financials.other_operating_expense"], 0),
        ("expenses::Lease", ["financials.monthly_rent_expense"], 1),
      ]:
        cur.execute(
          f"""
          UPDATE {_MAPPING_TABLE_NAME}
          SET seed_source_paths_json = %s,
              allow_zero = %s
          WHERE lever_id = %s
          """,
          (_json_dumps_value(source_paths), int(allow_zero), lever_id),
        )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET seed_formula_key = 'cash_strategy_schedule',
            finmo_formula_key = 'revenue_times_model_input_ratio',
            validation_formula_key = 'finmo_equals_revenue_times_model_input_ratio',
            required_when_key = 'business_applicable',
            business_applicability_key = 'revenue_positive_prepaid_applicable',
            forecast_presence_rule_key = 'positive_driver_when_applicable',
            zero_allowed_reason_key = 'revenue_not_positive',
            missing_seed_default_value = NULL,
            minimum_live_value = 0.01,
            maximum_live_value = 0.20,
            seed_source_paths_json = NULL,
            allow_zero = 1
        WHERE lever_id = 'balance_sheet::Prepaid Expenses (% of Revenue)'
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET seed_formula_key = 'cash_strategy_schedule',
            finmo_formula_key = 'revenue_times_model_input_ratio',
            validation_formula_key = 'finmo_equals_revenue_times_model_input_ratio',
            required_when_key = 'business_applicable',
            business_applicability_key = 'deferred_revenue_business',
            forecast_presence_rule_key = 'positive_driver_when_applicable',
            zero_allowed_reason_key = 'no_upfront_or_deferred_revenue_model',
            missing_seed_default_value = NULL,
            minimum_live_value = 0.01,
            maximum_live_value = 0.75,
            seed_source_paths_json = NULL,
            allow_zero = 1
        WHERE lever_id = 'balance_sheet::Deferred Revenue (% of Revenue)'
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET seed_formula_key = 'cash_strategy_schedule',
            finmo_formula_key = 'finmo_cash_strategy_driver',
            validation_formula_key = 'semantic_presence_only',
            required_when_key = 'cash_strategy_requires'
        WHERE control_owner = 'cash_pass'
          AND LOWER(COALESCE(driver_bundle, '')) NOT IN ('working_capital_bundle', 'debt_schedule_bundle')
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET validation_formula_key = 'finmo_equals_model_input_value'
        WHERE lever_id = 'expenses::Lease'
        """
      )
      cur.execute(
        f"""
        UPDATE {_MAPPING_TABLE_NAME}
        SET validation_formula_key = 'schedule_marker_validation'
        WHERE control_owner = 'python_derived'
        """
      )
      conn.commit()
      _ENSURE_MAPPING_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def _ensure_cash_policy_lookup_table(conn) -> None:
  global _ENSURE_CASH_POLICY_TABLE_READY
  if _ENSURE_CASH_POLICY_TABLE_READY:
    return
  with _ENSURE_CASH_POLICY_TABLE_LOCK:
    if _ENSURE_CASH_POLICY_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_CASH_POLICY_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          cash_strategy VARCHAR(64) NOT NULL,
          debt_position VARCHAR(64) NOT NULL,
          debt_to_equity_min DECIMAL(10,4) NOT NULL,
          debt_to_equity_max DECIMAL(10,4) NOT NULL,
          cash_floor_months DECIMAL(10,4) NOT NULL,
          cash_ceiling_months DECIMAL(10,4) NOT NULL,
          distribution_weight DECIMAL(10,4) NOT NULL,
          debt_paydown_weight DECIMAL(10,4) NOT NULL,
          retain_weight DECIMAL(10,4) NOT NULL,
          deploy_above_ceiling_required TINYINT(1) NOT NULL DEFAULT 1,
          debt_schedule_method VARCHAR(64) NOT NULL DEFAULT 'amortizing_remaining_balance',
          debt_schedule_required TINYINT(1) NOT NULL DEFAULT 1,
          debt_schedule_horizon_quarters INT NOT NULL DEFAULT 20,
          debt_minimum_payment_frequency VARCHAR(32) NOT NULL DEFAULT 'quarterly',
          debt_min_principal_source_priority_json LONGTEXT NOT NULL,
          debt_extra_paydown_policy VARCHAR(64) NOT NULL DEFAULT 'cash_strategy_surplus_only',
          debt_interest_rate_source_required VARCHAR(128) NOT NULL DEFAULT 'sba_loan_7a_raw',
          debt_interest_rate_fallback_allowed TINYINT(1) NOT NULL DEFAULT 0,
          cash_phase_sequence_json LONGTEXT NOT NULL,
          policy_label VARCHAR(255) NOT NULL,
          policy_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_cash_policy (cash_strategy, debt_position),
          KEY idx_post_intake_cash_policy_strategy (cash_strategy),
          KEY idx_post_intake_cash_policy_status (policy_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      try:
        cur.execute(
          f"""
          ALTER TABLE {_CASH_POLICY_TABLE_NAME}
          ADD COLUMN deploy_above_ceiling_required TINYINT(1) NOT NULL DEFAULT 1
          AFTER retain_weight
          """
        )
      except Exception:
        pass
      try:
        cur.execute(
          f"""
          ALTER TABLE {_CASH_POLICY_TABLE_NAME}
          ADD COLUMN cash_phase_sequence_json LONGTEXT NULL
          AFTER deploy_above_ceiling_required
          """
        )
      except Exception:
        pass
      for column_sql in [
        "ADD COLUMN debt_schedule_method VARCHAR(64) NOT NULL DEFAULT 'amortizing_remaining_balance' AFTER deploy_above_ceiling_required",
        "ADD COLUMN debt_schedule_required TINYINT(1) NOT NULL DEFAULT 1 AFTER debt_schedule_method",
        "ADD COLUMN debt_schedule_horizon_quarters INT NOT NULL DEFAULT 20 AFTER debt_schedule_required",
        "ADD COLUMN debt_minimum_payment_frequency VARCHAR(32) NOT NULL DEFAULT 'quarterly' AFTER debt_schedule_horizon_quarters",
        "ADD COLUMN debt_min_principal_source_priority_json LONGTEXT NULL AFTER debt_minimum_payment_frequency",
        "ADD COLUMN debt_extra_paydown_policy VARCHAR(64) NOT NULL DEFAULT 'cash_strategy_surplus_only' AFTER debt_min_principal_source_priority_json",
        "ADD COLUMN debt_interest_rate_source_required VARCHAR(128) NOT NULL DEFAULT 'sba_loan_7a_raw' AFTER debt_extra_paydown_policy",
        "ADD COLUMN debt_interest_rate_fallback_allowed TINYINT(1) NOT NULL DEFAULT 0 AFTER debt_interest_rate_source_required",
      ]:
        try:
          cur.execute(
            f"""
            ALTER TABLE {_CASH_POLICY_TABLE_NAME}
            {column_sql}
            """
          )
        except Exception:
          pass
      cur.execute(f"SELECT COUNT(*) AS row_count FROM {_CASH_POLICY_TABLE_NAME}")
      row_count = int((cur.fetchone() or [0])[0] or 0)
      if row_count == 0:
        for row in _DEFAULT_CASH_POLICY_ROWS:
          cur.execute(
            f"""
            INSERT INTO {_CASH_POLICY_TABLE_NAME} (
              cash_strategy,
              debt_position,
              debt_to_equity_min,
              debt_to_equity_max,
              cash_floor_months,
              cash_ceiling_months,
              distribution_weight,
              debt_paydown_weight,
              retain_weight,
              deploy_above_ceiling_required,
              debt_schedule_method,
              debt_schedule_required,
              debt_schedule_horizon_quarters,
              debt_minimum_payment_frequency,
              debt_min_principal_source_priority_json,
              debt_extra_paydown_policy,
              debt_interest_rate_source_required,
              debt_interest_rate_fallback_allowed,
              cash_phase_sequence_json,
              policy_label,
              policy_status,
              notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, 1, %s, %s, %s, %s, %s, 0, %s, %s, 'active', %s)
            """,
            (
              _clean_text(row.get("cash_strategy")).lower(),
              _clean_text(row.get("debt_position")).lower(),
              float(row.get("debt_to_equity_min") or 0.0),
              float(row.get("debt_to_equity_max") or 0.0),
              float(row.get("cash_floor_months") or 0.0),
              float(row.get("cash_ceiling_months") or 0.0),
              float(row.get("distribution_weight") or 0.0),
              float(row.get("debt_paydown_weight") or 0.0),
              float(row.get("retain_weight") or 0.0),
              str(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_schedule_method") or ""),
              int(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_schedule_horizon_quarters") or 20),
              str(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_minimum_payment_frequency") or ""),
              _json_dumps_value(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_min_principal_source_priority") or []),
              str(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_extra_paydown_policy") or ""),
              str(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_interest_rate_source_required") or ""),
              _json_dumps_value(_DEFAULT_CASH_PASS_PHASE_SEQUENCE),
              _clean_text(row.get("policy_label")),
              (
                "Debt position uses debt_to_equity = total_debt / total_equity. "
                "If equity is zero or negative and debt exists, classify as high_debt."
              ),
            ),
          )
      cur.execute(
        f"""
        UPDATE {_CASH_POLICY_TABLE_NAME}
        SET debt_schedule_method = %s
        WHERE policy_status = 'active'
          AND LOWER(COALESCE(debt_schedule_method, '')) IN ('', 'straight_line_minimum_principal')
        """,
        (
          str(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_schedule_method") or ""),
        ),
      )
      cur.execute(
        f"""
        UPDATE {_CASH_POLICY_TABLE_NAME}
        SET debt_min_principal_source_priority_json = %s
        WHERE policy_status = 'active'
          AND (
            debt_min_principal_source_priority_json IS NULL
            OR debt_min_principal_source_priority_json = ''
            OR debt_min_principal_source_priority_json NOT LIKE '%policy.amortizing_remaining_balance_over_contract_horizon%'
          )
        """,
        (
          _json_dumps_value(_DEFAULT_CASH_DEBT_SCHEDULE_POLICY.get("debt_min_principal_source_priority") or []),
        ),
      )
      conn.commit()
      _ENSURE_CASH_POLICY_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def _ensure_gpt_contract_lookup_table(conn) -> None:
  global _ENSURE_GPT_CONTRACT_TABLE_READY
  if _ENSURE_GPT_CONTRACT_TABLE_READY:
    return
  with _ENSURE_GPT_CONTRACT_TABLE_LOCK:
    if _ENSURE_GPT_CONTRACT_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_GPT_CONTRACT_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          contract_name VARCHAR(128) NOT NULL,
          grid_name VARCHAR(128) NOT NULL,
          field_path VARCHAR(255) NOT NULL,
          field_name VARCHAR(128) NOT NULL,
          field_type VARCHAR(64) NOT NULL,
          required TINYINT(1) NOT NULL DEFAULT 1,
          strict_required TINYINT(1) NOT NULL DEFAULT 1,
          allow_null TINYINT(1) NOT NULL DEFAULT 0,
          allow_empty TINYINT(1) NOT NULL DEFAULT 0,
          is_array_item TINYINT(1) NOT NULL DEFAULT 0,
          parent_field_path VARCHAR(255) NULL,
          json_schema_type VARCHAR(64) NOT NULL DEFAULT 'string',
          min_value DECIMAL(20,6) NULL,
          max_value DECIMAL(20,6) NULL,
          naics_baseline_metric_key VARCHAR(128) NULL,
          naics_baseline_band_kind VARCHAR(32) NULL,
          naics_baseline_min_quantile DECIMAL(6,4) NULL,
          naics_baseline_max_quantile DECIMAL(6,4) NULL,
          mapping_table_outer_envelope TINYINT(1) NOT NULL DEFAULT 1,
          min_items INT NULL,
          max_items INT NULL,
          item_contract_grid_name VARCHAR(128) NULL,
          additional_properties_allowed TINYINT(1) NOT NULL DEFAULT 0,
          gpt_owned TINYINT(1) NOT NULL DEFAULT 1,
          python_owned TINYINT(1) NOT NULL DEFAULT 0,
          editable TINYINT(1) NOT NULL DEFAULT 1,
          must_match_lookup TINYINT(1) NOT NULL DEFAULT 0,
          contract_phase VARCHAR(64) NULL,
          horizon_rule VARCHAR(128) NULL,
          normalization_kind VARCHAR(128) NOT NULL DEFAULT 'none',
          rounding_kind VARCHAR(64) NOT NULL DEFAULT 'none',
          decimal_places INT NULL,
          validation_kind VARCHAR(128) NOT NULL DEFAULT 'schema_only',
          lookup_source VARCHAR(128) NOT NULL DEFAULT 'none',
          enum_values LONGTEXT NULL,
          allowed_aliases LONGTEXT NULL,
          prompt_required_instruction LONGTEXT NULL,
          prompt_label VARCHAR(255) NULL,
          failure_code VARCHAR(255) NULL,
          contract_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_gpt_contract_field (contract_name, grid_name, field_path),
          KEY idx_post_intake_gpt_contract_name (contract_name),
          KEY idx_post_intake_gpt_contract_grid (grid_name),
          KEY idx_post_intake_gpt_contract_status (contract_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      for alter_sql in (
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN strict_required TINYINT(1) NOT NULL DEFAULT 1
        AFTER required
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN json_schema_type VARCHAR(64) NOT NULL DEFAULT 'string'
        AFTER parent_field_path
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN min_value DECIMAL(20,6) NULL
        AFTER json_schema_type
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN max_value DECIMAL(20,6) NULL
        AFTER min_value
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN min_items INT NULL
        AFTER max_value
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN max_items INT NULL
        AFTER min_items
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN item_contract_grid_name VARCHAR(128) NULL
        AFTER max_items
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN additional_properties_allowed TINYINT(1) NOT NULL DEFAULT 0
        AFTER item_contract_grid_name
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN gpt_owned TINYINT(1) NOT NULL DEFAULT 1
        AFTER additional_properties_allowed
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN python_owned TINYINT(1) NOT NULL DEFAULT 0
        AFTER gpt_owned
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN editable TINYINT(1) NOT NULL DEFAULT 1
        AFTER python_owned
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN must_match_lookup TINYINT(1) NOT NULL DEFAULT 0
        AFTER editable
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN contract_phase VARCHAR(64) NULL
        AFTER must_match_lookup
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN rounding_kind VARCHAR(64) NOT NULL DEFAULT 'none'
        AFTER normalization_kind
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN decimal_places INT NULL
        AFTER rounding_kind
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN prompt_required_instruction LONGTEXT NULL
        AFTER allowed_aliases
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN failure_code VARCHAR(255) NULL
        AFTER prompt_label
        """,
        # Module 3 Task 3.1 — NAICS-baseline bound columns. When set,
        # `min_value`/`max_value` are populated at prompt-build time from
        # the resolver cascade for `naics_baseline_metric_key`. Replaces
        # the hardcoded universal bounds previously living in code.
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN naics_baseline_metric_key VARCHAR(128) NULL
        AFTER max_value
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN naics_baseline_band_kind VARCHAR(32) NULL
        AFTER naics_baseline_metric_key
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN naics_baseline_min_quantile DECIMAL(6,4) NULL
        AFTER naics_baseline_band_kind
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN naics_baseline_max_quantile DECIMAL(6,4) NULL
        AFTER naics_baseline_min_quantile
        """,
        f"""
        ALTER TABLE {_GPT_CONTRACT_TABLE_NAME}
        ADD COLUMN mapping_table_outer_envelope TINYINT(1) NOT NULL DEFAULT 1
        AFTER naics_baseline_max_quantile
        """,
      ):
        try:
          cur.execute(alter_sql)
        except Exception:
          pass
      for row in _DEFAULT_GPT_CONTRACT_ROWS:
        cur.execute(
          f"""
          INSERT INTO {_GPT_CONTRACT_TABLE_NAME} (
            contract_name,
            grid_name,
            field_path,
            field_name,
            field_type,
            required,
            strict_required,
            allow_null,
            allow_empty,
            is_array_item,
            parent_field_path,
            json_schema_type,
            min_value,
            max_value,
            naics_baseline_metric_key,
            naics_baseline_band_kind,
            naics_baseline_min_quantile,
            naics_baseline_max_quantile,
            mapping_table_outer_envelope,
            min_items,
            max_items,
            item_contract_grid_name,
            additional_properties_allowed,
            gpt_owned,
            python_owned,
            editable,
            must_match_lookup,
            contract_phase,
            horizon_rule,
            normalization_kind,
            rounding_kind,
            decimal_places,
            validation_kind,
            lookup_source,
            enum_values,
            allowed_aliases,
            prompt_required_instruction,
            prompt_label,
            failure_code,
            contract_status,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
          ON DUPLICATE KEY UPDATE
            field_name = VALUES(field_name),
            field_type = VALUES(field_type),
            required = VALUES(required),
            strict_required = VALUES(strict_required),
            allow_null = VALUES(allow_null),
            allow_empty = VALUES(allow_empty),
            is_array_item = VALUES(is_array_item),
            parent_field_path = VALUES(parent_field_path),
            json_schema_type = VALUES(json_schema_type),
            min_value = VALUES(min_value),
            max_value = VALUES(max_value),
            naics_baseline_metric_key = VALUES(naics_baseline_metric_key),
            naics_baseline_band_kind = VALUES(naics_baseline_band_kind),
            naics_baseline_min_quantile = VALUES(naics_baseline_min_quantile),
            naics_baseline_max_quantile = VALUES(naics_baseline_max_quantile),
            mapping_table_outer_envelope = VALUES(mapping_table_outer_envelope),
            min_items = VALUES(min_items),
            max_items = VALUES(max_items),
            item_contract_grid_name = VALUES(item_contract_grid_name),
            additional_properties_allowed = VALUES(additional_properties_allowed),
            gpt_owned = VALUES(gpt_owned),
            python_owned = VALUES(python_owned),
            editable = VALUES(editable),
            must_match_lookup = VALUES(must_match_lookup),
            contract_phase = VALUES(contract_phase),
            horizon_rule = VALUES(horizon_rule),
            normalization_kind = VALUES(normalization_kind),
            rounding_kind = VALUES(rounding_kind),
            decimal_places = VALUES(decimal_places),
            validation_kind = VALUES(validation_kind),
            lookup_source = VALUES(lookup_source),
            enum_values = VALUES(enum_values),
            allowed_aliases = VALUES(allowed_aliases),
            prompt_required_instruction = VALUES(prompt_required_instruction),
            prompt_label = VALUES(prompt_label),
            failure_code = VALUES(failure_code),
            contract_status = VALUES(contract_status),
            notes = VALUES(notes)
          """,
          (
            _clean_text(row.get("contract_name")).lower(),
            _clean_text(row.get("grid_name")).lower(),
            _clean_text(row.get("field_path")),
            _clean_text(row.get("field_name")),
            _clean_text(row.get("field_type")).lower(),
            1 if _clean_bool(row.get("required"), default=True) else 0,
            1 if _clean_bool(row.get("strict_required"), default=True) else 0,
            1 if _clean_bool(row.get("allow_null")) else 0,
            1 if _clean_bool(row.get("allow_empty")) else 0,
            1 if _clean_bool(row.get("is_array_item")) else 0,
            _clean_text(row.get("parent_field_path")),
            _clean_text(row.get("json_schema_type")).lower() or "string",
            row.get("min_value"),
            row.get("max_value"),
            _clean_text(row.get("naics_baseline_metric_key")) or None,
            _clean_text(row.get("naics_baseline_band_kind")) or None,
            row.get("naics_baseline_min_quantile"),
            row.get("naics_baseline_max_quantile"),
            1 if _clean_bool(row.get("mapping_table_outer_envelope"), default=True) else 0,
            row.get("min_items"),
            row.get("max_items"),
            _clean_text(row.get("item_contract_grid_name")).lower(),
            1 if _clean_bool(row.get("additional_properties_allowed")) else 0,
            1 if _clean_bool(row.get("gpt_owned"), default=True) else 0,
            1 if _clean_bool(row.get("python_owned")) else 0,
            1 if _clean_bool(row.get("editable"), default=True) else 0,
            1 if _clean_bool(row.get("must_match_lookup")) else 0,
            _clean_text(row.get("contract_phase")).lower(),
            _clean_text(row.get("horizon_rule")).lower(),
            _clean_text(row.get("normalization_kind")).lower() or "none",
            _clean_text(row.get("rounding_kind")).lower() or "none",
            row.get("decimal_places"),
            _clean_text(row.get("validation_kind")).lower() or "schema_only",
            _clean_text(row.get("lookup_source")).lower() or "none",
            _json_dumps_list(row.get("enum_values")),
            _json_dumps_list(row.get("allowed_aliases")),
            _clean_text(row.get("prompt_required_instruction")),
            _clean_text(row.get("prompt_label")),
            _clean_text(row.get("failure_code")),
            _clean_text(row.get("notes")),
          ),
        )
      cur.execute(
        f"""
        UPDATE {_GPT_CONTRACT_TABLE_NAME}
        SET contract_status = 'retired',
            required = 0,
            strict_required = 0,
            prompt_required_instruction = 'Retired: per-quarter ramp prose is legacy bloat; root rationale remains the diagnostic explanation.'
        WHERE contract_name = 'stage_ramp_contract'
          AND field_path = 'quarter_ramp_grid[].why'
        """
      )
      cur.execute(
        f"""
        UPDATE {_GPT_CONTRACT_TABLE_NAME}
        SET contract_status = 'retired',
            required = 0,
            strict_required = 0,
            prompt_required_instruction = 'Retired: payroll is owned by the separate payroll_headcount_schedule contract, not stage_ramp_contract.'
        WHERE contract_name = 'stage_ramp_contract'
          AND (
            field_path = 'payroll_headcount_grid'
            OR grid_name = 'payroll_headcount_grid'
            OR parent_field_path = 'payroll_headcount_grid'
          )
        """
      )
      cur.execute(
        f"""
        UPDATE {_GPT_CONTRACT_TABLE_NAME}
        SET contract_status = 'retired',
            required = 0,
            prompt_required_instruction = 'Retired: FTE/headcount is owned by payroll_headcount_schedule, not stage_ramp_contract.'
        WHERE contract_name = 'stage_ramp_contract'
          AND (
            field_path = 'fte_spike_small_base_threshold'
            OR field_path LIKE 'quarter_ramp_grid[].fte_%'
            OR field_name IN ('fte_target', 'fte_max', 'fte_spike', 'fte_spike_max', 'fte_spike_small_base_threshold')
          )
        """
      )
      cur.execute(
        f"""
        UPDATE {_GPT_CONTRACT_TABLE_NAME}
        SET contract_status = 'retired',
            required = 0,
            strict_required = 0,
            prompt_required_instruction = 'Retired: GPT supplies supporting-staff FTE only. Python resolves payroll wages through OEWS and post_intake_headcount_policy_lookup.'
        WHERE contract_name = 'payroll_headcount_schedule'
          AND field_path IN (
            'payroll_headcount_grid[].avg_annual_wage',
            'payroll_headcount_grid[].annual_wage',
            'payroll_headcount_grid[].wage_source'
          )
        """
      )
      cur.execute(
        f"""
        DELETE FROM {_GPT_CONTRACT_TABLE_NAME}
        WHERE contract_name = 'payroll_headcount_schedule'
          AND field_path IN (
            'payroll_headcount_grid[].role_family',
            'payroll_headcount_grid[].role_category',
            'payroll_headcount_grid[].role_title'
          )
        """
      )
      conn.commit()
      _ENSURE_GPT_CONTRACT_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def _ensure_gpt_context_lookup_table(conn) -> None:
  global _ENSURE_GPT_CONTEXT_TABLE_READY
  if _ENSURE_GPT_CONTEXT_TABLE_READY:
    return
  with _ENSURE_GPT_CONTEXT_TABLE_LOCK:
    if _ENSURE_GPT_CONTEXT_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_GPT_CONTEXT_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          contract_name VARCHAR(128) NOT NULL,
          context_key VARCHAR(128) NOT NULL,
          context_group VARCHAR(128) NOT NULL DEFAULT '',
          source_kind VARCHAR(64) NOT NULL DEFAULT 'runtime',
          source_path VARCHAR(512) NOT NULL DEFAULT '',
          transform_kind VARCHAR(128) NOT NULL DEFAULT 'copy',
          include_phase VARCHAR(64) NOT NULL DEFAULT '',
          required TINYINT(1) NOT NULL DEFAULT 1,
          include_in_prompt TINYINT(1) NOT NULL DEFAULT 1,
          max_items INT NULL,
          max_chars INT NULL,
          failure_code VARCHAR(255) NULL,
          context_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_gpt_context_key (contract_name, context_key, include_phase),
          KEY idx_post_intake_gpt_context_contract (contract_name),
          KEY idx_post_intake_gpt_context_group (context_group),
          KEY idx_post_intake_gpt_context_status (context_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      for row in _DEFAULT_GPT_CONTEXT_ROWS:
        cur.execute(
          f"""
          INSERT INTO {_GPT_CONTEXT_TABLE_NAME} (
            contract_name,
            context_key,
            context_group,
            source_kind,
            source_path,
            transform_kind,
            include_phase,
            required,
            include_in_prompt,
            max_items,
            max_chars,
            failure_code,
            context_status,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
          ON DUPLICATE KEY UPDATE
            context_group = VALUES(context_group),
            source_kind = VALUES(source_kind),
            source_path = VALUES(source_path),
            transform_kind = VALUES(transform_kind),
            required = VALUES(required),
            include_in_prompt = VALUES(include_in_prompt),
            max_items = VALUES(max_items),
            max_chars = VALUES(max_chars),
            failure_code = VALUES(failure_code),
            context_status = VALUES(context_status),
            notes = VALUES(notes)
          """,
          (
            _clean_text(row.get("contract_name")).lower(),
            _clean_text(row.get("context_key")),
            _clean_text(row.get("context_group")).lower(),
            _clean_text(row.get("source_kind")).lower() or "runtime",
            _clean_text(row.get("source_path")),
            _clean_text(row.get("transform_kind")).lower() or "copy",
            _clean_text(row.get("include_phase")).lower(),
            1 if bool(row.get("required")) else 0,
            1 if bool(row.get("include_in_prompt")) else 0,
            row.get("max_items"),
            row.get("max_chars"),
            _clean_text(row.get("failure_code")),
            _clean_text(row.get("notes")),
          ),
        )
      cur.execute(
        f"""
        UPDATE {_GPT_CONTEXT_TABLE_NAME}
        SET required = 0,
            include_in_prompt = 0,
            notes = 'Prompts render contract structure from SQL directly; this duplicate context payload is intentionally disabled.'
        WHERE contract_name IN ('stage_ramp_contract', 'payroll_headcount_schedule')
          AND context_key IN ('contract_field_spec', 'required_response_shape')
          AND include_phase = 'pre_convergence'
        """
      )
      cur.execute(
        f"""
        UPDATE {_GPT_CONTEXT_TABLE_NAME}
        SET required = 0,
            include_in_prompt = 0,
            context_status = 'retired',
            notes = 'Retired: payroll is owned by payroll_headcount_schedule, not stage_ramp_contract.'
        WHERE contract_name = 'stage_ramp_contract'
          AND context_key IN ('payroll_headcount_policy', 'payroll_budget_context', 'payroll_budget_checklist', 'people_staffing_context')
          AND include_phase = 'pre_convergence'
        """
      )
      cur.execute(
        f"""
        DELETE FROM {_GPT_CONTEXT_TABLE_NAME}
        WHERE contract_name = 'payroll_headcount_schedule'
          AND context_key IN ('payroll_economic_guardrails', 'payroll_required_fte_grid')
          AND include_phase = 'pre_convergence'
        """
      )
      cur.execute(
        f"""
        DELETE FROM {_GPT_CONTEXT_TABLE_NAME}
        WHERE contract_name = 'payroll_headcount_schedule'
          AND context_key = 'oews_role_catalog'
          AND include_phase = 'pre_convergence'
        """
      )
      conn.commit()
      _ENSURE_GPT_CONTEXT_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def _ensure_process_sequence_lookup_table(conn) -> None:
  global _ENSURE_PROCESS_SEQUENCE_TABLE_READY
  if _ENSURE_PROCESS_SEQUENCE_TABLE_READY:
    return
  with _ENSURE_PROCESS_SEQUENCE_TABLE_LOCK:
    if _ENSURE_PROCESS_SEQUENCE_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_PROCESS_SEQUENCE_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          phase VARCHAR(64) NOT NULL,
          step_order INT NOT NULL,
          step_key VARCHAR(128) NOT NULL,
          handler_key VARCHAR(128) NOT NULL,
          parent_step_key VARCHAR(128) NOT NULL DEFAULT '',
          step_kind VARCHAR(64) NOT NULL DEFAULT 'process',
          hierarchy_level INT NOT NULL DEFAULT 1,
          sequence_path VARCHAR(255) NOT NULL DEFAULT '',
          executor_function VARCHAR(255) NOT NULL DEFAULT '',
          contract_name VARCHAR(128) NOT NULL DEFAULT '',
          context_contract_name VARCHAR(128) NOT NULL DEFAULT '',
          context_include_phase VARCHAR(64) NOT NULL DEFAULT '',
          required_context_keys_json LONGTEXT NOT NULL,
          produced_output_keys_json LONGTEXT NOT NULL,
          output_storage_json LONGTEXT NULL,
          recompute_triggers_json LONGTEXT NULL,
          output_finality VARCHAR(128) NOT NULL DEFAULT 'stage_final_no_downstream_mutation',
          required_lookup_tables_json LONGTEXT NOT NULL,
          horizon_rule VARCHAR(128) NOT NULL DEFAULT '',
          timeout_seconds DECIMAL(10,2) NULL,
          max_attempts INT NULL,
          required TINYINT(1) NOT NULL DEFAULT 1,
          enabled TINYINT(1) NOT NULL DEFAULT 1,
          fail_fast_code VARCHAR(255) NOT NULL,
          python_role VARCHAR(128) NOT NULL DEFAULT 'deterministic_step_executor',
          python_timing VARCHAR(128) NOT NULL DEFAULT '',
          python_action LONGTEXT NULL,
          input_object_path LONGTEXT NULL,
          output_object_path LONGTEXT NULL,
          validation_subject_path LONGTEXT NULL,
          object_controls_json LONGTEXT NULL,
          sequence_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_process_sequence_step (step_key),
          KEY idx_post_intake_process_sequence_parent (parent_step_key),
          KEY idx_post_intake_process_sequence_phase_order (phase, step_order),
          KEY idx_post_intake_process_sequence_status (sequence_status),
          KEY idx_post_intake_process_sequence_handler (handler_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      for ddl in [
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN python_role VARCHAR(128) NOT NULL DEFAULT 'deterministic_step_executor' AFTER fail_fast_code",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN python_timing VARCHAR(128) NOT NULL DEFAULT '' AFTER python_role",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN python_action LONGTEXT NULL AFTER python_timing",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN input_object_path LONGTEXT NULL AFTER python_action",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN output_object_path LONGTEXT NULL AFTER input_object_path",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN validation_subject_path LONGTEXT NULL AFTER output_object_path",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN object_controls_json LONGTEXT NULL AFTER validation_subject_path",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN parent_step_key VARCHAR(128) NOT NULL DEFAULT '' AFTER handler_key",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN step_kind VARCHAR(64) NOT NULL DEFAULT 'process' AFTER parent_step_key",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN hierarchy_level INT NOT NULL DEFAULT 1 AFTER step_kind",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN sequence_path VARCHAR(255) NOT NULL DEFAULT '' AFTER hierarchy_level",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN executor_function VARCHAR(255) NOT NULL DEFAULT '' AFTER sequence_path",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN required_context_keys_json LONGTEXT NULL AFTER context_include_phase",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN produced_output_keys_json LONGTEXT NULL AFTER required_context_keys_json",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN output_storage_json LONGTEXT NULL AFTER produced_output_keys_json",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN recompute_triggers_json LONGTEXT NULL AFTER output_storage_json",
        f"ALTER TABLE {_PROCESS_SEQUENCE_TABLE_NAME} ADD COLUMN output_finality VARCHAR(128) NOT NULL DEFAULT 'stage_final_no_downstream_mutation' AFTER recompute_triggers_json",
      ]:
        try:
          cur.execute(ddl)
        except Exception as exc:
          if "Duplicate column" not in str(exc):
            raise
      for row in _DEFAULT_PROCESS_SEQUENCE_ROWS:
        cur.execute(
          f"""
          INSERT INTO {_PROCESS_SEQUENCE_TABLE_NAME} (
            phase,
            step_order,
            step_key,
            handler_key,
            parent_step_key,
            step_kind,
            hierarchy_level,
            sequence_path,
            executor_function,
            contract_name,
            context_contract_name,
            context_include_phase,
            required_context_keys_json,
            produced_output_keys_json,
            output_storage_json,
            recompute_triggers_json,
            output_finality,
            required_lookup_tables_json,
            horizon_rule,
            timeout_seconds,
            max_attempts,
            required,
            enabled,
            fail_fast_code,
            python_role,
            python_timing,
            python_action,
            input_object_path,
            output_object_path,
            validation_subject_path,
            object_controls_json,
            sequence_status,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
          ON DUPLICATE KEY UPDATE
            phase = VALUES(phase),
            step_order = VALUES(step_order),
            handler_key = VALUES(handler_key),
            parent_step_key = VALUES(parent_step_key),
            step_kind = VALUES(step_kind),
            hierarchy_level = VALUES(hierarchy_level),
            sequence_path = VALUES(sequence_path),
            executor_function = VALUES(executor_function),
            contract_name = VALUES(contract_name),
            context_contract_name = VALUES(context_contract_name),
            context_include_phase = VALUES(context_include_phase),
            required_context_keys_json = VALUES(required_context_keys_json),
            produced_output_keys_json = VALUES(produced_output_keys_json),
            output_storage_json = VALUES(output_storage_json),
            recompute_triggers_json = VALUES(recompute_triggers_json),
            output_finality = VALUES(output_finality),
            required_lookup_tables_json = VALUES(required_lookup_tables_json),
            horizon_rule = VALUES(horizon_rule),
            timeout_seconds = VALUES(timeout_seconds),
            max_attempts = VALUES(max_attempts),
            required = VALUES(required),
            enabled = VALUES(enabled),
            fail_fast_code = VALUES(fail_fast_code),
            python_role = VALUES(python_role),
            python_timing = VALUES(python_timing),
            python_action = VALUES(python_action),
            input_object_path = VALUES(input_object_path),
            output_object_path = VALUES(output_object_path),
            validation_subject_path = VALUES(validation_subject_path),
            object_controls_json = VALUES(object_controls_json),
            sequence_status = VALUES(sequence_status),
            notes = VALUES(notes)
          """,
          (
            _clean_text(row.get("phase")).lower(),
            int(row.get("step_order") or 0),
            _clean_text(row.get("step_key")).lower(),
            _clean_text(row.get("handler_key")),
            _clean_text(row.get("parent_step_key")).lower(),
            _clean_text(row.get("step_kind")).lower() or "process",
            int(row.get("hierarchy_level") or 1),
            _clean_text(row.get("sequence_path")).lower(),
            _clean_text(row.get("executor_function")) or _clean_text(row.get("handler_key")),
            _clean_text(row.get("contract_name")).lower(),
            _clean_text(row.get("context_contract_name")).lower(),
            _clean_text(row.get("context_include_phase")).lower(),
            _json_dumps_value(row.get("required_context_keys") or []),
            _json_dumps_value(row.get("produced_output_keys") or []),
            _json_dumps_value(row.get("output_storage") or []),
            _json_dumps_value(row.get("recompute_triggers") or []),
            _clean_text(row.get("output_finality")).lower() or "stage_final_no_downstream_mutation",
            _json_dumps_value(row.get("required_lookup_tables") or []),
            _clean_text(row.get("horizon_rule")).lower(),
            row.get("timeout_seconds"),
            row.get("max_attempts"),
            1 if bool(row.get("required")) else 0,
            1 if bool(row.get("enabled")) else 0,
            _clean_text(row.get("fail_fast_code")) or f"{_clean_text(row.get('step_key')).lower()}_sequence_violation",
            _clean_text(row.get("python_role")) or "deterministic_step_executor",
            _clean_text(row.get("python_timing")) or _clean_text(row.get("phase")).lower(),
            _clean_text(row.get("python_action")),
            _clean_text(row.get("input_object_path")),
            _clean_text(row.get("output_object_path")),
            _clean_text(row.get("validation_subject_path")),
            _json_dumps_value(row.get("object_controls") or []),
            _clean_text(row.get("notes")),
          ),
        )
      conn.commit()
      _ENSURE_PROCESS_SEQUENCE_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def _ensure_process_context_lookup_table(conn) -> None:
  global _ENSURE_PROCESS_CONTEXT_TABLE_READY
  if _ENSURE_PROCESS_CONTEXT_TABLE_READY:
    return
  with _ENSURE_PROCESS_CONTEXT_TABLE_LOCK:
    if _ENSURE_PROCESS_CONTEXT_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_PROCESS_CONTEXT_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          step_key VARCHAR(128) NOT NULL,
          context_key VARCHAR(128) NOT NULL,
          context_domain VARCHAR(64) NOT NULL DEFAULT '',
          source_kind VARCHAR(64) NOT NULL DEFAULT 'runtime_context',
          source_path LONGTEXT NULL,
          transform_kind VARCHAR(64) NOT NULL DEFAULT 'copy',
          required TINYINT(1) NOT NULL DEFAULT 1,
          immutable_input TINYINT(1) NOT NULL DEFAULT 1,
          context_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_process_context (step_key, context_key),
          KEY idx_post_intake_process_context_step (step_key),
          KEY idx_post_intake_process_context_status (context_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      for ddl in [
        f"ALTER TABLE {_PROCESS_CONTEXT_TABLE_NAME} ADD COLUMN context_domain VARCHAR(64) NOT NULL DEFAULT '' AFTER context_key",
        f"ALTER TABLE {_PROCESS_CONTEXT_TABLE_NAME} ADD COLUMN source_kind VARCHAR(64) NOT NULL DEFAULT 'runtime_context' AFTER context_domain",
        f"ALTER TABLE {_PROCESS_CONTEXT_TABLE_NAME} ADD COLUMN source_path LONGTEXT NULL AFTER source_kind",
        f"ALTER TABLE {_PROCESS_CONTEXT_TABLE_NAME} ADD COLUMN transform_kind VARCHAR(64) NOT NULL DEFAULT 'copy' AFTER source_path",
        f"ALTER TABLE {_PROCESS_CONTEXT_TABLE_NAME} ADD COLUMN required TINYINT(1) NOT NULL DEFAULT 1 AFTER transform_kind",
        f"ALTER TABLE {_PROCESS_CONTEXT_TABLE_NAME} ADD COLUMN immutable_input TINYINT(1) NOT NULL DEFAULT 1 AFTER required",
        f"ALTER TABLE {_PROCESS_CONTEXT_TABLE_NAME} ADD COLUMN context_status VARCHAR(32) NOT NULL DEFAULT 'active' AFTER immutable_input",
      ]:
        try:
          cur.execute(ddl)
        except Exception as exc:
          if "Duplicate column" not in str(exc):
            raise
      for row in _DEFAULT_PROCESS_CONTEXT_ROWS:
        cur.execute(
          f"""
          INSERT INTO {_PROCESS_CONTEXT_TABLE_NAME} (
            step_key,
            context_key,
            context_domain,
            source_kind,
            source_path,
            transform_kind,
            required,
            immutable_input,
            context_status,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
          ON DUPLICATE KEY UPDATE
            context_domain = VALUES(context_domain),
            source_kind = VALUES(source_kind),
            source_path = VALUES(source_path),
            transform_kind = VALUES(transform_kind),
            required = VALUES(required),
            immutable_input = VALUES(immutable_input),
            context_status = VALUES(context_status),
            notes = VALUES(notes)
          """,
          (
            _clean_text(row.get("step_key")).lower(),
            _clean_text(row.get("context_key")),
            _clean_text(row.get("context_domain")).lower(),
            _clean_text(row.get("source_kind")).lower() or "runtime_context",
            _clean_text(row.get("source_path")),
            _clean_text(row.get("transform_kind")).lower() or "copy",
            1 if bool(row.get("required")) else 0,
            1 if bool(row.get("immutable_input")) else 0,
            _clean_text(row.get("notes")),
          ),
        )
      conn.commit()
      _ENSURE_PROCESS_CONTEXT_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def _ensure_headcount_policy_lookup_table(conn) -> None:
  try:
    from client_intake_and_finmo.post_intake_headcount import ensure_post_intake_headcount_policy_lookup_table  # type: ignore
  except Exception:
    from post_intake_headcount import ensure_post_intake_headcount_policy_lookup_table  # type: ignore
  ensure_post_intake_headcount_policy_lookup_table(conn)


def _post_intake_snapshot_source_tables() -> List[str]:
  return [
    _MAPPING_TABLE_NAME,
    _CASH_POLICY_TABLE_NAME,
    _GPT_CONTRACT_TABLE_NAME,
    _GPT_CONTEXT_TABLE_NAME,
    "post_intake_headcount_policy_lookup",
    _PROCESS_SEQUENCE_TABLE_NAME,
    _PROCESS_CONTEXT_TABLE_NAME,
  ]


def _ensure_lookup_snapshot_table(conn) -> None:
  global _ENSURE_LOOKUP_SNAPSHOT_TABLE_READY
  if _ENSURE_LOOKUP_SNAPSHOT_TABLE_READY:
    return
  with _ENSURE_LOOKUP_SNAPSHOT_TABLE_LOCK:
    if _ENSURE_LOOKUP_SNAPSHOT_TABLE_READY:
      return
    cur = conn.cursor()
    try:
      cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_LOOKUP_SNAPSHOT_TABLE_NAME} (
          id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
          baseline_name VARCHAR(128) NOT NULL,
          source_commit VARCHAR(64) NOT NULL DEFAULT '',
          table_name VARCHAR(128) NOT NULL,
          row_count INT NOT NULL,
          content_hash CHAR(64) NOT NULL,
          snapshot_json LONGTEXT NOT NULL,
          snapshot_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_lookup_snapshot (baseline_name, table_name),
          KEY idx_post_intake_lookup_snapshot_status (snapshot_status),
          KEY idx_post_intake_lookup_snapshot_commit (source_commit)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
      )
      conn.commit()
      _ENSURE_LOOKUP_SNAPSHOT_TABLE_READY = True
    finally:
      try:
        cur.close()
      except Exception:
        pass


def _ensure_all_post_intake_lookup_tables(conn) -> None:
  _ensure_mapping_lookup_table(conn)
  _ensure_cash_policy_lookup_table(conn)
  _ensure_gpt_contract_lookup_table(conn)
  _ensure_gpt_context_lookup_table(conn)
  _ensure_headcount_policy_lookup_table(conn)
  _ensure_process_sequence_lookup_table(conn)
  _ensure_process_context_lookup_table(conn)
  _ensure_lookup_snapshot_table(conn)


def _json_safe_snapshot_value(value: Any) -> Any:
  if value is None:
    return None
  if isinstance(value, (str, int, float, bool)):
    return value
  return str(value)


def _semantic_lookup_table_rows(conn, table_name: str) -> List[Dict[str, Any]]:
  if table_name not in set(_post_intake_snapshot_source_tables()):
    raise RuntimeError(f"post_intake_lookup_snapshot_unsupported_table: {table_name}")
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(f"SELECT * FROM `{table_name}` ORDER BY id ASC")
    raw_rows = cur.fetchall() or []
  finally:
    try:
      cur.close()
    except Exception:
      pass
  rows: List[Dict[str, Any]] = []
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    row: Dict[str, Any] = {}
    for key in sorted(raw_row.keys()):
      if key in {"id", "created_at", "updated_at"}:
        continue
      row[str(key)] = _json_safe_snapshot_value(raw_row.get(key))
    rows.append(row)
  return rows


def _lookup_table_snapshot_hash(rows: List[Dict[str, Any]]) -> str:
  payload = json.dumps(
    rows,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
  )
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refresh_post_intake_lookup_table_snapshot(
  *,
  baseline_name: Any = _GOLDEN_BASELINE_NAME,
  source_commit: Any = "",
  notes: Any = "",
) -> List[Dict[str, Any]]:
  """Freeze the semantic contents of every post-intake lookup table in SQL.

  This is the table-backed baseline used to prove future fixes have not drifted
  away from the current Golden Rule architecture.
  """
  _ensure_env_loaded()
  normalized_baseline = _clean_text(baseline_name).lower() or _GOLDEN_BASELINE_NAME
  normalized_commit = _clean_text(source_commit)
  conn = get_mysql_connection()
  snapshots: List[Dict[str, Any]] = []
  try:
    _ensure_all_post_intake_lookup_tables(conn)
    cur = conn.cursor()
    try:
      for table_name in _post_intake_snapshot_source_tables():
        rows = _semantic_lookup_table_rows(conn, table_name)
        snapshot_json = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        content_hash = _lookup_table_snapshot_hash(rows)
        cur.execute(
          f"""
          INSERT INTO {_LOOKUP_SNAPSHOT_TABLE_NAME} (
            baseline_name,
            source_commit,
            table_name,
            row_count,
            content_hash,
            snapshot_json,
            snapshot_status,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)
          ON DUPLICATE KEY UPDATE
            source_commit = VALUES(source_commit),
            row_count = VALUES(row_count),
            content_hash = VALUES(content_hash),
            snapshot_json = VALUES(snapshot_json),
            snapshot_status = 'active',
            notes = VALUES(notes)
          """,
          (
            normalized_baseline,
            normalized_commit,
            table_name,
            len(rows),
            content_hash,
            snapshot_json,
            _clean_text(notes),
          ),
        )
        snapshots.append(
          {
            "baseline_name": normalized_baseline,
            "source_commit": normalized_commit,
            "table_name": table_name,
            "row_count": len(rows),
            "content_hash": content_hash,
            "source_of_truth": f"sql.{_LOOKUP_SNAPSHOT_TABLE_NAME}",
          }
        )
      conn.commit()
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  post_intake_lookup_table_snapshot_rows.cache_clear()
  return snapshots


@lru_cache(maxsize=16)
def post_intake_lookup_table_snapshot_rows(
  *,
  baseline_name: Any = _GOLDEN_BASELINE_NAME,
) -> List[Dict[str, Any]]:
  _ensure_env_loaded()
  normalized_baseline = _clean_text(baseline_name).lower() or _GOLDEN_BASELINE_NAME
  conn = get_mysql_connection()
  try:
    _ensure_all_post_intake_lookup_tables(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          baseline_name,
          source_commit,
          table_name,
          row_count,
          content_hash,
          snapshot_status,
          notes
        FROM {_LOOKUP_SNAPSHOT_TABLE_NAME}
        WHERE baseline_name = %s
          AND snapshot_status = 'active'
        ORDER BY table_name ASC
        """,
        (normalized_baseline,),
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  rows: List[Dict[str, Any]] = []
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    rows.append(
      {
        "baseline_name": _clean_text(raw_row.get("baseline_name")).lower(),
        "source_commit": _clean_text(raw_row.get("source_commit")),
        "table_name": _clean_text(raw_row.get("table_name")),
        "row_count": int(raw_row.get("row_count") or 0),
        "content_hash": _clean_text(raw_row.get("content_hash")),
        "snapshot_status": _clean_text(raw_row.get("snapshot_status")).lower() or "active",
        "notes": _clean_text(raw_row.get("notes")),
        "source_of_truth": f"sql.{_LOOKUP_SNAPSHOT_TABLE_NAME}",
      }
    )
  return rows


def post_intake_lookup_table_snapshot_errors(
  *,
  baseline_name: Any = _GOLDEN_BASELINE_NAME,
) -> List[str]:
  normalized_baseline = _clean_text(baseline_name).lower() or _GOLDEN_BASELINE_NAME
  expected_tables = set(_post_intake_snapshot_source_tables())
  snapshot_rows = post_intake_lookup_table_snapshot_rows(baseline_name=normalized_baseline)
  if not snapshot_rows:
    return [
      f"post_intake_lookup_table_snapshot_missing: baseline={normalized_baseline} table={_LOOKUP_SNAPSHOT_TABLE_NAME}"
    ]
  snapshot_by_table = {
    _clean_text(row.get("table_name")): row
    for row in snapshot_rows
    if _clean_text(row.get("table_name"))
  }
  errors: List[str] = []
  missing = sorted(expected_tables - set(snapshot_by_table.keys()))
  for table_name in missing:
    errors.append(f"post_intake_lookup_table_snapshot_missing_table: baseline={normalized_baseline} table={table_name}")
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_all_post_intake_lookup_tables(conn)
    for table_name in sorted(expected_tables):
      snapshot = snapshot_by_table.get(table_name)
      if not snapshot:
        continue
      live_rows = _semantic_lookup_table_rows(conn, table_name)
      live_hash = _lookup_table_snapshot_hash(live_rows)
      expected_hash = _clean_text(snapshot.get("content_hash"))
      expected_count = int(snapshot.get("row_count") or 0)
      if len(live_rows) != expected_count:
        errors.append(
          f"post_intake_lookup_table_snapshot_row_count_mismatch: table={table_name} expected={expected_count} actual={len(live_rows)}"
        )
      if live_hash != expected_hash:
        errors.append(
          f"post_intake_lookup_table_snapshot_hash_mismatch: table={table_name} expected={expected_hash} actual={live_hash}"
        )
  finally:
    try:
      conn.close()
    except Exception:
      pass
  return errors


@lru_cache(maxsize=1)
def load_post_intake_driver_target_mapping_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_mapping_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          lever_id,
          driver_category,
          target_driver,
          model_input_field,
          financial_model_field,
          impact_type,
          post_intake_issue_codes,
          post_intake_phase,
          control_owner,
          value_kind,
          target_value_kind,
          value_rounding_kind,
          value_decimal_places,
          target_rounding_kind,
          target_decimal_places,
          input_semantics,
          driver_bundle,
          cash_strategy_role,
          targeting_allowed,
          diagnostic_only,
          tolerance_allowed,
          non_tolerable_issue_codes,
          repair_direction_rules_json,
          seed_source_paths_json,
          seed_formula_key,
          finmo_formula_key,
          validation_formula_key,
          required_when_key,
          business_applicability_key,
          applicability_positive_tokens_json,
          applicability_negative_tokens_json,
          forecast_presence_rule_key,
          zero_allowed_reason_key,
          missing_seed_default_value,
          minimum_live_value,
          maximum_live_value,
          allow_zero,
          formula_status,
          mapping_status,
          notes
        FROM {_MAPPING_TABLE_NAME}
        ORDER BY id ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    lever_id = _clean_text(raw_row.get("lever_id"))
    if not lever_id:
      continue
    row = {
      "lever_id": lever_id,
      "driver_category": _clean_text(raw_row.get("driver_category")).lower(),
      "target_driver": _clean_text(raw_row.get("target_driver")),
      "model_input_field": _clean_text(raw_row.get("model_input_field")),
      "financial_model_field": _clean_text(raw_row.get("financial_model_field")),
      "impact_type": _clean_text(raw_row.get("impact_type")).lower(),
      "post_intake_issue_codes": _split_tokens(raw_row.get("post_intake_issue_codes")),
      "post_intake_phase": _clean_text(raw_row.get("post_intake_phase")).lower(),
      "control_owner": _clean_text(raw_row.get("control_owner")).lower(),
      "value_kind": _clean_text(raw_row.get("value_kind")).lower(),
      "target_value_kind": (
        _clean_text(raw_row.get("target_value_kind")).lower()
        or _default_target_value_kind(raw_row.get("financial_model_field"))
      ),
      "value_precision": _normalize_precision_metadata(
        value_kind=raw_row.get("value_kind"),
        rounding_kind=raw_row.get("value_rounding_kind"),
        decimal_places=raw_row.get("value_decimal_places"),
      ),
      "target_precision": _normalize_precision_metadata(
        value_kind=(
          _clean_text(raw_row.get("target_value_kind")).lower()
          or _default_target_value_kind(raw_row.get("financial_model_field"))
        ),
        rounding_kind=raw_row.get("target_rounding_kind"),
        decimal_places=raw_row.get("target_decimal_places"),
      ),
      "input_semantics": _clean_text(raw_row.get("input_semantics")).lower(),
      "driver_bundle": _clean_text(raw_row.get("driver_bundle")).lower(),
      "cash_strategy_role": _clean_text(raw_row.get("cash_strategy_role")).lower(),
      "targeting_allowed": _clean_bool(raw_row.get("targeting_allowed")),
      "diagnostic_only": _clean_bool(raw_row.get("diagnostic_only")),
      "tolerance_allowed": _clean_bool(raw_row.get("tolerance_allowed"), default=True),
      "non_tolerable_issue_codes": _split_tokens(raw_row.get("non_tolerable_issue_codes")),
      "repair_direction_rules": _json_value(raw_row.get("repair_direction_rules_json"), {}),
      "seed_source_paths_json": _json_value(raw_row.get("seed_source_paths_json"), []),
      "seed_formula_key": _clean_text(raw_row.get("seed_formula_key")).lower(),
      "finmo_formula_key": _clean_text(raw_row.get("finmo_formula_key")).lower(),
      "validation_formula_key": _clean_text(raw_row.get("validation_formula_key")).lower(),
      "required_when_key": _clean_text(raw_row.get("required_when_key")).lower(),
      "business_applicability_key": _clean_text(raw_row.get("business_applicability_key")).lower(),
      "applicability_positive_tokens": _json_value(raw_row.get("applicability_positive_tokens_json"), []),
      "applicability_negative_tokens": _json_value(raw_row.get("applicability_negative_tokens_json"), []),
      "forecast_presence_rule_key": _clean_text(raw_row.get("forecast_presence_rule_key")).lower(),
      "zero_allowed_reason_key": _clean_text(raw_row.get("zero_allowed_reason_key")).lower(),
      "missing_seed_default_value": raw_row.get("missing_seed_default_value"),
      "minimum_live_value": raw_row.get("minimum_live_value"),
      "maximum_live_value": raw_row.get("maximum_live_value"),
      "allow_zero": _clean_bool(raw_row.get("allow_zero"), default=True),
      "formula_status": _clean_text(raw_row.get("formula_status")).lower() or "active",
      "mapping_status": _clean_text(raw_row.get("mapping_status")).lower() or "active",
      "notes": _clean_text(raw_row.get("notes")),
    }
    formula_defaults = mapping_formula_defaults(row)
    if not row["seed_source_paths_json"]:
      row["seed_source_paths_json"] = list(formula_defaults.get("seed_source_paths") or [])
    if not row["seed_formula_key"] or row["seed_formula_key"] == "none":
      row["seed_formula_key"] = str(formula_defaults.get("seed_formula_key") or "none")
    if not row["finmo_formula_key"] or row["finmo_formula_key"] == "none":
      row["finmo_formula_key"] = str(formula_defaults.get("finmo_formula_key") or "none")
    if not row["validation_formula_key"] or row["validation_formula_key"] == "none":
      row["validation_formula_key"] = str(formula_defaults.get("validation_formula_key") or "semantic_presence_only")
    if not row["required_when_key"]:
      row["required_when_key"] = str(formula_defaults.get("required_when_key") or "always")
    if not row["business_applicability_key"]:
      row["business_applicability_key"] = str(formula_defaults.get("business_applicability_key") or "always")
    if not row["forecast_presence_rule_key"]:
      row["forecast_presence_rule_key"] = str(formula_defaults.get("forecast_presence_rule_key") or "nonnegative_driver")
    if not row["zero_allowed_reason_key"]:
      row["zero_allowed_reason_key"] = str(formula_defaults.get("zero_allowed_reason_key") or "not_applicable_or_table_optional")
    if row.get("missing_seed_default_value") is None:
      row["missing_seed_default_value"] = formula_defaults.get("missing_seed_default_value")
    if row.get("minimum_live_value") is None:
      row["minimum_live_value"] = formula_defaults.get("minimum_live_value")
    if row.get("maximum_live_value") is None:
      row["maximum_live_value"] = formula_defaults.get("maximum_live_value")
    row["target_metric_name"] = _normalized_metric_id_from_field(row.get("financial_model_field"))
    row["lookup_lever_id"] = _normalized_lookup_key(lever_id)
    row["value_rounding_kind"] = _clean_text((row.get("value_precision") or {}).get("rounding_kind")).lower()
    row["value_decimal_places"] = (row.get("value_precision") or {}).get("decimal_places")
    row["target_rounding_kind"] = _clean_text((row.get("target_precision") or {}).get("rounding_kind")).lower()
    row["target_decimal_places"] = (row.get("target_precision") or {}).get("decimal_places")
    row["formula_contract"] = formula_contract_for_mapping_row(row)
    rows.append(row)
  if not rows:
    raise RuntimeError(f"{_MAPPING_TABLE_NAME}_empty: post-intake mapping lookup table has no rows")
  return rows


def _active_mapping_rows() -> List[Dict[str, Any]]:
  return [
    dict(row)
    for row in load_post_intake_driver_target_mapping_rows()
    if _clean_text(row.get("mapping_status")).lower() == "active"
  ]


@lru_cache(maxsize=1)
def load_post_intake_cash_policy_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_cash_policy_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          cash_strategy,
          debt_position,
          debt_to_equity_min,
          debt_to_equity_max,
          cash_floor_months,
          cash_ceiling_months,
          distribution_weight,
          debt_paydown_weight,
          retain_weight,
          deploy_above_ceiling_required,
          debt_schedule_method,
          debt_schedule_required,
          debt_schedule_horizon_quarters,
          debt_minimum_payment_frequency,
          debt_min_principal_source_priority_json,
          debt_extra_paydown_policy,
          debt_interest_rate_source_required,
          debt_interest_rate_fallback_allowed,
          cash_phase_sequence_json,
          policy_label,
          policy_status,
          notes
        FROM {_CASH_POLICY_TABLE_NAME}
        ORDER BY
          FIELD(cash_strategy, 'shareholder_return', 'balanced', 'preserve_cash'),
          debt_to_equity_min ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    strategy = _clean_text(raw_row.get("cash_strategy")).lower()
    position = _clean_text(raw_row.get("debt_position")).lower()
    if not strategy or not position:
      continue
    phase_sequence = _json_value(raw_row.get("cash_phase_sequence_json"), [])
    principal_source_priority = _json_value(raw_row.get("debt_min_principal_source_priority_json"), [])
    rows.append(
      {
        "cash_strategy": strategy,
        "debt_position": position,
        "debt_to_equity_min": float(raw_row.get("debt_to_equity_min") or 0.0),
        "debt_to_equity_max": float(raw_row.get("debt_to_equity_max") or 0.0),
        "cash_floor_months": float(raw_row.get("cash_floor_months") or 0.0),
        "cash_ceiling_months": float(raw_row.get("cash_ceiling_months") or 0.0),
        "distribution_weight": float(raw_row.get("distribution_weight") or 0.0),
        "debt_paydown_weight": float(raw_row.get("debt_paydown_weight") or 0.0),
        "retain_weight": float(raw_row.get("retain_weight") or 0.0),
        "deploy_above_ceiling_required": _clean_bool(raw_row.get("deploy_above_ceiling_required"), default=True),
        "debt_schedule_method": _clean_text(raw_row.get("debt_schedule_method")).lower(),
        "debt_schedule_required": _clean_bool(raw_row.get("debt_schedule_required"), default=True),
        "debt_schedule_horizon_quarters": int(float(raw_row.get("debt_schedule_horizon_quarters") or 0)),
        "debt_minimum_payment_frequency": _clean_text(raw_row.get("debt_minimum_payment_frequency")).lower(),
        "debt_min_principal_source_priority": principal_source_priority if isinstance(principal_source_priority, list) else [],
        "debt_extra_paydown_policy": _clean_text(raw_row.get("debt_extra_paydown_policy")).lower(),
        "debt_interest_rate_source_required": _clean_text(raw_row.get("debt_interest_rate_source_required")),
        "debt_interest_rate_fallback_allowed": _clean_bool(raw_row.get("debt_interest_rate_fallback_allowed")),
        "cash_phase_sequence": phase_sequence if isinstance(phase_sequence, list) else [],
        "policy_label": _clean_text(raw_row.get("policy_label")),
        "policy_status": _clean_text(raw_row.get("policy_status")).lower() or "active",
        "notes": _clean_text(raw_row.get("notes")),
      }
    )
  if not rows:
    raise RuntimeError(f"{_CASH_POLICY_TABLE_NAME}_empty: cash policy lookup table has no rows")
  return rows


@lru_cache(maxsize=1)
def load_post_intake_gpt_contract_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_gpt_contract_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          contract_name,
          grid_name,
          field_path,
          field_name,
          field_type,
          required,
          strict_required,
          allow_null,
          allow_empty,
          is_array_item,
          parent_field_path,
          json_schema_type,
          min_value,
          max_value,
          naics_baseline_metric_key,
          naics_baseline_band_kind,
          naics_baseline_min_quantile,
          naics_baseline_max_quantile,
          mapping_table_outer_envelope,
          min_items,
          max_items,
          item_contract_grid_name,
          additional_properties_allowed,
          gpt_owned,
          python_owned,
          editable,
          must_match_lookup,
          contract_phase,
          horizon_rule,
          normalization_kind,
          rounding_kind,
          decimal_places,
          validation_kind,
          lookup_source,
          enum_values,
          allowed_aliases,
          prompt_required_instruction,
          prompt_label,
          failure_code,
          contract_status,
          notes
        FROM {_GPT_CONTRACT_TABLE_NAME}
        ORDER BY contract_name ASC, grid_name ASC, id ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    contract_name = _clean_text(raw_row.get("contract_name")).lower()
    grid_name = _clean_text(raw_row.get("grid_name")).lower()
    field_path = _clean_text(raw_row.get("field_path"))
    field_name = _clean_text(raw_row.get("field_name"))
    if not contract_name or not grid_name or not field_path or not field_name:
      continue
    rows.append(
      {
        "contract_name": contract_name,
        "grid_name": grid_name,
        "field_path": field_path,
        "field_name": field_name,
        "field_type": _clean_text(raw_row.get("field_type")).lower(),
        "required": _clean_bool(raw_row.get("required"), default=True),
        "strict_required": _clean_bool(raw_row.get("strict_required"), default=True),
        "allow_null": _clean_bool(raw_row.get("allow_null")),
        "allow_empty": _clean_bool(raw_row.get("allow_empty")),
        "is_array_item": _clean_bool(raw_row.get("is_array_item")),
        "parent_field_path": _clean_text(raw_row.get("parent_field_path")),
        "json_schema_type": _clean_text(raw_row.get("json_schema_type")).lower() or "string",
        "min_value": float(raw_row.get("min_value")) if raw_row.get("min_value") is not None else None,
        "max_value": float(raw_row.get("max_value")) if raw_row.get("max_value") is not None else None,
        "naics_baseline_metric_key": _clean_text(raw_row.get("naics_baseline_metric_key")) or None,
        "naics_baseline_band_kind": _clean_text(raw_row.get("naics_baseline_band_kind")) or None,
        "naics_baseline_min_quantile": float(raw_row.get("naics_baseline_min_quantile")) if raw_row.get("naics_baseline_min_quantile") is not None else None,
        "naics_baseline_max_quantile": float(raw_row.get("naics_baseline_max_quantile")) if raw_row.get("naics_baseline_max_quantile") is not None else None,
        "mapping_table_outer_envelope": _clean_bool(raw_row.get("mapping_table_outer_envelope"), default=True),
        "min_items": int(raw_row.get("min_items")) if raw_row.get("min_items") is not None else None,
        "max_items": int(raw_row.get("max_items")) if raw_row.get("max_items") is not None else None,
        "item_contract_grid_name": _clean_text(raw_row.get("item_contract_grid_name")).lower(),
        "additional_properties_allowed": _clean_bool(raw_row.get("additional_properties_allowed")),
        "gpt_owned": _clean_bool(raw_row.get("gpt_owned"), default=True),
        "python_owned": _clean_bool(raw_row.get("python_owned")),
        "editable": _clean_bool(raw_row.get("editable"), default=True),
        "must_match_lookup": _clean_bool(raw_row.get("must_match_lookup")),
        "contract_phase": _clean_text(raw_row.get("contract_phase")).lower(),
        "horizon_rule": _clean_text(raw_row.get("horizon_rule")).lower(),
        "normalization_kind": _clean_text(raw_row.get("normalization_kind")).lower() or "none",
        "rounding_kind": _clean_text(raw_row.get("rounding_kind")).lower() or "none",
        "decimal_places": int(raw_row.get("decimal_places")) if raw_row.get("decimal_places") is not None else None,
        "validation_kind": _clean_text(raw_row.get("validation_kind")).lower() or "schema_only",
        "lookup_source": _clean_text(raw_row.get("lookup_source")).lower() or "none",
        "enum_values": _json_list(raw_row.get("enum_values")),
        "allowed_aliases": _json_list(raw_row.get("allowed_aliases")),
        "prompt_required_instruction": _clean_text(raw_row.get("prompt_required_instruction")),
        "prompt_label": _clean_text(raw_row.get("prompt_label")),
        "failure_code": _clean_text(raw_row.get("failure_code")),
        "contract_status": _clean_text(raw_row.get("contract_status")).lower() or "active",
        "notes": _clean_text(raw_row.get("notes")),
      }
    )
  if not rows:
    raise RuntimeError(f"{_GPT_CONTRACT_TABLE_NAME}_empty: GPT contract lookup table has no rows")
  return rows


@lru_cache(maxsize=1)
def load_post_intake_gpt_context_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_gpt_context_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          contract_name,
          context_key,
          context_group,
          source_kind,
          source_path,
          transform_kind,
          include_phase,
          required,
          include_in_prompt,
          max_items,
          max_chars,
          failure_code,
          context_status,
          notes
        FROM {_GPT_CONTEXT_TABLE_NAME}
        ORDER BY contract_name ASC, include_phase ASC, id ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    contract_name = _clean_text(raw_row.get("contract_name")).lower()
    context_key = _clean_text(raw_row.get("context_key"))
    if not contract_name or not context_key:
      continue
    rows.append(
      {
        "contract_name": contract_name,
        "context_key": context_key,
        "context_group": _clean_text(raw_row.get("context_group")).lower(),
        "source_kind": _clean_text(raw_row.get("source_kind")).lower() or "runtime",
        "source_path": _clean_text(raw_row.get("source_path")),
        "transform_kind": _clean_text(raw_row.get("transform_kind")).lower() or "copy",
        "include_phase": _clean_text(raw_row.get("include_phase")).lower(),
        "required": bool(int(raw_row.get("required"))) if raw_row.get("required") is not None else True,
        "include_in_prompt": bool(int(raw_row.get("include_in_prompt"))) if raw_row.get("include_in_prompt") is not None else True,
        "max_items": int(raw_row.get("max_items")) if raw_row.get("max_items") is not None else None,
        "max_chars": int(raw_row.get("max_chars")) if raw_row.get("max_chars") is not None else None,
        "failure_code": _clean_text(raw_row.get("failure_code")),
        "context_status": _clean_text(raw_row.get("context_status")).lower() or "active",
        "notes": _clean_text(raw_row.get("notes")),
      }
    )
  if not rows:
    raise RuntimeError(f"{_GPT_CONTEXT_TABLE_NAME}_empty: GPT context lookup table has no rows")
  return rows


@lru_cache(maxsize=1)
def load_post_intake_process_sequence_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_mapping_lookup_table(conn)
    _ensure_cash_policy_lookup_table(conn)
    _ensure_gpt_contract_lookup_table(conn)
    _ensure_gpt_context_lookup_table(conn)
    _ensure_process_sequence_lookup_table(conn)
    _ensure_process_context_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          phase,
          step_order,
          step_key,
          handler_key,
          parent_step_key,
          step_kind,
          hierarchy_level,
          sequence_path,
          executor_function,
          contract_name,
          context_contract_name,
          context_include_phase,
          required_context_keys_json,
          produced_output_keys_json,
          output_storage_json,
          recompute_triggers_json,
          output_finality,
          required_lookup_tables_json,
          horizon_rule,
          timeout_seconds,
          max_attempts,
          required,
          enabled,
          fail_fast_code,
          python_role,
          python_timing,
          python_action,
          input_object_path,
          output_object_path,
          validation_subject_path,
          object_controls_json,
          sequence_status,
          notes
        FROM {_PROCESS_SEQUENCE_TABLE_NAME}
        ORDER BY phase ASC, step_order ASC, id ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    step_key = _clean_text(raw_row.get("step_key")).lower()
    if not step_key:
      continue
    required_lookup_tables = _json_value(raw_row.get("required_lookup_tables_json"), [])
    required_context_keys = _json_value(raw_row.get("required_context_keys_json"), [])
    produced_output_keys = _json_value(raw_row.get("produced_output_keys_json"), [])
    rows.append(
      {
        "phase": _clean_text(raw_row.get("phase")).lower(),
        "step_order": int(raw_row.get("step_order") or 0),
        "step_key": step_key,
        "handler_key": _clean_text(raw_row.get("handler_key")),
        "parent_step_key": _clean_text(raw_row.get("parent_step_key")).lower(),
        "step_kind": _clean_text(raw_row.get("step_kind")).lower() or "process",
        "hierarchy_level": int(raw_row.get("hierarchy_level") or 1),
        "sequence_path": _clean_text(raw_row.get("sequence_path")).lower() or _process_sequence_path(
          phase=_clean_text(raw_row.get("phase")).lower(),
          step_key=step_key,
          parent_step_key=_clean_text(raw_row.get("parent_step_key")).lower(),
        ),
        "executor_function": _clean_text(raw_row.get("executor_function")) or _clean_text(raw_row.get("handler_key")),
        "contract_name": _clean_text(raw_row.get("contract_name")).lower(),
        "context_contract_name": _clean_text(raw_row.get("context_contract_name")).lower(),
        "context_include_phase": _clean_text(raw_row.get("context_include_phase")).lower(),
        "required_context_keys": [
          _clean_text(item)
          for item in (required_context_keys if isinstance(required_context_keys, list) else [])
          if _clean_text(item)
        ],
        "produced_output_keys": [
          _clean_text(item)
          for item in (produced_output_keys if isinstance(produced_output_keys, list) else [])
          if _clean_text(item)
        ],
        "output_storage": _json_value(raw_row.get("output_storage_json"), []),
        "recompute_triggers": _json_value(raw_row.get("recompute_triggers_json"), []),
        "output_finality": _clean_text(raw_row.get("output_finality")).lower() or "stage_final_no_downstream_mutation",
        "required_lookup_tables": [
          _clean_text(item)
          for item in (required_lookup_tables if isinstance(required_lookup_tables, list) else [])
          if _clean_text(item)
        ],
        "horizon_rule": _clean_text(raw_row.get("horizon_rule")).lower(),
        "timeout_seconds": float(raw_row.get("timeout_seconds")) if raw_row.get("timeout_seconds") is not None else None,
        "max_attempts": int(raw_row.get("max_attempts")) if raw_row.get("max_attempts") is not None else None,
        "required": _clean_bool(raw_row.get("required"), default=True),
        "enabled": _clean_bool(raw_row.get("enabled"), default=True),
        "fail_fast_code": _clean_text(raw_row.get("fail_fast_code")) or f"{step_key}_sequence_violation",
        "python_role": _clean_text(raw_row.get("python_role")) or "deterministic_step_executor",
        "python_timing": _clean_text(raw_row.get("python_timing")),
        "python_action": _clean_text(raw_row.get("python_action")),
        "input_object_path": _clean_text(raw_row.get("input_object_path")),
        "output_object_path": _clean_text(raw_row.get("output_object_path")),
        "validation_subject_path": _clean_text(raw_row.get("validation_subject_path")),
        "object_controls": _json_value(raw_row.get("object_controls_json"), []),
        "sequence_status": _clean_text(raw_row.get("sequence_status")).lower() or "active",
        "notes": _clean_text(raw_row.get("notes")),
        "source_of_truth": f"sql.{_PROCESS_SEQUENCE_TABLE_NAME}",
      }
    )
  if not rows:
    raise RuntimeError(f"{_PROCESS_SEQUENCE_TABLE_NAME}_empty: post-intake process sequence lookup table has no rows")
  return rows


def _phase_matches(row: Dict[str, Any], phase: Any = None) -> bool:
  requested = _clean_text(phase).lower()
  if not requested:
    return True
  row_phase = _clean_text(row.get("post_intake_phase")).lower()
  return row_phase in {requested, "both"}


@lru_cache(maxsize=1)
def load_post_intake_process_context_rows() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  _ensure_env_loaded()
  conn = get_mysql_connection()
  try:
    _ensure_process_sequence_lookup_table(conn)
    _ensure_process_context_lookup_table(conn)
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          step_key,
          context_key,
          context_domain,
          source_kind,
          source_path,
          transform_kind,
          required,
          immutable_input,
          context_status,
          notes
        FROM {_PROCESS_CONTEXT_TABLE_NAME}
        ORDER BY step_key ASC, id ASC
        """
      )
      raw_rows = cur.fetchall() or []
    finally:
      try:
        cur.close()
      except Exception:
        pass
  finally:
    try:
      conn.close()
    except Exception:
      pass
  for raw_row in raw_rows:
    if not isinstance(raw_row, dict):
      continue
    step_key = _clean_text(raw_row.get("step_key")).lower()
    context_key = _clean_text(raw_row.get("context_key"))
    if not step_key or not context_key:
      continue
    rows.append(
      {
        "step_key": step_key,
        "context_key": context_key,
        "context_domain": _clean_text(raw_row.get("context_domain")).lower(),
        "source_kind": _clean_text(raw_row.get("source_kind")).lower() or "runtime_context",
        "source_path": _clean_text(raw_row.get("source_path")) or context_key,
        "transform_kind": _clean_text(raw_row.get("transform_kind")).lower() or "copy",
        "required": _clean_bool(raw_row.get("required"), default=True),
        "immutable_input": _clean_bool(raw_row.get("immutable_input"), default=True),
        "context_status": _clean_text(raw_row.get("context_status")).lower() or "active",
        "notes": _clean_text(raw_row.get("notes")),
        "source_of_truth": f"sql.{_PROCESS_CONTEXT_TABLE_NAME}",
      }
    )
  if not rows:
    raise RuntimeError(f"{_PROCESS_CONTEXT_TABLE_NAME}_empty: post-intake process context lookup table has no rows")
  return rows


class PostIntakeMappingLookup:
  """Single gateway for the SQL-backed post-intake mapping table."""

  def __init__(self, rows: Iterable[Dict[str, Any]]) -> None:
    self._rows = [dict(row) for row in rows if isinstance(row, dict)]
    self._active_rows = [
      dict(row)
      for row in self._rows
      if _clean_text(row.get("mapping_status")).lower() == "active"
    ]
    self._by_lookup_lever: Dict[str, Dict[str, Any]] = {}
    for row in self._active_rows:
      lookup_key = _clean_text(row.get("lookup_lever_id"))
      if lookup_key and lookup_key not in self._by_lookup_lever:
        self._by_lookup_lever[lookup_key] = dict(row)

  def rows(self, *, active_only: bool = True, phase: Any = None) -> List[Dict[str, Any]]:
    source_rows = self._active_rows if active_only else self._rows
    return [
      dict(row)
      for row in source_rows
      if _phase_matches(row, phase)
    ]

  def entry_for_lever(self, lever_id: Any, *, required: bool = False) -> Optional[Dict[str, Any]]:
    lookup_key = _normalized_lookup_key(lever_id)
    entry = self._by_lookup_lever.get(lookup_key)
    if isinstance(entry, dict):
      return dict(entry)
    if required:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_lever: "
        f"{_clean_text(lever_id) or 'missing'}"
      )
    return None

  def formula_contract_for_lever(self, lever_id: Any, *, required: bool = True) -> Optional[Dict[str, Any]]:
    entry = self.entry_for_lever(lever_id, required=required)
    if not isinstance(entry, dict):
      return None
    return formula_contract_for_mapping_row(entry)

  def formula_contract_rows(self, *, phase: Any = None) -> List[Dict[str, Any]]:
    return [
      formula_contract_for_mapping_row(row)
      for row in self.rows(active_only=True, phase=phase)
      if _clean_text(row.get("formula_status")).lower() == "active"
    ]

  def lever_allowed_for_issue(
    self,
    lever_id: Any,
    issue_code: Any,
    *,
    phase: Any = None,
  ) -> bool:
    issue = _clean_text(issue_code).lower()
    if not issue:
      return False
    entry = self.entry_for_lever(lever_id)
    if not isinstance(entry, dict):
      return False
    if issue not in set(entry.get("post_intake_issue_codes") or []):
      return False
    if bool(entry.get("diagnostic_only")):
      return False
    return _phase_matches(entry, phase)

  def target_metric_for_lever(self, lever_id: Any, *, required: bool = False) -> str:
    entry = self.entry_for_lever(lever_id, required=required)
    metric_name = _clean_text((entry or {}).get("target_metric_name")).lower()
    if required and not metric_name:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_target_metric: "
        f"{_clean_text(lever_id) or 'missing'}"
      )
    return metric_name

  def target_metrics_for_levers(self, lever_ids: Optional[Iterable[Any]]) -> List[str]:
    ordered: List[str] = []
    for lever_id in (lever_ids or []):
      metric_name = self.target_metric_for_lever(lever_id)
      if metric_name and metric_name not in ordered:
        ordered.append(metric_name)
    return ordered

  def target_metric_ids(
    self,
    *,
    phase: Any = "convergence",
    targeting_allowed_only: bool = True,
  ) -> List[str]:
    ordered: List[str] = []
    for row in self.rows(active_only=True, phase=phase):
      if targeting_allowed_only and not bool(row.get("targeting_allowed")):
        continue
      if bool(row.get("diagnostic_only")):
        continue
      metric_name = _clean_text(row.get("target_metric_name")).lower()
      if metric_name and metric_name not in ordered:
        ordered.append(metric_name)
    return ordered

  def rows_for_issue(self, issue_code: Any, *, phase: Any = None) -> List[Dict[str, Any]]:
    normalized_issue = _clean_text(issue_code).lower()
    if not normalized_issue:
      return []
    return [
      dict(row)
      for row in self.rows(active_only=True, phase=phase)
      if normalized_issue in set(row.get("post_intake_issue_codes") or [])
      and not bool(row.get("diagnostic_only"))
    ]

  def lever_ids_for_issue(self, issue_code: Any, *, phase: Any = None) -> List[str]:
    ordered: List[str] = []
    for row in self.rows_for_issue(issue_code, phase=phase):
      lever_id = _clean_text(row.get("lever_id"))
      if lever_id and lever_id not in ordered:
        ordered.append(lever_id)
    return ordered

  def target_metrics_for_issue(self, issue_code: Any, *, phase: Any = None) -> List[str]:
    return self.target_metrics_for_levers(
      self.lever_ids_for_issue(issue_code, phase=phase)
    )

  def issue_codes_for_phase(self, phase: Any, *, targeting_allowed: Optional[bool] = None) -> List[str]:
    normalized_phase = _clean_text(phase).lower()
    out: List[str] = []
    for row in self.rows(active_only=True):
      if normalized_phase and _clean_text(row.get("post_intake_phase")).lower() != normalized_phase:
        continue
      if targeting_allowed is not None and bool(row.get("targeting_allowed")) != bool(targeting_allowed):
        continue
      if bool(row.get("diagnostic_only")):
        continue
      for issue_code in row.get("post_intake_issue_codes") or []:
        normalized_issue = _clean_text(issue_code).lower()
        if normalized_issue and normalized_issue not in out:
          out.append(normalized_issue)
    return out

  def issue_codes(self, *, targeting_allowed: Optional[bool] = None) -> List[str]:
    out: List[str] = []
    for row in self.rows(active_only=True):
      if targeting_allowed is not None and bool(row.get("targeting_allowed")) != bool(targeting_allowed):
        continue
      if bool(row.get("diagnostic_only")):
        continue
      for issue_code in row.get("post_intake_issue_codes") or []:
        normalized_issue = _clean_text(issue_code).lower()
        if normalized_issue and normalized_issue not in out:
          out.append(normalized_issue)
    return out

  def issue_has_phase(self, issue_code: Any, phase: Any) -> bool:
    normalized_issue = _clean_text(issue_code).lower()
    normalized_phase = _clean_text(phase).lower()
    if not normalized_issue or not normalized_phase:
      return False
    return any(
      normalized_issue in set(row.get("post_intake_issue_codes") or [])
      and _clean_text(row.get("post_intake_phase")).lower() == normalized_phase
      and not bool(row.get("diagnostic_only"))
      for row in self.rows(active_only=True)
    )

  def issue_tolerance_allowed(self, issue_code: Any, *, phase: Any = None) -> bool:
    issue = _clean_text(issue_code).lower()
    rows = self.rows_for_issue(issue_code, phase=phase)
    if not rows:
      return False
    if any(issue in set(row.get("non_tolerable_issue_codes") or []) for row in rows):
      return False
    return all(bool(row.get("tolerance_allowed")) for row in rows)

  def target_value_kind_for_metric(self, target_metric_name: Any, *, phase: Any = None) -> str:
    metric = _clean_text(target_metric_name).lower()
    if not metric:
      return ""
    kinds: List[str] = []
    for row in self.rows(active_only=True, phase=phase):
      if bool(row.get("diagnostic_only")):
        continue
      if _clean_text(row.get("target_metric_name")).lower() != metric:
        continue
      kind = _clean_text(row.get("target_value_kind")).lower()
      if kind and kind not in kinds:
        kinds.append(kind)
    if len(kinds) > 1:
      raise RuntimeError(
        "post_intake_mapping_target_value_kind_ambiguous: "
        f"{metric} has multiple target_value_kind values in {_MAPPING_TABLE_NAME}: {kinds}"
      )
    return kinds[0] if kinds else ""

  def target_precision_for_metric(self, target_metric_name: Any, *, phase: Any = None) -> Dict[str, Any]:
    metric = _clean_text(target_metric_name).lower()
    if not metric:
      return _normalize_precision_metadata(value_kind="number")
    precisions: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, Optional[int]]] = set()
    for row in self.rows(active_only=True, phase=phase):
      if bool(row.get("diagnostic_only")):
        continue
      if _clean_text(row.get("target_metric_name")).lower() != metric:
        continue
      precision = dict(row.get("target_precision") or {})
      if not precision:
        precision = _normalize_precision_metadata(value_kind=row.get("target_value_kind"))
      key = (
        _clean_text(precision.get("rounding_kind")).lower(),
        precision.get("decimal_places"),
      )
      if key not in seen_keys:
        seen_keys.add(key)
        precisions.append(precision)
    if len(precisions) > 1:
      raise RuntimeError(
        "post_intake_mapping_target_precision_ambiguous: "
        f"{metric} has multiple target precision values in {_MAPPING_TABLE_NAME}: {precisions}"
      )
    if precisions:
      out = dict(precisions[0])
      out["target_metric_name"] = metric
      return out
    out = _normalize_precision_metadata(value_kind="number")
    out["target_metric_name"] = metric
    return out

  def value_precision_for_lever(self, lever_id: Any) -> Dict[str, Any]:
    row = self.entry_for_lever(lever_id)
    if not isinstance(row, dict) or not row:
      raise RuntimeError(
        "post_intake_mapping_value_precision_missing: "
        f"lever_id={_clean_text(lever_id) or 'missing'} is not present in {_MAPPING_TABLE_NAME}"
      )
    precision = dict(row.get("value_precision") or {})
    if not precision:
      precision = _normalize_precision_metadata(value_kind=row.get("value_kind"))
    precision["lever_id"] = _clean_text(row.get("lever_id"))
    return precision

  def normalize_target_value(
    self,
    target_metric_name: Any,
    value: Any,
    *,
    phase: Any = None,
    bound_side: str = "",
  ) -> Any:
    precision = self.target_precision_for_metric(target_metric_name, phase=phase)
    return _round_by_precision_metadata(value, precision=precision, bound_side=bound_side)

  def normalize_lever_value(
    self,
    lever_id: Any,
    value: Any,
    *,
    bound_side: str = "",
  ) -> Any:
    precision = self.value_precision_for_lever(lever_id)
    return _round_by_precision_metadata(value, precision=precision, bound_side=bound_side)

  def issue_candidate_lever_ids(
    self,
    issue_code: Any,
    *,
    phase: Any = None,
  ) -> List[str]:
    issue = _clean_text(issue_code).lower()
    if not issue:
      return []
    return self.lever_ids_for_issue(issue, phase=phase)

  def concrete_issue_lever_ids_from_catalog(
    self,
    issue_code: Any,
    catalog_lever_ids: Iterable[Any],
    *,
    phase: Any = None,
  ) -> List[str]:
    issue = _clean_text(issue_code).lower()
    if not issue:
      return []
    allowed_lookup_keys = {
      _normalized_lookup_key(row.get("lever_id"))
      for row in self.rows_for_issue(issue, phase=phase)
      if _clean_text(row.get("lever_id"))
    }
    if not allowed_lookup_keys:
      return []
    ordered: List[str] = []
    for raw_lever_id in (catalog_lever_ids or []):
      lever_id = _clean_text(raw_lever_id)
      if not lever_id:
        continue
      lookup_key = _normalized_lookup_key(lever_id)
      if lookup_key not in allowed_lookup_keys:
        continue
      if not self.lever_allowed_for_issue(lever_id, issue, phase=phase):
        continue
      if lever_id not in ordered:
        ordered.append(lever_id)
    return ordered

  def issue_mapping_contract(
    self,
    issue_code: Any,
    *,
    phase: Any = None,
    allowed_target_metric_names: Optional[Iterable[Any]] = None,
    require: bool = True,
  ) -> Dict[str, Any]:
    issue = _clean_text(issue_code).lower()
    allowed_metrics = {
      _clean_text(item).lower()
      for item in (allowed_target_metric_names or [])
      if _clean_text(item)
    }
    candidate_levers = self.issue_candidate_lever_ids(
      issue,
      phase=phase,
    )
    target_metrics = [
      metric
      for metric in self.target_metrics_for_levers(candidate_levers)
      if metric and (not allowed_metrics or metric in allowed_metrics)
    ]
    if require and not candidate_levers:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_levers: "
        f"{issue or 'missing'} has no table-backed candidate levers."
      )
    if require and not target_metrics:
      raise RuntimeError(
        "post_intake_driver_target_mapping_missing_issue_targets: "
        f"{issue or 'missing'} has no table-backed target metrics from mapped candidate levers."
      )
    return {
      "issue_code": issue,
      "mapping_source": _MAPPING_TABLE_NAME,
      "candidate_lever_ids": copy.deepcopy(candidate_levers),
      "next_required_lever_ids": copy.deepcopy(candidate_levers),
      "target_metric_names": copy.deepcopy(target_metrics),
      "metric_targets": copy.deepcopy(target_metrics),
      "mapping_rows": self.compact_lookup_for_levers(candidate_levers),
    }

  def lever_ids_for_target_drivers(
    self,
    target_drivers: Iterable[Any],
    *,
    phase: Any = None,
  ) -> List[str]:
    targets: Set[str] = {
      _clean_text(item).lower()
      for item in (target_drivers or [])
      if _clean_text(item)
    }
    ordered: List[str] = []
    for row in self.rows(active_only=True, phase=phase):
      target_driver = _clean_text(row.get("target_driver")).lower()
      lever_id = _clean_text(row.get("lever_id"))
      if target_driver in targets and lever_id and lever_id not in ordered:
        ordered.append(lever_id)
    return ordered

  def single_lever_id_for_target_driver(self, target_driver: Any, *, phase: Any = None) -> str:
    target = _clean_text(target_driver).lower()
    lever_ids = self.lever_ids_for_target_drivers({target}, phase=phase)
    if len(lever_ids) != 1:
      raise RuntimeError(
        "post_intake_driver_target_mapping_single_lever_required: "
        f"target_driver={target or 'missing'} matched {len(lever_ids)} rows."
      )
    return lever_ids[0]

  def lever_ids_for_cash_roles(self, cash_strategy_roles: Iterable[Any]) -> List[str]:
    roles: Set[str] = {
      _clean_text(item).lower()
      for item in (cash_strategy_roles or [])
      if _clean_text(item)
    }
    ordered: List[str] = []
    for row in self.rows(active_only=True, phase="cash_pass"):
      role = _clean_text(row.get("cash_strategy_role")).lower()
      lever_id = _clean_text(row.get("lever_id"))
      if role in roles and lever_id and lever_id not in ordered:
        ordered.append(lever_id)
    return ordered

  def compact_lookup_for_levers(self, lever_ids: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
    requested = [
      _clean_text(item)
      for item in (lever_ids or [])
      if _clean_text(item)
    ]
    source_rows: List[Dict[str, Any]]
    if requested:
      source_rows = []
      seen_lookup_keys: Set[str] = set()
      for lever_id in requested:
        entry = self.entry_for_lever(lever_id)
        if not isinstance(entry, dict):
          continue
        lookup_key = _clean_text(entry.get("lookup_lever_id"))
        if lookup_key and lookup_key in seen_lookup_keys:
          continue
        if lookup_key:
          seen_lookup_keys.add(lookup_key)
        source_rows.append(entry)
    else:
      source_rows = self.rows(active_only=True)
    compact: List[Dict[str, Any]] = []
    for row in source_rows:
      lever_id = _clean_text(row.get("lever_id"))
      if not lever_id:
        continue
      compact.append(
        {
          "lever_id": lever_id,
          "driver_category": _clean_text(row.get("driver_category")).lower(),
          "target_driver": _clean_text(row.get("target_driver")),
          "target_metric_name": _clean_text(row.get("target_metric_name")).lower(),
          "model_input_field": _clean_text(row.get("model_input_field")),
          "financial_model_field": _clean_text(row.get("financial_model_field")),
          "impact_type": _clean_text(row.get("impact_type")).lower(),
          "post_intake_issue_codes": copy.deepcopy(row.get("post_intake_issue_codes") or []),
          "post_intake_phase": _clean_text(row.get("post_intake_phase")).lower(),
          "control_owner": _clean_text(row.get("control_owner")).lower(),
          "value_kind": _clean_text(row.get("value_kind")).lower(),
          "target_value_kind": _clean_text(row.get("target_value_kind")).lower(),
          "value_precision": copy.deepcopy(row.get("value_precision") or {}),
          "target_precision": copy.deepcopy(row.get("target_precision") or {}),
          "input_semantics": _clean_text(row.get("input_semantics")).lower(),
          "driver_bundle": _clean_text(row.get("driver_bundle")).lower(),
          "cash_strategy_role": _clean_text(row.get("cash_strategy_role")).lower(),
          "targeting_allowed": bool(row.get("targeting_allowed")),
          "diagnostic_only": bool(row.get("diagnostic_only")),
          "repair_direction_rules": copy.deepcopy(row.get("repair_direction_rules") or {}),
          "seed_source_paths": copy.deepcopy(row.get("seed_source_paths_json") or []),
          "seed_formula_key": _clean_text(row.get("seed_formula_key")).lower(),
          "finmo_formula_key": _clean_text(row.get("finmo_formula_key")).lower(),
          "validation_formula_key": _clean_text(row.get("validation_formula_key")).lower(),
          "required_when_key": _clean_text(row.get("required_when_key")).lower(),
          "business_applicability_key": _clean_text(row.get("business_applicability_key")).lower(),
          "applicability_positive_tokens": copy.deepcopy(row.get("applicability_positive_tokens") or []),
          "applicability_negative_tokens": copy.deepcopy(row.get("applicability_negative_tokens") or []),
          "forecast_presence_rule_key": _clean_text(row.get("forecast_presence_rule_key")).lower(),
          "zero_allowed_reason_key": _clean_text(row.get("zero_allowed_reason_key")).lower(),
          "missing_seed_default_value": row.get("missing_seed_default_value"),
          "minimum_live_value": row.get("minimum_live_value"),
          "maximum_live_value": row.get("maximum_live_value"),
          "allow_zero": bool(row.get("allow_zero")),
        }
      )
    return compact

  def validation_errors(self, expected_lever_ids: Optional[Iterable[Any]] = None) -> List[str]:
    errors: List[str] = []
    seen_lookup_keys: set[str] = set()
    valid_phases = {"convergence", "cash_pass", "both", "derived_only"}
    valid_control_owners = {"gpt_editable", "python_derived", "cash_pass", "locked"}
    valid_statuses = {"active", "retired", "review"}
    for row in self._rows:
      status = _clean_text(row.get("mapping_status")).lower()
      if status not in valid_statuses:
        errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported mapping_status {status}")
      if status != "active":
        continue
      lookup_key = _clean_text(row.get("lookup_lever_id"))
      if not lookup_key:
        errors.append("mapping row is missing lookup_lever_id")
        continue
      if lookup_key in seen_lookup_keys:
        errors.append(f"duplicate mapping row for {lookup_key}")
      seen_lookup_keys.add(lookup_key)
      metric_name = _clean_text(row.get("target_metric_name")).lower()
      if not metric_name:
        errors.append(
          f"{_clean_text(row.get('lever_id'))} has unsupported financial_model_field "
          f"{_clean_text(row.get('financial_model_field'))}"
        )
      if not _clean_text(row.get("model_input_field")):
        errors.append(f"{_clean_text(row.get('lever_id'))} is missing model_input_field")
      impact_type = _clean_text(row.get("impact_type")).lower()
      if impact_type not in {"direct", "derived"}:
        errors.append(
          f"{_clean_text(row.get('lever_id'))} has unsupported impact_type "
          f"{_clean_text(row.get('impact_type'))}"
        )
      phase = _clean_text(row.get("post_intake_phase")).lower()
      if phase not in valid_phases:
        errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported post_intake_phase {phase}")
      owner = _clean_text(row.get("control_owner")).lower()
      if owner not in valid_control_owners:
        errors.append(f"{_clean_text(row.get('lever_id'))} has unsupported control_owner {owner}")
      if not _clean_text(row.get("value_kind")):
        errors.append(f"{_clean_text(row.get('lever_id'))} is missing value_kind")
      if not _clean_text(row.get("target_value_kind")):
        errors.append(f"{_clean_text(row.get('lever_id'))} is missing target_value_kind")
      value_precision = row.get("value_precision") if isinstance(row.get("value_precision"), dict) else {}
      target_precision = row.get("target_precision") if isinstance(row.get("target_precision"), dict) else {}
      for precision_label, precision in (("value_precision", value_precision), ("target_precision", target_precision)):
        rounding_kind = _clean_text(precision.get("rounding_kind")).lower()
        decimal_places = precision.get("decimal_places")
        if rounding_kind not in {"nearest_integer", "nearest_decimal", "nearest_dollar", "none"}:
          errors.append(
            f"{_clean_text(row.get('lever_id'))} has unsupported {precision_label}.rounding_kind {rounding_kind}"
          )
        if rounding_kind in {"nearest_integer", "nearest_dollar"} and decimal_places != 0:
          errors.append(f"{_clean_text(row.get('lever_id'))} {precision_label} integer rounding must have decimal_places=0")
        if rounding_kind == "nearest_decimal":
          if decimal_places is None or int(decimal_places) < 0:
            errors.append(f"{_clean_text(row.get('lever_id'))} {precision_label} decimal rounding needs decimal_places >= 0")
      if not _clean_text(row.get("input_semantics")):
        errors.append(f"{_clean_text(row.get('lever_id'))} is missing input_semantics")
      errors.extend(formula_metadata_errors(row))
      lever_id = _clean_text(row.get("lever_id"))
      applicability_key = _clean_text(row.get("business_applicability_key")).lower()
      positive_tokens = [
        _clean_text(item)
        for item in (row.get("applicability_positive_tokens") or [])
        if _clean_text(item)
      ]
      if applicability_key in {"inventory_business_or_seed", "deferred_revenue_business"} and not positive_tokens:
        errors.append(f"{lever_id} requires table-backed applicability_positive_tokens")
      if (
        lever_id.startswith("balance_sheet::")
        and _clean_text(row.get("forecast_presence_rule_key")).lower() == "positive_driver_when_applicable"
        and row.get("missing_seed_default_value") is not None
      ):
        errors.append(f"{lever_id} must not define missing_seed_default_value; contextual seed must be GPT/table-backed")
      if phase == "cash_pass" and owner not in {"cash_pass", "locked"}:
        errors.append(f"{_clean_text(row.get('lever_id'))} cash_pass row must be owned by cash_pass or locked")
      if phase == "derived_only" and owner != "python_derived":
        errors.append(f"{_clean_text(row.get('lever_id'))} derived_only row must be owned by python_derived")
    expected_lookup_keys = {
      _normalized_lookup_key(item)
      for item in (expected_lever_ids or [])
      if _clean_text(item)
    }
    missing_lookup_keys = sorted(key for key in expected_lookup_keys if key and key not in seen_lookup_keys)
    for lookup_key in missing_lookup_keys:
      errors.append(f"missing driver-target mapping for writable lever {lookup_key}")
    return errors


class PostIntakeCashPolicyLookup:
  """Single gateway for the SQL-backed cash strategy policy table."""

  def __init__(self, rows: Iterable[Dict[str, Any]]) -> None:
    self._rows = [
      dict(row)
      for row in rows
      if isinstance(row, dict)
      and _clean_text(row.get("policy_status")).lower() == "active"
    ]

  def _normalized_phase_sequence(self, value: Any) -> List[Dict[str, Any]]:
    raw_sequence = value if isinstance(value, list) else []
    normalized: List[Dict[str, Any]] = []
    for item in raw_sequence:
      if not isinstance(item, dict):
        continue
      phase_code = _clean_text(item.get("phase_code")).lower()
      if not phase_code:
        continue
      normalized.append(
        {
          "phase_code": phase_code,
          "phase_order": int(float(item.get("phase_order") or 0)),
          "phase_owner": _clean_text(item.get("phase_owner")).lower() or "python",
          "required": _clean_bool(item.get("required"), default=True),
          "requires_finmo_rebuild_after": _clean_bool(item.get("requires_finmo_rebuild_after")),
          "validation_gate": _clean_text(item.get("validation_gate")).lower(),
          "notes": _clean_text(item.get("notes")),
        }
      )
    normalized.sort(key=lambda row: int(row.get("phase_order") or 0))
    return normalized

  def rows(self, *, cash_strategy: Any = None) -> List[Dict[str, Any]]:
    strategy = _clean_text(cash_strategy).lower()
    return [
      dict(row)
      for row in self._rows
      if not strategy or _clean_text(row.get("cash_strategy")).lower() == strategy
    ]

  def debt_position_for_ratio(self, debt_to_equity: Any) -> str:
    ratio = float(debt_to_equity or 0.0)
    if ratio < 0.50:
      return "low_debt"
    if ratio <= 1.00:
      return "healthy_debt"
    return "high_debt"

  def policy_for(
    self,
    *,
    cash_strategy: Any,
    debt_to_equity: Any,
    debt_position: Any = None,
    required: bool = True,
  ) -> Optional[Dict[str, Any]]:
    strategy = _clean_text(cash_strategy).lower() or "balanced"
    ratio = float(debt_to_equity or 0.0)
    position = _clean_text(debt_position).lower() or self.debt_position_for_ratio(ratio)
    for row in self.rows(cash_strategy=strategy):
      row_position = _clean_text(row.get("debt_position")).lower()
      row_min = float(row.get("debt_to_equity_min") or 0.0)
      row_max = float(row.get("debt_to_equity_max") or 0.0)
      if row_position == position and row_min <= ratio <= row_max:
        return dict(row)
    for row in self.rows(cash_strategy=strategy):
      if _clean_text(row.get("debt_position")).lower() == position:
        return dict(row)
    if required:
      raise RuntimeError(
        "post_intake_cash_policy_missing: "
        f"cash_strategy={strategy or 'missing'} debt_position={position or 'missing'} debt_to_equity={ratio}"
      )
    return None

  def phase_sequence(self, *, cash_strategy: Any = None, required: bool = True) -> List[Dict[str, Any]]:
    strategy = _clean_text(cash_strategy).lower()
    candidate_rows = self.rows(cash_strategy=strategy) if strategy else self.rows()
    for row in candidate_rows:
      sequence = self._normalized_phase_sequence(row.get("cash_phase_sequence"))
      if sequence:
        return sequence
    if required:
      raise RuntimeError(
        "post_intake_cash_policy_phase_sequence_missing: "
        f"cash_strategy={strategy or '*'}"
      )
    return []

  def debt_schedule_policy(
    self,
    *,
    cash_strategy: Any,
    debt_to_equity: Any = None,
    debt_position: Any = None,
    required: bool = True,
  ) -> Optional[Dict[str, Any]]:
    row = self.policy_for(
      cash_strategy=cash_strategy,
      debt_to_equity=debt_to_equity or 0.0,
      debt_position=debt_position,
      required=required,
    )
    if not row:
      return None
    return {
      "source_of_truth": "sql.post_intake_cash_policy_lookup",
      "lookup_function": "post_intake_cash_debt_schedule_policy",
      "cash_strategy": _clean_text(row.get("cash_strategy")).lower(),
      "debt_position": _clean_text(row.get("debt_position")).lower(),
      "debt_schedule_method": _clean_text(row.get("debt_schedule_method")).lower(),
      "debt_schedule_required": _clean_bool(row.get("debt_schedule_required"), default=True),
      "debt_schedule_horizon_quarters": int(float(row.get("debt_schedule_horizon_quarters") or 0)),
      "debt_minimum_payment_frequency": _clean_text(row.get("debt_minimum_payment_frequency")).lower(),
      "debt_min_principal_source_priority": [
        _clean_text(item)
        for item in (row.get("debt_min_principal_source_priority") or [])
        if _clean_text(item)
      ],
      "debt_extra_paydown_policy": _clean_text(row.get("debt_extra_paydown_policy")).lower(),
      "debt_interest_rate_source_required": _clean_text(row.get("debt_interest_rate_source_required")),
      "debt_interest_rate_fallback_allowed": _clean_bool(row.get("debt_interest_rate_fallback_allowed")),
    }

  def validation_errors(self) -> List[str]:
    errors: List[str] = []
    valid_strategies = {"shareholder_return", "balanced", "preserve_cash"}
    valid_positions = {"low_debt", "healthy_debt", "high_debt"}
    required_phase_codes = [
      _clean_text(item.get("phase_code")).lower()
      for item in _DEFAULT_CASH_PASS_PHASE_SEQUENCE
      if _clean_text(item.get("phase_code"))
    ]
    canonical_phase_codes: Optional[List[str]] = None
    seen: Set[tuple[str, str]] = set()
    for row in self._rows:
      strategy = _clean_text(row.get("cash_strategy")).lower()
      position = _clean_text(row.get("debt_position")).lower()
      if strategy not in valid_strategies:
        errors.append(f"unsupported cash_strategy {strategy or 'missing'}")
      if position not in valid_positions:
        errors.append(f"unsupported debt_position {position or 'missing'}")
      key = (strategy, position)
      if key in seen:
        errors.append(f"duplicate cash policy row for {strategy}/{position}")
      seen.add(key)
      floor = float(row.get("cash_floor_months") or 0.0)
      ceiling = float(row.get("cash_ceiling_months") or 0.0)
      if floor <= 0:
        errors.append(f"{strategy}/{position} cash_floor_months must be positive")
      if ceiling < floor:
        errors.append(f"{strategy}/{position} cash_ceiling_months must be >= cash_floor_months")
      weight_total = sum(
        float(row.get(key_name) or 0.0)
        for key_name in ("distribution_weight", "debt_paydown_weight", "retain_weight")
      )
      if round(weight_total, 4) != 1.0:
        errors.append(f"{strategy}/{position} weights must sum to 1.0; got {weight_total:.4f}")
      deploy_required = _clean_bool(row.get("deploy_above_ceiling_required"), default=True)
      deploy_weight = float(row.get("distribution_weight") or 0.0) + float(row.get("debt_paydown_weight") or 0.0)
      retain_weight = float(row.get("retain_weight") or 0.0)
      if deploy_required and deploy_weight <= 0:
        errors.append(f"{strategy}/{position} must provide distribution or debt paydown weight when surplus deployment is required")
      if deploy_required and retain_weight > 0:
        errors.append(f"{strategy}/{position} retain_weight must be 0.0 when surplus deployment above ceiling is required")
      debt_method = _clean_text(row.get("debt_schedule_method")).lower()
      if debt_method != "amortizing_remaining_balance":
        errors.append(f"{strategy}/{position} unsupported debt_schedule_method {debt_method or 'missing'}")
      expected_debt_horizon = len(
        post_intake_gpt_contract_lookup().forecast_horizon_quarters(
          contract_name="cash_strategy_review"
        )
      )
      if expected_debt_horizon <= 0:
        expected_debt_horizon = 20
      if int(float(row.get("debt_schedule_horizon_quarters") or 0)) != expected_debt_horizon:
        errors.append(
          f"{strategy}/{position} debt_schedule_horizon_quarters must match cash_strategy_review contract horizon {expected_debt_horizon}"
        )
      if _clean_text(row.get("debt_minimum_payment_frequency")).lower() != "quarterly":
        errors.append(f"{strategy}/{position} debt_minimum_payment_frequency must be quarterly")
      if _clean_text(row.get("debt_extra_paydown_policy")).lower() != "cash_strategy_surplus_only":
        errors.append(f"{strategy}/{position} debt_extra_paydown_policy must be cash_strategy_surplus_only")
      source_priority = [
        _clean_text(item)
        for item in (row.get("debt_min_principal_source_priority") or [])
        if _clean_text(item)
      ]
      if "financials.annual_principal_payment" not in source_priority:
        errors.append(f"{strategy}/{position} debt_min_principal_source_priority must include financials.annual_principal_payment")
      if "policy.amortizing_remaining_balance_over_contract_horizon" not in source_priority:
        errors.append(f"{strategy}/{position} debt_min_principal_source_priority must include policy.amortizing_remaining_balance_over_contract_horizon")
      if not _clean_text(row.get("debt_interest_rate_source_required")):
        errors.append(f"{strategy}/{position} debt_interest_rate_source_required must not be empty")
      if _clean_bool(row.get("debt_interest_rate_fallback_allowed")):
        errors.append(f"{strategy}/{position} debt_interest_rate_fallback_allowed must be false")
      phase_sequence = self._normalized_phase_sequence(row.get("cash_phase_sequence"))
      phase_codes = [_clean_text(item.get("phase_code")).lower() for item in phase_sequence]
      if not phase_codes:
        errors.append(f"{strategy}/{position} cash_phase_sequence must not be empty")
      if phase_codes != required_phase_codes:
        errors.append(
          f"{strategy}/{position} cash_phase_sequence must match required cash pass phase order; "
          f"got={phase_codes} expected={required_phase_codes}"
        )
      if canonical_phase_codes is None:
        canonical_phase_codes = list(phase_codes)
      elif phase_codes != canonical_phase_codes:
        errors.append(f"{strategy}/{position} cash_phase_sequence differs from other active cash policy rows")
      seen_phase_codes: Set[str] = set()
      prior_order = -1
      for phase in phase_sequence:
        phase_code = _clean_text(phase.get("phase_code")).lower()
        phase_order = int(phase.get("phase_order") or 0)
        if phase_code in seen_phase_codes:
          errors.append(f"{strategy}/{position} duplicate cash phase {phase_code}")
        seen_phase_codes.add(phase_code)
        if phase_order <= prior_order:
          errors.append(f"{strategy}/{position} cash_phase_sequence must be strictly ordered")
        prior_order = phase_order
        if _clean_text(phase.get("phase_owner")).lower() not in {"python", "gpt"}:
          errors.append(f"{strategy}/{position} cash phase {phase_code} has unsupported phase_owner")
        if bool(phase.get("required")) is not True:
          errors.append(f"{strategy}/{position} cash phase {phase_code} must be required")
    for strategy in sorted(valid_strategies):
      for position in sorted(valid_positions):
        if (strategy, position) not in seen:
          errors.append(f"missing cash policy row for {strategy}/{position}")
    return errors


class PostIntakeGptContractLookup:
  """Single gateway for SQL-backed GPT contract field definitions."""

  def __init__(self, rows: Iterable[Dict[str, Any]]) -> None:
    self._rows = [
      dict(row)
      for row in rows
      if isinstance(row, dict)
      and _clean_text(row.get("contract_status")).lower() == "active"
    ]

  def rows(
    self,
    *,
    contract_name: Any = None,
    grid_name: Any = None,
    active_only: bool = True,
  ) -> List[Dict[str, Any]]:
    contract = _clean_text(contract_name).lower()
    grid = _clean_text(grid_name).lower()
    return [
      dict(row)
      for row in self._rows
      if (not contract or _clean_text(row.get("contract_name")).lower() == contract)
      and (not grid or _clean_text(row.get("grid_name")).lower() == grid)
      and (not active_only or _clean_text(row.get("contract_status")).lower() == "active")
    ]

  def contract_names(self) -> List[str]:
    return sorted(
      {
        _clean_text(row.get("contract_name")).lower()
        for row in self._rows
        if _clean_text(row.get("contract_name"))
      }
    )

  def grid_names(self, contract_name: Any) -> List[str]:
    contract = _clean_text(contract_name).lower()
    return sorted(
      {
        _clean_text(row.get("grid_name")).lower()
        for row in self._rows
        if _clean_text(row.get("contract_name")).lower() == contract
      }
    )

  def field_for_path(
    self,
    *,
    contract_name: Any,
    field_path: Any,
    grid_name: Any = None,
    required: bool = True,
  ) -> Optional[Dict[str, Any]]:
    contract = _clean_text(contract_name).lower()
    path = _clean_text(field_path)
    grid = _clean_text(grid_name).lower()
    for row in self.rows(contract_name=contract, grid_name=grid or None):
      if _clean_text(row.get("field_path")) == path:
        return dict(row)
    if required:
      raise RuntimeError(
        "post_intake_gpt_contract_field_missing: "
        f"contract_name={contract or 'missing'} grid_name={grid or '*'} field_path={path or 'missing'}"
      )
    return None

  def fields_for_grid(
    self,
    *,
    contract_name: Any,
    grid_name: Any,
    required: bool = True,
  ) -> List[Dict[str, Any]]:
    rows = self.rows(contract_name=contract_name, grid_name=grid_name)
    if required and not rows:
      raise RuntimeError(
        "post_intake_gpt_contract_grid_missing: "
        f"contract_name={_clean_text(contract_name).lower() or 'missing'} grid_name={_clean_text(grid_name).lower() or 'missing'}"
      )
    return rows

  def required_field_names(
    self,
    *,
    contract_name: Any,
    grid_name: Any,
  ) -> List[str]:
    return [
      _clean_text(row.get("field_name"))
      for row in self.fields_for_grid(contract_name=contract_name, grid_name=grid_name)
      if bool(row.get("required")) and _clean_text(row.get("field_name"))
    ]

  def alias_to_field_name(
    self,
    *,
    contract_name: Any,
    grid_name: Any,
  ) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for row in self.fields_for_grid(contract_name=contract_name, grid_name=grid_name):
      field_name = _clean_text(row.get("field_name"))
      if not field_name:
        continue
      aliases[field_name] = field_name
      for alias in row.get("allowed_aliases") or []:
        alias_name = _clean_text(alias)
        if alias_name:
          aliases[alias_name] = field_name
    return aliases

  def _resolve_naics_bound(
    self,
    row: Dict[str, Any],
    *,
    business_naics: Optional[str],
  ) -> Tuple[Optional[float], Optional[float], Optional[Dict[str, Any]]]:
    """Module 3 Task 3.2 — resolve NAICS-derived min/max for one contract row.

    Returns a tuple of (effective_min, effective_max, provenance).
    When the row has no `naics_baseline_metric_key`, returns the row's
    static min/max unchanged. When the resolver succeeds, narrows the
    bounds inside the static envelope (when `mapping_table_outer_envelope`
    is True). Provenance describes the source (None when no NAICS lookup
    was attempted).
    """
    static_min = row.get("min_value")
    static_max = row.get("max_value")
    metric_key = _clean_text(row.get("naics_baseline_metric_key"))
    naics_clean = _clean_text(business_naics)
    if not metric_key or not naics_clean:
      return static_min, static_max, None
    try:
      from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
        post_intake_industry_baseline_for_naics,
      )
      band = post_intake_industry_baseline_for_naics(
        metric_key=metric_key, naics_6=naics_clean
      )
    except Exception:
      return static_min, static_max, None
    if not isinstance(band, dict) or band.get("trust_flag") == "no_coverage":
      return static_min, static_max, None
    band_kind = _clean_text(row.get("naics_baseline_band_kind")).lower() or "min_target_max"
    bench_min = band.get("benchmark_min")
    bench_target = band.get("benchmark_target")
    bench_max = band.get("benchmark_max")
    # Module 3 v2 — quantile widening for target-only bands.
    #
    # Some upstream data sources only supply target (e.g., the
    # `derived_depreciation_proxy` source for maintenance_capex). With
    # naics_baseline_band_kind = "min_target_max" and bench_min/bench_max
    # absent, the v1 implementation returned target as both min and max —
    # producing a degenerate point constraint instead of a usable range.
    # The fix: when band_kind = "min_target_max" but bench_min/bench_max
    # are missing, widen target by the row's `naics_baseline_min_quantile`
    # / `naics_baseline_max_quantile` multipliers (defaults 0.5 / 1.5 — i.e.
    # +/- 50% of target). When band_kind = "target_only", keep the target
    # exact (caller asked for a point constraint).
    min_quantile = row.get("naics_baseline_min_quantile")
    max_quantile = row.get("naics_baseline_max_quantile")
    min_quantile_f = float(min_quantile) if min_quantile is not None else 0.5
    max_quantile_f = float(max_quantile) if max_quantile is not None else 1.5
    naics_min: Optional[float]
    naics_max: Optional[float]
    if band_kind == "target_only" and bench_target is not None:
      target = float(bench_target)
      naics_min = target
      naics_max = target
    else:
      # min_target_max (default) — prefer real bench_min/bench_max; widen
      # target with the configured quantiles when min/max are missing.
      if bench_min is not None and bench_max is not None:
        naics_min = float(bench_min)
        naics_max = float(bench_max)
      elif bench_target is not None:
        target = float(bench_target)
        naics_min = target * min_quantile_f
        naics_max = target * max_quantile_f
      else:
        naics_min = float(bench_min) if bench_min is not None else None
        naics_max = float(bench_max) if bench_max is not None else None
    if naics_min is None or naics_max is None:
      return static_min, static_max, None
    if naics_min > naics_max:
      naics_min, naics_max = naics_max, naics_min
    outer_envelope = bool(row.get("mapping_table_outer_envelope"))
    effective_min: Optional[float] = naics_min
    effective_max: Optional[float] = naics_max
    if outer_envelope:
      if static_min is not None:
        effective_min = max(float(static_min), naics_min)
      if static_max is not None:
        effective_max = min(float(static_max), naics_max)
    if effective_min is not None and effective_max is not None and effective_min > effective_max:
      # NAICS band falls outside the static envelope — keep the static
      # envelope and surface the provenance for diagnostics.
      effective_min, effective_max = static_min, static_max
    provenance = {
      "metric_key": metric_key,
      "naics_level_used": band.get("naics_level_used"),
      "naics_code_used": band.get("naics_code_used"),
      "confidence_tier": band.get("confidence_tier"),
      "data_source": band.get("data_source"),
      "trust_flag": band.get("trust_flag"),
      "source_min": naics_min,
      "source_max": naics_max,
      "static_min": static_min,
      "static_max": static_max,
      "band_kind": band_kind,
      "outer_envelope_applied": outer_envelope,
      "effective_min": effective_min,
      "effective_max": effective_max,
    }
    return effective_min, effective_max, provenance

  def _field_schema(
    self,
    row: Dict[str, Any],
    *,
    field_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    array_item_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    business_naics: Optional[str] = None,
  ) -> Dict[str, Any]:
    overrides = field_schema_overrides if isinstance(field_schema_overrides, dict) else {}
    item_overrides = array_item_schema_overrides if isinstance(array_item_schema_overrides, dict) else {}
    field_path = _clean_text(row.get("field_path"))
    field_name = _clean_text(row.get("field_name"))
    if field_path in overrides:
      return copy.deepcopy(overrides[field_path])
    if field_name in overrides:
      return copy.deepcopy(overrides[field_name])
    schema_type = _clean_text(row.get("json_schema_type")).lower() or "string"
    schema: Dict[str, Any] = {"type": schema_type}
    if bool(row.get("allow_null")):
      schema["type"] = [schema_type, "null"]
    enum_values = _json_list(row.get("enum_values"))
    if enum_values:
      schema["enum"] = enum_values + ([None] if bool(row.get("allow_null")) else [])
    # Module 3 Task 3.2 — NAICS-band injection (narrows the schema's
    # min/max when the row declares a `naics_baseline_metric_key`).
    effective_min, effective_max, naics_provenance = self._resolve_naics_bound(
      row, business_naics=business_naics
    )
    if effective_min is not None and schema_type in {"integer", "number"}:
      schema["minimum"] = int(effective_min) if schema_type == "integer" else float(effective_min)
    if effective_max is not None and schema_type in {"integer", "number"}:
      schema["maximum"] = int(effective_max) if schema_type == "integer" else float(effective_max)
    if naics_provenance is not None:
      # Annotate the schema for downstream prompt-trace + workbook
      # provenance. OpenAI ignores `_naics_band` but it makes the rendered
      # contract self-describing.
      schema["_naics_band"] = naics_provenance
    if schema_type == "array":
      min_items = row.get("min_items")
      max_items = row.get("max_items")
      if min_items is not None:
        schema["minItems"] = int(min_items)
      if max_items is not None:
        schema["maxItems"] = int(max_items)
      item_grid = _clean_text(row.get("item_contract_grid_name")).lower()
      if field_path in item_overrides:
        schema["items"] = copy.deepcopy(item_overrides[field_path])
      elif field_name in item_overrides:
        schema["items"] = copy.deepcopy(item_overrides[field_name])
      elif item_grid:
        schema["items"] = self.object_schema_for_grid(
          contract_name=row.get("contract_name"),
          grid_name=item_grid,
          field_schema_overrides=overrides,
          array_item_schema_overrides=item_overrides,
          business_naics=business_naics,
        )
      else:
        schema["items"] = {"type": "string"}
    if schema_type == "object":
      schema["additionalProperties"] = bool(row.get("additional_properties_allowed"))
      schema.setdefault("properties", {})
      schema.setdefault("required", [])
    return schema

  def object_schema_for_grid(
    self,
    *,
    contract_name: Any,
    grid_name: Any = "root",
    field_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    array_item_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    business_naics: Optional[str] = None,
  ) -> Dict[str, Any]:
    rows = self.fields_for_grid(contract_name=contract_name, grid_name=grid_name)
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for row in rows:
      field_name = _clean_text(row.get("field_name"))
      if not field_name:
        continue
      properties[field_name] = self._field_schema(
        row,
        field_schema_overrides=field_schema_overrides,
        array_item_schema_overrides=array_item_schema_overrides,
        business_naics=business_naics,
      )
      if bool(row.get("strict_required")):
        required.append(field_name)
    return {
      "type": "object",
      "additionalProperties": False,
      "properties": properties,
      "required": required,
    }

  def openai_schema(
    self,
    *,
    contract_name: Any,
    field_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    array_item_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    business_naics: Optional[str] = None,
  ) -> Dict[str, Any]:
    return self.object_schema_for_grid(
      contract_name=contract_name,
      grid_name="root",
      field_schema_overrides=field_schema_overrides,
      array_item_schema_overrides=array_item_schema_overrides,
      business_naics=business_naics,
    )

  def prompt_field_spec(self, contract_name: Any) -> Dict[str, Any]:
    contract = _clean_text(contract_name).lower()
    rows = self.rows(contract_name=contract)
    return {
      "contract_name": contract,
      "contract_table": _GPT_CONTRACT_TABLE_NAME,
      "source_of_truth": "sql.post_intake_gpt_contract_lookup",
      "horizon_rules": sorted(
        {
          _clean_text(row.get("horizon_rule")).lower()
          for row in rows
          if _clean_text(row.get("horizon_rule"))
        }
      ),
      "normalization_rules": sorted(
        {
          _clean_text(row.get("normalization_kind")).lower()
          for row in rows
          if _clean_text(row.get("normalization_kind")).lower() not in {"", "none"}
        }
      ),
      "fields": [
        {
          "grid_name": row.get("grid_name"),
          "field_path": row.get("field_path"),
          "field_name": row.get("field_name"),
          "field_type": row.get("field_type"),
          "required": bool(row.get("required")),
          "strict_required": bool(row.get("strict_required")),
          "min_items": row.get("min_items"),
          "max_items": row.get("max_items"),
          "item_contract_grid_name": row.get("item_contract_grid_name"),
          "normalization_kind": row.get("normalization_kind"),
          "rounding_kind": row.get("rounding_kind"),
          "decimal_places": row.get("decimal_places"),
          "horizon_rule": row.get("horizon_rule"),
          "validation_kind": row.get("validation_kind"),
          "lookup_source": row.get("lookup_source"),
          "allowed_aliases": copy.deepcopy(row.get("allowed_aliases") or []),
          "enum_values": copy.deepcopy(row.get("enum_values") or []),
          "gpt_owned": bool(row.get("gpt_owned")),
          "python_owned": bool(row.get("python_owned")),
          "editable": bool(row.get("editable")),
          "prompt_required_instruction": row.get("prompt_required_instruction"),
          "prompt_label": row.get("prompt_label"),
          "failure_code": row.get("failure_code"),
          "notes": row.get("notes"),
        }
        for row in rows
      ],
    }

  def compact_prompt_field_spec(self, contract_name: Any) -> Dict[str, Any]:
    spec = self.prompt_field_spec(contract_name)
    fields = [row for row in (spec.get("fields") or []) if isinstance(row, dict)]
    root_fields = [
      _clean_text(row.get("field_name"))
      for row in fields
      if _clean_text(row.get("grid_name")).lower() == "root"
      and _clean_text(row.get("field_name"))
    ]
    grid_fields: Dict[str, List[str]] = {}
    grid_row_counts: Dict[str, int] = {}
    for row in fields:
      grid_name = _clean_text(row.get("grid_name")).lower()
      field_name = _clean_text(row.get("field_name"))
      if not grid_name or grid_name == "root" or not field_name:
        continue
      grid_fields.setdefault(grid_name, []).append(field_name)
    for row in fields:
      if _clean_text(row.get("grid_name")).lower() != "root":
        continue
      item_grid = _clean_text(row.get("item_contract_grid_name")).lower()
      if not item_grid:
        continue
      min_items = row.get("min_items")
      max_items = row.get("max_items")
      if min_items is not None and max_items is not None and int(min_items) == int(max_items):
        grid_row_counts[item_grid] = int(min_items)
    return {
      "source_of_truth": spec.get("source_of_truth"),
      "contract_name": spec.get("contract_name"),
      "grid_names": spec.get("grid_names"),
      "horizon_rules": spec.get("horizon_rules"),
      "normalization_rules": spec.get("normalization_rules"),
      "field_count": len(fields),
      "required_response_shape": {
        "root_fields": root_fields,
        "grid_fields": grid_fields,
        "grid_row_counts": grid_row_counts,
      },
      "field_instructions": [
        {
          "field_path": row.get("field_path"),
          "field_name": row.get("field_name"),
          "prompt_required_instruction": row.get("prompt_required_instruction"),
          "prompt_label": row.get("prompt_label"),
          "validation_kind": row.get("validation_kind"),
          "normalization_kind": row.get("normalization_kind"),
          "lookup_source": row.get("lookup_source"),
        }
        for row in fields
        if _clean_text(row.get("prompt_required_instruction"))
        or _clean_text(row.get("prompt_label"))
      ],
    }

  def _normalize_scalar_value(self, row: Dict[str, Any], value: Any) -> Any:
    if value is None:
      return None
    rounding_kind = _clean_text(row.get("rounding_kind")).lower()
    decimal_places = row.get("decimal_places")
    field_type = _clean_text(row.get("field_type")).lower()
    if rounding_kind in {"nearest_dollar", "nearest_integer"} or field_type in {"integer", "integer_currency", "integer_or_negative_one"}:
      try:
        return int(round(float(value)))
      except Exception:
        return value
    if rounding_kind == "nearest_decimal" and decimal_places is not None:
      try:
        return round(float(value), int(decimal_places))
      except Exception:
        return value
    if field_type == "enum":
      return _clean_text(value).lower()
    return value

  def normalize_payload_grid(
    self,
    *,
    contract_name: Any,
    grid_name: Any,
    payload: Any,
  ) -> Any:
    if not isinstance(payload, dict):
      return payload
    contract = _clean_text(contract_name).lower()
    grid = _clean_text(grid_name).lower() or "root"
    alias_map = self.alias_to_field_name(contract_name=contract, grid_name=grid)
    rows_by_field = {
      _clean_text(row.get("field_name")): row
      for row in self.fields_for_grid(contract_name=contract, grid_name=grid)
      if _clean_text(row.get("field_name"))
    }
    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
      canonical_key = alias_map.get(_clean_text(key), _clean_text(key))
      row = rows_by_field.get(canonical_key)
      if not isinstance(row, dict):
        normalized[canonical_key] = copy.deepcopy(value)
        continue
      if _clean_text(row.get("json_schema_type")).lower() == "array" and isinstance(value, list):
        item_grid = _clean_text(row.get("item_contract_grid_name")).lower()
        if item_grid:
          normalized[canonical_key] = [
            self.normalize_payload_grid(
              contract_name=contract,
              grid_name=item_grid,
              payload=item,
            )
            if isinstance(item, dict)
            else copy.deepcopy(item)
            for item in value
          ]
        else:
          normalized[canonical_key] = copy.deepcopy(value)
      else:
        normalized[canonical_key] = self._normalize_scalar_value(row, value)
    return normalized

  def normalize_payload(self, *, contract_name: Any, payload: Any) -> Any:
    return self.normalize_payload_grid(
      contract_name=contract_name,
      grid_name="root",
      payload=payload,
    )

  def payload_errors_for_grid(
    self,
    *,
    contract_name: Any,
    grid_name: Any,
    payload: Any,
  ) -> List[str]:
    if not isinstance(payload, dict):
      return [f"{_clean_text(contract_name).lower()}/{_clean_text(grid_name).lower()} payload must be an object"]
    rows = self.fields_for_grid(contract_name=contract_name, grid_name=grid_name)
    fields = {_clean_text(row.get("field_name")): row for row in rows}
    errors: List[str] = []
    extra = sorted([key for key in payload.keys() if key not in fields])
    if extra:
      errors.append(
        f"{_clean_text(contract_name).lower()}/{_clean_text(grid_name).lower()} contains undeclared fields {extra}"
      )
    for field_name, row in fields.items():
      if bool(row.get("required")) and field_name not in payload:
        errors.append(str(row.get("failure_code") or f"{field_name}_missing"))
        continue
      if field_name not in payload:
        continue
      value = payload.get(field_name)
      if value is None:
        if not bool(row.get("allow_null")):
          errors.append(f"{field_name} cannot be null")
        continue
      schema_type = _clean_text(row.get("json_schema_type")).lower()
      if schema_type == "array":
        if not isinstance(value, list):
          errors.append(f"{field_name} must be an array")
          continue
        min_items = row.get("min_items")
        max_items = row.get("max_items")
        if min_items is not None and len(value) < int(min_items):
          errors.append(f"{field_name} must contain at least {int(min_items)} rows")
        if max_items is not None and len(value) > int(max_items):
          errors.append(f"{field_name} must contain no more than {int(max_items)} rows")
        item_grid = _clean_text(row.get("item_contract_grid_name")).lower()
        if item_grid:
          for item in value:
            if isinstance(item, dict):
              errors.extend(
                self.payload_errors_for_grid(
                  contract_name=contract_name,
                  grid_name=item_grid,
                  payload=item,
                )
              )
      elif schema_type == "object" and not isinstance(value, dict):
        errors.append(f"{field_name} must be an object")
      elif schema_type == "boolean" and not isinstance(value, bool):
        errors.append(f"{field_name} must be a boolean")
      elif schema_type == "integer":
        try:
          int(round(float(value)))
        except Exception:
          errors.append(f"{field_name} must be integer-compatible")
      elif schema_type == "number":
        try:
          float(value)
        except Exception:
          errors.append(f"{field_name} must be numeric")
      enum_values = _json_list(row.get("enum_values"))
      if enum_values and value is not None and _clean_text(value).lower() not in {item.lower() for item in enum_values}:
        errors.append(f"{field_name} must be one of {enum_values}")
    return errors

  def payload_errors(self, *, contract_name: Any, payload: Any) -> List[str]:
    return self.payload_errors_for_grid(
      contract_name=contract_name,
      grid_name="root",
      payload=payload,
    )

  def _quarter_value_from_payload(self, payload: Dict[str, Any]) -> Optional[int]:
    for key in ("q", "quarter_index", "quarter"):
      if key not in payload:
        continue
      try:
        quarter_value = int(round(float(payload.get(key))))
      except Exception:
        return None
      return quarter_value
    return None

  def _quarter_set_from_array(self, rows: List[Any]) -> Set[int]:
    quarters: Set[int] = set()
    for item in rows:
      if not isinstance(item, dict):
        continue
      quarter_value = self._quarter_value_from_payload(item)
      if quarter_value is not None:
        quarters.add(int(quarter_value))
    return quarters

  def _horizon_count_from_rule(self, horizon_rule: Any) -> int:
    rule = _clean_text(horizon_rule).lower()
    if not rule:
      return 0
    # Horizon ownership lives in SQL via strings such as q1_to_q20_exactly_once.
    # Keep parsing deliberately narrow so a misspelled rule fails validation.
    match = re.search(r"q1_to_q(\d+)", rule)
    return int(match.group(1)) if match else 0

  def _expected_quarters_for_rule(self, horizon_rule: Any) -> Set[int]:
    horizon_count = self._horizon_count_from_rule(horizon_rule)
    if horizon_count <= 0:
      return set()
    return set(range(1, horizon_count + 1))

  def forecast_horizon_quarters(self, *, contract_name: Any = None) -> List[int]:
    rows = self.rows(contract_name=contract_name) if contract_name is not None else self.rows()
    quarters: Set[int] = set()
    for row in rows:
      quarters.update(self._expected_quarters_for_rule(row.get("horizon_rule")))
    if quarters:
      return sorted(quarters)
    return []

  def horizon_errors_for_payload(
    self,
    *,
    contract_name: Any,
    payload: Any,
  ) -> List[str]:
    contract = _clean_text(contract_name).lower()
    if not isinstance(payload, dict):
      return [f"{contract or 'unknown'} payload must be an object before horizon validation"]
    errors: List[str] = []
    for row in self.rows(contract_name=contract, grid_name="root"):
      horizon_rule = _clean_text(row.get("horizon_rule")).lower()
      if not horizon_rule:
        continue
      expected_quarters = self._expected_quarters_for_rule(horizon_rule)
      if not expected_quarters:
        continue
      field_name = _clean_text(row.get("field_name"))
      if not field_name:
        continue
      value = payload.get(field_name)
      if horizon_rule == "q1_to_q20_exactly_once":
        horizon_label = f"Q1-Q{len(expected_quarters)}"
        if not isinstance(value, list):
          errors.append(f"{contract}.{field_name} must be an array with {horizon_label}")
          continue
        quarters = self._quarter_set_from_array(value)
        missing = sorted(expected_quarters - quarters)
        extra = sorted(quarter for quarter in quarters if quarter not in expected_quarters)
        if len(value) != len(expected_quarters) or missing or extra:
          errors.append(
            f"{contract}.{field_name} must contain exactly one row for every forecast quarter {horizon_label}; "
            f"row_count={len(value)} missing={missing} extra={extra}"
          )
      elif horizon_rule == "q1_to_q20_at_least_once":
        horizon_label = f"Q1-Q{len(expected_quarters)}"
        if not isinstance(value, list):
          errors.append(f"{contract}.{field_name} must be an array with {horizon_label}")
          continue
        quarters = self._quarter_set_from_array(value)
        missing = sorted(expected_quarters - quarters)
        extra = sorted(quarter for quarter in quarters if quarter not in expected_quarters)
        if missing or extra:
          errors.append(
            f"{contract}.{field_name} must include at least one row for every forecast quarter {horizon_label}; "
            f"row_count={len(value)} missing={missing} extra={extra}"
          )
      elif horizon_rule == "q1_to_q20_editable_cells":
        horizon_label = f"Q1-Q{len(expected_quarters)}"
        if not isinstance(value, list):
          errors.append(f"{contract}.{field_name} must be an array of editable cells")
          continue
        quarters = self._quarter_set_from_array(value)
        missing = sorted(expected_quarters - quarters)
        extra = sorted(quarter for quarter in quarters if quarter not in expected_quarters)
        if missing or extra:
          errors.append(
            f"{contract}.{field_name} must include editable-cell coverage across {horizon_label}; "
            f"missing={missing} extra={extra}"
          )
      elif horizon_rule in {
        "q1_to_q20_subset",
        "q1_to_q20_cash_review_rows",
        "q1_to_q20_required_funding_rows",
      }:
        if value is None:
          continue
        if not isinstance(value, list):
          errors.append(f"{contract}.{field_name} must be an array")
          continue
        for item in value:
          if not isinstance(item, dict):
            continue
          quarter_value = self._quarter_value_from_payload(item)
          if quarter_value is not None and quarter_value not in expected_quarters:
            errors.append(
              f"{contract}.{field_name} contains out-of-horizon quarter {quarter_value}; "
              f"allowed Q1-Q{len(expected_quarters)}"
            )
    return errors

  def contract_summary(self, contract_name: Any) -> Dict[str, Any]:
    contract = _clean_text(contract_name).lower()
    rows = self.rows(contract_name=contract)
    grids: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
      grids.setdefault(_clean_text(row.get("grid_name")).lower(), []).append(dict(row))
    return {
      "contract_name": contract,
      "grid_names": sorted(grids.keys()),
      "field_count": len(rows),
      "required_field_count": sum(1 for row in rows if bool(row.get("required"))),
      "lookup_sources": sorted(
        {
          _clean_text(row.get("lookup_source")).lower()
          for row in rows
          if _clean_text(row.get("lookup_source")).lower() not in {"", "none"}
        }
      ),
      "horizon_rules": sorted(
        {
          _clean_text(row.get("horizon_rule")).lower()
          for row in rows
          if _clean_text(row.get("horizon_rule"))
        }
      ),
    }

  def validation_errors(self) -> List[str]:
    errors: List[str] = []
    valid_field_types = {
      "array",
      "boolean",
      "enum",
      "integer",
      "integer_currency",
      "integer_or_negative_one",
      "number",
      "object",
      "ratio_2dp",
      "string",
    }
    valid_lookup_sources = {
      "none",
      "oews_title_catalog",
      "post_intak_mapping_lookup",
      "post_intake_cash_policy_lookup",
      "post_intake_headcount_policy_lookup",
    }
    valid_normalizers = {
      "none",
      "integer",
      "integer_currency",
      "ratio_2dp",
      "enum_lowercase",
      "field_type_numeric_contract",
    }
    valid_rounding_kinds = {
      "none",
      "nearest_decimal",
      "nearest_dollar",
      "nearest_integer",
    }
    valid_json_schema_types = {
      "array",
      "boolean",
      "integer",
      "number",
      "object",
      "string",
    }
    seen: Set[tuple[str, str, str]] = set()
    contracts_seen: Set[str] = set()
    for row in self._rows:
      contract = _clean_text(row.get("contract_name")).lower()
      grid = _clean_text(row.get("grid_name")).lower()
      path = _clean_text(row.get("field_path"))
      field_name = _clean_text(row.get("field_name"))
      field_type = _clean_text(row.get("field_type")).lower()
      contracts_seen.add(contract)
      key = (contract, grid, path)
      if not contract:
        errors.append("contract row missing contract_name")
      if not grid:
        errors.append(f"{contract or 'missing'} contract row missing grid_name")
      if not path:
        errors.append(f"{contract or 'missing'}/{grid or 'missing'} contract row missing field_path")
      if not field_name:
        errors.append(f"{contract or 'missing'}/{grid or 'missing'}/{path or 'missing'} row missing field_name")
      if key in seen:
        errors.append(f"duplicate GPT contract field row for {contract}/{grid}/{path}")
      seen.add(key)
      if field_type not in valid_field_types:
        errors.append(f"{contract}/{grid}/{path} has unsupported field_type {field_type or 'missing'}")
      schema_type = _clean_text(row.get("json_schema_type")).lower() or "string"
      if schema_type not in valid_json_schema_types:
        errors.append(f"{contract}/{grid}/{path} has unsupported json_schema_type {schema_type}")
      if field_type == "array" and schema_type != "array":
        errors.append(f"{contract}/{grid}/{path} array field must use json_schema_type=array")
      if field_type == "object" and schema_type != "object":
        errors.append(f"{contract}/{grid}/{path} object field must use json_schema_type=object")
      if field_type in {"integer", "integer_currency", "integer_or_negative_one"} and schema_type != "integer":
        errors.append(f"{contract}/{grid}/{path} integer-like field must use json_schema_type=integer")
      if field_type == "ratio_2dp" and schema_type != "number":
        errors.append(f"{contract}/{grid}/{path} ratio_2dp must use json_schema_type=number")
      if bool(row.get("required")) and not bool(row.get("strict_required")):
        errors.append(f"{contract}/{grid}/{path} required fields must also be strict_required")
      lookup_source = _clean_text(row.get("lookup_source")).lower() or "none"
      if lookup_source not in valid_lookup_sources:
        errors.append(f"{contract}/{grid}/{path} has unsupported lookup_source {lookup_source}")
      if bool(row.get("must_match_lookup")) and lookup_source == "none":
        errors.append(f"{contract}/{grid}/{path} must_match_lookup requires a real lookup_source")
      normalizer = _clean_text(row.get("normalization_kind")).lower() or "none"
      if normalizer not in valid_normalizers:
        errors.append(f"{contract}/{grid}/{path} has unsupported normalization_kind {normalizer}")
      rounding_kind = _clean_text(row.get("rounding_kind")).lower() or "none"
      if rounding_kind not in valid_rounding_kinds:
        errors.append(f"{contract}/{grid}/{path} has unsupported rounding_kind {rounding_kind}")
      decimal_places = row.get("decimal_places")
      if field_type == "integer_currency":
        if rounding_kind != "nearest_dollar" or decimal_places != 0:
          errors.append(f"{contract}/{grid}/{path} integer_currency must round nearest_dollar with decimal_places=0")
      if field_type == "ratio_2dp":
        if rounding_kind != "nearest_decimal" or decimal_places != 2:
          errors.append(f"{contract}/{grid}/{path} ratio_2dp must round nearest_decimal with decimal_places=2")
      if field_type in {"integer", "integer_or_negative_one"}:
        if rounding_kind != "nearest_integer" or decimal_places != 0:
          errors.append(f"{contract}/{grid}/{path} integer fields must round nearest_integer with decimal_places=0")
      if decimal_places is not None and int(decimal_places) < 0:
        errors.append(f"{contract}/{grid}/{path} decimal_places cannot be negative")
      min_value = row.get("min_value")
      max_value = row.get("max_value")
      if min_value is not None and max_value is not None and float(min_value) > float(max_value):
        errors.append(f"{contract}/{grid}/{path} min_value cannot exceed max_value")
      min_items = row.get("min_items")
      max_items = row.get("max_items")
      if min_items is not None and max_items is not None and int(min_items) > int(max_items):
        errors.append(f"{contract}/{grid}/{path} min_items cannot exceed max_items")
      if field_type == "array" and bool(row.get("required")) and not _clean_text(row.get("item_contract_grid_name")) and path.endswith("_grid"):
        errors.append(f"{contract}/{grid}/{path} grid arrays should declare item_contract_grid_name")
      if not _clean_text(row.get("failure_code")):
        errors.append(f"{contract}/{grid}/{path} requires failure_code")
      if field_type == "enum" and not _json_list(row.get("enum_values")):
        errors.append(f"{contract}/{grid}/{path} enum field requires enum_values")
      if bool(row.get("is_array_item")) and not _clean_text(row.get("parent_field_path")):
        errors.append(f"{contract}/{grid}/{path} array item field requires parent_field_path")
    for required_contract in {
      "maintenance_capex_percent",
      "payroll_headcount_schedule",
      "stage_ramp_contract",
      "unified_convergence_decision",
      "cash_strategy_review",
      "r_and_d_applicability",
      "unified_convergence_verification",
      "quarter_grid_probe",
      "realism_memo",
    }:
      if required_contract not in contracts_seen:
        errors.append(f"missing GPT contract rows for {required_contract}")
    return errors


class PostIntakeGptContextLookup:
  """Single gateway for SQL-backed GPT input-context definitions."""

  def __init__(self, rows: Iterable[Dict[str, Any]]) -> None:
    self._rows = [
      dict(row)
      for row in rows
      if isinstance(row, dict)
      and _clean_text(row.get("context_status")).lower() == "active"
    ]

  def rows(
    self,
    *,
    contract_name: Any = None,
    include_phase: Any = None,
    include_in_prompt: Optional[bool] = None,
  ) -> List[Dict[str, Any]]:
    contract = _clean_text(contract_name).lower()
    phase = _clean_text(include_phase).lower()
    result: List[Dict[str, Any]] = []
    for row in self._rows:
      row_contract = _clean_text(row.get("contract_name")).lower()
      row_phase = _clean_text(row.get("include_phase")).lower()
      if contract and row_contract != contract:
        continue
      if phase and row_phase and row_phase != phase:
        continue
      if include_in_prompt is not None and bool(row.get("include_in_prompt")) != bool(include_in_prompt):
        continue
      result.append(dict(row))
    return result

  def prompt_rows(
    self,
    *,
    contract_name: Any,
    include_phase: Any = None,
  ) -> List[Dict[str, Any]]:
    return self.rows(
      contract_name=contract_name,
      include_phase=include_phase,
      include_in_prompt=True,
    )

  def allowed_context_keys(
    self,
    *,
    contract_name: Any,
    include_phase: Any = None,
  ) -> List[str]:
    return [
      _clean_text(row.get("context_key"))
      for row in self.prompt_rows(contract_name=contract_name, include_phase=include_phase)
      if _clean_text(row.get("context_key"))
    ]

  def request_char_budget(
    self,
    *,
    contract_name: Any,
    include_phase: Any = None,
    default: Optional[int] = None,
  ) -> Optional[int]:
    budgets = [
      int(row.get("max_chars"))
      for row in self.rows(contract_name=contract_name, include_phase=include_phase)
      if _clean_text(row.get("transform_kind")).lower() == "request_char_budget"
      and row.get("max_chars") is not None
    ]
    if not budgets:
      return default
    return min(budgets)

  def filter_payload(
    self,
    *,
    contract_name: Any,
    payload: Any,
    include_phase: Any = None,
  ) -> Dict[str, Any]:
    if not isinstance(payload, dict):
      raise RuntimeError(
        "post_intake_gpt_context_payload_invalid: payload must be a dict"
      )
    rows = self.prompt_rows(contract_name=contract_name, include_phase=include_phase)
    if not rows:
      raise RuntimeError(
        "post_intake_gpt_context_rows_missing: "
        f"contract_name={_clean_text(contract_name).lower() or 'missing'} "
        f"include_phase={_clean_text(include_phase).lower() or '*'}"
      )
    filtered: Dict[str, Any] = {}
    missing_required: List[str] = []
    for row in rows:
      key = _clean_text(row.get("context_key"))
      if not key:
        continue
      if key in payload:
        value = copy.deepcopy(payload.get(key))
        max_items = row.get("max_items")
        if isinstance(value, list) and max_items is not None:
          value = value[: int(max_items)]
        filtered[key] = value
      elif bool(row.get("required")):
        missing_required.append(key)
    if missing_required:
      raise RuntimeError(
        "post_intake_gpt_context_required_keys_missing: "
        + ", ".join(missing_required)
      )
    return filtered

  def contract_summary(self, contract_name: Any) -> Dict[str, Any]:
    contract = _clean_text(contract_name).lower()
    rows = self.rows(contract_name=contract)
    return {
      "contract_name": contract,
      "context_table": _GPT_CONTEXT_TABLE_NAME,
      "source_of_truth": "sql.post_intake_gpt_context_lookup",
      "prompt_context_keys": [
        _clean_text(row.get("context_key"))
        for row in rows
        if bool(row.get("include_in_prompt")) and _clean_text(row.get("context_key"))
      ],
      "request_char_budget": self.request_char_budget(contract_name=contract),
      "context_count": len(rows),
    }

  def validation_errors(self) -> List[str]:
    errors: List[str] = []
    contracts_seen = {
      _clean_text(row.get("contract_name")).lower()
      for row in self._rows
      if _clean_text(row.get("contract_name"))
    }
    for row in self._rows:
      contract = _clean_text(row.get("contract_name")).lower()
      key = _clean_text(row.get("context_key"))
      if not contract:
        errors.append("GPT context row missing contract_name")
      if not key:
        errors.append(f"{contract or 'unknown'} context row missing context_key")
      if not _clean_text(row.get("failure_code")):
        errors.append(f"{contract}/{key} requires failure_code")
      if _clean_text(row.get("transform_kind")).lower() == "request_char_budget" and row.get("max_chars") is None:
        errors.append(f"{contract}/{key} request budget row requires max_chars")
    for required_contract in {
      "payroll_headcount_schedule",
      "stage_ramp_contract",
      "unified_convergence_decision",
      "cash_strategy_review",
      "quarter_grid_probe",
      "realism_memo",
    }:
      if required_contract not in contracts_seen:
        errors.append(f"missing GPT context rows for {required_contract}")
    return errors


def _process_context_get_path(payload: Any, source_path: Any) -> Any:
  if not isinstance(payload, dict):
    return None
  raw_path = _clean_text(source_path)
  if not raw_path:
    return None
  if raw_path in payload:
    return copy.deepcopy(payload.get(raw_path))
  current: Any = payload
  for token in [part for part in raw_path.split(".") if part]:
    if not isinstance(current, dict):
      return None
    if token not in current:
      return None
    current = current.get(token)
  return copy.deepcopy(current)


class PostIntakeProcessContextLookup:
  """SQL-backed declaration of immutable input context required by each process step."""

  _ALLOWED_SOURCE_KINDS = {
    "draft_column",
    "runtime_context",
    "domain_output",
    "derived_fact",
    "sql_lookup",
    "validation_result",
  }

  def __init__(self, rows: Iterable[Dict[str, Any]]) -> None:
    self._rows = [dict(row) for row in rows if isinstance(row, dict)]
    self._active_rows = [
      dict(row)
      for row in self._rows
      if _clean_text(row.get("context_status")).lower() == "active"
    ]
    self._by_step_key: Dict[str, List[Dict[str, Any]]] = {}
    self._by_step_context_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in self._active_rows:
      step_key = _clean_text(row.get("step_key")).lower()
      context_key = _clean_text(row.get("context_key"))
      if not step_key or not context_key:
        continue
      self._by_step_key.setdefault(step_key, []).append(dict(row))
      self._by_step_context_key[(step_key, context_key)] = dict(row)

  def rows(self, *, step_key: Any = None, active_only: bool = True) -> List[Dict[str, Any]]:
    wanted_step = _clean_text(step_key).lower()
    source = self._active_rows if active_only else self._rows
    return [
      dict(row)
      for row in source
      if not wanted_step or _clean_text(row.get("step_key")).lower() == wanted_step
    ]

  def context_keys_for_step(self, step_key: Any, *, required_only: bool = True) -> List[str]:
    ordered: List[str] = []
    for row in self.rows(step_key=step_key, active_only=True):
      if required_only and not bool(row.get("required")):
        continue
      context_key = _clean_text(row.get("context_key"))
      if context_key and context_key not in ordered:
        ordered.append(context_key)
    return ordered

  def spec_for_step_key(
    self,
    *,
    step_key: Any,
    context_key: Any,
    required: bool = False,
  ) -> Optional[Dict[str, Any]]:
    step = _clean_text(step_key).lower()
    key = _clean_text(context_key)
    spec = self._by_step_context_key.get((step, key))
    if spec is None and required:
      raise RuntimeError(
        f"post_intake_process_context_key_missing: step_key={step or 'missing'} "
        f"context_key={key or 'missing'} source=sql.{_PROCESS_CONTEXT_TABLE_NAME}"
      )
    return copy.deepcopy(spec) if isinstance(spec, dict) else None

  def manifest_for_step(
    self,
    step_key: Any,
    *,
    required_context_keys: Optional[Iterable[Any]] = None,
  ) -> List[Dict[str, Any]]:
    requested = [
      _clean_text(item)
      for item in (required_context_keys or [])
      if _clean_text(item)
    ]
    if not requested:
      return self.rows(step_key=step_key, active_only=True)
    manifest: List[Dict[str, Any]] = []
    for context_key in requested:
      manifest.append(
        self.spec_for_step_key(
          step_key=step_key,
          context_key=context_key,
          required=True,
        )
        or {}
      )
    return manifest

  def resolve_step_context(
    self,
    *,
    step_key: Any,
    required_context_keys: Optional[Iterable[Any]] = None,
    runtime_context: Optional[Dict[str, Any]] = None,
  ) -> Dict[str, Any]:
    runtime_payload = runtime_context if isinstance(runtime_context, dict) else {}
    manifest = self.manifest_for_step(
      step_key,
      required_context_keys=required_context_keys,
    )
    resolved: Dict[str, Any] = {}
    missing: List[Dict[str, Any]] = []
    for spec in manifest:
      context_key = _clean_text(spec.get("context_key"))
      if not context_key:
        continue
      source_kind = _clean_text(spec.get("source_kind")).lower()
      source_path = _clean_text(spec.get("source_path")) or context_key
      value = _process_context_get_path(runtime_payload, context_key)
      if value is None:
        value = _process_context_get_path(runtime_payload, source_path)
      if value is None and source_kind == "sql_lookup":
        value = {
          "source_kind": "sql_lookup",
          "source_path": source_path,
          "resolved_by_process_function": True,
        }
      if value is None and bool(spec.get("required")):
        missing.append(
          {
            "context_key": context_key,
            "source_kind": source_kind,
            "source_path": source_path,
          }
        )
        continue
      resolved[context_key] = copy.deepcopy(value)
    if missing:
      raise RuntimeError(
        "post_intake_process_context_required_inputs_missing: "
        f"step_key={_clean_text(step_key).lower()} missing={missing[:20]} "
        f"source=sql.{_PROCESS_CONTEXT_TABLE_NAME}"
      )
    return {
      "step_key": _clean_text(step_key).lower(),
      "source_of_truth": f"sql.{_PROCESS_CONTEXT_TABLE_NAME}",
      "lookup_function": "post_intake_process_context_lookup.resolve_step_context",
      "resolved_context": resolved,
      "resolved_context_keys": sorted(resolved.keys()),
      "required_context_manifest": copy.deepcopy(manifest),
      "context_is_mutable_state_store": False,
    }

  def validation_errors(self) -> List[str]:
    errors: List[str] = []
    seen: Set[tuple[str, str]] = set()
    for row in self._rows:
      step_key = _clean_text(row.get("step_key")).lower()
      context_key = _clean_text(row.get("context_key"))
      if not step_key:
        errors.append("process context row missing step_key")
      if not context_key:
        errors.append(f"{step_key or 'missing_step'} process context row missing context_key")
      dedupe_key = (step_key, context_key)
      if dedupe_key in seen:
        errors.append(f"duplicate process context key for step={step_key} context_key={context_key}")
      seen.add(dedupe_key)
      source_kind = _clean_text(row.get("source_kind")).lower()
      if source_kind not in self._ALLOWED_SOURCE_KINDS:
        errors.append(f"{step_key}.{context_key} unsupported source_kind={source_kind or 'missing'}")
      if not _clean_text(row.get("source_path")):
        errors.append(f"{step_key}.{context_key} missing source_path")
      if not bool(row.get("immutable_input")):
        errors.append(f"{step_key}.{context_key} must be immutable_input=1; context is not mutable runtime state")
    return errors


class PostIntakeProcessSequenceLookup:
  """Single gateway for SQL-backed post-intake step sequencing."""

  def __init__(self, rows: Iterable[Dict[str, Any]]) -> None:
    self._rows = [dict(row) for row in rows if isinstance(row, dict)]
    self._active_rows = [
      dict(row)
      for row in self._rows
      if _clean_text(row.get("sequence_status")).lower() == "active"
      and bool(row.get("enabled"))
    ]
    self._by_step_key: Dict[str, Dict[str, Any]] = {
      _clean_text(row.get("step_key")).lower(): dict(row)
      for row in self._active_rows
      if _clean_text(row.get("step_key"))
    }

  def rows(self, *, phase: Any = None, active_only: bool = True) -> List[Dict[str, Any]]:
    wanted_phase = _clean_text(phase).lower()
    source = self._active_rows if active_only else self._rows
    out = [
      dict(row)
      for row in source
      if not wanted_phase or _clean_text(row.get("phase")).lower() == wanted_phase
    ]
    return sorted(out, key=lambda item: int(item.get("step_order") or 0))

  def step(self, step_key: Any, *, required: bool = True) -> Optional[Dict[str, Any]]:
    key = _clean_text(step_key).lower()
    row = self._by_step_key.get(key)
    if row is None and required:
      raise RuntimeError(
        f"post_intake_process_sequence_step_missing: step_key={key or 'missing'} source=sql.{_PROCESS_SEQUENCE_TABLE_NAME}"
      )
    return dict(row) if row is not None else None

  def _lookup_table_errors(self, row: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    valid_lookup_tables = {
      _MAPPING_TABLE_NAME,
      _CASH_POLICY_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
      _PROCESS_SEQUENCE_TABLE_NAME,
      _PROCESS_CONTEXT_TABLE_NAME,
      "post_intake_headcount_policy_lookup",
    }
    for table_name in row.get("required_lookup_tables") or []:
      normalized_table = _clean_text(table_name)
      if normalized_table not in valid_lookup_tables:
        errors.append(
          f"{row.get('step_key')} references unsupported required lookup table {normalized_table}"
        )
        continue
      try:
        if normalized_table == _MAPPING_TABLE_NAME:
          table_errors = post_intake_mapping_lookup().validation_errors()
        elif normalized_table == _CASH_POLICY_TABLE_NAME:
          table_errors = post_intake_cash_policy_lookup().validation_errors()
        elif normalized_table == _GPT_CONTRACT_TABLE_NAME:
          table_errors = post_intake_gpt_contract_lookup().validation_errors()
        elif normalized_table == _GPT_CONTEXT_TABLE_NAME:
          table_errors = post_intake_gpt_context_lookup().validation_errors()
        elif normalized_table == _PROCESS_CONTEXT_TABLE_NAME:
          table_errors = post_intake_process_context_lookup().validation_errors()
        elif normalized_table == "post_intake_headcount_policy_lookup":
          try:
            from client_intake_and_finmo.post_intake_headcount import post_intake_headcount_policy_errors  # type: ignore
          except Exception:
            from post_intake_headcount import post_intake_headcount_policy_errors  # type: ignore
          table_errors = post_intake_headcount_policy_errors()
        else:
          table_errors = []
        for table_error in table_errors or []:
          errors.append(f"{row.get('step_key')} required lookup table {normalized_table} validation_error={table_error}")
      except Exception as exc:
        errors.append(
          f"{row.get('step_key')} required lookup table {normalized_table} failed validation: {exc}"
        )
    return errors

  def _required_lookup_context(self, row: Dict[str, Any]) -> Dict[str, Any]:
    """Load the SQL lookup dependencies declared by this sequence step."""
    context: Dict[str, Any] = {}
    for table_name in row.get("required_lookup_tables") or []:
      normalized_table = _clean_text(table_name)
      if normalized_table == _MAPPING_TABLE_NAME:
        lookup = post_intake_mapping_lookup()
        context[normalized_table] = {
          "lookup_function": "post_intake_mapping_lookup",
          "source_of_truth": f"sql.{_MAPPING_TABLE_NAME}",
          "active_row_count": len(lookup.rows()),
        }
      elif normalized_table == _CASH_POLICY_TABLE_NAME:
        lookup = post_intake_cash_policy_lookup()
        context[normalized_table] = {
          "lookup_function": "post_intake_cash_policy_lookup",
          "source_of_truth": f"sql.{_CASH_POLICY_TABLE_NAME}",
          "active_row_count": len(lookup.rows()),
          "phase_count": len(lookup.phase_sequence(required=False)),
        }
      elif normalized_table == _GPT_CONTRACT_TABLE_NAME:
        lookup = post_intake_gpt_contract_lookup()
        contract_name = _clean_text(row.get("contract_name")).lower()
        context[normalized_table] = {
          "lookup_function": "post_intake_gpt_contract_lookup",
          "source_of_truth": f"sql.{_GPT_CONTRACT_TABLE_NAME}",
          "contract_name": contract_name or None,
          "active_row_count": len(lookup.rows(contract_name=contract_name)) if contract_name else len(lookup.rows()),
        }
      elif normalized_table == _GPT_CONTEXT_TABLE_NAME:
        lookup = post_intake_gpt_context_lookup()
        contract_name = _clean_text(row.get("context_contract_name")).lower()
        include_phase = _clean_text(row.get("context_include_phase")).lower()
        context[normalized_table] = {
          "lookup_function": "post_intake_gpt_context_lookup",
          "source_of_truth": f"sql.{_GPT_CONTEXT_TABLE_NAME}",
          "contract_name": contract_name or None,
          "include_phase": include_phase or None,
          "allowed_context_keys": lookup.allowed_context_keys(
            contract_name=contract_name,
            include_phase=include_phase,
          ) if contract_name else [],
          "request_char_budget": lookup.request_char_budget(
            contract_name=contract_name,
            include_phase=include_phase,
          ) if contract_name else None,
        }
      elif normalized_table == "post_intake_headcount_policy_lookup":
        try:
          from client_intake_and_finmo.post_intake_headcount import post_intake_headcount_policy_for  # type: ignore
        except Exception:
          from post_intake_headcount import post_intake_headcount_policy_for  # type: ignore
        policy = post_intake_headcount_policy_for("default")
        context[normalized_table] = {
          "lookup_function": "post_intake_headcount_policy_for",
          "source_of_truth": "sql.post_intake_headcount_policy_lookup",
          "policy_code": "default",
          "schedule_horizon_quarters": int(policy.get("schedule_horizon_quarters") or 0),
          "schedule_storage_table": policy.get("schedule_storage_table"),
          "schedule_storage_column": policy.get("schedule_storage_column"),
        }
      elif normalized_table == _PROCESS_SEQUENCE_TABLE_NAME:
        lookup = post_intake_process_sequence_lookup()
        context[normalized_table] = {
          "lookup_function": "post_intake_process_sequence_lookup",
          "source_of_truth": f"sql.{_PROCESS_SEQUENCE_TABLE_NAME}",
          "active_step_count": len(lookup.rows(active_only=True)),
        }
      elif normalized_table == _PROCESS_CONTEXT_TABLE_NAME:
        lookup = post_intake_process_context_lookup()
        step_key = _clean_text(row.get("step_key")).lower()
        context[normalized_table] = {
          "lookup_function": "post_intake_process_context_lookup",
          "source_of_truth": f"sql.{_PROCESS_CONTEXT_TABLE_NAME}",
          "step_key": step_key or None,
          "required_context_keys": lookup.context_keys_for_step(step_key) if step_key else [],
          "active_row_count": len(lookup.rows(step_key=step_key)) if step_key else len(lookup.rows()),
        }
    return context

  def assert_step(
    self,
    *,
    step_key: Any,
    expected_phase: Any = None,
    expected_handler_key: Any = None,
    required_contract_name: Any = None,
    required_context_contract_name: Any = None,
    required_context_include_phase: Any = None,
    required_lookup_tables: Optional[Iterable[Any]] = None,
    required_horizon_rule: Any = None,
  ) -> Dict[str, Any]:
    row = self.step(step_key, required=True) or {}
    fail_code = _clean_text(row.get("fail_fast_code")) or "post_intake_process_sequence_violation"
    errors: List[str] = []
    if expected_phase and _clean_text(row.get("phase")).lower() != _clean_text(expected_phase).lower():
      errors.append(f"phase expected={_clean_text(expected_phase).lower()} actual={row.get('phase')}")
    if expected_handler_key and _clean_text(row.get("handler_key")) != _clean_text(expected_handler_key):
      errors.append(f"handler_key expected={_clean_text(expected_handler_key)} actual={row.get('handler_key')}")
    if required_contract_name and _clean_text(row.get("contract_name")).lower() != _clean_text(required_contract_name).lower():
      errors.append(f"contract_name expected={_clean_text(required_contract_name).lower()} actual={row.get('contract_name')}")
    if required_context_contract_name and _clean_text(row.get("context_contract_name")).lower() != _clean_text(required_context_contract_name).lower():
      errors.append(
        f"context_contract_name expected={_clean_text(required_context_contract_name).lower()} actual={row.get('context_contract_name')}"
      )
    if required_context_include_phase and _clean_text(row.get("context_include_phase")).lower() != _clean_text(required_context_include_phase).lower():
      errors.append(
        f"context_include_phase expected={_clean_text(required_context_include_phase).lower()} actual={row.get('context_include_phase')}"
      )
    if required_horizon_rule and _clean_text(row.get("horizon_rule")).lower() != _clean_text(required_horizon_rule).lower():
      errors.append(f"horizon_rule expected={_clean_text(required_horizon_rule).lower()} actual={row.get('horizon_rule')}")
    required_table_set = {
      _clean_text(item)
      for item in (required_lookup_tables or [])
      if _clean_text(item)
    }
    actual_table_set = {
      _clean_text(item)
      for item in (row.get("required_lookup_tables") or [])
      if _clean_text(item)
    }
    missing_tables = sorted(required_table_set - actual_table_set)
    if missing_tables:
      errors.append(f"required_lookup_tables missing={missing_tables} actual={sorted(actual_table_set)}")
    contract_name = _clean_text(row.get("contract_name")).lower()
    if contract_name and not post_intake_gpt_contract_rows(contract_name=contract_name):
      errors.append(f"contract table has no active rows for {contract_name}")
    context_contract_name = _clean_text(row.get("context_contract_name")).lower()
    if context_contract_name:
      context_rows = post_intake_gpt_context_rows(
        contract_name=context_contract_name,
        include_phase=_clean_text(row.get("context_include_phase")).lower(),
        include_in_prompt=True,
      )
      if not context_rows:
        errors.append(
          f"context table has no active prompt rows for {context_contract_name}/{_clean_text(row.get('context_include_phase')).lower()}"
        )
    process_context_manifest: List[Dict[str, Any]] = []
    declared_context_keys = [
      _clean_text(item)
      for item in (row.get("required_context_keys") or [])
      if _clean_text(item)
    ]
    if declared_context_keys:
      try:
        context_lookup = post_intake_process_context_lookup()
        process_context_manifest = context_lookup.manifest_for_step(
          row.get("step_key"),
          required_context_keys=declared_context_keys,
        )
        manifest_keys = {
          _clean_text(item.get("context_key"))
          for item in process_context_manifest
          if isinstance(item, dict)
        }
        missing_context_specs = sorted(set(declared_context_keys) - manifest_keys)
        if missing_context_specs:
          errors.append(
            f"required_context_keys missing process context rows={missing_context_specs} "
            f"source=sql.{_PROCESS_CONTEXT_TABLE_NAME}"
          )
      except Exception as exc:
        errors.append(f"process context lookup unavailable for required_context_keys: {exc}")
    else:
      errors.append("required_context_keys_json is empty")
    errors.extend(self._lookup_table_errors(row))
    if errors:
      raise RuntimeError(
        f"{fail_code}: post_intake_process_sequence_lookup violation for step_key={row.get('step_key')}: "
        + "; ".join(errors)
      )
    return {
      **copy.deepcopy(row),
      "required_lookup_context": self._required_lookup_context(row),
      "required_process_context": copy.deepcopy(process_context_manifest),
      "object_controls": copy.deepcopy(row.get("object_controls") or []),
      "sequence_enforced": True,
      "source_of_truth": f"sql.{_PROCESS_SEQUENCE_TABLE_NAME}",
      "lookup_function": "post_intake_assert_process_sequence_step",
    }

  def validation_errors(self) -> List[str]:
    errors: List[str] = []
    seen_step_keys: Set[str] = set()
    required_steps = {
      _clean_text(row.get("step_key")).lower()
      for row in _DEFAULT_PROCESS_SEQUENCE_ROWS
      if bool(row.get("required")) and _clean_text(row.get("step_key"))
    }
    active_step_keys = {
      _clean_text(row.get("step_key")).lower()
      for row in self._active_rows
      if _clean_text(row.get("step_key"))
    }
    context_lookup: Optional[PostIntakeProcessContextLookup] = None
    try:
      context_lookup = post_intake_process_context_lookup()
    except Exception as exc:
      errors.append(f"process context lookup unavailable: {exc}")
    for row in self._rows:
      step_key = _clean_text(row.get("step_key")).lower()
      if not step_key:
        errors.append("process sequence row missing step_key")
        continue
      if step_key in seen_step_keys:
        errors.append(f"duplicate process sequence step_key {step_key}")
      seen_step_keys.add(step_key)
      if not _clean_text(row.get("phase")):
        errors.append(f"{step_key} missing phase")
      if not _clean_text(row.get("handler_key")):
        errors.append(f"{step_key} missing handler_key")
      if not _clean_text(row.get("executor_function")):
        errors.append(f"{step_key} missing executor_function")
      if _clean_text(row.get("step_kind")).lower() not in {"stage", "process", "subprocess", "operation", "validation"}:
        errors.append(f"{step_key} unsupported step_kind={row.get('step_kind')}")
      parent_step_key = _clean_text(row.get("parent_step_key")).lower()
      if parent_step_key and parent_step_key not in active_step_keys:
        errors.append(f"{step_key} parent_step_key missing active parent={parent_step_key}")
      if int(row.get("hierarchy_level") or 0) <= 0:
        errors.append(f"{step_key} hierarchy_level must be positive")
      if not _clean_text(row.get("sequence_path")):
        errors.append(f"{step_key} missing sequence_path")
      if bool(row.get("required")) and not bool(row.get("enabled")):
        errors.append(f"{step_key} is required but disabled")
      if not row.get("required_lookup_tables"):
        errors.append(f"{step_key} missing required_lookup_tables")
      declared_context_keys = [
        _clean_text(item)
        for item in (row.get("required_context_keys") or [])
        if _clean_text(item)
      ]
      if not declared_context_keys:
        errors.append(f"{step_key} missing required_context_keys_json")
      elif context_lookup is not None:
        context_keys = set(context_lookup.context_keys_for_step(step_key, required_only=False))
        missing_context_specs = sorted(set(declared_context_keys) - context_keys)
        if missing_context_specs:
          errors.append(
            f"{step_key} required_context_keys missing process context rows={missing_context_specs}"
          )
      if not row.get("produced_output_keys"):
        errors.append(f"{step_key} missing produced_output_keys_json")
      if _clean_text(row.get("output_finality")).lower() not in {
        "stage_final_no_downstream_mutation",
        "validation_result_final",
        "read_only_context",
      }:
        errors.append(f"{step_key} unsupported output_finality={row.get('output_finality')}")
      output_storage = row.get("output_storage") if isinstance(row.get("output_storage"), list) else []
      for storage in output_storage:
        if not isinstance(storage, dict):
          errors.append(f"{step_key} has non-object output_storage_json entry")
          continue
        if not _clean_text(storage.get("output_key")):
          errors.append(f"{step_key} output_storage entry missing output_key")
        if not _clean_text(storage.get("storage_kind")):
          errors.append(f"{step_key} output_storage entry missing storage_kind")
        if bool(storage.get("writes_core_context")):
          errors.append(f"{step_key} output_storage may not write outputs back to core context")
      if not _clean_text(row.get("horizon_rule")):
        errors.append(f"{step_key} missing horizon_rule")
      if not _clean_text(row.get("python_role")):
        errors.append(f"{step_key} missing python_role")
      if not _clean_text(row.get("python_timing")):
        errors.append(f"{step_key} missing python_timing")
      if not _clean_text(row.get("python_action")):
        errors.append(f"{step_key} missing python_action")
      if not _clean_text(row.get("output_object_path")):
        errors.append(f"{step_key} missing output_object_path")
      if not _clean_text(row.get("validation_subject_path")):
        errors.append(f"{step_key} missing validation_subject_path")
      if ";" in _clean_text(row.get("validation_subject_path")):
        errors.append(f"{step_key} validation_subject_path must be a machine-readable object path, not prose")
      if step_key in {"payroll_headcount_schedule", "payroll_feasibility_repair", "quarter_grid_generation"} and not row.get("object_controls"):
        errors.append(f"{step_key} missing object_controls_json for table-driven execution enforcement")
      for control in row.get("object_controls") or []:
        if not isinstance(control, dict):
          errors.append(f"{step_key} has non-object object_controls_json entry")
          continue
        if not _clean_text(control.get("object_name")):
          errors.append(f"{step_key} object control missing object_name")
        if _clean_text(control.get("owner")).lower() not in {"gpt", "python", "locked"}:
          errors.append(f"{step_key} object control {_clean_text(control.get('object_name'))} has unsupported owner {control.get('owner')}")
        actions = control.get("allowed_actions") if isinstance(control.get("allowed_actions"), list) else []
        if not actions:
          errors.append(f"{step_key} object control {_clean_text(control.get('object_name'))} missing allowed_actions")
      if _clean_text(row.get("context_contract_name")) and not _clean_text(row.get("context_include_phase")):
        errors.append(f"{step_key} has context_contract_name but missing context_include_phase")
      errors.extend(self._lookup_table_errors(row))
    missing_required = sorted(required_steps - set(self._by_step_key.keys()))
    for step_key in missing_required:
      errors.append(f"missing active required process sequence step {step_key}")
    return errors

  def gateway_contexts(self) -> List[Dict[str, Any]]:
    """Load and return every active step's declared SQL table dependencies."""
    contexts: List[Dict[str, Any]] = []
    for row in self.rows(active_only=True):
      step_key = _clean_text(row.get("step_key")).lower()
      if not step_key:
        continue
      contexts.append(
        self.assert_step(
          step_key=step_key,
          expected_phase=row.get("phase"),
          expected_handler_key=row.get("handler_key"),
          required_contract_name=row.get("contract_name") or None,
          required_context_contract_name=row.get("context_contract_name") or None,
          required_context_include_phase=row.get("context_include_phase") or None,
          required_lookup_tables=row.get("required_lookup_tables") or [],
          required_horizon_rule=row.get("horizon_rule") or None,
        )
      )
    return contexts

  def assert_object_control(
    self,
    *,
    step_key: Any,
    object_name: Any,
    action: Any,
    owner: Any,
    trigger: Any = "",
  ) -> Dict[str, Any]:
    row = self.step(step_key, required=True) or {}
    requested_object = _clean_text(object_name)
    requested_action = _clean_text(action).lower()
    requested_owner = _clean_text(owner).lower()
    requested_trigger = _clean_text(trigger).lower()
    controls = [item for item in (row.get("object_controls") or []) if isinstance(item, dict)]
    matched = None
    for control in controls:
      if _clean_text(control.get("object_name")).lower() == requested_object.lower():
        matched = control
        break
    fail_code = _clean_text(row.get("fail_fast_code")) or "post_intake_process_sequence_object_control_violation"
    if not isinstance(matched, dict):
      raise RuntimeError(
        f"{fail_code}: object control missing for step_key={row.get('step_key')} "
        f"object_name={requested_object}; source=sql.{_PROCESS_SEQUENCE_TABLE_NAME}.object_controls_json"
      )
    allowed_actions = {
      _clean_text(item).lower()
      for item in (matched.get("allowed_actions") if isinstance(matched.get("allowed_actions"), list) else [])
      if _clean_text(item)
    }
    allowed_triggers = {
      _clean_text(item).lower()
      for item in (matched.get("allowed_triggers") if isinstance(matched.get("allowed_triggers"), list) else [])
      if _clean_text(item)
    }
    expected_owner = _clean_text(matched.get("owner")).lower()
    errors: List[str] = []
    if expected_owner and requested_owner != expected_owner:
      errors.append(f"owner expected={expected_owner} actual={requested_owner}")
    if requested_action not in allowed_actions:
      errors.append(f"action {requested_action} not in allowed_actions={sorted(allowed_actions)}")
    if requested_trigger and allowed_triggers and requested_trigger not in allowed_triggers:
      errors.append(f"trigger {requested_trigger} not in allowed_triggers={sorted(allowed_triggers)}")
    if errors:
      raise RuntimeError(
        f"{fail_code}: object control violation for step_key={row.get('step_key')} "
        f"object_name={requested_object}: " + "; ".join(errors)
      )
    return {
      "sequence_enforced": True,
      "source_of_truth": f"sql.{_PROCESS_SEQUENCE_TABLE_NAME}.object_controls_json",
      "lookup_function": "post_intake_assert_process_object_control",
      "step_key": _clean_text(row.get("step_key")).lower(),
      "object_name": requested_object,
      "action": requested_action,
      "owner": requested_owner,
      "trigger": requested_trigger,
      "control": copy.deepcopy(matched),
    }


@lru_cache(maxsize=1)
def post_intake_mapping_lookup() -> PostIntakeMappingLookup:
  return PostIntakeMappingLookup(load_post_intake_driver_target_mapping_rows())


@lru_cache(maxsize=1)
def post_intake_cash_policy_lookup() -> PostIntakeCashPolicyLookup:
  return PostIntakeCashPolicyLookup(load_post_intake_cash_policy_rows())


@lru_cache(maxsize=1)
def post_intake_gpt_contract_lookup() -> PostIntakeGptContractLookup:
  return PostIntakeGptContractLookup(load_post_intake_gpt_contract_rows())


@lru_cache(maxsize=1)
def post_intake_gpt_context_lookup() -> PostIntakeGptContextLookup:
  return PostIntakeGptContextLookup(load_post_intake_gpt_context_rows())


@lru_cache(maxsize=1)
def post_intake_process_context_lookup() -> PostIntakeProcessContextLookup:
  return PostIntakeProcessContextLookup(load_post_intake_process_context_rows())


@lru_cache(maxsize=1)
def post_intake_process_sequence_lookup() -> PostIntakeProcessSequenceLookup:
  return PostIntakeProcessSequenceLookup(load_post_intake_process_sequence_rows())


@lru_cache(maxsize=1)
def post_intake_driver_target_mapping_by_lever() -> Dict[str, Dict[str, Any]]:
  return {
    _clean_text(row.get("lookup_lever_id")): dict(row)
    for row in post_intake_mapping_lookup().rows(active_only=True)
    if _clean_text(row.get("lookup_lever_id"))
  }


def post_intake_driver_target_mapping_entry(lever_id: Any) -> Optional[Dict[str, Any]]:
  return post_intake_mapping_lookup().entry_for_lever(lever_id)


def post_intake_driver_formula_contract(
  lever_id: Any,
  *,
  required: bool = True,
) -> Optional[Dict[str, Any]]:
  return post_intake_mapping_lookup().formula_contract_for_lever(
    lever_id,
    required=required,
  )


def post_intake_driver_formula_contract_rows(
  *,
  phase: Any = None,
) -> List[Dict[str, Any]]:
  return post_intake_mapping_lookup().formula_contract_rows(phase=phase)


def post_intake_direct_target_metric_for_lever(lever_id: Any) -> str:
  return post_intake_mapping_lookup().target_metric_for_lever(lever_id)


def post_intake_direct_target_metric_names_for_levers(lever_ids: Optional[Iterable[Any]]) -> List[str]:
  return post_intake_mapping_lookup().target_metrics_for_levers(lever_ids)


def post_intake_driver_target_metric_ids(
  *,
  phase: Any = "convergence",
  targeting_allowed_only: bool = True,
) -> List[str]:
  return post_intake_mapping_lookup().target_metric_ids(
    phase=phase,
    targeting_allowed_only=targeting_allowed_only,
  )


def post_intake_driver_target_mapping_rows_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[Dict[str, Any]]:
  return post_intake_mapping_lookup().rows_for_issue(issue_code, phase=phase)


def post_intake_payroll_feasibility_mapping() -> Dict[str, Any]:
  lever_ids = [
    f"{_REVENUE_PATTERN_PREFIX}Capacity",
    f"{_REVENUE_PATTERN_PREFIX}Unit Price",
    f"{_REVENUE_PATTERN_PREFIX}Utilization",
    "expenses::Payroll",
  ]
  rows = post_intake_mapping_lookup().compact_lookup_for_levers(lever_ids)
  missing_rules = [
    _clean_text(row.get("lever_id"))
    for row in rows
    if not isinstance(row.get("repair_direction_rules"), dict) or not row.get("repair_direction_rules")
  ]
  if missing_rules or len(rows) < len(lever_ids):
    raise RuntimeError(
      "post_intake_payroll_feasibility_mapping_missing_direction_rules: "
      f"missing_or_empty={missing_rules} row_count={len(rows)} expected={len(lever_ids)} "
      f"source=sql.{_MAPPING_TABLE_NAME}.repair_direction_rules_json"
    )
  return {
    "source_of_truth": f"sql.{_MAPPING_TABLE_NAME}.repair_direction_rules_json",
    "lookup_function": "post_intake_payroll_feasibility_mapping",
    "rule_keys": ["payroll_revenue_ratio_high", "payroll_revenue_ratio_low"],
    "rows": rows,
  }


def post_intake_driver_target_lever_ids_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().lever_ids_for_issue(issue_code, phase=phase)


def post_intake_driver_target_lever_allowed_for_issue(
  lever_id: Any,
  issue_code: Any,
  *,
  phase: Any = None,
) -> bool:
  return post_intake_mapping_lookup().lever_allowed_for_issue(
    lever_id,
    issue_code,
    phase=phase,
  )


def post_intake_issue_candidate_lever_ids(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().issue_candidate_lever_ids(
    issue_code,
    phase=phase,
  )


def post_intake_concrete_issue_lever_ids_from_catalog(
  issue_code: Any,
  catalog_lever_ids: Iterable[Any],
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().concrete_issue_lever_ids_from_catalog(
    issue_code,
    catalog_lever_ids,
    phase=phase,
  )


def post_intake_target_metric_names_for_issue(
  issue_code: Any,
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().target_metrics_for_issue(issue_code, phase=phase)


def post_intake_issue_codes(
  *,
  targeting_allowed: Optional[bool] = None,
) -> List[str]:
  return post_intake_mapping_lookup().issue_codes(targeting_allowed=targeting_allowed)


def post_intake_issue_codes_for_phase(
  phase: Any,
  *,
  targeting_allowed: Optional[bool] = None,
) -> List[str]:
  return post_intake_mapping_lookup().issue_codes_for_phase(
    phase,
    targeting_allowed=targeting_allowed,
  )


def post_intake_issue_has_phase(issue_code: Any, phase: Any) -> bool:
  return post_intake_mapping_lookup().issue_has_phase(issue_code, phase)


def post_intake_issue_tolerance_allowed(
  issue_code: Any,
  *,
  phase: Any = None,
) -> bool:
  return post_intake_mapping_lookup().issue_tolerance_allowed(issue_code, phase=phase)


def post_intake_target_value_kind_for_metric(
  target_metric_name: Any,
  *,
  phase: Any = None,
) -> str:
  return post_intake_mapping_lookup().target_value_kind_for_metric(
    target_metric_name,
    phase=phase,
  )


def post_intake_target_precision_for_metric(
  target_metric_name: Any,
  *,
  phase: Any = None,
) -> Dict[str, Any]:
  return post_intake_mapping_lookup().target_precision_for_metric(
    target_metric_name,
    phase=phase,
  )


def post_intake_value_precision_for_lever(lever_id: Any) -> Dict[str, Any]:
  return post_intake_mapping_lookup().value_precision_for_lever(lever_id)


def post_intake_normalize_target_value(
  target_metric_name: Any,
  value: Any,
  *,
  phase: Any = None,
  bound_side: str = "",
) -> Any:
  return post_intake_mapping_lookup().normalize_target_value(
    target_metric_name,
    value,
    phase=phase,
    bound_side=bound_side,
  )


def post_intake_normalize_lever_value(
  lever_id: Any,
  value: Any,
  *,
  bound_side: str = "",
) -> Any:
  return post_intake_mapping_lookup().normalize_lever_value(
    lever_id,
    value,
    bound_side=bound_side,
  )


def post_intake_precision_unit(precision: Any) -> float:
  if not isinstance(precision, dict):
    return 0.0
  try:
    return float(precision.get("precision_unit") or 0.0)
  except Exception:
    return 0.0


def post_intake_issue_mapping_contract(
  issue_code: Any,
  *,
  phase: Any = None,
  allowed_target_metric_names: Optional[Iterable[Any]] = None,
  require: bool = True,
) -> Dict[str, Any]:
  return post_intake_mapping_lookup().issue_mapping_contract(
    issue_code,
    phase=phase,
    allowed_target_metric_names=allowed_target_metric_names,
    require=require,
  )


def post_intake_driver_target_lever_ids_for_target_drivers(
  target_drivers: Iterable[Any],
  *,
  phase: Any = None,
) -> List[str]:
  return post_intake_mapping_lookup().lever_ids_for_target_drivers(
    target_drivers,
    phase=phase,
  )


def post_intake_driver_target_single_lever_id_for_target_driver(
  target_driver: Any,
  *,
  phase: Any = None,
) -> str:
  return post_intake_mapping_lookup().single_lever_id_for_target_driver(
    target_driver,
    phase=phase,
  )


def post_intake_driver_target_lever_ids_for_cash_roles(
  cash_strategy_roles: Iterable[Any],
) -> List[str]:
  return post_intake_mapping_lookup().lever_ids_for_cash_roles(cash_strategy_roles)


def post_intake_compact_mapping_lookup_for_levers(
  lever_ids: Optional[Iterable[Any]] = None,
) -> List[Dict[str, Any]]:
  return post_intake_mapping_lookup().compact_lookup_for_levers(lever_ids)


def post_intake_driver_target_mapping_errors(expected_lever_ids: Optional[Iterable[Any]] = None) -> List[str]:
  return post_intake_mapping_lookup().validation_errors(expected_lever_ids)


def post_intake_cash_policy_for(
  *,
  cash_strategy: Any,
  debt_to_equity: Any,
  debt_position: Any = None,
  required: bool = True,
) -> Optional[Dict[str, Any]]:
  return post_intake_cash_policy_lookup().policy_for(
    cash_strategy=cash_strategy,
    debt_to_equity=debt_to_equity,
    debt_position=debt_position,
    required=required,
  )


def post_intake_cash_policy_rows(*, cash_strategy: Any = None) -> List[Dict[str, Any]]:
  return post_intake_cash_policy_lookup().rows(cash_strategy=cash_strategy)


def post_intake_cash_policy_phase_sequence(
  *,
  cash_strategy: Any = None,
  required: bool = True,
) -> List[Dict[str, Any]]:
  return post_intake_cash_policy_lookup().phase_sequence(
    cash_strategy=cash_strategy,
    required=required,
  )


def post_intake_cash_debt_schedule_policy(
  *,
  cash_strategy: Any,
  debt_to_equity: Any = None,
  debt_position: Any = None,
  required: bool = True,
) -> Optional[Dict[str, Any]]:
  return post_intake_cash_policy_lookup().debt_schedule_policy(
    cash_strategy=cash_strategy,
    debt_to_equity=debt_to_equity,
    debt_position=debt_position,
    required=required,
  )


def post_intake_cash_policy_errors() -> List[str]:
  return post_intake_cash_policy_lookup().validation_errors()


def post_intake_gpt_contract_rows(
  *,
  contract_name: Any = None,
  grid_name: Any = None,
) -> List[Dict[str, Any]]:
  return post_intake_gpt_contract_lookup().rows(
    contract_name=contract_name,
    grid_name=grid_name,
  )


def post_intake_gpt_contract_fields_for_grid(
  *,
  contract_name: Any,
  grid_name: Any,
  required: bool = True,
) -> List[Dict[str, Any]]:
  return post_intake_gpt_contract_lookup().fields_for_grid(
    contract_name=contract_name,
    grid_name=grid_name,
    required=required,
  )


def post_intake_gpt_contract_field_for_path(
  *,
  contract_name: Any,
  field_path: Any,
  grid_name: Any = None,
  required: bool = True,
) -> Optional[Dict[str, Any]]:
  return post_intake_gpt_contract_lookup().field_for_path(
    contract_name=contract_name,
    grid_name=grid_name,
    field_path=field_path,
    required=required,
  )


def post_intake_gpt_contract_required_field_names(
  *,
  contract_name: Any,
  grid_name: Any,
) -> List[str]:
  return post_intake_gpt_contract_lookup().required_field_names(
    contract_name=contract_name,
    grid_name=grid_name,
  )


def post_intake_gpt_contract_alias_to_field_name(
  *,
  contract_name: Any,
  grid_name: Any,
) -> Dict[str, str]:
  return post_intake_gpt_contract_lookup().alias_to_field_name(
    contract_name=contract_name,
    grid_name=grid_name,
  )


def post_intake_gpt_contract_summary(contract_name: Any) -> Dict[str, Any]:
  return post_intake_gpt_contract_lookup().contract_summary(contract_name)


def post_intake_gpt_contract_errors() -> List[str]:
  return post_intake_gpt_contract_lookup().validation_errors()


def post_intake_gpt_contract_openai_schema(
  *,
  contract_name: Any,
  field_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
  array_item_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
  business_naics: Optional[str] = None,
) -> Dict[str, Any]:
  return post_intake_gpt_contract_lookup().openai_schema(
    contract_name=contract_name,
    field_schema_overrides=field_schema_overrides,
    array_item_schema_overrides=array_item_schema_overrides,
    business_naics=business_naics,
  )


def post_intake_gpt_contract_prompt_field_spec(contract_name: Any) -> Dict[str, Any]:
  return post_intake_gpt_contract_lookup().prompt_field_spec(contract_name)


def post_intake_gpt_contract_compact_prompt_field_spec(contract_name: Any) -> Dict[str, Any]:
  return post_intake_gpt_contract_lookup().compact_prompt_field_spec(contract_name)


def _post_intake_prompt_constraint_text(row: Dict[str, Any]) -> str:
  parts: List[str] = []
  for key, label in (
    ("required", "required"),
    ("strict_required", "strict"),
    ("gpt_owned", "gpt-owned"),
    ("python_owned", "python-owned"),
    ("editable", "editable"),
  ):
    if bool(row.get(key)):
      parts.append(label)
  for key in ("min_value", "max_value", "min_items", "max_items"):
    value = row.get(key)
    if value is not None and value != "":
      parts.append(f"{key}={value}")
  for key in ("normalization_kind", "rounding_kind", "decimal_places", "horizon_rule", "validation_kind", "lookup_source"):
    value = _clean_text(row.get(key))
    if value and value.lower() not in {"none", "0"}:
      parts.append(f"{key}={value}")
  aliases = [
    _clean_text(item)
    for item in (row.get("allowed_aliases") or [])
    if _clean_text(item)
  ]
  if aliases:
    parts.append(f"aliases={aliases}")
  enum_values = [
    _clean_text(item)
    for item in (row.get("enum_values") or [])
    if _clean_text(item)
  ]
  if enum_values:
    parts.append(f"enum={enum_values}")
  return "; ".join(parts)


def post_intake_build_prompt_from_contract(
  contract_name: Any,
  *,
  context_payload: Any = None,
  include_phase: Any = None,
  static_instruction: Any = "",
  task_instruction: Any = "",
) -> str:
  """Render a GPT prompt section from SQL contract/context lookup tables.

  Static prose may explain the thinking task, but deterministic structure comes
  from ``post_intake_gpt_contract_lookup`` and ``post_intake_gpt_context_lookup``.
  """
  contract = _clean_text(contract_name).lower()
  contract_rows = post_intake_gpt_contract_rows(contract_name=contract)
  if not contract_rows:
    raise RuntimeError(f"post_intake_prompt_contract_missing: {contract}")
  context_rows = post_intake_gpt_context_rows(
    contract_name=contract,
    include_phase=include_phase,
    include_in_prompt=True,
  )
  filtered_context = (
    post_intake_gpt_context_filter_payload(
      contract_name=contract,
      payload=context_payload,
      include_phase=include_phase,
    )
    if isinstance(context_payload, dict) and context_rows
    else {}
  )
  grouped_fields: Dict[str, List[Dict[str, Any]]] = {}
  for row in contract_rows:
    grouped_fields.setdefault(_clean_text(row.get("grid_name")).lower() or "root", []).append(row)

  lines: List[str] = [
    "STATIC ROLE INSTRUCTION:",
    _clean_text(static_instruction) or "Produce a valid contract payload using business judgment inside the table-defined contract.",
    "",
    "TABLE AUTHORITY:",
    "- Deterministic prompt structure is rendered from sql.post_intake_gpt_contract_lookup and sql.post_intake_gpt_context_lookup.",
    "- The SQL contract table is authoritative for fields, requiredness, types, normalization, horizon rules, lookup sources, and validation.",
    "- Do not add fields. Do not omit required fields. Do not invent structure outside the contract table.",
    "",
    f"CONTRACT SPEC: {contract}",
  ]
  for grid_name in sorted(grouped_fields.keys()):
    fields = grouped_fields[grid_name]
    root_row = next(
      (
        row for row in fields
        if _clean_text(row.get("grid_name")).lower() == "root"
        and _clean_text(row.get("item_contract_grid_name")).lower() == grid_name
      ),
      None,
    )
    grid_label = f"Grid: {grid_name}"
    if root_row:
      min_items = root_row.get("min_items")
      max_items = root_row.get("max_items")
      if min_items is not None and max_items is not None and str(min_items) == str(max_items):
        grid_label += f" ({min_items} rows)"
    lines.extend(["", grid_label])
    for row in fields:
      field_path = _clean_text(row.get("field_path")) or _clean_text(row.get("field_name"))
      field_type = _clean_text(row.get("field_type")) or _clean_text(row.get("json_schema_type"))
      constraints = _post_intake_prompt_constraint_text(row)
      instruction = _clean_text(row.get("prompt_required_instruction"))
      prompt_label = _clean_text(row.get("prompt_label"))
      label = f"{field_path}: {field_type}"
      if prompt_label:
        label += f" ({prompt_label})"
      if constraints:
        label += f" [{constraints}]"
      lines.append(f"- {label}")
      if instruction:
        lines.append(f"  Instruction: {instruction}")

  lines.extend(["", "CONTEXT SPEC:"])
  if context_rows:
    for row in context_rows:
      context_key = _clean_text(row.get("context_key"))
      source_kind = _clean_text(row.get("source_kind"))
      transform_kind = _clean_text(row.get("transform_kind"))
      required = "required" if bool(row.get("required")) else "optional"
      budget = []
      if row.get("max_items") is not None:
        budget.append(f"max_items={row.get('max_items')}")
      if row.get("max_chars") is not None:
        budget.append(f"max_chars={row.get('max_chars')}")
      suffix = f" [{'; '.join(budget)}]" if budget else ""
      lines.append(f"- {context_key}: {required}; source={source_kind}; transform={transform_kind}{suffix}")
  else:
    lines.append("- No prompt context rows are defined for this contract/phase.")
  if filtered_context:
    lines.extend(
      [
        "",
        "CONTEXT PAYLOAD KEYS:",
        "- " + ", ".join(sorted(str(key) for key in filtered_context.keys())),
      ]
    )
  lines.extend(
    [
      "",
      "TASK:",
      _clean_text(task_instruction) or "Return only JSON that satisfies this table-rendered contract.",
    ]
  )
  return "\n".join(lines).strip()


def post_intake_gpt_contract_normalize_payload(
  *,
  contract_name: Any,
  payload: Any,
) -> Any:
  return post_intake_gpt_contract_lookup().normalize_payload(
    contract_name=contract_name,
    payload=payload,
  )


def post_intake_gpt_contract_payload_errors(
  *,
  contract_name: Any,
  payload: Any,
) -> List[str]:
  return post_intake_gpt_contract_lookup().payload_errors(
    contract_name=contract_name,
    payload=payload,
  )


def post_intake_gpt_contract_horizon_errors(
  *,
  contract_name: Any,
  payload: Any,
) -> List[str]:
  return post_intake_gpt_contract_lookup().horizon_errors_for_payload(
    contract_name=contract_name,
    payload=payload,
  )


def post_intake_contract_forecast_horizon_quarters(
  *,
  contract_name: Any = None,
) -> List[int]:
  return post_intake_gpt_contract_lookup().forecast_horizon_quarters(
    contract_name=contract_name,
  )


def post_intake_contract_forecast_horizon_quarter_count(
  *,
  contract_name: Any = None,
) -> int:
  quarters = post_intake_contract_forecast_horizon_quarters(
    contract_name=contract_name,
  )
  return max(quarters or [20])


def post_intake_gpt_context_rows(
  *,
  contract_name: Any = None,
  include_phase: Any = None,
  include_in_prompt: Optional[bool] = None,
) -> List[Dict[str, Any]]:
  return post_intake_gpt_context_lookup().rows(
    contract_name=contract_name,
    include_phase=include_phase,
    include_in_prompt=include_in_prompt,
  )


def post_intake_gpt_context_allowed_keys(
  *,
  contract_name: Any,
  include_phase: Any = None,
) -> List[str]:
  return post_intake_gpt_context_lookup().allowed_context_keys(
    contract_name=contract_name,
    include_phase=include_phase,
  )


def post_intake_gpt_context_filter_payload(
  *,
  contract_name: Any,
  payload: Any,
  include_phase: Any = None,
) -> Dict[str, Any]:
  return post_intake_gpt_context_lookup().filter_payload(
    contract_name=contract_name,
    payload=payload,
    include_phase=include_phase,
  )


def post_intake_gpt_context_request_char_budget(
  *,
  contract_name: Any,
  include_phase: Any = None,
  default: Optional[int] = None,
) -> Optional[int]:
  return post_intake_gpt_context_lookup().request_char_budget(
    contract_name=contract_name,
    include_phase=include_phase,
    default=default,
  )


def post_intake_gpt_context_summary(contract_name: Any) -> Dict[str, Any]:
  return post_intake_gpt_context_lookup().contract_summary(contract_name)


def post_intake_gpt_context_errors() -> List[str]:
  return post_intake_gpt_context_lookup().validation_errors()


def post_intake_process_context_rows(
  *,
  step_key: Any = None,
  active_only: bool = True,
) -> List[Dict[str, Any]]:
  return post_intake_process_context_lookup().rows(
    step_key=step_key,
    active_only=active_only,
  )


def post_intake_process_context_errors() -> List[str]:
  return post_intake_process_context_lookup().validation_errors()


def post_intake_process_context_manifest(
  step_key: Any,
  *,
  required_context_keys: Optional[Iterable[Any]] = None,
) -> List[Dict[str, Any]]:
  return post_intake_process_context_lookup().manifest_for_step(
    step_key,
    required_context_keys=required_context_keys,
  )


def post_intake_resolve_process_context(
  *,
  step_key: Any,
  runtime_context: Optional[Dict[str, Any]] = None,
  required_context_keys: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
  row = post_intake_process_sequence_step(step_key, required=True) or {}
  resolved_required_keys = (
    list(required_context_keys)
    if required_context_keys is not None
    else list(row.get("required_context_keys") or [])
  )
  return post_intake_process_context_lookup().resolve_step_context(
    step_key=step_key,
    required_context_keys=resolved_required_keys,
    runtime_context=runtime_context,
  )


def post_intake_process_sequence_rows(
  *,
  phase: Any = None,
  active_only: bool = True,
) -> List[Dict[str, Any]]:
  return post_intake_process_sequence_lookup().rows(
    phase=phase,
    active_only=active_only,
  )


def post_intake_process_sequence_step(
  step_key: Any,
  *,
  required: bool = True,
) -> Optional[Dict[str, Any]]:
  return post_intake_process_sequence_lookup().step(
    step_key,
    required=required,
  )


def post_intake_assert_process_sequence_step(
  *,
  step_key: Any,
  expected_phase: Any = None,
  expected_handler_key: Any = None,
  required_contract_name: Any = None,
  required_context_contract_name: Any = None,
  required_context_include_phase: Any = None,
  required_lookup_tables: Optional[Iterable[Any]] = None,
  required_horizon_rule: Any = None,
) -> Dict[str, Any]:
  return post_intake_process_sequence_lookup().assert_step(
    step_key=step_key,
    expected_phase=expected_phase,
    expected_handler_key=expected_handler_key,
    required_contract_name=required_contract_name,
    required_context_contract_name=required_context_contract_name,
    required_context_include_phase=required_context_include_phase,
    required_lookup_tables=required_lookup_tables,
    required_horizon_rule=required_horizon_rule,
  )


def post_intake_assert_process_object_control(
  *,
  step_key: Any,
  object_name: Any,
  action: Any,
  owner: Any,
  trigger: Any = "",
) -> Dict[str, Any]:
  return post_intake_process_sequence_lookup().assert_object_control(
    step_key=step_key,
    object_name=object_name,
    action=action,
    owner=owner,
    trigger=trigger,
  )


def post_intake_process_step_context(
  *,
  step_key: Any,
  expected_phase: Any = None,
  expected_handler_key: Any = None,
  required_contract_name: Any = None,
  required_context_contract_name: Any = None,
  required_context_include_phase: Any = None,
  required_lookup_tables: Optional[Iterable[Any]] = None,
  required_horizon_rule: Any = None,
) -> Dict[str, Any]:
  context = post_intake_assert_process_sequence_step(
    step_key=step_key,
    expected_phase=expected_phase,
    expected_handler_key=expected_handler_key,
    required_contract_name=required_contract_name,
    required_context_contract_name=required_context_contract_name,
    required_context_include_phase=required_context_include_phase,
    required_lookup_tables=required_lookup_tables,
    required_horizon_rule=required_horizon_rule,
  )
  context["lookup_function"] = "post_intake_process_step_context"
  context["process_step_context_loaded"] = True
  return context


def post_intake_assert_required_process_sequence() -> Dict[str, Any]:
  """Fail fast unless the SQL sequence table and all declared lookup dependencies are valid."""
  lookup = post_intake_process_sequence_lookup()
  errors = lookup.validation_errors()
  if errors:
    raise RuntimeError(
      "post_intake_process_sequence_lookup_invalid: "
      + "; ".join(str(item) for item in errors[:30])
    )
  rows = lookup.rows(active_only=True)
  gateway_contexts = lookup.gateway_contexts()
  process_context_rows = post_intake_process_context_rows(active_only=True)
  return {
    "sequence_enforced": True,
    "source_of_truth": f"sql.{_PROCESS_SEQUENCE_TABLE_NAME}",
    "lookup_function": "post_intake_assert_required_process_sequence",
    "gateway_context_loaded": True,
    "active_step_count": len(rows),
    "process_context_source_of_truth": f"sql.{_PROCESS_CONTEXT_TABLE_NAME}",
    "process_context_row_count": len(process_context_rows),
    "active_steps": [
      _clean_text(row.get("step_key")).lower()
      for row in rows
      if _clean_text(row.get("step_key"))
    ],
    "step_table_dependencies": [
      {
        "step_key": _clean_text(context.get("step_key")).lower(),
        "phase": _clean_text(context.get("phase")).lower(),
        "parent_step_key": _clean_text(context.get("parent_step_key")).lower(),
        "step_kind": _clean_text(context.get("step_kind")).lower(),
        "sequence_path": _clean_text(context.get("sequence_path")).lower(),
        "handler_key": _clean_text(context.get("handler_key")),
        "executor_function": _clean_text(context.get("executor_function")),
        "required_context_keys": copy.deepcopy(context.get("required_context_keys") or []),
        "produced_output_keys": copy.deepcopy(context.get("produced_output_keys") or []),
        "required_lookup_tables": copy.deepcopy(context.get("required_lookup_tables") or []),
        "required_lookup_context": copy.deepcopy(context.get("required_lookup_context") or {}),
        "required_process_context": copy.deepcopy(context.get("required_process_context") or []),
        "horizon_rule": _clean_text(context.get("horizon_rule")).lower(),
        "python_role": _clean_text(context.get("python_role")),
        "python_timing": _clean_text(context.get("python_timing")),
        "input_object_path": _clean_text(context.get("input_object_path")),
        "output_object_path": _clean_text(context.get("output_object_path")),
        "validation_subject_path": _clean_text(context.get("validation_subject_path")),
        "output_storage": copy.deepcopy(context.get("output_storage") or []),
        "recompute_triggers": copy.deepcopy(context.get("recompute_triggers") or []),
        "output_finality": _clean_text(context.get("output_finality")).lower(),
        "object_controls": copy.deepcopy(context.get("object_controls") or []),
      }
      for context in gateway_contexts
    ],
  }


def post_intake_process_sequence_errors() -> List[str]:
  return post_intake_process_sequence_lookup().validation_errors()


def post_intake_golden_lookup_snapshot_errors(
  *,
  baseline_name: Any = _GOLDEN_BASELINE_NAME,
) -> List[str]:
  return post_intake_lookup_table_snapshot_errors(baseline_name=baseline_name)


def post_intake_golden_lookup_snapshot_rows(
  *,
  baseline_name: Any = _GOLDEN_BASELINE_NAME,
) -> List[Dict[str, Any]]:
  return post_intake_lookup_table_snapshot_rows(baseline_name=baseline_name)


def post_intake_refresh_golden_lookup_snapshot(
  *,
  baseline_name: Any = _GOLDEN_BASELINE_NAME,
  source_commit: Any = "",
  notes: Any = "",
) -> List[Dict[str, Any]]:
  return refresh_post_intake_lookup_table_snapshot(
    baseline_name=baseline_name,
    source_commit=source_commit,
    notes=notes,
  )
