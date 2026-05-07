"""Schedule-Parameter Tweak Interface — Phase 2 module 5.

Per-schedule helpers the solver can call when a schedule-locked driver
needs to move. Schedules (payroll headcount, debt amortization, capex /
depreciation) own their internal logic — the solver does NOT write into
their output rows directly. Instead, the solver picks a schedule
parameter to perturb and asks the schedule to recompute. The new driver
value flows through naturally.

Each helper returns a payload the solver can record in its trace:
  {
    "schedule": <str>,
    "parameter_changed": <str>,
    "old_value": ..., "new_value": ...,
    "schedule_recomputed": <bool>,
    "driver_values_after": [...],
  }

This module deliberately stays thin — it only routes the solver's
"please move driver X" intent to the right schedule parameter perturbation,
and re-runs the schedule. The schedule's own internal logic is unchanged.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def request_payroll_schedule_recompute(
  *,
  model_input_json: Optional[Dict[str, Any]],
  target_payroll_percent_of_revenue: Optional[float] = None,
  labor_intensity_class: Optional[str] = None,
  capacity_units_per_supporting_fte: Optional[float] = None,
) -> Dict[str, Any]:
  """Request the payroll/headcount schedule to recompute under modified params.

  Perturbable parameters (any subset may be supplied):
    - target_payroll_percent_of_revenue: shifts payroll envelope vs revenue
    - labor_intensity_class: adjusts headcount ramp slope
    - capacity_units_per_supporting_fte: shifts revenue/FTE productivity

  This is the indirect-tweak path the solver uses when it wants to move
  the schedule-locked Payroll lever. The schedule rebuild logic itself is
  imported lazily and unchanged from its current contract.
  """
  changes: Dict[str, Dict[str, Any]] = {}
  if target_payroll_percent_of_revenue is not None:
    changes["target_payroll_percent_of_revenue"] = {
      "new_value": float(target_payroll_percent_of_revenue),
    }
  if labor_intensity_class is not None:
    changes["labor_intensity_class"] = {"new_value": _clean_text(labor_intensity_class)}
  if capacity_units_per_supporting_fte is not None:
    changes["capacity_units_per_supporting_fte"] = {
      "new_value": float(capacity_units_per_supporting_fte),
    }

  if not changes:
    return {
      "schedule": "payroll_headcount",
      "schedule_recomputed": False,
      "reason": "no_parameter_change_requested",
      "changes": {},
    }

  try:
    from client_intake_and_finmo.post_intake_headcount import (  # type: ignore
      apply_payroll_headcount_policy_to_model_input,
    )
  except Exception as exc:
    return {
      "schedule": "payroll_headcount",
      "schedule_recomputed": False,
      "reason": "import_failed",
      "detail": str(exc),
      "changes": changes,
    }

  next_input = copy.deepcopy(model_input_json or {})
  payroll_policy = next_input.setdefault("derived_driver_policies", {}).setdefault(
    "payroll_headcount_policy", {}
  )
  for field, change in changes.items():
    change["old_value"] = payroll_policy.get(field)
    payroll_policy[field] = change["new_value"]

  try:
    next_input = apply_payroll_headcount_policy_to_model_input(next_input)
    recomputed = True
    error_detail: Optional[str] = None
  except Exception as exc:
    recomputed = False
    error_detail = str(exc)

  return {
    "schedule": "payroll_headcount",
    "schedule_recomputed": bool(recomputed),
    "changes": changes,
    "error_detail": error_detail,
    "model_input_json": next_input if recomputed else None,
  }


def request_debt_schedule_recompute(
  *,
  model_input_json: Optional[Dict[str, Any]],
  selected_cash_strategy: Optional[str] = None,
  debt_issuance_overrides: Optional[Dict[int, float]] = None,
  debt_repayment_overrides: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
  """Request the debt schedule to recompute under modified parameters.

  Perturbable parameters:
    - selected_cash_strategy: shareholder_return / balanced / preserve_cash
      (changes which cash-policy row gates issuance/repayment timing)
    - debt_issuance_overrides: {quarter_index: amount} explicit overrides
    - debt_repayment_overrides: {quarter_index: amount} explicit overrides

  This is the indirect-tweak path for schedule-locked Debt Issuance and
  Debt Repayment levers.
  """
  changes: Dict[str, Any] = {}
  if selected_cash_strategy is not None:
    changes["selected_cash_strategy"] = {"new_value": _clean_text(selected_cash_strategy)}
  if debt_issuance_overrides:
    changes["debt_issuance_overrides"] = {
      "new_value": {int(k): float(v) for k, v in debt_issuance_overrides.items()},
    }
  if debt_repayment_overrides:
    changes["debt_repayment_overrides"] = {
      "new_value": {int(k): float(v) for k, v in debt_repayment_overrides.items()},
    }
  if not changes:
    return {
      "schedule": "debt_schedule",
      "schedule_recomputed": False,
      "reason": "no_parameter_change_requested",
      "changes": {},
    }

  next_input = copy.deepcopy(model_input_json or {})
  policies = next_input.setdefault("derived_driver_policies", {})
  debt_policy = policies.setdefault("debt_schedule_policy", {})
  for field, change in changes.items():
    change["old_value"] = debt_policy.get(field)
    debt_policy[field] = change["new_value"]

  # The actual schedule rebuild is owned by post_intake_debt_schedule and
  # runs as part of the cash-pass pipeline. The solver records the
  # parameter change here; the next cash-pass invocation will pick it up.
  return {
    "schedule": "debt_schedule",
    "schedule_recomputed": False,
    "reason": "policy_recorded_recompute_deferred_to_cash_pass",
    "changes": changes,
    "model_input_json": next_input,
  }


def request_capex_schedule_recompute(
  *,
  model_input_json: Optional[Dict[str, Any]],
  maintenance_capex_percent_of_revenue: Optional[float] = None,
  explicit_capex_overrides: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
  """Request the capex/depreciation schedule to recompute under modified params.

  Perturbable parameters:
    - maintenance_capex_percent_of_revenue: baseline capex as a fraction of
      forecast revenue
    - explicit_capex_overrides: {quarter_index: amount} explicit overrides
      (these override the maintenance-percent baseline for the named
      quarters and feed straight into depreciation via the schedule).
  """
  changes: Dict[str, Any] = {}
  if maintenance_capex_percent_of_revenue is not None:
    changes["maintenance_capex_percent_of_revenue"] = {
      "new_value": float(maintenance_capex_percent_of_revenue),
    }
  if explicit_capex_overrides:
    changes["explicit_capex_overrides"] = {
      "new_value": {int(k): float(v) for k, v in explicit_capex_overrides.items()},
    }
  if not changes:
    return {
      "schedule": "capex_depreciation",
      "schedule_recomputed": False,
      "reason": "no_parameter_change_requested",
      "changes": {},
    }

  next_input = copy.deepcopy(model_input_json or {})
  policies = next_input.setdefault("derived_driver_policies", {})
  capex_policy = policies.setdefault("capex_depreciation_policy", {})
  for field, change in changes.items():
    change["old_value"] = capex_policy.get(field)
    capex_policy[field] = change["new_value"]

  return {
    "schedule": "capex_depreciation",
    "schedule_recomputed": False,
    "reason": "policy_recorded_recompute_deferred_to_finmo_build",
    "changes": changes,
    "model_input_json": next_input,
  }
