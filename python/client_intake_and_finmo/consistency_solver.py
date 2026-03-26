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

try:
  from solver_trace import trace_lazy, trace_values  # type: ignore
except Exception:
  from client_intake_and_finmo.solver_trace import trace_lazy, trace_values  # type: ignore


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
HIRE_DELAY_STEPS_MONTHS: Tuple[int, ...] = (3, 6, 9, 12, 15, 18, 24)
MAX_SCENARIOS = 3
ROLE_WAGE_MIN_FACTOR = _float_env("CONSISTENCY_ROLE_WAGE_MIN_FACTOR", 0.85)
ROLE_WAGE_MAX_FACTOR = _float_env("CONSISTENCY_ROLE_WAGE_MAX_FACTOR", 1.00)
MAX_ROLE_DELAY_MONTHS = max(12, int(round(_float_env("CONSISTENCY_SOLVER_MAX_ROLE_DELAY_MONTHS", 24.0))))
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
CHILD_PRODUCT_SPREAD_WEIGHT = _float_env("CONSISTENCY_SOLVER_CHILD_PRODUCT_SPREAD_WEIGHT", 0.6)
HEALTHY_EBITDA_MARGIN_RATIO = _float_env("CONSISTENCY_SOLVER_HEALTHY_EBITDA_MARGIN_RATIO", 0.05)
EBITDA_CUSHION_PREFERENCE_WEIGHT = _float_env("CONSISTENCY_SOLVER_EBITDA_CUSHION_WEIGHT", 1.5)
OPTION_OBJECTIVE_TOLERANCE_RATIO = _float_env("CONSISTENCY_SOLVER_OPTION_TOLERANCE_RATIO", 0.03)
OPTION_OBJECTIVE_TOLERANCE_ABS = _float_env("CONSISTENCY_SOLVER_OPTION_TOLERANCE_ABS", 0.05)
REALISM_DISTANCE_TOLERANCE = _float_env("CONSISTENCY_SOLVER_REALISM_DISTANCE_TOLERANCE", 0.001)
SOLVER_DISTANCE_REGRESSION_TOLERANCE = _float_env("CONSISTENCY_SOLVER_DISTANCE_REGRESSION_TOLERANCE", 0.10)
EBITDA_TARGET_TOLERANCE_RATIO = _float_env("CONSISTENCY_SOLVER_EBITDA_TARGET_TOLERANCE_RATIO", 0.001)
EBITDA_TARGET_TOLERANCE_ABS = _float_env("CONSISTENCY_SOLVER_EBITDA_TARGET_TOLERANCE_ABS", 250.0)
NONBLOCKING_VIOLATION_PENALTY = _float_env("CONSISTENCY_SOLVER_NONBLOCKING_VIOLATION_PENALTY", 15000.0)
UNRESOLVED_BLOCKING_SCENARIO_LIMIT = max(0, int(round(_float_env("CONSISTENCY_SOLVER_UNRESOLVED_BLOCKING_LIMIT", 1.0))))
EBITDA_SELECTION_TIEBREAKER_WEIGHT = _float_env("CONSISTENCY_SOLVER_EBITDA_SELECTION_WEIGHT", 0.001)
NET_INCOME_SELECTION_TIEBREAKER_WEIGHT = _float_env("CONSISTENCY_SOLVER_NET_INCOME_SELECTION_WEIGHT", 0.00001)
EBITDA_GAP_SELECTION_TIEBREAKER_WEIGHT = _float_env("CONSISTENCY_SOLVER_EBITDA_GAP_SELECTION_WEIGHT", 0.0001)

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
  "viability_stabilize": {
    "archetype": "operations",
    "display": "Operational balance",
    "tradeoff": "keeps the original plan intact with small targeted changes that improve Year-1 viability",
  },
}

DEFAULT_HARD_YEAR1_VIOLATIONS = {
  "capacity_unsupported",
  "payroll_too_light",
  "utilization_too_low",
}
VIABILITY_OPERATING_EBITDA_MARGIN_FLOOR = _float_env("CONSISTENCY_SOLVER_VIABILITY_OPERATING_MARGIN_FLOOR", -0.02)
VIABILITY_STARTUP_EBITDA_MARGIN_FLOOR = _float_env("CONSISTENCY_SOLVER_VIABILITY_STARTUP_MARGIN_FLOOR", -0.08)
VIABILITY_DEFAULT_EBITDA_MARGIN_FLOOR = _float_env("CONSISTENCY_SOLVER_VIABILITY_DEFAULT_MARGIN_FLOOR", -0.04)
VIABILITY_TARGET_TOLERANCE_RATIO = _float_env("CONSISTENCY_SOLVER_VIABILITY_TOLERANCE_RATIO", 0.002)
VIABILITY_TARGET_TOLERANCE_ABS = _float_env("CONSISTENCY_SOLVER_VIABILITY_TOLERANCE_ABS", 100.0)


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
  target_tolerance = max(EBITDA_TARGET_TOLERANCE_ABS, revenue * EBITDA_TARGET_TOLERANCE_RATIO)
  return _range_distance(
    ebitda,
    min_value=(None if target_ebitda_min is None else (target_ebitda_min - target_tolerance)),
    max_value=(None if target_ebitda_max is None else (target_ebitda_max + target_tolerance)),
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
  hard_codes: List[str] = []
  soft_codes: List[str] = []
  context_codes: List[str] = []
  class_map = _violation_class_map(constraint_engine_state)
  current_metrics = state.get("current_metrics") if isinstance(state, dict) else {}
  current_metrics = current_metrics if isinstance(current_metrics, dict) else {}
  hard_util_floor = _safe_float(current_metrics.get("hard_utilization_floor"))
  structural_payroll_floor = max(0.0, _safe_float(current_metrics.get("structural_payroll_floor")))

  def _maybe_add(code: str) -> None:
    if code not in codes:
      codes.append(code)
      constraint_class = class_map.get(code, "soft")
      if constraint_class == "hard":
        hard_codes.append(code)
      elif constraint_class == "context":
        context_codes.append(code)
      else:
        soft_codes.append(code)

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
  required_structural_payroll = _required_structural_payroll_from_metrics(
    current_metrics=current_metrics,
    units=units,
  )
  if required_structural_payroll > 0 and payroll < (required_structural_payroll * 0.97):
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
  if hard_util_floor is not None and utilization is not None and units > 0 and utilization < (hard_util_floor - REALISM_DISTANCE_TOLERANCE):
    _maybe_add("utilization_too_low")
  return {
    "all": codes,
    "blocking": list(dict.fromkeys(hard_codes)),
    "hard": list(dict.fromkeys(hard_codes)),
    "soft": list(dict.fromkeys(soft_codes)),
    "context": list(dict.fromkeys(context_codes)),
  }


def _loss_pct(summary: Dict[str, Any]) -> float:
  revenue = _safe_float((summary or {}).get("revenue"))
  net_income = _safe_float((summary or {}).get("net_income"))
  if revenue <= 0:
    return 0.0 if net_income >= 0 else 1.0
  return max(0.0, -net_income / revenue)


def _solver_required(summary: Dict[str, Any], constraint_engine_state: Optional[Dict[str, Any]] = None) -> bool:
  del summary, constraint_engine_state
  # Consistency is now a continuous realism-governance step, not a conditional
  # repair step. GPT + solver should run for every business and every quarter.
  return True


def _strategy_case_severity(
  *,
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_forecast_bundle: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
  summary = baseline_summary if isinstance(baseline_summary, dict) else {}
  revenue = max(0.0, _safe_float(summary.get("revenue")))
  ebitda = _safe_float(summary.get("ebitda"))
  gross_profit = _safe_float(summary.get("gross_profit"))
  ebitda_margin = (ebitda / revenue) if revenue > 0 else (-1.0 if ebitda < 0 else 0.0)
  gross_margin = (gross_profit / revenue) if revenue > 0 else 0.0
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  hard_count = len(_blocking_constraint_violations(state))
  all_violations = [
    str(code or "").strip()
    for code in (state.get("violations") or [])
    if str(code or "").strip()
  ]
  gross_margin_band = state.get("gross_margin_band") if isinstance(state, dict) else {}
  gross_min = _band_min(gross_margin_band)
  year3_margin = _forecast_year_metric(baseline_forecast_bundle, 3, "ebitda_margin")
  year5_margin = _forecast_year_metric(baseline_forecast_bundle, 5, "ebitda_margin")

  score = 0.0
  reasons: List[str] = []
  if ebitda_margin <= -1.0:
    score += 0.9
    reasons.append("year1_ebitda_margin_extreme_negative")
  elif ebitda_margin <= -0.6:
    score += 0.75
    reasons.append("year1_ebitda_margin_severely_negative")
  elif ebitda_margin <= -0.3:
    score += 0.45
    reasons.append("year1_ebitda_margin_materially_negative")
  elif ebitda_margin <= -0.1:
    score += 0.2
    reasons.append("year1_ebitda_margin_negative")

  if gross_min is not None and gross_margin < gross_min:
    gap = gross_min - gross_margin
    if gap >= 0.12:
      score += 0.3
      reasons.append("gross_margin_far_below_band")
    elif gap >= 0.05:
      score += 0.15
      reasons.append("gross_margin_below_band")

  if hard_count >= 2:
    score += 0.2
    reasons.append("multiple_hard_violations")
  elif hard_count == 1:
    score += 0.1
    reasons.append("hard_violation_present")

  if len(all_violations) >= 4:
    score += 0.1
    reasons.append("multiple_total_violations")

  if year3_margin is not None and year3_margin < ebitda_margin - 0.02:
    score += 0.1
    reasons.append("year3_path_degrades")
  if year5_margin is not None and year3_margin is not None and year5_margin < year3_margin - 0.02:
    score += 0.1
    reasons.append("outer_year_path_degrades")

  if score >= 0.75:
    severity_class = "severe"
    minimum_meaningful_levers = 4
    minimum_package_count = 2
    minimum_package_strength = "strong"
  elif score >= 0.4:
    severity_class = "moderate"
    minimum_meaningful_levers = 3
    minimum_package_count = 2
    minimum_package_strength = "moderate"
  else:
    severity_class = "mild"
    minimum_meaningful_levers = 2
    minimum_package_count = 1
    minimum_package_strength = "light"

  return {
    "severity_class": severity_class,
    "severity_score": round(score, 4),
    "severity_reason": ", ".join(reasons) if reasons else "baseline_within_expected_realism_range",
    "minimum_meaningful_levers": minimum_meaningful_levers,
    "minimum_package_count": minimum_package_count,
    "minimum_package_strength": minimum_package_strength,
  }


def _viability_margin_floor(normalized_traits: Optional[Dict[str, Any]]) -> float:
  traits = normalized_traits if isinstance(normalized_traits, dict) else {}
  stage = str(traits.get("business_stage") or "").strip().lower()
  if stage in {"startup", "pre_launch", "pre-launch", "launch", "early"}:
    return VIABILITY_STARTUP_EBITDA_MARGIN_FLOOR
  if stage in {"operating", "mature", "established"}:
    return VIABILITY_OPERATING_EBITDA_MARGIN_FLOOR
  return VIABILITY_DEFAULT_EBITDA_MARGIN_FLOOR


def _viability_adjustment_required(
  summary: Dict[str, Any],
  *,
  constraint_engine_state: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]],
) -> Tuple[bool, Optional[float], Optional[float]]:
  if _blocking_constraint_violations(constraint_engine_state):
    return False, None, None
  revenue = max(0.0, _safe_float((summary or {}).get("revenue")))
  if revenue <= 0:
    return False, None, None
  ebitda = _safe_float((summary or {}).get("ebitda"))
  viability_margin_floor = _viability_margin_floor(normalized_traits)
  viability_target = revenue * viability_margin_floor
  if ebitda >= viability_target:
    return False, viability_target, viability_margin_floor
  return True, viability_target, viability_margin_floor


def _blocking_constraint_violations(constraint_engine_state: Optional[Dict[str, Any]]) -> List[str]:
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  explicit = [
    str(code or "").strip()
    for code in (state.get("hard_violation_codes") or [])
    if str(code or "").strip()
  ]
  if explicit:
    return explicit
  return [
    str(code or "").strip()
    for code in (state.get("violations") or [])
    if str(code or "").strip() in DEFAULT_HARD_YEAR1_VIOLATIONS
  ]


def _violation_class_map(constraint_engine_state: Optional[Dict[str, Any]]) -> Dict[str, str]:
  state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  mapping: Dict[str, str] = {}
  for code in state.get("hard_violation_codes") or []:
    clean = str(code or "").strip()
    if clean:
      mapping[clean] = "hard"
  for code in state.get("soft_violation_codes") or []:
    clean = str(code or "").strip()
    if clean and clean not in mapping:
      mapping[clean] = "soft"
  for code in state.get("context_violation_codes") or []:
    clean = str(code or "").strip()
    if clean and clean not in mapping:
      mapping[clean] = "context"
  if not mapping:
    for code in state.get("violations") or []:
      clean = str(code or "").strip()
      if not clean:
        continue
      mapping[clean] = "hard" if clean in DEFAULT_HARD_YEAR1_VIOLATIONS else "soft"
  return mapping


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
    months_until_hire = max(0, _safe_int(role.get("months_until_hire")) or 0)
    active_months = max(0, 12 - months_until_hire)
    total += annual_wage * (active_months / 12.0)
  return round(total, 2)


