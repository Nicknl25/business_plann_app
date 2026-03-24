from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
  from benchmark_resolver import BENCHMARK_RESOLVER_VERSION, resolve_alpha_benchmark_payload  # type: ignore
except Exception:
  from client_intake_and_finmo.benchmark_resolver import (  # type: ignore
    BENCHMARK_RESOLVER_VERSION,
    resolve_alpha_benchmark_payload,
  )

try:
  from consistency_financials import build_consistency_financial_summary  # type: ignore
except Exception:
  from client_intake_and_finmo.consistency_financials import build_consistency_financial_summary  # type: ignore

try:
  from constraint_traits import CONSTRAINT_TRAITS_VERSION, extract_normalized_traits  # type: ignore
except Exception:
  from client_intake_and_finmo.constraint_traits import (  # type: ignore
    CONSTRAINT_TRAITS_VERSION,
    extract_normalized_traits,
  )

try:
  from planning_contract import (  # type: ignore
    PLANNING_CONTRACT_VERSION,
    SOLVER_MUTABLE_LEVERS,
    SOLVER_PROTECTED_FACTS,
    VIOLATION_CODES,
    engine_versions_payload,
  )
except Exception:
  from client_intake_and_finmo.planning_contract import (  # type: ignore
    PLANNING_CONTRACT_VERSION,
    SOLVER_MUTABLE_LEVERS,
    SOLVER_PROTECTED_FACTS,
    VIOLATION_CODES,
    engine_versions_payload,
  )


CONSTRAINT_ENGINE_VERSION = "constraint-engine/v1"


def _to_float(value: Any) -> Optional[float]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  if isinstance(value, (int, float)):
    num = float(value)
    return None if num != num else num
  try:
    num = float(str(value).strip().replace(",", ""))
    return None if num != num else num
  except Exception:
    return None


def _nonneg(value: Any) -> float:
  return max(0.0, _to_float(value) or 0.0)


def _safe_int(value: Any) -> Optional[int]:
  raw = _to_float(value)
  if raw is None:
    return None
  try:
    return int(round(raw))
  except Exception:
    return None


def _normalize_ratio(value: Any) -> Optional[float]:
  raw = _to_float(value)
  if raw is None:
    return None
  if raw > 1.0:
    raw = raw / 100.0
  return max(0.0, min(1.0, raw))


def _clamp_band(min_value: Optional[float], max_value: Optional[float], *, floor: float = 0.0, ceiling: float = 1.0) -> Dict[str, Optional[float]]:
  low = None if min_value is None else max(floor, min(ceiling, float(min_value)))
  high = None if max_value is None else max(floor, min(ceiling, float(max_value)))
  if low is not None and high is not None and low > high:
    low, high = high, low
  return {"min": round(low, 6) if low is not None else None, "max": round(high, 6) if high is not None else None}


def _band_from_current(current: Optional[float], *, width: float, floor: float = 0.0, ceiling: float = 1.0) -> Dict[str, Optional[float]]:
  if current is None:
    return {"min": None, "max": None}
  return _clamp_band(current - width, current + width, floor=floor, ceiling=ceiling)


def _band_value_max(band: Dict[str, Any]) -> Optional[float]:
  return _to_float((band or {}).get("max"))


def _band_value_min(band: Dict[str, Any]) -> Optional[float]:
  return _to_float((band or {}).get("min"))


def _top_level_driver_value(payload: Dict[str, Any], key: str) -> Optional[float]:
  if not isinstance(payload, dict):
    return None
  direct = _to_float(payload.get(key))
  if direct is not None:
    return direct
  lobs = payload.get("lobs")
  if not isinstance(lobs, list):
    return None
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      value = _to_float(product.get(key))
      if value is not None:
        return value
  return None


