from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
  from consistency_financials import build_consistency_financial_summary  # type: ignore
except Exception:
  from client_intake_and_finmo.consistency_financials import build_consistency_financial_summary  # type: ignore

try:
  from convergence_policy import CONVERGENCE_POLICY_VERSION, build_convergence_policy  # type: ignore
except Exception:
  from client_intake_and_finmo.convergence_policy import (  # type: ignore
    CONVERGENCE_POLICY_VERSION,
    build_convergence_policy,
  )

try:
  from planning_contract import PLANNING_CONTRACT_VERSION, engine_versions_payload  # type: ignore
except Exception:
  from client_intake_and_finmo.planning_contract import PLANNING_CONTRACT_VERSION, engine_versions_payload  # type: ignore


FORECAST_ENGINE_VERSION = "forecast-engine/v3"
FORECAST_QUARTERS = 20
BLOCKING_YEAR1_VIOLATIONS = {
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


def _clamp(value: float, low: float, high: float) -> float:
  return max(low, min(high, float(value)))


def _nonneg(value: Any) -> float:
  return max(0.0, _to_float(value) or 0.0)


def _normalize_ratio(value: Any) -> Optional[float]:
  raw = _to_float(value)
  if raw is None:
    return None
  if raw > 1.0:
    raw = raw / 100.0
  return _clamp(raw, 0.0, 1.0)


def _midpoint(band: Any, fallback: Optional[float] = None) -> Optional[float]:
  if not isinstance(band, dict):
    return fallback
  low = _to_float(band.get("min"))
  high = _to_float(band.get("max"))
  if low is not None and high is not None:
    return (low + high) / 2.0
  if low is not None:
    return low
  if high is not None:
    return high
  return fallback


def _band_min(band: Any) -> Optional[float]:
  return _to_float((band or {}).get("min")) if isinstance(band, dict) else None


def _band_max(band: Any) -> Optional[float]:
  return _to_float((band or {}).get("max")) if isinstance(band, dict) else None


def _lerp(start: Optional[float], end: Optional[float], progress: float) -> Optional[float]:
  if start is None and end is None:
    return None
  if start is None:
    return end
  if end is None:
    return start
  p = _clamp(progress, 0.0, 1.0)
  return start + ((end - start) * p)


def _ratio_band_from_point(point: Optional[float], width: float) -> Dict[str, Optional[float]]:
  if point is None:
    return {"min": None, "max": None}
  low = max(0.0, point - width)
  high = min(1.0, point + width)
  return {"min": round(low, 6), "max": round(high, 6)}


def _days_band_from_point(point: Optional[float], width: float) -> Dict[str, Optional[float]]:
  if point is None:
    return {"min": None, "max": None}
  low = max(0.0, point - width)
  high = max(low, point + width)
  return {"min": round(low, 2), "max": round(high, 2)}


def _blend_band(
  base_band: Any,
  target_band: Any,
  *,
  progress: float,
  expansion: float = 1.0,
) -> Dict[str, Optional[float]]:
  low = _lerp(_band_min(base_band), _band_min(target_band), progress)
  high = _lerp(_band_max(base_band), _band_max(target_band), progress)
  if low is None and high is None:
    return {"min": None, "max": None}
  if low is None:
    low = high
  if high is None:
    high = low
  if low is not None and high is not None and high < low:
    high = low
  if low is not None and high is not None and expansion > 1.0:
    mid = (low + high) / 2.0
    half = ((high - low) / 2.0) * expansion
    low = mid - half
    high = mid + half
  return {
    "min": round(low, 6) if low is not None else None,
    "max": round(high, 6) if high is not None else None,
  }


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
      product_name = str(product.get("product_name") or "").strip() or str(product.get("unit_name") or "").strip() or "Product"
      rows.append(
        {
          "lob_name": lob_name,
          "product_name": product_name,
          "product": product,
        }
      )
  return rows


def _build_child_revenue_basis(
  *,
  year1: Dict[str, Any],
  ops: Dict[str, Any],
) -> List[Dict[str, Any]]:
  basis: List[Dict[str, Any]] = []
  for row in _iter_year1_products(year1 or {}):
    product = row.get("product") if isinstance(row, dict) else {}
    product = product if isinstance(product, dict) else {}
    periods = max(
      0.0,
      _nonneg(product.get("operating_periods_per_year") or product.get("operating_weeks_per_year"))
      or _nonneg((year1 or {}).get("operating_periods_per_year") or (year1 or {}).get("operating_weeks_per_year"))
      or 0.0,
    )
    capacity_per_period = max(
      0.0,
      _nonneg(product.get("units_per_period_capacity") or product.get("units_per_week_capacity"))
      or _nonneg((year1 or {}).get("units_per_period_capacity") or (year1 or {}).get("units_per_week_capacity"))
      or 0.0,
    )
    utilization = _normalize_ratio(product.get("utilization_rate"))
    avg_units = max(0.0, _nonneg(product.get("avg_units_per_period_year1") or product.get("avg_units_per_week_year1")) or 0.0)
    if avg_units <= 0 and utilization is not None and capacity_per_period > 0:
      avg_units = capacity_per_period * utilization
    if utilization is None and capacity_per_period > 0 and avg_units > 0:
      utilization = _clamp(avg_units / max(capacity_per_period, 1e-9), 0.0, 1.0)
    price = max(0.0, _nonneg(product.get("unit_price")) or _nonneg((ops or {}).get("unit_price")) or 0.0)
    annual_units = avg_units * periods
    annual_capacity_units = capacity_per_period * periods
    annual_revenue = annual_units * price
    basis.append(
      {
        "lob_name": row.get("lob_name"),
        "product_name": row.get("product_name"),
        "unit_price": price,
        "utilization_rate": utilization,
        "avg_units_per_period_year1": avg_units,
        "operating_periods_per_year": periods,
        "units_per_period_capacity": capacity_per_period,
        "annual_units": annual_units,
        "annual_capacity_units": annual_capacity_units,
        "annual_revenue": annual_revenue,
      }
    )
  return basis


def _group_quarter_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  lob_map: Dict[str, Dict[str, Any]] = {}
  for product in products:
    if not isinstance(product, dict):
      continue
    lob_name = str(product.get("lob_name") or "").strip() or "Line of business"
    lob_entry = lob_map.setdefault(lob_name, {"lob_name": lob_name, "products": [], "revenue": 0.0, "units": 0.0})
    lob_entry["products"].append(product)
    lob_entry["revenue"] += _to_float(product.get("revenue")) or 0.0
    lob_entry["units"] += _to_float(product.get("units")) or 0.0
  out: List[Dict[str, Any]] = []
  for lob_entry in lob_map.values():
    lob_entry["revenue"] = round(_to_float(lob_entry.get("revenue")) or 0.0, 2)
    lob_entry["units"] = round(_to_float(lob_entry.get("units")) or 0.0, 2)
    out.append(lob_entry)
  return out


def _quarter_label(index: int) -> str:
  year_num = (index // 4) + 1
  quarter_num = (index % 4) + 1
  return f"Y{year_num} Q{quarter_num}"


def _growth_at(path: List[float], index: int, fallback: float) -> float:
  if not path:
    return fallback
  if index < len(path):
    return float(path[index])
  tail = path[-4:] if len(path) >= 4 else path
  if not tail:
    return fallback
  return float(tail[index % len(tail)])


def _working_capital_days_from_financials(financials_json: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Optional[float]]:
  revenue = max(0.0, _to_float((summary or {}).get("revenue")) or 0.0)
  cogs = max(0.0, _to_float((summary or {}).get("cogs")) or 0.0)
  ar = max(0.0, _to_float((financials_json or {}).get("ar_balance")) or 0.0)
  ap = max(0.0, _to_float((financials_json or {}).get("ap_balance")) or 0.0)
  inventory = max(0.0, _to_float((financials_json or {}).get("inventory_balance")) or 0.0)
  return {
    "dso": ((ar / revenue) * 365.0) if revenue > 0 else None,
    "dpo": ((ap / cogs) * 365.0) if cogs > 0 else None,
    "inventory_days": ((inventory / cogs) * 365.0) if cogs > 0 else None,
  }


def _quarter_status(
  *,
  actual: Optional[float],
  band: Any,
) -> str:
  if actual is None:
    return "insufficient_data"
  low = _band_min(band)
  high = _band_max(band)
  if low is not None and actual < low:
    return "below"
  if high is not None and actual > high:
    return "above"
  return "within_band"


def _policy_progress(policy: Dict[str, Any], metric: str, quarter_number: int) -> float:
  metrics = policy.get("metrics") if isinstance(policy, dict) else {}
  metric_policy = metrics.get(metric) if isinstance(metrics, dict) else {}
  start_quarter = int(metric_policy.get("start_quarter") or 1)
  full_effect_quarter = int(metric_policy.get("full_effect_quarter") or start_quarter)
  strength = _clamp(_to_float(metric_policy.get("strength")) or 0.0, 0.0, 1.0)
  if quarter_number < start_quarter:
    return 0.0
  if full_effect_quarter <= start_quarter:
    return strength
  raw_progress = (quarter_number - start_quarter) / float(full_effect_quarter - start_quarter)
  return _clamp(raw_progress, 0.0, 1.0) * strength


def _policy_initial_weight(policy: Dict[str, Any], metric: str) -> float:
  metrics = policy.get("metrics") if isinstance(policy, dict) else {}
  metric_policy = metrics.get(metric) if isinstance(metrics, dict) else {}
  return _clamp(_to_float(metric_policy.get("initial_weight")) or 0.25, 0.0, 1.0)


def _policy_expansion(policy: Dict[str, Any], metric: str) -> float:
  metrics = policy.get("metrics") if isinstance(policy, dict) else {}
  metric_policy = metrics.get(metric) if isinstance(metrics, dict) else {}
  return max(1.0, _to_float(metric_policy.get("band_expansion")) or 1.0)


def _quarter_violations(
  *,
  gross_margin: Optional[float],
  ebitda_margin: Optional[float],
  utilization: Optional[float],
  realized_growth: Optional[float],
  benchmark_growth: Optional[float],
  growth_tolerance: float,
  working_capital_days: Dict[str, Optional[float]],
  gross_margin_band: Any,
  ebitda_margin_band: Any,
  utilization_band: Any,
  working_capital_band: Any,
) -> List[str]:
  violations: List[str] = []
  if _quarter_status(actual=gross_margin, band=gross_margin_band) == "below":
    violations.append("gross_margin_too_low")
  elif _quarter_status(actual=gross_margin, band=gross_margin_band) == "above":
    violations.append("gross_margin_too_high")
  if _quarter_status(actual=ebitda_margin, band=ebitda_margin_band) == "below":
    violations.append("ebitda_margin_too_low")
  elif _quarter_status(actual=ebitda_margin, band=ebitda_margin_band) == "above":
    violations.append("ebitda_margin_too_high")
  if _quarter_status(actual=utilization, band=utilization_band) == "below":
    violations.append("utilization_too_low")
  elif _quarter_status(actual=utilization, band=utilization_band) == "above":
    violations.append("utilization_too_high")
  if benchmark_growth is not None and realized_growth is not None and realized_growth > benchmark_growth + growth_tolerance:
    violations.append("growth_too_fast")

  wc_band = working_capital_band if isinstance(working_capital_band, dict) else {}
  for metric in ("dso", "dpo", "inventory_days"):
    status = _quarter_status(actual=working_capital_days.get(metric), band=wc_band.get(metric))
    if status in ("below", "above"):
      violations.append("working_capital_inconsistent")
      break
  return violations


def _blocking_constraint_violations(constraint_engine_state: Optional[Dict[str, Any]]) -> List[str]:
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  return [
    str(code or "").strip()
    for code in (state.get("violations") or [])
    if str(code or "").strip() in BLOCKING_YEAR1_VIOLATIONS
  ]


def build_forecast_engine_bundle(
  *,
  shared_context: Optional[Dict[str, Any]] = None,
  operating_model_json: Optional[Dict[str, Any]] = None,
  target_market_json: Optional[Dict[str, Any]] = None,
  people_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  marketing_model_json: Optional[Dict[str, Any]] = None,
  normalized_traits: Optional[Dict[str, Any]] = None,
  benchmark_payload: Optional[Dict[str, Any]] = None,
  constraint_engine_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del target_market_json, people_json
  context = shared_context if isinstance(shared_context, dict) else {}
  ops = operating_model_json if isinstance(operating_model_json, dict) else dict(context.get("operating_model") or {})
  financials = financials_json if isinstance(financials_json, dict) else dict(context.get("financials") or {})
  year1 = (
    financials_year1_json
    if isinstance(financials_year1_json, dict)
    else dict(context.get("financials_year1_json") or {})
  )
  marketing = marketing_model_json if isinstance(marketing_model_json, dict) else dict(context.get("marketing") or {})
  traits = normalized_traits if isinstance(normalized_traits, dict) else dict(context.get("normalized_traits") or {})
  benchmark = benchmark_payload if isinstance(benchmark_payload, dict) else dict(context.get("benchmark_payload") or {})
  engine_state = (
    constraint_engine_state
    if isinstance(constraint_engine_state, dict)
    else dict(context.get("constraint_engine_state") or {})
  )
  convergence_policy = build_convergence_policy(
    normalized_traits=traits,
    benchmark_payload=benchmark,
  )
  blocking_violations = _blocking_constraint_violations(engine_state)

  if blocking_violations:
    forecast_engine_state = {
      "contract_version": PLANNING_CONTRACT_VERSION,
      "engine_version": FORECAST_ENGINE_VERSION,
      "quarter_count": FORECAST_QUARTERS,
      "benchmark_confidence_score": round(_clamp(_to_float((benchmark or {}).get("confidence_score")) or 0.0, 0.0, 1.0), 3),
      "fallback_level": str((benchmark or {}).get("fallback_level") or "generic"),
      "status": "blocked_unresolved_year1",
      "blocking_violations": blocking_violations,
      "explanation": "Forecast engine did not run because Year 1 remains outside the enforced realism envelope.",
      "benchmark_summary": benchmark,
      "convergence_policy": convergence_policy,
      "traits": traits,
    }
    versions = engine_versions_payload()
    versions["forecast_engine_version"] = FORECAST_ENGINE_VERSION
    versions["convergence_policy_version"] = CONVERGENCE_POLICY_VERSION
    return {
      "forecast_engine_state": forecast_engine_state,
      "forecast_quarters": [],
      "engine_versions": versions,
    }

  summary = build_consistency_financial_summary(
    financials_json=financials,
    financials_year1_json=year1,
  )
  child_revenue_basis = _build_child_revenue_basis(year1=year1, ops=ops)
  child_annual_revenue = sum(max(0.0, _to_float(item.get("annual_revenue")) or 0.0) for item in child_revenue_basis)
  child_annual_units = sum(max(0.0, _to_float(item.get("annual_units")) or 0.0) for item in child_revenue_basis)
  child_annual_capacity = sum(max(0.0, _to_float(item.get("annual_capacity_units")) or 0.0) for item in child_revenue_basis)

  annual_revenue = child_annual_revenue or _nonneg(summary.get("revenue"))
  annual_units = child_annual_units or _required_units_year1(year1)
  annual_cogs = _nonneg(summary.get("cogs"))
  annual_payroll = _nonneg(summary.get("payroll"))
  annual_marketing = _nonneg(summary.get("marketing"))
  annual_opex = _nonneg(summary.get("other_opex"))
  annual_interest = _nonneg(summary.get("interest"))
  annual_ebitda = _to_float(summary.get("ebitda")) or 0.0
  unit_price = (
    (child_annual_revenue / max(child_annual_units, 1e-9))
    if child_annual_revenue > 0 and child_annual_units > 0
    else _nonneg(year1.get("unit_price") or ops.get("unit_price") or (annual_revenue / annual_units if annual_units > 0 else 0.0))
  )
  utilization = (
    _clamp(child_annual_units / max(child_annual_capacity, 1e-9), 0.0, 1.0)
    if child_annual_capacity > 0 and child_annual_units > 0
    else _normalize_ratio(year1.get("utilization_rate") or (engine_state.get("current_metrics") or {}).get("utilization_rate"))
  )
  current_gross_margin = ((annual_revenue - annual_cogs) / annual_revenue) if annual_revenue > 0 else None
  current_payroll_ratio = (annual_payroll / annual_revenue) if annual_revenue > 0 else None
  current_opex_ratio = (annual_opex / annual_revenue) if annual_revenue > 0 else None
  current_marketing_ratio = (annual_marketing / annual_revenue) if annual_revenue > 0 else None
  current_ebitda_ratio = (annual_ebitda / annual_revenue) if annual_revenue > 0 else None
  current_capex_ratio = (
    _nonneg(financials.get("current_capex")) / annual_revenue if annual_revenue > 0 else None
  )
  current_dep_ratio = (
    _nonneg(financials.get("current_depreciation")) / annual_revenue if annual_revenue > 0 else 0.0
  )

  current_wc_days = _working_capital_days_from_financials(financials, summary)
  benchmark_confidence = _clamp(_to_float((benchmark or {}).get("confidence_score")) or 0.0, 0.0, 1.0)
  fallback_level = str((benchmark or {}).get("fallback_level") or "generic")
  growth_path = [float(v) for v in ((benchmark or {}).get("revenue_growth_path") or []) if _to_float(v) is not None]

  benchmark_gross_margin_band = (benchmark or {}).get("gross_margin_band") or {}
  benchmark_ebitda_margin_band = (benchmark or {}).get("ebitda_margin_band") or {}
  benchmark_payroll_band = (benchmark or {}).get("payroll_intensity") or {}
  benchmark_opex_band = (benchmark or {}).get("opex_intensity") or {}
  benchmark_capex_band = (benchmark or {}).get("capex_percent_revenue") or {}
  benchmark_dep_band = (benchmark or {}).get("depreciation_percent_revenue") or {}
  benchmark_wc_band = (benchmark or {}).get("working_capital") or {}
  benchmark_gross_margin = _midpoint(benchmark_gross_margin_band, current_gross_margin)
  benchmark_ebitda_margin = _midpoint(benchmark_ebitda_margin_band, current_ebitda_ratio)
  benchmark_payroll_ratio = _midpoint(benchmark_payroll_band, current_payroll_ratio)
  benchmark_opex_ratio = _midpoint(benchmark_opex_band, current_opex_ratio)
  benchmark_capex_ratio = _midpoint(benchmark_capex_band, current_capex_ratio)
  benchmark_dep_ratio = _midpoint(benchmark_dep_band, current_dep_ratio)
  benchmark_dso = _midpoint((benchmark_wc_band or {}).get("dso"), current_wc_days.get("dso"))
  benchmark_dpo = _midpoint((benchmark_wc_band or {}).get("dpo"), current_wc_days.get("dpo"))
  benchmark_inventory_days = _midpoint(
    (benchmark_wc_band or {}).get("inventory_days"),
    current_wc_days.get("inventory_days"),
  )

  utilization_band = (engine_state.get("utilization_range") if isinstance(engine_state, dict) else {}) or {}
  gross_margin_band = (engine_state.get("gross_margin_band") if isinstance(engine_state, dict) else {}) or {}
  ebitda_margin_band = (engine_state.get("ebitda_margin_band") if isinstance(engine_state, dict) else {}) or {}
  target_utilization = _midpoint(utilization_band, utilization)

  annual_capacity_units = max(
    child_annual_capacity,
    annual_units / max(utilization, 1e-9) if utilization and utilization > 0 else 0.0,
    _band_max((engine_state.get("supportable_unit_range") if isinstance(engine_state, dict) else {}) or {}) or annual_units,
    annual_units,
    1.0,
  )

  if annual_revenue <= 0 or annual_units <= 0 or unit_price <= 0:
    forecast_engine_state = {
      "contract_version": PLANNING_CONTRACT_VERSION,
      "engine_version": FORECAST_ENGINE_VERSION,
      "quarter_count": FORECAST_QUARTERS,
      "benchmark_confidence_score": benchmark_confidence,
      "fallback_level": fallback_level,
      "status": "insufficient_data",
      "explanation": "Forecast engine could not build quarter states because Year-1 revenue drivers are incomplete.",
      "starting_state": summary,
      "benchmark_summary": benchmark,
      "convergence_policy": convergence_policy,
    }
    versions = engine_versions_payload()
    versions["forecast_engine_version"] = FORECAST_ENGINE_VERSION
    versions["convergence_policy_version"] = CONVERGENCE_POLICY_VERSION
    return {
      "forecast_engine_state": forecast_engine_state,
      "forecast_quarters": [],
      "engine_versions": versions,
    }

  quarterly_revenue = annual_revenue / 4.0
  quarterly_interest = annual_interest / 4.0
  growth_tolerance = 0.015 + ((1.0 - (_to_float(convergence_policy.get("global_convergence_strength")) or 0.0)) * 0.05)

  quarters: List[Dict[str, Any]] = []
  previous_revenue = quarterly_revenue
  previous_price = unit_price
  product_states: List[Dict[str, Any]] = []
  for item in child_revenue_basis:
    if not isinstance(item, dict):
      continue
    product_states.append(
      {
        "lob_name": item.get("lob_name"),
        "product_name": item.get("product_name"),
        "price": max(0.0, _to_float(item.get("unit_price")) or 0.0),
        "quarter_units": max(0.0, (_to_float(item.get("annual_units")) or 0.0) / 4.0),
        "quarter_capacity_units": max(0.0, (_to_float(item.get("annual_capacity_units")) or 0.0) / 4.0),
        "utilization_rate": _normalize_ratio(item.get("utilization_rate")),
      }
    )

  for quarter_index in range(FORECAST_QUARTERS):
    quarter_number = quarter_index + 1
    revenue_progress = _policy_progress(convergence_policy, "revenue_growth", quarter_number)
    gross_progress = _policy_progress(convergence_policy, "gross_margin", quarter_number)
    ebitda_progress = _policy_progress(convergence_policy, "ebitda_margin", quarter_number)
    payroll_progress = _policy_progress(convergence_policy, "payroll_intensity", quarter_number)
    opex_progress = _policy_progress(convergence_policy, "opex_intensity", quarter_number)
    capex_progress = _policy_progress(convergence_policy, "capex_percent_revenue", quarter_number)
    dep_progress = _policy_progress(convergence_policy, "depreciation_percent_revenue", quarter_number)
    wc_progress = _policy_progress(convergence_policy, "working_capital", quarter_number)
    utilization_progress = _policy_progress(convergence_policy, "utilization", quarter_number)

    benchmark_growth = _growth_at(growth_path, quarter_index, 0.01)
    growth_seed = benchmark_growth * _policy_initial_weight(convergence_policy, "revenue_growth")
    realized_growth = _lerp(growth_seed, benchmark_growth, revenue_progress) or benchmark_growth

    price_growth = min(0.015, max(0.0, benchmark_growth * 0.25))
    price_seed = price_growth * 0.5
    realized_price_growth = _lerp(price_seed, price_growth, revenue_progress) or price_seed

    target_util = _lerp(utilization, target_utilization, utilization_progress)
    target_util = _normalize_ratio(target_util) if target_util is not None else utilization
    quarter_products: List[Dict[str, Any]] = []
    unit_growth = realized_growth - realized_price_growth
    if product_states:
      total_product_revenue = 0.0
      total_product_units = 0.0
      total_product_capacity = 0.0
      total_price_weight = 0.0
      next_states: List[Dict[str, Any]] = []
      for state in product_states:
        base_price = max(0.0, _to_float(state.get("price")) or 0.0)
        previous_units_product = max(0.0, _to_float(state.get("quarter_units")) or 0.0)
        quarter_capacity_units = max(0.0, _to_float(state.get("quarter_capacity_units")) or 0.0)
        base_util = _normalize_ratio(state.get("utilization_rate"))
        product_price = base_price * (1.0 + realized_price_growth) if quarter_index > 0 else base_price
        growth_units = previous_units_product * (1.0 + unit_growth) if quarter_index > 0 else previous_units_product
        product_target_util = target_util if target_util is not None else base_util
        if product_target_util is None and quarter_capacity_units > 0:
          product_target_util = _clamp(growth_units / max(quarter_capacity_units, 1e-9), 0.0, 1.0)
        if quarter_capacity_units > 0 and product_target_util is not None:
          util_target_units = quarter_capacity_units * product_target_util
          product_units = _lerp(growth_units, util_target_units, min(0.85, max(0.0, utilization_progress)))
          product_units = max(0.0, min(product_units or 0.0, quarter_capacity_units))
          product_util = _clamp((product_units or 0.0) / max(quarter_capacity_units, 1e-9), 0.0, 1.0)
        else:
          product_units = max(0.0, growth_units)
          product_util = product_target_util
        product_revenue = max(0.0, (product_units or 0.0) * product_price)
        total_product_revenue += product_revenue
        total_product_units += max(0.0, product_units or 0.0)
        total_product_capacity += quarter_capacity_units
        total_price_weight += product_units or 0.0
        quarter_products.append(
          {
            "lob_name": state.get("lob_name"),
            "product_name": state.get("product_name"),
            "units": round(max(0.0, product_units or 0.0), 2),
            "price": round(max(0.0, product_price), 2),
            "utilization": round(product_util, 6) if product_util is not None else None,
            "capacity_units": round(quarter_capacity_units, 2),
            "revenue": round(product_revenue, 2),
          }
        )
        next_states.append(
          {
            "lob_name": state.get("lob_name"),
            "product_name": state.get("product_name"),
            "price": product_price,
            "quarter_units": max(0.0, product_units or 0.0),
            "quarter_capacity_units": quarter_capacity_units,
            "utilization_rate": product_util,
          }
        )
      product_states = next_states
      quarter_revenue = total_product_revenue
      quarter_units = total_product_units
      implied_capacity_units = max(total_product_capacity, quarter_units / max(target_util or 0.5, 1e-9), 1e-9)
      quarter_utilization = quarter_units / max(implied_capacity_units, 1e-9)
      quarter_price = quarter_revenue / max(quarter_units, 1e-9) if quarter_units > 0 else previous_price
    else:
      quarter_revenue = previous_revenue * (1.0 + realized_growth) if quarter_index > 0 else previous_revenue
      quarter_price = previous_price * (1.0 + realized_price_growth) if quarter_index > 0 else previous_price
      quarter_units = quarter_revenue / max(quarter_price, 1e-9)
      implied_capacity_units = max(annual_capacity_units / 4.0, quarter_units / max(target_util or 0.5, 1e-9))
      quarter_utilization = quarter_units / max(implied_capacity_units, 1e-9)

    dynamic_gross_band = _blend_band(
      gross_margin_band,
      benchmark_gross_margin_band,
      progress=gross_progress,
      expansion=_policy_expansion(convergence_policy, "gross_margin"),
    )
    dynamic_ebitda_band = _blend_band(
      ebitda_margin_band,
      benchmark_ebitda_margin_band,
      progress=ebitda_progress,
      expansion=_policy_expansion(convergence_policy, "ebitda_margin"),
    )
    dynamic_util_band = _blend_band(
      utilization_band,
      utilization_band,
      progress=utilization_progress,
      expansion=1.0,
    )
    dynamic_wc_band = {
      "dso": _blend_band(
        _days_band_from_point(current_wc_days.get("dso"), 10.0),
        (benchmark_wc_band or {}).get("dso"),
        progress=wc_progress,
        expansion=_policy_expansion(convergence_policy, "working_capital"),
      ),
      "dpo": _blend_band(
        _days_band_from_point(current_wc_days.get("dpo"), 10.0),
        (benchmark_wc_band or {}).get("dpo"),
        progress=wc_progress,
        expansion=_policy_expansion(convergence_policy, "working_capital"),
      ),
      "inventory_days": _blend_band(
        _days_band_from_point(current_wc_days.get("inventory_days"), 12.0),
        (benchmark_wc_band or {}).get("inventory_days"),
        progress=wc_progress,
        expansion=_policy_expansion(convergence_policy, "working_capital"),
      ),
    }

    quarter_gross_margin = _lerp(current_gross_margin, benchmark_gross_margin, gross_progress)
    quarter_payroll_ratio = _lerp(current_payroll_ratio, benchmark_payroll_ratio, payroll_progress)
    quarter_opex_ratio = _lerp(current_opex_ratio, benchmark_opex_ratio, opex_progress)
    quarter_marketing_ratio = current_marketing_ratio
    quarter_capex_ratio = _lerp(current_capex_ratio, benchmark_capex_ratio, capex_progress)
    quarter_dep_ratio = _lerp(current_dep_ratio, benchmark_dep_ratio, dep_progress)
    quarter_dso = _lerp(current_wc_days.get("dso"), benchmark_dso, wc_progress)
    quarter_dpo = _lerp(current_wc_days.get("dpo"), benchmark_dpo, wc_progress)
    quarter_inventory_days = _lerp(current_wc_days.get("inventory_days"), benchmark_inventory_days, wc_progress)

    quarter_cogs = quarter_revenue * max(0.0, 1.0 - (quarter_gross_margin if quarter_gross_margin is not None else 0.0))
    quarter_payroll = quarter_revenue * max(0.0, quarter_payroll_ratio if quarter_payroll_ratio is not None else 0.0)
    quarter_marketing = quarter_revenue * max(0.0, quarter_marketing_ratio if quarter_marketing_ratio is not None else 0.0)
    quarter_opex = quarter_revenue * max(0.0, quarter_opex_ratio if quarter_opex_ratio is not None else 0.0)
    quarter_ebitda = quarter_revenue - quarter_cogs - quarter_payroll - quarter_marketing - quarter_opex
    quarter_net_income = quarter_ebitda - quarterly_interest
    quarter_capex = quarter_revenue * max(0.0, quarter_capex_ratio if quarter_capex_ratio is not None else 0.0)
    quarter_depreciation = quarter_revenue * max(0.0, quarter_dep_ratio if quarter_dep_ratio is not None else 0.0)
    quarter_ebitda_margin = (quarter_ebitda / quarter_revenue) if quarter_revenue > 0 else None
    quarter_gm_ratio = ((quarter_revenue - quarter_cogs) / quarter_revenue) if quarter_revenue > 0 else None

    working_capital_days = {
      "dso": quarter_dso,
      "dpo": quarter_dpo,
      "inventory_days": quarter_inventory_days,
    }
    violations = _quarter_violations(
      gross_margin=quarter_gm_ratio,
      ebitda_margin=quarter_ebitda_margin,
      utilization=quarter_utilization,
      realized_growth=realized_growth,
      benchmark_growth=benchmark_growth,
      growth_tolerance=growth_tolerance,
      working_capital_days=working_capital_days,
      gross_margin_band=dynamic_gross_band,
      ebitda_margin_band=dynamic_ebitda_band,
      utilization_band=dynamic_util_band,
      working_capital_band=dynamic_wc_band,
    )
    status = "within_band"
    if violations:
      if any(code.endswith("_too_high") or code == "growth_too_fast" for code in violations):
        status = "above"
      elif any(code.endswith("_too_low") or code == "working_capital_inconsistent" for code in violations):
        status = "below"

    working_capital = {
      "dso": round(quarter_dso, 2) if quarter_dso is not None else None,
      "dpo": round(quarter_dpo, 2) if quarter_dpo is not None else None,
      "inventory_days": round(quarter_inventory_days, 2) if quarter_inventory_days is not None else None,
      "ar_balance": round((quarter_revenue / 365.0) * quarter_dso, 2) if quarter_dso is not None else None,
      "ap_balance": round((quarter_cogs / 365.0) * quarter_dpo, 2) if quarter_dpo is not None else None,
      "inventory_balance": round((quarter_cogs / 365.0) * quarter_inventory_days, 2) if quarter_inventory_days is not None else None,
    }

    quarter_convergence_progress = (
      revenue_progress + gross_progress + ebitda_progress + payroll_progress + opex_progress + wc_progress
    ) / 6.0

    quarters.append(
      {
        "quarter_index": quarter_number,
        "period_label": _quarter_label(quarter_index),
        "revenue": round(quarter_revenue, 2),
        "units": round(quarter_units, 2),
        "price": round(quarter_price, 2),
        "utilization": round(quarter_utilization, 6) if quarter_utilization is not None else None,
        "payroll": round(quarter_payroll, 2),
        "marketing": round(quarter_marketing, 2),
        "opex": round(quarter_opex, 2),
        "cogs": round(quarter_cogs, 2),
        "ebitda": round(quarter_ebitda, 2),
        "net_income": round(quarter_net_income, 2),
        "working_capital": working_capital,
        "capex": round(quarter_capex, 2),
        "depreciation": round(quarter_depreciation, 2),
        "realism_check_status": status,
        "constraint_violations": violations,
        "convergence_progress": round(quarter_convergence_progress, 6),
        "lobs": _group_quarter_products(quarter_products) if product_states else [],
      }
    )

    previous_revenue = quarter_revenue
    previous_price = quarter_price

  forecast_engine_state = {
    "contract_version": PLANNING_CONTRACT_VERSION,
    "engine_version": FORECAST_ENGINE_VERSION,
    "quarter_count": FORECAST_QUARTERS,
    "benchmark_confidence_score": round(benchmark_confidence, 3),
    "fallback_level": fallback_level,
    "status": "ready",
    "starting_state": {
      "annual_revenue": round(annual_revenue, 2),
      "annual_units": round(annual_units, 2),
      "annual_cogs": round(annual_cogs, 2),
      "annual_payroll": round(annual_payroll, 2),
      "annual_marketing": round(annual_marketing, 2),
      "annual_opex": round(annual_opex, 2),
      "annual_interest": round(annual_interest, 2),
      "annual_ebitda": round(annual_ebitda, 2),
      "price": round(unit_price, 2),
      "utilization": round(utilization, 6) if utilization is not None else None,
    },
    "target_state": {
      "gross_margin": round(benchmark_gross_margin, 6) if benchmark_gross_margin is not None else None,
      "ebitda_margin": round(benchmark_ebitda_margin, 6) if benchmark_ebitda_margin is not None else None,
      "payroll_intensity": round(benchmark_payroll_ratio, 6) if benchmark_payroll_ratio is not None else None,
      "opex_intensity": round(benchmark_opex_ratio, 6) if benchmark_opex_ratio is not None else None,
      "capex_percent_revenue": round(benchmark_capex_ratio, 6) if benchmark_capex_ratio is not None else None,
      "depreciation_percent_revenue": round(benchmark_dep_ratio, 6) if benchmark_dep_ratio is not None else None,
      "dso": round(benchmark_dso, 2) if benchmark_dso is not None else None,
      "dpo": round(benchmark_dpo, 2) if benchmark_dpo is not None else None,
      "inventory_days": round(benchmark_inventory_days, 2) if benchmark_inventory_days is not None else None,
    },
    "convergence_policy": convergence_policy,
    "last_quarter_summary": quarters[-1] if quarters else {},
    "revenue_growth_path_used": growth_path,
    "traits": traits,
  }

  versions = engine_versions_payload()
  versions["forecast_engine_version"] = FORECAST_ENGINE_VERSION
  versions["convergence_policy_version"] = CONVERGENCE_POLICY_VERSION
  return {
    "forecast_engine_state": forecast_engine_state,
    "forecast_quarters": quarters,
    "engine_versions": versions,
  }
