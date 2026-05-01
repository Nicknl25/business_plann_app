"""Post-intake issue detection.

This module owns the detectors that decide whether a post-intake issue exists.
The runner still owns packet construction and convergence plumbing; detectors
must stay table-backed and must not live in the intake API handler.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Set

from client_intake_and_finmo.post_intake_mapping import (
  post_intake_issue_candidate_lever_ids,
  post_intake_target_metric_names_for_issue,
)

_RUNTIME: Dict[str, Any] = {}


def bind_runtime_dependencies(dependencies: Dict[str, Any]) -> None:
  if not isinstance(dependencies, dict):
    return
  _RUNTIME.update(dependencies)


def _dep(name: str) -> Any:
  value = _RUNTIME.get(name)
  if value is None:
    raise RuntimeError(f"post_intake_issue_detection_dependency_missing: {name}")
  return value


def _safe_float(value: Any) -> Optional[float]:
  return _dep("_safe_float")(value)


def _contract_forecast_quarter_count() -> int:
  return int(_dep("_contract_forecast_quarter_count")())


def _issue_allowed_target_metric_names(issue_code: Any, *, phase: str) -> Set[str]:
  return {
    str(item or "").strip().lower()
    for item in post_intake_target_metric_names_for_issue(issue_code, phase=phase)
    if str(item or "").strip()
  }


def _cost_structure_direct_metric_specs_for_quarter(
  *,
  quarter_index: int,
  quarter_row: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  row = quarter_row if isinstance(quarter_row, dict) else {}
  phase = _dep("_quarter_phase_label")(quarter_index)
  revenue = max(0.0, float(_safe_float(row.get("revenue")) or 0.0))
  if revenue <= 0.0:
    return []
  allowed_metrics = _issue_allowed_target_metric_names(
    "cost_structure_mismatch",
    phase="convergence",
  )
  if not allowed_metrics:
    raise RuntimeError(
      "cost_structure_mismatch_mapping_failed: cost structure issue has no table-backed target metrics."
    )
  cogs = float(_dep("_quarter_row_cost_of_goods_sold")(row) or 0.0)
  marketing = float(_safe_float(row.get("marketing")) or 0.0)
  research_and_development = float(_safe_float(row.get("research_and_development")) or 0.0)
  lease_rent = float(_safe_float(row.get("lease_rent")) or 0.0)
  g_and_a = float(_safe_float(row.get("g_and_a")) or 0.0)
  gross_margin_floor = {"early": 0.18, "mid": 0.20, "late": 0.22}[phase]
  gross_margin_ceiling = {"early": 0.65, "mid": 0.60, "late": 0.55}[phase]
  cogs_floor = max(0.0, revenue * (1.0 - gross_margin_ceiling))
  cogs_ceiling = max(cogs_floor, revenue * (1.0 - gross_margin_floor))
  cost_component_ceiling_pct = {
    "marketing": {"early": 0.45, "mid": 0.40, "late": 0.35}[phase],
    "research_and_development": {"early": 0.35, "mid": 0.30, "late": 0.25}[phase],
    "lease_rent": {"early": 0.35, "mid": 0.30, "late": 0.25}[phase],
    "g_and_a": {"early": 0.35, "mid": 0.30, "late": 0.25}[phase],
  }
  spec = _dep("_table_target_currency_metric_spec")
  specs: List[Dict[str, Any]] = []
  if "cogs" in allowed_metrics or "cost_of_goods_sold" in allowed_metrics:
    specs.append(spec(
      "cogs",
      actual_value=cogs,
      target_floor=cogs_floor,
      target_ceiling=cogs_ceiling,
      score_scale=max(revenue * 0.06, 1000.0),
      source_metric_names=["cogs", "revenue", "gross_profit"],
      metric_definition="COGS dollars must stay inside the direct table-backed operating cost band implied by revenue.",
    ))
  if "marketing" in allowed_metrics:
    specs.append(spec(
      "marketing",
      actual_value=marketing,
      target_floor=0.0,
      target_ceiling=revenue * cost_component_ceiling_pct["marketing"],
      score_scale=max(revenue * 0.08, 1000.0),
      source_metric_names=["marketing", "revenue"],
      metric_definition="Marketing dollars must stay inside the direct table-backed operating cost band implied by revenue.",
    ))
  if "research_and_development" in allowed_metrics:
    specs.append(spec(
      "research_and_development",
      actual_value=research_and_development,
      target_floor=0.0,
      target_ceiling=revenue * cost_component_ceiling_pct["research_and_development"],
      score_scale=max(revenue * 0.08, 1000.0),
      source_metric_names=["research_and_development", "revenue"],
      metric_definition="R&D dollars must stay inside the direct table-backed operating cost band implied by revenue.",
    ))
  if "lease_rent" in allowed_metrics:
    specs.append(spec(
      "lease_rent",
      actual_value=lease_rent,
      target_floor=0.0,
      target_ceiling=revenue * cost_component_ceiling_pct["lease_rent"],
      score_scale=max(revenue * 0.08, 1000.0),
      source_metric_names=["lease_rent", "revenue"],
      metric_definition="Lease/rent dollars must stay inside the direct table-backed operating cost band implied by revenue.",
    ))
  if "g_and_a" in allowed_metrics:
    specs.append(spec(
      "g_and_a",
      actual_value=g_and_a,
      target_floor=0.0,
      target_ceiling=revenue * cost_component_ceiling_pct["g_and_a"],
      score_scale=max(revenue * 0.08, 1000.0),
      source_metric_names=["g_and_a", "revenue"],
      metric_definition="G&A dollars must stay inside the direct table-backed operating cost band implied by revenue.",
    ))
  return [item for item in specs if isinstance(item, dict)]


def _issue_metric_specs_for_quarter(
  *,
  issue_code: Any,
  quarter_index: int,
  quarter_row: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  row = quarter_row if isinstance(quarter_row, dict) else {}
  code = str(issue_code or "").strip().lower()
  phase = _dep("_quarter_phase_label")(quarter_index)
  revenue = float(_safe_float(row.get("revenue")) or 0.0)
  current_assets = float(_safe_float(row.get("current_assets")) or 0.0)
  current_liabilities = float(_safe_float(row.get("current_liabilities")) or 0.0)
  working_capital = current_assets - current_liabilities
  specs: List[Optional[Dict[str, Any]]] = []
  table_spec = _dep("_table_target_currency_metric_spec")
  if code == "working_capital_mismatch":
    wc_ceiling = {"early": 0.24, "mid": 0.20, "late": 0.16}[phase] * max(revenue, 0.0)
    wc_floor = 0.0
    working_capital_gap_high = max(0.0, working_capital - wc_ceiling)
    working_capital_gap_low = max(0.0, wc_floor - working_capital)
    asset_components = {
      "accounts_receivable": float(_safe_float(row.get("accounts_receivable")) or 0.0),
      "inventory": float(_safe_float(row.get("inventory")) or 0.0),
      "prepaid_expenses": float(_safe_float(row.get("prepaid_expenses")) or 0.0),
    }
    liability_components = {
      "accounts_payable": float(_safe_float(row.get("accounts_payable")) or 0.0),
      "deferred_revenue": float(_safe_float(row.get("deferred_revenue")) or 0.0),
    }
    if revenue > 0.0 and working_capital_gap_high > 1.0:
      total_assets_for_repair = sum(max(0.0, value) for value in asset_components.values())
      total_liabilities_for_repair = sum(max(0.0, value) for value in liability_components.values())
      for metric_name, actual_value in asset_components.items():
        if actual_value <= 0.0 or total_assets_for_repair <= 0.0:
          continue
        allocated_reduction = working_capital_gap_high * (actual_value / total_assets_for_repair)
        specs.append(table_spec(
          metric_name,
          actual_value=actual_value,
          target_floor=0.0,
          target_ceiling=max(0.0, actual_value - allocated_reduction),
          score_scale=max(abs(allocated_reduction), revenue * 0.02, 1000.0),
          source_metric_names=[metric_name, "current_assets", "current_liabilities", "revenue"],
          metric_definition="Working-capital realism repairs only direct table-backed working-capital driver rows.",
        ))
      for metric_name, actual_value in liability_components.items():
        if total_liabilities_for_repair <= 0.0 and actual_value <= 0.0:
          continue
        denominator = total_liabilities_for_repair if total_liabilities_for_repair > 0.0 else float(len(liability_components))
        allocation_base = actual_value if total_liabilities_for_repair > 0.0 else 1.0
        allocated_increase = working_capital_gap_high * (allocation_base / denominator)
        specs.append(table_spec(
          metric_name,
          actual_value=actual_value,
          target_floor=max(0.0, actual_value + allocated_increase),
          score_scale=max(abs(allocated_increase), revenue * 0.02, 1000.0),
          source_metric_names=[metric_name, "current_assets", "current_liabilities", "revenue"],
          metric_definition="Working-capital realism repairs only direct table-backed working-capital driver rows.",
        ))
    elif revenue > 0.0 and working_capital_gap_low > 1.0:
      total_liabilities_for_repair = sum(max(0.0, value) for value in liability_components.values())
      total_assets_for_repair = sum(max(0.0, value) for value in asset_components.values())
      for metric_name, actual_value in liability_components.items():
        if actual_value <= 0.0 or total_liabilities_for_repair <= 0.0:
          continue
        allocated_reduction = working_capital_gap_low * (actual_value / total_liabilities_for_repair)
        specs.append(table_spec(
          metric_name,
          actual_value=actual_value,
          target_floor=0.0,
          target_ceiling=max(0.0, actual_value - allocated_reduction),
          score_scale=max(abs(allocated_reduction), revenue * 0.02, 1000.0),
          source_metric_names=[metric_name, "current_assets", "current_liabilities", "revenue"],
          metric_definition="Working-capital realism repairs only direct table-backed working-capital driver rows.",
        ))
      for metric_name, actual_value in asset_components.items():
        denominator = total_assets_for_repair if total_assets_for_repair > 0.0 else float(len(asset_components))
        allocation_base = actual_value if total_assets_for_repair > 0.0 else 1.0
        allocated_increase = working_capital_gap_low * (allocation_base / denominator)
        specs.append(table_spec(
          metric_name,
          actual_value=actual_value,
          target_floor=max(0.0, actual_value + allocated_increase),
          score_scale=max(abs(allocated_increase), revenue * 0.02, 1000.0),
          source_metric_names=[metric_name, "current_assets", "current_liabilities", "revenue"],
          metric_definition="Working-capital realism repairs only direct table-backed working-capital driver rows.",
        ))
  elif code == "accounting_integrity_failure":
    accounting_gap = abs(float(_safe_float(row.get("accounting_equation_check")) or 0.0))
    specs.append(_dep("_build_issue_metric_spec")(
      "accounting_equation_check_abs",
      actual_value=accounting_gap,
      target_ceiling=float(_dep("_UNIFIED_ACCOUNTING_EQUATION_TOLERANCE")),
      score_scale=max(float(_dep("_UNIFIED_ACCOUNTING_EQUATION_TOLERANCE")), 1.0),
      source_metric_names=["total_assets", "total_liabilities_and_equity"],
      metric_definition="The accounting equation must stay tied inside the configured tolerance.",
      unit_kind="currency",
    ))
  elif code in {"liquidity_failure", "funding_structure_mismatch"}:
    pass
  elif code == "cost_structure_mismatch":
    specs.extend(_cost_structure_direct_metric_specs_for_quarter(
      quarter_index=quarter_index,
      quarter_row=row,
    ))
  elif code == "capacity_support_mismatch" and revenue <= 0.0:
    allowed_metrics = _issue_allowed_target_metric_names(
      "capacity_support_mismatch",
      phase="convergence",
    )
    if "revenue" not in allowed_metrics:
      raise RuntimeError(
        "capacity_support_mismatch_mapping_failed: capacity support issue must map to the table-backed revenue target."
      )
    specs.append(table_spec(
      "revenue",
      actual_value=revenue,
      target_floor=1.0,
      score_scale=1000.0,
      source_metric_names=["revenue"],
      metric_definition="Capacity/revenue realism requires a positive direct table-backed revenue target.",
    ))
  return [item for item in specs if isinstance(item, dict) and str(item.get("metric_name") or "").strip()]


def _raise_p_and_l_flatline_if_needed(
  *,
  final_model_input_json: Optional[Dict[str, Any]],
  final_finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  issue_records = _build_p_and_l_flatline_issue_status_records(
    model_input_json=copy.deepcopy(final_model_input_json or {}),
    finmo_json=copy.deepcopy(final_finmo_json or {}),
    iteration=1,
  )
  if not issue_records:
    return
  first_issue = issue_records[0]
  diagnostics = {
    "failure_stage": str(stage or "final_model").strip() or "final_model",
    "failure_reason": "p_and_l_flatline",
    "validation_error": {
      "rejected": True,
      "reason_code": "p_and_l_flatline",
      "reason": "Final model contains an unrealistic flat or plateaued P&L trajectory.",
    },
    "pre_solver_validation": {
      "flags": ["p_and_l_flatline"],
      "errors": [
        {
          "error": "p_and_l_flatline",
          "reason": str(first_issue.get("detail") or "").strip(),
          "validation_category": "financial_realism",
          "violating_quarters": copy.deepcopy(first_issue.get("remaining_problem_quarters") or []),
        }
      ],
    },
    "p_and_l_flatline_issue": copy.deepcopy(first_issue),
  }
  raise _dep("StructuredSystemRunFailure")(
    detail="p_and_l_flatline",
    diagnostics=diagnostics,
  )


def _build_capacity_support_issue_status_records(
  *,
  finmo_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]] = None,
  iteration: int,
) -> List[Dict[str, Any]]:
  rows_by_q = _dep("_finmo_quarter_row_map")(finmo_json)
  if not rows_by_q:
    return []
  model_input = model_input_json if isinstance(model_input_json, dict) else {}
  lever_value_map = _dep("_solved_lever_value_map")(model_input) if model_input else {}
  metric_specs: List[Dict[str, Any]] = []
  problem_quarters: List[int] = []
  for quarter_index in range(1, _contract_forecast_quarter_count() + 1):
    quarter_row = rows_by_q.get(quarter_index) or {}
    actual_revenue = float(_safe_float(quarter_row.get("revenue")) or 0.0)
    expected_revenue = (
      _dep("_baseline_revenue_from_formula_levers")(
        baseline_values_by_lever=lever_value_map,
        quarter_index=quarter_index,
      )
      if lever_value_map
      else None
    )
    quarter_specs = []
    if expected_revenue is not None and expected_revenue > 0.0:
      gap = abs(float(actual_revenue) - float(expected_revenue))
      tolerance = max(1.0, abs(float(expected_revenue)) * 0.005)
      if gap > tolerance:
        quarter_specs.append(_dep("_table_target_currency_metric_spec")(
          "revenue",
          actual_value=actual_revenue,
          target_floor=float(expected_revenue) - tolerance,
          target_ceiling=float(expected_revenue) + tolerance,
          score_scale=max(abs(float(expected_revenue)) * 0.01, 1000.0),
          source_metric_names=["revenue", "capacity", "unit_price", "utilization"],
          metric_definition=(
            "Capacity support is a direct formula integrity check: revenue must equal "
            "sum(Capacity * Unit Price * Utilization) from table-backed revenue_formula_bundle drivers."
          ),
        ))
    else:
      quarter_specs = _issue_metric_specs_for_quarter(
        issue_code="capacity_support_mismatch",
        quarter_index=quarter_index,
        quarter_row=quarter_row,
      )
    actionable_specs = [
      copy.deepcopy(spec)
      for spec in quarter_specs
      if isinstance(spec, dict)
      and str(spec.get("metric_name") or "").strip()
      and (
        not bool(spec.get("within_boundary"))
        or abs(float(_safe_float(spec.get("gap_abs")) or 0.0)) > 1e-9
      )
      and (
        _safe_float(spec.get("target_floor")) is not None
        or _safe_float(spec.get("target_ceiling")) is not None
      )
    ]
    if not actionable_specs:
      continue
    problem_quarters.append(quarter_index)
    for spec in actionable_specs:
      spec["quarter_index"] = int(quarter_index)
      metric_specs.append(spec)
  if not problem_quarters or not metric_specs:
    return []
  allowed_levers = post_intake_issue_candidate_lever_ids(
    "capacity_support_mismatch",
    phase="convergence",
  )
  if not allowed_levers:
    raise RuntimeError(
      "capacity_support_mismatch_mapping_failed: capacity support issue fired but no table-backed revenue levers are available."
    )
  return [
    _dep("_normalize_issue_record_to_controller_truth")(
      {
        "issue": "capacity_support_mismatch",
        "issue_code": "capacity_support_mismatch",
        "detail": (
          "Revenue does not match the deterministic table-backed capacity, price, and utilization formula. "
          "Repair must use mapped revenue formula drivers only."
        ),
        "candidate_kind": "table_backed_revenue_formula_detector",
        "remaining_problem_quarters": sorted(set(problem_quarters)),
        "remaining_issue_materiality": "material",
        "remaining_issue_severity_score": 100,
        "next_required_lever_ids": copy.deepcopy(allowed_levers),
        "metric_debug": metric_specs,
        "first_detected_iteration": max(1, int(iteration or 1)),
        "last_seen_iteration": max(1, int(iteration or 1)),
        "verifier_status": "not_resolved",
      }
    )
  ]


def _p_and_l_flatline_signals(finmo_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  rows_by_q = _dep("_finmo_quarter_row_map")(finmo_json)
  quarters = sorted(rows_by_q)
  if len(quarters) < 8:
    return []
  fields = ["revenue", "cogs", "gross_profit", "ebitda", "net_income"]
  series = {
    field: [
      float(_safe_float((rows_by_q.get(quarter) or {}).get(field)) or 0.0)
      for quarter in quarters
    ]
    for field in fields
  }
  revenue_values = series.get("revenue") or []
  average_revenue = sum(max(0.0, value) for value in revenue_values) / max(len(revenue_values), 1)
  if average_revenue <= 1000.0:
    return []
  flat_runs = {
    field: _dep("_series_longest_flat_run")(values)
    for field, values in series.items()
  }
  live_count = len(quarters)
  revenue_flat = flat_runs["revenue"]
  companion_flat_fields = [
    field for field in ("cogs", "gross_profit", "ebitda", "net_income")
    if int(flat_runs.get(field, {}).get("length") or 0) >= int(revenue_flat.get("length") or 0) - 1
  ]
  full_horizon_flat = int(revenue_flat.get("length") or 0) >= live_count and bool(companion_flat_fields)
  late_plateau = (
    int(revenue_flat.get("length") or 0) >= 10
    and int(revenue_flat.get("start_quarter") or 99) >= 8
    and bool(companion_flat_fields)
  )
  if not full_horizon_flat and not late_plateau:
    return []
  reason = "p_and_l_full_horizon_flatline" if full_horizon_flat else "p_and_l_late_horizon_plateau"
  start_q = int(revenue_flat.get("start_quarter") or 1)
  end_q = int(revenue_flat.get("end_quarter") or live_count)
  signal_quarters = list(range(max(1, start_q), min(live_count, end_q) + 1))
  return [
    {
      "issue_code": "p_and_l_flatline",
      "signal_reason": reason,
      "problem_quarters": signal_quarters,
      "flat_runs": copy.deepcopy(flat_runs),
      "flat_fields": [
        field for field in fields
        if int(flat_runs.get(field, {}).get("length") or 0) >= (live_count if full_horizon_flat else 10)
      ],
      "average_revenue": int(round(average_revenue)),
      "first_revenue": int(round(float(revenue_values[0] if revenue_values else 0.0))),
      "last_revenue": int(round(float(revenue_values[-1] if revenue_values else 0.0))),
    }
  ]


def _build_p_and_l_flatline_issue_status_records(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  iteration: int,
) -> List[Dict[str, Any]]:
  signals = _p_and_l_flatline_signals(finmo_json)
  if not signals:
    return []
  allowed_levers = _dep("_operating_trajectory_allowed_levers")(model_input_json)
  if not allowed_levers:
    raise RuntimeError(
      "p_and_l_flatline_mapping_failed: flatline issue fired but no table-backed revenue or cost levers are available."
    )
  problem_quarters = sorted(
    {
      int(q)
      for signal in signals
      for q in (signal.get("problem_quarters") or [])
      if int(_safe_float(q) or 0) >= 1
    }
  )
  rows_by_q = _dep("_finmo_quarter_row_map")(finmo_json)
  metric_specs: List[Dict[str, Any]] = []
  baseline_revenue = max(
    1.0,
    float(
      _safe_float(next((signal.get("last_revenue") for signal in signals if _safe_float(signal.get("last_revenue")) is not None), None))
      or _safe_float(next((signal.get("average_revenue") for signal in signals if _safe_float(signal.get("average_revenue")) is not None), None))
      or 1.0
    ),
  )
  for index, quarter_index in enumerate(problem_quarters, start=1):
    row = rows_by_q.get(int(quarter_index)) or {}
    actual_revenue = max(0.0, float(_safe_float(row.get("revenue")) or baseline_revenue))
    target_floor = max(1.0, baseline_revenue * (1.0 + (0.01 * index)))
    if target_floor <= actual_revenue:
      target_floor = actual_revenue * 1.01
    spec = _dep("_table_target_currency_metric_spec")(
      "revenue",
      actual_value=actual_revenue,
      target_floor=target_floor,
      score_scale=max(1000.0, baseline_revenue * 0.05),
      source_metric_names=["revenue", "capacity", "utilization", "unit_price"],
      metric_definition=(
        "The forecast P&L cannot be a copied flatline. Use direct mapped revenue drivers and cost drivers "
        "to create a realistic quarter-by-quarter operating trajectory across the remaining horizon."
      ),
    )
    if isinstance(spec, dict):
      spec["quarter_index"] = int(quarter_index)
      spec["flatline_trajectory_target_index"] = index
      spec["flatline_target_basis"] = "minimum_one_percent_step_from_baseline_revenue"
      metric_specs.append(spec)
  return [
    _dep("_normalize_issue_record_to_controller_truth")(
      {
        "issue": "p_and_l_flatline",
        "issue_code": "p_and_l_flatline",
        "detail": (
          "P&L trajectory is flat or plateaued across too much of the live forecast. "
          f"problem_quarters={problem_quarters}; reasons={[signal.get('signal_reason') for signal in signals]}."
        ),
        "verifier_status": "not_resolved",
        "remaining_issue_materiality": "material",
        "remaining_issue_severity_score": 95,
        "remaining_problem_quarters": problem_quarters,
        "next_required_lever_ids": allowed_levers,
        "metric_debug": metric_specs,
        "flatline_failure_signals": copy.deepcopy(signals),
        "first_detected_iteration": max(1, int(iteration or 1)),
        "last_seen_iteration": max(1, int(iteration or 1)),
      }
    )
  ]


def _build_stage_maturity_cost_structure_issue_status_records(
  *,
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage_ramp_contract: Optional[Dict[str, Any]],
  iteration: int,
) -> List[Dict[str, Any]]:
  contract = stage_ramp_contract if isinstance(stage_ramp_contract, dict) else {}
  r_and_d_enabled = _dep("_r_and_d_enabled_from_model_input")(model_input_json)
  ramp_rows = {
    int(_safe_float(row.get("quarter_index")) or 0): row
    for row in (contract.get("quarter_ramp_grid") or [])
    if isinstance(row, dict) and int(_safe_float(row.get("quarter_index")) or 0) >= 1
  }
  rows_by_q = _dep("_finmo_quarter_row_map")(finmo_json)
  if not ramp_rows or not rows_by_q:
    return []
  allowed_levers = post_intake_issue_candidate_lever_ids(
    "cost_structure_mismatch",
    phase="convergence",
  )
  if not r_and_d_enabled:
    rd_lever = str(_dep("R_AND_D_APPLICABILITY_LEVER_ID") or "").strip()
    allowed_levers = [lever_id for lever_id in allowed_levers if str(lever_id or "").strip() != rd_lever]
  if not allowed_levers:
    raise RuntimeError(
      "stage_maturity_cost_structure_mapping_failed: cost_structure_mismatch fired but no table-backed cost levers are available."
    )
  component_specs = [
    ("cogs", "cogs", "cogs_percent_of_revenue_target", "cogs_percent_of_revenue_max"),
    ("marketing", "marketing", None, "marketing_percent_of_revenue_max"),
    ("lease_rent", "lease_rent", None, "lease_percent_of_revenue_max"),
    ("g_and_a", "g_and_a", None, "g_and_a_percent_of_revenue_max"),
  ]
  if r_and_d_enabled:
    component_specs.insert(2, ("research_and_development", "research_and_development", None, "rd_percent_of_revenue_max"))
  metric_specs: List[Dict[str, Any]] = []
  problem_quarters: List[int] = []
  for quarter_index in range(1, _contract_forecast_quarter_count() + 1):
    quarter_row = rows_by_q.get(quarter_index) or {}
    ramp_row = ramp_rows.get(quarter_index) or {}
    revenue = float(_safe_float(quarter_row.get("revenue")) or 0.0)
    floor_margin = _safe_float(ramp_row.get("net_income_margin_floor"))
    if revenue <= 0.0 or floor_margin is None:
      continue
    net_income = float(_safe_float(quarter_row.get("net_income")) or 0.0)
    actual_margin = net_income / revenue
    margin_gap = float(floor_margin) - actual_margin
    direct_cost_values = {
      "cogs": float(_dep("_quarter_row_cost_of_goods_sold")(quarter_row) or 0.0),
      "marketing": float(_safe_float(quarter_row.get("marketing")) or 0.0),
      "lease_rent": float(_safe_float(quarter_row.get("lease_rent")) or 0.0),
      "g_and_a": float(_safe_float(quarter_row.get("g_and_a")) or 0.0),
    }
    if r_and_d_enabled:
      direct_cost_values["research_and_development"] = float(_safe_float(quarter_row.get("research_and_development")) or 0.0)
    elif abs(float(_safe_float(quarter_row.get("research_and_development")) or 0.0)) > 1.0:
      raise RuntimeError(
        "r_and_d_disabled_cost_structure_finmo_leakage: "
        + json.dumps(
          {
            "quarter_index": quarter_index,
            "research_and_development": quarter_row.get("research_and_development"),
          },
          ensure_ascii=False,
        )
      )
    cap_violations: List[str] = []
    for metric_name, _, _, cap_field in component_specs:
      cap_ratio = _safe_float(ramp_row.get(cap_field))
      if cap_ratio is None:
        continue
      if direct_cost_values.get(metric_name, 0.0) > (revenue * float(cap_ratio)) + 1.0:
        cap_violations.append(metric_name)
    if margin_gap <= 0.0001 and not cap_violations:
      continue
    problem_quarters.append(quarter_index)
    margin_gap_dollars = max(0.0, margin_gap * revenue)
    positive_cost_pool = sum(max(0.0, value) for value in direct_cost_values.values()) or 1.0
    for metric_name, row_field, target_field, cap_field in component_specs:
      actual_value = max(0.0, direct_cost_values.get(metric_name, 0.0))
      if actual_value <= 0.0:
        continue
      cap_ratio = _safe_float(ramp_row.get(cap_field))
      cap_value = revenue * float(cap_ratio) if cap_ratio is not None else actual_value
      allocated_reduction = margin_gap_dollars * (actual_value / positive_cost_pool)
      target_ceiling = min(actual_value, cap_value, max(0.0, actual_value - allocated_reduction))
      target_ratio = _safe_float(ramp_row.get(target_field)) if target_field else None
      if target_ratio is not None:
        target_ceiling = min(target_ceiling, max(0.0, revenue * float(target_ratio)))
      spec = _dep("_table_target_currency_metric_spec")(
        metric_name,
        actual_value=actual_value,
        target_floor=0.0,
        target_ceiling=target_ceiling,
        score_scale=max(revenue * 0.03, abs(actual_value - target_ceiling), 1000.0),
        source_metric_names=[row_field, "revenue", "net_income", "stage_maturity_contract"],
        metric_definition=(
          "Stage maturity net-income guardrails are detected from the GPT-selected maturity grid, "
          "but repair targets only direct table-backed operating cost rows."
        ),
      )
      if isinstance(spec, dict):
        spec["quarter_index"] = int(quarter_index)
        spec["stage_maturity_floor_margin"] = round(float(floor_margin), 2)
        spec["actual_net_income_margin"] = round(float(actual_margin), 4)
        metric_specs.append(spec)
  if not problem_quarters or not metric_specs:
    return []
  return [
    _dep("_normalize_issue_record_to_controller_truth")(
      {
        "issue": "cost_structure_mismatch",
        "issue_code": "cost_structure_mismatch",
        "detail": (
          "Stage maturity profitability guardrail failed. Direct operating costs must be adjusted "
          "through table-backed cost_structure_mismatch levers so the business matures naturally."
        ),
        "candidate_kind": "stage_maturity_cost_structure_detector",
        "remaining_problem_quarters": sorted(set(problem_quarters)),
        "remaining_issue_materiality": "material",
        "remaining_issue_severity_score": 92,
        "next_required_lever_ids": copy.deepcopy(allowed_levers),
        "metric_debug": metric_specs,
        "first_detected_iteration": max(1, int(iteration or 1)),
        "last_seen_iteration": max(1, int(iteration or 1)),
        "verifier_status": "not_resolved",
      }
    )
  ]


__all__ = [
  "bind_runtime_dependencies",
  "_cost_structure_direct_metric_specs_for_quarter",
  "_issue_metric_specs_for_quarter",
  "_raise_p_and_l_flatline_if_needed",
  "_build_capacity_support_issue_status_records",
  "_p_and_l_flatline_signals",
  "_build_p_and_l_flatline_issue_status_records",
  "_build_stage_maturity_cost_structure_issue_status_records",
]
