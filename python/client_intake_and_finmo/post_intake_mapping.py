from __future__ import annotations

import os
import threading
import copy
import hashlib
import json
import math
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set


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
_LOOKUP_SNAPSHOT_TABLE_NAME = "post_intake_lookup_table_snapshot"
_GOLDEN_BASELINE_NAME = "post_intake_golden_f949316"
_FINMO_ROW_PREFIX = "finmo_json.quarter_rows[*]."
_REVENUE_PATTERN_PREFIX = "revenue::*::*::"
_ENSURE_MAPPING_TABLE_READY = False
_ENSURE_CASH_POLICY_TABLE_READY = False
_ENSURE_GPT_CONTRACT_TABLE_READY = False
_ENSURE_GPT_CONTEXT_TABLE_READY = False
_ENSURE_PROCESS_SEQUENCE_TABLE_READY = False
_ENSURE_LOOKUP_SNAPSHOT_TABLE_READY = False
_ENSURE_MAPPING_TABLE_LOCK = threading.Lock()
_ENSURE_CASH_POLICY_TABLE_LOCK = threading.Lock()
_ENSURE_GPT_CONTRACT_TABLE_LOCK = threading.Lock()
_ENSURE_GPT_CONTEXT_TABLE_LOCK = threading.Lock()
_ENSURE_PROCESS_SEQUENCE_TABLE_LOCK = threading.Lock()
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
    "notes": "Apply SQL cash-policy minimum debt schedule before cash review so scheduled principal is not optional.",
  },
  {
    "phase_code": "cash_short_term_debt_seed",
    "phase_order": 10,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "seed_short_term_debt_current_portion",
    "notes": "Normalize current debt portion semantics before building the cash review envelope.",
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
    "notes": "Reapply the minimum debt schedule floor after cash strategy updates while preserving extra paydown.",
  },
  {
    "phase_code": "cash_short_term_debt_current_portion",
    "phase_order": 60,
    "phase_owner": "python",
    "required": True,
    "requires_finmo_rebuild_after": True,
    "validation_gate": "short_term_debt_current_portion_applied",
    "notes": "Apply current portion of long-term debt after cash updates and rebuild FINMO.",
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
  notes: str = "",
) -> Dict[str, Any]:
  return {
    "phase": phase,
    "step_order": int(step_order),
    "step_key": step_key,
    "handler_key": handler_key,
    "contract_name": contract_name,
    "context_contract_name": context_contract_name,
    "context_include_phase": context_include_phase,
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
    "input_object_path": input_object_path or f"{step_key}.input",
    "output_object_path": output_object_path or f"{step_key}.output",
    "validation_subject_path": validation_subject_path or output_object_path or f"{step_key}.output",
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
    notes="GPT selects R&D on/off before forecast generation; Python enforces the toggle.",
  ),
  _process_sequence_row(
    "pre_convergence",
    40,
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
    timeout_seconds=60,
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
    50,
    "quarter_grid_generation",
    "generate_live_quarter_grid_plan",
    contract_name="quarter_grid_probe",
    context_contract_name="quarter_grid_probe",
    context_include_phase="initial_grid",
    required_lookup_tables=[
      _MAPPING_TABLE_NAME,
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
    ],
    horizon_rule="q1_to_q20_model_input_state",
    fail_fast_code="post_intake_sequence_quarter_grid_contract_missing",
    notes="Initial 20-quarter model_input grid uses quarter_grid_probe for its GPT response contract and consumes the stage ramp as runtime context.",
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
      _GPT_CONTRACT_TABLE_NAME,
      _GPT_CONTEXT_TABLE_NAME,
      "post_intake_headcount_policy_lookup",
    ],
    horizon_rule="q1_to_q20_at_least_once",
    timeout_seconds=None,
    max_attempts=1,
    fail_fast_code="post_intake_sequence_headcount_contract_missing",
    python_role="contract_request_and_schedule_builder",
    python_timing="after_quarter_grid_before_convergence",
    python_action=(
      "Call GPT for the independent payroll_headcount_schedule contract, validate it through "
      "post_intake_headcount_policy_lookup against the applied quarter grid, then calculate and persist the Payroll model-input schedule."
    ),
    input_object_path="business_facts, operating_model_json, people_json, financials_json, applied_model_input_json, applied_finmo_json, stage_ramp_contract",
    output_object_path="intake_consult_drafts.payroll_headcount; model_input_json.sections.expenses[Payroll]",
    validation_subject_path="payroll_headcount_schedule.payroll_headcount_grid",
    notes="Payroll is not part of stage_ramp_contract and must run after the quarter grid so the headcount schedule supports the actual applied revenue state.",
  ),
  _process_sequence_row(
    "convergence",
    70,
    "issue_detection",
    "detect_post_intake_issues",
    required_lookup_tables=[_MAPPING_TABLE_NAME, _GPT_CONTRACT_TABLE_NAME],
    horizon_rule="scan_all_q1_to_q20",
    fail_fast_code="post_intake_sequence_issue_detection_mapping_missing",
    notes="Issue detection may only produce issues with direct mapping-table repair paths or hard gates.",
  ),
  _process_sequence_row(
    "convergence",
    80,
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
    timeout_seconds=180,
    max_attempts=10,
    fail_fast_code="post_intake_sequence_unified_convergence_contract_missing",
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
    notes="Contract repair uses a compact planner_retry context slice, not original-plus-retry legacy payloads.",
  ),
  _process_sequence_row(
    "cash_pass",
    100,
    "cash_minimum_debt_schedule",
    "apply_cash_pass_minimum_debt_schedule",
    required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME],
    horizon_rule="q1_to_q20_debt_schedule",
    fail_fast_code="post_intake_sequence_cash_debt_schedule_policy_missing",
    notes="Debt schedule semantics come from cash policy lookup and mapping-table financing levers.",
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
    notes="Cash GPT fills only needed cash gap rows; validation inspects full Q1-Q20.",
  ),
  _process_sequence_row(
    "cash_pass",
    120,
    "cash_pass_validation",
    "validate_cash_pass",
    required_lookup_tables=[_CASH_POLICY_TABLE_NAME, _MAPPING_TABLE_NAME],
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
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].cogs_target", "cogs_target", "ratio_2dp", min_value=0.05, max_value=0.90, is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["cogs_percent_of_revenue_target"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].cogs_max", "cogs_max", "ratio_2dp", min_value=0.20, max_value=0.95, is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["cogs_percent_of_revenue_max"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].marketing_max", "marketing_max", "ratio_2dp", min_value=0.00, max_value=0.40, is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["marketing_percent_of_revenue_max"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].rd_max", "rd_max", "ratio_2dp", min_value=0.00, max_value=0.50, is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["rd_percent_of_revenue_max"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].ga_max", "ga_max", "ratio_2dp", min_value=0.00, max_value=0.60, is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["g_and_a_percent_of_revenue_max"]),
  _gpt_contract_row("stage_ramp_contract", "quarter_ramp_grid", "quarter_ramp_grid[].lease_max", "lease_max", "ratio_2dp", min_value=0.00, max_value=0.50, is_array_item=True, parent_field_path="quarter_ramp_grid", normalization_kind="ratio_2dp", validation_kind="stage_ramp_numeric", allowed_aliases=["lease_percent_of_revenue_max"]),
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
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].role_category", "role_category", "string", is_array_item=True, parent_field_path="payroll_headcount_grid", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="Role category", prompt_required_instruction="Use a concise staffing category tied to an actual role family or staffing bundle. Do not invent rows outside the payroll_headcount_grid contract."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].oews_occ_title", "oews_occ_title", "string", is_array_item=True, parent_field_path="payroll_headcount_grid", validation_kind="payroll_oews_catalog_member", lookup_source="oews_role_catalog", prompt_label="OEWS occupation title", prompt_required_instruction="Must be one exact occ_title from oews_role_catalog.role_candidates. Do not invent titles. Python uses this exact OEWS title for wage lookup."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].starting_fte", "starting_fte", "number", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0, max_value=100000, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="Starting FTE", prompt_required_instruction="Used with ending_fte to calculate average_fte=(starting_fte+ending_fte)/2. If average FTE is below the guardrail, increase starting_fte/hires/ending_fte; ending_fte alone is not enough."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].hires", "hires", "number", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0, max_value=100000, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="FTE hires/additions"),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].ending_fte", "ending_fte", "number", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0, max_value=100000, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="Ending FTE", prompt_required_instruction="Must satisfy payroll_economic_guardrails by quarter using average_fte=(starting_fte+ending_fte)/2, not ending_fte alone. Keep role continuity after hiring starts."),
  _gpt_contract_row("payroll_headcount_schedule", "payroll_headcount_grid", "payroll_headcount_grid[].payroll_tax_benefits_pct", "payroll_tax_benefits_pct", "ratio_2dp", is_array_item=True, parent_field_path="payroll_headcount_grid", min_value=0.12, max_value=0.35, normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule", lookup_source="post_intake_headcount_policy_lookup", prompt_label="Payroll taxes and benefits percent", prompt_required_instruction="Must stay inside post_intake_headcount_policy_lookup min/max benefits burden. Do not use 0.00 for employees."),
]


