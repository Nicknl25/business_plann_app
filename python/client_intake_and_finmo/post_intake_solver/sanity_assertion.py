"""Sanity-Assertion Finalize Check — Phase 2 module 6.

Replaces the deleted warning-aggregation block in finalize_post_intake.py.
After the solver returns, this assertion verifies the solver respected its
calibrated targets within numeric tolerance. If yes, it passes silently
(returning a structured "all_within_targets" payload). If no, it emits a
structured diagnostic naming the failed targets, the pinned drivers, and
the residual deviation.

Design contract (per Phase 2 directive):
  - The 1,314-warning aggregation theater is gone. The new finalize check
    is a *sanity check on the solver*, not a re-validation of the produced
    plan. By construction the solver should land all targets in range —
    if it doesn't, that's a solver bug.
  - Returns True/False status; the caller decides whether to raise or
    record. The Phase 2 finalize integration raises on any residual.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


_DEFAULT_NUMERIC_TOLERANCE = 1e-6

# CW-017 E7 (engine fragility ledger): the flat 1e-6 was applied to
# DOLLAR-scale metrics as well as ratios - on a $2M quarter it is
# effectively exact equality against a band edge, feeding two
# run-killers. Hybrid: the absolute floor stays exact for ratio-scale
# quantities; the relative term absorbs float residue at dollar scale.
_NUMERIC_TOLERANCE_RELATIVE = 1e-9


def _scaled_tolerance(floor: float, *edges: Optional[float]) -> float:
  scale = max((abs(float(e)) for e in edges if e is not None), default=0.0)
  return max(float(floor), scale * _NUMERIC_TOLERANCE_RELATIVE)


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


def _value_is_within_target(
  *,
  produced: Optional[float],
  target_min: Optional[float],
  target_max: Optional[float],
  numeric_tolerance: float,
) -> bool:
  if produced is None:
    return False
  if target_min is None and target_max is None:
    return True  # no calibrated target -> trivially within
  tol = _scaled_tolerance(numeric_tolerance, target_min, target_max, produced)
  if target_min is not None and produced + tol < float(target_min):
    return False
  if target_max is not None and produced - tol > float(target_max):
    return False
  return True


def _residual(
  *,
  produced: Optional[float],
  target_min: Optional[float],
  target_max: Optional[float],
) -> Optional[float]:
  if produced is None:
    return None
  lo = float(target_min) if target_min is not None else None
  hi = float(target_max) if target_max is not None else None
  if lo is not None and produced < lo:
    return round(produced - lo, 6)
  if hi is not None and produced > hi:
    return round(produced - hi, 6)
  return 0.0


def _produced_metric_series(
  *,
  finmo_json: Dict[str, Any],
  metric_key: str,
) -> List[Optional[float]]:
  quarter_rows = finmo_json.get("quarter_rows") if isinstance(finmo_json, dict) else None
  if not isinstance(quarter_rows, list):
    return []
  series: List[Optional[float]] = []
  for row in quarter_rows:
    if not isinstance(row, dict):
      series.append(None)
      continue
    series.append(_safe_float(row.get(metric_key)))
  return series


def assert_solver_respected_targets(
  *,
  finmo_json: Optional[Dict[str, Any]],
  output_targets_payload: Optional[Dict[str, Any]],
  driver_envelope_payload: Optional[Dict[str, Any]] = None,
  numeric_tolerance: float = _DEFAULT_NUMERIC_TOLERANCE,
) -> Dict[str, Any]:
  """Assert each output metric lands in its calibrated target range.

  Returns:
    {
      "status": "ok" | "residual_violations",
      "checked_metric_count": int,
      "violations": [
        {
          "metric_key", "quarter_index" (int|None),
          "produced", "target_min", "target_max", "residual",
          "gate_kind",
          "candidate_levers_pinned": [...],   # filled when envelope provided
        },
        ...
      ],
      "pinned_drivers": [
        {"lever_id", "current_value", "min_allowed", "max_allowed", "side"},
      ],
    }
  """
  finmo = finmo_json if isinstance(finmo_json, dict) else {}
  targets = output_targets_payload if isinstance(output_targets_payload, dict) else {}
  envelope = driver_envelope_payload if isinstance(driver_envelope_payload, dict) else {}

  violations: List[Dict[str, Any]] = []
  pinned_drivers: List[Dict[str, Any]] = []
  metrics = (targets.get("metrics") or {}) if isinstance(targets.get("metrics"), dict) else {}

  for metric_key, target_row in metrics.items():
    if not isinstance(target_row, dict):
      continue
    target_min = _safe_float(target_row.get("target_min"))
    target_max = _safe_float(target_row.get("target_max"))
    if target_min is None and target_max is None:
      continue
    quarter_aggregation = _clean_text(target_row.get("quarter_aggregation")) or "per_quarter"
    gate_kind = _clean_text(target_row.get("gate_kind")) or "warn"

    if quarter_aggregation == "per_quarter":
      series = _produced_metric_series(finmo_json=finmo, metric_key=metric_key)
      for idx, produced in enumerate(series):
        if produced is None:
          continue
        if _value_is_within_target(
          produced=produced,
          target_min=target_min,
          target_max=target_max,
          numeric_tolerance=numeric_tolerance,
        ):
          continue
        violations.append({
          "metric_key": metric_key,
          "quarter_index": idx + 1,
          "produced": round(float(produced), 6),
          "target_min": target_min,
          "target_max": target_max,
          "residual": _residual(produced=produced, target_min=target_min, target_max=target_max),
          "gate_kind": gate_kind,
        })
    else:
      aggregate = _safe_float((finmo.get("year_one_summary") or {}).get(metric_key))
      if aggregate is None:
        aggregate = _safe_float((finmo.get("aggregates") or {}).get(metric_key))
      if aggregate is None:
        continue
      if _value_is_within_target(
        produced=aggregate,
        target_min=target_min,
        target_max=target_max,
        numeric_tolerance=numeric_tolerance,
      ):
        continue
      violations.append({
        "metric_key": metric_key,
        "quarter_index": None,
        "quarter_aggregation": quarter_aggregation,
        "produced": round(float(aggregate), 6),
        "target_min": target_min,
        "target_max": target_max,
        "residual": _residual(produced=aggregate, target_min=target_min, target_max=target_max),
        "gate_kind": gate_kind,
      })

  # Pinned-driver detection over the envelope, when provided.
  drivers = (envelope.get("drivers") or {}) if isinstance(envelope.get("drivers"), dict) else {}
  if drivers:
    for lever_id, entry in drivers.items():
      if not isinstance(entry, dict) or not entry.get("applicable"):
        continue
      mn = _safe_float(entry.get("min_allowed"))
      mx = _safe_float(entry.get("max_allowed"))
      cur = _safe_float(entry.get("current_value"))
      if cur is None or mn is None or mx is None:
        continue
      if cur <= mn + numeric_tolerance:
        pinned_drivers.append({
          "lever_id": lever_id,
          "current_value": round(cur, 6),
          "min_allowed": round(mn, 6),
          "max_allowed": round(mx, 6),
          "side": "at_min",
        })
      elif cur >= mx - numeric_tolerance:
        pinned_drivers.append({
          "lever_id": lever_id,
          "current_value": round(cur, 6),
          "min_allowed": round(mn, 6),
          "max_allowed": round(mx, 6),
          "side": "at_max",
        })

  return {
    "status": "ok" if not violations else "residual_violations",
    "checked_metric_count": int(len(metrics)),
    "violations": violations,
    "pinned_drivers": pinned_drivers,
  }
