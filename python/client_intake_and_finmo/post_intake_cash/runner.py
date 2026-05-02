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

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_cash_debt_schedule_policy,
  post_intake_cash_policy_errors,
  post_intake_cash_policy_phase_sequence,
  post_intake_build_prompt_from_contract,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_driver_target_lever_ids_for_cash_roles,
  post_intake_driver_target_lever_ids_for_target_drivers,
  post_intake_driver_target_single_lever_id_for_target_driver,
  post_intake_gpt_context_request_char_budget,
  post_intake_issue_codes_for_phase,
  post_intake_issue_has_phase,
)
from client_intake_and_finmo.post_intake_cash.common import assert_cash_envelope_lifecycle  # type: ignore
from client_intake_and_finmo.post_intake_cash.planning_envelope import build_cash_planning_envelope  # type: ignore
from client_intake_and_finmo.post_intake_cash.validation_envelope import build_cash_validation_envelope  # type: ignore
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
  CASH_STRATEGY_TEST_MODE_FAIL_FLAGS,
)
from client_intake_and_finmo.post_intake_foundation import bind_table_safe_runtime_dependencies  # type: ignore

_CASH_STRATEGY_REVIEW_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "cash_strategy_review" / "reviewer.md"
_CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID = post_intake_driver_target_single_lever_id_for_target_driver("debt_issuance")
_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID = post_intake_driver_target_single_lever_id_for_target_driver("debt_repayment")
_CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID = post_intake_driver_target_single_lever_id_for_target_driver(
  "short_term_debt_percent_of_ltd"
)
_CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID = post_intake_driver_target_single_lever_id_for_target_driver("owners_capital")
_CASH_STRATEGY_OTHER_EQUITY_LEVER_ID = post_intake_driver_target_single_lever_id_for_target_driver("other_equity")
_CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID = post_intake_driver_target_single_lever_id_for_target_driver("distributions")
_CASH_STRATEGY_ALLOWED_LEVER_IDS: Tuple[str, ...] = tuple(
  post_intake_driver_target_lever_ids_for_cash_roles(
    {
      "distribution",
      "debt_paydown",
      "debt_raise",
      "equity_raise",
      "owner_equity_raise",
      "external_equity_raise",
    }
  )
)
_CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS: Tuple[str, ...] = tuple(
  post_intake_driver_target_lever_ids_for_cash_roles(
    {
      "debt_raise",
      "equity_raise",
      "owner_equity_raise",
      "external_equity_raise",
    }
  )
)
_CASH_STRATEGY_BUFFER_MONTHS = 1.0
_CASH_STRATEGY_MONTHS_PER_QUARTER = 3.0
_CASH_STRATEGY_PREFERRED_DEBT_RATIO = 0.40
_CASH_STRATEGY_PREFERRED_EQUITY_RATIO = 0.60
_CASH_STRATEGY_TEST_MODE_FAIL_FLAGS: Set[str] = set(CASH_STRATEGY_TEST_MODE_FAIL_FLAGS)
_UNIFIED_ALLOWED_TARGET_METRIC_KEYS: Tuple[str, ...] = tuple()
_UNIFIED_PRIMARY_TARGET_MIN_COUNT = 1
_UNIFIED_PRIMARY_TARGET_MAX_COUNT = 6
_IMPLEMENTED_CASH_PASS_ISSUE_CODES = {
  "working_capital_mismatch",
  "liquidity_failure",
  "funding_structure_mismatch",
}


def _cash_contract_horizon_quarters() -> int:
  count = int(
    post_intake_contract_forecast_horizon_quarter_count(
      contract_name="cash_strategy_review",
    )
    or 0
  )
  if count <= 0:
    raise RuntimeError(
      "cash_strategy_contract_horizon_missing: "
      "post_intake_gpt_contract_lookup must define cash_strategy_review forecast horizon."
    )
  return count


def post_intake_cash_issue_alignment_errors() -> List[str]:
  table_codes = {
    str(item or "").strip().lower()
    for item in post_intake_issue_codes_for_phase("cash_pass")
    if str(item or "").strip()
  }
  errors: List[str] = []
  missing = sorted(table_codes - _IMPLEMENTED_CASH_PASS_ISSUE_CODES)
  stale = sorted(_IMPLEMENTED_CASH_PASS_ISSUE_CODES - table_codes)
  if missing:
    errors.append(
      "post_intake_cash_issue_handler_missing_for_table_issue: "
      + json.dumps(missing, ensure_ascii=False)
    )
  if stale:
    errors.append(
      "post_intake_cash_issue_handler_stale_not_in_mapping_table: "
      + json.dumps(stale, ensure_ascii=False)
    )
  return errors


def _cash_table_issue_code(raw_code: Any) -> str:
  code = str(raw_code or "").strip().lower()
  if code and post_intake_issue_has_phase(code, "cash_pass"):
    return code
  if any(token in code for token in ("buffer", "liquidity", "underfund", "funding_gap", "cash_quarter")):
    return "liquidity_failure"
  if any(token in code for token in ("working_capital", "ar_", "ap_", "inventory", "receivable", "payable")):
    return "working_capital_mismatch"
  return "funding_structure_mismatch"


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  if not isinstance(dependencies, dict):
    return
  bind_table_safe_runtime_dependencies(globals(), dependencies)


__all__ = [
  "post_intake_cash_issue_alignment_errors",
  "_cash_strategy_fail_flags_from_review_payload",
  "_cash_strategy_failure_stage",
  "_cash_validation_errors_from_failure_payload",
  "_build_cash_strategy_failure_diagnostics",
  "_build_cash_strategy_test_mode_terminal_message",
  "_handle_cash_strategy_test_mode_failure",
  "_build_cash_strategy_test_failure_payload",
  "_cash_review_quarter_metrics",
  "_cash_strategy_live_quarter_rows",
  "_cash_strategy_financing_review_catalog",
  "_cash_strategy_operating_expense_from_row",
  "_canonical_cash_strategy_value",
  "_resolved_cash_strategy",
  "_cash_strategy_policy_guidance",
  "_hard_rules_can_defer_to_cash_strategy",
  "_cash_strategy_capital_structure_snapshot",
  "_cash_strategy_debt_schedule_snapshot",
  "_cash_strategy_debt_schedule_policy_for_state",
  "_cash_strategy_debt_opening_seed",
  "_cash_strategy_annual_principal_from_financials",
  "_cash_pass_minimum_debt_schedule_plan",
  "_apply_cash_pass_minimum_debt_schedule",
  "_cash_strategy_buffer_components",
  "_cash_strategy_debt_cash_support_multiplier",
  "_cash_pass_phase_contract",
  "_new_cash_pass_phase_trace",
  "_record_cash_pass_phase",
  "_assert_cash_pass_phase_trace_complete",
  "_cash_strategy_envelope_lever_ids",
  "_cash_strategy_planning_violation_envelope",
  "_cash_strategy_validation_violation_envelope",
  "_cash_strategy_summary_metrics",
  "_cash_strategy_required_funding_quarters",
  "_cash_strategy_funding_source_policy",
  "_cash_strategy_lever_bounds",
  "_build_cash_strategy_review_context_payload",
  "_build_cash_pass_controller_resolution_state",
  "_load_cash_strategy_review_prompt",
  "_cash_strategy_review_schema",
  "_cash_strategy_review_failure_payload",
  "_cash_strategy_gross_up_effective_support",
  "_normalize_cash_strategy_review_decision_from_funding_plan",
  "_cash_strategy_review_decision_contract_error",
  "_run_cash_strategy_review_openai",
  "_translate_cash_strategy_adjustment",
  "_build_cash_strategy_second_pass_plan",
  "_clamp_value",
  "_preferred_exact_from_band_control",
  "_apply_followup_exact_updates",
  "_apply_cash_strategy_exact_updates",
  "_apply_cash_pass_short_term_debt_current_portion",
  "_apply_cash_policy_surplus_cleanup",
  "_validate_cash_strategy_post_pass",
  "_raise_cash_pass_unresolved_liquidity_if_needed",
  "_build_cash_strategy_effect_summary",
]


def _cash_strategy_fail_flags_from_review_payload(
  review_payload: Optional[Dict[str, Any]],
) -> List[str]:
  payload = review_payload if isinstance(review_payload, dict) else {}
  status = str(payload.get("status") or "").strip().lower()
  flags: List[str] = []
  if status != "completed":
    flags.append("cash_pass_not_executed")
  if status == "failed_parse":
    flags.append("cash_parse_failed")
  if status == "completed" and not bool(payload.get("prompt_trace")):
    flags.append("cash_prompt_trace_missing")
  if status == "completed" and not bool(payload.get("raw_openai_response")):
    flags.append("cash_raw_response_missing")
  if str(payload.get("decision_source") or "").strip().lower() not in {"", "gpt"}:
    flags.append("cash_non_gpt_fallback_used")
  return list(dict.fromkeys(flag for flag in flags if flag in _CASH_STRATEGY_TEST_MODE_FAIL_FLAGS))

def _cash_strategy_failure_stage(
  *,
  review_payload: Optional[Dict[str, Any]] = None,
  plan_payload: Optional[Dict[str, Any]] = None,
  result_payload: Optional[Dict[str, Any]] = None,
) -> str:
  review = review_payload if isinstance(review_payload, dict) else {}
  plan = plan_payload if isinstance(plan_payload, dict) else {}
  result = result_payload if isinstance(result_payload, dict) else {}
  if _cash_strategy_fail_flags_from_review_payload(review):
    return "review"
  if plan.get("translation_fail_flags"):
    return "translation"
  if result.get("fail_flags") or result.get("post_validation"):
    return "validation"
  return "translation"

