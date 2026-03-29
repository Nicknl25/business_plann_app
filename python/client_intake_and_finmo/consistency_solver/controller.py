from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence

from .common import (
  _clone,
  _commercial_context_policy,
  _derive_commercial_archetype,
  _intensity_score,
  _safe_float,
  _safe_int,
  _severity_score,
  _unique_strings,
)


def _revenue_lever_id(lob_name: str, product_name: str, driver: str) -> str:
  return "::".join(["revenue", str(lob_name or "").strip(), str(product_name or "").strip(), str(driver or "").strip()])


def _simple_lever_id(section: str, label: str) -> str:
  return "::".join([str(section or "").strip(), str(label or "").strip()])


_CANONICAL_SIMPLE_LEVERS = {
  _simple_lever_id("expenses", "Cost of Goods Sold"),
  _simple_lever_id("expenses", "Marketing"),
  _simple_lever_id("expenses", "Payroll"),
  _simple_lever_id("expenses", "General & Administrative"),
}


def _all_model_input_levers(
  *,
  state_model: Optional[Dict[str, Any]] = None,
  direct_inputs: Optional[Dict[str, Any]] = None,
) -> List[str]:
  lever_catalog = _model_input_lever_catalog(state_model=state_model, direct_inputs=direct_inputs)
  if lever_catalog:
    return _unique_strings(sorted(str(key or "").strip() for key in lever_catalog.keys() if str(key or "").strip()))
  state_model = state_model if isinstance(state_model, dict) else {}
  direct_inputs = direct_inputs if isinstance(direct_inputs, dict) else {}
  product_basis = [
    item for item in (direct_inputs.get("product_driver_basis") or [])
    if isinstance(item, dict)
  ]
  if not product_basis:
    baseline_state = (state_model.get("baseline_state") or {}) if isinstance(state_model.get("baseline_state"), dict) else {}
    product_basis = _build_product_driver_basis(
      financials_year1_json=(baseline_state.get("financials_year1_json") or {}) if isinstance(baseline_state.get("financials_year1_json"), dict) else {},
      ops_json=(baseline_state.get("ops_json") or {}) if isinstance(baseline_state.get("ops_json"), dict) else {},
    )
  if not product_basis:
    product_basis = [{"lob_name": "LOB 1", "product_name": "Product 1"}]
  levers: List[str] = []
  for item in product_basis:
    lob_name = str(item.get("lob_name") or "").strip() or "LOB 1"
    product_name = str(item.get("product_name") or "").strip() or "Product 1"
    levers.extend(
      [
        _revenue_lever_id(lob_name, product_name, "Capacity"),
        _revenue_lever_id(lob_name, product_name, "Unit Price"),
        _revenue_lever_id(lob_name, product_name, "Utilization"),
      ]
    )
  levers.extend(
    [
      _simple_lever_id("expenses", "Cost of Goods Sold"),
      _simple_lever_id("expenses", "Marketing"),
      _simple_lever_id("expenses", "Payroll"),
      _simple_lever_id("expenses", "General & Administrative"),
    ]
  )
  return _unique_strings(levers)


