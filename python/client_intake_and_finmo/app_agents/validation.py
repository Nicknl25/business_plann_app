from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema_loader import load_schema
from .schema_validation import validate_data_against_schema


def _text(value: Any) -> str:
  return str(value or "").strip()


def _number(value: Any) -> Optional[float]:
  try:
    return float(value)
  except Exception:
    return None


def load_scenario_matrix() -> Dict[str, Any]:
  path = Path(__file__).resolve().parent / "scenario_matrix.json"
  return json.loads(path.read_text(encoding="utf-8"))


def _row_map(app_agents_run_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  grid_agent = app_agents_run_json.get("grid_agent") if isinstance(app_agents_run_json.get("grid_agent"), dict) else {}
  grid_json = grid_agent.get("grid_json") if isinstance(grid_agent.get("grid_json"), dict) else {}
  rows = grid_json.get("rows") if isinstance(grid_json.get("rows"), list) else []
  out: Dict[str, Dict[str, Any]] = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    row_id = _text(row.get("row_id"))
    if row_id:
      out[row_id] = row
  return out


def _row_catalog_map(shared_context: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  rows = shared_context.get("row_catalog") if isinstance(shared_context.get("row_catalog"), list) else []
  out: Dict[str, Dict[str, Any]] = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    row_id = _text(row.get("row_id"))
    if row_id:
      out[row_id] = row
  return out


def _band_values(row: Dict[str, Any]) -> List[Dict[str, float]]:
  out: List[Dict[str, float]] = []
  for band in (row.get("quarter_bands") or []):
    if not isinstance(band, dict):
      continue
    min_value = _number(band.get("min_value"))
    max_value = _number(band.get("max_value"))
    quarter_index = int(band.get("quarter_index") or 0)
    if min_value is None or max_value is None or quarter_index < 1:
      continue
    out.append({"quarter_index": quarter_index, "min_value": min_value, "max_value": max_value})
  return out


def _moved_row_count(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> int:
  catalog = _row_catalog_map(shared_context)
  grid_rows = _row_map(app_agents_run_json)
  moved = 0
  for row_id, grid_row in grid_rows.items():
    baseline = catalog.get(row_id) if isinstance(catalog.get(row_id), dict) else {}
    baseline_values = list(baseline.get("baseline_values") or [])
    band_values = _band_values(grid_row)
    if not baseline_values or not band_values:
      continue
    row_moved = False
    for index, band in enumerate(band_values):
      base = _number(baseline_values[index]) if index < len(baseline_values) else None
      if base is None:
        continue
      if abs(base - float(band["min_value"])) > 1e-6 or abs(base - float(band["max_value"])) > 1e-6:
        row_moved = True
        break
    if row_moved:
      moved += 1
  return moved


def _cash_monotonic_non_decreasing(app_agents_run_json: Dict[str, Any]) -> bool:
  cash_row = _row_map(app_agents_run_json).get("Cash") or {}
  bands = _band_values(cash_row)
  if len(bands) < 2:
    return False
  mins = [item["min_value"] for item in bands]
  maxs = [item["max_value"] for item in bands]
  mins_non_decreasing = all(mins[index] >= mins[index - 1] for index in range(1, len(mins)))
  maxs_non_decreasing = all(maxs[index] >= maxs[index - 1] for index in range(1, len(maxs)))
  return mins_non_decreasing and maxs_non_decreasing


def _capital_cash_monotonicity_expectation(app_agents_run_json: Dict[str, Any]) -> str:
  capital_agent = app_agents_run_json.get("capital_agent") if isinstance(app_agents_run_json.get("capital_agent"), dict) else {}
  strategy_signature = capital_agent.get("strategy_signature") if isinstance(capital_agent.get("strategy_signature"), dict) else {}
  return _text(strategy_signature.get("cash_monotonicity_expectation")).lower()


def _group_row_ids(shared_context: Dict[str, Any], group_id: str) -> List[str]:
  mechanics = shared_context.get("business_mechanics") if isinstance(shared_context.get("business_mechanics"), dict) else {}
  groups = mechanics.get("driver_groups") if isinstance(mechanics.get("driver_groups"), list) else []
  for group in groups:
    if not isinstance(group, dict):
      continue
    if _text(group.get("group_id")) != group_id:
      continue
    return [_text(item) for item in (group.get("row_ids") or []) if _text(item)]
  return []


def _row_changed(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any], row_id: str) -> bool:
  catalog = _row_catalog_map(shared_context)
  grid_rows = _row_map(app_agents_run_json)
  baseline = catalog.get(row_id) if isinstance(catalog.get(row_id), dict) else {}
  grid_row = grid_rows.get(row_id) if isinstance(grid_rows.get(row_id), dict) else {}
  baseline_values = list(baseline.get("baseline_values") or [])
  band_values = _band_values(grid_row)
  if not baseline_values or not band_values:
    return False
  for index, band in enumerate(band_values[:len(baseline_values)]):
    base = _number(baseline_values[index])
    if base is None:
      continue
    if abs(base - float(band["min_value"])) > 1e-6 or abs(base - float(band["max_value"])) > 1e-6:
      return True
  return False


def _group_changed(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any], group_id: str) -> bool:
  return any(_row_changed(shared_context, app_agents_run_json, row_id) for row_id in _group_row_ids(shared_context, group_id))


def _group_exists(shared_context: Dict[str, Any], group_id: str) -> bool:
  return bool(_group_row_ids(shared_context, group_id))


def _row_is_flat(app_agents_run_json: Dict[str, Any], row_id: str) -> bool:
  row = _row_map(app_agents_run_json).get(row_id) or {}
  bands = _band_values(row)
  if not bands:
    return False
  pairs = [(round(item["min_value"], 6), round(item["max_value"], 6)) for item in bands]
  return len(set(pairs)) == 1


def _group_all_flat(app_agents_run_json: Dict[str, Any], row_ids: List[str]) -> bool:
  relevant = [row_id for row_id in row_ids if row_id]
  if not relevant:
    return False
  return all(_row_is_flat(app_agents_run_json, row_id) for row_id in relevant)


def _contract_integrity(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> Dict[str, Any]:
  issues: List[str] = []
  run_errors = validate_data_against_schema(data=app_agents_run_json, schema=load_schema("app_agents_run.schema.json"))
  if run_errors:
    issues.extend(run_errors[:12])
  row_catalog = _row_catalog_map(shared_context)
  grid_rows = _row_map(app_agents_run_json)
  if row_catalog and len(grid_rows) != len(row_catalog):
    issues.append(f"grid row count {len(grid_rows)} does not match row catalog count {len(row_catalog)}")
  missing = sorted(row_id for row_id in row_catalog if row_id not in grid_rows)
  if missing:
    issues.append("missing grid rows: " + ", ".join(missing[:12]))
  return {"pass": not issues, "issues": issues}


def _planner_readiness(app_agents_run_json: Dict[str, Any]) -> Dict[str, Any]:
  issues: List[str] = []
  planner_status = _text(app_agents_run_json.get("planner_status"))
  if planner_status != "ready":
    issues.append(f"planner_status={planner_status or 'missing'}")
  grid_agent = app_agents_run_json.get("grid_agent") if isinstance(app_agents_run_json.get("grid_agent"), dict) else {}
  self_check = grid_agent.get("self_check") if isinstance(grid_agent.get("self_check"), dict) else {}
  for key in (
    "realism_satisfied",
    "operations_satisfied",
    "capital_satisfied",
    "row_coherence_satisfied",
    "solver_contract_preserved",
  ):
    if self_check.get(key) is not True:
      issues.append(f"grid self_check failed: {key}")
  blocking = list(grid_agent.get("blocking_conflicts") or [])
  if blocking:
    issues.append("blocking_conflicts present")
  return {"pass": not issues, "issues": issues}


def _strategy_visibility(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> Dict[str, Any]:
  issues: List[str] = []
  moved_row_count = _moved_row_count(shared_context, app_agents_run_json)
  strategy_value = _text((((shared_context.get("strategy_profile") or {}).get("cash_strategy_value"))))
  if moved_row_count <= 0:
    issues.append("no material row movement detected versus baseline")
  if strategy_value in {"reinvest", "shareholder_return", "balanced"} and moved_row_count < 2:
    issues.append("too little row movement for selected strategy to be visibly legible")
  return {"pass": not issues, "issues": issues, "moved_row_count": moved_row_count}


def _staircase_risk(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> Dict[str, Any]:
  issues: List[str] = []
  monotonic = _cash_monotonic_non_decreasing(app_agents_run_json)
  strategy_value = _text((((shared_context.get("strategy_profile") or {}).get("cash_strategy_value"))))
  expectation = _capital_cash_monotonicity_expectation(app_agents_run_json)
  monotonic_disallowed = expectation in {"non_monotonic_expected", "extraction_or_flattening_expected", "mixed"}
  if not expectation:
    monotonic_disallowed = strategy_value in {"reinvest", "shareholder_return", "balanced"}
  if monotonic and monotonic_disallowed:
    issues.append("cash row is monotonic non-decreasing despite a strategy that should often show visible deployment or extraction")
  return {
    "pass": not issues,
    "issues": issues,
    "cash_monotonic_non_decreasing": monotonic,
    "cash_monotonicity_expectation": expectation,
  }


def _row_coherence(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> Dict[str, Any]:
  issues: List[str] = []
  row_catalog = _row_catalog_map(shared_context)
  grid_rows = _row_map(app_agents_run_json)
  moved_rows = _moved_row_count(shared_context, app_agents_run_json)
  revenue_like = [row_id for row_id in grid_rows if "revenue::" in row_id.lower() or row_id == "Revenue"]
  payroll_like = [row_id for row_id in grid_rows if "payroll" in row_id.lower()]
  marketing_like = [row_id for row_id in grid_rows if "marketing" in row_id.lower()]
  capex_like = [row_id for row_id in grid_rows if "capital expenditures" in row_id.lower() or "capex" in row_id.lower()]
  if revenue_like and moved_rows > 0 and not (payroll_like or marketing_like or capex_like):
    issues.append("revenue-related movement detected without obvious supporting payroll, marketing, or capex rows")
  for row_id in payroll_like + marketing_like + capex_like:
    baseline = row_catalog.get(row_id) if isinstance(row_catalog.get(row_id), dict) else {}
    if not baseline:
      continue
    baseline_values = list(baseline.get("baseline_values") or [])
    bands = _band_values(grid_rows.get(row_id) or {})
    if baseline_values and bands:
      changed = any(
        (_number(baseline_values[index]) is not None)
        and (
          abs((_number(baseline_values[index]) or 0.0) - band["min_value"]) > 1e-6
          or abs((_number(baseline_values[index]) or 0.0) - band["max_value"]) > 1e-6
        )
        for index, band in enumerate(bands[:len(baseline_values)])
      )
      if not changed and _text((((shared_context.get("strategy_profile") or {}).get("cash_strategy_value")))) == "reinvest":
        issues.append(f"{row_id} stayed at baseline under reinvest strategy")
  return {"pass": not issues, "issues": issues}


def _business_mechanics_gate(shared_context: Dict[str, Any], app_agents_run_json: Dict[str, Any]) -> Dict[str, Any]:
  mechanics = shared_context.get("business_mechanics") if isinstance(shared_context.get("business_mechanics"), dict) else {}
  issues: List[str] = []
  growth_story_present = mechanics.get("growth_story_present") is True
  acquisition_motion_required = mechanics.get("acquisition_motion_required") is True
  labor_scaling_required = mechanics.get("labor_scaling_required") is True
  capital_deployment_required = mechanics.get("capital_deployment_required") is True
  working_capital_motion_expected = mechanics.get("working_capital_motion_expected") is True
  strategy_value = _text((((shared_context.get("strategy_profile") or {}).get("cash_strategy_value")))).lower()

  revenue_output_rows = _group_row_ids(shared_context, "output_revenue")
  revenue_driver_groups = ("capacity_drivers", "utilization_drivers", "pricing_drivers")
  support_groups = ("payroll_labor", "support_opex", "demand_generation")
  deployment_groups = ("capital_deployment", "payroll_labor", "demand_generation", "financing_flows")

  if growth_story_present:
    if revenue_output_rows and _group_all_flat(app_agents_run_json, revenue_output_rows):
      issues.append("growth story is present but Revenue output stayed flat across the full horizon")
    if not any(_group_changed(shared_context, app_agents_run_json, group_id) for group_id in revenue_driver_groups if _group_exists(shared_context, group_id)):
      issues.append("growth story is present but all core revenue driver groups stayed at baseline")
    payroll_rows = _group_row_ids(shared_context, "payroll_labor")
    if labor_scaling_required and payroll_rows and _group_all_flat(app_agents_run_json, payroll_rows):
      issues.append("business appears labor-constrained but payroll rows stayed flat across the full horizon")
    if labor_scaling_required and _group_exists(shared_context, "payroll_labor") and not _group_changed(shared_context, app_agents_run_json, "payroll_labor"):
      issues.append("business appears labor-constrained but payroll/labor rows did not move with the growth story")
    if acquisition_motion_required and _group_exists(shared_context, "demand_generation") and not _group_changed(shared_context, app_agents_run_json, "demand_generation"):
      issues.append("business appears acquisition-driven but demand-generation rows did not move")
    changed_core_groups = sum(
      1
      for group_id in revenue_driver_groups + support_groups
      if _group_exists(shared_context, group_id) and _group_changed(shared_context, app_agents_run_json, group_id)
    )
    if changed_core_groups < 2:
      issues.append("too few interacting operating groups changed for a business that claims meaningful growth or change")

  if capital_deployment_required:
    deployment_group_changes = sum(
      1
      for group_id in deployment_groups
      if _group_exists(shared_context, group_id) and _group_changed(shared_context, app_agents_run_json, group_id)
    )
    if strategy_value in {"reinvest", "balanced"} and _cash_monotonic_non_decreasing(app_agents_run_json) and deployment_group_changes < 2:
      issues.append("cash strategy implies visible deployment, but cash still staircases with too little movement in deployment groups")
    if strategy_value == "shareholder_return" and _cash_monotonic_non_decreasing(app_agents_run_json) and not _group_changed(shared_context, app_agents_run_json, "financing_flows"):
      issues.append("shareholder-return strategy is not visible because financing or extraction rows did not move while cash kept building")

  if working_capital_motion_expected and _group_changed(shared_context, app_agents_run_json, "output_revenue") and _group_exists(shared_context, "working_capital_and_tax") and not _group_changed(shared_context, app_agents_run_json, "working_capital_and_tax"):
    issues.append("revenue moved but working-capital and tax rows remained frozen")

  return {"pass": not issues, "issues": issues}


def evaluate_app_agents_run(
  *,
  scenario_id: str,
  shared_context: Dict[str, Any],
  app_agents_run_json: Dict[str, Any],
) -> Dict[str, Any]:
  shared_context_copy = copy.deepcopy(shared_context or {})
  run_copy = copy.deepcopy(app_agents_run_json or {})
  contract_integrity = _contract_integrity(shared_context_copy, run_copy)
  planner_readiness = _planner_readiness(run_copy)
  strategy_visibility = _strategy_visibility(shared_context_copy, run_copy)
  staircase_risk = _staircase_risk(shared_context_copy, run_copy)
  row_coherence = _row_coherence(shared_context_copy, run_copy)
  business_mechanics = _business_mechanics_gate(shared_context_copy, run_copy)
  overall_pass = all((
    contract_integrity["pass"],
    planner_readiness["pass"],
    strategy_visibility["pass"],
    staircase_risk["pass"],
    row_coherence["pass"],
    business_mechanics["pass"],
  ))
  result = {
    "scenario_id": _text(scenario_id),
    "planner_status": _text(run_copy.get("planner_status")),
    "overall_pass": bool(overall_pass),
    "contract_integrity": contract_integrity,
    "planner_readiness": planner_readiness,
    "strategy_visibility": strategy_visibility,
    "staircase_risk": staircase_risk,
    "row_coherence": row_coherence,
    "business_mechanics": business_mechanics,
  }
  errors = validate_data_against_schema(data=result, schema=load_schema("validation_result.schema.json"))
  if errors:
    raise ValueError("validation_result.schema.json validation failed: " + " | ".join(errors[:12]))
  return result
