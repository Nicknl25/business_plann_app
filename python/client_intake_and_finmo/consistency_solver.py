from __future__ import annotations

import json
import os
from itertools import combinations, product
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

try:
  from financials_year1 import apply_revenue_driver_patch  # type: ignore
except Exception:
  from client_intake_and_finmo.financials_year1 import apply_revenue_driver_patch  # type: ignore

try:
  from consistency_financials import (  # type: ignore
    build_consistency_financial_summary,
    build_consistency_financial_table,
  )
except Exception:
  from client_intake_and_finmo.consistency_financials import (  # type: ignore
    build_consistency_financial_summary,
    build_consistency_financial_table,
  )


def _load_root_env() -> None:
  try:
    from dotenv import load_dotenv  # type: ignore
  except Exception:
    return
  try:
    load_dotenv(str(ROOT_ENV_PATH))
  except Exception:
    pass


def _float_env(name: str, default: float) -> float:
  _load_root_env()
  raw = str(os.getenv(name) or "").strip()
  if not raw:
    return default
  try:
    return float(raw)
  except Exception:
    return default


def _bool_env(name: str, default: bool) -> bool:
  _load_root_env()
  raw = str(os.getenv(name) or "").strip().lower()
  if not raw:
    return default
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  return default


LOSS_THRESHOLD_RATIO = _float_env("CONSISTENCY_NET_LOSS_THRESHOLD_RATIO", 0.15)
PRICE_STEP_PCTS: Tuple[float, ...] = (0.05, 0.10)
UTILIZATION_STEP_PTS: Tuple[float, ...] = (0.05, 0.10)
MARKETING_REDUCTION_PCTS: Tuple[float, ...] = (0.10, 0.20)
OTHER_OPEX_REDUCTION_PCTS: Tuple[float, ...] = (0.10, 0.20)
HIRE_DELAY_STEPS_MONTHS: Tuple[int, ...] = (3, 6, 9, 12, 15)
MAX_SCENARIOS = 3
ROLE_WAGE_MIN_FACTOR = _float_env("CONSISTENCY_ROLE_WAGE_MIN_FACTOR", 0.85)
ROLE_WAGE_MAX_FACTOR = _float_env("CONSISTENCY_ROLE_WAGE_MAX_FACTOR", 1.00)
ENABLE_PRICE_LEVER = _bool_env("CONSISTENCY_SOLVER_ENABLE_PRICE", False)
PRICE_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_PRICE_WEIGHT", 18.0)
PRICE_DOWN_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_PRICE_DOWN_WEIGHT", 24.0)
UTILIZATION_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_UTILIZATION_WEIGHT", 4.0)
UTILIZATION_DOWN_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_UTILIZATION_DOWN_WEIGHT", UTILIZATION_DISTORTION_WEIGHT)
MARKETING_UP_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_MARKETING_UP_WEIGHT", 4.0)
MARKETING_DOWN_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_MARKETING_DOWN_WEIGHT", 5.0)
OTHER_OPEX_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_OTHER_OPEX_WEIGHT", 2.0)
OTHER_OPEX_UP_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_OTHER_OPEX_UP_WEIGHT", OTHER_OPEX_DISTORTION_WEIGHT)
COGS_DOWN_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_COGS_DOWN_WEIGHT", 1.5)
COGS_UP_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_COGS_UP_WEIGHT", 1.5)
HIRE_DELAY_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_HIRE_DELAY_WEIGHT", 6.0)
HIRE_ADVANCE_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_HIRE_ADVANCE_WEIGHT", 3.5)
PAYROLL_DOWN_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_PAYROLL_WEIGHT", 8.0)
PAYROLL_UP_DISTORTION_WEIGHT = _float_env("CONSISTENCY_SOLVER_PAYROLL_UP_WEIGHT", 3.5)
FAMILY_CONCENTRATION_WEIGHT = _float_env("CONSISTENCY_SOLVER_FAMILY_CONCENTRATION_WEIGHT", 6.0)
HEALTHY_EBITDA_MARGIN_RATIO = _float_env("CONSISTENCY_SOLVER_HEALTHY_EBITDA_MARGIN_RATIO", 0.05)
EBITDA_CUSHION_PREFERENCE_WEIGHT = _float_env("CONSISTENCY_SOLVER_EBITDA_CUSHION_WEIGHT", 1.5)
OPTION_OBJECTIVE_TOLERANCE_RATIO = _float_env("CONSISTENCY_SOLVER_OPTION_TOLERANCE_RATIO", 0.03)
OPTION_OBJECTIVE_TOLERANCE_ABS = _float_env("CONSISTENCY_SOLVER_OPTION_TOLERANCE_ABS", 0.05)
REALISM_DISTANCE_TOLERANCE = _float_env("CONSISTENCY_SOLVER_REALISM_DISTANCE_TOLERANCE", 0.001)
SOLVER_DISTANCE_REGRESSION_TOLERANCE = _float_env("CONSISTENCY_SOLVER_DISTANCE_REGRESSION_TOLERANCE", 0.10)
BLOCKING_VIOLATION_PENALTY = _float_env("CONSISTENCY_SOLVER_BLOCKING_VIOLATION_PENALTY", 250000.0)
NONBLOCKING_VIOLATION_PENALTY = _float_env("CONSISTENCY_SOLVER_NONBLOCKING_VIOLATION_PENALTY", 15000.0)
UNRESOLVED_BLOCKING_SCENARIO_LIMIT = max(0, int(round(_float_env("CONSISTENCY_SOLVER_UNRESOLVED_BLOCKING_LIMIT", 1.0))))

SCENARIO_ARCHETYPE_META = {
  "balanced": {
    "archetype": "operations",
    "display": "Operational balance",
    "tradeoff": "rebalances workload, staffing, and utilization without leaning too hard on one lever",
  },
  "operations_first": {
    "archetype": "operations",
    "display": "Operational balance",
    "tradeoff": "fixes delivery strain and support structure before pushing growth or cost cuts",
  },
  "labor_support_first": {
    "archetype": "operations",
    "display": "Operational balance",
    "tradeoff": "adds labor support or reduces strain so Year-1 workload is believable",
  },
  "growth_first": {
    "archetype": "growth",
    "display": "Growth path",
    "tradeoff": "protects the revenue plan and accepts more support spend where realism allows",
  },
  "profit_first": {
    "archetype": "efficiency",
    "display": "Efficiency path",
    "tradeoff": "improves margin quality and trims excess spend faster than the other paths",
  },
  "lean_survival": {
    "archetype": "efficiency",
    "display": "Efficiency path",
    "tradeoff": "leans harder on cost discipline and moderated demand to stabilize Year 1",
  },
}

BLOCKING_YEAR1_VIOLATIONS = {
  "capacity_unsupported",
  "revenue_out_of_range",
  "gross_margin_too_high",
  "gross_margin_too_low",
  "ebitda_margin_too_high",
  "ebitda_margin_too_low",
  "payroll_too_light",
  "payroll_too_heavy",
  "opex_too_light",
  "opex_too_heavy",
  "utilization_too_high",
  "utilization_too_low",
}


def _require_pulp():
  try:
    import pulp  # type: ignore
  except Exception as exc:
    raise RuntimeError("PuLP is required for the consistency solver.") from exc
  return pulp


def _clone(value: Any) -> Any:
  return json.loads(json.dumps(value, ensure_ascii=False))


def _safe_float(value: Any) -> float:
  if value is None or value == "" or isinstance(value, bool):
    return 0.0
  try:
    num = float(value)
  except Exception:
    return 0.0
  if num != num:
    return 0.0
  return num


def _safe_int(value: Any) -> Optional[int]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    return int(round(float(value)))
  except Exception:
    return None


def _lp_value(value: Any, default: float = 0.0) -> float:
  try:
    raw = value.value() if hasattr(value, "value") else value
  except Exception:
    raw = None
  if raw is None:
    return float(default)
  return float(raw)


def _normalize_ratio(value: Any) -> Optional[float]:
  if value is None or value == "" or isinstance(value, bool):
    return None
  try:
    ratio = float(value)
  except Exception:
    return None
  if ratio > 1.0:
    ratio = ratio / 100.0
  ratio = max(0.0, min(1.0, ratio))
  return ratio


def _format_currency(value: Any) -> str:
  amount = _safe_float(value)
  return f"${amount:,.0f}" if abs(amount - round(amount)) < 1e-9 else f"${amount:,.2f}"


def _format_percent(value: Any) -> str:
  ratio = _normalize_ratio(value)
  if ratio is None:
    return "0%"
  return f"{ratio * 100:.0f}%"


def _band_min(band: Any) -> Optional[float]:
  if not isinstance(band, dict):
    return None
  value = band.get("min")
  if value is None or value == "":
    return None
  return _safe_float(value)


def _band_max(band: Any) -> Optional[float]:
  if not isinstance(band, dict):
    return None
  value = band.get("max")
  if value is None or value == "":
    return None
  return _safe_float(value)


def _range_distance(value: Optional[float], *, min_value: Optional[float], max_value: Optional[float], scale: float) -> float:
  if value is None:
    return 0.0
  denom = max(abs(scale), 1e-6)
  if min_value is not None and value < min_value:
    return max(0.0, (min_value - value) / denom)
  if max_value is not None and value > max_value:
    return max(0.0, (value - max_value) / denom)
  return 0.0


def _ebitda_target_distance(
  summary: Dict[str, Any],
  *,
  target_ebitda_min: Optional[float],
  target_ebitda_max: Optional[float],
) -> float:
  ebitda = _safe_float((summary or {}).get("ebitda"))
  revenue = max(1.0, _safe_float((summary or {}).get("revenue")))
  return _range_distance(
    ebitda,
    min_value=target_ebitda_min,
    max_value=target_ebitda_max,
    scale=revenue,
  )


