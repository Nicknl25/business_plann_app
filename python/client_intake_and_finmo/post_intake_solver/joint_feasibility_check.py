"""Phase 5.2 — Pre-solver joint feasibility check.

Verifies that the calibrated driver bands and output-target ranges admit
at least one feasible solution before invoking the solver. Catches the
"no editable cells" / "all targets unreachable from this envelope"
failure modes at a structured gate, not after the solver has spent
seconds searching.

Fast: sub-second runtime. Two checks:

  1. Direct-governance check — for each output metric whose realism row
     declares ``governs_model_input_lever_id``, the metric value is the
     governing lever's value (e.g., metric cogs_percent_of_revenue is
     governed by lever expenses::Cost of Goods Sold; the lever value
     IS the cogs ratio at quarter granularity). Feasibility for that
     metric reduces to [lever_min, lever_max] ∩ [target_min, target_max] ≠ ∅.
     This catches the specific failure mode that bit Sunny Glaze: a band
     collapsed to [0, 0] for an applicable=false lever cannot produce a
     non-zero target.

  2. Editable-budget check — count the levers that have a non-degenerate
     band (min < max strictly, applicable=true, not schedule-locked).
     The convergence solver requires a minimum number of editable cells
     to operate within. Empty-or-near-empty editable surface is the
     "no editable cells" upstream failure made deterministic and visible
     before the solver runs.

Returns a FeasibilityResult dataclass plus a per-metric / per-lever
diagnostic. The orchestrator forwards an infeasibility into the
adaptation cascade's pre-solver tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_MIN_EDITABLE_LEVERS_DEFAULT = 4


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


@dataclass
class FeasibilityResult:
  feasible: bool
  unreachable_metrics: List[Dict[str, Any]] = field(default_factory=list)
  collapsed_levers: List[Dict[str, Any]] = field(default_factory=list)
  editable_lever_count: int = 0
  total_lever_count: int = 0
  applicable_lever_count: int = 0
  diagnostic_message: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "feasible": bool(self.feasible),
      "unreachable_metrics": list(self.unreachable_metrics),
      "collapsed_levers": list(self.collapsed_levers),
      "editable_lever_count": int(self.editable_lever_count),
      "applicable_lever_count": int(self.applicable_lever_count),
      "total_lever_count": int(self.total_lever_count),
      "diagnostic_message": _clean_text(self.diagnostic_message),
    }


def _interval_overlaps(
  a_min: float, a_max: float, b_min: float, b_max: float,
) -> bool:
  return max(a_min, b_min) <= min(a_max, b_max)


def verify_joint_feasibility(
  *,
  envelope_payload: Optional[Dict[str, Any]],
  targets_payload: Optional[Dict[str, Any]],
  business_profile: Optional[Dict[str, Any]] = None,
  min_editable_levers: int = _MIN_EDITABLE_LEVERS_DEFAULT,
) -> FeasibilityResult:
  """Cheap joint-feasibility test on (envelope, targets).

  Runs both checks; returns feasible=False on the first violation that
  would deterministically prevent the solver from landing. Caller (the
  orchestrator) forwards the diagnostic into the adaptation cascade.
  """
  envelope = envelope_payload if isinstance(envelope_payload, dict) else {}
  targets = targets_payload if isinstance(targets_payload, dict) else {}
  drivers = envelope.get("drivers") if isinstance(envelope.get("drivers"), dict) else {}
  metrics = targets.get("metrics") if isinstance(targets.get("metrics"), dict) else {}
  _ = business_profile  # accepted for forward compatibility; not needed today

  total_lever_count = sum(1 for k in drivers.keys())
  applicable_lever_count = 0
  editable_lever_count = 0
  collapsed_levers: List[Dict[str, Any]] = []

  for lever_id, entry in drivers.items():
    if not isinstance(entry, dict):
      continue
    if not bool(entry.get("applicable")):
      continue
    applicable_lever_count += 1
    if bool(entry.get("schedule_locked")):
      continue
    mn = _safe_float(entry.get("min_allowed"))
    mx = _safe_float(entry.get("max_allowed"))
    if mn is None or mx is None:
      continue
    if mx > mn:
      editable_lever_count += 1
    else:
      collapsed_levers.append({
        "lever_id": lever_id,
        "min_allowed": mn, "max_allowed": mx,
        "default_value": _safe_float(entry.get("default_value")),
        "calibration_source": (entry.get("provenance") or {}).get("calibration_source"),
      })

  unreachable: List[Dict[str, Any]] = []
  for metric_key, metric_entry in metrics.items():
    if not isinstance(metric_entry, dict):
      continue
    governs_lever = _clean_text(metric_entry.get("governs_model_input_lever_id"))
    if not governs_lever:
      continue
    target_min = _safe_float(metric_entry.get("target_min"))
    target_max = _safe_float(metric_entry.get("target_max"))
    if target_min is None or target_max is None:
      continue
    lever_entry = drivers.get(governs_lever)
    if not isinstance(lever_entry, dict):
      continue
    lever_applicable = bool(lever_entry.get("applicable"))
    lever_min = _safe_float(lever_entry.get("min_allowed"))
    lever_max = _safe_float(lever_entry.get("max_allowed"))
    if lever_min is None or lever_max is None:
      continue
    if not lever_applicable and not _interval_overlaps(0.0, 0.0, target_min, target_max):
      unreachable.append({
        "metric_key": metric_key,
        "governs_lever_id": governs_lever,
        "target_range": [target_min, target_max],
        "reachable_range": [0.0, 0.0],
        "reason": "lever_marked_not_applicable_but_target_excludes_zero",
      })
      continue
    if lever_applicable and not _interval_overlaps(lever_min, lever_max, target_min, target_max):
      unreachable.append({
        "metric_key": metric_key,
        "governs_lever_id": governs_lever,
        "target_range": [target_min, target_max],
        "reachable_range": [lever_min, lever_max],
        "reason": "lever_band_disjoint_from_target_range",
      })

  feasible = (
    not unreachable
    and editable_lever_count >= int(min_editable_levers)
  )
  message = ""
  if unreachable:
    message = (
      f"{len(unreachable)} target metric(s) unreachable from calibrated bands"
    )
  elif editable_lever_count < int(min_editable_levers):
    message = (
      f"editable_lever_count={editable_lever_count} < required minimum "
      f"{int(min_editable_levers)}"
    )

  return FeasibilityResult(
    feasible=feasible,
    unreachable_metrics=unreachable,
    collapsed_levers=collapsed_levers,
    editable_lever_count=editable_lever_count,
    applicable_lever_count=applicable_lever_count,
    total_lever_count=total_lever_count,
    diagnostic_message=message,
  )
