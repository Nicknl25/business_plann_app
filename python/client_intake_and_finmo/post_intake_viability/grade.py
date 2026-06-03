"""Tier 1 — competitiveness GRADE (Fix #1 spec §3, §5, §6, §7).

Above the gates, the four graded constructs (operating_cash_proxy,
rule_of_40, nwc_intensity, ebitda_ramp) are each scored on TWO axes and
combined stage-dependently:

  LEVEL      direction-oriented percentile vs cohort at the terminal quarter,
             mapped p25-clear / p50-full-credit (§7.2).
  TRAJECTORY gap-closure toward the healthy band by the (age-anchored)
             deadline (primary) + OLS slope momentum (secondary) (§7.4).

Constructs combine via stage weights (policy.STAGE_WEIGHTS) into an overall
Tier-1 score in [0,1]. Multi-component cohort references are combined as
documented COMPOSITE bands (interpretable, not hidden):
  rule_of_40   band = revenue_growth_q (+) ebitda_margin_q          (component-sum)
  nwc_intensity band = current_assets_minus_cash_to_revenue (-)
                       current_liabilities_to_revenue               (extremes-paired diff)
ebitda_ramp has no level percentile (slope construct) — trajectory-only,
converging toward the ebitda_margin_q band.

This is a GRADE, not a viability verdict — gates own non-viability (§3).
No confidence-weighting (§5.2): bands arrive cascade-resolved, used as-is;
unavailable bands drop the construct's level axis rather than faking it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import policy as _policy
from .cohort_bands import HIGHER_BETTER, LOWER_BETTER
from .constructs import (
  _OP_CA_FIELDS,
  _OP_CL_FIELDS,
  _f,
  _ols_slope,
  live_quarter_rows,
  nwc_intensity_series,
  operating_cash_proxy_series,
  rule_of_40_series,
)


# ---------------------------------------------------------------------------
# Health-percentile + score primitives.
# ---------------------------------------------------------------------------
def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
  return max(lo, min(hi, x))


def _health_percentile(
  v: Optional[float], p25: Optional[float], p50: Optional[float], p75: Optional[float],
  direction: str,
) -> Optional[float]:
  """Where v sits in the cohort, as a HEALTH fraction in [0,1] (1 = healthier
  than all peers). Piecewise-linear through (p25->.25, p50->.50, p75->.75),
  extrapolated and clamped; flipped for lower-better metrics."""
  if v is None or p25 is None or p50 is None or p75 is None:
    return None
  if v <= p50:
    rp = 0.25 + 0.25 * ((v - p25) / (p50 - p25)) if p50 > p25 else (0.5 if v >= p50 else 0.0)
  else:
    rp = 0.50 + 0.25 * ((v - p50) / (p75 - p50)) if p75 > p50 else 0.5
  rp = _clamp(rp)
  if direction == LOWER_BETTER:
    rp = 1.0 - rp
  return rp


def _level_score_from_health(hp: Optional[float]) -> Optional[float]:
  """Map a health percentile to a level score with the p25-clear /
  p50-full-credit rule (§7.2)."""
  if hp is None:
    return None
  clear = _policy.CLEAR_HEALTH
  full = _policy.FULL_CREDIT_HEALTH
  if hp >= full:
    return 1.0
  if hp >= clear:
    return 0.5 + 0.5 * (hp - clear) / (full - clear)
  return 0.5 * (hp / clear) if clear > 0 else 0.0


def _dir_sign(direction: str) -> float:
  return -1.0 if direction == LOWER_BETTER else 1.0


# ---------------------------------------------------------------------------
# Composite cohort bands (documented in module docstring).
# ---------------------------------------------------------------------------
def _band_sum(b1: Dict[str, Any], b2: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  if not (b1.get("available") and b2.get("available")):
    return None
  return {
    "p25": b1["p25"] + b2["p25"],
    "p50": b1["p50"] + b2["p50"],
    "p75": b1["p75"] + b2["p75"],
    "direction": HIGHER_BETTER,
  }


def _band_diff_extremes(b_ca: Dict[str, Any], b_cl: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  """NWC-intensity band = CA-intensity (-) CL-intensity, pairing extremes so
  the lowest (healthiest) NWC uses low CA and high CL."""
  if not (b_ca.get("available") and b_cl.get("available")):
    return None
  return {
    "p25": b_ca["p25"] - b_cl["p75"],   # lowest NWC intensity (healthiest)
    "p50": b_ca["p50"] - b_cl["p50"],
    "p75": b_ca["p75"] - b_cl["p25"],   # highest NWC intensity (worst)
    "direction": LOWER_BETTER,
  }


# ---------------------------------------------------------------------------
# Per-construct firm series extraction.
# ---------------------------------------------------------------------------
def _series_values(series: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
  """[{quarter_index, value}] dropping None values, sorted by quarter."""
  out = [{"quarter_index": x["quarter_index"], "value": x.get(key)} for x in series]
  return [x for x in out if x["value"] is not None]


def _ca_cl_intensity_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out: List[Dict[str, Any]] = []
  for r in rows:
    rev = _f(r.get("revenue"))
    if rev in (None, 0.0):
      continue
    ca = sum((_f(r.get(k)) or 0.0) for k in _OP_CA_FIELDS)
    cl = sum((_f(r.get(k)) or 0.0) for k in _OP_CL_FIELDS)
    have_ca = any(r.get(k) is not None for k in _OP_CA_FIELDS)
    have_cl = any(r.get(k) is not None for k in _OP_CL_FIELDS)
    out.append({
      "quarter_index": int(_f(r.get("quarter_index")) or 0),
      "ca_intensity": (ca / rev) if have_ca else None,
      "cl_intensity": (cl / rev) if have_cl else None,
    })
  return out


# ---------------------------------------------------------------------------
# Axis scorers.
# ---------------------------------------------------------------------------
def _value_at_or_before(series: List[Dict[str, Any]], deadline_q: int) -> Optional[float]:
  cand = [x for x in series if x["quarter_index"] <= deadline_q]
  pool = cand if cand else series
  return pool[-1]["value"] if pool else None


def _terminal_value(series: List[Dict[str, Any]]) -> Optional[float]:
  return series[-1]["value"] if series else None


def _level_score(series: List[Dict[str, Any]], band: Optional[Dict[str, Any]]) -> Optional[float]:
  if not band:
    return None
  v = _terminal_value(series)
  hp = _health_percentile(v, band.get("p25"), band.get("p50"), band.get("p75"), band.get("direction"))
  return _level_score_from_health(hp)


def _trajectory_score(
  series: List[Dict[str, Any]], band: Optional[Dict[str, Any]], *,
  deadline_q: int, distress: bool,
) -> Optional[float]:
  if not band or len(series) < 1:
    return None
  direction = band.get("direction", HIGHER_BETTER)
  target = _policy.FULL_CREDIT_HEALTH - (_policy.DISTRESS_CONVERGENCE_RELAX if distress else 0.0)
  target = max(_policy.CLEAR_HEALTH, target)

  hp_start = _health_percentile(series[0]["value"], band.get("p25"), band.get("p50"), band.get("p75"), direction)
  hp_end = _health_percentile(_value_at_or_before(series, deadline_q), band.get("p25"), band.get("p50"), band.get("p75"), direction)

  gap_closure: Optional[float]
  if hp_start is None or hp_end is None:
    gap_closure = None
  elif hp_start >= target:
    gap_closure = 1.0  # already healthy at the start
  else:
    gap_closure = _clamp((hp_end - hp_start) / (target - hp_start))

  # Momentum: OLS slope of the raw series, oriented by direction.
  xs = [float(x["quarter_index"]) for x in series]
  ys = [float(x["value"]) for x in series]
  slope = _ols_slope(xs, ys)
  if slope is None:
    slope_score = 0.5
  else:
    oriented = slope * _dir_sign(direction)
    slope_score = 1.0 if oriented > 1e-12 else (0.0 if oriented < -1e-12 else 0.5)

  gw, sw = _policy.TRAJECTORY_GAP_WEIGHT, _policy.TRAJECTORY_SLOPE_WEIGHT
  if gap_closure is None:
    return slope_score  # only momentum available
  return gw * gap_closure + sw * slope_score


# ---------------------------------------------------------------------------
# Top-level grade.
# ---------------------------------------------------------------------------
def grade(
  finmo_json: Optional[Dict[str, Any]],
  bands: Dict[str, Dict[str, Any]],
  *,
  stage: str,
  deadline_plan_q: int,
  distress: bool = False,
) -> Dict[str, Any]:
  """Compute the Tier-1 competitiveness grade. Returns per-construct level/
  trajectory/combined scores plus the stage-weighted overall in [0,1].

  `bands` is the resolve_viability_bands(...) output. `stage` is age-derived
  (Unit 2); `deadline_plan_q` is the Gate-A age-anchored deadline (Unit 5).
  """
  rows = live_quarter_rows(finmo_json)
  emq = bands.get("ebitda_margin_q", {"available": False})
  rgq = bands.get("revenue_growth_q", {"available": False})
  ca_band = bands.get("current_assets_minus_cash_to_revenue", {"available": False})
  cl_band = bands.get("current_liabilities_to_revenue", {"available": False})

  # Firm series per construct.
  c1_series = _series_values(operating_cash_proxy_series(rows), "margin")
  c2_series = _series_values(rule_of_40_series(rows), "rule_of_40")
  c3_series = _series_values(nwc_intensity_series(rows), "nwc_to_revenue")
  # ebitda margin series (for C4 trajectory) from rule_of_40 series component.
  c4_series = _series_values(rule_of_40_series(rows), "ebitda_margin")

  # Construct reference bands.
  c1_band = emq if emq.get("available") else None
  c2_band = _band_sum(rgq, emq)
  c3_band = _band_diff_extremes(ca_band, cl_band)
  c4_band = emq if emq.get("available") else None

  split = _policy.STAGE_LEVEL_TRAJECTORY_SPLIT.get(stage, _policy.STAGE_LEVEL_TRAJECTORY_SPLIT["operational"])
  lw, tw = split[0], split[1]

  def _combine(level: Optional[float], traj: Optional[float]) -> Optional[float]:
    if level is None and traj is None:
      return None
    if level is None:
      return traj
    if traj is None:
      return level
    return lw * level + tw * traj

  per_construct: Dict[str, Any] = {}
  specs = [
    ("operating_cash_proxy", c1_series, c1_band, True),
    ("rule_of_40", c2_series, c2_band, True),
    ("nwc_intensity", c3_series, c3_band, True),
    ("ebitda_ramp", c4_series, c4_band, False),  # trajectory-only (no level percentile)
  ]
  for name, series, band, has_level in specs:
    level = _level_score(series, band) if has_level else None
    traj = _trajectory_score(series, band, deadline_q=deadline_plan_q, distress=distress)
    combined = _combine(level, traj)
    per_construct[name] = {
      "level_score": level,
      "trajectory_score": traj,
      "combined": combined,
      "band_available": bool(band),
      "band_naics_level": (
        bands.get(_first_ref(name), {}).get("naics_level_used")
        if _first_ref(name) else None
      ),
    }

  # Stage-weighted overall over constructs that produced a combined score.
  weights = _policy.STAGE_WEIGHTS.get(stage, _policy.STAGE_WEIGHTS["operational"])
  num = 0.0
  den = 0.0
  for name, res in per_construct.items():
    if res["combined"] is None:
      continue
    w = float(weights.get(name, 1.0))
    num += w * res["combined"]
    den += w
  overall = (num / den) if den > 0 else None

  return {
    "stage": stage,
    "deadline_plan_q": deadline_plan_q,
    "distress_applied": bool(distress),
    "level_trajectory_split": [lw, tw],
    "per_construct": per_construct,
    "overall_score": overall,
    "scored_construct_count": int(den > 0) and sum(1 for r in per_construct.values() if r["combined"] is not None),
  }


def _first_ref(construct: str) -> Optional[str]:
  from .cohort_bands import CONSTRUCT_COHORT_REFERENCES
  refs = CONSTRUCT_COHORT_REFERENCES.get(construct) or []
  return refs[0] if refs else None