def _required_units_year1(financials_year1_json: Dict[str, Any]) -> float:
  total = 0.0
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  lobs = year1.get("lobs")
  if isinstance(lobs, list):
    for lob in lobs:
      if not isinstance(lob, dict):
        continue
      products = lob.get("products")
      if not isinstance(products, list):
        continue
      for product in products:
        if not isinstance(product, dict):
          continue
        avg_units = _nonneg(product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1"))
        periods = _nonneg(product.get("operating_periods_per_year") or product.get("operating_weeks_per_year"))
        total += avg_units * periods
  if total > 0:
    return total
  avg_units = _nonneg(year1.get("avg_units_per_period_year1") or year1.get("avg_units_per_week_year1"))
  periods = _nonneg(year1.get("operating_periods_per_year") or year1.get("operating_weeks_per_year"))
  return avg_units * periods


def _iter_year1_products(financials_year1_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  lobs = year1.get("lobs")
  if not isinstance(lobs, list):
    return rows
  for lob in lobs:
    if not isinstance(lob, dict):
      continue
    lob_name = str(lob.get("lob_name") or "").strip() or "Line of business"
    products = lob.get("products")
    if not isinstance(products, list):
      continue
    for product in products:
      if not isinstance(product, dict):
        continue
      rows.append(
        {
          "lob_name": lob_name,
          "product_name": str(product.get("product_name") or "").strip() or "Product",
          "product": product,
        }
      )
  return rows


def _build_child_metric_basis(financials_year1_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  basis: List[Dict[str, Any]] = []
  for item in _iter_year1_products(financials_year1_json or {}):
    product = item.get("product") if isinstance(item, dict) else {}
    product = product if isinstance(product, dict) else {}
    cadence = str(product.get("unit_cadence") or "").strip().lower()
    price = _nonneg(product.get("unit_price"))
    capacity_per_period = _nonneg(product.get("units_per_period_capacity") or product.get("units_per_week_capacity"))
    avg_units = _nonneg(
      product.get("avg_active_units_year1")
      if cadence == "contract"
      else product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1")
    )
    periods = _nonneg(
      product.get("annual_turns_per_year")
      if cadence == "contract"
      else product.get("operating_periods_per_year") or product.get("operating_weeks_per_year")
    )
    utilization = _normalize_ratio(product.get("utilization_rate"))
    annual_units = _nonneg(product.get("annual_units_year1"))
    if annual_units <= 0:
      annual_units = avg_units * periods
    annual_capacity_units = capacity_per_period * periods
    annual_revenue = _nonneg(product.get("revenue_total_year1"))
    if annual_revenue <= 0 and annual_units > 0 and price > 0:
      annual_revenue = annual_units * price
    basis.append(
      {
        "lob_name": item.get("lob_name"),
        "product_name": item.get("product_name"),
        "unit_cadence": cadence or str(product.get("unit_cadence") or "").strip().lower(),
        "unit_price": price,
        "avg_units_per_period_year1": avg_units,
        "operating_periods_per_year": periods,
        "utilization_rate": utilization,
        "units_per_period_capacity": capacity_per_period,
        "annual_units": annual_units,
        "annual_capacity_units": annual_capacity_units,
        "annual_revenue": annual_revenue,
      }
    )
  return basis


def _weighted_child_price(child_basis: List[Dict[str, Any]]) -> Optional[float]:
  total_units = sum(max(0.0, _to_float(item.get("annual_units")) or 0.0) for item in child_basis if isinstance(item, dict))
  if total_units <= 0:
    return None
  total_revenue = sum(max(0.0, _to_float(item.get("annual_revenue")) or 0.0) for item in child_basis if isinstance(item, dict))
  return total_revenue / max(total_units, 1e-9)


def _weighted_child_utilization(child_basis: List[Dict[str, Any]]) -> Optional[float]:
  total_capacity = sum(max(0.0, _to_float(item.get("annual_capacity_units")) or 0.0) for item in child_basis if isinstance(item, dict))
  if total_capacity <= 0:
    return None
  total_units = sum(max(0.0, _to_float(item.get("annual_units")) or 0.0) for item in child_basis if isinstance(item, dict))
  return max(0.0, min(1.0, total_units / max(total_capacity, 1e-9)))


def _default_marketing_center(traits: Dict[str, Any]) -> float:
  modality = str(traits.get("sales_modality") or "").strip().lower()
  customer = str(traits.get("customer_type") or "").strip().lower()
  geography = str(traits.get("geographic_scope") or "").strip().lower()
  stage = str(traits.get("business_stage") or "").strip().lower()
  base = {
    "local_service": 0.07,
    "retail": 0.06,
    "online": 0.16,
    "project_based": 0.05,
    "manufacturing": 0.04,
    "hybrid": 0.08,
  }.get(modality, 0.06)
  if customer == "b2b":
    base -= 0.015
  elif customer == "b2c":
    base += 0.01
  if geography in {"national", "international"}:
    base += 0.015
  if stage in {"pre_revenue", "startup"}:
    base += 0.02
  return max(0.01, min(0.35, base))


def _trait_marketing_band(
  *,
  traits: Dict[str, Any],
  current_ratio: Optional[float],
  opex_band: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[float]]:
  center = current_ratio if current_ratio is not None and current_ratio > 0 else _default_marketing_center(traits)
  width = 0.03 + (_stage_band_adjustment(traits) * 0.35)
  band = _clamp_band(center - width, center + width, floor=0.0, ceiling=0.40)
  opex_max = _band_value_max(opex_band or {})
  if opex_max is not None and band.get("max") is not None:
    band["max"] = round(min(float(band["max"]), max(0.02, opex_max * 0.72)), 6)
    if band.get("min") is not None and band["min"] > band["max"]:
      band["min"] = band["max"]
  return band


def _labor_workload_thresholds(traits: Dict[str, Any]) -> Dict[str, float]:
  modality = str(traits.get("sales_modality") or "").strip().lower()
  stage = str(traits.get("business_stage") or "").strip().lower()
  base_revenue_per_fte = {
    "local_service": 240000.0,
    "project_based": 300000.0,
    "retail": 220000.0,
    "manufacturing": 260000.0,
    "hybrid": 250000.0,
    "online": 320000.0,
  }.get(modality, 240000.0)
  stage_factor = {
    "pre_revenue": 0.75,
    "startup": 0.85,
    "operating": 1.0,
    "growth": 1.1,
    "mature": 1.15,
  }.get(stage, 1.0)
  return {
    "max_revenue_per_fte": base_revenue_per_fte * stage_factor,
  }


def _default_compensation_per_fte(traits: Dict[str, Any]) -> float:
  modality = str(traits.get("sales_modality") or "").strip().lower()
  return {
    "local_service": 65000.0,
    "project_based": 85000.0,
    "retail": 45000.0,
    "manufacturing": 60000.0,
    "hybrid": 70000.0,
    "online": 80000.0,
  }.get(modality, 60000.0)


def _derived_year1_payroll_from_people(people_json: Dict[str, Any]) -> float:
  total = 0.0
  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    total += max(0.0, _to_float(person.get("annual_wage")) or 0.0)
  for role in (people_json or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    annual_wage = max(0.0, _to_float(role.get("annual_wage")) or 0.0)
    months_until_hire = int(max(0, min(12, round(_to_float(role.get("months_until_hire")) or 0.0))))
    active_months = max(0, 12 - months_until_hire)
    total += annual_wage * (active_months / 12.0)
  return round(total, 2)


def _role_month_support_metrics(people_json: Dict[str, Any]) -> Dict[str, float]:
  fixed_active_role_months = 0.0
  baseline_adjustable_active_months = 0.0
  adjustable_role_month_cost_floor_total = 0.0
  fixed_people_payroll = 0.0

  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    annual_wage = max(0.0, _to_float(person.get("annual_wage")) or 0.0)
    if annual_wage <= 0:
      continue
    fixed_people_payroll += annual_wage
    fixed_active_role_months += 12.0

  for role in (people_json or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    annual_wage = max(0.0, _to_float(role.get("annual_wage")) or 0.0)
    if annual_wage <= 0:
      continue
    months_until_hire = max(0, min(12, _safe_int(role.get("months_until_hire")) or 0))
    active_months = max(0.0, 12.0 - float(months_until_hire))
    if active_months <= 0:
      continue
    baseline_adjustable_active_months += active_months
    adjustable_role_month_cost_floor_total += (annual_wage / 12.0) * active_months

  return {
    "fixed_people_payroll": round(fixed_people_payroll, 2),
    "fixed_active_role_months": round(fixed_active_role_months, 2),
    "baseline_adjustable_active_months": round(baseline_adjustable_active_months, 2),
    "adjustable_role_month_cost_floor": round(
      (adjustable_role_month_cost_floor_total / baseline_adjustable_active_months)
      if baseline_adjustable_active_months > 0
      else 0.0,
      6,
    ),
  }


def _required_structural_payroll_from_structure(
  *,
  units: float,
  people_payroll_floor: float,
  structural_payroll_floor: float,
  payroll_support_basis: str,
  units_per_active_role_month: float,
  fixed_active_role_months: float,
  adjustable_role_month_cost_floor: float,
  units_per_payroll_dollar: float,
) -> float:
  basis = str(payroll_support_basis or "").strip().lower()
  if basis == "role_months" and units_per_active_role_month > 0 and adjustable_role_month_cost_floor > 0:
    required_adjustable_active_months = max(
      0.0,
      (max(0.0, units) / units_per_active_role_month) - max(0.0, fixed_active_role_months),
    )
    return max(
      structural_payroll_floor,
      people_payroll_floor + (adjustable_role_month_cost_floor * required_adjustable_active_months),
    )
  if basis == "payroll" and units_per_payroll_dollar > 0:
    return max(
      structural_payroll_floor,
      max(0.0, units) / units_per_payroll_dollar,
    )
  return structural_payroll_floor


def _default_payroll_center(traits: Dict[str, Any]) -> float:
  driver = str(traits.get("capacity_driver") or "").strip().lower()
  return {
    "labor": 0.30,
    "system": 0.10,
    "space": 0.18,
    "equipment": 0.18,
    "demand": 0.15,
  }.get(driver, 0.18)


def _default_opex_center(traits: Dict[str, Any]) -> float:
  modality = str(traits.get("sales_modality") or "").strip().lower()
  return {
    "local_service": 0.16,
    "retail": 0.18,
    "online": 0.12,
    "project_based": 0.15,
    "manufacturing": 0.10,
    "hybrid": 0.16,
  }.get(modality, 0.15)


def _default_gross_margin_center(traits: Dict[str, Any]) -> float:
  modality = str(traits.get("sales_modality") or "").strip().lower()
  center = {
    "local_service": 0.62,
    "retail": 0.42,
    "online": 0.68,
    "project_based": 0.64,
    "manufacturing": 0.34,
    "hybrid": 0.52,
  }.get(modality, 0.50)
  driver = str(traits.get("capacity_driver") or "").strip().lower()
  if driver == "labor":
    center += 0.04
  elif driver == "system":
    center += 0.08
  return max(0.15, min(0.92, center))


def _default_ebitda_center(traits: Dict[str, Any]) -> float:
  stage = str(traits.get("business_stage") or "").strip().lower()
  modality = str(traits.get("sales_modality") or "").strip().lower()
  base = {
    "local_service": 0.11,
    "retail": 0.08,
    "online": 0.16,
    "project_based": 0.13,
    "manufacturing": 0.10,
    "hybrid": 0.11,
  }.get(modality, 0.10)
  stage_adjustment = {
    "pre_revenue": -0.18,
    "startup": -0.08,
    "operating": 0.0,
    "growth": 0.01,
    "mature": 0.03,
  }.get(stage, -0.02)
  driver = str(traits.get("capacity_driver") or "").strip().lower()
  if driver == "system":
    base += 0.03
  elif driver == "labor":
    base -= 0.01
  return max(-0.20, min(0.40, base + stage_adjustment))


def _stage_band_adjustment(traits: Dict[str, Any]) -> float:
  stage = str(traits.get("business_stage") or "").strip().lower()
  return {
    "pre_revenue": 0.10,
    "startup": 0.08,
    "operating": 0.04,
    "growth": 0.05,
    "mature": 0.03,
  }.get(stage, 0.06)


def _trait_payroll_band(*, traits: Dict[str, Any], current_ratio: Optional[float]) -> Dict[str, Optional[float]]:
  center = current_ratio if current_ratio is not None and current_ratio > 0 else _default_payroll_center(traits)
  width = 0.10 + _stage_band_adjustment(traits)
  return _clamp_band(center - width, center + width, floor=0.0, ceiling=1.0)


def _trait_opex_band(*, traits: Dict[str, Any], current_ratio: Optional[float]) -> Dict[str, Optional[float]]:
  center = current_ratio if current_ratio is not None and current_ratio > 0 else _default_opex_center(traits)
  width = 0.10 + _stage_band_adjustment(traits)
  return _clamp_band(center - width, center + width, floor=0.0, ceiling=1.0)


def _trait_gross_margin_band(*, traits: Dict[str, Any], current_ratio: Optional[float]) -> Dict[str, Optional[float]]:
  center = _default_gross_margin_center(traits)
  if current_ratio is not None and current_ratio > 0:
    center = (center * 0.65) + (current_ratio * 0.35)
  width = 0.12 + (_stage_band_adjustment(traits) * 0.5)
  return _clamp_band(center - width, center + width, floor=0.0, ceiling=1.0)


def _trait_ebitda_band(*, traits: Dict[str, Any], current_ratio: Optional[float]) -> Dict[str, Optional[float]]:
  center = _default_ebitda_center(traits)
  if current_ratio is not None:
    center = (center * 0.75) + (current_ratio * 0.25)
  width = 0.07 + _stage_band_adjustment(traits)
  return _clamp_band(center - width, center + width, floor=-0.30, ceiling=0.50)


def _trait_utilization_band(*, traits: Dict[str, Any], current_util: Optional[float]) -> Dict[str, Optional[float]]:
  stage = str(traits.get("business_stage") or "").strip().lower()
  driver = str(traits.get("capacity_driver") or "").strip().lower()
  modality = str(traits.get("sales_modality") or "").strip().lower()
  cadence = str(traits.get("unit_cadence") or "").strip().lower()
  base_bounds = {
    "pre_revenue": (0.0, 0.40),
    "startup": (0.10, 0.62),
    "operating": (0.25, 0.82),
    "growth": (0.35, 0.86),
    "mature": (0.45, 0.88),
  }.get(stage, (0.10, 0.78))
  lower = base_bounds[0]
  upper = base_bounds[1]
  if driver == "labor":
    if modality in {"local_service", "project_based"}:
      lower += 0.12
      upper = min(upper, 0.84)
    if cadence in {"contract", "project"}:
      lower += 0.05
      upper = min(upper, 0.82)
  elif driver == "system":
    lower = max(0.05, lower - 0.10)
    upper = min(0.95, upper + 0.06)
  elif driver in {"space", "equipment"}:
    lower += 0.03
    upper = min(upper, 0.87)
  driver = str(traits.get("capacity_driver") or "").strip().lower()
  if driver == "labor":
    upper = min(upper, 0.85)
  elif driver == "system":
    upper = min(0.95, upper + 0.05)
  if current_util is None:
    return _clamp_band(lower, upper, floor=0.0, ceiling=1.0)
  high = max(upper, min(1.0, current_util + 0.06))
  return _clamp_band(lower, high, floor=0.0, ceiling=1.0)


def _hard_utilization_floor(
  *,
  traits: Dict[str, Any],
  utilization_band: Dict[str, Any],
) -> Optional[float]:
  stage = str(traits.get("business_stage") or "").strip().lower()
  driver = str(traits.get("capacity_driver") or "").strip().lower()
  modality = str(traits.get("sales_modality") or "").strip().lower()
  cadence = str(traits.get("unit_cadence") or "").strip().lower()
  if driver != "labor" or stage not in {"operating", "growth", "mature"}:
    return None
  floor = {
    "local_service": 0.45,
    "project_based": 0.42,
    "retail": 0.35,
    "hybrid": 0.38,
    "manufacturing": 0.36,
    "online": 0.30,
  }.get(modality, 0.35)
  if cadence in {"contract", "project"}:
    floor += 0.05
  if stage == "growth":
    floor += 0.03
  elif stage == "mature":
    floor += 0.05
  band_min = _band_value_min(utilization_band)
  if band_min is not None:
    floor = max(floor, band_min)
  return round(min(0.90, max(0.0, floor)), 6)


def _benchmark_or_trait_band(
  benchmark_band: Dict[str, Any],
  trait_band: Dict[str, Any],
  *,
  benchmark_confidence: float,
  fallback_level: str,
) -> Tuple[Dict[str, Any], str]:
  benchmark_min = _band_value_min(benchmark_band)
  benchmark_max = _band_value_max(benchmark_band)
  trait_min = _band_value_min(trait_band)
  trait_max = _band_value_max(trait_band)
  if benchmark_min is None and benchmark_max is None:
    return trait_band, "trait"

  fallback_weight = {
    "naics_6": 1.0,
    "naics_5": 0.92,
    "naics_4": 0.85,
    "naics_3": 0.75,
    "naics_2": 0.65,
    "trait_based": 0.45,
    "generic": 0.18,
  }.get(str(fallback_level or "generic").strip().lower(), 0.25)
  alpha_weight = max(0.0, min(0.9, benchmark_confidence * fallback_weight))
  if alpha_weight <= 0.0:
    return trait_band, "trait"

  def _blend_value(trait_value: Optional[float], benchmark_value: Optional[float]) -> Optional[float]:
    if benchmark_value is None and trait_value is None:
      return None
    if benchmark_value is None:
      return trait_value
    if trait_value is None:
      return benchmark_value
    return (trait_value * (1.0 - alpha_weight)) + (benchmark_value * alpha_weight)

  floor = -0.30 if ((trait_min is not None and trait_min < 0) or (benchmark_min is not None and benchmark_min < 0)) else 0.0
  blended = _clamp_band(
    _blend_value(trait_min, benchmark_min),
    _blend_value(trait_max, benchmark_max),
    floor=floor,
    ceiling=1.0,
  )
  if alpha_weight >= 0.6:
    return blended, "alpha"
  if alpha_weight >= 0.25:
    return blended, "alpha_blend"
  return trait_band, "trait"


def _add_violation(
  findings: List[Dict[str, Any]],
  violations: List[str],
  *,
  code: str,
  constraint_class: str,
  metric: str,
  actual: Any,
  bound_min: Any = None,
  bound_max: Any = None,
  severity: str = "warning",
  explanation: str,
) -> None:
  if code not in VIOLATION_CODES:
    return
  if code not in violations:
    violations.append(code)
  findings.append(
    {
      "code": code,
      "constraint_class": str(constraint_class or "soft").strip() or "soft",
      "metric": metric,
      "severity": severity,
      "actual": actual,
      "bound_min": bound_min,
      "bound_max": bound_max,
      "explanation": explanation,
    }
  )


def _constraint_item(
  *,
  constraint_id: str,
  metric: str,
  bound_type: str,
  constraint_class: str,
  source_type: str,
  confidence_score: float,
  explanation: str,
) -> Dict[str, Any]:
  return {
    "constraint_id": constraint_id,
    "metric": metric,
    "bound_type": bound_type,
    "constraint_class": str(constraint_class or "soft").strip() or "soft",
    "source_type": source_type,
    "confidence_score": round(max(0.0, min(1.0, confidence_score)), 3),
    "explanation": explanation,
    "engine_version": CONSTRAINT_ENGINE_VERSION,
  }


def build_constraint_engine_bundle(
  *,
  conn=None,
  shared_context: Optional[Dict[str, Any]] = None,
  operating_model_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  fulfillment_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  ops = operating_model_json if isinstance(operating_model_json, dict) else dict((shared_context or {}).get("operating_model") or {})
  market = target_market_json if isinstance(target_market_json, dict) else dict((shared_context or {}).get("target_market") or {})
  people = people_json if isinstance(people_json, dict) else dict((shared_context or {}).get("people_capability") or {})
  financials = financials_json if isinstance(financials_json, dict) else dict((shared_context or {}).get("financials") or {})
  year1 = (
    financials_year1_json
    if isinstance(financials_year1_json, dict)
    else dict((shared_context or {}).get("financials_year1_json") or {})
  )
  marketing = (
    marketing_model_json if isinstance(marketing_model_json, dict) else dict((shared_context or {}).get("marketing") or {})
  )
  fulfillment = fulfillment_json if isinstance(fulfillment_json, dict) else dict((shared_context or {}).get("fulfillment_json") or {})
  financials_for_summary = dict(financials)
  if _nonneg(financials_for_summary.get("payroll_total_year1")) <= 0 and _nonneg(financials_for_summary.get("current_payroll")) <= 0:
    derived_payroll = _derived_year1_payroll_from_people(people)
    if derived_payroll > 0:
      financials_for_summary["payroll_total_year1"] = derived_payroll
      financials_for_summary["current_payroll"] = derived_payroll

  traits = extract_normalized_traits(
    conn=conn,
    shared_context=shared_context,
    operating_model=ops,
    target_market=market,
    financials_year1_json=year1,
    fulfillment_json=fulfillment,
  )
  benchmark = resolve_alpha_benchmark_payload(normalized_traits=traits, conn=conn)
  summary = build_consistency_financial_summary(
    financials_json=financials_for_summary,
    financials_year1_json=year1,
  )

  child_basis = _build_child_metric_basis(year1)
  has_child_metrics = bool(child_basis)

  current_units = _required_units_year1(year1)
  current_price = _nonneg((_weighted_child_price(child_basis) if has_child_metrics else None) or _top_level_driver_value(year1, "unit_price") or ops.get("unit_price"))
  current_util = _normalize_ratio((_weighted_child_utilization(child_basis) if has_child_metrics else None) or _top_level_driver_value(year1, "utilization_rate") or ops.get("utilization_rate"))
  current_revenue = _nonneg(summary.get("revenue"))
  current_payroll = _nonneg(summary.get("payroll"))
  current_marketing = _nonneg(summary.get("marketing"))
  current_other_opex = _nonneg(summary.get("other_opex"))
  current_cogs = _nonneg(summary.get("cogs"))
  current_gross_margin = ((current_revenue - current_cogs) / current_revenue) if current_revenue > 0 else None
  current_ebitda_margin = (_to_float(summary.get("ebitda")) / current_revenue) if current_revenue > 0 else None
  current_payroll_ratio = (current_payroll / current_revenue) if current_revenue > 0 else None
  current_marketing_ratio = (current_marketing / current_revenue) if current_revenue > 0 else None
  current_opex_ratio = (current_other_opex / current_revenue) if current_revenue > 0 else None
  benchmark_confidence = _to_float((benchmark or {}).get("confidence_score")) or 0.0
  benchmark_fallback_level = str((benchmark or {}).get("fallback_level") or "generic").strip() or "generic"

  capacity_units = sum(max(0.0, _to_float(item.get("annual_capacity_units")) or 0.0) for item in child_basis if isinstance(item, dict))
  if capacity_units <= 0:
    per_period_capacity = _nonneg(_top_level_driver_value(year1, "units_per_period_capacity") or ops.get("units_per_period_capacity"))
    periods = _nonneg(_top_level_driver_value(year1, "operating_periods_per_year") or year1.get("operating_periods_per_year"))
    if per_period_capacity > 0 and periods > 0:
      capacity_units = per_period_capacity * periods
    else:
      week_capacity = _nonneg(_top_level_driver_value(year1, "units_per_week_capacity") or ops.get("units_per_week_capacity"))
      weeks = _nonneg(_top_level_driver_value(year1, "operating_weeks_per_year") or year1.get("operating_weeks_per_year") or 52)
      if week_capacity > 0 and weeks > 0:
        capacity_units = week_capacity * weeks
      elif current_util is not None and current_util > 0 and current_units > 0:
        capacity_units = current_units / max(current_util, 1e-9)

  demand_supported_units = None
  for key in ("expected_units_year1", "required_units_year1", "expected_customers_or_clients_year1", "reachable_market"):
    value = _to_float(marketing.get(key))
    if value is not None and value > 0:
      demand_supported_units = float(value)
      break

  utilization_band = _trait_utilization_band(traits=traits, current_util=current_util)
  hard_utilization_floor = _hard_utilization_floor(
    traits=traits,
    utilization_band=utilization_band,
  )
  util_max = _band_value_max(utilization_band) or 1.0
  util_min = _band_value_min(utilization_band) or 0.0
  supportable_units_max = capacity_units * util_max if capacity_units > 0 else current_units
  supportable_units_min = 0.0
  supportable_unit_range = {
    "min": round(max(0.0, supportable_units_min), 2),
    "max": round(max(0.0, supportable_units_max), 2),
  }

  supportable_revenue_range = {
    "min": round(max(0.0, supportable_unit_range["min"] * current_price), 2) if current_price > 0 else 0.0,
    "max": round(max(0.0, supportable_unit_range["max"] * current_price), 2) if current_price > 0 else round(current_revenue, 2),
  }

  gross_margin_band, gross_margin_source = _benchmark_or_trait_band(
    benchmark.get("gross_margin_band") if isinstance(benchmark, dict) else {},
    _trait_gross_margin_band(traits=traits, current_ratio=current_gross_margin),
    benchmark_confidence=benchmark_confidence,
    fallback_level=benchmark_fallback_level,
  )
  ebitda_margin_band, ebitda_source = _benchmark_or_trait_band(
    benchmark.get("ebitda_margin_band") if isinstance(benchmark, dict) else {},
    _trait_ebitda_band(traits=traits, current_ratio=current_ebitda_margin),
    benchmark_confidence=benchmark_confidence,
    fallback_level=benchmark_fallback_level,
  )
  payroll_intensity_band, payroll_source = _benchmark_or_trait_band(
    benchmark.get("payroll_intensity") if isinstance(benchmark, dict) else {},
    _trait_payroll_band(traits=traits, current_ratio=current_payroll_ratio),
    benchmark_confidence=benchmark_confidence,
    fallback_level=benchmark_fallback_level,
  )
  opex_intensity_band, opex_source = _benchmark_or_trait_band(
    benchmark.get("opex_intensity") if isinstance(benchmark, dict) else {},
    _trait_opex_band(traits=traits, current_ratio=current_opex_ratio),
    benchmark_confidence=benchmark_confidence,
    fallback_level=benchmark_fallback_level,
  )
  marketing_intensity_band = _trait_marketing_band(
    traits=traits,
    current_ratio=current_marketing_ratio,
    opex_band=opex_intensity_band,
  )
  working_capital_band = (benchmark.get("working_capital") if isinstance(benchmark, dict) else {}) or {
    "dso": {"min": None, "max": None},
    "dpo": {"min": None, "max": None},
    "inventory_days": {"min": None, "max": None},
  }
  trait_confidence = 0.15
  populated_traits = len([key for key in ("naics_6", "business_type", "customer_type", "sales_modality", "capacity_driver", "unit_cadence", "geographic_scope", "business_stage", "fulfillment_shape") if traits.get(key)])
  trait_confidence += min(0.35, populated_traits * 0.04)
  constraint_confidence_score = round(min(0.95, 0.5 * benchmark_confidence + 0.5 * trait_confidence), 3)

  active_role_months = 0.0
  current_people_count = 0
  planned_roles_count = 0
  role_month_support = _role_month_support_metrics(people or {})
  fixed_people_payroll = max(0.0, _to_float(role_month_support.get("fixed_people_payroll")) or 0.0)
  fixed_active_role_months = max(0.0, _to_float(role_month_support.get("fixed_active_role_months")) or 0.0)
  baseline_adjustable_active_months = max(0.0, _to_float(role_month_support.get("baseline_adjustable_active_months")) or 0.0)
  adjustable_role_month_cost_floor = max(0.0, _to_float(role_month_support.get("adjustable_role_month_cost_floor")) or 0.0)
  for person in (people or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    current_people_count += 1
    active_role_months += 12.0
  for role in (people or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    planned_roles_count += 1
    months_until_hire = int(max(0, min(12, round(_to_float(role.get("months_until_hire")) or 0.0))))
    active_role_months += max(0, 12 - months_until_hire)
  fte_equivalent = active_role_months / 12.0
  workload_required_payroll = 0.0
  required_fte = 0.0
  revenue_per_fte = None
  payroll_support_basis = "floor"
  units_per_active_role_month = 0.0
  units_per_payroll_dollar = 0.0
  if str(traits.get("capacity_driver") or "").strip().lower() == "labor" and fte_equivalent > 0 and current_revenue > 0:
    thresholds = _labor_workload_thresholds(traits)
    max_revenue_per_fte = max(1.0, _to_float(thresholds.get("max_revenue_per_fte")) or 1.0)
    required_fte = current_revenue / max_revenue_per_fte
    implied_comp_per_fte = max(
      (current_payroll / max(fte_equivalent, 1e-9)) if current_payroll > 0 else 0.0,
      (_derived_year1_payroll_from_people(people) / max(fte_equivalent, 1e-9)) if fte_equivalent > 0 else 0.0,
      _default_compensation_per_fte(traits),
    )
    workload_required_payroll = required_fte * implied_comp_per_fte
    revenue_per_fte = current_revenue / max(fte_equivalent, 1e-9)
  people_payroll_floor = fixed_people_payroll
  if active_role_months > 0 and current_units > 0 and adjustable_role_month_cost_floor > 0:
    payroll_support_basis = "role_months"
    units_per_active_role_month = current_units / max(active_role_months, 1e-9)
  elif people_payroll_floor > 0 and current_units > 0:
    payroll_support_basis = "payroll"
    units_per_payroll_dollar = current_units / max(people_payroll_floor, 1e-9)
  structural_payroll_floor = max(people_payroll_floor, workload_required_payroll)
  structural_payroll_base = people_payroll_floor
  structural_payroll_floor = max(
    structural_payroll_floor,
    _required_structural_payroll_from_structure(
      units=current_units,
      people_payroll_floor=people_payroll_floor,
      structural_payroll_floor=structural_payroll_floor,
      payroll_support_basis=payroll_support_basis,
      units_per_active_role_month=units_per_active_role_month,
      fixed_active_role_months=fixed_active_role_months,
      adjustable_role_month_cost_floor=adjustable_role_month_cost_floor,
      units_per_payroll_dollar=units_per_payroll_dollar,
    ),
  )

  violations: List[str] = []
  findings: List[Dict[str, Any]] = []

  if supportable_unit_range["max"] > 0 and current_units > supportable_unit_range["max"] * 1.01:
    _add_violation(
      findings,
      violations,
      code="capacity_unsupported",
      constraint_class="hard",
      metric="units",
      actual=round(current_units, 2),
      bound_max=supportable_unit_range["max"],
      explanation="Planned Year-1 units exceed the supportable capacity implied by persisted capacity and utilization assumptions.",
    )

  if demand_supported_units is not None and demand_supported_units > 0 and current_units > demand_supported_units * 1.01:
    _add_violation(
      findings,
      violations,
      code="demand_unsupported",
      constraint_class="context",
      metric="units",
      actual=round(current_units, 2),
      bound_max=round(demand_supported_units, 2),
      severity="info",
      explanation="Planned Year-1 units are above the currently modeled demand support, so the solver should consider marketing and demand-building levers before treating this as a hard ceiling.",
    )

  if supportable_revenue_range["max"] > 0 and current_revenue > supportable_revenue_range["max"] * 1.01:
    _add_violation(
      findings,
      violations,
      code="revenue_out_of_range",
      constraint_class="soft",
      metric="revenue",
      actual=round(current_revenue, 2),
      bound_max=supportable_revenue_range["max"],
      explanation="Planned Year-1 revenue exceeds the supportable revenue envelope implied by supportable units and current price assumptions.",
    )

  gross_min = _band_value_min(gross_margin_band)
  gross_max = _band_value_max(gross_margin_band)
  if current_gross_margin is not None and gross_max is not None and current_gross_margin > gross_max + 0.01:
    _add_violation(
      findings,
      violations,
      code="gross_margin_too_high",
      constraint_class="soft",
      metric="gross_margin",
      actual=round(current_gross_margin, 6),
      bound_max=gross_max,
      explanation="Gross margin is above the benchmark or fallback realism band for the current business traits and industry match.",
    )
  if current_gross_margin is not None and gross_min is not None and current_gross_margin < gross_min - 0.01:
    _add_violation(
      findings,
      violations,
      code="gross_margin_too_low",
      constraint_class="soft",
      metric="gross_margin",
      actual=round(current_gross_margin, 6),
      bound_min=gross_min,
      explanation="Gross margin is below the benchmark or fallback realism band for the current business traits and industry match.",
    )

  ebitda_min = _band_value_min(ebitda_margin_band)
  ebitda_max = _band_value_max(ebitda_margin_band)
  if current_ebitda_margin is not None and ebitda_max is not None and current_ebitda_margin > ebitda_max + 0.01:
    _add_violation(
      findings,
      violations,
      code="ebitda_margin_too_high",
      constraint_class="soft",
      metric="ebitda_margin",
      actual=round(current_ebitda_margin, 6),
      bound_max=ebitda_max,
      explanation="EBITDA margin is above the current realism band and is likely unsupported by the plan's staffing, utilization, or spend structure.",
    )
  if current_ebitda_margin is not None and ebitda_min is not None and current_ebitda_margin < ebitda_min - 0.01:
    _add_violation(
      findings,
      violations,
      code="ebitda_margin_too_low",
      constraint_class="soft",
      metric="ebitda_margin",
      actual=round(current_ebitda_margin, 6),
      bound_min=ebitda_min,
      explanation="EBITDA margin is below the current realism band and may indicate unsupported downside economics or an overbuilt cost structure.",
    )

  payroll_min = _band_value_min(payroll_intensity_band)
  payroll_max = _band_value_max(payroll_intensity_band)
  if (
    current_payroll > 0
    and structural_payroll_floor > 0
    and current_payroll < (structural_payroll_floor * 0.97)
  ):
    _add_violation(
      findings,
      violations,
      code="payroll_too_light",
      constraint_class="hard",
      metric="payroll_intensity",
      actual=round(current_payroll_ratio, 6) if current_payroll_ratio is not None else None,
      bound_min=round((structural_payroll_floor / max(current_revenue, 1.0)), 6) if current_revenue > 0 else None,
      explanation="Payroll support is below the structural requirement implied by the current workload, staffing basis, and Year-1 labor model.",
    )
  if current_payroll_ratio is not None and payroll_max is not None and current_payroll_ratio > payroll_max + 0.01:
    _add_violation(
      findings,
      violations,
      code="payroll_too_heavy",
      constraint_class="soft",
      metric="payroll_intensity",
      actual=round(current_payroll_ratio, 6),
      bound_max=payroll_max,
      explanation="Payroll intensity is above the realism band for this plan and may indicate an overstaffed or underproductive Year-1 setup.",
    )

  opex_min = _band_value_min(opex_intensity_band)
  opex_max = _band_value_max(opex_intensity_band)
  marketing_min = _band_value_min(marketing_intensity_band)
  marketing_max = _band_value_max(marketing_intensity_band)
  if current_marketing_ratio is not None and marketing_min is not None and current_marketing_ratio < marketing_min - 0.01:
    _add_violation(
      findings,
      violations,
      code="marketing_too_low",
      constraint_class="soft",
      metric="marketing_intensity",
      actual=round(current_marketing_ratio, 6),
      bound_min=marketing_min,
      severity="info",
      explanation="Marketing intensity is below the current realism corridor for this business model and may under-support the stated demand path.",
    )
  if current_marketing_ratio is not None and marketing_max is not None and current_marketing_ratio > marketing_max + 0.01:
    _add_violation(
      findings,
      violations,
      code="marketing_too_high",
      constraint_class="soft",
      metric="marketing_intensity",
      actual=round(current_marketing_ratio, 6),
      bound_max=marketing_max,
      explanation="Marketing intensity is above the realism corridor for this business model and is too large to be the default absorber of other plan inconsistencies.",
    )
  if current_opex_ratio is not None and opex_min is not None and current_opex_ratio < opex_min - 0.01:
    _add_violation(
      findings,
      violations,
      code="opex_too_light",
      constraint_class="soft",
      metric="opex_intensity",
      actual=round(current_opex_ratio, 6),
      bound_min=opex_min,
      explanation="Operating expense intensity is below the realism band and may be understating the cost to support the current business model.",
    )
  if current_opex_ratio is not None and opex_max is not None and current_opex_ratio > opex_max + 0.01:
    _add_violation(
      findings,
      violations,
      code="opex_too_heavy",
      constraint_class="soft",
      metric="opex_intensity",
      actual=round(current_opex_ratio, 6),
      bound_max=opex_max,
      explanation="Operating expense intensity is above the realism band for the current business model and benchmark context.",
    )

  if current_util is not None and current_util > util_max + 0.01:
    _add_violation(
      findings,
      violations,
      code="utilization_too_high",
      constraint_class="soft",
      metric="utilization_rate",
      actual=round(current_util, 6),
      bound_max=util_max,
      explanation="Utilization is above the trait-derived realism band for the current stage and capacity model.",
    )
  if current_util is not None and hard_utilization_floor is not None and current_units > 0 and current_util < hard_utilization_floor - 0.01:
    _add_violation(
      findings,
      violations,
      code="utilization_too_low",
      constraint_class="hard",
      metric="utilization_rate",
      actual=round(current_util, 6),
      bound_min=hard_utilization_floor,
      explanation="Utilization is below the hard credibility floor for the current operating labor model and makes the Year-1 plan operationally unrealistic.",
    )
  elif current_util is not None and current_units > 0 and current_util < util_min - 0.01:
    _add_violation(
      findings,
      violations,
      code="utilization_too_low",
      constraint_class="soft",
      metric="utilization_rate",
      actual=round(current_util, 6),
      bound_min=util_min,
      explanation="Utilization is below the trait-derived realism band for the current stage and capacity model.",
    )

  if benchmark_confidence < 0.4:
    _add_violation(
      findings,
      violations,
      code="benchmark_low_confidence",
      constraint_class="context",
      metric="benchmark_confidence",
      actual=benchmark_confidence,
      severity="info",
      explanation="Benchmark fallback confidence is low, so realism bands should be treated as wider and less prescriptive.",
    )

  constraints = [
    _constraint_item(
      constraint_id="capacity_support",
      metric="units",
      bound_type="hard",
      constraint_class="hard",
      source_type="fact",
      confidence_score=max(constraint_confidence_score, 0.6),
      explanation="Supportable unit range comes from persisted Year-1 volume, capacity, utilization, and demand-support facts.",
    ),
    _constraint_item(
      constraint_id="workload_payroll_support",
      metric="payroll_support",
      bound_type="hard",
      constraint_class="hard",
      source_type="fact",
      confidence_score=max(constraint_confidence_score, 0.6),
      explanation="Workload support requires Year-1 payroll and staffing structure to credibly support the planned delivery load.",
    ),
    _constraint_item(
      constraint_id="supportable_revenue_range",
      metric="revenue",
      bound_type="soft",
      constraint_class="soft",
      source_type="fact",
      confidence_score=max(constraint_confidence_score, 0.55),
      explanation="Supportable revenue range is derived from supportable units and the current persisted price assumption.",
    ),
    _constraint_item(
      constraint_id="demand_supported_units",
      metric="units",
      bound_type="soft",
      constraint_class="context",
      source_type="fact",
      confidence_score=max(constraint_confidence_score, 0.45),
      explanation="Demand-supported units reflect the currently modeled Year-1 demand support and should shape solver choices without acting as a universal hard cap when demand-building levers are still mutable.",
    ),
    _constraint_item(
      constraint_id="gross_margin_band",
      metric="gross_margin",
      bound_type="soft" if gross_margin_source == "alpha" else "prior",
      constraint_class="soft",
      source_type=gross_margin_source,
      confidence_score=max(constraint_confidence_score, benchmark_confidence if gross_margin_source == "alpha" else trait_confidence),
      explanation="Gross margin band uses Alpha benchmark data when available and falls back to a current-state band when benchmark coverage is limited.",
    ),
    _constraint_item(
      constraint_id="ebitda_margin_band",
      metric="ebitda_margin",
      bound_type="soft" if ebitda_source == "alpha" else "prior",
      constraint_class="soft",
      source_type=ebitda_source,
      confidence_score=max(constraint_confidence_score, benchmark_confidence if ebitda_source == "alpha" else trait_confidence),
      explanation="EBITDA margin band is the core realism envelope for detecting unsupported downside and upside profitability.",
    ),
    _constraint_item(
      constraint_id="payroll_intensity_band",
      metric="payroll_intensity",
      bound_type="soft" if payroll_source == "alpha" else "prior",
      constraint_class="soft",
      source_type=payroll_source,
      confidence_score=max(constraint_confidence_score, benchmark_confidence if payroll_source == "alpha" else trait_confidence),
      explanation="Payroll intensity band uses benchmarks when present and otherwise falls back to trait-derived operating priors.",
    ),
    _constraint_item(
      constraint_id="marketing_intensity_band",
      metric="marketing_intensity",
      bound_type="soft",
      constraint_class="soft",
      source_type="trait",
      confidence_score=trait_confidence,
      explanation="Marketing intensity corridor is trait-driven and bounded by business model and compatible operating-expense realism.",
    ),
    _constraint_item(
      constraint_id="opex_intensity_band",
      metric="opex_intensity",
      bound_type="soft" if opex_source == "alpha" else "prior",
      constraint_class="soft",
      source_type=opex_source,
      confidence_score=max(constraint_confidence_score, benchmark_confidence if opex_source == "alpha" else trait_confidence),
      explanation="Operating expense intensity band uses Alpha benchmark data when available and falls back to deterministic trait priors otherwise.",
    ),
    _constraint_item(
      constraint_id="utilization_range",
      metric="utilization_rate",
      bound_type="soft",
      constraint_class="soft",
      source_type="trait",
      confidence_score=trait_confidence,
      explanation="Utilization range is trait-derived from business stage and capacity model and is used to evaluate whether the Year-1 operating load is plausible.",
    ),
  ]
  if hard_utilization_floor is not None:
    constraints.insert(
      2,
      _constraint_item(
        constraint_id="utilization_hard_floor",
        metric="utilization_rate",
        bound_type="hard",
        constraint_class="hard",
        source_type="trait",
        confidence_score=trait_confidence,
        explanation="Operating labor-driven businesses must stay above a hard utilization credibility floor for Year 1.",
      ),
    )
  hard_violation_codes = sorted({
    str(item.get("code") or "").strip()
    for item in findings
    if str(item.get("constraint_class") or "").strip() == "hard" and str(item.get("code") or "").strip()
  })
  soft_violation_codes = sorted({
    str(item.get("code") or "").strip()
    for item in findings
    if str(item.get("constraint_class") or "").strip() == "soft" and str(item.get("code") or "").strip()
  })
  context_violation_codes = sorted({
    str(item.get("code") or "").strip()
    for item in findings
    if str(item.get("constraint_class") or "").strip() == "context" and str(item.get("code") or "").strip()
  })

  engine_state = {
    "contract_version": PLANNING_CONTRACT_VERSION,
    "engine_version": CONSTRAINT_ENGINE_VERSION,
    "constraint_confidence_score": constraint_confidence_score,
    "fallback_level": str((benchmark or {}).get("fallback_level") or "generic"),
    "supportable_unit_range": supportable_unit_range,
    "supportable_revenue_range": supportable_revenue_range,
    "gross_margin_band": gross_margin_band,
    "ebitda_margin_band": ebitda_margin_band,
    "payroll_intensity_band": payroll_intensity_band,
    "marketing_intensity_band": marketing_intensity_band,
    "opex_intensity_band": opex_intensity_band,
    "working_capital_band": working_capital_band,
    "utilization_range": utilization_band,
    "demand_supported_units": round(demand_supported_units, 2) if demand_supported_units is not None else None,
    "solver_mutable_levers": list(SOLVER_MUTABLE_LEVERS),
    "solver_protected_facts": list(SOLVER_PROTECTED_FACTS),
    "violations": violations,
    "hard_violation_codes": hard_violation_codes,
    "soft_violation_codes": soft_violation_codes,
    "context_violation_codes": context_violation_codes,
    "constraints": constraints,
    "findings": findings,
    "current_metrics": {
      "units_year1": round(current_units, 2),
      "revenue_year1": round(current_revenue, 2),
      "price": round(current_price, 2),
      "utilization_rate": round(current_util, 6) if current_util is not None else None,
      "gross_margin": round(current_gross_margin, 6) if current_gross_margin is not None else None,
      "ebitda_margin": round(current_ebitda_margin, 6) if current_ebitda_margin is not None else None,
      "payroll_intensity": round(current_payroll_ratio, 6) if current_payroll_ratio is not None else None,
      "marketing_intensity": round(current_marketing_ratio, 6) if current_marketing_ratio is not None else None,
      "opex_intensity": round(current_opex_ratio, 6) if current_opex_ratio is not None else None,
      "capacity_units_year1": round(capacity_units, 2),
      "child_product_count": len(child_basis),
      "weighted_child_price": round(_weighted_child_price(child_basis), 2) if has_child_metrics and _weighted_child_price(child_basis) is not None else None,
      "weighted_child_utilization_rate": round(_weighted_child_utilization(child_basis), 6) if has_child_metrics and _weighted_child_utilization(child_basis) is not None else None,
      "people_payroll_floor": round(people_payroll_floor, 2),
      "structural_payroll_floor": round(structural_payroll_floor, 2),
      "structural_payroll_base": round(structural_payroll_base, 2),
      "workload_payroll_per_unit": 0.0,
      "payroll_support_basis": payroll_support_basis,
      "fixed_active_role_months": round(fixed_active_role_months, 2),
      "baseline_adjustable_active_months": round(baseline_adjustable_active_months, 2),
      "adjustable_role_month_cost_floor": round(adjustable_role_month_cost_floor, 6),
      "units_per_active_role_month": round(units_per_active_role_month, 6),
      "units_per_payroll_dollar": round(units_per_payroll_dollar, 8),
      "hard_utilization_floor": hard_utilization_floor,
      "active_role_months_year1": round(active_role_months, 2),
      "fte_equivalent_year1": round(fte_equivalent, 4),
      "revenue_per_fte_year1": round(revenue_per_fte, 2) if revenue_per_fte is not None else None,
      "required_fte_from_workload": round(required_fte, 4),
      "current_people_count": current_people_count,
      "planned_roles_count": planned_roles_count,
    },
    "summary": summary,
  }

  versions = engine_versions_payload()
  versions["constraint_traits_version"] = CONSTRAINT_TRAITS_VERSION
  versions["benchmark_resolver_version"] = BENCHMARK_RESOLVER_VERSION
  versions["constraint_engine_version"] = CONSTRAINT_ENGINE_VERSION

  return {
    "normalized_traits": traits,
    "benchmark_payload": benchmark,
    "constraint_engine_state": engine_state,
    "engine_versions": versions,
  }
