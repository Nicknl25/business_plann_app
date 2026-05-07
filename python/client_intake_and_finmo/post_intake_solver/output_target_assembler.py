"""FINMO Output Target Assembler — Phase 2 module 2.

Per-metric target ranges that the target-seeking solver chases. For each
realism-band metric (gross_margin, ebitda_margin, net_income_margin,
ar_days_dso, ap_days_dpo, etc.):

  {
    metric_key, finmo_line_label, gate_kind,
    target_min, target_target, target_max,
    quarter_aggregation, applicability_rule_key,
    provenance: {naics_band, tolerance_bps, confidence_tier, calibration_source},
  }

Sources:
  1. realism_check_lookup row -> metric metadata (gate_kind, tolerance bps,
     applicability_rule_key, governs_model_input_lever_id)
  2. NAICS industry baseline (post_intake_industry_baseline_for_naics) ->
     benchmark_min/target/max
  3. Tolerance widening from realism row's tolerance_bps_<confidence_tier>
     applied symmetrically around benchmark_min/max.

This deterministic skeleton runs without GPT. Phase 3 layers GPT
calibration on top via the target-shaping consultant — it can tighten or
widen specific metric ranges per business profile. Provenance carries the
calibration source for every target row.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


FINMO_OUTPUT_TARGET_KEY = "finmo_output_targets"
HORIZON = 20

# Tolerance bps -> additive widening as a fraction. 100 bps = 1%-point
# widening on each side. Applied to ratio/percent metrics. For day-count
# metrics the realism formula treats bps as days directly via the
# tolerance_bps_<tier> -> days mapping defined in post_intake_realism.
_BPS_TO_FRACTION = 1.0 / 10000.0


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    number = float(value)
  except Exception:
    return None
  if number != number:
    return None
  return number


def _normalized_naics_6(naics_6: Optional[str]) -> str:
  return "".join(ch for ch in str(naics_6 or "") if ch.isdigit())


def _resolve_naics_band(metric_key: str, naics_6: str) -> Optional[Dict[str, Any]]:
  if not metric_key or not naics_6:
    return None
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    band = post_intake_industry_baseline_for_naics(metric_key=metric_key, naics_6=naics_6)
  except Exception:
    return None
  if not isinstance(band, dict) or band.get("trust_flag") == "no_coverage":
    return None
  return band


def _tolerance_bps_for_confidence(realism_row: Dict[str, Any], confidence_tier: str) -> Optional[float]:
  tier = _clean_text(confidence_tier).lower()
  field_map = {
    "high": "tolerance_bps_high_confidence",
    "high_confidence": "tolerance_bps_high_confidence",
    "medium": "tolerance_bps_medium_confidence",
    "medium_confidence": "tolerance_bps_medium_confidence",
    "low": "tolerance_bps_low_confidence",
    "low_confidence": "tolerance_bps_low_confidence",
    "generic": "tolerance_bps_generic_default",
    "generic_default": "tolerance_bps_generic_default",
  }
  field = field_map.get(tier) or "tolerance_bps_medium_confidence"
  value = _safe_float(realism_row.get(field))
  if value is not None:
    return value
  return _safe_float(realism_row.get("tolerance_bps_generic_default"))


def _is_day_count_metric(metric_key: str) -> bool:
  return "_days_" in metric_key or metric_key.endswith("_days") or "days_" in metric_key


def _target_range_for_metric(
  *,
  realism_row: Dict[str, Any],
  naics_6: str,
) -> Dict[str, Any]:
  metric_key = _clean_text(realism_row.get("metric_key"))
  band = _resolve_naics_band(metric_key, naics_6) if metric_key else None
  if band is None:
    return {
      "metric_key": metric_key,
      "finmo_line_label": _clean_text(realism_row.get("finmo_line_label")),
      "derivation_formula_key": _clean_text(realism_row.get("derivation_formula_key")),
      "quarter_aggregation": _clean_text(realism_row.get("quarter_aggregation")) or "per_quarter",
      "applicability_rule_key": _clean_text(realism_row.get("applicability_rule_key")) or None,
      "gate_kind": _clean_text(realism_row.get("gate_kind")) or "warn",
      "governs_model_input_lever_id": _clean_text(realism_row.get("governs_model_input_lever_id")) or None,
      "target_min": None,
      "target_target": None,
      "target_max": None,
      "provenance": {
        "calibration_source": "no_naics_coverage",
        "naics_band": None,
        "tolerance_bps": None,
        "confidence_tier": None,
      },
    }

  raw_target = _safe_float(band.get("benchmark_target"))
  raw_min = _safe_float(band.get("benchmark_min"))
  raw_max = _safe_float(band.get("benchmark_max"))
  confidence_tier = _clean_text(band.get("confidence_tier")) or "generic_default"
  tolerance_bps = _tolerance_bps_for_confidence(realism_row, confidence_tier)
  is_days = _is_day_count_metric(metric_key)
  widen = float(tolerance_bps or 0.0)
  if not is_days:
    widen = widen * _BPS_TO_FRACTION

  lo = raw_min if raw_min is not None else (raw_target if raw_target is not None else raw_max)
  hi = raw_max if raw_max is not None else (raw_target if raw_target is not None else raw_min)
  if lo is None or hi is None:
    target_min = None
    target_max = None
  else:
    target_min = float(lo) - widen
    target_max = float(hi) + widen
  target = raw_target if raw_target is not None else (
    (target_min + target_max) / 2.0 if target_min is not None and target_max is not None else None
  )

  return {
    "metric_key": metric_key,
    "finmo_line_label": _clean_text(realism_row.get("finmo_line_label")),
    "derivation_formula_key": _clean_text(realism_row.get("derivation_formula_key")),
    "quarter_aggregation": _clean_text(realism_row.get("quarter_aggregation")) or "per_quarter",
    "applicability_rule_key": _clean_text(realism_row.get("applicability_rule_key")) or None,
    "gate_kind": _clean_text(realism_row.get("gate_kind")) or "warn",
    "governs_model_input_lever_id": _clean_text(realism_row.get("governs_model_input_lever_id")) or None,
    "target_min": round(target_min, 6) if target_min is not None else None,
    "target_target": round(float(target), 6) if target is not None else None,
    "target_max": round(target_max, 6) if target_max is not None else None,
    "provenance": {
      "calibration_source": "naics_default",
      "naics_band": {
        "benchmark_target": raw_target,
        "benchmark_min": raw_min,
        "benchmark_max": raw_max,
        "naics_code_used": band.get("naics_code_used"),
        "naics_level_used": band.get("naics_level_used"),
        "confidence_tier": confidence_tier,
        "data_source": band.get("data_source"),
        "trust_flag": band.get("trust_flag"),
      },
      "tolerance_bps": tolerance_bps,
      "confidence_tier": confidence_tier,
    },
  }


def assemble_finmo_output_targets(
  *,
  business_naics_6: Optional[str],
  live_count: int = HORIZON,
  realism_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
  """Build the per-metric FINMO output target payload.

  Returns:
    {
      "contract_version": "finmo_output_targets_v1",
      "horizon": <live_count>,
      "naics_6": <normalized>,
      "decision_source": "python_proposer",
      "metrics": { metric_key: <target_row> },
      "metrics_with_naics_coverage": [...],
      "uncalibrated_metric_keys": [...],
    }
  """
  naics_6 = _normalized_naics_6(business_naics_6)
  if realism_rows is None:
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    rows = post_intake_finalize_realism_check_rows()
  else:
    rows = realism_rows

  metrics: Dict[str, Dict[str, Any]] = {}
  with_coverage: List[str] = []
  uncalibrated: List[str] = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    if not bool(row.get("active", True)):
      continue
    metric_key = _clean_text(row.get("metric_key"))
    if not metric_key:
      continue
    target = _target_range_for_metric(realism_row=row, naics_6=naics_6)
    metrics[metric_key] = target
    if (target.get("provenance") or {}).get("calibration_source") == "naics_default":
      with_coverage.append(metric_key)
    else:
      uncalibrated.append(metric_key)

  return {
    "contract_version": "finmo_output_targets_v1",
    "horizon": int(max(0, live_count or HORIZON)),
    "naics_6": naics_6 or None,
    "decision_source": "python_proposer",
    "metrics": metrics,
    "metrics_with_naics_coverage": sorted(with_coverage),
    "uncalibrated_metric_keys": sorted(uncalibrated),
  }
