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

logger = logging.getLogger(__name__)
from client_intake_and_finmo.post_intake_mapping import (
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_assert_required_process_sequence,
  post_intake_assert_process_sequence_step,
  post_intake_build_prompt_from_contract,
  post_intake_direct_target_metric_for_lever,
  post_intake_driver_target_lever_allowed_for_issue,
  post_intake_driver_target_mapping_entry,
  post_intake_driver_target_metric_ids,
  post_intake_issue_codes_for_phase,
  post_intake_process_sequence_step,
  post_intake_process_sequence_errors,
  post_intake_process_sequence_rows,
  post_intake_gpt_context_filter_payload,
  post_intake_gpt_context_rows,
  post_intake_gpt_context_request_char_budget,
  post_intake_gpt_contract_normalize_payload,
  post_intake_gpt_contract_openai_schema,
  post_intake_gpt_contract_payload_errors,
  post_intake_gpt_contract_prompt_field_spec,
  post_intake_normalize_lever_value,
  post_intake_precision_unit,
)
from client_intake_and_finmo.post_intake_foundation import (  # type: ignore
  bind_table_safe_runtime_dependencies,
)
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
  PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS,
  TRANSLATION_TEST_MODE_FAIL_FLAGS,
  post_intake_convergence_test_mode_enabled,
  post_intake_fail_fast_raise,
)

_CONVERGENCE_DEFAULT_QUARTER_COUNT = int(
  post_intake_contract_forecast_horizon_quarter_count(
    contract_name="unified_convergence_decision",
  )
  or 20
)
# Phase 6 Step 2 — reproducible-output seed for the unified_convergence_decision
# OpenAI call. Combined with temperature=0, the seed parameter bounds OpenAI's
# residual sampling variance (documented at
# https://platform.openai.com/docs/guides/text-generation/reproducible-outputs).
# Without it, the Phase 5.2 audit observed Sunny Glaze hitting different
# planner-status failures across consecutive runs of the same intake — a
# symptom of unseeded cross-call variance in the legacy gpt-5.1 planner.
# Stamped onto both the initial planner payload and its validation-retry
# payload so the retry's "fix the contract" prompt deterministically
# corresponds to the original prompt.
_UNIFIED_CONVERGENCE_DECISION_SEED = 1729
_CONVERGENCE_MAX_FOCUS_LEVERS = 12
_CONVERGENCE_MAX_FOCUS_LEVER_FAMILIES = 3
_CONVERGENCE_MAX_FOCUS_DRIVER_PATHS = 12
_CONVERGENCE_MAX_FOCUS_METRICS_PER_ISSUE = 2
_CONVERGENCE_PROMPT_METRIC_PACKET_LIMIT = 10
_CONVERGENCE_PROMPT_LEVER_PACKET_LIMIT = 12
_CONVERGENCE_MEANINGFUL_SCORE_DELTA_PCT = 5.0
_UNIFIED_ACCOUNTING_EQUATION_TOLERANCE = 1.0
_UNIFIED_CATASTROPHIC_LIQUIDITY_FLOOR = -250000.0
_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT = 1
_UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT = _CONVERGENCE_DEFAULT_QUARTER_COUNT
_UNIFIED_ALLOWED_TARGET_METRIC_KEYS: Tuple[str, ...] = tuple()
_UNIFIED_PRIMARY_TARGET_MIN_COUNT = 1
_UNIFIED_PRIMARY_TARGET_MAX_COUNT = 6
_UNIFIED_EXPLICIT_CAPITAL_ALLOCATION_LEVER_IDS: Tuple[str, ...] = tuple()
_CASH_PASS_OWNED_ISSUE_CODES = set(post_intake_issue_codes_for_phase("cash_pass"))
_REMAINING_HORIZON_ISSUE_CODES = set(
  post_intake_issue_codes_for_phase("convergence", targeting_allowed=True)
)
_CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS: Tuple[str, ...] = tuple()
_UNIFIED_CONVERGENCE_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts" / "unified_convergence"
_UNIFIED_CONVERGENCE_PROMPT_PATH = _UNIFIED_CONVERGENCE_PROMPTS_DIR / "reviewer.md"
_UNIFIED_ALLOWED_TARGET_METRIC_KEYS = tuple(post_intake_driver_target_metric_ids())
_PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS = set(PAYROLL_HEADCOUNT_TEST_MODE_FAIL_FLAGS)
_TRANSLATION_TEST_MODE_FAIL_FLAGS = set(TRANSLATION_TEST_MODE_FAIL_FLAGS)
_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT = 3
_POST_INTAKE_RUNTIME_PROBE_VERSION = "2026-05-01-table-backed-post-intake-v1"
_ISSUE_CODE_REGISTRY: Dict[str, Dict[str, Any]] = {
  code: {"title": code}
  for code in post_intake_issue_codes_for_phase("convergence")
}
for _hard_issue_code in ("accounting_integrity_failure", "structural_impossibility"):
  _ISSUE_CODE_REGISTRY.setdefault(_hard_issue_code, {"title": _hard_issue_code})


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    return float(value)
  except Exception:
    return None


def _post_intake_contract_prompt_spec(contract_name: str) -> Dict[str, Any]:
  return post_intake_gpt_contract_prompt_field_spec(contract_name)


