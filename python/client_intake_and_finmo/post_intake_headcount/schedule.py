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
  post_intake_gpt_contract_compact_prompt_field_spec,
  post_intake_gpt_contract_horizon_errors,
  post_intake_gpt_contract_normalize_payload,
  post_intake_gpt_contract_openai_schema,
  post_intake_gpt_contract_payload_errors,
  post_intake_gpt_context_filter_payload,
  post_intake_gpt_context_request_char_budget,
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


def _contract_horizon_quarters() -> int:
  count = int(
    post_intake_contract_forecast_horizon_quarter_count(
      contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    )
    or 0
  )
  if count <= 0:
    raise RuntimeError(
      "payroll_headcount_contract_horizon_missing: "
      "post_intake_gpt_contract_lookup must define a positive payroll horizon."
    )
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
) -> Dict[str, Any]:
  payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  schedule = _schedule_from_model_input(payload)
  if not schedule:
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


def _payroll_headcount_grid_rows(payroll_headcount_contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  payload = payroll_headcount_contract if isinstance(payroll_headcount_contract, dict) else {}
  raw_rows = payload.get("payroll_headcount_grid")
  if not isinstance(raw_rows, list):
    raw_rows = []
  rows_by_quarter: Dict[int, Dict[str, Any]] = {}
  for item in raw_rows:
    if not isinstance(item, dict):
      continue
    quarter_index = int(round(float(_safe_float(item.get("q") or item.get("quarter_index")) or 0.0)))
    horizon = _contract_horizon_quarters()
    if quarter_index < 1 or quarter_index > horizon or quarter_index in rows_by_quarter:
      continue
    starting_fte = round(max(0.0, float(_safe_float(item.get("starting_fte")) or 0.0)), 2)
    hires = round(max(0.0, float(_safe_float(item.get("hires")) or 0.0)), 2)
    ending_fte = round(max(0.0, float(_safe_float(item.get("ending_fte")) or 0.0)), 2)
    annual_wage = _round_currency(item.get("avg_annual_wage") or item.get("annual_wage"))
    payroll_tax_benefits_pct = round(max(0.0, float(_safe_ratio(item.get("payroll_tax_benefits_pct")) or 0.0)), 2)
    role_category = str(item.get("role_category") or "aggregate_staff").strip() or "aggregate_staff"
    wage_source = str(item.get("wage_source") or "gpt_business_role_wage").strip() or "gpt_business_role_wage"
    rows_by_quarter[quarter_index] = {
      "quarter_index": quarter_index,
      "role_category": role_category,
      "starting_fte": starting_fte,
      "hires": hires,
      "ending_fte": ending_fte,
      "annual_wage": annual_wage,
      "wage_source": wage_source,
      "payroll_taxes_benefits_percent": payroll_tax_benefits_pct,
    }
  return [rows_by_quarter[quarter] for quarter in sorted(rows_by_quarter)]


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
    raise RuntimeError(
      "payroll_headcount_contract_table_validation_failed: "
      + "; ".join(str(item) for item in contract_errors[:20])
    )
  horizon_errors = post_intake_gpt_contract_horizon_errors(
    contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME,
    payload=candidate,
  )
  if horizon_errors:
    raise RuntimeError(
      "payroll_headcount_contract_horizon_violation: "
      + "; ".join(str(item) for item in horizon_errors[:20])
    )
  rows = _payroll_headcount_grid_rows(candidate)
  horizon = _contract_horizon_quarters()
  if len(rows) != horizon or {int(row.get("quarter_index") or 0) for row in rows} != set(range(1, horizon + 1)):
    raise RuntimeError(
      f"payroll_headcount_contract_missing_full_horizon: payroll_headcount_grid must include Q1-Q{horizon}."
    )
  previous_ending_fte: Optional[float] = None
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    hires = round(float(row.get("hires") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    if previous_ending_fte is not None and abs(starting_fte - previous_ending_fte) > 0.01:
      raise RuntimeError(f"payroll_headcount_contract_continuity_failed: Q{quarter_index} starting_fte must equal prior quarter ending_fte.")
    if abs((starting_fte + hires) - ending_fte) > 0.01:
      raise RuntimeError(f"payroll_headcount_contract_math_failed: Q{quarter_index} starting_fte + hires must equal ending_fte.")
    previous_ending_fte = ending_fte
  rationale = str(candidate.get("rationale") or "").strip()
  if not rationale:
    raise RuntimeError("payroll_headcount_contract_rationale_missing")
  return {
    "contract_version": "payroll_headcount_schedule_gpt_v1",
    "decision_source": "gpt_pre_convergence",
    "payroll_headcount_grid": rows,
    "rationale": rationale,
  }


def build_payroll_headcount_payload_from_contract(
  payroll_headcount_contract: Optional[Dict[str, Any]],
  *,
  draft_id: Any = "",
  client_id: Any = "",
  policy_code: Any = "default",
) -> Dict[str, Any]:
  policy = post_intake_headcount_policy_for(policy_code=policy_code)
  horizon = int((policy or {}).get("schedule_horizon_quarters") or 0)
  contract_horizon = _contract_horizon_quarters()
  if horizon != contract_horizon:
    raise RuntimeError(
      f"payroll_headcount_policy_invalid: schedule_horizon_quarters must be {contract_horizon}"
    )
  rows = _payroll_headcount_grid_rows(payroll_headcount_contract)
  if len(rows) != horizon or {int(row.get("quarter_index") or 0) for row in rows} != set(range(1, horizon + 1)):
    raise RuntimeError(
      "payroll_headcount_schedule_missing_full_horizon: payroll_headcount_schedule.payroll_headcount_grid must include Q1-Q20."
    )
  normalized_rows: List[Dict[str, Any]] = []
  quarter_totals: List[Dict[str, Any]] = []
  previous_ending_fte: Optional[float] = None
  for row in rows:
    quarter_index = int(row.get("quarter_index") or 0)
    starting_fte = round(float(row.get("starting_fte") or 0.0), 2)
    hires = round(float(row.get("hires") or 0.0), 2)
    ending_fte = round(float(row.get("ending_fte") or 0.0), 2)
    if previous_ending_fte is not None and abs(starting_fte - previous_ending_fte) > 0.01:
      raise RuntimeError(
        f"payroll_headcount_schedule_continuity_failed: Q{quarter_index} starting_fte must equal prior quarter ending_fte."
      )
    if abs((starting_fte + hires) - ending_fte) > 0.01:
      raise RuntimeError(
        f"payroll_headcount_schedule_math_failed: Q{quarter_index} starting_fte + hires must equal ending_fte."
      )
    annual_wage = _round_currency(row.get("annual_wage"))
    if annual_wage <= 0:
      raise RuntimeError(f"payroll_headcount_schedule_wage_invalid: Q{quarter_index} annual_wage must be > 0.")
    benefits_pct = round(float(_safe_ratio(row.get("payroll_taxes_benefits_percent")) or 0.0), 2)
    if benefits_pct < 0.0 or benefits_pct > 1.0:
      raise RuntimeError(
        f"payroll_headcount_schedule_benefits_invalid: Q{quarter_index} payroll_taxes_benefits_percent must be 0.00-1.00."
      )
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
    quarter_totals.append(
      {
        "quarter_index": quarter_index,
        "ending_fte": ending_fte,
        "payroll": total_quarterly_payroll,
      }
    )
    previous_ending_fte = ending_fte
  payload = {
    "contract_version": str((policy or {}).get("schedule_contract_version") or "payroll_headcount_schedule_v1"),
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
    raise RuntimeError("payroll_headcount_schedule_validation_failed: " + "; ".join(validation_errors[:20]))
  return payload


def estimate_payroll_headcount_schedule_with_gpt(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  planning_mode: str,
  planning_mode_reason: str,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  api_key = _openai_key()
  if not api_key:
    raise RuntimeError("payroll_headcount_contract_openai_key_missing: OPENAI_API_KEY is not configured.")
  facts = business_facts if isinstance(business_facts, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  policy = post_intake_headcount_policy_for("default")
  compact_contract_spec = post_intake_gpt_contract_compact_prompt_field_spec(PAYROLL_HEADCOUNT_CONTRACT_NAME)
  finmo_rows = [
    row for row in ((finmo_json or {}).get("quarter_rows") or []) if isinstance(row, dict)
  ]
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
      if key in {
        "contract_version",
        "stage_family",
        "quarter_ramp_grid",
        "fte_qoq_default",
        "fte_qoq_max",
        "fte_qoq_max_spike",
        "fte_spike_small_base_threshold",
        "utilization_high_watermark",
      }
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
        "currency_rounding",
        "ratio_rounding",
      }
    },
    "current_model_snapshot": {
      "finmo_revenue_first_4_quarters": [
        {
          "quarter_index": int(_safe_float(row.get("quarter_index")) or 0),
          "revenue": int(round(float(_safe_float(row.get("revenue")) or 0.0))),
          "payroll": int(round(float(_safe_float(row.get("payroll")) or 0.0))),
        }
        for row in finmo_rows[:4]
      ],
    },
    "contract_field_spec": compact_contract_spec,
    "required_response_shape": compact_contract_spec.get("required_response_shape"),
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
      raise RuntimeError(
        f"payroll_headcount_gpt_context_payload_budget_exceeded: chars={context_chars} budget={int(context_budget)}"
      )
  system_prompt = post_intake_build_prompt_from_contract(
    PAYROLL_HEADCOUNT_CONTRACT_NAME,
    context_payload=user_context,
    include_phase="pre_convergence",
    static_instruction=(
      "Decide the payroll headcount schedule using business judgment, but only inside the "
      "SQL-defined payroll headcount contract. Python will calculate payroll from the returned "
      "headcount schedule and table-backed policy."
    ),
    task_instruction=(
      "Return only JSON matching the payroll_headcount_schedule contract. Do not add fields, "
      "omit required fields, or invent staffing structure outside the contract."
    ),
  )
  payload = {
    "model": _openai_model(),
    "temperature": 0,
    "input": [
      {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
      {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_context, ensure_ascii=False)}]},
    ],
    "text": {
      "format": {
        "type": "json_schema",
        "name": PAYROLL_HEADCOUNT_CONTRACT_NAME,
        "schema": post_intake_gpt_contract_openai_schema(contract_name=PAYROLL_HEADCOUNT_CONTRACT_NAME),
        "strict": True,
      }
    },
  }
  start = time.perf_counter()
  resp = _post_openai(
    url="https://api.openai.com/v1/responses",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    payload=payload,
  )
  elapsed = time.perf_counter() - start
  if elapsed > 120:
    raise RuntimeError(f"payroll_headcount_contract_timeout: GPT headcount schedule exceeded 120s before convergence.")
  if resp.status_code >= 400:
    raise RuntimeError(f"payroll_headcount_contract_openai_status: {resp.text[:1200]}")
  raw_openai_response = resp.json() if isinstance(resp.json(), dict) else {"response": resp.text[:4000]}
  parsed = _parse_responses_json_dict(raw_openai_response)
  if not isinstance(parsed, dict):
    raise RuntimeError("payroll_headcount_contract_parse_failed: GPT did not return a JSON object.")
  try:
    contract = validate_payroll_headcount_contract_payload(parsed)
  except RuntimeError as exc:
    raise RuntimeError(
      "payroll_headcount_contract_invalid_fail_fast: "
      f"{exc}; raw_payroll_headcount_response={json.dumps(parsed, ensure_ascii=False)[:3000]}"
    ) from exc
  contract["prompt_context"] = user_context
  contract["raw_openai_response"] = raw_openai_response
  return contract


def apply_payroll_headcount_payload_to_model_input(
  model_input_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  *,
  live_count: int,
) -> Dict[str, Any]:
  next_payload = deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  schedule = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  if not schedule:
    return next_payload
  validation_errors = validate_payroll_headcount_payload(schedule)
  if validation_errors:
    raise RuntimeError("payroll_headcount_schedule_validation_failed: " + "; ".join(validation_errors[:20]))
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
    raise RuntimeError("payroll_row_missing: model_input.sections.expenses must include Payroll for headcount schedule application.")
  values = list(payroll_row.get("values") or [])
  stub_value, _existing_live_values = _row_stub_and_live_values(values, live_count=live_count)
  totals_by_quarter = {
    int(item.get("quarter_index") or 0): int(round(float(_safe_float(item.get("payroll")) or 0.0)))
    for item in (schedule.get("quarter_totals") or [])
    if isinstance(item, dict)
  }
  expected_quarters = set(range(1, live_count + 1))
  if set(totals_by_quarter.keys()) & expected_quarters != expected_quarters:
    raise RuntimeError("payroll_headcount_schedule_missing_live_quarters")
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
  if not schedule:
    details.append({
      "error": "payroll_headcount_schedule_missing",
      "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
      "quarter": 0,
      "reason": "Payroll must be backed by intake_consult_drafts.payroll_headcount / derived_driver_runtime payroll_headcount.",
      "validation_category": "payroll_headcount_schedule",
    })
  else:
    for error in validate_payroll_headcount_payload(schedule):
      details.append({
        "error": error,
        "lever_id": PAYROLL_HEADCOUNT_LEVER_ID,
        "quarter": 0,
        "reason": "Payroll headcount schedule failed schedule validation.",
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
  if schedule:
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
