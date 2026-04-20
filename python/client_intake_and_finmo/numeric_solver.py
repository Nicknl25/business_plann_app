"""Canonical quarter-by-quarter numeric solver for GPT-owned finmo targets.

This module is the only numeric fitting engine that should be invoked by
planner execution paths. It does not decide business validity, issue
resolution, or pass/fail. It only uses GPT-approved model-input levers to
get as close as possible to GPT-defined quarter-level finmo targets.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize  # type: ignore

try:
  from financial_model_engine.model_inputs import QUARTER_COUNT  # type: ignore
except Exception:
  QUARTER_COUNT = 20


TARGET_METRIC_KEYS = (
  "revenue",
  "gross_profit",
  "ebitda",
  "net_income",
  "ending_cash",
  "operating_cash_flow",
  "investing_cash_flow",
  "financing_cash_flow",
  "current_assets",
  "ppe",
  "current_liabilities",
  "noncurrent_liabilities",
  "payroll",
  "marketing",
  "g_and_a",
  "lease_rent",
  "capital_expenditures",
  "long_term_debt",
  "total_liabilities",
  "owners_capital",
  "other_equity",
  "distributions",
)


def _safe_float(value: Any) -> Optional[float]:
  try:
    if value is None or value == "":
      return None
    return float(value)
  except Exception:
    return None


def _load_numeric_apply_helpers() -> Tuple[Any, Any]:
  try:
    from client_intake_and_finmo.quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore
  except Exception:
    from quarter_grid import apply_exact_lever_updates_to_model_input  # type: ignore
  try:
    from client_intake_and_finmo.finmo_bridge import build_python_finmo_json  # type: ignore
  except Exception:
    from finmo_bridge import build_python_finmo_json  # type: ignore
  return apply_exact_lever_updates_to_model_input, build_python_finmo_json


def _iter_controller_write_rows(model_input_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  sections = model_input.get("sections") if isinstance(model_input.get("sections"), dict) else {}
  rows: List[Dict[str, Any]] = []
  for section_name in ("revenue", "expenses", "balance_sheet"):
    for row in (sections.get(section_name) or []):
      lever_id = str((row or {}).get("lever_id") or "").strip()
      if isinstance(row, dict) and bool(row.get("controller_write", True)) and lever_id:
        rows.append(row)
  schedules = sections.get("schedules") if isinstance(sections.get("schedules"), dict) else {}
  for row in (schedules.get("rows") or []):
    lever_id = str((row or {}).get("lever_id") or "").strip()
    if isinstance(row, dict) and bool(row.get("controller_write", True)) and lever_id:
      rows.append(row)
  return rows


def _lever_row_map(model_input_json: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
  return {
    str(item.get("lever_id") or "").strip(): item
    for item in _iter_controller_write_rows(model_input_json)
    if str(item.get("lever_id") or "").strip()
  }


def _row_has_stub(values: List[Any]) -> bool:
  return len(values) >= QUARTER_COUNT + 1


def _row_value(row: Optional[Dict[str, Any]], quarter_index: int) -> float:
  if not isinstance(row, dict):
    return 0.0
  values = list(row.get("values") or [])
  if not values or quarter_index < 1 or quarter_index > QUARTER_COUNT:
    return 0.0
  has_stub = _row_has_stub(values)
  index = quarter_index if has_stub else quarter_index - 1
  if index < 0 or index >= len(values):
    return 0.0
  return float(_safe_float(values[index]) or 0.0)


def _relative_move_limit(
  *,
  baseline_value: float,
  max_relative_change: float,
  value_kind: str,
  input_semantics: str,
  anchor_floor: float = 1.0,
) -> float:
  baseline_abs = abs(float(baseline_value or 0.0))
  max_rel = max(0.0, float(max_relative_change or 0.0))
  value_kind_norm = str(value_kind or "").strip().lower()
  semantics_norm = str(input_semantics or "").strip().lower()
  if value_kind_norm == "ratio":
    max_rel = min(1.0, max_rel)
    anchor = max(baseline_abs, 0.05)
    return min(0.5, anchor * max_rel)
  if value_kind_norm == "day_count":
    max_rel = min(2.0, max_rel)
    anchor = max(baseline_abs, 5.0)
    return max(1.0, anchor * max_rel)
  if "percent_of_revenue" in semantics_norm or "percent_of_long_term_debt" in semantics_norm:
    max_rel = min(1.0, max_rel)
    anchor = max(baseline_abs, 0.05)
    return min(0.5, anchor * max_rel)
  anchor = max(baseline_abs, float(anchor_floor or 1.0), 1.0)
  return anchor * max_rel


def _structural_amount_anchor_floor(meta: Dict[str, Any], aggressiveness: str) -> float:
  if str(aggressiveness or "").strip().lower() != "structural":
    return 1.0
  section = str(meta.get("section") or "").strip().lower()
  descriptor = " ".join(
    [
      str(meta.get("section") or ""),
      str(meta.get("driver") or ""),
      str(meta.get("label_path") or ""),
      str(meta.get("lever_id") or ""),
      str(meta.get("accounting_role") or ""),
      str(meta.get("input_semantics") or ""),
    ]
  ).strip().lower()
  if section in {"balance_sheet", "schedules"}:
    return 250000.0
  if any(
    token in descriptor
    for token in (
      "debt",
      "equity",
      "capital",
      "distribution",
      "cash",
      "receivable",
      "inventory",
      "payable",
      "ppe",
      "capex",
    )
  ):
    return 250000.0
  if section == "expenses" or any(
    token in descriptor
    for token in (
      "payroll",
      "marketing",
      "lease",
      "rent",
      "general",
      "administrative",
      "research",
    )
  ):
    return 100000.0
  if section == "revenue":
    return 50000.0
  return 25000.0


def _default_move_band(
  *,
  baseline_value: float,
  meta: Dict[str, Any],
  aggressiveness: str,
) -> Tuple[float, float]:
  max_rel = 0.15
  aggressiveness_norm = str(aggressiveness or "").strip().lower()
  if aggressiveness_norm == "moderate":
    max_rel = 0.30
  elif aggressiveness_norm == "high":
    max_rel = 1.50
  elif aggressiveness_norm == "structural":
    max_rel = 8.0
  move = _relative_move_limit(
    baseline_value=baseline_value,
    max_relative_change=max_rel,
    value_kind=str(meta.get("value_kind") or "").strip(),
    input_semantics=str(meta.get("input_semantics") or "").strip(),
    anchor_floor=_structural_amount_anchor_floor(meta, aggressiveness_norm),
  )
  low = baseline_value - move
  high = baseline_value + move
  if baseline_value >= 0 and str(meta.get("value_kind") or "").strip().lower() != "ratio":
    low = max(0.0, low)
  return float(min(low, high)), float(max(low, high))


def _tolerance_override_map(action: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
  current_action = action if isinstance(action, dict) else {}
  out: Dict[str, Dict[str, Any]] = {}
  for item in (current_action.get("target_tolerances") or []):
    if not isinstance(item, dict):
      continue
    metric_name = str(item.get("metric_name") or "").strip().lower()
    if not metric_name:
      continue
    out[metric_name] = {
      "relative_tolerance_pct": _safe_float(item.get("relative_tolerance_pct")),
      "absolute_tolerance": _safe_float(item.get("absolute_tolerance")),
      "tolerance_reason": str(item.get("tolerance_reason") or "").strip(),
    }
  return out


def _metric_tolerance(
  metric_name: str,
  target_value: float,
  *,
  tolerance_override: Optional[Dict[str, Any]] = None,
) -> float:
  metric = str(metric_name or "").strip().lower()
  base = 250.0
  if metric in {
    "revenue",
    "gross_profit",
    "ending_cash",
    "current_assets",
    "noncurrent_assets",
    "current_liabilities",
    "noncurrent_liabilities",
    "total_liabilities",
    "total_equity",
    "ppe",
    "long_term_debt",
    "owners_capital",
    "other_equity",
  }:
    base = 1000.0
  elif metric in {
    "operating_cash_flow",
    "investing_cash_flow",
    "financing_cash_flow",
    "capital_expenditures",
    "payroll",
    "marketing",
    "g_and_a",
    "lease_rent",
    "distributions",
  }:
    base = 500.0
  override = tolerance_override if isinstance(tolerance_override, dict) else {}
  relative_tolerance_pct = _safe_float(override.get("relative_tolerance_pct"))
  absolute_tolerance = _safe_float(override.get("absolute_tolerance"))
  candidates = [float(base), abs(float(target_value or 0.0)) * 0.02]
  if absolute_tolerance is not None:
    candidates.append(float(max(0.0, absolute_tolerance)))
  if relative_tolerance_pct is not None:
    candidates.append(float(abs(float(target_value or 0.0)) * max(0.0, relative_tolerance_pct) / 100.0))
  return float(max(candidates))


def _finmo_row_map(finmo_json: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
  out: Dict[int, Dict[str, Any]] = {}
  for row in ((finmo_json or {}).get("quarter_rows") or []):
    if not isinstance(row, dict):
      continue
    quarter_index = int(_safe_float(row.get("quarter_index")) or 0)
    if quarter_index >= 1:
      out[quarter_index] = row
  return out


def _normalize_finmo_metric_value(metric_name: str, row: Dict[str, Any]) -> float:
  metric = str(metric_name or "").strip().lower()
  if metric == "noncurrent_assets":
    return float(_safe_float(row.get("total_assets")) or 0.0) - float(_safe_float(row.get("current_assets")) or 0.0)
  if metric == "noncurrent_liabilities":
    return float(_safe_float(row.get("total_liabilities")) or 0.0) - float(_safe_float(row.get("current_liabilities")) or 0.0)
  return float(_safe_float(row.get(metric)) or 0.0)


def _guidance_map(review_plan: Optional[Dict[str, Any]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
  out: Dict[Tuple[str, int], Dict[str, Any]] = {}
  for action in [item for item in ((review_plan or {}).get("translated_action_packages") or []) if isinstance(item, dict)]:
    for update in [item for item in (action.get("translated_updates") or []) if isinstance(item, dict)]:
      lever_id = str(update.get("lever_id") or "").strip()
      quarter_index = int(_safe_float(update.get("quarter_index")) or 0)
      if lever_id and quarter_index >= 1:
        out[(lever_id, quarter_index)] = {
          "source": "translated_update",
          "direction": "increase" if float(_safe_float(update.get("exact_value")) or 0.0) >= float(_safe_float(update.get("baseline_value")) or 0.0) else "decrease",
          "exact_value": float(_safe_float(update.get("exact_value")) or 0.0),
          "baseline_value": float(_safe_float(update.get("baseline_value")) or 0.0),
        }
    for control in [item for item in (action.get("translated_controls") or []) if isinstance(item, dict)]:
      lever_id = str(control.get("lever_id") or "").strip()
      start_q = int(_safe_float(control.get("timing_start_q")) or 0)
      end_q = int(_safe_float(control.get("timing_end_q")) or start_q)
      if not lever_id or start_q < 1 or end_q < start_q:
        continue
      for quarter_index in range(start_q, end_q + 1):
        payload = {
          "source": "translated_control",
          "direction": str(control.get("direction") or "").strip().lower(),
          "control_mode": str(control.get("control_mode") or "").strip().lower(),
          "exact_value": _safe_float(control.get("exact_value")),
          "min_value": _safe_float(control.get("min_value")),
          "max_value": _safe_float(control.get("max_value")),
          "baseline_value": _safe_float(((control.get("baseline_window") or {}) if isinstance(control.get("baseline_window"), dict) else {}).get("value_end")),
        }
        out[(lever_id, quarter_index)] = payload
  return out


def _normalized_target_metric_names(raw_metric_names: Any) -> List[str]:
  allowed = set(TARGET_METRIC_KEYS)
  out: List[str] = []
  for item in (raw_metric_names or []):
    metric_name = str(item or "").strip().lower()
    if not metric_name or metric_name not in allowed or metric_name in out:
      continue
    out.append(metric_name)
  return out


def _required_target_metric_keys_for_action(
  action: Optional[Dict[str, Any]],
) -> List[str]:
  current_action = action if isinstance(action, dict) else {}
  normalized = _normalized_target_metric_names(
    current_action.get("required_target_metric_keys") or []
  )
  if normalized:
    return normalized
  inferred: List[str] = []
  for target in [item for item in (current_action.get("quarter_target_metrics") or []) if isinstance(item, dict)]:
    for metric_name in TARGET_METRIC_KEYS:
      if _safe_float(target.get(metric_name)) is None or metric_name in inferred:
        continue
      inferred.append(metric_name)
  return inferred


def _quarter_tasks(review_plan: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  merged: Dict[int, Dict[str, Any]] = {}
  for action in [item for item in ((review_plan or {}).get("translated_action_packages") or []) if isinstance(item, dict)]:
    action_id = str(action.get("action_id") or "").strip() or "action"
    required_target_metric_keys = _required_target_metric_keys_for_action(action)
    target_tolerances = _tolerance_override_map(action)
    allowed_levers = [
      str(item).strip()
      for item in (action.get("solver_allowed_lever_ids") or [])
      if str(item).strip()
    ]
    for target in [item for item in (action.get("quarter_target_metrics") or []) if isinstance(item, dict)]:
      quarter_index = int(_safe_float(target.get("quarter_index")) or 0)
      if quarter_index < 1:
        continue
      entry = merged.setdefault(
        quarter_index,
        {
          "quarter_index": quarter_index,
          "target_metrics": {},
          "allowed_lever_ids": [],
          "source_action_ids": [],
          "required_target_metric_keys": [],
          "target_tolerances": {},
        },
      )
      for lever_id in allowed_levers:
        if lever_id not in entry["allowed_lever_ids"]:
          entry["allowed_lever_ids"].append(lever_id)
      if action_id not in entry["source_action_ids"]:
        entry["source_action_ids"].append(action_id)
      for metric_name in required_target_metric_keys:
        if metric_name not in entry["required_target_metric_keys"]:
          entry["required_target_metric_keys"].append(metric_name)
      for metric_name, tolerance_payload in target_tolerances.items():
        entry["target_tolerances"][metric_name] = copy.deepcopy(tolerance_payload)
      for metric_name in TARGET_METRIC_KEYS:
        metric_value = _safe_float(target.get(metric_name))
        if metric_value is not None:
          entry["target_metrics"][metric_name] = float(metric_value)
  normalized: List[Dict[str, Any]] = []
  for quarter_index in sorted(merged.keys()):
    entry = copy.deepcopy(merged[quarter_index])
    required_target_metric_keys = [
      metric_name for metric_name in (entry.get("required_target_metric_keys") or [])
      if metric_name in TARGET_METRIC_KEYS
    ]
    missing_required_metrics = [
      metric_name for metric_name in required_target_metric_keys
      if metric_name not in (entry.get("target_metrics") or {})
    ]
    entry["missing_required_metrics"] = missing_required_metrics
    entry["solver_ready"] = bool(
      (entry.get("allowed_lever_ids") or [])
      and required_target_metric_keys
      and not missing_required_metrics
    )
    normalized.append(entry)
  return normalized


def _build_variable_specs(
  *,
  working_model_input_json: Dict[str, Any],
  quarter_index: int,
  allowed_lever_ids: List[str],
  numeric_solver_contract: Optional[Dict[str, Any]],
  guidance_by_key: Dict[Tuple[str, int], Dict[str, Any]],
) -> List[Dict[str, Any]]:
  row_map = _lever_row_map(working_model_input_json)
  catalog_entries = {
    str(item.get("lever_id") or "").strip(): item
    for item in (((numeric_solver_contract or {}).get("writable_lever_catalog") or {}).get("entries") or [])
    if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
  }
  aggressiveness = str((((numeric_solver_contract or {}).get("solver_settings") or {}).get("aggressiveness")) or "moderate").strip().lower()
  specs: List[Dict[str, Any]] = []
  for lever_id in allowed_lever_ids:
    row = row_map.get(lever_id)
    if not isinstance(row, dict):
      continue
    baseline_value = _row_value(row, quarter_index)
    guidance = guidance_by_key.get((lever_id, quarter_index)) or {}
    meta = catalog_entries.get(lever_id) or {}
    low: Optional[float] = None
    high: Optional[float] = None
    anchor = baseline_value
    direction = str(guidance.get("direction") or "either").strip().lower()
    if str(guidance.get("control_mode") or "").strip().lower() == "band":
      low = _safe_float(guidance.get("min_value"))
      high = _safe_float(guidance.get("max_value"))
      if low is not None and high is not None:
        anchor = float((float(min(low, high)) + float(max(low, high))) / 2.0)
    elif _safe_float(guidance.get("exact_value")) is not None:
      anchor = float(_safe_float(guidance.get("exact_value")) or baseline_value)
      scale = max(abs(anchor - baseline_value), abs(anchor) * 0.10, 1.0)
      expansion = 0.25
      if aggressiveness == "high":
        expansion = 0.50
      elif aggressiveness == "structural":
        expansion = 1.00
      low = min(baseline_value, anchor) - (expansion * scale)
      high = max(baseline_value, anchor) + (expansion * scale)
    if low is None or high is None:
      low, high = _default_move_band(
        baseline_value=baseline_value,
        meta=meta,
        aggressiveness=aggressiveness,
      )
    if direction == "increase":
      low = max(low, min(anchor, baseline_value))
    elif direction == "decrease":
      high = min(high, max(anchor, baseline_value))
    if low > high:
      low, high = high, low
    specs.append(
      {
        "lever_id": lever_id,
        "quarter_index": quarter_index,
        "baseline_value": float(baseline_value),
        "anchor_value": float(anchor),
        "min_value": float(low),
        "max_value": float(high),
      }
    )
  return specs


def _candidate_updates(
  *,
  quarter_index: int,
  variable_specs: List[Dict[str, Any]],
  vector: List[float],
) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  for idx, spec in enumerate(variable_specs):
    out.append(
      {
        "lever_id": str(spec.get("lever_id") or "").strip(),
        "quarter_index": int(quarter_index),
        "exact_value": float(vector[idx]),
      }
    )
  return out


def _vector_to_unit_interval(
  *,
  actual_vector: List[float],
  variable_specs: List[Dict[str, Any]],
) -> List[float]:
  lows = np.array([float(spec.get("min_value") or 0.0) for spec in variable_specs], dtype=float)
  highs = np.array([float(spec.get("max_value") or 0.0) for spec in variable_specs], dtype=float)
  spans = np.maximum(highs - lows, 1e-9)
  values = np.array([float(value) for value in actual_vector], dtype=float)
  unit_vector = np.clip((values - lows) / spans, 0.0, 1.0)
  return [float(value) for value in unit_vector.tolist()]


def _vector_from_unit_interval(
  *,
  unit_vector: List[float],
  variable_specs: List[Dict[str, Any]],
) -> List[float]:
  lows = np.array([float(spec.get("min_value") or 0.0) for spec in variable_specs], dtype=float)
  highs = np.array([float(spec.get("max_value") or 0.0) for spec in variable_specs], dtype=float)
  spans = np.maximum(highs - lows, 1e-9)
  unit_values = np.clip(np.array([float(value) for value in unit_vector], dtype=float), 0.0, 1.0)
  actual_vector = lows + (unit_values * spans)
  return [float(value) for value in actual_vector.tolist()]


def _evaluate_quarter_objective(
  *,
  base_model_input_json: Dict[str, Any],
  quarter_index: int,
  variable_specs: List[Dict[str, Any]],
  vector: List[float],
  target_metrics: Dict[str, float],
  tolerance_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[float, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  apply_exact_lever_updates_to_model_input, build_python_finmo_json = _load_numeric_apply_helpers()
  candidate_updates = _candidate_updates(
    quarter_index=quarter_index,
    variable_specs=variable_specs,
    vector=vector,
  )
  updated_model_input_json = apply_exact_lever_updates_to_model_input(
    model_input_json=base_model_input_json,
    exact_updates=[copy.deepcopy(item) for item in candidate_updates],
  )
  updated_finmo_json = build_python_finmo_json(model_input_json=updated_model_input_json)
  quarter_row = _finmo_row_map(updated_finmo_json).get(quarter_index) or {}
  telemetry_metrics: Dict[str, Any] = {}
  score = 0.0
  for metric_name, target_value in target_metrics.items():
    actual_value = _normalize_finmo_metric_value(metric_name, quarter_row)
    tolerance = _metric_tolerance(
      metric_name,
      float(target_value),
      tolerance_override=(tolerance_overrides or {}).get(str(metric_name or "").strip().lower()),
    )
    residual = max(abs(actual_value - float(target_value)) - tolerance, 0.0)
    score += (residual / max(tolerance, 1.0)) ** 2
    telemetry_metrics[metric_name] = {
      "target_value": float(target_value),
      "actual_value": float(actual_value),
      "tolerance": float(tolerance),
      "absolute_difference": float(abs(actual_value - float(target_value))),
      "residual_after_tolerance": float(residual),
    }
  for idx, spec in enumerate(variable_specs):
    scale = max(abs(float(spec.get("max_value") or 0.0) - float(spec.get("min_value") or 0.0)), 1.0)
    score += 0.08 * (((float(vector[idx]) - float(spec.get("anchor_value") or 0.0)) / scale) ** 2)
  return float(score), updated_model_input_json, updated_finmo_json, telemetry_metrics


def solve_review_plan(
  *,
  model_input_json: Optional[Dict[str, Any]],
  review_plan: Optional[Dict[str, Any]],
  numeric_solver_contract: Optional[Dict[str, Any]],
  fallback_exact_updates: List[Dict[str, Any]],
) -> Dict[str, Any]:
  contract = numeric_solver_contract if isinstance(numeric_solver_contract, dict) else {}
  pass_name = str(contract.get("pass_name") or "").strip()
  if pass_name not in {
    "initial_restructure",
    "realism_resolution",
    "cash_strategy_review",
    "unified_convergence",
  }:
    return {
      "execution_state": "numeric_solver_not_applicable",
      "solver_invoked": False,
      "exact_updates": copy.deepcopy(fallback_exact_updates),
      "attempts": [],
      "quarter_results": [],
      "outcome": {
        "execution_state": "numeric_solver_not_applicable",
        "reason": "Current numeric worker only activates for initial_restructure, realism_resolution, cash_strategy_review, and unified_convergence.",
      },
    }

  base_model_input_json = copy.deepcopy(model_input_json if isinstance(model_input_json, dict) else {})
  quarter_tasks = _quarter_tasks(review_plan)
  invalid_quarter_tasks = [
    {
      "quarter_index": int(task.get("quarter_index") or 0),
      "allowed_lever_ids": copy.deepcopy(task.get("allowed_lever_ids") or []),
      "missing_required_metrics": copy.deepcopy(task.get("missing_required_metrics") or []),
      "source_action_ids": copy.deepcopy(task.get("source_action_ids") or []),
    }
    for task in quarter_tasks
    if not bool(task.get("solver_ready"))
  ]
  if invalid_quarter_tasks:
    return {
      "execution_state": "numeric_solver_invalid_quarter_contract",
      "solver_invoked": False,
      "exact_updates": copy.deepcopy(fallback_exact_updates),
      "attempts": [],
      "quarter_results": [],
      "outcome": {
        "execution_state": "numeric_solver_invalid_quarter_contract",
        "reason": "One or more quarter tasks were missing required target metrics or allowed levers.",
        "execution_mode": "sequential_quarter_fit",
        "lumped_horizon_objective_used": False,
        "invalid_quarter_tasks": invalid_quarter_tasks,
      },
    }
  if not quarter_tasks:
    return {
      "execution_state": "numeric_solver_no_quarter_targets",
      "solver_invoked": False,
      "exact_updates": copy.deepcopy(fallback_exact_updates),
      "attempts": [],
      "quarter_results": [],
      "outcome": {
        "execution_state": "numeric_solver_no_quarter_targets",
        "reason": "No GPT-owned quarter target metrics were provided for this pass.",
        "execution_mode": "sequential_quarter_fit",
        "lumped_horizon_objective_used": False,
      },
    }

  guidance_by_key = _guidance_map(review_plan)
  fallback_map: Dict[Tuple[str, int], Dict[str, Any]] = {}
  for item in fallback_exact_updates:
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    quarter_index = int(_safe_float(item.get("quarter_index")) or 0)
    exact_value = _safe_float(item.get("exact_value"))
    if lever_id and quarter_index >= 1 and exact_value is not None:
      fallback_map[(lever_id, quarter_index)] = {
        "lever_id": lever_id,
        "quarter_index": quarter_index,
        "exact_value": float(exact_value),
      }

  solved_map: Dict[Tuple[str, int], Dict[str, Any]] = {}
  attempts: List[Dict[str, Any]] = []
  quarter_results: List[Dict[str, Any]] = []
  quarter_fit_summary: List[Dict[str, Any]] = []
  working_model_input_json = copy.deepcopy(base_model_input_json)

  for task in quarter_tasks:
    quarter_index = int(task.get("quarter_index") or 0)
    target_metrics = {
      str(metric_name).strip(): float(metric_value)
      for metric_name, metric_value in (task.get("target_metrics") or {}).items()
      if str(metric_name).strip() and _safe_float(metric_value) is not None
    }
    allowed_lever_ids = [
      str(item).strip()
      for item in (task.get("allowed_lever_ids") or [])
      if str(item).strip()
    ]
    if quarter_index < 1 or not target_metrics or not allowed_lever_ids:
      continue

    variable_specs = _build_variable_specs(
      working_model_input_json=working_model_input_json,
      quarter_index=quarter_index,
      allowed_lever_ids=allowed_lever_ids,
      numeric_solver_contract=contract,
      guidance_by_key=guidance_by_key,
    )
    if not variable_specs:
      continue

    baseline_vector = [float(spec.get("baseline_value") or 0.0) for spec in variable_specs]
    anchor_vector = [float(spec.get("anchor_value") or 0.0) for spec in variable_specs]
    unit_bounds = [(0.0, 1.0) for _ in variable_specs]

    baseline_score, _, _, baseline_metrics = _evaluate_quarter_objective(
      base_model_input_json=working_model_input_json,
      quarter_index=quarter_index,
      variable_specs=variable_specs,
      vector=baseline_vector,
      target_metrics=target_metrics,
      tolerance_overrides=copy.deepcopy(task.get("target_tolerances") or {}),
    )
    best_score = float(baseline_score)
    best_vector = list(baseline_vector)
    updated_model_input_json = copy.deepcopy(working_model_input_json)
    updated_finmo_json = {}
    metric_results = copy.deepcopy(baseline_metrics)
    optimizer_message = "baseline_only"
    optimizer_success = False

    seed_vectors = [
      _vector_to_unit_interval(
        actual_vector=baseline_vector,
        variable_specs=variable_specs,
      ),
      _vector_to_unit_interval(
        actual_vector=anchor_vector,
        variable_specs=variable_specs,
      ),
    ]
    normalized_seeds: List[List[float]] = []
    for seed in seed_vectors:
      rounded = [round(float(value), 6) for value in seed]
      if rounded not in normalized_seeds:
        normalized_seeds.append(rounded)

    def _unit_objective(arr: List[float]) -> float:
      actual_vector = _vector_from_unit_interval(
        unit_vector=[float(v) for v in arr],
        variable_specs=variable_specs,
      )
      return _evaluate_quarter_objective(
        base_model_input_json=working_model_input_json,
        quarter_index=quarter_index,
        variable_specs=variable_specs,
        vector=actual_vector,
        target_metrics=target_metrics,
        tolerance_overrides=copy.deepcopy(task.get("target_tolerances") or {}),
      )[0]

    for seed in normalized_seeds:
      result = minimize(
        _unit_objective,
        x0=seed,
        method="L-BFGS-B",
        bounds=unit_bounds,
        options={
          "maxiter": 80,
          # The objective surface comes from a full model recalculation, so
          # normalized finite-difference steps are more reliable than raw-value
          # steps on million-dollar levers.
          "eps": 0.05,
          "ftol": 1e-9,
        },
      )
      candidate_vector = _vector_from_unit_interval(
        unit_vector=[float(v) for v in result.x],
        variable_specs=variable_specs,
      )
      candidate_score, candidate_model_input_json, candidate_finmo_json, candidate_metric_results = _evaluate_quarter_objective(
        base_model_input_json=working_model_input_json,
        quarter_index=quarter_index,
        variable_specs=variable_specs,
        vector=candidate_vector,
        target_metrics=target_metrics,
        tolerance_overrides=copy.deepcopy(task.get("target_tolerances") or {}),
      )
      if float(candidate_score) < float(best_score) - 1e-9:
        best_score = float(candidate_score)
        best_vector = list(candidate_vector)
        updated_model_input_json = copy.deepcopy(candidate_model_input_json)
        updated_finmo_json = copy.deepcopy(candidate_finmo_json)
        metric_results = copy.deepcopy(candidate_metric_results)
        optimizer_message = str(result.message)
        optimizer_success = bool(result.success) or (float(baseline_score) - float(candidate_score) > 1e-6)

    quarter_updates = _candidate_updates(
      quarter_index=quarter_index,
      variable_specs=variable_specs,
      vector=best_vector,
    )
    for item in quarter_updates:
      solved_map[(str(item.get("lever_id") or "").strip(), int(item.get("quarter_index") or 0))] = copy.deepcopy(item)
    working_model_input_json = copy.deepcopy(updated_model_input_json)

    attempts.append(
      {
        "attempt_index": len(attempts) + 1,
        "quarter_index": quarter_index,
        "optimizer_converged": bool(optimizer_success),
        "objective_value": float(best_score),
        "objective_improvement": float(baseline_score - best_score),
        "lever_families": sorted(
          {
            str(item.get("lever_id") or "").split("::", 1)[0].strip().lower()
            for item in quarter_updates
            if str(item.get("lever_id") or "").strip()
          }
        ),
        "message": str(optimizer_message),
      }
    )
    quarter_results.append(
      {
        "quarter_index": quarter_index,
        "source_action_ids": copy.deepcopy(task.get("source_action_ids") or []),
        "required_target_metric_keys": copy.deepcopy(task.get("required_target_metric_keys") or []),
        "target_tolerances": copy.deepcopy(task.get("target_tolerances") or {}),
        "target_metrics": copy.deepcopy(metric_results),
        "allowed_lever_ids": copy.deepcopy(allowed_lever_ids),
        "variable_spec_count": len(variable_specs),
        "baseline_objective": float(baseline_score),
        "best_objective": float(best_score),
        "objective_delta": float(baseline_score - best_score),
        "applied_updates": copy.deepcopy(quarter_updates),
      }
    )
    met_metric_names = sorted(
      [
        metric_name
        for metric_name, metric_payload in metric_results.items()
        if float(_safe_float((metric_payload or {}).get("residual_after_tolerance")) or 0.0) <= 1e-9
      ]
    )
    unmet_metric_names = sorted(
      [
        metric_name
        for metric_name, metric_payload in metric_results.items()
        if float(_safe_float((metric_payload or {}).get("residual_after_tolerance")) or 0.0) > 1e-9
      ]
    )
    quarter_fit_summary.append(
      {
        "quarter_index": quarter_index,
        "within_tolerance_all_targets": not unmet_metric_names,
        "met_target_metric_names": met_metric_names,
        "unmet_target_metric_names": unmet_metric_names,
        "max_absolute_difference": max(
          [
            float(_safe_float((metric_payload or {}).get("absolute_difference")) or 0.0)
            for metric_payload in metric_results.values()
          ] or [0.0]
        ),
        "max_residual_after_tolerance": max(
          [
            float(_safe_float((metric_payload or {}).get("residual_after_tolerance")) or 0.0)
            for metric_payload in metric_results.values()
          ] or [0.0]
        ),
      }
    )

  final_updates = list(fallback_map.values())
  for key, item in solved_map.items():
    replaced = False
    for idx, existing in enumerate(final_updates):
      if (
        str(existing.get("lever_id") or "").strip() == key[0]
        and int(existing.get("quarter_index") or 0) == key[1]
      ):
        final_updates[idx] = copy.deepcopy(item)
        replaced = True
        break
    if not replaced:
      final_updates.append(copy.deepcopy(item))
  final_updates.sort(key=lambda item: (int(item.get("quarter_index") or 0), str(item.get("lever_id") or "").strip()))

  baseline_objective = sum(float(item.get("objective_value") or 0.0) + float(item.get("objective_improvement") or 0.0) for item in attempts)
  best_objective = sum(float(item.get("objective_value") or 0.0) for item in attempts)

  return {
    "execution_state": "numeric_attempt_completed",
    "solver_invoked": True,
    "exact_updates": final_updates,
    "attempts": attempts,
    "quarter_results": quarter_results,
    "outcome": {
      "execution_state": "numeric_attempt_completed",
      "reason": "Quarter-by-quarter numeric fitting completed using GPT-owned finmo targets and GPT-approved model-input levers.",
      "execution_mode": "sequential_quarter_fit",
      "lumped_horizon_objective_used": False,
      "quarter_execution_order": "ascending",
      "quarter_count_processed": len(quarter_results),
      "quarters_with_all_targets_within_tolerance": int(
        sum(1 for item in quarter_fit_summary if bool(item.get("within_tolerance_all_targets")))
      ),
      "quarters_with_target_misses": int(
        sum(1 for item in quarter_fit_summary if not bool(item.get("within_tolerance_all_targets")))
      ),
      "attempted_lever_families": sorted(
        {
          str(item.get("lever_id") or "").split("::", 1)[0].strip().lower()
          for item in final_updates
          if str(item.get("lever_id") or "").strip()
        }
      ),
      "baseline_objective": float(baseline_objective),
      "best_objective": float(best_objective),
      "objective_delta": float(baseline_objective - best_objective),
      "quarter_fit_summary": copy.deepcopy(quarter_fit_summary),
      "quarter_results": copy.deepcopy(quarter_results),
    },
  }