def _model_input_lever_catalog(
  *,
  state_model: Optional[Dict[str, Any]] = None,
  direct_inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
  direct_inputs = direct_inputs if isinstance(direct_inputs, dict) else {}
  direct_model_input = direct_inputs.get("model_input_json") if isinstance(direct_inputs.get("model_input_json"), dict) else {}
  direct_catalog = direct_model_input.get("lever_catalog") if isinstance(direct_model_input.get("lever_catalog"), dict) else {}
  if direct_catalog:
    return {
      str(key): _clone(value) for key, value in direct_catalog.items()
      if str(key or "").strip() and isinstance(value, dict)
    }
  state_model = state_model if isinstance(state_model, dict) else {}
  fixed_facts = (state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}
  model_input_json = fixed_facts.get("model_input_json") if isinstance(fixed_facts.get("model_input_json"), dict) else {}
  catalog = model_input_json.get("lever_catalog") if isinstance(model_input_json.get("lever_catalog"), dict) else {}
  return {
    str(key): _clone(value) for key, value in catalog.items()
    if str(key or "").strip() and isinstance(value, dict)
  }


def _fallback_model_input_lever_detail(lever_id: str) -> Dict[str, Any]:
  lever_text = str(lever_id or "").strip()
  parts = [part.strip() for part in lever_text.split("::")]
  detail: Dict[str, Any] = {
    "lever_id": lever_text,
    "writable_full_quarters_only": True,
  }
  if len(parts) == 4 and parts[0] == "revenue":
    driver = parts[3]
    detail.update(
      {
        "section": "revenue",
        "named_range": "model_input_revenue",
        "lob": parts[1],
        "product": parts[2],
        "driver": driver,
        "label_path": f"{parts[1]} > {parts[2]} > {driver}",
        "value_kind": "ratio" if driver == "Utilization" else "direct_number",
        "input_semantics": (
          "utilization_ratio" if driver == "Utilization"
          else "currency_per_unit" if driver == "Unit Price"
          else "quarter_capacity_units" if driver == "Capacity"
          else "direct_input"
        ),
      }
    )
    return detail
  if len(parts) == 2:
    label = parts[1]
    semantics = "direct_input"
    value_kind = "direct_number"
    if label in {
      "Cost of Goods Sold",
      "Marketing",
      "Research & Development",
      "General & Administrative",
      "Interest Rate",
      "Depreciation",
      "Taxes",
    }:
      semantics = "percent_of_revenue"
      value_kind = "ratio"
    elif label in {"Accounts Receivable Days", "Inventory Days", "Accounts Payable Days"}:
      semantics = "days"
      value_kind = "day_count"
    detail.update(
      {
        "section": parts[0],
        "named_range": (
          "model_input_expenses" if parts[0] == "expenses"
          else "model_input_balancehseet" if parts[0] == "balance_sheet"
          else "model_input_schedules" if parts[0] == "schedules"
          else ""
        ),
        "label": label,
        "label_path": label,
        "value_kind": value_kind,
        "input_semantics": semantics,
      }
    )
  return detail


def _selection_lever_adjustment_plan(
  selection: Dict[str, Any],
  *,
  max_quarter: Optional[int] = None,
) -> List[Dict[str, Any]]:
  plan: List[Dict[str, Any]] = []
  for item in (selection.get("lever_adjustment_plan") or []):
    if not isinstance(item, dict):
      continue
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    quarter_start = max(1, _safe_int(item.get("quarter_start")) or 1)
    if max_quarter is not None and quarter_start > max_quarter:
      continue
    quarter_end = max(quarter_start, _safe_int(item.get("quarter_end")) or quarter_start)
    plan.append(
      {
        "lever_id": lever_id,
        "direction": str(item.get("direction") or "").strip().lower() or "hold",
        "intensity": str(item.get("intensity") or "").strip().lower() or "moderate",
        "quarter_start": quarter_start,
        "quarter_end": min(20, quarter_end),
        "rationale": str(item.get("rationale") or "").strip(),
      }
    )
  return plan


def _selection_allowed_model_input_levers(
  selection: Dict[str, Any],
  *,
  fallback_allowed: Optional[Sequence[Any]] = None,
  max_quarter: Optional[int] = None,
) -> List[str]:
  allowed = _unique_strings(selection.get("allowed_model_input_levers") or [])
  if fallback_allowed:
    allowed = _unique_strings(allowed + [str(item or "").strip() for item in fallback_allowed if str(item or "").strip()])
  plan_levers = [
    str(item.get("lever_id") or "").strip()
    for item in _selection_lever_adjustment_plan(selection, max_quarter=max_quarter)
    if str(item.get("lever_id") or "").strip()
  ]
  allowed = _unique_strings(allowed + plan_levers)
  forbidden = {
    str(item or "").strip()
    for item in (selection.get("forbidden_model_input_levers") or [])
    if str(item or "").strip()
  }
  if forbidden:
    allowed = [item for item in allowed if item not in forbidden]
  return _unique_strings(allowed)


def _selection_allowed_levers_matching(
  selection: Dict[str, Any],
  *,
  suffix: Optional[str] = None,
) -> List[str]:
  allowed = _selection_allowed_model_input_levers(selection)
  if not suffix:
    return allowed
  return [item for item in allowed if str(item or "").strip().endswith(suffix)]


def _selection_payroll_lever(selection: Dict[str, Any]) -> str:
  payroll_lever = _simple_lever_id("expenses", "Payroll")
  allowed = set(_selection_allowed_model_input_levers(selection))
  return payroll_lever if payroll_lever in allowed else ""


def _selection_marketing_lever(selection: Dict[str, Any]) -> str:
  marketing_lever = _simple_lever_id("expenses", "Marketing")
  allowed = set(_selection_allowed_model_input_levers(selection))
  return marketing_lever if marketing_lever in allowed else ""


def _selection_ganda_lever(selection: Dict[str, Any]) -> str:
  ganda_lever = _simple_lever_id("expenses", "General & Administrative")
  allowed = set(_selection_allowed_model_input_levers(selection))
  return ganda_lever if ganda_lever in allowed else ""


def _selection_cogs_lever(selection: Dict[str, Any]) -> str:
  cogs_lever = _simple_lever_id("expenses", "Cost of Goods Sold")
  allowed = set(_selection_allowed_model_input_levers(selection))
  return cogs_lever if cogs_lever in allowed else ""


def _iter_year1_products(financials_year1_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  items: List[Dict[str, Any]] = []
  for lob in (financials_year1_json or {}).get("lobs") or []:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip()
    for product in lob.get("products") or []:
      if not isinstance(product, dict):
        continue
      product_name = str(product.get("product_name") or "").strip()
      key = f"{lob_name}::{product_name}".strip(":").lower()
      items.append(
        {
          "lob_name": lob_name,
          "product_name": product_name,
          "product_key": key,
          "product": _clone(product),
        }
      )
  return items


def _build_product_driver_basis(
  *,
  financials_year1_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  basis: List[Dict[str, Any]] = []
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  for item in _iter_year1_products(year1):
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    unit_price = max(0.0, _safe_float(product.get("unit_price") or ops.get("unit_price")))
    periods = max(
      0.0,
      _safe_float(product.get("operating_periods_per_year"))
      or _safe_float(year1.get("operating_periods_per_year"))
      or 0.0,
    )
    capacity_per_period = max(
      0.0,
      _safe_float(product.get("units_per_period_capacity"))
      or _safe_float(year1.get("units_per_period_capacity"))
      or 0.0,
    )
    avg_units = max(0.0, _safe_float(product.get("avg_units_per_period_year1")))
    utilization = _safe_float(product.get("utilization_rate"))
    if avg_units <= 0 and utilization > 0 and capacity_per_period > 0:
      avg_units = capacity_per_period * utilization
    if utilization <= 0 and avg_units > 0 and capacity_per_period > 0:
      utilization = avg_units / max(capacity_per_period, 1e-9)
    if unit_price <= 0 or periods <= 0 or (capacity_per_period <= 0 and avg_units <= 0):
      continue
    annual_units = avg_units * periods
    annual_capacity_units = capacity_per_period * periods
    annual_revenue = annual_units * unit_price
    basis.append(
      {
        "lob_name": item.get("lob_name"),
        "product_name": item.get("product_name"),
        "product_key": item.get("product_key"),
        "unit_price": unit_price,
        "operating_periods_per_year": periods,
        "units_per_period_capacity": capacity_per_period,
        "avg_units_per_period_year1": avg_units,
        "utilization_rate": utilization if utilization > 0 else None,
        "annual_units": annual_units,
        "annual_capacity_units": annual_capacity_units,
        "annual_revenue": annual_revenue,
      }
    )
  return basis


def _gpt_blueprint_is_usable(selection: Dict[str, Any]) -> bool:
  if not isinstance(selection, dict):
    return False
  selected_ids = [str(item or "").strip() for item in (selection.get("selected_strategy_ids") or []) if str(item or "").strip()]
  if not selected_ids:
    return False
  target_margin_path = selection.get("target_margin_path")
  if not isinstance(target_margin_path, dict):
    return False
  allowed_model_input_levers = _unique_strings(selection.get("allowed_model_input_levers") or [])
  lever_plan = _selection_lever_adjustment_plan(selection)
  governed_period_groups = [item for item in (selection.get("governed_period_groups") or []) if isinstance(item, dict)]
  if not allowed_model_input_levers or not lever_plan or not governed_period_groups:
    return False
  plan_levers = {str(item.get("lever_id") or "").strip() for item in lever_plan if str(item.get("direction") or "").strip().lower() != "hold"}
  if not set(allowed_model_input_levers).intersection(plan_levers):
    return False
  severity = str(selection.get("severity_class") or "").strip().lower()
  minimum_strength = str(selection.get("minimum_package_strength") or "").strip().lower()
  directives = selection.get("controller_directives") if isinstance(selection.get("controller_directives"), dict) else {}
  effective_meaningful_levers = max(
    _safe_int(directives.get("minimum_meaningful_levers")),
    len(plan_levers),
  )
  effective_package_count = max(
    _safe_int(directives.get("minimum_package_count")),
    len(governed_period_groups),
  )
  if severity == "severe":
    if minimum_strength != "strong":
      return False
    if effective_meaningful_levers < 4:
      return False
    if effective_package_count < 2:
      return False
    if not directives.get("escalate_on_retry"):
      return False
  return True


def _build_strategy_catalog(
  *,
  state_model: Optional[Dict[str, Any]] = None,
  direct_inputs: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  all_levers = _all_model_input_levers(state_model=state_model, direct_inputs=direct_inputs)
  lever_catalog = _model_input_lever_catalog(state_model=state_model, direct_inputs=direct_inputs)
  def _details(levers: Sequence[str]) -> List[Dict[str, Any]]:
    return [
      _clone(lever_catalog.get(str(item or "").strip()) or _fallback_model_input_lever_detail(str(item or "").strip()))
      for item in _unique_strings(levers)
      if str(item or "").strip()
    ]
  price_levers = [item for item in all_levers if item.endswith("::Unit Price")]
  util_levers = [item for item in all_levers if item.endswith("::Utilization")]
  capacity_levers = [item for item in all_levers if item.endswith("::Capacity")]
  marketing = [_simple_lever_id("expenses", "Marketing")]
  ganda = [_simple_lever_id("expenses", "General & Administrative")]
  cogs = [_simple_lever_id("expenses", "Cost of Goods Sold")]
  payroll = [_simple_lever_id("expenses", "Payroll")]
  return [
    {
      "strategy_id": "reality_normalization_strategy",
      "strategy_name": "Reality normalization strategy",
      "archetype": "operations",
      "allowed_model_input_levers": _unique_strings(price_levers + util_levers + marketing + ganda + payroll),
      "allowed_model_input_lever_details": _details(price_levers + util_levers + marketing + ganda + payroll),
      "dominant_tradeoff": "normalizes unrealistic upside without pretending the business can over-earn indefinitely",
    },
    {
      "strategy_id": "viability_stabilize",
      "strategy_name": "Viability stabilize",
      "archetype": "operations",
      "allowed_model_input_levers": _unique_strings(price_levers + util_levers + ganda + payroll + cogs + marketing),
      "allowed_model_input_lever_details": _details(price_levers + util_levers + ganda + payroll + cogs + marketing),
      "dominant_tradeoff": "restores viable unit economics before outer-year growth",
    },
    {
      "strategy_id": "pricing_adjustment",
      "strategy_name": "Pricing adjustment",
      "archetype": "efficiency",
      "allowed_model_input_levers": _unique_strings(price_levers + util_levers + cogs + ganda),
      "allowed_model_input_lever_details": _details(price_levers + util_levers + cogs + ganda),
      "dominant_tradeoff": "leans on repricing and margin repair",
    },
    {
      "strategy_id": "demand_supported_growth",
      "strategy_name": "Demand supported growth",
      "archetype": "growth",
      "allowed_model_input_levers": _unique_strings(marketing + payroll + price_levers + util_levers + capacity_levers + ganda),
      "allowed_model_input_lever_details": _details(marketing + payroll + price_levers + util_levers + capacity_levers + ganda),
      "dominant_tradeoff": "builds support and demand together",
    },
    {
      "strategy_id": "staffing_ramp_adjustment",
      "strategy_name": "Staffing ramp adjustment",
      "archetype": "operations",
      "allowed_model_input_levers": _unique_strings(payroll + util_levers + ganda + price_levers + marketing),
      "allowed_model_input_lever_details": _details(payroll + util_levers + ganda + price_levers + marketing),
      "dominant_tradeoff": "slows staffing cost until the revenue base catches up",
    },
    {
      "strategy_id": "operational_balance_strategy",
      "strategy_name": "Operational balance strategy",
      "archetype": "operations",
      "allowed_model_input_levers": _unique_strings(price_levers + util_levers + ganda + payroll + cogs),
      "allowed_model_input_lever_details": _details(price_levers + util_levers + ganda + payroll + cogs),
      "dominant_tradeoff": "balances economics without a full growth reset",
    },
    {
      "strategy_id": "cost_structure_adjustment",
      "strategy_name": "Cost structure adjustment",
      "archetype": "efficiency",
      "allowed_model_input_levers": _unique_strings(ganda + cogs + payroll + marketing),
      "allowed_model_input_lever_details": _details(ganda + cogs + payroll + marketing),
      "dominant_tradeoff": "reduces cost load first",
    },
    ]


def _contextualize_deterministic_strategy(
  *,
  template: Dict[str, Any],
  diagnosis: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  del diagnosis
  next_strategy = _clone(template)
  violations = {
    str(item or "").strip()
    for item in ((constraint_engine_state or {}).get("violations") or [])
    if str(item or "").strip()
  }
  if "payroll_too_light" not in violations:
    return next_strategy
  strategy_id = str(next_strategy.get("strategy_id") or "").strip()
  price_levers = [item for item in (next_strategy.get("allowed_model_input_levers") or []) if str(item).endswith("::Unit Price")]
  util_levers = [item for item in (next_strategy.get("allowed_model_input_levers") or []) if str(item).endswith("::Utilization")]
  marketing_lever = _simple_lever_id("expenses", "Marketing")
  ganda_lever = _simple_lever_id("expenses", "General & Administrative")
  payroll_lever = _simple_lever_id("expenses", "Payroll")
  if strategy_id == "staffing_ramp_adjustment":
    next_strategy["allowed_model_input_levers"] = _unique_strings(price_levers + util_levers + [ganda_lever, payroll_lever, marketing_lever])
    next_strategy["dominant_tradeoff"] = "adds support payroll and tempers Year-1 throughput until the cost base is believable"
  elif strategy_id == "operational_balance_strategy":
    next_strategy["allowed_model_input_levers"] = _unique_strings(price_levers + util_levers + [ganda_lever, payroll_lever])
    next_strategy["dominant_tradeoff"] = "normalizes an under-supported plan by adding support cost and easing early throughput"
  elif strategy_id == "viability_stabilize":
    next_strategy["allowed_model_input_levers"] = _unique_strings(price_levers + util_levers + [marketing_lever, ganda_lever, payroll_lever])
    next_strategy["dominant_tradeoff"] = "normalizes Year-1 economics before preserving later growth"
  return next_strategy


def _diagnose_case(
  *,
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  violations = set(str(item or "").strip() for item in (state.get("violations") or []))
  revenue = max(1.0, _safe_float(baseline_summary.get("revenue")))
  ebitda_margin = _safe_float(baseline_summary.get("ebitda")) / revenue
  payroll_ratio = _safe_float(baseline_summary.get("payroll")) / revenue
  gross_margin = _safe_float(baseline_summary.get("gross_profit")) / revenue
  if violations.intersection({"gross_margin_too_high", "ebitda_margin_too_high", "utilization_too_high"}):
    primary = "pricing-driven"
  elif "payroll_too_light" in violations or "payroll_too_heavy" in violations or payroll_ratio > 0.45:
    primary = "payroll-driven"
  elif "gross_margin_too_low" in violations or gross_margin < 0.35:
    primary = "pricing-driven"
  elif "utilization_too_low" in violations:
    primary = "utilization-driven"
  else:
    primary = "mixed"
  severity = "mild"
  if ebitda_margin < -0.35 or len(violations.intersection({"ebitda_margin_too_low", "gross_margin_too_low", "payroll_too_heavy", "capacity_unsupported"})) >= 2:
    severity = "severe"
  elif ebitda_margin < -0.12 or violations:
    severity = "moderate"
  ebitda_band = state.get("ebitda_margin_band") if isinstance(state.get("ebitda_margin_band"), dict) else {}
  band_min = _safe_float((ebitda_band or {}).get("min"))
  band_max = _safe_float((ebitda_band or {}).get("max"))
  has_ebitda_band = bool(ebitda_band) and ("min" in ebitda_band or "max" in ebitda_band)
  structurally_valid_loss = (
    "ebitda_margin_too_low" in violations
    and not violations.intersection({"payroll_too_light", "payroll_too_heavy", "capacity_unsupported", "utilization_too_low", "gross_margin_too_low"})
  )
  target_margin_path = {
    "year1_min": round(max(-0.95, ebitda_margin + 0.22), 4),
    "year1_max": round(max(-0.75, ebitda_margin + 0.38), 4),
    "year2_min": round(max(-0.55, ebitda_margin + 0.42), 4),
    "year2_max": round(max(-0.25, ebitda_margin + 0.58), 4),
    "year3_min": round(max(-0.18, ebitda_margin + 0.62), 4),
    "year3_max": round(max(0.02, ebitda_margin + 0.72), 4),
  }
  if has_ebitda_band and "payroll_too_light" in violations:
    year1_min = band_min if band_min or band_min == 0 else max(-0.02, min(ebitda_margin, 0.0))
    year1_max = band_max if band_max or band_max == 0 else max(year1_min, year1_min + 0.08)
    target_margin_path = {
      "year1_min": round(year1_min, 4),
      "year1_max": round(max(year1_min, year1_max), 4),
      "year2_min": round(year1_min, 4),
      "year2_max": round(max(year1_min, year1_max), 4),
      "year3_min": round(year1_min, 4),
      "year3_max": round(max(year1_min, year1_max), 4),
    }
  if structurally_valid_loss:
    target_margin_path = {
      "year1_min": round(max(-0.12, ebitda_margin + 0.03), 4),
      "year1_max": round(max(0.01, ebitda_margin + 0.08), 4),
      "year2_min": round(max(-0.04, ebitda_margin + 0.08), 4),
      "year2_max": round(max(0.08, ebitda_margin + 0.14), 4),
      "year3_min": round(max(0.02, ebitda_margin + 0.14), 4),
      "year3_max": round(max(0.14, ebitda_margin + 0.2), 4),
    }
  return {
    "primary_cause": primary,
    "severity_class": severity,
    "minimum_package_strength": "strong" if severity == "severe" else "moderate",
      "preferred_strategy_ids": (
        ["reality_normalization_strategy", "pricing_adjustment"]
        if violations.intersection({"gross_margin_too_high", "ebitda_margin_too_high", "utilization_too_high"})
        else ["viability_stabilize", "operational_balance_strategy"]
        if structurally_valid_loss
        else ["staffing_ramp_adjustment", "reality_normalization_strategy"]
        if primary == "payroll-driven" and "payroll_too_light" in violations
        else ["staffing_ramp_adjustment", "operational_balance_strategy"]
        if primary == "payroll-driven"
        else ["pricing_adjustment", "viability_stabilize"]
      if primary == "pricing-driven"
      else ["demand_supported_growth", "operational_balance_strategy"]
    ),
    "target_margin_path": target_margin_path,
  }


def _build_solver_state_model(
  *,
  ops_json: Dict[str, Any],
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]],
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]] = None,
  benchmark_payload: Optional[Dict[str, Any]] = None,
  finmo_path: Optional[str] = None,
  business_facts: Optional[Dict[str, Any]] = None,
  model_input_json: Optional[Dict[str, Any]] = None,
  finmo_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  normalized_traits = normalized_traits if isinstance(normalized_traits, dict) else {}
  benchmark_payload = benchmark_payload if isinstance(benchmark_payload, dict) else {}
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  current_other_opex = _safe_float(baseline_summary.get("other_opex_non_rent"))
  current_marketing = _safe_float(baseline_summary.get("marketing"))
  current_revenue = max(1.0, _safe_float(baseline_summary.get("revenue")))
  current_cogs = _safe_float(baseline_summary.get("cogs"))
  current_cogs_ratio = min(0.98, current_cogs / current_revenue) if current_revenue > 0 else 0.0
  product_driver_basis = _build_product_driver_basis(
    financials_year1_json=financials_year1_json,
    ops_json=ops_json,
  )
  raw_product_count = len(_iter_year1_products(financials_year1_json if isinstance(financials_year1_json, dict) else {}))
  solve_mode = "child_first" if product_driver_basis and (raw_product_count == 0 or len(product_driver_basis) == raw_product_count) else "parent_fallback"
  commercial_context = _commercial_context_policy(
    normalized_traits=normalized_traits,
    ops_json=ops_json,
    current_marketing=current_marketing,
    current_other_opex=current_other_opex,
  )
  if commercial_context["opex_flexibility"] == "tight":
    opex_min = current_other_opex * max(0.0, 1.0 - _safe_float(commercial_context.get("other_opex_down_cap_ratio")))
    opex_max = current_other_opex * (1.0 + _safe_float(commercial_context.get("other_opex_up_cap_ratio")))
  else:
    opex_min = current_other_opex * max(0.0, 1.0 - _safe_float(commercial_context.get("other_opex_down_cap_ratio")))
    opex_max = current_other_opex * (1.0 + _safe_float(commercial_context.get("other_opex_up_cap_ratio")))
  marketing_intensity_band = state.get("marketing_intensity_band") if isinstance(state.get("marketing_intensity_band"), dict) else {}
  marketing_min_ratio = max(0.0, _safe_float((marketing_intensity_band or {}).get("min")))
  marketing_max_ratio = max(marketing_min_ratio, _safe_float((marketing_intensity_band or {}).get("max")) or marketing_min_ratio)
  expected_units = max(0.0, _safe_float((marketing_model_json or {}).get("expected_units_year1")))
  supportable_units = state.get("supportable_unit_range") if isinstance(state.get("supportable_unit_range"), dict) else {}
  supportable_units_min = max(0.0, _safe_float((supportable_units or {}).get("min")))
  supportable_units_max = max(supportable_units_min, _safe_float((supportable_units or {}).get("max")) or supportable_units_min)
  units_per_marketing_dollar = (
    expected_units / max(current_marketing, 1e-9)
    if current_marketing > 0 and expected_units > 0
    else 0.0
  )
  revenue_marketing_floor = current_revenue * marketing_min_ratio if current_revenue > 0 else 0.0
  revenue_marketing_cap = current_revenue * marketing_max_ratio if current_revenue > 0 and marketing_max_ratio > 0 else None
  units_based_marketing_cap = (
    supportable_units_max / max(units_per_marketing_dollar, 1e-9)
    if units_per_marketing_dollar > 0 and supportable_units_max > 0
    else None
  )
  marketing_down_floor_total = current_marketing * max(0.0, 1.0 - _safe_float(commercial_context.get("marketing_down_cap_ratio")))
  marketing_up_cap_total = current_marketing * (1.0 + _safe_float(commercial_context.get("marketing_up_cap_ratio")))
  marketing_min_total = revenue_marketing_floor
  if current_marketing > 0 and (revenue_marketing_cap is None or current_marketing <= revenue_marketing_cap + 0.01):
    marketing_min_total = max(marketing_min_total, marketing_down_floor_total)
  if revenue_marketing_cap is not None and units_based_marketing_cap is not None:
    marketing_max_total = min(revenue_marketing_cap, units_based_marketing_cap, marketing_up_cap_total)
  elif revenue_marketing_cap is not None:
    marketing_max_total = min(revenue_marketing_cap, marketing_up_cap_total)
  elif units_based_marketing_cap is not None:
    marketing_max_total = min(units_based_marketing_cap, marketing_up_cap_total)
  else:
    marketing_max_total = marketing_up_cap_total if current_marketing > 0 else 0.0
  marketing_max_total = max(marketing_min_total, marketing_max_total)
  gross_margin_band = state.get("gross_margin_band") if isinstance(state.get("gross_margin_band"), dict) else {}
  cogs_ratio_min = max(0.0, 1.0 - (_safe_float((gross_margin_band or {}).get("max")) or max(0.0, 1.0 - current_cogs_ratio)))
  cogs_ratio_max = min(0.98, 1.0 - (_safe_float((gross_margin_band or {}).get("min")) or max(0.0, 1.0 - current_cogs_ratio)))
  diagnosis = _diagnose_case(baseline_summary=baseline_summary, constraint_engine_state=state)
  return {
    "baseline_summary": _clone(baseline_summary),
    "baseline_state": {
      "ops_json": _clone(ops_json),
      "target_market_json": _clone(target_market_json or {}),
      "people_json": _clone(people_json),
      "financials_json": _clone(financials_json),
      "financials_year1_json": _clone(financials_year1_json),
      "fulfillment_json": _clone(fulfillment_json or {}),
      "marketing_model_json": _clone(marketing_model_json or {}),
    },
    "constraint_engine_state": _clone(state),
    "normalized_traits": _clone(normalized_traits),
    "benchmark_payload": _clone(benchmark_payload),
    "fixed_facts": {
      "business_type": str(normalized_traits.get("business_type") or ops_json.get("business_type") or "").strip(),
      "business_stage": str(normalized_traits.get("business_stage") or ops_json.get("business_stage") or "").strip(),
      "capacity_driver": str(normalized_traits.get("capacity_driver") or ops_json.get("capacity_driver") or "").strip(),
      "sales_modality": str(normalized_traits.get("sales_modality") or ops_json.get("sales_modality") or "").strip(),
      "customer_type": str(normalized_traits.get("customer_type") or ops_json.get("customer_type") or "").strip(),
      "unit_cadence": str(normalized_traits.get("unit_cadence") or ops_json.get("unit_cadence") or "").strip(),
      "commercial_context": commercial_context,
      "product_driver_basis": _clone(product_driver_basis),
      "baseline_units_year1": max(
        0.0,
        sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_driver_basis),
        (_safe_float(financials_year1_json.get("avg_units_per_period_year1")) * max(1.0, _safe_float(financials_year1_json.get("operating_periods_per_year")) or 12.0)),
      ),
      "physical_capacity_units_year1": max(
        0.0,
        sum(max(0.0, _safe_float(item.get("annual_capacity_units"))) for item in product_driver_basis),
        (_safe_float((state.get("current_metrics") or {}).get("capacity_units_year1")) if isinstance(state.get("current_metrics"), dict) else 0.0),
      ),
      "current_staff": _clone([item for item in (people_json.get("people") or []) if isinstance(item, dict)]),
      "constraint_engine_state": _clone(state),
      "finmo_path": str(finmo_path or "").strip(),
      "business_facts": _clone(business_facts or {}),
      "model_input_json": _clone(model_input_json or {}),
      "finmo_json": _clone(finmo_json or {}),
    },
    "constraint_profile": {
      "constraint_engine_violations": list(state.get("violations") or []),
      "current_metrics": _clone(state.get("current_metrics") or {}),
      "supportable_unit_range": _clone(state.get("supportable_unit_range") or {}),
      "supportable_revenue_range": _clone(state.get("supportable_revenue_range") or {}),
      "utilization_envelope": _clone(state.get("utilization_range") or {}),
      "gross_margin_band": _clone(state.get("gross_margin_band") or {}),
      "ebitda_margin_band": _clone(state.get("ebitda_margin_band") or {}),
      "payroll_intensity_band": _clone(state.get("payroll_intensity_band") or {}),
      "opex_intensity_band": _clone(state.get("opex_intensity_band") or {}),
      "marketing_intensity_band": _clone(state.get("marketing_intensity_band") or {}),
      "marketing_envelope": {
        "baseline": round(current_marketing, 2),
        "min": round(marketing_min_total, 2),
        "max": round(marketing_max_total, 2),
        "enabled": marketing_max_total > marketing_min_total + 0.01,
        "commercial_role": str(commercial_context.get("marketing_role") or "").strip(),
      },
      "demand_curve": {
        "enabled": bool(commercial_context.get("marketing_demand_link")) and units_per_marketing_dollar > 0,
        "units_per_marketing_dollar": round(units_per_marketing_dollar, 6),
        "baseline_supported_units": round(expected_units, 4),
      },
      "price_envelope": {
        "baseline": round(
          _safe_float(financials_year1_json.get("unit_price")) or _safe_float(ops_json.get("unit_price")),
          4,
        ),
      },
      "cogs_envelope": {
        "baseline_ratio": round(current_cogs_ratio, 6),
        "min_ratio": round(cogs_ratio_min, 6),
        "max_ratio": round(max(cogs_ratio_min, cogs_ratio_max), 6),
      },
      "current_revenue": round(current_revenue, 2),
      "current_cogs": round(current_cogs, 2),
      "current_interest": round(_safe_float(baseline_summary.get("interest")), 2),
      "rent_annualized": round(_safe_float(baseline_summary.get("rent_annualized")), 2),
      "other_opex_envelope": {
        "min": round(opex_min, 2),
        "max": round(opex_max, 2),
        "flexibility": commercial_context["opex_flexibility"],
        "baseline": round(current_other_opex, 2),
      },
      "marketing_children": {
        "baseline_expected_units_year1": round(expected_units, 4),
        "reachable_market": round(_safe_float((marketing_model_json or {}).get("reachable_market")), 4),
      },
    },
    "objective_policy": {
      "healthy_ebitda_margin_ratio": 0.05,
      "distortion_weights": {
        "price_up": 14.0,
        "price_down": 18.0,
        "util_up": 4.0,
        "util_down": 5.0,
        "marketing_up": 5.0,
        "marketing_down": 4.0,
        "other_opex_down": 2.5,
        "other_opex_up": 3.0,
        "cogs_down": 2.0,
        "cogs_up": 2.5,
        "hire_delay": 5.5,
        "hire_advance": 3.5,
        "payroll_down": 5.5,
        "payroll_up": 3.5,
      },
      "diagnosis": diagnosis,
    },
    "controllable_drivers": {
      "people": {
        "inferred_roles": [
          {
            "role_title": str(item.get("role_title") or item.get("full_name") or "").strip(),
            "annual_wage": max(0.0, _safe_float(item.get("annual_wage"))),
            "base_months": max(0, _safe_int(item.get("months_until_hire"))),
            "min_months": max(0, _safe_int(item.get("months_until_hire"))),
            "max_months": max(60, max(0, _safe_int(item.get("months_until_hire"))) + 60),
          }
          for item in ((people_json.get("inferred_roles") or people_json.get("future_roles") or []))
          if isinstance(item, dict) and str(item.get("role_title") or item.get("full_name") or "").strip()
        ],
      },
    },
    "solve_mode": solve_mode,
  }


def _build_direct_solver_inputs(*, state_model: Dict[str, Any]) -> Dict[str, Any]:
  baseline_summary = (state_model.get("baseline_summary") or {}) if isinstance(state_model, dict) else {}
  baseline_state = (state_model.get("baseline_state") or {}) if isinstance(state_model.get("baseline_state"), dict) else {}
  financials = (baseline_state.get("financials_json") or {}) if isinstance(baseline_state.get("financials_json"), dict) else {}
  year1 = (baseline_state.get("financials_year1_json") or {}) if isinstance(baseline_state.get("financials_year1_json"), dict) else {}
  people = (baseline_state.get("people_json") or {}) if isinstance(baseline_state.get("people_json"), dict) else {}
  profile = (state_model.get("constraint_profile") or {}) if isinstance(state_model.get("constraint_profile"), dict) else {}
  fixed_facts = (state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}
  model_input_json = (fixed_facts.get("model_input_json") or {}) if isinstance(fixed_facts.get("model_input_json"), dict) else {}
  finmo_json = (fixed_facts.get("finmo_json") or {}) if isinstance(fixed_facts.get("finmo_json"), dict) else {}
  marketing_envelope = (profile.get("marketing_envelope") or {}) if isinstance(profile.get("marketing_envelope"), dict) else {}
  demand_curve = (profile.get("demand_curve") or {}) if isinstance(profile.get("demand_curve"), dict) else {}
  price_envelope = (profile.get("price_envelope") or {}) if isinstance(profile.get("price_envelope"), dict) else {}
  cogs_envelope = (profile.get("cogs_envelope") or {}) if isinstance(profile.get("cogs_envelope"), dict) else {}
  commercial_context = (fixed_facts.get("commercial_context") or {}) if isinstance(fixed_facts.get("commercial_context"), dict) else {}
  solve_mode = str(state_model.get("solve_mode") or "parent_fallback")
  revenue = max(1.0, _safe_float(baseline_summary.get("revenue")))
  current_metrics = profile.get("current_metrics") if isinstance(profile.get("current_metrics"), dict) else {}
  product_driver_basis = _clone(fixed_facts.get("product_driver_basis") or [])
  weighted_child_price = _safe_float(current_metrics.get("weighted_child_price"))
  weighted_child_util = _safe_float(current_metrics.get("weighted_child_utilization_rate"))
  child_units_year1 = max(
    0.0,
    _safe_float(current_metrics.get("units_year1")),
    sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_driver_basis if isinstance(item, dict)),
  )
  avg_units = _safe_float(year1.get("avg_units_per_period_year1"))
  periods = max(1.0, _safe_float(year1.get("operating_periods_per_year")) or 12.0)
  current_price = (
    weighted_child_price if solve_mode == "child_first" and weighted_child_price > 0 else 0.0
  ) or _safe_float((price_envelope or {}).get("baseline")) or _safe_float(year1.get("unit_price")) or (revenue / max(avg_units * periods, 1.0))
  current_util = (
    weighted_child_util if solve_mode == "child_first" and weighted_child_util > 0 else 0.0
  ) or _safe_float(year1.get("utilization_rate")) or _safe_float((profile.get("utilization_envelope") or {}).get("min")) or 0.65
  baseline_units = (
    child_units_year1 if solve_mode == "child_first" and child_units_year1 > 0 else 0.0
  ) or (avg_units * periods if avg_units > 0 else revenue / max(current_price, 1.0))
  supportable_units = profile.get("supportable_unit_range") or {}
  units_min = _safe_float(supportable_units.get("min")) or (baseline_units * 0.9)
  units_max = _safe_float(supportable_units.get("max")) or (baseline_units * 1.1)
  cogs = _safe_float(baseline_summary.get("cogs"))
  current_cogs_ratio = _safe_float((cogs_envelope or {}).get("baseline_ratio")) or (min(0.98, cogs / revenue) if revenue > 0 else 0.0)
  gross_band = profile.get("gross_margin_band") or {}
  cogs_ratio_min = _safe_float((cogs_envelope or {}).get("min_ratio")) or max(0.0, 1.0 - (_safe_float(gross_band.get("max")) or max(0.0, 1.0 - current_cogs_ratio)))
  cogs_ratio_max = _safe_float((cogs_envelope or {}).get("max_ratio")) or min(0.98, 1.0 - (_safe_float(gross_band.get("min")) or max(0.0, 1.0 - current_cogs_ratio)))
  marketing_intensity_band = profile.get("marketing_intensity_band") or {}
  current_marketing = _safe_float(baseline_summary.get("marketing"))
  marketing_min = _safe_float((marketing_envelope or {}).get("min")) or max(0.0, revenue * (_safe_float(marketing_intensity_band.get("min")) or (current_marketing / revenue if revenue > 0 else 0.0)))
  marketing_upper = _safe_float((marketing_envelope or {}).get("max")) or max(marketing_min, revenue * (_safe_float(marketing_intensity_band.get("max")) or (current_marketing / revenue if revenue > 0 else 0.0)))
  other_opex_env = profile.get("other_opex_envelope") or {}
  current_other_opex = _safe_float(baseline_summary.get("other_opex_non_rent"))
  current_payroll_total = _safe_float(baseline_summary.get("payroll"))
  current_staff = [item for item in (people.get("people") or []) if isinstance(item, dict)]
  roles = [item for item in (people.get("inferred_roles") or people.get("future_roles") or []) if isinstance(item, dict)]
  fixed_people_payroll = sum(max(0.0, _safe_float(item.get("annual_wage"))) for item in current_staff)
  role_inputs: List[Dict[str, Any]] = []
  planned_payroll = 0.0
  baseline_adjustable_active_months = 0.0
  adjustable_role_month_cost_floor = 0.0
  for role in roles:
    annual = max(0.0, _safe_float(role.get("annual_wage")))
    months = max(0, _safe_int(role.get("months_until_hire")))
    base_months = max(0, 12 - min(12, months))
    year1_amount = annual * (base_months / 12.0)
    planned_payroll += year1_amount
    baseline_adjustable_active_months += base_months
    if annual > 0:
      adjustable_role_month_cost_floor = max(adjustable_role_month_cost_floor, annual / 12.0)
    role_inputs.append(
      {
        "role_title": str(role.get("role_title") or role.get("full_name") or "").strip(),
        "base_months": months,
        "min_months": months,
        "max_months": max(months, months + 60),
        "annual_wage": annual,
        "baseline_year1_amount": year1_amount,
      }
    )
  active_role_months_year1 = max(0.0, _safe_float(current_metrics.get("active_role_months_year1")))
  fixed_active_role_months = min(active_role_months_year1, max(0.0, 12.0 * len(current_staff)))
  units_per_active_role_month = (
    baseline_units / max(active_role_months_year1, 1e-9)
    if active_role_months_year1 > 0 and baseline_units > 0
    else 0.0
  )
  structural_payroll_floor = max(
    _safe_float(financials.get("current_payroll")),
    fixed_people_payroll,
    _safe_float(current_metrics.get("structural_payroll_floor")),
  )
  people_payroll_floor = max(
    fixed_people_payroll,
    _safe_float(current_metrics.get("people_payroll_floor")),
  )
  payroll_support_basis = "floor"
  if roles:
    payroll_support_basis = "role_months"
  elif fixed_people_payroll > 0:
    payroll_support_basis = "payroll"
  marketing_children = (profile.get("marketing_children") or {}) if isinstance(profile.get("marketing_children"), dict) else {}
  baseline_expected_units = max(0.0, _safe_float(marketing_children.get("baseline_expected_units_year1")))
  target_payroll_max_total = max(current_payroll_total, people_payroll_floor)
  if "payroll_too_light" in set((state_model.get("constraint_profile") or {}).get("constraint_engine_violations") or []):
    target_payroll_max_total = max(target_payroll_max_total, structural_payroll_floor, fixed_people_payroll + planned_payroll)
  result = {
    "solve_mode": solve_mode,
    "current_revenue": revenue,
    "baseline_units": baseline_units,
    "capacity_units": max(0.0, _safe_float(fixed_facts.get("physical_capacity_units_year1")) or units_max),
    "current_price": current_price,
    "current_util": current_util,
    "current_cogs": cogs,
    "current_cogs_ratio": current_cogs_ratio,
    "current_marketing": current_marketing,
    "marketing_support_units_baseline": max(baseline_expected_units, _safe_float((demand_curve or {}).get("baseline_supported_units"))),
    "marketing_support_units_min": min(max(baseline_expected_units, _safe_float((demand_curve or {}).get("baseline_supported_units"))), units_max),
    "marketing_support_units_max": max(baseline_expected_units, units_max, _safe_float((demand_curve or {}).get("baseline_supported_units"))),
    "marketing_units_per_dollar": _safe_float((demand_curve or {}).get("units_per_marketing_dollar")) or ((baseline_expected_units / current_marketing) if current_marketing > 0 and baseline_expected_units > 0 else 0.0),
    "marketing_demand_link": bool(commercial_context.get("marketing_demand_link")),
    "growth_demand_mode_enabled": bool(commercial_context.get("growth_demand_mode_enabled")) and bool((demand_curve or {}).get("enabled")) and (_safe_float((demand_curve or {}).get("units_per_marketing_dollar")) > 0),
    "current_other_opex": current_other_opex,
    "opex_ratio_min": _safe_float((profile.get("opex_intensity_band") or {}).get("min")) or (current_other_opex / revenue if revenue > 0 else 0.0),
    "opex_ratio_max": _safe_float((profile.get("opex_intensity_band") or {}).get("max")) or (current_other_opex / revenue if revenue > 0 else 0.0),
    "rent_annualized": _safe_float(financials.get("monthly_rent_expense")) * 12.0,
    "current_interest": _safe_float(financials.get("annual_interest_payment")),
    "fixed_people_payroll": round(fixed_people_payroll, 2),
    "current_payroll_total": round(current_payroll_total, 2),
    "baseline_planned_payroll": round(planned_payroll, 2),
    "baseline_payroll_support": round(current_payroll_total, 2),
    "people_payroll_floor": round(people_payroll_floor, 2),
    "structural_payroll_floor": round(structural_payroll_floor, 2),
    "structural_payroll_base": round(structural_payroll_floor, 2),
    "payroll_support_basis": payroll_support_basis,
    "units_per_active_role_month": round(units_per_active_role_month, 6),
    "fixed_active_role_months": round(fixed_active_role_months, 6),
    "baseline_adjustable_active_months": round(max(0.0, baseline_adjustable_active_months), 6),
    "adjustable_role_month_cost_floor": round(
      max(
        0.0,
        adjustable_role_month_cost_floor,
        (_safe_float(current_metrics.get("adjustable_role_month_cost_floor"))),
      ),
      2,
    ),
    "constraint_violations": list((state_model.get("constraint_profile") or {}).get("constraint_engine_violations") or []),
    "current_staff": _clone(current_staff),
    "roles": role_inputs,
    "product_driver_basis": product_driver_basis,
    "constraint_profile": _clone(profile),
    "model_input_json": _clone(model_input_json),
    "finmo_json": _clone(finmo_json),
    "units_min": units_min,
    "units_max": units_max,
    "util_min": _safe_float((profile.get("utilization_envelope") or {}).get("min")) or max(0.0, current_util - 0.08),
    "util_max": _safe_float((profile.get("utilization_envelope") or {}).get("max")) or min(0.98, current_util + 0.08),
    "price_lower": max(1.0, _safe_float((price_envelope or {}).get("min")) or (current_price * 0.95)),
    "price_upper": max(current_price, _safe_float((price_envelope or {}).get("max")) or (current_price * 1.08)),
    "cogs_ratio_min": max(0.0, cogs_ratio_min),
    "cogs_ratio_max": min(0.98, max(cogs_ratio_min, cogs_ratio_max)),
    "marketing_min": round(marketing_min, 2),
    "marketing_upper": round(marketing_upper, 2),
    "other_opex_min": round(_safe_float(other_opex_env.get("min")) or current_other_opex, 2),
    "other_opex_max": round(_safe_float(other_opex_env.get("max")) or current_other_opex, 2),
    "target_payroll_min_total": round(people_payroll_floor, 2),
    "target_payroll_max_total": round(target_payroll_max_total, 2),
  }
  return result

def _build_runtime_strategy(strategy_id: str, strategy_selection: Dict[str, Any], diagnosis: Dict[str, Any]) -> Dict[str, Any]:
  constraints: Dict[str, Any] = {}
  lever_plan = _selection_lever_adjustment_plan(strategy_selection)
  allowed_model_input_levers = _selection_allowed_model_input_levers(
    strategy_selection,
    fallback_allowed=strategy_selection.get("allowed_model_input_levers") or [],
  )
  governed_retry_attempt = _safe_int(diagnosis.get("governed_retry_attempt"))
  severity = _severity_score(strategy_selection.get("severity_class") or diagnosis.get("severity_class"))

  def _matches(plan_item: Dict[str, Any], suffix: str, direction: str) -> bool:
    lever_id = str(plan_item.get("lever_id") or "").strip()
    if not lever_id.endswith(suffix):
      return False
    return str(plan_item.get("direction") or "").strip().lower() == direction

  archetype_by_id = {
    "demand_supported_growth": "growth",
    "pricing_adjustment": "efficiency",
    "cost_structure_adjustment": "efficiency",
  }
  archetype = archetype_by_id.get(str(strategy_id or "").strip(), "operations")
  price_plan = any(_matches(item, "::Unit Price", "up") for item in lever_plan)
  marketing_growth = any(_matches(item, "::Marketing", "up") for item in lever_plan)
  utilization_down = any(_matches(item, "::Utilization", "down") for item in lever_plan)
  payroll_up = any(_matches(item, "::Payroll", "up") for item in lever_plan)
  payroll_down = any(_matches(item, "::Payroll", "down") for item in lever_plan)
  ganda_down = any(_matches(item, "::General & Administrative", "down") for item in lever_plan)
  cogs_down = any(_matches(item, "::Cost of Goods Sold", "down") for item in lever_plan)
  posture = {
    "demand_posture": "reduce" if utilization_down else "preserve" if marketing_growth else "moderate",
    "staffing_posture": "add_support" if payroll_up else "tighten" if payroll_down else "measured",
    "cost_posture": "tighten" if (ganda_down or cogs_down or payroll_down) else "protect" if payroll_up else "moderate",
  }
  orchestration = _clone((strategy_selection.get("governed_forecast_orchestration") or {}) if isinstance(strategy_selection.get("governed_forecast_orchestration"), dict) else {})
  if isinstance(orchestration, dict):
    orchestration["target_margin_path"] = _clone(strategy_selection.get("target_margin_path") or {})
  runtime = {
    "strategy_id": strategy_id,
    "profile_id": f"gpt_{strategy_id}",
    "strategy_name": str(strategy_id).replace("_", " ").title(),
    "strategy_source": "gpt",
    "archetype": archetype,
    "dominant_tradeoff": str(strategy_selection.get("viability_blueprint_summary") or diagnosis.get("business_model_assessment") or "").strip(),
    "allowed_model_input_levers": allowed_model_input_levers,
    "lever_adjustment_plan": lever_plan,
    "controlled_output_targets": _clone(strategy_selection.get("controlled_output_targets") or []),
    "governed_period_groups": _clone(strategy_selection.get("governed_period_groups") or []),
    "controller_directives": _clone(strategy_selection.get("controller_directives") or {}),
    "constraints": constraints,
    "forecast_orchestration": orchestration,
    **posture,
  }
  return runtime


def _solver_profiles(*, state_model: Dict[str, Any]) -> List[Dict[str, Any]]:
  strategy_layer = (state_model.get("strategy_layer") or {}) if isinstance(state_model.get("strategy_layer"), dict) else {}
  strategies = [item for item in (strategy_layer.get("strategies") or []) if isinstance(item, dict)]
  if strategies:
    return [_clone(item) for item in strategies]
  fixed_facts = (state_model.get("fixed_facts") or {}) if isinstance(state_model.get("fixed_facts"), dict) else {}
  commercial_context = (fixed_facts.get("commercial_context") or {}) if isinstance(fixed_facts.get("commercial_context"), dict) else {}
  growth_demand_mode_enabled = bool(commercial_context.get("growth_demand_mode_enabled"))
  ops_constraints = {
    "marketing_up_cap_ratio": 0.04 if str(commercial_context.get("marketing_role") or "") == "constrained" else max(0.08, min(0.12, _safe_float(commercial_context.get("marketing_up_cap_ratio")) or 0.12)),
    "marketing_down_cap_ratio": max(0.10, _safe_float(commercial_context.get("marketing_down_cap_ratio")) or 0.25),
    "other_opex_down_cap_ratio": max(0.06, _safe_float(commercial_context.get("other_opex_down_cap_ratio")) or (0.08 if str(commercial_context.get("opex_flexibility") or "") == "tight" else 0.15)),
  }
  growth_constraints = {
    "marketing_up_cap_ratio": max(0.16, _safe_float(commercial_context.get("marketing_up_cap_ratio")) or 0.16),
    "marketing_down_cap_ratio": max(0.08, _safe_float(commercial_context.get("marketing_down_cap_ratio")) or 0.20),
    "other_opex_down_cap_ratio": max(0.06, _safe_float(commercial_context.get("other_opex_down_cap_ratio")) or 0.06),
    "prefer_growth_units": growth_demand_mode_enabled,
  }
  weights = (state_model.get("objective_policy") or {}).get("distortion_weights") or {}
  operations_weights = dict(weights)
  growth_weights = dict(weights)
  operations_weights["marketing_up"] = max(operations_weights.get("marketing_up") or 0.0, 7.0)
  operations_weights["other_opex_down"] = max(operations_weights.get("other_opex_down") or 0.0, 2.5)
  growth_weights["marketing_up"] = min(growth_weights.get("marketing_up") or 4.0, 4.0)
  all_levers = _all_model_input_levers(state_model=state_model)
  price_and_util = [item for item in all_levers if item.endswith("::Unit Price") or item.endswith("::Utilization")]
  growth_revenue = [item for item in all_levers if item.endswith("::Unit Price") or item.endswith("::Utilization") or item.endswith("::Capacity")]
  return [
    {
      "strategy_id": "operational_balance_strategy",
      "profile_id": "operations_first",
      "strategy_name": "Operational balance",
      "strategy_source": "deterministic",
      "archetype": "operations",
      "dominant_tradeoff": "restores Year-1 viability before leaning into growth",
      "allowed_model_input_levers": _unique_strings(
        price_and_util
        + [
          _simple_lever_id("expenses", "General & Administrative"),
          _simple_lever_id("expenses", "Marketing"),
          _simple_lever_id("expenses", "Payroll"),
          _simple_lever_id("expenses", "Cost of Goods Sold"),
        ]
      ),
      "lever_adjustment_plan": [],
      "constraints": ops_constraints,
      "weights": operations_weights,
    },
    {
      "strategy_id": "demand_supported_growth",
      "profile_id": "growth_first",
      "strategy_name": "Demand supported growth",
      "strategy_source": "deterministic",
      "archetype": "growth",
      "dominant_tradeoff": "releases growth only when support is in place",
      "allowed_model_input_levers": _unique_strings(
        growth_revenue
        + [_simple_lever_id("expenses", "Marketing"), _simple_lever_id("expenses", "Payroll"), _simple_lever_id("expenses", "General & Administrative")]
      ),
      "lever_adjustment_plan": [],
      "constraints": growth_constraints,
      "weights": growth_weights,
    },
  ]


def _controller_enforced_profile(
  *,
  profile: Dict[str, Any],
  strategy_layer: Dict[str, Any],
  active_violations: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
  del active_violations
  selection = strategy_layer.get("strategy_selection") if isinstance(strategy_layer.get("strategy_selection"), dict) else {}
  directed_allowed = _selection_allowed_model_input_levers(
    selection,
    fallback_allowed=profile.get("allowed_model_input_levers") or [],
    max_quarter=4,
  )
  if not directed_allowed:
    directed_allowed = _unique_strings(profile.get("allowed_model_input_levers") or [])
  next_profile = _clone(profile)
  next_profile["allowed_model_input_levers"] = directed_allowed
  lever_plan = _selection_lever_adjustment_plan(selection, max_quarter=4)
  if lever_plan:
    next_profile["lever_adjustment_plan"] = lever_plan
  next_profile["controlled_output_targets"] = _clone(selection.get("controlled_output_targets") or profile.get("controlled_output_targets") or [])
  next_profile["constraints"] = {}
  return {"profile": next_profile}


def _default_quarter_policy(profile: Dict[str, Any], quarter_index: int) -> Dict[str, Any]:
  return {
    "quarter_start": quarter_index,
    "quarter_end": quarter_index,
    "demand_posture": profile.get("demand_posture") or "moderate",
    "staffing_posture": profile.get("staffing_posture") or "measured",
    "cost_posture": profile.get("cost_posture") or "moderate",
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


def _role_titles_for_scope(scope: str, direct_inputs: Dict[str, Any]) -> List[str]:
  token = str(scope or "").strip().lower()
  titles: List[str] = []
  role_sources = []
  for key in ("roles", "current_staff"):
    for item in direct_inputs.get(key) or []:
      if not isinstance(item, dict):
        continue
      title = str(item.get("role_title") or item.get("full_name") or "").strip()
      if not title:
        continue
      role_sources.append({"title": title, "source": key})
  for item in role_sources:
    title = item["title"]
    source = item["source"]
    lower_title = title.lower()
    if token in {"all_roles", "all"}:
      titles.append(title)
    elif token in {"planned_roles", "inferred_roles"} and source == "roles":
      titles.append(title)
    elif token in {"current_staff", "current_people"} and source == "current_staff":
      titles.append(title)
    elif token in {"support_roles", "support"} and any(word in lower_title for word in ["coordinator", "scheduler", "assistant", "admin", "support", "intake"]):
      titles.append(title)
    elif token in {"clinical_roles", "licensed_roles", "clinical"} and any(word in lower_title for word in ["nurse", "rn", "therap", "clinical", "aide"]):
      titles.append(title)
    elif token in {"founder_key_people", "core_leadership", "leaders"} and any(word in lower_title for word in ["founder", "ceo", "director", "owner", "president"]):
      titles.append(title)
    elif token and token in lower_title:
      titles.append(title)
  return _unique_strings(titles)


def _compress_quarter_policies(policies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  if not policies:
    return []
  compressed: List[Dict[str, Any]] = []
  for policy in sorted(policies, key=lambda item: (_safe_int(item.get("quarter_start")) or 1, _safe_int(item.get("quarter_end")) or 1)):
    current = _clone(policy)
    if not compressed:
      compressed.append(current)
      continue
    previous = compressed[-1]
    comparable_prev = _clone(previous)
    comparable_curr = _clone(current)
    comparable_prev.pop("quarter_start", None)
    comparable_prev.pop("quarter_end", None)
    comparable_curr.pop("quarter_start", None)
    comparable_curr.pop("quarter_end", None)
    if comparable_prev == comparable_curr and (_safe_int(previous.get("quarter_end")) + 1) == _safe_int(current.get("quarter_start")):
      previous["quarter_end"] = _safe_int(current.get("quarter_end"))
      continue
    compressed.append(current)
  return compressed


def _overlay_selection_plans_onto_quarter_map(
  *,
  quarter_map: Dict[int, Dict[str, Any]],
  selection: Dict[str, Any],
  apply_only_to_quarters: Optional[Sequence[int]] = None,
) -> None:
  target_quarters = {
    int(item)
    for item in (apply_only_to_quarters or [])
    if _safe_int(item) > 0
  }

  def _allow_quarter(quarter_index: int) -> bool:
    if not target_quarters:
      return True
    return quarter_index in target_quarters

  lever_plan = _selection_lever_adjustment_plan(selection)
  for item in lever_plan:
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    direction = str(item.get("direction") or "").strip().lower()
    lever_id = str(item.get("lever_id") or "").strip()
    intensity = _intensity_score(item.get("intensity"))
    for quarter_index in range(start, min(20, end) + 1):
      if not _allow_quarter(quarter_index):
        continue
      policy = quarter_map.setdefault(quarter_index, _default_quarter_policy({}, quarter_index))
      policy["active_levers"] = _unique_strings((policy.get("active_levers") or []) + ([lever_id] if lever_id else []))
      if lever_id.endswith("::Unit Price"):
        delta = round(0.002 * (1.0 + intensity), 6)
        if direction == "up":
          policy["price_growth_bias"] = max(_safe_float(policy.get("price_growth_bias")), delta)
        elif direction == "down":
          policy["price_growth_bias"] = min(_safe_float(policy.get("price_growth_bias")), -delta)
      elif lever_id.endswith("::Utilization"):
        delta = round(0.015 * (1.0 + intensity), 6)
        if direction == "up":
          policy["utilization_target_bias"] = max(_safe_float(policy.get("utilization_target_bias")), delta)
          policy["growth_multiplier"] = max(1.0, round(max(_safe_float(policy.get("growth_multiplier")), 1.0) * 1.03, 6))
        elif direction == "down":
          policy["utilization_target_bias"] = min(_safe_float(policy.get("utilization_target_bias")), -delta)
          policy["growth_multiplier"] = min(1.0, round(max(_safe_float(policy.get("growth_multiplier")), 0.1) * 0.98, 6))
      elif lever_id == _simple_lever_id("expenses", "Marketing"):
        delta = round(0.01 * (1.0 + intensity), 6)
        if direction == "up":
          policy["marketing_ratio_bias"] = max(_safe_float(policy.get("marketing_ratio_bias")), delta)
          policy["growth_multiplier"] = max(1.0, round(max(_safe_float(policy.get("growth_multiplier")), 1.0) * 1.04, 6))
        elif direction == "down":
          policy["marketing_ratio_bias"] = min(_safe_float(policy.get("marketing_ratio_bias")), -delta)
      elif lever_id == _simple_lever_id("expenses", "General & Administrative"):
        delta = round(0.01 * (1.0 + intensity), 6)
        if direction == "up":
          policy["opex_ratio_bias"] = max(_safe_float(policy.get("opex_ratio_bias")), delta)
        elif direction == "down":
          policy["opex_ratio_bias"] = min(_safe_float(policy.get("opex_ratio_bias")), -delta)
      elif lever_id == _simple_lever_id("expenses", "Payroll"):
        delta = round(0.02 * (1.0 + intensity), 6)
        if direction == "up":
          policy["payroll_ratio_bias"] = max(_safe_float(policy.get("payroll_ratio_bias")), delta)
          policy["capacity_release_multiplier"] = max(1.0, round(max(_safe_float(policy.get("capacity_release_multiplier")), 1.0) * 1.08, 6))
          policy["growth_multiplier"] = max(1.0, round(max(_safe_float(policy.get("growth_multiplier")), 1.0) * 1.05, 6))
          policy["staffing_posture"] = "add_support"
        elif direction == "down":
          policy["payroll_ratio_bias"] = min(_safe_float(policy.get("payroll_ratio_bias")), -delta)
          policy["capacity_release_multiplier"] = min(1.0, round(max(_safe_float(policy.get("capacity_release_multiplier")), 0.1) * 0.92, 6))
          policy["growth_multiplier"] = min(1.0, round(max(_safe_float(policy.get("growth_multiplier")), 0.1) * 0.97, 6))
          policy["staffing_posture"] = "delay"

  for item in (selection.get("demand_build_plan") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    for quarter_index in range(start, min(20, end) + 1):
      if not _allow_quarter(quarter_index):
        continue
      policy = quarter_map.setdefault(quarter_index, _default_quarter_policy({}, quarter_index))
      if item.get("demand_posture") is not None:
        policy["demand_posture"] = str(item.get("demand_posture") or "").strip().lower() or policy.get("demand_posture")
      if item.get("marketing_ratio_bias") is not None:
        policy["marketing_ratio_bias"] = round(_safe_float(item.get("marketing_ratio_bias")), 6)
      growth_mult = _safe_float(item.get("growth_multiplier"))
      if growth_mult > 0:
        policy["growth_multiplier"] = round(growth_mult, 6)
      demand_levers: List[str] = []
      marketing_bias = _safe_float(item.get("marketing_ratio_bias"))
      if marketing_bias > 0:
        if _selection_marketing_lever(selection):
          demand_levers.append(_selection_marketing_lever(selection))
      elif marketing_bias < 0:
        if _selection_marketing_lever(selection):
          demand_levers.append(_selection_marketing_lever(selection))
      posture = str(item.get("demand_posture") or "").strip().lower()
      if growth_mult > 1.0 or posture in {"build", "grow", "expand", "accelerate", "preserve"}:
        demand_levers.extend(_selection_allowed_levers_matching(selection, suffix="::Utilization"))
      policy["active_levers"] = _unique_strings((policy.get("active_levers") or []) + demand_levers)

  for item in (selection.get("capacity_release_plan") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    for quarter_index in range(start, min(20, end) + 1):
      if not _allow_quarter(quarter_index):
        continue
      policy = quarter_map.setdefault(quarter_index, _default_quarter_policy({}, quarter_index))
      capacity_mult = _safe_float(item.get("capacity_release_multiplier"))
      if capacity_mult > 0:
        policy["capacity_release_multiplier"] = round(capacity_mult, 6)
      posture = str(item.get("capacity_posture") or "").strip().lower()
      if posture:
        if posture in {"expand", "release", "build", "cautious_expand"}:
          policy["staffing_posture"] = "add_support"
          policy["active_levers"] = _unique_strings(
            (policy.get("active_levers") or [])
            + _selection_allowed_levers_matching(selection, suffix="::Utilization")
            + ([_selection_payroll_lever(selection)] if _selection_payroll_lever(selection) else [])
          )
        elif posture in {"hold", "tight", "constrained"}:
          policy["staffing_posture"] = "delay"
          policy["active_levers"] = _unique_strings((policy.get("active_levers") or []) + ([_selection_payroll_lever(selection)] if _selection_payroll_lever(selection) else []))

  for item in (selection.get("support_overhead_plan") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    for quarter_index in range(start, min(20, end) + 1):
      if not _allow_quarter(quarter_index):
        continue
      policy = quarter_map.setdefault(quarter_index, _default_quarter_policy({}, quarter_index))
      if item.get("cost_posture") is not None:
        policy["cost_posture"] = str(item.get("cost_posture") or "").strip().lower() or policy.get("cost_posture")
      if item.get("opex_ratio_bias") is not None:
        policy["opex_ratio_bias"] = round(_safe_float(item.get("opex_ratio_bias")), 6)
      if item.get("payroll_ratio_bias") is not None:
        policy["payroll_ratio_bias"] = round(_safe_float(item.get("payroll_ratio_bias")), 6)
      support_levers: List[str] = []
      if _safe_float(item.get("opex_ratio_bias")) > 0:
        if _selection_ganda_lever(selection):
          support_levers.append(_selection_ganda_lever(selection))
      elif _safe_float(item.get("opex_ratio_bias")) < 0:
        if _selection_ganda_lever(selection):
          support_levers.append(_selection_ganda_lever(selection))
      if _safe_float(item.get("payroll_ratio_bias")) > 0:
        if _selection_payroll_lever(selection):
          support_levers.append(_selection_payroll_lever(selection))
      elif _safe_float(item.get("payroll_ratio_bias")) < 0:
        if _selection_payroll_lever(selection):
          support_levers.append(_selection_payroll_lever(selection))
      policy["active_levers"] = _unique_strings((policy.get("active_levers") or []) + support_levers)


def _normalize_governed_forecast_orchestration(
  *,
  selection: Dict[str, Any],
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  strict_translation: bool,
  translation_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  governed = _clone((translation_audit or {}).get("replacement_forecast_orchestration") or {}) if isinstance((translation_audit or {}).get("replacement_forecast_orchestration"), dict) else {}
  if not governed:
    governed = selection.get("governed_forecast_orchestration") if isinstance(selection.get("governed_forecast_orchestration"), dict) else {}
  if not governed:
    return {}
  authoritative_direct = bool([item for item in (governed.get("quarter_policies") or []) if isinstance(item, dict)])
  expected_levers_by_quarter = _selection_expected_levers_by_quarter(selection)
  direct_covered_quarters: set[int] = set()
  direct_active_by_quarter: Dict[int, List[str]] = {}
  for item in governed.get("quarter_policies") or []:
    if not isinstance(item, dict):
      continue
    direct_active = _unique_strings(item.get("active_levers") or [])
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    for quarter_index in range(start, min(20, end) + 1):
      direct_covered_quarters.add(quarter_index)
      if direct_active:
        direct_active_by_quarter[quarter_index] = _unique_strings((direct_active_by_quarter.get(quarter_index) or []) + direct_active)
        expected_levers_by_quarter[quarter_index] = _unique_strings((expected_levers_by_quarter.get(quarter_index) or []) + direct_active)
  quarter_map: Dict[int, Dict[str, Any]] = {
    quarter_index: _default_quarter_policy(profile, quarter_index)
    for quarter_index in range(1, 21)
  }
  for item in governed.get("quarter_policies") or []:
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    for quarter_index in range(start, min(20, end) + 1):
      policy = quarter_map.setdefault(quarter_index, _default_quarter_policy(profile, quarter_index))
      for key in (
        "demand_posture",
        "staffing_posture",
        "cost_posture",
        "growth_multiplier",
        "convergence_multiplier",
        "price_growth_bias",
        "utilization_target_bias",
        "marketing_ratio_bias",
        "opex_ratio_bias",
        "payroll_ratio_bias",
        "capacity_release_multiplier",
      ):
        if item.get(key) is not None:
          policy[key] = item.get(key)
      if item.get("active_levers") is not None:
        policy["active_levers"] = _unique_strings(item.get("active_levers") or [])
      direct_covered_quarters.add(quarter_index)
  if authoritative_direct:
    first_direct_policy = next(
      (quarter_map.get(quarter_index) for quarter_index in range(1, 21) if quarter_index in direct_covered_quarters),
      None,
    )
    last_policy = _clone(first_direct_policy or _default_quarter_policy(profile, 1))
    for quarter_index in range(1, 21):
      if quarter_index in direct_covered_quarters:
        last_policy = _clone(quarter_map.get(quarter_index) or last_policy)
        continue
      carried = _clone(last_policy or first_direct_policy or _default_quarter_policy(profile, quarter_index))
      carried["quarter_start"] = quarter_index
      carried["quarter_end"] = quarter_index
      quarter_map[quarter_index] = carried
  else:
    uncovered_quarters = [quarter_index for quarter_index in range(1, 21) if quarter_index not in direct_covered_quarters]
    _overlay_selection_plans_onto_quarter_map(
      quarter_map=quarter_map,
      selection=selection,
      apply_only_to_quarters=uncovered_quarters,
    )
  forbidden_exact = {
    str(item or "").strip()
    for item in (selection.get("forbidden_model_input_levers") or [])
    if str(item or "").strip()
  }
  current_util = max(0.0, _safe_float(direct_inputs.get("current_util")))
  translation_issues: List[str] = []
  for quarter_index in range(1, 21):
    policy = quarter_map.setdefault(quarter_index, _default_quarter_policy(profile, quarter_index))
    explicit_active = _unique_strings(policy.get("active_levers") or [])
    direct_active = _unique_strings(direct_active_by_quarter.get(quarter_index) or [])
    if direct_active:
      policy["active_levers"] = [
        item for item in direct_active
        if str(item or "").strip() not in forbidden_exact
      ]
    else:
      base_active = explicit_active if authoritative_direct else (explicit_active or (expected_levers_by_quarter.get(quarter_index) or []))
      policy["active_levers"] = _policy_active_levers_from_values(
        base_active_levers=base_active if (authoritative_direct or strict_translation or explicit_active or expected_levers_by_quarter.get(quarter_index)) else [],
        marketing_ratio_bias=_safe_float(policy.get("marketing_ratio_bias")),
        opex_ratio_bias=_safe_float(policy.get("opex_ratio_bias")),
        payroll_ratio_bias=_safe_float(policy.get("payroll_ratio_bias")),
        capacity_release_multiplier=max(0.1, _safe_float(policy.get("capacity_release_multiplier")) or 1.0),
        price_growth_bias=_safe_float(policy.get("price_growth_bias")),
        utilization_target_bias=_safe_float(policy.get("utilization_target_bias")),
        growth_multiplier=max(0.1, _safe_float(policy.get("growth_multiplier")) or 1.0),
      )
      policy["active_levers"] = [
        item for item in _reconcile_active_levers_for_quarter(
          quarter_index=quarter_index,
          active_levers=policy.get("active_levers") or [],
          expected_levers_by_quarter=({} if authoritative_direct else expected_levers_by_quarter),
        )
        if str(item or "").strip() not in forbidden_exact
      ]
    capacity_mult = max(0.1, _safe_float(policy.get("capacity_release_multiplier")) or 1.0)
    util_bias = _safe_float(policy.get("utilization_target_bias"))
    minimum_capacity_mult = max(0.9, (current_util + max(0.0, util_bias)) / 0.95) if current_util > 0 else 0.9
    if capacity_mult < minimum_capacity_mult:
      policy["capacity_release_multiplier"] = round(minimum_capacity_mult, 6)
    translation_issues.extend(
      _quarter_policy_translation_issues(
        quarter_index=quarter_index,
        policy=policy,
        expected_levers_by_quarter=({} if authoritative_direct else expected_levers_by_quarter),
        current_util=current_util,
      )
    )
  orchestration = {
    "orchestration_summary": str(governed.get("orchestration_summary") or "").strip(),
    "quarter_policies": _compress_quarter_policies(list(quarter_map.values())),
    "role_timing_overrides": [
      {
        "role_title": str(item.get("role_title") or "").strip(),
        "months_until_activate": max(0, _safe_int(item.get("months_until_activate"))),
      }
      for item in (governed.get("role_timing_overrides") or [])
      if isinstance(item, dict) and str(item.get("role_title") or "").strip()
    ],
    "milestone_timing_overrides": [
      {
        "description": str(item.get("description") or "").strip(),
        "months_until_activate": max(0, _safe_int(item.get("months_until_activate"))),
        "target_quarter": max(1, min(20, _safe_int(item.get("target_quarter")) or 1)),
        "activation_condition": str(item.get("activation_condition") or "").strip(),
      }
      for item in (governed.get("milestone_timing_overrides") or [])
      if isinstance(item, dict) and str(item.get("description") or "").strip()
    ],
    "event_response": _clone((governed.get("event_response") or {}) if isinstance(governed.get("event_response"), dict) else {}),
    "target_margin_path": _clone(selection.get("target_margin_path") or {}),
    "translated_growth_architecture": {
      "capacity_release_plan": _clone(selection.get("capacity_release_plan") or []),
      "hiring_release_plan": _clone(selection.get("hiring_release_plan") or []),
      "demand_build_plan": _clone(selection.get("demand_build_plan") or []),
      "milestone_activation_plan": _clone(selection.get("milestone_activation_plan") or []),
      "support_overhead_plan": _clone(selection.get("support_overhead_plan") or []),
      "governed_forecast_orchestration": _clone(governed),
    },
    "translation_issues": _unique_strings(translation_issues),
  }
  event_response = orchestration["event_response"]
  event_response.setdefault("hire_capacity_multiplier", 1.0)
  event_response.setdefault("hire_growth_bonus_delta", 0.0)
  event_response.setdefault("marketing_growth_multiplier", 1.0)
  event_response.setdefault("milestone_capacity_multiplier", 1.0)
  event_response.setdefault("milestone_growth_multiplier", 1.0)
  if authoritative_direct:
    structural_issues: List[str] = []
    if not list(orchestration.get("quarter_policies") or []):
      structural_issues.append("missing_forecast_orchestration")
    orchestration["translation_issues"] = _unique_strings(list(orchestration.get("translation_issues") or []) + structural_issues)
  else:
    orchestration["translation_issues"] = _unique_strings(
      list(orchestration.get("translation_issues") or [])
      + _orchestration_translation_issues(
        selection=selection,
        orchestration=orchestration,
        direct_inputs=direct_inputs,
      )
    )
  return orchestration


def _selection_expected_levers_by_quarter(selection: Dict[str, Any]) -> Dict[int, List[str]]:
  expected: Dict[int, List[str]] = {quarter_index: [] for quarter_index in range(1, 21)}
  for item in _selection_lever_adjustment_plan(selection):
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    lever_id = str(item.get("lever_id") or "").strip()
    if not lever_id:
      continue
    for quarter_index in range(start, min(20, end) + 1):
      expected[quarter_index] = _unique_strings((expected.get(quarter_index) or []) + [lever_id])
  for item in (selection.get("demand_build_plan") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    direct: List[str] = []
    marketing_lever = _selection_marketing_lever(selection)
    if marketing_lever:
      direct.append(marketing_lever)
    direct.extend(_selection_allowed_levers_matching(selection, suffix="::Utilization"))
    for quarter_index in range(start, min(20, end) + 1):
      expected[quarter_index] = _unique_strings((expected.get(quarter_index) or []) + direct)
  for item in (selection.get("capacity_release_plan") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    posture = str(item.get("capacity_posture") or "").strip().lower()
    direct: List[str] = []
    if posture in {"expand", "cautious_expand", "release", "build"}:
      direct.extend(_selection_allowed_levers_matching(selection, suffix="::Utilization"))
      if _selection_payroll_lever(selection):
        direct.append(_selection_payroll_lever(selection))
    elif posture in {"hold", "tight", "constrained"} and _selection_payroll_lever(selection):
      direct.append(_selection_payroll_lever(selection))
    for quarter_index in range(start, min(20, end) + 1):
      expected[quarter_index] = _unique_strings((expected.get(quarter_index) or []) + direct)
  for item in (selection.get("support_overhead_plan") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    direct: List[str] = []
    if item.get("opex_ratio_bias") is not None and _selection_ganda_lever(selection):
      direct.append(_selection_ganda_lever(selection))
    if item.get("payroll_ratio_bias") is not None and _selection_payroll_lever(selection):
      direct.append(_selection_payroll_lever(selection))
    for quarter_index in range(start, min(20, end) + 1):
      expected[quarter_index] = _unique_strings((expected.get(quarter_index) or []) + direct)
  return expected


def _reconcile_active_levers_for_quarter(
  *,
  quarter_index: int,
  active_levers: Sequence[Any],
  expected_levers_by_quarter: Dict[int, List[str]],
) -> List[str]:
  expected = set(expected_levers_by_quarter.get(quarter_index) or [])
  cleaned = _unique_strings([str(item or "").strip() for item in (active_levers or []) if str(item or "").strip()])
  return [item for item in cleaned if not expected or item in expected]


def _quarter_policy_translation_issues(
  *,
  quarter_index: int,
  policy: Dict[str, Any],
  expected_levers_by_quarter: Dict[int, List[str]],
  current_util: float,
) -> List[str]:
  issues: List[str] = []
  active = set(str(item or "").strip() for item in (policy.get("active_levers") or []) if str(item or "").strip())
  expected = set(expected_levers_by_quarter.get(quarter_index) or [])
  if expected and not active:
    issues.append(f"empty_active_levers_q{quarter_index}")
  elif expected and not active.intersection(expected):
    issues.append(f"missing_expected_levers_q{quarter_index}")
  capacity_mult = max(0.1, _safe_float(policy.get("capacity_release_multiplier")) or 1.0)
  util_bias = _safe_float(policy.get("utilization_target_bias"))
  implied_util = (current_util + util_bias) / max(capacity_mult, 1e-9)
  if implied_util > 0.95:
    issues.append(f"capacity_utilization_mismatch_q{quarter_index}")
  return issues


def _translation_audit_requires_correction(translation_audit: Optional[Dict[str, Any]]) -> bool:
  if not isinstance(translation_audit, dict) or not translation_audit:
    return False
  status = str(translation_audit.get("audit_status") or "").strip().lower()
  return (
    status == "rejected_translation"
    or bool(translation_audit.get("required_corrections") or [])
    or bool(translation_audit.get("introduced_conflicts") or [])
  )


def _quarter_span(item: Dict[str, Any]) -> range:
  start = max(1, _safe_int(item.get("quarter_start")) or _safe_int(item.get("target_quarter")) or 1)
  end = max(start, _safe_int(item.get("quarter_end")) or start)
  return range(start, min(20, end) + 1)


def _entry_months_until_activate(item: Dict[str, Any]) -> int:
  explicit_months = _safe_int(item.get("months_until_activate"))
  if explicit_months > 0:
    return explicit_months
  target_quarter = max(1, min(20, _safe_int(item.get("target_quarter")) or 1))
  return max(0, (target_quarter - 1) * 3)


def _policy_active_levers_from_values(
  *,
  base_active_levers: Sequence[Any],
  marketing_ratio_bias: float,
  opex_ratio_bias: float,
  payroll_ratio_bias: float,
  capacity_release_multiplier: float,
  price_growth_bias: float,
  utilization_target_bias: float,
  growth_multiplier: float,
) -> List[str]:
  del marketing_ratio_bias, opex_ratio_bias, payroll_ratio_bias
  del capacity_release_multiplier, price_growth_bias, utilization_target_bias, growth_multiplier
  return _unique_strings([str(item or "").strip() for item in (base_active_levers or []) if str(item or "").strip()])


def _orchestration_required_families(selection: Dict[str, Any]) -> List[str]:
  required: List[str] = []
  if selection.get("demand_build_plan"):
    required.append("demand_build_plan")
  if selection.get("capacity_release_plan"):
    required.append("capacity_release_plan")
  if selection.get("support_overhead_plan"):
    required.append("support_overhead_plan")
  if selection.get("hiring_release_plan"):
    required.append("hiring_release_plan")
  if selection.get("milestone_activation_plan"):
    required.append("milestone_activation_plan")
  return required


def _orchestration_translation_issues(
  *,
  selection: Dict[str, Any],
  orchestration: Dict[str, Any],
  direct_inputs: Dict[str, Any],
) -> List[str]:
  issues: List[str] = []
  quarter_policies = [item for item in (orchestration.get("quarter_policies") or []) if isinstance(item, dict)]
  role_overrides = [item for item in (orchestration.get("role_timing_overrides") or []) if isinstance(item, dict)]
  milestone_overrides = [item for item in (orchestration.get("milestone_timing_overrides") or []) if isinstance(item, dict)]
  event_response = orchestration.get("event_response") if isinstance(orchestration.get("event_response"), dict) else {}
  translated_growth_architecture = orchestration.get("translated_growth_architecture") if isinstance(orchestration.get("translated_growth_architecture"), dict) else {}

  if _orchestration_required_families(selection) and not quarter_policies:
    issues.append("missing_forecast_orchestration")
    return issues

  if selection.get("hiring_release_plan") and not role_overrides:
    issues.append("missing_hiring_release_translation")
  if selection.get("milestone_activation_plan") and not milestone_overrides:
    issues.append("missing_milestone_translation")
  if selection.get("target_margin_path") and not isinstance(orchestration.get("target_margin_path"), dict):
    issues.append("missing_target_margin_path_translation")
  if _orchestration_required_families(selection) and not translated_growth_architecture:
    issues.append("missing_growth_architecture_translation")

  if selection.get("hiring_release_plan"):
    translated_titles = {
      str(item.get("role_title") or "").strip()
      for item in role_overrides
      if str(item.get("role_title") or "").strip()
    }
    for item in selection.get("hiring_release_plan") or []:
      if not isinstance(item, dict):
        continue
      expected_titles = set(_role_titles_for_scope(str(item.get("role_scope") or "").strip(), direct_inputs))
      if expected_titles and not expected_titles.intersection(translated_titles):
        issues.append("missing_hiring_scope_translation")
      max_months = _entry_months_until_activate(item)
      for title in expected_titles:
        actual = next(
          (max(0, _safe_int(override.get("months_until_activate"))) for override in role_overrides if str(override.get("role_title") or "").strip() == title),
          None,
        )
        if actual is None:
          continue
        if actual > max_months + 6:
          issues.append("overshot_hiring_release_timing")

  if selection.get("milestone_activation_plan"):
    translated_descriptions = {
      str(item.get("description") or "").strip().lower()
      for item in milestone_overrides
      if str(item.get("description") or "").strip()
    }
    for item in selection.get("milestone_activation_plan") or []:
      if not isinstance(item, dict):
        continue
      description = str(item.get("description") or "").strip().lower()
      if description and description not in translated_descriptions:
        issues.append("missing_milestone_description_translation")

  expected_by_quarter = _selection_expected_levers_by_quarter(selection)
  policy_by_quarter: Dict[int, Dict[str, Any]] = {}
  for item in quarter_policies:
    for quarter_index in range(max(1, _safe_int(item.get("quarter_start")) or 1), min(20, _safe_int(item.get("quarter_end")) or 1) + 1):
      policy_by_quarter[quarter_index] = item
  for quarter_index, expected in expected_by_quarter.items():
    if not expected:
      continue
    policy = policy_by_quarter.get(quarter_index)
    if not isinstance(policy, dict):
      issues.append(f"missing_quarter_policy_q{quarter_index}")
      continue
    active = set(str(item or "").strip().lower() for item in (policy.get("active_levers") or []) if str(item or "").strip())
    if not active:
      issues.append(f"empty_active_levers_q{quarter_index}")
      continue
    if not active.intersection(expected):
      issues.append(f"missing_expected_levers_q{quarter_index}")

  if selection.get("demand_build_plan") and _safe_float(event_response.get("marketing_growth_multiplier")) <= 0:
    issues.append("missing_demand_event_response")
  if selection.get("capacity_release_plan") and _safe_float(event_response.get("hire_capacity_multiplier")) <= 0:
    issues.append("missing_capacity_event_response")
  if selection.get("milestone_activation_plan") and _safe_float(event_response.get("milestone_capacity_multiplier")) <= 0:
    issues.append("missing_milestone_event_response")

  return _unique_strings(issues)


def _build_forecast_orchestration(
  *,
  selection: Dict[str, Any],
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  retry_attempt: int,
  translation_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  strict_translation = _translation_audit_requires_correction(translation_audit)
  direct_governed = _normalize_governed_forecast_orchestration(
    selection=selection,
    profile=profile,
    direct_inputs=direct_inputs,
    strict_translation=strict_translation,
    translation_audit=translation_audit,
  )
  if direct_governed:
    return direct_governed
  baseline_orchestration = selection.get("baseline_forecast_orchestration") if isinstance(selection.get("baseline_forecast_orchestration"), dict) else {}
  quarter_map: Dict[int, Dict[str, Any]] = {
    quarter_index: _default_quarter_policy(profile, quarter_index)
    for quarter_index in range(1, 21)
  }
  for item in (baseline_orchestration.get("quarter_policies") or []):
    if not isinstance(item, dict):
      continue
    start = max(1, _safe_int(item.get("quarter_start")) or 1)
    end = max(start, _safe_int(item.get("quarter_end")) or start)
    for quarter_index in range(start, min(20, end) + 1):
      seeded = quarter_map.setdefault(quarter_index, _default_quarter_policy(profile, quarter_index))
      for key in (
        "demand_posture",
        "staffing_posture",
        "cost_posture",
        "growth_multiplier",
        "convergence_multiplier",
        "price_growth_bias",
        "utilization_target_bias",
        "marketing_ratio_bias",
        "opex_ratio_bias",
        "payroll_ratio_bias",
        "capacity_release_multiplier",
      ):
        if item.get(key) is not None:
          seeded[key] = item.get(key)
      seeded["active_levers"] = _unique_strings(
        (seeded.get("active_levers") or [])
        + [str(lever or "").strip() for lever in (item.get("active_levers") or []) if str(lever or "").strip() and "::" in str(lever or "").strip()]
      )
  _overlay_selection_plans_onto_quarter_map(
    quarter_map=quarter_map,
    selection=selection,
  )
  role_overrides: List[Dict[str, Any]] = [
    item for item in (baseline_orchestration.get("role_timing_overrides") or [])
    if isinstance(item, dict)
  ]
  milestone_overrides: List[Dict[str, Any]] = [
    item for item in (baseline_orchestration.get("milestone_timing_overrides") or [])
    if isinstance(item, dict)
  ]
  for item in (selection.get("hiring_release_plan") or []):
    if not isinstance(item, dict):
      continue
    months = _entry_months_until_activate(item)
    scope = str(item.get("role_scope") or "").strip()
    for title in _role_titles_for_scope(scope, direct_inputs):
      role_overrides.append({"role_title": title, "months_until_activate": months})
  for item in (selection.get("milestone_activation_plan") or []):
    if not isinstance(item, dict):
      continue
    milestone_overrides.append({
      "description": str(item.get("description") or "").strip(),
      "months_until_activate": _entry_months_until_activate(item),
      "target_quarter": max(1, min(20, _safe_int(item.get("target_quarter")) or 1)),
      "activation_condition": str(item.get("activation_condition") or "").strip(),
    })
  event_response = _clone((baseline_orchestration.get("event_response") or {}) if isinstance(baseline_orchestration.get("event_response"), dict) else {})
  event_response.setdefault("hire_capacity_multiplier", 1.0)
  event_response.setdefault("hire_growth_bonus_delta", 0.0)
  event_response.setdefault("marketing_growth_multiplier", 1.0)
  event_response.setdefault("milestone_capacity_multiplier", 1.0)
  event_response.setdefault("milestone_growth_multiplier", 1.0)
  return {
    "orchestration_summary": str(selection.get("viability_blueprint_summary") or profile.get("dominant_tradeoff") or "").strip(),
    "quarter_policies": _compress_quarter_policies(list(quarter_map.values())),
    "role_timing_overrides": role_overrides,
    "milestone_timing_overrides": milestone_overrides,
    "event_response": event_response,
    "target_margin_path": _clone(selection.get("target_margin_path") or {}),
    "translated_growth_architecture": {
      "capacity_release_plan": _clone(selection.get("capacity_release_plan") or []),
      "hiring_release_plan": _clone(selection.get("hiring_release_plan") or []),
      "demand_build_plan": _clone(selection.get("demand_build_plan") or []),
      "milestone_activation_plan": _clone(selection.get("milestone_activation_plan") or []),
      "support_overhead_plan": _clone(selection.get("support_overhead_plan") or []),
      "governed_forecast_orchestration": {},
    },
    "translation_issues": _orchestration_translation_issues(
      selection=selection,
      orchestration={
        "quarter_policies": _compress_quarter_policies(list(quarter_map.values())),
        "role_timing_overrides": role_overrides,
        "milestone_timing_overrides": milestone_overrides,
        "event_response": event_response,
      },
      direct_inputs=direct_inputs,
    ),
  }


def _build_profile_solver_contract(
  *,
  state_model: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  profile: Dict[str, Any],
  target_ebitda_min: Optional[float],
  target_ebitda_max: Optional[float],
  translation_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  strategy_layer = (state_model.get("strategy_layer") or {}) if isinstance(state_model.get("strategy_layer"), dict) else {}
  selection = (strategy_layer.get("strategy_selection") or {}) if isinstance(strategy_layer.get("strategy_selection"), dict) else {}
  enforced = _controller_enforced_profile(
    profile=profile,
    strategy_layer=strategy_layer,
    active_violations=direct_inputs.get("constraint_violations") or [],
  )
  contract_profile = _clone((enforced.get("profile") or {}) if isinstance(enforced, dict) else profile)
  current_revenue = max(1.0, _safe_float(direct_inputs.get("current_revenue")))
  current_ebitda = current_revenue - _safe_float(direct_inputs.get("current_cogs")) - _safe_float(direct_inputs.get("current_payroll_total")) - _safe_float(direct_inputs.get("current_marketing")) - _safe_float(direct_inputs.get("current_other_opex")) - _safe_float(direct_inputs.get("rent_annualized"))
  selection_plan = _selection_lever_adjustment_plan(selection, max_quarter=4)
  if not selection_plan:
    selection_plan = [item for item in (contract_profile.get("lever_adjustment_plan") or []) if isinstance(item, dict)]
  allowed = set(contract_profile.get("allowed_model_input_levers") or [])
  allowed.update(
    _selection_allowed_model_input_levers(
      selection,
      fallback_allowed=profile.get("allowed_model_input_levers") or [],
      max_quarter=4,
    )
  )
  contract_profile["allowed_model_input_levers"] = _unique_strings(sorted(allowed))
  contract_profile["lever_adjustment_plan"] = _clone(selection_plan)
  contract_profile["controlled_output_targets"] = _clone(
    selection.get("controlled_output_targets")
    or contract_profile.get("controlled_output_targets")
    or []
  )
  contract_profile["controller_directives"] = _clone(selection.get("controller_directives") or {})
  contract_profile["constraints"] = {}
  if not contract_profile.get("forecast_orchestration"):
    replacement_orchestration = _clone((translation_audit or {}).get("replacement_forecast_orchestration") or {})
    if replacement_orchestration:
      contract_profile["forecast_orchestration"] = replacement_orchestration
    elif isinstance(selection.get("governed_forecast_orchestration"), dict):
      contract_profile["forecast_orchestration"] = _clone(selection.get("governed_forecast_orchestration") or {})
    else:
      contract_profile["forecast_orchestration"] = _build_forecast_orchestration(
        selection=selection,
        profile=contract_profile,
        direct_inputs=direct_inputs,
        retry_attempt=_safe_int(
          ((strategy_layer.get("diagnosis") or {}) if isinstance(strategy_layer.get("diagnosis"), dict) else {}).get("governed_retry_attempt")
        ),
        translation_audit=translation_audit,
      )
  orchestration = (contract_profile.get("forecast_orchestration") or {}) if isinstance(contract_profile.get("forecast_orchestration"), dict) else {}
  orchestration_issues = list(orchestration.get("translation_issues") or [])
  issues: List[str] = []
  if str(profile.get("strategy_source") or "").strip().lower() == "gpt" and orchestration_issues:
    issues.append("invalid_gpt_orchestration")
  return {
    "profile": contract_profile,
    "direct_inputs": _clone(direct_inputs),
    "target_ebitda_min": target_ebitda_min,
    "target_ebitda_max": target_ebitda_max,
    "diagnostics": {
      "strategy_id": str(profile.get("strategy_id") or "").strip(),
      "strategy_source": str(profile.get("strategy_source") or "").strip(),
      "controller_profile": {
        "allowed_model_input_levers": sorted(allowed),
        "lever_adjustment_plan_count": len(selection_plan),
        "governed_period_group_count": len([item for item in (selection.get("governed_period_groups") or []) if isinstance(item, dict)]),
        "lever_ids_in_plan": sorted({
          str(item.get("lever_id") or "").strip()
          for item in selection_plan
          if str(item.get("lever_id") or "").strip()
        }),
      },
      "issues": _unique_strings(issues + orchestration_issues),
      "adjustments": [],
      "translation_self_audit": {
        "captured_correctly": not bool(orchestration_issues),
        "missing_intents": [],
        "distorted_intents": [],
        "introduced_conflicts": _unique_strings(orchestration_issues),
        "correction_requested": _translation_audit_requires_correction(translation_audit),
      },
      "dynamic_controller_ranges": {
        "constraint_updates": {},
        "adjustments": [],
      },
      "optimistic_ebitda": round(current_ebitda, 2),
      "current_ebitda": round(current_ebitda, 2),
      "target_ebitda_min": target_ebitda_min,
      "target_ebitda_max": target_ebitda_max,
    },
  }
