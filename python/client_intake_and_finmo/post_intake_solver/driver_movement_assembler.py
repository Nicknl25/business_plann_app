"""Driver Movement Assembler — Phase 2 module 1.

Given a business profile, returns the per-lever movement envelope that the
target-seeking solver consumes. For each lever:

  {
    lever_id, value_kind, applicable, schedule_locked,
    default_value, min_allowed, max_allowed,
    provenance: {naics_band, applicability, calibration_source},
  }

Sources, in priority order:
  1. NAICS industry baseline cascade (post_intake_industry_baseline_for_naics)
     — the deterministic default. benchmark_target -> default_value;
     benchmark_min/max bound the envelope (clamped to the mapping table's
     absolute live-value bounds).
  2. Per-lever applicability via post_intake_baseline_applicability_for_naics2
     and the dedicated applicability lookups (R&D, deferred revenue).
     When not applicable -> default_value=0.0, envelope collapsed to {0, 0}.
  3. Mapping-table band midpoint as last resort when NAICS has no coverage.
     Provenance carries calibration_source=`mapping_band_midpoint_no_naics_coverage`
     so Phase 3's GPT calibration consultant can override it.

The assembler is deterministic and runs once per business at the start of
the system run; the result is stored on the model_input_json (or an outer
solver_input payload) and consumed by the solver loop.

GPT calibration (Phase 3) is layered on top: it edits the envelope and
records `calibration_source=gpt_calibrated` with rationale per change. If
GPT is unavailable or returns invalid output, the deterministic defaults
stand and provenance carries `calibration_source=uncalibrated_due_to_gpt_failure`.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


DRIVER_MOVEMENT_ENVELOPE_KEY = "driver_movement_envelope"
HORIZON = 20

# Levers whose live values are computed by a downstream schedule and cannot
# be tweaked directly by the solver. To move these, the solver perturbs the
# schedule's parameters (see schedule_tweak module).
_SCHEDULE_LOCKED_LEVER_IDS = frozenset({
  "expenses::Payroll",
  "expenses::Depreciation",
  "schedules::Capital Expenditures",
  "schedules::Debt Issuance (New Borrowing)",
  "schedules::Debt Repayment (Scheduled)",
  "schedules::Less: Principal Repayments",
  "schedules::Plus: Net Additions",
})

# Per-lever applicability gating on top of the generic NAICS-2 baseline
# applicability resolver. Each entry maps a lever_id to a (loader_function,
# row_key) pair; the loader returns a dict whose `applicability_default`
# field decides applicability. Loaders are imported lazily to avoid a
# circular import between this module and post_intake_mapping.
_PER_LEVER_APPLICABILITY: Dict[str, Dict[str, Any]] = {
  "expenses::Research & Development": {
    "loader_path": (
      "client_intake_and_finmo.post_intake_mapping",
      "post_intake_r_and_d_applicability_for_naics2",
    ),
    "applicable_values": {"required", "optional"},
    "not_applicable_values": {"not_applicable"},
  },
}


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


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _naics_2_from_naics_6(naics_6: Optional[str]) -> str:
  return "".join(ch for ch in str(naics_6 or "") if ch.isdigit())[:2]


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
  # P3.40 Contract 6 Commit 3 -- Shape A consumer-side gate #2.
  # Validates the cascade resolver payload (13 fields per F5-α)
  # before returning to the envelope-assembly caller. Mirrors
  # the gate at finmo_bridge.py:339 _attach_seed_provenance.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore  # noqa: E501
    SIDE_CONSUMER as _IBR_SIDE_CONSUMER,
    validate_industry_baseline_cascade_payload_at_boundary,
  )
  validate_industry_baseline_cascade_payload_at_boundary(
    band, side=_IBR_SIDE_CONSUMER,
  )
  return band


def _resolve_cohort_band_for_lever(
  *,
  lever_id: str,
  metric_key: str,
  business_profile: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """First-priority band source: cohort-matched percentiles.

  Phase 3.5: queries industry_metrics_raw at runtime against a business
  cohort (NAICS prefix + revenue window + cap_category set + recent date
  window). Returns the cascade resolver's payload shape so the caller
  doesn't need to branch on the source. Returns None when:
    - business_profile is missing
    - the lever has no industry_metrics_raw column mapping
    - the cohort is too small at every widening tier (caller falls back
      to the cascade resolver via _resolve_naics_band)
  """
  if not isinstance(business_profile, dict) or not business_profile:
    return None
  try:
    from client_intake_and_finmo.post_intake_solver.cohort_band_resolver import (  # type: ignore
      LEVER_TO_METRIC_COLUMN,
      cohort_calibration_source_for_confidence,
      resolve_cohort_band,
    )
  except Exception:
    return None
  metric_column = LEVER_TO_METRIC_COLUMN.get(_clean_text(lever_id))
  if not metric_column:
    return None
  result = resolve_cohort_band(
    metric_key=metric_key or lever_id,
    business_profile=business_profile,
    metric_column_override=metric_column,
  )
  if result is None:
    return None
  payload = result.to_dict()
  payload["calibration_source"] = cohort_calibration_source_for_confidence(result.confidence_tier)
  return payload


def _resolve_per_lever_applicability(lever_id: str, naics_2: str) -> Optional[Dict[str, Any]]:
  rule = _PER_LEVER_APPLICABILITY.get(lever_id)
  if not rule or not naics_2:
    return None
  module_path, attr_name = rule["loader_path"]
  try:
    import importlib
    module = importlib.import_module(module_path)
    loader = getattr(module, attr_name)
    row = loader(naics_2)
  except Exception:
    return None
  if not isinstance(row, dict):
    return None
  applicability_default = _clean_text(row.get("applicability_default")).lower()
  if applicability_default in rule.get("not_applicable_values", set()):
    return {"applicable": False, "reason": f"per_lever_applicability:{applicability_default}"}
  if applicability_default in rule.get("applicable_values", set()):
    return {"applicable": True, "reason": f"per_lever_applicability:{applicability_default}"}
  return None


def _resolve_baseline_applicability(metric_key: str, naics_2: str) -> Optional[Dict[str, Any]]:
  if not metric_key or not naics_2:
    return None
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_baseline_applicability_for_naics2,
    )
    payload = post_intake_baseline_applicability_for_naics2(
      metric_key=metric_key, naics_2=naics_2
    )
  except Exception:
    return None
  if not isinstance(payload, dict):
    return None
  return {
    "applicable": bool(payload.get("applicable")),
    "reason": _clean_text(payload.get("reason")) or "baseline_applicability_lookup",
    "confidence": _clean_text(payload.get("confidence")),
  }


def _metric_key_for_lever(mapping_row: Dict[str, Any]) -> str:
  metric = _clean_text(mapping_row.get("target_metric_name"))
  if metric:
    return metric
  field = _clean_text(mapping_row.get("financial_model_field"))
  return field


def _bounds_for_mapping_row(mapping_row: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
  return (
    _safe_float(mapping_row.get("minimum_live_value")),
    _safe_float(mapping_row.get("maximum_live_value")),
  )


def _clamp_to_bounds(value: float, lo: Optional[float], hi: Optional[float]) -> float:
  result = float(value)
  if lo is not None and result < float(lo):
    result = float(lo)
  if hi is not None and result > float(hi):
    result = float(hi)
  return result


def _envelope_for_lever(
  *,
  mapping_row: Dict[str, Any],
  naics_6: str,
  naics_2: str,
  business_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  lever_id = _clean_text(mapping_row.get("lever_id"))
  metric_key = _metric_key_for_lever(mapping_row)
  value_kind = _clean_text(mapping_row.get("value_kind")).lower()
  control_owner = _clean_text(mapping_row.get("control_owner")).lower()
  schedule_locked = (
    lever_id in _SCHEDULE_LOCKED_LEVER_IDS
    or control_owner in {"payroll_headcount_schedule", "debt_schedule", "capex_schedule", "depreciation_schedule"}
  )
  mapping_min, mapping_max = _bounds_for_mapping_row(mapping_row)

  per_lever_applicability = _resolve_per_lever_applicability(lever_id, naics_2)
  baseline_applicability = _resolve_baseline_applicability(metric_key, naics_2)
  applicability = per_lever_applicability or baseline_applicability or {
    "applicable": True,
    "reason": "no_applicability_rule_default_applicable",
  }

  if not applicability.get("applicable"):
    return {
      "lever_id": lever_id,
      "metric_key": metric_key,
      "value_kind": value_kind,
      "applicable": False,
      "schedule_locked": schedule_locked,
      "default_value": 0.0,
      "min_allowed": 0.0,
      "max_allowed": 0.0,
      "provenance": {
        "calibration_source": "applicability_gate_not_applicable",
        "applicability": copy.deepcopy(applicability),
        "naics_band": None,
      },
    }

  # Phase 3.5: cohort-matched bands take priority over the cascade
  # resolver's pre-aggregated single-band-per-NAICS rows. When the
  # business cohort is too small at every widening tier, the function
  # returns None and we fall through to the cascade.
  cohort_band = _resolve_cohort_band_for_lever(
    lever_id=lever_id,
    metric_key=metric_key,
    business_profile=business_profile,
  )
  if cohort_band is not None:
    raw_min = _safe_float(cohort_band.get("benchmark_min"))
    raw_target = _safe_float(cohort_band.get("benchmark_target"))
    raw_max = _safe_float(cohort_band.get("benchmark_max"))
    if raw_target is not None or raw_min is not None or raw_max is not None:
      target = raw_target if raw_target is not None else (raw_min if raw_min is not None else raw_max)
      lo = raw_min if raw_min is not None else target
      hi = raw_max if raw_max is not None else target
      default_value = _clamp_to_bounds(float(target), mapping_min, mapping_max)
      min_allowed = _clamp_to_bounds(float(lo), mapping_min, mapping_max)
      max_allowed = _clamp_to_bounds(float(hi), mapping_min, mapping_max)
      if max_allowed < min_allowed:
        min_allowed, max_allowed = max_allowed, min_allowed
      return {
        "lever_id": lever_id,
        "metric_key": metric_key,
        "value_kind": value_kind,
        "applicable": True,
        "schedule_locked": schedule_locked,
        "default_value": round(default_value, 6),
        "min_allowed": round(min_allowed, 6),
        "max_allowed": round(max_allowed, 6),
        "provenance": {
          "calibration_source": cohort_band.get("calibration_source") or "cohort_matched_unknown",
          "applicability": copy.deepcopy(applicability),
          "cohort_band": {
            "metric_column": cohort_band.get("metric_column"),
            "benchmark_min": raw_min,
            "benchmark_target": raw_target,
            "benchmark_max": raw_max,
            "cohort_size": cohort_band.get("cohort_size"),
            "confidence_tier": cohort_band.get("confidence_tier"),
            "cohort_query": cohort_band.get("cohort_query"),
            "data_source": cohort_band.get("data_source"),
          },
          "naics_band": None,
        },
      }

  band = _resolve_naics_band(metric_key, naics_6) if metric_key else None
  if band is not None:
    raw_target = _safe_float(band.get("benchmark_target"))
    raw_min = _safe_float(band.get("benchmark_min"))
    raw_max = _safe_float(band.get("benchmark_max"))
    target = raw_target if raw_target is not None else (raw_min if raw_min is not None else raw_max)
    if target is None:
      band = None  # treat as no-coverage if neither target nor min/max present
    else:
      lo = raw_min if raw_min is not None else target
      hi = raw_max if raw_max is not None else target
      default_value = _clamp_to_bounds(float(target), mapping_min, mapping_max)
      min_allowed = _clamp_to_bounds(float(lo), mapping_min, mapping_max)
      max_allowed = _clamp_to_bounds(float(hi), mapping_min, mapping_max)
      if max_allowed < min_allowed:
        min_allowed, max_allowed = max_allowed, min_allowed
      return {
        "lever_id": lever_id,
        "metric_key": metric_key,
        "value_kind": value_kind,
        "applicable": True,
        "schedule_locked": schedule_locked,
        "default_value": round(default_value, 6),
        "min_allowed": round(min_allowed, 6),
        "max_allowed": round(max_allowed, 6),
        "provenance": {
          "calibration_source": "naics_default",
          "applicability": copy.deepcopy(applicability),
          "naics_band": {
            "metric_key": metric_key,
            "benchmark_target": raw_target,
            "benchmark_min": raw_min,
            "benchmark_max": raw_max,
            "naics_code_used": band.get("naics_code_used"),
            "naics_level_used": band.get("naics_level_used"),
            "confidence_tier": band.get("confidence_tier"),
            "data_source": band.get("data_source"),
            "trust_flag": band.get("trust_flag"),
          },
        },
      }

  # No NAICS coverage. Fall back to mapping-band midpoint with explicit
  # provenance. Phase 3 GPT calibration is expected to override this path.
  if mapping_min is not None and mapping_max is not None:
    midpoint = (float(mapping_min) + float(mapping_max)) / 2.0
    return {
      "lever_id": lever_id,
      "metric_key": metric_key,
      "value_kind": value_kind,
      "applicable": True,
      "schedule_locked": schedule_locked,
      "default_value": round(midpoint, 6),
      "min_allowed": round(float(mapping_min), 6),
      "max_allowed": round(float(mapping_max), 6),
      "provenance": {
        "calibration_source": "mapping_band_midpoint_no_naics_coverage",
        "applicability": copy.deepcopy(applicability),
        "naics_band": None,
      },
    }

  # No bounds at all — fail loudly. Phase 3 GPT must supply a calibration.
  return {
    "lever_id": lever_id,
    "metric_key": metric_key,
    "value_kind": value_kind,
    "applicable": True,
    "schedule_locked": schedule_locked,
    "default_value": None,
    "min_allowed": None,
    "max_allowed": None,
    "provenance": {
      "calibration_source": "uncalibrated_no_bounds",
      "applicability": copy.deepcopy(applicability),
      "naics_band": None,
    },
  }


def assemble_driver_movement_envelope(
  *,
  business_naics_6: Optional[str],
  live_count: int = HORIZON,
  mapping_rows: Optional[List[Dict[str, Any]]] = None,
  business_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
  """Build the deterministic driver movement envelope for a business.

  Args:
    business_naics_6: 6-digit NAICS code; non-digit chars stripped.
    live_count: number of forecast quarters (typically 20).
    mapping_rows: optional pre-loaded mapping rows; when None, the active
      rows from the post_intake_mapping_lookup are loaded.
    business_profile: Phase 3.5 — when supplied with naics_6 +
      target_annual_revenue + stage (+ optional business_model), the
      cohort-matched percentile resolver runs first; cascade resolver
      stays as fallback when the cohort is too small. When None, the
      assembler skips the cohort path and uses the cascade resolver
      exactly as in Phase 2.

  Returns:
    A payload dict with shape:
      {
        "horizon": <live_count>,
        "naics_6": <normalized>,
        "naics_2": <derived>,
        "drivers": { lever_id: <envelope_row> },
        "applicable_lever_ids": [...],
        "schedule_locked_lever_ids": [...],
        "uncalibrated_lever_ids": [...],   # for traceability
        "cohort_resolver_used": bool,
        "cohort_matched_lever_count": int,
      }
  """
  naics_6 = _normalized_naics_6(business_naics_6)
  naics_2 = _naics_2_from_naics_6(naics_6)

  effective_profile: Optional[Dict[str, Any]] = None
  if isinstance(business_profile, dict):
    effective_profile = dict(business_profile)
    if "naics_6" not in effective_profile:
      effective_profile["naics_6"] = naics_6

  if mapping_rows is None:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      load_post_intake_driver_target_mapping_rows,
    )
    rows = load_post_intake_driver_target_mapping_rows()
  else:
    rows = mapping_rows

  drivers: Dict[str, Dict[str, Any]] = {}
  applicable_lever_ids: List[str] = []
  schedule_locked_lever_ids: List[str] = []
  uncalibrated_lever_ids: List[str] = []
  cohort_matched_lever_ids: List[str] = []

  for raw_row in rows:
    if not isinstance(raw_row, dict):
      continue
    if _clean_text(raw_row.get("mapping_status")).lower() not in {"", "active"}:
      continue
    lever_id = _clean_text(raw_row.get("lever_id"))
    if not lever_id:
      continue
    envelope = _envelope_for_lever(
      mapping_row=raw_row,
      naics_6=naics_6,
      naics_2=naics_2,
      business_profile=effective_profile,
    )
    drivers[lever_id] = envelope
    if envelope.get("applicable"):
      applicable_lever_ids.append(lever_id)
    if envelope.get("schedule_locked"):
      schedule_locked_lever_ids.append(lever_id)
    calibration_source = (envelope.get("provenance") or {}).get("calibration_source")
    if isinstance(calibration_source, str) and calibration_source.startswith("cohort_matched_"):
      cohort_matched_lever_ids.append(lever_id)
    if calibration_source not in {
      "naics_default",
      "applicability_gate_not_applicable",
      "cohort_matched_high_confidence",
      "cohort_matched_medium_confidence",
      "cohort_matched_low_confidence",
    }:
      uncalibrated_lever_ids.append(lever_id)

  return {
    "contract_version": "driver_movement_envelope_v1",
    "horizon": int(max(0, live_count or HORIZON)),
    "naics_6": naics_6 or None,
    "naics_2": naics_2 or None,
    "decision_source": "python_proposer",
    "drivers": drivers,
    "applicable_lever_ids": sorted(applicable_lever_ids),
    "schedule_locked_lever_ids": sorted(schedule_locked_lever_ids),
    "uncalibrated_lever_ids": sorted(uncalibrated_lever_ids),
    "cohort_resolver_used": bool(effective_profile),
    "cohort_matched_lever_ids": sorted(cohort_matched_lever_ids),
    "cohort_matched_lever_count": len(cohort_matched_lever_ids),
  }


def default_value_for_lever(
  *,
  envelope_payload: Optional[Dict[str, Any]],
  lever_id: str,
) -> Optional[Dict[str, Any]]:
  """Lookup the single-lever default value + bounds from an assembled envelope.

  Used by finmo_bridge expense-row and balance-sheet row construction to
  populate Q1-Q20 driver values. Returns None when the lever isn't in the
  envelope (caller should treat as fail-loud).
  """
  if not isinstance(envelope_payload, dict):
    return None
  drivers = envelope_payload.get("drivers")
  if not isinstance(drivers, dict):
    return None
  entry = drivers.get(_clean_text(lever_id))
  if not isinstance(entry, dict):
    return None
  return copy.deepcopy(entry)
