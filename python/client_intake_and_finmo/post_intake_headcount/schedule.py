from __future__ import annotations

import json
import os
import time
import requests
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
  post_intake_build_prompt_from_contract,
  post_intake_contract_forecast_horizon_quarter_count,
  post_intake_gpt_contract_horizon_errors,
  post_intake_gpt_contract_normalize_payload,
  post_intake_gpt_contract_openai_schema,
  post_intake_gpt_contract_payload_errors,
  post_intake_gpt_context_filter_payload,
  post_intake_gpt_context_request_char_budget,
  post_intake_process_sequence_step,
)
from client_intake_and_finmo.fail_fast.post_intake_fail_fast import (  # type: ignore
  post_intake_fail_fast_raise,
)
from .lookup import (
  PAYROLL_HEADCOUNT_DRAFT_COLUMN,
  post_intake_headcount_policy_for,
  validate_payroll_headcount_payload,
)


PAYROLL_HEADCOUNT_SOURCE = "headcount_schedule_derived"
PAYROLL_HEADCOUNT_POLICY_VERSION = "payroll_headcount_schedule_policy_v1"
PAYROLL_HEADCOUNT_LEVER_ID = "expenses::Payroll"
PAYROLL_HEADCOUNT_CONTRACT_NAME = "payroll_headcount_schedule"


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
  return apply_payroll_headcount_payload_to_model_input(
    payload,
    schedule,
    live_count=live_count,
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
  rows_by_key: Dict[Tuple[int, str], Dict[str, Any]] = {}
  for item in raw_rows:
    if not isinstance(item, dict):
      continue
    quarter_index = int(round(float(_safe_float(item.get("q") or item.get("quarter_index")) or 0.0)))
    horizon = _contract_horizon_quarters()
    if quarter_index < 1 or quarter_index > horizon:
      continue
    starting_fte = round(max(0.0, float(_safe_float(item.get("starting_fte")) or 0.0)), 2)
    hires = round(max(0.0, float(_safe_float(item.get("hires")) or 0.0)), 2)
    ending_fte = round(max(0.0, float(_safe_float(item.get("ending_fte")) or 0.0)), 2)
    annual_wage = _round_currency(item.get("avg_annual_wage") or item.get("annual_wage"))
    benefits_raw = item.get("payroll_tax_benefits_pct")
    if benefits_raw is None:
      benefits_raw = item.get("payroll_taxes_benefits_percent")
    payroll_tax_benefits_pct = round(max(0.0, float(_safe_ratio(benefits_raw) or 0.0)), 2)
    role_category = str(item.get("role_category") or "aggregate_staff").strip() or "aggregate_staff"
    wage_source = str(item.get("wage_source") or "gpt_business_role_wage").strip() or "gpt_business_role_wage"
    role_key = role_category.lower()
    if (quarter_index, role_key) in rows_by_key:
      continue
    rows_by_key[(quarter_index, role_key)] = {
      "quarter_index": quarter_index,
      "role_category": role_category,
      "starting_fte": starting_fte,
      "hires": hires,
      "ending_fte": ending_fte,
      "annual_wage": annual_wage,
      "wage_source": wage_source,
      "payroll_taxes_benefits_percent": payroll_tax_benefits_pct,
    }
  return [
    rows_by_key[key]
    for key in sorted(rows_by_key.keys(), key=lambda item: (item[0], item[1]))
  ]


def _openai_key() -> Optional[str]:
  key = (os.getenv("OPENAI_API_KEY") or "").strip()
  return key or None


def _openai_model() -> str:
  return (os.getenv("OPENAI_MODEL") or "gpt-5.1").strip() or "gpt-5.1"


def _post_openai(*, url: str, headers: Dict[str, str], payload: Dict[str, Any]):
  return requests.post(url, headers=headers, json=payload, timeout=(10, 120))


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
  for group_name in ("people", "inferred_roles"):
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
          "role_title": role_title,
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
    "known_staffing_roles": rows[:32],
  }


def _role_key(value: Any) -> str:
  return str(value or "").strip().lower()