def _constraint_engine_realism_distance(
  *,
  constraint_engine_state: Optional[Dict[str, Any]],
  summary: Dict[str, Any],
  year1_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> float:
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  if not state:
    return 0.0

  units = _required_units_year1(year1_json or {})
  revenue = max(0.0, _safe_float((summary or {}).get("revenue")))
  cogs = max(0.0, _safe_float((summary or {}).get("cogs")))
  payroll = max(0.0, _safe_float((summary or {}).get("payroll")))
  other_opex = max(0.0, _safe_float((summary or {}).get("other_opex")))
  ebitda = _safe_float((summary or {}).get("ebitda"))
  utilization = _normalize_ratio(
    _top_level_driver_value(year1_json or {}, "utilization_rate")
    or (ops_json or {}).get("utilization_rate")
  )

  gross_margin = ((revenue - cogs) / revenue) if revenue > 0 else None
  ebitda_margin = (ebitda / revenue) if revenue > 0 else None
  payroll_intensity = (payroll / revenue) if revenue > 0 else None
  opex_intensity = (other_opex / revenue) if revenue > 0 else None

  distance = 0.0
  unit_range = state.get("supportable_unit_range") if isinstance(state, dict) else {}
  revenue_range = state.get("supportable_revenue_range") if isinstance(state, dict) else {}
  utilization_range = state.get("utilization_range") if isinstance(state, dict) else {}
  gross_margin_band = state.get("gross_margin_band") if isinstance(state, dict) else {}
  ebitda_margin_band = state.get("ebitda_margin_band") if isinstance(state, dict) else {}
  payroll_band = state.get("payroll_intensity_band") if isinstance(state, dict) else {}
  opex_band = state.get("opex_intensity_band") if isinstance(state, dict) else {}

  distance += _range_distance(
    units,
    min_value=_band_min(unit_range),
    max_value=_band_max(unit_range),
    scale=max(1.0, _band_max(unit_range) or units or 1.0),
  )
  distance += _range_distance(
    revenue,
    min_value=_band_min(revenue_range),
    max_value=_band_max(revenue_range),
    scale=max(1.0, _band_max(revenue_range) or revenue or 1.0),
  )
  distance += _range_distance(
    utilization,
    min_value=_band_min(utilization_range),
    max_value=_band_max(utilization_range),
    scale=1.0,
  )
  distance += _range_distance(
    gross_margin,
    min_value=_band_min(gross_margin_band),
    max_value=_band_max(gross_margin_band),
    scale=1.0,
  )
  distance += _range_distance(
    ebitda_margin,
    min_value=_band_min(ebitda_margin_band),
    max_value=_band_max(ebitda_margin_band),
    scale=1.0,
  )
  distance += _range_distance(
    payroll_intensity,
    min_value=_band_min(payroll_band),
    max_value=_band_max(payroll_band),
    scale=1.0,
  )
  distance += _range_distance(
    opex_intensity,
    min_value=_band_min(opex_band),
    max_value=_band_max(opex_band),
    scale=1.0,
  )
  return round(distance, 6)


def _scenario_realism_violations(
  *,
  constraint_engine_state: Optional[Dict[str, Any]],
  summary: Dict[str, Any],
  year1_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Dict[str, List[str]]:
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  if not state:
    return {"all": [], "blocking": []}

  units = _required_units_year1(year1_json or {})
  revenue = max(0.0, _safe_float((summary or {}).get("revenue")))
  cogs = max(0.0, _safe_float((summary or {}).get("cogs")))
  payroll = max(0.0, _safe_float((summary or {}).get("payroll")))
  other_opex = max(0.0, _safe_float((summary or {}).get("other_opex")))
  ebitda = _safe_float((summary or {}).get("ebitda"))
  utilization = _normalize_ratio(
    _top_level_driver_value(year1_json or {}, "utilization_rate")
    or (ops_json or {}).get("utilization_rate")
  )
  gross_margin = ((revenue - cogs) / revenue) if revenue > 0 else None
  ebitda_margin = (ebitda / revenue) if revenue > 0 else None
  payroll_intensity = (payroll / revenue) if revenue > 0 else None
  opex_intensity = (other_opex / revenue) if revenue > 0 else None

  codes: List[str] = []

  def _maybe_add(code: str) -> None:
    if code not in codes:
      codes.append(code)

  unit_range = state.get("supportable_unit_range") if isinstance(state, dict) else {}
  revenue_range = state.get("supportable_revenue_range") if isinstance(state, dict) else {}
  util_range = state.get("utilization_range") if isinstance(state, dict) else {}
  gross_band = state.get("gross_margin_band") if isinstance(state, dict) else {}
  ebitda_band = state.get("ebitda_margin_band") if isinstance(state, dict) else {}
  payroll_band = state.get("payroll_intensity_band") if isinstance(state, dict) else {}
  opex_band = state.get("opex_intensity_band") if isinstance(state, dict) else {}

  if _range_distance(units, min_value=_band_min(unit_range), max_value=_band_max(unit_range), scale=max(1.0, units or 1.0)) > REALISM_DISTANCE_TOLERANCE:
    _maybe_add("capacity_unsupported")
  if _range_distance(revenue, min_value=_band_min(revenue_range), max_value=_band_max(revenue_range), scale=max(1.0, revenue or 1.0)) > REALISM_DISTANCE_TOLERANCE:
    _maybe_add("revenue_out_of_range")
  if _range_distance(gross_margin, min_value=_band_min(gross_band), max_value=_band_max(gross_band), scale=1.0) > REALISM_DISTANCE_TOLERANCE:
    if gross_margin is not None and _band_max(gross_band) is not None and gross_margin > _band_max(gross_band):
      _maybe_add("gross_margin_too_high")
    else:
      _maybe_add("gross_margin_too_low")
  if _range_distance(ebitda_margin, min_value=_band_min(ebitda_band), max_value=_band_max(ebitda_band), scale=1.0) > REALISM_DISTANCE_TOLERANCE:
    if ebitda_margin is not None and _band_max(ebitda_band) is not None and ebitda_margin > _band_max(ebitda_band):
      _maybe_add("ebitda_margin_too_high")
    else:
      _maybe_add("ebitda_margin_too_low")
  if _range_distance(payroll_intensity, min_value=_band_min(payroll_band), max_value=_band_max(payroll_band), scale=1.0) > REALISM_DISTANCE_TOLERANCE:
    if payroll_intensity is not None and _band_max(payroll_band) is not None and payroll_intensity > _band_max(payroll_band):
      _maybe_add("payroll_too_heavy")
    else:
      _maybe_add("payroll_too_light")
  if _range_distance(opex_intensity, min_value=_band_min(opex_band), max_value=_band_max(opex_band), scale=1.0) > REALISM_DISTANCE_TOLERANCE:
    if opex_intensity is not None and _band_max(opex_band) is not None and opex_intensity > _band_max(opex_band):
      _maybe_add("opex_too_heavy")
    else:
      _maybe_add("opex_too_light")
  if _range_distance(utilization, min_value=_band_min(util_range), max_value=_band_max(util_range), scale=1.0) > REALISM_DISTANCE_TOLERANCE:
    if utilization is not None and _band_max(util_range) is not None and utilization > _band_max(util_range):
      _maybe_add("utilization_too_high")
    else:
      _maybe_add("utilization_too_low")
  return {
    "all": codes,
    "blocking": [code for code in codes if code in BLOCKING_YEAR1_VIOLATIONS],
  }


def _loss_pct(summary: Dict[str, Any]) -> float:
  revenue = _safe_float((summary or {}).get("revenue"))
  net_income = _safe_float((summary or {}).get("net_income"))
  if revenue <= 0:
    return 0.0 if net_income >= 0 else 1.0
  return max(0.0, -net_income / revenue)


def _solver_required(summary: Dict[str, Any], constraint_engine_state: Optional[Dict[str, Any]] = None) -> bool:
  if isinstance(constraint_engine_state, dict):
    violations = [
      str(code or "").strip()
      for code in (constraint_engine_state.get("violations") or [])
      if str(code or "").strip() and str(code or "").strip() != "benchmark_low_confidence"
    ]
    if violations:
      return True
  revenue = _safe_float((summary or {}).get("revenue"))
  net_income = _safe_float((summary or {}).get("net_income"))
  ebitda = _safe_float((summary or {}).get("ebitda"))
  if revenue <= 0:
    return net_income < 0
  healthy_target = max(0.0, revenue * HEALTHY_EBITDA_MARGIN_RATIO)
  return ebitda < healthy_target or (_loss_pct(summary) > LOSS_THRESHOLD_RATIO)


def _blocking_constraint_violations(constraint_engine_state: Optional[Dict[str, Any]]) -> List[str]:
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  return [
    str(code or "").strip()
    for code in (state.get("violations") or [])
    if str(code or "").strip() in BLOCKING_YEAR1_VIOLATIONS
  ]


def _ebitda_gap(summary: Dict[str, Any]) -> float:
  return max(0.0, -_safe_float((summary or {}).get("ebitda")))


def _is_break_even_ebitda(summary: Dict[str, Any]) -> bool:
  return _safe_float((summary or {}).get("ebitda")) >= 0.0


def _top_level_driver_value(payload: Dict[str, Any], key: str) -> Optional[float]:
  value = payload.get(key)
  if value is not None and value != "":
    try:
      return float(value)
    except Exception:
      pass
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
      if product.get(key) is None or product.get(key) == "":
        continue
      try:
        return float(product.get(key))
      except Exception:
        continue
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
        avg_units = _safe_float(product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1"))
        periods = _safe_float(product.get("operating_periods_per_year") or product.get("operating_weeks_per_year"))
        total += avg_units * periods
  if total > 0:
    return total
  avg_units = _safe_float(year1.get("avg_units_per_period_year1") or year1.get("avg_units_per_week_year1"))
  periods = _safe_float(year1.get("operating_periods_per_year") or year1.get("operating_weeks_per_year"))
  return avg_units * periods


def _derived_year1_payroll_from_people(people_json: Dict[str, Any]) -> float:
  total = 0.0
  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    total += max(0.0, _safe_float(person.get("annual_wage")))
  for role in (people_json or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    annual_wage = max(0.0, _safe_float(role.get("annual_wage")))
    months_until_hire = max(0, min(12, _safe_int(role.get("months_until_hire")) or 0))
    active_months = max(0, 12 - months_until_hire)
    total += annual_wage * (active_months / 12.0)
  return round(total, 2)


def _iter_year1_products(financials_year1_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  products_out: List[Dict[str, Any]] = []
  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  lobs = year1.get("lobs")
  if not isinstance(lobs, list):
    return products_out
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
      product_name = str(product.get("product_name") or "").strip() or str(product.get("unit_name") or "").strip() or "Product"
      products_out.append(
        {
          "lob_name": lob_name,
          "product_name": product_name,
          "product_key": f"{lob_name.strip().lower()}::{product_name.strip().lower()}",
          "product": product,
        }
      )
  return products_out


def _product_driver_is_solver_usable(product_basis: Dict[str, Any]) -> bool:
  if not isinstance(product_basis, dict):
    return False
  unit_price = max(0.0, _safe_float(product_basis.get("unit_price")))
  periods = max(0.0, _safe_float(product_basis.get("operating_periods_per_year")))
  capacity = max(0.0, _safe_float(product_basis.get("units_per_period_capacity")))
  avg_units = max(0.0, _safe_float(product_basis.get("avg_units_per_period_year1")))
  util = _normalize_ratio(product_basis.get("utilization_rate"))
  if unit_price <= 0 or periods <= 0:
    return False
  if capacity <= 0 and avg_units <= 0:
    return False
  if capacity > 0 and util is None and avg_units <= 0:
    return False
  return True


def _resolve_solver_mode(
  *,
  financials_year1_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]]]:
  product_basis = _build_product_driver_basis(
    financials_year1_json=financials_year1_json or {},
    ops_json=ops_json or {},
  )
  if not product_basis:
    return "parent_fallback", []
  if all(_product_driver_is_solver_usable(item) for item in product_basis):
    return "child_first", product_basis
  return "parent_fallback", []


def _build_product_driver_basis(
  *,
  financials_year1_json: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
  basis: List[Dict[str, Any]] = []
  for item in _iter_year1_products(financials_year1_json or {}):
    product = item.get("product") if isinstance(item, dict) else {}
    product = product if isinstance(product, dict) else {}
    unit_price = max(0.0, _safe_float(product.get("unit_price") or (ops_json or {}).get("unit_price")))
    periods = max(
      0.0,
      _safe_float(product.get("operating_periods_per_year") or product.get("operating_weeks_per_year"))
      or _safe_float((financials_year1_json or {}).get("operating_periods_per_year") or (financials_year1_json or {}).get("operating_weeks_per_year"))
      or 0.0,
    )
    units_capacity_per_period = max(
      0.0,
      _safe_float(product.get("units_per_period_capacity") or product.get("units_per_week_capacity"))
      or _safe_float((financials_year1_json or {}).get("units_per_period_capacity") or (financials_year1_json or {}).get("units_per_week_capacity"))
      or 0.0,
    )
    avg_units_per_period = max(
      0.0,
      _safe_float(product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1"))
      or 0.0,
    )
    utilization_rate = _normalize_ratio(product.get("utilization_rate"))
    if avg_units_per_period <= 0 and utilization_rate is not None and units_capacity_per_period > 0:
      avg_units_per_period = units_capacity_per_period * utilization_rate
    if utilization_rate is None and units_capacity_per_period > 0 and avg_units_per_period > 0:
      utilization_rate = max(0.0, min(1.0, avg_units_per_period / max(units_capacity_per_period, 1e-9)))
    annual_units = avg_units_per_period * periods
    annual_capacity_units = units_capacity_per_period * periods
    annual_revenue = annual_units * unit_price
    basis.append(
      {
        "lob_name": item.get("lob_name"),
        "product_name": item.get("product_name"),
        "product_key": item.get("product_key"),
        "unit_price": unit_price,
        "operating_periods_per_year": periods,
        "units_per_period_capacity": units_capacity_per_period,
        "avg_units_per_period_year1": avg_units_per_period,
        "utilization_rate": utilization_rate,
        "annual_units": annual_units,
        "annual_capacity_units": annual_capacity_units,
        "annual_revenue": annual_revenue,
      }
    )
  return basis


def _weighted_product_price(product_basis: Sequence[Dict[str, Any]]) -> float:
  total_units = sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_basis if isinstance(item, dict))
  if total_units <= 0:
    return 0.0
  total_revenue = sum(max(0.0, _safe_float(item.get("annual_revenue"))) for item in product_basis if isinstance(item, dict))
  return total_revenue / max(total_units, 1e-9)


def _weighted_product_utilization(product_basis: Sequence[Dict[str, Any]]) -> Optional[float]:
  total_capacity = sum(max(0.0, _safe_float(item.get("annual_capacity_units"))) for item in product_basis if isinstance(item, dict))
  if total_capacity <= 0:
    return None
  total_units = sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_basis if isinstance(item, dict))
  return max(0.0, min(1.0, total_units / max(total_capacity, 1e-9)))


def _recompute_payroll_fields(
  *,
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  roles_basis: List[Dict[str, Any]] = []
  total = 0.0

  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    annual_wage = max(0.0, _safe_float(person.get("annual_wage")))
    total += annual_wage
    roles_basis.append(
      {
        "source": "person",
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_counted_year1": 12,
        "year1_payroll_amount": annual_wage,
      }
    )

  for role in (people_json or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    annual_wage = max(0.0, _safe_float(role.get("annual_wage")))
    raw_months = _safe_int(role.get("months_until_hire"))
    months_until_hire = max(0, raw_months if raw_months is not None else 0)
    months_counted = max(0, 12 - min(12, months_until_hire))
    year1_amount = annual_wage * (months_counted / 12.0)
    total += year1_amount
    roles_basis.append(
      {
        "source": "inferred_role",
        "role_title": str(role.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "months_until_hire": months_until_hire,
        "months_counted_year1": months_counted,
        "year1_payroll_amount": year1_amount,
      }
    )

  next_financials["baseline_payroll_year1"] = float(total)
  next_financials["payroll_adjustment"] = 0.0
  next_financials["payroll_total_year1"] = float(total)
  next_financials["payroll_basis_people_roles"] = roles_basis
  next_financials["current_payroll"] = float(total)
  return next_financials


def _apply_marketing_total(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  total: float,
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  revenue = _safe_float((financials_year1_json or {}).get("company_revenue_total_year1"))
  baseline_amount = _safe_float(next_financials.get("baseline_marketing"))
  baseline_percent = _safe_float(next_financials.get("baseline_marketing_percent"))
  if baseline_amount <= 0 and baseline_percent > 0 and revenue > 0:
    baseline_amount = revenue * baseline_percent

  total = max(0.0, float(total))
  next_financials["marketing_total_year1"] = total
  next_financials["marketing_percent_of_revenue"] = float(total / revenue) if revenue > 0 else 0.0
  if baseline_amount > 0:
    next_financials["baseline_marketing"] = baseline_amount
    next_financials["marketing_adjustment"] = total - baseline_amount
  if baseline_percent > 0:
    next_financials["baseline_marketing_percent"] = baseline_percent
  return next_financials


def _apply_marketing_model_patch(
  *,
  marketing_model_json: Dict[str, Any],
  patch: Dict[str, Any],
) -> Dict[str, Any]:
  next_model = dict(marketing_model_json or {})
  for key, value in (patch or {}).items():
    next_model[str(key)] = value
  return next_model


def _marketing_units_per_dollar(marketing_model_json: Optional[Dict[str, Any]]) -> float:
  model = marketing_model_json if isinstance(marketing_model_json, dict) else {}
  baseline_marketing = max(
    0.0,
    _safe_float(model.get("marketing_total_year1"))
    or _safe_float(model.get("baseline_marketing")),
  )
  expected_units = max(0.0, _safe_float(model.get("expected_units_year1")))
  if baseline_marketing <= 0 or expected_units <= 0:
    return 0.0
  return expected_units / max(baseline_marketing, 1e-9)


def _sync_marketing_derived_fields(
  *,
  marketing_model_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  units_per_dollar: Optional[float] = None,
  min_total: Optional[float] = None,
  max_total: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
  next_model = dict(marketing_model_json or {})
  next_financials = dict(financials_json or {})
  units_per_dollar = max(0.0, _safe_float(units_per_dollar))
  if units_per_dollar <= 0:
    units_per_dollar = _marketing_units_per_dollar(next_model)
  expected_units = max(0.0, _safe_float(next_model.get("expected_units_year1")))
  if units_per_dollar > 0 and expected_units >= 0:
    marketing_total = round(expected_units / units_per_dollar, 2)
    if max_total is not None:
      marketing_total = min(marketing_total, max(0.0, _safe_float(max_total)))
    if min_total is not None:
      marketing_total = max(marketing_total, max(0.0, _safe_float(min_total)))
    next_model["marketing_total_year1"] = marketing_total
    next_financials = _apply_marketing_total(
      financials_json=next_financials,
      financials_year1_json=financials_year1_json,
      total=marketing_total,
    )
  reachable_market = max(0.0, _safe_float(next_model.get("reachable_market")))
  if reachable_market > 0 and expected_units >= 0:
    next_model["capture_rate_year1"] = round(expected_units / max(reachable_market, 1e-9), 6)
  baseline_expected_units = max(0.0, _safe_float(next_model.get("required_units_year1")))
  baseline_expected_customers = max(0.0, _safe_float(next_model.get("expected_customers_or_clients_year1")))
  if baseline_expected_units > 0 and baseline_expected_customers > 0 and expected_units >= 0:
    scaled_customers = baseline_expected_customers * (expected_units / max(baseline_expected_units, 1e-9))
    if reachable_market > 0:
      scaled_customers = min(reachable_market, scaled_customers)
    next_model["expected_customers_or_clients_year1"] = round(scaled_customers, 2)
  return next_model, next_financials


def _apply_other_opex_total(
  *,
  financials_json: Dict[str, Any],
  total: float,
) -> Dict[str, Any]:
  next_financials = dict(financials_json or {})
  next_financials["other_operating_expense"] = max(0.0, float(total))
  return next_financials


def _render_timing_text(months: int) -> str:
  months = max(1, int(months))
  if months == 1:
    return "within 1 month"
  return f"within {months} months"


def _attach_milestone_updates_for_delay(
  *,
  ops_json: Dict[str, Any],
  minimum_months: int,
) -> List[Dict[str, Any]]:
  updates: List[Dict[str, Any]] = []
  milestones = (ops_json or {}).get("milestones") or []
  if not isinstance(milestones, list):
    return updates
  for index, milestone in enumerate(milestones):
    if not isinstance(milestone, dict):
      continue
    timing_months = _safe_int(milestone.get("timing_months_max"))
    if timing_months is None or timing_months >= minimum_months:
      continue
    updates.append(
      {
        "index": index,
        "timing_months_max": int(minimum_months),
        "timing": _render_timing_text(int(minimum_months)),
      }
    )
  return updates


def _candidate_disruption_score(exact_patches: Dict[str, Any]) -> float:
  score = 0.0
  lever_count = 0

  year1_patch = exact_patches.get("financials_year1_patch")
  if isinstance(year1_patch, dict):
    product_overrides = year1_patch.get("product_overrides")
    if isinstance(product_overrides, dict) and product_overrides:
      saw_price = False
      saw_util = False
      for override in product_overrides.values():
        if not isinstance(override, dict):
          continue
        if override.get("unit_price") is not None:
          saw_price = True
        if override.get("utilization_rate") is not None or override.get("avg_units_per_period_year1") is not None:
          saw_util = True
      if saw_util:
        lever_count += 1
        score += 0.75
      if saw_price:
        lever_count += 1
        score += 1.0
    if year1_patch.get("utilization_rate") is not None:
      lever_count += 1
      score += abs(_safe_float(year1_patch.get("utilization_rate")))
    if year1_patch.get("unit_price") is not None:
      lever_count += 1
      score += 1.0

  financials_patch = exact_patches.get("financials_patch")
  if isinstance(financials_patch, dict):
    if financials_patch.get("marketing_total_year1") is not None:
      lever_count += 1
      score += 0.75
    if financials_patch.get("other_operating_expense") is not None:
      lever_count += 1
      score += 0.5
    if financials_patch.get("cogs_total_year1") is not None:
      lever_count += 1
      score += 0.6
  marketing_model_patch = exact_patches.get("marketing_model_patch")
  if isinstance(marketing_model_patch, dict) and marketing_model_patch.get("expected_units_year1") is not None:
    lever_count += 1
    score += 0.75

  role_updates = exact_patches.get("people_role_updates")
  if isinstance(role_updates, list) and role_updates:
    lever_count += len(role_updates)
    for item in role_updates:
      if not isinstance(item, dict):
        continue
      score += max(0.0, (_safe_int(item.get("months_until_hire")) or 0) / 12.0)
      if item.get("annual_wage") is not None:
        score += 1.5

  milestone_updates = exact_patches.get("milestone_updates")
  if isinstance(milestone_updates, list) and milestone_updates:
    lever_count += 1
    score += 0.25

  return score + (0.35 * lever_count)


def _apply_exact_patches(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  exact_patches: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
  next_ops = _clone(ops_json or {})
  next_people = _clone(people_json or {})
  next_financials = _clone(financials_json or {})
  next_year1 = _clone(financials_year1_json or {})
  next_marketing_model = _clone(marketing_model_json or {})

  year1_patch = exact_patches.get("financials_year1_patch")
  if isinstance(year1_patch, dict) and year1_patch:
    next_year1 = apply_revenue_driver_patch(next_year1, year1_patch)

  role_updates = exact_patches.get("people_role_updates")
  if isinstance(role_updates, list) and isinstance(next_people.get("inferred_roles"), list):
    roles = next_people.get("inferred_roles") or []
    for update in role_updates:
      if not isinstance(update, dict):
        continue
      role_title = str(update.get("role_title") or "").strip().lower()
      months = _safe_int(update.get("months_until_hire"))
      annual_wage = _safe_float(update.get("annual_wage")) if update.get("annual_wage") is not None else None
      if not role_title or months is None:
        continue
      for role in roles:
        if not isinstance(role, dict):
          continue
        if str(role.get("role_title") or "").strip().lower() != role_title:
          continue
        role["months_until_hire"] = int(max(0, months))
        if annual_wage is not None and annual_wage > 0:
          role["annual_wage"] = float(annual_wage)
        break

  financials_patch = exact_patches.get("financials_patch")
  if isinstance(financials_patch, dict):
    for key, value in financials_patch.items():
      next_financials[str(key)] = value
  solver_meta = exact_patches.get("solver_meta") if isinstance(exact_patches, dict) else {}
  solver_meta = solver_meta if isinstance(solver_meta, dict) else {}

  milestone_updates = exact_patches.get("milestone_updates")
  milestones = next_ops.get("milestones")
  if isinstance(milestone_updates, list) and isinstance(milestones, list):
    for update in milestone_updates:
      if not isinstance(update, dict):
        continue
      index = _safe_int(update.get("index"))
      if index is None or index < 0 or index >= len(milestones):
        continue
      milestone = milestones[index]
      if not isinstance(milestone, dict):
        continue
      if update.get("timing_months_max") is not None:
        milestone["timing_months_max"] = int(max(1, _safe_int(update.get("timing_months_max")) or 1))
      if str(update.get("timing") or "").strip():
        milestone["timing"] = str(update.get("timing") or "").strip()

  next_financials = _recompute_payroll_fields(
    people_json=next_people,
    financials_json=next_financials,
  )

  if isinstance(financials_patch, dict) and "marketing_total_year1" in financials_patch:
    next_financials = _apply_marketing_total(
      financials_json=next_financials,
      financials_year1_json=next_year1,
      total=_safe_float(financials_patch.get("marketing_total_year1")),
    )
  elif next_financials.get("marketing_total_year1") is not None:
    next_financials = _apply_marketing_total(
      financials_json=next_financials,
      financials_year1_json=next_year1,
      total=_safe_float(next_financials.get("marketing_total_year1")),
    )

  if isinstance(financials_patch, dict) and "other_operating_expense" in financials_patch:
    next_financials = _apply_other_opex_total(
      financials_json=next_financials,
      total=_safe_float(financials_patch.get("other_operating_expense")),
    )

  updated_revenue_total = max(0.0, _safe_float((next_year1 or {}).get("company_revenue_total_year1")))
  cogs_ratio_target = _safe_float((solver_meta or {}).get("cogs_ratio_target"))
  if updated_revenue_total > 0 and cogs_ratio_target > 0:
    next_financials["cogs_total_year1"] = round(updated_revenue_total * cogs_ratio_target, 2)
  opex_total_ratio_target = _safe_float((solver_meta or {}).get("opex_total_ratio_target"))
  if updated_revenue_total > 0 and opex_total_ratio_target > 0:
    rent_annualized = max(0.0, _safe_float(next_financials.get("monthly_rent_expense")) * 12.0)
    other_opex_total = max(0.0, (updated_revenue_total * opex_total_ratio_target) - rent_annualized)
    next_financials = _apply_other_opex_total(
      financials_json=next_financials,
      total=other_opex_total,
    )

  marketing_model_patch = exact_patches.get("marketing_model_patch")
  if isinstance(marketing_model_patch, dict) and marketing_model_patch:
    baseline_units_per_dollar = _marketing_units_per_dollar(next_marketing_model)
    solver_meta = exact_patches.get("solver_meta") if isinstance(exact_patches, dict) else {}
    solver_meta = solver_meta if isinstance(solver_meta, dict) else {}
    next_marketing_model = _apply_marketing_model_patch(
      marketing_model_json=next_marketing_model,
      patch=marketing_model_patch,
    )
    next_marketing_model, next_financials = _sync_marketing_derived_fields(
      marketing_model_json=next_marketing_model,
      financials_json=next_financials,
      financials_year1_json=next_year1,
      units_per_dollar=baseline_units_per_dollar,
      min_total=_safe_float(solver_meta.get("marketing_min_total")) if solver_meta.get("marketing_min_total") is not None else None,
      max_total=_safe_float(solver_meta.get("marketing_max_total")) if solver_meta.get("marketing_max_total") is not None else None,
    )

  return next_ops, next_people, next_financials, next_year1, next_marketing_model


def _scenario_violations(
  *,
  baseline_state: Dict[str, Any],
  next_ops: Dict[str, Any],
  next_financials: Dict[str, Any],
  next_year1: Dict[str, Any],
  exact_patches: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
) -> List[str]:
  del baseline_state, next_ops, next_financials, exact_patches, marketing_model_json
  next_required_units = _required_units_year1(next_year1 or {})
  if next_required_units < 0:
    return ["required units must be non-negative"]
  return []


def _scenario_signature(exact_patches: Dict[str, Any]) -> str:
  return json.dumps(exact_patches or {}, sort_keys=True, ensure_ascii=False)


def _build_lever_summary(
  *,
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
  family_alias = {
    "price_up": "price",
    "price_down": "price",
    "util_up": "utilization",
    "util_down": "utilization",
    "marketing_up": "marketing",
    "marketing_down": "marketing",
    "other_opex_down": "other_opex",
    "other_opex_up": "other_opex",
    "cogs_down": "cogs",
    "cogs_up": "cogs",
    "hire_delay": "hire_delay",
    "hire_advance": "hire_delay",
    "payroll_down": "payroll",
    "payroll_up": "payroll",
    "payroll_shortfall": "payroll",
    "payroll_excess": "payroll",
    "structural_payroll_shortfall": "payroll",
  }
  raw_moves: Dict[str, float] = {}
  for raw_name, raw_value in family_raw_components.items():
    family_name = family_alias.get(str(raw_name), str(raw_name))
    value = max(0.0, _safe_float(raw_value))
    raw_moves[family_name] = max(raw_moves.get(family_name, 0.0), value)
  year1_patch = exact_patches.get("financials_year1_patch") if isinstance(exact_patches, dict) else {}
  year1_patch = year1_patch if isinstance(year1_patch, dict) else {}
  product_overrides = year1_patch.get("product_overrides") if isinstance(year1_patch, dict) else {}
  product_overrides = product_overrides if isinstance(product_overrides, dict) else {}
  financials_patch = exact_patches.get("financials_patch") if isinstance(exact_patches, dict) else {}
  financials_patch = financials_patch if isinstance(financials_patch, dict) else {}
  if financials_patch.get("marketing_total_year1") is not None:
    raw_moves["marketing"] = max(raw_moves.get("marketing", 0.0), 0.1)
  if financials_patch.get("other_operating_expense") is not None:
    raw_moves["other_opex"] = max(raw_moves.get("other_opex", 0.0), 0.1)
  if financials_patch.get("cogs_total_year1") is not None:
    raw_moves["cogs"] = max(raw_moves.get("cogs", 0.0), 0.1)
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
    raw_moves["marketing"] = max(raw_moves.get("marketing", 0.0), 0.1)
  if isinstance(exact_patches.get("people_role_updates"), list) and exact_patches["people_role_updates"]:
    role_updates = exact_patches["people_role_updates"]
    if any(isinstance(item, dict) and item.get("months_until_hire") is not None for item in role_updates):
      raw_moves["hire_delay"] = max(raw_moves.get("hire_delay", 0.0), 0.1)
    if any(isinstance(item, dict) and item.get("annual_wage") is not None for item in role_updates):
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
  coordination_score = (
    float(len(meaningful_families))
    + (0.35 * max(0, changed_products - 1))
    + (0.2 * max(0, len(raw_moves) - len(meaningful_families)))
  )
  return {
    "meaningful_families": meaningful_families,
    "meaningful_lever_count": len(meaningful_families),
    "raw_family_moves": {key: round(value, 6) for key, value in raw_moves.items()},
    "changed_products": changed_products,
    "moved_product_keys": moved_products,
    "coordination_score": round(coordination_score, 4),
  }


def _nontrivial_repair_required(
  *,
  baseline_realism_distance: float,
  target_ebitda_min: Optional[float],
  target_ebitda_max: Optional[float],
  baseline_blocking_count: int,
) -> bool:
  return (
    baseline_blocking_count >= 1
    or baseline_realism_distance >= 0.015
    or target_ebitda_min is not None
    or target_ebitda_max is not None
  )


def _build_candidate(
  *,
  scenario_id: str,
  baseline_summary: Dict[str, Any],
  baseline_state: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  label: str,
  rationale: str,
  lever_families: Sequence[str],
  exact_patches: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]] = None,
  baseline_realism_distance: Optional[float] = None,
  target_ebitda_min: Optional[float] = None,
  target_ebitda_max: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
  next_ops, next_people, next_financials, next_year1, next_marketing_model = _apply_exact_patches(
    ops_json=baseline_state.get("ops_json") or {},
    people_json=baseline_state.get("people_json") or {},
    financials_json=baseline_state.get("financials_json") or {},
    financials_year1_json=baseline_state.get("financials_year1_json") or {},
    marketing_model_json=baseline_state.get("marketing_model_json") or marketing_model_json or {},
    exact_patches=exact_patches,
  )
  summary = build_consistency_financial_summary(
    financials_json=next_financials,
    financials_year1_json=next_year1,
  )
  violations = _scenario_violations(
    baseline_state=baseline_state,
    next_ops=next_ops,
    next_financials=next_financials,
    next_year1=next_year1,
    exact_patches=exact_patches,
    marketing_model_json=next_marketing_model,
  )
  if violations:
    return None
  baseline_net_income = _safe_float(baseline_summary.get("net_income"))
  next_net_income = _safe_float(summary.get("net_income"))
  improvement = next_net_income - baseline_net_income
  baseline_distance = (
    max(0.0, _safe_float(baseline_realism_distance))
    if baseline_realism_distance is not None
    else 0.0
  )
  next_distance = _constraint_engine_realism_distance(
    constraint_engine_state=constraint_engine_state,
    summary=summary,
    year1_json=next_year1,
    ops_json=next_ops,
  )
  remaining_violations = _scenario_realism_violations(
    constraint_engine_state=constraint_engine_state,
    summary=summary,
    year1_json=next_year1,
    ops_json=next_ops,
  )
  remaining_blocking = list(remaining_violations.get("blocking") or [])
  all_remaining = list(remaining_violations.get("all") or [])
  baseline_blocking_count = len(_blocking_constraint_violations(constraint_engine_state))
  target_distance = _ebitda_target_distance(
    summary,
    target_ebitda_min=target_ebitda_min,
    target_ebitda_max=target_ebitda_max,
  )
  baseline_target_distance = _ebitda_target_distance(
    baseline_summary,
    target_ebitda_min=target_ebitda_min,
    target_ebitda_max=target_ebitda_max,
  )
  if constraint_engine_state:
    if target_ebitda_min is not None or target_ebitda_max is not None:
      if target_distance > (baseline_target_distance - REALISM_DISTANCE_TOLERANCE):
        return None
      if next_distance > (baseline_distance + SOLVER_DISTANCE_REGRESSION_TOLERANCE):
        return None
      if len(remaining_blocking) > max(UNRESOLVED_BLOCKING_SCENARIO_LIMIT, baseline_blocking_count - 1):
        return None
    elif next_distance > (baseline_distance - REALISM_DISTANCE_TOLERANCE):
      return None
  elif improvement <= 0:
    return None

  disruption_score = _candidate_disruption_score(exact_patches)
  is_break_even = _is_break_even_ebitda(summary)
  ebitda_gap = _ebitda_gap(summary)
  lever_summary = _build_lever_summary(exact_patches=exact_patches)

  return {
    "scenario_id": scenario_id,
    "label": label,
    "rationale": rationale,
    "lever_families": list(lever_families),
    "exact_patches": exact_patches,
    "summary": summary,
    "ebitda": _safe_float(summary.get("ebitda")),
    "net_income": next_net_income,
    "loss_pct": _loss_pct(summary),
    "ebitda_gap": ebitda_gap,
    "break_even_ebitda": is_break_even,
    "disruption_score": disruption_score,
    "improvement_amount": improvement,
    "realism_distance": next_distance,
    "target_distance": target_distance,
    "remaining_violations": all_remaining,
    "remaining_blocking_violations": remaining_blocking,
    "remaining_blocking_count": len(remaining_blocking),
    "remaining_violation_count": len(all_remaining),
    "signature": _scenario_signature(exact_patches),
    "lever_summary": lever_summary,
    "meaningful_families": list(lever_summary.get("meaningful_families") or []),
    "meaningful_lever_count": int(max(0, _safe_int(lever_summary.get("meaningful_lever_count")) or 0)),
    "coordination_score": _safe_float(lever_summary.get("coordination_score")),
    "editable_role_titles": [
      str(update.get("role_title") or "").strip()
      for update in (exact_patches.get("people_role_updates") or [])
      if isinstance(update, dict) and str(update.get("role_title") or "").strip()
    ],
    "editable_milestone_indexes": [
      int(_safe_int(update.get("index")) or 0)
      for update in (exact_patches.get("milestone_updates") or [])
      if isinstance(update, dict) and _safe_int(update.get("index")) is not None
    ],
  }


def _merge_exact_patches(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
  merged: Dict[str, Any] = {}
  for key in ("financials_year1_patch", "financials_patch"):
    base = first.get(key) if isinstance(first, dict) else None
    extra = second.get(key) if isinstance(second, dict) else None
    combined: Dict[str, Any] = {}
    if isinstance(base, dict):
      combined.update(base)
    if isinstance(extra, dict):
      combined.update(extra)
    if combined:
      merged[key] = combined

  role_updates: Dict[str, Dict[str, Any]] = {}
  for source in (first.get("people_role_updates"), second.get("people_role_updates")):
    if not isinstance(source, list):
      continue
    for item in source:
      if not isinstance(item, dict):
        continue
      role_title = str(item.get("role_title") or "").strip().lower()
      if not role_title:
        continue
      role_updates[role_title] = dict(item)
  if role_updates:
    merged["people_role_updates"] = list(role_updates.values())

  milestone_updates: Dict[int, Dict[str, Any]] = {}
  for source in (first.get("milestone_updates"), second.get("milestone_updates")):
    if not isinstance(source, list):
      continue
    for item in source:
      if not isinstance(item, dict):
        continue
      index = _safe_int(item.get("index"))
      if index is None:
        continue
      current = milestone_updates.get(index, {})
      current.update(item)
      milestone_updates[index] = current
  if milestone_updates:
    merged["milestone_updates"] = [milestone_updates[idx] for idx in sorted(milestone_updates)]

  return merged


def _select_top_candidates(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  all_candidates = _dedupe_by_economic_outcome(
    [candidate for candidate in candidates if isinstance(candidate, dict)]
  )
  if not all_candidates:
    return []

  pulp = _require_pulp()
  break_even_target_exists = any(bool(candidate.get("break_even_ebitda")) for candidate in all_candidates)
  selected: List[Dict[str, Any]] = []
  excluded_signatures = set()

  while len(selected) < MAX_SCENARIOS:
    pool = [
      candidate
      for candidate in all_candidates
      if _economic_signature(candidate) not in excluded_signatures
    ]
    if not pool:
      break

    problem = pulp.LpProblem("consistency_solver_select", pulp.LpMaximize)
    vars_by_idx = {
      idx: pulp.LpVariable(f"pick_{idx}", lowBound=0, upBound=1, cat="Binary")
      for idx in range(len(pool))
    }
    problem += pulp.lpSum(vars_by_idx.values()) == 1
    problem += pulp.lpSum(
      _candidate_objective(candidate, break_even_target_exists=break_even_target_exists) * vars_by_idx[idx]
      for idx, candidate in enumerate(pool)
    )
    problem.solve(pulp.PULP_CBC_CMD(msg=False))
    chosen_idx = None
    for idx, variable in vars_by_idx.items():
      try:
        value = float(variable.value())
      except Exception:
        value = 0.0
      if value >= 0.5:
        chosen_idx = idx
        break
    if chosen_idx is None:
      break
    chosen = pool[chosen_idx]
    selected.append(chosen)
    excluded_signatures.add(_economic_signature(chosen))

  return selected


def _primary_family(candidate: Dict[str, Any]) -> str:
  families = candidate.get("lever_families") if isinstance(candidate, dict) else None
  if not isinstance(families, list) or not families:
    return ""
  return str(families[0] or "").strip()


def _scenario_archetype_meta(profile_id: str) -> Dict[str, str]:
  profile_key = str(profile_id or "").strip()
  payload = SCENARIO_ARCHETYPE_META.get(profile_key) or {}
  return {
    "archetype": str(payload.get("archetype") or "operations"),
    "display": str(payload.get("display") or "Operational balance"),
    "tradeoff": str(payload.get("tradeoff") or "rebalances the Year-1 plan within the realism envelope"),
  }


def _dominant_tradeoff(lever_families: Sequence[str], archetype: str) -> str:
  families = [str(item or "").strip() for item in lever_families if str(item or "").strip()]
  family_set = set(families)
  if archetype == "growth":
    if "marketing" in family_set or "utilization" in family_set:
      return "keeps more of the revenue ambition while adding enough support to stay credible"
    return "leans toward preserving growth with less disruption to the revenue plan"
  if archetype == "efficiency":
    if "other_opex" in family_set or "cogs" in family_set or "payroll" in family_set:
      return "trades some upside for cleaner margin structure and tighter cost control"
    return "leans into efficiency over reach"
  if "hire_delay" in family_set or "payroll" in family_set or "utilization" in family_set:
    return "rebalances staffing, workload, and timing to make operations believable"
  return "balances workload and support structure without overusing one lever family"


def _economic_signature(candidate: Dict[str, Any]) -> str:
  return json.dumps(
    {
      "ebitda": round(_safe_float(candidate.get("ebitda")), 2),
      "net_income": round(_safe_float(candidate.get("net_income")), 2),
      "loss_pct": round(_safe_float(candidate.get("loss_pct")), 6),
      "break_even_ebitda": bool(candidate.get("break_even_ebitda")),
    },
    sort_keys=True,
    ensure_ascii=False,
  )


def _dedupe_by_economic_outcome(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  deduped: List[Dict[str, Any]] = []
  seen = set()
  for candidate in candidates:
    if not isinstance(candidate, dict):
      continue
    signature = _economic_signature(candidate)
    if not signature or signature in seen:
      continue
    seen.add(signature)
    deduped.append(candidate)
  return deduped


def _role_update_map(candidate: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  updates = (candidate.get("exact_patches") or {}).get("people_role_updates") if isinstance(candidate, dict) else None
  updates = updates if isinstance(updates, list) else []
  mapped: Dict[str, Dict[str, Any]] = {}
  for item in updates:
    if not isinstance(item, dict):
      continue
    role_title = str(item.get("role_title") or "").strip().lower()
    if role_title:
      mapped[role_title] = item
  return mapped


def _materially_distinct_candidate(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
  left_archetype = str(left.get("archetype") or "").strip()
  right_archetype = str(right.get("archetype") or "").strip()
  if left_archetype and right_archetype and left_archetype != right_archetype:
    return True
  left_tradeoff = str(left.get("dominant_tradeoff") or "").strip()
  right_tradeoff = str(right.get("dominant_tradeoff") or "").strip()
  if left_tradeoff and right_tradeoff and left_tradeoff != right_tradeoff:
    return True
  left_families = tuple(str(item or "").strip() for item in (left.get("lever_families") or []) if str(item or "").strip())
  right_families = tuple(str(item or "").strip() for item in (right.get("lever_families") or []) if str(item or "").strip())
  if left_families and right_families and left_families != right_families:
    return True
  left_patch = left.get("exact_patches") if isinstance(left, dict) else {}
  right_patch = right.get("exact_patches") if isinstance(right, dict) else {}
  left_year1 = left_patch.get("financials_year1_patch") if isinstance(left_patch, dict) else {}
  right_year1 = right_patch.get("financials_year1_patch") if isinstance(right_patch, dict) else {}
  left_marketing = left_patch.get("marketing_model_patch") if isinstance(left_patch, dict) else {}
  right_marketing = right_patch.get("marketing_model_patch") if isinstance(right_patch, dict) else {}
  left_product_overrides = (left_year1 or {}).get("product_overrides") if isinstance(left_year1, dict) else {}
  right_product_overrides = (right_year1 or {}).get("product_overrides") if isinstance(right_year1, dict) else {}

  if isinstance(left_product_overrides, dict) or isinstance(right_product_overrides, dict):
    left_product_overrides = left_product_overrides if isinstance(left_product_overrides, dict) else {}
    right_product_overrides = right_product_overrides if isinstance(right_product_overrides, dict) else {}
    if set(left_product_overrides.keys()) != set(right_product_overrides.keys()):
      return True
    for product_name in left_product_overrides.keys():
      left_override = left_product_overrides.get(product_name) or {}
      right_override = right_product_overrides.get(product_name) or {}
      left_price = _safe_float((left_override or {}).get("unit_price"))
      right_price = _safe_float((right_override or {}).get("unit_price"))
      if max(left_price, right_price) > 0 and abs(left_price - right_price) >= max(0.25, 0.01 * max(left_price, right_price)):
        return True
      left_avg_units = _safe_float((left_override or {}).get("avg_units_per_period_year1"))
      right_avg_units = _safe_float((right_override or {}).get("avg_units_per_period_year1"))
      if max(left_avg_units, right_avg_units) > 0 and abs(left_avg_units - right_avg_units) >= max(1.0, 0.02 * max(left_avg_units, right_avg_units)):
        return True
      left_prod_util = _normalize_ratio((left_override or {}).get("utilization_rate"))
      right_prod_util = _normalize_ratio((right_override or {}).get("utilization_rate"))
      if left_prod_util is not None and right_prod_util is not None and abs(left_prod_util - right_prod_util) >= 0.01:
        return True

  left_util = _normalize_ratio((left_year1 or {}).get("utilization_rate"))
  right_util = _normalize_ratio((right_year1 or {}).get("utilization_rate"))
  if left_util is not None and right_util is not None and abs(left_util - right_util) >= 0.01:
    return True

  left_units = _safe_float((left_marketing or {}).get("expected_units_year1"))
  right_units = _safe_float((right_marketing or {}).get("expected_units_year1"))
  if max(left_units, right_units) > 0 and abs(left_units - right_units) >= max(1.0, 0.02 * max(left_units, right_units)):
    return True

  left_roles = _role_update_map(left)
  right_roles = _role_update_map(right)
  if set(left_roles.keys()) != set(right_roles.keys()):
    return True
  for role_title in left_roles.keys():
    left_item = left_roles.get(role_title) or {}
    right_item = right_roles.get(role_title) or {}
    if abs((_safe_int(left_item.get("months_until_hire")) or 0) - (_safe_int(right_item.get("months_until_hire")) or 0)) >= 1:
      return True
    left_wage = _safe_float(left_item.get("annual_wage"))
    right_wage = _safe_float(right_item.get("annual_wage"))
    if max(left_wage, right_wage) > 0 and abs(left_wage - right_wage) >= max(250.0, 0.01 * max(left_wage, right_wage)):
      return True
  return False


def _candidate_objective(candidate: Dict[str, Any], *, break_even_target_exists: bool) -> float:
  break_even = 1.0 if bool(candidate.get("break_even_ebitda")) else 0.0
  ebitda_gap = _safe_float(candidate.get("ebitda_gap"))
  ebitda = _safe_float(candidate.get("ebitda"))
  net_income = _safe_float(candidate.get("net_income"))
  disruption = _safe_float(candidate.get("disruption_score"))
  improvement = _safe_float(candidate.get("improvement_amount"))
  blocking_count = max(0.0, _safe_float(candidate.get("remaining_blocking_count")))
  remaining_count = max(0.0, _safe_float(candidate.get("remaining_violation_count")))
  realism_distance = max(0.0, _safe_float(candidate.get("realism_distance")))
  coordination_score = max(0.0, _safe_float(candidate.get("coordination_score")))
  meaningful_lever_count = max(0.0, _safe_float(candidate.get("meaningful_lever_count")))
  if break_even_target_exists:
    return (
      1_000_000.0 * break_even
      - (BLOCKING_VIOLATION_PENALTY * blocking_count)
      - (NONBLOCKING_VIOLATION_PENALTY * max(0.0, remaining_count - blocking_count))
      - 2_500.0 * realism_distance
      - 1_000.0 * disruption
      + 250.0 * coordination_score
      + 400.0 * meaningful_lever_count
      + ebitda
      + 0.01 * net_income
      + 0.001 * improvement
    )
  return (
    - (BLOCKING_VIOLATION_PENALTY * blocking_count)
    - (NONBLOCKING_VIOLATION_PENALTY * max(0.0, remaining_count - blocking_count))
    -10_000.0 * ebitda_gap
    - 2_500.0 * realism_distance
    + 250.0 * coordination_score
    + 400.0 * meaningful_lever_count
    + ebitda
    + 0.01 * net_income
    - 10.0 * disruption
    + 0.001 * improvement
  )


def _select_materially_distinct_scenarios(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
  archetype_priority = {
    "operations": 0,
    "growth": 1,
    "efficiency": 2,
  }
  profile_priority = {
    "balanced": 0,
    "operations_first": 1,
    "labor_support_first": 2,
    "growth_first": 3,
    "profit_first": 4,
    "lean_survival": 5,
  }
  scenarios = [candidate for candidate in candidates if isinstance(candidate, dict)]
  scenarios.sort(
    key=lambda item: (
      _safe_float(item.get("remaining_blocking_count")),
      _safe_float(item.get("remaining_violation_count")),
      -_safe_float(item.get("meaningful_lever_count")),
      -_safe_float(item.get("coordination_score")),
      archetype_priority.get(str(item.get("archetype") or "").strip(), 99),
      profile_priority.get(str(item.get("solution_profile_id") or "").strip(), 99),
      _safe_float(item.get("realism_distance")),
      _safe_float(item.get("target_distance")),
      _safe_float(item.get("distortion_total")) or _safe_float(item.get("disruption_score")),
      -abs(_safe_float(item.get("ebitda"))),
    )
  )
  materially_distinct: List[Dict[str, Any]] = []
  used_profiles = set()
  used_archetypes = set()
  for candidate in scenarios:
    profile_id = str(candidate.get("solution_profile_id") or "").strip()
    archetype = str(candidate.get("archetype") or "").strip()
    if archetype in used_archetypes:
      continue
    if any(not _materially_distinct_candidate(candidate, existing) for existing in materially_distinct):
      continue
    materially_distinct.append(candidate)
    used_profiles.add(profile_id)
    used_archetypes.add(archetype)
    if len(materially_distinct) >= MAX_SCENARIOS:
      return materially_distinct[:MAX_SCENARIOS]
  if len(materially_distinct) < MAX_SCENARIOS:
    for candidate in scenarios:
      if any(candidate is existing for existing in materially_distinct):
        continue
      profile_id = str(candidate.get("solution_profile_id") or "").strip()
      if profile_id in used_profiles:
        continue
      if any(not _materially_distinct_candidate(candidate, existing) for existing in materially_distinct):
        continue
      materially_distinct.append(candidate)
      used_profiles.add(profile_id)
      if len(materially_distinct) >= MAX_SCENARIOS:
        break
  return materially_distinct[:MAX_SCENARIOS]


def _scenario_marketing_ratio(candidate: Dict[str, Any]) -> Optional[float]:
  summary = candidate.get("summary") if isinstance(candidate, dict) else {}
  summary = summary if isinstance(summary, dict) else {}
  revenue = max(0.0, _safe_float(summary.get("revenue")))
  marketing = max(0.0, _safe_float(summary.get("marketing")))
  if revenue <= 0:
    return None
  return marketing / revenue


def _presentation_issues(
  candidate: Dict[str, Any],
  *,
  state_model: Optional[Dict[str, Any]] = None,
  selected_candidates: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[str]:
  issues: List[str] = []
  candidate = candidate if isinstance(candidate, dict) else {}
  state_model = state_model if isinstance(state_model, dict) else {}
  selected_candidates = [item for item in (selected_candidates or []) if isinstance(item, dict)]

  if _safe_float(candidate.get("remaining_blocking_count")) > 0:
    issues.append("remaining_blockers")

  if any(not _materially_distinct_candidate(candidate, existing) for existing in selected_candidates):
    issues.append("near_duplicate")

  exact_patches = candidate.get("exact_patches") if isinstance(candidate, dict) else {}
  exact_patches = exact_patches if isinstance(exact_patches, dict) else {}
  year1_patch = exact_patches.get("financials_year1_patch") if isinstance(exact_patches, dict) else {}
  year1_patch = year1_patch if isinstance(year1_patch, dict) else {}
  product_overrides = year1_patch.get("product_overrides") if isinstance(year1_patch, dict) else {}
  product_overrides = product_overrides if isinstance(product_overrides, dict) else {}
  if product_overrides and (year1_patch.get("unit_price") is not None or year1_patch.get("utilization_rate") is not None):
    issues.append("child_parent_contradiction")

  fixed_facts = state_model.get("fixed_facts") if isinstance(state_model, dict) else {}
  fixed_facts = fixed_facts if isinstance(fixed_facts, dict) else {}
  sales_modality = str(fixed_facts.get("sales_modality") or "").strip().lower()
  capacity_driver = str(fixed_facts.get("capacity_driver") or "").strip().lower()
  constraint_profile = state_model.get("constraint_profile") if isinstance(state_model, dict) else {}
  constraint_profile = constraint_profile if isinstance(constraint_profile, dict) else {}
  util_envelope = (constraint_profile.get("utilization_envelope") if isinstance(constraint_profile, dict) else {}) or {}
  util_floor = _normalize_ratio((util_envelope or {}).get("min"))
  summary = candidate.get("summary") if isinstance(candidate, dict) else {}
  summary = summary if isinstance(summary, dict) else {}
  scenario_util = _normalize_ratio(
    ((year1_patch or {}).get("utilization_rate"))
    or (summary.get("utilization"))
    or (((candidate.get("forecast_engine_state") or {}) if isinstance(candidate.get("forecast_engine_state"), dict) else {}).get("starting_state") or {}).get("utilization")
  )
  presentation_util_floor = util_floor
  if capacity_driver == "labor" and sales_modality in {"local_service", "project_based"}:
    presentation_util_floor = max(presentation_util_floor or 0.0, 0.45)
  if scenario_util is not None and presentation_util_floor is not None and scenario_util < presentation_util_floor - 0.01:
    issues.append("weak_utilization_story")

  marketing_ratio = _scenario_marketing_ratio(candidate)
  archetype = str(candidate.get("archetype") or "").strip()
  if marketing_ratio is not None:
    if archetype != "growth" and marketing_ratio > 0.22:
      issues.append("bizarre_marketing")
    elif archetype == "growth" and marketing_ratio > 0.32:
      issues.append("bizarre_marketing")

  label = str(candidate.get("label") or "").strip()
  rationale = str(candidate.get("rationale") or "").strip().lower()
  dominant_tradeoff = str(candidate.get("dominant_tradeoff") or "").strip().lower()
  if not label or ":" not in label:
    issues.append("weak_label")
  if dominant_tradeoff and dominant_tradeoff not in rationale:
    issues.append("weak_rationale")

  return list(dict.fromkeys(issues))


def _select_client_ready_scenarios(
  candidates: Sequence[Dict[str, Any]],
  *,
  state_model: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  selected: List[Dict[str, Any]] = []
  for candidate in _select_materially_distinct_scenarios(candidates):
    issues = _presentation_issues(candidate, state_model=state_model, selected_candidates=selected)
    if issues:
      continue
    next_candidate = dict(candidate)
    next_candidate["presentation_issues"] = []
    selected.append(next_candidate)
    if len(selected) >= MAX_SCENARIOS:
      break
  if selected:
    return selected
  fallback: List[Dict[str, Any]] = []
  for candidate in _select_materially_distinct_scenarios(candidates):
    issues = _presentation_issues(candidate, state_model=state_model, selected_candidates=fallback)
    if "remaining_blockers" in issues:
      continue
    next_candidate = dict(candidate)
    next_candidate["presentation_issues"] = issues
    fallback.append(next_candidate)
    if len(fallback) >= MAX_SCENARIOS:
      break
  return fallback


def _scenario_forecast_summary(bundle: Dict[str, Any]) -> Dict[str, Any]:
  bundle = bundle if isinstance(bundle, dict) else {}
  state = bundle.get("forecast_engine_state") if isinstance(bundle, dict) else {}
  state = state if isinstance(state, dict) else {}
  quarters = bundle.get("forecast_quarters") if isinstance(bundle, dict) else []
  quarters = quarters if isinstance(quarters, list) else []
  def _quarter_at(index: int) -> Dict[str, Any]:
    if 0 <= index < len(quarters) and isinstance(quarters[index], dict):
      return quarters[index]
    return {}
  q4 = _quarter_at(3)
  q12 = _quarter_at(11)
  q20 = _quarter_at(19)
  return {
    "status": str(state.get("status") or "unavailable").strip() or "unavailable",
    "quarter_count": len(quarters),
    "year1_exit_ebitda": round(_safe_float(q4.get("ebitda")), 2) if q4 else None,
    "year3_exit_ebitda": round(_safe_float(q12.get("ebitda")), 2) if q12 else None,
    "year5_exit_ebitda": round(_safe_float(q20.get("ebitda")), 2) if q20 else None,
    "year5_exit_revenue": round(_safe_float(q20.get("revenue")), 2) if q20 else None,
    "year5_status": str(q20.get("realism_check_status") or "").strip() if q20 else None,
  }


def _build_scenario_forecast_bundle(
  *,
  baseline_state: Dict[str, Any],
  exact_patches: Dict[str, Any],
  remaining_violations: Sequence[str],
  constraint_engine_state: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]],
  benchmark_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  remaining = [
    str(code or "").strip()
    for code in (remaining_violations or [])
    if str(code or "").strip()
  ]
  blocking_remaining = [
    code for code in remaining
    if code in {
      "ebitda_margin_too_low",
      "ebitda_margin_too_high",
      "capacity_unsupported",
      "revenue_out_of_range",
      "gross_margin_too_low",
      "gross_margin_too_high",
      "payroll_too_light",
      "payroll_too_heavy",
      "opex_too_light",
      "opex_too_heavy",
      "utilization_too_low",
      "utilization_too_high",
    }
  ]
  if blocking_remaining:
    bundle = {
      "forecast_engine_state": {
        "status": "blocked_unresolved_year1",
        "blocking_violations": blocking_remaining,
      },
      "forecast_quarters": [],
      "engine_versions": {},
    }
    bundle["forecast_summary"] = _scenario_forecast_summary(bundle)
    return bundle
  if not isinstance(normalized_traits, dict) or not isinstance(benchmark_payload, dict):
    bundle = {
      "forecast_engine_state": {
        "status": "unavailable_missing_inputs",
        "blocking_violations": [],
      },
      "forecast_quarters": [],
      "engine_versions": {},
    }
    bundle["forecast_summary"] = _scenario_forecast_summary(bundle)
    return bundle
  next_ops, next_people, next_financials, next_year1, next_marketing_model = _apply_exact_patches(
    ops_json=baseline_state.get("ops_json") or {},
    people_json=baseline_state.get("people_json") or {},
    financials_json=baseline_state.get("financials_json") or {},
    financials_year1_json=baseline_state.get("financials_year1_json") or {},
    marketing_model_json=baseline_state.get("marketing_model_json") or {},
    exact_patches=exact_patches,
  )
  scenario_engine_state = _clone(constraint_engine_state or {})
  if isinstance(scenario_engine_state, dict):
    scenario_engine_state["violations"] = list(remaining)
  try:
    try:
      from forecast_engine import build_forecast_engine_bundle  # type: ignore
    except Exception:
      from client_intake_and_finmo.forecast_engine import build_forecast_engine_bundle  # type: ignore
    bundle = build_forecast_engine_bundle(
      operating_model_json=next_ops,
      people_json=next_people,
      financials_json=next_financials,
      financials_year1_json=next_year1,
      marketing_model_json=next_marketing_model,
      normalized_traits=normalized_traits,
      benchmark_payload=benchmark_payload,
      constraint_engine_state=scenario_engine_state,
    )
  except Exception:
    bundle = {
      "forecast_engine_state": {
        "status": "forecast_error",
        "blocking_violations": [],
      },
      "forecast_quarters": [],
      "engine_versions": {},
    }
  bundle["forecast_summary"] = _scenario_forecast_summary(bundle)
  return bundle


def _collect_solver_roles(people_json: Dict[str, Any]) -> List[Dict[str, Any]]:
  all_role_wages: List[float] = []
  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    annual_wage = _safe_float(person.get("annual_wage"))
    if annual_wage > 0:
      all_role_wages.append(annual_wage)
  for role in (people_json or {}).get("inferred_roles") or []:
    if not isinstance(role, dict):
      continue
    annual_wage = _safe_float(role.get("annual_wage"))
    if annual_wage > 0:
      all_role_wages.append(annual_wage)
  all_role_wages = sorted({round(wage, 2) for wage in all_role_wages if wage > 0})

  roles_out: List[Dict[str, Any]] = []
  roles = (people_json or {}).get("inferred_roles") or []
  if not isinstance(roles, list):
    return roles_out
  for role in roles:
    if not isinstance(role, dict):
      continue
    annual_wage = _safe_float(role.get("annual_wage"))
    if annual_wage <= 0:
      continue
    role_title = str(role.get("role_title") or "").strip()
    if not role_title:
      continue
    base_months = max(0, min(12, _safe_int(role.get("months_until_hire")) or 0))
    baseline_year1_amount = annual_wage * ((12.0 - float(base_months)) / 12.0)
    if baseline_year1_amount <= 0:
      continue
    lower_neighbors = [wage for wage in all_role_wages if wage < annual_wage - 0.01]
    upper_neighbors = [wage for wage in all_role_wages if wage > annual_wage + 0.01]
    nearest_lower = max(lower_neighbors) if lower_neighbors else annual_wage * ROLE_WAGE_MIN_FACTOR
    nearest_upper = min(upper_neighbors) if upper_neighbors else annual_wage * max(ROLE_WAGE_MAX_FACTOR, 1.15)
    wage_floor = max(0.0, min(annual_wage, (annual_wage + nearest_lower) / 2.0))
    wage_ceiling = max(wage_floor, nearest_upper)
    roles_out.append(
      {
        "role_title": role_title,
        "annual_wage": annual_wage,
        "base_months": base_months,
        "baseline_year1_amount": baseline_year1_amount,
        "wage_floor": wage_floor,
        "wage_ceiling": wage_ceiling,
      }
    )
  roles_out.sort(key=lambda item: item.get("baseline_year1_amount") or 0.0, reverse=True)
  return roles_out


def _semantic_value(
  *,
  value: Any,
  metric_type: str,
  unit_basis: str,
  time_basis: str,
  hard_constraint_eligible: bool,
  transform_required: Optional[str] = None,
) -> Dict[str, Any]:
  return {
    "value": value,
    "metric_type": str(metric_type or "").strip(),
    "unit_basis": str(unit_basis or "").strip(),
    "time_basis": str(time_basis or "").strip(),
    "hard_constraint_eligible": bool(hard_constraint_eligible),
    "transform_required": str(transform_required or "").strip() or None,
  }


def _semantic_value_number(payload: Any) -> float:
  if isinstance(payload, dict):
    return _safe_float(payload.get("value"))
  return _safe_float(payload)


def _semantic_values_compatible(left: Any, right: Any) -> bool:
  if not isinstance(left, dict) or not isinstance(right, dict):
    return False
  if not bool(left.get("hard_constraint_eligible")):
    return False
  if not bool(right.get("hard_constraint_eligible")):
    return False
  if str(left.get("transform_required") or "").strip():
    return False
  if str(right.get("transform_required") or "").strip():
    return False
  return (
    str(left.get("metric_type") or "").strip() == str(right.get("metric_type") or "").strip()
    and str(left.get("unit_basis") or "").strip() == str(right.get("unit_basis") or "").strip()
    and str(left.get("time_basis") or "").strip() == str(right.get("time_basis") or "").strip()
  )


def _constraint_source_value(
  constraint_basis: Dict[str, Any],
  key: str,
) -> Optional[Dict[str, Any]]:
  payload = constraint_basis.get(key) if isinstance(constraint_basis, dict) else None
  return payload if isinstance(payload, dict) else None


def _build_constraint_audit(constraint_basis: Dict[str, Any]) -> List[Dict[str, Any]]:
  audit: List[Dict[str, Any]] = []
  for key, payload in (constraint_basis or {}).items():
    if not isinstance(payload, dict):
      continue
    audit.append(
      {
        "field": str(key),
        "metric_type": str(payload.get("metric_type") or "").strip(),
        "unit_basis": str(payload.get("unit_basis") or "").strip(),
        "time_basis": str(payload.get("time_basis") or "").strip(),
        "hard_constraint_eligible": bool(payload.get("hard_constraint_eligible")),
        "transform_required": payload.get("transform_required"),
      }
    )
  return audit


def _build_constraint_profile(
  *,
  fixed_facts: Dict[str, Any],
  controllable_drivers: Dict[str, Any],
  derived_outputs: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  baseline_payroll_support: float,
  fixed_people_payroll: float,
) -> Dict[str, Any]:
  revenue_drivers = controllable_drivers.get("revenue") if isinstance(controllable_drivers, dict) else {}
  marketing_drivers = controllable_drivers.get("marketing") if isinstance(controllable_drivers, dict) else {}
  opex_drivers = controllable_drivers.get("other_opex") if isinstance(controllable_drivers, dict) else {}
  people_drivers = controllable_drivers.get("people") if isinstance(controllable_drivers, dict) else {}
  constraint_basis = fixed_facts.get("constraint_basis") if isinstance(fixed_facts, dict) else {}

  price_driver = (revenue_drivers or {}).get("unit_price") if isinstance(revenue_drivers, dict) else {}
  util_driver = (revenue_drivers or {}).get("utilization_rate") if isinstance(revenue_drivers, dict) else {}
  marketing_driver = (marketing_drivers or {}).get("marketing_total_year1") if isinstance(marketing_drivers, dict) else {}
  opex_driver = (opex_drivers or {}).get("other_operating_expense") if isinstance(opex_drivers, dict) else {}
  inferred_roles = (people_drivers or {}).get("inferred_roles") if isinstance(people_drivers, dict) else []
  inferred_roles = inferred_roles if isinstance(inferred_roles, list) else []

  demand_supported_units_semantic = _constraint_source_value(constraint_basis, "demand_supported_units_year1")
  staffing_supported_capacity_semantic = _constraint_source_value(constraint_basis, "staffing_supported_capacity_units_year1")
  required_units_semantic = _semantic_value(
    value=max(0.0, _safe_float(fixed_facts.get("baseline_units_year1"))),
    metric_type="units",
    unit_basis="core_unit",
    time_basis="per_year",
    hard_constraint_eligible=True,
  )
  demand_curve: Dict[str, Any] = {
    "semantic": demand_supported_units_semantic,
    "baseline_supported_units": _semantic_value_number(demand_supported_units_semantic),
    "units_per_marketing_dollar": 0.0,
    "enabled": False,
  }
  marketing_baseline = max(0.0, _safe_float((marketing_driver or {}).get("baseline")))
  if (
    _semantic_values_compatible(required_units_semantic, demand_supported_units_semantic)
    and marketing_baseline > 0
  ):
    demand_curve["units_per_marketing_dollar"] = (
      _semantic_value_number(demand_supported_units_semantic) / max(marketing_baseline, 1e-9)
    )
    demand_curve["enabled"] = demand_curve["units_per_marketing_dollar"] > 0

  capacity_curve: Dict[str, Any] = {
    "semantic": staffing_supported_capacity_semantic,
    "baseline_supported_units": _semantic_value_number(staffing_supported_capacity_semantic),
    "units_per_payroll_dollar": 0.0,
    "baseline_payroll_support": max(0.0, baseline_payroll_support),
    "fixed_people_payroll": max(0.0, fixed_people_payroll),
    "units_per_active_role_month": 0.0,
    "fixed_active_role_months": 0.0,
    "baseline_adjustable_active_months": 0.0,
    "basis": "payroll",
    "enabled": False,
  }
  current_staff = fixed_facts.get("current_staff") if isinstance(fixed_facts, dict) else []
  current_staff = current_staff if isinstance(current_staff, list) else []
  fixed_active_role_months = 12.0 * float(len([p for p in current_staff if isinstance(p, dict)]))
  baseline_adjustable_active_months = 0.0
  for role in inferred_roles:
    if not isinstance(role, dict):
      continue
    base_months = max(0, min(12, _safe_int(role.get("base_months")) or 0))
    baseline_adjustable_active_months += max(0.0, 12.0 - float(base_months))
  total_active_role_months = fixed_active_role_months + baseline_adjustable_active_months
  if (
    _semantic_values_compatible(required_units_semantic, staffing_supported_capacity_semantic)
    and total_active_role_months > 0
  ):
    capacity_curve["units_per_active_role_month"] = (
      _semantic_value_number(staffing_supported_capacity_semantic) / max(total_active_role_months, 1e-9)
    )
    capacity_curve["fixed_active_role_months"] = fixed_active_role_months
    capacity_curve["baseline_adjustable_active_months"] = baseline_adjustable_active_months
    capacity_curve["basis"] = "role_months"
    capacity_curve["enabled"] = capacity_curve["units_per_active_role_month"] > 0
  elif (
    _semantic_values_compatible(required_units_semantic, staffing_supported_capacity_semantic)
    and baseline_payroll_support > 0
  ):
    capacity_curve["units_per_payroll_dollar"] = (
      _semantic_value_number(staffing_supported_capacity_semantic) / max(baseline_payroll_support, 1e-9)
    )
    capacity_curve["basis"] = "payroll"
    capacity_curve["enabled"] = capacity_curve["units_per_payroll_dollar"] > 0

  role_wage_bounds: List[Dict[str, Any]] = []
  for role in inferred_roles:
    if not isinstance(role, dict):
      continue
    role_wage_bounds.append(
      {
        "role_title": str(role.get("role_title") or "").strip(),
        "baseline": max(0.0, _safe_float(role.get("annual_wage"))),
        "min": max(0.0, _safe_float(role.get("wage_floor"))),
        "max": max(0.0, _safe_float(role.get("wage_ceiling"))),
      }
    )

  return {
    "required_units_semantic": required_units_semantic,
    "constraint_audit": _build_constraint_audit(constraint_basis or {}),
    "price_envelope": {
      "baseline": _safe_float((price_driver or {}).get("baseline")),
      "min": _safe_float((price_driver or {}).get("min")),
      "max": _safe_float((price_driver or {}).get("max")),
      "enabled": bool((price_driver or {}).get("enabled")),
    },
    "utilization_envelope": {
      "baseline": _normalize_ratio((util_driver or {}).get("baseline")) or 0.0,
      "min": _normalize_ratio((util_driver or {}).get("min")) or 0.0,
      "max": _normalize_ratio((util_driver or {}).get("max")) or 1.0,
      "enabled": bool((util_driver or {}).get("enabled")),
    },
    "marketing_envelope": {
      "baseline": marketing_baseline,
      "min": max(0.0, _safe_float((marketing_driver or {}).get("min"))),
      "max": max(0.0, _safe_float((marketing_driver or {}).get("max"))),
      "enabled": bool((marketing_driver or {}).get("enabled")),
      "source": str((marketing_driver or {}).get("source") or "").strip() or "parent_fallback",
    },
    "marketing_children": {
      "reachable_market": max(0.0, _safe_float((marketing_model_json or {}).get("reachable_market"))),
      "baseline_capture_rate": max(
        _safe_float((marketing_model_json or {}).get("capture_rate_year1")),
        (
          max(0.0, _safe_float(fixed_facts.get("baseline_units_year1")))
          / max(_safe_float((marketing_model_json or {}).get("reachable_market")), 1e-9)
          if _safe_float((marketing_model_json or {}).get("reachable_market")) > 0
          else 0.0
        ),
      ),
      "baseline_expected_customers_or_clients_year1": max(
        0.0,
        _safe_float((marketing_model_json or {}).get("expected_customers_or_clients_year1")),
      ),
      "baseline_expected_units_year1": max(
        0.0,
        _safe_float((marketing_model_json or {}).get("expected_units_year1")),
      ),
    },
    "other_opex_envelope": {
      "baseline": max(0.0, _safe_float((opex_driver or {}).get("baseline"))),
      "min": (
        max(0.0, _safe_float((opex_driver or {}).get("baseline")))
        if str((opex_driver or {}).get("source") or "").strip() == "parent_fallback"
        else max(0.0, _safe_float((opex_driver or {}).get("min")))
      ),
      "max": max(0.0, _safe_float((opex_driver or {}).get("max"))),
      "enabled": bool((opex_driver or {}).get("enabled")) and str((opex_driver or {}).get("source") or "").strip() != "parent_fallback",
      "source": str((opex_driver or {}).get("source") or "").strip() or "parent_fallback",
    },
    "demand_curve": demand_curve,
    "capacity_curve": capacity_curve,
    "role_wage_bounds": role_wage_bounds,
    "current_revenue": max(0.0, _safe_float((derived_outputs or {}).get("revenue"))),
    "current_cogs": max(0.0, _safe_float((fixed_facts or {}).get("cogs_total_year1"))),
    "current_interest": max(0.0, _safe_float((fixed_facts or {}).get("interest"))),
    "rent_annualized": max(0.0, _safe_float((fixed_facts or {}).get("rent_annualized"))),
  }


def _build_solver_state_model(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  engine_state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  if not engine_state:
    return None
  solve_mode, product_driver_basis = _resolve_solver_mode(
    financials_year1_json=financials_year1_json or {},
    ops_json=ops_json or {},
  )
  current_price = _safe_float(
    (
      _weighted_product_price(product_driver_basis)
      if solve_mode == "child_first"
      else 0.0
    )
    or _top_level_driver_value(financials_year1_json or {}, "unit_price")
    or (ops_json or {}).get("unit_price")
  )
  current_util = _normalize_ratio(
    (
      _weighted_product_utilization(product_driver_basis)
      if solve_mode == "child_first"
      else None
    )
    or _top_level_driver_value(financials_year1_json or {}, "utilization_rate")
    or (ops_json or {}).get("utilization_rate")
  )
  baseline_units = (
    sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_driver_basis)
    if solve_mode == "child_first"
    else 0.0
  ) or _required_units_year1(financials_year1_json or {})
  if current_price <= 0 or current_util is None or baseline_units <= 0:
    return None

  current_marketing = max(0.0, _safe_float((financials_json or {}).get("marketing_total_year1")))
  current_other_opex = max(0.0, _safe_float((financials_json or {}).get("other_operating_expense")))
  current_interest = max(0.0, _safe_float((baseline_summary or {}).get("interest")))
  current_cogs = max(0.0, _safe_float((baseline_summary or {}).get("cogs")))
  rent_annualized = max(0.0, _safe_float((baseline_summary or {}).get("rent_annualized")))
  current_revenue = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
  current_cogs_ratio = (current_cogs / current_revenue) if current_revenue > 0 else None

  supportable_unit_range = engine_state.get("supportable_unit_range") if isinstance(engine_state, dict) else {}
  supportable_revenue_range = engine_state.get("supportable_revenue_range") if isinstance(engine_state, dict) else {}
  utilization_range = engine_state.get("utilization_range") if isinstance(engine_state, dict) else {}
  gross_margin_band = engine_state.get("gross_margin_band") if isinstance(engine_state, dict) else {}
  ebitda_margin_band = engine_state.get("ebitda_margin_band") if isinstance(engine_state, dict) else {}
  opex_intensity_band = engine_state.get("opex_intensity_band") if isinstance(engine_state, dict) else {}
  marketing_intensity_band = engine_state.get("marketing_intensity_band") if isinstance(engine_state, dict) else {}
  current_metrics = engine_state.get("current_metrics") if isinstance(engine_state, dict) else {}
  payroll_structural = {
    "people_payroll_floor": max(0.0, _safe_float((current_metrics or {}).get("people_payroll_floor"))),
    "structural_payroll_floor": max(0.0, _safe_float((current_metrics or {}).get("structural_payroll_floor"))),
    "active_role_months_year1": max(0.0, _safe_float((current_metrics or {}).get("active_role_months_year1"))),
    "fte_equivalent_year1": max(0.0, _safe_float((current_metrics or {}).get("fte_equivalent_year1"))),
    "required_fte_from_workload": max(0.0, _safe_float((current_metrics or {}).get("required_fte_from_workload"))),
  }

  supportable_units_min = _band_min(supportable_unit_range)
  supportable_units_max = _band_max(supportable_unit_range)
  supportable_revenue_min = _band_min(supportable_revenue_range)
  supportable_revenue_max = _band_max(supportable_revenue_range)
  util_min = _band_min(utilization_range)
  util_max = _band_max(utilization_range)
  gross_margin_min = _band_min(gross_margin_band)
  gross_margin_max = _band_max(gross_margin_band)
  opex_min_ratio = _band_min(opex_intensity_band)
  opex_max_ratio = _band_max(opex_intensity_band)
  marketing_min_ratio = _band_min(marketing_intensity_band)
  marketing_max_ratio = _band_max(marketing_intensity_band)
  physical_capacity_units = max(
    sum(max(0.0, _safe_float(item.get("annual_capacity_units"))) for item in product_driver_basis),
    baseline_units / max(current_util, 1e-9),
    max(0.0, _safe_float((current_metrics or {}).get("capacity_units_year1"))),
    baseline_units,
  )
  constraint_confidence = max(0.0, min(1.0, _safe_float(engine_state.get("constraint_confidence_score"))))
  fallback_level = str(engine_state.get("fallback_level") or "generic").strip().lower()
  price_down_pct = 0.02 if constraint_confidence >= 0.65 and fallback_level != "generic" else 0.04
  price_up_pct = 0.03 if constraint_confidence >= 0.65 and fallback_level != "generic" else 0.05

  current_people: List[Dict[str, Any]] = []
  for person in (people_json or {}).get("people") or []:
    if not isinstance(person, dict):
      continue
    annual_wage = max(0.0, _safe_float(person.get("annual_wage")))
    current_people.append(
      {
        "full_name": str(person.get("full_name") or "").strip(),
        "role_title": str(person.get("role_title") or "").strip(),
        "annual_wage": annual_wage,
        "adjustable": False,
      }
    )

  planned_roles = _collect_solver_roles(people_json or {})
  expected_units = max(
    0.0,
    _safe_float((marketing_model_json or {}).get("expected_units_year1"))
    or _safe_float(engine_state.get("demand_supported_units"))
    or baseline_units,
  )
  units_per_marketing_dollar = (
    expected_units / max(current_marketing, 1e-9)
    if current_marketing > 0 and expected_units > 0
    else 0.0
  )
  marketing_units_min = max(0.0, min(expected_units, supportable_units_min if supportable_units_min is not None else expected_units))
  marketing_units_max = max(expected_units, supportable_units_max if supportable_units_max is not None else expected_units)
  revenue_marketing_floor = (current_revenue * marketing_min_ratio) if current_revenue > 0 and marketing_min_ratio is not None else 0.0
  revenue_marketing_cap = (current_revenue * marketing_max_ratio) if current_revenue > 0 and marketing_max_ratio is not None else None
  units_based_marketing_cap = (
    marketing_units_max / max(units_per_marketing_dollar, 1e-9)
    if units_per_marketing_dollar > 0
    else None
  )
  marketing_min_total = revenue_marketing_floor
  if revenue_marketing_cap is not None and units_based_marketing_cap is not None:
    marketing_max_total = min(revenue_marketing_cap, units_based_marketing_cap)
  elif revenue_marketing_cap is not None:
    marketing_max_total = revenue_marketing_cap
  elif units_based_marketing_cap is not None:
    marketing_max_total = units_based_marketing_cap
  else:
    marketing_max_total = current_marketing
  marketing_max_total = max(marketing_min_total, marketing_max_total)

  revenue_anchor = max(
    current_revenue,
    supportable_revenue_max or 0.0,
    supportable_revenue_min or 0.0,
    1.0,
  )
  other_opex_min = max(
    0.0,
    min(
      current_other_opex,
      (opex_min_ratio * revenue_anchor) if opex_min_ratio is not None else current_other_opex,
    ),
  )
  other_opex_max = max(
    current_other_opex,
    (opex_max_ratio * revenue_anchor) if opex_max_ratio is not None else current_other_opex,
  )

  controllable_drivers = {
    "revenue": {
      "unit_price": {
        "baseline": current_price,
        "min": round(current_price * (1.0 - price_down_pct), 2),
        "max": round(current_price * (1.0 + price_up_pct), 2),
        "enabled": True,
      },
      "utilization_rate": {
        "baseline": current_util,
        "min": util_min if util_min is not None else current_util,
        "max": util_max if util_max is not None else current_util,
        "enabled": True,
      },
    },
    "marketing": {
      "marketing_total_year1": {
        "baseline": current_marketing,
        "min": marketing_min_total,
        "max": marketing_max_total,
        "enabled": True,
        "source": "constraint_engine",
      },
    },
    "other_opex": {
      "other_operating_expense": {
        "baseline": current_other_opex,
        "min": other_opex_min,
        "max": other_opex_max,
        "enabled": True,
        "source": "constraint_engine",
      },
    },
    "people": {
      "inferred_roles": [
        {
          "role_title": str(role.get("role_title") or "").strip(),
          "annual_wage": _safe_float(role.get("annual_wage")),
          "base_months": max(0, min(12, _safe_int(role.get("base_months")) or 0)),
          "min_months": 0,
          "max_months": 12,
          "baseline_year1_amount": max(0.0, _safe_float(role.get("baseline_year1_amount"))),
          "wage_floor": max(0.0, _safe_float(role.get("wage_floor"))),
          "wage_ceiling": max(
            max(0.0, _safe_float(role.get("wage_ceiling"))),
            _safe_float(role.get("annual_wage")),
          ),
          "enabled": True,
        }
        for role in planned_roles
        if isinstance(role, dict)
      ],
    },
    "milestones": {
      "timing_months_max": [
        {
          "index": index,
          "baseline": int(max(1, _safe_int(milestone.get("timing_months_max")) or 1)),
        }
        for index, milestone in enumerate((ops_json or {}).get("milestones") or [])
        if isinstance(milestone, dict)
      ],
    },
  }
  derived_outputs = {
    "revenue": current_revenue,
    "gross_profit": max(0.0, _safe_float((baseline_summary or {}).get("gross_profit"))),
    "payroll_total_year1": max(0.0, _safe_float((baseline_summary or {}).get("payroll"))),
    "marketing_total_year1": current_marketing,
    "other_opex_total_year1": max(0.0, _safe_float((baseline_summary or {}).get("other_opex"))),
    "ebitda": _safe_float((baseline_summary or {}).get("ebitda")),
    "net_income": _safe_float((baseline_summary or {}).get("net_income")),
    "loss_pct": _loss_pct(baseline_summary),
    "break_even_gap": _ebitda_gap(baseline_summary),
  }
  fixed_facts = {
    "solve_mode": solve_mode,
    "sales_modality": str((ops_json or {}).get("sales_modality") or "").strip(),
    "capacity_driver": str((ops_json or {}).get("capacity_driver") or "").strip(),
    "current_staff": current_people,
    "rent_annualized": rent_annualized,
    "interest": current_interest,
    "cogs_total_year1": current_cogs,
    "reachable_market": max(0.0, _safe_float((marketing_model_json or {}).get("reachable_market"))),
    "baseline_units_year1": baseline_units,
    "physical_capacity_units_year1": physical_capacity_units,
    "supported_capacity_units_year1": max(
      baseline_units,
      supportable_units_max if supportable_units_max is not None else baseline_units,
    ),
    "expected_units_year1": expected_units,
    "constraint_engine_state": _clone(engine_state),
    "constraint_audit": _clone(engine_state.get("constraints") or []),
    "product_driver_basis": _clone(product_driver_basis),
    "payroll_structural": payroll_structural,
  }
  constraint_profile = {
    "constraint_audit": _clone(engine_state.get("constraints") or []),
    "price_envelope": {
      "baseline": current_price,
      "min": round(current_price * (1.0 - price_down_pct), 2),
      "max": round(current_price * (1.0 + price_up_pct), 2),
      "enabled": True,
    },
    "utilization_envelope": {
      "baseline": current_util,
      "min": util_min if util_min is not None else current_util,
      "max": util_max if util_max is not None else current_util,
      "enabled": True,
    },
    "marketing_envelope": {
      "baseline": current_marketing,
      "min": marketing_min_total,
      "max": marketing_max_total if marketing_max_total > 0 else current_marketing,
      "enabled": True,
      "source": "constraint_engine",
      "intensity_min_ratio": marketing_min_ratio,
      "intensity_max_ratio": marketing_max_ratio,
    },
    "marketing_children": {
      "reachable_market": max(0.0, _safe_float((marketing_model_json or {}).get("reachable_market"))),
      "baseline_capture_rate": max(0.0, _safe_float((marketing_model_json or {}).get("capture_rate_year1"))),
      "baseline_expected_customers_or_clients_year1": max(
        0.0,
        _safe_float((marketing_model_json or {}).get("expected_customers_or_clients_year1")),
      ),
      "baseline_expected_units_year1": expected_units,
    },
    "other_opex_envelope": {
      "baseline": current_other_opex,
      "min": other_opex_min,
      "max": other_opex_max if other_opex_max > 0 else current_other_opex,
      "enabled": True,
      "source": "constraint_engine",
    },
    "cogs_envelope": {
      "baseline": current_cogs,
      "baseline_ratio": current_cogs_ratio,
      "min_ratio": max(0.0, 1.0 - (gross_margin_max if gross_margin_max is not None else (1.0 - (current_cogs_ratio or 0.0)))),
      "max_ratio": max(0.0, 1.0 - (gross_margin_min if gross_margin_min is not None else (1.0 - (current_cogs_ratio or 0.0)))),
      "enabled": True,
      "source": "constraint_engine",
    },
    "demand_curve": {
      "semantic": None,
      "baseline_supported_units": expected_units,
      "units_per_marketing_dollar": units_per_marketing_dollar,
      "enabled": units_per_marketing_dollar > 0,
    },
    "capacity_curve": {
      "semantic": None,
      "basis": "hard_units",
      "hard_units_min": supportable_units_min if supportable_units_min is not None else 0.0,
      "hard_units_max": supportable_units_max if supportable_units_max is not None else baseline_units,
      "enabled": True,
    },
    "role_wage_bounds": [
      {
        "role_title": str(role.get("role_title") or "").strip(),
        "baseline": max(0.0, _safe_float(role.get("annual_wage"))),
        "min": max(0.0, _safe_float(role.get("wage_floor"))),
        "max": max(0.0, _safe_float(role.get("wage_ceiling"))),
      }
      for role in planned_roles
      if isinstance(role, dict)
    ],
    "current_revenue": current_revenue,
    "current_cogs": current_cogs,
    "current_interest": current_interest,
    "current_other_opex_total": current_other_opex,
    "rent_annualized": rent_annualized,
    "constraint_engine_violations": list(engine_state.get("violations") or []),
    "constraint_engine_state": _clone(engine_state),
    "payroll_structural": payroll_structural,
  }

  return {
    "solve_mode": solve_mode,
    "fixed_facts": fixed_facts,
    "controllable_drivers": controllable_drivers,
    "derived_outputs": derived_outputs,
    "constraint_profile": constraint_profile,
    "objective_policy": {
      "primary_target": "year1_realism",
      "fallback_target": "minimize_realism_gap",
      "healthy_ebitda_margin_ratio": HEALTHY_EBITDA_MARGIN_RATIO,
      "ebitda_cushion_preference_weight": EBITDA_CUSHION_PREFERENCE_WEIGHT,
      "option_objective_tolerance_ratio": OPTION_OBJECTIVE_TOLERANCE_RATIO,
      "option_objective_tolerance_abs": OPTION_OBJECTIVE_TOLERANCE_ABS,
      "family_concentration_weight": FAMILY_CONCENTRATION_WEIGHT,
      "distortion_weights": {
        "price_up": PRICE_DISTORTION_WEIGHT,
        "price_down": PRICE_DOWN_DISTORTION_WEIGHT,
        "util_up": UTILIZATION_DISTORTION_WEIGHT,
        "util_down": UTILIZATION_DOWN_DISTORTION_WEIGHT,
        "marketing_up": MARKETING_UP_DISTORTION_WEIGHT,
        "marketing_down": MARKETING_DOWN_DISTORTION_WEIGHT,
        "other_opex_down": OTHER_OPEX_DISTORTION_WEIGHT,
        "other_opex_up": OTHER_OPEX_UP_DISTORTION_WEIGHT,
        "cogs_down": COGS_DOWN_DISTORTION_WEIGHT,
        "cogs_up": COGS_UP_DISTORTION_WEIGHT,
        "hire_delay": HIRE_DELAY_DISTORTION_WEIGHT,
        "hire_advance": HIRE_ADVANCE_DISTORTION_WEIGHT,
        "payroll_down": PAYROLL_DOWN_DISTORTION_WEIGHT,
        "payroll_up": PAYROLL_UP_DISTORTION_WEIGHT,
      },
    },
  }


def _solver_profiles(state_model: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  base_weights = {}
  family_concentration_weight = FAMILY_CONCENTRATION_WEIGHT
  ebitda_cushion_preference_weight = EBITDA_CUSHION_PREFERENCE_WEIGHT
  objective_tolerance_ratio = OPTION_OBJECTIVE_TOLERANCE_RATIO
  objective_tolerance_abs = OPTION_OBJECTIVE_TOLERANCE_ABS
  active_violations: List[str] = []
  sales_modality = ""
  capacity_driver = ""
  if isinstance(state_model, dict):
    objective_policy = state_model.get("objective_policy")
    if isinstance(objective_policy, dict):
      maybe_weights = objective_policy.get("distortion_weights")
      if isinstance(maybe_weights, dict):
        base_weights = dict(maybe_weights)
      family_concentration_weight = _safe_float(
        objective_policy.get("family_concentration_weight"),
      ) or FAMILY_CONCENTRATION_WEIGHT
      ebitda_cushion_preference_weight = _safe_float(
        objective_policy.get("ebitda_cushion_preference_weight"),
      ) or EBITDA_CUSHION_PREFERENCE_WEIGHT
      objective_tolerance_ratio = _safe_float(
        objective_policy.get("option_objective_tolerance_ratio"),
      ) or OPTION_OBJECTIVE_TOLERANCE_RATIO
      objective_tolerance_abs = _safe_float(
        objective_policy.get("option_objective_tolerance_abs"),
      ) or OPTION_OBJECTIVE_TOLERANCE_ABS
    constraint_profile = state_model.get("constraint_profile")
    if isinstance(constraint_profile, dict):
      active_violations = [
        str(code or "").strip()
        for code in (constraint_profile.get("constraint_engine_violations") or [])
        if str(code or "").strip()
      ]
    fixed_facts = state_model.get("fixed_facts")
    if isinstance(fixed_facts, dict):
      sales_modality = str(fixed_facts.get("sales_modality") or "").strip().lower()
      capacity_driver = str(fixed_facts.get("capacity_driver") or "").strip().lower()
  if not base_weights:
    base_weights = {
      "price_up": PRICE_DISTORTION_WEIGHT,
      "price_down": PRICE_DOWN_DISTORTION_WEIGHT,
      "util_up": UTILIZATION_DISTORTION_WEIGHT,
      "util_down": UTILIZATION_DOWN_DISTORTION_WEIGHT,
      "marketing_up": MARKETING_UP_DISTORTION_WEIGHT,
      "marketing_down": MARKETING_DOWN_DISTORTION_WEIGHT,
      "other_opex_down": OTHER_OPEX_DISTORTION_WEIGHT,
      "other_opex_up": OTHER_OPEX_UP_DISTORTION_WEIGHT,
      "cogs_down": COGS_DOWN_DISTORTION_WEIGHT,
      "cogs_up": COGS_UP_DISTORTION_WEIGHT,
      "hire_delay": HIRE_DELAY_DISTORTION_WEIGHT,
      "hire_advance": HIRE_ADVANCE_DISTORTION_WEIGHT,
      "payroll_down": PAYROLL_DOWN_DISTORTION_WEIGHT,
      "payroll_up": PAYROLL_UP_DISTORTION_WEIGHT,
    }
  if sales_modality in {"local_service", "project_based"} and capacity_driver == "labor":
    base_weights["marketing_up"] = _safe_float(base_weights.get("marketing_up")) * 1.85
    base_weights["marketing_down"] = _safe_float(base_weights.get("marketing_down")) * 0.7
  if "marketing_too_high" in active_violations:
    base_weights["marketing_up"] = _safe_float(base_weights.get("marketing_up")) * 2.2
    base_weights["marketing_down"] = _safe_float(base_weights.get("marketing_down")) * 0.6
  if "marketing_too_low" in active_violations:
    base_weights["marketing_up"] = _safe_float(base_weights.get("marketing_up")) * 0.75

  def profile_with(
    profile_id: str,
    overrides: Dict[str, float],
    *,
    constraints: Optional[Dict[str, float]] = None,
    anchor_strict: bool = False,
  ) -> Dict[str, Any]:
    archetype_meta = _scenario_archetype_meta(profile_id)
    weights = dict(base_weights)
    for key, factor in overrides.items():
      weights[key] = _safe_float(weights.get(key)) * _safe_float(factor)
    return {
      "profile_id": profile_id,
      "archetype": archetype_meta["archetype"],
      "archetype_display": archetype_meta["display"],
      "dominant_tradeoff": archetype_meta["tradeoff"],
      "weights": weights,
      "constraints": dict(constraints or {}),
      "family_concentration_weight": family_concentration_weight,
      "ebitda_cushion_preference_weight": ebitda_cushion_preference_weight,
      "objective_tolerance_ratio": objective_tolerance_ratio,
      "objective_tolerance_abs": objective_tolerance_abs,
      "anchor_strict": bool(anchor_strict),
    }

  profiles = [
    profile_with("balanced", {}, anchor_strict=True),
    profile_with(
      "growth_first",
      {
        "marketing_up": 0.55,
        "util_up": 0.65,
        "marketing_down": 1.5,
        "other_opex_down": 1.15,
        "hire_delay": 1.35,
        "payroll_down": 1.35,
      },
      constraints={
        "marketing_min_ratio": 0.95,
      },
    ),
    profile_with(
      "profit_first",
      {
        "marketing_up": 1.15,
        "util_up": 1.1,
        "marketing_down": 0.8,
        "other_opex_down": 0.7,
        "other_opex_up": 0.75,
        "cogs_up": 0.7,
        "hire_delay": 0.9,
        "payroll_down": 0.7,
        "payroll_up": 0.8,
      },
      constraints={
        "marketing_max_ratio": 1.05,
      },
    ),
    profile_with(
      "operations_first",
      {
        "price_up": 1.5,
        "price_down": 1.8,
        "util_up": 0.9,
        "marketing_up": 0.95,
        "marketing_down": 1.15,
        "other_opex_up": 0.65,
        "other_opex_down": 1.2,
        "cogs_up": 0.6,
        "cogs_down": 1.2,
        "hire_advance": 0.55,
        "hire_delay": 1.4,
        "payroll_up": 0.55,
        "payroll_down": 1.4,
      },
      constraints={
        "marketing_min_ratio": 0.9,
      },
    ),
    profile_with(
      "lean_survival",
      {
        "marketing_up": 1.6,
        "util_up": 1.25,
        "marketing_down": 0.7,
        "other_opex_down": 0.7,
        "hire_delay": 0.65,
        "payroll_down": 0.6,
      },
      constraints={
        "marketing_max_ratio": 1.0,
      },
    ),
  ]

  if "payroll_too_light" in active_violations:
    profiles.insert(
      1,
      profile_with(
        "labor_support_first",
        {
          "price_up": 1.5,
          "util_up": 1.8,
          "util_down": 0.5,
          "marketing_up": 1.5,
          "marketing_down": 0.45,
          "other_opex_down": 0.75,
          "other_opex_up": 1.2,
          "cogs_down": 0.9,
          "cogs_up": 1.1,
          "hire_advance": 0.5,
          "hire_delay": 1.6,
          "payroll_up": 0.45,
          "payroll_down": 1.6,
        },
        constraints={
          "marketing_max_ratio": 0.95,
          "utilization_max_ratio": 0.92,
          "payroll_down_max_ratio": 0.05,
          "hire_delay_max_months_total": 1.0,
        },
      ),
    )

  return profiles


def _build_direct_solver_inputs(
  *,
  state_model: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
  fixed_facts = state_model.get("fixed_facts") if isinstance(state_model, dict) else {}
  controllable = state_model.get("controllable_drivers") if isinstance(state_model, dict) else {}
  constraint_profile = state_model.get("constraint_profile") if isinstance(state_model, dict) else {}
  people_drivers = (controllable or {}).get("people") if isinstance(controllable, dict) else {}
  price_envelope = (constraint_profile or {}).get("price_envelope") if isinstance(constraint_profile, dict) else {}
  util_envelope = (constraint_profile or {}).get("utilization_envelope") if isinstance(constraint_profile, dict) else {}
  marketing_envelope = (constraint_profile or {}).get("marketing_envelope") if isinstance(constraint_profile, dict) else {}
  other_opex_envelope = (constraint_profile or {}).get("other_opex_envelope") if isinstance(constraint_profile, dict) else {}
  capacity_curve = (constraint_profile or {}).get("capacity_curve") if isinstance(constraint_profile, dict) else {}
  demand_curve = (constraint_profile or {}).get("demand_curve") if isinstance(constraint_profile, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}

  current_price = _safe_float((price_envelope or {}).get("baseline"))
  current_util = _normalize_ratio((util_envelope or {}).get("baseline"))
  if current_price <= 0 or current_util is None or current_util <= 0:
    return None

  baseline_units = max(0.0, _safe_float((fixed_facts or {}).get("baseline_units_year1")))
  if baseline_units <= 0:
    return None

  capacity_units = max(
    0.0,
    _safe_float((fixed_facts or {}).get("physical_capacity_units_year1"))
    or _safe_float((fixed_facts or {}).get("supported_capacity_units_year1")),
  )
  fixed_people_payroll = 0.0
  for person in (fixed_facts or {}).get("current_staff") or []:
    if not isinstance(person, dict):
      continue
    fixed_people_payroll += max(0.0, _safe_float(person.get("annual_wage")))

  roles = (people_drivers or {}).get("inferred_roles") if isinstance(people_drivers, dict) else []
  roles = roles if isinstance(roles, list) else []
  baseline_planned_payroll = sum(_safe_float(role.get("baseline_year1_amount")) for role in roles)
  baseline_payroll_support = max(
    fixed_people_payroll + baseline_planned_payroll,
    _safe_float((capacity_curve or {}).get("baseline_payroll_support")),
  )
  constraint_engine_state = (fixed_facts or {}).get("constraint_engine_state") if isinstance(fixed_facts, dict) else {}
  constraint_engine_state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  current_metrics = (constraint_engine_state or {}).get("current_metrics") if isinstance(constraint_engine_state, dict) else {}
  current_metrics = current_metrics if isinstance(current_metrics, dict) else {}
  active_violations = [
    str(code or "").strip()
    for code in ((constraint_profile or {}).get("constraint_engine_violations") or [])
    if str(code or "").strip()
  ]
  payroll_band = constraint_engine_state.get("payroll_intensity_band") if isinstance(constraint_engine_state, dict) else {}
  payroll_ratio_min = max(0.0, _safe_float((payroll_band or {}).get("min")))
  payroll_ratio_max = max(payroll_ratio_min, _safe_float((payroll_band or {}).get("max")) or payroll_ratio_min)
  current_revenue_amount = max(0.0, _safe_float((constraint_profile or {}).get("current_revenue")))
  max_planned_payroll = sum(max(0.0, _safe_float(role.get("wage_ceiling"))) for role in roles if isinstance(role, dict))
  max_payroll_total = fixed_people_payroll + max_planned_payroll
  people_payroll_floor = max(
    fixed_people_payroll,
    _safe_float((current_metrics or {}).get("people_payroll_floor")),
    _safe_float(((constraint_profile or {}).get("payroll_structural") or {}).get("people_payroll_floor")),
  )
  structural_payroll_floor = max(
    people_payroll_floor,
    _safe_float((current_metrics or {}).get("structural_payroll_floor")),
    _safe_float(((constraint_profile or {}).get("payroll_structural") or {}).get("structural_payroll_floor")),
  )
  structural_payroll_base = people_payroll_floor
  workload_payroll_per_unit = 0.0
  if baseline_units > 0 and structural_payroll_floor > structural_payroll_base:
    workload_payroll_per_unit = (structural_payroll_floor - structural_payroll_base) / max(baseline_units, 1e-9)
  ratio_floor_total = (current_revenue_amount * payroll_ratio_min) if payroll_ratio_min > 0 else 0.0
  target_payroll_min_total = max(ratio_floor_total, structural_payroll_base)
  target_payroll_max_total = max(
    fixed_people_payroll + baseline_planned_payroll,
    min(max_payroll_total if max_payroll_total > 0 else (current_revenue_amount * payroll_ratio_max), current_revenue_amount * payroll_ratio_max if payroll_ratio_max > 0 else max_payroll_total),
  )
  target_payroll_max_total = max(target_payroll_min_total, target_payroll_max_total)
  units_min = max(0.0, _safe_float((capacity_curve or {}).get("hard_units_min")))
  units_max = max(
    baseline_units,
    _safe_float((capacity_curve or {}).get("hard_units_max")) or _safe_float((fixed_facts or {}).get("supported_capacity_units_year1")),
  )
  marketing_support_units_min = min(
    max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1"))),
    max(0.0, _safe_float((demand_curve or {}).get("baseline_supported_units")) or units_max),
  )
  marketing_support_units_max = max(
    max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1"))),
    max(0.0, _safe_float((demand_curve or {}).get("baseline_supported_units")) or units_max),
  )

  return {
    "solve_mode": str(state_model.get("solve_mode") or "parent_fallback") if isinstance(state_model, dict) else "parent_fallback",
    "current_price": current_price,
    "price_enabled": bool((price_envelope or {}).get("enabled")),
    "current_util": current_util,
    "util_min": _normalize_ratio((util_envelope or {}).get("min")) or current_util,
    "util_max": _normalize_ratio((util_envelope or {}).get("max")) or current_util,
    "baseline_units": baseline_units,
    "capacity_units": capacity_units,
    "units_min": units_min,
    "units_max": units_max,
    "current_marketing": max(0.0, _safe_float((marketing_envelope or {}).get("baseline"))),
    "marketing_min": max(0.0, _safe_float((marketing_envelope or {}).get("min"))),
    "marketing_upper": max(0.0, _safe_float((marketing_envelope or {}).get("max")) or _safe_float((marketing_envelope or {}).get("baseline"))),
    "marketing_support_units_baseline": max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1"))),
    "marketing_support_units_min": marketing_support_units_min,
    "marketing_support_units_max": max(
      marketing_support_units_max,
      max(
        0.0,
        _safe_float((demand_curve or {}).get("units_per_marketing_dollar")) * max(0.0, _safe_float((marketing_envelope or {}).get("max"))),
      ),
    ),
    "marketing_units_per_dollar": max(0.0, _safe_float((demand_curve or {}).get("units_per_marketing_dollar"))),
    "current_other_opex": max(0.0, _safe_float((other_opex_envelope or {}).get("baseline"))),
    "other_opex_min": max(0.0, _safe_float((other_opex_envelope or {}).get("min"))),
    "other_opex_max": max(0.0, _safe_float((other_opex_envelope or {}).get("max")) or _safe_float((other_opex_envelope or {}).get("baseline"))),
    "other_opex_enabled": bool((other_opex_envelope or {}).get("enabled")),
    "payroll_ratio_min": max(0.0, _safe_float((constraint_profile.get("constraint_engine_state") or {}).get("payroll_intensity_band", {}).get("min")) if isinstance(constraint_profile, dict) else 0.0),
    "payroll_ratio_max": max(0.0, _safe_float((constraint_profile.get("constraint_engine_state") or {}).get("payroll_intensity_band", {}).get("max")) if isinstance(constraint_profile, dict) else 0.0),
    "opex_ratio_min": max(0.0, _safe_float((constraint_profile.get("constraint_engine_state") or {}).get("opex_intensity_band", {}).get("min")) if isinstance(constraint_profile, dict) else 0.0),
    "opex_ratio_max": max(0.0, _safe_float((constraint_profile.get("constraint_engine_state") or {}).get("opex_intensity_band", {}).get("max")) if isinstance(constraint_profile, dict) else 0.0),
    "fixed_people_payroll": fixed_people_payroll,
    "baseline_planned_payroll": baseline_planned_payroll,
    "baseline_payroll_support": baseline_payroll_support,
    "payroll_ratio_min": payroll_ratio_min,
    "payroll_ratio_max": payroll_ratio_max,
    "target_payroll_min_total": max(0.0, target_payroll_min_total),
    "target_payroll_max_total": max(0.0, target_payroll_max_total),
    "people_payroll_floor": max(0.0, people_payroll_floor),
    "structural_payroll_floor": max(0.0, structural_payroll_floor),
    "structural_payroll_base": max(0.0, structural_payroll_base),
    "workload_payroll_per_unit": max(0.0, workload_payroll_per_unit),
    "required_fte_from_workload": max(
      0.0,
      _safe_float((current_metrics or {}).get("required_fte_from_workload"))
      or _safe_float(((constraint_profile or {}).get("payroll_structural") or {}).get("required_fte_from_workload")),
    ),
    "fte_equivalent_year1": max(
      0.0,
      _safe_float((current_metrics or {}).get("fte_equivalent_year1"))
      or _safe_float(((constraint_profile or {}).get("payroll_structural") or {}).get("fte_equivalent_year1")),
    ),
    "active_role_months_year1": max(
      0.0,
      _safe_float((current_metrics or {}).get("active_role_months_year1"))
      or _safe_float(((constraint_profile or {}).get("payroll_structural") or {}).get("active_role_months_year1")),
    ),
    "constraint_violations": active_violations,
    "roles": roles,
    "constraint_profile": constraint_profile,
    "expected_units": max(0.0, _safe_float((demand_curve or {}).get("baseline_supported_units"))),
    "required_units_semantic": (constraint_profile or {}).get("required_units_semantic"),
    "staffing_supported_capacity_semantic": (capacity_curve or {}).get("semantic"),
    "demand_supported_units_semantic": (demand_curve or {}).get("semantic"),
    "reachable_market_semantic": _constraint_source_value(
      (fixed_facts or {}).get("constraint_basis") if isinstance(fixed_facts, dict) else {},
      "reachable_market",
    ),
    "current_revenue": max(0.0, _safe_float((constraint_profile or {}).get("current_revenue"))),
    "current_cogs": max(0.0, _safe_float((constraint_profile or {}).get("current_cogs"))),
    "current_interest": max(0.0, _safe_float((constraint_profile or {}).get("current_interest"))),
    "current_other_opex_total": max(
      0.0,
      _safe_float((constraint_profile or {}).get("current_other_opex_total") or (state_model.get("derived_outputs") or {}).get("other_opex_total_year1")),
    ),
    "rent_annualized": max(0.0, _safe_float((constraint_profile or {}).get("rent_annualized"))),
    "price_upper": max(current_price, _safe_float((price_envelope or {}).get("max"))),
    "price_lower": max(0.0, _safe_float((price_envelope or {}).get("min")) or current_price),
    "current_cogs_ratio": _safe_float(((constraint_profile or {}).get("cogs_envelope") or {}).get("baseline_ratio")),
    "cogs_ratio_min": max(0.0, _safe_float(((constraint_profile or {}).get("cogs_envelope") or {}).get("min_ratio"))),
    "cogs_ratio_max": max(0.0, _safe_float(((constraint_profile or {}).get("cogs_envelope") or {}).get("max_ratio"))),
    "product_driver_basis": _clone((fixed_facts or {}).get("product_driver_basis") or []),
  }


def _build_blocking_solver_state(
  *,
  baseline_summary: Dict[str, Any],
  state_model: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_realism_distance: float,
  blocking_reason: str,
) -> Dict[str, Any]:
  return {
    "status": "blocking_unresolved",
    "solve_mode": str(state_model.get("solve_mode") or "parent_fallback") if isinstance(state_model, dict) else "parent_fallback",
    "target_metric": "year1_realism",
    "search_mode": "direct_pulp",
    "blocking_reason": blocking_reason,
    "blocking_violations": _blocking_constraint_violations(constraint_engine_state),
    "baseline_summary": baseline_summary,
    "baseline_loss_pct": _loss_pct(baseline_summary),
    "baseline_table_markdown": build_consistency_financial_table(baseline_summary),
    "state_model": state_model,
    "constraint_engine_state": _clone(constraint_engine_state or {}),
    "baseline_realism_distance": baseline_realism_distance,
    "structural_gap": True,
    "scenarios": [],
  }


def _label_and_rationale_from_patches(
  exact_patches: Dict[str, Any],
  *,
  archetype: str = "operations",
  archetype_display: Optional[str] = None,
  dominant_tradeoff: Optional[str] = None,
) -> Tuple[str, str, List[str]]:
  label_parts: List[str] = []
  rationale_parts: List[str] = []
  families: List[str] = []

  year1_patch = exact_patches.get("financials_year1_patch")
  if isinstance(year1_patch, dict):
    product_overrides = year1_patch.get("product_overrides")
    if isinstance(product_overrides, dict) and product_overrides:
      saw_price = any(isinstance(override, dict) and override.get("unit_price") is not None for override in product_overrides.values())
      saw_util = any(
        isinstance(override, dict)
        and (override.get("utilization_rate") is not None or override.get("avg_units_per_period_year1") is not None)
        for override in product_overrides.values()
      )
      if saw_price:
        families.append("price")
        label_parts.append(f"Reset product pricing across {len(product_overrides)} product(s)")
        rationale_parts.append("rebalance product-level pricing within the realism envelope")
      if saw_util:
        families.append("utilization")
        label_parts.append(f"Reset product volume and utilization across {len(product_overrides)} product(s)")
        rationale_parts.append("rebalance product-level demand and capacity usage")
    if year1_patch.get("unit_price") is not None:
      families.append("price")
      label_parts.append(f"Set price to {_format_currency(year1_patch.get('unit_price'))}")
      rationale_parts.append("reset pricing")
    if year1_patch.get("utilization_rate") is not None:
      families.append("utilization")
      label_parts.append(f"Set utilization to {_format_percent(year1_patch.get('utilization_rate'))}")
      rationale_parts.append("reset utilization to a more supportable level")

  financials_patch = exact_patches.get("financials_patch")
  if isinstance(financials_patch, dict):
    if financials_patch.get("marketing_total_year1") is not None:
      target = _safe_float(financials_patch.get("marketing_total_year1"))
      families.append("marketing")
      label_parts.append(f"Set Year-1 marketing to {_format_currency(target)}")
      rationale_parts.append("reset the Year-1 marketing ramp")
    if financials_patch.get("other_operating_expense") is not None:
      target = _safe_float(financials_patch.get("other_operating_expense"))
      families.append("other_opex")
      label_parts.append(f"Set other operating expense to {_format_currency(target)}")
      rationale_parts.append("reset non-rent operating spend")
    if financials_patch.get("cogs_total_year1") is not None:
      target = _safe_float(financials_patch.get("cogs_total_year1"))
      families.append("cogs")
      label_parts.append(f"Set Year-1 COGS to {_format_currency(target)}")
      rationale_parts.append("reset direct cost assumptions to fit the realism band")
  marketing_model_patch = exact_patches.get("marketing_model_patch")
  if isinstance(marketing_model_patch, dict):
    expected_units = _safe_float(marketing_model_patch.get("expected_units_year1"))
    if expected_units > 0:
      families.append("marketing")
      label_parts.append(f"Reset marketing support to {expected_units:,.0f} Year-1 units")
      rationale_parts.append("rebuild the marketing support level behind Year-1 demand")

  role_updates = exact_patches.get("people_role_updates")
  if isinstance(role_updates, list):
    for update in role_updates:
      if not isinstance(update, dict):
        continue
      role_title = str(update.get("role_title") or "").strip()
      months = _safe_int(update.get("months_until_hire"))
      if not role_title or months is None:
        continue
      families.append("hire_delay")
      label_parts.append(f"Set {role_title} timing to month {months}")
      rationale_parts.append(f"reset {role_title} timing in Year 1")
      if update.get("annual_wage") is not None and _safe_float(update.get("annual_wage")) > 0:
        families.append("payroll")
        label_parts.append(f"Set {role_title} pay to {_format_currency(update.get('annual_wage'))}/year")
        rationale_parts.append(f"reset {role_title} pay for Year 1")

  marketing_mentions = len([family for family in families if family == "marketing"])
  if marketing_mentions > 0 and len(set(families)) <= 2:
    label_parts.insert(0, "Marketing-heavy path")
    rationale_parts.append("leans more heavily on marketing than the other repair paths")
  display_name = str(archetype_display or "").strip() or _scenario_archetype_meta(archetype).get("display") or "Operational balance"
  strategic_tradeoff = str(dominant_tradeoff or "").strip() or _dominant_tradeoff(families, archetype)
  label = " + ".join(label_parts)
  if label:
    label = f"{display_name}: {label}"
  else:
    label = display_name
  rationale = "This path " + ", ".join(rationale_parts) + f", and {strategic_tradeoff}."
  if not label:
    label = "Keep the current plan"
  if not rationale_parts:
    rationale = f"This path {strategic_tradeoff}."
  return label, rationale, list(dict.fromkeys(families))


def _build_candidate_from_exact_patches(
  *,
  scenario_id: str,
  baseline_summary: Dict[str, Any],
  baseline_state: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  exact_patches: Dict[str, Any],
  archetype: str = "operations",
  archetype_display: Optional[str] = None,
  dominant_tradeoff: Optional[str] = None,
  constraint_engine_state: Optional[Dict[str, Any]] = None,
  baseline_realism_distance: Optional[float] = None,
  target_ebitda_min: Optional[float] = None,
  target_ebitda_max: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
  label, rationale, families = _label_and_rationale_from_patches(
    exact_patches,
    archetype=archetype,
    archetype_display=archetype_display,
    dominant_tradeoff=dominant_tradeoff,
  )
  candidate = _build_candidate(
    scenario_id=scenario_id,
    baseline_summary=baseline_summary,
    baseline_state=baseline_state,
    marketing_model_json=marketing_model_json,
    label=label,
    rationale=rationale,
    lever_families=families,
    exact_patches=exact_patches,
    constraint_engine_state=constraint_engine_state,
    baseline_realism_distance=baseline_realism_distance,
    target_ebitda_min=target_ebitda_min,
    target_ebitda_max=target_ebitda_max,
  )
  if isinstance(candidate, dict):
    candidate["archetype"] = str(archetype or "operations")
    candidate["archetype_display"] = str(archetype_display or "").strip() or _scenario_archetype_meta(archetype).get("display") or "Operational balance"
    candidate["dominant_tradeoff"] = str(dominant_tradeoff or "").strip() or _dominant_tradeoff(families, archetype)
  return candidate


def _archetype_preference_objective(
  *,
  profile_id: str,
  max_family_move: Any,
  price_up_move: Any,
  price_down_move: Any,
  util_move: Any,
  marketing_up_move: Any,
  marketing_down_move: Any,
  opex_down_move: Any,
  cogs_move: Any,
  hire_delay_move: Any,
  payroll_down_move: Any,
  ebitda_expr: Any,
  revenue_scale: float,
):
  normalized_ebitda = ebitda_expr / max(revenue_scale, 1.0)
  if profile_id == "growth_first":
    return (
      1.0 * max_family_move
      - 1.25 * util_move
      - 1.15 * marketing_up_move
      - 0.45 * cogs_move
      + 0.85 * marketing_down_move
      + 0.75 * hire_delay_move
      + 0.75 * payroll_down_move
      + 0.35 * opex_down_move
      + 0.25 * price_down_move
      - 0.35 * normalized_ebitda
    )
  if profile_id == "profit_first":
    return (
      0.95 * max_family_move
      - 0.95 * payroll_down_move
      - 0.8 * opex_down_move
      - 0.7 * cogs_move
      - 0.45 * marketing_down_move
      + 0.85 * marketing_up_move
      + 0.35 * util_move
      + 0.25 * price_up_move
      + 0.3 * hire_delay_move
      - 0.5 * normalized_ebitda
    )
  if profile_id == "lean_survival":
    return (
      0.9 * max_family_move
      - 1.0 * hire_delay_move
      - 0.95 * payroll_down_move
      - 0.65 * marketing_down_move
      - 0.35 * opex_down_move
      - 0.45 * cogs_move
      + 1.0 * marketing_up_move
      + 0.55 * util_move
      - 0.25 * normalized_ebitda
    )
  return (
    1.15 * max_family_move
    - 0.45 * util_move
    - 0.4 * marketing_up_move
    - 0.35 * payroll_down_move
    - 0.3 * hire_delay_move
    - 0.2 * opex_down_move
    - 0.35 * cogs_move
    + 0.15 * (price_up_move + price_down_move)
    - 0.3 * normalized_ebitda
  )


def _solve_direct_profile(
  *,
  profile: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  target_ebitda_min: Optional[float],
  target_ebitda_max: Optional[float] = None,
  family_caps: Optional[Dict[str, float]] = None,
  enforce_blocking_bands: bool = False,
):
  pulp = _require_pulp()
  problem = pulp.LpProblem(f"consistency_solver_{profile.get('profile_id')}", pulp.LpMinimize)
  weights = profile.get("weights") if isinstance(profile, dict) else {}
  weights = weights if isinstance(weights, dict) else {}
  profile_constraints = profile.get("constraints") if isinstance(profile, dict) else {}
  profile_constraints = profile_constraints if isinstance(profile_constraints, dict) else {}
  family_concentration_weight = (
    _safe_float(profile.get("family_concentration_weight"))
    if isinstance(profile, dict)
    else 0.0
  )
  ebitda_cushion_preference_weight = (
    _safe_float(profile.get("ebitda_cushion_preference_weight"))
    if isinstance(profile, dict)
    else 0.0
  )
  objective_tolerance_ratio = (
    max(0.0, _safe_float(profile.get("objective_tolerance_ratio")))
    if isinstance(profile, dict)
    else 0.0
  )
  objective_tolerance_abs = (
    max(0.0, _safe_float(profile.get("objective_tolerance_abs")))
    if isinstance(profile, dict)
    else 0.0
  )
  anchor_strict = bool(profile.get("anchor_strict")) if isinstance(profile, dict) else False

  current_price = _safe_float(direct_inputs.get("current_price"))
  price_enabled = bool(direct_inputs.get("price_enabled"))
  price_lower = max(0.0, _safe_float(direct_inputs.get("price_lower")) or current_price)
  price_upper = max(0.0, _safe_float(direct_inputs.get("price_upper")) or current_price)
  current_util = _normalize_ratio(direct_inputs.get("current_util")) or 0.0
  util_min = min(current_util, _normalize_ratio(direct_inputs.get("util_min")) or current_util)
  util_max = max(util_min, _normalize_ratio(direct_inputs.get("util_max")) or current_util)
  current_marketing = max(0.0, _safe_float(direct_inputs.get("current_marketing")))
  marketing_min = max(0.0, _safe_float(direct_inputs.get("marketing_min")))
  marketing_upper = max(marketing_min, _safe_float(direct_inputs.get("marketing_upper")) or current_marketing)
  marketing_support_units_baseline = max(0.0, _safe_float(direct_inputs.get("marketing_support_units_baseline")))
  marketing_support_units_min = min(
    marketing_support_units_baseline,
    max(0.0, _safe_float(direct_inputs.get("marketing_support_units_min"))),
  )
  marketing_support_units_max = max(marketing_support_units_baseline, _safe_float(direct_inputs.get("marketing_support_units_max")))
  marketing_units_per_dollar = max(0.0, _safe_float(direct_inputs.get("marketing_units_per_dollar")))
  current_other_opex = max(0.0, _safe_float(direct_inputs.get("current_other_opex")))
  other_opex_min = max(0.0, _safe_float(direct_inputs.get("other_opex_min")))
  other_opex_max = max(other_opex_min, _safe_float(direct_inputs.get("other_opex_max")) or current_other_opex)
  other_opex_enabled = bool(direct_inputs.get("other_opex_enabled"))
  payroll_ratio_min = max(0.0, _safe_float(direct_inputs.get("payroll_ratio_min")))
  payroll_ratio_max = max(payroll_ratio_min, _safe_float(direct_inputs.get("payroll_ratio_max")) or payroll_ratio_min)
  opex_ratio_min = max(0.0, _safe_float(direct_inputs.get("opex_ratio_min")))
  opex_ratio_max = max(opex_ratio_min, _safe_float(direct_inputs.get("opex_ratio_max")) or opex_ratio_min)
  current_cogs = max(0.0, _safe_float(direct_inputs.get("current_cogs")))
  current_cogs_ratio = max(0.0, _safe_float(direct_inputs.get("current_cogs_ratio")))
  cogs_ratio_min = max(0.0, _safe_float(direct_inputs.get("cogs_ratio_min")))
  cogs_ratio_max = max(cogs_ratio_min, _safe_float(direct_inputs.get("cogs_ratio_max")) or current_cogs_ratio)
  current_interest = max(0.0, _safe_float(direct_inputs.get("current_interest")))
  rent_annualized = max(0.0, _safe_float(direct_inputs.get("rent_annualized")))
  capacity_units = max(0.0, _safe_float(direct_inputs.get("capacity_units")))
  units_min = max(0.0, _safe_float(direct_inputs.get("units_min")))
  units_max = max(units_min, _safe_float(direct_inputs.get("units_max")) or capacity_units)
  expected_units = max(0.0, _safe_float(direct_inputs.get("expected_units")))
  required_units_semantic = direct_inputs.get("required_units_semantic")
  staffing_supported_capacity_semantic = direct_inputs.get("staffing_supported_capacity_semantic")
  demand_supported_units_semantic = direct_inputs.get("demand_supported_units_semantic")
  reachable_market_semantic = direct_inputs.get("reachable_market_semantic")
  constraint_profile = direct_inputs.get("constraint_profile") if isinstance(direct_inputs, dict) else {}
  capacity_curve = (constraint_profile or {}).get("capacity_curve") if isinstance(constraint_profile, dict) else {}
  demand_curve = (constraint_profile or {}).get("demand_curve") if isinstance(constraint_profile, dict) else {}
  fixed_people_payroll = max(0.0, _safe_float(direct_inputs.get("fixed_people_payroll")))
  baseline_payroll_support = max(0.0, _safe_float(direct_inputs.get("baseline_payroll_support")))
  target_payroll_min_total = max(0.0, _safe_float(direct_inputs.get("target_payroll_min_total")))
  target_payroll_max_total = max(target_payroll_min_total, _safe_float(direct_inputs.get("target_payroll_max_total")) or target_payroll_min_total)
  people_payroll_floor = max(0.0, _safe_float(direct_inputs.get("people_payroll_floor")))
  structural_payroll_floor = max(people_payroll_floor, _safe_float(direct_inputs.get("structural_payroll_floor")))
  structural_payroll_base = max(people_payroll_floor, _safe_float(direct_inputs.get("structural_payroll_base")) or people_payroll_floor)
  workload_payroll_per_unit = max(0.0, _safe_float(direct_inputs.get("workload_payroll_per_unit")))
  active_violations = {
    str(code or "").strip()
    for code in (direct_inputs.get("constraint_violations") or [])
    if str(code or "").strip()
  }
  if "payroll_too_light" in active_violations and (workload_payroll_per_unit > 0 or structural_payroll_floor > target_payroll_min_total):
    payroll_ratio_max = 0.0
  roles = direct_inputs.get("roles") if isinstance(direct_inputs, dict) else []
  roles = roles if isinstance(roles, list) else []

  price = pulp.LpVariable("price", lowBound=(current_price if not price_enabled else price_lower), upBound=(current_price if not price_enabled else price_upper), cat="Continuous")
  util = pulp.LpVariable("util", lowBound=util_min, upBound=util_max, cat="Continuous")
  if marketing_units_per_dollar > 0:
    marketing_support_units = pulp.LpVariable(
      "marketing_support_units",
      lowBound=marketing_support_units_min,
      upBound=marketing_support_units_max,
      cat="Continuous",
    )
    marketing_expr = marketing_support_units / marketing_units_per_dollar
  else:
    marketing_support_units = pulp.LpVariable(
      "marketing_support_units",
      lowBound=marketing_support_units_baseline,
      upBound=marketing_support_units_baseline,
      cat="Continuous",
    )
    marketing_expr = current_marketing
  other_opex = pulp.LpVariable(
    "other_opex",
    lowBound=(other_opex_min if other_opex_enabled else current_other_opex),
    upBound=(other_opex_max if other_opex_enabled else current_other_opex),
    cat="Continuous",
  )
  price_util = pulp.LpVariable("price_util", lowBound=0.0, upBound=price_upper * util_max, cat="Continuous")

  # McCormick envelope for z = price * util.
  price_lb = price_lower if price_enabled else current_price
  price_ub = price_upper
  util_lb = util_min
  util_ub = util_max
  problem += price_util >= price_lb * util + util_lb * price - (price_lb * util_lb)
  problem += price_util >= price_ub * util + util_ub * price - (price_ub * util_ub)
  problem += price_util <= price_lb * util + util_ub * price - (price_lb * util_ub)
  problem += price_util <= price_ub * util + util_lb * price - (price_ub * util_lb)

  role_month_vars: Dict[str, Any] = {}
  role_payroll_vars: Dict[str, Any] = {}
  role_wage_meta: Dict[str, Dict[str, float]] = {}
  payroll_terms: List[Any] = []
  total_delay_expr = 0
  total_advance_expr = 0
  total_payroll_down_expr = 0
  total_payroll_up_expr = 0
  for index, role in enumerate(roles):
    role_title = str(role.get("role_title") or "").strip()
    base_months = max(0, min(12, _safe_int(role.get("base_months")) or 0))
    min_months = max(0, min(base_months, _safe_int(role.get("min_months")) if role.get("min_months") is not None else 0))
    max_months = max(base_months, min(12, _safe_int(role.get("max_months")) if role.get("max_months") is not None else 12))
    annual_wage = max(0.0, _safe_float(role.get("annual_wage")))
    wage_floor = max(0.0, _safe_float(role.get("wage_floor")) or annual_wage)
    wage_ceiling = max(wage_floor, _safe_float(role.get("wage_ceiling")) or annual_wage)
    baseline_year1_amount = max(0.0, _safe_float(role.get("baseline_year1_amount")))
    if not role_title or annual_wage <= 0:
      continue
    month_var = pulp.LpVariable(
      f"role_month_{index}",
      lowBound=min_months,
      upBound=max_months,
      cat="Integer",
    )
    payroll_var = pulp.LpVariable(
      f"role_payroll_{index}",
      lowBound=0.0,
      upBound=(wage_ceiling * 12.0 / 12.0),
      cat="Continuous",
    )
    role_month_vars[role_title] = month_var
    role_payroll_vars[role_title] = payroll_var
    role_wage_meta[role_title] = {
      "annual_wage": annual_wage,
      "wage_floor": wage_floor,
      "wage_ceiling": wage_ceiling,
      "baseline_year1_amount": baseline_year1_amount,
      "base_months": float(base_months),
    }
    active_months_expr = 12 - month_var
    problem += payroll_var >= (wage_floor / 12.0) * active_months_expr
    problem += payroll_var <= (wage_ceiling / 12.0) * active_months_expr
    payroll_terms.append(payroll_var)
    delay_var = pulp.LpVariable(f"role_delay_{index}", lowBound=0.0, cat="Continuous")
    advance_var = pulp.LpVariable(f"role_advance_{index}", lowBound=0.0, cat="Continuous")
    problem += month_var - base_months == delay_var - advance_var
    total_delay_expr += delay_var
    total_advance_expr += advance_var
    if baseline_year1_amount > 0:
      payroll_down_var = pulp.LpVariable(f"role_payroll_down_{index}", lowBound=0.0, cat="Continuous")
      payroll_up_var = pulp.LpVariable(f"role_payroll_up_{index}", lowBound=0.0, cat="Continuous")
      problem += baseline_year1_amount - payroll_var == payroll_down_var - payroll_up_var
      total_payroll_down_expr += payroll_down_var / baseline_year1_amount
      total_payroll_up_expr += payroll_up_var / baseline_year1_amount
  role_count = max(len(role_payroll_vars), 1)

  payroll_expr = fixed_people_payroll + pulp.lpSum(payroll_terms)
  payroll_shortfall = pulp.LpVariable("payroll_shortfall", lowBound=0.0, cat="Continuous")
  payroll_excess = pulp.LpVariable("payroll_excess", lowBound=0.0, cat="Continuous")
  if target_payroll_min_total > 0:
    problem += payroll_expr + payroll_shortfall >= target_payroll_min_total
  else:
    problem += payroll_shortfall == 0
  if target_payroll_max_total > 0:
    problem += payroll_expr - payroll_excess <= target_payroll_max_total
  else:
    problem += payroll_excess == 0
  units_expr = capacity_units * util
  revenue_expr = capacity_units * price_util
  revenue_lb = max(0.0, capacity_units * price_lb * util_lb)
  revenue_ub = max(revenue_lb, capacity_units * price_ub * util_ub)
  required_structural_payroll_expr: Any = max(structural_payroll_floor, structural_payroll_base)
  structural_payroll_shortfall = pulp.LpVariable("structural_payroll_shortfall", lowBound=0.0, cat="Continuous")
  if workload_payroll_per_unit > 0:
    required_structural_payroll_expr = structural_payroll_base + (workload_payroll_per_unit * units_expr)
  elif structural_payroll_floor > 0:
    required_structural_payroll_expr = structural_payroll_floor
  if workload_payroll_per_unit > 0 or structural_payroll_floor > 0:
    if enforce_blocking_bands and "payroll_too_light" in active_violations:
      problem += payroll_expr >= required_structural_payroll_expr
      problem += structural_payroll_shortfall == 0
    else:
      problem += payroll_expr + structural_payroll_shortfall >= required_structural_payroll_expr
  else:
    problem += structural_payroll_shortfall == 0
  cogs_ratio = pulp.LpVariable("cogs_ratio", lowBound=cogs_ratio_min, upBound=cogs_ratio_max, cat="Continuous")
  cogs_total = pulp.LpVariable("cogs_total", lowBound=0.0, upBound=max(current_cogs * 2.0, revenue_ub), cat="Continuous")
  problem += cogs_total >= revenue_lb * cogs_ratio + cogs_ratio_min * revenue_expr - (revenue_lb * cogs_ratio_min)
  problem += cogs_total >= revenue_ub * cogs_ratio + cogs_ratio_max * revenue_expr - (revenue_ub * cogs_ratio_max)
  problem += cogs_total <= revenue_lb * cogs_ratio + cogs_ratio_max * revenue_expr - (revenue_lb * cogs_ratio_max)
  problem += cogs_total <= revenue_ub * cogs_ratio + cogs_ratio_min * revenue_expr - (revenue_ub * cogs_ratio_min)
  ebitda_expr = revenue_expr - cogs_total - payroll_expr - marketing_expr - other_opex - rent_annualized
  net_income_expr = ebitda_expr - current_interest
  revenue_scale = max(1.0, _safe_float(direct_inputs.get("current_revenue")) or (capacity_units * max(current_price, 1.0)))
  total_opex_expr = other_opex + rent_annualized

  capacity_basis = str((capacity_curve or {}).get("basis") or "").strip().lower()
  capacity_units_per_role_month = max(0.0, _safe_float((capacity_curve or {}).get("units_per_active_role_month")))
  capacity_units_per_payroll = max(0.0, _safe_float((capacity_curve or {}).get("units_per_payroll_dollar")))
  if bool((capacity_curve or {}).get("enabled")) and capacity_basis == "role_months" and capacity_units_per_role_month > 0:
    fixed_active_role_months = max(0.0, _safe_float((capacity_curve or {}).get("fixed_active_role_months")))
    adjustable_active_role_months_expr = pulp.lpSum(12 - month_var for month_var in role_month_vars.values())
    staffing_supported_units = capacity_units_per_role_month * (fixed_active_role_months + adjustable_active_role_months_expr)
    problem += units_expr <= staffing_supported_units
  elif bool((capacity_curve or {}).get("enabled")) and capacity_units_per_payroll > 0:
    staffing_supported_units = capacity_units_per_payroll * payroll_expr
    problem += units_expr <= staffing_supported_units
  elif bool((capacity_curve or {}).get("enabled")) and capacity_basis == "hard_units":
    hard_units_min = max(0.0, _safe_float((capacity_curve or {}).get("hard_units_min")) or units_min)
    hard_units_max = max(hard_units_min, _safe_float((capacity_curve or {}).get("hard_units_max")) or units_max)
    problem += units_expr >= hard_units_min
    problem += units_expr <= hard_units_max

  if enforce_blocking_bands and payroll_ratio_min > 0:
    problem += payroll_expr >= payroll_ratio_min * revenue_expr
  if enforce_blocking_bands and payroll_ratio_max > 0:
    problem += payroll_expr <= payroll_ratio_max * revenue_expr
  if enforce_blocking_bands and opex_ratio_min > 0:
    problem += total_opex_expr >= opex_ratio_min * revenue_expr
  if enforce_blocking_bands and opex_ratio_max > 0:
    problem += total_opex_expr <= opex_ratio_max * revenue_expr

  demand_units_per_marketing = max(0.0, _safe_float((demand_curve or {}).get("units_per_marketing_dollar")))
  if bool((demand_curve or {}).get("enabled")) and demand_units_per_marketing > 0:
    problem += units_expr <= marketing_support_units
  elif _semantic_values_compatible(required_units_semantic, demand_supported_units_semantic):
    demand_supported_units = _semantic_value_number(demand_supported_units_semantic)
    if demand_supported_units > 0:
      if current_marketing > 0:
        problem += units_expr <= demand_supported_units * (marketing_expr / max(current_marketing, 1e-9))
      else:
        problem += units_expr <= demand_supported_units
  if _semantic_values_compatible(required_units_semantic, reachable_market_semantic):
    reachable_market = _semantic_value_number(reachable_market_semantic)
    if reachable_market > 0:
      problem += units_expr <= reachable_market
  marketing_min_ratio = _safe_float(profile_constraints.get("marketing_min_ratio"))
  if current_marketing > 0 and marketing_min_ratio > 0:
    problem += marketing_expr >= current_marketing * marketing_min_ratio
  marketing_max_ratio = _safe_float(profile_constraints.get("marketing_max_ratio"))
  if current_marketing > 0 and marketing_max_ratio > 0:
    problem += marketing_expr <= current_marketing * marketing_max_ratio
  utilization_max_ratio = _safe_float(profile_constraints.get("utilization_max_ratio"))
  if current_util > 0 and utilization_max_ratio > 0:
    problem += util <= max(util_min, current_util * utilization_max_ratio)
  utilization_min_ratio = _safe_float(profile_constraints.get("utilization_min_ratio"))
  if current_util > 0 and utilization_min_ratio > 0:
    problem += util >= min(util_max, current_util * utilization_min_ratio)
  payroll_down_max_ratio = _safe_float(profile_constraints.get("payroll_down_max_ratio"))
  if payroll_down_max_ratio > 0:
    problem += total_payroll_down_expr <= payroll_down_max_ratio
  hire_delay_max_months_total = _safe_float(profile_constraints.get("hire_delay_max_months_total"))
  if hire_delay_max_months_total > 0:
    problem += total_delay_expr <= hire_delay_max_months_total

  shortfall = None
  target_ebitda_min = None if target_ebitda_min is None else float(target_ebitda_min)
  target_ebitda_max = None if target_ebitda_max is None else float(target_ebitda_max)
  if target_ebitda_min is not None:
    problem += ebitda_expr >= target_ebitda_min
  if target_ebitda_max is not None:
    problem += ebitda_expr <= target_ebitda_max
  else:
    if target_ebitda_min is None:
      shortfall = pulp.LpVariable("ebitda_shortfall", lowBound=0.0, cat="Continuous")
      problem += shortfall >= -ebitda_expr

  marketing_up = pulp.LpVariable("marketing_up", lowBound=0.0, cat="Continuous")
  marketing_down = pulp.LpVariable("marketing_down", lowBound=0.0, cat="Continuous")
  problem += marketing_expr - current_marketing == marketing_up - marketing_down
  price_up = pulp.LpVariable("price_up", lowBound=0.0, cat="Continuous")
  price_down = pulp.LpVariable("price_down", lowBound=0.0, cat="Continuous")
  problem += price - current_price == price_up - price_down
  util_up = pulp.LpVariable("util_up", lowBound=0.0, cat="Continuous")
  util_down = pulp.LpVariable("util_down", lowBound=0.0, cat="Continuous")
  problem += util - current_util == util_up - util_down
  other_opex_up = pulp.LpVariable("other_opex_up", lowBound=0.0, cat="Continuous")
  other_opex_down = pulp.LpVariable("other_opex_down", lowBound=0.0, cat="Continuous")
  problem += other_opex - current_other_opex == other_opex_up - other_opex_down
  cogs_up = pulp.LpVariable("cogs_up", lowBound=0.0, cat="Continuous")
  cogs_down = pulp.LpVariable("cogs_down", lowBound=0.0, cat="Continuous")
  problem += cogs_total - current_cogs == cogs_up - cogs_down

  price_up_move = price_up / max(current_price, 1.0) if price_enabled else 0.0
  price_down_move = price_down / max(current_price, 1.0) if price_enabled else 0.0
  util_up_move = util_up / max(1.0 - current_util, 1e-6)
  util_down_move = util_down / max(current_util or 1.0, 1e-6)
  marketing_up_move = marketing_up / max(marketing_upper or 1.0, 1.0)
  marketing_down_move = marketing_down / max(current_marketing or 1.0, 1.0)
  opex_down_move = other_opex_down / max(current_other_opex or 1.0, 1.0)
  opex_up_move = other_opex_up / max(other_opex_max or 1.0, 1.0)
  cogs_down_move = cogs_down / max(current_cogs or 1.0, 1.0)
  cogs_up_move = cogs_up / max(current_cogs or 1.0, 1.0)
  payroll_down_move = total_payroll_down_expr / float(role_count)
  payroll_up_move = total_payroll_up_expr / float(role_count)
  hire_delay_move = total_delay_expr / (12.0 * float(role_count))
  hire_advance_move = total_advance_expr / (12.0 * float(role_count))
  max_family_move = pulp.LpVariable("max_family_move", lowBound=0.0, cat="Continuous")
  for expr in (
    price_up_move,
    price_down_move,
    util_up_move,
    util_down_move,
    marketing_up_move,
    marketing_down_move,
    opex_down_move,
    opex_up_move,
    cogs_down_move,
    cogs_up_move,
    payroll_down_move,
    payroll_up_move,
    hire_delay_move,
    hire_advance_move,
  ):
    if isinstance(expr, (int, float)):
      continue
    problem += max_family_move >= expr
  family_caps = family_caps if isinstance(family_caps, dict) else {}
  family_exprs = {
    "price_up": price_up_move,
    "price_down": price_down_move,
    "util_up": util_up_move,
    "util_down": util_down_move,
    "marketing_up": marketing_up_move,
    "marketing_down": marketing_down_move,
    "other_opex_down": opex_down_move,
    "other_opex_up": opex_up_move,
    "cogs_down": cogs_down_move,
    "cogs_up": cogs_up_move,
    "hire_delay": hire_delay_move,
    "hire_advance": hire_advance_move,
    "payroll_down": payroll_down_move,
    "payroll_up": payroll_up_move,
  }
  for family_name, family_cap in family_caps.items():
    expr = family_exprs.get(str(family_name))
    if expr is None or isinstance(expr, (int, float)):
      continue
    cap_value = max(0.0, _safe_float(family_cap))
    problem += expr <= cap_value

  distortion_expr = (
    _safe_float(weights.get("price_up")) * price_up_move
    + _safe_float(weights.get("price_down")) * price_down_move
    + _safe_float(weights.get("util_up")) * util_up_move
    + _safe_float(weights.get("util_down")) * util_down_move
    + _safe_float(weights.get("marketing_up")) * (marketing_up / max(marketing_upper or 1.0, 1.0))
    + _safe_float(weights.get("marketing_down")) * (marketing_down / max(current_marketing or 1.0, 1.0))
    + _safe_float(weights.get("other_opex_down")) * opex_down_move
    + _safe_float(weights.get("other_opex_up")) * opex_up_move
    + _safe_float(weights.get("cogs_down")) * cogs_down_move
    + _safe_float(weights.get("cogs_up")) * cogs_up_move
    + _safe_float(weights.get("hire_delay")) * hire_delay_move
    + _safe_float(weights.get("hire_advance")) * hire_advance_move
    + _safe_float(weights.get("payroll_down")) * payroll_down_move
    + _safe_float(weights.get("payroll_up")) * payroll_up_move
    + (6.0 * (payroll_shortfall / revenue_scale))
    + (2.0 * (payroll_excess / revenue_scale))
    + (10.0 * (structural_payroll_shortfall / revenue_scale))
  )
  solver = pulp.PULP_CBC_CMD(msg=False)

  if shortfall is not None:
    problem.setObjective(shortfall)
  else:
    problem.setObjective(max_family_move)
  status = problem.solve(solver)
  if status != pulp.LpStatusOptimal:
    return None

  optimal_shortfall = _lp_value(shortfall, 0.0) if shortfall is not None else 0.0
  if target_ebitda_min is not None or target_ebitda_max is not None:
    optimal_max_family_move = _lp_value(max_family_move, 0.0)
  else:
    problem += shortfall <= (optimal_shortfall + 1e-6)
    problem.setObjective(max_family_move)
    status = problem.solve(solver)
    if status != pulp.LpStatusOptimal:
      return None
    optimal_max_family_move = _lp_value(max_family_move, 0.0)
  problem += max_family_move <= (optimal_max_family_move + 1e-6)

  final_objective = distortion_expr
  if family_concentration_weight > 0:
    final_objective = final_objective + (family_concentration_weight * max_family_move)
  if ebitda_cushion_preference_weight > 0:
    final_objective = final_objective - (
      ebitda_cushion_preference_weight * (ebitda_expr / revenue_scale)
    )
  problem.setObjective(final_objective)
  status = problem.solve(solver)
  if status != pulp.LpStatusOptimal:
    return None
  optimal_final_objective = _lp_value(final_objective, 0.0)

  if not anchor_strict:
    objective_tolerance = max(
      objective_tolerance_abs,
      abs(optimal_final_objective) * objective_tolerance_ratio,
    )
    if objective_tolerance > 0:
      problem += final_objective <= (optimal_final_objective + objective_tolerance)
    archetype_objective = _archetype_preference_objective(
      profile_id=str(profile.get("profile_id") or "").strip(),
      max_family_move=max_family_move,
      price_up_move=price_up_move,
      price_down_move=price_down_move,
      util_move=util_up_move + util_down_move,
      marketing_up_move=marketing_up_move,
      marketing_down_move=marketing_down_move,
      opex_down_move=opex_down_move + opex_up_move,
      cogs_move=cogs_down_move + cogs_up_move,
      hire_delay_move=hire_delay_move + hire_advance_move,
      payroll_down_move=payroll_down_move + payroll_up_move,
      ebitda_expr=ebitda_expr,
      revenue_scale=revenue_scale,
    )
    problem.setObjective(archetype_objective)
    status = problem.solve(solver)
    if status != pulp.LpStatusOptimal:
      return None

  role_month_values = {
    role_title: int(round(_lp_value(month_var, 0.0)))
    for role_title, month_var in role_month_vars.items()
  }
  role_payroll_values = {
    role_title: round(_lp_value(payroll_var, 0.0), 2)
    for role_title, payroll_var in role_payroll_vars.items()
  }
  distortion_components = {
    "price_up": _safe_float(weights.get("price_up")) * max(0.0, _lp_value(price_up, 0.0) / max(current_price, 1.0)),
    "price_down": _safe_float(weights.get("price_down")) * max(0.0, _lp_value(price_down, 0.0) / max(current_price, 1.0)),
    "util_up": _safe_float(weights.get("util_up")) * max(0.0, _lp_value(util_up, 0.0) / max(1.0 - current_util, 1e-6)),
    "util_down": _safe_float(weights.get("util_down")) * max(0.0, _lp_value(util_down, 0.0) / max(current_util or 1.0, 1e-6)),
    "marketing_up": _safe_float(weights.get("marketing_up")) * max(0.0, _lp_value(marketing_up, 0.0) / max(marketing_upper or 1.0, 1.0)),
    "marketing_down": _safe_float(weights.get("marketing_down")) * max(0.0, _lp_value(marketing_down, 0.0) / max(current_marketing or 1.0, 1.0)),
    "other_opex_down": _safe_float(weights.get("other_opex_down")) * max(0.0, _lp_value(other_opex_down, 0.0) / max(current_other_opex or 1.0, 1.0)),
    "other_opex_up": _safe_float(weights.get("other_opex_up")) * max(0.0, _lp_value(other_opex_up, 0.0) / max(other_opex_max or 1.0, 1.0)),
    "cogs_down": _safe_float(weights.get("cogs_down")) * max(0.0, _lp_value(cogs_down, 0.0) / max(current_cogs or 1.0, 1.0)),
    "cogs_up": _safe_float(weights.get("cogs_up")) * max(0.0, _lp_value(cogs_up, 0.0) / max(current_cogs or 1.0, 1.0)),
    "hire_delay": _safe_float(weights.get("hire_delay")) * max(0.0, _lp_value(total_delay_expr, 0.0) / (12.0 * float(role_count))),
    "hire_advance": _safe_float(weights.get("hire_advance")) * max(0.0, _lp_value(total_advance_expr, 0.0) / (12.0 * float(role_count))),
    "payroll_down": _safe_float(weights.get("payroll_down")) * max(0.0, _lp_value(total_payroll_down_expr, 0.0) / float(role_count)),
    "payroll_up": _safe_float(weights.get("payroll_up")) * max(0.0, _lp_value(total_payroll_up_expr, 0.0) / float(role_count)),
    "payroll_shortfall": 6.0 * max(0.0, _lp_value(payroll_shortfall, 0.0) / revenue_scale),
    "payroll_excess": 2.0 * max(0.0, _lp_value(payroll_excess, 0.0) / revenue_scale),
    "structural_payroll_shortfall": 10.0 * max(0.0, _lp_value(structural_payroll_shortfall, 0.0) / revenue_scale),
  }
  family_raw_components = {
    "price_up": max(0.0, _lp_value(price_up, 0.0) / max(current_price, 1.0)) if price_enabled else 0.0,
    "price_down": max(0.0, _lp_value(price_down, 0.0) / max(current_price, 1.0)) if price_enabled else 0.0,
    "util_up": max(0.0, _lp_value(util_up, 0.0) / max(1.0 - current_util, 1e-6)),
    "util_down": max(0.0, _lp_value(util_down, 0.0) / max(current_util or 1.0, 1e-6)),
    "marketing_up": max(0.0, _lp_value(marketing_up, 0.0) / max(marketing_upper or 1.0, 1.0)),
    "marketing_down": max(0.0, _lp_value(marketing_down, 0.0) / max(current_marketing or 1.0, 1.0)),
    "other_opex_down": max(0.0, _lp_value(other_opex_down, 0.0) / max(current_other_opex or 1.0, 1.0)),
    "other_opex_up": max(0.0, _lp_value(other_opex_up, 0.0) / max(other_opex_max or 1.0, 1.0)),
    "cogs_down": max(0.0, _lp_value(cogs_down, 0.0) / max(current_cogs or 1.0, 1.0)),
    "cogs_up": max(0.0, _lp_value(cogs_up, 0.0) / max(current_cogs or 1.0, 1.0)),
    "hire_delay": max(0.0, _lp_value(total_delay_expr, 0.0) / (12.0 * float(role_count))),
    "hire_advance": max(0.0, _lp_value(total_advance_expr, 0.0) / (12.0 * float(role_count))),
    "payroll_down": max(0.0, _lp_value(total_payroll_down_expr, 0.0) / float(role_count)),
    "payroll_up": max(0.0, _lp_value(total_payroll_up_expr, 0.0) / float(role_count)),
    "payroll_shortfall": max(0.0, _lp_value(payroll_shortfall, 0.0) / revenue_scale),
    "payroll_excess": max(0.0, _lp_value(payroll_excess, 0.0) / revenue_scale),
    "structural_payroll_shortfall": max(0.0, _lp_value(structural_payroll_shortfall, 0.0) / revenue_scale),
  }
  return {
    "profile_id": str(profile.get("profile_id") or "").strip() or "profile",
    "archetype": str(profile.get("archetype") or "").strip() or _scenario_archetype_meta(str(profile.get("profile_id") or "")).get("archetype") or "operations",
    "archetype_display": str(profile.get("archetype_display") or "").strip() or _scenario_archetype_meta(str(profile.get("profile_id") or "")).get("display") or "Operational balance",
    "dominant_tradeoff": str(profile.get("dominant_tradeoff") or "").strip() or _scenario_archetype_meta(str(profile.get("profile_id") or "")).get("tradeoff") or "rebalances the Year-1 plan within the realism envelope",
    "target_ebitda_min": target_ebitda_min,
    "target_ebitda_max": target_ebitda_max,
    "threshold_feasible": (target_ebitda_min is not None or target_ebitda_max is not None),
    "anchor_strict": anchor_strict,
    "objective_tolerance_ratio": objective_tolerance_ratio,
    "price": round(_lp_value(price, current_price), 2),
    "utilization_rate": _lp_value(util, current_util),
    "cogs_total_year1": round(_lp_value(cogs_total, current_cogs), 2),
    "cogs_ratio": _lp_value(cogs_ratio, current_cogs_ratio),
    "marketing_total_year1": round(_lp_value(marketing_expr, current_marketing), 2),
    "marketing_support_units_year1": round(_lp_value(marketing_support_units, marketing_support_units_baseline), 2),
    "other_operating_expense": round(_lp_value(other_opex, current_other_opex), 2),
    "other_opex_total_ratio": (_lp_value(total_opex_expr, current_other_opex + rent_annualized) / max(_lp_value(revenue_expr, revenue_scale), 1.0)),
    "role_months": role_month_values,
    "role_year1_payroll": role_payroll_values,
    "role_wage_meta": role_wage_meta,
    "structural_payroll_required_total": round(_lp_value(required_structural_payroll_expr, structural_payroll_floor), 2),
    "structural_payroll_shortfall": round(_lp_value(structural_payroll_shortfall, 0.0), 2),
    "distortion_components": distortion_components,
    "distortion_total": sum(distortion_components.values()),
    "family_raw_components": family_raw_components,
    "max_family_move": _lp_value(max_family_move, 0.0),
    "final_objective_value": _lp_value(final_objective, 0.0),
    "optimal_final_objective": optimal_final_objective,
    "ebitda": _lp_value(ebitda_expr, 0.0),
    "net_income": _lp_value(net_income_expr, 0.0),
    "shortfall": optimal_shortfall,
    "enforce_blocking_bands": bool(enforce_blocking_bands),
  }


def _build_product_overrides_from_targets(
  *,
  product_driver_basis: Sequence[Dict[str, Any]],
  target_price: float,
  target_util: float,
  current_price: float,
  current_util: float,
  target_units_total: float,
) -> Dict[str, Dict[str, Any]]:
  overrides: Dict[str, Dict[str, Any]] = {}
  if not product_driver_basis:
    return overrides
  total_units = sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_driver_basis if isinstance(item, dict))
  total_capacity = sum(max(0.0, _safe_float(item.get("annual_capacity_units"))) for item in product_driver_basis if isinstance(item, dict))
  price_factor = (target_price / max(current_price, 1e-9)) if current_price > 0 else 1.0
  util_factor = (target_util / max(current_util, 1e-9)) if current_util > 0 else 1.0

  for item in product_driver_basis:
    if not isinstance(item, dict):
      continue
    product_key = str(item.get("product_key") or "").strip()
    product_name = str(item.get("product_name") or "").strip()
    if not product_key or not product_name:
      continue
    baseline_price = max(0.0, _safe_float(item.get("unit_price")))
    baseline_periods = max(0.0, _safe_float(item.get("operating_periods_per_year")))
    capacity_per_period = max(0.0, _safe_float(item.get("units_per_period_capacity")))
    baseline_avg_units = max(0.0, _safe_float(item.get("avg_units_per_period_year1")))
    baseline_util = _normalize_ratio(item.get("utilization_rate"))
    annual_capacity_units = max(0.0, _safe_float(item.get("annual_capacity_units")))
    annual_units = max(0.0, _safe_float(item.get("annual_units")))

    units_share = (annual_units / max(total_units, 1e-9)) if total_units > 0 else ((annual_capacity_units / max(total_capacity, 1e-9)) if total_capacity > 0 else 0.0)
    target_product_units = max(0.0, target_units_total * units_share)
    target_product_price = round(max(0.0, baseline_price * price_factor), 2) if baseline_price > 0 else round(target_price, 2)

    if capacity_per_period > 0 and baseline_periods > 0:
      target_avg_units = target_product_units / max(baseline_periods, 1e-9)
      target_product_util = max(0.0, min(1.0, target_avg_units / max(capacity_per_period, 1e-9)))
    else:
      target_product_util = max(0.0, min(1.0, (baseline_util or current_util or target_util or 0.0) * util_factor))
      if capacity_per_period > 0:
        target_avg_units = capacity_per_period * target_product_util
      else:
        target_avg_units = baseline_avg_units * util_factor if baseline_avg_units > 0 else 0.0

    override: Dict[str, Any] = {}
    if target_product_price > 0 and abs(target_product_price - baseline_price) >= 0.01:
      override["unit_price"] = target_product_price
    if abs(target_avg_units - baseline_avg_units) >= 0.01:
      override["avg_units_per_period_year1"] = round(max(0.0, target_avg_units), 4)
    if baseline_util is None or abs(target_product_util - baseline_util) >= 0.0005:
      override["utilization_rate"] = round(target_product_util, 6)
    if override:
      overrides[product_key] = override
  return overrides


def _effective_product_basis_from_patch(
  *,
  product_driver_basis: Sequence[Dict[str, Any]],
  year1_patch: Dict[str, Any],
) -> List[Dict[str, Any]]:
  effective: List[Dict[str, Any]] = []
  patch = year1_patch if isinstance(year1_patch, dict) else {}
  product_overrides = patch.get("product_overrides") if isinstance(patch, dict) else {}
  product_overrides = product_overrides if isinstance(product_overrides, dict) else {}
  for item in product_driver_basis:
    if not isinstance(item, dict):
      continue
    next_item = _clone(item)
    override = product_overrides.get(str(item.get("product_key") or "").strip())
    override = override if isinstance(override, dict) else {}
    unit_price = max(0.0, _safe_float(override.get("unit_price")) or _safe_float(next_item.get("unit_price")))
    periods = max(0.0, _safe_float(next_item.get("operating_periods_per_year")))
    capacity = max(0.0, _safe_float(next_item.get("units_per_period_capacity")))
    avg_units = max(
      0.0,
      _safe_float(override.get("avg_units_per_period_year1"))
      or _safe_float(next_item.get("avg_units_per_period_year1")),
    )
    util = _normalize_ratio(override.get("utilization_rate"))
    if util is not None and capacity > 0:
      avg_units = capacity * util
    elif util is None:
      util = _normalize_ratio(next_item.get("utilization_rate"))
      if util is None and capacity > 0 and avg_units > 0:
        util = max(0.0, min(1.0, avg_units / max(capacity, 1e-9)))
    next_item["unit_price"] = unit_price
    next_item["avg_units_per_period_year1"] = avg_units
    next_item["utilization_rate"] = util
    next_item["annual_units"] = avg_units * periods
    next_item["annual_capacity_units"] = capacity * periods
    next_item["annual_revenue"] = next_item["annual_units"] * unit_price
    effective.append(next_item)
  return effective


def _normalize_child_first_year1_patch(
  *,
  year1_patch: Dict[str, Any],
  direct_inputs: Dict[str, Any],
) -> Dict[str, Any]:
  next_patch = _clone(year1_patch or {})
  if str(direct_inputs.get("solve_mode") or "").strip().lower() != "child_first":
    return next_patch
  product_driver_basis = direct_inputs.get("product_driver_basis")
  product_driver_basis = product_driver_basis if isinstance(product_driver_basis, list) else []
  if not product_driver_basis:
    return next_patch

  effective_basis = _effective_product_basis_from_patch(
    product_driver_basis=product_driver_basis,
    year1_patch=next_patch,
  )
  effective_price = _safe_float(_weighted_product_price(effective_basis) or direct_inputs.get("current_price"))
  effective_util = _normalize_ratio(_weighted_product_utilization(effective_basis) or direct_inputs.get("current_util")) or 0.0
  explicit_target_price = _safe_float(next_patch.get("unit_price"))
  explicit_target_util = _normalize_ratio(next_patch.get("utilization_rate"))
  target_price = explicit_target_price if explicit_target_price > 0 else effective_price
  target_util = explicit_target_util if explicit_target_util is not None else effective_util
  target_units_total = (
    sum(max(0.0, _safe_float(item.get("annual_capacity_units"))) for item in effective_basis) * target_util
    if explicit_target_util is not None
    else sum(max(0.0, _safe_float(item.get("annual_units"))) for item in effective_basis)
  )
  product_overrides = _build_product_overrides_from_targets(
    product_driver_basis=product_driver_basis,
    target_price=target_price,
    target_util=target_util,
    current_price=effective_price,
    current_util=effective_util,
    target_units_total=target_units_total,
  )
  next_patch.pop("unit_price", None)
  next_patch.pop("utilization_rate", None)
  if product_overrides:
    existing = next_patch.get("product_overrides")
    existing = existing if isinstance(existing, dict) else {}
    merged = dict(existing)
    merged.update(product_overrides)
    next_patch["product_overrides"] = merged
  return next_patch


def _exact_patches_from_solution(
  *,
  solution: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  ops_json: Dict[str, Any],
) -> Dict[str, Any]:
  exact_patches: Dict[str, Any] = {}
  financials_year1_patch: Dict[str, Any] = {}
  financials_patch: Dict[str, Any] = {}
  marketing_model_patch: Dict[str, Any] = {}
  people_role_updates: List[Dict[str, Any]] = []

  current_price = _safe_float(direct_inputs.get("current_price"))
  current_util = _normalize_ratio(direct_inputs.get("current_util")) or 0.0
  current_marketing = _safe_float(direct_inputs.get("current_marketing"))
  marketing_support_units_baseline = _safe_float(direct_inputs.get("marketing_support_units_baseline"))
  current_other_opex = _safe_float(direct_inputs.get("current_other_opex"))

  target_price = round(_safe_float(solution.get("price")), 2)
  target_util = _normalize_ratio(solution.get("utilization_rate"))
  product_driver_basis = direct_inputs.get("product_driver_basis") if isinstance(direct_inputs, dict) else []
  product_driver_basis = product_driver_basis if isinstance(product_driver_basis, list) else []
  solve_mode = str(direct_inputs.get("solve_mode") or "parent_fallback").strip().lower()

  target_marketing = round(_safe_float(solution.get("marketing_total_year1")), 2)
  constraint_profile = direct_inputs.get("constraint_profile") if isinstance(direct_inputs, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}
  reachable_market = max(0.0, _safe_float((marketing_children or {}).get("reachable_market")))
  capacity_units = max(0.0, _safe_float(direct_inputs.get("capacity_units")))
  target_units = max(0.0, capacity_units * (target_util or current_util))
  target_support_units = round(_safe_float(solution.get("marketing_support_units_year1")), 2)

  if solve_mode == "child_first" and product_driver_basis:
    product_overrides = _build_product_overrides_from_targets(
      product_driver_basis=product_driver_basis,
      target_price=target_price if target_price > 0 else current_price,
      target_util=target_util if target_util is not None else current_util,
      current_price=current_price,
      current_util=current_util,
      target_units_total=target_units,
    )
    if product_overrides:
      financials_year1_patch["product_overrides"] = product_overrides
  else:
    if target_price > 0 and abs(target_price - current_price) >= 0.01:
      financials_year1_patch["unit_price"] = target_price
    if target_util is not None and abs(target_util - current_util) >= 0.0005:
      financials_year1_patch["utilization_rate"] = target_util

  if reachable_market > 0 and target_units >= 0:
    marketing_model_patch["capture_rate_year1"] = round(target_units / max(reachable_market, 1e-9), 6)
  if target_support_units >= 0 and abs(target_support_units - marketing_support_units_baseline) >= 0.01:
    marketing_model_patch["expected_units_year1"] = target_support_units
  if target_units >= 0:
    marketing_model_patch["required_units_year1"] = round(target_units, 2)
    marketing_model_patch["demand_supports_required_units"] = True
  baseline_expected_customers = max(
    0.0,
    _safe_float((marketing_children or {}).get("baseline_expected_customers_or_clients_year1")),
  )
  baseline_expected_units = max(
    0.0,
    _safe_float((marketing_children or {}).get("baseline_expected_units_year1")),
  )
  if baseline_expected_customers > 0 and baseline_expected_units > 0 and target_support_units >= 0:
    scaled_expected_customers = baseline_expected_customers * (target_support_units / max(baseline_expected_units, 1e-9))
    if reachable_market > 0:
      scaled_expected_customers = min(reachable_market, scaled_expected_customers)
    marketing_model_patch["expected_customers_or_clients_year1"] = round(scaled_expected_customers, 2)

  target_other_opex = round(_safe_float(solution.get("other_operating_expense")), 2)
  if abs(target_other_opex - current_other_opex) >= 0.01:
    financials_patch["other_operating_expense"] = target_other_opex

  current_cogs = _safe_float(direct_inputs.get("current_cogs"))
  target_cogs = round(_safe_float(solution.get("cogs_total_year1")), 2)
  if abs(target_cogs - current_cogs) >= 0.01:
    financials_patch["cogs_total_year1"] = target_cogs
  solver_meta: Dict[str, Any] = {}
  target_cogs_ratio = _safe_float(solution.get("cogs_ratio"))
  if target_cogs_ratio > 0:
    solver_meta["cogs_ratio_target"] = round(target_cogs_ratio, 6)
  target_opex_total_ratio = _safe_float(solution.get("other_opex_total_ratio"))
  if target_opex_total_ratio > 0:
    solver_meta["opex_total_ratio_target"] = round(target_opex_total_ratio, 6)
  marketing_min_total = max(0.0, _safe_float(direct_inputs.get("marketing_min")))
  marketing_max_total = max(marketing_min_total, _safe_float(direct_inputs.get("marketing_upper")))
  solver_meta["marketing_min_total"] = round(marketing_min_total, 2)
  solver_meta["marketing_max_total"] = round(marketing_max_total, 2)

  role_months = solution.get("role_months") if isinstance(solution, dict) else {}
  role_year1_payroll = solution.get("role_year1_payroll") if isinstance(solution, dict) else {}
  role_wage_meta = solution.get("role_wage_meta") if isinstance(solution, dict) else {}
  baseline_roles = {
    str(role.get("role_title") or "").strip(): max(0, min(12, _safe_int(role.get("base_months")) or 0))
    for role in (direct_inputs.get("roles") or [])
    if isinstance(role, dict)
  }
  baseline_role_wages = {
    str(role.get("role_title") or "").strip(): max(0.0, _safe_float(role.get("annual_wage")))
    for role in (direct_inputs.get("roles") or [])
    if isinstance(role, dict)
  }
  max_role_month = 0
  if isinstance(role_months, dict):
    for role_title, months in role_months.items():
      clean_title = str(role_title or "").strip()
      if not clean_title:
        continue
      target_months = max(0, min(12, _safe_int(months) or 0))
      baseline_months = baseline_roles.get(clean_title)
      meta = role_wage_meta.get(clean_title) if isinstance(role_wage_meta, dict) else {}
      target_year1_payroll = _safe_float(role_year1_payroll.get(clean_title)) if isinstance(role_year1_payroll, dict) else 0.0
      active_months = max(0, 12 - target_months)
      implied_wage = None
      if active_months > 0 and target_year1_payroll > 0:
        implied_wage = round((target_year1_payroll * 12.0) / active_months, 2)
      baseline_wage = baseline_role_wages.get(clean_title, 0.0)
      months_changed = baseline_months is not None and target_months != baseline_months
      wage_changed = implied_wage is not None and abs(implied_wage - baseline_wage) >= 0.01
      if baseline_months is None or (not months_changed and not wage_changed):
        continue
      update = {
        "role_title": clean_title,
        "months_until_hire": target_months,
      }
      if wage_changed:
        floor = _safe_float((meta or {}).get("wage_floor"))
        ceiling = _safe_float((meta or {}).get("wage_ceiling"))
        if floor > 0:
          implied_wage = max(floor, implied_wage)
        if ceiling > 0:
          implied_wage = min(ceiling, implied_wage)
        update["annual_wage"] = round(implied_wage, 2)
      people_role_updates.append(update)
      max_role_month = max(max_role_month, target_months)

  if financials_year1_patch:
    exact_patches["financials_year1_patch"] = financials_year1_patch
  if financials_patch:
    exact_patches["financials_patch"] = financials_patch
  if solver_meta:
    exact_patches["solver_meta"] = solver_meta
  if marketing_model_patch:
    exact_patches["marketing_model_patch"] = marketing_model_patch
  if people_role_updates:
    exact_patches["people_role_updates"] = people_role_updates
  if max_role_month > 0:
    milestone_updates = _attach_milestone_updates_for_delay(
      ops_json=ops_json,
      minimum_months=max_role_month,
    )
    if milestone_updates:
      exact_patches["milestone_updates"] = milestone_updates
  return exact_patches


def _family_cap_variants(candidate: Dict[str, Any]) -> List[Dict[str, float]]:
  raw = candidate.get("family_raw_components") if isinstance(candidate, dict) else {}
  raw = raw if isinstance(raw, dict) else {}
  ranked = [
    (str(name), max(0.0, _safe_float(value)))
    for name, value in raw.items()
    if max(0.0, _safe_float(value)) > 0.05
  ]
  ranked.sort(key=lambda item: item[1], reverse=True)
  variants: List[Dict[str, float]] = []
  for family_name, family_value in ranked[:3]:
    capped = max(0.0, family_value * 0.8)
    variants.append({family_name: capped})
  return variants


def build_consistency_solver_state(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
  normalized_traits: Optional[Dict[str, Any]] = None,
  benchmark_payload: Optional[Dict[str, Any]] = None,
  constraint_engine_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  baseline_financials = _clone(financials_json or {})
  if _safe_float((baseline_financials or {}).get("payroll_total_year1")) <= 0 and _safe_float((baseline_financials or {}).get("current_payroll")) <= 0:
    derived_payroll = _derived_year1_payroll_from_people(people_json or {})
    if derived_payroll > 0:
      baseline_financials["payroll_total_year1"] = derived_payroll
      baseline_financials["current_payroll"] = derived_payroll
  baseline_summary = build_consistency_financial_summary(
    financials_json=baseline_financials,
    financials_year1_json=financials_year1_json,
  )
  if not _solver_required(baseline_summary, constraint_engine_state=constraint_engine_state):
    return None

  baseline_state = {
    "ops_json": _clone(ops_json or {}),
    "people_json": _clone(people_json or {}),
    "financials_json": _clone(baseline_financials),
    "financials_year1_json": _clone(financials_year1_json or {}),
    "marketing_model_json": _clone(marketing_model_json or {}),
  }
  state_model = _build_solver_state_model(
    ops_json=ops_json,
    people_json=people_json,
    financials_json=baseline_financials,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
  )
  baseline_realism_distance = _constraint_engine_realism_distance(
    constraint_engine_state=constraint_engine_state,
    summary=baseline_summary,
    year1_json=financials_year1_json,
    ops_json=ops_json,
  )
  if not isinstance(state_model, dict):
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      state_model={},
      constraint_engine_state=constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      blocking_reason="missing_solver_state_model",
    )
  direct_inputs = _build_direct_solver_inputs(
    state_model=state_model,
  )
  if not isinstance(direct_inputs, dict):
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      state_model=state_model,
      constraint_engine_state=constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      blocking_reason="missing_direct_solver_inputs",
    )

  profiles = _solver_profiles(state_model=state_model)
  feasible_scenarios: List[Dict[str, Any]] = []
  fallback_scenarios: List[Dict[str, Any]] = []
  seen_feasible = set()
  seen_fallback = set()
  objective_policy = state_model.get("objective_policy") if isinstance(state_model, dict) else {}
  healthy_ratio = max(0.0, _safe_float((objective_policy or {}).get("healthy_ebitda_margin_ratio")))
  baseline_revenue = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
  healthy_ebitda_target = baseline_revenue * healthy_ratio if baseline_revenue > 0 and healthy_ratio > 0 else 0.0
  selected_target_label = "constraint_envelope"
  selected_target_amount = 0.0
  selected_target_ceiling = None
  baseline_blocking_count = len(_blocking_constraint_violations(constraint_engine_state))
  current_ebitda_margin = (
    _safe_float((baseline_summary or {}).get("ebitda")) / baseline_revenue
    if baseline_revenue > 0
    else None
  )
  ebitda_band = (constraint_engine_state or {}).get("ebitda_margin_band") if isinstance(constraint_engine_state, dict) else {}
  target_ebitda_min = None
  target_ebitda_max = None
  ebitda_band_min = _band_min(ebitda_band)
  ebitda_band_max = _band_max(ebitda_band)
  if current_ebitda_margin is not None and ebitda_band_min is not None and current_ebitda_margin < (ebitda_band_min - 0.001):
    target_ebitda_min = baseline_revenue * ebitda_band_min
    if ebitda_band_max is not None:
      target_ebitda_max = baseline_revenue * ebitda_band_max
    selected_target_label = "ebitda_floor"
    selected_target_amount = target_ebitda_min
  elif current_ebitda_margin is not None and ebitda_band_max is not None and current_ebitda_margin > (ebitda_band_max + 0.001):
    target_ebitda_max = baseline_revenue * ebitda_band_max
    if ebitda_band_min is not None:
      target_ebitda_min = baseline_revenue * ebitda_band_min
    selected_target_label = "ebitda_ceiling"
    selected_target_ceiling = target_ebitda_max
  elif healthy_ebitda_target > 0 and _safe_float((baseline_summary or {}).get("ebitda")) < healthy_ebitda_target:
    target_ebitda_min = healthy_ebitda_target
    if ebitda_band_max is not None:
      target_ebitda_max = baseline_revenue * ebitda_band_max
    selected_target_label = "healthy_floor"
    selected_target_amount = target_ebitda_min

  def _try_add_solution(
    *,
    profile: Dict[str, Any],
    target_ebitda_min: Optional[float],
    target_ebitda_max: Optional[float],
    target_list: List[Dict[str, Any]],
    seen_signatures: set,
    family_caps: Optional[Dict[str, float]] = None,
    enforce_blocking_bands: bool = False,
  ) -> Optional[Dict[str, Any]]:
    solution = _solve_direct_profile(
      profile=profile,
      direct_inputs=direct_inputs,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
      family_caps=family_caps,
      enforce_blocking_bands=enforce_blocking_bands,
    )
    if not isinstance(solution, dict):
      return None
    exact_patches = _exact_patches_from_solution(
      solution=solution,
      direct_inputs=direct_inputs,
      ops_json=ops_json,
    )
    signature = _scenario_signature(exact_patches)
    if not signature or signature in seen_signatures:
      return None
    profile_id = str(solution.get("profile_id") or profile.get("profile_id") or "").strip()
    archetype_meta = _scenario_archetype_meta(profile_id)
    candidate = _build_candidate_from_exact_patches(
      scenario_id=str(len(target_list) + 1),
      baseline_summary=baseline_summary,
      baseline_state=baseline_state,
      marketing_model_json=marketing_model_json,
      exact_patches=exact_patches,
      archetype=archetype_meta["archetype"],
      archetype_display=archetype_meta["display"],
      dominant_tradeoff=archetype_meta["tradeoff"],
      constraint_engine_state=constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
    )
    if not candidate:
      return None
    candidate["solution_profile_id"] = profile_id
    candidate["archetype"] = archetype_meta["archetype"]
    candidate["archetype_display"] = archetype_meta["display"]
    candidate["dominant_tradeoff"] = archetype_meta["tradeoff"]
    candidate["enforce_blocking_bands"] = bool(solution.get("enforce_blocking_bands"))
    candidate["distortion_components"] = dict(solution.get("distortion_components") or {})
    candidate["distortion_total"] = _safe_float(solution.get("distortion_total"))
    candidate["family_raw_components"] = dict(solution.get("family_raw_components") or {})
    candidate["max_family_move"] = _safe_float(solution.get("max_family_move"))
    lever_summary = _build_lever_summary(
      exact_patches=exact_patches,
      family_raw_components=candidate["family_raw_components"],
    )
    candidate["lever_summary"] = lever_summary
    candidate["meaningful_families"] = list(lever_summary.get("meaningful_families") or [])
    candidate["meaningful_lever_count"] = int(max(0, _safe_int(lever_summary.get("meaningful_lever_count")) or 0))
    candidate["coordination_score"] = _safe_float(lever_summary.get("coordination_score"))
    if _nontrivial_repair_required(
      baseline_realism_distance=baseline_realism_distance,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
      baseline_blocking_count=baseline_blocking_count,
    ) and _safe_float(candidate.get("meaningful_lever_count")) < 2:
      return None
    scenario_forecast = _build_scenario_forecast_bundle(
      baseline_state=baseline_state,
      exact_patches=exact_patches,
      remaining_violations=candidate.get("remaining_violations") or [],
      constraint_engine_state=constraint_engine_state,
      normalized_traits=normalized_traits,
      benchmark_payload=benchmark_payload,
    )
    candidate["scenario_forecast"] = scenario_forecast
    candidate["forecast_engine_state"] = _clone((scenario_forecast or {}).get("forecast_engine_state") or {})
    candidate["forecast_quarters"] = _clone((scenario_forecast or {}).get("forecast_quarters") or [])
    candidate["forecast_summary"] = _clone((scenario_forecast or {}).get("forecast_summary") or {})
    seen_signatures.add(signature)
    target_list.append(candidate)
    return candidate

  for profile in profiles:
    solved_for_profile = False
    target_specs = [
      (selected_target_label, target_ebitda_min, target_ebitda_max, feasible_scenarios, seen_feasible),
      ("fallback", None, None, fallback_scenarios, seen_fallback),
    ]
    for target_label, target_floor, target_ceiling, target_list, seen_signatures in target_specs:
      candidate = None
      for enforce_blocking_bands in (True, False):
        candidate = _try_add_solution(
          profile=profile,
          target_ebitda_min=target_floor,
          target_ebitda_max=target_ceiling,
          target_list=target_list,
          seen_signatures=seen_signatures,
          enforce_blocking_bands=enforce_blocking_bands,
        )
        if candidate:
          break
      if candidate:
        if target_label != "fallback":
          candidate["target_label"] = target_label
          candidate["target_ebitda_min"] = target_floor
          candidate["target_ebitda_max"] = target_ceiling
        else:
          candidate["target_label"] = target_label
          candidate["target_ebitda_min"] = None
          candidate["target_ebitda_max"] = None

        for family_cap in _family_cap_variants(candidate):
          alt_candidate = None
          for enforce_blocking_bands in (True, False):
            alt_candidate = _try_add_solution(
              profile=profile,
              target_ebitda_min=target_floor,
              target_ebitda_max=target_ceiling,
              target_list=target_list,
              seen_signatures=seen_signatures,
              family_caps=family_cap,
              enforce_blocking_bands=enforce_blocking_bands,
            )
            if alt_candidate:
              break
          if not alt_candidate:
            continue
          alt_candidate["target_label"] = candidate.get("target_label")
          alt_candidate["target_ebitda_min"] = candidate.get("target_ebitda_min")
          alt_candidate["target_ebitda_max"] = candidate.get("target_ebitda_max")
        solved_for_profile = True
        break
    if solved_for_profile:
      continue

  break_even_found = bool(feasible_scenarios)
  scenarios = feasible_scenarios if feasible_scenarios else fallback_scenarios
  if not feasible_scenarios:
    selected_target_label = "fallback"
    selected_target_amount = 0.0
    selected_target_ceiling = None

  if not scenarios:
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      state_model=state_model,
      constraint_engine_state=constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      blocking_reason="no_viable_scenarios",
    )

  zero_blocker_scenarios = [
    candidate for candidate in scenarios
    if isinstance(candidate, dict) and _safe_float(candidate.get("remaining_blocking_count")) <= 0
  ]
  if zero_blocker_scenarios:
    scenarios = zero_blocker_scenarios

  scenarios = _select_client_ready_scenarios(scenarios, state_model=state_model)

  if not scenarios:
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      state_model=state_model,
      constraint_engine_state=constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      blocking_reason="no_client_ready_scenarios",
    )

  normalized_selected: List[Dict[str, Any]] = []
  for index, candidate in enumerate(scenarios, start=1):
    normalized = dict(candidate)
    normalized["scenario_id"] = str(index)
    normalized["presentation_issues"] = list(normalized.get("presentation_issues") or [])
    normalized_selected.append(normalized)

  return {
    "status": "awaiting_choice",
    "solve_mode": str(state_model.get("solve_mode") or "parent_fallback"),
    "target_metric": "year1_realism",
    "search_mode": "direct_pulp",
    "loss_threshold_ratio": LOSS_THRESHOLD_RATIO,
    "healthy_ebitda_margin_ratio": healthy_ratio,
    "selected_target_label": selected_target_label,
    "selected_target_ebitda_min": selected_target_amount,
    "selected_target_ebitda_max": selected_target_ceiling,
    "baseline_summary": baseline_summary,
    "baseline_loss_pct": _loss_pct(baseline_summary),
    "baseline_table_markdown": build_consistency_financial_table(baseline_summary),
    "state_model": state_model,
    "constraint_engine_state": _clone(constraint_engine_state or {}),
    "baseline_realism_distance": baseline_realism_distance,
    "structural_gap": not break_even_found,
    "scenarios": normalized_selected,
  }


def apply_consistency_solver_choice(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  solver_state: Dict[str, Any],
  selected_scenario_id: str,
  overrides: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
  scenarios = solver_state.get("scenarios") if isinstance(solver_state, dict) else None
  if not isinstance(scenarios, list):
    return None
  selected = None
  for scenario in scenarios:
    if not isinstance(scenario, dict):
      continue
    if str(scenario.get("scenario_id") or "").strip() == str(selected_scenario_id or "").strip():
      selected = scenario
      break
  if not isinstance(selected, dict):
    return None

  exact_patches = _clone(selected.get("exact_patches") or {})
  overrides = overrides if isinstance(overrides, dict) else {}
  state_model = solver_state.get("state_model") if isinstance(solver_state, dict) else {}
  constraint_profile = (state_model or {}).get("constraint_profile") if isinstance(state_model, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}
  baseline_expected_units = max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1")))
  units_per_marketing_dollar = max(0.0, _safe_float(((constraint_profile or {}).get("demand_curve") or {}).get("units_per_marketing_dollar")))

  if overrides.get("price_change_percent") is not None:
    current_price = _safe_float(
      _top_level_driver_value(financials_year1_json or {}, "unit_price")
      or (ops_json or {}).get("unit_price")
    )
    pct = _safe_float(overrides.get("price_change_percent")) / 100.0
    if current_price > 0 and pct > 0:
      exact_patches.setdefault("financials_year1_patch", {})
      exact_patches["financials_year1_patch"]["unit_price"] = round(current_price * (1.0 + pct), 2)
  if overrides.get("unit_price_absolute") is not None:
    absolute_price = _safe_float(overrides.get("unit_price_absolute"))
    if absolute_price > 0:
      exact_patches.setdefault("financials_year1_patch", {})
      exact_patches["financials_year1_patch"]["unit_price"] = round(absolute_price, 2)

  if overrides.get("utilization_percent") is not None:
    util_ratio = _normalize_ratio(overrides.get("utilization_percent"))
    if util_ratio is not None:
      exact_patches.setdefault("financials_year1_patch", {})
      exact_patches["financials_year1_patch"]["utilization_rate"] = util_ratio

  direct_inputs = _build_direct_solver_inputs(state_model=state_model or {}) if isinstance(state_model, dict) else None
  if isinstance(direct_inputs, dict):
    year1_patch = exact_patches.get("financials_year1_patch")
    if isinstance(year1_patch, dict) and year1_patch:
      exact_patches["financials_year1_patch"] = _normalize_child_first_year1_patch(
        year1_patch=year1_patch,
        direct_inputs=direct_inputs,
      )

  if overrides.get("marketing_reduction_percent") is not None:
    current_marketing = _safe_float((financials_json or {}).get("marketing_total_year1"))
    pct = _safe_float(overrides.get("marketing_reduction_percent")) / 100.0
    if current_marketing > 0 and pct >= 0 and units_per_marketing_dollar > 0:
      target_marketing = round(current_marketing * (1.0 - pct), 2)
      target_units = round(target_marketing * units_per_marketing_dollar, 2)
      exact_patches.setdefault("marketing_model_patch", {})
      exact_patches["marketing_model_patch"]["expected_units_year1"] = target_units
  if overrides.get("marketing_total_year1_absolute") is not None:
    total = _safe_float(overrides.get("marketing_total_year1_absolute"))
    if total >= 0 and units_per_marketing_dollar > 0:
      target_units = round(total * units_per_marketing_dollar, 2)
      exact_patches.setdefault("marketing_model_patch", {})
      exact_patches["marketing_model_patch"]["expected_units_year1"] = target_units

  if overrides.get("other_opex_reduction_percent") is not None:
    current_other_opex = _safe_float((financials_json or {}).get("other_operating_expense"))
    pct = _safe_float(overrides.get("other_opex_reduction_percent")) / 100.0
    if current_other_opex > 0 and pct >= 0:
      exact_patches.setdefault("financials_patch", {})
      exact_patches["financials_patch"]["other_operating_expense"] = round(current_other_opex * (1.0 - pct), 2)
  if overrides.get("other_opex_absolute") is not None:
    total = _safe_float(overrides.get("other_opex_absolute"))
    if total >= 0:
      exact_patches.setdefault("financials_patch", {})
      exact_patches["financials_patch"]["other_operating_expense"] = round(total, 2)

  role_title = str(overrides.get("role_title") or "").strip().lower()
  months_until_hire = _safe_int(overrides.get("months_until_hire"))
  if role_title and months_until_hire is not None:
    role_updates = exact_patches.get("people_role_updates")
    if not isinstance(role_updates, list):
      role_updates = []
      exact_patches["people_role_updates"] = role_updates
    updated = False
    for item in role_updates:
      if not isinstance(item, dict):
        continue
      if str(item.get("role_title") or "").strip().lower() != role_title:
        continue
      item["months_until_hire"] = int(max(0, months_until_hire))
      updated = True
      break
    if not updated:
      role_updates.append(
        {"role_title": role_title, "months_until_hire": int(max(0, months_until_hire))}
      )
    milestone_updates = _attach_milestone_updates_for_delay(
      ops_json=ops_json,
      minimum_months=int(max(1, months_until_hire)),
    )
    if milestone_updates:
      exact_patches["milestone_updates"] = milestone_updates

  milestone_months = _safe_int(overrides.get("milestone_timing_months_max"))
  if milestone_months is not None and milestone_months > 0:
    milestone_updates = exact_patches.get("milestone_updates")
    if not isinstance(milestone_updates, list) or not milestone_updates:
      auto_updates = _attach_milestone_updates_for_delay(
        ops_json=ops_json,
        minimum_months=milestone_months,
      )
      milestone_updates = auto_updates if auto_updates else []
    for update in milestone_updates:
      if not isinstance(update, dict):
        continue
      update["timing_months_max"] = int(milestone_months)
      update["timing"] = _render_timing_text(int(milestone_months))
    if milestone_updates:
      exact_patches["milestone_updates"] = milestone_updates

  next_ops, next_people, next_financials, next_year1, next_marketing_model = _apply_exact_patches(
    ops_json=ops_json,
    people_json=people_json,
    financials_json=financials_json,
    financials_year1_json=financials_year1_json,
    marketing_model_json=marketing_model_json,
    exact_patches=exact_patches,
  )
  violations = _scenario_violations(
    baseline_state={
      "ops_json": _clone(ops_json or {}),
      "people_json": _clone(people_json or {}),
      "financials_json": _clone(financials_json or {}),
      "financials_year1_json": _clone(financials_year1_json or {}),
      "marketing_model_json": _clone(marketing_model_json or {}),
    },
    next_ops=next_ops,
    next_financials=next_financials,
    next_year1=next_year1,
    exact_patches=exact_patches,
    marketing_model_json=next_marketing_model,
  )
  if violations:
    return None
  summary = build_consistency_financial_summary(
    financials_json=next_financials,
    financials_year1_json=next_year1,
  )
  return {
    "ops_json": next_ops,
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "marketing_model_json": next_marketing_model,
    "summary": summary,
    "exact_patches": exact_patches,
    "scenario": selected,
  }
