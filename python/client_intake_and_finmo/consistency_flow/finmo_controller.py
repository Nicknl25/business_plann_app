from __future__ import annotations

import os
import shutil
import tempfile
import traceback
from typing import Any, Dict, List, Sequence

from consistency_financials import build_consistency_financial_summary  # type: ignore

from .common import (
  _clone,
  _normalize_ratio,
  _presentation_issues,
  _safe_float,
  _safe_int,
  _unique_strings,
)


def _revenue_lever_id(lob_name: str, product_name: str, driver: str) -> str:
  return "::".join(["revenue", str(lob_name or "").strip(), str(product_name or "").strip(), str(driver or "").strip()])


def _simple_lever_id(section: str, label: str) -> str:
  return "::".join([str(section or "").strip(), str(label or "").strip()])


def _ratio(total: Any, revenue: Any) -> float:
  revenue_value = max(0.0, _safe_float(revenue))
  if revenue_value <= 0:
    return 0.0
  return max(0.0, _safe_float(total)) / revenue_value


def _policy_period_groups(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
  groups: List[Dict[str, Any]] = []
  allowed_levers = {
    str(item or "").strip()
    for item in (profile.get("allowed_model_input_levers") or [])
    if str(item or "").strip()
  }
  for item in (profile.get("governed_period_groups") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    raw_granularity = str(item.get("input_granularity") or "").strip().lower()
    input_granularity = raw_granularity if raw_granularity in {"grouped", "quarterly"} else "grouped"
    quarterly_expansion_levers = [
      str(lever_id or "").strip()
      for lever_id in (item.get("quarterly_expansion_levers") or [])
      if str(lever_id or "").strip() in allowed_levers
    ]
    groups.append(
      {
        "quarter_start": start,
        "quarter_end": min(20, end),
        "input_granularity": input_granularity,
        "quarterly_expansion_levers": quarterly_expansion_levers,
      }
    )
  return groups


def _profile_lever_summary(profile: Dict[str, Any]) -> Dict[str, Any]:
  families: List[str] = []
  for item in (profile.get("lever_adjustment_plan") or []):
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if lever_id.endswith("::Unit Price"):
      families.append("price")
    elif lever_id.endswith("::Utilization"):
      families.append("utilization")
    elif lever_id.endswith("::Capacity"):
      families.append("capacity")
    elif lever_id == _simple_lever_id("expenses", "Marketing"):
      families.append("marketing")
    elif lever_id == _simple_lever_id("expenses", "Payroll"):
      families.append("payroll")
    elif lever_id == _simple_lever_id("expenses", "General & Administrative"):
      families.append("other_opex")
    elif lever_id == _simple_lever_id("expenses", "Cost of Goods Sold"):
      families.append("cogs")
  families = list(dict.fromkeys(families))
  revenue_side = any(item in {"price", "utilization", "capacity"} for item in families)
  cost_side = any(item in {"marketing", "payroll", "other_opex", "cogs"} for item in families)
  coordination_issues: List[str] = []
  if revenue_side and not cost_side:
    coordination_issues.append("revenue_without_cost_support")
  if cost_side and not revenue_side:
    coordination_issues.append("cost_without_revenue_support")
  return {
    "meaningful_families": families,
    "meaningful_lever_count": len(families),
    "raw_family_moves": {family: 0.1 for family in families},
    "dominant_family": families[0] if families else "",
    "dominant_family_share": round((1.0 / max(1, len(families))) if families else 0.0, 6),
    "aligned_pair_count": 1 if (revenue_side and cost_side) else 0,
    "coordination_issues": coordination_issues,
    "changed_products": 0,
    "moved_product_keys": [],
    "coordination_score": round(float(len(families)) + (0.75 if (revenue_side and cost_side) else 0.0) - (0.75 * len(coordination_issues)), 4),
  }


def _profile_label_and_rationale(profile: Dict[str, Any]) -> tuple[str, str]:
  strategy_name = str(profile.get("strategy_name") or "Governed strategy").strip() or "Governed strategy"
  rationale = str(profile.get("dominant_tradeoff") or "").strip() or "Applies GPT-governed workbook levers to produce a believable viable operating path."
  return strategy_name, rationale


def _lever_band_for_quarter(
  *,
  profile: Dict[str, Any],
  lever_id: str,
  quarter_index: int,
) -> Dict[str, float | None]:
  min_value: float | None = None
  max_value: float | None = None
  direction = "hold"
  for item in (profile.get("lever_adjustment_plan") or []):
    if not isinstance(item, dict):
      continue
    if str(item.get("lever_id") or "").strip() != lever_id:
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    if quarter_index < start or quarter_index > end:
      continue
    direction = str(item.get("direction") or "").strip().lower() or direction
    raw_min = item.get("min_value")
    raw_max = item.get("max_value")
    item_min = None if raw_min in {None, ""} else _safe_float(raw_min)
    item_max = None if raw_max in {None, ""} else _safe_float(raw_max)
    if item_min is not None:
      min_value = item_min if min_value is None else max(min_value, item_min)
    if item_max is not None:
      max_value = item_max if max_value is None else min(max_value, item_max)
  return {"min": min_value, "max": max_value, "direction": direction}


def _pick_banded_value(
  *,
  current_value: float,
  min_value: float | None,
  max_value: float | None,
  direction: str,
) -> float:
  if min_value is None and max_value is None:
    return current_value
  if direction == "up":
    return max_value if max_value is not None else max(current_value, min_value or current_value)
  if direction == "down":
    return min_value if min_value is not None else min(current_value, max_value or current_value)
  if min_value is not None and max_value is not None:
    return (min_value + max_value) / 2.0
  return min_value if min_value is not None else max_value if max_value is not None else current_value


def _build_controller_input_seed_from_profile(
  *,
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  baseline_state: Dict[str, Any],
) -> List[Dict[str, Any]]:
  product_basis = [item for item in (direct_inputs.get("product_driver_basis") or []) if isinstance(item, dict)]
  lever_catalog = _model_input_lever_catalog_from_direct_inputs(direct_inputs)
  revenue_slot_details = _revenue_slot_details_from_catalog(lever_catalog)
  slot_by_names = {
    (str(item.get("lob") or "").strip(), str(item.get("product") or "").strip()): item
    for item in revenue_slot_details
    if str(item.get("lob") or "").strip() and str(item.get("product") or "").strip()
  }
  financials_json = (baseline_state.get("financials_json") or {}) if isinstance(baseline_state.get("financials_json"), dict) else {}
  people_json = (baseline_state.get("people_json") or {}) if isinstance(baseline_state.get("people_json"), dict) else {}
  marketing_model_json = (baseline_state.get("marketing_model_json") or {}) if isinstance(baseline_state.get("marketing_model_json"), dict) else {}
  year1_revenue = max(
    0.0,
    _safe_float((baseline_state.get("financials_year1_json") or {}).get("company_revenue_total_year1"))
    or _safe_float(financials_json.get("current_revenue"))
    or sum(max(0.0, _safe_float(item.get("annual_revenue"))) for item in product_basis),
  )
  cogs_ratio_baseline = _ratio(financials_json.get("cogs_total_year1"), year1_revenue)
  marketing_ratio_baseline = _normalize_ratio(marketing_model_json.get("marketing_percent_of_revenue"))
  if marketing_ratio_baseline is None:
    marketing_ratio_baseline = _normalize_ratio(financials_json.get("marketing_percent_of_revenue")) or 0.0
  payroll_total_year1 = (
    _safe_float(financials_json.get("payroll_total_year1"))
    or _safe_float(financials_json.get("current_payroll"))
    or 0.0
  )
  if payroll_total_year1 <= 0:
    payroll_total_year1 = sum(
      max(0.0, _safe_float(item.get("annual_wage")) or 0.0)
      for item in (people_json.get("people") or [])
      if isinstance(item, dict)
    )
  g_and_a_ratio_baseline = _ratio(
    max(
      0.0,
      (
        _safe_float(financials_json.get("other_opex_absolute"))
        or _safe_float(financials_json.get("other_operating_expense"))
        or 0.0
      ) - ((_safe_float(financials_json.get("monthly_rent_expense")) or 0.0) * 12.0)
    ),
    year1_revenue,
  )
  lease_amount = round(max(0.0, _safe_float(financials_json.get("monthly_rent_expense"))) * 3.0, 6)
  interest_rate = round(_ratio(financials_json.get("annual_interest_payment"), financials_json.get("total_debt_outstanding")), 6)
  depreciation_percent = round(_ratio(financials_json.get("accumulated_depreciation"), year1_revenue), 6)
  tax_percent = round(_normalize_ratio(financials_json.get("annual_tax_rate")) or _normalize_ratio(financials_json.get("taxes_percent")) or 0.0, 6)
  slots: List[Dict[str, Any]] = []
  for quarter_index in range(1, 21):
    revenue_lobs: Dict[str, List[Dict[str, Any]]] = {}
    quarter_revenue = 0.0
    for basis_index, basis in enumerate(product_basis):
      basis_lob_name = str(basis.get("lob_name") or "").strip() or "LOB 1"
      basis_product_name = str(basis.get("product_name") or "").strip() or "Product 1"
      slot_detail = slot_by_names.get((basis_lob_name, basis_product_name))
      if slot_detail is None and len(product_basis) == 1 and revenue_slot_details:
        slot_detail = revenue_slot_details[0]
      elif slot_detail is None and basis_index < len(revenue_slot_details):
        slot_detail = revenue_slot_details[basis_index]
      lob_name = str((slot_detail or {}).get("lob") or basis_lob_name).strip() or "LOB 1"
      product_name = str((slot_detail or {}).get("product") or basis_product_name).strip() or "Product 1"
      revenue_slot_key = str((slot_detail or {}).get("revenue_slot_key") or "").strip()
      base_capacity = max(0.0, _safe_float(basis.get("annual_capacity_units")) / 4.0)
      base_price = max(0.0, _safe_float(basis.get("unit_price")))
      base_util = _normalize_ratio(basis.get("utilization_rate")) or 0.0
      capacity_band = _lever_band_for_quarter(profile=profile, lever_id=_revenue_lever_id(lob_name, product_name, "Capacity"), quarter_index=quarter_index)
      price_band = _lever_band_for_quarter(profile=profile, lever_id=_revenue_lever_id(lob_name, product_name, "Unit Price"), quarter_index=quarter_index)
      utilization_band = _lever_band_for_quarter(profile=profile, lever_id=_revenue_lever_id(lob_name, product_name, "Utilization"), quarter_index=quarter_index)
      capacity = _pick_banded_value(current_value=base_capacity, min_value=capacity_band.get("min"), max_value=capacity_band.get("max"), direction=str(capacity_band.get("direction") or "hold"))
      price = _pick_banded_value(current_value=base_price, min_value=price_band.get("min"), max_value=price_band.get("max"), direction=str(price_band.get("direction") or "hold"))
      utilization = _pick_banded_value(current_value=base_util, min_value=utilization_band.get("min"), max_value=utilization_band.get("max"), direction=str(utilization_band.get("direction") or "hold"))
      units = max(0.0, capacity * max(0.0, utilization))
      quarter_revenue += units * max(0.0, price)
      revenue_lobs.setdefault(lob_name, []).append(
        {
          "product_name": product_name,
          "revenue_slot_key": revenue_slot_key,
          "capacity_units": round(capacity, 6),
          "utilization": round(utilization, 6),
          "units": round(units, 6),
          "price": round(price, 6),
        }
      )
    revenue_products = [{"lob_name": lob_name, "products": products} for lob_name, products in revenue_lobs.items()]
    cogs_band = _lever_band_for_quarter(profile=profile, lever_id=_simple_lever_id("expenses", "Cost of Goods Sold"), quarter_index=quarter_index)
    marketing_band = _lever_band_for_quarter(profile=profile, lever_id=_simple_lever_id("expenses", "Marketing"), quarter_index=quarter_index)
    payroll_band = _lever_band_for_quarter(profile=profile, lever_id=_simple_lever_id("expenses", "Payroll"), quarter_index=quarter_index)
    ganda_band = _lever_band_for_quarter(profile=profile, lever_id=_simple_lever_id("expenses", "General & Administrative"), quarter_index=quarter_index)
    slots.append(
      {
        "quarter_index": quarter_index,
        "revenue_products": revenue_products,
        "revenue": round(quarter_revenue, 6),
        "cogs_percent": round(_pick_banded_value(current_value=cogs_ratio_baseline, min_value=cogs_band.get("min"), max_value=cogs_band.get("max"), direction=str(cogs_band.get("direction") or "hold")), 6),
        "marketing_percent": round(_pick_banded_value(current_value=marketing_ratio_baseline or 0.0, min_value=marketing_band.get("min"), max_value=marketing_band.get("max"), direction=str(marketing_band.get("direction") or "hold")), 6),
        "r_and_d_percent": 0.0,
        "lease_amount": lease_amount,
        "payroll_amount": round(_pick_banded_value(current_value=max(0.0, payroll_total_year1) / 4.0, min_value=payroll_band.get("min"), max_value=payroll_band.get("max"), direction=str(payroll_band.get("direction") or "hold")), 6),
        "g_and_a_percent": round(_pick_banded_value(current_value=g_and_a_ratio_baseline, min_value=ganda_band.get("min"), max_value=ganda_band.get("max"), direction=str(ganda_band.get("direction") or "hold")), 6),
        "interest_rate": interest_rate,
        "depreciation_percent": depreciation_percent,
        "tax_percent": tax_percent,
        "working_capital": {},
        "capex": 0.0,
      }
    )
  return slots


def _banded_input_spec(
  *,
  spec: Dict[str, Any],
  min_value: float | None,
  max_value: float | None,
) -> Dict[str, Any]:
  next_spec = _clone(spec)
  next_spec["band"] = {
    "min": None if min_value is None else round(min_value, 6),
    "max": None if max_value is None else round(max_value, 6),
  }
  return next_spec


def _allowed_model_input_levers(
  *,
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
) -> List[str]:
  del direct_inputs
  return _unique_strings(profile.get("allowed_model_input_levers") or [])


def _model_input_lever_catalog_from_direct_inputs(direct_inputs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  model_input_json = (direct_inputs.get("model_input_json") or {}) if isinstance(direct_inputs.get("model_input_json"), dict) else {}
  catalog = (model_input_json.get("lever_catalog") or {}) if isinstance(model_input_json.get("lever_catalog"), dict) else {}
  return {
    str(key): _clone(value) for key, value in catalog.items()
    if str(key or "").strip() and isinstance(value, dict)
  }


def _revenue_slot_details_from_catalog(lever_catalog: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
  slot_details: Dict[str, Dict[str, Any]] = {}
  for meta in lever_catalog.values():
    if not isinstance(meta, dict):
      continue
    if str(meta.get("section") or "").strip() != "revenue":
      continue
    revenue_slot_key = str(meta.get("revenue_slot_key") or "").strip()
    if not revenue_slot_key:
      continue
    existing = slot_details.get(revenue_slot_key) or {}
    slot_details[revenue_slot_key] = {
      **existing,
      **{
        "revenue_slot_key": revenue_slot_key,
        "lob": str(meta.get("lob") or existing.get("lob") or "").strip(),
        "product": str(meta.get("product") or existing.get("product") or "").strip(),
        "lob_slot_index": _safe_int(meta.get("lob_slot_index")) if meta.get("lob_slot_index") is not None else existing.get("lob_slot_index"),
        "product_slot_index": _safe_int(meta.get("product_slot_index")) if meta.get("product_slot_index") is not None else existing.get("product_slot_index"),
      },
    }
  return sorted(
    [value for value in slot_details.values() if isinstance(value, dict)],
    key=lambda item: (
      _safe_int(item.get("lob_slot_index")) or 0,
      _safe_int(item.get("product_slot_index")) or 0,
      str(item.get("revenue_slot_key") or "").strip(),
    ),
  )


def _optional_float(value: Any) -> float | None:
  return None if value in {None, ""} else _safe_float(value)


def _group_output_targets(
  *,
  profile: Dict[str, Any],
  quarter_start: int,
  quarter_end: int,
) -> List[Dict[str, Any]]:
  targets: List[Dict[str, Any]] = []
  for item in (profile.get("controlled_output_targets") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    overlap_start = max(start, quarter_start)
    overlap_end = min(end, quarter_end)
    if overlap_start > overlap_end:
      continue
    targets.append(
      {
        "line_item": str(item.get("line_item") or "").strip(),
        "quarter_start": overlap_start,
        "quarter_end": overlap_end,
        "min_value": _safe_float(item.get("min_value")),
        "max_value": _safe_float(item.get("max_value")),
        "rationale": str(item.get("rationale") or "").strip(),
      }
    )
  return targets


def _calibration_variable_specs(
  *,
  profile: Dict[str, Any],
  allowed_model_input_levers: Sequence[str],
  lever_catalog: Dict[str, Dict[str, Any]],
  quarter_index: int,
  group_key: str | None = None,
  grouping_mode: str = "quarterly",
) -> List[Dict[str, Any]]:
  specs: List[Dict[str, Any]] = []
  allowed_set = {
    str(item or "").strip()
    for item in (allowed_model_input_levers or [])
    if str(item or "").strip()
  }
  for lever_id in sorted(allowed_set):
    metadata = lever_catalog.get(lever_id)
    if not isinstance(metadata, dict) or not metadata:
      continue
    if str(metadata.get("driver") or "").strip() == "Unit Price":
      continue
    valid_quarters = [int(item) for item in (metadata.get("valid_quarter_indices") or []) if _safe_int(item) > 0]
    if valid_quarters and quarter_index not in valid_quarters:
      continue
    section = str(metadata.get("section") or "").strip()
    if not section:
      continue
    band = _lever_band_for_quarter(profile=profile, lever_id=lever_id, quarter_index=quarter_index)
    spec: Dict[str, Any] = {
      "section": section,
      "lever_id": lever_id,
      "quarter_index": quarter_index,
      "named_range": str(metadata.get("named_range") or "").strip(),
      "value_kind": str(metadata.get("value_kind") or "").strip(),
      "input_semantics": str(metadata.get("input_semantics") or "").strip(),
      "grouping_mode": grouping_mode,
    }
    if group_key:
      spec["group_key"] = group_key
    if section == "revenue":
      spec.update(
        {
          "lob": str(metadata.get("lob") or "").strip(),
          "product": str(metadata.get("product") or "").strip(),
          "driver": str(metadata.get("driver") or "").strip(),
        }
      )
    else:
      spec["label"] = str(metadata.get("label") or "").strip()
    specs.append(_banded_input_spec(spec=spec, min_value=_optional_float(band.get("min")), max_value=_optional_float(band.get("max"))))
  return specs


def _group_expansion_permissions(group: Dict[str, Any]) -> tuple[str, set[str]]:
  raw_granularity = str(group.get("input_granularity") or "").strip().lower()
  input_granularity = raw_granularity if raw_granularity in {"grouped", "quarterly"} else "grouped"
  quarterly_expansion_levers = {
    str(item or "").strip()
    for item in (group.get("quarterly_expansion_levers") or [])
    if str(item or "").strip()
  }
  return input_granularity, quarterly_expansion_levers


def _build_finmo_calibration_spec(
  *,
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  controller_input_seed: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
  allowed_model_input_levers = _allowed_model_input_levers(profile=profile, direct_inputs=direct_inputs)
  lever_catalog = _model_input_lever_catalog_from_direct_inputs(direct_inputs)
  solver_requests: List[Dict[str, Any]] = []
  governed_period_groups = _policy_period_groups(profile)
  allowed_model_input_levers = [
    lever_id for lever_id in allowed_model_input_levers
    if isinstance(lever_catalog.get(lever_id), dict) and lever_catalog.get(lever_id)
  ]
  for group_index, group in enumerate(governed_period_groups, start=1):
    quarter_start = max(1, _safe_int(group.get("quarter_start")) or 1)
    quarter_end = max(quarter_start, _safe_int(group.get("quarter_end")) or quarter_start)
    final_quarter = quarter_end
    input_granularity, quarterly_expansion_levers = _group_expansion_permissions(group)
    group_targets = _group_output_targets(profile=profile, quarter_start=quarter_start, quarter_end=quarter_end)
    objective_spec: Dict[str, Any] | None = None
    band_constraints: List[Dict[str, Any]] = []
    for target in group_targets:
      for quarter_index in range(max(quarter_start, _safe_int(target.get("quarter_start")) or quarter_start), min(quarter_end, _safe_int(target.get("quarter_end")) or quarter_end) + 1):
        band_constraints.append(
          {
            "target": {
              "sheet_range": "finmo_pl",
              "line_item": str(target.get("line_item") or "").strip(),
              "quarter_index": quarter_index,
            },
            "goal_band": {
              "min": _safe_float(target.get("min_value")),
              "max": _safe_float(target.get("max_value")),
            },
          }
        )
        if objective_spec is None and quarter_index == final_quarter:
          objective_spec = {
            "sheet_range": "finmo_pl",
            "line_item": str(target.get("line_item") or "").strip(),
            "quarter_index": quarter_index,
            "goal_band": {
              "min": _safe_float(target.get("min_value")),
              "max": _safe_float(target.get("max_value")),
            },
            "objective_mode": "maximize",
          }
    if objective_spec is None:
      continue
    changing_inputs: List[Dict[str, Any]] = []
    for lever_id in allowed_model_input_levers:
      lever_metadata = lever_catalog.get(lever_id)
      if not isinstance(lever_metadata, dict) or not lever_metadata:
        continue
      lever_group_mode = "quarterly" if (input_granularity == "quarterly" or lever_id in quarterly_expansion_levers) else "grouped"
      for quarter_index in range(quarter_start, quarter_end + 1):
        changing_inputs.extend(
          _calibration_variable_specs(
            profile=profile,
            allowed_model_input_levers=[lever_id],
            lever_catalog=lever_catalog,
            quarter_index=quarter_index,
            grouping_mode=lever_group_mode,
            group_key=(f"group_{group_index}::{lever_id}" if lever_group_mode == "grouped" else None),
          )
        )
    solver_requests.append(
      {
        "request_id": f"solver_group_{group_index}_q{quarter_start}_q{quarter_end}",
        "objective": objective_spec,
        "changing_inputs": changing_inputs,
        "band_constraints": band_constraints,
        "constraints": [],
        "group_execution": {
          "input_granularity": input_granularity,
          "quarterly_expansion_levers": sorted(quarterly_expansion_levers),
        },
        "mode": "excel_solver_shell",
      }
    )
  active_levers = sorted(
    {
      str(item.get("lever_id") or "").strip()
      for request in solver_requests
      for item in (request.get("changing_inputs") or [])
      if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
    }
  ) or allowed_model_input_levers
  return {
    "contract_version": "finmo_calibration_shell_v1",
    "canonical_lever_vocabulary": "model_inputs_controller_write_only",
    "goal_seek_requests": [],
    "solver_requests": solver_requests,
    "governed_period_groups": governed_period_groups,
    "allowed_model_input_levers": active_levers,
    "allowed_model_input_lever_details": [
      _clone(lever_catalog.get(lever_id) or {})
      for lever_id in active_levers
      if str(lever_id or "").strip() and isinstance(lever_catalog.get(lever_id), dict) and lever_catalog.get(lever_id)
    ],
  }


def _candidate_failure_result(
  *,
  failure_stage: str,
  source_finmo_path: str,
  temp_path: str,
  controller_input_seed: Sequence[Dict[str, Any]],
  calibration_request: Dict[str, Any],
  error: Exception | None = None,
  detail: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
  failure_payload: Dict[str, Any] = {
    "contract_version": "finmo_candidate_failure_v1",
    "failure_stage": str(failure_stage or "").strip() or "unknown_failure",
    "source_finmo_path": str(source_finmo_path or "").strip(),
    "temp_finmo_path": str(temp_path or "").strip(),
    "controller_input_seed_count": len([item for item in controller_input_seed if isinstance(item, dict)]),
    "allowed_model_input_levers": _clone(calibration_request.get("allowed_model_input_levers") or []),
    "solver_request_count": len([item for item in (calibration_request.get("solver_requests") or []) if isinstance(item, dict)]),
    "goal_seek_request_count": len([item for item in (calibration_request.get("goal_seek_requests") or []) if isinstance(item, dict)]),
  }
  if isinstance(detail, dict) and detail:
    failure_payload["detail"] = _clone(detail)
  if error is not None:
    failure_payload["error_type"] = type(error).__name__
    failure_payload["error_message"] = str(error)
    failure_payload["traceback"] = traceback.format_exc()
  try:
    try:
      from consistency_trace import trace_lazy  # type: ignore
    except Exception:
      from client_intake_and_finmo.consistency_trace import trace_lazy  # type: ignore
    trace_lazy(
      "FINMO_CANDIDATE_FAILURE",
      "Finmo candidate build failure",
      lambda: _clone(failure_payload),
    )
  except Exception:
    pass
  return {"candidate_failure": failure_payload}


def _candidate_finmo_readback(
  *,
  state_model: Dict[str, Any],
  modified_state: Dict[str, Any],
  controller_input_seed: Sequence[Dict[str, Any]],
  calibration_request: Dict[str, Any],
) -> Dict[str, Any]:
  fixed_facts = (state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}
  source_finmo_path = str(fixed_facts.get("finmo_path") or "").strip()
  if not source_finmo_path or not os.path.exists(source_finmo_path):
    return _candidate_failure_result(
      failure_stage="missing_source_finmo_path",
      source_finmo_path=source_finmo_path,
      temp_path="",
      controller_input_seed=controller_input_seed,
      calibration_request=calibration_request,
      detail={"source_finmo_exists": bool(source_finmo_path and os.path.exists(source_finmo_path))},
    )
  temp_handle = tempfile.NamedTemporaryFile(prefix="consistency_candidate_", suffix=".xlsx", delete=False)
  temp_handle.close()
  temp_path = temp_handle.name
  try:
    shutil.copyfile(source_finmo_path, temp_path)
    try:
      from finmo_bridge import build_consistency_forecast_view_from_finmo, sync_consistency_state_to_finmo  # type: ignore
    except Exception:
      from client_intake_and_finmo.finmo_bridge import build_consistency_forecast_view_from_finmo, sync_consistency_state_to_finmo  # type: ignore
    result = sync_consistency_state_to_finmo(
      finmo_path=temp_path,
      business_facts=(fixed_facts.get("business_facts") if isinstance(fixed_facts.get("business_facts"), dict) else {}),
      ops_json=(modified_state.get("ops_json") if isinstance(modified_state.get("ops_json"), dict) else {}),
      people_json=(modified_state.get("people_json") if isinstance(modified_state.get("people_json"), dict) else {}),
      financials_json=(modified_state.get("financials_json") if isinstance(modified_state.get("financials_json"), dict) else {}),
      financials_year1_json=(modified_state.get("financials_year1_json") if isinstance(modified_state.get("financials_year1_json"), dict) else {}),
      marketing_model_json=(modified_state.get("marketing_model_json") if isinstance(modified_state.get("marketing_model_json"), dict) else {}),
      controller_input_seed=controller_input_seed,
      forecast_quarters=[],
      calibration_spec=calibration_request,
    )
    finmo_json = (result.get("finmo_json") or {}) if isinstance(result.get("finmo_json"), dict) else {}
    if not finmo_json:
      return _candidate_failure_result(
        failure_stage="empty_finmo_json",
        source_finmo_path=source_finmo_path,
        temp_path=temp_path,
        controller_input_seed=controller_input_seed,
        calibration_request=calibration_request,
      )
    forecast_view = build_consistency_forecast_view_from_finmo(finmo_json)
    quarter_driver_path = [item for item in (forecast_view.get("quarter_driver_path") or []) if isinstance(item, dict)]
    forecast_years = [item for item in (forecast_view.get("forecast_years") or []) if isinstance(item, dict)]
    if not quarter_driver_path or not forecast_years:
      return _candidate_failure_result(
        failure_stage="empty_forecast_view",
        source_finmo_path=source_finmo_path,
        temp_path=temp_path,
        controller_input_seed=controller_input_seed,
        calibration_request=calibration_request,
        detail={
          "quarter_driver_count": len(quarter_driver_path),
          "forecast_year_count": len(forecast_years),
        },
      )
    return {
      "model_input_json": (result.get("model_input_json") or {}) if isinstance(result.get("model_input_json"), dict) else {},
      "finmo_json": finmo_json,
      "quarter_driver_path": quarter_driver_path,
      "forecast_years": forecast_years,
    }
  except Exception as exc:
    return _candidate_failure_result(
      failure_stage="sync_exception",
      source_finmo_path=source_finmo_path,
      temp_path=temp_path,
      controller_input_seed=controller_input_seed,
      calibration_request=calibration_request,
      error=exc,
    )
  finally:
    try:
      os.remove(temp_path)
    except Exception:
      pass


def build_controller_finmo_candidate(
  *,
  profile: Dict[str, Any],
  contract_bundle: Dict[str, Any],
  state_model: Dict[str, Any],
  scenario_index: int,
) -> Dict[str, Any]:
  baseline_state = (state_model.get("baseline_state") or {}) if isinstance(state_model.get("baseline_state"), dict) else {}
  next_ops = _clone((baseline_state.get("ops_json") or {}) if isinstance(baseline_state.get("ops_json"), dict) else {})
  next_people = _clone((baseline_state.get("people_json") or {}) if isinstance(baseline_state.get("people_json"), dict) else {})
  next_financials = _clone((baseline_state.get("financials_json") or {}) if isinstance(baseline_state.get("financials_json"), dict) else {})
  next_year1 = _clone((baseline_state.get("financials_year1_json") or {}) if isinstance(baseline_state.get("financials_year1_json"), dict) else {})
  next_marketing = _clone((baseline_state.get("marketing_model_json") or {}) if isinstance(baseline_state.get("marketing_model_json"), dict) else {})
  modified_state = {
    "ops_json": next_ops,
    "target_market_json": _clone((baseline_state.get("target_market_json") or {}) if isinstance(baseline_state.get("target_market_json"), dict) else {}),
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "fulfillment_json": _clone((baseline_state.get("fulfillment_json") or {}) if isinstance(baseline_state.get("fulfillment_json"), dict) else {}),
    "marketing_model_json": next_marketing,
  }
  controller_input_seed = _build_controller_input_seed_from_profile(
    profile=profile,
    direct_inputs=(contract_bundle.get("direct_inputs") or {}) if isinstance(contract_bundle.get("direct_inputs"), dict) else {},
    baseline_state=baseline_state,
  )
  controller_calibration_request = _build_finmo_calibration_spec(
    profile=profile,
    direct_inputs=(contract_bundle.get("direct_inputs") or {}) if isinstance(contract_bundle.get("direct_inputs"), dict) else {},
    controller_input_seed=controller_input_seed,
  )
  allowed_model_input_levers = _clone(controller_calibration_request.get("allowed_model_input_levers") or [])
  finmo_readback = _candidate_finmo_readback(
    state_model=state_model,
    modified_state=modified_state,
    controller_input_seed=controller_input_seed,
    calibration_request=controller_calibration_request,
  )
  candidate_failure = (finmo_readback.get("candidate_failure") or {}) if isinstance(finmo_readback.get("candidate_failure"), dict) else {}
  if candidate_failure:
    return {
      "scenario_id": str(scenario_index),
      "strategy_id": str(profile.get("strategy_id") or "").strip(),
      "strategy_name": str(profile.get("strategy_name") or "").strip(),
      "allowed_model_input_levers": allowed_model_input_levers,
      "controller_input_seed": _clone(controller_input_seed),
      "controller_calibration_request": _clone(controller_calibration_request),
      "candidate_failure": _clone(candidate_failure),
    }
  forecast_quarters = [item for item in (finmo_readback.get("quarter_driver_path") or []) if isinstance(item, dict)]
  forecast_years = [item for item in (finmo_readback.get("forecast_years") or []) if isinstance(item, dict)]
  if not forecast_quarters or not forecast_years:
    return {}
  finmo_execution_state = {
    "status": "finmo_readback_ready",
    "scenario_strategy": {
      "strategy_id": str(profile.get("strategy_id") or "").strip(),
      "strategy_name": str(profile.get("strategy_name") or "").strip(),
    },
    "quarter_count": len(forecast_quarters),
  }
  if isinstance(finmo_readback.get("finmo_json"), dict):
    finmo_execution_state["finmo_json"] = _clone(finmo_readback.get("finmo_json") or {})
    finmo_execution_state["accounting_check"] = _clone((((finmo_readback.get("finmo_json") or {}) if isinstance(finmo_readback.get("finmo_json"), dict) else {}).get("accounting_check") or {}))
  summary = build_consistency_financial_summary(financials_json=next_financials, financials_year1_json=next_year1)
  if forecast_years:
    year1 = forecast_years[0]
    summary = {
      "revenue": _safe_float(year1.get("revenue")),
      "cogs": _safe_float(year1.get("cogs")),
      "gross_profit": _safe_float(year1.get("gross_profit")),
      "marketing": _safe_float(year1.get("marketing")),
      "payroll": _safe_float(year1.get("payroll")),
      "opex": _safe_float(year1.get("opex")),
      "ebitda": _safe_float(year1.get("ebitda")),
      "interest": _safe_float(year1.get("interest")),
      "taxes": _safe_float(year1.get("taxes")),
      "net_income": _safe_float(year1.get("net_income")),
    }
  lever_summary = _profile_lever_summary(profile)
  label, rationale = _profile_label_and_rationale(profile)
  remaining_blocking_violations: List[str] = []
  finmo_execution_state["blocking_violations"] = _clone(remaining_blocking_violations)
  finmo_execution_state["year1_warning_status"] = "blocked_unresolved_year1" if remaining_blocking_violations else "ready"
  candidate: Dict[str, Any] = {
    "scenario_id": str(scenario_index),
    "strategy_id": str(profile.get("strategy_id") or "").strip(),
    "strategy_name": str(profile.get("strategy_name") or "").strip(),
    "solution_profile_id": str(profile.get("profile_id") or profile.get("strategy_id") or "").strip(),
    "financial_authority": "finmo",
    "forecast_role": "controller_finmo_projection",
    "archetype": str(profile.get("archetype") or "operations").strip(),
    "archetype_display": str(profile.get("archetype_display") or "Operational balance").strip(),
    "dominant_tradeoff": str(profile.get("dominant_tradeoff") or "").strip(),
    "canonical_lever_vocabulary": "model_inputs_controller_write_only",
    "allowed_model_input_levers": allowed_model_input_levers,
    "label": label,
    "rationale": rationale,
    "summary": summary,
    "modified_state": modified_state,
    "controller_input_seed": _clone(controller_input_seed),
    "model_input_json": _clone((finmo_readback.get("model_input_json") or {}) if isinstance(finmo_readback.get("model_input_json"), dict) else {}),
    "finmo_json": _clone((finmo_readback.get("finmo_json") or {}) if isinstance(finmo_readback.get("finmo_json"), dict) else {}),
    "scenario_strategy": {"strategy_id": str(profile.get("strategy_id") or "").strip(), "strategy_name": str(profile.get("strategy_name") or "").strip(), "archetype": str(profile.get("archetype") or "operations").strip()},
    "forecast_quarters": _clone(forecast_quarters),
    "forecast_years": _clone(forecast_years),
    "finmo_execution_state": finmo_execution_state,
    "forecast_summary": {"status": finmo_execution_state.get("status"), "year1_ebitda": _safe_float((forecast_years[0] if forecast_years else {}).get("ebitda")), "year3_ebitda": _safe_float((forecast_years[2] if len(forecast_years) >= 3 else {}).get("ebitda")), "year5_exit_ebitda": _safe_float((forecast_years[4] if len(forecast_years) >= 5 else {}).get("ebitda"))},
    "remaining_violations": _clone(remaining_blocking_violations),
    "remaining_blocking_count": len(remaining_blocking_violations),
    "remaining_blocking_violations": _clone(remaining_blocking_violations),
    "remaining_violation_count": len(remaining_blocking_violations),
    "contract_diagnostics": _clone(contract_bundle.get("diagnostics") or {}),
    "lever_summary": lever_summary,
    "ebitda": _safe_float(summary.get("ebitda")),
    "realism_distance": 0.0,
    "target_distance": 0.0,
    "distortion_total": 0.0,
    "disruption_score": 0.0,
    "controller_calibration_request": controller_calibration_request,
    "gpt_validation_request": {
      "validation_contract_version": "finmo_validation_request_v1",
      "canonical_lever_vocabulary": "model_inputs_controller_write_only",
      "authoritative_input_sheet": "Model Inputs",
      "authoritative_output_sheet": "Financial Model QTR",
      "named_ranges": [
        "model_input_periods",
        "model_input_revenue",
        "model_input_expenses",
        "model_input_balancehseet",
        "model_input_schedules",
        "finmo_accountingcheck",
        "finmo_periods",
        "finmo_pl",
        "finmo_balancesheet",
        "finmo_cfs",
      ],
      "allowed_model_input_levers": allowed_model_input_levers,
      "focus_line_items": ["Revenue", "EBITDA", "Net Income", "Cash", "Total Assets", "Total Liabilities & Equity"],
      "governed_period_groups": _policy_period_groups(profile),
    },
  }
  candidate["finmo_calibration_spec"] = _clone(candidate.get("controller_calibration_request") or {})
  candidate["presentation_issues"] = _presentation_issues(candidate, state_model=state_model)
  candidate["meaningful_lever_count"] = _safe_int((lever_summary or {}).get("meaningful_lever_count"))
  candidate["coordination_score"] = _safe_float((lever_summary or {}).get("coordination_score"))
  candidate["client_output"] = {
    "scenario_id": str(scenario_index),
    "scenario_name": str(profile.get("strategy_name") or "Governed Strategy").strip(),
    "summary": str(rationale or "").strip(),
    "key_metrics": {
      "year1_revenue": _safe_float((forecast_years[0] if forecast_years else {}).get("revenue")),
      "year1_ebitda": _safe_float((forecast_years[0] if forecast_years else {}).get("ebitda")),
      "year5_revenue": _safe_float((forecast_years[4] if len(forecast_years) >= 5 else {}).get("revenue")),
      "year5_ebitda": _safe_float((forecast_years[4] if len(forecast_years) >= 5 else {}).get("ebitda")),
    },
    "tradeoff": str(profile.get("dominant_tradeoff") or "").strip(),
    "confidence": {"forecast_confidence": 1.0, "convergence_strength": 1.0},
  }
  return candidate