_DEFAULT_GPT_CONTRACT_ROWS: List[Dict[str, Any]] = [
  _gpt_contract_row("maintenance_capex_percent", "root", "maintenance_capex_percent", "maintenance_capex_percent", "ratio_2dp", min_value=2.00, max_value=15.00, normalization_kind="ratio_2dp", validation_kind="maintenance_capex_percent_range", contract_phase="pre_forecast"),
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
    max_items=160,
    item_contract_grid_name="payroll_headcount_grid",
    horizon_rule="q1_to_q20_at_least_once",
    validation_kind="payroll_headcount_schedule",
    lookup_source="post_intake_headcount_policy_lookup",
    prompt_required_instruction="Provide active supporting-staff role/FTE rows for every forecast quarter Q1 through Q20. Select oews_occ_title from oews_role_catalog. Do not provide wages and do not include key people; Python injects key people from intake, resolves wages through OEWS, calculates payroll dollars, and stores intake_consult_drafts.payroll_headcount. If a role has no FTE in all 20 quarters, omit it. Once a role starts, keep it active through Q20. Every quarter must satisfy payroll_economic_guardrails using average_fte=(starting_fte+ending_fte)/2; matching only ending_fte is invalid.",
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
    max_chars=120000,
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
  _gpt_context_row("payroll_headcount_schedule", "oews_role_catalog", context_group="wage_role_lookup", source_kind="python_derived_from_oews", source_path="oews_state_wages via business_naics_6", include_phase="pre_convergence", max_items=160, notes="Python builds this role catalog before GPT chooses supporting-staff rows. GPT must select oews_occ_title values from role_candidates[].occ_title."),
  _gpt_context_row("payroll_headcount_schedule", "financial_context", context_group="financials", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "stage_ramp_contract", context_group="policy", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "payroll_headcount_policy", context_group="policy", source_kind="sql_lookup", source_path="post_intake_headcount_policy_lookup.default", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "payroll_economic_guardrails", context_group="policy", source_kind="python_derived_from_sql_lookup", source_path="post_intake_headcount_policy_lookup.default", include_phase="pre_convergence"),
  _gpt_context_row("payroll_headcount_schedule", "payroll_required_fte_grid", context_group="policy", source_kind="python_derived_from_sql_lookup", source_path="post_intake_headcount_policy_lookup.default + model_input_json revenue", include_phase="pre_convergence", max_items=20, notes="Python renders the exact Q1-Q20 supporting-staff average FTE floor before GPT chooses role rows. GPT must satisfy this grid; Python validates it after response."),
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
) -> Dict[str, Any]:
  """Deterministic lifecycle policy shared by ramp GPT, validation, and quarter-grid."""
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
          seed_source_paths_json LONGTEXT NULL,
          seed_formula_key VARCHAR(128) NOT NULL DEFAULT 'none',
          finmo_formula_key VARCHAR(128) NOT NULL DEFAULT 'none',
          validation_formula_key VARCHAR(128) NOT NULL DEFAULT 'semantic_presence_only',
          required_when_key VARCHAR(128) NOT NULL DEFAULT 'always',
          business_applicability_key VARCHAR(128) NOT NULL DEFAULT 'always',
          forecast_presence_rule_key VARCHAR(128) NOT NULL DEFAULT 'nonnegative_driver',
          zero_allowed_reason_key VARCHAR(128) NOT NULL DEFAULT 'not_applicable_or_table_optional',
          missing_seed_default_value DOUBLE NULL,
          minimum_live_value DOUBLE NULL,
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
        "ADD COLUMN seed_source_paths_json LONGTEXT NULL AFTER non_tolerable_issue_codes",
        "ADD COLUMN seed_formula_key VARCHAR(128) NOT NULL DEFAULT 'none' AFTER seed_source_paths_json",
        "ADD COLUMN finmo_formula_key VARCHAR(128) NOT NULL DEFAULT 'none' AFTER seed_formula_key",
        "ADD COLUMN validation_formula_key VARCHAR(128) NOT NULL DEFAULT 'semantic_presence_only' AFTER finmo_formula_key",
        "ADD COLUMN required_when_key VARCHAR(128) NOT NULL DEFAULT 'always' AFTER validation_formula_key",
        "ADD COLUMN business_applicability_key VARCHAR(128) NOT NULL DEFAULT 'always' AFTER required_when_key",
        "ADD COLUMN forecast_presence_rule_key VARCHAR(128) NOT NULL DEFAULT 'nonnegative_driver' AFTER business_applicability_key",
        "ADD COLUMN zero_allowed_reason_key VARCHAR(128) NOT NULL DEFAULT 'not_applicable_or_table_optional' AFTER forecast_presence_rule_key",
        "ADD COLUMN missing_seed_default_value DOUBLE NULL AFTER zero_allowed_reason_key",
        "ADD COLUMN minimum_live_value DOUBLE NULL AFTER missing_seed_default_value",
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
            WHEN lever_id = 'balance_sheet::Accounts Receivable Days' THEN 2.0
            WHEN lever_id = 'balance_sheet::Accounts Payable Days' THEN 2.0
            WHEN lever_id = 'balance_sheet::Inventory Days' THEN 15.0
            WHEN lever_id = 'balance_sheet::Prepaid Expenses (% of Revenue)' THEN 0.01
            WHEN lever_id = 'balance_sheet::Deferred Revenue (% of Revenue)' THEN 0.05
            WHEN lever_id = 'balance_sheet::Short Term Debt (% of LTD)' THEN 0.0
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
          formula_status = 'active'
        WHERE mapping_status = 'active'
        """
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
            missing_seed_default_value = 0.01,
            minimum_live_value = 0.01,
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
            missing_seed_default_value = 0.05,
            minimum_live_value = 0.01,
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
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
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
          contract_name VARCHAR(128) NOT NULL DEFAULT '',
          context_contract_name VARCHAR(128) NOT NULL DEFAULT '',
          context_include_phase VARCHAR(64) NOT NULL DEFAULT '',
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
          sequence_status VARCHAR(32) NOT NULL DEFAULT 'active',
          notes LONGTEXT NULL,
          created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
          updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
          UNIQUE KEY uniq_post_intake_process_sequence_step (step_key),
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
            contract_name,
            context_contract_name,
            context_include_phase,
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
            sequence_status,
            notes
          ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
          ON DUPLICATE KEY UPDATE
            phase = VALUES(phase),
            step_order = VALUES(step_order),
            handler_key = VALUES(handler_key),
            contract_name = VALUES(contract_name),
            context_contract_name = VALUES(context_contract_name),
            context_include_phase = VALUES(context_include_phase),
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
            sequence_status = VALUES(sequence_status),
            notes = VALUES(notes)
          """,
          (
            _clean_text(row.get("phase")).lower(),
            int(row.get("step_order") or 0),
            _clean_text(row.get("step_key")).lower(),
            _clean_text(row.get("handler_key")),
            _clean_text(row.get("contract_name")).lower(),
            _clean_text(row.get("context_contract_name")).lower(),
            _clean_text(row.get("context_include_phase")).lower(),
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
          seed_source_paths_json,
          seed_formula_key,
          finmo_formula_key,
          validation_formula_key,
          required_when_key,
          business_applicability_key,
          forecast_presence_rule_key,
          zero_allowed_reason_key,
          missing_seed_default_value,
          minimum_live_value,
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
      "seed_source_paths_json": _json_value(raw_row.get("seed_source_paths_json"), []),
      "seed_formula_key": _clean_text(raw_row.get("seed_formula_key")).lower(),
      "finmo_formula_key": _clean_text(raw_row.get("finmo_formula_key")).lower(),
      "validation_formula_key": _clean_text(raw_row.get("validation_formula_key")).lower(),
      "required_when_key": _clean_text(raw_row.get("required_when_key")).lower(),
      "business_applicability_key": _clean_text(raw_row.get("business_applicability_key")).lower(),
      "forecast_presence_rule_key": _clean_text(raw_row.get("forecast_presence_rule_key")).lower(),
      "zero_allowed_reason_key": _clean_text(raw_row.get("zero_allowed_reason_key")).lower(),
      "missing_seed_default_value": raw_row.get("missing_seed_default_value"),
      "minimum_live_value": raw_row.get("minimum_live_value"),
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
    cur = conn.cursor(dictionary=True)
    try:
      cur.execute(
        f"""
        SELECT
          phase,
          step_order,
          step_key,
          handler_key,
          contract_name,
          context_contract_name,
          context_include_phase,
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
    rows.append(
      {
        "phase": _clean_text(raw_row.get("phase")).lower(),
        "step_order": int(raw_row.get("step_order") or 0),
        "step_key": step_key,
        "handler_key": _clean_text(raw_row.get("handler_key")),
        "contract_name": _clean_text(raw_row.get("contract_name")).lower(),
        "context_contract_name": _clean_text(raw_row.get("context_contract_name")).lower(),
        "context_include_phase": _clean_text(raw_row.get("context_include_phase")).lower(),
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
          "seed_source_paths": copy.deepcopy(row.get("seed_source_paths_json") or []),
          "seed_formula_key": _clean_text(row.get("seed_formula_key")).lower(),
          "finmo_formula_key": _clean_text(row.get("finmo_formula_key")).lower(),
          "validation_formula_key": _clean_text(row.get("validation_formula_key")).lower(),
          "required_when_key": _clean_text(row.get("required_when_key")).lower(),
          "business_applicability_key": _clean_text(row.get("business_applicability_key")).lower(),
          "forecast_presence_rule_key": _clean_text(row.get("forecast_presence_rule_key")).lower(),
          "zero_allowed_reason_key": _clean_text(row.get("zero_allowed_reason_key")).lower(),
          "missing_seed_default_value": row.get("missing_seed_default_value"),
          "minimum_live_value": row.get("minimum_live_value"),
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

  def _field_schema(
    self,
    row: Dict[str, Any],
    *,
    field_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    array_item_schema_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
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
    min_value = row.get("min_value")
    max_value = row.get("max_value")
    if min_value is not None and schema_type in {"integer", "number"}:
      schema["minimum"] = int(min_value) if schema_type == "integer" else float(min_value)
    if max_value is not None and schema_type in {"integer", "number"}:
      schema["maximum"] = int(max_value) if schema_type == "integer" else float(max_value)
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
  ) -> Dict[str, Any]:
    return self.object_schema_for_grid(
      contract_name=contract_name,
      grid_name="root",
      field_schema_overrides=field_schema_overrides,
      array_item_schema_overrides=array_item_schema_overrides,
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
      "oews_role_catalog",
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
    errors.extend(self._lookup_table_errors(row))
    if errors:
      raise RuntimeError(
        f"{fail_code}: post_intake_process_sequence_lookup violation for step_key={row.get('step_key')}: "
        + "; ".join(errors)
      )
    return {
      **copy.deepcopy(row),
      "required_lookup_context": self._required_lookup_context(row),
      "sequence_enforced": True,
      "source_of_truth": f"sql.{_PROCESS_SEQUENCE_TABLE_NAME}",
      "lookup_function": "post_intake_assert_process_sequence_step",
    }

  def validation_errors(self) -> List[str]:
    errors: List[str] = []
    seen_step_keys: Set[str] = set()
    required_steps = {
      "post_intake_initialize_validation",
      "stage_ramp_contract",
      "payroll_headcount_schedule",
      "quarter_grid_generation",
      "issue_detection",
      "unified_convergence_decision",
      "unified_convergence_retry",
      "cash_minimum_debt_schedule",
      "cash_strategy_review",
      "cash_pass_validation",
      "final_hard_gates",
      "post_intake_finalize_validation",
    }
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
      if bool(row.get("required")) and not bool(row.get("enabled")):
        errors.append(f"{step_key} is required but disabled")
      if not row.get("required_lookup_tables"):
        errors.append(f"{step_key} missing required_lookup_tables")
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
) -> Dict[str, Any]:
  return post_intake_gpt_contract_lookup().openai_schema(
    contract_name=contract_name,
    field_schema_overrides=field_schema_overrides,
    array_item_schema_overrides=array_item_schema_overrides,
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
  return {
    "sequence_enforced": True,
    "source_of_truth": f"sql.{_PROCESS_SEQUENCE_TABLE_NAME}",
    "lookup_function": "post_intake_assert_required_process_sequence",
    "gateway_context_loaded": True,
    "active_step_count": len(rows),
    "active_steps": [
      _clean_text(row.get("step_key")).lower()
      for row in rows
      if _clean_text(row.get("step_key"))
    ],
    "step_table_dependencies": [
      {
        "step_key": _clean_text(context.get("step_key")).lower(),
        "phase": _clean_text(context.get("phase")).lower(),
        "handler_key": _clean_text(context.get("handler_key")),
        "required_lookup_tables": copy.deepcopy(context.get("required_lookup_tables") or []),
        "required_lookup_context": copy.deepcopy(context.get("required_lookup_context") or {}),
        "horizon_rule": _clean_text(context.get("horizon_rule")).lower(),
        "python_role": _clean_text(context.get("python_role")),
        "python_timing": _clean_text(context.get("python_timing")),
        "input_object_path": _clean_text(context.get("input_object_path")),
        "output_object_path": _clean_text(context.get("output_object_path")),
        "validation_subject_path": _clean_text(context.get("validation_subject_path")),
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