def _normalize_post_intake_contract_payload(
  *,
  contract_name: str,
  payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  normalized = post_intake_gpt_contract_normalize_payload(
    contract_name=contract_name,
    payload=payload if isinstance(payload, dict) else {},
  )
  return normalized if isinstance(normalized, dict) else {}


def _post_intake_contract_payload_errors(
  *,
  contract_name: str,
  payload: Optional[Dict[str, Any]],
) -> List[str]:
  return list(
    post_intake_gpt_contract_payload_errors(
      contract_name=contract_name,
      payload=payload if isinstance(payload, dict) else {},
    )
    or []
  )


def _contract_forecast_quarter_count() -> int:
  count = int(
    post_intake_contract_forecast_horizon_quarter_count(
      contract_name="unified_convergence_decision",
    )
    or 0
  )
  if count <= 0:
    raise RuntimeError(
      "post_intake_contract_horizon_missing: "
      "post_intake_gpt_contract_lookup must define a positive convergence forecast horizon."
    )
  return count


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  if not isinstance(dependencies, dict):
    return
  bind_table_safe_runtime_dependencies(globals(), dependencies)


__all__ = [
  "_build_unified_horizon_snapshot",
  "_build_unified_hard_rule_assessment",
  "_planning_mode_prompt_text",
  "_build_planning_mode_context",
  "_truncate_summary_text",
  "_compact_summary_value",
  "_compact_summary_section",
  "_build_planning_context_summary_payload",
  "_persist_unified_convergence_state",
  "_parse_responses_json_dict",
  "_openai_strict_json_schema",
  "_compact_convergence_quarter_rows_for_state",
  "_build_current_cycle_convergence_packet",
  "_quarter_count_from_model_input",
  "_normalized_quarter_window",
  "_solved_lever_value_map",
  "_subset_lever_value_map",
  "_finmo_rows_for_quarters",
  "_window_values",
  "_baseline_window_summary",
  "_scoped_unified_allowed_lever_ids",
  "_lever_family_from_lever_id",
  "_sum_series",
  "_model_input_revenue_driver_quarter_states",
  "get_runtime_probe_payload",
  "_convergence_test_mode_enabled",
]


def _build_unified_horizon_snapshot(
  current_finmo_json: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
  metrics = _cash_review_quarter_metrics(current_finmo_json)
  ending_cash_series = [float(_safe_float(item.get("ending_cash")) or 0.0) for item in metrics]
  ebitda_series = [float(_safe_float(item.get("ebitda")) or 0.0) for item in metrics]
  net_income_series = [float(_safe_float(item.get("net_income")) or 0.0) for item in metrics]
  revenue_series = [float(_safe_float(item.get("revenue")) or 0.0) for item in metrics]
  negative_cash_quarters = [idx + 1 for idx, value in enumerate(ending_cash_series) if value < 0.0]
  catastrophic_liquidity_quarters = [
    idx + 1
    for idx, value in enumerate(ending_cash_series)
    if value < _UNIFIED_CATASTROPHIC_LIQUIDITY_FLOOR
  ]
  negative_net_income_quarters = [idx + 1 for idx, value in enumerate(net_income_series) if value < 0.0]
  negative_ebitda_quarters = [idx + 1 for idx, value in enumerate(ebitda_series) if value < 0.0]
  final_cash = ending_cash_series[-1] if ending_cash_series else 0.0
  horizon_snapshot = {
    "quarter_count": len(metrics),
    "negative_cash_quarters": negative_cash_quarters,
    "catastrophic_liquidity_quarters": catastrophic_liquidity_quarters,
    "negative_net_income_quarters": negative_net_income_quarters,
    "negative_ebitda_quarters": negative_ebitda_quarters,
    "minimum_ending_cash": min(ending_cash_series) if ending_cash_series else 0.0,
    "maximum_ending_cash": max(ending_cash_series) if ending_cash_series else 0.0,
    "final_ending_cash": final_cash,
    "final_revenue": revenue_series[-1] if revenue_series else 0.0,
    "final_ebitda": ebitda_series[-1] if ebitda_series else 0.0,
    "final_net_income": net_income_series[-1] if net_income_series else 0.0,
    "business_appears_ongoing_concern": not catastrophic_liquidity_quarters and final_cash > _UNIFIED_CATASTROPHIC_LIQUIDITY_FLOOR,
  }
  return horizon_snapshot, metrics

def _build_unified_hard_rule_assessment(
  *,
  controller_resolution_state: Optional[Dict[str, Any]],
  current_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  controller_state = controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  horizon_snapshot, metrics = _build_unified_horizon_snapshot(current_finmo_json)
  accounting_failure_quarters: List[int] = []
  catastrophic_liquidity_quarters = [
    int(_safe_float(item) or 0)
    for item in (horizon_snapshot.get("catastrophic_liquidity_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  for row in (metrics or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    accounting_gap = abs(float(_safe_float(row.get("accounting_equation_check")) or 0.0))
    if accounting_gap > _UNIFIED_ACCOUNTING_EQUATION_TOLERANCE:
      accounting_failure_quarters.append(quarter_index)

  remaining_hard_issue_codes: List[str] = []
  for item in _controller_state_issue_status_records(controller_state):
    if not isinstance(item, dict):
      continue
    snapshot = _controller_issue_completion_snapshot(
      item,
      current_finmo_json=current_finmo_json,
    )
    if not bool(snapshot.get("blocking")) or not bool(snapshot.get("hard_issue")):
      continue
    issue_code = str(snapshot.get("issue_code") or "").strip().lower()
    if _is_cash_pass_owned_issue_code(issue_code):
      continue
    if issue_code and issue_code not in remaining_hard_issue_codes:
      remaining_hard_issue_codes.append(issue_code)

  failed_rule_codes: List[str] = []
  if accounting_failure_quarters:
    failed_rule_codes.append("accounting_integrity_failure")
  for issue_code in remaining_hard_issue_codes:
    if issue_code not in failed_rule_codes:
      failed_rule_codes.append(issue_code)

  return {
    "contract_version": "unified_hard_rule_assessment_v1",
    "all_hard_rules_cleared": not failed_rule_codes,
    "remaining_hard_issue_count": len(remaining_hard_issue_codes),
    "remaining_hard_issue_codes": copy.deepcopy(remaining_hard_issue_codes),
    "accounting_integrity_passed": not accounting_failure_quarters,
    "accounting_failure_quarters": copy.deepcopy(accounting_failure_quarters),
    "cash_pass_owns_liquidity_detection": True,
    "catastrophic_liquidity_passed": True,
    "catastrophic_liquidity_quarters": copy.deepcopy(catastrophic_liquidity_quarters),
    "failed_rule_codes": copy.deepcopy(failed_rule_codes),
    "minimum_ending_cash": float(_safe_float(horizon_snapshot.get("minimum_ending_cash")) or 0.0),
    "final_ending_cash": float(_safe_float(horizon_snapshot.get("final_ending_cash")) or 0.0),
    "final_ebitda": float(_safe_float(horizon_snapshot.get("final_ebitda")) or 0.0),
  }


def _planning_mode_prompt_text(planning_mode: Any) -> str:
  mode = str(planning_mode or "").strip().lower()
  if not mode:
    return ""
  from client_intake_and_finmo.quarter_grid import planning_mode_text  # type: ignore
  try:
    return str(planning_mode_text(mode) or "").strip()
  except Exception:
    return ""

def _build_planning_mode_context(
  *,
  planning_mode: Any,
  planning_mode_reason: Any = "",
  prompt_file: Any = "",
) -> Dict[str, Any]:
  mode = str(planning_mode or "").strip().lower()
  return {
    "planning_mode": mode,
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "prompt_file": str(prompt_file or "").strip(),
    "mode_prompt_text": _planning_mode_prompt_text(mode),
    "carryforward_instruction": (
      "Continue this exact quarter-grid planning mode downstream. "
      "Do not invent a new posture or reinterpret the mode."
      if mode
      else ""
    ),
  }

def _truncate_summary_text(value: Any, *, max_len: int = 220) -> str:
  text = " ".join(str(value or "").strip().split())
  if not text:
    return ""
  if len(text) <= max_len:
    return text
  return text[: max_len - 3].rstrip() + "..."

def _compact_summary_value(value: Any) -> Any:
  if value is None:
    return None
  if isinstance(value, bool):
    return value
  if isinstance(value, (int, float)):
    return value
  if isinstance(value, str):
    return _truncate_summary_text(value)
  if isinstance(value, list):
    compact_items: List[Any] = []
    for item in value:
      compact_item = _compact_summary_value(item)
      if compact_item in (None, "", [], {}):
        continue
      if isinstance(compact_item, dict):
        continue
      compact_items.append(compact_item)
      if len(compact_items) >= 6:
        break
    return compact_items or None
  return None

def _compact_summary_section(
  payload: Optional[Dict[str, Any]],
  *,
  preferred_keys: List[str],
  max_fields: int = 10,
) -> Dict[str, Any]:
  source = payload if isinstance(payload, dict) else {}
  result: Dict[str, Any] = {}
  seen: set[str] = set()
  ordered_keys = list(preferred_keys) + sorted(source.keys())
  for key in ordered_keys:
    key_name = str(key or "").strip()
    if not key_name or key_name in seen or key_name not in source:
      continue
    compact_value = _compact_summary_value(source.get(key_name))
    if compact_value in (None, "", [], {}):
      continue
    result[key_name] = compact_value
    seen.add(key_name)
    if len(result) >= max_fields:
      break
  return result

def _build_planning_context_summary_payload(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  target_market_json: Optional[Dict[str, Any]],
  people_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  marketing_model_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]] = None,
  planning_mode: str = "",
  planning_mode_reason: str = "",
  prompt_file: str = "",
) -> Dict[str, Any]:
  business = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  market = target_market_json if isinstance(target_market_json, dict) else {}
  people = people_json if isinstance(people_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  marketing = marketing_model_json if isinstance(marketing_model_json, dict) else {}
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  people_list = [item for item in (people.get("people") or []) if isinstance(item, dict)]
  inferred_roles = [item for item in (people.get("inferred_roles") or []) if isinstance(item, dict)]
  products = [item for item in (ops.get("products") or []) if isinstance(item, dict)]
  services = [item for item in (ops.get("services") or []) if isinstance(item, dict)]
  return {
    "contract_version": "planning_context_summary_v1",
    "business_name": str(business.get("name") or business.get("business_name") or "").strip(),
    "planning_mode_context": _build_planning_mode_context(
      planning_mode=planning_mode,
      planning_mode_reason=planning_mode_reason,
      prompt_file=prompt_file,
    ),
    "selected_cash_strategy": str(financials.get("cash_strategy") or "").strip(),
    "intake_non_binding_policy": {
      "intake_numbers_are_binding": False,
      "realism_overrides_intake": True,
      "stub_values_are_intake_snapshot_only": True,
      "stub_values_must_not_drive_forecast_decisions": True,
    },
    "business_profile": _compact_summary_section(
      business,
      preferred_keys=[
        "business_name",
        "name",
        "start_date",
        "address",
        "address_city",
        "address_state",
        "address_country",
      ],
      max_fields=7,
    ),
    "operating_profile": {
      **_compact_summary_section(
        ops,
        preferred_keys=[
          "business_type",
          "business_naics_6",
          "unit_name",
          "unit_description",
          "unit_cadence",
          "unit_price",
          "capacity_driver",
          "units_per_period_capacity",
          "units_per_week_capacity",
          "operating_periods_per_year",
          "utilization_rate",
          "shipping_method",
          "sales_modality",
          "geographic_scope",
          "competitive_advantage",
        ],
        max_fields=12,
      ),
      "product_count": len(products),
      "service_count": len(services),
    },
    "market_profile": _compact_summary_section(
      market,
      preferred_keys=[
        "target_market_summary",
        "customer_description",
        "primary_customer",
        "target_customer",
        "pricing_position",
        "sales_cycle",
        "geographic_focus",
      ],
      max_fields=10,
    ),
    "people_profile": {
      **_compact_summary_section(
        people,
        preferred_keys=[
          "key_people_summary",
          "management_summary",
          "staffing_strategy",
          "org_design_summary",
        ],
        max_fields=8,
      ),
      "people_count": len(people_list),
      "inferred_role_count": len(inferred_roles),
    },
    "financial_profile": _compact_summary_section(
      financials,
      preferred_keys=[
        "cash_strategy",
        "funding_strategy",
        "owner_draw_strategy",
        "owner_distributions",
        "debt_strategy",
        "equity_strategy",
        "capital_intensity",
      ],
      max_fields=10,
    ),
    "year1_anchor_summary": _compact_summary_section(
      year1,
      preferred_keys=[
        "revenue",
        "gross_profit",
        "ebitda",
        "net_income",
        "ending_cash",
        "operating_cash_flow",
        "capital_expenditures",
      ],
      max_fields=10,
    ),
    "marketing_profile": _compact_summary_section(
      marketing,
      preferred_keys=[
        "summary",
        "primary_channel",
        "channel_mix",
        "sales_motion",
        "go_to_market_motion",
      ],
      max_fields=8,
    ),
  }

def _persist_unified_convergence_state(
  *,
  conn,
  draft_id: str,
  stage: str,
  status: str,
  planning_context_summary_json: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  resolution_summary: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  grid_application_summary: Optional[Dict[str, Any]],
  realism_memo_before_resolution: Optional[Dict[str, Any]],
  realism_memo_json: Optional[Dict[str, Any]],
  unified_convergence_context: Optional[Dict[str, Any]],
  unified_convergence_decision: Optional[Dict[str, Any]],
  unified_convergence_plan: Optional[Dict[str, Any]],
  unified_convergence_result: Optional[Dict[str, Any]],
  unified_convergence_iterations: Optional[List[Dict[str, Any]]],
  unified_convergence_cycle_count: Optional[int],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  cash_strategy_effect_summary: Optional[Dict[str, Any]] = None,
  controller_retry_heartbeat: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  return _persist_post_intake_stage_state(
    conn=conn,
    draft_id=str(draft_id).strip(),
    stage=stage,
    status=status,
    planning_context_summary_json=copy.deepcopy(planning_context_summary_json or {}),
    controller_resolution_state=copy.deepcopy(controller_resolution_state or {}),
    resolution_summary=copy.deepcopy(resolution_summary or {}),
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    prompt_file=prompt_file,
    grid_application_summary=copy.deepcopy(grid_application_summary or {}),
    realism_memo_before_resolution=copy.deepcopy(realism_memo_before_resolution or {}),
    realism_memo_json=copy.deepcopy(realism_memo_json or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    finmo_json=copy.deepcopy(finmo_json or {}),
    unified_convergence_context=copy.deepcopy(unified_convergence_context or {}),
    unified_convergence_decision=copy.deepcopy(unified_convergence_decision or {}),
    unified_convergence_plan=copy.deepcopy(unified_convergence_plan or {}),
    unified_convergence_result=copy.deepcopy(unified_convergence_result or {}),
    unified_convergence_iterations=copy.deepcopy(unified_convergence_iterations or []),
    unified_convergence_cycle_count=unified_convergence_cycle_count,
    cash_strategy_review_context=copy.deepcopy(cash_strategy_review_context or {}),
    cash_strategy_review_decision=copy.deepcopy(cash_strategy_review_decision or {}),
    cash_strategy_second_pass_plan=copy.deepcopy(cash_strategy_second_pass_plan or {}),
    cash_strategy_second_pass_result=copy.deepcopy(cash_strategy_second_pass_result or {}),
    cash_strategy_effect_summary=copy.deepcopy(cash_strategy_effect_summary or {}),
    controller_retry_heartbeat=copy.deepcopy(controller_retry_heartbeat or {}),
    explicit_numeric_feedback_candidates=[
      ("unified_convergence_result", unified_convergence_result),
      ("cash_strategy_second_pass_result", cash_strategy_second_pass_result),
    ],
  )

def _parse_responses_json_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  output = data.get("output") or []
  for item in output:
    for part in item.get("content", []) or []:
      if part.get("type") == "output_json" and isinstance(part.get("json"), dict):
        return part["json"]
  try:
    parsed = json.loads(_parse_responses_text(data))
  except Exception:
    return None
  return parsed if isinstance(parsed, dict) else None

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

def _compact_convergence_quarter_rows_for_state(rows: Any) -> List[Dict[str, Any]]:
  compact_rows: List[Dict[str, Any]] = []
  for row in (rows or []):
    if not isinstance(row, dict):
      continue
    try:
      quarter_index = int(float(row.get("quarter_index") or 0))
    except Exception:
      quarter_index = 0
    if quarter_index < 1:
      continue
    compact_rows.append(
      {
        "quarter_index": quarter_index,
        "year": copy.deepcopy(row.get("year")),
        "quarter": copy.deepcopy(row.get("quarter")),
        "revenue": _safe_float(row.get("revenue")),
        "gross_profit": _safe_float(row.get("gross_profit")),
        "ebitda": _safe_float(row.get("ebitda")),
        "net_income": _safe_float(row.get("net_income")),
        "ending_cash": _safe_float(row.get("ending_cash")),
        "operating_cash_flow": _safe_float(row.get("operating_cash_flow")),
        "investing_cash_flow": _safe_float(row.get("investing_cash_flow")),
        "financing_cash_flow": _safe_float(row.get("financing_cash_flow")),
        "current_assets": _safe_float(row.get("current_assets")),
        "ppe": _safe_float(row.get("ppe")),
        "current_liabilities": _safe_float(row.get("current_liabilities")),
        "total_liabilities": _safe_float(row.get("total_liabilities")),
        "total_equity": _safe_float(row.get("total_equity")),
        "accounting_equation_check": _safe_float(row.get("accounting_equation_check")),
      }
    )
  return compact_rows

def _build_current_cycle_convergence_packet(
  *,
  stage: str,
  status: str,
  planning_mode: Optional[str],
  planning_mode_reason: Optional[str],
  planning_context_summary: Optional[Dict[str, Any]],
  unified_convergence_context: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]],
  controller_retry_context: Optional[Dict[str, Any]] = None,
  prior_numeric_feedback: Optional[Dict[str, Any]] = None,
  unified_convergence_decision: Optional[Dict[str, Any]] = None,
  unified_convergence_plan: Optional[Dict[str, Any]] = None,
  unified_convergence_result: Optional[Dict[str, Any]] = None,
  unified_convergence_cycle_count: Optional[int] = None,
  cycle_debug: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  planning_summary = planning_context_summary if isinstance(planning_context_summary, dict) else {}
  convergence_context = (
    unified_convergence_context if isinstance(unified_convergence_context, dict) else {}
  )
  controller_state = (
    controller_resolution_state if isinstance(controller_resolution_state, dict) else {}
  )
  retry_context = (
    controller_retry_context if isinstance(controller_retry_context, dict) else {}
  )
  numeric_feedback = (
    prior_numeric_feedback if isinstance(prior_numeric_feedback, dict) else {}
  )
  cycle_debug_payload = cycle_debug if isinstance(cycle_debug, dict) else {}
  lever_catalog = (
    convergence_context.get("writable_lever_catalog")
    if isinstance(convergence_context.get("writable_lever_catalog"), dict)
    else {}
  )
  lever_ids = [
    str(item or "").strip()
    for item in (lever_catalog.get("lever_ids") or [])
    if str(item or "").strip()
  ]
  current_finmo_json = (
    convergence_context.get("current_finmo_json")
    if isinstance(convergence_context.get("current_finmo_json"), dict)
    else {}
  )
  current_finmo_rows = (
    current_finmo_json.get("quarter_rows")
    if isinstance(current_finmo_json.get("quarter_rows"), list)
    else convergence_context.get("current_finmo_quarter_rows")
    if isinstance(convergence_context.get("current_finmo_quarter_rows"), list)
    else []
  )
  numeric_guidance_packet = _build_unified_numeric_guidance_packet(
    controller_resolution_state=controller_state,
    controller_retry_context=retry_context,
    unified_convergence_context=convergence_context,
    quarter_count=_contract_forecast_quarter_count(),
  )
  repair_aware_issue_packets = _repair_aware_issue_packets(
    issue_packets=copy.deepcopy(convergence_context.get("deterministic_issue_packets") or []),
    numeric_guidance_packet=copy.deepcopy(numeric_guidance_packet),
  )
  convergence_scorecard = _build_convergence_scorecard(
    controller_resolution_state=controller_state,
    controller_retry_context=retry_context,
  )
  hard_rule_state = (
    convergence_context.get("hard_rule_assessment")
    if isinstance(convergence_context.get("hard_rule_assessment"), dict)
    else {}
  )
  return {
    "contract_version": "convergence_state_v1",
    "owner": "unified_convergence",
    "stage": str(stage or "").strip() or None,
    "status": str(status or "").strip() or None,
    "current_cycle": (
      int(_safe_float(unified_convergence_cycle_count))
      if unified_convergence_cycle_count is not None
      else None
    ),
    "convergence_test_mode": _convergence_test_mode_enabled(),
    "convergence_engine_contract": _unified_convergence_engine_contract_payload(),
    "business_context": {
      "business_name": str(
        planning_summary.get("business_name")
        or convergence_context.get("business_name")
        or ""
      ).strip() or None,
      "business_type": str(
        planning_summary.get("business_type")
        or planning_summary.get("industry")
        or ""
      ).strip() or None,
      "business_model": str(
        planning_summary.get("business_model")
        or planning_summary.get("business_model_summary")
        or ""
      ).strip() or None,
      "planning_mode": str(planning_mode or "").strip() or None,
      "planning_mode_reason": str(planning_mode_reason or "").strip() or None,
      "selected_cash_strategy": str(
        convergence_context.get("selected_cash_strategy") or ""
      ).strip() or None,
    },
    "issue_state": {
      "controller_status": str(controller_state.get("status") or "").strip() or None,
      "detected_issue_count": int(_safe_float(controller_state.get("detected_issue_count")) or 0),
      "remaining_issue_count": int(_safe_float(controller_state.get("remaining_issue_count")) or 0),
      "resolved_issue_count": int(_safe_float(controller_state.get("resolved_issue_count")) or 0),
      "tolerated_issue_count": int(_safe_float(controller_state.get("tolerated_issue_count")) or 0),
      "iteration_pending_issue_count": int(
        _safe_float(controller_state.get("iteration_pending_issue_count")) or 0
      ),
      "overall_completion_score_pct": int(
        _safe_float(controller_state.get("overall_completion_score_pct")) or 0
      ),
      "overall_completion_grade": str(
        controller_state.get("overall_completion_grade") or ""
      ).strip() or "D",
      "lowest_quarter_score_pct": int(
        _safe_float(controller_state.get("lowest_quarter_score_pct")) or 0
      ),
      "failing_quarters": copy.deepcopy(controller_state.get("failing_quarters") or []),
      "open_issue_codes": [
        str(item.get("issue_code") or "").strip()
        for item in (controller_state.get("remaining_issues") or [])
        if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
      ],
      "resolved_issue_codes": [
        str(item.get("issue_code") or "").strip()
        for item in (controller_state.get("resolved_issues") or [])
        if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
      ],
      "tolerated_issue_codes": [
        str(item.get("issue_code") or "").strip()
        for item in (controller_state.get("tolerated_issues") or [])
        if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
      ],
      "current_issue_summaries": copy.deepcopy(
        convergence_context.get("current_issue_summaries") or {}
      ),
      "deterministic_issue_packets": copy.deepcopy(repair_aware_issue_packets),
    },
    "hard_rule_state": copy.deepcopy(hard_rule_state),
    "retry_state": {
      "progress_status": str(retry_context.get("progress_status") or "").strip() or None,
      "failed_quarters": copy.deepcopy(retry_context.get("failed_quarters") or []),
      "failed_metrics": copy.deepcopy(retry_context.get("failed_metrics") or []),
      "required_open_issue_codes": copy.deepcopy(
        retry_context.get("required_open_issue_codes") or []
      ),
      "required_primary_metric_candidates": copy.deepcopy(
        retry_context.get("required_primary_metric_candidates") or []
      ),
      "required_issue_lever_ids": copy.deepcopy(
        retry_context.get("required_issue_lever_ids") or []
      ),
      "last_failure_reason": str(
        retry_context.get("last_failure_reason") or ""
      ).strip() or None,
      "minimum_primary_metric_coverage_count": int(
        _safe_float(retry_context.get("minimum_primary_metric_coverage_count")) or 0
      ) or None,
    },
    "numeric_state": {
      "solver_invoked": bool(numeric_feedback.get("solver_invoked")),
      "solver_execution_state": str(
        numeric_feedback.get("solver_execution_state") or ""
      ).strip() or None,
      "execution_state": str(
        numeric_feedback.get("execution_state") or ""
      ).strip() or None,
      "target_metric_names": copy.deepcopy(numeric_feedback.get("target_metric_names") or []),
      "targeted_quarters": copy.deepcopy(numeric_feedback.get("targeted_quarters") or []),
      "quarters_with_all_targets_within_tolerance": int(
        _safe_float(numeric_feedback.get("quarters_with_all_targets_within_tolerance")) or 0
      ),
      "quarters_with_target_misses": int(
        _safe_float(numeric_feedback.get("quarters_with_target_misses")) or 0
      ),
      "quarter_fit_summary": copy.deepcopy(numeric_feedback.get("quarter_fit_summary") or []),
    },
    "convergence_scorecard": copy.deepcopy(convergence_scorecard),
    "deterministic_numeric_guidance": copy.deepcopy(numeric_guidance_packet),
    "quarter_snapshot": _compact_convergence_quarter_rows_for_state(
      copy.deepcopy(current_finmo_rows or [])
    ),
    "lever_scope": {
      "lever_count": len(lever_ids),
      "lever_ids": copy.deepcopy(lever_ids),
    },
    "context_modules": copy.deepcopy(convergence_context.get("context_modules") or {}),
    "decision_summary": _compact_unified_convergence_decision_for_storage(
      copy.deepcopy(unified_convergence_decision or {})
    ),
    "plan_summary": _compact_unified_convergence_plan_for_storage(
      copy.deepcopy(unified_convergence_plan or {})
    ),
    "result_summary": _compact_unified_convergence_result_for_storage(
      copy.deepcopy(unified_convergence_result or {})
    ),
    "cycle_debug_summary": copy.deepcopy(
      cycle_debug_payload.get("issue_alignment_debug_summary") or {}
    ),
    "cycle_issue_debug": copy.deepcopy(
      cycle_debug_payload.get("issue_alignment_debug") or []
    ),
  }


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


def _quarter_count_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> int:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  periods = [item for item in (model_input.get("periods") or []) if isinstance(item, dict)]
  if not periods:
    return 20
  live_quarters = [
    int(_safe_float(item.get("quarter")) or 0)
    for item in periods
    if (
      not bool(item.get("is_stub"))
      and int(_safe_float(item.get("quarter")) or 0) >= 1
    )
  ]
  if live_quarters:
    return max(live_quarters)
  non_stub_count = len([item for item in periods if not bool(item.get("is_stub"))])
  if non_stub_count > 0:
    return max(1, non_stub_count)
  return max(1, len(periods))

def _normalized_quarter_window(start_q: Any, end_q: Any, *, quarter_count: int) -> Tuple[int, int]:
  start = int(_safe_float(start_q) or 1)
  end = int(_safe_float(end_q) or start)
  start = max(1, min(int(quarter_count or 1), start))
  end = max(start, min(int(quarter_count or 1), end))
  return start, end

def _solved_lever_value_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, List[float]]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  lever_map: Dict[str, List[float]] = {}
  horizon_count = _contract_forecast_quarter_count()

  def _live_values(row_values: Any) -> List[float]:
    values = [float(_safe_float(value) or 0.0) for value in (row_values or [])]
    if len(values) >= horizon_count + 1:
      return values[1:horizon_count + 1]
    return values[:horizon_count]

  for row in [item for item in (sections.get("revenue") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = _live_values(row.get("values") or [])
  for section_name in ("expenses", "balance_sheet"):
    for row in [item for item in (sections.get(section_name) or []) if isinstance(item, dict)]:
      lever_id = str(row.get("lever_id") or "").strip()
      if lever_id:
        lever_map[lever_id] = _live_values(row.get("values") or [])
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in [item for item in (schedules.get("rows") or []) if isinstance(item, dict)]:
    lever_id = str(row.get("lever_id") or "").strip()
    if lever_id:
      lever_map[lever_id] = _live_values(row.get("values") or [])
  return lever_map


def _subset_lever_value_map(
  lever_value_map: Optional[Dict[str, List[float]]],
  lever_ids: Optional[List[str]],
  quarter_indexes: Optional[List[int]] = None,
) -> Dict[str, List[float]]:
  lever_map = lever_value_map if isinstance(lever_value_map, dict) else {}
  lever_id_set = {
    str(item).strip()
    for item in (lever_ids or [])
    if str(item).strip()
  }
  quarter_list = [
    int(_safe_float(item) or 0)
    for item in (quarter_indexes or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  out: Dict[str, List[float]] = {}
  for lever_id, values in lever_map.items():
    if lever_id_set and lever_id not in lever_id_set:
      continue
    normalized_values = [float(_safe_float(value) or 0.0) for value in (values or [])]
    if quarter_list:
      out[lever_id] = [
        float(normalized_values[quarter_index - 1] if 0 <= quarter_index - 1 < len(normalized_values) else 0.0)
        for quarter_index in quarter_list
      ]
    else:
      out[lever_id] = normalized_values[:_contract_forecast_quarter_count()]
  return out

def _finmo_rows_for_quarters(
  finmo_json: Optional[Dict[str, Any]],
  quarter_indexes: Optional[List[int]],
) -> List[Dict[str, Any]]:
  quarter_set = {
    int(_safe_float(item) or 0)
    for item in (quarter_indexes or [])
    if int(_safe_float(item) or 0) >= 1
  }
  rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or [])
    if isinstance(row, dict)
  ]
  if not quarter_set:
    return copy.deepcopy(rows)
  return [
    copy.deepcopy(row)
    for row in rows
    if int(_safe_float(row.get("quarter_index")) or 0) in quarter_set
  ]

def _window_values(values: List[float], *, start_q: int, end_q: int) -> List[float]:
  if not values:
    return []
  start_idx = max(0, int(start_q) - 1)
  end_idx = max(start_idx, int(end_q) - 1)
  return [float(_safe_float(item) or 0.0) for item in values[start_idx:end_idx + 1]]

def _baseline_window_summary(values: List[float], *, start_q: int, end_q: int) -> Dict[str, Any]:
  window = _window_values(values, start_q=start_q, end_q=end_q)
  if not window:
    return {
      "quarter_start": start_q,
      "quarter_end": end_q,
      "value_start": 0.0,
      "value_end": 0.0,
      "value_min": 0.0,
      "value_max": 0.0,
    }
  return {
    "quarter_start": start_q,
    "quarter_end": end_q,
    "value_start": window[0],
    "value_end": window[-1],
    "value_min": min(window),
    "value_max": max(window),
  }

def _scoped_unified_allowed_lever_ids(
  *,
  fallback_allowed_lever_ids: Optional[List[str]],
  deterministic_numeric_guidance: Optional[Dict[str, Any]],
) -> List[str]:
  fallback_ids = [
    str(item).strip()
    for item in (fallback_allowed_lever_ids or [])
    if str(item).strip()
  ]
  guidance = deterministic_numeric_guidance if isinstance(deterministic_numeric_guidance, dict) else {}
  issue_packets = [
    item
    for item in (guidance.get("issue_repair_packets") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  focus_issue_code_set = {
    str(item.get("issue_code") or "").strip().lower()
    for item in issue_packets
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  }
  scoped_ids: List[str] = []
  for issue_packet in issue_packets:
    for lever_id in _issue_packet_mapped_driver_lever_ids(issue_packet):
      lever = str(lever_id).strip()
      if lever and lever in fallback_ids and lever not in scoped_ids:
        scoped_ids.append(lever)
  if issue_packets:
    return scoped_ids
  for scaffold in (guidance.get("lever_band_scaffold") or []):
    if not isinstance(scaffold, dict):
      continue
    lever = str(scaffold.get("lever_id") or "").strip()
    if not lever or lever not in fallback_ids or lever in scoped_ids:
      continue
    covered_issue_codes = {
      str(item).strip().lower()
      for item in (scaffold.get("covered_issue_codes") or [])
      if str(item).strip()
    }
    if focus_issue_code_set and covered_issue_codes and covered_issue_codes.isdisjoint(focus_issue_code_set):
      continue
    scoped_ids.append(lever)
  return fallback_ids


def _lever_family_from_lever_id(lever_id: Any) -> str:
  raw = str(lever_id or "").strip()
  if not raw:
    return ""
  return str(raw.split("::", 1)[0] or "").strip().lower()


def _sum_series(values: Any) -> float:
  if not isinstance(values, list):
    return 0.0
  return float(sum(float(_safe_float(item) or 0.0) for item in values))

def _model_input_revenue_driver_quarter_states(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
  revenue_rows = [row for row in (sections.get("revenue") or []) if isinstance(row, dict)]
  grouped: Dict[str, Dict[str, List[Any]]] = {}
  max_live_count = 0
  for row in revenue_rows:
    driver = str(row.get("driver") or row.get("label") or "").strip().lower()
    if driver not in {"capacity", "unit price", "utilization"}:
      continue
    slot_key = str(row.get("revenue_slot_key") or row.get("lever_id") or "").strip()
    if not slot_key:
      continue
    values = list(row.get("values") or [])
    max_live_count = max(max_live_count, max(0, len(values) - 1))
    grouped.setdefault(slot_key, {})[driver] = values
  states: Dict[int, Dict[str, Any]] = {}
  for quarter_index in range(1, max_live_count + 1):
    total_capacity = 0.0
    total_realized_units = 0.0
    populated_slots = 0
    for driver_rows in grouped.values():
      capacity_values = driver_rows.get("capacity") or []
      utilization_values = driver_rows.get("utilization") or []
      capacity = max(0.0, float(_safe_float(capacity_values[quarter_index] if quarter_index < len(capacity_values) else None) or 0.0))
      utilization = max(0.0, float(_safe_float(utilization_values[quarter_index] if quarter_index < len(utilization_values) else None) or 0.0))
      if capacity <= 0.0 and utilization <= 0.0:
        continue
      populated_slots += 1
      total_capacity += capacity
      total_realized_units += capacity * utilization
    aggregate_utilization = (total_realized_units / total_capacity) if total_capacity > 0.0 else 0.0
    states[quarter_index] = {
      "quarter_index": quarter_index,
      "structural_capacity": total_capacity,
      "aggregate_utilization": aggregate_utilization,
      "populated_revenue_slots": populated_slots,
    }
  previous: Optional[Dict[str, Any]] = None
  for quarter_index in sorted(states):
    state = states[quarter_index]
    if previous:
      previous_capacity = float(previous.get("structural_capacity") or 0.0)
      current_capacity = float(state.get("structural_capacity") or 0.0)
      previous_utilization = float(previous.get("aggregate_utilization") or 0.0)
      current_utilization = float(state.get("aggregate_utilization") or 0.0)
      state["capacity_growth_qoq"] = (
        ((current_capacity - previous_capacity) / previous_capacity)
        if previous_capacity > 0.0
        else None
      )
      state["utilization_change_qoq"] = current_utilization - previous_utilization
      state["previous_structural_capacity"] = previous_capacity
      state["previous_aggregate_utilization"] = previous_utilization
    previous = state
  return states


def get_runtime_probe_payload() -> Dict[str, Any]:
  try:
    process_sequence_assertion = post_intake_assert_required_process_sequence()
    process_sequence_errors = []
  except Exception as exc:
    process_sequence_assertion = {}
    process_sequence_errors = [f"post_intake_process_sequence_lookup_unavailable: {exc}"]
  try:
    process_sequence_steps = [
      str((row or {}).get("step_key") or "").strip()
      for row in post_intake_process_sequence_rows(active_only=True)
      if str((row or {}).get("step_key") or "").strip()
    ]
  except Exception:
    process_sequence_steps = []
  return {
    "status": "ok",
    "runtime_probe_version": _POST_INTAKE_RUNTIME_PROBE_VERSION,
    "architecture": "unified_convergence_plus_cash_pass",
    "mapping_source": "sql.post_intak_mapping_lookup",
    "process_sequence_source": "sql.post_intake_process_sequence_lookup",
    "process_sequence_valid": not bool(process_sequence_errors),
    "process_sequence_errors": process_sequence_errors,
    "process_sequence_steps": process_sequence_steps,
    "process_sequence_gateway_context_loaded": bool(
      process_sequence_assertion.get("gateway_context_loaded")
    ),
    "process_sequence_step_table_dependencies": copy.deepcopy(
      process_sequence_assertion.get("step_table_dependencies") or []
    ),
    "unified_convergence": {
      "max_cycles": int(_UNIFIED_CONVERGENCE_MAX_CYCLES),
      "cycle_timeout_seconds": float(_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS),
      "active_issue_limit": int(_UNIFIED_CONVERGENCE_ACTIVE_ISSUE_LIMIT),
      "active_quarter_limit": int(_UNIFIED_CONVERGENCE_ACTIVE_QUARTER_LIMIT),
      "non_productive_cycle_limit": int(_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT),
    },
    "issue_codes": sorted(_ISSUE_CODE_REGISTRY.keys()),
    "cash_pass_owned_issue_codes": sorted(_CASH_PASS_OWNED_ISSUE_CODES),
    "remaining_horizon_issue_codes": sorted(_REMAINING_HORIZON_ISSUE_CODES),
  }

def _convergence_test_mode_enabled() -> bool:
  return post_intake_convergence_test_mode_enabled()


