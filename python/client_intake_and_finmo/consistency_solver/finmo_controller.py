from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence

from consistency_financials import build_consistency_financial_summary  # type: ignore

from .common import (
  _clone,
  _normalize_ratio,
  _presentation_issues,
  _safe_float,
  _safe_int,
  _unique_strings,
)
from .patches import _build_lever_summary, _exact_patches_from_solution, _label_and_rationale_from_patches


def _revenue_lever_id(lob_name: str, product_name: str, driver: str) -> str:
  return "::".join(["revenue", str(lob_name or "").strip(), str(product_name or "").strip(), str(driver or "").strip()])


def _simple_lever_id(section: str, label: str) -> str:
  return "::".join([str(section or "").strip(), str(label or "").strip()])

def _quarter_policy_map(orchestration: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
  default_policy = {
    "growth_multiplier": 1.0,
    "convergence_multiplier": 1.0,
    "price_growth_bias": 0.0,
    "utilization_target_bias": 0.0,
    "marketing_ratio_bias": 0.0,
    "opex_ratio_bias": 0.0,
    "payroll_ratio_bias": 0.0,
    "capacity_release_multiplier": 1.0,
    "active_levers": [],
  }
  quarter_map: Dict[int, Dict[str, Any]] = {quarter_index: _clone(default_policy) for quarter_index in range(1, 21)}
  for item in orchestration.get("quarter_policies") or []:
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    for quarter_index in range(start, min(20, end) + 1):
      quarter_map[quarter_index] = {
        **quarter_map.get(quarter_index, _clone(default_policy)),
        **{
          "growth_multiplier": _safe_float(item.get("growth_multiplier")) or quarter_map[quarter_index]["growth_multiplier"],
          "convergence_multiplier": _safe_float(item.get("convergence_multiplier")) or quarter_map[quarter_index]["convergence_multiplier"],
          "price_growth_bias": _safe_float(item.get("price_growth_bias")),
          "utilization_target_bias": _safe_float(item.get("utilization_target_bias")),
          "marketing_ratio_bias": _safe_float(item.get("marketing_ratio_bias")),
          "opex_ratio_bias": _safe_float(item.get("opex_ratio_bias")),
          "payroll_ratio_bias": _safe_float(item.get("payroll_ratio_bias")),
          "capacity_release_multiplier": _safe_float(item.get("capacity_release_multiplier")) or quarter_map[quarter_index]["capacity_release_multiplier"],
          "active_levers": _unique_strings(item.get("active_levers") or []),
        },
      }
  return quarter_map


def _activation_quarter_from_months(months_until_activate: int) -> int:
  months = max(0, _safe_int(months_until_activate))
  return min(20, max(1, (months // 3) + 1))


def _role_activation_schedule(
  *,
  baseline_people_json: Dict[str, Any],
  exact_patches: Dict[str, Any],
  orchestration: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
  baseline_roles = {
    str(item.get("role_title") or item.get("full_name") or "").strip(): item
    for item in ((baseline_people_json.get("inferred_roles") or baseline_people_json.get("future_roles") or []))
    if isinstance(item, dict) and str(item.get("role_title") or item.get("full_name") or "").strip()
  }
  patched_roles = {
    str(item.get("role_title") or "").strip(): item
    for item in (exact_patches.get("people_role_updates") or [])
    if isinstance(item, dict) and str(item.get("role_title") or "").strip()
  }
  orchestration_overrides = {
    str(item.get("role_title") or "").strip(): item
    for item in (orchestration.get("role_timing_overrides") or [])
    if isinstance(item, dict) and str(item.get("role_title") or "").strip()
  }
  schedule: Dict[str, Dict[str, Any]] = {}
  titles = set(baseline_roles.keys()) | set(patched_roles.keys()) | set(orchestration_overrides.keys())
  for title in titles:
    base = baseline_roles.get(title) or {}
    patched = patched_roles.get(title) or {}
    override = orchestration_overrides.get(title) or {}
    annual_wage = (_safe_float(patched.get("annual_wage")) or _safe_float(base.get("annual_wage")) or 0.0)
    months = _safe_int(override.get("months_until_activate"))
    if months <= 0 and override.get("months_until_activate") in (None, ""):
      months = _safe_int(patched.get("months_until_hire"))
    if months <= 0 and patched.get("months_until_hire") in (None, ""):
      months = _safe_int(base.get("months_until_hire"))
    schedule[title] = {
      "annual_wage": annual_wage,
      "activation_quarter": _activation_quarter_from_months(months),
      "months_until_activate": months,
    }
  return schedule


def _milestone_schedule(orchestration: Dict[str, Any]) -> List[Dict[str, Any]]:
  schedule: List[Dict[str, Any]] = []
  for item in (orchestration.get("milestone_timing_overrides") or []):
    if not isinstance(item, dict):
      continue
    target_quarter = _safe_int(item.get("target_quarter"))
    if target_quarter <= 0:
      target_quarter = _activation_quarter_from_months(_safe_int(item.get("months_until_activate")))
    schedule.append(
      {
        "description": str(item.get("description") or "").strip(),
        "target_quarter": max(1, min(20, target_quarter)),
      }
    )
  return schedule


def _build_controller_anchor_solution(
  *,
  profile: Dict[str, Any],
  contract_bundle: Dict[str, Any],
) -> Dict[str, Any]:
  direct_inputs = (contract_bundle.get("direct_inputs") or {}) if isinstance(contract_bundle.get("direct_inputs"), dict) else {}
  product_basis = [item for item in (direct_inputs.get("product_driver_basis") or []) if isinstance(item, dict)]
  solve_mode = str(direct_inputs.get("solve_mode") or "").strip().lower()
  allowed = set(_allowed_model_input_levers(profile=profile, direct_inputs=direct_inputs))
  revenue_targets = _effective_revenue_targets(product_basis)
  growth_seed = str(profile.get("archetype") or "").strip().lower() == "growth"
  unit_price_levers = {_revenue_lever_id(target["lob"], target["product"], "Unit Price") for target in revenue_targets}
  utilization_levers = {_revenue_lever_id(target["lob"], target["product"], "Utilization") for target in revenue_targets}
  price_enabled = bool(unit_price_levers.intersection(allowed)) or any(str(item).endswith("::Unit Price") for item in allowed)
  utilization_enabled = bool(utilization_levers.intersection(allowed)) or any(str(item).endswith("::Utilization") for item in allowed)
  marketing_lever = _simple_lever_id("expenses", "Marketing")
  ganda_lever = _simple_lever_id("expenses", "General & Administrative")
  cogs_lever = _simple_lever_id("expenses", "Cost of Goods Sold")
  payroll_lever = _simple_lever_id("expenses", "Payroll")
  price_band = _lever_band_for_quarter(profile=profile, lever_id=next(iter(unit_price_levers), ""), quarter_index=1) if price_enabled else {"min": None, "max": None, "direction": "hold"}
  util_band = _lever_band_for_quarter(profile=profile, lever_id=next(iter(utilization_levers), ""), quarter_index=1) if utilization_enabled else {"min": None, "max": None, "direction": "hold"}
  marketing_band = _lever_band_for_quarter(profile=profile, lever_id=marketing_lever, quarter_index=1) if marketing_lever in allowed else {"min": None, "max": None, "direction": "hold"}
  ganda_band = _lever_band_for_quarter(profile=profile, lever_id=ganda_lever, quarter_index=1) if ganda_lever in allowed else {"min": None, "max": None, "direction": "hold"}
  cogs_band = _lever_band_for_quarter(profile=profile, lever_id=cogs_lever, quarter_index=1) if cogs_lever in allowed else {"min": None, "max": None, "direction": "hold"}
  payroll_band = _lever_band_for_quarter(profile=profile, lever_id=payroll_lever, quarter_index=1) if payroll_lever in allowed else {"min": None, "max": None, "direction": "hold"}
  if price_enabled:
    price = _pick_banded_value(
      current_value=_safe_float(direct_inputs.get("current_price")),
      min_value=_optional_float(price_band.get("min")),
      max_value=_optional_float(price_band.get("max")),
      direction=str(price_band.get("direction") or "hold"),
    )
  else:
    price = _safe_float(direct_inputs.get("current_price"))
  if utilization_enabled:
    util = _pick_banded_value(
      current_value=_safe_float(direct_inputs.get("current_util")),
      min_value=_optional_float(util_band.get("min")),
      max_value=_optional_float(util_band.get("max")),
      direction=str(util_band.get("direction") or "hold"),
    )
  else:
    util = _safe_float(direct_inputs.get("current_util"))
  if marketing_lever in allowed:
    marketing = _pick_banded_value(
      current_value=_safe_float(direct_inputs.get("current_marketing")),
      min_value=_optional_float(marketing_band.get("min")),
      max_value=_optional_float(marketing_band.get("max")),
      direction=str(marketing_band.get("direction") or ("up" if growth_seed else "down")),
    )
  else:
    marketing = _safe_float(direct_inputs.get("current_marketing"))
  if ganda_lever in allowed:
    other_opex = _pick_banded_value(
      current_value=_safe_float(direct_inputs.get("current_other_opex")),
      min_value=_optional_float(ganda_band.get("min")),
      max_value=_optional_float(ganda_band.get("max")),
      direction=str(ganda_band.get("direction") or "hold"),
    )
  else:
    other_opex = _safe_float(direct_inputs.get("current_other_opex"))
  if cogs_lever in allowed:
    cogs_ratio = _pick_banded_value(
      current_value=_safe_float(direct_inputs.get("current_cogs_ratio")),
      min_value=_optional_float(cogs_band.get("min")),
      max_value=_optional_float(cogs_band.get("max")),
      direction=str(cogs_band.get("direction") or "hold"),
    )
  else:
    cogs_ratio = _safe_float(direct_inputs.get("current_cogs_ratio"))
  payroll_too_light = "payroll_too_light" in {
    str(item or "").strip()
    for item in (direct_inputs.get("constraint_violations") or [])
    if str(item or "").strip()
  }
  if payroll_lever in allowed:
    payroll_total = _pick_banded_value(
      current_value=_safe_float(direct_inputs.get("current_payroll_total")),
      min_value=_optional_float(payroll_band.get("min")),
      max_value=_optional_float(payroll_band.get("max")),
      direction=str(payroll_band.get("direction") or ("up" if growth_seed or payroll_too_light or str(profile.get("strategy_id") or "").strip() == "staffing_ramp_adjustment" else "down")),
    )
  else:
    payroll_total = _safe_float(direct_inputs.get("current_payroll_total"))
  payroll_total = max(
    payroll_total,
    _safe_float(direct_inputs.get("structural_payroll_floor")),
    _safe_float(direct_inputs.get("people_payroll_floor")),
  )
  fixed_people_target = _safe_float(direct_inputs.get("fixed_people_payroll"))
  if fixed_people_target is None:
    fixed_people_target = payroll_total or _safe_float(direct_inputs.get("current_payroll_total"))
  current_price = max(1.0, _safe_float(direct_inputs.get("current_price")))
  current_util = max(0.01, _safe_float(direct_inputs.get("current_util")))
  baseline_units = max(1.0, _safe_float(direct_inputs.get("baseline_units")))
  current_marketing = max(0.0, _safe_float(direct_inputs.get("current_marketing")))
  marketing_factor = 1.0
  if current_marketing > 0 and marketing is not None:
    marketing_factor = max(0.75, min(1.35, 1.0 + 0.35 * ((marketing / current_marketing) - 1.0)))
  price_factor = 1.0
  if price is not None:
    if price >= current_price:
      price_factor = max(0.7, 1.0 - ((price / current_price) - 1.0) * 0.35)
    else:
      price_factor = min(1.25, 1.0 + ((current_price - price) / current_price) * 0.3)
  annual_units_total = baseline_units * ((util or current_util) / max(current_util, 0.01)) * marketing_factor * price_factor
  annual_units_total = max(1.0, annual_units_total)
  revenue = annual_units_total * max(1.0, price or current_price)
  cogs_total_year1 = revenue * max(0.0, cogs_ratio or _safe_float(direct_inputs.get("current_cogs_ratio")))
  role_months: Dict[str, int] = {}
  ebitda = revenue - cogs_total_year1 - max(0.0, payroll_total or 0.0) - max(0.0, marketing or 0.0) - max(0.0, other_opex or 0.0) - max(0.0, _safe_float(direct_inputs.get("rent_annualized"))) - max(0.0, _safe_float(direct_inputs.get("current_interest")))
  solution = {
    "price": round(price or current_price, 2),
    "utilization_rate": round(util or current_util, 6),
    "annual_units_total": round(annual_units_total, 4),
    "marketing_total_year1": round(marketing or current_marketing, 2),
    "marketing_support_units_year1": round(annual_units_total, 2),
    "other_operating_expense": round(other_opex or _safe_float(direct_inputs.get("current_other_opex")), 2),
    "cogs_total_year1": round(cogs_total_year1, 2),
    "payroll_total_year1": round(payroll_total or _safe_float(direct_inputs.get("current_payroll_total")), 2),
    "current_payroll_total": round(payroll_total or _safe_float(direct_inputs.get("current_payroll_total")), 2),
    "fixed_people_payroll_target": round(fixed_people_target or 0.0, 2),
    "structural_payroll_required_total": round(max(_safe_float(direct_inputs.get("structural_payroll_floor")), payroll_total or 0.0), 2),
    "role_months": role_months,
    "family_raw_components": {lever: 1.0 for lever in allowed},
    "ebitda": round(ebitda, 2),
    "ebitda_margin": round(ebitda / max(revenue, 1.0), 6),
  }
  if solve_mode == "child_first" and product_basis:
    child_solution, changed_count = _distribute_child_solution(
      product_basis=product_basis,
      annual_units_total=annual_units_total,
      price_ratio=(max(1.0, price or current_price) / max(current_price, 1.0)),
    )
    solution["child_product_solution"] = child_solution
    solution["changed_child_product_count"] = changed_count
  return solution


def _distribute_child_solution(
  *,
  product_basis: Sequence[Dict[str, Any]],
  annual_units_total: float,
  price_ratio: float,
) -> tuple[Dict[str, Dict[str, Any]], int]:
  baseline_total = sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_basis if isinstance(item, dict))
  remaining = annual_units_total - baseline_total
  child_solution: Dict[str, Dict[str, Any]] = {}
  basis_items = [item for item in product_basis if isinstance(item, dict)]
  if remaining >= 0:
    ranked = sorted(
      basis_items,
      key=lambda item: (
        -max(0.0, _safe_float(item.get("annual_capacity_units")) - _safe_float(item.get("annual_units"))),
        str(item.get("product_key") or ""),
      ),
    )
  else:
    ranked = sorted(
      basis_items,
      key=lambda item: (
        -_safe_float(item.get("annual_units")),
        str(item.get("product_key") or ""),
      ),
    )
  for item in basis_items:
    child_solution[str(item.get("product_key") or "")] = {
      "unit_price": _safe_float(item.get("unit_price")),
      "utilization_rate": _safe_float(item.get("utilization_rate")),
      "avg_units_per_period_year1": _safe_float(item.get("avg_units_per_period_year1")),
    }
  changed: set[str] = set()
  for item in ranked:
    key = str(item.get("product_key") or "")
    if not key:
      continue
    current_units = max(0.0, _safe_float(item.get("annual_units")))
    capacity_units = max(current_units, _safe_float(item.get("annual_capacity_units")))
    periods = max(1.0, _safe_float(item.get("operating_periods_per_year")))
    if remaining > 0:
      delta = min(remaining, max(0.0, capacity_units - current_units))
      if delta <= 0:
        continue
      current_units += delta
      remaining -= delta
    elif remaining < 0:
      delta = min(current_units, abs(remaining))
      current_units -= delta
      remaining += delta
    else:
      break
    child_solution[key]["avg_units_per_period_year1"] = round(current_units / periods, 4)
    child_solution[key]["utilization_rate"] = round(current_units / max(capacity_units, 1e-9), 6) if capacity_units > 0 else child_solution[key]["utilization_rate"]
    child_solution[key]["unit_price"] = round(_safe_float(item.get("unit_price")) * price_ratio, 2)
    changed.add(key)
    if abs(remaining) <= 1e-6:
      break
  return child_solution, len(changed)


def _base_child_quarter_drivers(financials_year1_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  drivers: List[Dict[str, Any]] = []
  lobs = financials_year1_json.get("lobs") if isinstance(financials_year1_json.get("lobs"), list) else []
  if lobs:
    for lob_idx, lob in enumerate(lobs, start=1):
      if not isinstance(lob, dict):
        continue
      for product_idx, product in enumerate((lob.get("products") or []), start=1):
        if not isinstance(product, dict):
          continue
        price = _safe_float(product.get("unit_price"))
        util = _normalize_ratio(product.get("utilization_rate"))
        annual_capacity = (
          _safe_float(product.get("units_per_week_capacity")) * (_safe_float(product.get("operating_weeks_per_year")) or 52.0)
          if _safe_float(product.get("units_per_week_capacity")) is not None
          else _safe_float(product.get("units_per_period_capacity"))
        )
        if annual_capacity is None:
          annual_capacity = _safe_float(product.get("concurrent_capacity_units"))
        if annual_capacity is None:
          avg_units = (
            _safe_float(product.get("avg_units_per_week_year1")) * (_safe_float(product.get("operating_weeks_per_year")) or 52.0)
            if _safe_float(product.get("avg_units_per_week_year1")) is not None
            else _safe_float(product.get("avg_units_per_period_year1"))
          )
          if avg_units is None:
            avg_units = _safe_float(product.get("avg_active_units_year1"))
          annual_capacity = max(avg_units or 0.0, (avg_units or 0.0) / max(util or 0.65, 0.01))
        drivers.append(
          {
            "lob_name": f"LOB {lob_idx}",
            "product_name": f"Product {product_idx}",
            "price": round(price or 0.0, 6),
            "utilization": round(util or 0.0, 6),
            "annual_capacity_units": round(annual_capacity or 0.0, 6),
          }
        )
  if drivers:
    return drivers
  price = _safe_float(financials_year1_json.get("unit_price")) or 0.0
  util = _normalize_ratio(financials_year1_json.get("utilization_rate")) or 0.0
  annual_units = (_safe_float(financials_year1_json.get("avg_units_per_period_year1")) or 0.0) * max(1.0, _safe_float(financials_year1_json.get("operating_periods_per_year")) or 4.0)
  annual_capacity = annual_units / max(util or 0.65, 0.01)
  return [
    {
      "lob_name": "LOB 1",
      "product_name": "Product 1",
      "price": round(price, 6),
      "utilization": round(util, 6),
      "annual_capacity_units": round(annual_capacity or 0.0, 6),
    }
  ]


def _quarter_projection_from_controller(
  *,
  modified_state: Dict[str, Any],
  exact_patches: Dict[str, Any],
  orchestration: Dict[str, Any],
) -> List[Dict[str, Any]]:
  financials = (modified_state.get("financials_json") or {}) if isinstance(modified_state.get("financials_json"), dict) else {}
  year1 = (modified_state.get("financials_year1_json") or {}) if isinstance(modified_state.get("financials_year1_json"), dict) else {}
  people = (modified_state.get("people_json") or {}) if isinstance(modified_state.get("people_json"), dict) else {}
  quarter_map = _quarter_policy_map(orchestration)
  role_schedule = _role_activation_schedule(
    baseline_people_json=people,
    exact_patches=exact_patches,
    orchestration=orchestration,
  )
  milestone_schedule = _milestone_schedule(orchestration)
  event_response = (orchestration.get("event_response") or {}) if isinstance(orchestration.get("event_response"), dict) else {}
  hire_capacity_multiplier = _safe_float(event_response.get("hire_capacity_multiplier")) or 1.0
  hire_growth_bonus_delta = _safe_float(event_response.get("hire_growth_bonus_delta")) or 0.0
  marketing_growth_multiplier = _safe_float(event_response.get("marketing_growth_multiplier")) or 1.0
  milestone_capacity_multiplier = _safe_float(event_response.get("milestone_capacity_multiplier")) or 1.0
  milestone_growth_multiplier = _safe_float(event_response.get("milestone_growth_multiplier")) or 1.0
  child_drivers = _base_child_quarter_drivers(year1)
  base_revenue = max(1.0, _safe_float(year1.get("company_revenue_total_year1")) or 1.0)
  base_cogs_ratio = (_safe_float(financials.get("cogs_total_year1")) or 0.0) / base_revenue
  base_marketing_ratio = (_safe_float(financials.get("marketing_total_year1")) or 0.0) / base_revenue
  annual_other_opex = max(0.0, _safe_float(financials.get("other_operating_expense")) or 0.0)
  annual_lease = max(0.0, (_safe_float(financials.get("monthly_rent_expense")) or 0.0) * 12.0)
  annual_ganda = max(0.0, annual_other_opex - annual_lease)
  base_ganda_ratio = annual_ganda / base_revenue
  base_depreciation_ratio = (_safe_float(financials.get("annual_depreciation")) or 0.0) / base_revenue
  base_tax_ratio = max(0.0, _safe_float(financials.get("annual_tax_rate")) or 0.0)
  base_payroll_per_quarter = max(0.0, _safe_float(financials.get("payroll_total_year1")) or 0.0) / 4.0
  current_staff_payroll_quarter = sum(max(0.0, _safe_float(item.get("annual_wage")) or 0.0) for item in (people.get("people") or []) if isinstance(item, dict)) / 4.0
  milestone_quarters = {max(1, min(20, _safe_int(item.get("target_quarter")) or 1)) for item in milestone_schedule}
  projected_quarters: List[Dict[str, Any]] = []
  prior_prices = {(item.get("lob_name"), item.get("product_name")): _safe_float(item.get("price")) or 0.0 for item in child_drivers}
  for quarter_index in range(1, 21):
    policy = quarter_map.get(quarter_index) or {}
    active_roles = [item for item in role_schedule.values() if quarter_index >= max(1, _safe_int(item.get("activation_quarter")) or 1)]
    active_role_payroll_quarter = sum(max(0.0, _safe_float(item.get("annual_wage")) or 0.0) for item in active_roles) / 4.0
    quarter_capacity_multiplier = max(0.1, _safe_float(policy.get("capacity_release_multiplier")) or 1.0)
    quarter_growth_multiplier = max(0.1, _safe_float(policy.get("growth_multiplier")) or 1.0)
    if active_roles:
      quarter_capacity_multiplier *= max(1.0, hire_capacity_multiplier)
      quarter_growth_multiplier += max(0.0, hire_growth_bonus_delta)
    if quarter_index in milestone_quarters:
      quarter_capacity_multiplier *= max(1.0, milestone_capacity_multiplier)
      quarter_growth_multiplier *= max(1.0, milestone_growth_multiplier)
    quarter_growth_multiplier *= max(0.1, marketing_growth_multiplier if _safe_float(policy.get("marketing_ratio_bias")) > 0 else 1.0)
    quarter_products: List[Dict[str, Any]] = []
    quarter_revenue = 0.0
    for item in child_drivers:
      key = (item.get("lob_name"), item.get("product_name"))
      prior_price = prior_prices.get(key) or (_safe_float(item.get("price")) or 0.0)
      next_price = prior_price * (1.0 + (_safe_float(policy.get("price_growth_bias")) or 0.0))
      prior_prices[key] = next_price
      capacity_units = (max(0.0, _safe_float(item.get("annual_capacity_units")) or 0.0) / 4.0) * quarter_capacity_multiplier
      utilization = max(0.01, min(0.98, (_normalize_ratio(item.get("utilization")) or 0.0) + (_safe_float(policy.get("utilization_target_bias")) or 0.0)))
      effective_utilization = max(0.01, min(0.98, utilization * quarter_growth_multiplier))
      units = capacity_units * effective_utilization
      revenue = units * next_price
      quarter_revenue += revenue
      quarter_products.append(
        {
          "product_name": item.get("product_name"),
          "capacity_units": round(capacity_units, 6),
          "utilization": round(effective_utilization, 6),
          "units": round(units, 6),
          "price": round(next_price, 6),
          "revenue": round(revenue, 6),
        }
      )
    marketing_ratio = max(0.0, base_marketing_ratio + (_safe_float(policy.get("marketing_ratio_bias")) or 0.0))
    ganda_ratio = max(0.0, base_ganda_ratio + (_safe_float(policy.get("opex_ratio_bias")) or 0.0))
    payroll_amount = max(
      current_staff_payroll_quarter,
      (current_staff_payroll_quarter + active_role_payroll_quarter) * (1.0 + (_safe_float(policy.get("payroll_ratio_bias")) or 0.0)),
      base_payroll_per_quarter * (1.0 + (_safe_float(policy.get("payroll_ratio_bias")) or 0.0)),
    )
    cogs = quarter_revenue * max(0.0, base_cogs_ratio)
    marketing = quarter_revenue * marketing_ratio
    g_and_a = quarter_revenue * ganda_ratio
    lease_rent = annual_lease / 4.0
    opex = g_and_a + lease_rent
    depreciation = quarter_revenue * max(0.0, base_depreciation_ratio)
    interest = max(0.0, _safe_float(financials.get("annual_interest_payment")) or 0.0) / 4.0
    taxes = max(0.0, quarter_revenue * base_tax_ratio)
    ebitda = quarter_revenue - cogs - marketing - payroll_amount - opex
    projected_quarters.append(
      {
        "quarter_index": quarter_index,
        "period_label": f"Year {((quarter_index - 1) // 4) + 1} Q{((quarter_index - 1) % 4) + 1}",
        "capacity_units": round(sum(_safe_float(item.get("capacity_units")) or 0.0 for item in quarter_products), 6),
        "price": round((sum((_safe_float(item.get("price")) or 0.0) * (_safe_float(item.get("units")) or 0.0) for item in quarter_products) / max(sum(_safe_float(item.get("units")) or 0.0 for item in quarter_products), 1.0)), 6),
        "utilization": round((sum((_safe_float(item.get("utilization")) or 0.0) * (_safe_float(item.get("capacity_units")) or 0.0) for item in quarter_products) / max(sum(_safe_float(item.get("capacity_units")) or 0.0 for item in quarter_products), 1.0)), 6),
        "units": round(sum(_safe_float(item.get("units")) or 0.0 for item in quarter_products), 6),
        "revenue": round(quarter_revenue, 6),
        "cogs": round(cogs, 6),
        "marketing": round(marketing, 6),
        "payroll": round(payroll_amount, 6),
        "opex": round(opex, 6),
        "ebitda": round(ebitda, 6),
        "interest": round(interest, 6),
        "depreciation": round(depreciation, 6),
        "taxes": round(taxes, 6),
        "net_income": round(ebitda - interest - depreciation - taxes, 6),
        "lobs": [{"lob_name": "Primary", "products": quarter_products}],
        "active_levers": _clone(policy.get("active_levers") or []),
        "policy_effects": _clone(policy),
        "working_capital": {},
      }
    )
  return projected_quarters


def _rollup_years(quarters: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  forecast_years: List[Dict[str, Any]] = []
  valid_quarters = [item for item in quarters if isinstance(item, dict)]
  for idx in range(0, len(valid_quarters), 4):
    year_quarters = valid_quarters[idx:idx + 4]
    if not year_quarters:
      continue
    year_number = (idx // 4) + 1
    forecast_years.append(
      {
        "year_index": year_number,
        "period_label": f"Year {year_number}",
        "revenue": round(sum(_safe_float(item.get("revenue")) or 0.0 for item in year_quarters), 2),
        "cogs": round(sum(_safe_float(item.get("cogs")) or 0.0 for item in year_quarters), 2),
        "gross_profit": round(sum((_safe_float(item.get("revenue")) or 0.0) - (_safe_float(item.get("cogs")) or 0.0) for item in year_quarters), 2),
        "marketing": round(sum(_safe_float(item.get("marketing")) or 0.0 for item in year_quarters), 2),
        "payroll": round(sum(_safe_float(item.get("payroll")) or 0.0 for item in year_quarters), 2),
        "opex": round(sum(_safe_float(item.get("opex")) or 0.0 for item in year_quarters), 2),
        "ebitda": round(sum(_safe_float(item.get("ebitda")) or 0.0 for item in year_quarters), 2),
        "interest": round(sum(_safe_float(item.get("interest")) or 0.0 for item in year_quarters), 2),
        "depreciation": round(sum(_safe_float(item.get("depreciation")) or 0.0 for item in year_quarters), 2),
        "taxes": round(sum(_safe_float(item.get("taxes")) or 0.0 for item in year_quarters), 2),
        "net_income": round(sum(_safe_float(item.get("net_income")) or 0.0 for item in year_quarters), 2),
      }
    )
  return forecast_years


def _controller_input_seed_from_projection(
  *,
  forecast_quarters: Sequence[Dict[str, Any]],
  financials_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  annual_interest = max(0.0, _safe_float((financials_json or {}).get("annual_interest_payment")))
  debt_outstanding = max(1.0, _safe_float((financials_json or {}).get("total_debt_outstanding")))
  annual_tax_rate = max(0.0, _safe_float((financials_json or {}).get("annual_tax_rate")))
  input_seed: List[Dict[str, Any]] = []
  for quarter in [item for item in (forecast_quarters or []) if isinstance(item, dict)]:
    revenue = max(1.0, _safe_float(quarter.get("revenue")))
    lobs = quarter.get("lobs") if isinstance(quarter.get("lobs"), list) else []
    input_seed.append(
      {
        "quarter_index": _safe_int(quarter.get("quarter_index")) or (len(input_seed) + 1),
        "revenue_products": _clone(lobs),
        "cogs_percent": round(max(0.0, _safe_float(quarter.get("cogs"))) / revenue, 6),
        "marketing_percent": round(max(0.0, _safe_float(quarter.get("marketing"))) / revenue, 6),
        "r_and_d_percent": 0.0,
        "lease_amount": round(max(0.0, _safe_float((financials_json or {}).get("monthly_rent_expense"))) * 3.0, 6),
        "payroll_amount": round(max(0.0, _safe_float(quarter.get("payroll"))), 6),
        "g_and_a_percent": round(max(0.0, (_safe_float(quarter.get("opex")) or 0.0) - (max(0.0, _safe_float((financials_json or {}).get("monthly_rent_expense"))) * 3.0)) / revenue, 6),
        "interest_rate": round(annual_interest / debt_outstanding, 6),
        "depreciation_percent": round(max(0.0, _safe_float(quarter.get("depreciation"))) / revenue, 6),
        "tax_percent": round(max(0.0, _safe_float(quarter.get("taxes"))) / revenue, 6) if _safe_float(quarter.get("taxes")) is not None else round(annual_tax_rate, 6),
        "working_capital": _clone(quarter.get("working_capital") or {}),
        "capex": round(max(0.0, _safe_float(quarter.get("capex"))), 6),
      }
    )
  return input_seed


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


def _effective_revenue_targets(product_basis: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
  targets: List[Dict[str, str]] = []
  seen: set[tuple[str, str]] = set()
  for item in [entry for entry in (product_basis or []) if isinstance(entry, dict)]:
    lob_name = str(item.get("lob_name") or "").strip() or "LOB 1"
    product_name = str(item.get("product_name") or "").strip() or "Product 1"
    key = (lob_name, product_name)
    if key in seen:
      continue
    seen.add(key)
    targets.append({"lob": lob_name, "product": product_name})
  if targets:
    return targets
  return [{"lob": "LOB 1", "product": "Product 1"}]


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
  product_basis: Sequence[Dict[str, Any]],
  direct_inputs: Dict[str, Any],
  annual_revenue: float,
  quarterly_seed: Optional[Dict[str, Any]] = None,
  group_key: str | None = None,
  grouping_mode: str = "quarterly",
) -> List[Dict[str, Any]]:
  specs: List[Dict[str, Any]] = []
  allowed_set = {
    str(item or "").strip()
    for item in (allowed_model_input_levers or [])
    if str(item or "").strip()
  }
  del product_basis, direct_inputs, annual_revenue, quarterly_seed
  for lever_id in sorted(allowed_set):
    metadata = lever_catalog.get(lever_id)
    if not isinstance(metadata, dict) or not metadata:
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
    specs.append(
      _banded_input_spec(
        spec=spec,
        min_value=_optional_float(band.get("min")),
        max_value=_optional_float(band.get("max")),
      )
    )
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
  product_count: int,
) -> Dict[str, Any]:
  allowed_model_input_levers = _allowed_model_input_levers(profile=profile, direct_inputs=direct_inputs)
  lever_catalog = _model_input_lever_catalog_from_direct_inputs(direct_inputs)
  goal_seek_requests: List[Dict[str, Any]] = []
  solver_requests: List[Dict[str, Any]] = []
  annual_revenue = max(1.0, _safe_float(direct_inputs.get("current_revenue")) or sum(max(0.0, _safe_float((item or {}).get("revenue"))) for item in controller_input_seed) / max(1.0, len(controller_input_seed) / 4.0))
  product_basis = [item for item in (direct_inputs.get("product_driver_basis") or []) if isinstance(item, dict)]
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
        seed = next((item for item in controller_input_seed if _safe_int(item.get("quarter_index")) == quarter_index), {})
        changing_inputs.extend(
          _calibration_variable_specs(
            profile=profile,
            allowed_model_input_levers=[lever_id],
            lever_catalog=lever_catalog,
            quarter_index=quarter_index,
            product_basis=product_basis,
            direct_inputs=direct_inputs,
            annual_revenue=annual_revenue,
            quarterly_seed=seed,
            grouping_mode=lever_group_mode,
            group_key=(f"group_{group_index}::{lever_id}" if lever_group_mode == "grouped" else None),
          )
        )
    goal_seek_requests.append(
      {
        "request_id": f"goal_seek_group_{group_index}_q{quarter_start}_q{quarter_end}",
        "objective": objective_spec,
        "changing_inputs": changing_inputs[:1],
        "mode": "goal_seek_shell",
      }
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
  return {
    "contract_version": "finmo_calibration_shell_v1",
    "canonical_lever_vocabulary": "model_inputs_controller_write_only",
    "goal_seek_requests": goal_seek_requests,
    "solver_requests": solver_requests,
    "governed_period_groups": governed_period_groups,
    "allowed_model_input_levers": sorted(
      {
        str(item.get("lever_id") or "").strip()
        for request in solver_requests
        for item in (request.get("changing_inputs") or [])
        if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
      }
    ) or allowed_model_input_levers,
    "allowed_model_input_lever_details": [
      _clone(lever_catalog.get(lever_id) or {})
      for lever_id in (
        sorted(
          {
            str(item.get("lever_id") or "").strip()
            for request in solver_requests
            for item in (request.get("changing_inputs") or [])
            if isinstance(item, dict) and str(item.get("lever_id") or "").strip()
          }
        ) or list(allowed_model_input_levers)
      )
      if str(lever_id or "").strip() and isinstance(lever_catalog.get(lever_id), dict) and lever_catalog.get(lever_id)
    ],
  }


def _candidate_finmo_readback(
  *,
  state_model: Dict[str, Any],
  modified_state: Dict[str, Any],
  controller_input_seed: Sequence[Dict[str, Any]],
  calibration_request: Dict[str, Any],
  fallback_forecast_quarters: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
  fixed_facts = (state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}
  source_finmo_path = str(fixed_facts.get("finmo_path") or "").strip()
  if not source_finmo_path or not os.path.exists(source_finmo_path):
    return {}
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
      forecast_quarters=fallback_forecast_quarters,
      calibration_spec=calibration_request,
    )
    finmo_json = (result.get("finmo_json") or {}) if isinstance(result.get("finmo_json"), dict) else {}
    if not finmo_json:
      return {}
    forecast_view = build_consistency_forecast_view_from_finmo(finmo_json)
    return {
      "model_input_json": (result.get("model_input_json") or {}) if isinstance(result.get("model_input_json"), dict) else {},
      "finmo_json": finmo_json,
      "quarter_driver_path": [item for item in (forecast_view.get("quarter_driver_path") or []) if isinstance(item, dict)],
      "forecast_years": [item for item in (forecast_view.get("forecast_years") or []) if isinstance(item, dict)],
    }
  except Exception:
    return {}
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
  solution = _build_controller_anchor_solution(profile=profile, contract_bundle=contract_bundle)
  exact_patches = _exact_patches_from_solution(
    solution=solution,
    direct_inputs=contract_bundle.get("direct_inputs") or {},
    ops_json=(baseline_state.get("ops_json") or {}) if isinstance(baseline_state.get("ops_json"), dict) else {},
  )
  from .patches import _apply_exact_patches  # local import to avoid cycles

  next_ops, next_people, next_financials, next_year1, next_marketing = _apply_exact_patches(
    ops_json=_clone((baseline_state.get("ops_json") or {}) if isinstance(baseline_state.get("ops_json"), dict) else {}),
    people_json=_clone((baseline_state.get("people_json") or {}) if isinstance(baseline_state.get("people_json"), dict) else {}),
    financials_json=_clone((baseline_state.get("financials_json") or {}) if isinstance(baseline_state.get("financials_json"), dict) else {}),
    financials_year1_json=_clone((baseline_state.get("financials_year1_json") or {}) if isinstance(baseline_state.get("financials_year1_json"), dict) else {}),
    marketing_model_json=_clone((baseline_state.get("marketing_model_json") or {}) if isinstance(baseline_state.get("marketing_model_json"), dict) else {}),
    exact_patches=exact_patches,
  )
  modified_state = {
    "ops_json": next_ops,
    "target_market_json": _clone((baseline_state.get("target_market_json") or {}) if isinstance(baseline_state.get("target_market_json"), dict) else {}),
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "fulfillment_json": _clone((baseline_state.get("fulfillment_json") or {}) if isinstance(baseline_state.get("fulfillment_json"), dict) else {}),
    "marketing_model_json": next_marketing,
  }
  preview_forecast_quarters = _quarter_projection_from_controller(modified_state=modified_state, exact_patches=exact_patches, orchestration={})
  controller_input_seed = _controller_input_seed_from_projection(
    forecast_quarters=preview_forecast_quarters,
    financials_json=next_financials,
  )
  controller_calibration_request = _build_finmo_calibration_spec(
    profile=profile,
    direct_inputs=(contract_bundle.get("direct_inputs") or {}) if isinstance(contract_bundle.get("direct_inputs"), dict) else {},
    controller_input_seed=controller_input_seed,
    product_count=max(1, len(_base_child_quarter_drivers(next_year1))),
  )
  allowed_model_input_levers = _clone(controller_calibration_request.get("allowed_model_input_levers") or [])
  finmo_readback = _candidate_finmo_readback(
    state_model=state_model,
    modified_state=modified_state,
    controller_input_seed=controller_input_seed,
    calibration_request=controller_calibration_request,
    fallback_forecast_quarters=preview_forecast_quarters,
  )
  forecast_quarters = [item for item in (finmo_readback.get("quarter_driver_path") or []) if isinstance(item, dict)]
  forecast_years = [item for item in (finmo_readback.get("forecast_years") or []) if isinstance(item, dict)]
  if not forecast_quarters or not forecast_years:
    return {}
  forecast_engine_state = {
    "status": "finmo_readback_ready",
    "scenario_strategy": {
      "strategy_id": str(profile.get("strategy_id") or "").strip(),
      "strategy_name": str(profile.get("strategy_name") or "").strip(),
    },
    "quarter_count": len(forecast_quarters),
  }
  if isinstance(finmo_readback.get("finmo_json"), dict):
    forecast_engine_state["finmo_json"] = _clone(finmo_readback.get("finmo_json") or {})
    forecast_engine_state["accounting_check"] = _clone((((finmo_readback.get("finmo_json") or {}) if isinstance(finmo_readback.get("finmo_json"), dict) else {}).get("accounting_check") or {}))
  summary = build_consistency_financial_summary(financials_json=next_financials, financials_year1_json=next_year1)
  lever_summary = _build_lever_summary(exact_patches=exact_patches, family_raw_components=solution.get("family_raw_components"))
  label, rationale, families = _label_and_rationale_from_patches(
    exact_patches=exact_patches,
    archetype=str(profile.get("archetype") or "operations"),
    archetype_display=str(profile.get("archetype_display") or "Operational balance"),
    dominant_tradeoff=str(profile.get("dominant_tradeoff") or ""),
  )
  constraint_profile = (state_model.get("constraint_profile") or {}) if isinstance(state_model.get("constraint_profile"), dict) else {}
  current_constraint_violations = {
    str(item or "").strip()
    for item in (constraint_profile.get("constraint_engine_violations") or [])
    if str(item or "").strip()
  }
  remaining_blocking_violations: List[str] = []
  year1_forecast = forecast_years[0] if forecast_years else {}
  year1_revenue = _safe_float(year1_forecast.get("revenue"))
  year1_ebitda = _safe_float(year1_forecast.get("ebitda"))
  year1_margin = year1_ebitda / max(year1_revenue, 1.0)
  year1_payroll = _safe_float(year1_forecast.get("payroll"))
  year1_utilization = _normalize_ratio(year1_forecast.get("utilization"))
  if "payroll_too_light" in current_constraint_violations:
    payroll_floor = max(
      _safe_float(((constraint_profile.get("current_metrics") or {}) if isinstance(constraint_profile.get("current_metrics"), dict) else {}).get("people_payroll_floor")),
      _safe_float(((constraint_profile.get("current_metrics") or {}) if isinstance(constraint_profile.get("current_metrics"), dict) else {}).get("structural_payroll_floor")),
    )
    if payroll_floor > 0 and year1_payroll + 1.0 < payroll_floor:
      remaining_blocking_violations.append("payroll_too_light")
  if "utilization_too_low" in current_constraint_violations:
    util_floor = _normalize_ratio(((constraint_profile.get("utilization_envelope") or {}) if isinstance(constraint_profile.get("utilization_envelope"), dict) else {}).get("min"))
    if util_floor is not None and year1_utilization is not None and year1_utilization < util_floor - 0.01:
      remaining_blocking_violations.append("utilization_too_low")
  if "ebitda_margin_too_low" in current_constraint_violations:
    ebitda_floor = _safe_float(((constraint_profile.get("ebitda_margin_band") or {}) if isinstance(constraint_profile.get("ebitda_margin_band"), dict) else {}).get("min"))
    target_ebitda_min = _safe_float(contract_bundle.get("target_ebitda_min"))
    target_ebitda_max = _safe_float(contract_bundle.get("target_ebitda_max"))
    meets_governed_year1_target = (
      target_ebitda_min is not None
      and target_ebitda_max is not None
      and year1_ebitda >= target_ebitda_min - 1.0
      and year1_ebitda <= target_ebitda_max + 1.0
    )
    if not meets_governed_year1_target and ebitda_floor is not None and year1_margin < ebitda_floor - 0.005:
      remaining_blocking_violations.append("ebitda_margin_too_low")
  if "gross_margin_too_low" in current_constraint_violations:
    gross_margin_floor = _safe_float(((constraint_profile.get("gross_margin_band") or {}) if isinstance(constraint_profile.get("gross_margin_band"), dict) else {}).get("min"))
    gross_profit = year1_revenue - _safe_float(year1_forecast.get("cogs"))
    gross_margin = gross_profit / max(year1_revenue, 1.0)
    if gross_margin_floor is not None and gross_margin < gross_margin_floor - 0.01:
      remaining_blocking_violations.append("gross_margin_too_low")
  remaining_blocking_violations = _unique_strings(remaining_blocking_violations)
  forecast_engine_state["blocking_violations"] = _clone(remaining_blocking_violations)
  forecast_engine_state["year1_warning_status"] = "blocked_unresolved_year1" if remaining_blocking_violations else "ready"
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
    "exact_patches": exact_patches,
    "modified_state": modified_state,
    "controller_input_seed": _clone(controller_input_seed),
    "model_input_json": _clone((finmo_readback.get("model_input_json") or {}) if isinstance(finmo_readback.get("model_input_json"), dict) else {}),
    "finmo_json": _clone((finmo_readback.get("finmo_json") or {}) if isinstance(finmo_readback.get("finmo_json"), dict) else {}),
    "scenario_strategy": {"strategy_id": str(profile.get("strategy_id") or "").strip(), "strategy_name": str(profile.get("strategy_name") or "").strip(), "archetype": str(profile.get("archetype") or "operations").strip()},
    "forecast_quarters": _clone(forecast_quarters),
    "forecast_years": _clone(forecast_years),
    "forecast_engine_state": forecast_engine_state,
    "forecast_summary": {"status": forecast_engine_state.get("status"), "year1_ebitda": _safe_float((forecast_years[0] if forecast_years else {}).get("ebitda")), "year3_ebitda": _safe_float((forecast_years[2] if len(forecast_years) >= 3 else {}).get("ebitda")), "year5_exit_ebitda": _safe_float((forecast_years[4] if len(forecast_years) >= 5 else {}).get("ebitda"))},
    "remaining_violations": _clone(remaining_blocking_violations),
    "remaining_blocking_count": len(remaining_blocking_violations),
    "remaining_blocking_violations": _clone(remaining_blocking_violations),
    "remaining_violation_count": len(remaining_blocking_violations),
    "contract_diagnostics": _clone(contract_bundle.get("diagnostics") or {}),
    "lever_summary": lever_summary,
    "ebitda": _safe_float(summary.get("ebitda")),
    "realism_distance": 0.0,
    "target_distance": 0.0,
    "distortion_total": sum(max(0.0, _safe_float(value)) for value in (solution.get("family_raw_components") or {}).values()) if isinstance(solution.get("family_raw_components"), dict) else 0.0,
    "disruption_score": sum(max(0.0, _safe_float(value)) for value in (solution.get("family_raw_components") or {}).values()) if isinstance(solution.get("family_raw_components"), dict) else 0.0,
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
      "target_margin_path": _clone(orchestration.get("target_margin_path") or {}),
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
