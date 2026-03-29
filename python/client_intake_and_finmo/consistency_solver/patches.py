from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from financials_year1 import apply_revenue_driver_patch  # type: ignore

from .common import _clone, _safe_float, _safe_int


def _sync_marketing_derived_fields(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  units_per_dollar: Optional[float] = None,
  min_total: Optional[float] = None,
  max_total: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_model = _clone(marketing_model_json or {})
  next_financials = _clone(financials_json or {})
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  marketing = marketing_model_json if isinstance(marketing_model_json, dict) else {}
  expected_units = _safe_float(marketing.get("expected_units_year1"))
  unit_price = _safe_float(year1.get("unit_price"))
  if units_per_dollar and units_per_dollar > 0 and expected_units > 0:
    marketing_total = expected_units / max(units_per_dollar, 1e-9)
    if min_total is not None:
      marketing_total = max(marketing_total, _safe_float(min_total))
    if max_total is not None and _safe_float(max_total) > 0:
      marketing_total = min(marketing_total, _safe_float(max_total))
    next_model["marketing_total_year1"] = round(marketing_total, 2)
    next_financials["marketing_total_year1"] = round(marketing_total, 2)
  if expected_units > 0 and unit_price > 0 and _safe_float(year1.get("company_revenue_total_year1")) <= 0:
    next_financials["current_revenue"] = round(expected_units * unit_price, 2)
  return next_model, next_financials


def _build_lever_summary(
  exact_patches: Dict[str, Any],
  family_raw_components: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  family_raw_components = family_raw_components if isinstance(family_raw_components, dict) else {}
  meaningful_thresholds = {
    "price": 0.015,
    "utilization": 0.03,
    "marketing": 0.06,
    "other_opex": 0.06,
    "cogs": 0.03,
    "hire_delay": 0.05,
    "payroll": 0.04,
  }
  canonical_families = {
    "price",
    "utilization",
    "marketing",
    "other_opex",
    "cogs",
    "hire_delay",
    "payroll",
  }
  raw_moves: Dict[str, float] = {}
  for raw_name, raw_value in family_raw_components.items():
    family_name = str(raw_name or "").strip().lower()
    if family_name not in canonical_families:
      continue
    value = max(0.0, _safe_float(raw_value))
    raw_moves[family_name] = max(raw_moves.get(family_name, 0.0), value)
  year1_patch = exact_patches.get("financials_year1_patch") if isinstance(exact_patches, dict) else {}
  year1_patch = year1_patch if isinstance(year1_patch, dict) else {}
  product_overrides = year1_patch.get("product_overrides") if isinstance(year1_patch, dict) else {}
  product_overrides = product_overrides if isinstance(product_overrides, dict) else {}
  financials_patch = exact_patches.get("financials_patch") if isinstance(exact_patches, dict) else {}
  financials_patch = financials_patch if isinstance(financials_patch, dict) else {}
  solver_meta = exact_patches.get("solver_meta") if isinstance(exact_patches, dict) else {}
  solver_meta = solver_meta if isinstance(solver_meta, dict) else {}
  if financials_patch.get("marketing_total_year1") is not None:
    raw_moves["marketing"] = max(raw_moves.get("marketing", 0.0), 0.1)
  if financials_patch.get("payroll_total_year1") is not None or financials_patch.get("current_payroll") is not None:
    raw_moves["payroll"] = max(raw_moves.get("payroll", 0.0), 0.1)
  if financials_patch.get("other_operating_expense") is not None:
    raw_moves["other_opex"] = max(raw_moves.get("other_opex", 0.0), 0.1)
  if financials_patch.get("cogs_total_year1") is not None:
    raw_moves["cogs"] = max(raw_moves.get("cogs", 0.0), 0.1)
  if solver_meta.get("opex_total_ratio_target") is not None:
    raw_moves["other_opex"] = max(raw_moves.get("other_opex", 0.0), 0.08)
  if solver_meta.get("cogs_ratio_target") is not None:
    raw_moves["cogs"] = max(raw_moves.get("cogs", 0.0), 0.08)
  if year1_patch.get("unit_price") is not None:
    raw_moves["price"] = max(raw_moves.get("price", 0.0), 0.1)
  if year1_patch.get("utilization_rate") is not None or year1_patch.get("avg_units_per_period_year1") is not None:
    raw_moves["utilization"] = max(raw_moves.get("utilization", 0.0), 0.1)
  if product_overrides:
    for override in product_overrides.values():
      if not isinstance(override, dict) or not override:
        continue
      if override.get("unit_price") is not None:
        raw_moves["price"] = max(raw_moves.get("price", 0.0), 0.1)
      if override.get("utilization_rate") is not None or override.get("avg_units_per_period_year1") is not None:
        raw_moves["utilization"] = max(raw_moves.get("utilization", 0.0), 0.1)
  if isinstance(exact_patches.get("marketing_model_patch"), dict) and exact_patches["marketing_model_patch"]:
    marketing_model_patch = exact_patches["marketing_model_patch"]
    if (
      marketing_model_patch.get("expected_units_year1") is not None
      or marketing_model_patch.get("expected_customers_or_clients_year1") is not None
    ):
      raw_moves["marketing"] = max(raw_moves.get("marketing", 0.0), 0.1)
  if isinstance(exact_patches.get("people_role_updates"), list) and exact_patches["people_role_updates"]:
    role_updates = exact_patches["people_role_updates"]
    if any(isinstance(item, dict) and item.get("months_until_hire") is not None for item in role_updates):
      raw_moves["hire_delay"] = max(raw_moves.get("hire_delay", 0.0), 0.1)
    if any(isinstance(item, dict) and item.get("annual_wage") is not None for item in role_updates):
      raw_moves["payroll"] = max(raw_moves.get("payroll", 0.0), 0.1)
  if isinstance(exact_patches.get("people_compensation_updates"), list) and exact_patches["people_compensation_updates"]:
    if any(isinstance(item, dict) and item.get("annual_wage") is not None for item in exact_patches["people_compensation_updates"]):
      raw_moves["payroll"] = max(raw_moves.get("payroll", 0.0), 0.1)
  meaningful_families = [
    family_name
    for family_name, value in raw_moves.items()
    if value >= max(0.0, _safe_float(meaningful_thresholds.get(family_name, 0.03)) or 0.03)
  ]
  meaningful_families = list(dict.fromkeys(meaningful_families))
  moved_products = [
    product_key for product_key, override in product_overrides.items()
    if isinstance(override, dict) and override
  ]
  changed_products = len(moved_products)
  total_move = sum(max(0.0, _safe_float(value)) for value in raw_moves.values())
  dominant_family = max(raw_moves.items(), key=lambda item: item[1])[0] if raw_moves else ""
  dominant_family_share = (
    max(0.0, _safe_float(raw_moves.get(dominant_family))) / max(total_move, 1e-9)
    if dominant_family and total_move > 0
    else 0.0
  )
  aligned_pairs = 0
  coordination_issues: List[str] = []
  marketing_move = max(0.0, _safe_float(raw_moves.get("marketing")))
  staffing_move = max(0.0, _safe_float(raw_moves.get("payroll"))) + max(0.0, _safe_float(raw_moves.get("hire_delay")))
  utilization_move = max(0.0, _safe_float(raw_moves.get("utilization")))
  cost_move = max(0.0, _safe_float(raw_moves.get("other_opex"))) + max(0.0, _safe_float(raw_moves.get("cogs")))
  price_move = max(0.0, _safe_float(raw_moves.get("price")))
  if marketing_move > 0.03 and staffing_move > 0.03:
    aligned_pairs += 1
  if cost_move > 0.03 and (utilization_move > 0.03 or staffing_move > 0.03 or price_move > 0.03):
    aligned_pairs += 1
  if utilization_move > 0.03 and (staffing_move > 0.03 or cost_move > 0.03 or price_move > 0.03):
    aligned_pairs += 1
  if marketing_move > 0.06 and staffing_move <= 0.02:
    coordination_issues.append("demand_without_staffing")
  if cost_move > 0.08 and utilization_move <= 0.02 and staffing_move <= 0.02 and price_move <= 0.02:
    coordination_issues.append("cost_without_structure")
  if utilization_move > 0.06 and staffing_move <= 0.02 and cost_move <= 0.02:
    coordination_issues.append("utilization_without_support")
  coordination_score = (
    float(len(meaningful_families))
    + (0.35 * max(0, changed_products - 1))
    + (0.2 * max(0, len(raw_moves) - len(meaningful_families)))
    + (0.7 * aligned_pairs)
    - (1.2 * len(coordination_issues))
    - max(0.0, dominant_family_share - 0.7) * 2.0
  )
  return {
    "meaningful_families": meaningful_families,
    "meaningful_lever_count": len(meaningful_families),
    "raw_family_moves": {key: round(value, 6) for key, value in raw_moves.items()},
    "dominant_family": dominant_family,
    "dominant_family_share": round(dominant_family_share, 6),
    "aligned_pair_count": aligned_pairs,
    "coordination_issues": coordination_issues,
    "changed_products": changed_products,
    "moved_product_keys": moved_products,
    "coordination_score": round(coordination_score, 4),
  }


def _normalize_year1_patch_for_existing_products(
  financials_year1_json: Dict[str, Any],
  patch: Dict[str, Any],
) -> Dict[str, Any]:
  next_patch = _clone(patch or {})
  if not isinstance(next_patch, dict):
    return {}
  product_overrides = next_patch.get("product_overrides")
  product_overrides = product_overrides if isinstance(product_overrides, dict) else {}
  if not product_overrides:
    return next_patch
  lobs = financials_year1_json.get("lobs")
  lobs = lobs if isinstance(lobs, list) else []
  product_meta: Dict[str, Dict[str, Any]] = {}
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip()
    for product in (lob.get("products") or []):
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip()
      if not product_name:
        continue
      key = f"{lob_name}::{product_name}".strip(":")
      product_meta[key.lower()] = {
        "unit_cadence": str(product.get("unit_cadence") or "").strip().lower(),
      }
      product_meta[product_name.lower()] = {
        "unit_cadence": str(product.get("unit_cadence") or "").strip().lower(),
      }
  normalized_overrides: Dict[str, Dict[str, Any]] = {}
  for product_key, override in product_overrides.items():
    if not isinstance(override, dict):
      continue
    normalized_override = _clone(override)
    meta = product_meta.get(str(product_key or "").strip().lower()) or {}
    cadence = str(meta.get("unit_cadence") or "").strip().lower()
    if "avg_units_per_period_year1" in normalized_override:
      avg_units = normalized_override.get("avg_units_per_period_year1")
      if cadence == "weekly" and "avg_units_per_week_year1" not in normalized_override:
        normalized_override["avg_units_per_week_year1"] = avg_units
      elif cadence == "monthly" and "avg_units_per_month_year1" not in normalized_override:
        normalized_override["avg_units_per_month_year1"] = avg_units
      elif cadence not in {"weekly", "monthly"} and "avg_active_units_year1" not in normalized_override:
        normalized_override["avg_active_units_year1"] = avg_units
    if "units_per_period_capacity" in normalized_override:
      capacity = normalized_override.get("units_per_period_capacity")
      if cadence == "weekly" and "units_per_week_capacity" not in normalized_override:
        normalized_override["units_per_week_capacity"] = capacity
      elif cadence == "monthly" and "units_per_month_capacity" not in normalized_override:
        normalized_override["units_per_month_capacity"] = capacity
      elif cadence not in {"weekly", "monthly"} and "concurrent_capacity_units" not in normalized_override:
        normalized_override["concurrent_capacity_units"] = capacity
    if "operating_periods_per_year" in normalized_override:
      periods = normalized_override.get("operating_periods_per_year")
      if cadence == "weekly" and "operating_weeks_per_year" not in normalized_override:
        normalized_override["operating_weeks_per_year"] = periods
      elif cadence == "monthly" and "operating_months_per_year" not in normalized_override:
        normalized_override["operating_months_per_year"] = periods
      elif cadence not in {"weekly", "monthly"} and "annual_turns_per_year" not in normalized_override:
        normalized_override["annual_turns_per_year"] = periods
    normalized_overrides[str(product_key)] = normalized_override
  next_patch["product_overrides"] = normalized_overrides
  return next_patch


def _label_and_rationale_from_patches(
  exact_patches: Dict[str, Any],
  *,
  archetype: str,
  archetype_display: str,
  dominant_tradeoff: str,
) -> Tuple[str, str, List[str]]:
  families: List[str] = []
  year1_patch = exact_patches.get("financials_year1_patch") if isinstance(exact_patches.get("financials_year1_patch"), dict) else {}
  financials_patch = exact_patches.get("financials_patch") if isinstance(exact_patches.get("financials_patch"), dict) else {}
  if "unit_price" in year1_patch:
    families.append("price")
  if "utilization_rate" in year1_patch:
    families.append("utilization")
  if exact_patches.get("people_role_updates"):
    families.append("hire_delay")
  if exact_patches.get("people_compensation_updates") or "current_payroll" in financials_patch:
    families.append("payroll")
  if "other_operating_expense" in financials_patch:
    families.append("other_opex")
  if "marketing_total_year1" in financials_patch or exact_patches.get("marketing_model_patch"):
    families.append("marketing")
  if "cogs_total_year1" in financials_patch:
    families.append("cogs")
  families = list(dict.fromkeys(families))
  label_bits: List[str] = []
  if "marketing" in families and archetype == "growth":
    label_bits.append("Marketing-heavy path")
  if "utilization" in families:
    label_bits.append("Improve utilization")
  if "hire_delay" in families:
    label_bits.append("Delay hiring")
  if "price" in families and "marketing" not in families:
    label_bits.append("Reprice Year 1")
  if "other_opex" in families and not label_bits:
    label_bits.append("Reset operating overhead")
  if not label_bits:
    label_bits.append("Year-1 reset")
  label = f"{archetype_display}: " + " + ".join(label_bits)
  rationale = str(dominant_tradeoff or "").strip() or "rebalances the Year-1 plan to make the business more believable."
  if "marketing" in families and archetype == "growth":
    rationale = "This path leans more heavily on marketing support while preserving a believable growth story."
  return label, rationale, families


def _exact_patches_from_solution(
  *,
  solution: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Dict[str, Any]:
  del ops_json
  year1_patch: Dict[str, Any] = {}
  financials_patch: Dict[str, Any] = {}
  marketing_patch: Dict[str, Any] = {}
  if solution.get("child_product_solution") and str(direct_inputs.get("solve_mode") or "") == "child_first":
    overrides: Dict[str, Any] = {}
    for basis in direct_inputs.get("product_driver_basis") or []:
      if not isinstance(basis, dict):
        continue
      key = str(basis.get("product_key") or "").strip()
      solved = (solution.get("child_product_solution") or {}).get(key) if isinstance(solution.get("child_product_solution"), dict) else None
      if not isinstance(solved, dict):
        continue
      product_override: Dict[str, Any] = {}
      if _safe_float(solved.get("unit_price")) != _safe_float(basis.get("unit_price")):
        product_override["unit_price"] = round(_safe_float(solved.get("unit_price")), 2)
      if _safe_float(solved.get("utilization_rate")) != _safe_float(basis.get("utilization_rate")):
        product_override["utilization_rate"] = round(_safe_float(solved.get("utilization_rate")), 6)
      if _safe_float(solved.get("avg_units_per_period_year1")) != _safe_float(basis.get("avg_units_per_period_year1")):
        product_override["avg_units_per_period_year1"] = round(_safe_float(solved.get("avg_units_per_period_year1")), 4)
      if product_override:
        overrides[key] = product_override
    if overrides:
      year1_patch["product_overrides"] = overrides
  else:
    if _safe_float(solution.get("price")) > 0 and abs(_safe_float(solution.get("price")) - _safe_float(direct_inputs.get("current_price"))) > 1e-6:
      year1_patch["unit_price"] = round(_safe_float(solution.get("price")), 2)
    util = solution.get("utilization_rate")
    if util is not None and abs(_safe_float(util) - _safe_float(direct_inputs.get("current_util"))) > 1e-6:
      year1_patch["utilization_rate"] = round(_safe_float(util), 6)
  solved_revenue = _safe_float(solution.get("annual_units_total")) * max(_safe_float(solution.get("price")), _safe_float(direct_inputs.get("current_price")))
  current_revenue = _safe_float(direct_inputs.get("current_revenue"))
  if solved_revenue > 0 and abs(solved_revenue - current_revenue) > 1.0:
    year1_patch["company_revenue_total_year1"] = round(solved_revenue, 2)
  solved_cogs = _safe_float(solution.get("cogs_total_year1"))
  if solved_cogs > 0 and abs(solved_cogs - _safe_float(direct_inputs.get("current_cogs"))) > 1.0:
    financials_patch["cogs_total_year1"] = round(solved_cogs, 2)
    year1_patch["company_cogs_total_year1"] = round(solved_cogs, 2)
  solved_marketing = _safe_float(solution.get("marketing_total_year1"))
  if solved_marketing >= 0 and abs(solved_marketing - _safe_float(direct_inputs.get("current_marketing"))) > 1.0:
    financials_patch["marketing_total_year1"] = round(solved_marketing, 2)
    year1_patch["company_marketing_total_year1"] = round(solved_marketing, 2)
  solved_opex = _safe_float(solution.get("other_operating_expense"))
  if solved_opex >= 0 and abs(solved_opex - _safe_float(direct_inputs.get("current_other_opex"))) > 1.0:
    financials_patch["other_operating_expense"] = round(solved_opex, 2)
    year1_patch["other_operating_expense_total_year1"] = round(solved_opex, 2)
  target_payroll = (
    _safe_float(solution.get("payroll_total_year1"))
    or _safe_float(solution.get("current_payroll_total"))
    or _safe_float(solution.get("fixed_people_payroll_target"))
  )
  fixed_people_target = _safe_float(solution.get("fixed_people_payroll_target"))
  if target_payroll > 0 and abs(target_payroll - _safe_float(direct_inputs.get("current_payroll_total"))) > 1.0:
    financials_patch["current_payroll"] = round(target_payroll, 2)
    financials_patch["payroll_total_year1"] = round(target_payroll, 2)
    year1_patch["company_payroll_total_year1"] = round(target_payroll, 2)
    if fixed_people_target > 0 and abs(fixed_people_target - _safe_float(direct_inputs.get("fixed_people_payroll"))) > 1.0:
      financials_patch["fixed_people_payroll_target"] = round(fixed_people_target, 2)
  solved_expected_units = _safe_float(solution.get("marketing_support_units_year1"))
  if (
    bool(direct_inputs.get("marketing_demand_link"))
    and solved_expected_units >= 0
    and abs(solved_expected_units - _safe_float(direct_inputs.get("marketing_support_units_baseline"))) > 1.0
  ):
    marketing_patch["expected_units_year1"] = round(solved_expected_units, 2)
  role_updates: List[Dict[str, Any]] = []
  baseline_role_months = {
    str(item.get("role_title") or "").strip(): max(0, _safe_int(item.get("base_months")))
    for item in (direct_inputs.get("roles") or [])
    if isinstance(item, dict) and str(item.get("role_title") or "").strip()
  }
  for title, months in (solution.get("role_months") or {}).items():
    normalized_title = str(title or "").strip()
    if not normalized_title:
      continue
    if max(0, _safe_int(months)) == baseline_role_months.get(normalized_title, max(0, _safe_int(months))):
      continue
    role_updates.append(
      {
        "role_title": normalized_title,
        "months_until_hire": max(0, _safe_int(months)),
      }
    )
  compensation_updates: List[Dict[str, Any]] = []
  current_staff = [item for item in (direct_inputs.get("current_staff") or []) if isinstance(item, dict)]
  current_total = max(1.0, _safe_float(direct_inputs.get("fixed_people_payroll")) or _safe_float(direct_inputs.get("current_payroll_total")))
  target_fixed = _safe_float(solution.get("fixed_people_payroll_target"))
  if target_fixed > 0 and current_staff and current_total > 0 and abs(target_fixed - current_total) > 1.0:
    ratio = target_fixed / current_total
    for person in current_staff:
      compensation_updates.append(
        {
          "full_name": str(person.get("full_name") or "").strip(),
          "role_title": str(person.get("role_title") or "").strip(),
          "annual_wage": round(_safe_float(person.get("annual_wage")) * ratio, 2),
        }
      )
  exact: Dict[str, Any] = {}
  if year1_patch:
    exact["financials_year1_patch"] = year1_patch
  if financials_patch:
    exact["financials_patch"] = financials_patch
  if marketing_patch:
    exact["marketing_model_patch"] = marketing_patch
  if role_updates:
    exact["people_role_updates"] = role_updates
  if compensation_updates:
    exact["people_compensation_updates"] = compensation_updates
  return exact


def _apply_exact_patches(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  exact_patches: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  next_ops = _clone(ops_json or {})
  next_people = _clone(people_json or {})
  next_financials = _clone(financials_json or {})
  next_year1 = _clone(financials_year1_json or {})
  next_marketing = _clone(marketing_model_json or {})
  exact_patches = exact_patches if isinstance(exact_patches, dict) else {}
  original_payroll = _safe_float(next_financials.get("payroll_total_year1") or next_financials.get("current_payroll"))
  patch = exact_patches.get("financials_patch")
  if isinstance(patch, dict):
    next_financials.update(_clone(patch))
  patch = exact_patches.get("financials_year1_patch")
  if isinstance(patch, dict):
    normalized_patch = _normalize_year1_patch_for_existing_products(next_year1, patch)
    next_year1 = apply_revenue_driver_patch(next_year1, normalized_patch)
    has_product_overrides = isinstance(normalized_patch.get("product_overrides"), dict) and bool(normalized_patch.get("product_overrides"))
    child_authoritative_keys = {
      "unit_cadence",
      "unit_price",
      "units_per_week_capacity",
      "units_per_month_capacity",
      "concurrent_capacity_units",
      "units_per_period_capacity",
      "avg_units_per_week_year1",
      "avg_units_per_month_year1",
      "avg_active_units_year1",
      "avg_units_per_period_year1",
      "operating_weeks_per_year",
      "operating_months_per_year",
      "annual_turns_per_year",
      "operating_periods_per_year",
      "utilization_rate",
      "company_revenue_total_year1",
    }
    scalar_patch = {
      key: value
      for key, value in normalized_patch.items()
      if key != "product_overrides" and not (has_product_overrides and key in child_authoritative_keys)
    }
    if scalar_patch:
      next_year1.update(scalar_patch)
  patch = exact_patches.get("marketing_model_patch")
  if isinstance(patch, dict):
    next_marketing.update(_clone(patch))
  for update in (exact_patches.get("people_role_updates") or []):
    if not isinstance(update, dict):
      continue
    role_title = str(update.get("role_title") or "").strip().lower()
    for role in (next_people.get("inferred_roles") or next_people.get("future_roles") or []):
      if not isinstance(role, dict):
        continue
      if str(role.get("role_title") or "").strip().lower() != role_title:
        continue
      role["months_until_hire"] = max(0, _safe_int(update.get("months_until_hire")))
  if isinstance(next_people.get("people"), list):
    people_map = {
      (str(item.get("full_name") or "").strip().lower(), str(item.get("role_title") or "").strip().lower()): item
      for item in next_people.get("people") or []
      if isinstance(item, dict)
    }
    for update in (exact_patches.get("people_compensation_updates") or []):
      if not isinstance(update, dict):
        continue
      key = (
        str(update.get("full_name") or "").strip().lower(),
        str(update.get("role_title") or "").strip().lower(),
      )
      person = people_map.get(key)
      if person is None:
        continue
      person["annual_wage"] = _safe_float(update.get("annual_wage"))
  if "current_payroll" in next_financials or "payroll_total_year1" in next_financials:
    current_payroll = _safe_float(next_financials.get("current_payroll") or next_financials.get("payroll_total_year1"))
    next_financials["current_payroll"] = round(current_payroll, 2)
    next_financials["payroll_total_year1"] = round(_safe_float(next_financials.get("payroll_total_year1") or current_payroll), 2)
    next_financials["baseline_payroll_year1"] = round(original_payroll, 2)
    next_financials["payroll_adjustment"] = round(current_payroll - original_payroll, 2)
  return next_ops, next_people, next_financials, next_year1, next_marketing