def _role_month_support_profile(roles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
  baseline_adjustable_active_months = 0.0
  adjustable_role_month_cost_floor_total = 0.0
  role_month_shares: List[Dict[str, float]] = []
  for role in roles:
    if not isinstance(role, dict):
      continue
    role_title = str(role.get("role_title") or "").strip()
    base_months = max(0, min(12, _safe_int(role.get("base_months")) or 0))
    baseline_active_months = max(0.0, 12.0 - float(base_months))
    wage_floor = max(
      0.0,
      _safe_float(role.get("wage_floor")) or _safe_float(role.get("annual_wage")),
    )
    if not role_title or baseline_active_months <= 0 or wage_floor <= 0:
      continue
    monthly_wage_floor = wage_floor / 12.0
    baseline_adjustable_active_months += baseline_active_months
    adjustable_role_month_cost_floor_total += monthly_wage_floor * baseline_active_months
    role_month_shares.append(
      {
        "role_title": role_title,
        "baseline_active_months": baseline_active_months,
        "monthly_wage_floor": monthly_wage_floor,
      }
    )
  if baseline_adjustable_active_months > 0:
    for item in role_month_shares:
      item["month_share"] = max(
        0.0,
        _safe_float(item.get("baseline_active_months")) / baseline_adjustable_active_months,
      )
  return {
    "baseline_adjustable_active_months": baseline_adjustable_active_months,
    "baseline_adjustable_payroll_total": adjustable_role_month_cost_floor_total,
    "adjustable_role_month_cost_floor": (
      adjustable_role_month_cost_floor_total / baseline_adjustable_active_months
      if baseline_adjustable_active_months > 0
      else 0.0
    ),
    "role_month_shares": role_month_shares,
  }


def _effective_solver_role_grounding(
  *,
  fixed_people_payroll: float,
  current_payroll_total: float,
  role_month_support: Dict[str, Any],
) -> Dict[str, float]:
  fixed_people_payroll = max(0.0, _safe_float(fixed_people_payroll))
  current_payroll_total = max(0.0, _safe_float(current_payroll_total))
  baseline_adjustable_active_months = max(
    0.0,
    _safe_float((role_month_support or {}).get("baseline_adjustable_active_months")),
  )
  baseline_adjustable_payroll_total = max(
    0.0,
    _safe_float((role_month_support or {}).get("baseline_adjustable_payroll_total")),
  )
  adjustable_role_month_cost_floor = max(
    0.0,
    _safe_float((role_month_support or {}).get("adjustable_role_month_cost_floor")),
  )

  effective_fixed_people_payroll = fixed_people_payroll
  effective_planned_payroll = baseline_adjustable_payroll_total
  effective_adjustable_active_months = baseline_adjustable_active_months
  role_activation_ratio = 1.0 if baseline_adjustable_payroll_total > 0 else 0.0

  if current_payroll_total > 0:
    effective_fixed_people_payroll = min(fixed_people_payroll, current_payroll_total)
    if baseline_adjustable_payroll_total > 0:
      effective_planned_payroll = max(
        0.0,
        min(
          baseline_adjustable_payroll_total,
          current_payroll_total - effective_fixed_people_payroll,
        ),
      )
      role_activation_ratio = max(
        0.0,
        min(1.0, effective_planned_payroll / baseline_adjustable_payroll_total),
      )
      effective_adjustable_active_months = baseline_adjustable_active_months * role_activation_ratio
    else:
      effective_planned_payroll = 0.0
      effective_adjustable_active_months = 0.0
      role_activation_ratio = 0.0

  return {
    "effective_fixed_people_payroll": effective_fixed_people_payroll,
    "effective_planned_payroll": effective_planned_payroll,
    "effective_adjustable_active_months": effective_adjustable_active_months,
    "role_activation_ratio": role_activation_ratio,
    "adjustable_role_month_cost_floor": (
      effective_planned_payroll / effective_adjustable_active_months
      if effective_adjustable_active_months > 0
      else adjustable_role_month_cost_floor
    ),
  }


def _required_structural_payroll_from_metrics(
  *,
  current_metrics: Dict[str, Any],
  units: float,
) -> float:
  metrics = current_metrics if isinstance(current_metrics, dict) else {}
  people_payroll_floor = max(0.0, _safe_float(metrics.get("people_payroll_floor")))
  structural_payroll_floor = max(
    people_payroll_floor,
    _safe_float(metrics.get("structural_payroll_floor")),
  )
  support_basis = str(metrics.get("payroll_support_basis") or "").strip().lower()
  units_per_active_role_month = max(
    0.0,
    _safe_float(metrics.get("units_per_active_role_month")),
  )
  fixed_active_role_months = max(
    0.0,
    _safe_float(metrics.get("fixed_active_role_months")),
  )
  adjustable_role_month_cost_floor = max(
    0.0,
    _safe_float(metrics.get("adjustable_role_month_cost_floor")),
  )
  units_per_payroll_dollar = max(
    0.0,
    _safe_float(metrics.get("units_per_payroll_dollar")),
  )

  if support_basis == "role_months" and units_per_active_role_month > 0 and adjustable_role_month_cost_floor > 0:
    required_adjustable_active_months = max(
      0.0,
      (max(0.0, units) / units_per_active_role_month) - fixed_active_role_months,
    )
    return max(
      structural_payroll_floor,
      people_payroll_floor + (adjustable_role_month_cost_floor * required_adjustable_active_months),
    )
  if support_basis == "payroll" and units_per_payroll_dollar > 0:
    return max(
      structural_payroll_floor,
      max(0.0, units) / units_per_payroll_dollar,
    )
  return structural_payroll_floor


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
  util = _normalize_ratio(product_basis.get("utilization_rate"))
  if unit_price <= 0 or periods <= 0:
    return False
  if capacity <= 0:
    return False
  if util is None:
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
  solver_locked_payroll_total = None
  if isinstance(financials_patch, dict):
    if financials_patch.get("payroll_total_year1") is not None:
      solver_locked_payroll_total = max(0.0, _safe_float(financials_patch.get("payroll_total_year1")))
    elif financials_patch.get("current_payroll") is not None:
      solver_locked_payroll_total = max(0.0, _safe_float(financials_patch.get("current_payroll")))
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
  if solver_locked_payroll_total is not None:
    baseline_payroll = max(0.0, _safe_float(next_financials.get("baseline_payroll_year1")))
    next_financials["payroll_total_year1"] = round(solver_locked_payroll_total, 2)
    next_financials["current_payroll"] = round(solver_locked_payroll_total, 2)
    next_financials["payroll_adjustment"] = round(solver_locked_payroll_total - baseline_payroll, 2)

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


def _build_modified_state(
  *,
  baseline_state: Dict[str, Any],
  exact_patches: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  next_ops, next_people, next_financials, next_year1, next_marketing_model = _apply_exact_patches(
    ops_json=baseline_state.get("ops_json") or {},
    people_json=baseline_state.get("people_json") or {},
    financials_json=baseline_state.get("financials_json") or {},
    financials_year1_json=baseline_state.get("financials_year1_json") or {},
    marketing_model_json=baseline_state.get("marketing_model_json") or marketing_model_json or {},
    exact_patches=exact_patches,
  )
  return {
    "ops_json": next_ops,
    "people_json": next_people,
    "financials_json": next_financials,
    "financials_year1_json": next_year1,
    "marketing_model_json": next_marketing_model,
    "exact_patches": _clone(exact_patches or {}),
  }


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


def _derive_scenario_posture(candidate: Dict[str, Any]) -> Dict[str, str]:
  candidate = candidate if isinstance(candidate, dict) else {}
  lever_summary = candidate.get("lever_summary") if isinstance(candidate.get("lever_summary"), dict) else {}
  raw_moves = lever_summary.get("raw_family_moves") if isinstance(lever_summary, dict) else {}
  raw_moves = raw_moves if isinstance(raw_moves, dict) else {}
  meaningful_families = {
    str(item or "").strip()
    for item in (candidate.get("meaningful_families") or candidate.get("lever_families") or [])
    if str(item or "").strip()
  }
  baseline_units = max(
    0.0,
    _safe_float(candidate.get("baseline_required_units")),
    _safe_float(candidate.get("baseline_expected_units")),
  )
  scenario_units = max(
    0.0,
    _safe_float(candidate.get("scenario_required_units")),
    _safe_float(candidate.get("scenario_expected_units")),
  )
  baseline_revenue = max(0.0, _safe_float(candidate.get("baseline_revenue")))
  scenario_revenue = max(0.0, _safe_float(candidate.get("scenario_revenue")))
  unit_change_ratio = (
    ((scenario_units - baseline_units) / max(baseline_units, 1.0))
    if max(baseline_units, scenario_units) > 0
    else 0.0
  )
  revenue_change_ratio = (
    ((scenario_revenue - baseline_revenue) / max(baseline_revenue, 1.0))
    if max(baseline_revenue, scenario_revenue) > 0
    else 0.0
  )

  marketing_up = _safe_float(raw_moves.get("marketing_up"))
  marketing_down = _safe_float(raw_moves.get("marketing_down"))
  if marketing_up <= 0 and marketing_down <= 0 and "marketing" in meaningful_families:
    marketing_up = 0.08 if scenario_units >= baseline_units else 0.0
    marketing_down = 0.08 if scenario_units < baseline_units else 0.0
  payroll_up = _safe_float(raw_moves.get("payroll_up"))
  payroll_down = _safe_float(raw_moves.get("payroll_down"))
  if payroll_up <= 0 and payroll_down <= 0 and "payroll" in meaningful_families:
    payroll_up = 0.06
  hire_advance = _safe_float(raw_moves.get("hire_advance"))
  hire_delay = _safe_float(raw_moves.get("hire_delay"))
  if hire_advance <= 0 and hire_delay <= 0 and "hire_delay" in meaningful_families:
    hire_advance = 0.05
  util_up = _safe_float(raw_moves.get("util_up"))
  util_down = _safe_float(raw_moves.get("util_down"))
  if util_up <= 0 and util_down <= 0 and "utilization" in meaningful_families:
    util_up = 0.05
  cost_tighten_signal = (
    _safe_float(raw_moves.get("other_opex_down"))
    + _safe_float(raw_moves.get("cogs_down"))
    + payroll_down
  )
  cost_protect_signal = (
    _safe_float(raw_moves.get("other_opex_up"))
    + _safe_float(raw_moves.get("cogs_up"))
    + payroll_up
    + marketing_up
  )
  if cost_tighten_signal <= 0 and meaningful_families.intersection({"other_opex", "cogs"}):
    cost_tighten_signal = 0.08

  if unit_change_ratio >= 0.03 or revenue_change_ratio >= 0.03 or marketing_up > marketing_down + 0.02:
    demand_posture = "preserve"
  elif unit_change_ratio <= -0.03 or revenue_change_ratio <= -0.03 or marketing_down > marketing_up + 0.03:
    demand_posture = "reduce"
  else:
    demand_posture = "moderate"

  if (payroll_up + hire_advance) > (payroll_down + hire_delay) + 0.03:
    staffing_posture = "add_support"
  elif (payroll_down + hire_delay) > (payroll_up + hire_advance) + 0.03:
    staffing_posture = "delay"
  elif meaningful_families.intersection({"payroll", "hire_delay", "utilization"}):
    staffing_posture = "rebalance"
  else:
    staffing_posture = "hold"

  if cost_tighten_signal > cost_protect_signal + 0.04:
    cost_posture = "tighten"
  elif cost_protect_signal > cost_tighten_signal + 0.04:
    cost_posture = "protect"
  else:
    cost_posture = "moderate"

  return {
    "demand_posture": demand_posture,
    "staffing_posture": staffing_posture,
    "cost_posture": cost_posture,
  }


def _derive_structured_tradeoff(
  *,
  archetype: str,
  demand_posture: str,
  staffing_posture: str,
  cost_posture: str,
  meaningful_families: Sequence[str],
) -> str:
  families = {
    str(item or "").strip()
    for item in (meaningful_families or [])
    if str(item or "").strip()
  }
  if archetype == "growth":
    if staffing_posture == "add_support":
      return "preserves more Year-1 demand by adding support capacity behind the plan"
    if "marketing" in families:
      return "keeps more Year-1 demand in place and accepts support spend where it remains credible"
    return "leans toward preserving Year-1 volume without breaking delivery realism"
  if archetype == "efficiency":
    if cost_posture == "tighten":
      return "accepts a tighter cost posture and some revenue moderation to improve margin quality"
    return "leans into cleaner Year-1 economics instead of preserving every unit"
  if staffing_posture in {"add_support", "rebalance"}:
    return "rebalances staffing, workload, and throughput so the Year-1 plan is believable"
  if demand_posture == "reduce":
    return "moderates Year-1 demand to bring delivery and support back into line"
  return "balances workload, staffing, and throughput without leaning too hard on cost cuts or demand push"


def _archetype_consistency(candidate: Dict[str, Any]) -> Dict[str, Any]:
  candidate = candidate if isinstance(candidate, dict) else {}
  archetype = str(candidate.get("archetype") or "").strip()
  lever_summary = candidate.get("lever_summary") if isinstance(candidate.get("lever_summary"), dict) else {}
  dominant_family = str((lever_summary or {}).get("dominant_family") or "").strip()
  meaningful_families = {
    str(item or "").strip()
    for item in (candidate.get("meaningful_families") or candidate.get("lever_families") or [])
    if str(item or "").strip()
  }
  demand_posture = str(candidate.get("demand_posture") or "").strip()
  staffing_posture = str(candidate.get("staffing_posture") or "").strip()
  cost_posture = str(candidate.get("cost_posture") or "").strip()
  dominant_family_share = max(
    0.0,
    _safe_float(candidate.get("dominant_family_share"))
    or _safe_float((lever_summary or {}).get("dominant_family_share")),
  )
  coordination_issues = {
    str(item or "").strip()
    for item in ((candidate.get("coordination_issues") or []) or ((lever_summary or {}).get("coordination_issues") or []))
    if str(item or "").strip()
  }

  score = 0.0
  issues: List[str] = []
  if archetype == "growth":
    if demand_posture == "preserve":
      score += 2.5
    else:
      issues.append("growth_not_preserving_demand")
    if staffing_posture in {"add_support", "rebalance"}:
      score += 1.5
    if meaningful_families.intersection({"marketing", "utilization", "price"}):
      score += 1.0
    if cost_posture == "tighten" and not meaningful_families.intersection({"marketing", "utilization", "price"}):
      issues.append("growth_cost_story")
    if dominant_family in {"other_opex", "cogs"} and demand_posture != "preserve":
      issues.append("archetype_mismatch")
    if not meaningful_families.intersection({"marketing", "utilization", "price"}):
      issues.append("growth_missing_demand_lever")
    if staffing_posture not in {"add_support", "rebalance"}:
      issues.append("growth_missing_staffing_support")
  elif archetype == "efficiency":
    if cost_posture == "tighten":
      score += 2.5
    else:
      issues.append("efficiency_not_cost_led")
    if demand_posture in {"moderate", "reduce"}:
      score += 1.0
    if meaningful_families.intersection({"other_opex", "cogs", "payroll"}):
      score += 1.0
    if demand_posture == "preserve" and meaningful_families.intersection({"marketing", "utilization"}):
      issues.append("efficiency_growth_story")
    if dominant_family == "marketing":
      issues.append("archetype_mismatch")
    if not meaningful_families.intersection({"other_opex", "cogs", "payroll"}):
      issues.append("efficiency_missing_cost_lever")
    if not meaningful_families.intersection({"utilization", "payroll", "hire_delay", "price"}):
      issues.append("efficiency_missing_structure")
  else:
    if staffing_posture in {"add_support", "rebalance", "delay"}:
      score += 2.0
    else:
      issues.append("operations_not_staffing_led")
    if meaningful_families.intersection({"utilization", "payroll", "hire_delay"}):
      score += 1.5
    if demand_posture == "moderate":
      score += 1.0
    if dominant_family in {"marketing", "other_opex"} and not meaningful_families.intersection({"utilization", "payroll", "hire_delay"}):
      issues.append("operations_absorber_story")
      issues.append("archetype_mismatch")
    if not meaningful_families.intersection({"utilization", "payroll", "hire_delay"}):
      issues.append("operations_missing_structural_lever")
    if len(meaningful_families) < 2:
      issues.append("operations_missing_balance_lever")

  if dominant_family_share > 0.72 and len(meaningful_families) < 3:
    issues.append("single_lever_dominance")
  if coordination_issues:
    issues.extend(sorted(coordination_issues))

  return {
    "archetype_consistency_score": round(score, 4),
    "archetype_consistency_issues": list(dict.fromkeys(issues)),
  }


def _enrich_candidate_strategy(candidate: Dict[str, Any]) -> Dict[str, Any]:
  candidate = dict(candidate or {})
  if not isinstance(candidate.get("lever_summary"), dict):
    candidate["lever_summary"] = _build_lever_summary(
      exact_patches=candidate.get("exact_patches") or {},
      family_raw_components=candidate.get("family_raw_components") or {},
    )
  if not candidate.get("meaningful_families"):
    merged_families = list(
      dict.fromkeys(
        [
          str(item or "").strip()
          for item in (
            list((candidate.get("lever_summary") or {}).get("meaningful_families") or [])
            + list(candidate.get("lever_families") or [])
          )
          if str(item or "").strip()
        ]
      )
    )
    candidate["meaningful_families"] = merged_families
  lever_count_floor = len(candidate.get("meaningful_families") or [])
  lever_count_current = int(max(0, _safe_int(candidate.get("meaningful_lever_count")) or 0))
  lever_count_summary = int(max(0, _safe_int((candidate.get("lever_summary") or {}).get("meaningful_lever_count")) or 0))
  candidate["meaningful_lever_count"] = max(lever_count_current, lever_count_summary, lever_count_floor)
  if candidate.get("coordination_score") is None:
    candidate["coordination_score"] = _safe_float((candidate.get("lever_summary") or {}).get("coordination_score"))
  if candidate.get("dominant_family_share") is None:
    candidate["dominant_family_share"] = _safe_float((candidate.get("lever_summary") or {}).get("dominant_family_share"))
  if candidate.get("aligned_pair_count") is None:
    candidate["aligned_pair_count"] = int(max(0, _safe_int((candidate.get("lever_summary") or {}).get("aligned_pair_count")) or 0))
  if candidate.get("coordination_issues") is None:
    candidate["coordination_issues"] = list((candidate.get("lever_summary") or {}).get("coordination_issues") or [])
  candidate.update(_derive_scenario_posture(candidate))
  if not str(candidate.get("dominant_tradeoff") or "").strip():
    candidate["dominant_tradeoff"] = _derive_structured_tradeoff(
      archetype=str(candidate.get("archetype") or "").strip(),
      demand_posture=str(candidate.get("demand_posture") or "").strip(),
      staffing_posture=str(candidate.get("staffing_posture") or "").strip(),
      cost_posture=str(candidate.get("cost_posture") or "").strip(),
      meaningful_families=candidate.get("meaningful_families") or [],
    )
  candidate.update(_archetype_consistency(candidate))
  return candidate


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
  )


def _allowed_realism_distance(
  *,
  baseline_distance: float,
  allow_realism_relaxation: bool,
  baseline_blocking_count: int,
) -> float:
  allowed_distance = baseline_distance + REALISM_DISTANCE_TOLERANCE
  if baseline_blocking_count > 0:
    # Clearing a hard structural contradiction can temporarily worsen soft-band
    # distance; allow that trade while the solver searches for a viable repair.
    allowed_distance = max(
      allowed_distance,
      baseline_distance + 0.12 + (0.03 * min(baseline_blocking_count, 3)),
    )
  if allow_realism_relaxation and baseline_blocking_count <= 0:
    allowed_distance = max(
      allowed_distance,
      baseline_distance + max(0.08, 0.25 * baseline_distance),
    )
  return allowed_distance


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
  scenario_constraint_engine_state: Optional[Dict[str, Any]] = None,
  baseline_realism_distance: Optional[float] = None,
  target_ebitda_min: Optional[float] = None,
  target_ebitda_max: Optional[float] = None,
  allow_realism_relaxation: bool = False,
) -> Optional[Dict[str, Any]]:
  modified_state = _build_modified_state(
    baseline_state=baseline_state,
    exact_patches=exact_patches,
    marketing_model_json=marketing_model_json,
  )
  next_ops = modified_state.get("ops_json") if isinstance(modified_state.get("ops_json"), dict) else {}
  next_people = modified_state.get("people_json") if isinstance(modified_state.get("people_json"), dict) else {}
  next_financials = modified_state.get("financials_json") if isinstance(modified_state.get("financials_json"), dict) else {}
  next_year1 = modified_state.get("financials_year1_json") if isinstance(modified_state.get("financials_year1_json"), dict) else {}
  next_marketing_model = modified_state.get("marketing_model_json") if isinstance(modified_state.get("marketing_model_json"), dict) else {}
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
    trace_lazy(
      "CONSISTENCY",
      f"Candidate {scenario_id} rejected by scenario violations",
      lambda: {
        "scenario_id": scenario_id,
        "label": label,
        "violations": violations,
        "exact_patches": exact_patches,
      },
    )
    return None
  baseline_net_income = _safe_float(baseline_summary.get("net_income"))
  next_net_income = _safe_float(summary.get("net_income"))
  improvement = next_net_income - baseline_net_income
  baseline_required_units = _required_units_year1((baseline_state or {}).get("financials_year1_json") or {})
  baseline_expected_units = max(
    0.0,
    _safe_float((((baseline_state or {}).get("marketing_model_json") or marketing_model_json or {}) if isinstance((baseline_state or {}).get("marketing_model_json") or marketing_model_json or {}, dict) else {}).get("expected_units_year1")),
  )
  scenario_required_units = _required_units_year1(next_year1 or {})
  scenario_expected_units = max(0.0, _safe_float((next_marketing_model or {}).get("expected_units_year1")))
  baseline_distance = (
    max(0.0, _safe_float(baseline_realism_distance))
    if baseline_realism_distance is not None
    else 0.0
  )
  next_distance = _constraint_engine_realism_distance(
    constraint_engine_state=scenario_constraint_engine_state or constraint_engine_state,
    summary=summary,
    year1_json=next_year1,
    ops_json=next_ops,
  )
  remaining_violations = _scenario_realism_violations(
    constraint_engine_state=scenario_constraint_engine_state or constraint_engine_state,
    summary=summary,
    year1_json=next_year1,
    ops_json=next_ops,
  )
  remaining_blocking = list(remaining_violations.get("hard") or remaining_violations.get("blocking") or [])
  all_remaining = list(remaining_violations.get("all") or [])
  baseline_blocking_count = len(_blocking_constraint_violations(constraint_engine_state))
  target_distance = 0.0
  if constraint_engine_state:
    if remaining_blocking:
      trace_lazy(
        "CONSISTENCY",
        f"Candidate {scenario_id} rejected by hard violations",
        lambda: {
          "scenario_id": scenario_id,
          "label": label,
          "remaining_blocking": remaining_blocking,
          "remaining_violations": all_remaining,
          "summary": summary,
          "realism_distance": next_distance,
          "target_distance": target_distance,
        },
      )
      return None
    allowed_distance = _allowed_realism_distance(
      baseline_distance=baseline_distance,
      allow_realism_relaxation=allow_realism_relaxation,
      baseline_blocking_count=baseline_blocking_count,
    )
    if next_distance > allowed_distance:
      trace_lazy(
        "CONSISTENCY",
        f"Candidate {scenario_id} rejected by realism tolerance",
        lambda: {
          "scenario_id": scenario_id,
          "label": label,
          "realism_distance": next_distance,
          "baseline_realism_distance": baseline_distance,
          "tolerance": REALISM_DISTANCE_TOLERANCE,
          "allowed_distance": allowed_distance,
          "allow_realism_relaxation": allow_realism_relaxation,
          "summary": summary,
        },
      )
      return None
    if allow_realism_relaxation and next_distance > (baseline_distance + REALISM_DISTANCE_TOLERANCE):
      trace_lazy(
        "CONSISTENCY",
        f"Candidate {scenario_id} accepted with viability realism flex",
        lambda: {
          "scenario_id": scenario_id,
          "label": label,
          "realism_distance": next_distance,
          "baseline_realism_distance": baseline_distance,
          "allowed_distance": allowed_distance,
          "summary": summary,
        },
      )
  elif improvement <= 0:
    trace_lazy(
      "CONSISTENCY",
      f"Candidate {scenario_id} rejected by no improvement",
      lambda: {
        "scenario_id": scenario_id,
        "label": label,
        "improvement_amount": improvement,
        "baseline_net_income": baseline_net_income,
        "scenario_net_income": next_net_income,
        "summary": summary,
      },
    )
    return None

  disruption_score = _candidate_disruption_score(exact_patches)
  is_break_even = _is_break_even_ebitda(summary)
  ebitda_gap = _ebitda_gap(summary)
  lever_summary = _build_lever_summary(exact_patches=exact_patches)

  candidate_payload = {
    "scenario_id": scenario_id,
    "label": label,
    "rationale": rationale,
    "lever_families": list(lever_families),
    "exact_patches": exact_patches,
    "summary": summary,
    "modified_state": modified_state,
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
    "baseline_required_units": baseline_required_units,
    "baseline_expected_units": baseline_expected_units,
    "scenario_required_units": scenario_required_units,
    "scenario_expected_units": scenario_expected_units,
    "baseline_revenue": _safe_float(baseline_summary.get("revenue")),
    "scenario_revenue": _safe_float(summary.get("revenue")),
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
  trace_lazy(
    "CONSISTENCY",
    f"Candidate {scenario_id} accepted",
    lambda: {
      "scenario_id": scenario_id,
      "label": label,
      "summary": summary,
      "improvement_amount": improvement,
      "realism_distance": next_distance,
      "target_distance": target_distance,
      "remaining_violations": all_remaining,
      "lever_summary": lever_summary,
      "exact_patches": exact_patches,
    },
  )
  return candidate_payload


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
  for posture_key in ("demand_posture", "staffing_posture", "cost_posture"):
    left_posture = str(left.get(posture_key) or "").strip()
    right_posture = str(right.get(posture_key) or "").strip()
    if left_posture and right_posture and left_posture != right_posture:
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
  remaining_count = max(0.0, _safe_float(candidate.get("remaining_violation_count")))
  realism_distance = max(0.0, _safe_float(candidate.get("realism_distance")))
  coordination_score = max(0.0, _safe_float(candidate.get("coordination_score")))
  meaningful_lever_count = max(0.0, _safe_float(candidate.get("meaningful_lever_count")))
  archetype_consistency_score = max(0.0, _safe_float(candidate.get("archetype_consistency_score")))
  if break_even_target_exists:
    return (
      1_000_000.0 * break_even
      - (NONBLOCKING_VIOLATION_PENALTY * remaining_count)
      - 2_500.0 * realism_distance
      - 1_000.0 * disruption
      + 600.0 * archetype_consistency_score
      + 250.0 * coordination_score
      + 400.0 * meaningful_lever_count
      + (EBITDA_SELECTION_TIEBREAKER_WEIGHT * ebitda)
      + (NET_INCOME_SELECTION_TIEBREAKER_WEIGHT * net_income)
      + 0.001 * improvement
    )
  return (
    - (NONBLOCKING_VIOLATION_PENALTY * remaining_count)
    - (EBITDA_GAP_SELECTION_TIEBREAKER_WEIGHT * ebitda_gap)
    - 2_500.0 * realism_distance
    + 600.0 * archetype_consistency_score
    + 250.0 * coordination_score
    + 400.0 * meaningful_lever_count
    + (EBITDA_SELECTION_TIEBREAKER_WEIGHT * ebitda)
    + (NET_INCOME_SELECTION_TIEBREAKER_WEIGHT * net_income)
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
    "viability_stabilize": -1,
    "balanced": 0,
    "operations_first": 1,
    "labor_support_first": 2,
    "growth_first": 3,
    "profit_first": 4,
    "lean_survival": 5,
  }
  scenarios = [_enrich_candidate_strategy(candidate) for candidate in candidates if isinstance(candidate, dict)]
  scenarios.sort(
    key=lambda item: (
      _safe_float(item.get("remaining_blocking_count")),
      _safe_float(item.get("remaining_violation_count")),
      -_safe_float(item.get("archetype_consistency_score")),
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


def _candidate_target_margin_path(candidate: Dict[str, Any], *, state_model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
  controller_profile = (
    ((candidate.get("contract_diagnostics") or {}) if isinstance(candidate.get("contract_diagnostics"), dict) else {}).get("controller_profile")
  )
  controller_profile = controller_profile if isinstance(controller_profile, dict) else {}
  path = controller_profile.get("target_margin_path") if isinstance(controller_profile.get("target_margin_path"), dict) else {}
  if not path and isinstance(state_model, dict):
    strategy_layer = state_model.get("strategy_layer") if isinstance(state_model.get("strategy_layer"), dict) else {}
    diagnosis = (strategy_layer or {}).get("diagnosis") if isinstance((strategy_layer or {}).get("diagnosis"), dict) else {}
    if isinstance(diagnosis, dict):
      path = diagnosis.get("target_margin_path") if isinstance(diagnosis.get("target_margin_path"), dict) else {}
  return dict(path or {}) if isinstance(path, dict) else {}


def _candidate_target_path_assessment(
  candidate: Dict[str, Any],
  *,
  state_model: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  path = _candidate_target_margin_path(candidate, state_model=state_model)
  years = candidate.get("forecast_years") if isinstance(candidate.get("forecast_years"), list) else []
  year_margins: Dict[int, Optional[float]] = {}
  for item in years:
    if not isinstance(item, dict):
      continue
    year_index = _safe_int(item.get("year_index"))
    if year_index is None:
      continue
    revenue = max(0.0, _safe_float(item.get("revenue")))
    ebitda = _safe_float(item.get("ebitda"))
    year_margins[year_index] = (ebitda / revenue) if revenue > 0 else None
  misses: List[Dict[str, Any]] = []
  tolerance = 0.03
  for year_index in (1, 2, 3):
    margin = year_margins.get(year_index)
    if margin is None:
      continue
    min_key = f"year{year_index}_min"
    max_key = f"year{year_index}_max"
    target_min = _safe_float(path.get(min_key))
    target_max = _safe_float(path.get(max_key))
    if target_min is not None and margin < (target_min - tolerance):
      misses.append({"year_index": year_index, "kind": "below_min", "margin": margin, "target": target_min})
    if target_max is not None and margin > (target_max + tolerance):
      misses.append({"year_index": year_index, "kind": "above_max", "margin": margin, "target": target_max})
  year1_margin = year_margins.get(1)
  year2_margin = year_margins.get(2)
  year3_margin = year_margins.get(3)
  year5_margin = year_margins.get(5)
  all_negative = all(
    year_margins.get(idx) is not None and _safe_float(year_margins.get(idx)) < 0.0
    for idx in (1, 2, 3, 4, 5)
    if idx in year_margins
  ) and len(year_margins) >= 5
  degrading = False
  if year1_margin is not None and year2_margin is not None and year3_margin is not None:
    if year2_margin < (year1_margin - 0.01) or year3_margin < (year2_margin - 0.01):
      degrading = True
  if year3_margin is not None and year5_margin is not None and year5_margin < (year3_margin - 0.02):
    degrading = True
  return {
    "target_margin_path": _clone(path),
    "year_margins": {str(key): value for key, value in year_margins.items()},
    "misses": misses,
    "all_negative": all_negative,
    "degrading": degrading,
  }


def _presentation_issues(
  candidate: Dict[str, Any],
  *,
  state_model: Optional[Dict[str, Any]] = None,
  selected_candidates: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[str]:
  issues: List[str] = []
  candidate = _enrich_candidate_strategy(candidate if isinstance(candidate, dict) else {})
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
  commercial_context = fixed_facts.get("commercial_context") if isinstance(fixed_facts.get("commercial_context"), dict) else {}
  marketing_role = str(commercial_context.get("marketing_role") or "").strip().lower()
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
  lever_families = {
    str(family or "").strip()
    for family in (candidate.get("meaningful_families") or candidate.get("lever_families") or [])
    if str(family or "").strip()
  }
  if marketing_ratio is not None:
    bizarre_marketing_floor = 0.22
    if marketing_role == "constrained":
      bizarre_marketing_floor = 0.12
    elif marketing_role == "supporting":
      bizarre_marketing_floor = 0.18
    elif marketing_role == "primary":
      bizarre_marketing_floor = 0.28
    if archetype != "growth" and marketing_ratio > bizarre_marketing_floor:
      issues.append("bizarre_marketing")
    elif archetype == "growth" and marketing_ratio > max(0.32, bizarre_marketing_floor + 0.08):
      issues.append("bizarre_marketing")
  if marketing_role == "constrained" and "marketing" in lever_families and archetype != "growth":
    issues.append("marketing_absorber_story")
  if lever_families and lever_families.issubset({"marketing", "other_opex"}) and archetype != "growth":
    issues.append("commercial_absorber_story")
  if archetype == "efficiency" and lever_families and "other_opex" in lever_families and lever_families.issubset({"other_opex", "marketing"}):
    issues.append("commercial_absorber_story")
  if max(0.0, _safe_float(candidate.get("dominant_family_share"))) > 0.72 and _safe_float(candidate.get("meaningful_lever_count")) < 3:
    issues.append("single_lever_dominance")
  for issue in (candidate.get("coordination_issues") or []):
    issue = str(issue or "").strip()
    if issue in {"demand_without_staffing", "cost_without_structure", "utilization_without_support"}:
      issues.append(issue)
  for issue in (candidate.get("archetype_consistency_issues") or []):
    issue = str(issue or "").strip()
    if issue in {
      "archetype_mismatch",
      "growth_cost_story",
      "efficiency_growth_story",
      "operations_absorber_story",
      "single_lever_dominance",
    }:
      issues.append(issue)
  if _safe_float(candidate.get("archetype_consistency_score")) < 1.5 and issues:
    issues.append("weak_archetype_identity")

  label = str(candidate.get("label") or "").strip()
  rationale = str(candidate.get("rationale") or "").strip().lower()
  dominant_tradeoff = str(candidate.get("dominant_tradeoff") or "").strip().lower()
  if not label or ":" not in label:
    issues.append("weak_label")
  if dominant_tradeoff and dominant_tradeoff not in rationale:
    issues.append("weak_rationale")

  target_path = _candidate_target_path_assessment(candidate, state_model=state_model)
  candidate["target_path_assessment"] = _clone(target_path)
  if target_path.get("all_negative"):
    issues.append("all_negative_five_year_path")
  if target_path.get("degrading"):
    issues.append("degrading_five_year_path")
  misses = target_path.get("misses") if isinstance(target_path.get("misses"), list) else []
  if misses:
    issues.append("target_path_miss")

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
    if any(
      issue in {
        "remaining_blockers",
        "bizarre_marketing",
        "marketing_absorber_story",
        "commercial_absorber_story",
        "archetype_mismatch",
        "weak_archetype_identity",
        "single_lever_dominance",
        "demand_without_staffing",
        "cost_without_structure",
        "utilization_without_support",
        "all_negative_five_year_path",
        "degrading_five_year_path",
        "target_path_miss",
      }
      for issue in issues
    ):
      continue
    next_candidate = dict(candidate)
    next_candidate["presentation_issues"] = issues
    fallback.append(next_candidate)
    if len(fallback) >= MAX_SCENARIOS:
      break
  return fallback


def _select_best_effort_governed_scenarios(
  candidates: Sequence[Dict[str, Any]],
  *,
  state_model: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
  best_effort: List[Dict[str, Any]] = []
  for candidate in _select_materially_distinct_scenarios(candidates):
    issues = _presentation_issues(candidate, state_model=state_model, selected_candidates=best_effort)
    if "near_duplicate" in issues:
      continue
    next_candidate = dict(candidate)
    next_candidate["presentation_issues"] = issues
    best_effort.append(next_candidate)
    if len(best_effort) >= MAX_SCENARIOS:
      break
  return best_effort


def _scenario_forecast_summary(bundle: Dict[str, Any]) -> Dict[str, Any]:
  bundle = bundle if isinstance(bundle, dict) else {}
  state = bundle.get("forecast_engine_state") if isinstance(bundle, dict) else {}
  state = state if isinstance(state, dict) else {}
  quarters = bundle.get("forecast_quarters") if isinstance(bundle, dict) else []
  quarters = quarters if isinstance(quarters, list) else []
  years = state.get("forecast_years") if isinstance(state, dict) else []
  years = years if isinstance(years, list) else []
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
    "forecast_confidence": _safe_float(state.get("forecast_confidence")) if state.get("forecast_confidence") is not None else None,
    "convergence_source": str(state.get("convergence_source") or "").strip() or None,
    "convergence_strength": _safe_float(state.get("convergence_strength")) if state.get("convergence_strength") is not None else None,
    "year1_exit_ebitda": round(_safe_float(q4.get("ebitda")), 2) if q4 else None,
    "year3_exit_ebitda": round(_safe_float(q12.get("ebitda")), 2) if q12 else None,
    "year5_exit_ebitda": round(_safe_float(q20.get("ebitda")), 2) if q20 else None,
    "year5_exit_revenue": round(_safe_float(q20.get("revenue")), 2) if q20 else None,
    "year5_status": str(q20.get("realism_check_status") or "").strip() if q20 else None,
    "forecast_years": _clone(years),
  }


def _client_scenario_name(archetype: str) -> str:
  archetype_key = str(archetype or "").strip().lower()
  if archetype_key == "growth":
    return "Growth Strategy"
  if archetype_key == "efficiency":
    return "Efficiency Strategy"
  return "Operational Balance Strategy"


def _client_scenario_confidence(candidate: Dict[str, Any]) -> str:
  forecast_state = (candidate.get("forecast_engine_state") if isinstance(candidate, dict) else {}) or {}
  years = candidate.get("forecast_years") if isinstance(candidate, dict) else []
  years = years if isinstance(years, list) else []
  forecast_confidence = _safe_float((forecast_state or {}).get("forecast_confidence"))
  convergence_strength = _safe_float((forecast_state or {}).get("convergence_strength"))
  year5 = years[-1] if years and isinstance(years[-1], dict) else {}
  year1 = candidate.get("summary") if isinstance(candidate.get("summary"), dict) else {}
  revenue_delta = abs(_safe_float(year5.get("revenue")) - _safe_float(year1.get("revenue")))
  revenue_base = max(1.0, _safe_float(year1.get("revenue")))
  stability = 1.0 - min(1.0, revenue_delta / max(revenue_base * 1.5, 1.0))
  score = (forecast_confidence * 0.55) + (convergence_strength * 0.25) + (stability * 0.20)
  if score >= 0.72:
    return "High"
  if score >= 0.45:
    return "Medium"
  return "Low"


def _client_metric_block(candidate: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
  year1 = candidate.get("summary") if isinstance(candidate.get("summary"), dict) else {}
  years = candidate.get("forecast_years") if isinstance(candidate.get("forecast_years"), list) else []
  year5 = years[-1] if years and isinstance(years[-1], dict) else {}
  year1_revenue = _safe_float(year1.get("revenue"))
  year1_ebitda = _safe_float(year1.get("ebitda"))
  year5_revenue = _safe_float(year5.get("revenue"))
  year5_ebitda = _safe_float(year5.get("ebitda"))
  return {
    "year_1": {
      "revenue": _format_currency(year1_revenue),
      "ebitda": _format_currency(year1_ebitda),
      "ebitda_margin": _format_percent((year1_ebitda / year1_revenue) if year1_revenue > 0 else None),
      "payroll": _format_currency(year1.get("payroll")),
      "marketing": _format_currency(year1.get("marketing")),
      "utilization": _format_percent(year1.get("utilization")),
    },
    "year_5": {
      "revenue": _format_currency(year5_revenue),
      "ebitda": _format_currency(year5_ebitda),
      "ebitda_margin": _format_percent((year5_ebitda / year5_revenue) if year5_revenue > 0 else None),
      "payroll": _format_currency(year5.get("payroll")),
      "marketing": _format_currency(year5.get("marketing")),
      "utilization": _format_percent(year5.get("utilization")),
    },
  }


def _client_tradeoff(candidate: Dict[str, Any]) -> Dict[str, str]:
  demand_posture = str(candidate.get("demand_posture") or "").strip().lower()
  staffing_posture = str(candidate.get("staffing_posture") or "").strip().lower()
  cost_posture = str(candidate.get("cost_posture") or "").strip().lower()
  year1 = candidate.get("summary") if isinstance(candidate.get("summary"), dict) else {}
  years = candidate.get("forecast_years") if isinstance(candidate.get("forecast_years"), list) else []
  year5 = years[-1] if years and isinstance(years[-1], dict) else {}
  year1_revenue = _safe_float(year1.get("revenue"))
  year5_revenue = _safe_float(year5.get("revenue"))
  year1_ebitda = _safe_float(year1.get("ebitda"))
  year5_ebitda = _safe_float(year5.get("ebitda"))
  revenue_gain = year5_revenue > max(1.0, year1_revenue) * 1.08
  margin_gain = (year5_ebitda / max(year5_revenue, 1.0)) > ((year1_ebitda / max(year1_revenue, 1.0)) + 0.02)
  if demand_posture == "preserve":
    upside = "Carries more demand forward and keeps the revenue path stronger over time."
  elif margin_gain:
    upside = "Improves profit quality by tightening the operating structure over time."
  else:
    upside = "Keeps the business on a more stable path without forcing one aggressive move."
  if staffing_posture == "add_support":
    downside = "Needs earlier capacity investment, so labor costs stay higher while the business scales."
  elif cost_posture == "tighten":
    downside = "Gives up some near-term demand and operates with less slack to protect margins."
  elif demand_posture == "reduce":
    downside = "Accepts a slower top-line path in exchange for a cleaner operating model."
  elif revenue_gain:
    downside = "Requires more operating support to keep that growth path credible."
  else:
    downside = "Does not push as hard on either growth or margin as the more specialized paths."
  return {"upside": upside, "downside": downside}


def _client_scenario_summary(candidate: Dict[str, Any]) -> str:
  demand_posture = str(candidate.get("demand_posture") or "").strip().lower()
  staffing_posture = str(candidate.get("staffing_posture") or "").strip().lower()
  cost_posture = str(candidate.get("cost_posture") or "").strip().lower()
  tradeoff = _client_tradeoff(candidate)
  if demand_posture == "preserve":
    sentence_one = "This approach keeps demand moving early and supports it with more operating capacity as the business grows."
  elif cost_posture == "tighten":
    sentence_one = "This approach improves the operating model by tightening cost structure and asking less of the business early."
  else:
    sentence_one = "This approach rebalances the business so demand, staffing, and operating load stay aligned as the plan develops."
  if staffing_posture == "add_support":
    sentence_two = "It works by adding support earlier so higher activity levels remain credible instead of stretching the team too thin."
  elif staffing_posture == "delay":
    sentence_two = "It works by keeping staffing leaner and asking the business to grow at a more measured pace."
  elif cost_posture == "tighten":
    sentence_two = "It works by holding a tighter cost structure while letting demand build more gradually."
  else:
    sentence_two = "It works by moderating the pace of change and keeping capacity and cost decisions in balance."
  sentence_three = f"The upside is that it {tradeoff['upside'].rstrip('.').lower()}; the downside is that it {tradeoff['downside'].rstrip('.').lower()}."
  return f"{sentence_one} {sentence_two} {sentence_three}"


def _build_client_scenario_output(candidate: Dict[str, Any], *, scenario_id: str) -> Dict[str, Any]:
  return {
    "scenario_id": str(scenario_id),
    "scenario_name": _client_scenario_name(str(candidate.get("archetype") or "").strip()),
    "summary": _client_scenario_summary(candidate),
    "key_metrics": _client_metric_block(candidate),
    "tradeoff": _client_tradeoff(candidate),
    "confidence": _client_scenario_confidence(candidate),
  }


def _build_scenario_forecast_bundle(
  *,
  baseline_state: Dict[str, Any],
  exact_patches: Dict[str, Any],
  modified_state: Optional[Dict[str, Any]] = None,
  remaining_violations: Sequence[str],
  constraint_engine_state: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]],
  benchmark_payload: Optional[Dict[str, Any]],
  scenario_strategy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  remaining = [
    str(code or "").strip()
    for code in (remaining_violations or [])
    if str(code or "").strip()
  ]
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
  effective_state = (
    _clone(modified_state)
    if isinstance(modified_state, dict) and modified_state
    else _build_modified_state(
      baseline_state=baseline_state,
      exact_patches=exact_patches,
      marketing_model_json=baseline_state.get("marketing_model_json") if isinstance(baseline_state, dict) else {},
    )
  )
  next_ops = effective_state.get("ops_json") if isinstance(effective_state.get("ops_json"), dict) else {}
  next_people = effective_state.get("people_json") if isinstance(effective_state.get("people_json"), dict) else {}
  next_financials = effective_state.get("financials_json") if isinstance(effective_state.get("financials_json"), dict) else {}
  next_year1 = effective_state.get("financials_year1_json") if isinstance(effective_state.get("financials_year1_json"), dict) else {}
  next_marketing_model = effective_state.get("marketing_model_json") if isinstance(effective_state.get("marketing_model_json"), dict) else {}
  scenario_engine_state = _clone(constraint_engine_state or {})
  if isinstance(scenario_engine_state, dict):
    scenario_engine_state["violations"] = list(remaining)
    class_map = _violation_class_map(constraint_engine_state)
    scenario_engine_state["hard_violation_codes"] = [code for code in remaining if class_map.get(code, "soft") == "hard"]
    scenario_engine_state["soft_violation_codes"] = [code for code in remaining if class_map.get(code, "soft") == "soft"]
    scenario_engine_state["context_violation_codes"] = [code for code in remaining if class_map.get(code, "soft") == "context"]
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
      scenario_strategy=scenario_strategy,
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


def _build_baseline_forecast_bundle(
  *,
  ops_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]],
  benchmark_payload: Optional[Dict[str, Any]],
  constraint_engine_state: Optional[Dict[str, Any]],
  scenario_strategy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    try:
      from forecast_engine import build_forecast_engine_bundle  # type: ignore
    except Exception:
      from client_intake_and_finmo.forecast_engine import build_forecast_engine_bundle  # type: ignore
    return build_forecast_engine_bundle(
      operating_model_json=ops_json,
      people_json=people_json,
      financials_json=financials_json,
      financials_year1_json=financials_year1_json,
      marketing_model_json=marketing_model_json,
      normalized_traits=normalized_traits,
      benchmark_payload=benchmark_payload,
      constraint_engine_state=constraint_engine_state,
      scenario_strategy=scenario_strategy or {
        "strategy_id": "baseline_current_state",
        "strategy_name": "Baseline current state",
      },
    )
  except Exception:
    return {
      "forecast_engine_state": {
        "status": "forecast_error",
        "blocking_violations": [],
      },
      "forecast_quarters": [],
      "forecast_years": [],
      "engine_versions": {},
    }


def _collect_solver_roles(
  people_json: Dict[str, Any],
  *,
  role_activation_ratio: float = 1.0,
) -> List[Dict[str, Any]]:
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
    base_months = max(0, _safe_int(role.get("months_until_hire")) or 0)
    baseline_year1_amount = annual_wage * (max(0.0, 12.0 - float(base_months)) / 12.0)
    baseline_year1_amount *= max(0.0, min(1.0, _safe_float(role_activation_ratio) or 0.0))
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
        "max_months": max(MAX_ROLE_DELAY_MONTHS, base_months),
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


def _derive_commercial_archetype(
  *,
  normalized_traits: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]] = None,
) -> str:
  traits = normalized_traits if isinstance(normalized_traits, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  capacity_driver = str(traits.get("capacity_driver") or ops.get("capacity_driver") or "").strip().lower()
  sales_modality = str(traits.get("sales_modality") or ops.get("sales_modality") or "").strip().lower()
  customer_type = str(traits.get("customer_type") or "").strip().lower()
  unit_cadence = str(traits.get("unit_cadence") or "").strip().lower()

  if capacity_driver == "labor" and sales_modality in {"local_service", "project_based"}:
    if unit_cadence in {"contract", "project"}:
      return "labor_professional_service"
    return "labor_local_service"
  if sales_modality == "retail":
    return "retail_store"
  if sales_modality == "online" and capacity_driver in {"system", "space", "equipment"}:
    return "scalable_online"
  if unit_cadence in {"recurring", "subscription"}:
    if capacity_driver == "system":
      return "subscription_model"
    if capacity_driver == "labor":
      return "recurring_labor_service"
  if customer_type == "b2b" and capacity_driver == "labor" and unit_cadence in {"contract", "project"}:
    return "labor_professional_service"
  if capacity_driver == "system":
    return "system_service"
  if capacity_driver == "space":
    return "space_service"
  return "general_operating_business"


def _commercial_context_policy(
  *,
  normalized_traits: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  current_marketing: float,
  current_other_opex: float,
) -> Dict[str, Any]:
  traits = normalized_traits if isinstance(normalized_traits, dict) else {}
  ops = ops_json if isinstance(ops_json, dict) else {}
  sales_modality = str(traits.get("sales_modality") or ops.get("sales_modality") or "").strip().lower()
  capacity_driver = str(traits.get("capacity_driver") or ops.get("capacity_driver") or "").strip().lower()
  customer_type = str(traits.get("customer_type") or "").strip().lower()
  business_stage = str(traits.get("business_stage") or "").strip().lower()
  unit_cadence = str(traits.get("unit_cadence") or "").strip().lower()
  archetype = _derive_commercial_archetype(
    normalized_traits=traits,
    ops_json=ops,
  )

  marketing_role = "supporting"
  marketing_up_cap_ratio = 0.22
  marketing_down_cap_ratio = 0.35
  marketing_demand_link = True
  growth_demand_mode_enabled = False
  opex_flexibility = "moderate"
  other_opex_down_cap_ratio = 0.10
  other_opex_up_cap_ratio = 0.08

  if archetype in {"labor_local_service", "labor_professional_service"}:
    marketing_role = "constrained"
    marketing_up_cap_ratio = 0.06 if customer_type == "b2b" else 0.09
    marketing_down_cap_ratio = 0.25
    marketing_demand_link = False
    opex_flexibility = "tight"
    other_opex_down_cap_ratio = 0.06
    other_opex_up_cap_ratio = 0.04
  elif archetype == "retail_store":
    marketing_role = "supporting"
    marketing_up_cap_ratio = 0.18
    marketing_down_cap_ratio = 0.25
    marketing_demand_link = True
    opex_flexibility = "moderate"
    other_opex_down_cap_ratio = 0.10
    other_opex_up_cap_ratio = 0.08
  elif archetype == "scalable_online":
    marketing_role = "primary"
    marketing_up_cap_ratio = 0.45
    marketing_down_cap_ratio = 0.30
    marketing_demand_link = True
    opex_flexibility = "moderate"
    other_opex_down_cap_ratio = 0.12
    other_opex_up_cap_ratio = 0.10
  elif archetype in {"subscription_model", "recurring_labor_service"}:
    marketing_role = "supporting" if archetype == "recurring_labor_service" else "primary"
    marketing_up_cap_ratio = 0.14 if archetype == "recurring_labor_service" else 0.30
    marketing_down_cap_ratio = 0.25
    marketing_demand_link = archetype != "recurring_labor_service"
    opex_flexibility = "moderate"
    other_opex_down_cap_ratio = 0.08
    other_opex_up_cap_ratio = 0.06

  if business_stage == "pre_revenue":
    marketing_up_cap_ratio *= 1.2
    marketing_down_cap_ratio *= 0.8
    if marketing_role != "constrained":
      marketing_demand_link = True
  if current_marketing <= 0 and marketing_role != "primary":
    marketing_up_cap_ratio = 0.0
    marketing_demand_link = False
  if current_other_opex <= 0:
    other_opex_down_cap_ratio = 0.0
    other_opex_up_cap_ratio = min(other_opex_up_cap_ratio, 0.03)

  growth_capable_archetypes = {
    "retail_store",
    "scalable_online",
    "subscription_model",
    "system_service",
    "space_service",
    "general_operating_business",
  }
  growth_demand_mode_enabled = bool(marketing_demand_link) and archetype in growth_capable_archetypes

  return {
    "commercial_archetype": archetype,
    "sales_modality": sales_modality,
    "capacity_driver": capacity_driver,
    "customer_type": customer_type,
    "business_stage": business_stage,
    "marketing_role": marketing_role,
    "marketing_demand_link": marketing_demand_link,
    "growth_demand_mode_enabled": growth_demand_mode_enabled,
    "marketing_up_cap_ratio": round(max(0.0, marketing_up_cap_ratio), 6),
    "marketing_down_cap_ratio": round(max(0.0, marketing_down_cap_ratio), 6),
    "opex_flexibility": opex_flexibility,
    "other_opex_down_cap_ratio": round(max(0.0, other_opex_down_cap_ratio), 6),
    "other_opex_up_cap_ratio": round(max(0.0, other_opex_up_cap_ratio), 6),
  }


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
    base_months = max(0, _safe_int(role.get("base_months")) or 0)
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
  normalized_traits: Optional[Dict[str, Any]] = None,
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
  commercial_context = _commercial_context_policy(
    normalized_traits=normalized_traits,
    ops_json=ops_json,
    current_marketing=current_marketing,
    current_other_opex=current_other_opex,
  )

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
    "payroll_support_basis": str((current_metrics or {}).get("payroll_support_basis") or "floor"),
    "fixed_active_role_months": max(0.0, _safe_float((current_metrics or {}).get("fixed_active_role_months"))),
    "baseline_adjustable_active_months": max(0.0, _safe_float((current_metrics or {}).get("baseline_adjustable_active_months"))),
    "adjustable_role_month_cost_floor": max(0.0, _safe_float((current_metrics or {}).get("adjustable_role_month_cost_floor"))),
    "units_per_active_role_month": max(0.0, _safe_float((current_metrics or {}).get("units_per_active_role_month"))),
    "units_per_payroll_dollar": max(0.0, _safe_float((current_metrics or {}).get("units_per_payroll_dollar"))),
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

  current_payroll_total = max(0.0, _safe_float((baseline_summary or {}).get("payroll")))
  nominal_fixed_people_payroll = sum(max(0.0, _safe_float(person.get("annual_wage"))) for person in current_people if isinstance(person, dict))
  nominal_role_support = _role_month_support_profile(_collect_solver_roles(people_json or {}))
  role_grounding = _effective_solver_role_grounding(
    fixed_people_payroll=nominal_fixed_people_payroll,
    current_payroll_total=current_payroll_total,
    role_month_support=nominal_role_support,
  )
  planned_roles = _collect_solver_roles(
    people_json or {},
    role_activation_ratio=max(0.0, _safe_float(role_grounding.get("role_activation_ratio")) or 0.0),
  )
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
  marketing_up_cap_total = current_marketing * (1.0 + _safe_float(commercial_context.get("marketing_up_cap_ratio")))
  marketing_down_floor_total = current_marketing * max(0.0, 1.0 - _safe_float(commercial_context.get("marketing_down_cap_ratio")))
  if revenue_marketing_cap is not None and units_based_marketing_cap is not None:
    marketing_max_total = min(revenue_marketing_cap, units_based_marketing_cap)
  elif revenue_marketing_cap is not None:
    marketing_max_total = revenue_marketing_cap
  elif units_based_marketing_cap is not None:
    marketing_max_total = units_based_marketing_cap
  else:
    marketing_max_total = current_marketing
  marketing_already_too_high = "marketing_too_high" in set(str(code or "").strip() for code in (engine_state.get("violations") or []))
  if current_marketing > 0:
    if not marketing_already_too_high and not (revenue_marketing_cap is not None and current_marketing > revenue_marketing_cap):
      marketing_min_total = max(marketing_min_total, marketing_down_floor_total)
    else:
      marketing_min_total = revenue_marketing_floor
    marketing_max_total = min(marketing_max_total, marketing_up_cap_total)
  elif _safe_float(commercial_context.get("marketing_up_cap_ratio")) <= 0:
    marketing_max_total = 0.0
  marketing_max_total = max(marketing_min_total, marketing_max_total)

  revenue_anchor = max(
    current_revenue,
    supportable_revenue_max or 0.0,
    supportable_revenue_min or 0.0,
    1.0,
  )
  opex_down_cap_total = current_other_opex * max(0.0, 1.0 - _safe_float(commercial_context.get("other_opex_down_cap_ratio")))
  opex_up_cap_total = current_other_opex * (1.0 + _safe_float(commercial_context.get("other_opex_up_cap_ratio")))
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
  if current_other_opex > 0:
    other_opex_min = max(other_opex_min, opex_down_cap_total)
    other_opex_max = min(other_opex_max, max(current_other_opex, opex_up_cap_total))

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
        "enabled": marketing_max_total > marketing_min_total + 0.01,
        "source": "constraint_engine",
      },
    },
    "other_opex": {
      "other_operating_expense": {
        "baseline": current_other_opex,
        "min": other_opex_min,
        "max": other_opex_max,
        "enabled": other_opex_max > other_opex_min + 0.01,
        "source": "constraint_engine",
      },
    },
    "people": {
      "inferred_roles": [
        {
          "role_title": str(role.get("role_title") or "").strip(),
          "annual_wage": _safe_float(role.get("annual_wage")),
          "base_months": max(0, _safe_int(role.get("base_months")) or 0),
          "min_months": 0,
          "max_months": max(MAX_ROLE_DELAY_MONTHS, _safe_int(role.get("max_months")) or _safe_int(role.get("base_months")) or 0),
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
    "business_type": str((normalized_traits or {}).get("business_type") or "").strip(),
    "sales_modality": str((normalized_traits or {}).get("sales_modality") or (ops_json or {}).get("sales_modality") or "").strip(),
    "capacity_driver": str((normalized_traits or {}).get("capacity_driver") or (ops_json or {}).get("capacity_driver") or "").strip(),
    "customer_type": str((normalized_traits or {}).get("customer_type") or "").strip(),
    "business_stage": str((normalized_traits or {}).get("business_stage") or "").strip(),
    "unit_cadence": str((normalized_traits or {}).get("unit_cadence") or "").strip(),
    "current_staff": current_people,
    "rent_annualized": rent_annualized,
    "interest": current_interest,
    "current_payroll_total": current_payroll_total,
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
    "commercial_context": commercial_context,
    "role_grounding": role_grounding,
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
      "enabled": marketing_max_total > marketing_min_total + 0.01,
      "source": "constraint_engine",
      "intensity_min_ratio": marketing_min_ratio,
      "intensity_max_ratio": marketing_max_ratio,
      "commercial_role": commercial_context.get("marketing_role"),
      "commercial_up_cap_ratio": commercial_context.get("marketing_up_cap_ratio"),
      "commercial_down_cap_ratio": commercial_context.get("marketing_down_cap_ratio"),
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
      "enabled": other_opex_max > other_opex_min + 0.01,
      "source": "constraint_engine",
      "flexibility": commercial_context.get("opex_flexibility"),
      "commercial_down_cap_ratio": commercial_context.get("other_opex_down_cap_ratio"),
      "commercial_up_cap_ratio": commercial_context.get("other_opex_up_cap_ratio"),
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
      "enabled": units_per_marketing_dollar > 0 and bool(commercial_context.get("marketing_demand_link")),
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
    "commercial_context": commercial_context,
  }

  state_model = {
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
  trace_lazy(
    "DERIVED",
    "Solver state model",
    lambda: {
      "solve_mode": solve_mode,
      "baseline_summary": baseline_summary,
      "fixed_facts": fixed_facts,
      "controllable_drivers": controllable_drivers,
      "derived_outputs": derived_outputs,
      "constraint_profile": constraint_profile,
    },
  )
  return state_model


def _strategy_constraints_for_allowed_levers(
  allowed_levers: Sequence[str],
  *,
  base_constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  allowed = {str(item or "").strip() for item in allowed_levers if str(item or "").strip()}
  constraints = dict(base_constraints or {})

  if "marketing_up" not in allowed:
    constraints["marketing_up_cap_ratio"] = 0.0
    constraints.setdefault("marketing_max_ratio", 1.0)
  if "marketing_down" not in allowed:
    constraints["marketing_down_cap_ratio"] = 0.0
    constraints.setdefault("marketing_min_ratio", 1.0)
  if "price_up" not in allowed:
    constraints["price_up_cap_ratio"] = 0.0
  if "price_down" not in allowed:
    constraints["price_down_cap_ratio"] = 0.0
  if "util_up" not in allowed:
    constraints["util_up_cap_ratio"] = 0.0
    constraints.setdefault("utilization_max_ratio", 1.0)
  if "util_down" not in allowed:
    constraints["util_down_cap_ratio"] = 0.0
    constraints.setdefault("utilization_min_ratio", 1.0)
  if "other_opex_down" not in allowed:
    constraints["other_opex_down_cap_ratio"] = 0.0
  if "other_opex_up" not in allowed:
    constraints["other_opex_up_cap_ratio"] = 0.0
  if "cogs_down" not in allowed:
    constraints["cogs_down_cap_ratio"] = 0.0
  if "cogs_up" not in allowed:
    constraints["cogs_up_cap_ratio"] = 0.0
  if "payroll_down" not in allowed:
    constraints["payroll_down_max_ratio"] = 0.0
  if "payroll_up" not in allowed:
    constraints["payroll_up_max_ratio"] = 0.0
  if "hire_delay" not in allowed:
    constraints["hire_delay_max_months_total"] = 0.0
  if "hire_advance" not in allowed:
    constraints["hire_advance_max_months_total"] = 0.0
  return constraints


def _strategy_blueprint(
  *,
  strategy_id: str,
  strategy_name: str,
  archetype: str,
  archetype_display: str,
  dominant_tradeoff: str,
  allowed_levers: Sequence[str],
  relationship_rules: Sequence[str],
  weight_overrides: Optional[Dict[str, float]] = None,
  constraints: Optional[Dict[str, Any]] = None,
  anchor_strict: bool = True,
) -> Dict[str, Any]:
  return {
    "strategy_id": strategy_id,
    "strategy_name": strategy_name,
    "profile_id": strategy_id,
    "archetype": archetype,
    "archetype_display": archetype_display,
    "dominant_tradeoff": dominant_tradeoff,
    "allowed_levers": [
      str(item or "").strip()
      for item in allowed_levers
      if str(item or "").strip()
    ],
    "relationship_rules": [
      str(item or "").strip()
      for item in relationship_rules
      if str(item or "").strip()
    ],
    "weight_overrides": dict(weight_overrides or {}),
    "constraints": dict(constraints or {}),
    "anchor_strict": bool(anchor_strict),
  }


def _forecast_year_metric(
  baseline_forecast_bundle: Optional[Dict[str, Any]],
  year_number: int,
  metric_key: str,
) -> Optional[float]:
  bundle = baseline_forecast_bundle if isinstance(baseline_forecast_bundle, dict) else {}
  years = bundle.get("forecast_years") if isinstance(bundle.get("forecast_years"), list) else []
  for item in years:
    if not isinstance(item, dict):
      continue
    year_index = _safe_int(item.get("year"))
    if year_index != year_number:
      continue
    value = item.get(metric_key)
    if value is not None:
      return _safe_float(value)
    if metric_key == "ebitda_margin":
      revenue = _safe_float(item.get("revenue"))
      ebitda = _safe_float(item.get("ebitda"))
      if revenue > 0:
        return ebitda / revenue
    return None
  return None


def _build_orchestration_context_from_state_model(state_model: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  model = state_model if isinstance(state_model, dict) else {}
  fixed_facts = model.get("fixed_facts") if isinstance(model.get("fixed_facts"), dict) else {}
  fixed_facts = fixed_facts if isinstance(fixed_facts, dict) else {}
  controllable_drivers = model.get("controllable_drivers") if isinstance(model.get("controllable_drivers"), dict) else {}
  controllable_drivers = controllable_drivers if isinstance(controllable_drivers, dict) else {}
  people_drivers = controllable_drivers.get("people") if isinstance(controllable_drivers.get("people"), dict) else {}
  milestone_drivers = controllable_drivers.get("milestones") if isinstance(controllable_drivers.get("milestones"), dict) else {}
  current_staff = fixed_facts.get("current_staff") if isinstance(fixed_facts.get("current_staff"), list) else []
  planned_roles = people_drivers.get("inferred_roles") if isinstance(people_drivers.get("inferred_roles"), list) else []
  product_driver_basis = fixed_facts.get("product_driver_basis") if isinstance(fixed_facts.get("product_driver_basis"), list) else []
  milestones = milestone_drivers.get("timing_months_max") if isinstance(milestone_drivers.get("timing_months_max"), list) else []
  return {
    "current_staff": _clone(current_staff),
    "planned_roles": _clone(planned_roles),
    "product_driver_basis": _clone(product_driver_basis),
    "milestones": _clone(milestones),
    "business_type": str(fixed_facts.get("business_type") or "").strip(),
    "capacity_driver": str(fixed_facts.get("capacity_driver") or "").strip(),
    "sales_modality": str(fixed_facts.get("sales_modality") or "").strip(),
    "customer_type": str(fixed_facts.get("customer_type") or "").strip(),
    "unit_cadence": str(fixed_facts.get("unit_cadence") or "").strip(),
    "solve_mode": str(fixed_facts.get("solve_mode") or "").strip(),
  }


def _gpt_strategy_selection(
  *,
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_forecast_bundle: Optional[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
  viability_mode: bool,
  diagnosis: Dict[str, Any],
  strategy_catalog: List[Dict[str, Any]],
  orchestration_context: Optional[Dict[str, Any]] = None,
  solver_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  try:
    try:
      from consistency_strategy_advisor import advise_consistency_strategy_selection  # type: ignore
    except Exception:
      from client_intake_and_finmo.consistency_strategy_advisor import advise_consistency_strategy_selection  # type: ignore
  except Exception as exc:
    return {
      "error": "strategy_advisor_import_failed",
      "error_detail": str(exc),
    }
  try:
    selection = advise_consistency_strategy_selection(
      baseline_summary=baseline_summary,
      constraint_engine_state=constraint_engine_state,
      baseline_forecast_bundle=baseline_forecast_bundle,
      fixed_facts=fixed_facts,
      viability_mode=viability_mode,
      diagnosis=diagnosis,
      strategy_catalog=strategy_catalog,
      orchestration_context=orchestration_context,
      solver_feedback=solver_feedback,
    )
  except Exception as exc:
    return {
      "error": "strategy_advisor_execution_failed",
      "error_detail": str(exc),
    }
  if isinstance(selection, dict):
    return selection
  return {
    "error": "strategy_advisor_invalid_response",
    "error_detail": f"non_dict_response:{type(selection).__name__}",
  }


def _strategy_forecast_orchestration(
  strategy: Optional[Dict[str, Any]],
  *,
  fallback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  raw = (strategy or {}).get("forecast_orchestration") if isinstance(strategy, dict) else None
  if isinstance(raw, dict) and raw:
    return _clone(raw)
  return _clone(fallback or {})


def _baseline_forecast_strategy_from_layer(strategy_layer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  layer = strategy_layer if isinstance(strategy_layer, dict) else {}
  strategies = layer.get("strategies") if isinstance(layer.get("strategies"), list) else []
  primary = strategies[0] if strategies and isinstance(strategies[0], dict) else {}
  selection = layer.get("strategy_selection") if isinstance(layer.get("strategy_selection"), dict) else {}
  baseline_orchestration = (
    selection.get("baseline_forecast_orchestration")
    if isinstance(selection.get("baseline_forecast_orchestration"), dict)
    else {}
  )
  return {
    "strategy_id": str((primary or {}).get("strategy_id") or "baseline_current_state").strip() or "baseline_current_state",
    "strategy_name": str((primary or {}).get("strategy_name") or "Baseline current state").strip() or "Baseline current state",
    "archetype": str((primary or {}).get("archetype") or "operations").strip() or "operations",
    "archetype_display": str((primary or {}).get("archetype_display") or "Operational balance").strip() or "Operational balance",
    "dominant_tradeoff": str((primary or {}).get("dominant_tradeoff") or "").strip(),
    "demand_posture": str((primary or {}).get("demand_posture") or "").strip(),
    "staffing_posture": str((primary or {}).get("staffing_posture") or "").strip(),
    "cost_posture": str((primary or {}).get("cost_posture") or "").strip(),
    "forecast_orchestration": _strategy_forecast_orchestration(primary, fallback=baseline_orchestration),
  }


def _gpt_strategy_required() -> bool:
  import sys

  joined_argv = " ".join(str(arg or "") for arg in sys.argv).lower()
  if "test_planning_engines.py" in joined_argv or "unittest" in joined_argv or "\\tests\\" in joined_argv:
    return False
  # GPT governance is mandatory in live consistency runtime. The only
  # supported non-GPT path is the local test harness, where unit tests
  # deliberately patch or bypass the advisor.
  return True


def _apply_gpt_strategy_overrides(
  *,
  strategy_by_id: Dict[str, Dict[str, Any]],
  advisor_selection: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
  if not isinstance(strategy_by_id, dict) or not isinstance(advisor_selection, dict):
    return strategy_by_id
  overrides = advisor_selection.get("strategy_overrides")
  if not isinstance(overrides, list):
    return strategy_by_id
  allowed_constraint_keys = {
    "price_up_cap_ratio",
    "price_down_cap_ratio",
    "util_up_cap_ratio",
    "util_down_cap_ratio",
    "marketing_up_cap_ratio",
    "marketing_down_cap_ratio",
    "marketing_min_ratio",
    "marketing_max_ratio",
    "other_opex_down_cap_ratio",
    "other_opex_up_cap_ratio",
    "cogs_down_cap_ratio",
    "cogs_up_cap_ratio",
    "payroll_up_max_ratio",
    "payroll_down_max_ratio",
    "hire_delay_max_months_total",
    "hire_advance_max_months_total",
    "units_min_ratio",
    "utilization_min_ratio",
    "utilization_max_ratio",
    "prefer_growth_units",
  }
  allowed_lever_keys = {
    "price_up",
    "price_down",
    "util_up",
    "util_down",
    "marketing_up",
    "marketing_down",
    "other_opex_down",
    "other_opex_up",
    "cogs_down",
    "cogs_up",
    "hire_delay",
    "hire_advance",
    "payroll_down",
    "payroll_up",
  }
  next_map = {key: _clone(value) for key, value in strategy_by_id.items()}
  for item in overrides:
    if not isinstance(item, dict):
      continue
    strategy_id = str(item.get("strategy_id") or "").strip()
    if not strategy_id or strategy_id not in next_map:
      continue
    strategy = next_map[strategy_id]
    allowed_levers = item.get("allowed_levers")
    if isinstance(allowed_levers, list):
      filtered_levers = [
        str(lever or "").strip()
        for lever in allowed_levers
        if str(lever or "").strip() in allowed_lever_keys
      ]
      if filtered_levers:
        strategy["allowed_levers"] = filtered_levers
    constraints = item.get("constraints")
    if isinstance(constraints, dict):
      current_constraints = strategy.get("constraints") if isinstance(strategy.get("constraints"), dict) else {}
      current_constraints = dict(current_constraints or {})
      for key, value in constraints.items():
        clean_key = str(key or "").strip()
        if clean_key not in allowed_constraint_keys:
          continue
        if value is None:
          continue
        if isinstance(value, bool):
          current_constraints[clean_key] = bool(value)
          continue
        current_constraints[clean_key] = _safe_float(value)
      strategy["constraints"] = _strategy_constraints_for_allowed_levers(
        strategy.get("allowed_levers") or [],
        base_constraints=current_constraints,
      )
    forecast_orchestration = item.get("forecast_orchestration")
    if isinstance(forecast_orchestration, dict) and forecast_orchestration:
      strategy["forecast_orchestration"] = _clone(forecast_orchestration)
  return next_map


def _apply_global_strategy_overrides_to_state_model(
  *,
  state_model: Dict[str, Any],
  strategy_layer: Dict[str, Any],
) -> Dict[str, Any]:
  if not isinstance(state_model, dict) or not isinstance(strategy_layer, dict):
    return state_model
  selection = strategy_layer.get("strategy_selection")
  if not isinstance(selection, dict):
    return state_model
  overrides = selection.get("global_overrides")
  if not isinstance(overrides, dict):
    return state_model

  next_state_model = _clone(state_model)
  fixed_facts = next_state_model.get("fixed_facts") if isinstance(next_state_model.get("fixed_facts"), dict) else {}
  fixed_facts = dict(fixed_facts or {})
  constraint_profile = next_state_model.get("constraint_profile") if isinstance(next_state_model.get("constraint_profile"), dict) else {}
  constraint_profile = dict(constraint_profile or {})
  commercial_context = constraint_profile.get("commercial_context") if isinstance(constraint_profile.get("commercial_context"), dict) else {}
  commercial_context = dict(commercial_context or {})
  price_envelope = constraint_profile.get("price_envelope") if isinstance(constraint_profile.get("price_envelope"), dict) else {}
  price_envelope = dict(price_envelope or {})
  util_envelope = constraint_profile.get("utilization_envelope") if isinstance(constraint_profile.get("utilization_envelope"), dict) else {}
  util_envelope = dict(util_envelope or {})
  marketing_envelope = constraint_profile.get("marketing_envelope") if isinstance(constraint_profile.get("marketing_envelope"), dict) else {}
  marketing_envelope = dict(marketing_envelope or {})
  other_opex_envelope = constraint_profile.get("other_opex_envelope") if isinstance(constraint_profile.get("other_opex_envelope"), dict) else {}
  other_opex_envelope = dict(other_opex_envelope or {})
  cogs_envelope = constraint_profile.get("cogs_envelope") if isinstance(constraint_profile.get("cogs_envelope"), dict) else {}
  cogs_envelope = dict(cogs_envelope or {})
  engine_state = constraint_profile.get("constraint_engine_state") if isinstance(constraint_profile.get("constraint_engine_state"), dict) else {}
  engine_state = dict(engine_state or {})
  marketing_band = engine_state.get("marketing_intensity_band") if isinstance(engine_state.get("marketing_intensity_band"), dict) else {}
  opex_band = engine_state.get("opex_intensity_band") if isinstance(engine_state.get("opex_intensity_band"), dict) else {}
  current_revenue = max(0.0, _safe_float(constraint_profile.get("current_revenue")))
  current_price = max(0.0, _safe_float(price_envelope.get("baseline")))
  current_marketing = max(0.0, _safe_float(marketing_envelope.get("baseline")))
  current_other_opex = max(0.0, _safe_float(other_opex_envelope.get("baseline")))
  current_cogs_ratio = max(0.0, _safe_float(cogs_envelope.get("baseline_ratio")))

  price_min_ratio = overrides.get("price_min_ratio")
  if price_min_ratio is not None and current_price > 0:
    ratio = max(0.6, min(1.2, _safe_float(price_min_ratio)))
    price_envelope["min"] = round(current_price * ratio, 2)
  price_max_ratio = overrides.get("price_max_ratio")
  if price_max_ratio is not None and current_price > 0:
    ratio = max(0.8, min(1.5, _safe_float(price_max_ratio)))
    price_envelope["max"] = round(current_price * ratio, 2)
  if price_envelope.get("min") is not None and price_envelope.get("max") is not None:
    price_envelope["max"] = max(_safe_float(price_envelope.get("min")), _safe_float(price_envelope.get("max")))

  util_min = overrides.get("util_min")
  if util_min is not None:
    util_envelope["min"] = max(0.0, min(1.0, _safe_float(util_min)))
  util_max = overrides.get("util_max")
  if util_max is not None:
    util_envelope["max"] = max(
      max(0.0, min(1.0, _safe_float(util_envelope.get("min")))),
      max(0.0, min(1.0, _safe_float(util_max))),
    )

  marketing_up_cap_ratio = overrides.get("marketing_up_cap_ratio")
  if marketing_up_cap_ratio is not None:
    commercial_context["marketing_up_cap_ratio"] = max(0.0, min(1.0, _safe_float(marketing_up_cap_ratio)))
  marketing_down_cap_ratio = overrides.get("marketing_down_cap_ratio")
  if marketing_down_cap_ratio is not None:
    commercial_context["marketing_down_cap_ratio"] = max(0.0, min(1.0, _safe_float(marketing_down_cap_ratio)))
  if current_marketing > 0:
    marketing_envelope["min"] = max(
      0.0,
      current_marketing * max(0.0, 1.0 - _safe_float(commercial_context.get("marketing_down_cap_ratio"))),
    )
    marketing_envelope["max"] = max(
      _safe_float(marketing_envelope.get("min")),
      current_marketing * (1.0 + max(0.0, _safe_float(commercial_context.get("marketing_up_cap_ratio")))),
    )
  elif current_revenue > 0:
    band_max = max(0.0, _safe_float((marketing_band or {}).get("max")))
    marketing_envelope["max"] = current_revenue * min(
      max(0.0, _safe_float(commercial_context.get("marketing_up_cap_ratio"))),
      band_max if band_max > 0 else 0.1,
    )
    marketing_envelope["min"] = 0.0
  marketing_envelope["enabled"] = _safe_float(marketing_envelope.get("max")) > _safe_float(marketing_envelope.get("min")) + 0.01

  other_opex_down_cap_ratio = overrides.get("other_opex_down_cap_ratio")
  if other_opex_down_cap_ratio is not None:
    commercial_context["other_opex_down_cap_ratio"] = max(0.0, min(1.0, _safe_float(other_opex_down_cap_ratio)))
  other_opex_up_cap_ratio = overrides.get("other_opex_up_cap_ratio")
  if other_opex_up_cap_ratio is not None:
    commercial_context["other_opex_up_cap_ratio"] = max(0.0, min(1.0, _safe_float(other_opex_up_cap_ratio)))
  if current_other_opex > 0:
    opex_band_min = max(0.0, _safe_float((opex_band or {}).get("min")))
    opex_band_max = max(opex_band_min, _safe_float((opex_band or {}).get("max")))
    lower_from_band = (current_revenue * opex_band_min) if current_revenue > 0 and opex_band_min > 0 else 0.0
    upper_from_band = (current_revenue * opex_band_max) if current_revenue > 0 and opex_band_max > 0 else current_other_opex
    other_opex_envelope["min"] = max(
      lower_from_band,
      current_other_opex * max(0.0, 1.0 - _safe_float(commercial_context.get("other_opex_down_cap_ratio"))),
    )
    other_opex_envelope["max"] = max(
      _safe_float(other_opex_envelope.get("min")),
      min(
        upper_from_band if upper_from_band > 0 else current_other_opex,
        current_other_opex * (1.0 + max(0.0, _safe_float(commercial_context.get("other_opex_up_cap_ratio")))),
      ),
    )

  cogs_ratio_min = overrides.get("cogs_ratio_min")
  if cogs_ratio_min is not None:
    cogs_envelope["min_ratio"] = max(0.0, min(1.0, _safe_float(cogs_ratio_min)))
  cogs_ratio_max = overrides.get("cogs_ratio_max")
  if cogs_ratio_max is not None:
    cogs_envelope["max_ratio"] = max(
      max(0.0, min(1.0, _safe_float(cogs_envelope.get("min_ratio")))),
      max(0.0, min(1.0, _safe_float(cogs_ratio_max))),
    )
  if cogs_envelope.get("min_ratio") is not None and cogs_envelope.get("max_ratio") is not None:
    cogs_envelope["baseline_ratio"] = min(
      max(current_cogs_ratio, _safe_float(cogs_envelope.get("min_ratio"))),
      _safe_float(cogs_envelope.get("max_ratio")),
    )

  marketing_role = str(overrides.get("marketing_role") or "").strip().lower()
  if marketing_role in {"primary", "supporting", "constrained"}:
    commercial_context["marketing_role"] = marketing_role
  opex_flexibility = str(overrides.get("opex_flexibility") or "").strip().lower()
  if opex_flexibility in {"tight", "moderate", "flexible"}:
    commercial_context["opex_flexibility"] = opex_flexibility

  constraint_profile["commercial_context"] = commercial_context
  constraint_profile["price_envelope"] = price_envelope
  constraint_profile["utilization_envelope"] = util_envelope
  constraint_profile["marketing_envelope"] = marketing_envelope
  constraint_profile["other_opex_envelope"] = other_opex_envelope
  constraint_profile["cogs_envelope"] = cogs_envelope
  fixed_facts["commercial_context"] = commercial_context
  if isinstance(next_state_model.get("strategy_layer"), dict):
    next_strategy_layer = dict(next_state_model.get("strategy_layer") or {})
    selection = next_strategy_layer.get("strategy_selection") if isinstance(next_strategy_layer.get("strategy_selection"), dict) else {}
    selection = dict(selection or {})
    selection["applied_global_overrides"] = {
      "price_envelope": {
        "min": price_envelope.get("min"),
        "max": price_envelope.get("max"),
      },
      "utilization_envelope": {
        "min": util_envelope.get("min"),
        "max": util_envelope.get("max"),
      },
      "marketing_envelope": {
        "enabled": marketing_envelope.get("enabled"),
        "min": marketing_envelope.get("min"),
        "max": marketing_envelope.get("max"),
      },
      "other_opex_envelope": {
        "min": other_opex_envelope.get("min"),
        "max": other_opex_envelope.get("max"),
      },
      "cogs_envelope": {
        "min_ratio": cogs_envelope.get("min_ratio"),
        "max_ratio": cogs_envelope.get("max_ratio"),
        "baseline_ratio": cogs_envelope.get("baseline_ratio"),
      },
      "commercial_context": commercial_context,
    }
    next_strategy_layer["strategy_selection"] = selection
    next_state_model["strategy_layer"] = next_strategy_layer
  next_state_model["constraint_profile"] = constraint_profile
  next_state_model["fixed_facts"] = fixed_facts
  trace_lazy(
    "DERIVED",
    "Applied GPT global strategy overrides",
    lambda: {
      "global_overrides": overrides,
      "price_envelope": price_envelope,
      "utilization_envelope": util_envelope,
      "marketing_envelope": marketing_envelope,
      "other_opex_envelope": other_opex_envelope,
      "cogs_envelope": cogs_envelope,
      "commercial_context": commercial_context,
    },
  )
  return next_state_model


def _diagnose_strategy_context(
  *,
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_forecast_bundle: Optional[Dict[str, Any]],
  fixed_facts: Dict[str, Any],
  viability_mode: bool,
  growth_enabled: bool,
  marketing_demand_link: bool,
) -> Dict[str, Any]:
  violations = [
    str(code or "").strip()
    for code in ((constraint_engine_state or {}).get("violations") or [])
    if str(code or "").strip()
  ]
  blocking = set(_blocking_constraint_violations(constraint_engine_state))
  current_metrics = (constraint_engine_state or {}).get("current_metrics") if isinstance(constraint_engine_state, dict) else {}
  current_metrics = current_metrics if isinstance(current_metrics, dict) else {}
  revenue = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
  gross_profit = _safe_float((baseline_summary or {}).get("gross_profit"))
  payroll = max(0.0, _safe_float((baseline_summary or {}).get("payroll")))
  ebitda = _safe_float((baseline_summary or {}).get("ebitda"))
  current_gross_margin = (gross_profit / revenue) if revenue > 0 else None
  current_payroll_ratio = (payroll / revenue) if revenue > 0 else None
  supportable_units = max(
    0.0,
    _safe_float(current_metrics.get("capacity_units_year1"))
    or _safe_float((fixed_facts or {}).get("supported_capacity_units_year1")),
  )
  baseline_units = max(0.0, _safe_float((fixed_facts or {}).get("baseline_units_year1")))
  utilization = None
  fixed_utilization = (fixed_facts or {}).get("utilization_rate")
  current_metric_utilization = (current_metrics or {}).get("utilization_rate")
  if fixed_utilization is not None:
    fixed_util = _safe_float(fixed_utilization)
    if fixed_util > 0:
      utilization = fixed_util
  if utilization is None and current_metric_utilization is not None:
    current_util = _safe_float(current_metric_utilization)
    if current_util > 0:
      utilization = current_util
  gross_band = (constraint_engine_state or {}).get("gross_margin_band") if isinstance(constraint_engine_state, dict) else {}
  payroll_band = (constraint_engine_state or {}).get("payroll_intensity_band") if isinstance(constraint_engine_state, dict) else {}
  util_range = (constraint_engine_state or {}).get("utilization_range") if isinstance(constraint_engine_state, dict) else {}
  forecast_state = (baseline_forecast_bundle or {}).get("forecast_engine_state") if isinstance((baseline_forecast_bundle or {}).get("forecast_engine_state"), dict) else {}
  forecast_status = str((forecast_state or {}).get("status") or "").strip()
  year3_ebitda_margin = _forecast_year_metric(baseline_forecast_bundle, 3, "ebitda_margin")
  year3_payroll_ratio = _forecast_year_metric(baseline_forecast_bundle, 3, "payroll_ratio")
  year3_utilization = _forecast_year_metric(baseline_forecast_bundle, 3, "utilization")
  ebitda_band = (constraint_engine_state or {}).get("ebitda_margin_band") if isinstance(constraint_engine_state, dict) else {}

  scores = {
    "payroll-driven": 0.0,
    "pricing-driven": 0.0,
    "utilization-driven": 0.0,
  }
  reasons: List[str] = []

  if "payroll_too_light" in blocking:
    scores["payroll-driven"] += 4.0
    reasons.append("hard_payroll_support_gap")
  if "payroll_too_heavy" in violations:
    scores["payroll-driven"] += 3.0
    reasons.append("payroll_intensity_above_realistic_range")
  payroll_max = _band_max(payroll_band)
  if payroll_max is not None and current_payroll_ratio is not None and current_payroll_ratio > (payroll_max + 0.015):
    scores["payroll-driven"] += 2.0
    reasons.append("baseline_payroll_ratio_high")
  structural_payroll_floor = _safe_float(current_metrics.get("structural_payroll_floor"))
  if structural_payroll_floor > max(0.0, payroll) * 1.05:
    scores["payroll-driven"] += 2.0
    reasons.append("structural_payroll_floor_exceeds_baseline")
  if year3_payroll_ratio is not None and payroll_max is not None and year3_payroll_ratio > payroll_max:
    scores["payroll-driven"] += 1.0
    reasons.append("forecast_payroll_pressure_persists")

  if "gross_margin_too_low" in violations:
    scores["pricing-driven"] += 4.0
    reasons.append("gross_margin_below_band")
  gross_min = _band_min(gross_band)
  if gross_min is not None and current_gross_margin is not None and current_gross_margin < (gross_min - 0.015):
    scores["pricing-driven"] += 2.5
    reasons.append("baseline_gross_margin_weak")
  if viability_mode and ebitda < 0:
    scores["pricing-driven"] += 1.0
    reasons.append("viability_gap_present")
  ebitda_min = _band_min((constraint_engine_state or {}).get("ebitda_margin_band") if isinstance(constraint_engine_state, dict) else {})
  ebitda_max = _band_max(ebitda_band)
  if year3_ebitda_margin is not None and ebitda_min is not None and year3_ebitda_margin < ebitda_min:
    scores["pricing-driven"] += 1.0
    reasons.append("forecast_margin_stays_below_target")
  if "gross_margin_too_high" in violations:
    scores["pricing-driven"] += 2.0
    reasons.append("gross_margin_above_band")
  if "ebitda_margin_too_high" in violations:
    scores["pricing-driven"] += 2.5
    reasons.append("ebitda_above_band")
  if ebitda_max is not None and revenue > 0:
    current_ebitda_margin = ebitda / revenue if revenue > 0 else None
    if current_ebitda_margin is not None and current_ebitda_margin > (ebitda_max + 0.02):
      scores["pricing-driven"] += 1.5
      reasons.append("baseline_ebitda_above_realistic_range")
  if year3_ebitda_margin is not None and ebitda_max is not None and year3_ebitda_margin > ebitda_max:
    scores["pricing-driven"] += 1.0
    reasons.append("forecast_margin_stays_above_target")

  if "capacity_unsupported" in blocking:
    scores["utilization-driven"] += 4.0
    reasons.append("hard_capacity_gap")
  if "utilization_too_low" in blocking or "utilization_too_low" in violations:
    scores["utilization-driven"] += 3.5
    reasons.append("utilization_outside_hard_range")
  if supportable_units > 0 and baseline_units >= (0.92 * supportable_units):
    scores["utilization-driven"] += 1.5
    reasons.append("baseline_capacity_headroom_tight")
  util_min = _band_min(util_range)
  if util_min is not None and utilization is not None and utilization < util_min:
    scores["utilization-driven"] += 1.5
    reasons.append("baseline_utilization_below_range")
  if year3_utilization is not None and util_min is not None and year3_utilization < util_min:
    scores["utilization-driven"] += 1.0
    reasons.append("forecast_utilization_stays_low")

  ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
  top_cause, top_score = ranked[0]
  second_score = ranked[1][1] if len(ranked) > 1 else -1.0
  primary_cause = "mixed" if top_score <= 0 or (second_score >= max(2.5, top_score - 0.75)) else top_cause

  preferred: List[str]
  if primary_cause == "payroll-driven":
    preferred = ["staffing_ramp_adjustment"]
    if growth_enabled and marketing_demand_link and scores["pricing-driven"] < 2.0 and scores["utilization-driven"] < 2.0:
      preferred.append("demand_supported_growth")
    else:
      preferred.append("operational_balance_strategy")
  elif primary_cause == "pricing-driven":
    if "ebitda_margin_too_high" in violations or "gross_margin_too_high" in violations:
      preferred = ["reality_normalization_strategy", "operational_balance_strategy"]
    else:
      preferred = ["viability_stabilize", "pricing_adjustment"] if viability_mode else ["pricing_adjustment", "operational_balance_strategy"]
  elif primary_cause == "utilization-driven":
    if viability_mode:
      preferred = ["viability_stabilize", "operational_balance_strategy"]
    else:
      preferred = ["utilization_rebalance"]
      preferred.append("demand_supported_growth" if growth_enabled and marketing_demand_link else "operational_balance_strategy")
  else:
    preferred = ["viability_stabilize" if viability_mode else "operational_balance_strategy", "cost_structure_adjustment"]

  diagnosis = {
    "primary_cause": primary_cause,
    "scores": {key: round(value, 3) for key, value in scores.items()},
    "reasons": list(dict.fromkeys(reasons)),
    "forecast_status": forecast_status or "unavailable",
    "forecast_signals": {
      "year3_ebitda_margin": year3_ebitda_margin,
      "year3_payroll_ratio": year3_payroll_ratio,
      "year3_utilization": year3_utilization,
    },
    "preferred_strategy_ids": preferred[:2],
  }
  return diagnosis


def _build_strategy_layer(
  *,
  state_model: Dict[str, Any],
  baseline_summary: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  normalized_traits: Optional[Dict[str, Any]],
  viability_mode: bool,
  baseline_forecast_bundle: Optional[Dict[str, Any]] = None,
  solver_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  del normalized_traits
  fixed_facts = state_model.get("fixed_facts") if isinstance(state_model, dict) else {}
  fixed_facts = fixed_facts if isinstance(fixed_facts, dict) else {}
  constraint_profile = state_model.get("constraint_profile") if isinstance(state_model, dict) else {}
  constraint_profile = constraint_profile if isinstance(constraint_profile, dict) else {}
  commercial_context = fixed_facts.get("commercial_context") if isinstance(fixed_facts.get("commercial_context"), dict) else {}
  commercial_context = commercial_context if isinstance(commercial_context, dict) else {}
  blocking = _blocking_constraint_violations(constraint_engine_state)
  violations = [
    str(code or "").strip()
    for code in ((constraint_engine_state or {}).get("violations") or [])
    if str(code or "").strip()
  ]
  revenue = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
  ebitda = _safe_float((baseline_summary or {}).get("ebitda"))
  current_metrics = (constraint_engine_state or {}).get("current_metrics") if isinstance(constraint_engine_state, dict) else {}
  current_metrics = current_metrics if isinstance(current_metrics, dict) else {}
  supportable_units = max(0.0, _safe_float(current_metrics.get("capacity_units_year1")) or _safe_float((fixed_facts or {}).get("supported_capacity_units_year1")))
  baseline_units = max(0.0, _safe_float((fixed_facts or {}).get("baseline_units_year1")))
  growth_enabled = bool(commercial_context.get("growth_demand_mode_enabled"))
  marketing_demand_link = bool(commercial_context.get("marketing_demand_link"))
  marketing_up_cap_ratio = max(0.0, _safe_float(commercial_context.get("marketing_up_cap_ratio")))
  drivers: List[str] = []
  if "payroll_too_light" in blocking:
    drivers.append("labor_support_gap")
  if "capacity_unsupported" in blocking:
    drivers.append("capacity_support_gap")
  if "utilization_too_low" in blocking:
    drivers.append("utilization_floor_gap")
  if viability_mode:
    drivers.append("year1_viability_gap")
  elif ebitda < 0:
    drivers.append("negative_year1_ebitda")
  if revenue > 0 and supportable_units > 0 and baseline_units > 0 and baseline_units >= (0.92 * supportable_units):
    drivers.append("tight_capacity_headroom")
  diagnosis = _diagnose_strategy_context(
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
    baseline_forecast_bundle=baseline_forecast_bundle,
    fixed_facts=fixed_facts,
    viability_mode=viability_mode,
    growth_enabled=growth_enabled,
    marketing_demand_link=marketing_demand_link,
  )
  severity = _strategy_case_severity(
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
    baseline_forecast_bundle=baseline_forecast_bundle,
  )
  diagnosis["severity_class"] = str(severity.get("severity_class") or "moderate").strip() or "moderate"
  diagnosis["severity_score"] = _safe_float(severity.get("severity_score"))
  diagnosis["severity_reason"] = str(severity.get("severity_reason") or "").strip()
  diagnosis["minimum_meaningful_levers"] = max(1, _safe_int(severity.get("minimum_meaningful_levers")) or 1)
  diagnosis["minimum_package_count"] = max(1, _safe_int(severity.get("minimum_package_count")) or 1)
  diagnosis["minimum_package_strength"] = str(severity.get("minimum_package_strength") or "moderate").strip() or "moderate"

  strategies: List[Dict[str, Any]] = []

  if viability_mode:
    strategies.append(
      _strategy_blueprint(
        strategy_id="viability_stabilize",
        strategy_name="Minimal viability adjustment",
        archetype="operations",
        archetype_display="Operational balance",
        dominant_tradeoff="keeps the original plan intact with small targeted changes that improve Year-1 viability",
        allowed_levers=["price_up", "hire_delay", "util_up", "other_opex_down"],
        relationship_rules=[
          "price_change_stays_small",
          "staffing_delay_can_extend_beyond_year1",
          "utilization_improvement_stays_modest",
        ],
        weight_overrides={
          "price_up": 0.25,
          "price_down": 2.0,
          "util_up": 0.8,
          "util_down": 2.2,
          "marketing_up": 4.0,
          "marketing_down": 2.0,
          "other_opex_down": 2.0,
          "other_opex_up": 2.5,
          "cogs_down": 4.0,
          "cogs_up": 3.0,
          "hire_delay": 0.6,
          "hire_advance": 1.6,
          "payroll_down": 2.5,
          "payroll_up": 3.5,
        },
        constraints=_strategy_constraints_for_allowed_levers(
          ["price_up", "hire_delay", "util_up", "other_opex_down"],
          base_constraints={
            "price_up_cap_ratio": 0.15,
            "price_down_cap_ratio": 0.02,
            "utilization_max_ratio": 1.12,
            "utilization_min_ratio": 1.0,
            "other_opex_down_cap_ratio": 0.05,
            "other_opex_up_cap_ratio": 0.02,
            "cogs_down_cap_ratio": 0.03,
            "cogs_up_cap_ratio": 0.01,
            "payroll_down_max_ratio": 0.02,
            "hire_delay_max_months_total": float(MAX_ROLE_DELAY_MONTHS),
            "units_min_ratio": 0.98,
          },
        ),
      )
    )
    strategies.append(
      _strategy_blueprint(
        strategy_id="pricing_adjustment",
        strategy_name="Pricing adjustment",
        archetype="operations",
        archetype_display="Operational balance",
        dominant_tradeoff="leans on modest pricing improvement while preserving the underlying operating model",
        allowed_levers=["price_up", "util_down"],
        relationship_rules=["price_increase_capped", "utilization_softens_if_price_moves"],
        weight_overrides={
          "price_up": 0.35,
          "price_down": 3.0,
          "util_down": 0.9,
          "util_up": 2.0,
          "marketing_up": 5.0,
          "other_opex_down": 3.0,
          "cogs_down": 5.0,
          "hire_delay": 3.0,
          "hire_advance": 4.0,
          "payroll_down": 4.0,
          "payroll_up": 4.0,
        },
        constraints=_strategy_constraints_for_allowed_levers(
          ["price_up", "util_down"],
          base_constraints={
            "price_up_cap_ratio": 0.12,
            "util_down_cap_ratio": 0.08,
            "units_min_ratio": 0.95,
          },
        ),
      )
    )
    strategies.append(
      _strategy_blueprint(
        strategy_id="operational_balance_strategy",
        strategy_name="Operational balance strategy",
        archetype="operations",
        archetype_display="Operational balance",
        dominant_tradeoff="uses a small mix of pricing, throughput, and overhead timing changes to stabilize the existing plan",
        allowed_levers=["price_up", "util_up", "other_opex_down", "hire_delay"],
        relationship_rules=["throughput_change_stays_small", "delayed_hiring_carries_into_forecast"],
        weight_overrides={
          "price_up": 0.5,
          "price_down": 2.5,
          "util_up": 0.9,
          "util_down": 2.0,
          "marketing_up": 5.0,
          "marketing_down": 2.0,
          "other_opex_down": 1.2,
          "other_opex_up": 4.0,
          "cogs_down": 3.0,
          "cogs_up": 3.0,
          "hire_delay": 0.9,
          "hire_advance": 3.0,
          "payroll_down": 2.0,
          "payroll_up": 3.0,
        },
        constraints=_strategy_constraints_for_allowed_levers(
          ["price_up", "util_up", "other_opex_down", "hire_delay"],
          base_constraints={
            "price_up_cap_ratio": 0.08,
            "util_up_cap_ratio": 0.08,
            "other_opex_down_cap_ratio": 0.05,
            "hire_delay_max_months_total": float(MAX_ROLE_DELAY_MONTHS),
            "units_min_ratio": 0.97,
          },
        ),
      )
    )
    strategies.append(
      _strategy_blueprint(
        strategy_id="cost_structure_adjustment",
        strategy_name="Cost structure adjustment",
        archetype="efficiency",
        archetype_display="Efficiency path",
        dominant_tradeoff="moderates support costs and non-core spend without replacing the original business model",
        allowed_levers=["other_opex_down", "hire_delay", "cogs_down"],
        relationship_rules=["cost_changes_stay_narrow", "delayed_hiring_flows_into_forecast"],
        weight_overrides={
          "price_up": 2.5,
          "price_down": 3.0,
          "util_up": 2.0,
          "util_down": 2.0,
          "marketing_up": 6.0,
          "marketing_down": 2.5,
          "other_opex_down": 0.8,
          "other_opex_up": 4.0,
          "cogs_down": 0.9,
          "cogs_up": 4.0,
          "hire_delay": 0.75,
          "hire_advance": 4.0,
          "payroll_down": 1.5,
          "payroll_up": 4.0,
        },
        constraints=_strategy_constraints_for_allowed_levers(
          ["other_opex_down", "hire_delay", "cogs_down"],
          base_constraints={
            "other_opex_down_cap_ratio": 0.05,
            "cogs_down_cap_ratio": 0.02,
            "hire_delay_max_months_total": float(MAX_ROLE_DELAY_MONTHS),
            "units_min_ratio": 0.97,
          },
        ),
      )
    )
  else:
    if "ebitda_margin_too_high" in violations or "gross_margin_too_high" in violations:
      strategies.append(
        _strategy_blueprint(
          strategy_id="reality_normalization_strategy",
          strategy_name="Reality normalization strategy",
          archetype="operations",
          archetype_display="Operational balance",
          dominant_tradeoff="normalizes implausibly strong Year-1 economics by adding the support, delivery, and go-to-market structure the business would realistically need",
          allowed_levers=["price_down", "util_down", "hire_advance", "payroll_up", "marketing_up", "other_opex_up", "cogs_up"],
          relationship_rules=[
            "unsupported_upside_requires_reinvestment_or_delivery_support",
            "pricing_can_step_down_if_above_realistic_range",
            "support_spend_and_capacity_buildout_can_increase_together",
          ],
          weight_overrides={
            "price_up": 5.0,
            "price_down": 0.7,
            "util_up": 3.5,
            "util_down": 0.7,
            "marketing_up": 0.75,
            "marketing_down": 3.0,
            "other_opex_down": 3.0,
            "other_opex_up": 0.8,
            "cogs_down": 4.0,
            "cogs_up": 0.9,
            "hire_delay": 4.0,
            "hire_advance": 0.65,
            "payroll_down": 4.0,
            "payroll_up": 0.65,
          },
          constraints=_strategy_constraints_for_allowed_levers(
            ["price_down", "util_down", "hire_advance", "payroll_up", "marketing_up", "other_opex_up", "cogs_up"],
            base_constraints={
              "price_down_cap_ratio": 0.12,
              "util_down_cap_ratio": 0.12,
              "hire_advance_max_months_total": float(MAX_ROLE_DELAY_MONTHS),
              "payroll_up_max_ratio": 0.50,
              "marketing_up_cap_ratio": min(0.35, max(0.10, marketing_up_cap_ratio or 0.20)),
              "other_opex_up_cap_ratio": 0.15,
              "cogs_up_cap_ratio": 0.08,
              "units_min_ratio": 0.90,
            },
          ),
        )
      )
    if "payroll_too_light" in blocking:
      strategies.append(
        _strategy_blueprint(
          strategy_id="staffing_ramp_adjustment",
          strategy_name="Staffing ramp adjustment",
          archetype="operations",
          archetype_display="Operational balance",
          dominant_tradeoff="aligns labor support with workload before pushing for more demand or margin",
          allowed_levers=["hire_advance", "payroll_up", "util_down", "price_up"],
          relationship_rules=["workload_requires_staffing_support", "utilization_resets_before_growth"],
          weight_overrides={
            "price_up": 1.1,
            "price_down": 2.5,
            "util_up": 2.0,
            "util_down": 0.7,
            "marketing_up": 4.0,
            "marketing_down": 1.2,
            "other_opex_down": 2.0,
            "other_opex_up": 3.0,
            "cogs_down": 2.5,
            "cogs_up": 2.5,
            "hire_delay": 3.0,
            "hire_advance": 0.45,
            "payroll_down": 3.5,
            "payroll_up": 0.45,
          },
          constraints=_strategy_constraints_for_allowed_levers(
            ["hire_advance", "payroll_up", "util_down", "price_up"],
            base_constraints={
              "hire_advance_max_months_total": 12.0,
              "payroll_up_max_ratio": 0.45,
              "util_down_cap_ratio": 0.18,
              "price_up_cap_ratio": 0.08,
              "units_min_ratio": 0.9,
            },
          ),
        )
      )
      strategies.append(
        _strategy_blueprint(
          strategy_id="pricing_adjustment",
          strategy_name="Pricing adjustment",
          archetype="operations",
          archetype_display="Operational balance",
          dominant_tradeoff="leans on modest pricing improvement while preserving the underlying operating model",
          allowed_levers=["price_up", "util_down"],
          relationship_rules=["price_increase_capped", "utilization_softens_if_price_moves"],
          weight_overrides={
            "price_up": 0.45,
            "price_down": 2.5,
            "util_up": 2.0,
            "util_down": 0.9,
            "marketing_up": 5.0,
            "other_opex_down": 3.0,
            "cogs_down": 5.0,
            "hire_advance": 3.5,
            "hire_delay": 3.5,
            "payroll_down": 4.0,
            "payroll_up": 3.5,
          },
          constraints=_strategy_constraints_for_allowed_levers(
            ["price_up", "util_down"],
            base_constraints={
              "price_up_cap_ratio": 0.08,
              "util_down_cap_ratio": 0.10,
              "units_min_ratio": 0.92,
              "utilization_max_ratio": 1.0,
            },
          ),
        )
      )
    if "capacity_unsupported" in blocking or "utilization_too_low" in blocking:
      strategies.append(
        _strategy_blueprint(
          strategy_id="utilization_rebalance",
          strategy_name="Utilization rebalance",
          archetype="operations",
          archetype_display="Operational balance",
          dominant_tradeoff="resets throughput and utilization so delivery stays believable under real capacity",
          allowed_levers=["util_down", "price_up", "hire_advance", "payroll_up"],
          relationship_rules=["capacity_and_staffing_move_together", "price_change_is_secondary"],
          weight_overrides={
            "price_up": 1.0,
            "price_down": 2.4,
            "util_up": 3.0,
            "util_down": 0.55,
            "marketing_up": 4.5,
            "marketing_down": 1.2,
            "other_opex_down": 2.0,
            "cogs_down": 2.5,
            "hire_delay": 3.0,
            "hire_advance": 0.55,
            "payroll_down": 3.0,
            "payroll_up": 0.55,
          },
          constraints=_strategy_constraints_for_allowed_levers(
            ["util_down", "price_up", "hire_advance", "payroll_up"],
            base_constraints={
              "util_down_cap_ratio": 0.22,
              "price_up_cap_ratio": 0.08,
              "hire_advance_max_months_total": 12.0,
              "payroll_up_max_ratio": 0.4,
              "units_min_ratio": 0.85,
            },
          ),
        )
      )
    if growth_enabled and marketing_demand_link:
      strategies.append(
        _strategy_blueprint(
          strategy_id="demand_supported_growth",
          strategy_name="Utilization-driven growth",
          archetype="growth",
          archetype_display="Growth path",
          dominant_tradeoff="preserves more demand, but only with matching staffing and capacity support",
          allowed_levers=["marketing_up", "util_up", "hire_advance", "payroll_up", "price_up"],
          relationship_rules=["demand_requires_staffing_support", "price_increase_capped_when_preserving_demand"],
          weight_overrides={
            "marketing_up": 0.55,
            "marketing_down": 1.8,
            "util_up": 0.6,
            "util_down": 1.6,
            "hire_advance": 0.45,
            "hire_delay": 3.0,
            "payroll_up": 0.45,
            "payroll_down": 3.0,
            "price_up": 0.9,
            "price_down": 2.5,
            "other_opex_down": 2.5,
            "cogs_down": 3.0,
          },
          constraints=_strategy_constraints_for_allowed_levers(
            ["marketing_up", "util_up", "hire_advance", "payroll_up", "price_up"],
            base_constraints={
              "marketing_min_ratio": 1.0,
              "marketing_up_cap_ratio": max(0.0, _safe_float(commercial_context.get("marketing_up_cap_ratio"))),
              "prefer_growth_units": True,
              "price_up_cap_ratio": 0.06,
              "util_up_cap_ratio": 0.12,
              "hire_advance_max_months_total": 12.0,
              "payroll_up_max_ratio": 0.45,
              "units_min_ratio": 0.98,
            },
          ),
        )
      )
    strategies.append(
      _strategy_blueprint(
        strategy_id="operational_balance_strategy",
        strategy_name="Operational balance strategy",
        archetype="operations",
        archetype_display="Operational balance",
        dominant_tradeoff="balances staffing, pricing, and throughput so the plan becomes operationally supportable without over-rotating into cost cutting",
        allowed_levers=["price_up", "util_down", "hire_advance", "payroll_up", "other_opex_down"],
        relationship_rules=["staffing_and_throughput_move_together", "support_spend_precedes_growth"],
        weight_overrides={
          "price_up": 0.95,
          "price_down": 2.5,
          "util_up": 2.0,
          "util_down": 0.8,
          "marketing_up": 3.5,
          "marketing_down": 1.3,
          "other_opex_down": 1.1,
          "other_opex_up": 2.5,
          "cogs_down": 2.0,
          "cogs_up": 2.5,
          "hire_delay": 3.0,
          "hire_advance": 0.6,
          "payroll_down": 3.0,
          "payroll_up": 0.6,
        },
        constraints=_strategy_constraints_for_allowed_levers(
          ["price_up", "util_down", "hire_advance", "payroll_up", "other_opex_down"],
          base_constraints={
            "price_up_cap_ratio": 0.08,
            "util_down_cap_ratio": 0.12,
            "hire_advance_max_months_total": 12.0,
            "payroll_up_max_ratio": 0.35,
            "other_opex_down_cap_ratio": 0.05,
            "units_min_ratio": 0.9,
          },
        ),
      )
    )
    strategies.append(
      _strategy_blueprint(
        strategy_id="pricing_adjustment",
        strategy_name="Pricing adjustment",
        archetype="operations",
        archetype_display="Operational balance",
        dominant_tradeoff="rebalances pricing and throughput without fundamentally changing the business model",
        allowed_levers=["price_up", "price_down", "util_down"],
        relationship_rules=["price_moves_stay_bounded", "throughput_adjusts_with_price"],
        weight_overrides={
          "price_up": 0.8,
          "price_down": 0.8,
          "util_up": 2.5,
          "util_down": 0.9,
          "marketing_up": 3.5,
          "marketing_down": 1.8,
          "other_opex_down": 2.0,
          "other_opex_up": 2.0,
          "cogs_down": 3.0,
          "cogs_up": 2.0,
          "hire_delay": 3.0,
          "hire_advance": 2.0,
          "payroll_down": 3.0,
          "payroll_up": 2.0,
        },
        constraints=_strategy_constraints_for_allowed_levers(
          ["price_up", "price_down", "util_down"],
          base_constraints={
            "price_up_cap_ratio": 0.10,
            "price_down_cap_ratio": 0.10,
            "util_down_cap_ratio": 0.12,
            "units_min_ratio": 0.90,
          },
        ),
      )
    )
    strategies.append(
      _strategy_blueprint(
        strategy_id="cost_structure_adjustment",
        strategy_name="Cost structure adjustment",
        archetype="efficiency",
        archetype_display="Efficiency path",
        dominant_tradeoff="tightens cost structure while preserving the core operating model",
        allowed_levers=["other_opex_down", "cogs_down", "hire_delay", "payroll_down"],
        relationship_rules=["cost_actions_must_stay_structural", "delayed_hiring_carries_into_forecast"],
        weight_overrides={
          "price_up": 2.0,
          "price_down": 2.2,
          "util_up": 2.0,
          "util_down": 1.6,
          "marketing_up": 5.0,
          "marketing_down": 1.5,
          "other_opex_down": 0.7,
          "other_opex_up": 4.0,
          "cogs_down": 0.7,
          "cogs_up": 4.0,
          "hire_delay": 0.7,
          "hire_advance": 4.0,
          "payroll_down": 0.8,
          "payroll_up": 4.0,
        },
        constraints=_strategy_constraints_for_allowed_levers(
          ["other_opex_down", "cogs_down", "hire_delay", "payroll_down"],
          base_constraints={
            "other_opex_down_cap_ratio": 0.08,
            "cogs_down_cap_ratio": 0.04,
            "hire_delay_max_months_total": float(MAX_ROLE_DELAY_MONTHS),
            "payroll_down_max_ratio": 0.15,
            "units_min_ratio": 0.9,
          },
        ),
      )
    )

  deduped: List[Dict[str, Any]] = []
  strategy_by_id: Dict[str, Dict[str, Any]] = {}
  seen_ids = set()
  for strategy in strategies:
    strategy_id = str(strategy.get("strategy_id") or "").strip()
    if not strategy_id or strategy_id in seen_ids:
      continue
    strategy_by_id[strategy_id] = strategy
    seen_ids.add(strategy_id)
  advisor_selection = _gpt_strategy_selection(
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
    baseline_forecast_bundle=baseline_forecast_bundle,
    fixed_facts=fixed_facts,
    viability_mode=viability_mode,
    diagnosis=diagnosis,
    strategy_catalog=list(strategy_by_id.values()),
    orchestration_context=_build_orchestration_context_from_state_model(state_model),
    solver_feedback=solver_feedback,
  )
  advisor_selected_ids = [
    str(item or "").strip()
    for item in (advisor_selection.get("selected_strategy_ids") or [])
    if str(item or "").strip() in strategy_by_id
  ] if isinstance(advisor_selection, dict) else []
  gpt_required = _gpt_strategy_required()
  if gpt_required and not advisor_selected_ids:
    diagnosis_out = dict(diagnosis or {})
    diagnosis_out["strategy_advisor_required"] = True
    diagnosis_out["strategy_advisor_error"] = str((advisor_selection or {}).get("error") or "missing_strategy_selection")
    error_detail = str((advisor_selection or {}).get("error_detail") or "").strip()
    if error_detail:
      diagnosis_out["strategy_advisor_error_detail"] = error_detail
    layer = {
      "source": "gpt_required_unavailable",
      "primary_drivers": drivers,
      "diagnosis": diagnosis_out,
      "baseline_forecast_status": str((((baseline_forecast_bundle or {}).get("forecast_engine_state") or {}) if isinstance((baseline_forecast_bundle or {}).get("forecast_engine_state"), dict) else {}).get("status") or "").strip() or "unavailable",
      "strategies": [],
      "strategy_catalog": list(strategy_by_id.values()),
      "strategy_selection": advisor_selection if isinstance(advisor_selection, dict) else {},
    }
    trace_lazy(
      "DERIVED",
      "Solver strategy layer unavailable",
      lambda: layer,
    )
    return layer
  if gpt_required and advisor_selected_ids and not _gpt_blueprint_is_usable(advisor_selection):
    diagnosis_out = dict(diagnosis or {})
    diagnosis_out["strategy_advisor_required"] = True
    diagnosis_out["strategy_advisor_error"] = "strategy_advisor_invalid_blueprint"
    layer = {
      "source": "gpt_required_invalid_blueprint",
      "primary_drivers": drivers,
      "diagnosis": diagnosis_out,
      "baseline_forecast_status": str((((baseline_forecast_bundle or {}).get("forecast_engine_state") or {}) if isinstance((baseline_forecast_bundle or {}).get("forecast_engine_state"), dict) else {}).get("status") or "").strip() or "unavailable",
      "strategies": [],
      "strategy_catalog": list(strategy_by_id.values()),
      "strategy_selection": advisor_selection if isinstance(advisor_selection, dict) else {},
    }
    trace_lazy(
      "DERIVED",
      "Solver strategy layer invalid blueprint",
      lambda: layer,
    )
    return layer
  if advisor_selected_ids:
    strategy_by_id = _apply_gpt_strategy_overrides(
      strategy_by_id=strategy_by_id,
      advisor_selection=advisor_selection,
    )
  selected_ids: List[str] = []
  if advisor_selected_ids:
    for strategy_id in advisor_selected_ids[:2]:
      if strategy_id not in selected_ids:
        selected_ids.append(strategy_id)
  else:
    for strategy_id in (diagnosis.get("preferred_strategy_ids") or []):
      strategy_id = str(strategy_id or "").strip()
      if strategy_id and strategy_id in strategy_by_id and strategy_id not in selected_ids:
        selected_ids.append(strategy_id)
      if len(selected_ids) >= 2:
        break
    for strategy_id in strategy_by_id.keys():
      if len(selected_ids) >= min(2, len(strategy_by_id)):
        break
      if strategy_id not in selected_ids:
        selected_ids.append(strategy_id)
  for strategy_id in selected_ids:
    if strategy_id in strategy_by_id:
      deduped.append(strategy_by_id[strategy_id])

  diagnosis_out = dict(diagnosis or {})
  if isinstance(advisor_selection, dict) and advisor_selection:
    gpt_primary_cause = str(advisor_selection.get("primary_cause") or "").strip()
    gpt_reason = str(advisor_selection.get("reason") or "").strip()
    if gpt_primary_cause:
      diagnosis_out["primary_cause"] = gpt_primary_cause
      diagnosis_out["gpt_primary_cause"] = gpt_primary_cause
    if gpt_reason:
      diagnosis_out["reasons"] = [gpt_reason]
      diagnosis_out["gpt_reason"] = gpt_reason
    diagnosis_out["selected_strategy_ids"] = list(selected_ids)
    diagnosis_out["preferred_strategy_ids"] = list(selected_ids)
    expected_margin_min = advisor_selection.get("expected_year1_ebitda_margin_min")
    expected_margin_max = advisor_selection.get("expected_year1_ebitda_margin_max")
    if expected_margin_min is not None:
      diagnosis_out["gpt_expected_year1_ebitda_margin_min"] = _safe_float(expected_margin_min)
    if expected_margin_max is not None:
      diagnosis_out["gpt_expected_year1_ebitda_margin_max"] = _safe_float(expected_margin_max)
    business_model_assessment = str(advisor_selection.get("business_model_assessment") or "").strip()
    if business_model_assessment:
      diagnosis_out["business_model_assessment"] = business_model_assessment
    secondary_causes = [
      str(item or "").strip()
      for item in (advisor_selection.get("secondary_causes") or [])
      if str(item or "").strip()
    ]
    if secondary_causes:
      diagnosis_out["secondary_causes"] = secondary_causes[:4]
    required_lever_families = [
      str(item or "").strip()
      for item in (advisor_selection.get("required_lever_families") or [])
      if str(item or "").strip()
    ]
    forbidden_lever_families = [
      str(item or "").strip()
      for item in (advisor_selection.get("forbidden_lever_families") or [])
      if str(item or "").strip()
    ]
    if required_lever_families:
      diagnosis_out["required_lever_families"] = required_lever_families[:8]
    if forbidden_lever_families:
      diagnosis_out["forbidden_lever_families"] = forbidden_lever_families[:8]
    controller_directives = advisor_selection.get("controller_directives")
    if isinstance(controller_directives, dict) and controller_directives:
      diagnosis_out["controller_directives"] = _clone(controller_directives)
    target_margin_path = advisor_selection.get("target_margin_path")
    if isinstance(target_margin_path, dict) and target_margin_path:
      diagnosis_out["target_margin_path"] = _clone(target_margin_path)
    target_posture = advisor_selection.get("target_posture")
    if isinstance(target_posture, dict) and target_posture:
      diagnosis_out["target_posture"] = _clone(target_posture)
    coordinated_lever_packages = [
      _clone(item)
      for item in (advisor_selection.get("coordinated_lever_packages") or [])
      if isinstance(item, dict)
    ]
    if coordinated_lever_packages:
      diagnosis_out["coordinated_lever_packages"] = coordinated_lever_packages[:8]
    severity_class = str(advisor_selection.get("severity_class") or "").strip().lower()
    if severity_class in {"mild", "moderate", "severe"}:
      diagnosis_out["severity_class"] = severity_class
    severity_reason = str(advisor_selection.get("severity_reason") or "").strip()
    if severity_reason:
      diagnosis_out["severity_reason"] = severity_reason
    minimum_package_strength = str(advisor_selection.get("minimum_package_strength") or "").strip().lower()
    if minimum_package_strength in {"light", "moderate", "strong"}:
      diagnosis_out["minimum_package_strength"] = minimum_package_strength
  if isinstance(solver_feedback, dict) and solver_feedback:
    diagnosis_out["governed_retry_attempt"] = len([
      item for item in (solver_feedback.get("prior_attempts") or [])
      if isinstance(item, dict)
    ])

  layer = {
    "source": "gpt" if advisor_selected_ids else "deterministic",
    "primary_drivers": drivers,
    "diagnosis": diagnosis_out,
    "baseline_forecast_status": str((((baseline_forecast_bundle or {}).get("forecast_engine_state") or {}) if isinstance((baseline_forecast_bundle or {}).get("forecast_engine_state"), dict) else {}).get("status") or "").strip() or "unavailable",
    "strategies": deduped,
    "strategy_catalog": list(strategy_by_id.values()),
    "strategy_selection": advisor_selection if isinstance(advisor_selection, dict) else {},
  }
  trace_lazy(
    "DERIVED",
    "Solver strategy layer",
    lambda: layer,
  )
  return layer


def _solver_profiles(state_model: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  base_weights = {}
  family_concentration_weight = FAMILY_CONCENTRATION_WEIGHT
  ebitda_cushion_preference_weight = EBITDA_CUSHION_PREFERENCE_WEIGHT
  objective_tolerance_ratio = OPTION_OBJECTIVE_TOLERANCE_RATIO
  objective_tolerance_abs = OPTION_OBJECTIVE_TOLERANCE_ABS
  active_violations: List[str] = []
  sales_modality = ""
  capacity_driver = ""
  commercial_context: Dict[str, Any] = {}
  viability_mode = False
  strategy_layer: Dict[str, Any] = {}
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
      viability_mode = bool(objective_policy.get("viability_mode"))
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
      commercial_context = fixed_facts.get("commercial_context") if isinstance(fixed_facts.get("commercial_context"), dict) else {}
    strategy_layer = state_model.get("strategy_layer") if isinstance(state_model.get("strategy_layer"), dict) else {}
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
  marketing_role = str(commercial_context.get("marketing_role") or "").strip().lower()
  growth_demand_mode_enabled = bool(commercial_context.get("growth_demand_mode_enabled"))
  opex_flexibility = str(commercial_context.get("opex_flexibility") or "").strip().lower()
  marketing_up_cap_ratio = max(0.0, _safe_float(commercial_context.get("marketing_up_cap_ratio")))
  marketing_down_cap_ratio = max(0.0, _safe_float(commercial_context.get("marketing_down_cap_ratio")))
  other_opex_down_cap_ratio = max(0.0, _safe_float(commercial_context.get("other_opex_down_cap_ratio")))
  other_opex_up_cap_ratio = max(0.0, _safe_float(commercial_context.get("other_opex_up_cap_ratio")))
  if sales_modality in {"local_service", "project_based"} and capacity_driver == "labor":
    base_weights["marketing_up"] = _safe_float(base_weights.get("marketing_up")) * 2.25
    base_weights["marketing_down"] = _safe_float(base_weights.get("marketing_down")) * 0.8
  if marketing_role == "constrained":
    base_weights["marketing_up"] = _safe_float(base_weights.get("marketing_up")) * 1.8
    base_weights["marketing_down"] = _safe_float(base_weights.get("marketing_down")) * 0.85
  elif marketing_role == "primary":
    base_weights["marketing_up"] = _safe_float(base_weights.get("marketing_up")) * 0.7
    base_weights["marketing_down"] = _safe_float(base_weights.get("marketing_down")) * 1.15
  if opex_flexibility == "tight":
    base_weights["other_opex_down"] = _safe_float(base_weights.get("other_opex_down")) * 2.2
    base_weights["other_opex_up"] = _safe_float(base_weights.get("other_opex_up")) * 2.0
  elif opex_flexibility == "moderate":
    base_weights["other_opex_down"] = _safe_float(base_weights.get("other_opex_down")) * 1.35
    base_weights["other_opex_up"] = _safe_float(base_weights.get("other_opex_up")) * 1.2
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

  planned_strategies = strategy_layer.get("strategies") if isinstance(strategy_layer, dict) else []
  planned_strategies = planned_strategies if isinstance(planned_strategies, list) else []
  if planned_strategies:
    profiles: List[Dict[str, Any]] = []
    for strategy in planned_strategies:
      if not isinstance(strategy, dict):
        continue
      profile_id = str(strategy.get("profile_id") or strategy.get("strategy_id") or "").strip()
      if not profile_id:
        continue
      profile = profile_with(
        profile_id,
        strategy.get("weight_overrides") if isinstance(strategy.get("weight_overrides"), dict) else {},
        constraints=strategy.get("constraints") if isinstance(strategy.get("constraints"), dict) else {},
        anchor_strict=bool(strategy.get("anchor_strict", True)),
      )
      profile["strategy_id"] = str(strategy.get("strategy_id") or profile_id).strip()
      profile["strategy_name"] = str(strategy.get("strategy_name") or profile_id).strip()
      profile["strategy_source"] = str((strategy_layer or {}).get("source") or "deterministic").strip() or "deterministic"
      profile["allowed_levers"] = [
        str(item or "").strip()
        for item in (strategy.get("allowed_levers") or [])
        if str(item or "").strip()
      ]
      profile["relationship_rules"] = [
        str(item or "").strip()
        for item in (strategy.get("relationship_rules") or [])
        if str(item or "").strip()
      ]
      profile["forecast_orchestration"] = _strategy_forecast_orchestration(strategy)
      if str(strategy.get("archetype") or "").strip():
        profile["archetype"] = str(strategy.get("archetype") or "").strip()
      if str(strategy.get("archetype_display") or "").strip():
        profile["archetype_display"] = str(strategy.get("archetype_display") or "").strip()
      if str(strategy.get("dominant_tradeoff") or "").strip():
        profile["dominant_tradeoff"] = str(strategy.get("dominant_tradeoff") or "").strip()
      profiles.append(profile)
    if profiles:
      return profiles

  profiles = [
    profile_with("balanced", {}, anchor_strict=True),
    profile_with(
      "growth_first",
      {
        "marketing_up": 0.55,
        "util_up": 0.65,
        "util_down": 1.35,
        "marketing_down": 1.5,
        "other_opex_down": 1.15,
        "hire_delay": 1.75,
        "hire_advance": 0.5,
        "payroll_down": 1.75,
        "payroll_up": 0.45,
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

  if viability_mode:
    profiles.insert(
      0,
      profile_with(
        "viability_stabilize",
        {
          "price_up": 0.25,
          "price_down": 2.0,
          "util_up": 0.8,
          "util_down": 2.2,
          "marketing_up": 4.0,
          "marketing_down": 2.0,
          "other_opex_down": 2.0,
          "other_opex_up": 2.5,
          "cogs_down": 4.0,
          "cogs_up": 3.0,
          "hire_delay": 0.6,
          "hire_advance": 1.6,
          "payroll_down": 2.5,
          "payroll_up": 3.5,
        },
        constraints={
          "marketing_max_ratio": 1.0,
          "marketing_min_ratio": 1.0,
          "price_up_cap_ratio": 0.15,
          "price_down_cap_ratio": 0.02,
          "utilization_max_ratio": 1.12,
          "utilization_min_ratio": 1.0,
          "other_opex_down_cap_ratio": 0.05,
          "other_opex_up_cap_ratio": 0.02,
          "cogs_down_cap_ratio": 0.03,
          "cogs_up_cap_ratio": 0.01,
          "payroll_down_max_ratio": 0.02,
          "hire_delay_max_months_total": 3.0,
          "units_min_ratio": 0.98,
        },
        anchor_strict=True,
      ),
    )

  if growth_demand_mode_enabled:
    for profile in profiles:
      if str(profile.get("profile_id") or "").strip() != "growth_first":
        continue
      constraints = profile.get("constraints") if isinstance(profile, dict) else {}
      constraints = constraints if isinstance(constraints, dict) else {}
      constraints["prefer_growth_units"] = True
      constraints["units_min_ratio"] = max(0.98, _safe_float(constraints.get("units_min_ratio")) or 0.0)
      constraints["marketing_min_ratio"] = max(1.0, _safe_float(constraints.get("marketing_min_ratio")) or 0.0)
      profile["constraints"] = constraints
      weights = profile.get("weights") if isinstance(profile, dict) else {}
      weights = weights if isinstance(weights, dict) else {}
      weights["payroll_up"] = _safe_float(weights.get("payroll_up")) * 0.7
      weights["hire_advance"] = _safe_float(weights.get("hire_advance")) * 0.7
      weights["payroll_down"] = _safe_float(weights.get("payroll_down")) * 1.15
      weights["hire_delay"] = _safe_float(weights.get("hire_delay")) * 1.15
      weights["util_down"] = _safe_float(weights.get("util_down")) * 1.2
      profile["weights"] = weights

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

  for profile in profiles:
    constraints = profile.get("constraints") if isinstance(profile, dict) else {}
    constraints = constraints if isinstance(constraints, dict) else {}
    if marketing_up_cap_ratio > 0:
      if str(profile.get("archetype") or "").strip() == "growth":
        constraints["marketing_up_cap_ratio"] = marketing_up_cap_ratio
      else:
        constraints["marketing_up_cap_ratio"] = min(marketing_up_cap_ratio, 0.35 * marketing_up_cap_ratio + 0.03)
    if marketing_down_cap_ratio > 0:
      constraints["marketing_down_cap_ratio"] = marketing_down_cap_ratio
    if other_opex_down_cap_ratio > 0:
      constraints["other_opex_down_cap_ratio"] = other_opex_down_cap_ratio
    if other_opex_up_cap_ratio > 0:
      constraints["other_opex_up_cap_ratio"] = other_opex_up_cap_ratio
    if marketing_role == "constrained" and str(profile.get("archetype") or "").strip() != "growth":
      constraints["marketing_max_ratio"] = min(max(0.0, _safe_float(constraints.get("marketing_max_ratio")) or 1.0), 1.0 + min(marketing_up_cap_ratio, 0.05))
    profile["constraints"] = constraints

  return profiles


def _relax_strategy_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
  relaxed = _clone(profile if isinstance(profile, dict) else {})
  constraints = relaxed.get("constraints") if isinstance(relaxed.get("constraints"), dict) else {}
  constraints = dict(constraints or {})

  def _expand_ratio(key: str, *, floor: Optional[float] = None, ceiling: Optional[float] = None, factor: float = 1.5) -> None:
    raw = constraints.get(key)
    if raw is None:
      return
    value = max(0.0, _safe_float(raw))
    widened = value * factor
    if floor is not None:
      widened = max(floor, widened)
    if ceiling is not None:
      widened = min(ceiling, widened)
    constraints[key] = widened

  _expand_ratio("price_up_cap_ratio", floor=0.12, ceiling=0.20, factor=1.6)
  _expand_ratio("price_down_cap_ratio", floor=0.04, ceiling=0.12, factor=1.5)
  _expand_ratio("util_up_cap_ratio", floor=0.08, ceiling=0.22, factor=1.6)
  _expand_ratio("util_down_cap_ratio", floor=0.10, ceiling=0.28, factor=1.6)
  _expand_ratio("marketing_up_cap_ratio", floor=0.08, ceiling=0.35, factor=1.6)
  _expand_ratio("marketing_down_cap_ratio", floor=0.10, ceiling=0.45, factor=1.4)
  _expand_ratio("other_opex_down_cap_ratio", floor=0.05, ceiling=0.15, factor=1.6)
  _expand_ratio("other_opex_up_cap_ratio", floor=0.04, ceiling=0.15, factor=1.4)
  _expand_ratio("cogs_down_cap_ratio", floor=0.03, ceiling=0.10, factor=1.6)
  _expand_ratio("cogs_up_cap_ratio", floor=0.02, ceiling=0.08, factor=1.4)
  _expand_ratio("payroll_up_max_ratio", floor=0.25, ceiling=0.75, factor=1.6)
  _expand_ratio("payroll_down_max_ratio", floor=0.04, ceiling=0.30, factor=1.6)

  if constraints.get("hire_delay_max_months_total") is not None:
    constraints["hire_delay_max_months_total"] = max(
      float(MAX_ROLE_DELAY_MONTHS),
      _safe_float(constraints.get("hire_delay_max_months_total")),
    )
  if constraints.get("hire_advance_max_months_total") is not None:
    constraints["hire_advance_max_months_total"] = max(
      12.0,
      min(float(MAX_ROLE_DELAY_MONTHS), _safe_float(constraints.get("hire_advance_max_months_total")) * 1.5),
    )
  if constraints.get("units_min_ratio") is not None:
    constraints["units_min_ratio"] = max(0.80, min(1.0, _safe_float(constraints.get("units_min_ratio")) - 0.08))
  if constraints.get("marketing_min_ratio") is not None:
    constraints["marketing_min_ratio"] = max(0.85, min(1.0, _safe_float(constraints.get("marketing_min_ratio")) - 0.10))
  if constraints.get("marketing_max_ratio") is not None:
    constraints["marketing_max_ratio"] = max(
      _safe_float(constraints.get("marketing_max_ratio")),
      min(1.35, _safe_float(constraints.get("marketing_max_ratio")) + 0.15),
    )
  if constraints.get("utilization_min_ratio") is not None:
    constraints["utilization_min_ratio"] = max(0.80, min(1.0, _safe_float(constraints.get("utilization_min_ratio")) - 0.10))
  if constraints.get("utilization_max_ratio") is not None:
    constraints["utilization_max_ratio"] = max(
      _safe_float(constraints.get("utilization_max_ratio")),
      min(1.25, _safe_float(constraints.get("utilization_max_ratio")) + 0.12),
    )

  relaxed["constraints"] = constraints
  relaxed["anchor_strict"] = False
  relaxed["profile_id"] = f"{str(profile.get('profile_id') or 'profile').strip()}__relaxed"
  relaxed["base_profile_id"] = str(profile.get("profile_id") or "").strip()
  return relaxed


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
  commercial_context = (fixed_facts or {}).get("commercial_context") if isinstance(fixed_facts, dict) else {}
  commercial_context = commercial_context if isinstance(commercial_context, dict) else {}

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
  current_staff = (fixed_facts or {}).get("current_staff") if isinstance(fixed_facts, dict) else []
  current_staff = current_staff if isinstance(current_staff, list) else []
  for person in current_staff:
    if not isinstance(person, dict):
      continue
    fixed_people_payroll += max(0.0, _safe_float(person.get("annual_wage")))
  current_payroll_total = max(
    0.0,
    _safe_float((state_model.get("derived_outputs") or {}).get("payroll_total_year1")) if isinstance(state_model, dict) else 0.0,
  )

  roles = (people_drivers or {}).get("inferred_roles") if isinstance(people_drivers, dict) else []
  roles = roles if isinstance(roles, list) else []
  constraint_engine_state = (fixed_facts or {}).get("constraint_engine_state") if isinstance(fixed_facts, dict) else {}
  constraint_engine_state = constraint_engine_state if isinstance(constraint_engine_state, dict) else {}
  current_metrics = (constraint_engine_state or {}).get("current_metrics") if isinstance(constraint_engine_state, dict) else {}
  current_metrics = current_metrics if isinstance(current_metrics, dict) else {}
  role_month_support = _role_month_support_profile(roles)
  role_grounding = _effective_solver_role_grounding(
    fixed_people_payroll=fixed_people_payroll,
    current_payroll_total=current_payroll_total,
    role_month_support=role_month_support,
  )
  fixed_people_payroll = max(
    0.0,
    _safe_float((current_metrics or {}).get("people_payroll_floor"))
    or _safe_float(role_grounding.get("effective_fixed_people_payroll"))
    or fixed_people_payroll,
  )
  baseline_planned_payroll = max(
    0.0,
    _safe_float(role_grounding.get("effective_planned_payroll"))
    or max(0.0, current_payroll_total - fixed_people_payroll),
  )
  baseline_payroll_support = max(
    current_payroll_total,
    fixed_people_payroll + baseline_planned_payroll,
    _safe_float((capacity_curve or {}).get("baseline_payroll_support")),
  )
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
  hard_utilization_floor = _normalize_ratio(
    _safe_float((current_metrics or {}).get("hard_utilization_floor"))
    or _safe_float((util_envelope or {}).get("hard_min"))
  )
  structural_payroll_base = people_payroll_floor
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
  fixed_active_role_months_fallback = 12.0 * float(len([person for person in current_staff if isinstance(person, dict)]))
  payroll_support_basis = str((capacity_curve or {}).get("basis") or "").strip().lower() if bool((capacity_curve or {}).get("enabled")) else ""
  units_per_active_role_month = max(0.0, _safe_float((capacity_curve or {}).get("units_per_active_role_month")))
  fixed_active_role_months = max(
    0.0,
    _safe_float((current_metrics or {}).get("fixed_active_role_months"))
    or _safe_float((capacity_curve or {}).get("fixed_active_role_months"))
    or fixed_active_role_months_fallback,
  )
  baseline_adjustable_active_months = max(
    0.0,
    _safe_float((current_metrics or {}).get("baseline_adjustable_active_months"))
    or _safe_float((capacity_curve or {}).get("baseline_adjustable_active_months"))
    or _safe_float(role_grounding.get("effective_adjustable_active_months"))
    or _safe_float(role_month_support.get("baseline_adjustable_active_months")),
  )
  adjustable_role_month_cost_floor = max(
    0.0,
    _safe_float((current_metrics or {}).get("adjustable_role_month_cost_floor"))
    or _safe_float(role_grounding.get("adjustable_role_month_cost_floor"))
    or _safe_float(role_month_support.get("adjustable_role_month_cost_floor")),
  )
  units_per_payroll_dollar = max(0.0, _safe_float((capacity_curve or {}).get("units_per_payroll_dollar")))
  if (
    payroll_support_basis not in {"role_months", "payroll"}
    and baseline_units > 0
    and (fixed_active_role_months + baseline_adjustable_active_months) > 0
    and adjustable_role_month_cost_floor > 0
  ):
    payroll_support_basis = "role_months"
    units_per_active_role_month = baseline_units / max(fixed_active_role_months + baseline_adjustable_active_months, 1e-9)
  elif payroll_support_basis not in {"role_months", "payroll"} and baseline_units > 0 and people_payroll_floor > 0:
    payroll_support_basis = "payroll"
    units_per_payroll_dollar = baseline_units / max(people_payroll_floor, 1e-9)
  if payroll_support_basis not in {"role_months", "payroll"}:
    payroll_support_basis = "floor"
  marketing_support_units_min = min(
    max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1"))),
    max(0.0, _safe_float((demand_curve or {}).get("baseline_supported_units")) or units_max),
  )
  marketing_support_units_max = max(
    max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1"))),
    max(0.0, _safe_float((demand_curve or {}).get("baseline_supported_units")) or units_max),
  )
  if "payroll_too_light" in active_violations:
    target_payroll_max_total = max(
      target_payroll_max_total,
      structural_payroll_floor,
      max_payroll_total,
    )

  direct_inputs = {
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
    "marketing_demand_link": bool((commercial_context or {}).get("marketing_demand_link")),
    "growth_demand_mode_enabled": bool((commercial_context or {}).get("growth_demand_mode_enabled"))
    and bool((demand_curve or {}).get("enabled"))
    and max(0.0, _safe_float((demand_curve or {}).get("units_per_marketing_dollar"))) > 0,
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
    "workload_payroll_per_unit": 0.0,
    "payroll_support_basis": payroll_support_basis or "floor",
    "units_per_active_role_month": units_per_active_role_month,
    "fixed_active_role_months": fixed_active_role_months,
    "baseline_adjustable_active_months": baseline_adjustable_active_months,
    "adjustable_role_month_cost_floor": adjustable_role_month_cost_floor,
    "units_per_payroll_dollar": units_per_payroll_dollar,
    "role_month_support_profile": _clone(role_month_support.get("role_month_shares") or []),
    "hard_utilization_floor": hard_utilization_floor,
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
    "current_payroll_total": max(
      0.0,
      _safe_float((state_model.get("derived_outputs") or {}).get("payroll_total_year1"))
      or _safe_float((fixed_facts or {}).get("constraint_basis", {}).get("current_payroll")),
    ),
    "rent_annualized": max(0.0, _safe_float((constraint_profile or {}).get("rent_annualized"))),
    "price_upper": max(current_price, _safe_float((price_envelope or {}).get("max"))),
    "price_lower": max(0.0, _safe_float((price_envelope or {}).get("min")) or current_price),
    "current_cogs_ratio": _safe_float(((constraint_profile or {}).get("cogs_envelope") or {}).get("baseline_ratio")),
    "cogs_ratio_min": max(0.0, _safe_float(((constraint_profile or {}).get("cogs_envelope") or {}).get("min_ratio"))),
    "cogs_ratio_max": max(0.0, _safe_float(((constraint_profile or {}).get("cogs_envelope") or {}).get("max_ratio"))),
    "product_driver_basis": _clone((fixed_facts or {}).get("product_driver_basis") or []),
  }
  trace_lazy(
    "DERIVED",
    "Direct solver inputs",
    lambda: direct_inputs,
  )
  return direct_inputs


def _build_blocking_solver_state(
  *,
  baseline_summary: Dict[str, Any],
  state_model: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_realism_distance: float,
  blocking_reason: str,
  governed_attempt_count: int = 0,
  strategy_retry_attempts: Optional[Sequence[Dict[str, Any]]] = None,
  attempted_contract_bundles: Optional[Sequence[Dict[str, Any]]] = None,
  attempted_scenarios: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  blocking_state = {
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
    "governed_attempt_count": max(0, int(governed_attempt_count or 0)),
    "strategy_retry_attempts": _clone(list(strategy_retry_attempts or [])),
    "attempted_contract_bundles": _clone(list(attempted_contract_bundles or [])),
    "attempted_scenarios": _clone(list(attempted_scenarios or [])),
    "scenarios": [],
    "client_scenarios": [],
  }
  trace_lazy(
    "FINAL",
    "Blocking solver state",
    lambda: blocking_state,
  )
  return blocking_state


def _normalized_role_title(value: Any) -> str:
  return " ".join(str(value or "").strip().lower().split())


def _year1_amount_from_start_month(annual_wage: float, start_month: int) -> float:
  clean_start = max(0, int(start_month))
  active_months = max(0, 12 - min(clean_start, 12))
  return max(0.0, annual_wage) * (active_months / 12.0)


def _profile_allowed_levers(profile: Optional[Dict[str, Any]]) -> set:
  if not isinstance(profile, dict):
    return set()
  return {
    str(item or "").strip()
    for item in (profile.get("allowed_levers") or [])
    if str(item or "").strip()
  }


def _profile_constraints(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(profile, dict):
    return {}
  raw = profile.get("constraints")
  return dict(raw or {}) if isinstance(raw, dict) else {}


_CONTROLLER_LEVER_FAMILIES = {
  "price_up",
  "price_down",
  "util_up",
  "util_down",
  "marketing_up",
  "marketing_down",
  "other_opex_down",
  "other_opex_up",
  "cogs_down",
  "cogs_up",
  "hire_delay",
  "hire_advance",
  "payroll_down",
  "payroll_up",
}


_CONTROLLER_LEVER_ALIASES = {
  "pricing": ["price_up", "price_down"],
  "price": ["price_up", "price_down"],
  "opex_up": ["other_opex_up"],
  "opex_down": ["other_opex_down"],
  "overhead_opex": ["other_opex_up", "other_opex_down"],
  "overhead": ["other_opex_up", "other_opex_down"],
  "operating_expense": ["other_opex_up", "other_opex_down"],
  "operating_expenses": ["other_opex_up", "other_opex_down"],
  "other_opex_up": ["other_opex_up"],
  "other_opex_down": ["other_opex_down"],
  "pricing_adjustment": ["price_up", "price_down"],
  "utilization": ["util_up", "util_down"],
  "utilization_adjustment": ["util_up", "util_down"],
  "staffing": ["hire_advance", "hire_delay", "payroll_up", "payroll_down"],
  "staffing_timing_and_payroll": ["hire_advance", "hire_delay", "payroll_up", "payroll_down"],
  "hiring_timing_and_structural_payroll": ["hire_advance", "hire_delay", "payroll_up", "payroll_down"],
  "structural_payroll": ["payroll_up", "payroll_down", "hire_delay"],
  "payroll": ["payroll_up", "payroll_down"],
  "marketing_to_demand_link": ["marketing_up", "util_up"],
  "staffing_support": ["hire_advance", "payroll_up"],
  "staffing_timing": ["hire_advance", "hire_delay"],
  "cost_structure_adjustment": ["other_opex_down", "cogs_down"],
  "extreme_cost_cutting": ["other_opex_down", "cogs_down", "payroll_down", "hire_delay"],
}


def _normalize_controller_lever_family(value: Any) -> List[str]:
  clean = str(value or "").strip().lower()
  if not clean:
    return []
  if clean in _CONTROLLER_LEVER_FAMILIES:
    return [clean]
  aliases = _CONTROLLER_LEVER_ALIASES.get(clean)
  if aliases:
    return [item for item in aliases if item in _CONTROLLER_LEVER_FAMILIES]
  return []


def _strategy_selection(strategy_layer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(strategy_layer, dict):
    return {}
  selection = strategy_layer.get("strategy_selection")
  return selection if isinstance(selection, dict) else {}


def _selection_lever_families(selection: Optional[Dict[str, Any]], key: str) -> List[str]:
  if not isinstance(selection, dict):
    return []
  normalized: List[str] = []
  for item in (selection.get(key) or []):
    normalized.extend(_normalize_controller_lever_family(item))
  return list(dict.fromkeys(normalized))


def _selection_controller_directives(selection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(selection, dict):
    return {}
  directives = selection.get("controller_directives")
  return dict(directives or {}) if isinstance(directives, dict) else {}


def _selection_target_margin_path(selection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
  if not isinstance(selection, dict):
    return {}
  path = selection.get("target_margin_path")
  return dict(path or {}) if isinstance(path, dict) else {}


def _selection_severity_class(selection: Optional[Dict[str, Any]]) -> str:
  if not isinstance(selection, dict):
    return ""
  raw = str(selection.get("severity_class") or "").strip().lower()
  return raw if raw in {"mild", "moderate", "severe"} else ""


def _selection_minimum_package_strength(selection: Optional[Dict[str, Any]]) -> str:
  if not isinstance(selection, dict):
    return ""
  raw = str(selection.get("minimum_package_strength") or "").strip().lower()
  return raw if raw in {"light", "moderate", "strong"} else ""


def _selection_coordinated_lever_packages(selection: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
  if not isinstance(selection, dict):
    return []
  return [
    _clone(item)
    for item in (selection.get("coordinated_lever_packages") or [])
    if isinstance(item, dict)
  ]


def _coordinated_package_levers(
  packages: Optional[List[Dict[str, Any]]],
  *,
  max_quarter: int = 20,
) -> set:
  lever_families: set = set()
  for package in (packages or []):
    if not isinstance(package, dict):
      continue
    quarter_start = _safe_int(package.get("quarter_start")) or 1
    quarter_end = _safe_int(package.get("quarter_end")) or quarter_start
    if quarter_start > max_quarter:
      continue
    if quarter_end < 1:
      continue
    for lever in package.get("levers") or []:
      for clean in _normalize_controller_lever_family(lever):
        lever_families.add(clean)
  return lever_families


def _strategy_layer_retry_attempt(strategy_layer: Optional[Dict[str, Any]]) -> int:
  if not isinstance(strategy_layer, dict):
    return 0
  diagnosis = strategy_layer.get("diagnosis")
  if isinstance(diagnosis, dict):
    return max(0, _safe_int(diagnosis.get("governed_retry_attempt")) or 0)
  return 0


def _controller_aggression_level(directives: Dict[str, Any]) -> str:
  raw = str(directives.get("aggression_level") or "").strip().lower()
  return raw if raw in {"low", "moderate", "high"} else "moderate"


def _severity_directive_minima(
  *,
  severity_class: str,
  minimum_package_strength: str,
) -> Dict[str, Any]:
  severity = str(severity_class or "").strip().lower()
  strength = str(minimum_package_strength or "").strip().lower()
  if severity == "severe":
    return {
      "aggression_level": "high",
      "escalate_on_retry": True,
      "minimum_meaningful_levers": 4,
      "minimum_package_count": 2,
      "minimum_package_strength": "strong",
    }
  if severity == "moderate":
    return {
      "aggression_level": "moderate" if strength != "strong" else "high",
      "escalate_on_retry": True,
      "minimum_meaningful_levers": 3,
      "minimum_package_count": 2,
      "minimum_package_strength": strength or "moderate",
    }
  return {
    "aggression_level": "low" if strength == "light" else "moderate",
    "escalate_on_retry": bool(strength in {"moderate", "strong"}),
    "minimum_meaningful_levers": 2,
    "minimum_package_count": 1,
    "minimum_package_strength": strength or "light",
  }


def _coordinated_package_strength(packages: Optional[List[Dict[str, Any]]]) -> float:
  score = 0.0
  for package in (packages or []):
    if not isinstance(package, dict):
      continue
    strength = str(package.get("minimum_strength") or "").strip().lower()
    if strength == "strong":
      score += 1.0
    elif strength == "moderate":
      score += 0.5
    elif strength == "light":
      score += 0.25
  return score


def _package_strength_rank(value: str) -> int:
  return {"light": 1, "moderate": 2, "strong": 3}.get(str(value or "").strip().lower(), 0)


def _target_margin_path_is_progressive(
  path: Dict[str, Any],
  *,
  severity_class: str,
) -> bool:
  if not isinstance(path, dict) or not path:
    return False
  year1_min = path.get("year1_min")
  year2_min = path.get("year2_min")
  year3_min = path.get("year3_min")
  year1_max = path.get("year1_max")
  year2_max = path.get("year2_max")
  year3_max = path.get("year3_max")
  if any(v is None for v in (year1_min, year2_min, year3_min, year1_max, year2_max, year3_max)):
    return False
  y1_min = _safe_float(year1_min)
  y2_min = _safe_float(year2_min)
  y3_min = _safe_float(year3_min)
  y1_max = _safe_float(year1_max)
  y2_max = _safe_float(year2_max)
  y3_max = _safe_float(year3_max)
  if y1_min > y1_max or y2_min > y2_max or y3_min > y3_max:
    return False
  if y2_min < y1_min or y3_min < y2_min:
    return False
  if y2_max < y1_max or y3_max < y2_max:
    return False
  if severity_class == "severe":
    if y2_min < (y1_min + 0.08):
      return False
    if y3_min < (y2_min + 0.05):
      return False
  elif severity_class == "moderate":
    if y2_min < (y1_min + 0.04):
      return False
    if y3_min < (y2_min + 0.03):
      return False
  return True


def _package_expected_effects(packages: Optional[List[Dict[str, Any]]], *, max_quarter: int = 4) -> set:
  effects: set = set()
  for package in (packages or []):
    if not isinstance(package, dict):
      continue
    quarter_start = _safe_int(package.get("quarter_start")) or 1
    quarter_end = _safe_int(package.get("quarter_end")) or quarter_start
    if quarter_start > max_quarter or quarter_end < 1:
      continue
    for effect in package.get("expected_effects") or []:
      clean = str(effect or "").strip().lower()
      if clean:
        effects.add(clean)
        if "opex" in clean or "overhead" in clean or "compliance" in clean or "admin" in clean:
          effects.add("support_opex_required")
        if "payroll" in clean or "structural floor" in clean or "role months" in clean:
          effects.add("structural_staffing_required")
        if "advance activation" in clean or ("hire" in clean and ("advance" in clean or "activate" in clean)):
          effects.add("capacity_expands_with_staffing")
        if "ease utilization" in clean or "avoiding overstretching" in clean or "avoid overstretching" in clean:
          effects.add("capacity_tighter_until_hires")
        if "price" in clean and ("soften" in clean or "elastic" in clean or "demand" in clean):
          effects.add("demand_softens_with_price")
        if "marketing" in clean or "build demand" in clean or "demand growth" in clean or "utilization gradually increases" in clean:
          effects.add("demand_requires_marketing_support")
        if ("growth" in clean or "utilization" in clean or "demand" in clean) and ("cost" in clean or "opex" in clean or "payroll" in clean):
          effects.add("costs_scale_with_growth")
  return effects


def _package_policy_biases(
  *,
  package: Dict[str, Any],
  target_posture: Dict[str, Any],
) -> Dict[str, Any]:
  levers = _coordinated_package_levers([package], max_quarter=20)
  demand_posture = "moderate"
  if "marketing_up" in levers or "util_up" in levers:
    demand_posture = "build"
  elif "util_down" in levers:
    demand_posture = "cautious"
  staffing_posture = "rebalance"
  if "hire_advance" in levers or "payroll_up" in levers:
    staffing_posture = "ramp_support"
  elif "hire_delay" in levers or "payroll_down" in levers:
    staffing_posture = "delay"
  cost_posture = "moderate"
  if "other_opex_up" in levers:
    cost_posture = "normalize_up"
  elif "other_opex_down" in levers or "cogs_down" in levers:
    cost_posture = "tighten"
  growth_multiplier = 1.0
  if "marketing_up" in levers or "util_up" in levers:
    growth_multiplier += 0.05
  if "util_down" in levers:
    growth_multiplier -= 0.05
  return {
    "quarter_start": max(1, _safe_int(package.get("quarter_start")) or 1),
    "quarter_end": max(1, _safe_int(package.get("quarter_end")) or (_safe_int(package.get("quarter_start")) or 1)),
    "active_levers": sorted(list(levers)),
    "growth_multiplier": round(growth_multiplier, 3),
    "convergence_multiplier": 0.82 if "marketing_up" in levers or "util_up" in levers else 0.75,
    "capacity_release_multiplier": 1.05 if "hire_advance" in levers else 1.0,
    "marketing_ratio_bias": 0.02 if "marketing_up" in levers else 0.0,
    "opex_ratio_bias": 0.12 if "other_opex_up" in levers else (-0.04 if "other_opex_down" in levers else 0.0),
    "payroll_ratio_bias": 0.08 if "payroll_up" in levers else (-0.05 if "payroll_down" in levers else 0.0),
    "price_growth_bias": 0.01 if "price_up" in levers else (-0.01 if "price_down" in levers else 0.0),
    "utilization_target_bias": 0.03 if "util_up" in levers else (-0.03 if "util_down" in levers else 0.0),
    "demand_posture": demand_posture,
    "staffing_posture": staffing_posture,
    "cost_posture": cost_posture,
  }


def _merge_controller_package_orchestration(
  *,
  profile: Dict[str, Any],
  packages: Optional[List[Dict[str, Any]]],
  target_posture: Dict[str, Any],
) -> Dict[str, Any]:
  base = _clone(profile.get("forecast_orchestration") or {})
  if not isinstance(base, dict):
    base = {}
  existing_policies = [
    _clone(item)
    for item in (base.get("quarter_policies") or [])
    if isinstance(item, dict)
  ]
  merged_policies = list(existing_policies)
  for package in (packages or []):
    if not isinstance(package, dict):
      continue
    policy = _package_policy_biases(package=package, target_posture=target_posture)
    if any(
      _safe_int(item.get("quarter_start")) == _safe_int(policy.get("quarter_start"))
      and _safe_int(item.get("quarter_end")) == _safe_int(policy.get("quarter_end"))
      for item in merged_policies
      if isinstance(item, dict)
    ):
      continue
    merged_policies.append(policy)
  merged_policies.sort(
    key=lambda item: (
      _safe_int(item.get("quarter_start")) or 1,
      _safe_int(item.get("quarter_end")) or 1,
    )
  )
  if merged_policies:
    base["quarter_policies"] = merged_policies
  if "orchestration_summary" not in base or not str(base.get("orchestration_summary") or "").strip():
    base["orchestration_summary"] = "controller-enforced multi-quarter viability orchestration"
  return base


def _expand_to_minimum_meaningful_levers(
  *,
  effective_levers: set,
  minimum_count: int,
  primary_cause: str,
  active_violations: set,
  forbidden_levers: set,
) -> set:
  next_levers = set(effective_levers)
  preferred_order: List[str] = []
  if primary_cause == "payroll-driven":
    if "payroll_too_heavy" in active_violations:
      preferred_order = ["hire_delay", "price_up", "util_up", "other_opex_down", "cogs_down"]
    else:
      preferred_order = ["hire_advance", "payroll_up", "util_down", "price_up", "marketing_down"]
  elif primary_cause == "pricing-driven":
    preferred_order = ["price_up", "util_down", "marketing_down", "other_opex_down"]
  elif primary_cause == "utilization-driven":
    preferred_order = ["util_down", "hire_advance", "payroll_up", "price_up", "marketing_down"]
  else:
    preferred_order = ["price_up", "util_down", "hire_delay", "other_opex_down", "marketing_down"]
  for lever in preferred_order:
    if len(next_levers) >= minimum_count:
      break
    if lever in forbidden_levers or lever not in _CONTROLLER_LEVER_FAMILIES:
      continue
    next_levers.add(lever)
  return next_levers


def _gpt_blueprint_is_usable(selection: Optional[Dict[str, Any]]) -> bool:
  if not isinstance(selection, dict):
    return False
  selected_ids = [
    str(item or "").strip()
    for item in (selection.get("selected_strategy_ids") or [])
    if str(item or "").strip()
  ]
  if not selected_ids:
    return False
  if not str(selection.get("business_model_assessment") or "").strip():
    return False
  if not isinstance(selection.get("controller_directives"), dict):
    return False
  severity_class = _selection_severity_class(selection)
  if not severity_class:
    return False
  if not str(selection.get("severity_reason") or "").strip():
    return False
  minimum_package_strength = _selection_minimum_package_strength(selection)
  if not minimum_package_strength:
    return False
  if not isinstance(selection.get("target_margin_path"), dict):
    return False
  if not _target_margin_path_is_progressive(selection.get("target_margin_path") or {}, severity_class=severity_class):
    return False
  if not isinstance(selection.get("target_posture"), dict):
    return False
  directives = _selection_controller_directives(selection)
  minimum_meaningful_levers = max(1, _safe_int(directives.get("minimum_meaningful_levers")) or 1)
  minimum_package_count = max(1, _safe_int(directives.get("minimum_package_count")) or 1)
  aggression = _controller_aggression_level(directives)
  required_levers = _selection_lever_families(selection, "required_lever_families")
  if not required_levers:
    return False
  packages = _selection_coordinated_lever_packages(selection)
  if not packages:
    return False
  package_strength_score = _coordinated_package_strength(packages)
  strongest_package_rank = max(
    (_package_strength_rank(str(item.get("minimum_strength") or "").strip().lower()) for item in packages if isinstance(item, dict)),
    default=0,
  )
  if severity_class == "severe":
    if aggression != "high":
      return False
    if not bool(directives.get("escalate_on_retry")):
      return False
    if minimum_meaningful_levers < 4 or minimum_package_count < 2:
      return False
    if len(required_levers) < 4 or len(packages) < 2:
      return False
    if strongest_package_rank < _package_strength_rank("strong"):
      return False
    if package_strength_score < 1.5:
      return False
  elif severity_class == "moderate":
    if aggression == "low":
      return False
    if minimum_meaningful_levers < 3 or minimum_package_count < 2:
      return False
    if len(required_levers) < 3 or len(packages) < 2:
      return False
    if strongest_package_rank < _package_strength_rank(minimum_package_strength):
      return False
    if package_strength_score < 1.0:
      return False
  else:
    if strongest_package_rank < _package_strength_rank(minimum_package_strength):
      return False
  return True


def _minimum_constraint_overrides_for_levers(
  effective_levers: set,
  current_constraints: Dict[str, Any],
) -> Dict[str, Any]:
  next_constraints = dict(current_constraints or {})

  def _ensure_min(key: str, value: float) -> None:
    current = next_constraints.get(key)
    if current is None:
      next_constraints[key] = value
      return
    if isinstance(current, bool):
      return
    next_constraints[key] = max(value, _safe_float(current))

  if "price_up" in effective_levers:
    _ensure_min("price_up_cap_ratio", 0.06)
  if "price_down" in effective_levers:
    _ensure_min("price_down_cap_ratio", 0.06)
  if "util_up" in effective_levers:
    _ensure_min("util_up_cap_ratio", 0.08)
    _ensure_min("utilization_max_ratio", 1.05)
  if "util_down" in effective_levers:
    _ensure_min("util_down_cap_ratio", 0.08)
    existing = next_constraints.get("utilization_min_ratio")
    if existing is None:
      next_constraints["utilization_min_ratio"] = 0.9
    elif not isinstance(existing, bool):
      next_constraints["utilization_min_ratio"] = min(0.95, _safe_float(existing))
  if "marketing_up" in effective_levers:
    _ensure_min("marketing_up_cap_ratio", 0.10)
    _ensure_min("marketing_max_ratio", 1.10)
  if "marketing_down" in effective_levers:
    _ensure_min("marketing_down_cap_ratio", 0.10)
    existing = next_constraints.get("marketing_min_ratio")
    if existing is None:
      next_constraints["marketing_min_ratio"] = 0.85
    elif not isinstance(existing, bool):
      next_constraints["marketing_min_ratio"] = min(0.95, _safe_float(existing))
  if "other_opex_down" in effective_levers:
    _ensure_min("other_opex_down_cap_ratio", 0.05)
  if "other_opex_up" in effective_levers:
    _ensure_min("other_opex_up_cap_ratio", 0.05)
  if "cogs_down" in effective_levers:
    _ensure_min("cogs_down_cap_ratio", 0.03)
  if "cogs_up" in effective_levers:
    _ensure_min("cogs_up_cap_ratio", 0.03)
  if "payroll_down" in effective_levers:
    _ensure_min("payroll_down_max_ratio", 0.12)
  if "payroll_up" in effective_levers:
    _ensure_min("payroll_up_max_ratio", 0.30)
  if "hire_delay" in effective_levers:
    _ensure_min("hire_delay_max_months_total", float(MAX_ROLE_DELAY_MONTHS))
  if "hire_advance" in effective_levers:
    _ensure_min("hire_advance_max_months_total", 12.0)
  return next_constraints


def _apply_retry_and_aggression_overrides(
  *,
  constraints: Dict[str, Any],
  directives: Dict[str, Any],
  retry_attempt: int,
  primary_cause: str,
  target_margin_path: Dict[str, Any],
  package_strength: float,
) -> Dict[str, Any]:
  next_constraints = dict(constraints or {})
  aggression = _controller_aggression_level(directives)
  escalate = bool(directives.get("escalate_on_retry"))
  if retry_attempt <= 0 and not package_strength:
    return next_constraints

  retry_boost = float(retry_attempt if escalate else 0)
  if aggression == "high":
    retry_boost += 1.0
  elif aggression == "moderate":
    retry_boost += 0.5
  retry_boost += min(1.5, package_strength * 0.5)

  year2_min = _safe_float(target_margin_path.get("year2_min"))
  year3_min = _safe_float(target_margin_path.get("year3_min"))
  positive_path = (year2_min is not None and year2_min >= 0.0) or (year3_min is not None and year3_min > 0.0)

  def _raise_cap(key: str, delta: float, hard_cap: float) -> None:
    current = _safe_float(next_constraints.get(key))
    current = current if current is not None else 0.0
    next_constraints[key] = min(hard_cap, current + delta)

  if retry_boost <= 0:
    return next_constraints

  if primary_cause == "pricing-driven":
    _raise_cap("price_up_cap_ratio", 0.03 * retry_boost, 0.25)
    _raise_cap("util_down_cap_ratio", 0.02 * retry_boost, 0.20)
    if positive_path:
      existing = _safe_float(next_constraints.get("units_min_ratio"))
      existing = existing if existing is not None else 1.0
      next_constraints["units_min_ratio"] = max(0.80, existing - (0.02 * retry_boost))
  elif primary_cause == "payroll-driven":
    _raise_cap("hire_delay_max_months_total", 6.0 * retry_boost, float(max(MAX_ROLE_DELAY_MONTHS, 30)))
    _raise_cap("payroll_down_max_ratio", 0.04 * retry_boost, 0.25)
    _raise_cap("payroll_up_max_ratio", 0.06 * retry_boost, 0.60)
    _raise_cap("util_down_cap_ratio", 0.03 * retry_boost, 0.25)
    if positive_path:
      _raise_cap("price_up_cap_ratio", 0.02 * retry_boost, 0.20)
  elif primary_cause == "utilization-driven":
    _raise_cap("util_up_cap_ratio", 0.03 * retry_boost, 0.25)
    _raise_cap("hire_advance_max_months_total", 4.0 * retry_boost, 24.0)
    _raise_cap("payroll_up_max_ratio", 0.05 * retry_boost, 0.60)
  else:
    _raise_cap("price_up_cap_ratio", 0.02 * retry_boost, 0.22)
    _raise_cap("util_down_cap_ratio", 0.02 * retry_boost, 0.20)
    _raise_cap("other_opex_down_cap_ratio", 0.02 * retry_boost, 0.12)
    _raise_cap("hire_delay_max_months_total", 4.0 * retry_boost, float(max(MAX_ROLE_DELAY_MONTHS, 30)))

  return next_constraints


def _apply_expected_effect_linkages(
  *,
  effective_levers: set,
  package_effects: set,
  active_violations: set,
  forbidden_levers: set,
) -> set:
  next_levers = set(effective_levers)
  if "capacity_tighter_until_hires" in package_effects:
    next_levers.update({"hire_delay", "util_down"})
  if "capacity_expands_with_staffing" in package_effects:
    next_levers.update({"hire_advance", "payroll_up", "util_up"})
  if "demand_softens_with_price" in package_effects:
    next_levers.update({"price_up", "util_down"})
  if "demand_requires_marketing_support" in package_effects:
    next_levers.update({"marketing_up"})
    if "payroll_too_light" in active_violations or "capacity_unsupported" in active_violations:
      next_levers.update({"hire_advance", "payroll_up"})
  if "costs_scale_with_growth" in package_effects:
    next_levers.update({"other_opex_up", "marketing_up"})
  if "support_opex_required" in package_effects:
    next_levers.update({"other_opex_up"})
  if "structural_staffing_required" in package_effects:
    next_levers.update({"hire_advance", "payroll_up"})
  next_levers.difference_update(forbidden_levers)
  return {lever for lever in next_levers if lever in _CONTROLLER_LEVER_FAMILIES}


def _controller_enforced_profile(
  *,
  profile: Dict[str, Any],
  strategy_layer: Dict[str, Any],
  active_violations: set,
) -> Dict[str, Any]:
  next_profile = _clone(profile or {})
  selection = _strategy_selection(strategy_layer)
  diagnosis = strategy_layer.get("diagnosis") if isinstance(strategy_layer.get("diagnosis"), dict) else {}
  diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
  directives = _selection_controller_directives(selection)
  target_margin_path = _selection_target_margin_path(selection)
  severity_class = _selection_severity_class(selection) or str(diagnosis.get("severity_class") or "").strip().lower()
  minimum_package_strength = _selection_minimum_package_strength(selection) or str(diagnosis.get("minimum_package_strength") or "").strip().lower()
  severity_minima = _severity_directive_minima(
    severity_class=severity_class,
    minimum_package_strength=minimum_package_strength,
  )
  directives = dict(directives or {})
  existing_min_levers = max(1, _safe_int(directives.get("minimum_meaningful_levers")) or 1)
  existing_min_packages = max(1, _safe_int(directives.get("minimum_package_count")) or 1)
  directives["minimum_meaningful_levers"] = max(existing_min_levers, _safe_int(severity_minima.get("minimum_meaningful_levers")) or 1)
  directives["minimum_package_count"] = max(existing_min_packages, _safe_int(severity_minima.get("minimum_package_count")) or 1)
  if _controller_aggression_level(severity_minima) == "high":
    directives["aggression_level"] = "high"
  elif _controller_aggression_level(directives) not in {"moderate", "high"}:
    directives["aggression_level"] = str(severity_minima.get("aggression_level") or "moderate")
  directives["escalate_on_retry"] = bool(directives.get("escalate_on_retry")) or bool(severity_minima.get("escalate_on_retry"))
  required_levers = set(_selection_lever_families(selection, "required_lever_families"))
  forbidden_levers = set(_selection_lever_families(selection, "forbidden_lever_families"))
  coordinated_packages = _selection_coordinated_lever_packages(selection)
  package_levers = _coordinated_package_levers(coordinated_packages)
  package_effects = _package_expected_effects(coordinated_packages, max_quarter=20)
  package_strength = _coordinated_package_strength(coordinated_packages)
  primary_cause = str(diagnosis.get("primary_cause") or "").strip().lower()
  retry_attempt = _strategy_layer_retry_attempt(strategy_layer)
  current_allowed = _profile_allowed_levers(next_profile)
  effective_levers = set(current_allowed)
  effective_levers.update(required_levers)
  effective_levers.update(package_levers)

  require_multi = bool(directives.get("require_multi_lever_coordination"))
  if require_multi:
    if primary_cause == "payroll-driven":
      if "payroll_too_heavy" in active_violations:
        effective_levers.update({"hire_delay", "price_up", "util_up", "other_opex_down"})
      elif "payroll_too_light" in active_violations:
        effective_levers.update({"hire_advance", "payroll_up", "util_down", "price_up"})
    elif primary_cause == "pricing-driven":
      effective_levers.update({"price_up", "util_down"})
    elif primary_cause == "utilization-driven":
      if "capacity_unsupported" in active_violations or "payroll_too_light" in active_violations:
        effective_levers.update({"util_down", "hire_advance", "payroll_up"})
      else:
        effective_levers.update({"util_up", "price_up"})
    elif primary_cause == "mixed":
      effective_levers.update({"price_up", "util_down", "other_opex_down", "hire_delay"})

  if severity_class == "severe":
    if primary_cause == "pricing-driven":
      effective_levers.update({"price_up", "cogs_down", "other_opex_down", "hire_delay", "util_up"})
    elif primary_cause == "payroll-driven":
      if "payroll_too_heavy" in active_violations:
        effective_levers.update({"hire_delay", "price_up", "cogs_down", "other_opex_down", "util_up"})
      else:
        effective_levers.update({"hire_advance", "payroll_up", "price_up", "other_opex_up", "util_down"})
    elif primary_cause == "utilization-driven":
      effective_levers.update({"util_up", "price_up", "cogs_down", "other_opex_down", "hire_advance", "payroll_up"})
    else:
      effective_levers.update({"price_up", "cogs_down", "other_opex_down", "hire_delay", "util_up"})

  if bool(directives.get("preserve_price_demand_link")):
    if "price_up" in effective_levers:
      effective_levers.add("util_down")
    if "price_down" in effective_levers:
      effective_levers.add("util_up")
  if bool(directives.get("preserve_marketing_demand_link")) and "marketing_up" in effective_levers:
    effective_levers.add("util_up")
    if "payroll_too_light" in active_violations or "capacity_unsupported" in active_violations:
      effective_levers.update({"hire_advance", "payroll_up"})
  if bool(directives.get("preserve_capacity_staffing_link")):
    if "hire_delay" in effective_levers or "payroll_down" in effective_levers:
      effective_levers.add("util_down")
    if "hire_advance" in effective_levers or "payroll_up" in effective_levers:
      effective_levers.add("util_up")
  if bool(directives.get("prefer_delay_over_delete")) and "payroll_down" in effective_levers:
    effective_levers.add("hire_delay")

  minimum_meaningful_levers = max(1, _safe_int(directives.get("minimum_meaningful_levers")) or 1)
  minimum_package_count = max(1, _safe_int(directives.get("minimum_package_count")) or 1)
  if retry_attempt > 0 and bool(directives.get("escalate_on_retry")):
    minimum_meaningful_levers = min(6, minimum_meaningful_levers + retry_attempt)
    minimum_package_count = min(4, minimum_package_count + min(1, retry_attempt))
  effective_levers = _expand_to_minimum_meaningful_levers(
    effective_levers=effective_levers,
    minimum_count=minimum_meaningful_levers,
    primary_cause=primary_cause,
    active_violations=active_violations,
    forbidden_levers=forbidden_levers,
  )
  effective_levers = _apply_expected_effect_linkages(
    effective_levers=effective_levers,
    package_effects=package_effects,
    active_violations=active_violations,
    forbidden_levers=forbidden_levers,
  )

  effective_levers.difference_update(forbidden_levers)
  effective_levers = {
    lever for lever in effective_levers
    if lever in _CONTROLLER_LEVER_FAMILIES
  }

  current_constraints = _profile_constraints(next_profile)
  next_constraints = _minimum_constraint_overrides_for_levers(
    effective_levers=effective_levers,
    current_constraints=current_constraints,
  )
  next_constraints = _apply_retry_and_aggression_overrides(
    constraints=next_constraints,
    directives=directives,
    retry_attempt=retry_attempt,
    primary_cause=primary_cause,
    target_margin_path=target_margin_path,
    package_strength=package_strength,
  )
  next_profile["allowed_levers"] = sorted(list(effective_levers))
  next_profile["constraints"] = _strategy_constraints_for_allowed_levers(
    next_profile.get("allowed_levers") or [],
    base_constraints=next_constraints,
  )
  next_profile["controller_directives"] = _clone(directives)
  next_profile["coordinated_lever_packages"] = coordinated_packages
  next_profile["business_model_assessment"] = str(selection.get("business_model_assessment") or "").strip()
  next_profile["target_margin_path"] = _clone(target_margin_path)
  target_posture = _clone(selection.get("target_posture") or {}) if isinstance(selection.get("target_posture"), dict) else {}
  next_profile["target_posture"] = target_posture
  next_profile["forecast_orchestration"] = _merge_controller_package_orchestration(
    profile=next_profile,
    packages=coordinated_packages,
    target_posture=target_posture,
  )

  return {
    "profile": next_profile,
    "diagnostics": {
      "retry_attempt": retry_attempt,
      "primary_cause": primary_cause,
      "required_lever_families": sorted(list(required_levers)),
      "forbidden_lever_families": sorted(list(forbidden_levers)),
      "package_lever_families": sorted(list(package_levers)),
      "package_expected_effects": sorted(list(package_effects)),
      "package_strength_score": package_strength,
      "effective_lever_families": sorted(list(effective_levers)),
      "controller_directives": _clone(directives),
      "target_margin_path": _clone(target_margin_path),
      "coordinated_lever_packages": coordinated_packages[:8],
      "business_model_assessment": str(selection.get("business_model_assessment") or "").strip(),
      "target_posture": _clone(selection.get("target_posture") or {}) if isinstance(selection.get("target_posture"), dict) else {},
      "minimum_package_count": minimum_package_count,
      "severity_class": severity_class,
      "minimum_package_strength": minimum_package_strength or str(severity_minima.get("minimum_package_strength") or "").strip(),
    },
  }


def _profile_role_timing_overrides(profile: Optional[Dict[str, Any]]) -> Dict[str, int]:
  if not isinstance(profile, dict):
    return {}
  orchestration = profile.get("forecast_orchestration")
  orchestration = orchestration if isinstance(orchestration, dict) else {}
  overrides = orchestration.get("role_timing_overrides") if isinstance(orchestration, dict) else []
  overrides = overrides if isinstance(overrides, list) else []
  timing_by_title: Dict[str, int] = {}
  for item in overrides:
    if not isinstance(item, dict):
      continue
    title = _normalized_role_title(item.get("role_title"))
    months = _safe_int(item.get("months_until_activate"))
    if not title or months is None:
      continue
    timing_by_title[title] = max(0, months)
  return timing_by_title


def _apply_profile_role_contract(
  roles: List[Dict[str, Any]],
  *,
  profile: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  allowed_levers = _profile_allowed_levers(profile)
  timing_overrides = _profile_role_timing_overrides(profile)
  adjusted_roles: List[Dict[str, Any]] = []
  for role in roles:
    if not isinstance(role, dict):
      continue
    next_role = _clone(role)
    role_title = _normalized_role_title(next_role.get("role_title"))
    base_months = max(0, _safe_int(next_role.get("base_months")) or 0)
    min_months = max(0, _safe_int(next_role.get("min_months")) or 0)
    max_months = max(base_months, _safe_int(next_role.get("max_months")) or max(MAX_ROLE_DELAY_MONTHS, base_months))
    override_months = timing_overrides.get(role_title)
    if override_months is not None:
      base_months = max(0, override_months)
      if "hire_advance" not in allowed_levers:
        min_months = max(min_months, base_months)
      if "hire_delay" not in allowed_levers:
        max_months = min(max_months, base_months)
      max_months = max(min_months, max_months)
    annual_wage = max(0.0, _safe_float(next_role.get("annual_wage")))
    next_role["base_months"] = base_months
    next_role["min_months"] = min_months
    next_role["max_months"] = max_months
    next_role["baseline_year1_amount"] = _year1_amount_from_start_month(annual_wage, base_months)
    adjusted_roles.append(next_role)
  return adjusted_roles


def _estimate_contract_ebitda_bounds(contract_inputs: Dict[str, Any]) -> Tuple[float, float]:
  current_revenue = max(0.0, _safe_float(contract_inputs.get("current_revenue")))
  baseline_units = max(0.0, _safe_float(contract_inputs.get("baseline_units")))
  units_min = max(0.0, _safe_float(contract_inputs.get("units_min")))
  units_max = max(units_min, _safe_float(contract_inputs.get("units_max")) or units_min)
  current_price = max(0.0, _safe_float(contract_inputs.get("current_price")))
  price_lower = max(0.0, _safe_float(contract_inputs.get("price_lower")) or current_price)
  price_upper = max(price_lower, _safe_float(contract_inputs.get("price_upper")) or price_lower)
  revenue_min = current_revenue
  revenue_max = current_revenue
  if baseline_units > 0 and current_price > 0 and current_revenue > 0:
    units_scale_min = units_min / max(baseline_units, 1e-9)
    units_scale_max = units_max / max(baseline_units, 1e-9)
    price_scale_min = price_lower / max(current_price, 1e-9)
    price_scale_max = price_upper / max(current_price, 1e-9)
    revenue_min = current_revenue * min(max(units_scale_min, 0.0), max(units_scale_max, 0.0)) * min(price_scale_min, price_scale_max)
    revenue_max = current_revenue * max(units_scale_max, 0.0) * max(price_scale_max, 0.0)
  cogs_ratio_min = max(0.0, _safe_float(contract_inputs.get("cogs_ratio_min")))
  cogs_ratio_max = max(cogs_ratio_min, _safe_float(contract_inputs.get("cogs_ratio_max")) or cogs_ratio_min)
  payroll_min = max(
    0.0,
    _safe_float(contract_inputs.get("target_payroll_min_total"))
    or _safe_float(contract_inputs.get("structural_payroll_floor"))
    or _safe_float(contract_inputs.get("people_payroll_floor")),
  )
  payroll_max = max(payroll_min, _safe_float(contract_inputs.get("target_payroll_max_total")) or payroll_min)
  marketing_min = max(0.0, _safe_float(contract_inputs.get("marketing_min")))
  marketing_max = max(marketing_min, _safe_float(contract_inputs.get("marketing_upper")) or marketing_min)
  other_opex_min = max(0.0, _safe_float(contract_inputs.get("other_opex_min")))
  other_opex_max = max(other_opex_min, _safe_float(contract_inputs.get("other_opex_max")) or other_opex_min)
  rent_annualized = max(0.0, _safe_float(contract_inputs.get("rent_annualized")))
  current_interest = max(0.0, _safe_float(contract_inputs.get("current_interest")))
  optimistic_ebitda = revenue_max - (revenue_max * cogs_ratio_min) - payroll_min - marketing_min - other_opex_min - rent_annualized
  pessimistic_ebitda = revenue_min - (revenue_min * cogs_ratio_max) - payroll_max - marketing_max - other_opex_max - rent_annualized
  return (
    optimistic_ebitda - current_interest,
    pessimistic_ebitda - current_interest,
  )


def _build_profile_solver_contract(
  *,
  state_model: Dict[str, Any],
  direct_inputs: Dict[str, Any],
  profile: Dict[str, Any],
  target_ebitda_min: Optional[float],
  target_ebitda_max: Optional[float],
  ) -> Dict[str, Any]:
  contract_inputs = _clone(direct_inputs or {})
  issues: List[str] = []
  adjustments: List[str] = []
  strategy_layer = state_model.get("strategy_layer") if isinstance(state_model, dict) else {}
  strategy_layer = strategy_layer if isinstance(strategy_layer, dict) else {}
  diagnosis = strategy_layer.get("diagnosis") if isinstance(strategy_layer.get("diagnosis"), dict) else {}
  diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
  active_violations = {
    str(code or "").strip()
    for code in (contract_inputs.get("constraint_violations") or [])
    if str(code or "").strip()
  }
  hard_violations = {code for code in active_violations if code in DEFAULT_HARD_YEAR1_VIOLATIONS}
  profile_contract = _controller_enforced_profile(
    profile=profile,
    strategy_layer=strategy_layer,
    active_violations=active_violations,
  )
  effective_profile = (
    profile_contract.get("profile")
    if isinstance(profile_contract.get("profile"), dict)
    else _clone(profile)
  )
  profile_contract_diagnostics = (
    profile_contract.get("diagnostics")
    if isinstance(profile_contract.get("diagnostics"), dict)
    else {}
  )
  strategy_source = str(effective_profile.get("strategy_source") or strategy_layer.get("source") or "").strip().lower()
  allowed_levers = _profile_allowed_levers(effective_profile)
  profile_constraints = _profile_constraints(effective_profile)

  if strategy_source == "gpt":
    original_roles = [
      item for item in (contract_inputs.get("roles") or [])
      if isinstance(item, dict)
    ]
    adjusted_roles = _apply_profile_role_contract(original_roles, profile=effective_profile)
    if adjusted_roles != original_roles:
      contract_inputs["roles"] = adjusted_roles
      role_support = _role_month_support_profile(adjusted_roles)
      contract_inputs["role_month_support_profile"] = _clone(role_support.get("role_month_shares") or [])
      contract_inputs["baseline_adjustable_active_months"] = max(
        0.0,
        _safe_float(role_support.get("baseline_adjustable_active_months")),
      )
      contract_inputs["adjustable_role_month_cost_floor"] = max(
        0.0,
        _safe_float(role_support.get("adjustable_role_month_cost_floor")),
      )
      adjusted_planned_payroll = sum(
        max(0.0, _safe_float(role.get("baseline_year1_amount")))
        for role in adjusted_roles
        if isinstance(role, dict)
      )
      fixed_people_payroll = max(0.0, _safe_float(contract_inputs.get("fixed_people_payroll")))
      if "payroll_too_heavy" in active_violations and "payroll_too_light" not in hard_violations:
        contract_inputs["people_payroll_floor"] = fixed_people_payroll
        contract_inputs["structural_payroll_floor"] = fixed_people_payroll
        contract_inputs["structural_payroll_base"] = fixed_people_payroll
        contract_inputs["baseline_planned_payroll"] = adjusted_planned_payroll
        contract_inputs["baseline_payroll_support"] = max(
          fixed_people_payroll,
          fixed_people_payroll + adjusted_planned_payroll,
        )
        contract_inputs["target_payroll_min_total"] = max(
          fixed_people_payroll,
          _safe_float(contract_inputs.get("people_payroll_floor")),
        )
        contract_inputs["target_payroll_max_total"] = max(
          _safe_float(contract_inputs.get("target_payroll_min_total")),
          fixed_people_payroll + adjusted_planned_payroll,
        )
        adjustments.append("translated_gpt_role_timing_into_payroll_contract")

    package_effects = {
      str(item or "").strip()
      for item in (profile_contract_diagnostics.get("package_expected_effects") or [])
      if str(item or "").strip()
    }
    current_revenue = max(0.0, _safe_float(contract_inputs.get("current_revenue")))
    rent_annualized = max(0.0, _safe_float(contract_inputs.get("rent_annualized")))
    opex_ratio_min = max(0.0, _safe_float(contract_inputs.get("opex_ratio_min")))
    opex_ratio_max = max(opex_ratio_min, _safe_float(contract_inputs.get("opex_ratio_max")) or opex_ratio_min)
    if "opex_too_light" in active_violations and "other_opex_up" in allowed_levers:
      current_other_opex = max(0.0, _safe_float(contract_inputs.get("current_other_opex")))
      realistic_opex_floor = max(
        current_other_opex,
        (current_revenue * opex_ratio_min) - rent_annualized if current_revenue > 0 and opex_ratio_min > 0 else current_other_opex,
      )
      realistic_opex_ceiling = max(
        realistic_opex_floor,
        (current_revenue * opex_ratio_max) - rent_annualized if current_revenue > 0 and opex_ratio_max > 0 else realistic_opex_floor,
      )
      contract_inputs["other_opex_min"] = realistic_opex_floor
      contract_inputs["other_opex_max"] = realistic_opex_ceiling
      contract_inputs["other_opex_enabled"] = bool(realistic_opex_ceiling > realistic_opex_floor + 0.01)
      adjustments.append("expanded_opex_contract_to_realism_band")
    elif "opex_too_light" in active_violations and "other_opex_up" not in allowed_levers:
      current_other_opex = max(0.0, _safe_float(contract_inputs.get("current_other_opex")))
      down_cap_ratio = max(0.0, _safe_float(profile_constraints.get("other_opex_down_cap_ratio")))
      up_cap_ratio = max(0.0, _safe_float(profile_constraints.get("other_opex_up_cap_ratio")))
      other_opex_min = current_other_opex
      if "other_opex_down" in allowed_levers:
        other_opex_min = current_other_opex * max(0.0, 1.0 - down_cap_ratio)
      other_opex_max = current_other_opex * (1.0 + up_cap_ratio) if up_cap_ratio > 0 else current_other_opex
      if other_opex_max < other_opex_min:
        other_opex_max = other_opex_min
      contract_inputs["other_opex_min"] = other_opex_min
      contract_inputs["other_opex_max"] = other_opex_max
      contract_inputs["other_opex_enabled"] = bool(other_opex_max > other_opex_min + 0.01)
      adjustments.append("translated_soft_opex_floor_into_strategy_envelope")

    if "demand_requires_marketing_support" in package_effects and "marketing_up" in allowed_levers:
      current_marketing = max(0.0, _safe_float(contract_inputs.get("current_marketing")))
      marketing_min = max(0.0, _safe_float(contract_inputs.get("marketing_min")))
      marketing_upper = max(marketing_min, _safe_float(contract_inputs.get("marketing_upper")) or marketing_min)
      if marketing_upper <= marketing_min + 0.01 and current_revenue > 0:
        target_marketing_floor = max(marketing_min, current_marketing)
        target_marketing_ceiling = max(
          target_marketing_floor,
          current_marketing * 1.15,
          current_revenue * 0.14,
        )
        contract_inputs["marketing_min"] = target_marketing_floor
        contract_inputs["marketing_upper"] = target_marketing_ceiling
        adjustments.append("expanded_marketing_contract_for_demand_support")

    required_lever_families = {
      str(item or "").strip()
      for item in (profile_contract_diagnostics.get("required_lever_families") or [])
      if str(item or "").strip()
    }
    package_lever_families = {
      str(item or "").strip()
      for item in (profile_contract_diagnostics.get("package_lever_families") or [])
      if str(item or "").strip()
    }
    translated_quarter_policies = [
      item
      for item in (((effective_profile.get("forecast_orchestration") or {}) if isinstance(effective_profile.get("forecast_orchestration"), dict) else {}).get("quarter_policies") or [])
      if isinstance(item, dict)
    ]
    minimum_package_count = max(
      1,
      _safe_int(profile_contract_diagnostics.get("minimum_package_count")) or 1,
    )
    missing_required = sorted(list(required_lever_families.difference(set(allowed_levers))))
    if missing_required:
      issues.append("missing_required_lever_families")
      adjustments.append("controller_contract_missing_required_levers")
    missing_package = sorted(list(package_lever_families.difference(set(allowed_levers))))
    if missing_package:
      issues.append("missing_package_lever_families")
      adjustments.append("controller_contract_missing_package_levers")
    if package_lever_families and len(translated_quarter_policies) < minimum_package_count:
      issues.append("missing_package_orchestration")
      adjustments.append("controller_contract_missing_package_orchestration")
    if "support_opex_required" in package_effects:
      translated_opex_max = max(0.0, _safe_float(contract_inputs.get("other_opex_max")))
      current_other_opex = max(0.0, _safe_float(contract_inputs.get("current_other_opex")))
      if "other_opex_up" not in allowed_levers or translated_opex_max <= current_other_opex + 0.01:
        issues.append("untranslated_support_opex_effect")
        adjustments.append("controller_contract_failed_support_opex_translation")
    if "demand_requires_marketing_support" in package_effects:
      translated_marketing_upper = max(0.0, _safe_float(contract_inputs.get("marketing_upper")))
      current_marketing = max(0.0, _safe_float(contract_inputs.get("current_marketing")))
      if "marketing_up" not in allowed_levers or translated_marketing_upper <= current_marketing + 0.01:
        issues.append("untranslated_marketing_support_effect")
        adjustments.append("controller_contract_failed_marketing_translation")
    if "capacity_expands_with_staffing" in package_effects or "structural_staffing_required" in package_effects:
      if "hire_advance" not in allowed_levers and "payroll_up" not in allowed_levers:
        issues.append("untranslated_staffing_capacity_effect")
        adjustments.append("controller_contract_failed_staffing_translation")

  structural_payroll_floor = max(
    0.0,
    _safe_float(contract_inputs.get("structural_payroll_floor")),
  )
  target_payroll_min_total = max(
    0.0,
    _safe_float(contract_inputs.get("target_payroll_min_total")),
  )
  target_payroll_max_total = max(
    target_payroll_min_total,
    _safe_float(contract_inputs.get("target_payroll_max_total")) or target_payroll_min_total,
  )
  if structural_payroll_floor > target_payroll_max_total:
    target_payroll_max_total = structural_payroll_floor
    adjustments.append("lifted_target_payroll_max_to_structural_floor")
    issues.append("target_payroll_max_below_structural_floor")
  if target_payroll_min_total > target_payroll_max_total:
    target_payroll_min_total = target_payroll_max_total
    adjustments.append("clamped_target_payroll_min_to_max")
    issues.append("target_payroll_min_exceeded_max")
  contract_inputs["target_payroll_min_total"] = target_payroll_min_total
  contract_inputs["target_payroll_max_total"] = target_payroll_max_total

  validated_target_min = target_ebitda_min
  validated_target_max = target_ebitda_max
  optimistic_ebitda, pessimistic_ebitda = _estimate_contract_ebitda_bounds(contract_inputs)
  target_tolerance = max(
    EBITDA_TARGET_TOLERANCE_ABS,
    max(1.0, abs(optimistic_ebitda), abs(pessimistic_ebitda)) * EBITDA_TARGET_TOLERANCE_RATIO,
  )
  if validated_target_min is not None and (optimistic_ebitda + target_tolerance) < validated_target_min:
    issues.append("target_ebitda_min_exceeds_contract_upper_bound")
    if strategy_source == "gpt":
      issues.append("underpowered_gpt_target_path")
    validated_target_min = None
    validated_target_max = None
    adjustments.append("relaxed_unreachable_target_ebitda_band")
  elif validated_target_max is not None and (pessimistic_ebitda - target_tolerance) > validated_target_max:
    issues.append("target_ebitda_max_below_contract_lower_bound")
    if strategy_source == "gpt":
      issues.append("underpowered_gpt_target_path")
    validated_target_max = None
    adjustments.append("relaxed_unreachable_target_ebitda_ceiling")
  if validated_target_min is not None and validated_target_max is not None and validated_target_min > validated_target_max:
    issues.append("target_ebitda_band_inverted_after_validation")
    validated_target_max = None
    adjustments.append("cleared_inverted_target_ebitda_ceiling")

  diagnostics = {
    "strategy_id": str(profile.get("strategy_id") or profile.get("profile_id") or "").strip(),
    "strategy_source": strategy_source,
    "allowed_levers": sorted(list(allowed_levers)),
    "controller_profile": _clone(profile_contract_diagnostics),
    "primary_cause": str(diagnosis.get("primary_cause") or "").strip(),
    "active_violations": sorted(list(active_violations)),
    "adjustments": adjustments,
    "issues": issues,
    "optimistic_ebitda": optimistic_ebitda,
    "pessimistic_ebitda": pessimistic_ebitda,
    "target_ebitda_min_in": target_ebitda_min,
    "target_ebitda_max_in": target_ebitda_max,
    "target_ebitda_min_out": validated_target_min,
    "target_ebitda_max_out": validated_target_max,
    "structural_payroll_floor": contract_inputs.get("structural_payroll_floor"),
    "target_payroll_min_total": contract_inputs.get("target_payroll_min_total"),
    "target_payroll_max_total": contract_inputs.get("target_payroll_max_total"),
    "other_opex_min": contract_inputs.get("other_opex_min"),
    "other_opex_max": contract_inputs.get("other_opex_max"),
  }
  contract_inputs["contract_diagnostics"] = diagnostics
  return {
    "profile": effective_profile,
    "direct_inputs": contract_inputs,
    "target_ebitda_min": validated_target_min,
    "target_ebitda_max": validated_target_max,
    "diagnostics": diagnostics,
  }


def _rescue_move_fraction(
  *,
  contract_profile: Dict[str, Any],
  contract_diagnostics: Dict[str, Any],
) -> float:
  directives = (
    contract_profile.get("controller_directives")
    if isinstance(contract_profile.get("controller_directives"), dict)
    else {}
  )
  aggression = _controller_aggression_level(directives)
  retry_attempt = max(
    0,
    _safe_int(
      ((contract_diagnostics.get("controller_profile") or {}) if isinstance(contract_diagnostics, dict) else {}).get("retry_attempt")
    ) or 0,
  )
  base = {
    "low": 0.58,
    "moderate": 0.74,
    "high": 0.88,
  }.get(aggression, 0.74)
  return max(0.45, min(0.97, base + (0.06 * min(retry_attempt, 2))))


def _move_within_bounds(
  *,
  current: float,
  lower: float,
  upper: float,
  allow_up: bool,
  allow_down: bool,
  fraction: float,
  prefer_up: bool,
) -> float:
  current = _safe_float(current)
  lower = max(0.0, _safe_float(lower))
  upper = max(lower, _safe_float(upper) or lower)
  if prefer_up and allow_up and upper > current:
    return current + (upper - current) * fraction
  if (not prefer_up) and allow_down and current > lower:
    return current - (current - lower) * fraction
  if allow_up and upper > current:
    return current + (upper - current) * fraction
  if allow_down and current > lower:
    return current - (current - lower) * fraction
  return current


def _build_governed_rescue_solution(
  *,
  contract_profile: Dict[str, Any],
  contract_inputs: Dict[str, Any],
  contract_diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
  allowed_levers = _profile_allowed_levers(contract_profile)
  active_violations = {
    str(code or "").strip()
    for code in (contract_diagnostics.get("active_violations") or [])
    if str(code or "").strip()
  }
  primary_cause = str(contract_diagnostics.get("primary_cause") or "").strip().lower()
  fraction = _rescue_move_fraction(
    contract_profile=contract_profile,
    contract_diagnostics=contract_diagnostics,
  )
  prefer_margin_up = not ("ebitda_margin_too_high" in active_violations or "ebitda_too_high" in active_violations)

  current_price = max(0.0, _safe_float(contract_inputs.get("current_price")))
  price_lower = max(0.0, _safe_float(contract_inputs.get("price_lower")) or current_price)
  price_upper = max(price_lower, _safe_float(contract_inputs.get("price_upper")) or current_price)
  current_util = max(0.0, min(1.0, _safe_float(contract_inputs.get("current_util"))))
  util_min = max(0.0, min(current_util, _safe_float(contract_inputs.get("util_min")) or current_util))
  util_max = max(util_min, min(1.0, _safe_float(contract_inputs.get("util_max")) or current_util))
  current_other_opex = max(0.0, _safe_float(contract_inputs.get("current_other_opex")))
  other_opex_min = max(0.0, _safe_float(contract_inputs.get("other_opex_min")))
  other_opex_max = max(other_opex_min, _safe_float(contract_inputs.get("other_opex_max")) or other_opex_min)
  current_marketing = max(0.0, _safe_float(contract_inputs.get("current_marketing")))
  marketing_min = max(0.0, _safe_float(contract_inputs.get("marketing_min")))
  marketing_upper = max(marketing_min, _safe_float(contract_inputs.get("marketing_upper")) or marketing_min)
  current_cogs_ratio = max(0.0, _safe_float(contract_inputs.get("current_cogs_ratio")))
  cogs_ratio_min = max(0.0, _safe_float(contract_inputs.get("cogs_ratio_min")))
  cogs_ratio_max = max(cogs_ratio_min, _safe_float(contract_inputs.get("cogs_ratio_max")) or cogs_ratio_min)
  baseline_units = max(0.0, _safe_float(contract_inputs.get("baseline_units")))
  units_min = max(0.0, _safe_float(contract_inputs.get("units_min")))
  units_max = max(units_min, _safe_float(contract_inputs.get("units_max")) or units_min)
  current_revenue = max(0.0, _safe_float(contract_inputs.get("current_revenue")))

  prefer_price_up = prefer_margin_up and primary_cause not in {"utilization-driven"}
  prefer_util_up = prefer_margin_up and primary_cause in {"utilization-driven", "mixed"}
  if primary_cause == "payroll-driven":
    prefer_price_up = True
    prefer_util_up = True

  target_price = _move_within_bounds(
    current=current_price,
    lower=price_lower,
    upper=price_upper,
    allow_up="price_up" in allowed_levers,
    allow_down="price_down" in allowed_levers,
    fraction=fraction,
    prefer_up=prefer_price_up,
  )
  target_util = _move_within_bounds(
    current=current_util,
    lower=util_min,
    upper=util_max,
    allow_up="util_up" in allowed_levers,
    allow_down="util_down" in allowed_levers,
    fraction=fraction,
    prefer_up=prefer_util_up,
  )
  target_marketing = _move_within_bounds(
    current=current_marketing,
    lower=marketing_min,
    upper=marketing_upper,
    allow_up="marketing_up" in allowed_levers,
    allow_down="marketing_down" in allowed_levers,
    fraction=fraction,
    prefer_up=prefer_margin_up and ("demand_requires_marketing_support" in _package_expected_effects(contract_profile.get("coordinated_lever_packages"))),
  )
  target_other_opex = _move_within_bounds(
    current=current_other_opex,
    lower=other_opex_min,
    upper=other_opex_max,
    allow_up="other_opex_up" in allowed_levers,
    allow_down="other_opex_down" in allowed_levers,
    fraction=fraction,
    prefer_up=("opex_too_light" in active_violations and "other_opex_up" in allowed_levers),
  )
  if "cogs_down" in allowed_levers and prefer_margin_up:
    target_cogs_ratio = current_cogs_ratio - ((current_cogs_ratio - cogs_ratio_min) * fraction)
  elif "cogs_up" in allowed_levers and not prefer_margin_up:
    target_cogs_ratio = current_cogs_ratio + ((cogs_ratio_max - current_cogs_ratio) * fraction)
  else:
    target_cogs_ratio = current_cogs_ratio
  target_cogs_ratio = max(cogs_ratio_min, min(cogs_ratio_max, target_cogs_ratio))

  child_product_solution: Dict[str, Dict[str, Any]] = {}
  annual_units_total = 0.0
  annual_revenue_total = 0.0
  product_driver_basis = [
    item for item in (contract_inputs.get("product_driver_basis") or [])
    if isinstance(item, dict)
  ]
  solve_mode = str(contract_inputs.get("solve_mode") or "").strip().lower()
  if solve_mode == "child_first" and product_driver_basis:
    price_lower_ratio = (price_lower / max(current_price, 1e-9)) if current_price > 0 else 1.0
    price_upper_ratio = (price_upper / max(current_price, 1e-9)) if current_price > 0 else 1.0
    for item in product_driver_basis:
      product_key = str(item.get("product_key") or "").strip()
      if not product_key:
        continue
      baseline_price = max(0.0, _safe_float(item.get("unit_price")))
      baseline_util = max(0.0, min(1.0, _safe_float(item.get("utilization_rate"))))
      capacity_per_period = max(0.0, _safe_float(item.get("units_per_period_capacity")))
      periods = max(0.0, _safe_float(item.get("operating_periods_per_year")))
      child_price_lower = baseline_price * price_lower_ratio
      child_price_upper = max(child_price_lower, baseline_price * price_upper_ratio)
      child_target_price = _move_within_bounds(
        current=baseline_price,
        lower=child_price_lower,
        upper=child_price_upper,
        allow_up="price_up" in allowed_levers,
        allow_down="price_down" in allowed_levers,
        fraction=fraction,
        prefer_up=prefer_price_up,
      )
      child_target_util = _move_within_bounds(
        current=baseline_util,
        lower=util_min,
        upper=util_max,
        allow_up="util_up" in allowed_levers,
        allow_down="util_down" in allowed_levers,
        fraction=fraction,
        prefer_up=prefer_util_up,
      )
      child_avg_units = capacity_per_period * child_target_util
      child_product_solution[product_key] = {
        "unit_price": round(child_target_price, 2),
        "utilization_rate": round(child_target_util, 6),
        "avg_units_per_period_year1": round(child_avg_units, 4),
      }
      annual_units_total += periods * child_avg_units
      annual_revenue_total += periods * child_avg_units * child_target_price
    if current_revenue <= 0:
      current_revenue = annual_revenue_total
  else:
    annual_units_total = _move_within_bounds(
      current=baseline_units,
      lower=units_min,
      upper=units_max,
      allow_up="util_up" in allowed_levers or "marketing_up" in allowed_levers or "hire_advance" in allowed_levers,
      allow_down="util_down" in allowed_levers or "hire_delay" in allowed_levers,
      fraction=fraction,
      prefer_up=prefer_margin_up,
    )
    annual_revenue_total = annual_units_total * max(target_price, 0.0)
  annual_units_total = max(units_min if units_min > 0 else 0.0, min(units_max if units_max > 0 else annual_units_total, annual_units_total))
  if annual_revenue_total <= 0 and current_revenue > 0:
    revenue_units_scale = (annual_units_total / max(baseline_units, 1e-9)) if baseline_units > 0 else 1.0
    revenue_price_scale = (target_price / max(current_price, 1e-9)) if current_price > 0 else 1.0
    annual_revenue_total = current_revenue * revenue_units_scale * revenue_price_scale

  marketing_units_per_dollar = max(0.0, _safe_float(contract_inputs.get("marketing_units_per_dollar")))
  marketing_support_units_baseline = max(0.0, _safe_float(contract_inputs.get("marketing_support_units_baseline")))
  marketing_support_units_min = max(0.0, _safe_float(contract_inputs.get("marketing_support_units_min")))
  marketing_support_units_max = max(marketing_support_units_min, _safe_float(contract_inputs.get("marketing_support_units_max")) or marketing_support_units_min)
  if marketing_units_per_dollar > 0:
    target_support_units = max(marketing_support_units_min, min(marketing_support_units_max, target_marketing * marketing_units_per_dollar))
  else:
    target_support_units = marketing_support_units_baseline

  roles = [item for item in (contract_inputs.get("roles") or []) if isinstance(item, dict)]
  role_months: Dict[str, int] = {}
  role_year1_payroll: Dict[str, float] = {}
  role_wage_meta: Dict[str, Dict[str, Any]] = {}
  for role in roles:
    role_title = str(role.get("role_title") or "").strip()
    if not role_title:
      continue
    base_months = max(0, _safe_int(role.get("base_months")) or 0)
    min_months = max(0, _safe_int(role.get("min_months")) or 0)
    max_months = max(min_months, _safe_int(role.get("max_months")) or base_months)
    prefer_delay = "payroll_too_heavy" in active_violations or primary_cause == "payroll-driven"
    target_months = int(round(_move_within_bounds(
      current=float(base_months),
      lower=float(min_months),
      upper=float(max_months),
      allow_up="hire_delay" in allowed_levers,
      allow_down="hire_advance" in allowed_levers,
      fraction=fraction,
      prefer_up=prefer_delay,
    )))
    annual_wage = max(0.0, _safe_float(role.get("annual_wage")))
    role_months[role_title] = max(min_months, min(max_months, target_months))
    role_year1_payroll[role_title] = round(
      _year1_amount_from_start_month(annual_wage, role_months[role_title]),
      2,
    )
    role_wage_meta[role_title] = {
      "wage_floor": max(0.0, _safe_float(role.get("wage_floor"))),
      "wage_ceiling": max(0.0, _safe_float(role.get("wage_ceiling"))),
    }

  fixed_people_payroll = max(0.0, _safe_float(contract_inputs.get("fixed_people_payroll")))
  target_payroll_total = fixed_people_payroll + sum(role_year1_payroll.values())
  target_payroll_min_total = max(0.0, _safe_float(contract_inputs.get("target_payroll_min_total")))
  target_payroll_max_total = max(target_payroll_min_total, _safe_float(contract_inputs.get("target_payroll_max_total")) or target_payroll_min_total)
  target_payroll_total = max(target_payroll_min_total, min(target_payroll_max_total, target_payroll_total))

  target_cogs_total = annual_revenue_total * target_cogs_ratio
  rent_annualized = max(0.0, _safe_float(contract_inputs.get("rent_annualized")))
  target_opex_total_ratio = (
    (target_other_opex + rent_annualized) / max(annual_revenue_total, 1.0)
    if annual_revenue_total > 0
    else 0.0
  )

  return {
    "profile_id": str(contract_profile.get("profile_id") or contract_profile.get("strategy_id") or "governed_rescue").strip() or "governed_rescue",
    "price": round(target_price, 2),
    "utilization_rate": round(target_util, 6),
    "marketing_total_year1": round(target_marketing, 2),
    "marketing_support_units_year1": round(target_support_units, 2),
    "other_operating_expense": round(target_other_opex, 2),
    "other_opex_total_ratio": round(target_opex_total_ratio, 6),
    "cogs_ratio": round(target_cogs_ratio, 6),
    "cogs_total_year1": round(target_cogs_total, 2),
    "annual_units_total": round(annual_units_total, 4),
    "child_product_solution": child_product_solution,
    "role_months": role_months,
    "role_year1_payroll": role_year1_payroll,
    "role_wage_meta": role_wage_meta,
    "structural_payroll_required_total": round(target_payroll_total, 2),
    "enforce_blocking_bands": False,
    "distortion_components": {},
    "distortion_total": 0.0,
    "family_raw_components": {},
    "max_family_move": 0.0,
    "ebitda": round(
      annual_revenue_total - target_cogs_total - target_marketing - target_other_opex - target_payroll_total - rent_annualized - max(0.0, _safe_float(contract_inputs.get("current_interest"))),
      2,
    ),
    "net_income": round(
      annual_revenue_total - target_cogs_total - target_marketing - target_other_opex - target_payroll_total - rent_annualized - max(0.0, _safe_float(contract_inputs.get("current_interest"))),
      2,
    ),
  }


def _build_governed_rescue_scenarios(
  *,
  contract_bundles: Sequence[Dict[str, Any]],
  baseline_summary: Dict[str, Any],
  baseline_state: Dict[str, Any],
  marketing_model_json: Optional[Dict[str, Any]],
  ops_json: Dict[str, Any],
  constraint_engine_state: Optional[Dict[str, Any]],
  baseline_realism_distance: Optional[float],
  normalized_traits: Optional[Dict[str, Any]],
  benchmark_payload: Optional[Dict[str, Any]],
  target_ebitda_min: Optional[float],
  target_ebitda_max: Optional[float],
  viability_mode: bool,
) -> List[Dict[str, Any]]:
  rescue_candidates: List[Dict[str, Any]] = []
  seen_signatures: set = set()
  ordered_bundles = sorted(
    [
      item for item in contract_bundles
      if isinstance(item, dict)
      and isinstance(item.get("profile"), dict)
      and isinstance(item.get("direct_inputs"), dict)
    ],
    key=lambda item: _safe_float(((item.get("diagnostics") or {}) if isinstance(item.get("diagnostics"), dict) else {}).get("optimistic_ebitda")),
    reverse=True,
  )
  for bundle in ordered_bundles:
    contract_profile = _clone(bundle.get("profile") or {})
    contract_inputs = _clone(bundle.get("direct_inputs") or {})
    contract_diagnostics = _clone(bundle.get("diagnostics") or {})
    rescue_solution = _build_governed_rescue_solution(
      contract_profile=contract_profile,
      contract_inputs=contract_inputs,
      contract_diagnostics=contract_diagnostics,
    )
    exact_patches = _exact_patches_from_solution(
      solution=rescue_solution,
      direct_inputs=contract_inputs,
      ops_json=ops_json,
    )
    signature = _scenario_signature(exact_patches)
    if not signature or signature in seen_signatures:
      continue
    seen_signatures.add(signature)
    default_archetype_meta = _scenario_archetype_meta(str(contract_profile.get("profile_id") or "").strip())
    candidate = _build_candidate_from_exact_patches(
      scenario_id=str(len(rescue_candidates) + 1),
      baseline_summary=baseline_summary,
      baseline_state=baseline_state,
      marketing_model_json=marketing_model_json,
      exact_patches=exact_patches,
      archetype=str(contract_profile.get("archetype") or default_archetype_meta.get("archetype") or "operations").strip() or "operations",
      archetype_display=str(contract_profile.get("archetype_display") or default_archetype_meta.get("display") or "Operational balance").strip() or "Operational balance",
      dominant_tradeoff=str(contract_profile.get("dominant_tradeoff") or default_archetype_meta.get("tradeoff") or "keeps the business inside a governed repair envelope").strip(),
      constraint_engine_state=constraint_engine_state,
      scenario_constraint_engine_state=_clone(constraint_engine_state or {}),
      baseline_realism_distance=baseline_realism_distance,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
      allow_realism_relaxation=True,
    )
    if not isinstance(candidate, dict):
      continue
    candidate["scenario_id"] = str(len(rescue_candidates) + 1)
    candidate["strategy_id"] = str(contract_profile.get("strategy_id") or contract_profile.get("profile_id") or "governed_rescue").strip() or "governed_rescue"
    candidate["strategy_name"] = str(contract_profile.get("strategy_name") or candidate["strategy_id"]).strip() or candidate["strategy_id"]
    candidate["strategy_source"] = str(contract_profile.get("strategy_source") or "gpt").strip() or "gpt"
    candidate["allowed_levers"] = [
      str(item or "").strip()
      for item in (contract_profile.get("allowed_levers") or [])
      if str(item or "").strip()
    ]
    candidate["relationship_rules"] = [
      str(item or "").strip()
      for item in (contract_profile.get("relationship_rules") or [])
      if str(item or "").strip()
    ]
    candidate["forecast_orchestration"] = _clone(contract_profile.get("forecast_orchestration") or {})
    candidate["contract_diagnostics"] = _clone(contract_diagnostics)
    candidate["target_ebitda_min"] = target_ebitda_min
    candidate["target_ebitda_max"] = target_ebitda_max
    candidate["strategy_relaxed"] = True
    candidate["rescue_generated"] = True
    candidate["rescue_source"] = "controller_contract"
    candidate["selection_mode_hint"] = "governed_rescue"
    candidate.update(_derive_scenario_posture(candidate))
    candidate.update(_archetype_consistency(candidate))
    candidate["scenario_forecast"] = _build_scenario_forecast_bundle(
      baseline_state=baseline_state,
      exact_patches=exact_patches,
      modified_state=(candidate.get("modified_state") if isinstance(candidate.get("modified_state"), dict) else None),
      remaining_violations=candidate.get("remaining_violations") or [],
      constraint_engine_state=constraint_engine_state,
      normalized_traits=normalized_traits,
      benchmark_payload=benchmark_payload,
      scenario_strategy={
        "strategy_id": str(candidate.get("strategy_id") or "").strip(),
        "strategy_name": str(candidate.get("strategy_name") or "").strip(),
        "archetype": str(candidate.get("archetype") or "").strip(),
        "archetype_display": str(candidate.get("archetype_display") or "").strip(),
        "dominant_tradeoff": str(candidate.get("dominant_tradeoff") or "").strip(),
        "demand_posture": str(candidate.get("demand_posture") or "").strip(),
        "staffing_posture": str(candidate.get("staffing_posture") or "").strip(),
        "cost_posture": str(candidate.get("cost_posture") or "").strip(),
        "forecast_orchestration": _clone(candidate.get("forecast_orchestration") or {}),
      },
    )
    candidate["forecast_engine_state"] = _clone((candidate["scenario_forecast"] or {}).get("forecast_engine_state") or {})
    candidate["forecast_quarters"] = _clone((candidate["scenario_forecast"] or {}).get("forecast_quarters") or [])
    candidate["forecast_years"] = _clone((candidate["scenario_forecast"] or {}).get("forecast_years") or [])
    candidate["forecast_summary"] = _clone((candidate["scenario_forecast"] or {}).get("forecast_summary") or {})
    rescue_candidates.append(candidate)
    if len(rescue_candidates) >= MAX_SCENARIOS:
      break
  trace_lazy(
    "ITERATION",
    "Governed rescue scenarios built",
    lambda: {
      "candidate_count": len(rescue_candidates),
      "target_ebitda_min": target_ebitda_min,
      "target_ebitda_max": target_ebitda_max,
      "viability_mode": viability_mode,
      "strategy_ids": [str(item.get("strategy_id") or "").strip() for item in rescue_candidates],
    },
  )
  return rescue_candidates


def _strategy_retry_feedback(
  *,
  strategy_layer: Dict[str, Any],
  direct_inputs: Optional[Dict[str, Any]],
  contract_feedback: Optional[List[Dict[str, Any]]] = None,
  feasible_scenarios: List[Dict[str, Any]],
  fallback_scenarios: List[Dict[str, Any]],
  attempted_scenarios: Optional[List[Dict[str, Any]]] = None,
  client_ready_scenarios: Optional[List[Dict[str, Any]]] = None,
  baseline_summary: Dict[str, Any],
) -> Dict[str, Any]:
  selected_ids = [
    str(item.get("strategy_id") or "").strip()
    for item in (strategy_layer.get("strategies") or [])
    if isinstance(item, dict) and str(item.get("strategy_id") or "").strip()
  ] if isinstance(strategy_layer, dict) else []
  direct_inputs = direct_inputs if isinstance(direct_inputs, dict) else {}
  attempted_scenarios = [item for item in (attempted_scenarios or []) if isinstance(item, dict)]
  client_ready_scenarios = [item for item in (client_ready_scenarios or []) if isinstance(item, dict)]
  failure_mode = "no_scenarios"
  if attempted_scenarios and not client_ready_scenarios:
    failure_mode = "no_client_ready_scenarios"
  contract_feedback = [
    _clone(item) for item in (contract_feedback or [])
    if isinstance(item, dict)
  ][:8]
  dominant_contract_issues = sorted({
    str(issue or "").strip()
    for feedback in contract_feedback
    for issue in (feedback.get("issues") or [])
    if str(issue or "").strip()
  })
  best_optimistic_ebitda = None
  worst_pessimistic_ebitda = None
  diagnosis = (strategy_layer.get("diagnosis") or {}) if isinstance(strategy_layer, dict) and isinstance(strategy_layer.get("diagnosis"), dict) else {}
  severity_class = str(diagnosis.get("severity_class") or "").strip().lower()
  for feedback in contract_feedback:
    optimistic = _safe_float(feedback.get("optimistic_ebitda"))
    pessimistic = _safe_float(feedback.get("pessimistic_ebitda"))
    if optimistic is not None:
      best_optimistic_ebitda = optimistic if best_optimistic_ebitda is None else max(best_optimistic_ebitda, optimistic)
    if pessimistic is not None:
      worst_pessimistic_ebitda = pessimistic if worst_pessimistic_ebitda is None else min(worst_pessimistic_ebitda, pessimistic)
  return {
    "selected_strategy_ids": selected_ids,
    "strategy_source": str((strategy_layer or {}).get("source") or "").strip() if isinstance(strategy_layer, dict) else "",
    "diagnosis": _clone(diagnosis),
    "severity_class": severity_class,
    "solve_mode": str(direct_inputs.get("solve_mode") or "").strip(),
    "hard_violations": list(_blocking_constraint_violations((direct_inputs.get("constraint_profile") or {}).get("constraint_engine_state") if isinstance(direct_inputs.get("constraint_profile"), dict) else {})),
    "constraint_violations": list(direct_inputs.get("constraint_violations") or []),
    "feasible_scenario_count": len(feasible_scenarios),
    "fallback_scenario_count": len(fallback_scenarios),
    "attempted_scenario_count": len(attempted_scenarios),
    "client_ready_scenario_count": len(client_ready_scenarios),
    "failure_mode": failure_mode,
    "attempted_scenarios": [
      {
        "strategy_id": str(item.get("strategy_id") or item.get("solution_profile_id") or "").strip(),
        "archetype": str(item.get("archetype") or "").strip(),
        "remaining_blocking_count": _safe_float(item.get("remaining_blocking_count")),
        "remaining_violation_count": _safe_float(item.get("remaining_violation_count")),
        "realism_distance": _safe_float(item.get("realism_distance")),
        "presentation_issues": list(item.get("presentation_issues") or []),
        "lever_summary": _clone(item.get("lever_summary") or {}),
        "contract_diagnostics": _clone(item.get("contract_diagnostics") or {}),
        "target_path_assessment": _clone(item.get("target_path_assessment") or {}),
      }
      for item in attempted_scenarios[:MAX_SCENARIOS]
    ],
    "baseline_ebitda": _safe_float((baseline_summary or {}).get("ebitda")),
    "baseline_revenue": _safe_float((baseline_summary or {}).get("revenue")),
    "best_optimistic_ebitda": best_optimistic_ebitda,
    "worst_pessimistic_ebitda": worst_pessimistic_ebitda,
    "dominant_contract_issues": dominant_contract_issues,
    "contract_feedback": contract_feedback,
    "message": (
      "Selected strategies did not produce a client-ready repaired scenario. "
      "Analyze the exact failure mode, especially any target-path misses or degrading outer-year forecast, escalate the coordinated lever package materially, and choose a different bounded strategy mix that can realistically hit the Year 1-3 path."
      if failure_mode == "no_client_ready_scenarios"
      else "Selected strategies did not produce a workable repaired scenario. Choose a different bounded strategy mix and strengthen the coordinated lever package."
    ),
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
    if financials_patch.get("payroll_total_year1") is not None or financials_patch.get("current_payroll") is not None:
      target = _safe_float(
        financials_patch.get("payroll_total_year1")
        if financials_patch.get("payroll_total_year1") is not None
        else financials_patch.get("current_payroll")
      )
      families.append("payroll")
      label_parts.append(f"Set Year-1 payroll to {_format_currency(target)}")
      rationale_parts.append("reset Year-1 labor support to match the staffing plan")
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
  scenario_constraint_engine_state: Optional[Dict[str, Any]] = None,
  baseline_realism_distance: Optional[float] = None,
  target_ebitda_min: Optional[float] = None,
  target_ebitda_max: Optional[float] = None,
  allow_realism_relaxation: bool = False,
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
    scenario_constraint_engine_state=scenario_constraint_engine_state,
    baseline_realism_distance=baseline_realism_distance,
    target_ebitda_min=target_ebitda_min,
    target_ebitda_max=target_ebitda_max,
    allow_realism_relaxation=allow_realism_relaxation,
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
):
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
  profile_id = str(profile.get("profile_id") or "").strip() or "profile"
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
  hard_utilization_floor = _normalize_ratio(direct_inputs.get("hard_utilization_floor"))
  if hard_utilization_floor is not None:
    util_min = max(util_min, hard_utilization_floor)
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
  growth_demand_mode_enabled = bool(direct_inputs.get("growth_demand_mode_enabled"))
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
  baseline_units = max(0.0, _safe_float(direct_inputs.get("baseline_units")))
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
  payroll_support_basis = str(direct_inputs.get("payroll_support_basis") or "floor").strip().lower()
  units_per_active_role_month = max(0.0, _safe_float(direct_inputs.get("units_per_active_role_month")))
  fixed_active_role_months = max(0.0, _safe_float(direct_inputs.get("fixed_active_role_months")))
  adjustable_role_month_cost_floor = max(0.0, _safe_float(direct_inputs.get("adjustable_role_month_cost_floor")))
  units_per_payroll_dollar = max(0.0, _safe_float(direct_inputs.get("units_per_payroll_dollar")))
  role_month_support_profile = direct_inputs.get("role_month_support_profile") if isinstance(direct_inputs, dict) else []
  role_month_support_profile = role_month_support_profile if isinstance(role_month_support_profile, list) else []
  active_violations = {
    str(code or "").strip()
    for code in (direct_inputs.get("constraint_violations") or [])
    if str(code or "").strip()
  }
  if "payroll_too_light" in active_violations and (
    payroll_support_basis in {"role_months", "payroll"} or structural_payroll_floor > target_payroll_min_total
  ):
    payroll_ratio_max = 0.0
  roles = direct_inputs.get("roles") if isinstance(direct_inputs, dict) else []
  roles = roles if isinstance(roles, list) else []
  solve_mode = str(direct_inputs.get("solve_mode") or "parent_fallback").strip().lower()
  product_driver_basis = direct_inputs.get("product_driver_basis") if isinstance(direct_inputs, dict) else []
  product_driver_basis = product_driver_basis if isinstance(product_driver_basis, list) else []
  child_first = solve_mode == "child_first" and bool(product_driver_basis)

  trace_lazy(
    "ITERATION",
    f"Profile {profile_id} solve start",
    lambda: {
      "profile": profile,
      "targets": {
        "target_ebitda_min": target_ebitda_min,
        "target_ebitda_max": target_ebitda_max,
        "enforce_blocking_bands": enforce_blocking_bands,
        "family_caps": family_caps or {},
      },
      "direct_inputs": {
        "solve_mode": solve_mode,
        "current_price": current_price,
        "price_lower": price_lower,
        "price_upper": price_upper,
        "current_util": current_util,
        "util_min": util_min,
        "util_max": util_max,
        "hard_utilization_floor": hard_utilization_floor,
        "baseline_units": baseline_units,
        "units_min": units_min,
        "units_max": units_max,
        "capacity_units": capacity_units,
        "current_marketing": current_marketing,
        "marketing_min": marketing_min,
        "marketing_upper": marketing_upper,
        "current_other_opex": current_other_opex,
        "other_opex_min": other_opex_min,
        "other_opex_max": other_opex_max,
        "current_cogs": current_cogs,
        "cogs_ratio_min": cogs_ratio_min,
        "cogs_ratio_max": cogs_ratio_max,
        "target_payroll_min_total": target_payroll_min_total,
        "target_payroll_max_total": target_payroll_max_total,
        "people_payroll_floor": people_payroll_floor,
        "structural_payroll_floor": structural_payroll_floor,
        "payroll_support_basis": payroll_support_basis,
        "constraint_violations": sorted(list(active_violations)),
        "role_count": len(roles),
        "child_product_count": len(product_driver_basis),
      },
    },
  )

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
  child_price_vars: Dict[str, Any] = {}
  child_util_vars: Dict[str, Any] = {}
  child_avg_unit_vars: Dict[str, Any] = {}
  child_price_avg_vars: Dict[str, Any] = {}
  child_move_weights: Dict[str, float] = {}
  child_price_up_vars: Dict[str, Any] = {}
  child_price_down_vars: Dict[str, Any] = {}
  child_util_up_vars: Dict[str, Any] = {}
  child_util_down_vars: Dict[str, Any] = {}
  total_child_capacity_units = 0.0
  total_child_revenue = sum(max(0.0, _safe_float(item.get("annual_revenue"))) for item in product_driver_basis if isinstance(item, dict))
  total_child_units = sum(max(0.0, _safe_float(item.get("annual_units"))) for item in product_driver_basis if isinstance(item, dict))

  if child_first:
    price_lower_ratio = (price_lower / max(current_price, 1e-9)) if price_enabled and current_price > 0 else 1.0
    price_upper_ratio = (price_upper / max(current_price, 1e-9)) if price_enabled and current_price > 0 else 1.0
    for index, item in enumerate(product_driver_basis):
      if not isinstance(item, dict):
        continue
      product_key = str(item.get("product_key") or "").strip()
      if not product_key:
        continue
      baseline_price = max(0.0, _safe_float(item.get("unit_price")))
      baseline_util = _normalize_ratio(item.get("utilization_rate")) or 0.0
      capacity_per_period = max(0.0, _safe_float(item.get("units_per_period_capacity")))
      periods = max(0.0, _safe_float(item.get("operating_periods_per_year")))
      annual_capacity_units = max(0.0, _safe_float(item.get("annual_capacity_units")) or (capacity_per_period * periods))
      annual_units = max(0.0, _safe_float(item.get("annual_units")))
      total_child_capacity_units += annual_capacity_units
      child_move_weights[product_key] = (
        (annual_units / max(total_child_units, 1e-9))
        if total_child_units > 0
        else ((annual_capacity_units / max(sum(max(0.0, _safe_float(p.get("annual_capacity_units"))) for p in product_driver_basis if isinstance(p, dict)), 1e-9)) if annual_capacity_units > 0 else 0.0)
      )
      child_price_lower = baseline_price if not price_enabled else round(max(0.0, baseline_price * price_lower_ratio), 2)
      child_price_upper = baseline_price if not price_enabled else round(max(child_price_lower, baseline_price * price_upper_ratio), 2)
      child_util_lower = max(0.0, min(1.0, util_min))
      child_util_upper = max(child_util_lower, min(1.0, util_max))
      avg_units_lower = capacity_per_period * child_util_lower
      avg_units_upper = capacity_per_period * child_util_upper
      price_var = pulp.LpVariable(
        f"price_child_{index}",
        lowBound=child_price_lower,
        upBound=child_price_upper,
        cat="Continuous",
      )
      util_var = pulp.LpVariable(
        f"util_child_{index}",
        lowBound=child_util_lower,
        upBound=child_util_upper,
        cat="Continuous",
      )
      avg_units_var = pulp.LpVariable(
        f"avg_units_child_{index}",
        lowBound=avg_units_lower,
        upBound=avg_units_upper,
        cat="Continuous",
      )
      problem += avg_units_var == (capacity_per_period * util_var)
      price_avg_var = pulp.LpVariable(
        f"price_avg_child_{index}",
        lowBound=max(0.0, child_price_lower * avg_units_lower),
        upBound=max(0.0, child_price_upper * avg_units_upper),
        cat="Continuous",
      )
      problem += price_avg_var >= child_price_lower * avg_units_var + avg_units_lower * price_var - (child_price_lower * avg_units_lower)
      problem += price_avg_var >= child_price_upper * avg_units_var + avg_units_upper * price_var - (child_price_upper * avg_units_upper)
      problem += price_avg_var <= child_price_lower * avg_units_var + avg_units_upper * price_var - (child_price_lower * avg_units_upper)
      problem += price_avg_var <= child_price_upper * avg_units_var + avg_units_lower * price_var - (child_price_upper * avg_units_lower)
      child_price_vars[product_key] = price_var
      child_util_vars[product_key] = util_var
      child_avg_unit_vars[product_key] = avg_units_var
      child_price_avg_vars[product_key] = price_avg_var
    if total_child_capacity_units <= 0:
      trace_values(
        "ITERATION",
        f"Profile {profile_id} rejected before solve",
        reason="child_capacity_zero",
        total_child_capacity_units=total_child_capacity_units,
      )
      return None
    capacity_units = total_child_capacity_units
    units_max = max(units_min, units_max, total_child_capacity_units)
    units_expr = pulp.lpSum(
      max(0.0, _safe_float(item.get("operating_periods_per_year"))) * child_avg_unit_vars[str(item.get("product_key") or "").strip()]
      for item in product_driver_basis
      if isinstance(item, dict) and str(item.get("product_key") or "").strip() in child_avg_unit_vars
    )
    revenue_expr = pulp.lpSum(
      max(0.0, _safe_float(item.get("operating_periods_per_year"))) * child_price_avg_vars[str(item.get("product_key") or "").strip()]
      for item in product_driver_basis
      if isinstance(item, dict) and str(item.get("product_key") or "").strip() in child_price_avg_vars
    )
    util = units_expr / max(total_child_capacity_units, 1e-9)
    revenue_lb = sum(
      max(0.0, _safe_float(item.get("operating_periods_per_year")))
      * max(0.0, (_safe_float(item.get("unit_price")) if not price_enabled else round(max(0.0, _safe_float(item.get("unit_price")) * price_lower_ratio), 2)))
      * (max(0.0, _safe_float(item.get("units_per_period_capacity"))) * max(0.0, min(1.0, util_min)))
      for item in product_driver_basis
      if isinstance(item, dict)
    )
    revenue_ub = sum(
      max(0.0, _safe_float(item.get("operating_periods_per_year")))
      * max(
        max(0.0, (_safe_float(item.get("unit_price")) if not price_enabled else round(max(0.0, _safe_float(item.get("unit_price")) * price_lower_ratio), 2))),
        (_safe_float(item.get("unit_price")) if not price_enabled else round(max(0.0, _safe_float(item.get("unit_price")) * price_upper_ratio), 2)),
      )
      * (max(0.0, _safe_float(item.get("units_per_period_capacity"))) * max(max(0.0, min(1.0, util_min)), min(1.0, util_max)))
      for item in product_driver_basis
      if isinstance(item, dict)
    )
  else:
    price = pulp.LpVariable("price", lowBound=(current_price if not price_enabled else price_lower), upBound=(current_price if not price_enabled else price_upper), cat="Continuous")
    util = pulp.LpVariable("util", lowBound=util_min, upBound=util_max, cat="Continuous")
    price_util = pulp.LpVariable("price_util", lowBound=0.0, upBound=price_upper * util_max, cat="Continuous")

    price_lb = price_lower if price_enabled else current_price
    price_ub = price_upper
    util_lb = util_min
    util_ub = util_max
    problem += price_util >= price_lb * util + util_lb * price - (price_lb * util_lb)
    problem += price_util >= price_ub * util + util_ub * price - (price_ub * util_ub)
    problem += price_util <= price_lb * util + util_ub * price - (price_lb * util_ub)
    problem += price_util <= price_ub * util + util_lb * price - (price_ub * util_lb)
    units_expr = capacity_units * util
    revenue_expr = capacity_units * price_util
    revenue_lb = max(0.0, capacity_units * price_lb * util_lb)
    revenue_ub = max(revenue_lb, capacity_units * price_ub * util_ub)

  role_month_vars: Dict[str, Any] = {}
  role_active_month_vars: Dict[str, Any] = {}
  role_payroll_vars: Dict[str, Any] = {}
  role_wage_meta: Dict[str, Dict[str, float]] = {}
  payroll_terms: List[Any] = []
  total_delay_expr = 0
  total_advance_expr = 0
  total_payroll_down_expr = 0
  total_payroll_up_expr = 0
  for index, role in enumerate(roles):
    role_title = str(role.get("role_title") or "").strip()
    base_months = max(0, _safe_int(role.get("base_months")) or 0)
    min_months = max(0, min(base_months, _safe_int(role.get("min_months")) if role.get("min_months") is not None else 0))
    max_months = max(
      base_months,
      _safe_int(role.get("max_months")) if role.get("max_months") is not None else max(MAX_ROLE_DELAY_MONTHS, base_months),
    )
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
    active_months_var = pulp.LpVariable(
      f"role_active_months_{index}",
      lowBound=0.0,
      upBound=12.0,
      cat="Continuous",
    )
    starts_after_year1 = pulp.LpVariable(
      f"role_after_year1_{index}",
      lowBound=0.0,
      upBound=1.0,
      cat="Binary",
    )
    payroll_var = pulp.LpVariable(
      f"role_payroll_{index}",
      lowBound=0.0,
      upBound=(wage_ceiling * 12.0 / 12.0),
      cat="Continuous",
    )
    role_month_vars[role_title] = month_var
    role_active_month_vars[role_title] = active_months_var
    role_payroll_vars[role_title] = payroll_var
    role_wage_meta[role_title] = {
      "annual_wage": annual_wage,
      "wage_floor": wage_floor,
      "wage_ceiling": wage_ceiling,
      "baseline_year1_amount": baseline_year1_amount,
      "base_months": float(base_months),
    }
    delay_big_m = float(max(MAX_ROLE_DELAY_MONTHS, max_months, 12))
    problem += month_var <= 12 + delay_big_m * starts_after_year1
    problem += month_var >= 12 * starts_after_year1
    problem += active_months_var >= 12 - month_var
    problem += active_months_var <= 12 - month_var + delay_big_m * starts_after_year1
    problem += active_months_var <= 12 * (1 - starts_after_year1)
    problem += payroll_var >= (wage_floor / 12.0) * active_months_var
    problem += payroll_var <= (wage_ceiling / 12.0) * active_months_var
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
  payroll_excess = pulp.LpVariable("payroll_excess", lowBound=0.0, cat="Continuous")
  if target_payroll_min_total > 0:
    problem += payroll_expr >= target_payroll_min_total
  if target_payroll_max_total > 0:
    problem += payroll_expr - payroll_excess <= target_payroll_max_total
  else:
    problem += payroll_excess == 0
  required_structural_payroll_expr: Any = max(structural_payroll_floor, structural_payroll_base)
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
  support_basis = payroll_support_basis if payroll_support_basis in {"role_months", "payroll"} else capacity_basis
  support_units_per_role_month = (
    units_per_active_role_month if support_basis == "role_months" and units_per_active_role_month > 0 else capacity_units_per_role_month
  )
  support_units_per_payroll = (
    units_per_payroll_dollar if support_basis == "payroll" and units_per_payroll_dollar > 0 else capacity_units_per_payroll
  )
  adjustable_active_role_months_expr = pulp.lpSum(active_month_var for active_month_var in role_active_month_vars.values())
  if support_basis == "role_months" and support_units_per_role_month > 0:
    required_adjustable_active_role_months = pulp.LpVariable(
      "required_adjustable_active_role_months",
      lowBound=0.0,
      cat="Continuous",
    )
    problem += units_expr <= support_units_per_role_month * (fixed_active_role_months + required_adjustable_active_role_months)
    problem += adjustable_active_role_months_expr >= required_adjustable_active_role_months
    if role_month_support_profile:
      required_structural_payroll_expr = fixed_people_payroll + pulp.lpSum(
        max(0.0, _safe_float(item.get("month_share"))) * max(0.0, _safe_float(item.get("monthly_wage_floor"))) * required_adjustable_active_role_months
        for item in role_month_support_profile
        if isinstance(item, dict)
      )
    elif adjustable_role_month_cost_floor > 0:
      required_structural_payroll_expr = fixed_people_payroll + (adjustable_role_month_cost_floor * required_adjustable_active_role_months)
    elif structural_payroll_floor > 0:
      required_structural_payroll_expr = structural_payroll_floor
    if adjustable_role_month_cost_floor > 0 or role_month_support_profile or structural_payroll_floor > 0:
      problem += payroll_expr >= required_structural_payroll_expr
    staffing_supported_units = support_units_per_role_month * (fixed_active_role_months + adjustable_active_role_months_expr)
    problem += units_expr <= staffing_supported_units
  elif support_basis == "payroll" and support_units_per_payroll > 0:
    required_structural_payroll_expr = units_expr / support_units_per_payroll
    problem += payroll_expr >= required_structural_payroll_expr
    staffing_supported_units = support_units_per_payroll * payroll_expr
    problem += units_expr <= staffing_supported_units
  if bool((capacity_curve or {}).get("enabled")) and capacity_basis == "hard_units":
    hard_units_min = max(0.0, _safe_float((capacity_curve or {}).get("hard_units_min")) or units_min)
    hard_units_max = max(hard_units_min, _safe_float((capacity_curve or {}).get("hard_units_max")) or units_max)
    problem += units_expr >= hard_units_min
    problem += units_expr <= hard_units_max
  elif support_basis not in {"role_months", "payroll"} and structural_payroll_floor > 0:
    required_structural_payroll_expr = structural_payroll_floor
    problem += payroll_expr >= required_structural_payroll_expr

  if hard_utilization_floor is not None and hard_utilization_floor > 0:
    problem += util >= hard_utilization_floor

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
  payroll_down_max_ratio_raw = profile_constraints.get("payroll_down_max_ratio")
  payroll_down_max_ratio = _safe_float(payroll_down_max_ratio_raw)
  if payroll_down_max_ratio_raw is not None:
    problem += total_payroll_down_expr <= payroll_down_max_ratio
  payroll_up_max_ratio_raw = profile_constraints.get("payroll_up_max_ratio")
  payroll_up_max_ratio = _safe_float(payroll_up_max_ratio_raw)
  if payroll_up_max_ratio_raw is not None:
    problem += total_payroll_up_expr <= payroll_up_max_ratio
  hire_delay_max_months_total_raw = profile_constraints.get("hire_delay_max_months_total")
  hire_delay_max_months_total = _safe_float(hire_delay_max_months_total_raw)
  if hire_delay_max_months_total_raw is not None:
    problem += total_delay_expr <= hire_delay_max_months_total
  hire_advance_max_months_total_raw = profile_constraints.get("hire_advance_max_months_total")
  hire_advance_max_months_total = _safe_float(hire_advance_max_months_total_raw)
  if hire_advance_max_months_total_raw is not None:
    problem += total_advance_expr <= hire_advance_max_months_total
  units_min_ratio = _safe_float(profile_constraints.get("units_min_ratio"))
  if baseline_units > 0 and units_min_ratio > 0:
    problem += units_expr >= (baseline_units * units_min_ratio)

  growth_units_shortfall = None
  growth_units_priority = (
    bool(profile_constraints.get("prefer_growth_units"))
    and growth_demand_mode_enabled
  )
  if growth_units_priority:
    growth_units_target = max(
      baseline_units,
      expected_units,
      marketing_support_units_baseline,
    )
    if marketing_support_units_max > 0:
      growth_units_target = min(growth_units_target, marketing_support_units_max)
    if units_max > 0:
      growth_units_target = min(growth_units_target, units_max)
    growth_units_target = max(0.0, growth_units_target)
    if growth_units_target > 0:
      growth_units_shortfall = pulp.LpVariable("growth_units_shortfall", lowBound=0.0, cat="Continuous")
      problem += units_expr + growth_units_shortfall >= growth_units_target

  shortfall = None
  target_ebitda_min = None if target_ebitda_min is None else float(target_ebitda_min)
  target_ebitda_max = None if target_ebitda_max is None else float(target_ebitda_max)
  if target_ebitda_min is not None or target_ebitda_max is not None:
    shortfall = pulp.LpVariable("ebitda_shortfall", lowBound=0.0, cat="Continuous")
    if target_ebitda_min is not None:
      problem += ebitda_expr + shortfall >= target_ebitda_min
    if target_ebitda_max is not None:
      problem += ebitda_expr - shortfall <= target_ebitda_max

  marketing_up = pulp.LpVariable("marketing_up", lowBound=0.0, cat="Continuous")
  marketing_down = pulp.LpVariable("marketing_down", lowBound=0.0, cat="Continuous")
  problem += marketing_expr - current_marketing == marketing_up - marketing_down
  if child_first:
    child_price_up_terms: List[Any] = []
    child_price_down_terms: List[Any] = []
    child_util_up_terms: List[Any] = []
    child_util_down_terms: List[Any] = []
    for item in product_driver_basis:
      if not isinstance(item, dict):
        continue
      product_key = str(item.get("product_key") or "").strip()
      if product_key not in child_price_vars or product_key not in child_util_vars:
        continue
      baseline_price = max(0.0, _safe_float(item.get("unit_price")))
      baseline_util = _normalize_ratio(item.get("utilization_rate")) or 0.0
      price_up_var = pulp.LpVariable(f"price_up_{product_key.replace(':', '_')}", lowBound=0.0, cat="Continuous")
      price_down_var = pulp.LpVariable(f"price_down_{product_key.replace(':', '_')}", lowBound=0.0, cat="Continuous")
      util_up_var = pulp.LpVariable(f"util_up_{product_key.replace(':', '_')}", lowBound=0.0, cat="Continuous")
      util_down_var = pulp.LpVariable(f"util_down_{product_key.replace(':', '_')}", lowBound=0.0, cat="Continuous")
      problem += child_price_vars[product_key] - baseline_price == price_up_var - price_down_var
      problem += child_util_vars[product_key] - baseline_util == util_up_var - util_down_var
      child_price_up_vars[product_key] = price_up_var
      child_price_down_vars[product_key] = price_down_var
      child_util_up_vars[product_key] = util_up_var
      child_util_down_vars[product_key] = util_down_var
      move_weight = max(0.0, _safe_float(child_move_weights.get(product_key)))
      child_price_up_terms.append(move_weight * (price_up_var / max(baseline_price, 1.0)))
      child_price_down_terms.append(move_weight * (price_down_var / max(baseline_price, 1.0)))
      child_util_up_terms.append(move_weight * (util_up_var / max(1.0 - baseline_util, 1e-6)))
      child_util_down_terms.append(move_weight * (util_down_var / max(baseline_util or 1.0, 1e-6)))
    price_up_move = pulp.lpSum(child_price_up_terms) if child_price_up_terms else 0.0
    price_down_move = pulp.lpSum(child_price_down_terms) if child_price_down_terms else 0.0
    util_up_move = pulp.lpSum(child_util_up_terms) if child_util_up_terms else 0.0
    util_down_move = pulp.lpSum(child_util_down_terms) if child_util_down_terms else 0.0
    price_up = price_up_move
    price_down = price_down_move
    util_up = util_up_move
    util_down = util_down_move
  else:
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

  if not child_first:
    price_up_move = price_up / max(current_price, 1.0) if price_enabled else 0.0
    price_down_move = price_down / max(current_price, 1.0) if price_enabled else 0.0
    util_up_move = util_up / max(1.0 - current_util, 1e-6)
    util_down_move = util_down / max(current_util or 1.0, 1e-6)
  marketing_up_move = marketing_up / max(marketing_upper or 1.0, 1.0)
  marketing_down_move = marketing_down / max(current_marketing or 1.0, 1.0)
  opex_down_move = other_opex_down / max(current_other_opex or 1.0, 1.0)
  opex_up_move = other_opex_up / max(other_opex_max or 1.0, 1.0)
  marketing_up_cap_ratio_raw = profile_constraints.get("marketing_up_cap_ratio")
  marketing_up_cap_ratio = _safe_float(marketing_up_cap_ratio_raw)
  if marketing_up_cap_ratio_raw is not None:
    problem += marketing_up_move <= marketing_up_cap_ratio
  marketing_down_cap_ratio_raw = profile_constraints.get("marketing_down_cap_ratio")
  marketing_down_cap_ratio = _safe_float(marketing_down_cap_ratio_raw)
  if marketing_down_cap_ratio_raw is not None:
    problem += marketing_down_move <= marketing_down_cap_ratio
  price_up_cap_ratio_raw = profile_constraints.get("price_up_cap_ratio")
  price_up_cap_ratio = _safe_float(price_up_cap_ratio_raw)
  if price_up_cap_ratio_raw is not None and not isinstance(price_up_move, (int, float)):
    problem += price_up_move <= price_up_cap_ratio
  price_down_cap_ratio_raw = profile_constraints.get("price_down_cap_ratio")
  price_down_cap_ratio = _safe_float(price_down_cap_ratio_raw)
  if price_down_cap_ratio_raw is not None and not isinstance(price_down_move, (int, float)):
    problem += price_down_move <= price_down_cap_ratio
  util_up_cap_ratio_raw = profile_constraints.get("util_up_cap_ratio")
  util_up_cap_ratio = _safe_float(util_up_cap_ratio_raw)
  if util_up_cap_ratio_raw is not None and not isinstance(util_up_move, (int, float)):
    problem += util_up_move <= util_up_cap_ratio
  util_down_cap_ratio_raw = profile_constraints.get("util_down_cap_ratio")
  util_down_cap_ratio = _safe_float(util_down_cap_ratio_raw)
  if util_down_cap_ratio_raw is not None and not isinstance(util_down_move, (int, float)):
    problem += util_down_move <= util_down_cap_ratio
  other_opex_down_cap_ratio_raw = profile_constraints.get("other_opex_down_cap_ratio")
  other_opex_down_cap_ratio = _safe_float(other_opex_down_cap_ratio_raw)
  if other_opex_down_cap_ratio_raw is not None:
    problem += opex_down_move <= other_opex_down_cap_ratio
  other_opex_up_cap_ratio_raw = profile_constraints.get("other_opex_up_cap_ratio")
  other_opex_up_cap_ratio = _safe_float(other_opex_up_cap_ratio_raw)
  if other_opex_up_cap_ratio_raw is not None:
    problem += opex_up_move <= other_opex_up_cap_ratio
  cogs_down_move = cogs_down / max(current_cogs or 1.0, 1.0)
  cogs_up_move = cogs_up / max(current_cogs or 1.0, 1.0)
  cogs_down_cap_ratio_raw = profile_constraints.get("cogs_down_cap_ratio")
  cogs_down_cap_ratio = _safe_float(cogs_down_cap_ratio_raw)
  if cogs_down_cap_ratio_raw is not None:
    problem += cogs_down_move <= cogs_down_cap_ratio
  cogs_up_cap_ratio_raw = profile_constraints.get("cogs_up_cap_ratio")
  cogs_up_cap_ratio = _safe_float(cogs_up_cap_ratio_raw)
  if cogs_up_cap_ratio_raw is not None:
    problem += cogs_up_move <= cogs_up_cap_ratio
  payroll_down_move = total_payroll_down_expr / float(role_count)
  payroll_up_move = total_payroll_up_expr / float(role_count)
  hire_delay_move = total_delay_expr / (12.0 * float(role_count))
  hire_advance_move = total_advance_expr / (12.0 * float(role_count))
  child_product_spread_expr: Any = 0.0
  if child_first:
    child_spread_terms: List[Any] = []
    for item in product_driver_basis:
      if not isinstance(item, dict):
        continue
      product_key = str(item.get("product_key") or "").strip()
      if (
        product_key not in child_price_up_vars
        or product_key not in child_price_down_vars
        or product_key not in child_util_up_vars
        or product_key not in child_util_down_vars
      ):
        continue
      baseline_price = max(0.0, _safe_float(item.get("unit_price")))
      baseline_util = _normalize_ratio(item.get("utilization_rate")) or 0.0
      spread_var = pulp.LpVariable(f"child_spread_{product_key.replace(':', '_')}", lowBound=0.0, upBound=1.0, cat="Continuous")
      problem += spread_var >= (child_price_up_vars[product_key] / max(baseline_price, 1.0))
      problem += spread_var >= (child_price_down_vars[product_key] / max(baseline_price, 1.0))
      problem += spread_var >= (child_util_up_vars[product_key] / max(1.0 - baseline_util, 1e-6))
      problem += spread_var >= (child_util_down_vars[product_key] / max(baseline_util or 1.0, 1e-6))
      child_spread_terms.append(spread_var)
    if child_spread_terms:
      child_product_spread_expr = pulp.lpSum(child_spread_terms)
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
  total_family_move_expr = (
    price_up_move
    + price_down_move
    + util_up_move
    + util_down_move
    + marketing_up_move
    + marketing_down_move
    + opex_down_move
    + opex_up_move
    + cogs_down_move
    + cogs_up_move
    + hire_delay_move
    + hire_advance_move
    + payroll_down_move
    + payroll_up_move
  )
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
    + ((0.7 if growth_units_priority else 2.0) * (payroll_excess / revenue_scale))
  )
  dominant_family_excess = pulp.LpVariable("dominant_family_excess", lowBound=0.0, cat="Continuous")
  problem += dominant_family_excess >= max_family_move - (0.70 * total_family_move_expr)

  growth_coordination = pulp.LpVariable("growth_coordination", lowBound=0.0, cat="Continuous")
  growth_demand_move = marketing_up_move + util_up_move + price_up_move
  growth_staffing_move = payroll_up_move + hire_advance_move
  problem += growth_coordination <= growth_demand_move
  problem += growth_coordination <= growth_staffing_move

  operations_coordination = pulp.LpVariable("operations_coordination", lowBound=0.0, cat="Continuous")
  operations_structural_move = util_up_move + util_down_move + payroll_up_move + payroll_down_move + hire_delay_move + hire_advance_move
  operations_balance_move = price_up_move + price_down_move + opex_down_move + cogs_down_move + cogs_up_move
  problem += operations_coordination <= operations_structural_move
  problem += operations_coordination <= operations_balance_move

  efficiency_coordination = pulp.LpVariable("efficiency_coordination", lowBound=0.0, cat="Continuous")
  efficiency_cost_move = opex_down_move + cogs_down_move + payroll_down_move
  efficiency_structural_move = util_down_move + hire_delay_move + price_up_move + price_down_move + payroll_up_move
  problem += efficiency_coordination <= efficiency_cost_move
  problem += efficiency_coordination <= efficiency_structural_move
  solver = pulp.PULP_CBC_CMD(msg=False)

  if growth_units_shortfall is not None:
    problem.setObjective(growth_units_shortfall)
    status = problem.solve(solver)
    if status != pulp.LpStatusOptimal:
      trace_values(
        "ITERATION",
        f"Profile {profile_id} growth solve failed",
        status=int(status),
        reason="growth_units_shortfall_not_optimal",
      )
      return None
    optimal_growth_units_shortfall = _lp_value(growth_units_shortfall, 0.0)
    problem += growth_units_shortfall <= (optimal_growth_units_shortfall + 1e-6)

  if shortfall is not None:
    problem.setObjective(shortfall)
    status = problem.solve(solver)
    if status != pulp.LpStatusOptimal:
      trace_values(
        "ITERATION",
        f"Profile {profile_id} threshold solve failed",
        status=int(status),
        reason="threshold_objective_not_optimal",
      )
      return None
    optimal_shortfall = _lp_value(shortfall, 0.0)
    problem += shortfall <= (optimal_shortfall + 1e-6)
  else:
    optimal_shortfall = 0.0
  problem.setObjective(max_family_move)
  status = problem.solve(solver)
  if status != pulp.LpStatusOptimal:
    trace_values(
      "ITERATION",
      f"Profile {profile_id} family concentration solve degraded",
      status=int(status),
      reason="family_move_not_optimal_continuing",
    )
  else:
    optimal_max_family_move = _lp_value(max_family_move, 0.0)
    problem += max_family_move <= (optimal_max_family_move + 1e-6)

  final_objective = distortion_expr
  if family_concentration_weight > 0:
    final_objective = final_objective + (family_concentration_weight * max_family_move)
  final_objective = final_objective + (8.0 * dominant_family_excess)
  if child_first and not isinstance(child_product_spread_expr, (int, float)):
    final_objective = final_objective + (CHILD_PRODUCT_SPREAD_WEIGHT * child_product_spread_expr)
  profile_archetype = str(profile.get("archetype") or "").strip().lower()
  if profile_archetype == "growth":
    final_objective = final_objective - (4.0 * growth_coordination)
  elif profile_archetype == "efficiency":
    final_objective = final_objective - (4.0 * efficiency_coordination)
  else:
    final_objective = final_objective - (4.0 * operations_coordination)
  problem.setObjective(final_objective)
  status = problem.solve(solver)
  if status != pulp.LpStatusOptimal:
    trace_values(
      "ITERATION",
      f"Profile {profile_id} final objective solve failed",
      status=int(status),
      reason="final_objective_not_optimal",
    )
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
    )
    problem.setObjective(archetype_objective)
    status = problem.solve(solver)
    if status != pulp.LpStatusOptimal:
      trace_values(
        "ITERATION",
        f"Profile {profile_id} archetype refinement solve failed",
        status=int(status),
        reason="archetype_objective_not_optimal",
      )
      return None

  role_month_values = {
    role_title: int(round(_lp_value(month_var, 0.0)))
    for role_title, month_var in role_month_vars.items()
  }
  role_payroll_values = {
    role_title: round(_lp_value(payroll_var, 0.0), 2)
    for role_title, payroll_var in role_payroll_vars.items()
  }
  child_product_solution: Dict[str, Dict[str, Any]] = {}
  child_changed_product_count = 0
  solved_price_value = current_price
  solved_util_value = current_util
  solved_units_total = _lp_value(units_expr, 0.0)
  if child_first:
    solved_revenue_total = _lp_value(revenue_expr, 0.0)
    solved_capacity_total = 0.0
    for item in product_driver_basis:
      if not isinstance(item, dict):
        continue
      product_key = str(item.get("product_key") or "").strip()
      if product_key not in child_price_vars or product_key not in child_util_vars or product_key not in child_avg_unit_vars:
        continue
      solved_price = round(_lp_value(child_price_vars[product_key], _safe_float(item.get("unit_price"))), 2)
      solved_util = _lp_value(child_util_vars[product_key], _normalize_ratio(item.get("utilization_rate")) or 0.0)
      solved_avg_units = _lp_value(child_avg_unit_vars[product_key], _safe_float(item.get("avg_units_per_period_year1")))
      child_product_solution[product_key] = {
        "unit_price": solved_price,
        "utilization_rate": solved_util,
        "avg_units_per_period_year1": solved_avg_units,
      }
      if (
        abs(solved_price - max(0.0, _safe_float(item.get("unit_price")))) >= 0.01
        or abs(solved_avg_units - max(0.0, _safe_float(item.get("avg_units_per_period_year1")))) >= 0.01
        or abs(solved_util - (_normalize_ratio(item.get("utilization_rate")) or 0.0)) >= 0.0005
      ):
        child_changed_product_count += 1
      solved_capacity_total += max(0.0, _safe_float(item.get("annual_capacity_units")))
    if solved_units_total > 0:
      solved_price_value = round(solved_revenue_total / max(solved_units_total, 1e-9), 2)
    if solved_capacity_total > 0:
      solved_util_value = max(0.0, min(1.0, solved_units_total / max(solved_capacity_total, 1e-9)))
  else:
    solved_price_value = round(_lp_value(price, current_price), 2)
    solved_util_value = _lp_value(util, current_util)
  distortion_components = {
    "price_up": _safe_float(weights.get("price_up")) * max(0.0, _lp_value(price_up_move if child_first else price_up, 0.0) / (1.0 if child_first else max(current_price, 1.0))),
    "price_down": _safe_float(weights.get("price_down")) * max(0.0, _lp_value(price_down_move if child_first else price_down, 0.0) / (1.0 if child_first else max(current_price, 1.0))),
    "util_up": _safe_float(weights.get("util_up")) * max(0.0, _lp_value(util_up_move if child_first else util_up, 0.0) / (1.0 if child_first else max(1.0 - current_util, 1e-6))),
    "util_down": _safe_float(weights.get("util_down")) * max(0.0, _lp_value(util_down_move if child_first else util_down, 0.0) / (1.0 if child_first else max(current_util or 1.0, 1e-6))),
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
    "payroll_excess": 2.0 * max(0.0, _lp_value(payroll_excess, 0.0) / revenue_scale),
  }
  family_raw_components = {
    "price_up": (max(0.0, _lp_value(price_up_move, 0.0)) if child_first else (max(0.0, _lp_value(price_up, 0.0) / max(current_price, 1.0)) if price_enabled else 0.0)),
    "price_down": (max(0.0, _lp_value(price_down_move, 0.0)) if child_first else (max(0.0, _lp_value(price_down, 0.0) / max(current_price, 1.0)) if price_enabled else 0.0)),
    "util_up": (max(0.0, _lp_value(util_up_move, 0.0)) if child_first else max(0.0, _lp_value(util_up, 0.0) / max(1.0 - current_util, 1e-6))),
    "util_down": (max(0.0, _lp_value(util_down_move, 0.0)) if child_first else max(0.0, _lp_value(util_down, 0.0) / max(current_util or 1.0, 1e-6))),
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
    "payroll_excess": max(0.0, _lp_value(payroll_excess, 0.0) / revenue_scale),
  }
  solution_payload = {
    "profile_id": str(profile.get("profile_id") or "").strip() or "profile",
    "archetype": str(profile.get("archetype") or "").strip() or _scenario_archetype_meta(str(profile.get("profile_id") or "")).get("archetype") or "operations",
    "archetype_display": str(profile.get("archetype_display") or "").strip() or _scenario_archetype_meta(str(profile.get("profile_id") or "")).get("display") or "Operational balance",
    "dominant_tradeoff": str(profile.get("dominant_tradeoff") or "").strip() or _scenario_archetype_meta(str(profile.get("profile_id") or "")).get("tradeoff") or "rebalances the Year-1 plan within the realism envelope",
    "target_ebitda_min": None,
    "target_ebitda_max": None,
    "threshold_feasible": False,
    "anchor_strict": anchor_strict,
    "objective_tolerance_ratio": objective_tolerance_ratio,
    "price": solved_price_value,
    "utilization_rate": solved_util_value,
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
    "structural_payroll_shortfall": 0.0,
    "distortion_components": distortion_components,
    "distortion_total": sum(distortion_components.values()),
    "family_raw_components": family_raw_components,
    "max_family_move": _lp_value(max_family_move, 0.0),
    "final_objective_value": _lp_value(final_objective, 0.0),
    "optimal_final_objective": optimal_final_objective,
    "ebitda": _lp_value(ebitda_expr, 0.0),
    "net_income": _lp_value(net_income_expr, 0.0),
    "annual_units_total": solved_units_total,
    "child_product_solution": child_product_solution,
    "changed_child_product_count": child_changed_product_count,
    "shortfall": optimal_shortfall,
    "enforce_blocking_bands": bool(enforce_blocking_bands),
  }
  trace_lazy(
    "ITERATION",
    f"Profile {profile_id} solution accepted",
    lambda: solution_payload,
  )
  return solution_payload


def _build_product_overrides_from_child_solution(
  *,
  product_driver_basis: Sequence[Dict[str, Any]],
  child_product_solution: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
  overrides: Dict[str, Dict[str, Any]] = {}
  if not product_driver_basis or not isinstance(child_product_solution, dict):
    return overrides
  for item in product_driver_basis:
    if not isinstance(item, dict):
      continue
    product_key = str(item.get("product_key") or "").strip()
    if not product_key:
      continue
    solved = child_product_solution.get(product_key)
    solved = solved if isinstance(solved, dict) else {}
    if not solved:
      continue
    baseline_price = max(0.0, _safe_float(item.get("unit_price")))
    baseline_avg_units = max(0.0, _safe_float(item.get("avg_units_per_period_year1")))
    baseline_util = _normalize_ratio(item.get("utilization_rate"))
    target_price = max(0.0, _safe_float(solved.get("unit_price")))
    target_avg_units = max(0.0, _safe_float(solved.get("avg_units_per_period_year1")))
    target_util = _normalize_ratio(solved.get("utilization_rate"))

    override: Dict[str, Any] = {}
    if target_price > 0 and abs(target_price - baseline_price) >= 0.01:
      override["unit_price"] = round(target_price, 2)
    if abs(target_avg_units - baseline_avg_units) >= 0.01:
      override["avg_units_per_period_year1"] = round(target_avg_units, 4)
    if target_util is not None and (baseline_util is None or abs(target_util - baseline_util) >= 0.0005):
      override["utilization_rate"] = round(target_util, 6)
    if override:
      overrides[product_key] = override
  return overrides


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
  child_product_solution = solution.get("child_product_solution") if isinstance(solution, dict) else {}
  child_product_solution = child_product_solution if isinstance(child_product_solution, dict) else {}
  product_driver_basis = direct_inputs.get("product_driver_basis") if isinstance(direct_inputs, dict) else []
  product_driver_basis = product_driver_basis if isinstance(product_driver_basis, list) else []
  solve_mode = str(direct_inputs.get("solve_mode") or "parent_fallback").strip().lower()

  target_marketing = round(_safe_float(solution.get("marketing_total_year1")), 2)
  constraint_profile = direct_inputs.get("constraint_profile") if isinstance(direct_inputs, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}
  reachable_market = max(0.0, _safe_float((marketing_children or {}).get("reachable_market")))
  capacity_units = max(0.0, _safe_float(direct_inputs.get("capacity_units")))
  target_units = max(0.0, _safe_float(solution.get("annual_units_total")))
  if target_units <= 0:
    target_units = max(0.0, capacity_units * (target_util or current_util))
  target_support_units = round(_safe_float(solution.get("marketing_support_units_year1")), 2)

  if solve_mode == "child_first" and product_driver_basis:
    product_overrides = _build_product_overrides_from_child_solution(
      product_driver_basis=product_driver_basis,
      child_product_solution=child_product_solution,
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
  target_payroll_total = max(
    0.0,
    _safe_float(direct_inputs.get("fixed_people_payroll"))
    + sum(
      max(0.0, _safe_float(value))
      for value in (role_year1_payroll.values() if isinstance(role_year1_payroll, dict) else [])
    ),
  )
  current_payroll_total = max(
    0.0,
    _safe_float((direct_inputs or {}).get("current_payroll_total")),
  )
  if abs(target_payroll_total - current_payroll_total) >= 0.01:
    financials_patch["payroll_total_year1"] = round(target_payroll_total, 2)
    financials_patch["current_payroll"] = round(target_payroll_total, 2)
  baseline_roles = {
    str(role.get("role_title") or "").strip(): max(0, _safe_int(role.get("base_months")) or 0)
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
      target_months = max(0, _safe_int(months) or 0)
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
  trace_lazy(
    "DERIVED",
    "Baseline solver state",
    lambda: {
      "ops_json": ops_json or {},
      "people_json": people_json or {},
      "financials_json": baseline_financials,
      "financials_year1_json": financials_year1_json or {},
      "marketing_model_json": marketing_model_json or {},
      "normalized_traits": normalized_traits or {},
      "benchmark_payload": benchmark_payload or {},
      "constraint_engine_state": constraint_engine_state or {},
      "baseline_summary": baseline_summary,
    },
  )
  viability_mode, viability_target_ebitda_min, viability_margin_floor = _viability_adjustment_required(
    baseline_summary,
    constraint_engine_state=constraint_engine_state,
    normalized_traits=normalized_traits,
  )
  if not _solver_required(baseline_summary, constraint_engine_state=constraint_engine_state) and not viability_mode:
    trace_values(
      "FINAL",
      "Solver skipped",
      reason="solver_not_required",
      baseline_ebitda=_safe_float((baseline_summary or {}).get("ebitda")),
      baseline_loss_pct=_loss_pct(baseline_summary),
    )
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
    normalized_traits=normalized_traits,
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
  objective_policy = state_model.get("objective_policy") if isinstance(state_model, dict) else {}
  objective_policy = objective_policy if isinstance(objective_policy, dict) else {}
  objective_policy["viability_mode"] = bool(viability_mode)
  objective_policy["viability_target_ebitda_min"] = viability_target_ebitda_min
  objective_policy["viability_margin_floor"] = viability_margin_floor
  state_model["objective_policy"] = objective_policy
  baseline_forecast_bundle = _build_baseline_forecast_bundle(
    ops_json=ops_json or {},
    people_json=people_json or {},
    financials_json=baseline_financials,
    financials_year1_json=financials_year1_json or {},
    marketing_model_json=marketing_model_json,
    normalized_traits=normalized_traits,
    benchmark_payload=benchmark_payload,
    constraint_engine_state=constraint_engine_state,
  )
  state_model["baseline_forecast_bundle"] = _clone(baseline_forecast_bundle)
  base_state_model = _clone(state_model)
  # In live runtime, GPT strategy governance is mandatory for every plan.
  # The only bypass is the test harness, which patches this helper.
  gpt_strategy_required = _gpt_strategy_required()
  state_model["strategy_layer"] = _build_strategy_layer(
    state_model=state_model,
    baseline_summary=baseline_summary,
    constraint_engine_state=constraint_engine_state,
    normalized_traits=normalized_traits,
    viability_mode=viability_mode,
    baseline_forecast_bundle=baseline_forecast_bundle,
  )
  strategy_layer = state_model.get("strategy_layer") if isinstance(state_model.get("strategy_layer"), dict) else {}
  if gpt_strategy_required and (
    not isinstance(strategy_layer, dict)
    or str(strategy_layer.get("source") or "").strip() != "gpt"
    or not isinstance(strategy_layer.get("strategies"), list)
    or not list(strategy_layer.get("strategies") or [])
  ):
    return _build_blocking_solver_state(
      baseline_summary=baseline_summary,
      state_model=state_model,
      constraint_engine_state=constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      blocking_reason="gpt_strategy_selection_unavailable",
    )
  state_model = _apply_global_strategy_overrides_to_state_model(
    state_model=state_model,
    strategy_layer=(state_model.get("strategy_layer") if isinstance(state_model, dict) else {}) or {},
  )
  baseline_forecast_bundle = _build_baseline_forecast_bundle(
    ops_json=ops_json or {},
    people_json=people_json or {},
    financials_json=baseline_financials,
    financials_year1_json=financials_year1_json or {},
    marketing_model_json=marketing_model_json,
    normalized_traits=normalized_traits,
    benchmark_payload=benchmark_payload,
    constraint_engine_state=constraint_engine_state,
    scenario_strategy=_baseline_forecast_strategy_from_layer(
      (state_model.get("strategy_layer") if isinstance(state_model, dict) else {}) or {}
    ),
  )
  state_model["baseline_forecast_bundle"] = _clone(baseline_forecast_bundle)
  strategy_diagnosis = (
    (state_model.get("strategy_layer") or {}).get("diagnosis")
    if isinstance((state_model.get("strategy_layer") or {}), dict)
    else {}
  )
  strategy_diagnosis = strategy_diagnosis if isinstance(strategy_diagnosis, dict) else {}
  if viability_mode and baseline_summary:
    baseline_revenue_amount = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
    gpt_margin_min = strategy_diagnosis.get("gpt_expected_year1_ebitda_margin_min")
    gpt_margin_max = strategy_diagnosis.get("gpt_expected_year1_ebitda_margin_max")
    gpt_margin_min = max(-1.0, min(1.0, _safe_float(gpt_margin_min))) if gpt_margin_min is not None else None
    gpt_margin_max = max(-1.0, min(1.0, _safe_float(gpt_margin_max))) if gpt_margin_max is not None else None
    if gpt_margin_min is not None and baseline_revenue_amount > 0:
      viability_target_ebitda_min = baseline_revenue_amount * gpt_margin_min
    if gpt_margin_max is not None and baseline_revenue_amount > 0:
      objective_policy["viability_target_ebitda_max"] = baseline_revenue_amount * gpt_margin_max
  objective_policy["viability_target_ebitda_min"] = viability_target_ebitda_min
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
  attempted_scenarios: List[Dict[str, Any]] = []
  selected_scenarios: List[Dict[str, Any]] = []
  best_effort_scenarios: List[Dict[str, Any]] = []
  last_attempt_contract_bundles: List[Dict[str, Any]] = []
  seen_feasible = set()
  seen_fallback = set()
  healthy_ratio = max(0.0, _safe_float((objective_policy or {}).get("healthy_ebitda_margin_ratio")))
  baseline_revenue = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
  selected_target_label = "hard_structure_only"
  selected_target_amount = None
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
  if viability_mode and viability_target_ebitda_min is not None:
    selected_target_label = "minimal_viability_adjustment"
    selected_target_amount = viability_target_ebitda_min
    target_ebitda_min = viability_target_ebitda_min
    viability_target_ebitda_max = objective_policy.get("viability_target_ebitda_max") if isinstance(objective_policy, dict) else None
    if viability_target_ebitda_max is not None:
      target_ebitda_max = _safe_float(viability_target_ebitda_max)
      selected_target_ceiling = target_ebitda_max

  trace_lazy(
    "CONSTRAINTS",
    "Solver target selection",
    lambda: {
      "baseline_revenue": baseline_revenue,
      "baseline_ebitda": _safe_float((baseline_summary or {}).get("ebitda")),
      "baseline_ebitda_margin": current_ebitda_margin,
      "ebitda_band": ebitda_band,
      "healthy_ebitda_target": None,
      "viability_mode": viability_mode,
      "viability_margin_floor": viability_margin_floor,
      "viability_target_ebitda_min": viability_target_ebitda_min,
      "selected_target_label": selected_target_label,
      "target_ebitda_min": target_ebitda_min,
      "target_ebitda_max": target_ebitda_max,
      "baseline_blocking_count": baseline_blocking_count,
      "baseline_realism_distance": baseline_realism_distance,
    },
  )

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
    contract_bundle = _build_profile_solver_contract(
      state_model=state_model,
      direct_inputs=direct_inputs,
      profile=profile,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
    )
    attempt_contract_bundles.append(_clone(contract_bundle))
    contract_inputs = (
      contract_bundle.get("direct_inputs")
      if isinstance(contract_bundle.get("direct_inputs"), dict)
      else _clone(direct_inputs)
    )
    contract_profile = (
      contract_bundle.get("profile")
      if isinstance(contract_bundle.get("profile"), dict)
      else _clone(profile)
    )
    contract_target_ebitda_min = contract_bundle.get("target_ebitda_min")
    contract_target_ebitda_max = contract_bundle.get("target_ebitda_max")
    contract_diagnostics = (
      contract_bundle.get("diagnostics")
      if isinstance(contract_bundle.get("diagnostics"), dict)
      else {}
    )
    if contract_diagnostics:
      attempt_contract_feedback.append(_clone(contract_diagnostics))
      trace_lazy(
        "CONSTRAINTS",
        f"Profile {str(profile.get('profile_id') or '').strip() or 'profile'} solver contract",
        lambda: _clone(contract_diagnostics),
      )
    translation_issues = {
      str(item or "").strip()
      for item in (contract_diagnostics.get("issues") or [])
      if str(item or "").strip()
    }
    if translation_issues.intersection({
      "missing_required_lever_families",
      "missing_package_lever_families",
      "missing_package_orchestration",
      "untranslated_support_opex_effect",
      "untranslated_marketing_support_effect",
      "untranslated_staffing_capacity_effect",
      "target_ebitda_min_exceeds_contract_upper_bound",
      "target_ebitda_max_below_contract_lower_bound",
      "underpowered_gpt_target_path",
    }):
      trace_lazy(
        "ITERATION",
        f"Profile {str(profile.get('profile_id') or '').strip() or 'profile'} rejected before solve due to incomplete controller contract",
        lambda: {
          "contract_diagnostics": _clone(contract_diagnostics),
          "profile_id": str(profile.get("profile_id") or "").strip(),
        },
      )
      return None
    solution = _solve_direct_profile(
      profile=contract_profile,
      direct_inputs=contract_inputs,
      target_ebitda_min=contract_target_ebitda_min,
      target_ebitda_max=contract_target_ebitda_max,
      family_caps=family_caps,
      enforce_blocking_bands=enforce_blocking_bands,
    )
    if not isinstance(solution, dict):
      trace_values(
        "ITERATION",
        f"Profile {str(profile.get('profile_id') or '').strip() or 'profile'} yielded no solution",
        target_ebitda_min=contract_target_ebitda_min,
        target_ebitda_max=contract_target_ebitda_max,
        enforce_blocking_bands=enforce_blocking_bands,
        family_caps=family_caps or {},
        contract_diagnostics=contract_diagnostics,
      )
      return None
    revenue_scale = max(1.0, _safe_float(solution.get("revenue")) or _safe_float((baseline_summary or {}).get("revenue")))
    viability_tolerance = max(VIABILITY_TARGET_TOLERANCE_ABS, revenue_scale * VIABILITY_TARGET_TOLERANCE_RATIO)
    if (contract_target_ebitda_min is not None or contract_target_ebitda_max is not None) and _safe_float(solution.get("shortfall")) > viability_tolerance:
      trace_lazy(
        "ITERATION",
        f"Profile {str(profile.get('profile_id') or '').strip() or 'profile'} rejected for unresolved viability shortfall",
        lambda: {
          "shortfall": solution.get("shortfall"),
          "viability_tolerance": viability_tolerance,
          "target_ebitda_min": contract_target_ebitda_min,
          "target_ebitda_max": contract_target_ebitda_max,
          "solution": solution,
          "contract_diagnostics": contract_diagnostics,
        },
      )
      return None
    exact_patches = _exact_patches_from_solution(
      solution=solution,
      direct_inputs=contract_inputs,
      ops_json=ops_json,
    )
    profile_id = str(solution.get("profile_id") or profile.get("profile_id") or "").strip()
    signature = _scenario_signature(exact_patches)
    if not signature or signature in seen_signatures:
      trace_lazy(
        "ITERATION",
        f"Profile {profile_id} rejected duplicate or empty signature",
        lambda: {
          "signature": signature,
          "seen_signature_count": len(seen_signatures),
          "exact_patches": exact_patches,
        },
      )
      return None
    default_archetype_meta = _scenario_archetype_meta(profile_id)
    archetype_meta = {
      "archetype": str(profile.get("archetype") or solution.get("archetype") or default_archetype_meta.get("archetype") or "operations").strip() or "operations",
      "display": str(profile.get("archetype_display") or solution.get("archetype_display") or default_archetype_meta.get("display") or "Operational balance").strip() or "Operational balance",
      "tradeoff": str(profile.get("dominant_tradeoff") or solution.get("dominant_tradeoff") or default_archetype_meta.get("tradeoff") or "rebalances the Year-1 plan within the realism envelope").strip() or "rebalances the Year-1 plan within the realism envelope",
    }
    scenario_constraint_engine_state = _clone(constraint_engine_state or {})
    scenario_metrics = (
      scenario_constraint_engine_state.get("current_metrics")
      if isinstance(scenario_constraint_engine_state, dict)
      else {}
    )
    scenario_metrics = dict(scenario_metrics or {}) if isinstance(scenario_metrics, dict) else {}
    existing_support_basis = str(scenario_metrics.get("payroll_support_basis") or "").strip().lower()
    direct_support_basis = str(contract_inputs.get("payroll_support_basis") or "").strip().lower()
    resolved_support_basis = existing_support_basis
    if resolved_support_basis not in {"role_months", "payroll"} and direct_support_basis in {"role_months", "payroll"}:
      resolved_support_basis = direct_support_basis
    existing_structural_floor = max(0.0, _safe_float(scenario_metrics.get("structural_payroll_floor")))
    solved_structural_floor = max(0.0, _safe_float(solution.get("structural_payroll_required_total")))
    scenario_structural_floor = max(existing_structural_floor, solved_structural_floor)
    if existing_structural_floor > 0 and solved_structural_floor > 0:
      scenario_structural_floor = min(existing_structural_floor, solved_structural_floor)
    scenario_metrics.update(
      {
        "structural_payroll_floor": scenario_structural_floor,
        "payroll_support_basis": resolved_support_basis or existing_support_basis or "floor",
      }
    )
    if resolved_support_basis in {"role_months", "payroll"}:
      scenario_metrics["fixed_active_role_months"] = max(
        0.0,
        _safe_float(scenario_metrics.get("fixed_active_role_months"))
        or _safe_float(contract_inputs.get("fixed_active_role_months")),
      )
      scenario_metrics["baseline_adjustable_active_months"] = max(
        0.0,
        _safe_float(scenario_metrics.get("baseline_adjustable_active_months"))
        or _safe_float(contract_inputs.get("baseline_adjustable_active_months")),
      )
      scenario_metrics["adjustable_role_month_cost_floor"] = max(
        0.0,
        _safe_float(scenario_metrics.get("adjustable_role_month_cost_floor"))
        or _safe_float(contract_inputs.get("adjustable_role_month_cost_floor")),
      )
      scenario_metrics["units_per_active_role_month"] = max(
        0.0,
        _safe_float(scenario_metrics.get("units_per_active_role_month"))
        or _safe_float(contract_inputs.get("units_per_active_role_month")),
      )
      scenario_metrics["units_per_payroll_dollar"] = max(
        0.0,
        _safe_float(scenario_metrics.get("units_per_payroll_dollar"))
        or _safe_float(contract_inputs.get("units_per_payroll_dollar")),
      )
    if isinstance(scenario_constraint_engine_state, dict):
      scenario_constraint_engine_state["current_metrics"] = scenario_metrics
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
      scenario_constraint_engine_state=scenario_constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      target_ebitda_min=contract_target_ebitda_min,
      target_ebitda_max=contract_target_ebitda_max,
      allow_realism_relaxation=bool(viability_mode),
    )
    if not candidate:
      trace_lazy(
        "ITERATION",
        f"Profile {profile_id} candidate build failed",
        lambda: {
          "exact_patches": exact_patches,
          "solution": solution,
        },
      )
      return None
    candidate["solution_profile_id"] = profile_id
    candidate["strategy_id"] = str(contract_profile.get("strategy_id") or profile.get("strategy_id") or profile_id).strip() or profile_id
    candidate["strategy_name"] = str(contract_profile.get("strategy_name") or profile.get("strategy_name") or candidate["strategy_id"]).strip() or candidate["strategy_id"]
    candidate["strategy_source"] = str(contract_profile.get("strategy_source") or profile.get("strategy_source") or "deterministic").strip() or "deterministic"
    candidate["allowed_levers"] = [
      str(item or "").strip()
      for item in (contract_profile.get("allowed_levers") or profile.get("allowed_levers") or [])
      if str(item or "").strip()
    ]
    candidate["relationship_rules"] = [
      str(item or "").strip()
      for item in (contract_profile.get("relationship_rules") or profile.get("relationship_rules") or [])
      if str(item or "").strip()
    ]
    candidate["forecast_orchestration"] = _clone(contract_profile.get("forecast_orchestration") or profile.get("forecast_orchestration") or {})
    candidate["contract_diagnostics"] = _clone(contract_diagnostics)
    candidate["target_ebitda_min"] = contract_target_ebitda_min
    candidate["target_ebitda_max"] = contract_target_ebitda_max
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
    candidate.update(_derive_scenario_posture(candidate))
    candidate["dominant_tradeoff"] = _derive_structured_tradeoff(
      archetype=str(candidate.get("archetype") or "").strip(),
      demand_posture=str(candidate.get("demand_posture") or "").strip(),
      staffing_posture=str(candidate.get("staffing_posture") or "").strip(),
      cost_posture=str(candidate.get("cost_posture") or "").strip(),
      meaningful_families=candidate.get("meaningful_families") or [],
    )
    label, rationale, families = _label_and_rationale_from_patches(
      exact_patches,
      archetype=str(candidate.get("archetype") or "").strip() or archetype_meta["archetype"],
      archetype_display=str(candidate.get("archetype_display") or "").strip() or archetype_meta["display"],
      dominant_tradeoff=str(candidate.get("dominant_tradeoff") or "").strip(),
    )
    candidate["label"] = label
    candidate["rationale"] = rationale
    candidate["lever_families"] = list(families)
    candidate.update(_archetype_consistency(candidate))
    if _nontrivial_repair_required(
      baseline_realism_distance=baseline_realism_distance,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
      baseline_blocking_count=baseline_blocking_count,
    ) and _safe_float(candidate.get("meaningful_lever_count")) < 2:
      trace_lazy(
        "ITERATION",
        f"Profile {profile_id} candidate rejected for insufficient lever count",
        lambda: {
          "candidate": candidate,
          "meaningful_lever_count": candidate.get("meaningful_lever_count"),
        },
      )
      return None
    if _nontrivial_repair_required(
      baseline_realism_distance=baseline_realism_distance,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
      baseline_blocking_count=baseline_blocking_count,
    ):
      if max(0.0, _safe_float(candidate.get("dominant_family_share"))) > 0.72 and _safe_float(candidate.get("meaningful_lever_count")) < 3:
        trace_lazy(
          "ITERATION",
          f"Profile {profile_id} candidate rejected for family concentration",
          lambda: {
            "candidate": candidate,
            "dominant_family_share": candidate.get("dominant_family_share"),
            "meaningful_lever_count": candidate.get("meaningful_lever_count"),
          },
        )
        return None
    scenario_forecast = _build_scenario_forecast_bundle(
      baseline_state=baseline_state,
      exact_patches=exact_patches,
      modified_state=(candidate.get("modified_state") if isinstance(candidate.get("modified_state"), dict) else None),
      remaining_violations=candidate.get("remaining_violations") or [],
      constraint_engine_state=constraint_engine_state,
      normalized_traits=normalized_traits,
      benchmark_payload=benchmark_payload,
      scenario_strategy={
        "strategy_id": str(candidate.get("strategy_id") or "").strip(),
        "strategy_name": str(candidate.get("strategy_name") or "").strip(),
        "archetype": str(candidate.get("archetype") or "").strip(),
        "archetype_display": str(candidate.get("archetype_display") or "").strip(),
        "dominant_tradeoff": str(candidate.get("dominant_tradeoff") or "").strip(),
        "demand_posture": str(candidate.get("demand_posture") or "").strip(),
        "staffing_posture": str(candidate.get("staffing_posture") or "").strip(),
        "cost_posture": str(candidate.get("cost_posture") or "").strip(),
        "forecast_orchestration": _clone(candidate.get("forecast_orchestration") or {}),
      },
    )
    candidate["scenario_forecast"] = scenario_forecast
    candidate["forecast_engine_state"] = _clone((scenario_forecast or {}).get("forecast_engine_state") or {})
    candidate["forecast_quarters"] = _clone((scenario_forecast or {}).get("forecast_quarters") or [])
    candidate["forecast_years"] = _clone((scenario_forecast or {}).get("forecast_years") or [])
    candidate["forecast_summary"] = _clone((scenario_forecast or {}).get("forecast_summary") or {})
    seen_signatures.add(signature)
    target_list.append(candidate)
    return candidate

  def _run_profile_search(search_profiles: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    local_feasible: List[Dict[str, Any]] = []
    local_fallback: List[Dict[str, Any]] = []
    local_seen_feasible = set()
    local_seen_fallback = set()
    for profile in search_profiles:
      solved_for_profile = False
      if target_ebitda_min is not None or target_ebitda_max is not None:
        target_specs = [(selected_target_label, target_ebitda_min, target_ebitda_max, local_feasible, local_seen_feasible)]
        if viability_mode:
          target_specs.append((selected_target_label, None, None, local_fallback, local_seen_fallback))
      else:
        target_specs = [("fallback", None, None, local_fallback, local_seen_fallback)]
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
            candidate["target_ebitda_min"] = candidate.get("target_ebitda_min")
            candidate["target_ebitda_max"] = candidate.get("target_ebitda_max")
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
      relaxed_profile = _relax_strategy_profile(profile)
      trace_lazy(
        "ITERATION",
        f"Relaxing strategy envelope for {str(profile.get('profile_id') or '').strip() or 'profile'}",
        lambda: {
          "base_constraints": profile.get("constraints") or {},
          "relaxed_constraints": relaxed_profile.get("constraints") or {},
          "strategy_id": str(profile.get("strategy_id") or "").strip(),
        },
      )
      for target_label, target_floor, target_ceiling, target_list, seen_signatures in target_specs:
        candidate = None
        for enforce_blocking_bands in (True, False):
          candidate = _try_add_solution(
            profile=relaxed_profile,
            target_ebitda_min=target_floor,
            target_ebitda_max=target_ceiling,
            target_list=target_list,
            seen_signatures=seen_signatures,
            enforce_blocking_bands=enforce_blocking_bands,
          )
          if candidate:
            break
        if candidate:
          candidate["target_label"] = target_label
          candidate["target_ebitda_min"] = candidate.get("target_ebitda_min") if target_label != "fallback" else None
          candidate["target_ebitda_max"] = candidate.get("target_ebitda_max") if target_label != "fallback" else None
          candidate["strategy_relaxed"] = True
          solved_for_profile = True
          break
      if solved_for_profile:
        continue
    return local_feasible, local_fallback

  strategy_retry_attempts: List[Dict[str, Any]] = []
  max_governed_attempts = 3 if gpt_strategy_required else 1
  attempt_index = 0
  while attempt_index < max_governed_attempts:
    attempt_contract_feedback: List[Dict[str, Any]] = []
    attempt_contract_bundles: List[Dict[str, Any]] = []
    if attempt_index > 0:
      retry_feedback = {"prior_attempts": _clone(strategy_retry_attempts)}
      state_model = _clone(base_state_model)
      state_model["strategy_layer"] = _build_strategy_layer(
        state_model=state_model,
        baseline_summary=baseline_summary,
        constraint_engine_state=constraint_engine_state,
        normalized_traits=normalized_traits,
        viability_mode=viability_mode,
        baseline_forecast_bundle=baseline_forecast_bundle,
        solver_feedback=retry_feedback,
      )
      strategy_layer = state_model.get("strategy_layer") if isinstance(state_model.get("strategy_layer"), dict) else {}
      if (
        not isinstance(strategy_layer, dict)
        or str(strategy_layer.get("source") or "").strip() != "gpt"
        or not isinstance(strategy_layer.get("strategies"), list)
        or not list(strategy_layer.get("strategies") or [])
      ):
        return _build_blocking_solver_state(
          baseline_summary=baseline_summary,
          state_model=state_model,
          constraint_engine_state=constraint_engine_state,
          baseline_realism_distance=baseline_realism_distance,
          blocking_reason="gpt_strategy_selection_unavailable",
          governed_attempt_count=attempt_index + 1,
          strategy_retry_attempts=strategy_retry_attempts,
          attempted_contract_bundles=attempt_contract_bundles,
        )
      state_model = _apply_global_strategy_overrides_to_state_model(
        state_model=state_model,
        strategy_layer=(state_model.get("strategy_layer") if isinstance(state_model, dict) else {}) or {},
      )
      strategy_diagnosis = (
        (state_model.get("strategy_layer") or {}).get("diagnosis")
        if isinstance((state_model.get("strategy_layer") or {}), dict)
        else {}
      )
      strategy_diagnosis = strategy_diagnosis if isinstance(strategy_diagnosis, dict) else {}
      objective_policy = state_model.get("objective_policy") if isinstance(state_model, dict) else {}
      objective_policy = objective_policy if isinstance(objective_policy, dict) else {}
      if viability_mode and baseline_summary:
        baseline_revenue_amount = max(0.0, _safe_float((baseline_summary or {}).get("revenue")))
        gpt_margin_min = strategy_diagnosis.get("gpt_expected_year1_ebitda_margin_min")
        gpt_margin_max = strategy_diagnosis.get("gpt_expected_year1_ebitda_margin_max")
        gpt_margin_min = max(-1.0, min(1.0, _safe_float(gpt_margin_min))) if gpt_margin_min is not None else None
        gpt_margin_max = max(-1.0, min(1.0, _safe_float(gpt_margin_max))) if gpt_margin_max is not None else None
        local_viability_target_min = viability_target_ebitda_min
        if gpt_margin_min is not None and baseline_revenue_amount > 0:
          local_viability_target_min = baseline_revenue_amount * gpt_margin_min
        local_viability_target_max = None
        if gpt_margin_max is not None and baseline_revenue_amount > 0:
          local_viability_target_max = baseline_revenue_amount * gpt_margin_max
          objective_policy["viability_target_ebitda_max"] = local_viability_target_max
        objective_policy["viability_target_ebitda_min"] = local_viability_target_min
        state_model["objective_policy"] = objective_policy
        if local_viability_target_min is not None:
          target_ebitda_min = local_viability_target_min
          selected_target_amount = local_viability_target_min
        target_ebitda_max = local_viability_target_max
        selected_target_ceiling = local_viability_target_max
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
          governed_attempt_count=attempt_index + 1,
          strategy_retry_attempts=strategy_retry_attempts,
          attempted_contract_bundles=attempt_contract_bundles,
        )
      profiles = _solver_profiles(state_model=state_model)
      trace_lazy(
        "ITERATION",
        "Retrying GPT-selected strategy set after governed miss",
        lambda: {
          "retry_attempt": attempt_index + 1,
          "selected_strategy_ids": [
            str(item.get("strategy_id") or "").strip()
            for item in ((state_model.get("strategy_layer") or {}).get("strategies") or [])
            if isinstance(item, dict)
          ],
          "solver_feedback": retry_feedback,
        },
      )
    feasible_scenarios, fallback_scenarios = _run_profile_search(profiles)
    last_attempt_contract_bundles = _clone(attempt_contract_bundles)
    attempted_scenarios = feasible_scenarios if feasible_scenarios else fallback_scenarios
    scenarios = attempted_scenarios
    zero_blocker_scenarios = [
      candidate for candidate in scenarios
      if isinstance(candidate, dict) and _safe_float(candidate.get("remaining_blocking_count")) <= 0
    ]
    if zero_blocker_scenarios:
      scenarios = zero_blocker_scenarios
    selected_scenarios = _select_client_ready_scenarios(scenarios, state_model=state_model)
    if selected_scenarios:
      break
    best_effort_scenarios = _select_best_effort_governed_scenarios(scenarios, state_model=state_model)
    if not gpt_strategy_required or attempt_index >= max_governed_attempts - 1:
      break
    strategy_retry_attempts.append(
      _strategy_retry_feedback(
        strategy_layer=(state_model.get("strategy_layer") if isinstance(state_model, dict) else {}) or {},
        direct_inputs=direct_inputs,
        contract_feedback=attempt_contract_feedback,
        feasible_scenarios=feasible_scenarios,
        fallback_scenarios=fallback_scenarios,
        attempted_scenarios=attempted_scenarios,
        client_ready_scenarios=selected_scenarios,
        baseline_summary=baseline_summary,
      )
    )
    attempt_index += 1
  if not feasible_scenarios and not fallback_scenarios:
    trace_lazy(
      "ITERATION",
      "Selected strategy set produced no scenarios",
      lambda: {
        "selected_strategy_ids": [
          str(item.get("strategy_id") or "").strip()
          for item in ((state_model.get("strategy_layer") or {}).get("strategies") or [])
          if isinstance(item, dict)
        ] if isinstance(state_model, dict) else [],
        "strategy_source": str(((state_model.get("strategy_layer") or {}) if isinstance(state_model, dict) else {}).get("source") or "").strip(),
      },
    )
    best_effort_scenarios = _build_governed_rescue_scenarios(
      contract_bundles=last_attempt_contract_bundles,
      baseline_summary=baseline_summary,
      baseline_state=baseline_state,
      marketing_model_json=marketing_model_json,
      ops_json=ops_json,
      constraint_engine_state=constraint_engine_state,
      baseline_realism_distance=baseline_realism_distance,
      normalized_traits=normalized_traits,
      benchmark_payload=benchmark_payload,
      target_ebitda_min=target_ebitda_min,
      target_ebitda_max=target_ebitda_max,
      viability_mode=viability_mode,
    )

  break_even_found = bool(feasible_scenarios)
  scenarios = selected_scenarios if selected_scenarios else best_effort_scenarios
  if not feasible_scenarios and not viability_mode:
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
      governed_attempt_count=attempt_index + 1,
      strategy_retry_attempts=strategy_retry_attempts,
      attempted_contract_bundles=last_attempt_contract_bundles,
      attempted_scenarios=attempted_scenarios,
    )

  normalized_selected: List[Dict[str, Any]] = []
  client_selected: List[Dict[str, Any]] = []
  selection_mode = "client_ready" if selected_scenarios else "best_effort_governed"
  for index, candidate in enumerate(scenarios, start=1):
    normalized = dict(candidate)
    normalized["scenario_id"] = str(index)
    normalized["presentation_issues"] = list(normalized.get("presentation_issues") or [])
    normalized["client_output"] = _build_client_scenario_output(normalized, scenario_id=str(index))
    normalized_selected.append(normalized)
    client_selected.append(_clone(normalized["client_output"]))

  final_state = {
    "status": "awaiting_choice",
    "solve_mode": str(state_model.get("solve_mode") or "parent_fallback"),
    "target_metric": "year1_realism",
    "search_mode": "direct_pulp",
    "selection_mode": selection_mode,
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
    "governed_attempt_count": attempt_index + 1,
    "strategy_retry_attempts": _clone(strategy_retry_attempts),
    "strategy_layer": _clone(state_model.get("strategy_layer") or {}),
    "scenarios": normalized_selected,
    "client_scenarios": client_selected,
  }
  trace_lazy(
    "FINAL",
    "Solver final state",
    lambda: final_state,
  )
  return final_state


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

  selected_modified_state = (
    _clone(selected.get("modified_state"))
    if isinstance(selected.get("modified_state"), dict)
    else {}
  )
  exact_patches = {} if selected_modified_state else _clone(selected.get("exact_patches") or {})
  overrides = overrides if isinstance(overrides, dict) else {}
  base_ops_json = selected_modified_state.get("ops_json") if isinstance(selected_modified_state.get("ops_json"), dict) else (ops_json or {})
  base_people_json = selected_modified_state.get("people_json") if isinstance(selected_modified_state.get("people_json"), dict) else (people_json or {})
  base_financials_json = selected_modified_state.get("financials_json") if isinstance(selected_modified_state.get("financials_json"), dict) else (financials_json or {})
  base_financials_year1_json = selected_modified_state.get("financials_year1_json") if isinstance(selected_modified_state.get("financials_year1_json"), dict) else (financials_year1_json or {})
  base_marketing_model_json = selected_modified_state.get("marketing_model_json") if isinstance(selected_modified_state.get("marketing_model_json"), dict) else (marketing_model_json or {})
  if selected_modified_state and not overrides:
    return {
      "ops_json": _clone(base_ops_json),
      "people_json": _clone(base_people_json),
      "financials_json": _clone(base_financials_json),
      "financials_year1_json": _clone(base_financials_year1_json),
      "marketing_model_json": _clone(base_marketing_model_json),
      "summary": build_consistency_financial_summary(
        financials_json=base_financials_json,
        financials_year1_json=base_financials_year1_json,
      ),
      "exact_patches": _clone(selected.get("exact_patches") or {}),
      "scenario": selected,
    }
  state_model = solver_state.get("state_model") if isinstance(solver_state, dict) else {}
  constraint_profile = (state_model or {}).get("constraint_profile") if isinstance(state_model, dict) else {}
  marketing_children = (constraint_profile or {}).get("marketing_children") if isinstance(constraint_profile, dict) else {}
  baseline_expected_units = max(0.0, _safe_float((marketing_children or {}).get("baseline_expected_units_year1")))
  units_per_marketing_dollar = max(0.0, _safe_float(((constraint_profile or {}).get("demand_curve") or {}).get("units_per_marketing_dollar")))

  if overrides.get("price_change_percent") is not None:
    current_price = _safe_float(
      _top_level_driver_value(base_financials_year1_json or {}, "unit_price")
      or (base_ops_json or {}).get("unit_price")
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

  if overrides.get("marketing_reduction_percent") is not None:
    current_marketing = _safe_float((base_financials_json or {}).get("marketing_total_year1"))
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
    current_other_opex = _safe_float((base_financials_json or {}).get("other_operating_expense"))
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
      ops_json=base_ops_json,
      minimum_months=int(max(1, months_until_hire)),
    )
    if milestone_updates:
      exact_patches["milestone_updates"] = milestone_updates

  milestone_months = _safe_int(overrides.get("milestone_timing_months_max"))
  if milestone_months is not None and milestone_months > 0:
    milestone_updates = exact_patches.get("milestone_updates")
    if not isinstance(milestone_updates, list) or not milestone_updates:
      auto_updates = _attach_milestone_updates_for_delay(
        ops_json=base_ops_json,
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

  modified_state = _build_modified_state(
    baseline_state={
      "ops_json": _clone(base_ops_json),
      "people_json": _clone(base_people_json),
      "financials_json": _clone(base_financials_json),
      "financials_year1_json": _clone(base_financials_year1_json),
      "marketing_model_json": _clone(base_marketing_model_json),
    },
    exact_patches=exact_patches,
    marketing_model_json=base_marketing_model_json,
  )
  next_ops = modified_state.get("ops_json") if isinstance(modified_state.get("ops_json"), dict) else {}
  next_people = modified_state.get("people_json") if isinstance(modified_state.get("people_json"), dict) else {}
  next_financials = modified_state.get("financials_json") if isinstance(modified_state.get("financials_json"), dict) else {}
  next_year1 = modified_state.get("financials_year1_json") if isinstance(modified_state.get("financials_year1_json"), dict) else {}
  next_marketing_model = modified_state.get("marketing_model_json") if isinstance(modified_state.get("marketing_model_json"), dict) else {}
  violations = _scenario_violations(
    baseline_state={
      "ops_json": _clone(base_ops_json),
      "people_json": _clone(base_people_json),
      "financials_json": _clone(base_financials_json),
      "financials_year1_json": _clone(base_financials_year1_json),
      "marketing_model_json": _clone(base_marketing_model_json),
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
    "modified_state": modified_state,
    "scenario": selected,
  }
