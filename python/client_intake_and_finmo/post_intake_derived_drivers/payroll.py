from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
  PAYROLL_HEADCOUNT_LEVER_ID,
  PAYROLL_HEADCOUNT_POLICY_VERSION,
  PAYROLL_HEADCOUNT_SOURCE,
  apply_payroll_headcount_payload_to_model_input,
  post_intake_headcount_policy_for,
  validate_payroll_headcount_model_input_contract,
)


__all__ = [
  "PAYROLL_HEADCOUNT_POLICY_VERSION",
  "PAYROLL_HEADCOUNT_SOURCE",
  "PAYROLL_HEADCOUNT_LEVER_ID",
  "default_payroll_headcount_policy",
  "normalized_payroll_headcount_policy",
  "apply_payroll_headcount_policy_to_model_input",
  "validate_payroll_headcount_contract",
]


def _live_count_from_model_input(model_input_json: Optional[Dict[str, Any]]) -> int:
  payload = model_input_json if isinstance(model_input_json, dict) else {}
  periods = payload.get("periods") if isinstance(payload.get("periods"), list) else []
  live_count = len([item for item in periods if isinstance(item, dict) and not bool(item.get("is_stub"))])
  return live_count or 20


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