def _quarter_role_counts(rows: Sequence[Dict[str, Any]]) -> Dict[int, int]:
  counts: Dict[int, int] = {}
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    counts[quarter_index] = int(counts.get(quarter_index) or 0) + 1
  return counts


def _validate_payroll_role_rows(
  rows: Sequence[Dict[str, Any]],
  *,
  policy: Dict[str, Any],
) -> None:
  horizon = _contract_horizon_quarters()
  quarters = {int(row.get("quarter_index") or 0) for row in rows}
  if quarters != set(range(1, horizon + 1)):
    missing = sorted(set(range(1, horizon + 1)) - quarters)
    extra = sorted(quarter for quarter in quarters if quarter < 1 or quarter > horizon)
    _payroll_fail_fast(
      "payroll_headcount_contract_missing_full_horizon",
      f"payroll_headcount_grid must include at least one role row for every Q1-Q{horizon}; missing={missing} extra={extra}.",
      stage="payroll_headcount_role_row_validation",
      details={"missing": missing, "extra": extra, "horizon": horizon},
    )
  max_role_rows = int(policy.get("max_role_rows_per_quarter") or 8)
  for quarter_index, count in _quarter_role_counts(rows).items():
    if count > max_role_rows:
      _payroll_fail_fast(
        "payroll_headcount_contract_too_many_role_rows",
        f"Q{quarter_index} has {count} rows; max={max_role_rows} from post_intake_headcount_policy_lookup.",
        stage="payroll_headcount_role_row_validation",
        details={"quarter_index": quarter_index, "row_count": count, "max_role_rows": max_role_rows},
      )
  min_benefits = round(float(policy.get("min_payroll_tax_benefits_pct") or 0.12), 2)
  max_benefits = round(float(policy.get("max_payroll_tax_benefits_pct") or 0.35), 2)
  min_annual_wage = _round_currency(policy.get("min_annual_wage") or 25000)
  previous_by_role: Dict[str, float] = {}
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    role_category = _role_key(row.get("role_category"))
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    hires = round(float(row.get("hires") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    if quarter_index > 1 and role_category in previous_by_role and abs(starting_fte - previous_by_role[role_category]) > 0.01:
      _payroll_fail_fast(
        "payroll_headcount_contract_continuity_failed",
        f"Q{quarter_index} {role_category} starting_fte must equal prior quarter ending_fte.",
        stage="payroll_headcount_role_row_validation",
      )
    if abs((starting_fte + hires) - ending_fte) > 0.01:
      _payroll_fail_fast(
        "payroll_headcount_contract_math_failed",
        f"Q{quarter_index} {role_category} starting_fte + hires must equal ending_fte.",
        stage="payroll_headcount_role_row_validation",
      )
    benefits_pct = round(float(_safe_ratio(row.get("payroll_taxes_benefits_percent")) or 0.0), 2)
    if benefits_pct < min_benefits or benefits_pct > max_benefits:
      _payroll_fail_fast(
        "payroll_headcount_schedule_benefits_invalid",
        f"Q{quarter_index} {role_category} payroll_taxes_benefits_percent must be {min_benefits:.2f}-{max_benefits:.2f} per post_intake_headcount_policy_lookup.",
        stage="payroll_headcount_role_row_validation",
      )
    annual_wage = _round_currency(row.get("annual_wage"))
    if annual_wage < min_annual_wage:
      _payroll_fail_fast(
        "payroll_headcount_schedule_wage_below_policy_floor",
        f"Q{quarter_index} {role_category} annual_wage={annual_wage}; min={min_annual_wage} from post_intake_headcount_policy_lookup.",
        stage="payroll_headcount_role_row_validation",
      )
    previous_by_role[role_category] = ending_fte


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


def _revenue_per_employee_from_policy(
  policy: Dict[str, Any],
  *,
  financials_json: Optional[Dict[str, Any]] = None,
) -> Tuple[float, str]:
  del financials_json
  return (
    round(float(policy.get("default_revenue_per_employee") or 650000.0), 6),
    "post_intake_headcount_policy_lookup.default_revenue_per_employee",
  )


def _payroll_economic_guardrails(
  *,
  model_input_json: Optional[Dict[str, Any]],
  policy: Dict[str, Any],
  financials_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  horizon = _contract_horizon_quarters()
  revenue_by_quarter = _revenue_by_quarter_from_model_input(model_input_json)
  revenue_per_employee, revenue_per_employee_source = _revenue_per_employee_from_policy(
    policy,
    financials_json=financials_json,
  )
  min_fte_coverage_ratio = round(float(policy.get("min_fte_coverage_ratio") or 0.85), 4)
  quarter_rows: List[Dict[str, Any]] = []
  for quarter_index in range(1, horizon + 1):
    quarter_revenue = int(round(float(revenue_by_quarter.get(quarter_index) or 0.0)))
    implied_full_support_fte = (
      round(float((max(0, quarter_revenue) * 4.0) / max(revenue_per_employee, 1.0)), 2)
      if quarter_revenue > 0
      else 0.0
    )
    minimum_average_fte = round(implied_full_support_fte * min_fte_coverage_ratio, 2)
    quarter_rows.append(
      {
        "quarter_index": quarter_index,
        "revenue": quarter_revenue,
        "revenue_per_employee": round(float(revenue_per_employee), 2),
        "implied_full_support_fte": implied_full_support_fte,
        "minimum_average_fte": minimum_average_fte,
      }
    )
  return {
    "source_table": "post_intake_headcount_policy_lookup",
    "headcount_economic_basis": str(policy.get("headcount_economic_basis") or "revenue_per_employee"),
    "revenue_per_employee": round(float(revenue_per_employee), 2),
    "revenue_per_employee_source": revenue_per_employee_source,
    "min_fte_coverage_ratio": min_fte_coverage_ratio,
    "rule": "average_fte_by_quarter must be >= minimum_average_fte for every Q1-Q20",
    "quarter_rows": quarter_rows,
  }


def _validate_payroll_economic_guardrails(
  rows: Sequence[Dict[str, Any]],
  *,
  model_input_json: Optional[Dict[str, Any]],
  policy: Dict[str, Any],
  financials_json: Optional[Dict[str, Any]] = None,
  stage: str,
) -> None:
  guardrails = _payroll_economic_guardrails(
    model_input_json=model_input_json,
    policy=policy,
    financials_json=financials_json,
  )
  average_fte_by_quarter = _average_fte_by_quarter_from_rows(rows)
  violations: List[Dict[str, Any]] = []
  for item in guardrails.get("quarter_rows") or []:
    if not isinstance(item, dict):
      continue
    quarter_index = int(item.get("quarter_index") or 0)
    required_average_fte = round(float(item.get("minimum_average_fte") or 0.0), 2)
    actual_average_fte = round(float(average_fte_by_quarter.get(quarter_index) or 0.0), 2)
    if required_average_fte > 0.0 and actual_average_fte + 0.01 < required_average_fte:
      violations.append(
        {
          "quarter_index": quarter_index,
          "actual_average_fte": actual_average_fte,
          "required_average_fte": required_average_fte,
          "guardrail": item,
        }
      )
  if violations:
    first = violations[0]
    _payroll_fail_fast(
      "payroll_headcount_economic_coverage_failed",
      (
        f"Q{first.get('quarter_index')} average_fte={first.get('actual_average_fte')} is below "
        f"required_average_fte={first.get('required_average_fte')} from post_intake_headcount_policy_lookup "
        f"revenue_per_employee guardrail; total_violating_quarters={len(violations)}."
      ),
      stage=stage,
      details={
        "violating_quarters": violations,
        "required_action": (
          "Return a corrected full Q1-Q20 payroll_headcount_grid. For every violating quarter, increase "
          "starting_fte/hires/ending_fte so average_fte=(starting_fte+ending_fte)/2 is at least required_average_fte. "
          "Maintain per-role continuity across quarters."
        ),
        "guardrail_source": {
          "table": "post_intake_headcount_policy_lookup",
          "revenue_per_employee": guardrails.get("revenue_per_employee"),
          "revenue_per_employee_source": guardrails.get("revenue_per_employee_source"),
          "min_fte_coverage_ratio": guardrails.get("min_fte_coverage_ratio"),
        },
      },
    )


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
  rows = _payroll_headcount_grid_rows(candidate)
  _validate_payroll_role_rows(rows, policy=policy)
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
  rows = _payroll_headcount_grid_rows(payroll_headcount_contract)
  _validate_payroll_role_rows(rows, policy=policy)
  _validate_payroll_economic_guardrails(
    rows,
    model_input_json=model_input_json,
    policy=policy,
    stage="payroll_headcount_payload_build",
  )
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
  )


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
) -> Dict[str, Any]:
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
  finmo_rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
  ]
  payroll_economic_guardrails = _payroll_economic_guardrails(
    model_input_json=model_input_json,
    policy=policy or {},
    financials_json=financials,
  )
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
    "people_staffing_context": _people_staffing_context(people_json),
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
    "stage_ramp_contract": {
      key: deepcopy(value)
      for key, value in (stage_ramp_contract or {}).items()
      if key not in {"prompt_context", "raw_openai_response"}
    },
    "payroll_headcount_policy": {
      key: deepcopy(value)
      for key, value in (policy or {}).items()
      if key in {
        "policy_code",
        "schedule_storage_table",
        "schedule_storage_column",
        "schedule_contract_version",
        "schedule_horizon_quarters",
        "model_input_driver",
        "financial_model_field",
        "headcount_source_priority",
        "wage_source_priority",
        "generic_oews_fallback_allowed",
        "role_category_required",
        "fte_math_required",
        "min_payroll_tax_benefits_pct",
        "max_payroll_tax_benefits_pct",
        "min_annual_wage",
        "max_role_rows_per_quarter",
        "headcount_economic_basis",
        "default_revenue_per_employee",
        "min_fte_coverage_ratio",
        "salary_basis",
        "default_avg_annual_wage",
        "min_wage_benchmark_ratio",
        "currency_rounding",
        "ratio_rounding",
      }
    },
    "payroll_economic_guardrails": payroll_economic_guardrails,
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
        "schema": post_intake_gpt_contract_openai_schema(contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME),
        "strict": True,
      }
    },
  }
  raw_openai_response: Dict[str, Any] = {}
  last_contract_error = ""
  last_parsed: Dict[str, Any] = {}
  start = time.perf_counter()
  for attempt_index in range(3):
    request_context = deepcopy(user_context)
    if last_contract_error:
      request_context["previous_contract_failure"] = {
        "source_of_truth": "post_intake_headcount_policy_lookup + payroll_headcount_schedule validator",
        "required_action": (
          "Return a corrected full payroll_headcount_schedule. Do not change stage_ramp_contract. "
          "Increase staffing rows so every quarter average FTE satisfies payroll_economic_guardrails.minimum_average_fte. "
          "Review every violating_quarters item in the failure details; fixing only the first failing quarter is invalid."
        ),
        "error": last_contract_error[:6000],
        "invalid_response_excerpt": json.dumps(last_parsed, ensure_ascii=False)[:6000],
      }
    system_prompt = post_intake_build_prompt_from_contract(
      PAYROLL_HEADCOUNT_CONTRACT_NAME,
      context_payload=request_context,
      include_phase="pre_convergence",
      static_instruction=(
        "Decide the payroll headcount schedule using business judgment inside the SQL-defined "
        "payroll_headcount_schedule contract. Python will calculate payroll dollars from this schedule "
        "and validate it against payroll_economic_guardrails from post_intake_headcount_policy_lookup."
      ),
      task_instruction=(
        "Return only JSON matching payroll_headcount_schedule. Use the stage_ramp_contract as context, "
        "but do not change ramp. Output staffing/FTE/wage assumptions only; Python calculates and persists payroll. "
        "Every quarter's average FTE must satisfy payroll_economic_guardrails.minimum_average_fte. "
        "If a prior failure is provided, fix that exact table-backed validation failure."
      ),
    )
    payload = deepcopy(payload_base)
    payload["input"] = [
      {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(request_context, ensure_ascii=False)}]},
    ]
    resp = _post_openai(
      url="https://api.openai.com/v1/responses",
      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
      payload=payload,
    )
    elapsed = time.perf_counter() - start
    if elapsed > 120:
      _payroll_fail_fast(
        "payroll_headcount_contract_timeout",
        f"GPT headcount schedule exceeded 120s before convergence; elapsed={elapsed:.2f}s.",
        stage="payroll_headcount_contract_request",
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
      last_contract_error = "payroll_headcount_contract_parse_failed: GPT did not return a JSON object."
      if attempt_index < 2:
        continue
      _payroll_fail_fast(
        "payroll_headcount_contract_parse_failed",
        "GPT did not return a JSON object.",
        stage="payroll_headcount_contract_response",
      )
      parsed = {}
    last_parsed = deepcopy(parsed)
    try:
      contract = validate_payroll_headcount_contract_payload(parsed)
      contract["prompt_context"] = request_context
      contract["raw_openai_response"] = raw_openai_response
      return build_payroll_headcount_payload_from_contract(
        contract,
        draft_id=draft_id,
        client_id=client_id,
        model_input_json=model_input_json,
      )
    except RuntimeError as exc:
      last_contract_error = str(exc)
      if attempt_index < 2:
        continue
      _payroll_fail_fast(
        "payroll_headcount_contract_invalid_fail_fast",
        f"{last_contract_error}; raw_payroll_headcount_response={json.dumps(parsed, ensure_ascii=False)[:8000]}",
        stage="payroll_headcount_contract_response",
        details={"raw_payroll_headcount_response": parsed},
      )
  _payroll_fail_fast(
    "payroll_headcount_contract_invalid_fail_fast",
    last_contract_error or "Payroll headcount contract did not produce a valid schedule.",
    stage="payroll_headcount_contract_response",
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


def _revenue_by_quarter_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> Dict[int, int]:
  context = _revenue_driver_context_from_model_input(model_input_json)
  return {
    int(row.get("quarter_index") or 0): int(row.get("computed_revenue_from_model_input") or 0)
    for row in (context.get("quarter_rows") or [])
    if isinstance(row, dict)
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


def _validate_quarter_totals_match_role_rows(
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
        f"Q{quarter_index} quarter_totals.payroll={provided} calculated_from_role_rows={expected}. "
        "Payroll schedule quarter_totals must be a deterministic rollup of rows.",
        stage="payroll_headcount_quarter_total_rollup",
        details={"quarter_index": quarter_index, "provided": provided, "expected": expected},
      )


def apply_payroll_headcount_payload_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> Dict[str, Any]:
  next_payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule:
    _payroll_fail_fast(
      "payroll_headcount_schedule_missing_at_application",
      "apply_payroll_headcount_payload_to_model_input requires the table-backed payroll_headcount payload.",
      stage="payroll_headcount_model_input_application",
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
  _validate_quarter_totals_match_role_rows(schedule, rows=schedule_rows)
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
  _validate_payroll_role_rows(rows, policy=policy)
  if isinstance(model_input_json, dict):
    _validate_payroll_economic_guardrails(
      rows,
      model_input_json=model_input_json,
      policy=policy,
      stage=stage,
    )
  _validate_quarter_totals_match_role_rows(schedule, rows=rows)


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
      try:
        rows = _payroll_headcount_grid_rows(schedule)
        _validate_payroll_economic_guardrails(
          rows,
          model_input_json=payload,
          policy=post_intake_headcount_policy_for("default"),
          stage="payroll_headcount_model_input_validation",
        )
      except RuntimeError as exc:
        details.append({
          "error": "payroll_headcount_economic_coverage_failed",
          "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
          "quarter": 0,
          "reason": str(exc),
          "validation_category": "payroll_headcount_schedule",
        })
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
    expected_payload = apply_payroll_headcount_payload_to_model_input(deepcopy(payload), schedule, live_count=live_count)
    expected_row = payroll_row_from_model_input(expected_payload)
    current_values = list(current_row.get("values") or [])
    expected_values = list((expected_row or {}).get("values") or [])
    if len(current_values) >= live_count + 1 and len(expected_values) >= live_count + 1:
      for quarter_index in range(1, live_count + 1):
        current_value = _safe_float(current_values[quarter_index])
        expected_value = _safe_float(expected_values[quarter_index])
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
