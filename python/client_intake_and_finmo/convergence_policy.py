from __future__ import annotations

from typing import Any, Dict, Optional

try:
  from planning_contract import PLANNING_CONTRACT_VERSION  # type: ignore
except Exception:
  from client_intake_and_finmo.planning_contract import PLANNING_CONTRACT_VERSION  # type: ignore


CONVERGENCE_POLICY_VERSION = "convergence-policy/v1"
FORECAST_QUARTERS = 20

_FALLBACK_MULTIPLIERS = {
  "naics_6": 1.00,
  "naics_5": 0.94,
  "naics_4": 0.88,
  "naics_3": 0.80,
  "naics_2": 0.72,
  "trait_based": 0.60,
  "generic": 0.48,
}

_STAGE_SETTINGS = {
  "pre_revenue": {"start_quarter": 5, "strength": 0.62},
  "startup": {"start_quarter": 5, "strength": 0.72},
  "operating": {"start_quarter": 3, "strength": 0.86},
  "growth": {"start_quarter": 2, "strength": 0.94},
  "mature": {"start_quarter": 1, "strength": 1.00},
}

_METRIC_DEFAULTS = {
  "revenue_growth": {"base_strength": 0.78, "duration": 14},
  "gross_margin": {"base_strength": 0.82, "duration": 12},
  "ebitda_margin": {"base_strength": 0.84, "duration": 14},
  "payroll_intensity": {"base_strength": 0.90, "duration": 10},
  "opex_intensity": {"base_strength": 0.84, "duration": 10},
  "capex_percent_revenue": {"base_strength": 0.72, "duration": 10},
  "depreciation_percent_revenue": {"base_strength": 0.68, "duration": 10},
  "working_capital": {"base_strength": 0.92, "duration": 8},
  "utilization": {"base_strength": 0.52, "duration": 12},
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


def _metric_modifier(metric: str, *, traits: Dict[str, Any]) -> float:
  capacity_driver = str(traits.get("capacity_driver") or "").strip().lower()
  sales_modality = str(traits.get("sales_modality") or "").strip().lower()
  business_stage = str(traits.get("business_stage") or "").strip().lower()

  modifier = 1.0

  if metric == "payroll_intensity":
    if capacity_driver == "labor":
      modifier *= 1.18
    elif capacity_driver == "system":
      modifier *= 0.82
  elif metric == "capex_percent_revenue":
    if capacity_driver in ("equipment", "space"):
      modifier *= 1.18
    elif capacity_driver == "labor":
      modifier *= 0.86
  elif metric == "depreciation_percent_revenue":
    if capacity_driver in ("equipment", "space"):
      modifier *= 1.12
  elif metric == "revenue_growth":
    if sales_modality == "online":
      modifier *= 1.08
    elif sales_modality == "project_based":
      modifier *= 0.88
    elif sales_modality == "local_service":
      modifier *= 0.92
  elif metric == "ebitda_margin":
    if business_stage in ("pre_revenue", "startup"):
      modifier *= 0.82
  elif metric == "utilization":
    if capacity_driver == "labor":
      modifier *= 0.96
    elif capacity_driver == "system":
      modifier *= 1.06

  return modifier


def build_convergence_policy(
  *,
  normalized_traits: Optional[Dict[str, Any]] = None,
  benchmark_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  traits = normalized_traits if isinstance(normalized_traits, dict) else {}
  benchmark = benchmark_payload if isinstance(benchmark_payload, dict) else {}

  business_stage = str(traits.get("business_stage") or "operating").strip().lower() or "operating"
  stage_settings = _STAGE_SETTINGS.get(business_stage, _STAGE_SETTINGS["operating"])
  fallback_level = str(benchmark.get("fallback_level") or "generic").strip() or "generic"
  benchmark_confidence = _clamp(_to_float(benchmark.get("confidence_score")) or 0.0, 0.0, 1.0)
  fallback_multiplier = _FALLBACK_MULTIPLIERS.get(fallback_level, _FALLBACK_MULTIPLIERS["generic"])
  global_strength = _clamp(benchmark_confidence * fallback_multiplier * stage_settings["strength"], 0.12, 0.95)
  band_expansion = round(1.0 + ((1.0 - global_strength) * 0.55), 6)
  initial_weight = round(_clamp(0.18 + (0.42 * global_strength), 0.18, 0.72), 6)

  metrics: Dict[str, Dict[str, Any]] = {}
  for metric, defaults in _METRIC_DEFAULTS.items():
    modifier = _metric_modifier(metric, traits=traits)
    strength = _clamp(defaults["base_strength"] * global_strength * modifier, 0.08, 0.98)
    start_quarter = int(stage_settings["start_quarter"])
    if metric == "working_capital":
      start_quarter = max(1, start_quarter - 1)
    elif metric in ("ebitda_margin", "utilization"):
      start_quarter = min(FORECAST_QUARTERS, start_quarter + 1)
    duration = max(4, int(round(defaults["duration"] + ((1.0 - global_strength) * 4.0))))
    full_effect_quarter = min(FORECAST_QUARTERS, start_quarter + duration - 1)
    metrics[metric] = {
      "metric": metric,
      "start_quarter": start_quarter,
      "full_effect_quarter": full_effect_quarter,
      "strength": round(strength, 6),
      "band_expansion": band_expansion,
      "initial_weight": initial_weight,
    }

  return {
    "contract_version": PLANNING_CONTRACT_VERSION,
    "policy_version": CONVERGENCE_POLICY_VERSION,
    "fallback_level": fallback_level,
    "benchmark_confidence_score": round(benchmark_confidence, 3),
    "global_convergence_strength": round(global_strength, 6),
    "stage_start_quarter": int(stage_settings["start_quarter"]),
    "band_expansion": band_expansion,
    "metrics": metrics,
  }