def _cash_validation_errors_from_failure_payload(
  *,
  review_payload: Optional[Dict[str, Any]] = None,
  plan_payload: Optional[Dict[str, Any]] = None,
  result_payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  review = review_payload if isinstance(review_payload, dict) else {}
  plan = plan_payload if isinstance(plan_payload, dict) else {}
  result = result_payload if isinstance(result_payload, dict) else {}
  errors: List[Dict[str, Any]] = []
  for warning in [str(item).strip() for item in (plan.get("translation_warnings") or []) if str(item).strip()]:
    errors.append(
      {
        "quarter": None,
        "lever": None,
        "expected": "cash adjustment inside deterministic cash bounds",
        "actual": warning,
        "reason": warning,
      }
    )
  post_validation = (
    result.get("post_validation")
    if isinstance(result.get("post_validation"), dict)
    else {}
  )
  for issue_code in [str(item).strip() for item in (post_validation.get("remaining_issue_codes") or []) if str(item).strip()]:
    errors.append(
      {
        "quarter": None,
        "lever": None,
        "expected": "all issues remain cleared after cash pass",
        "actual": issue_code,
        "reason": "cash_pass_reopened_issue",
      }
    )
  for rule_code in [str(item).strip() for item in (post_validation.get("failed_rule_codes") or []) if str(item).strip()]:
    errors.append(
      {
        "quarter": None,
        "lever": None,
        "expected": "all hard rules remain satisfied after cash pass",
        "actual": rule_code,
        "reason": "cash_pass_failed_hard_rule",
      }
    )
  for violation in [item for item in (post_validation.get("cash_buffer_violations") or []) if isinstance(item, dict)]:
    errors.append(
      {
        "quarter": int(_safe_float(violation.get("quarter_index")) or 0) or None,
        "lever": None,
        "expected": f"ending_cash >= {int(round(float(_safe_float(violation.get('buffer')) or 0.0)))}",
        "actual": f"{int(round(float(_safe_float(violation.get('ending_cash')) or 0.0)))}",
        "reason": "cash_buffer_violation",
      }
    )
  if (
    not errors
    and isinstance(review.get("detail"), str)
    and str(review.get("detail") or "").strip()
    and str(review.get("status") or "").strip().lower() != "completed"
  ):
    errors.append(
      {
        "quarter": None,
        "lever": None,
        "expected": "completed GPT cash review",
        "actual": str(review.get("status") or "").strip() or None,
        "reason": str(review.get("detail") or "").strip(),
      }
    )
  return errors

def _build_cash_strategy_failure_diagnostics(
  *,
  review_payload: Optional[Dict[str, Any]] = None,
  plan_payload: Optional[Dict[str, Any]] = None,
  result_payload: Optional[Dict[str, Any]] = None,
  extra_flags: Optional[List[str]] = None,
) -> Dict[str, Any]:
  review = review_payload if isinstance(review_payload, dict) else {}
  plan = plan_payload if isinstance(plan_payload, dict) else {}
  result = result_payload if isinstance(result_payload, dict) else {}
  flags = list(
    dict.fromkeys(
      [
        *[str(item).strip() for item in (_cash_strategy_fail_flags_from_review_payload(review) or []) if str(item).strip()],
        *[str(item).strip() for item in (plan.get("translation_fail_flags") or []) if str(item).strip()],
        *[str(item).strip() for item in (result.get("fail_flags") or []) if str(item).strip()],
        *[str(item).strip() for item in (extra_flags or []) if str(item).strip()],
      ]
    )
  )
  context_payload = (
    review.get("cash_strategy_review_context")
    if isinstance(review.get("cash_strategy_review_context"), dict)
    else {}
  )
  return {
    "cash_plan_fail_stage": _cash_strategy_failure_stage(
      review_payload=review,
      plan_payload=plan,
      result_payload=result,
    ),
    "cash_plan_fail_flags": flags,
    "cash_prompt_trace": copy.deepcopy(review.get("prompt_trace") or {}),
    "cash_raw_response": copy.deepcopy(review.get("raw_openai_response") or {}),
    "cash_review_decision": copy.deepcopy(review.get("decision") or {}),
    "cash_translated_plan": copy.deepcopy(plan or {}),
    "cash_bounds_context": {
      "selected_cash_strategy": str(review.get("selected_cash_strategy") or "").strip() or None,
      "allowed_quarters": copy.deepcopy(context_payload.get("allowed_quarters") or []),
      "lever_bounds": copy.deepcopy(context_payload.get("lever_bounds") or {}),
      "summary_metrics": copy.deepcopy(context_payload.get("summary_metrics") or {}),
      "cash_profile_summary": copy.deepcopy(context_payload.get("cash_profile_summary") or {}),
    },
    "cash_validation_errors": _cash_validation_errors_from_failure_payload(
      review_payload=review,
      plan_payload=plan,
      result_payload=result,
    ),
    "cash_result_payload": copy.deepcopy(result or {}),
  }

def _build_cash_strategy_test_mode_terminal_message(
  *,
  failure_payload: Optional[Dict[str, Any]],
) -> str:
  payload = failure_payload if isinstance(failure_payload, dict) else {}
  failure_diagnostics = (
    payload.get("cash_failure_diagnostics")
    if isinstance(payload.get("cash_failure_diagnostics"), dict)
    else {}
  )
  return "\n".join(
    [
      "STRICT FAILURE: cash strategy test mode triggered",
      f"cash_plan_fail_stage={str(failure_diagnostics.get('cash_plan_fail_stage') or 'unknown').strip() or 'unknown'}",
      f"selected_cash_strategy={str(payload.get('selected_cash_strategy') or '').strip() or 'unknown'}",
      f"status={str(payload.get('status') or '').strip() or 'unknown'}",
      f"selected_levers={', '.join([str(item).strip() for item in (payload.get('selected_lever_ids') or []) if str(item).strip()]) or 'none'}",
      f"flags={', '.join([str(item).strip() for item in (payload.get('flags') or []) if str(item).strip()]) or 'none'}",
      f"before_remaining_issue_count={int(_safe_float(payload.get('before_remaining_issue_count')) or 0)} after_remaining_issue_count={int(_safe_float(payload.get('after_remaining_issue_count')) or 0)}",
      f"before_all_cleared={bool(payload.get('before_all_cleared'))} after_all_cleared={bool(payload.get('after_all_cleared'))}",
    ]
  )

def _handle_cash_strategy_test_mode_failure(
  failure_payload: Optional[Dict[str, Any]],
) -> None:
  payload = failure_payload if isinstance(failure_payload, dict) else {}
  if not payload:
    return
  terminal_message = str(payload.get("terminal_message") or "").strip()
  detail = str(payload.get("detail") or terminal_message or "cash_strategy_test_mode_failure").strip()
  if _convergence_test_mode_enabled():
    if terminal_message:
      print(terminal_message, flush=True)
      logger.error(terminal_message)
    raise StructuredSystemRunFailure(
      detail=detail,
      diagnostics=copy.deepcopy(payload),
    )
  if terminal_message:
    logger.warning(terminal_message)
  else:
    logger.warning(detail)

def _build_cash_strategy_test_failure_payload(
  *,
  review_payload: Optional[Dict[str, Any]] = None,
  plan_payload: Optional[Dict[str, Any]] = None,
  result_payload: Optional[Dict[str, Any]] = None,
  before_controller_resolution_state: Optional[Dict[str, Any]] = None,
  after_controller_resolution_state: Optional[Dict[str, Any]] = None,
  extra_flags: Optional[List[str]] = None,
  detail: str = "",
) -> Dict[str, Any]:
  review = review_payload if isinstance(review_payload, dict) else {}
  plan = plan_payload if isinstance(plan_payload, dict) else {}
  result = result_payload if isinstance(result_payload, dict) else {}
  before_state = before_controller_resolution_state if isinstance(before_controller_resolution_state, dict) else {}
  after_state = after_controller_resolution_state if isinstance(after_controller_resolution_state, dict) else {}
  review_flags = _cash_strategy_fail_flags_from_review_payload(review)
  plan_flags = [
    str(item).strip()
    for item in (plan.get("translation_fail_flags") or [])
    if str(item).strip() in _CASH_STRATEGY_TEST_MODE_FAIL_FLAGS
  ]
  result_flags = [
    str(item).strip()
    for item in (result.get("fail_flags") or [])
    if str(item).strip() in _CASH_STRATEGY_TEST_MODE_FAIL_FLAGS
  ]
  combined_flags = list(
    dict.fromkeys(
      [
        *review_flags,
        *plan_flags,
        *result_flags,
        *[
          str(item).strip()
          for item in (extra_flags or [])
          if str(item).strip() in _CASH_STRATEGY_TEST_MODE_FAIL_FLAGS
        ],
      ]
    )
  )
  selected_lever_ids = [
    str(item).strip()
    for item in (plan.get("touched_lever_ids") or [])
    if str(item).strip()
  ]
  if not selected_lever_ids:
    selected_lever_ids = [
      str((item or {}).get("lever_id") or "").strip()
      for item in ((review.get("decision") or {}).get("recommended_adjustments") or [])
      if isinstance(item, dict) and str((item or {}).get("lever_id") or "").strip()
    ]
  status = (
    str(result.get("status") or "").strip()
    or str(plan.get("status") or "").strip()
    or str(review.get("status") or "").strip()
  )
  payload = {
    "selected_cash_strategy": str(review.get("selected_cash_strategy") or "").strip(),
    "status": status,
    "selected_lever_ids": selected_lever_ids,
    "flags": combined_flags,
    "before_remaining_issue_count": int(_safe_float(before_state.get("remaining_issue_count")) or 0),
    "after_remaining_issue_count": int(_safe_float(after_state.get("remaining_issue_count")) or 0),
    "before_all_cleared": bool(before_state.get("all_cleared")),
    "after_all_cleared": bool(after_state.get("all_cleared")),
    "detail": str(detail or "").strip() or "cash_strategy_test_mode_failure",
  }
  payload["cash_failure_diagnostics"] = _build_cash_strategy_failure_diagnostics(
    review_payload=review,
    plan_payload=plan,
    result_payload=result,
    extra_flags=combined_flags,
  )
  payload["terminal_message"] = _build_cash_strategy_test_mode_terminal_message(
    failure_payload=payload
  )
  return payload

def _cash_review_quarter_metrics(finmo_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  quarter_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  live_rows = [row for row in quarter_rows if int(float(row.get("quarter_index") or 0)) >= 1]
  metrics: List[Dict[str, Any]] = []
  for row in live_rows:
    metrics.append(
      {
        "quarter_index": int(float(row.get("quarter_index") or 0)),
        "year": row.get("year"),
        "quarter": row.get("quarter"),
        "date": row.get("date"),
        "revenue": _safe_float(row.get("revenue")),
        "ebitda": _safe_float(row.get("ebitda")),
        "net_income": _safe_float(row.get("net_income")),
        "ending_cash": _safe_float(row.get("ending_cash")),
        "total_assets": _safe_float(row.get("total_assets")),
        "short_term_debt": _safe_float(row.get("short_term_debt")),
        "long_term_debt": _safe_float(row.get("long_term_debt")),
        "total_equity": _safe_float(row.get("total_equity")),
        "total_liabilities_and_equity": _safe_float(row.get("total_liabilities_and_equity")),
      }
    )
  return metrics

def _cash_strategy_live_quarter_rows(finmo_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  finmo_obj = finmo_payload if isinstance(finmo_payload, dict) else {}
  quarter_rows = [row for row in (finmo_obj.get("quarter_rows") or []) if isinstance(row, dict)]
  return [
    row for row in quarter_rows
    if int(_safe_float(row.get("quarter_index")) or 0) >= 1
  ]

def _cash_strategy_financing_review_catalog(
  model_input_json: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  allowed_ids = set(_CASH_STRATEGY_ALLOWED_LEVER_IDS)
  return [
    copy.deepcopy(item)
    for item in _build_writable_lever_review_catalog(model_input_json)
    if str(item.get("lever_id") or "").strip() in allowed_ids
  ]

def _cash_strategy_operating_expense_from_row(row: Optional[Dict[str, Any]]) -> float:
  item = row if isinstance(row, dict) else {}
  return float(
    sum(
      float(_safe_float(item.get(key)) or 0.0)
      for key in (
        "cost_of_goods_sold",
        "payroll",
        "marketing",
        "research_and_development",
        "lease_rent",
        "general_and_administrative",
      )
    )
  )

def _canonical_cash_strategy_value(value: Any) -> str:
  text = str(value or "").strip().lower()
  if not text:
    return ""
  compact = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
  if compact in {"preserve_cash", "shareholder_return", "balanced"}:
    return compact
  # Explicit labels must win over descriptive words inside the same sentence
  # such as "Balanced ... preserve liquidity".
  if compact.startswith("balanced"):
    return "balanced"
  if compact.startswith("shareholder_return") or compact.startswith("shareholder"):
    return "shareholder_return"
  if compact.startswith("preserve_cash") or compact.startswith("preserve"):
    return "preserve_cash"
  if compact == "reinvest":
    return "balanced"
  if "balanced" in text or "mixed" in text:
    return "balanced"
  if "shareholder" in text or "distribution" in text or "payout" in text or "return capital" in text:
    return "shareholder_return"
  if "preserve" in text or "conservative" in text or "cushion" in text:
    return "preserve_cash"
  if "reinvest" in text or "growth" in text or "expansion" in text:
    return "balanced"
  return ""

def _resolved_cash_strategy(*strategy_candidates: Any) -> str:
  for candidate in strategy_candidates:
    if isinstance(candidate, dict):
      for key in ("cash_strategy", "selected_cash_strategy"):
        value = _canonical_cash_strategy_value(candidate.get(key))
        if value:
          return value
      continue
    value = _canonical_cash_strategy_value(candidate)
    if value:
      return value
  return "balanced"

def _cash_strategy_policy_guidance(selected_cash_strategy: Any) -> Dict[str, Any]:
  strategy = _canonical_cash_strategy_value(selected_cash_strategy) or "balanced"
  strategy_map = {
    "preserve_cash": {
      "strategy_label": "preserve_cash",
      "priority_order": [
        "satisfy_liquidity_buffer",
        "retain_extra_liquidity",
        "minimize_optional_outflows",
      ],
      "guidance": (
        "Fund only when cash would otherwise fall below the required buffer, prefer conservative non-debt "
        "support when leverage is already high, and do not create optional distributions."
      ),
    },
    "shareholder_return": {
      "strategy_label": "shareholder_return",
      "priority_order": [
        "satisfy_liquidity_buffer",
        "allow_payouts_only_from_true_excess_cash",
        "avoid_destabilizing_the_business",
      ],
      "guidance": (
        "Protect the required buffer first. Only true surplus above the buffer may be distributed, and "
        "new debt or equity must never be raised to fund shareholder payouts."
      ),
    },
    "balanced": {
      "strategy_label": "balanced",
      "priority_order": [
        "satisfy_liquidity_buffer",
        "respect_a_mixed_capital_posture",
        "avoid_extremes",
      ],
      "guidance": (
        "Fund liquidity gaps just in time, use debt and equity according to business realism and leverage, "
        "and avoid both unnecessary cash hoarding and unnecessary dilution."
      ),
    },
  }
  return copy.deepcopy(strategy_map.get(strategy) or strategy_map["balanced"])

def _hard_rules_can_defer_to_cash_strategy(
  hard_rule_assessment: Optional[Dict[str, Any]],
) -> bool:
  assessment = hard_rule_assessment if isinstance(hard_rule_assessment, dict) else {}
  failed_rule_codes = {
    str(item).strip().lower()
    for item in (assessment.get("failed_rule_codes") or [])
    if str(item).strip()
  }
  if not failed_rule_codes:
    return False
  if failed_rule_codes != {"liquidity_failure"}:
    return False
  if not bool(assessment.get("accounting_integrity_passed")):
    return False
  return True

def _cash_strategy_capital_structure_snapshot(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  item = row if isinstance(row, dict) else {}
  debt_level = int(
    round(
      max(
        0.0,
        float(_safe_float(item.get("short_term_debt")) or 0.0)
        + float(_safe_float(item.get("long_term_debt")) or 0.0),
      )
    )
  )
  equity_level = int(round(max(0.0, float(_safe_float(item.get("total_equity")) or 0.0))))
  capital_base = float(debt_level + equity_level)
  debt_ratio = round(float(debt_level / capital_base), 2) if capital_base > 1e-9 else None
  equity_ratio = round(float(equity_level / capital_base), 2) if capital_base > 1e-9 else None
  if equity_level > 0:
    debt_to_equity = round(float(debt_level / equity_level), 4)
  elif debt_level > 0:
    debt_to_equity = 999.0
  else:
    debt_to_equity = 0.0
  if debt_to_equity < 0.50:
    debt_position = "low_debt"
  elif debt_to_equity <= 1.00:
    debt_position = "healthy_debt"
  else:
    debt_position = "high_debt"
  return {
    "debt": debt_level,
    "equity": equity_level,
    "debt_level": debt_level,
    "equity_level": equity_level,
    "debt_to_equity": debt_to_equity,
    "debt_position": debt_position,
    "debt_ratio": debt_ratio,
    "equity_ratio": equity_ratio,
    "preferred_debt_ratio": round(float(_CASH_STRATEGY_PREFERRED_DEBT_RATIO), 2),
    "preferred_equity_ratio": round(float(_CASH_STRATEGY_PREFERRED_EQUITY_RATIO), 2),
    "guidance_only": True,
  }

def _cash_strategy_debt_schedule_snapshot(
  *,
  finmo_payload: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  rows_by_quarter = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in _cash_strategy_live_quarter_rows(finmo_payload)
    if int(_safe_float(row.get("quarter_index")) or 0) >= 1
  }
  lever_map = _solved_lever_value_map(model_input_json)
  debt_issuance_series = [
    int(round(float(_safe_float(value) or 0.0)))
    for value in (lever_map.get(_CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID) or [])
  ]
  debt_repayment_series = [
    int(round(float(_safe_float(value) or 0.0)))
    for value in (lever_map.get(_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID) or [])
  ]
  interest_rate_series = [
    round(float(_safe_float(value) or 0.0), 6)
    for value in (lever_map.get("expenses::Interest Rate") or [])
  ]
  schedule_rows: List[Dict[str, Any]] = []
  for quarter_index in sorted(rows_by_quarter.keys()):
    row = rows_by_quarter.get(quarter_index) or {}
    opening_debt = int(round(float(_safe_float(row.get("debt_opening_balance")) or 0.0)))
    requested_issuance = int(debt_issuance_series[quarter_index - 1] if quarter_index - 1 < len(debt_issuance_series) else 0)
    requested_repayment = int(debt_repayment_series[quarter_index - 1] if quarter_index - 1 < len(debt_repayment_series) else 0)
    actual_issuance = int(round(float(_safe_float(row.get("debt_issuance")) or 0.0)))
    actual_repayment = int(round(float(_safe_float(row.get("debt_repayment")) or 0.0)))
    closing_debt = int(round(float(_safe_float(row.get("debt_closing_balance")) or _safe_float(row.get("long_term_debt")) or 0.0)))
    interest_rate = round(
      float(
        _safe_float(row.get("debt_interest_rate"))
        if _safe_float(row.get("debt_interest_rate")) is not None
        else (
          interest_rate_series[quarter_index - 1]
          if quarter_index - 1 < len(interest_rate_series)
          else 0.0
        )
      ),
      6,
    )
    interest_expense = int(round(float(_safe_float(row.get("debt_interest_expense")) or _safe_float(row.get("interest")) or 0.0)))
    schedule_rows.append(
      {
        "quarter_index": quarter_index,
        "date": row.get("date"),
        "opening_debt": opening_debt,
        "requested_debt_issuance": requested_issuance,
        "actual_debt_issuance": actual_issuance,
        "requested_debt_repayment": requested_repayment,
        "actual_debt_repayment": actual_repayment,
        "closing_debt": closing_debt,
        "interest_rate": interest_rate,
        "interest_expense": interest_expense,
        "available_debt_before_repayment": int(max(0, opening_debt + actual_issuance)),
        "finmo_formula": "closing_debt = max(0, opening_debt + debt_issuance - debt_repayment); interest = average(opening_debt, closing_debt) * interest_rate",
      }
    )
  return {
    "contract_version": "cash_strategy_debt_schedule_snapshot_v1",
    "schedule_role": "diagnostic_and_conversion_basis_for_existing_model_input_debt_rows",
    "finmo_formula_unchanged": True,
    "model_input_drivers": [
      "expenses::Interest Rate",
      _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID,
      _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
    ],
    "rows": schedule_rows,
  }

def _cash_strategy_debt_schedule_policy_for_state(
  *,
  selected_cash_strategy: Any,
  finmo_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  rows = _cash_strategy_live_quarter_rows(finmo_payload)
  first_row = rows[0] if rows else {}
  capital_structure = _cash_strategy_capital_structure_snapshot(first_row)
  return post_intake_cash_debt_schedule_policy(
    cash_strategy=_canonical_cash_strategy_value(selected_cash_strategy) or "balanced",
    debt_to_equity=capital_structure.get("debt_to_equity"),
    debt_position=capital_structure.get("debt_position"),
    required=True,
  ) or {}

def _cash_strategy_sba_forecast_interest_rate_policy(
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  derived_policies = (
    model_input.get("derived_driver_policies")
    if isinstance(model_input.get("derived_driver_policies"), dict)
    else {}
  )
  debt_rate_policy = (
    derived_policies.get("debt_interest_rate_policy")
    if isinstance(derived_policies.get("debt_interest_rate_policy"), dict)
    else {}
  )
  debt_rate_source = (
    debt_rate_policy.get("source_detail")
    if isinstance(debt_rate_policy.get("source_detail"), dict)
    else {}
  )
  if not debt_rate_policy:
    raise RuntimeError(
      "cash_debt_interest_rate_policy_missing: forecast Q1-Q20 interest rates must be backed by SBA 7(a) policy"
    )
  if str(debt_rate_source.get("source") or "").strip() != "sba_loan_7a_raw":
    raise RuntimeError(
      "cash_debt_interest_rate_policy_not_sba_backed: forecast Q1-Q20 interest rates must use sba_loan_7a_raw"
    )
  annual_rate = _safe_float(debt_rate_policy.get("annual_rate_decimal"))
  if annual_rate is None:
    annual_rate = _safe_float(debt_rate_source.get("annual_rate_decimal"))
  if annual_rate is None or float(annual_rate) <= 0.0:
    raise RuntimeError(
      "cash_debt_interest_rate_policy_rate_missing: SBA-backed annual_rate_decimal must be positive"
    )
  return {
    "policy": copy.deepcopy(debt_rate_policy),
    "source_detail": copy.deepcopy(debt_rate_source),
    "annual_rate_decimal": round(float(annual_rate), 6),
  }

def _cash_strategy_debt_opening_seed(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_payload: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
) -> int:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  seed = _safe_float(schedules.get("debt_opening_balance_seed"))
  if seed is not None:
    return int(round(max(0.0, float(seed))))
  rows = _cash_strategy_live_quarter_rows(finmo_payload)
  if rows:
    opening = _safe_float(rows[0].get("debt_opening_balance"))
    if opening is not None:
      return int(round(max(0.0, float(opening))))
  financials = financials_json if isinstance(financials_json, dict) else {}
  return int(round(max(0.0, float(_safe_float(financials.get("total_debt_outstanding")) or 0.0))))

def _cash_strategy_annual_principal_from_financials(
  *,
  financials_json: Optional[Dict[str, Any]],
  policy: Optional[Dict[str, Any]],
  opening_debt: int,
) -> Tuple[int, str]:
  if int(opening_debt or 0) <= 0:
    return 0, "no_opening_debt"
  financials = financials_json if isinstance(financials_json, dict) else {}
  policy_payload = policy if isinstance(policy, dict) else {}
  source_priority = [
    str(item or "").strip()
    for item in (policy_payload.get("debt_min_principal_source_priority") or [])
    if str(item or "").strip()
  ] or ["financials.annual_principal_payment"]
  for source in source_priority:
    if source == "financials.annual_principal_payment":
      value = int(round(max(0.0, float(_safe_float(financials.get("annual_principal_payment")) or 0.0))))
      if value > 0:
        return value, source
    if source == "financials.other_monthly_debt_payments_minus_annual_interest_payment":
      monthly_payment = max(0.0, float(_safe_float(financials.get("other_monthly_debt_payments")) or 0.0))
      annual_interest = max(0.0, float(_safe_float(financials.get("annual_interest_payment")) or 0.0))
      value = int(round(max(0.0, monthly_payment * 12.0 - annual_interest)))
      if value > 0:
        return value, source
  raise RuntimeError(
    "cash_debt_schedule_minimum_principal_missing: "
    "opening debt exists, but no positive annual principal source was available. "
    f"opening_debt={int(opening_debt)} source_priority={source_priority}"
  )

def _cash_pass_minimum_debt_schedule_plan(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_payload: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  selected_cash_strategy: Any,
) -> Dict[str, Any]:
  policy = _cash_strategy_debt_schedule_policy_for_state(
    selected_cash_strategy=selected_cash_strategy,
    finmo_payload=finmo_payload,
  )
  if str(policy.get("debt_schedule_method") or "").strip().lower() != "straight_line_minimum_principal":
    raise RuntimeError(
      "cash_debt_schedule_policy_invalid: debt_schedule_method must be straight_line_minimum_principal"
    )
  if not bool(policy.get("debt_schedule_required", True)):
    raise RuntimeError(
      "cash_debt_schedule_policy_invalid: debt_schedule_required must be true"
    )
  horizon_count = _cash_contract_horizon_quarters()
  if int(_safe_float(policy.get("debt_schedule_horizon_quarters")) or 0) != horizon_count:
    raise RuntimeError(
      "cash_debt_schedule_policy_invalid: "
      f"debt_schedule_horizon_quarters must match cash_strategy_review contract horizon ({horizon_count})"
    )
  opening_debt_seed = _cash_strategy_debt_opening_seed(
    model_input_json=model_input_json,
    finmo_payload=finmo_payload,
    financials_json=financials_json,
  )
  lever_map = _solved_lever_value_map(model_input_json)
  debt_issuance_series = [
    int(round(max(0.0, float(_safe_float(value) or 0.0))))
    for value in (lever_map.get(_CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID) or [])
  ]
  current_repayment_series = [
    int(round(max(0.0, float(_safe_float(value) or 0.0))))
    for value in (lever_map.get(_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID) or [])
  ]
  interest_rate_policy = _cash_strategy_sba_forecast_interest_rate_policy(model_input_json)
  forecast_interest_rate = round(float(interest_rate_policy.get("annual_rate_decimal") or 0.0), 6)
  rows: List[Dict[str, Any]] = []
  exact_updates: List[Dict[str, Any]] = []
  if opening_debt_seed <= 0 and not any(debt_issuance_series):
    for quarter_index in range(1, horizon_count + 1):
      exact_updates.append(
        {
          "lever_id": "expenses::Interest Rate",
          "quarter_index": quarter_index,
          "exact_value": forecast_interest_rate,
          "issue_codes": ["funding_structure_mismatch"],
          "rationale": "Forecast Q1-Q20 interest-rate driver must use the SBA 7(a)-backed policy rate; stub Q0 remains intake history.",
        }
      )
    return {
      "contract_version": "cash_debt_schedule_plan_v2",
      "status": "skipped_no_debt",
      "source_of_truth": policy.get("source_of_truth") or "sql.post_intake_cash_policy_lookup",
      "lookup_function": policy.get("lookup_function") or "post_intake_cash_debt_schedule_policy",
      "policy": copy.deepcopy(policy),
      "interest_rate_policy": copy.deepcopy(interest_rate_policy),
      "opening_debt_seed": 0,
      "annual_principal_payment": 0,
      "quarterly_minimum_principal": 0,
      "rows": rows,
      "exact_updates": exact_updates,
    }
  annual_principal, annual_principal_source = _cash_strategy_annual_principal_from_financials(
    financials_json=financials_json,
    policy=policy,
    opening_debt=opening_debt_seed,
  )
  quarterly_minimum = int(round(max(0.0, float(annual_principal)) / 4.0))
  if quarterly_minimum <= 0 and opening_debt_seed > 0:
    raise RuntimeError(
      "cash_debt_schedule_quarterly_minimum_zero: opening debt exists but computed quarterly principal is zero"
    )
  opening_debt = int(opening_debt_seed)
  for quarter_index in range(1, horizon_count + 1):
    current_issuance = int(debt_issuance_series[quarter_index - 1] if quarter_index - 1 < len(debt_issuance_series) else 0)
    current_repayment = int(current_repayment_series[quarter_index - 1] if quarter_index - 1 < len(current_repayment_series) else 0)
    available_debt = int(max(0, opening_debt + current_issuance))
    minimum_principal = int(min(available_debt, quarterly_minimum if available_debt > 0 else 0))
    scheduled_principal = int(max(current_repayment, minimum_principal))
    scheduled_principal = int(min(available_debt, scheduled_principal))
    closing_debt = int(max(0, available_debt - scheduled_principal))
    interest_rate = forecast_interest_rate
    if available_debt > 0 and interest_rate <= 0.0:
      raise RuntimeError(
        "cash_debt_schedule_interest_rate_missing: "
        f"Q{quarter_index} has debt outstanding but expenses::Interest Rate is not positive"
      )
    interest_estimate = int(round(((opening_debt + closing_debt) / 2.0) * interest_rate))
    exact_updates.append(
      {
        "lever_id": _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
        "quarter_index": quarter_index,
        "exact_value": scheduled_principal,
        "issue_codes": ["funding_structure_mismatch"],
        "rationale": "SQL cash-policy minimum debt schedule floor; cash strategy may add extra paydown but may not skip required principal.",
      }
    )
    if interest_rate > 0.0:
      exact_updates.append(
      {
        "lever_id": "expenses::Interest Rate",
        "quarter_index": quarter_index,
        "exact_value": interest_rate,
        "issue_codes": ["funding_structure_mismatch"],
        "rationale": "Forecast Q1-Q20 interest-rate driver must use the SBA 7(a)-backed policy rate; stub Q0 remains intake history.",
      }
    )
    rows.append(
      {
        "quarter_index": quarter_index,
        "opening_debt": opening_debt,
        "new_borrowing": current_issuance,
        "minimum_principal_payment": minimum_principal,
        "extra_principal_payment": int(max(0, scheduled_principal - minimum_principal)),
        "total_principal_payment": scheduled_principal,
        "closing_debt": closing_debt,
        "annual_interest_rate": interest_rate,
        "estimated_interest_expense": interest_estimate,
        "principal_source": annual_principal_source,
      }
    )
    opening_debt = closing_debt
  return {
    "contract_version": "cash_debt_schedule_plan_v2",
    "status": "ready",
    "source_of_truth": policy.get("source_of_truth") or "sql.post_intake_cash_policy_lookup",
    "lookup_function": policy.get("lookup_function") or "post_intake_cash_debt_schedule_policy",
    "policy": copy.deepcopy(policy),
    "interest_rate_policy": copy.deepcopy(interest_rate_policy),
    "opening_debt_seed": int(opening_debt_seed),
    "annual_principal_payment": int(annual_principal),
    "annual_principal_source": annual_principal_source,
    "quarterly_minimum_principal": int(quarterly_minimum),
    "model_input_rows_written": [
      _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
      "expenses::Interest Rate",
    ],
    "rows": rows,
    "exact_updates": exact_updates,
  }

def _apply_cash_pass_minimum_debt_schedule(
  *,
  cash_strategy_result: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  result = copy.deepcopy(cash_strategy_result if isinstance(cash_strategy_result, dict) else {})
  model_input_json = result.get("updated_model_input_json") if isinstance(result.get("updated_model_input_json"), dict) else {}
  finmo_json = result.get("updated_finmo_json") if isinstance(result.get("updated_finmo_json"), dict) else {}
  if not model_input_json or not finmo_json:
    return result
  try:
    from client_intake_and_finmo.numeric_execution import execute_numeric_plan  # type: ignore
  except Exception:
    from numeric_execution import execute_numeric_plan  # type: ignore
  selected_cash_strategy = _resolved_cash_strategy(financials_json)
  schedule_plan = _cash_pass_minimum_debt_schedule_plan(
    model_input_json=copy.deepcopy(model_input_json),
    finmo_payload=copy.deepcopy(finmo_json),
    financials_json=copy.deepcopy(financials_json or {}),
    selected_cash_strategy=selected_cash_strategy,
  )
  exact_updates = [
    copy.deepcopy(item)
    for item in (schedule_plan.get("exact_updates") or [])
    if isinstance(item, dict)
  ]
  if not exact_updates:
    result["minimum_debt_schedule_policy"] = copy.deepcopy(schedule_plan)
    return result
  execution_result = execute_numeric_plan(
    model_input_json=copy.deepcopy(model_input_json),
    exact_updates=copy.deepcopy(exact_updates),
    numeric_solver_contract={
      "pass_name": "cash_strategy_review",
      "contract_scope": "cash_pass_minimum_debt_schedule",
      "solver_phase_status": "phase_6_cash_strategy_solver_live",
      "solver_settings": {"max_solver_attempts_per_pass": 1},
    },
    review_plan=None,
    phase_status="phase_6_cash_strategy_solver_live",
    executor_context={
      "source": "_apply_cash_pass_minimum_debt_schedule",
      "execution_mode": "deterministic_minimum_debt_schedule",
    },
  )
  result["updated_model_input_json"] = execution_result.get("updated_model_input_json") or model_input_json
  result["updated_finmo_json"] = execution_result.get("updated_finmo_json") or finmo_json
  result["minimum_debt_schedule_policy"] = copy.deepcopy(schedule_plan)
  applied_updates = [
    copy.deepcopy(item)
    for item in (result.get("applied_updates") or [])
    if isinstance(item, dict)
  ]
  result["applied_updates"] = applied_updates + copy.deepcopy(exact_updates)
  result["applied_update_count"] = len(result["applied_updates"])
  result["applied_control_count"] = len(result["applied_updates"])
  return result

def _cash_strategy_buffer_components(
  row: Optional[Dict[str, Any]],
  *,
  cash_floor_months: Optional[float] = None,
  cash_ceiling_months: Optional[float] = None,
) -> Dict[str, Any]:
  opex_quarter = int(round(max(0.0, _cash_strategy_operating_expense_from_row(row))))
  monthly_opex = int(round(max(0.0, float(opex_quarter) / max(_CASH_STRATEGY_MONTHS_PER_QUARTER, 1.0))))
  floor_months = float(cash_floor_months if cash_floor_months is not None else _CASH_STRATEGY_BUFFER_MONTHS)
  ceiling_months = float(cash_ceiling_months if cash_ceiling_months is not None else max(floor_months, _CASH_STRATEGY_BUFFER_MONTHS))
  return {
    "operating_expense_quarter": opex_quarter,
    "buffer_months": round(float(floor_months), 2),
    "cash_floor_months": round(float(floor_months), 2),
    "cash_ceiling_months": round(float(ceiling_months), 2),
    "monthly_opex": monthly_opex,
    "cash_buffer_required": int(round(max(float(monthly_opex) * floor_months, 0.0))),
    "cash_ceiling": int(round(max(float(monthly_opex) * ceiling_months, 0.0))),
  }

def _cash_strategy_debt_cash_support_multiplier(
  *,
  lever_map: Optional[Dict[str, List[float]]],
  quarter_index: int,
) -> float:
  if quarter_index < 1:
    return 1.0
  rate_series = (
    (lever_map or {}).get("expenses::Interest Rate")
    if isinstance(lever_map, dict)
    else []
  ) or []
  raw_rate = (
    float(_safe_float(rate_series[quarter_index - 1]) or 0.0)
    if quarter_index - 1 < len(rate_series)
    else 0.0
  )
  normalized_rate = min(max(raw_rate, 0.0), 1.0)
  # New borrowing and skipped repayment do not lift ending cash 1:1 inside the
  # same quarter because FINMO applies an immediate partial-quarter interest drag.
  return round(max(0.0, 1.0 - (normalized_rate / 2.0)), 6)

def _cash_pass_phase_contract(
  *,
  financials_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  selected_cash_strategy = _resolved_cash_strategy(financials_json)
  cash_policy_errors = post_intake_cash_policy_errors()
  if cash_policy_errors:
    raise RuntimeError(
      "post_intake_cash_policy_invalid: " + "; ".join(str(item) for item in cash_policy_errors[:10])
    )
  phase_sequence = post_intake_cash_policy_phase_sequence(
    cash_strategy=selected_cash_strategy,
    required=True,
  )
  phase_codes = [
    str(item.get("phase_code") or "").strip().lower()
    for item in phase_sequence
    if str(item.get("phase_code") or "").strip()
  ]
  if not phase_codes:
    raise RuntimeError(
      f"post_intake_cash_policy_phase_sequence_missing: cash_strategy={selected_cash_strategy}"
    )
  return {
    "contract_version": "cash_pass_phase_contract_v1",
    "source_of_truth": "sql.post_intake_cash_policy_lookup",
    "lookup_function": "post_intake_cash_policy_phase_sequence",
    "selected_cash_strategy": selected_cash_strategy,
    "phase_codes": phase_codes,
    "phase_sequence": copy.deepcopy(phase_sequence),
    "required_phase_count": len(phase_codes),
  }

def _new_cash_pass_phase_trace(phase_contract: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  contract = phase_contract if isinstance(phase_contract, dict) else {}
  return {
    "contract_version": "cash_pass_phase_trace_v1",
    "source_of_truth": contract.get("source_of_truth") or "sql.post_intake_cash_policy_lookup",
    "lookup_function": contract.get("lookup_function") or "post_intake_cash_policy_phase_sequence",
    "selected_cash_strategy": contract.get("selected_cash_strategy"),
    "expected_phase_codes": copy.deepcopy(contract.get("phase_codes") or []),
    "completed_phase_codes": [],
    "events": [],
  }

def _record_cash_pass_phase(
  phase_trace: Dict[str, Any],
  phase_contract: Dict[str, Any],
  phase_code: str,
  *,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
  detail: str = "",
) -> Dict[str, Any]:
  trace = phase_trace if isinstance(phase_trace, dict) else _new_cash_pass_phase_trace(phase_contract)
  contract = phase_contract if isinstance(phase_contract, dict) else {}
  phase_sequence = [
    item for item in (contract.get("phase_sequence") or [])
    if isinstance(item, dict)
  ]
  completed = [
    str(item or "").strip().lower()
    for item in (trace.get("completed_phase_codes") or [])
    if str(item or "").strip()
  ]
  current_code = str(phase_code or "").strip().lower()
  if not current_code:
    raise RuntimeError("cash_pass_phase_sequence_violation: missing phase_code")
  expected_phase = phase_sequence[len(completed)] if len(completed) < len(phase_sequence) else {}
  expected_code = str(expected_phase.get("phase_code") or "").strip().lower()
  if current_code != expected_code:
    raise RuntimeError(
      "cash_pass_phase_sequence_violation: "
      f"expected={expected_code or 'none'} actual={current_code} "
      f"completed={completed}"
    )
  requires_finmo = bool(expected_phase.get("requires_finmo_rebuild_after"))
  if requires_finmo:
    if not isinstance(model_input_json, dict) or not model_input_json:
      raise RuntimeError(
        f"cash_pass_phase_state_invalid: phase={current_code} requires updated_model_input_json"
      )
    if not isinstance(finmo_json, dict) or not (finmo_json.get("quarter_rows") or []):
      raise RuntimeError(
        f"cash_pass_phase_state_invalid: phase={current_code} requires rebuilt updated_finmo_json"
      )
  event = {
    "phase_code": current_code,
    "phase_order": expected_phase.get("phase_order"),
    "phase_owner": expected_phase.get("phase_owner"),
    "requires_finmo_rebuild_after": requires_finmo,
    "validation_gate": expected_phase.get("validation_gate"),
    "detail": str(detail or "").strip(),
    "model_input_present": isinstance(model_input_json, dict) and bool(model_input_json),
    "finmo_present": isinstance(finmo_json, dict) and bool(finmo_json.get("quarter_rows") if isinstance(finmo_json, dict) else False),
  }
  completed.append(current_code)
  trace["completed_phase_codes"] = completed
  trace.setdefault("events", [])
  if isinstance(trace.get("events"), list):
    trace["events"].append(event)
  return trace

def _assert_cash_pass_phase_trace_complete(
  phase_trace: Optional[Dict[str, Any]],
  phase_contract: Optional[Dict[str, Any]],
) -> None:
  trace = phase_trace if isinstance(phase_trace, dict) else {}
  contract = phase_contract if isinstance(phase_contract, dict) else {}
  expected = [
    str(item or "").strip().lower()
    for item in (contract.get("phase_codes") or [])
    if str(item or "").strip()
  ]
  completed = [
    str(item or "").strip().lower()
    for item in (trace.get("completed_phase_codes") or [])
    if str(item or "").strip()
  ]
  if completed != expected:
    raise RuntimeError(
      "cash_pass_phase_sequence_incomplete: "
      f"expected={expected} completed={completed}"
    )

def _cash_strategy_envelope_lever_ids() -> Dict[str, str]:
  return {
    "debt_issuance": _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID,
    "debt_repayment": _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
    "owners_capital": _CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID,
    "other_equity": _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID,
    "distributions": _CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID,
  }

def _cash_strategy_planning_violation_envelope(
  *,
  selected_cash_strategy: Any,
  finmo_payload: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  envelope = build_cash_planning_envelope(
    selected_cash_strategy=selected_cash_strategy,
    finmo_payload=copy.deepcopy(finmo_payload or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    lever_ids=_cash_strategy_envelope_lever_ids(),
    default_buffer_months=_CASH_STRATEGY_BUFFER_MONTHS,
    months_per_quarter=_CASH_STRATEGY_MONTHS_PER_QUARTER,
    preferred_debt_ratio=_CASH_STRATEGY_PREFERRED_DEBT_RATIO,
    preferred_equity_ratio=_CASH_STRATEGY_PREFERRED_EQUITY_RATIO,
  )
  assert_cash_envelope_lifecycle(envelope, "planning_pre_action")
  return envelope

def _cash_strategy_validation_violation_envelope(
  *,
  selected_cash_strategy: Any,
  finmo_payload: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  envelope = build_cash_validation_envelope(
    selected_cash_strategy=selected_cash_strategy,
    finmo_payload=copy.deepcopy(finmo_payload or {}),
    model_input_json=copy.deepcopy(model_input_json or {}),
    lever_ids=_cash_strategy_envelope_lever_ids(),
    default_buffer_months=_CASH_STRATEGY_BUFFER_MONTHS,
    months_per_quarter=_CASH_STRATEGY_MONTHS_PER_QUARTER,
    preferred_debt_ratio=_CASH_STRATEGY_PREFERRED_DEBT_RATIO,
    preferred_equity_ratio=_CASH_STRATEGY_PREFERRED_EQUITY_RATIO,
  )
  assert_cash_envelope_lifecycle(envelope, "validation_post_action_actual_state")
  return envelope

def _cash_strategy_summary_metrics(
  *,
  selected_cash_strategy: Any,
  violation_envelope: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  envelope = violation_envelope if isinstance(violation_envelope, dict) else {}
  quarter_envelopes = [
    item for item in (envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
  ]
  return {
    "selected_cash_strategy": str(selected_cash_strategy or "").strip(),
    "has_violations": bool(envelope.get("has_violations")),
    "violation_quarters": copy.deepcopy(envelope.get("violation_quarters") or []),
    "residual_gap_quarters": copy.deepcopy(envelope.get("residual_gap_quarters") or []),
    "surplus_deployment_quarters": copy.deepcopy(envelope.get("surplus_deployment_quarters") or []),
    "allowed_review_quarters": copy.deepcopy(envelope.get("allowed_review_quarters") or []),
    "buffer_quarters": [
      {
        "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
        "ending_cash": int(round(float(_safe_float(item.get("ending_cash")) or 0.0))),
        "buffer": int(round(float(_safe_float(item.get("buffer")) or 0.0))),
        "cash_ceiling": int(round(float(_safe_float(item.get("cash_ceiling")) or 0.0))),
        "ending_cash_after_hard_rules": int(round(float(_safe_float(item.get("ending_cash_after_hard_rules")) or 0.0))),
        "residual_funding_gap": int(round(float(_safe_float(item.get("residual_funding_gap")) or 0.0))),
        "deployable_surplus_above_ceiling": int(round(float(_safe_float(item.get("deployable_surplus_above_ceiling")) or 0.0))),
        "max_additional_distribution": int(round(float(_safe_float(item.get("max_additional_distribution")) or 0.0))),
        "max_additional_debt_paydown": int(round(float(_safe_float(item.get("max_additional_debt_paydown")) or 0.0))),
        "buffer_violation": bool(item.get("buffer_violation")),
        "distribution_violation": bool(item.get("distribution_violation")),
      }
      for item in quarter_envelopes
    ],
  }

def _cash_strategy_required_funding_quarters(
  violation_envelope: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  envelope = violation_envelope if isinstance(violation_envelope, dict) else {}
  quarter_envelopes = [
    item for item in (envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
  ]
  required_quarters: List[Dict[str, Any]] = []
  prior_peak_gap = 0
  for item in quarter_envelopes:
    residual_gap = int(round(float(_safe_float(item.get("residual_funding_gap")) or 0.0)))
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    incremental_gap = int(max(0, residual_gap - prior_peak_gap))
    prior_peak_gap = int(max(prior_peak_gap, residual_gap))
    if quarter_index < 1 or incremental_gap <= 0:
      continue
    capital_structure = item.get("capital_structure") if isinstance(item.get("capital_structure"), dict) else {}
    required_quarters.append(
      {
        "quarter_index": quarter_index,
        "buffer": int(round(float(_safe_float(item.get("buffer")) or 0.0))),
        "ending_cash_after_hard_rules": int(round(float(_safe_float(item.get("ending_cash_after_hard_rules")) or 0.0))),
        "cumulative_buffer_gap_after_hard_rules": residual_gap,
        "prior_peak_buffer_gap_after_hard_rules": int(max(0, prior_peak_gap - incremental_gap)),
        "required_incremental_funding_after_hard_rules": incremental_gap,
        "funding_timing_rule": "fund_only_the_incremental_new_high_water_gap_needed_to_restore_the_buffer",
        "debt_cash_support_multiplier_estimate": round(
          float(_safe_float(item.get("debt_cash_support_multiplier")) or 1.0),
          6,
        ),
        "debt_cash_support_per_1000": int(round(float(_safe_float(item.get("debt_cash_support_per_1000")) or 1000.0))),
        "capital_structure": {
          "debt": int(round(float(_safe_float(capital_structure.get("debt")) or _safe_float(capital_structure.get("debt_level")) or 0.0))),
          "equity": int(round(float(_safe_float(capital_structure.get("equity")) or _safe_float(capital_structure.get("equity_level")) or 0.0))),
          "debt_ratio": round(float(_safe_float(capital_structure.get("debt_ratio")) or 0.0), 2),
          "equity_ratio": round(float(_safe_float(capital_structure.get("equity_ratio")) or 0.0), 2),
        },
      }
    )
  return required_quarters

def _cash_strategy_funding_source_policy(
  *,
  violation_envelope: Optional[Dict[str, Any]],
  debt_schedule_snapshot: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  """Scope cash funding sources before GPT chooses the source mix.

  Debt is a valid funding tool for short bridge needs, but chronic liquidity
  gaps funded with debt can reopen the cash buffer through FINMO interest drag.
  This policy narrows the source surface deterministically; GPT still chooses
  among the remaining mapped funding levers.
  """
  envelope = violation_envelope if isinstance(violation_envelope, dict) else {}
  schedule = debt_schedule_snapshot if isinstance(debt_schedule_snapshot, dict) else {}
  residual_gap_quarters = [
    int(_safe_float(item) or 0)
    for item in (envelope.get("residual_gap_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  rows = [
    item for item in (schedule.get("rows") or [])
    if isinstance(item, dict)
  ]
  interest_rates = [
    float(_safe_float(item.get("interest_rate")) or 0.0)
    for item in rows
    if float(_safe_float(item.get("interest_rate")) or 0.0) > 0.0
  ]
  max_interest_rate = max(interest_rates) if interest_rates else 0.0
  quarter_envelopes = [
    item for item in (envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
  ]
  debt_ratios = [
    float(_safe_float(((item.get("capital_structure") or {}) if isinstance(item.get("capital_structure"), dict) else {}).get("debt_ratio")) or 0.0)
    for item in quarter_envelopes
  ]
  max_debt_ratio = max(debt_ratios) if debt_ratios else 0.0
  gap_count = len(set(residual_gap_quarters))
  chronic_gap = bool(gap_count >= 5)
  debt_drag_material = bool(max_interest_rate >= 0.03)
  leverage_material = bool(max_debt_ratio >= 0.55)
  external_equity_justified = bool(chronic_gap or leverage_material)
  allowed_sources = [str(item).strip() for item in _CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS if str(item).strip()]
  excluded_sources: List[str] = []
  if chronic_gap and debt_drag_material and _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID in allowed_sources:
    allowed_sources = [
      lever_id for lever_id in allowed_sources
      if lever_id != _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID
    ]
    excluded_sources.append(_CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID)
  if not external_equity_justified and _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID in allowed_sources:
    allowed_sources = [
      lever_id for lever_id in allowed_sources
      if lever_id != _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID
    ]
    excluded_sources.append(_CASH_STRATEGY_OTHER_EQUITY_LEVER_ID)
  policy_reasons: List[str] = []
  if _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID in excluded_sources:
    policy_reasons.append(
      "Chronic liquidity gaps with material debt interest must not be solved with new debt because FINMO interest drag can reopen later cash-buffer violations."
    )
  else:
    policy_reasons.append(
      "Debt issuance remains available because the liquidity gap is not chronic or interest drag is not material."
    )
  if _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID in excluded_sources:
    policy_reasons.append(
      "Other Equity is reserved for outside-investor funding and is only available for chronic liquidity gaps or materially leveraged capital structures."
    )
  elif _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID in allowed_sources:
    policy_reasons.append(
      "Other Equity is available because the gap is chronic or leverage is material enough to justify outside-investor funding."
    )
  return {
    "contract_version": "cash_strategy_funding_source_policy_v1",
    "allowed_funding_source_lever_ids": allowed_sources,
    "excluded_funding_source_lever_ids": excluded_sources,
    "chronic_liquidity_gap": chronic_gap,
    "residual_gap_quarter_count": gap_count,
    "max_interest_rate": round(float(max_interest_rate), 6),
    "max_debt_ratio": round(float(max_debt_ratio), 2),
    "debt_interest_drag_material": debt_drag_material,
    "external_equity_justified": external_equity_justified,
    "external_equity_semantics": (
      "Other Equity means outside investor capital such as angel, VC, silent partners, crowdfunding, "
      "or another investor ownership stake. It is not routine working-capital funding."
    ),
    "owner_capital_semantics": "Owner's Capital means owner/founder/member/insider capital contributions.",
    "policy_reason": " ".join(policy_reasons),
  }

def _cash_strategy_lever_bounds(
  *,
  selected_cash_strategy: Any,
  violation_envelope: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  strategy = _canonical_cash_strategy_value(selected_cash_strategy) or "balanced"
  envelope = violation_envelope if isinstance(violation_envelope, dict) else {}
  quarter_envelopes = {
    int(_safe_float(item.get("quarter_index")) or 0): item
    for item in (envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  quarter_list = [
    int(_safe_float(item) or 0)
    for item in (envelope.get("allowed_review_quarters") or [])
    if int(_safe_float(item) or 0) >= 1 and int(_safe_float(item) or 0) in quarter_envelopes
  ]
  lever_bounds: Dict[str, List[Dict[str, Any]]] = {lever_id: [] for lever_id in _CASH_STRATEGY_ALLOWED_LEVER_IDS}
  for quarter_index in quarter_list:
    quarter_payload = quarter_envelopes.get(quarter_index) or {}
    residual_gap = int(round(float(_safe_float(quarter_payload.get("residual_funding_gap")) or 0.0)))
    carryforward_headroom = int(round(float(_safe_float(quarter_payload.get("cumulative_support_headroom")) or 0.0)))
    current_values = (
      quarter_payload.get("effective_current_values")
      if isinstance(quarter_payload.get("effective_current_values"), dict)
      else {}
    )
    debt_repayment_current = int(round(float(_safe_float(current_values.get(_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID)) or 0.0)))
    debt_issuance_current = int(round(float(_safe_float(current_values.get(_CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID)) or 0.0)))
    owners_capital_current = int(round(float(_safe_float(current_values.get(_CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID)) or 0.0)))
    other_equity_current = int(round(float(_safe_float(current_values.get(_CASH_STRATEGY_OTHER_EQUITY_LEVER_ID)) or 0.0)))
    distributions_current = int(round(float(_safe_float(current_values.get(_CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID)) or 0.0)))
    deployable_surplus = int(round(float(_safe_float(quarter_payload.get("deployable_surplus_above_ceiling")) or 0.0)))
    max_additional_debt_paydown = int(round(float(_safe_float(quarter_payload.get("max_additional_debt_paydown")) or 0.0)))
    max_additional_distribution = int(round(float(_safe_float(quarter_payload.get("max_additional_distribution")) or 0.0)))
    cash_policy = quarter_payload.get("cash_policy") if isinstance(quarter_payload.get("cash_policy"), dict) else {}

    lever_bounds[_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID].append(
      {
        "quarter_index": quarter_index,
        "current_value": debt_repayment_current,
        "min_value": debt_repayment_current,
        "max_value": int(debt_repayment_current + max_additional_debt_paydown),
        "supporting_metrics": {
          "buffer": int(round(float(_safe_float(quarter_payload.get("buffer")) or 0.0))),
          "cash_ceiling": int(round(float(_safe_float(quarter_payload.get("cash_ceiling")) or 0.0))),
          "ending_cash_after_hard_rules": int(round(float(_safe_float(quarter_payload.get("ending_cash_after_hard_rules")) or 0.0))),
          "residual_funding_gap": residual_gap,
          "deployable_surplus_above_ceiling": deployable_surplus,
          "max_additional_debt_paydown": max_additional_debt_paydown,
          "cash_support_multiplier": round(
            float(_safe_float(quarter_payload.get("debt_cash_support_multiplier")) or 1.0),
            6,
          ),
          "cash_support_per_1000": int(round(float(_safe_float(quarter_payload.get("debt_cash_support_per_1000")) or 1000.0))),
          "allowed_action": "increase_repayment_for_surplus_deployment_only; minimum scheduled debt service is Python-owned and cannot be reduced by cash strategy",
        },
      }
    )
    lever_bounds[_CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID].append(
      {
        "quarter_index": quarter_index,
        "current_value": distributions_current,
        "min_value": 0,
        "max_value": int(distributions_current + max_additional_distribution),
        "supporting_metrics": {
          "buffer": int(round(float(_safe_float(quarter_payload.get("buffer")) or 0.0))),
          "cash_ceiling": int(round(float(_safe_float(quarter_payload.get("cash_ceiling")) or 0.0))),
          "ending_cash_after_hard_rules": int(round(float(_safe_float(quarter_payload.get("ending_cash_after_hard_rules")) or 0.0))),
          "residual_funding_gap": residual_gap,
          "deployable_surplus_above_ceiling": deployable_surplus,
          "max_additional_distribution": max_additional_distribution,
          "allowed_action": "increase_distributions_only_from_surplus_above_strategy_cash_ceiling",
          "strategy": strategy,
        },
      }
    )
    lever_bounds[_CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID].append(
      {
        "quarter_index": quarter_index,
        "current_value": debt_issuance_current,
        "min_value": debt_issuance_current,
        "max_value": int(debt_issuance_current + carryforward_headroom),
        "supporting_metrics": {
          "buffer": int(round(float(_safe_float(quarter_payload.get("buffer")) or 0.0))),
          "cash_ceiling": int(round(float(_safe_float(quarter_payload.get("cash_ceiling")) or 0.0))),
          "ending_cash_after_hard_rules": int(round(float(_safe_float(quarter_payload.get("ending_cash_after_hard_rules")) or 0.0))),
          "residual_funding_gap": residual_gap,
          "carryforward_headroom": carryforward_headroom,
          "cash_support_multiplier": round(
            float(_safe_float(quarter_payload.get("debt_cash_support_multiplier")) or 1.0),
            6,
          ),
          "cash_support_per_1000": int(round(float(_safe_float(quarter_payload.get("debt_cash_support_per_1000")) or 1000.0))),
          "soft_capital_structure_guidance": copy.deepcopy(quarter_payload.get("soft_capital_structure_guidance") or {}),
        },
      }
    )
    lever_bounds[_CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID].append(
      {
        "quarter_index": quarter_index,
        "current_value": owners_capital_current,
        "min_value": owners_capital_current,
        "max_value": int(owners_capital_current + carryforward_headroom),
        "supporting_metrics": {
          "buffer": int(round(float(_safe_float(quarter_payload.get("buffer")) or 0.0))),
          "cash_ceiling": int(round(float(_safe_float(quarter_payload.get("cash_ceiling")) or 0.0))),
          "ending_cash_after_hard_rules": int(round(float(_safe_float(quarter_payload.get("ending_cash_after_hard_rules")) or 0.0))),
          "residual_funding_gap": residual_gap,
          "carryforward_headroom": carryforward_headroom,
          "capital_structure": copy.deepcopy(quarter_payload.get("capital_structure") or {}),
        },
      }
    )
    lever_bounds[_CASH_STRATEGY_OTHER_EQUITY_LEVER_ID].append(
      {
        "quarter_index": quarter_index,
        "current_value": other_equity_current,
        "min_value": other_equity_current,
        "max_value": int(other_equity_current + carryforward_headroom),
        "supporting_metrics": {
          "buffer": int(round(float(_safe_float(quarter_payload.get("buffer")) or 0.0))),
          "cash_ceiling": int(round(float(_safe_float(quarter_payload.get("cash_ceiling")) or 0.0))),
          "ending_cash_after_hard_rules": int(round(float(_safe_float(quarter_payload.get("ending_cash_after_hard_rules")) or 0.0))),
          "residual_funding_gap": residual_gap,
          "carryforward_headroom": carryforward_headroom,
          "capital_structure": copy.deepcopy(quarter_payload.get("capital_structure") or {}),
        },
      }
    )
  return {
    "contract_version": "cash_strategy_lever_bounds_v2",
    "allowed_quarters": quarter_list,
    "lever_bounds": lever_bounds,
  }

def _build_cash_strategy_review_context_payload(
  *,
  draft_id: str,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  prompt_file: str,
  solved_model_input_json: Optional[Dict[str, Any]],
  solved_finmo_json: Optional[Dict[str, Any]],
  controller_resolution_state: Optional[Dict[str, Any]] = None,
  prior_numeric_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.numeric_execution import build_numeric_solver_contract  # type: ignore
  except Exception:
    from numeric_execution import build_numeric_solver_contract  # type: ignore
  business = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  model_input = solved_model_input_json if isinstance(solved_model_input_json, dict) else {}
  finmo = solved_finmo_json if isinstance(solved_finmo_json, dict) else {}
  selected_cash_strategy = _resolved_cash_strategy(financials)
  cash_pass_phase_contract = _cash_pass_phase_contract(financials_json=financials)
  lever_catalog = _cash_strategy_financing_review_catalog(model_input)
  lever_ids = [str(item.get("lever_id") or "").strip() for item in lever_catalog if str(item.get("lever_id") or "").strip()]
  section_counts: Dict[str, int] = {}
  for item in lever_catalog:
    section_name = str(item.get("section") or "").strip() or "unknown"
    section_counts[section_name] = int(section_counts.get(section_name) or 0) + 1
  issue_status_records = _controller_state_issue_status_records(controller_resolution_state)
  numeric_solver_contract = build_numeric_solver_contract(
    planning_mode=planning_mode,
    planning_mode_reason=planning_mode_reason,
    selected_cash_strategy=selected_cash_strategy,
    issue_status_records=copy.deepcopy(issue_status_records),
    writable_lever_catalog=copy.deepcopy(lever_catalog),
    current_model_input_json=copy.deepcopy(model_input),
    current_finmo_json=copy.deepcopy(finmo),
    pass_name="cash_strategy_review",
    contract_scope="cash_strategy_review",
  )
  violation_envelope = _cash_strategy_planning_violation_envelope(
    selected_cash_strategy=selected_cash_strategy,
    finmo_payload=copy.deepcopy(finmo),
    model_input_json=copy.deepcopy(model_input),
  )
  debt_schedule_snapshot = _cash_strategy_debt_schedule_snapshot(
    finmo_payload=copy.deepcopy(finmo),
    model_input_json=copy.deepcopy(model_input),
  )
  minimum_debt_schedule_plan = _cash_pass_minimum_debt_schedule_plan(
    model_input_json=copy.deepcopy(model_input),
    finmo_payload=copy.deepcopy(finmo),
    financials_json=copy.deepcopy(financials),
    selected_cash_strategy=selected_cash_strategy,
  )
  funding_source_policy = _cash_strategy_funding_source_policy(
    violation_envelope=copy.deepcopy(violation_envelope),
    debt_schedule_snapshot=copy.deepcopy(debt_schedule_snapshot),
  )
  allowed_quarters = [
    int(_safe_float(item) or 0)
    for item in (violation_envelope.get("allowed_review_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  quarter_metrics = _cash_review_quarter_metrics(finmo)
  ending_cash_series = [int(round(float(_safe_float(item.get("ending_cash")) or 0.0))) for item in quarter_metrics]
  return {
    "contract_version": "cash_strategy_review_context_v2",
    "status": "ready",
    "review_required": True,
    "review_role": "mandatory_post_solve_cash_strategy_review",
    "draft_id": str(draft_id or "").strip(),
    "planning_mode": str(planning_mode or "").strip(),
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "prompt_file": str(prompt_file or "").strip(),
    "selected_cash_strategy": selected_cash_strategy,
    "cash_pass_phase_contract": copy.deepcopy(cash_pass_phase_contract),
    "business_snapshot": {
      "business_name": str(business.get("name") or business.get("business_name") or "").strip(),
      "business_type": str(ops.get("business_type") or "").strip(),
      "business_stage": str(ops.get("business_stage") or "").strip(),
      "capacity_driver": str(ops.get("capacity_driver") or "").strip(),
      "unit_name": str(ops.get("unit_name") or "").strip(),
      "sales_modality": str(ops.get("sales_modality") or "").strip(),
      "geographic_scope": str(ops.get("geographic_scope") or "").strip(),
    },
    "source_artifacts": {
      "model_input_json_field": "model_input_json",
      "finmo_json_field": "finmo_json",
      "solved_model_input_persisted": bool(model_input),
      "solved_finmo_persisted": bool(finmo),
    },
    "writable_lever_catalog": {
      "lever_count": len(lever_ids),
      "section_counts": section_counts,
      "lever_ids": lever_ids,
      "entries": copy.deepcopy(lever_catalog),
    },
    "allowed_quarters": copy.deepcopy(allowed_quarters),
    "strategy_policy": copy.deepcopy(violation_envelope.get("strategy_policy") or {}),
    "funding_source_policy": copy.deepcopy(funding_source_policy),
    "cash_violation_envelope": copy.deepcopy(violation_envelope),
    "debt_schedule_snapshot": copy.deepcopy(debt_schedule_snapshot),
    "minimum_debt_schedule_plan": copy.deepcopy(minimum_debt_schedule_plan),
    "required_funding_quarters": _cash_strategy_required_funding_quarters(
      copy.deepcopy(violation_envelope)
    ),
    "summary_metrics": _cash_strategy_summary_metrics(
      selected_cash_strategy=selected_cash_strategy,
      violation_envelope=copy.deepcopy(violation_envelope),
    ),
    "lever_bounds": _cash_strategy_lever_bounds(
      selected_cash_strategy=selected_cash_strategy,
      violation_envelope=copy.deepcopy(violation_envelope),
    ),
    "quarter_metrics": quarter_metrics,
    "cash_profile_summary": {
      "quarter_count": len(quarter_metrics),
      "cash_peak": max(ending_cash_series) if ending_cash_series else 0,
      "cash_trough": min(ending_cash_series) if ending_cash_series else 0,
      "ending_cash_final": ending_cash_series[-1] if ending_cash_series else 0,
    },
    "prior_numeric_solver_feedback": copy.deepcopy(prior_numeric_feedback or {}),
    "numeric_solver_contract": copy.deepcopy(numeric_solver_contract),
    "validation_requirements": {
      "ending_cash_must_be_greater_than_or_equal_to_buffer": True,
      "no_distributions_when_cash_is_below_or_equal_to_buffer": True,
      "do_not_validate_on_debt_to_equity_ratio": True,
    },
  }

def _build_cash_pass_controller_resolution_state(
  *,
  phase: str,
  base_controller_resolution_state: Optional[Dict[str, Any]] = None,
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
  cash_post_validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  base_state = base_controller_resolution_state if isinstance(base_controller_resolution_state, dict) else {}
  context = cash_strategy_review_context if isinstance(cash_strategy_review_context, dict) else {}
  decision = cash_strategy_review_decision if isinstance(cash_strategy_review_decision, dict) else {}
  plan = cash_strategy_second_pass_plan if isinstance(cash_strategy_second_pass_plan, dict) else {}
  result = cash_strategy_second_pass_result if isinstance(cash_strategy_second_pass_result, dict) else {}
  post_validation = cash_post_validation if isinstance(cash_post_validation, dict) else {}
  phase_name = str(phase or "").strip() or "cash_pass_running"

  def _issue_record(issue_code: str, *, quarters: Optional[List[int]] = None, detail: str = "") -> Dict[str, Any]:
    clean_code = str(issue_code or "").strip().lower()
    clean_quarters = sorted(
      {
        int(_safe_float(item) or 0)
        for item in (quarters or [])
        if int(_safe_float(item) or 0) >= 1
      }
    )
    return {
      "issue_code": clean_code,
      "issue_title": clean_code,
      "status": "remaining",
      "severity": "hard",
      "phase": "cash_pass",
      "problem_quarters": clean_quarters,
      "remaining_problem_quarters": clean_quarters,
      "verification_reason": str(detail or "").strip(),
    }

  issue_records_by_code: Dict[str, Dict[str, Any]] = {}

  def _add_issue(issue_code: str, *, quarters: Optional[List[int]] = None, detail: str = "") -> None:
    clean_code = _cash_table_issue_code(issue_code)
    if not clean_code:
      return
    if not post_intake_issue_has_phase(clean_code, "cash_pass"):
      raise RuntimeError(
        "cash_pass_issue_code_not_table_backed: "
        + json.dumps(
          {
            "issue_code": clean_code,
            "mapping_table": "post_intak_mapping_lookup",
            "detail": "Cash pass can only emit issue codes owned by the SQL mapping table.",
          },
          ensure_ascii=False,
        )
      )
    incoming = _issue_record(clean_code, quarters=quarters, detail=detail)
    existing = issue_records_by_code.get(clean_code)
    if not existing:
      issue_records_by_code[clean_code] = incoming
      return
    merged_quarters = sorted(
      {
        *[
          int(_safe_float(item) or 0)
          for item in (existing.get("problem_quarters") or [])
          if int(_safe_float(item) or 0) >= 1
        ],
        *[
          int(_safe_float(item) or 0)
          for item in (incoming.get("problem_quarters") or [])
          if int(_safe_float(item) or 0) >= 1
        ],
      }
    )
    existing["problem_quarters"] = merged_quarters
    existing["remaining_problem_quarters"] = merged_quarters
    if detail and not str(existing.get("verification_reason") or "").strip():
      existing["verification_reason"] = str(detail).strip()

  required_funding_quarters = [
    int(_safe_float(item.get("quarter_index")) or 0)
    for item in (context.get("required_funding_quarters") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  if required_funding_quarters:
    _add_issue(
      "liquidity_failure",
      quarters=required_funding_quarters,
      detail="Cash pass has required funding quarters to resolve.",
    )
  envelope = context.get("cash_violation_envelope") if isinstance(context.get("cash_violation_envelope"), dict) else {}
  distribution_violation_quarters = [
    int(_safe_float(item.get("quarter_index")) or 0)
    for item in (envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
    and bool(item.get("distribution_violation"))
    and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  if distribution_violation_quarters:
    _add_issue(
      "funding_structure_mismatch",
      quarters=distribution_violation_quarters,
      detail="Cash pass must remove distributions that violate the selected cash posture.",
    )

  if decision and _cash_strategy_fail_flags_from_review_payload(decision):
    _add_issue(
      "funding_structure_mismatch",
      detail="GPT cash strategy review did not satisfy the mandatory cash contract.",
    )
  for flag in [str(item).strip() for item in (plan.get("translation_fail_flags") or []) if str(item).strip()]:
    _add_issue(
      _cash_table_issue_code(flag),
      detail=f"Cash strategy translation failed: {flag}",
    )
  for flag in [str(item).strip() for item in (result.get("fail_flags") or []) if str(item).strip()]:
    _add_issue(
      _cash_table_issue_code(flag),
      detail=f"Cash strategy result failed: {flag}",
    )
  for rule_code in [str(item).strip() for item in (post_validation.get("failed_rule_codes") or []) if str(item).strip()]:
    _add_issue(_cash_table_issue_code(rule_code), detail="Cash post-validation failed this hard rule.")
  cash_buffer_quarters = [
    int(_safe_float(item.get("quarter_index")) or 0)
    for item in (post_validation.get("cash_buffer_violations") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  if cash_buffer_quarters:
    _add_issue(
      "liquidity_failure",
      quarters=cash_buffer_quarters,
      detail="Cash pass finished with ending cash below the required cash buffer.",
    )
  cash_distribution_post_quarters = [
    int(_safe_float(item.get("quarter_index")) or 0)
    for item in (post_validation.get("cash_distribution_violations") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  if cash_distribution_post_quarters:
    _add_issue(
      "funding_structure_mismatch",
      quarters=cash_distribution_post_quarters,
      detail="Cash pass finished with invalid distributions.",
    )
  if post_validation.get("cash_contract_failures"):
    _add_issue(
      "funding_structure_mismatch",
      detail="Cash pass contract validation failed.",
    )

  if str(post_validation.get("status") or "").strip().lower() == "accepted":
    issue_records_by_code = {}

  issue_records = list(issue_records_by_code.values())
  remaining_count = len(issue_records)
  try:
    last_review_iteration = int(float(base_state.get("last_review_iteration")))
  except Exception:
    last_review_iteration = None
  return {
    "contract_version": "cash_pass_controller_resolution_state_v1",
    "status": phase_name,
    "phase": "cash_pass",
    "selected_cash_strategy": str(context.get("selected_cash_strategy") or decision.get("selected_cash_strategy") or "").strip(),
    "last_review_iteration": last_review_iteration,
    "detected_issue_count": remaining_count,
    "remaining_issue_count": remaining_count,
    "resolved_issue_count": 0 if remaining_count else int(_safe_float(base_state.get("resolved_issue_count")) or 0),
    "tolerated_issue_count": 0,
    "iteration_pending_issue_count": remaining_count,
    "all_cleared": remaining_count == 0,
    "remaining_issues": copy.deepcopy(issue_records),
    "issue_status_records": copy.deepcopy(issue_records),
    "cash_pass_visibility": {
      "stage_visible_in_sql": True,
      "required_funding_quarters": copy.deepcopy(required_funding_quarters),
      "cash_buffer_violation_quarters": copy.deepcopy(cash_buffer_quarters),
      "failed_rule_codes": copy.deepcopy(post_validation.get("failed_rule_codes") or []),
      "phase": phase_name,
    },
  }

def _load_cash_strategy_review_prompt() -> str:
  try:
    return _CASH_STRATEGY_REVIEW_PROMPT_PATH.read_text(encoding="utf-8").strip()
  except Exception:
    return (
      "You are the post-solve cash strategy reviewer for a real business plan.\n"
      "You are reviewing an already solved, coherent business model.\n"
      "Your job is to decide whether the solved business visibly reflects the selected cash strategy and, if not, prescribe realistic coordinated management actions using only the provided writable lever ids.\n"
      "Be bold within reason: make the selected strategy visible when the solved economics support it, but do not force reckless or fake moves.\n"
      "Think like actual management of a living business, not like a spreadsheet optimizer.\n"
      "Any recommendation must preserve believable operating continuity of the current business.\n"
      "You may re-time, phase, slow, or scale real business actions, but do not hollow out the business below a believable steady-state operating condition.\n"
      "Do not use writable rows as implicit plugs or balancing placeholders.\n"
      "Do not silently force cash, solvency, profitability, or optics with row tweaks that lack a believable operating story.\n"
      "Capital allocation must read like a real management decision, not hidden model repair.\n"
      "Levers do not operate in silos. When a real-world action requires coordinated changes across multiple rows, return a linked lever package rather than isolated row tweaks.\n"
      "Do not invent lever ids. Do not rebuild the whole business from scratch."
    )

def _cash_strategy_review_schema(
  allowed_lever_ids: List[str],
  allowed_quarters: List[int],
  required_funding_quarters: Optional[List[int]] = None,
  funding_source_lever_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
  funding_quarter_enum = list(required_funding_quarters or allowed_quarters or [1])
  funding_lever_enum = list(funding_source_lever_ids or allowed_lever_ids or [""])
  return _post_intake_contract_schema(
    "cash_strategy_review",
    field_schema_overrides={
      "recommended_adjustments[].lever_id": {"type": "string", "enum": allowed_lever_ids or [""]},
      "recommended_adjustments[].timing_start_q": {"type": "integer", "enum": allowed_quarters or [1]},
      "recommended_adjustments[].timing_end_q": {"type": "integer", "enum": allowed_quarters or [1]},
      "quarter_funding_plan[].quarter_index": {"type": "integer", "enum": funding_quarter_enum},
      "quarter_funding_plan[].required_funding_gap": {"type": "integer", "minimum": 0},
      "quarter_funding_plan[].expected_buffer": {"type": "integer", "minimum": 0},
      "funding_sources[].lever_id": {"type": "string", "enum": funding_lever_enum},
      "funding_sources[].amount": {"type": "integer", "minimum": 0},
    },
  )

def _cash_strategy_review_failure_payload(
  *,
  selected_cash_strategy: str,
  prompt_file: str,
  status: str,
  detail: str = "",
  prompt_trace: Optional[Dict[str, Any]] = None,
  raw_openai_response: Optional[Dict[str, Any]] = None,
  decision_source: str = "gpt",
) -> Dict[str, Any]:
  return {
    "contract_version": "cash_strategy_review_decision_v2",
    "status": status,
    "prompt_file": prompt_file,
    "selected_cash_strategy": str(selected_cash_strategy or "").strip(),
    "review_status": "not_completed",
    "detail": str(detail or "").strip(),
    "decision_source": str(decision_source or "").strip() or "gpt",
    "prompt_trace": copy.deepcopy(prompt_trace or {}),
    "raw_openai_response": copy.deepcopy(raw_openai_response or {}),
    "decision": {},
  }

def _cash_strategy_gross_up_effective_support(amount: int, multiplier: float) -> int:
  target = max(0, int(round(float(amount or 0))))
  factor = float(multiplier or 1.0)
  if target <= 0:
    return 0
  if factor <= 0.0:
    return target
  candidate = max(0, int(round(target / factor)))
  for value in range(max(0, candidate - 3), candidate + 4):
    if int(round(value * factor)) == target:
      return int(value)
  return int(math.ceil(target / factor))

def _normalize_cash_strategy_review_decision_from_funding_plan(
  *,
  parsed: Optional[Dict[str, Any]],
  cash_strategy_review_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  decision = copy.deepcopy(parsed if isinstance(parsed, dict) else {})
  if str(decision.get("recommendation_mode") or "").strip().lower() != "adjust":
    return decision
  context_payload = cash_strategy_review_context if isinstance(cash_strategy_review_context, dict) else {}
  required_funding_quarters = {
    int(_safe_float(item.get("quarter_index")) or 0)
    for item in (context_payload.get("required_funding_quarters") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  lever_bounds_payload = (
    context_payload.get("lever_bounds")
    if isinstance(context_payload.get("lever_bounds"), dict)
    else {}
  )
  funding_source_policy = (
    context_payload.get("funding_source_policy")
    if isinstance(context_payload.get("funding_source_policy"), dict)
    else {}
  )
  policy_allowed_funding_sources = {
    str(item).strip()
    for item in (
      funding_source_policy.get("allowed_funding_source_lever_ids")
      or _CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS
    )
    if str(item).strip()
  }
  lever_bound_lookup: Dict[tuple[str, int], Dict[str, Any]] = {}
  for lever_id, rows in (lever_bounds_payload.get("lever_bounds") or {}).items():
    for row in rows or []:
      if not isinstance(row, dict):
        continue
      quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
      if quarter_index >= 1:
        lever_bound_lookup[(str(lever_id or "").strip(), quarter_index)] = row
  derived_adjustments: List[Dict[str, Any]] = []
  if required_funding_quarters:
    for quarter_plan in (decision.get("quarter_funding_plan") or []):
      if not isinstance(quarter_plan, dict):
        continue
      quarter_index = int(_safe_float(quarter_plan.get("quarter_index")) or 0)
      if quarter_index not in required_funding_quarters:
        continue
      funding_sources = [
        source for source in (quarter_plan.get("funding_sources") or [])
        if isinstance(source, dict)
      ]
      if len(funding_sources) != 1:
        continue
      source = funding_sources[0]
      lever_id = str(source.get("lever_id") or "").strip()
      amount = int(round(float(_safe_float(source.get("amount")) or 0.0)))
      if not lever_id:
        continue
      exact_value = amount
      if lever_id == _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID:
        bound = lever_bound_lookup.get((lever_id, quarter_index)) or {}
        supporting_metrics = bound.get("supporting_metrics") if isinstance(bound.get("supporting_metrics"), dict) else {}
        multiplier = float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0)
        exact_value = _cash_strategy_gross_up_effective_support(amount, multiplier)
      derived_adjustments.append(
        {
          "lever_id": lever_id,
          "timing_start_q": quarter_index,
          "timing_end_q": quarter_index,
          "exact_value": int(exact_value),
          "business_reason": str(quarter_plan.get("business_reason") or "Derived deterministically from quarter_funding_plan.").strip(),
        }
      )
  # Only liquidity funding gaps are translated from the pre-action GPT review.
  # Surplus deployment is intentionally applied later from the rebuilt
  # post-action FINMO state so early distributions cannot overdraw future cash.
  decision["recommended_adjustments"] = derived_adjustments
  return decision

def _cash_strategy_review_decision_contract_error(
  *,
  parsed: Optional[Dict[str, Any]],
  cash_strategy_review_context: Optional[Dict[str, Any]],
) -> Optional[str]:
  decision = parsed if isinstance(parsed, dict) else {}
  table_contract_errors = _post_intake_contract_payload_errors(
    contract_name="cash_strategy_review",
    payload=decision,
  )
  if table_contract_errors:
    return (
      "cash_strategy_review_table_contract_invalid: "
      + "; ".join(str(item) for item in table_contract_errors[:20])
    )
  context_payload = cash_strategy_review_context if isinstance(cash_strategy_review_context, dict) else {}
  recommendation_mode = str(decision.get("recommendation_mode") or "").strip().lower()
  if recommendation_mode not in {"maintain", "adjust"}:
    return "recommendation_mode must be either 'maintain' or 'adjust'."
  recommended_adjustments = [
    item for item in (decision.get("recommended_adjustments") or [])
    if isinstance(item, dict)
  ]
  quarter_funding_plan = [
    item for item in (decision.get("quarter_funding_plan") or [])
    if isinstance(item, dict)
  ]
  required_funding_quarters = {
    int(_safe_float(item.get("quarter_index")) or 0): item
    for item in (context_payload.get("required_funding_quarters") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  lever_bounds_payload = (
    context_payload.get("lever_bounds")
    if isinstance(context_payload.get("lever_bounds"), dict)
    else {}
  )
  funding_source_policy = (
    context_payload.get("funding_source_policy")
    if isinstance(context_payload.get("funding_source_policy"), dict)
    else {}
  )
  policy_allowed_funding_sources = {
    str(item).strip()
    for item in (
      funding_source_policy.get("allowed_funding_source_lever_ids")
      or _CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS
    )
    if str(item).strip()
  }
  lever_bound_lookup: Dict[tuple[str, int], Dict[str, Any]] = {}
  for lever_id, rows in (lever_bounds_payload.get("lever_bounds") or {}).items():
    for row in rows or []:
      if not isinstance(row, dict):
        continue
      quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
      lever_bound_lookup[(str(lever_id or "").strip(), quarter_index)] = row
  if recommendation_mode == "maintain":
    if recommended_adjustments:
      return "recommendation_mode='maintain' must not include recommended_adjustments."
    if quarter_funding_plan:
      return "recommendation_mode='maintain' must not include quarter_funding_plan."
    return None
  if required_funding_quarters and not recommended_adjustments:
    return "Violating quarters require financing adjustments, so recommended_adjustments must not be empty."
  declared_quarter_plan = {
    int(_safe_float(item.get("quarter_index")) or 0): item
    for item in quarter_funding_plan
    if int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  missing_quarters = [
    quarter for quarter in sorted(required_funding_quarters.keys())
    if quarter not in declared_quarter_plan
  ]
  if missing_quarters:
    return f"quarter_funding_plan must explicitly cover every required funding quarter. missing={missing_quarters}."
  adjustment_by_lever_quarter: Dict[tuple[str, int], Dict[str, Any]] = {}
  for adjustment in recommended_adjustments:
    lever_id = str(adjustment.get("lever_id") or "").strip()
    start_q = int(_safe_float(adjustment.get("timing_start_q")) or 0)
    end_q = int(_safe_float(adjustment.get("timing_end_q")) or start_q)
    if not lever_id or start_q < 1 or end_q < start_q:
      continue
    for quarter_index in range(start_q, end_q + 1):
      adjustment_by_lever_quarter[(lever_id, quarter_index)] = adjustment
      bound = lever_bound_lookup.get((lever_id, quarter_index))
      if not isinstance(bound, dict):
        return (
          f"recommended_adjustments {lever_id} Q{quarter_index} is outside the deterministic cash lever bounds."
        )
      exact_value = int(round(float(_safe_float(adjustment.get("exact_value")) or 0.0)))
      current_value = int(round(float(_safe_float(bound.get("current_value")) or 0.0)))
      min_value = int(round(float(_safe_float(bound.get("min_value")) or 0.0)))
      max_value = int(round(float(_safe_float(bound.get("max_value")) or current_value)))
      financing_amount_lever_ids = {
        _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID,
        _CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID,
        _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID,
      }
      candidate_value = int(current_value + max(exact_value, 0)) if lever_id in financing_amount_lever_ids else exact_value
      if candidate_value < min_value or candidate_value > max_value:
        return (
          f"recommended_adjustments {lever_id} Q{quarter_index} is outside allowed bounds. "
          f"candidate_value={candidate_value} min_value={min_value} max_value={max_value}."
        )
      supporting_metrics = bound.get("supporting_metrics") if isinstance(bound.get("supporting_metrics"), dict) else {}
      residual_gap = int(round(float(_safe_float(supporting_metrics.get("residual_funding_gap")) or 0.0)))
      if (
        lever_id == _CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID
        and candidate_value > current_value
        and residual_gap > 0
      ):
        return (
          f"recommended_adjustments {lever_id} Q{quarter_index} cannot increase distributions while "
          f"the quarter has residual_funding_gap={residual_gap}."
        )
  for quarter_index, required_payload in required_funding_quarters.items():
    quarter_plan = declared_quarter_plan.get(quarter_index) or {}
    funding_sources = [
      item for item in (quarter_plan.get("funding_sources") or [])
      if isinstance(item, dict)
    ]
    if not funding_sources:
      return f"quarter_funding_plan Q{quarter_index} must include at least one funding source."
    if len(funding_sources) != 1:
      return (
        f"quarter_funding_plan Q{quarter_index} must include exactly one funding source. "
        "Use a single source per quarter and make its amount equal the required funding gap exactly."
      )
    funding_lever_id = str((funding_sources[0] or {}).get("lever_id") or "").strip()
    if funding_lever_id not in set(_CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS):
      return (
        f"quarter_funding_plan Q{quarter_index} funding source {funding_lever_id or 'missing'} is not allowed. "
        "Use only debt issuance, debt repayment reduction, owner's capital, or policy-justified outside-investor other equity."
      )
    if policy_allowed_funding_sources and funding_lever_id not in policy_allowed_funding_sources:
      return (
        f"quarter_funding_plan Q{quarter_index} funding source {funding_lever_id} is outside the deterministic "
        f"cash funding source policy. allowed={sorted(policy_allowed_funding_sources)}."
      )
    declared_gap = int(round(float(_safe_float(quarter_plan.get("required_funding_gap")) or 0.0)))
    expected_gap = int(round(float(_safe_float(required_payload.get("required_incremental_funding_after_hard_rules")) or 0.0)))
    if declared_gap != expected_gap:
      return (
        f"quarter_funding_plan Q{quarter_index} required_funding_gap must match the Python-required funding gap. "
        f"expected={expected_gap} declared={declared_gap}."
      )
    expected_buffer = int(round(float(_safe_float(quarter_plan.get("expected_buffer")) or 0.0)))
    required_buffer = int(round(float(_safe_float(required_payload.get("buffer")) or 0.0)))
    if expected_buffer != required_buffer:
      return (
        f"quarter_funding_plan Q{quarter_index} expected_buffer must match the Python buffer. "
        f"expected={required_buffer} declared={expected_buffer}."
      )
    expected_ending_cash = int(round(float(_safe_float(quarter_plan.get("expected_ending_cash_after_actions")) or 0.0)))
    if expected_ending_cash < required_buffer:
      return (
        f"quarter_funding_plan Q{quarter_index} expected_ending_cash_after_actions must be at least the required buffer. "
        f"ending_cash={expected_ending_cash} buffer={required_buffer}."
      )
    declared_total = sum(int(round(float(_safe_float(item.get("amount")) or 0.0))) for item in funding_sources)
    if declared_total != expected_gap:
      return (
        f"quarter_funding_plan Q{quarter_index} declared funding sources must sum exactly to the required funding gap. "
        f"declared_total={declared_total} required_gap={expected_gap}."
      )
    funding_source = funding_sources[0] if funding_sources else {}
    funding_lever_id = str(funding_source.get("lever_id") or "").strip()
    funding_amount = int(round(float(_safe_float(funding_source.get("amount")) or 0.0)))
    matching_adjustment = adjustment_by_lever_quarter.get((funding_lever_id, quarter_index))
    if not isinstance(matching_adjustment, dict):
      return (
        f"quarter_funding_plan Q{quarter_index} funding source {funding_lever_id} must have a matching "
        "recommended_adjustment for the same lever and quarter."
      )
    adjustment_exact_value = int(round(float(_safe_float(matching_adjustment.get("exact_value")) or 0.0)))
    bound = lever_bound_lookup.get((funding_lever_id, quarter_index)) or {}
    current_value = int(round(float(_safe_float(bound.get("current_value")) or 0.0)))
    max_value = int(round(float(_safe_float(bound.get("max_value")) or current_value)))
    supporting_metrics = bound.get("supporting_metrics") if isinstance(bound.get("supporting_metrics"), dict) else {}
    cash_support_multiplier = float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0)
    if funding_lever_id in {_CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID, _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID}:
      if adjustment_exact_value != funding_amount:
        return (
          f"quarter_funding_plan Q{quarter_index} {funding_lever_id} exact_value must be the incremental funding amount, "
          f"not the final balance-sheet value. exact_value={adjustment_exact_value} funding_amount={funding_amount}."
        )
      headroom = max(0, max_value - current_value)
      if funding_amount > headroom:
        return (
          f"quarter_funding_plan Q{quarter_index} {funding_lever_id} funding_amount exceeds available headroom. "
          f"amount={funding_amount} headroom={headroom} current_value={current_value} max_value={max_value}."
        )
    elif funding_lever_id == _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID:
      effective_support = int(round(max(adjustment_exact_value, 0) * cash_support_multiplier))
      if effective_support != funding_amount:
        return (
          f"quarter_funding_plan Q{quarter_index} debt issuance exact_value must gross up to funding_amount after interest cash support multiplier. "
          f"exact_value={adjustment_exact_value} effective_support={effective_support} funding_amount={funding_amount} multiplier={round(cash_support_multiplier, 6)}."
        )
  return None

def _run_cash_strategy_review_openai(
  *,
  draft_id: str,
  business_facts: Dict[str, Any],
  ops_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  planning_mode_prompt_file: str,
  first_pass_handoff: Dict[str, Any],
  cash_strategy_review_context: Dict[str, Any],
  solved_model_input_json: Dict[str, Any],
  solved_finmo_json: Dict[str, Any],
  prior_numeric_feedback: Optional[Dict[str, Any]] = None,
  controller_retry_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  prompt_file = "client_intake_and_finmo/prompts/cash_strategy_review/reviewer.md"
  del first_pass_handoff, solved_finmo_json, prior_numeric_feedback, controller_retry_context
  selected_cash_strategy = _resolved_cash_strategy(financials_json)
  prompt_trace: Dict[str, Any] = {}
  api_key = _openai_key()
  if not api_key:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="skipped_missing_openai_key",
      detail="OPENAI_API_KEY is not configured.",
      prompt_trace=prompt_trace,
    )
  context_payload = cash_strategy_review_context if isinstance(cash_strategy_review_context, dict) else {}
  allowed_quarters = [
    int(_safe_float(item) or 0)
    for item in (context_payload.get("allowed_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  allowed_lever_ids = [
    str(item or "").strip()
    for item in (((context_payload.get("writable_lever_catalog") or {}) if isinstance(context_payload.get("writable_lever_catalog"), dict) else {}).get("lever_ids") or [])
    if str(item or "").strip()
  ]
  if not allowed_lever_ids:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_missing_levers",
      detail="No writable lever ids were available for cash strategy review.",
      prompt_trace=prompt_trace,
    )
  if not allowed_quarters:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_missing_quarters",
      detail="No allowed quarter window was available for cash strategy review.",
      prompt_trace=prompt_trace,
    )
  scoped_lever_catalog = copy.deepcopy((((context_payload.get("writable_lever_catalog") or {}) if isinstance(context_payload.get("writable_lever_catalog"), dict) else {}).get("entries") or []))
  solved_lever_values = _solved_lever_value_map(solved_model_input_json)
  scoped_lever_values = _subset_lever_value_map(
    solved_lever_values,
    allowed_lever_ids,
    allowed_quarters,
  )
  scoped_lever_values = {
    lever_id: [
      int(round(float(_safe_float(value) or 0.0)))
      for value in (values or [])
    ]
    for lever_id, values in scoped_lever_values.items()
  }
  required_funding_quarters = [
    copy.deepcopy(item)
    for item in (context_payload.get("required_funding_quarters") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  required_funding_quarter_indexes = [
    int(_safe_float(item.get("quarter_index")) or 0)
    for item in required_funding_quarters
    if int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  required_funding_quarter_set = set(required_funding_quarter_indexes)
  raw_violation_envelope = (
    context_payload.get("cash_violation_envelope")
    if isinstance(context_payload.get("cash_violation_envelope"), dict)
    else {}
  )
  surplus_deployment_quarter_indexes = [
    int(_safe_float(item) or 0)
    for item in (raw_violation_envelope.get("surplus_deployment_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  surplus_deployment_quarter_set = set(surplus_deployment_quarter_indexes)
  decision_quarter_set = set(required_funding_quarter_set) | set(surplus_deployment_quarter_set)
  required_surplus_deployment_quarters = [
    {
      "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
      "required_surplus_deployment": int(round(float(_safe_float(item.get("deployable_surplus_above_ceiling")) or 0.0))),
      "ending_cash_after_hard_rules": int(round(float(_safe_float(item.get("ending_cash_after_hard_rules")) or 0.0))),
      "cash_ceiling": int(round(float(_safe_float(item.get("cash_ceiling")) or 0.0))),
      "max_additional_distribution": int(round(float(_safe_float(item.get("max_additional_distribution")) or 0.0))),
      "max_additional_debt_paydown": int(round(float(_safe_float(item.get("max_additional_debt_paydown")) or 0.0))),
    }
    for item in (raw_violation_envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
    and int(_safe_float(item.get("quarter_index")) or 0) >= 1
    and int(round(float(_safe_float(item.get("deployable_surplus_above_ceiling")) or 0.0))) > 0
  ]
  funding_source_policy = (
    context_payload.get("funding_source_policy")
    if isinstance(context_payload.get("funding_source_policy"), dict)
    else {}
  )
  prompt_allowed_funding_sources = {
    str(item).strip()
    for item in (
      funding_source_policy.get("allowed_funding_source_lever_ids")
      or _CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS
    )
    if str(item).strip()
  }
  prompt_cash_violation_envelope = {
    "contract_version": str(raw_violation_envelope.get("contract_version") or "cash_strategy_violation_envelope_v1"),
    "selected_cash_strategy": str(raw_violation_envelope.get("selected_cash_strategy") or "").strip(),
    "has_violations": bool(raw_violation_envelope.get("has_violations")),
    "violation_quarters": copy.deepcopy(raw_violation_envelope.get("violation_quarters") or []),
    "residual_gap_quarters": copy.deepcopy(raw_violation_envelope.get("residual_gap_quarters") or []),
    "surplus_deployment_quarters": copy.deepcopy(raw_violation_envelope.get("surplus_deployment_quarters") or []),
    "allowed_review_quarters": copy.deepcopy(raw_violation_envelope.get("allowed_review_quarters") or []),
    "capital_structure_guidance": copy.deepcopy(raw_violation_envelope.get("capital_structure_guidance") or {}),
    "validation_requirements": copy.deepcopy(raw_violation_envelope.get("validation_requirements") or {}),
  }
  raw_summary_metrics = (
    context_payload.get("summary_metrics")
    if isinstance(context_payload.get("summary_metrics"), dict)
    else {}
  )
  prompt_summary_metrics = copy.deepcopy(raw_summary_metrics)
  if isinstance(prompt_summary_metrics.get("buffer_quarters"), list) and decision_quarter_set:
    prompt_summary_metrics["buffer_quarters"] = [
      item for item in prompt_summary_metrics.get("buffer_quarters") or []
      if isinstance(item, dict)
      and int(_safe_float(item.get("quarter_index")) or 0) in decision_quarter_set
    ]
  raw_lever_bounds = (
    context_payload.get("lever_bounds")
    if isinstance(context_payload.get("lever_bounds"), dict)
    else {}
  )
  prompt_lever_bounds_rows: Dict[str, List[Dict[str, Any]]] = {}
  surplus_deployment_lever_ids = {
    _CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID,
    _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
  }
  for lever_id, rows in (raw_lever_bounds.get("lever_bounds") or {}).items():
    lever_key = str(lever_id or "").strip()
    if (
      prompt_allowed_funding_sources
      and lever_key not in prompt_allowed_funding_sources
      and not (surplus_deployment_quarter_set and lever_key in surplus_deployment_lever_ids)
    ):
      continue
    compact_rows: List[Dict[str, Any]] = []
    for row in rows or []:
      if not isinstance(row, dict):
        continue
      quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
      if decision_quarter_set and quarter_index not in decision_quarter_set:
        continue
      supporting_metrics = (
        row.get("supporting_metrics")
        if isinstance(row.get("supporting_metrics"), dict)
        else {}
      )
      compact_rows.append(
        {
          "quarter_index": quarter_index,
          "current_value": int(round(float(_safe_float(row.get("current_value")) or 0.0))),
          "min_value": int(round(float(_safe_float(row.get("min_value")) or 0.0))),
          "max_value": int(round(float(_safe_float(row.get("max_value")) or 0.0))),
          "supporting_metrics": {
            "buffer": int(round(float(_safe_float(supporting_metrics.get("buffer")) or 0.0))),
            "cash_ceiling": int(round(float(_safe_float(supporting_metrics.get("cash_ceiling")) or 0.0))),
            "ending_cash_after_hard_rules": int(round(float(_safe_float(supporting_metrics.get("ending_cash_after_hard_rules")) or 0.0))),
            "residual_funding_gap": int(round(float(_safe_float(supporting_metrics.get("residual_funding_gap")) or 0.0))),
            "deployable_surplus_above_ceiling": int(round(float(_safe_float(supporting_metrics.get("deployable_surplus_above_ceiling")) or 0.0))),
            "carryforward_headroom": int(round(float(_safe_float(supporting_metrics.get("carryforward_headroom")) or 0.0))),
            "cash_support_multiplier": round(float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0), 6),
            "allowed_action": str(supporting_metrics.get("allowed_action") or "").strip(),
          },
        }
      )
    if compact_rows:
      prompt_lever_bounds_rows[lever_key] = compact_rows
  raw_debt_schedule = (
    context_payload.get("debt_schedule_snapshot")
    if isinstance(context_payload.get("debt_schedule_snapshot"), dict)
    else {}
  )
  prompt_debt_rows = [
    {
      "quarter_index": int(_safe_float(row.get("quarter_index")) or 0),
      "opening_debt": int(round(float(_safe_float(row.get("opening_debt")) or 0.0))),
      "actual_debt_issuance": int(round(float(_safe_float(row.get("actual_debt_issuance")) or 0.0))),
      "actual_debt_repayment": int(round(float(_safe_float(row.get("actual_debt_repayment")) or 0.0))),
      "closing_debt": int(round(float(_safe_float(row.get("closing_debt")) or 0.0))),
      "interest_rate": round(float(_safe_float(row.get("interest_rate")) or 0.0), 6),
      "interest_expense": int(round(float(_safe_float(row.get("interest_expense")) or 0.0))),
    }
    for row in (raw_debt_schedule.get("rows") or [])
    if isinstance(row, dict)
    and (
      not decision_quarter_set
      or int(_safe_float(row.get("quarter_index")) or 0) in decision_quarter_set
    )
  ]
  prompt_safe_cash_strategy_review_context = {
    "contract_version": str(context_payload.get("contract_version") or "cash_strategy_review_context_v2"),
    "status": str(context_payload.get("status") or "").strip(),
    "review_required": bool(context_payload.get("review_required")),
    "review_role": str(context_payload.get("review_role") or "").strip(),
    "draft_id": str(context_payload.get("draft_id") or "").strip(),
    "planning_mode": str(context_payload.get("planning_mode") or "").strip(),
    "planning_mode_reason": str(context_payload.get("planning_mode_reason") or "").strip(),
    "selected_cash_strategy": str(context_payload.get("selected_cash_strategy") or "").strip(),
    "cash_pass_phase_contract": copy.deepcopy(context_payload.get("cash_pass_phase_contract") or {}),
    "business_snapshot": copy.deepcopy(context_payload.get("business_snapshot") or {}),
    "cash_profile_summary": copy.deepcopy(context_payload.get("cash_profile_summary") or {}),
    "strategy_policy": copy.deepcopy(context_payload.get("strategy_policy") or {}),
    "funding_source_policy": copy.deepcopy(funding_source_policy),
    "cash_violation_envelope": copy.deepcopy(prompt_cash_violation_envelope),
    "debt_schedule_snapshot": {
      "contract_version": str(raw_debt_schedule.get("contract_version") or "cash_strategy_debt_schedule_snapshot_v1"),
      "rows": prompt_debt_rows,
    },
    "required_funding_quarters": copy.deepcopy(required_funding_quarters),
    "required_surplus_deployment_quarters": copy.deepcopy(required_surplus_deployment_quarters),
    "allowed_quarters": copy.deepcopy(allowed_quarters),
    "summary_metrics": copy.deepcopy(prompt_summary_metrics),
    "lever_bounds": {
      "contract_version": str(raw_lever_bounds.get("contract_version") or "cash_strategy_lever_bounds_v2"),
      "allowed_quarters": [
        quarter for quarter in (raw_lever_bounds.get("allowed_quarters") or allowed_quarters)
        if not decision_quarter_set or int(_safe_float(quarter) or 0) in decision_quarter_set
      ],
      "lever_bounds": prompt_lever_bounds_rows,
    },
    "validation_requirements": copy.deepcopy(context_payload.get("validation_requirements") or {}),
  }

  static_cash_prompt = _load_cash_strategy_review_prompt()
  cash_policy_prompt = {
    "selected_cash_strategy": selected_cash_strategy,
    "planning_mode": str(planning_mode or "").strip(),
    "planning_mode_reason": str(planning_mode_reason or "").strip(),
    "business_name": str((business_facts or {}).get("name") or (business_facts or {}).get("business_name") or "").strip(),
    "business_snapshot": copy.deepcopy(context_payload.get("business_snapshot") or {}),
    "strategy_policy": copy.deepcopy(context_payload.get("strategy_policy") or {}),
    "funding_source_policy": copy.deepcopy(funding_source_policy),
    "cash_profile_summary": copy.deepcopy(context_payload.get("cash_profile_summary") or {}),
    "cash_pass_phase_contract": copy.deepcopy(context_payload.get("cash_pass_phase_contract") or {}),
  }
  cash_envelope_prompt = {
    "cash_violation_envelope": copy.deepcopy(prompt_cash_violation_envelope),
    "summary_metrics": copy.deepcopy(prompt_summary_metrics),
    "allowed_quarters": copy.deepcopy(allowed_quarters),
  }
  funding_action_cells_prompt = {
    "required_funding_quarters": copy.deepcopy(required_funding_quarters),
    "required_surplus_deployment_quarters": copy.deepcopy(required_surplus_deployment_quarters),
    "lever_bounds": {
      "contract_version": str(raw_lever_bounds.get("contract_version") or "cash_strategy_lever_bounds_v2"),
      "allowed_quarters": [
        quarter for quarter in (raw_lever_bounds.get("allowed_quarters") or allowed_quarters)
        if not decision_quarter_set or int(_safe_float(quarter) or 0) in decision_quarter_set
      ],
      "lever_bounds": prompt_lever_bounds_rows,
    },
    "writable_lever_current_values": copy.deepcopy(scoped_lever_values),
  }
  user_context = {
    "cash_policy": cash_policy_prompt,
    "cash_envelope": cash_envelope_prompt,
    "liquidity_violation_grid": copy.deepcopy(required_funding_quarters),
    "debt_schedule_summary": copy.deepcopy(prompt_safe_cash_strategy_review_context.get("debt_schedule_snapshot") or {}),
    "funding_action_cells": funding_action_cells_prompt,
    "gpt_contract_field_spec": _post_intake_contract_prompt_spec("cash_strategy_review"),
  }
  prompt_budget = post_intake_gpt_context_request_char_budget(
    contract_name="cash_strategy_review",
    include_phase="cash_pass",
  )
  user_context_chars = len(json.dumps(user_context, ensure_ascii=False))
  if prompt_budget is not None and user_context_chars > int(prompt_budget):
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_prompt_context_budget_exceeded",
      detail=(
        "cash_strategy_review_prompt_context_budget_exceeded: "
        f"user_payload_chars={user_context_chars}; sql_budget={int(prompt_budget)}"
      ),
      prompt_trace={"user_payload_chars": user_context_chars, "sql_budget": int(prompt_budget)},
    )
  system_prompt = post_intake_build_prompt_from_contract(
    "cash_strategy_review",
    context_payload=user_context,
    include_phase="cash_pass",
    static_instruction=static_cash_prompt,
    task_instruction=(
      "Return only JSON matching the SQL-backed cash_strategy_review contract. Use only mapping-table cash levers, "
      "respect the cash policy lookup, and fill only the contract-authorized funding/action rows."
    ),
  )
  prompt_trace = {
    "system_prompt": system_prompt,
    "user_payload": copy.deepcopy(user_context),
  }
  payload = {
    "model": _openai_model(),
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_context, ensure_ascii=False)}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": "cash_strategy_review_decision",
        "schema": _cash_strategy_review_schema(
          allowed_lever_ids,
          allowed_quarters,
          required_funding_quarter_indexes,
          [
            lever_id
            for lever_id in allowed_lever_ids
            if lever_id in (
              set(
                str(item).strip()
                for item in (
                  (
                    context_payload.get("funding_source_policy")
                    if isinstance(context_payload.get("funding_source_policy"), dict)
                    else {}
                  ).get("allowed_funding_source_lever_ids")
                  or _CASH_STRATEGY_FUNDING_SOURCE_LEVER_IDS
                )
                if str(item).strip()
              )
            )
          ],
        ),
        "strict": True,
      }
    },
  }
  raw_openai_response: Dict[str, Any] = {}
  cash_review_deadline_seconds = 45.0
  previous_cash_review_deadline = _set_active_openai_deadline(
    time.perf_counter() + cash_review_deadline_seconds
  )
  try:
    resp = _post_openai(
      url="https://api.openai.com/v1/responses",
      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
      payload=payload,
    )
  except Exception as exc:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_openai_request",
      detail=str(exc),
      prompt_trace=prompt_trace,
    )
  finally:
    _set_active_openai_deadline(previous_cash_review_deadline)
  if resp.status_code >= 400:
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_openai_status",
      detail=resp.text[:1200],
      prompt_trace=prompt_trace,
    )
  raw_openai_response = resp.json() if isinstance(resp.json(), dict) else {"response": resp.text[:4000]}
  parsed = _parse_responses_json_dict(raw_openai_response)
  if not isinstance(parsed, dict):
    return _cash_strategy_review_failure_payload(
      selected_cash_strategy=selected_cash_strategy,
      prompt_file=prompt_file,
      status="failed_parse",
      detail="Unable to parse cash strategy review JSON.",
      prompt_trace=prompt_trace,
      raw_openai_response=raw_openai_response,
    )
  parsed = _normalize_cash_strategy_review_decision_from_funding_plan(
    parsed=parsed,
    cash_strategy_review_context=context_payload,
  )
  parsed = _normalize_post_intake_contract_payload(
    contract_name="cash_strategy_review",
    payload=parsed,
  )
  contract_error = _cash_strategy_review_decision_contract_error(
    parsed=parsed,
    cash_strategy_review_context=context_payload,
  )
  provisional_review_payload = {
    "contract_version": "cash_strategy_review_decision_v2",
    "status": "completed",
    "prompt_file": prompt_file,
    "selected_cash_strategy": selected_cash_strategy,
    "review_status": "completed",
    "decision_source": "gpt",
    "cash_strategy_review_context": copy.deepcopy(context_payload),
    "numeric_solver_contract": copy.deepcopy(
      context_payload.get("numeric_solver_contract")
      if isinstance(context_payload.get("numeric_solver_contract"), dict)
      else {}
    ),
    "prompt_trace": copy.deepcopy(prompt_trace),
    "raw_openai_response": copy.deepcopy(raw_openai_response),
    "detail": "",
    "decision": copy.deepcopy(parsed),
  }
  provisional_plan = _build_cash_strategy_second_pass_plan(
    review_decision_payload=copy.deepcopy(provisional_review_payload),
    solved_model_input_json=copy.deepcopy(solved_model_input_json or {}),
    financials_json=copy.deepcopy(financials_json or {}),
  )
  provisional_plan_status = str(provisional_plan.get("status") or "").strip().lower()
  provisional_plan_fail_flags = {
    str(item).strip()
    for item in (provisional_plan.get("translation_fail_flags") or [])
    if str(item).strip()
  }
  should_retry = bool(contract_error) or provisional_plan_status == "ready_no_valid_solver_contract" or bool(
    provisional_plan_fail_flags & {
      "cash_required_action_missing",
      "cash_quarter_coverage_missing",
      "cash_quarter_underfunded",
      "cash_quarter_overfunded",
      "cash_translation_failed",
    }
  )
  if should_retry:
    retry_payload = copy.deepcopy(payload)
    retry_payload["input"] = list(retry_payload.get("input") or []) + [
      {
        "role": "user",
        "content": [
          {
            "type": "input_text",
            "text": json.dumps(
              {
                "repair_contract_violation": str(contract_error or "").strip() or "cash_strategy_plan_did_not_fully_cover_required_funding_quarters",
                "required_funding_quarters": copy.deepcopy(required_funding_quarters),
                "required_surplus_deployment_quarters": copy.deepcopy(required_surplus_deployment_quarters),
                "provisional_translation_fail_flags": sorted(provisional_plan_fail_flags),
                "provisional_translation_warnings": copy.deepcopy(provisional_plan.get("translation_warnings") or []),
                "instruction": (
                  "You must fully cover every required incremental funding quarter with integer whole-dollar amounts only. "
                  "You must also deploy every surplus_deployment_quarter by increasing Distributions and/or Debt Repayment enough "
                  "to eliminate cash above the strategy cash ceiling, using only Python-provided lever bounds. "
                  "Return recommendation_mode='adjust', include quarter_funding_plan entries for every required funding quarter, "
                  "and make recommended_adjustments sufficient so the translated financing plan covers the full residual funding gap "
                  "for each required incremental quarter. Every quarter_funding_plan funding_sources list must contain exactly one source, and that "
                  "single funding_sources.amount must equal that quarter's required incremental funding gap exactly using integer amounts with no decimals and no cents. "
                  "For debt-based levers, use the Python-provided "
                  "cash_support_multiplier guidance: quarter_funding_plan funding_sources.amount is the effective cash support toward the gap, "
                  "while recommended_adjustments.exact_value must be the grossed-up actual lever value needed to deliver that support. "
                  "For equity levers, the funding_sources amount and exact_value can match 1:1. Do not split a quarter across multiple funding sources. "
                  "A balanced strategy may mix source types across different quarters, but each quarter must reconcile with one source exactly. "
                  "Underfunded or overfunded quarters will fail. Do not re-fund prior quarter support in later quarters."
                ),
              },
              ensure_ascii=False,
            ),
          }
        ],
      }
    ]
    previous_cash_review_retry_deadline = _set_active_openai_deadline(
      time.perf_counter() + cash_review_deadline_seconds
    )
    try:
      retry_resp = _post_openai(
        url="https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload=retry_payload,
      )
    except Exception as exc:
      return _cash_strategy_review_failure_payload(
        selected_cash_strategy=selected_cash_strategy,
        prompt_file=prompt_file,
        status="failed_contract_retry_request",
        detail=f"{str(contract_error or provisional_plan_status or 'cash_strategy_review_invalid_contract').strip()} Retry error: {exc}",
        prompt_trace=prompt_trace,
        raw_openai_response=raw_openai_response,
      )
    finally:
      _set_active_openai_deadline(previous_cash_review_retry_deadline)
    if retry_resp.status_code >= 400:
      return _cash_strategy_review_failure_payload(
        selected_cash_strategy=selected_cash_strategy,
        prompt_file=prompt_file,
        status="failed_contract_retry_status",
        detail=f"{str(contract_error or provisional_plan_status or 'cash_strategy_review_invalid_contract').strip()} Retry status body: {retry_resp.text[:1200]}",
        prompt_trace=prompt_trace,
        raw_openai_response=raw_openai_response,
      )
    retry_raw_openai_response = retry_resp.json() if isinstance(retry_resp.json(), dict) else {"response": retry_resp.text[:4000]}
    parsed_retry = _parse_responses_json_dict(retry_raw_openai_response)
    if not isinstance(parsed_retry, dict):
      return _cash_strategy_review_failure_payload(
        selected_cash_strategy=selected_cash_strategy,
        prompt_file=prompt_file,
        status="failed_contract_retry_parse",
        detail="Cash strategy review retry returned an unparsable response.",
        prompt_trace=prompt_trace,
        raw_openai_response=retry_raw_openai_response,
      )
    parsed_retry = _normalize_cash_strategy_review_decision_from_funding_plan(
      parsed=parsed_retry,
      cash_strategy_review_context=context_payload,
    )
    parsed_retry = _normalize_post_intake_contract_payload(
      contract_name="cash_strategy_review",
      payload=parsed_retry,
    )
    retry_contract_error = _cash_strategy_review_decision_contract_error(
      parsed=parsed_retry,
      cash_strategy_review_context=context_payload,
    )
    retry_review_payload = copy.deepcopy(provisional_review_payload)
    retry_review_payload["raw_openai_response"] = copy.deepcopy(retry_raw_openai_response)
    retry_review_payload["decision"] = copy.deepcopy(parsed_retry)
    retry_plan = _build_cash_strategy_second_pass_plan(
      review_decision_payload=copy.deepcopy(retry_review_payload),
      solved_model_input_json=copy.deepcopy(solved_model_input_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
    )
    retry_plan_status = str(retry_plan.get("status") or "").strip().lower()
    retry_plan_fail_flags = {
      str(item).strip()
      for item in (retry_plan.get("translation_fail_flags") or [])
      if str(item).strip()
    }
    if retry_contract_error or retry_plan_status == "ready_no_valid_solver_contract" or bool(
      retry_plan_fail_flags & {
        "cash_required_action_missing",
        "cash_quarter_coverage_missing",
        "cash_quarter_underfunded",
        "cash_quarter_overfunded",
        "cash_translation_failed",
      }
    ):
      return _cash_strategy_review_failure_payload(
        selected_cash_strategy=selected_cash_strategy,
        prompt_file=prompt_file,
        status="failed_invalid_contract",
        detail=str(
          retry_contract_error
          or "; ".join(copy.deepcopy(retry_plan.get("translation_warnings") or []))
          or "Cash strategy review retry still did not fully cover the required funding quarters."
        ).strip(),
        prompt_trace=prompt_trace,
        raw_openai_response=retry_raw_openai_response,
      )
    raw_openai_response = retry_raw_openai_response
    parsed = parsed_retry
  return {
    "contract_version": "cash_strategy_review_decision_v2",
    "status": "completed",
    "prompt_file": prompt_file,
    "selected_cash_strategy": selected_cash_strategy,
    "review_status": "completed",
    "decision_source": "gpt",
    "cash_strategy_review_context": copy.deepcopy(context_payload),
    "numeric_solver_contract": copy.deepcopy(
      context_payload.get("numeric_solver_contract")
      if isinstance(context_payload.get("numeric_solver_contract"), dict)
      else {}
    ),
    "prompt_trace": copy.deepcopy(prompt_trace),
    "raw_openai_response": copy.deepcopy(raw_openai_response),
    "detail": "",
    "decision": parsed,
  }

def _translate_cash_strategy_adjustment(
  *,
  adjustment: Dict[str, Any],
  baseline_map: Dict[str, List[float]],
  quarter_count: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
  lever_id = str(adjustment.get("lever_id") or "").strip()
  if not lever_id:
    return None, "missing lever_id"
  baseline_values = baseline_map.get(lever_id)
  if not baseline_values:
    return None, f"unknown lever_id {lever_id}"

  start_q, end_q = _normalized_quarter_window(
    adjustment.get("timing_start_q"),
    adjustment.get("timing_end_q"),
    quarter_count=quarter_count,
  )
  value_mode = str(adjustment.get("value_mode") or "").strip().lower()
  direction = str(adjustment.get("direction") or "").strip().lower()
  translated: Dict[str, Any] = {
    "lever_id": lever_id,
    "section": str(adjustment.get("section") or "").strip(),
    "direction": direction,
    "control_mode": value_mode,
    "timing_start_q": start_q,
    "timing_end_q": end_q,
    "baseline_window": _baseline_window_summary(baseline_values, start_q=start_q, end_q=end_q),
    "business_reason": str(adjustment.get("business_reason") or "").strip(),
    "linked_action_effect": str(adjustment.get("linked_action_effect") or "").strip(),
    "mapped_repair_targets": _normalize_unified_mapped_repair_targets(
      adjustment.get("mapped_repair_targets") or []
    ),
  }

  if value_mode == "exact":
    exact_value = _safe_float(adjustment.get("exact_value"))
    if exact_value is None:
      return None, f"{lever_id} exact mode missing exact_value"
    translated["exact_value"] = (
      int(round(float(exact_value)))
      if float(int(round(float(exact_value)))) == float(exact_value)
      else round(float(exact_value), 2)
    )
    translated["min_value"] = None
    translated["max_value"] = None
    return translated, None

  if value_mode == "band":
    min_value = _safe_float(adjustment.get("min_value"))
    max_value = _safe_float(adjustment.get("max_value"))
    if min_value is None or max_value is None:
      return None, f"{lever_id} band mode missing min_value or max_value"
    low_raw = float(min(min_value, max_value))
    high_raw = float(max(min_value, max_value))
    low = int(round(low_raw)) if float(int(round(low_raw))) == low_raw else round(low_raw, 2)
    high = int(round(high_raw)) if float(int(round(high_raw))) == high_raw else round(high_raw, 2)
    translated["exact_value"] = None
    translated["min_value"] = low
    translated["max_value"] = high
    return translated, None

  return None, f"{lever_id} has unsupported value_mode {value_mode}"

def _build_cash_strategy_second_pass_plan(
  *,
  review_decision_payload: Optional[Dict[str, Any]],
  solved_model_input_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del solved_model_input_json
  review_payload = review_decision_payload if isinstance(review_decision_payload, dict) else {}
  scoped_contract = (
    review_payload.get("numeric_solver_contract")
    if isinstance(review_payload.get("numeric_solver_contract"), dict)
    else {}
  )
  solver_contract = (
    copy.deepcopy(scoped_contract)
    if isinstance(scoped_contract, dict) and scoped_contract
    else copy.deepcopy(numeric_solver_contract)
    if isinstance(numeric_solver_contract, dict)
    else {}
  )
  selected_cash_strategy = _resolved_cash_strategy(financials_json, review_payload)
  review_status = str(review_payload.get("status") or "").strip()
  prompt_file = str(review_payload.get("prompt_file") or "").strip()
  if review_status != "completed":
    return {
      "contract_version": "cash_strategy_second_pass_plan_v2",
      "status": "skipped_review_not_completed",
      "selected_cash_strategy": selected_cash_strategy,
      "prompt_file": prompt_file,
      "review_status": review_status,
      "default_unspecified_lever_policy": {},
      "numeric_solver_contract": solver_contract,
      "translated_action_packages": [],
      "translation_warnings": [],
      "translation_fail_flags": ["cash_pass_not_executed"],
      "exact_updates": [],
      "next_step": "wait_for_completed_cash_strategy_review",
    }

  decision = review_payload.get("decision") if isinstance(review_payload.get("decision"), dict) else {}
  recommendation_mode = str(decision.get("recommendation_mode") or "").strip().lower()
  context_payload = (
    review_payload.get("cash_strategy_review_context")
    if isinstance(review_payload.get("cash_strategy_review_context"), dict)
    else {}
  )
  lever_bounds_payload = (
    context_payload.get("lever_bounds")
    if isinstance(context_payload.get("lever_bounds"), dict)
    else {}
  )
  violation_envelope = (
    context_payload.get("cash_violation_envelope")
    if isinstance(context_payload.get("cash_violation_envelope"), dict)
    else {}
  )
  bound_entries = (
    lever_bounds_payload.get("lever_bounds")
    if isinstance(lever_bounds_payload.get("lever_bounds"), dict)
    else {}
  )
  allowed_quarters = [
    int(_safe_float(item) or 0)
    for item in (
      violation_envelope.get("allowed_review_quarters")
      or lever_bounds_payload.get("allowed_quarters")
      or context_payload.get("allowed_quarters")
      or []
    )
    if int(_safe_float(item) or 0) >= 1
  ]
  has_violations = bool(violation_envelope.get("has_violations"))
  residual_gap_quarters = [
    int(_safe_float(item) or 0)
    for item in (violation_envelope.get("residual_gap_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  required_funding_quarters = {
    int(_safe_float(item.get("quarter_index")) or 0): copy.deepcopy(item)
    for item in (context_payload.get("required_funding_quarters") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  residual_gap_required = bool(residual_gap_quarters)
  deterministic_hard_rule_updates = [
    copy.deepcopy(item)
    for item in (violation_envelope.get("deterministic_hard_rule_updates") or [])
    if isinstance(item, dict)
  ]
  warnings: List[str] = []
  fail_flags: List[str] = []
  translated_packages: List[Dict[str, Any]] = []
  touched_lever_ids: List[str] = []
  exact_updates_by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
  stock_financing_start_quarters: Dict[str, int] = {}
  quarter_funding_plan = {
    int(_safe_float(item.get("quarter_index")) or 0): copy.deepcopy(item)
    for item in (decision.get("quarter_funding_plan") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  allowed_lever_ids = {
    str(item).strip()
    for item in (((context_payload.get("writable_lever_catalog") or {}) if isinstance(context_payload.get("writable_lever_catalog"), dict) else {}).get("lever_ids") or [])
    if str(item).strip()
  }
  if not bool(review_payload.get("prompt_trace")):
    fail_flags.append("cash_prompt_trace_missing")
  if not bool(review_payload.get("raw_openai_response")):
    fail_flags.append("cash_raw_response_missing")
  if str(review_payload.get("decision_source") or "").strip().lower() != "gpt":
    fail_flags.append("cash_non_gpt_fallback_used")
  if has_violations and recommendation_mode != "adjust":
    warnings.append("violations_present: coercing recommendation_mode to adjust because Python already determined cash action is required")
    recommendation_mode = "adjust"

  financing_amount_lever_ids = {
    _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID,
    _CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID,
    _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID,
  }
  debt_cash_effect_lever_ids = {
    _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID,
    _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
  }
  stock_financing_level_lever_ids = {
    _CASH_STRATEGY_OWNERS_CAPITAL_LEVER_ID,
    _CASH_STRATEGY_OTHER_EQUITY_LEVER_ID,
  }
  direct_cash_support_flows_by_quarter: Dict[int, int] = {}

  for idx, update in enumerate(deterministic_hard_rule_updates, start=1):
    lever_id = str(update.get("lever_id") or "").strip()
    quarter_index = int(_safe_float(update.get("quarter_index")) or 0)
    exact_value_raw = _safe_float(update.get("exact_value"))
    exact_value = int(round(float(exact_value_raw))) if exact_value_raw is not None else None
    if not lever_id or quarter_index < 1 or exact_value is None:
      fail_flags.append("cash_translation_failed")
      warnings.append(f"hard_rule_{idx}: invalid deterministic cash update payload")
      continue
    exact_updates_by_key[(lever_id, quarter_index)] = {
      "lever_id": lever_id,
      "quarter_index": quarter_index,
      "exact_value": int(exact_value),
    }
    translated_packages.append(
      {
        "action_id": f"cash_hard_rule_{idx}",
        "business_move": f"Apply hard rule to {lever_id}",
        "why_now": str(update.get("business_reason") or "Python-enforced cash hard rule.").strip(),
        "expected_visual_effect": "Deterministic liquidity-protection adjustment",
        "coordination_notes": "Post-convergence cash hard rule applied before GPT financing choices.",
        "timing_start_q": quarter_index,
        "timing_end_q": quarter_index,
        "priority": idx,
        "boldness": "moderate",
        "solver_allowed_lever_ids": [lever_id],
        "quarter_target_metrics": [],
        "translated_controls": [
          {
            "lever_id": lever_id,
            "section": "schedules" if lever_id.startswith("schedules::") else "balance_sheet",
            "direction": "increase",
            "control_mode": "exact",
            "timing_start_q": quarter_index,
            "timing_end_q": quarter_index,
            "baseline_window": {
              "quarter_start": quarter_index,
              "quarter_end": quarter_index,
              "value_start": None,
              "value_end": None,
              "value_min": None,
              "value_max": None,
            },
            "business_reason": str(update.get("business_reason") or "").strip(),
            "linked_action_effect": "post_convergence_cash_hard_rule",
            "exact_value": int(exact_value),
            "min_value": None,
            "max_value": None,
          }
        ],
      }
    )
    if lever_id not in touched_lever_ids:
      touched_lever_ids.append(lever_id)

  sorted_allowed_quarters = sorted({quarter for quarter in allowed_quarters if quarter >= 1})

  def _quarter_bound_entry_for_lever(lever_id: str, quarter_index: int) -> Dict[str, Any]:
    return next(
      (
        item for item in (bound_entries.get(lever_id) or [])
        if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) == quarter_index
      ),
      {},
    )

  def _current_value_for_update(lever_id: str, quarter_index: int) -> int:
    existing_update = exact_updates_by_key.get((lever_id, quarter_index))
    if isinstance(existing_update, dict):
      return int(round(float(_safe_float(existing_update.get("exact_value")) or 0.0)))
    if lever_id in stock_financing_level_lever_ids:
      for prior_quarter in range(quarter_index - 1, 0, -1):
        prior_update = exact_updates_by_key.get((lever_id, prior_quarter))
        if isinstance(prior_update, dict):
          return int(round(float(_safe_float(prior_update.get("exact_value")) or 0.0)))
    quarter_bounds = _quarter_bound_entry_for_lever(lever_id, quarter_index)
    return int(round(float(_safe_float(quarter_bounds.get("current_value")) or 0.0)))

  for idx, adjustment in enumerate([item for item in (decision.get("recommended_adjustments") or []) if isinstance(item, dict)], start=1):
    lever_id = str(adjustment.get("lever_id") or "").strip()
    if not lever_id or lever_id not in allowed_lever_ids:
      warnings.append(f"adjustment_{idx}: invalid or unauthorized lever_id {lever_id or 'missing'}")
      fail_flags.append("cash_translation_failed")
      continue
    start_q = int(_safe_float(adjustment.get("timing_start_q")) or 0)
    end_q = int(_safe_float(adjustment.get("timing_end_q")) or start_q)
    if start_q < 1 or end_q < start_q or any(quarter not in allowed_quarters for quarter in range(start_q, end_q + 1)):
      warnings.append(f"adjustment_{idx}: quarter window {start_q}-{end_q} is outside allowed_quarters")
      fail_flags.append("cash_translation_failed")
      continue
    exact_value_raw = _safe_float(adjustment.get("exact_value"))
    exact_value = int(round(float(exact_value_raw))) if exact_value_raw is not None else None
    if exact_value is None:
      warnings.append(f"adjustment_{idx}: missing exact_value")
      fail_flags.append("cash_translation_failed")
      continue
    translated_controls: List[Dict[str, Any]] = []
    target_quarters = list(range(start_q, end_q + 1))
    if lever_id in stock_financing_level_lever_ids:
      stock_financing_start_quarters[lever_id] = min(start_q, stock_financing_start_quarters.get(lever_id, start_q))
      warnings.append(
        f"adjustment_{idx}: {lever_id} is a stock financing lever, so only declared contribution quarters are written; model-input stock semantics carry the level forward"
      )
    for quarter_index in target_quarters:
      quarter_bounds = _quarter_bound_entry_for_lever(lever_id, quarter_index)
      current_value = _current_value_for_update(lever_id, quarter_index)
      min_value = int(round(float(_safe_float(quarter_bounds.get("min_value")) or 0.0)))
      max_value = int(round(float(_safe_float(quarter_bounds.get("max_value")) or 0.0)))
      supporting_metrics = (
        quarter_bounds.get("supporting_metrics")
        if isinstance(quarter_bounds.get("supporting_metrics"), dict)
        else {}
      )
      carryforward_headroom = int(round(float(_safe_float(supporting_metrics.get("carryforward_headroom")) or 0.0)))
      cash_support_multiplier = round(
        float(_safe_float(supporting_metrics.get("cash_support_multiplier")) or 1.0),
        6,
      )
      effective_min_value = min_value
      effective_max_value = max_value
      if lever_id in stock_financing_level_lever_ids:
        # Stock financing rows persist forward, so later-quarter bounds must honor
        # the already-carried-forward stock level from earlier approved contributions.
        effective_min_value = int(max(min_value, current_value))
        effective_max_value = int(max(max_value, current_value + max(carryforward_headroom, 0)))
      candidate_exact_value = int(exact_value)
      if lever_id in financing_amount_lever_ids:
        candidate_exact_value = int(current_value + max(int(exact_value), 0))
      bounded_exact_value = int(min(max(candidate_exact_value, effective_min_value), effective_max_value))
      if bounded_exact_value != candidate_exact_value:
        if lever_id in financing_amount_lever_ids:
          warnings.append(
            f"adjustment_{idx}: {lever_id} Q{quarter_index} financing amount {int(exact_value)} translated to final value {candidate_exact_value} and was clamped into bounds [{effective_min_value}, {effective_max_value}]"
          )
        else:
          warnings.append(
            f"adjustment_{idx}: {lever_id} Q{quarter_index} exact_value {int(exact_value)} was clamped into bounds [{effective_min_value}, {effective_max_value}]"
          )
      elif lever_id in financing_amount_lever_ids:
        if lever_id in debt_cash_effect_lever_ids:
          estimated_support = int(round(max(int(candidate_exact_value - current_value), 0) * cash_support_multiplier))
          warnings.append(
            f"adjustment_{idx}: {lever_id} Q{quarter_index} financing amount {int(exact_value)} translated to final value {candidate_exact_value} with estimated effective cash support {estimated_support} at multiplier {cash_support_multiplier}"
          )
        else:
          warnings.append(
            f"adjustment_{idx}: {lever_id} Q{quarter_index} financing amount {int(exact_value)} translated to final value {candidate_exact_value}"
          )
      direct_support_flow = 0
      if lever_id in stock_financing_level_lever_ids:
        if quarter_index == start_q:
          direct_support_flow = int(bounded_exact_value - current_value)
      elif lever_id == _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID:
        direct_support_flow = int(round((current_value - bounded_exact_value) * cash_support_multiplier))
      elif lever_id in financing_amount_lever_ids:
        if lever_id in debt_cash_effect_lever_ids:
          direct_support_flow = int(round((bounded_exact_value - current_value) * cash_support_multiplier))
        else:
          direct_support_flow = int(bounded_exact_value - current_value)
      if direct_support_flow != 0:
        direct_cash_support_flows_by_quarter[quarter_index] = int(
          direct_cash_support_flows_by_quarter.get(quarter_index, 0) + direct_support_flow
        )
      translated_controls.append(
        {
          "lever_id": lever_id,
          "section": "schedules" if lever_id.startswith("schedules::") else "balance_sheet",
          "direction": "increase" if int(bounded_exact_value) >= current_value else "decrease",
          "control_mode": "exact",
          "timing_start_q": quarter_index,
          "timing_end_q": quarter_index,
          "baseline_window": {
            "quarter_start": quarter_index,
            "quarter_end": quarter_index,
            "value_start": current_value,
            "value_end": current_value,
            "value_min": current_value,
            "value_max": current_value,
          },
          "business_reason": str(adjustment.get("business_reason") or "").strip(),
          "linked_action_effect": "post_convergence_cash_strategy",
          "exact_value": int(bounded_exact_value),
          "min_value": None,
          "max_value": None,
        }
      )
      exact_updates_by_key[(lever_id, quarter_index)] = {
        "lever_id": lever_id,
        "quarter_index": quarter_index,
        "exact_value": int(bounded_exact_value),
      }
    if translated_controls:
      if lever_id not in touched_lever_ids:
        touched_lever_ids.append(lever_id)
      translated_packages.append(
        {
          "action_id": f"cash_adjustment_{idx}",
          "business_move": f"Adjust {lever_id}",
          "why_now": str(adjustment.get("business_reason") or "").strip(),
          "expected_visual_effect": "Bounded financing-layer cash strategy adjustment",
          "coordination_notes": "Post-convergence financing-only cash strategy pass.",
          "timing_start_q": start_q,
          "timing_end_q": end_q,
          "priority": idx,
          "boldness": "moderate",
          "solver_allowed_lever_ids": [lever_id],
          "quarter_target_metrics": [],
          "translated_controls": translated_controls,
        }
      )
      for control in translated_controls:
        quarter_index = int(_safe_float(control.get("timing_start_q")) or 0)
        if quarter_index < 1:
          continue
        exact_updates_by_key[(lever_id, quarter_index)] = {
          "lever_id": lever_id,
          "quarter_index": quarter_index,
          "exact_value": int(round(float(_safe_float(control.get("exact_value")) or 0.0))),
        }

  exact_updates = list(exact_updates_by_key.values())
  for lever_id, start_q in stock_financing_start_quarters.items():
    warnings.append(
      f"stock_financing_carryforward: {lever_id} starts at Q{start_q}; downstream model-input stock semantics persist the latest level through later quarters without explicit zero updates"
    )
  missing_declared_funding_quarters = [
    quarter for quarter in sorted(required_funding_quarters.keys())
    if quarter not in quarter_funding_plan
  ]
  if missing_declared_funding_quarters:
    fail_flags.append("cash_quarter_coverage_missing")
    warnings.append(
      f"quarter_funding_plan_missing: required funding quarters {missing_declared_funding_quarters} were not explicitly covered by GPT."
    )
  cumulative_cash_support_by_quarter: Dict[int, int] = {}
  running_cash_support = 0
  for quarter_index in sorted_allowed_quarters:
    running_cash_support = int(running_cash_support + int(direct_cash_support_flows_by_quarter.get(quarter_index, 0) or 0))
    cumulative_cash_support_by_quarter[quarter_index] = int(running_cash_support)
  underfunded_required_quarters: List[Dict[str, Any]] = []
  mismatched_required_quarters: List[Dict[str, Any]] = []
  for quarter_index in sorted(required_funding_quarters.keys()):
    required_payload = required_funding_quarters.get(quarter_index) or {}
    required_gap = int(round(float(_safe_float(required_payload.get("required_incremental_funding_after_hard_rules")) or 0.0)))
    covered_gap = int(round(float(direct_cash_support_flows_by_quarter.get(quarter_index, 0) or 0.0)))
    if covered_gap != required_gap:
      mismatched_required_quarters.append(
        {
          "quarter_index": int(quarter_index),
          "required_gap": required_gap,
          "covered_gap": covered_gap,
        }
      )
    if covered_gap < required_gap:
      underfunded_required_quarters.append(
        {
          "quarter_index": int(quarter_index),
          "required_gap": required_gap,
          "covered_gap": covered_gap,
        }
      )
  if underfunded_required_quarters:
    fail_flags.append("cash_quarter_underfunded")
    fail_flags.append("cash_required_action_missing")
    warnings.append(
      "quarter_funding_plan_underfunded: "
      + ", ".join(
        f"Q{int(item.get('quarter_index') or 0)} required={int(item.get('required_gap') or 0)} covered={int(item.get('covered_gap') or 0)}"
        for item in underfunded_required_quarters
      )
    )
  overfunded_required_quarters = [
    item for item in mismatched_required_quarters
    if int(item.get("covered_gap") or 0) > int(item.get("required_gap") or 0)
  ]
  if overfunded_required_quarters:
    fail_flags.append("cash_quarter_overfunded")
    fail_flags.append("cash_translation_failed")
    warnings.append(
      "quarter_funding_plan_overfunded: "
      + ", ".join(
        f"Q{int(item.get('quarter_index') or 0)} required={int(item.get('required_gap') or 0)} covered={int(item.get('covered_gap') or 0)}"
        for item in overfunded_required_quarters
      )
    )
  status = "ready"
  next_step = "ready_for_cash_strategy_solver"
  if recommendation_mode == "maintain" and not has_violations:
    status = "ready_maintain_first_pass"
    next_step = "no_cash_strategy_adjustment_required"
  elif any(
    flag in fail_flags
    for flag in ("cash_quarter_coverage_missing", "cash_quarter_underfunded", "cash_quarter_overfunded")
  ):
    status = "ready_no_valid_solver_contract"
    next_step = "fully_cover_required_funding_quarters_before_cash_strategy_solver"
  elif residual_gap_required and not exact_updates:
    status = "ready_no_valid_solver_contract"
    fail_flags.append("cash_required_action_missing")
    next_step = "supply_required_cash_actions_before_cash_strategy_solver"
  elif recommendation_mode == "adjust" and not exact_updates:
    status = "ready_surplus_cleanup_only"
    next_step = "run_python_owned_actual_state_surplus_cleanup"
  if review_status == "completed" and not bool(review_payload.get("prompt_trace")):
    fail_flags.append("cash_prompt_trace_missing")
  if review_status == "completed" and not bool(review_payload.get("raw_openai_response")):
    fail_flags.append("cash_raw_response_missing")
  debt_schedule_updates = [
    {
      "quarter_index": int(item.get("quarter_index") or 0),
      "lever_id": str(item.get("lever_id") or "").strip(),
      "exact_value": int(round(float(_safe_float(item.get("exact_value")) or 0.0))),
    }
    for item in exact_updates
    if str(item.get("lever_id") or "").strip() in {
      _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID,
      _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
    }
  ]

  return {
    "contract_version": "cash_strategy_second_pass_plan_v2",
    "status": status,
    "solver_phase_status": str(solver_contract.get("solver_phase_status") or "").strip(),
    "numeric_execution_phase": "cash_strategy_review",
    "selected_cash_strategy": selected_cash_strategy,
    "prompt_file": prompt_file,
    "review_status": review_status,
    "recommendation_mode": recommendation_mode,
    "executive_summary": str(decision.get("executive_summary") or "").strip(),
    "capital_posture_summary": str(decision.get("capital_posture_summary") or "").strip(),
    "funding_mix_summary": str(decision.get("funding_mix_summary") or "").strip(),
    "confidence": str(decision.get("confidence") or "").strip(),
    "baseline_source": "first_pass_solved_model",
    "has_violations": has_violations,
    "deterministic_hard_rule_update_count": len(deterministic_hard_rule_updates),
    "gpt_adjustment_count": len([item for item in (decision.get("recommended_adjustments") or []) if isinstance(item, dict)]),
    "quarter_funding_plan": copy.deepcopy(list(quarter_funding_plan.values())),
    "required_funding_quarters": copy.deepcopy(list(required_funding_quarters.values())),
    "cumulative_cash_support_by_quarter": copy.deepcopy(cumulative_cash_support_by_quarter),
    "debt_schedule_plan": {
      "contract_version": "cash_strategy_debt_schedule_plan_v1",
      "plan_role": "conversion_plan_for_existing_model_input_debt_rows",
      "finmo_formula_unchanged": True,
      "model_input_rows_written": [
        _CASH_STRATEGY_DEBT_ISSUANCE_LEVER_ID,
        _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
      ],
      "updates": debt_schedule_updates,
    },
    "numeric_solver_contract": solver_contract,
    "default_unspecified_lever_policy": {
      "mode": "lock_to_first_pass_solved_values",
      "scope": "all_unspecified_writable_levers",
      "rationale": "Second pass should only move levers explicitly prescribed by the cash strategy review.",
    },
    "translated_action_packages": translated_packages,
    "translated_control_count": len(exact_updates),
    "touched_lever_ids": touched_lever_ids,
    "translation_warnings": warnings,
    "translation_fail_flags": list(dict.fromkeys(fail_flags)),
    "exact_updates": exact_updates,
    "allowed_quarters": copy.deepcopy(allowed_quarters),
    "next_step": next_step,
  }

def _clamp_value(value: float, *, minimum: Optional[float], maximum: Optional[float]) -> float:
  next_value = float(value)
  if minimum is not None:
    next_value = max(next_value, float(minimum))
  if maximum is not None:
    next_value = min(next_value, float(maximum))
  return float(next_value)

def _preferred_exact_from_band_control(control: Dict[str, Any], *, boldness: str) -> Optional[float]:
  minimum = _safe_float(control.get("min_value"))
  maximum = _safe_float(control.get("max_value"))
  if minimum is None and maximum is None:
    return None
  baseline_window = control.get("baseline_window") if isinstance(control.get("baseline_window"), dict) else {}
  baseline_value = _safe_float(baseline_window.get("value_end"))
  if baseline_value is None:
    baseline_value = _safe_float(baseline_window.get("value_start"))
  if baseline_value is None:
    baseline_value = 0.0
  direction = str(control.get("direction") or "").strip().lower()
  boldness_norm = str(boldness or "").strip().lower()

  if direction == "increase":
    if maximum is None:
      return minimum
    edge = float(maximum)
    if boldness_norm == "light":
      return float((baseline_value + edge) / 2.0)
    if boldness_norm == "moderate":
      return float(baseline_value + 0.75 * (edge - baseline_value))
    return edge

  if direction == "decrease":
    if minimum is None:
      return maximum
    edge = float(minimum)
    if boldness_norm == "light":
      return float((baseline_value + edge) / 2.0)
    if boldness_norm == "moderate":
      return float(baseline_value + 0.75 * (edge - baseline_value))
    return edge

  if direction == "hold":
    return _clamp_value(float(baseline_value), minimum=minimum, maximum=maximum)

  if direction == "retime":
    return _clamp_value(float(baseline_value), minimum=minimum, maximum=maximum)

  candidate = baseline_value
  if minimum is not None and maximum is not None:
    candidate = (float(minimum) + float(maximum)) / 2.0
  elif minimum is not None:
    candidate = float(minimum)
  elif maximum is not None:
    candidate = float(maximum)
  return float(candidate)

def _apply_followup_exact_updates(
  *,
  review_plan: Optional[Dict[str, Any]],
  current_model_input_json: Optional[Dict[str, Any]],
  contract_version: str,
  solver_deadline_monotonic: Optional[float] = None,
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.numeric_execution import build_numeric_execution_boundary_payload, execute_numeric_plan, CURRENT_NUMERIC_EXECUTOR  # type: ignore
  except Exception:
    from numeric_execution import build_numeric_execution_boundary_payload, execute_numeric_plan, CURRENT_NUMERIC_EXECUTOR  # type: ignore
  plan = review_plan if isinstance(review_plan, dict) else {}
  solver_contract = (
    copy.deepcopy(plan.get("numeric_solver_contract"))
    if isinstance(plan.get("numeric_solver_contract"), dict)
    else {}
  )
  if isinstance(solver_deadline_monotonic, (int, float)) and float(solver_deadline_monotonic) > 0:
    solver_contract["runtime_deadline_monotonic"] = float(solver_deadline_monotonic)
    solver_contract["runtime_timeout_policy"] = "fail_fast_before_cycle_timeout"
  active_issue_count = int(_safe_float(solver_contract.get("active_issue_count")) or 0)
  phase_status = str(solver_contract.get("solver_phase_status") or "").strip()
  plan_status = str(plan.get("status") or "").strip()
  if plan_status == "ready_maintain_first_pass":
    if active_issue_count > 0:
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_illegally_requested_maintain_mode"
      )
    return {
      "contract_version": contract_version,
      "status": "skipped_maintain_first_pass",
      "execution_state": "skipped_maintain_first_pass",
      "solver_execution_state": "not_run",
      "solver_invoked": False,
      "final_model_source": "current_model",
      "applied_update_count": 0,
      "applied_updates": [],
      "attempt_count": 0,
      "quarters_with_target_misses": 0,
      "targeted_quarters": [],
      "target_metric_names": [],
      "allowed_lever_ids": [],
      "warnings": [],
      "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
      "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": {},
    }
  if plan_status != "ready":
    if active_issue_count > 0:
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_not_ready_for_target_driven_execution"
      )
    return {
      "contract_version": contract_version,
      "status": "skipped_not_ready",
      "execution_state": "skipped_not_ready",
      "solver_execution_state": "not_run",
      "solver_invoked": False,
      "final_model_source": "current_model",
      "applied_update_count": 0,
      "applied_updates": [],
      "attempt_count": 0,
      "quarters_with_target_misses": 0,
      "targeted_quarters": [],
      "target_metric_names": [],
      "allowed_lever_ids": [],
      "warnings": [str(item).strip() for item in (plan.get("translation_warnings") or []) if str(item).strip()],
      "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
      "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": {},
    }

  warnings = [str(item).strip() for item in (plan.get("translation_warnings") or []) if str(item).strip()]
  full_horizon_exact_updates = [
    copy.deepcopy(item)
    for item in (plan.get("model_input_repair_exact_updates") or [])
    if isinstance(item, dict)
  ]
  if full_horizon_exact_updates:
    from client_intake_and_finmo.quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore
    from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
    updated_model_input_json = apply_exact_lever_updates_to_model_input(
      model_input_json=current_model_input_json if isinstance(current_model_input_json, dict) else {},
      exact_updates=copy.deepcopy(full_horizon_exact_updates),
    )
    updated_finmo_json = build_python_finmo_json(
      model_input_json=copy.deepcopy(updated_model_input_json)
    )
    targeted_quarters = sorted(
      {
        int(_safe_float(item.get("quarter_index")) or 0)
        for item in full_horizon_exact_updates
        if int(_safe_float(item.get("quarter_index")) or 0) >= 1
      }
    )
    allowed_lever_ids = sorted(
      {
        str(item.get("lever_id") or "").strip()
        for item in full_horizon_exact_updates
        if str(item.get("lever_id") or "").strip()
      }
    )
    return {
      "contract_version": contract_version,
      "status": "completed_full_horizon_model_input_repair",
      "execution_state": "completed_full_horizon_model_input_repair",
      "solver_execution_state": "applied_full_horizon_model_input_cells",
      "solver_invoked": True,
      "final_model_source": "model_input_json",
      "state_model": "single_model_input_truth_full_horizon_v1",
      "applied_update_count": len(full_horizon_exact_updates),
      "applied_updates": copy.deepcopy(full_horizon_exact_updates),
      "attempt_count": 1,
      "quarters_with_target_misses": 0,
      "targeted_quarters": copy.deepcopy(targeted_quarters),
      "target_metric_names": copy.deepcopy(plan.get("required_target_metric_keys") or []),
      "allowed_lever_ids": copy.deepcopy(allowed_lever_ids),
      "warnings": warnings,
      "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
      "numeric_executor": "full_horizon_model_input_cell_executor",
      "numeric_execution_plan": {
        "execution_mode": "full_horizon_model_input_cells",
        "targeted_quarters": copy.deepcopy(targeted_quarters),
        "allowed_lever_ids": copy.deepcopy(allowed_lever_ids),
        "target_metric_names": copy.deepcopy(plan.get("required_target_metric_keys") or []),
      },
      "numeric_solver_result": {
        "status": "applied_full_horizon_model_input_cells",
        "execution_state": "applied_full_horizon_model_input_cells",
        "solver_invoked": True,
        "used_solver": False,
        "exact_updates": copy.deepcopy(full_horizon_exact_updates),
      },
      "numeric_execution_outcome": {
        "execution_state": "applied_full_horizon_model_input_cells",
        "quarter_fit_summary": [],
      },
      "target_verification": {
        "controller_state": "pending_rescan",
        "controller_reason": "Full-horizon model_input_json repair cells applied; issue scanner owns final verification.",
        "quarters_failed": [],
      },
      "full_horizon_model_input_repair_contract": copy.deepcopy(
        plan.get("full_horizon_model_input_repair_contract") or {}
      ),
      "model_input_repair_cells": copy.deepcopy(plan.get("model_input_repair_cells") or []),
      "updated_model_input_json": updated_model_input_json,
      "updated_finmo_json": updated_finmo_json,
    }
  solver_ready_actions = _review_plan_has_solver_ready_actions(plan)
  if not solver_ready_actions:
    if active_issue_count > 0:
      raise RuntimeError(
        f"{contract_version}_missing_required_solver_target_contract_for_active_issues"
      )
    return {
      "contract_version": contract_version,
      "status": "skipped_no_solver_contract_required",
      "execution_state": "skipped_no_solver_contract_required",
      "solver_execution_state": "not_run",
      "solver_invoked": False,
      "final_model_source": "current_model",
      "applied_update_count": 0,
      "applied_updates": [],
      "attempt_count": 0,
      "quarters_with_target_misses": 0,
      "targeted_quarters": [],
      "target_metric_names": [],
      "allowed_lever_ids": [],
      "warnings": warnings,
      "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
      "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": {},
    }

  gpt_authored_exact_updates: List[Dict[str, Any]] = []
  for action in [item for item in (plan.get("translated_action_packages") or []) if isinstance(item, dict)]:
    for control in [item for item in (action.get("translated_controls") or []) if isinstance(item, dict)]:
      lever_id = str(control.get("lever_id") or "").strip()
      start_q = int(_safe_float(control.get("timing_start_q")) or 0)
      end_q = int(_safe_float(control.get("timing_end_q")) or start_q)
      exact_value = _safe_float(control.get("exact_value"))
      if (
        not lever_id
        or start_q < 1
        or end_q != start_q
        or exact_value is None
        or str(control.get("control_mode") or "").strip().lower() != "exact"
      ):
        continue
      gpt_authored_exact_updates.append(
        {
          "lever_id": lever_id,
          "quarter_index": int(start_q),
          "exact_value": float(exact_value),
        }
      )

  execution_result = execute_numeric_plan(
    model_input_json=current_model_input_json if isinstance(current_model_input_json, dict) else {},
    exact_updates=copy.deepcopy(gpt_authored_exact_updates),
    numeric_solver_contract=copy.deepcopy(solver_contract),
    review_plan=copy.deepcopy(plan),
    phase_status=phase_status,
    executor_context={
      "source": "_apply_followup_exact_updates",
      "execution_mode": "target_driven_solver_with_gpt_authored_shape_controls",
      "gpt_authored_exact_update_count": len(gpt_authored_exact_updates),
    },
  )
  numeric_execution_plan = copy.deepcopy(execution_result.get("numeric_execution_plan") or {})
  numeric_solver_result = copy.deepcopy(execution_result.get("numeric_solver_result") or {})
  applied_updates = [
    copy.deepcopy(item)
    for item in (numeric_solver_result.get("exact_updates") or [])
    if isinstance(item, dict)
  ]
  targeted_quarters = [
    int(_safe_float(item) or 0)
    for item in (numeric_execution_plan.get("targeted_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  relevant_target_quarters = _relevant_solver_target_quarters(solver_contract)
  allowed_lever_ids = [
    str(item).strip()
    for item in (numeric_execution_plan.get("allowed_lever_ids") or [])
    if str(item).strip()
  ]
  solver_invoked = bool(
    numeric_solver_result.get("solver_invoked")
    if "solver_invoked" in numeric_solver_result
    else numeric_solver_result.get("used_solver")
  )
  execution_outcome = (
    execution_result.get("numeric_execution_outcome")
    if isinstance(execution_result.get("numeric_execution_outcome"), dict)
    else {}
  )
  execution_state = str(
    execution_outcome.get("execution_state")
    or numeric_solver_result.get("execution_state")
    or numeric_solver_result.get("status")
    or execution_result.get("status")
    or ""
  ).strip()
  solver_execution_state = str(
    numeric_solver_result.get("execution_state")
    or numeric_solver_result.get("status")
    or execution_state
    or ""
  ).strip()
  quarter_fit_summary = [
    item
    for item in (
      execution_outcome.get("quarter_fit_summary")
      or []
    )
    if isinstance(item, dict)
  ]
  target_quarters_with_fit = {
    int(_safe_float(item.get("quarter_index")) or 0)
    for item in quarter_fit_summary
    if int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  quarters_failed = sorted(
    {
      int(_safe_float(item.get("quarter_index")) or 0)
      for item in quarter_fit_summary
      if int(_safe_float(item.get("quarter_index")) or 0) >= 1
      and not bool(item.get("within_tolerance_all_targets"))
    }
  )
  missing_relevant_quarters = [
    quarter
    for quarter in relevant_target_quarters
    if quarter not in set(targeted_quarters)
  ]
  target_quarters_missing_fit = [
    quarter
    for quarter in targeted_quarters
    if quarter not in target_quarters_with_fit
  ]
  attempt_budget = int(_safe_float(numeric_execution_plan.get("attempt_budget")) or 0)
  attempt_count = len(
    [
      item
      for item in (execution_result.get("numeric_execution_attempts") or [])
      if isinstance(item, dict)
    ]
  )
  active_issue_failure_context = {
    "plan_status": plan_status or None,
    "phase_status": phase_status or None,
    "active_issue_count": active_issue_count,
    "execution_state": execution_state or None,
    "solver_execution_state": solver_execution_state or None,
    "solver_invoked": solver_invoked,
    "targeted_quarters": copy.deepcopy(targeted_quarters),
    "missing_relevant_quarters": copy.deepcopy(missing_relevant_quarters),
    "target_metric_names": [
      str(item).strip()
      for item in (numeric_execution_plan.get("target_metric_names") or [])
      if str(item).strip()
    ],
    "allowed_lever_ids": copy.deepcopy(allowed_lever_ids),
    "attempt_budget": attempt_budget,
    "attempt_count": attempt_count,
    "numeric_execution_outcome": copy.deepcopy(execution_outcome),
    "numeric_solver_outcome": copy.deepcopy(
      numeric_solver_result.get("outcome")
      if isinstance(numeric_solver_result.get("outcome"), dict)
      else {}
    ),
    "numeric_solver_error": (
      str((numeric_solver_result.get("outcome") or {}).get("reason") or "").strip()
      if isinstance(numeric_solver_result.get("outcome"), dict)
      else ""
    ) or None,
    "translated_action_package_count": len(
      [
        item
        for item in (plan.get("translated_action_packages") or [])
        if isinstance(item, dict)
      ]
    ),
    "translated_control_count": int(_safe_float(plan.get("translated_control_count")) or 0),
    "review_plan_next_step": str(plan.get("next_step") or "").strip() or None,
    "review_plan_warnings": [
      str(item).strip()
      for item in (plan.get("translation_warnings") or [])
      if str(item).strip()
    ][:12],
  }
  active_issue_failure_detail = json.dumps(
    active_issue_failure_context,
    sort_keys=True,
    default=str,
  )[:3000]
  if active_issue_count > 0:
    if execution_state == "numeric_solver_exception" or solver_execution_state == "numeric_solver_exception":
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_solver_exception:{active_issue_failure_detail}"
      )
    if missing_relevant_quarters:
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_missing_required_quarter_coverage_{missing_relevant_quarters}:{active_issue_failure_detail}"
      )
    if not targeted_quarters or not allowed_lever_ids:
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_missing_targets_or_allowed_levers:{active_issue_failure_detail}"
      )
    if not solver_invoked:
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_solver_did_not_run:{active_issue_failure_detail}"
      )
    if not quarter_fit_summary or target_quarters_missing_fit:
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_missing_target_fit_verification:{active_issue_failure_detail}"
      )
    if not applied_updates:
      raise RuntimeError(
        f"{contract_version}_active_issue_pass_completed_without_numeric_updates:{active_issue_failure_detail}"
      )
  target_verification = {
    "verification_mode": "strict_target_hit",
    "solver_invoked": solver_invoked,
    "targeted_quarters": targeted_quarters,
    "relevant_target_quarters": relevant_target_quarters,
    "missing_relevant_quarters": missing_relevant_quarters,
    "quarters_failed": quarters_failed,
    "target_quarters_missing_fit": target_quarters_missing_fit,
    "attempt_budget": attempt_budget,
    "attempt_count": attempt_count,
    "controller_state": "success" if not quarters_failed and not target_quarters_missing_fit else "retry_required",
    "controller_reason": (
      "All targeted quarters were verified within tolerance."
      if not quarters_failed and not target_quarters_missing_fit
      else "One or more targeted quarters remained outside tolerance after numeric execution."
    ),
  }
  status = "completed"
  if targeted_quarters and (quarters_failed or target_quarters_missing_fit):
    status = "retry_required_target_miss"
  return {
    "contract_version": contract_version,
    "status": status,
    "execution_state": execution_state,
    "solver_execution_state": solver_execution_state,
    "solver_invoked": solver_invoked,
    "final_model_source": "solver_review_applied",
    "applied_update_count": len(applied_updates),
    "applied_control_count": len(applied_updates),
    "applied_updates": applied_updates,
    "attempt_count": attempt_count,
    "quarters_with_target_misses": len(quarters_failed),
    "targeted_quarters": copy.deepcopy(targeted_quarters),
    "target_metric_names": [
      str(item).strip()
      for item in (numeric_execution_plan.get("target_metric_names") or [])
      if str(item).strip()
    ],
    "allowed_lever_ids": copy.deepcopy(allowed_lever_ids),
    "warnings": warnings,
    "numeric_execution_boundary": execution_result.get("numeric_execution_boundary") or build_numeric_execution_boundary_payload(),
    "numeric_executor": execution_result.get("numeric_executor") or CURRENT_NUMERIC_EXECUTOR,
    "numeric_execution_plan": numeric_execution_plan,
    "numeric_execution_attempts": copy.deepcopy(execution_result.get("numeric_execution_attempts") or []),
    "numeric_execution_outcome": copy.deepcopy(execution_result.get("numeric_execution_outcome") or {}),
    "numeric_solver_result": numeric_solver_result,
    "target_verification": target_verification,
    "updated_model_input_json": execution_result.get("updated_model_input_json") or {},
    "updated_finmo_json": execution_result.get("updated_finmo_json") or {},
  }

def _apply_cash_strategy_exact_updates(
  *,
  review_plan: Optional[Dict[str, Any]],
  current_model_input_json: Optional[Dict[str, Any]],
  current_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  try:
    from client_intake_and_finmo.numeric_execution import build_numeric_execution_boundary_payload, execute_numeric_plan, CURRENT_NUMERIC_EXECUTOR  # type: ignore
  except Exception:
    from numeric_execution import build_numeric_execution_boundary_payload, execute_numeric_plan, CURRENT_NUMERIC_EXECUTOR  # type: ignore
  plan = review_plan if isinstance(review_plan, dict) else {}
  solver_contract = (
    copy.deepcopy(plan.get("numeric_solver_contract"))
    if isinstance(plan.get("numeric_solver_contract"), dict)
    else {}
  )
  phase_status = str(plan.get("numeric_execution_phase") or solver_contract.get("solver_phase_status") or "").strip()
  warnings = [str(item).strip() for item in (plan.get("translation_warnings") or []) if str(item).strip()]
  fail_flags = [
    str(item).strip()
    for item in (plan.get("translation_fail_flags") or [])
    if str(item).strip()
  ]
  plan_status = str(plan.get("status") or "").strip()
  exact_updates = [
    copy.deepcopy(item)
    for item in (plan.get("exact_updates") or [])
    if isinstance(item, dict)
  ]
  if plan_status in {"ready_maintain_first_pass", "ready_surplus_cleanup_only"}:
    execution_state_label = (
      "skipped_surplus_cleanup_only"
      if plan_status == "ready_surplus_cleanup_only"
      else "skipped_maintain_first_pass"
    )
    return {
      "contract_version": "cash_strategy_second_pass_result_v1",
      "status": execution_state_label,
      "execution_state": execution_state_label,
      "solver_execution_state": "not_run",
      "solver_invoked": False,
      "final_model_source": "converged_model_unchanged",
      "applied_update_count": 0,
      "applied_control_count": 0,
      "applied_updates": [],
      "attempt_count": 0,
      "quarters_with_target_misses": 0,
      "targeted_quarters": [],
      "target_metric_names": [],
      "allowed_lever_ids": [],
      "warnings": warnings,
      "fail_flags": fail_flags,
      "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
      "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": current_finmo_json if isinstance(current_finmo_json, dict) else {},
    }
  if plan_status != "ready":
    if plan_status == "ready_no_valid_solver_contract" and "cash_translation_failed" not in fail_flags:
      fail_flags.append("cash_translation_failed")
    return {
      "contract_version": "cash_strategy_second_pass_result_v1",
      "status": "skipped_not_ready",
      "execution_state": "skipped_not_ready",
      "solver_execution_state": "not_run",
      "solver_invoked": False,
      "final_model_source": "converged_model_unchanged",
      "applied_update_count": 0,
      "applied_control_count": 0,
      "applied_updates": [],
      "attempt_count": 0,
      "quarters_with_target_misses": 0,
      "targeted_quarters": [],
      "target_metric_names": [],
      "allowed_lever_ids": [],
      "warnings": warnings,
      "fail_flags": list(dict.fromkeys(fail_flags)),
      "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
      "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": current_finmo_json if isinstance(current_finmo_json, dict) else {},
    }
  if not exact_updates:
    if "cash_translation_failed" not in fail_flags:
      fail_flags.append("cash_translation_failed")
    return {
      "contract_version": "cash_strategy_second_pass_result_v1",
      "status": "skipped_no_exact_updates",
      "execution_state": "skipped_no_exact_updates",
      "solver_execution_state": "not_run",
      "solver_invoked": False,
      "final_model_source": "converged_model_unchanged",
      "applied_update_count": 0,
      "applied_control_count": 0,
      "applied_updates": [],
      "attempt_count": 0,
      "quarters_with_target_misses": 0,
      "targeted_quarters": [],
      "target_metric_names": [],
      "allowed_lever_ids": [],
      "warnings": warnings,
      "fail_flags": list(dict.fromkeys(fail_flags)),
      "numeric_execution_boundary": build_numeric_execution_boundary_payload(phase_status=phase_status),
      "numeric_executor": CURRENT_NUMERIC_EXECUTOR,
      "updated_model_input_json": current_model_input_json if isinstance(current_model_input_json, dict) else {},
      "updated_finmo_json": current_finmo_json if isinstance(current_finmo_json, dict) else {},
    }

  execution_result = execute_numeric_plan(
    model_input_json=current_model_input_json if isinstance(current_model_input_json, dict) else {},
    exact_updates=copy.deepcopy(exact_updates),
    numeric_solver_contract=copy.deepcopy(solver_contract),
    review_plan=None,
    phase_status=phase_status,
    executor_context={"source": "_apply_cash_strategy_exact_updates", "execution_mode": "post_convergence_cash_strategy_exact"},
  )
  numeric_solver_result = (
    execution_result.get("numeric_solver_result")
    if isinstance(execution_result.get("numeric_solver_result"), dict)
    else {}
  )
  numeric_execution_plan = (
    execution_result.get("numeric_execution_plan")
    if isinstance(execution_result.get("numeric_execution_plan"), dict)
    else {}
  )
  applied_updates = [
    copy.deepcopy(item)
    for item in (numeric_solver_result.get("exact_updates") or exact_updates)
    if isinstance(item, dict)
  ]
  solver_invoked = bool(
    numeric_solver_result.get("solver_invoked")
    if "solver_invoked" in numeric_solver_result
    else numeric_solver_result.get("used_solver")
  )
  execution_state = str(
    (execution_result.get("numeric_execution_outcome") if isinstance(execution_result.get("numeric_execution_outcome"), dict) else {}).get("execution_state")
    or numeric_solver_result.get("execution_state")
    or numeric_solver_result.get("status")
    or execution_result.get("status")
    or ""
  ).strip()
  solver_execution_state = str(
    numeric_solver_result.get("execution_state")
    or numeric_solver_result.get("status")
    or execution_state
    or ""
  ).strip()
  attempt_count = len(
    [
      item
      for item in (execution_result.get("numeric_execution_attempts") or [])
      if isinstance(item, dict)
    ]
  )
  targeted_quarters = [
    int(_safe_float(item) or 0)
    for item in (numeric_execution_plan.get("targeted_quarters") or [])
    if int(_safe_float(item) or 0) >= 1
  ]
  target_metric_names = [
    str(item).strip()
    for item in (numeric_execution_plan.get("target_metric_names") or [])
    if str(item).strip()
  ]
  allowed_lever_ids = [
    str(item).strip()
    for item in (numeric_execution_plan.get("allowed_lever_ids") or [])
    if str(item).strip()
  ]
  quarter_fit_summary = [
    item
    for item in (
      (
        execution_result.get("numeric_execution_outcome")
        if isinstance(execution_result.get("numeric_execution_outcome"), dict)
        else {}
      ).get("quarter_fit_summary")
      or []
    )
    if isinstance(item, dict)
  ]
  quarters_with_target_misses = len(
    [
      item
      for item in quarter_fit_summary
      if not bool(item.get("within_tolerance_all_targets"))
    ]
  )
  if execution_state.endswith("exception") or execution_state.endswith("error"):
    fail_flags.append("cash_translation_failed")
  updated_model_input_json = execution_result.get("updated_model_input_json") or {}
  updated_finmo_json = execution_result.get("updated_finmo_json") or {}
  return {
    "contract_version": "cash_strategy_second_pass_result_v1",
    "status": "completed" if "cash_translation_failed" not in fail_flags else "completed_with_execution_warnings",
    "execution_state": execution_state,
    "solver_execution_state": solver_execution_state,
    "solver_invoked": solver_invoked,
    "final_model_source": "cash_strategy_solver_applied",
    "applied_update_count": len(applied_updates),
    "applied_control_count": len(applied_updates),
    "applied_updates": applied_updates,
    "attempt_count": attempt_count,
    "quarters_with_target_misses": int(quarters_with_target_misses),
    "targeted_quarters": copy.deepcopy(targeted_quarters),
    "target_metric_names": copy.deepcopy(target_metric_names),
    "allowed_lever_ids": copy.deepcopy(allowed_lever_ids),
    "warnings": warnings,
    "fail_flags": list(dict.fromkeys(fail_flags)),
    "numeric_execution_boundary": execution_result.get("numeric_execution_boundary") or build_numeric_execution_boundary_payload(phase_status=phase_status),
    "numeric_executor": execution_result.get("numeric_executor") or CURRENT_NUMERIC_EXECUTOR,
    "numeric_execution_plan": copy.deepcopy(numeric_execution_plan),
    "debt_schedule_plan": copy.deepcopy(plan.get("debt_schedule_plan") or {}),
    "numeric_execution_attempts": copy.deepcopy(execution_result.get("numeric_execution_attempts") or []),
    "numeric_execution_outcome": copy.deepcopy(execution_result.get("numeric_execution_outcome") or {}),
    "numeric_solver_result": copy.deepcopy(numeric_solver_result),
    "updated_model_input_json": updated_model_input_json if isinstance(updated_model_input_json, dict) else {},
    "updated_finmo_json": updated_finmo_json if isinstance(updated_finmo_json, dict) else {},
  }

def _apply_cash_pass_short_term_debt_current_portion(
  *,
  cash_strategy_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  result = copy.deepcopy(cash_strategy_result if isinstance(cash_strategy_result, dict) else {})
  model_input_json = result.get("updated_model_input_json") if isinstance(result.get("updated_model_input_json"), dict) else {}
  finmo_json = result.get("updated_finmo_json") if isinstance(result.get("updated_finmo_json"), dict) else {}
  if not model_input_json or not finmo_json:
    return result
  try:
    from client_intake_and_finmo.numeric_execution import execute_numeric_plan  # type: ignore
  except Exception:
    from numeric_execution import execute_numeric_plan  # type: ignore
  lever_values = _solved_lever_value_map(model_input_json)
  repayment_values = [
    max(0.0, float(_safe_float(item) or 0.0))
    for item in (lever_values.get(_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID) or [])
  ]
  if not repayment_values:
    return result
  rows = [
    row for row in (finmo_json.get("quarter_rows") or [])
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  ]
  if not rows:
    return result
  exact_updates: List[Dict[str, Any]] = []
  ratio_series: List[Dict[str, Any]] = []
  for row in rows:
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    long_term_debt = max(0.0, float(_safe_float(row.get("long_term_debt")) or 0.0))
    next_four_repayments = sum(
      repayment_values[idx]
      for idx in range(quarter_index - 1, min(len(repayment_values), quarter_index + 3))
    )
    ratio = 0.0
    if long_term_debt > 1.0 and next_four_repayments > 1.0:
      ratio = min(1.0, max(0.0, next_four_repayments / long_term_debt))
    ratio = round(float(ratio), 2)
    exact_updates.append(
      {
        "lever_id": _CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID,
        "quarter_index": quarter_index,
        "exact_value": ratio,
        "issue_codes": ["funding_structure_mismatch"],
        "rationale": (
          "Set current-portion short-term debt from the next four quarters of scheduled debt repayment "
          "divided by long-term debt."
        ),
      }
    )
    ratio_series.append(
      {
        "quarter_index": quarter_index,
        "long_term_debt": int(round(long_term_debt)),
        "next_four_quarters_debt_repayment": int(round(next_four_repayments)),
        "short_term_debt_percent_of_ltd": ratio,
      }
    )
  if not exact_updates:
    return result
  execution_result = execute_numeric_plan(
    model_input_json=copy.deepcopy(model_input_json),
    exact_updates=copy.deepcopy(exact_updates),
    numeric_solver_contract={
      "pass_name": "cash_strategy_review",
      "contract_scope": "cash_pass_debt_schedule_semantics",
      "solver_phase_status": "phase_6_cash_strategy_solver_live",
      "solver_settings": {"max_solver_attempts_per_pass": 1},
    },
    review_plan=None,
    phase_status="phase_6_cash_strategy_solver_live",
    executor_context={
      "source": "_apply_cash_pass_short_term_debt_current_portion",
      "execution_mode": "deterministic_debt_schedule_semantics",
    },
  )
  result["updated_model_input_json"] = execution_result.get("updated_model_input_json") or model_input_json
  result["updated_finmo_json"] = execution_result.get("updated_finmo_json") or finmo_json
  result["short_term_debt_current_portion_policy"] = {
    "contract_version": "cash_pass_short_term_debt_current_portion_v1",
    "status": "applied",
    "lever_id": _CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID,
    "basis": "next_four_quarters_scheduled_debt_repayment_divided_by_long_term_debt",
    "rows": copy.deepcopy(ratio_series),
  }
  applied_updates = [
    copy.deepcopy(item)
    for item in (result.get("applied_updates") or [])
    if isinstance(item, dict)
  ]
  result["applied_updates"] = applied_updates + copy.deepcopy(exact_updates)
  result["applied_update_count"] = len(result["applied_updates"])
  result["applied_control_count"] = len(result["applied_updates"])
  return result

def _apply_cash_policy_surplus_cleanup(
  *,
  cash_strategy_result: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  max_passes: int = 20,
) -> Dict[str, Any]:
  result = copy.deepcopy(cash_strategy_result if isinstance(cash_strategy_result, dict) else {})
  model_input_json = result.get("updated_model_input_json") if isinstance(result.get("updated_model_input_json"), dict) else {}
  finmo_json = result.get("updated_finmo_json") if isinstance(result.get("updated_finmo_json"), dict) else {}
  if not model_input_json or not finmo_json:
    return result
  try:
    from client_intake_and_finmo.numeric_execution import execute_numeric_plan  # type: ignore
  except Exception:
    from numeric_execution import execute_numeric_plan  # type: ignore

  cleanup_passes: List[Dict[str, Any]] = []
  selected_cash_strategy = _resolved_cash_strategy(financials_json)
  live_quarter_count = len(_cash_strategy_live_quarter_rows(finmo_json)) or 20
  cleanup_pass_limit = max(max(1, int(max_passes)), live_quarter_count * 2)
  for pass_index in range(1, cleanup_pass_limit + 1):
    envelope = _cash_strategy_validation_violation_envelope(
      selected_cash_strategy=selected_cash_strategy,
      finmo_payload=copy.deepcopy(finmo_json),
      model_input_json=copy.deepcopy(model_input_json),
    )
    lever_values = _solved_lever_value_map(model_input_json)
    distribution_values = [
      int(round(float(_safe_float(item) or 0.0)))
      for item in (lever_values.get(_CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID) or [])
    ]
    debt_repayment_values = [
      int(round(float(_safe_float(item) or 0.0)))
      for item in (lever_values.get(_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID) or [])
    ]
    exact_updates: List[Dict[str, Any]] = []
    current_value_by_update_key: Dict[tuple[str, int], int] = {}
    for quarter_payload in (envelope.get("quarter_envelopes") or []):
      if not isinstance(quarter_payload, dict):
        continue
      quarter_index = int(_safe_float(quarter_payload.get("quarter_index")) or 0)
      residual_surplus = int(round(float(_safe_float(quarter_payload.get("deployable_surplus_above_ceiling")) or 0.0)))
      residual_gap = int(round(float(_safe_float(quarter_payload.get("residual_funding_gap")) or 0.0)))
      if quarter_index < 1 or residual_surplus <= 0 or residual_gap > 0:
        continue
      current_distribution = (
        int(distribution_values[quarter_index - 1])
        if quarter_index - 1 < len(distribution_values)
        else int(round(float(_safe_float(quarter_payload.get("distribution_current_value")) or 0.0)))
      )
      current_debt_repayment = (
        int(debt_repayment_values[quarter_index - 1])
        if quarter_index - 1 < len(debt_repayment_values)
        else int(round(float(_safe_float(quarter_payload.get("debt_repayment_current_value")) or 0.0)))
      )
      cash_policy = quarter_payload.get("cash_policy") if isinstance(quarter_payload.get("cash_policy"), dict) else {}
      distribution_weight = max(0.0, float(_safe_float(cash_policy.get("distribution_weight")) or 0.0))
      debt_paydown_weight = max(0.0, float(_safe_float(cash_policy.get("debt_paydown_weight")) or 0.0))
      weight_total = distribution_weight + debt_paydown_weight
      if weight_total <= 0.0:
        distribution_weight = 1.0
        debt_paydown_weight = 0.0
        weight_total = 1.0
      distribution_weight = distribution_weight / weight_total
      debt_paydown_weight = debt_paydown_weight / weight_total
      max_debt_add = int(round(float(_safe_float(quarter_payload.get("max_additional_debt_paydown")) or 0.0)))
      max_distribution_add = int(round(float(_safe_float(quarter_payload.get("max_additional_distribution")) or residual_surplus)))
      debt_add = int(min(max_debt_add, max(0, round(residual_surplus * debt_paydown_weight))))
      distribution_add = int(min(max_distribution_add, max(0, residual_surplus - debt_add)))
      remaining_surplus = int(max(0, residual_surplus - debt_add - distribution_add))
      if remaining_surplus > 0 and max_debt_add > debt_add:
        extra_debt = int(min(max_debt_add - debt_add, remaining_surplus))
        debt_add += extra_debt
        remaining_surplus -= extra_debt
      if remaining_surplus > 0 and max_distribution_add > distribution_add:
        distribution_add += int(min(max_distribution_add - distribution_add, remaining_surplus))
      if debt_add > 0:
        current_value_by_update_key[(_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID, quarter_index)] = int(current_debt_repayment)
        exact_updates.append(
          {
            "lever_id": _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
            "quarter_index": quarter_index,
            "exact_value": int(current_debt_repayment + debt_add),
            "issue_codes": ["funding_structure_mismatch"],
            "rationale": (
              "Deterministic SQL cash policy cleanup: deploy actual post-action surplus above the "
              "strategy ceiling through the mapped Debt Repayment lever after FINMO recalculation."
            ),
          }
        )
      if distribution_add > 0:
        current_value_by_update_key[(_CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID, quarter_index)] = int(current_distribution)
        exact_updates.append(
          {
            "lever_id": _CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID,
            "quarter_index": quarter_index,
            "exact_value": int(current_distribution + distribution_add),
            "issue_codes": ["funding_structure_mismatch"],
            "rationale": (
              "Deterministic SQL cash policy cleanup: deploy actual post-action surplus above the "
              "strategy ceiling through the mapped Distributions lever after FINMO recalculation."
            ),
          }
        )
      if exact_updates:
        break
    if not exact_updates:
      break
    base_model_input_json = copy.deepcopy(model_input_json)
    execution_result = execute_numeric_plan(
      model_input_json=copy.deepcopy(base_model_input_json),
      exact_updates=copy.deepcopy(exact_updates),
      numeric_solver_contract={},
      review_plan=None,
      phase_status="cash_policy_surplus_cleanup",
      executor_context={
        "source": "_apply_cash_policy_surplus_cleanup",
        "execution_mode": "deterministic_cash_policy_cleanup",
      },
    )
    candidate_model_input_json = (
      execution_result.get("updated_model_input_json")
      if isinstance(execution_result.get("updated_model_input_json"), dict)
      else model_input_json
    )
    candidate_finmo_json = (
      execution_result.get("updated_finmo_json")
      if isinstance(execution_result.get("updated_finmo_json"), dict)
      else finmo_json
    )
    candidate_envelope = _cash_strategy_validation_violation_envelope(
      selected_cash_strategy=selected_cash_strategy,
      finmo_payload=copy.deepcopy(candidate_finmo_json),
      model_input_json=copy.deepcopy(candidate_model_input_json),
    )
    buffer_gap_after_candidate = max(
      [
        int(round(float(_safe_float(item.get("residual_funding_gap")) or 0.0)))
        for item in (candidate_envelope.get("quarter_envelopes") or [])
        if isinstance(item, dict)
      ]
      or [0]
    )
    if buffer_gap_after_candidate > 0:
      remaining_reduction = int(buffer_gap_after_candidate)
      guarded_updates = copy.deepcopy(exact_updates)
      for lever_id in (_CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID, _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID):
        if remaining_reduction <= 0:
          break
        for update in guarded_updates:
          if remaining_reduction <= 0:
            break
          if str(update.get("lever_id") or "").strip() != lever_id:
            continue
          quarter_index = int(_safe_float(update.get("quarter_index")) or 0)
          current_floor = int(current_value_by_update_key.get((lever_id, quarter_index), 0))
          candidate_value = int(round(float(_safe_float(update.get("exact_value")) or 0.0)))
          reducible_amount = int(max(0, candidate_value - current_floor))
          if reducible_amount <= 0:
            continue
          reduction = int(min(reducible_amount, remaining_reduction))
          update["exact_value"] = int(candidate_value - reduction)
          update["cash_policy_guardrail_reduction"] = int(reduction)
          update["cash_policy_guardrail_reason"] = (
            "Reduced Python-owned surplus cleanup so rebuilt FINMO keeps every live quarter "
            "at or above the required cash buffer."
          )
          remaining_reduction -= reduction
      guarded_updates = [
        update for update in guarded_updates
        if int(round(float(_safe_float(update.get("exact_value")) or 0.0)))
        > int(current_value_by_update_key.get((str(update.get("lever_id") or "").strip(), int(_safe_float(update.get("quarter_index")) or 0)), 0))
      ]
      if not guarded_updates:
        break
      execution_result = execute_numeric_plan(
        model_input_json=copy.deepcopy(base_model_input_json),
        exact_updates=copy.deepcopy(guarded_updates),
        numeric_solver_contract={},
        review_plan=None,
        phase_status="cash_policy_surplus_cleanup",
        executor_context={
          "source": "_apply_cash_policy_surplus_cleanup",
          "execution_mode": "deterministic_cash_policy_cleanup_guarded",
          "buffer_gap_after_initial_candidate": int(buffer_gap_after_candidate),
        },
      )
      exact_updates = guarded_updates
    model_input_json = (
      execution_result.get("updated_model_input_json")
      if isinstance(execution_result.get("updated_model_input_json"), dict)
      else model_input_json
    )
    finmo_json = (
      execution_result.get("updated_finmo_json")
      if isinstance(execution_result.get("updated_finmo_json"), dict)
      else finmo_json
    )
    numeric_solver_result = (
      execution_result.get("numeric_solver_result")
      if isinstance(execution_result.get("numeric_solver_result"), dict)
      else {}
    )
    applied_updates = [
      copy.deepcopy(item)
      for item in (numeric_solver_result.get("exact_updates") or exact_updates)
      if isinstance(item, dict)
    ]
    cleanup_passes.append(
      {
        "pass_index": pass_index,
        "applied_update_count": len(applied_updates),
        "applied_updates": applied_updates,
      }
    )
  if cleanup_passes:
    prior_updates = [
      copy.deepcopy(item)
      for item in (result.get("applied_updates") or [])
      if isinstance(item, dict)
    ]
    cleanup_updates = [
      copy.deepcopy(item)
      for cleanup_pass in cleanup_passes
      for item in (cleanup_pass.get("applied_updates") or [])
      if isinstance(item, dict)
    ]
    result["updated_model_input_json"] = model_input_json
    result["updated_finmo_json"] = finmo_json
    result["applied_updates"] = prior_updates + cleanup_updates
    result["applied_update_count"] = len(result["applied_updates"])
    result["applied_control_count"] = len(result["applied_updates"])
    result["cash_policy_surplus_cleanup"] = {
      "contract_version": "cash_policy_surplus_cleanup_v1",
      "source_of_truth": "sql.post_intake_cash_policy_lookup",
      "mapped_lever_ids": [
        _CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID,
        _CASH_STRATEGY_DISTRIBUTIONS_LEVER_ID,
      ],
      "deployment_mode": "sequential_actual_state_recompute",
      "pass_limit": int(cleanup_pass_limit),
      "pass_count": len(cleanup_passes),
      "passes": cleanup_passes,
    }
  return result

def _validate_cash_strategy_post_pass(
  *,
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  baseline_issue_ledger: Optional[List[Dict[str, Any]]],
  candidate_model_input_json: Optional[Dict[str, Any]],
  candidate_finmo_json: Optional[Dict[str, Any]],
  iteration: int,
) -> Dict[str, Any]:
  scan_memo = {
    "contract_version": "post_intake_deterministic_cash_validation_v1",
    "status": "ready",
    "source_of_truth": "cash_policy_and_hard_rule_validators",
    "issues": [],
    "remaining_issues": [],
  }
  # Cash pass owns liquidity, funding, debt/equity usage, and accounting gates.
  # It must not reopen convergence-owned issue classes after convergence cleared.
  refreshed_issue_ledger = copy.deepcopy(baseline_issue_ledger or [])
  resolution_summary = _build_resolution_summary_from_issue_ledger(
    before_memo=copy.deepcopy(scan_memo),
    issue_status_records=copy.deepcopy(refreshed_issue_ledger),
  )
  realism_memo_json = _build_realism_memo_from_issue_ledger(
    before_memo=copy.deepcopy(scan_memo),
    issue_status_records=copy.deepcopy(refreshed_issue_ledger),
    resolution_summary=copy.deepcopy(resolution_summary),
    iteration=iteration,
  )
  controller_resolution_state = _build_controller_resolution_state_from_issue_ledger(
    issue_status_records=copy.deepcopy(refreshed_issue_ledger),
    iteration=iteration,
    current_finmo_json=copy.deepcopy(candidate_finmo_json or {}),
  )
  hard_rule_assessment = _build_unified_hard_rule_assessment(
    controller_resolution_state=copy.deepcopy(controller_resolution_state),
    current_finmo_json=copy.deepcopy(candidate_finmo_json or {}),
  )
  remaining_issue_codes = [
    str(item.get("issue_code") or "").strip().lower()
    for item in (controller_resolution_state.get("remaining_issues") or [])
    if isinstance(item, dict) and str(item.get("issue_code") or "").strip()
  ]
  failed_rule_codes = [
    str(item).strip()
    for item in (hard_rule_assessment.get("failed_rule_codes") or [])
    if str(item).strip()
  ]
  cash_validation_envelope = _cash_strategy_validation_violation_envelope(
    selected_cash_strategy=_resolved_cash_strategy(financials_json),
    finmo_payload=copy.deepcopy(candidate_finmo_json or {}),
    model_input_json=copy.deepcopy(candidate_model_input_json or {}),
  )
  cash_buffer_violations = [
    {
      "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
      "ending_cash": int(round(float(_safe_float(item.get("ending_cash")) or 0.0))),
      "buffer": int(round(float(_safe_float(item.get("buffer")) or 0.0))),
    }
    for item in (cash_validation_envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict) and bool(item.get("buffer_violation"))
  ]
  cash_distribution_violations = [
    {
      "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
      "ending_cash": int(round(float(_safe_float(item.get("ending_cash")) or 0.0))),
      "buffer": int(round(float(_safe_float(item.get("buffer")) or 0.0))),
      "distribution_current_value": int(round(float(_safe_float(item.get("distribution_current_value")) or 0.0))),
    }
    for item in (cash_validation_envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict) and bool(item.get("distribution_violation"))
  ]
  cash_surplus_ceiling_violations = [
    {
      "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
      "ending_cash_after_hard_rules": int(round(float(_safe_float(item.get("ending_cash_after_hard_rules")) or 0.0))),
      "cash_ceiling": int(round(float(_safe_float(item.get("cash_ceiling")) or 0.0))),
      "deployable_surplus_above_ceiling": int(round(float(_safe_float(item.get("deployable_surplus_above_ceiling")) or 0.0))),
      "cash_policy": copy.deepcopy(item.get("cash_policy") or {}),
    }
    for item in (cash_validation_envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
    and bool(item.get("deploy_above_ceiling_required"))
    and int(round(float(_safe_float(item.get("deployable_surplus_above_ceiling")) or 0.0))) > 0
  ]
  cash_contract_failures: List[Dict[str, Any]] = []
  selected_strategy = _resolved_cash_strategy(financials_json)
  if selected_strategy not in {"preserve_cash", "balanced", "shareholder_return"}:
    cash_contract_failures.append(
      {
        "error": "cash_strategy_contract_invalid_strategy",
        "reason": "Cash pass supports only preserve_cash, balanced, and shareholder_return.",
        "selected_cash_strategy": selected_strategy,
      }
    )
  model_input = candidate_model_input_json if isinstance(candidate_model_input_json, dict) else {}
  derived_policies = model_input.get("derived_driver_policies") if isinstance(model_input.get("derived_driver_policies"), dict) else {}
  debt_rate_policy = derived_policies.get("debt_interest_rate_policy") if isinstance(derived_policies.get("debt_interest_rate_policy"), dict) else {}
  debt_rate_source = debt_rate_policy.get("source_detail") if isinstance(debt_rate_policy.get("source_detail"), dict) else {}
  if not debt_rate_policy:
    cash_contract_failures.append(
      {
        "error": "cash_debt_interest_rate_policy_missing",
        "reason": "Cash pass requires the model-input Interest Rate driver to be backed by the SBA 7(a) loan-rate policy.",
      }
    )
  elif str(debt_rate_source.get("source") or "").strip() != "sba_loan_7a_raw":
    cash_contract_failures.append(
      {
        "error": "cash_debt_interest_rate_policy_not_sba_backed",
        "reason": "Cash pass requires interest-rate coverage from sba_loan_7a_raw, not a silent fallback.",
        "source_detail": copy.deepcopy(debt_rate_source),
      }
    )
  else:
    expected_sba_rate = _safe_float(debt_rate_policy.get("annual_rate_decimal"))
    if expected_sba_rate is None:
      expected_sba_rate = _safe_float(debt_rate_source.get("annual_rate_decimal"))
    if expected_sba_rate is None or float(expected_sba_rate) <= 0.0:
      cash_contract_failures.append(
        {
          "error": "cash_debt_interest_rate_policy_rate_missing",
          "reason": "SBA-backed debt_interest_rate_policy must provide a positive annual_rate_decimal.",
          "source_detail": copy.deepcopy(debt_rate_source),
        }
      )
    else:
      expected_sba_rate = round(float(expected_sba_rate), 6)
      interest_rate_values = (
        _solved_lever_value_map(candidate_model_input_json).get("expenses::Interest Rate")
        or []
      )
      horizon_count = _cash_contract_horizon_quarters()
      mismatched_forecast_rates = [
        {
          "quarter_index": index + 1,
          "actual_interest_rate": round(float(_safe_float(value) or 0.0), 6),
          "expected_sba_interest_rate": expected_sba_rate,
        }
        for index, value in enumerate(interest_rate_values[:horizon_count])
        if round(float(_safe_float(value) or 0.0), 6) != expected_sba_rate
      ]
      if len(interest_rate_values) < horizon_count:
        mismatched_forecast_rates.append(
          {
            "quarter_index": "missing",
            "actual_interest_rate": None,
            "expected_sba_interest_rate": expected_sba_rate,
            "received_forecast_rate_count": len(interest_rate_values),
          }
        )
      if mismatched_forecast_rates:
        cash_contract_failures.append(
          {
            "error": "cash_debt_interest_rate_forecast_mismatch",
            "reason": f"Stub Q0 may reflect intake, but every forecast quarter Q1-Q{horizon_count} must equal the SBA-backed interest-rate policy.",
            "violating_quarters": copy.deepcopy(mismatched_forecast_rates[:horizon_count]),
            "source_detail": copy.deepcopy(debt_rate_source),
          }
        )
  debt_schedule = _cash_strategy_debt_schedule_snapshot(
    finmo_payload=copy.deepcopy(candidate_finmo_json or {}),
    model_input_json=copy.deepcopy(candidate_model_input_json or {}),
  )
  minimum_debt_schedule_plan: Dict[str, Any] = {}
  try:
    minimum_debt_schedule_plan = _cash_pass_minimum_debt_schedule_plan(
      model_input_json=copy.deepcopy(candidate_model_input_json or {}),
      finmo_payload=copy.deepcopy(candidate_finmo_json or {}),
      financials_json=copy.deepcopy(financials_json or {}),
      selected_cash_strategy=selected_strategy,
    )
  except Exception as exc:
    cash_contract_failures.append(
      {
        "error": "cash_debt_schedule_minimum_plan_failed",
        "reason": str(exc),
      }
    )
  debt_schedule_rows = [
    item for item in (debt_schedule.get("rows") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  ]
  if not debt_schedule_rows:
    cash_contract_failures.append(
      {
        "error": "cash_debt_schedule_missing",
        "reason": "Cash pass requires a debt schedule snapshot for every live quarter.",
      }
    )
  missing_interest_rows = [
    {
      "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
      "opening_debt": int(round(float(_safe_float(item.get("opening_debt")) or 0.0))),
      "closing_debt": int(round(float(_safe_float(item.get("closing_debt")) or 0.0))),
      "interest_rate": round(float(_safe_float(item.get("interest_rate")) or 0.0), 6),
    }
    for item in debt_schedule_rows
    if (
      int(round(float(_safe_float(item.get("opening_debt")) or 0.0))) > 0
      or int(round(float(_safe_float(item.get("closing_debt")) or 0.0))) > 0
      or int(round(float(_safe_float(item.get("actual_debt_issuance")) or 0.0))) > 0
    )
    and round(float(_safe_float(item.get("interest_rate")) or 0.0), 6) <= 0.0
  ]
  if missing_interest_rows:
    cash_contract_failures.append(
      {
        "error": "cash_debt_schedule_interest_rate_missing",
        "reason": "Any quarter with debt outstanding or new borrowing must have a positive interest rate before FINMO calculates interest.",
        "violating_quarters": copy.deepcopy(missing_interest_rows),
      }
    )
  lever_values = _solved_lever_value_map(candidate_model_input_json)
  debt_repayment_values = [
    max(0.0, float(_safe_float(item) or 0.0))
    for item in (lever_values.get(_CASH_STRATEGY_DEBT_REPAYMENT_LEVER_ID) or [])
  ]
  short_term_ratio_values = [
    max(0.0, float(_safe_float(item) or 0.0))
    for item in (lever_values.get(_CASH_STRATEGY_SHORT_TERM_DEBT_RATIO_LEVER_ID) or [])
  ]
  missing_short_term_current_portion_rows: List[Dict[str, Any]] = []
  for item in debt_schedule_rows:
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    if quarter_index < 1:
      continue
    closing_debt = max(0.0, float(_safe_float(item.get("closing_debt")) or 0.0))
    next_four_repayments = sum(
      debt_repayment_values[idx]
      for idx in range(quarter_index - 1, min(len(debt_repayment_values), quarter_index + 3))
    )
    ratio = (
      float(short_term_ratio_values[quarter_index - 1])
      if quarter_index - 1 < len(short_term_ratio_values)
      else 0.0
    )
    if closing_debt > 1.0 and next_four_repayments > 1.0 and round(ratio, 2) <= 0.0:
      missing_short_term_current_portion_rows.append(
        {
          "quarter_index": quarter_index,
          "closing_debt": int(round(closing_debt)),
          "next_four_quarters_debt_repayment": int(round(next_four_repayments)),
          "short_term_debt_percent_of_ltd": round(ratio, 2),
        }
      )
  if missing_short_term_current_portion_rows:
    cash_contract_failures.append(
      {
        "error": "cash_debt_schedule_short_term_current_portion_missing",
        "reason": (
          "Any quarter with debt outstanding and scheduled repayment in the next four quarters must set "
          "Short Term Debt (% of LTD) from the current debt schedule."
        ),
        "violating_quarters": copy.deepcopy(missing_short_term_current_portion_rows),
      }
    )
  minimum_repayment_rows = {
    int(_safe_float(item.get("quarter_index")) or 0): int(round(float(_safe_float(item.get("minimum_principal_payment")) or 0.0)))
    for item in (minimum_debt_schedule_plan.get("rows") or [])
    if isinstance(item, dict) and int(_safe_float(item.get("quarter_index")) or 0) >= 1
  }
  under_scheduled_debt_rows = []
  for quarter_index, required_minimum in sorted(minimum_repayment_rows.items()):
    actual_repayment = (
      int(round(float(debt_repayment_values[quarter_index - 1])))
      if quarter_index - 1 < len(debt_repayment_values)
      else 0
    )
    if required_minimum > 0 and actual_repayment < required_minimum:
      under_scheduled_debt_rows.append(
        {
          "quarter_index": int(quarter_index),
          "minimum_principal_payment": int(required_minimum),
          "actual_debt_repayment": int(actual_repayment),
        }
      )
  if under_scheduled_debt_rows:
    cash_contract_failures.append(
      {
        "error": "cash_debt_schedule_minimum_principal_not_applied",
        "reason": "Every quarter with scheduled debt service must keep at least the SQL cash-policy minimum principal payment.",
        "violating_quarters": copy.deepcopy(under_scheduled_debt_rows),
      }
    )
  cash_failed_rule_codes: List[str] = []
  if cash_buffer_violations:
    cash_failed_rule_codes.append("liquidity_failure")
  if cash_distribution_violations:
    cash_failed_rule_codes.append("funding_structure_mismatch")
  if cash_surplus_ceiling_violations:
    cash_failed_rule_codes.append("funding_structure_mismatch")
  if cash_contract_failures:
    cash_failed_rule_codes.append("funding_structure_mismatch")
  keep_changes = bool(
    hard_rule_assessment.get("all_hard_rules_cleared")
    and not cash_buffer_violations
    and not cash_distribution_violations
    and not cash_surplus_ceiling_violations
    and not cash_contract_failures
  )
  detail_parts: List[str] = []
  if remaining_issue_codes:
    detail_parts.append(f"reopened_issues={remaining_issue_codes}")
  if failed_rule_codes:
    detail_parts.append(f"failed_hard_rules={failed_rule_codes}")
  if cash_buffer_violations:
    detail_parts.append(
      f"cash_buffer_violations={[int(_safe_float(item.get('quarter_index')) or 0) for item in cash_buffer_violations]}"
    )
  if cash_distribution_violations:
    detail_parts.append(
      f"cash_distribution_violations={[int(_safe_float(item.get('quarter_index')) or 0) for item in cash_distribution_violations]}"
    )
  if cash_surplus_ceiling_violations:
    detail_parts.append(
      f"cash_surplus_ceiling_violations={[int(_safe_float(item.get('quarter_index')) or 0) for item in cash_surplus_ceiling_violations]}"
    )
  if cash_contract_failures:
    detail_parts.append(
      "cash_contract_failures="
      + str([str(item.get("error") or "").strip() for item in cash_contract_failures if isinstance(item, dict)])
    )
  return {
    "contract_version": "cash_strategy_post_validation_v1",
    "status": "accepted" if keep_changes else "reverted",
    "keep_changes": keep_changes,
    "detail": "; ".join(detail_parts).strip(),
    "scan_memo": copy.deepcopy(scan_memo),
    "resolution_summary": copy.deepcopy(resolution_summary),
    "realism_memo_json": copy.deepcopy(realism_memo_json),
    "issue_ledger": copy.deepcopy(refreshed_issue_ledger),
    "cash_pass_scope": "cash_accounting_and_cash_contract_only",
    "ignored_non_cash_scan_issue_codes": [],
    "controller_resolution_state": copy.deepcopy(controller_resolution_state),
    "hard_rule_assessment": copy.deepcopy(hard_rule_assessment),
    "remaining_issue_codes": remaining_issue_codes,
    "failed_rule_codes": list(dict.fromkeys([*failed_rule_codes, *cash_failed_rule_codes])),
    "cash_validation_envelope": copy.deepcopy(cash_validation_envelope),
    "cash_contract_failures": copy.deepcopy(cash_contract_failures),
    "debt_schedule_snapshot": copy.deepcopy(debt_schedule),
    "minimum_debt_schedule_plan": copy.deepcopy(minimum_debt_schedule_plan),
    "cash_buffer_violations": copy.deepcopy(cash_buffer_violations),
    "cash_distribution_violations": copy.deepcopy(cash_distribution_violations),
    "cash_surplus_ceiling_violations": copy.deepcopy(cash_surplus_ceiling_violations),
  }

def _raise_cash_pass_unresolved_liquidity_if_needed(
  *,
  financials_json: Optional[Dict[str, Any]],
  final_model_input_json: Optional[Dict[str, Any]],
  final_finmo_json: Optional[Dict[str, Any]],
  cash_strategy_review_context: Optional[Dict[str, Any]] = None,
  cash_strategy_review_decision: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_plan: Optional[Dict[str, Any]] = None,
  cash_strategy_second_pass_result: Optional[Dict[str, Any]] = None,
) -> None:
  envelope = _cash_strategy_validation_violation_envelope(
    selected_cash_strategy=_resolved_cash_strategy(financials_json),
    finmo_payload=copy.deepcopy(final_finmo_json or {}),
    model_input_json=copy.deepcopy(final_model_input_json or {}),
  )
  violations = [
    {
      "quarter_index": int(_safe_float(item.get("quarter_index")) or 0),
      "ending_cash": int(round(float(_safe_float(item.get("ending_cash")) or 0.0))),
      "required_cash_buffer": int(round(float(_safe_float(item.get("buffer")) or 0.0))),
      "residual_funding_gap": int(round(float(_safe_float(item.get("residual_funding_gap")) or 0.0))),
    }
    for item in (envelope.get("quarter_envelopes") or [])
    if isinstance(item, dict)
    and int(round(float(_safe_float(item.get("ending_cash")) or 0.0)))
    < int(round(float(_safe_float(item.get("buffer")) or 0.0)))
  ]
  if not violations:
    return
  diagnostics = {
    "failure_stage": "cash_strategy",
    "failure_reason": "liquidity_failure",
    "selected_cash_strategy": str(envelope.get("selected_cash_strategy") or "").strip(),
    "validation_error": {
      "rejected": True,
      "reason_code": "liquidity_failure",
      "reason": "Cash pass finished with live-quarter ending_cash below the required cash buffer.",
    },
    "pre_solver_validation": {
      "flags": ["liquidity_failure"],
      "errors": [
        {
          "error": "liquidity_failure",
          "reason": (
            "Cash pass is a hard viability gate: every live quarter must satisfy "
            "ending_cash >= required_cash_buffer."
          ),
          "validation_category": "cash_strategy",
          "violating_quarters": [int(item.get("quarter_index") or 0) for item in violations],
        }
      ],
    },
    "cash_buffer_violations": copy.deepcopy(violations),
    "cash_validation_envelope": copy.deepcopy(envelope),
    "cash_strategy_review_context": copy.deepcopy(cash_strategy_review_context or {}),
    "cash_strategy_review_decision": copy.deepcopy(cash_strategy_review_decision or {}),
    "cash_strategy_second_pass_plan": copy.deepcopy(cash_strategy_second_pass_plan or {}),
    "cash_strategy_second_pass_result": copy.deepcopy(cash_strategy_second_pass_result or {}),
  }
  raise StructuredSystemRunFailure(
    detail="liquidity_failure",
    diagnostics=diagnostics,
  )

def _build_cash_strategy_effect_summary(
  *,
  financials_json: Optional[Dict[str, Any]],
  review_decision_payload: Optional[Dict[str, Any]],
  second_pass_result: Optional[Dict[str, Any]],
  first_pass_finmo_json: Optional[Dict[str, Any]],
  final_finmo_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  financials = financials_json if isinstance(financials_json, dict) else {}
  review_payload = review_decision_payload if isinstance(review_decision_payload, dict) else {}
  decision = review_payload.get("decision") if isinstance(review_payload.get("decision"), dict) else {}
  result = second_pass_result if isinstance(second_pass_result, dict) else {}
  first_finmo = first_pass_finmo_json if isinstance(first_pass_finmo_json, dict) else {}
  final_finmo = final_finmo_json if isinstance(final_finmo_json, dict) else {}

  first_metrics = _cash_review_quarter_metrics(first_finmo)
  final_metrics = _cash_review_quarter_metrics(final_finmo)

  first_cash_series = [float(_safe_float(item.get("ending_cash")) or 0.0) for item in first_metrics]
  final_cash_series = [float(_safe_float(item.get("ending_cash")) or 0.0) for item in final_metrics]
  first_debt_issuance = _finmo_labeled_series(first_finmo, section_key="cash_flow", label="Debt Issuance (New Borrowing)")
  final_debt_issuance = _finmo_labeled_series(final_finmo, section_key="cash_flow", label="Debt Issuance (New Borrowing)")
  first_debt_repayment = _finmo_labeled_series(first_finmo, section_key="cash_flow", label="Debt Repayment")
  final_debt_repayment = _finmo_labeled_series(final_finmo, section_key="cash_flow", label="Debt Repayment")
  first_distributions = _finmo_labeled_series(first_finmo, section_key="cash_flow", label="Distributions")
  final_distributions = _finmo_labeled_series(final_finmo, section_key="cash_flow", label="Distributions")

  first_final_cash = first_cash_series[-1] if first_cash_series else 0.0
  final_final_cash = final_cash_series[-1] if final_cash_series else 0.0
  first_peak_cash = max(first_cash_series) if first_cash_series else 0.0
  final_peak_cash = max(final_cash_series) if final_cash_series else 0.0
  first_final_debt = float(
    (float(_safe_float((first_metrics[-1] if first_metrics else {}).get("short_term_debt")) or 0.0))
    + (float(_safe_float((first_metrics[-1] if first_metrics else {}).get("long_term_debt")) or 0.0))
  )
  final_final_debt = float(
    (float(_safe_float((final_metrics[-1] if final_metrics else {}).get("short_term_debt")) or 0.0))
    + (float(_safe_float((final_metrics[-1] if final_metrics else {}).get("long_term_debt")) or 0.0))
  )

  changed_quarters = _series_changed_count(first_cash_series, final_cash_series, tolerance=1.0)
  material_change_detected = any([
    abs(final_final_cash - first_final_cash) > 1.0,
    abs(final_peak_cash - first_peak_cash) > 1.0,
    _series_changed_count(first_debt_issuance, final_debt_issuance, tolerance=1.0) > 0,
    _series_changed_count(first_debt_repayment, final_debt_repayment, tolerance=1.0) > 0,
    _series_changed_count(first_distributions, final_distributions, tolerance=1.0) > 0,
    abs(final_final_debt - first_final_debt) > 1.0,
  ])

  recommendation_mode = str(decision.get("recommendation_mode") or "").strip()
  final_model_source = str(result.get("final_model_source") or "").strip() or "first_pass"
  result_status = str(result.get("status") or "").strip()

  summary_line = (
    f"Cash review selected `{final_model_source}` with status `{result_status}`. "
    f"Final ending cash changed by {_format_currency(final_final_cash - first_final_cash)} "
    f"and peak cash changed by {_format_currency(final_peak_cash - first_peak_cash)}."
  )
  if recommendation_mode == "adjust" and not material_change_detected:
    summary_line += " Review requested adjustment, but no material post-solve change was achieved."
  elif recommendation_mode == "maintain":
    summary_line += " Review determined the first-pass model already expressed the chosen cash strategy adequately."

  return {
    "contract_version": "cash_strategy_effect_summary_v1",
    "selected_cash_strategy": str(financials.get("cash_strategy") or "").strip(),
    "review_status": str(review_payload.get("status") or "").strip(),
    "recommendation_mode": recommendation_mode,
    "recommended_adjustment_count": len([item for item in (decision.get("recommended_adjustments") or []) if isinstance(item, dict)]),
    "second_pass_status": result_status,
    "final_model_source": final_model_source,
    "applied_control_count": int(_safe_float(result.get("applied_control_count")) or 0),
    "material_change_detected": bool(material_change_detected),
    "changed_cash_quarter_count": changed_quarters,
    "cash_metrics": {
      "first_pass_final_cash": first_final_cash,
      "final_pass_final_cash": final_final_cash,
      "delta_final_cash": float(final_final_cash - first_final_cash),
      "first_pass_peak_cash": first_peak_cash,
      "final_pass_peak_cash": final_peak_cash,
      "delta_peak_cash": float(final_peak_cash - first_peak_cash),
      "first_pass_final_debt": first_final_debt,
      "final_pass_final_debt": final_final_debt,
      "delta_final_debt": float(final_final_debt - first_final_debt),
    },
    "deployment_deltas": {
      "debt_issuance_total_delta": float(_sum_series(final_debt_issuance) - _sum_series(first_debt_issuance)),
      "debt_repayment_total_delta": float(_sum_series(final_debt_repayment) - _sum_series(first_debt_repayment)),
      "distributions_total_delta": float(_sum_series(final_distributions) - _sum_series(first_distributions)),
    },
    "summary_line": summary_line,
  }
