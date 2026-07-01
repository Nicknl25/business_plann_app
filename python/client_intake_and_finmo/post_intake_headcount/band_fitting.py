"""Band-fitting transform: fit industry bands to a specific business.

THE KEYSTONE. The cascade, the executive, and the realism gate all aim levers
at industry bands sourced from ``assemble_finmo_output_targets`` (the cohort
table is empty for SMB NAICS). Those bands have the right SHAPE but the wrong
SCALE for a specific business, so "move toward the band" could mean "move away
from viable" (a law firm driven toward 74% R&D). This transform produces
business-fitted, per-quarter, step-changed bands so that aiming at the band
finally means aiming at viable.

Design (settled with Nick):
  - Revenue is the scaling anchor; ratio metrics scale to the business's
    reachable revenue. (The industry envelope itself is resolved cohort-matched
    to target revenue when a business_profile is supplied to the assembler.)
  - GPT AUTHORS the per-quarter step trajectory per metric from the compact
    (gpt_band_author); PYTHON VALIDATES against the scaled industry envelope and
    the HARD Q11 net-income rule (>=0 by Q11, non-negative thereafter; loss-
    tolerant early but provably climbing).
  - Bands are fitted BEFORE anything downstream consumes them.

Same author/validate split as revenue authoring. On no-key / GPT failure the
pass returns ok=False and the caller keeps the raw industry bands.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_headcount.gpt_band_author import (  # type: ignore
  BAND_METRIC_KEYS,
)

_HORIZON = 20
_Q11 = 11
# Cost-ratio metrics step DOWN toward viability; net_income_margin steps UP.
_COST_RATIO_KEYS = (
  "cogs_percent_of_revenue",
  "marketing_percent_of_revenue",
  "sga_percent_of_revenue",
  "r_and_d_percent_of_revenue",
)
# Viability-spine margins: loss-tolerant early, non-decreasing through Q11 and
# >= 0 from Q11 (the hard Q11 net-income rule). EBITDA margin tracks the same
# spine (it is always >= net income in a quarter).
_NI_KEY = "net_income_margin"
_VIABILITY_SPINE_KEYS = ("net_income_margin", "ebitda_margin")


def _f(v: Any) -> Optional[float]:
  try:
    return float(v)
  except (TypeError, ValueError):
    return None


def industry_envelope_from_targets(targets_payload: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
  """Extract the per-metric {min,target,max} envelope from an
  assemble_finmo_output_targets payload, restricted to the band metrics."""
  metrics = (targets_payload or {}).get("metrics") or {}
  envelope: Dict[str, Dict[str, float]] = {}
  for key in BAND_METRIC_KEYS:
    row = metrics.get(key)
    if not isinstance(row, dict):
      continue
    lo = _f(row.get("target_min"))
    tgt = _f(row.get("target_target"))
    hi = _f(row.get("target_max"))
    entry: Dict[str, float] = {}
    if lo is not None:
      entry["min"] = lo
    if tgt is not None:
      entry["target"] = tgt
    if hi is not None:
      entry["max"] = hi
    if entry:
      envelope[key] = entry
  return envelope


# Operator-filled financials -> the LEVEL this specific business runs each cost
# line at. The cohort gives the SHAPE (relative spread / trajectory); these give
# the LEVEL. A $1M dental office is not a hospital system, so a hospital cohort's
# raw levels must be scaled to the operator's reality -- floor included.
def operator_cost_levels(
  financials_json: Optional[Dict[str, Any]],
  revenue_year1: Optional[float],
) -> Dict[str, float]:
  """Per-metric cost LEVELS (fraction of revenue) from the operator's filled
  financials, for the metrics a human authors. Empty when nothing is fillable."""
  fin = financials_json if isinstance(financials_json, dict) else {}
  rev = _f(revenue_year1)
  levels: Dict[str, float] = {}

  cogs = _f(fin.get("cogs_percent_of_revenue"))
  if cogs is None and rev:
    c = _f(fin.get("cogs_total_year1"))
    if c is None:
      c = _f(fin.get("current_cogs"))
    if c is not None:
      cogs = c / rev
  if cogs is not None and cogs >= 0:
    levels["cogs_percent_of_revenue"] = cogs

  mkp = _f(fin.get("marketing_percent_of_revenue"))
  if mkp is None and rev:
    mk = _f(fin.get("marketing_total_year1"))
    if mk is None:
      mk = _f(fin.get("baseline_marketing"))
    if mk is not None:
      mkp = mk / rev
  if mkp is not None and mkp >= 0:
    levels["marketing_percent_of_revenue"] = mkp

  if rev:
    ga = _f(fin.get("other_operating_expense"))
    if ga is None:
      ga = _f(fin.get("other_opex_absolute"))
    if ga is not None and ga >= 0:
      levels["sga_percent_of_revenue"] = ga / rev
  return levels


def rescale_envelope_to_operator(
  envelope: Dict[str, Dict[str, float]],
  operator_levels: Dict[str, float],
) -> Dict[str, Dict[str, float]]:
  """Proportional band-scaling: keep the cohort SHAPE, move the LEVEL to the
  operator's reality. For each metric the operator filled, anchor the target to
  the operator level and scale the floor AND ceiling by the same factor so the
  relative spread (the cohort's shape) is preserved. This frees a small private
  business from being floored at a large-public-company's minimum -- the whole
  envelope (min/target/max) shifts to the business's scale, not just the target.
  Metrics with no operator anchor keep the raw cohort band."""
  out: Dict[str, Dict[str, float]] = {}
  for metric, band in (envelope or {}).items():
    lvl = operator_levels.get(metric) if operator_levels else None
    tgt = _f(band.get("target"))
    if lvl is not None and tgt is not None and tgt > 1e-9 and lvl >= 0:
      scale = lvl / tgt
      nb: Dict[str, float] = {"target": lvl}
      mn = _f(band.get("min"))
      mx = _f(band.get("max"))
      if mn is not None:
        nb["min"] = max(0.0, mn * scale)
      if mx is not None:
        nb["max"] = max(nb.get("min", 0.0), mx * scale)
      out[metric] = nb
    else:
      out[metric] = dict(band)
  return out


# Maps the model_input expense-row labels to the fitted-band metric keys. The
# fitted bands are the cohort envelope rescaled to THIS operator's level; writing
# them onto the actual cost rows is what makes a viable plan REAL -- the plan's
# actual costs and the targets it aims at finally agree, instead of the actuals
# sitting at cohort scale while the targets sit at operator scale (an unclosable
# gap no amount of lever-moving can fix).
FITTED_BAND_ROW_LABEL_TO_METRIC = {
  "Cost of Goods Sold": "cogs_percent_of_revenue",
  "Marketing": "marketing_percent_of_revenue",
  "General & Administrative": "sga_percent_of_revenue",
  "Research & Development": "r_and_d_percent_of_revenue",
}


def apply_fitted_cost_bands_to_model_input(
  model_input: Optional[Dict[str, Any]],
  fitted_bands: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
  """Write the fitted (operator-rescaled) per-quarter cost ratios onto the
  model_input expense-ratio rows, in place.

  ``fitted_bands`` is ``{metric_key: {quarter: ratio}}`` (quarter keys may be
  int or str) as produced by the band-fitting pass. Only ratio-kind rows whose
  label maps to a fitted cost metric are touched; every other row -- and any run
  where band-fitting produced no bands -- is left exactly as-is. Universal: this
  is the same grounding every real intake run gets, independent of any harness."""
  if not isinstance(model_input, dict) or not isinstance(fitted_bands, dict) or not fitted_bands:
    return model_input
  rows = (model_input.get("sections") or {}).get("expenses") or []
  if not isinstance(rows, list):
    return model_input
  for row in rows:
    if not isinstance(row, dict):
      continue
    metric = FITTED_BAND_ROW_LABEL_TO_METRIC.get(str(row.get("label") or ""))
    if not metric:
      continue
    if str(row.get("value_kind") or "").strip().lower() != "ratio":
      continue
    traj = fitted_bands.get(metric)
    if not isinstance(traj, dict) or not traj:
      continue
    values = row.get("values")
    if not isinstance(values, list) or not values:
      continue
    for q in range(1, len(values)):
      ratio = traj.get(q, traj.get(str(q)))
      if ratio is None:
        continue
      try:
        values[q] = max(0.0, float(ratio))
      except (TypeError, ValueError):
        continue
  return model_input


def normalize_band_trajectories(bands: Any) -> Dict[str, Dict[int, float]]:
  """GPT band output -> {metric_key: {q (1..20): value}}, forward/backward filled."""
  out: Dict[str, Dict[int, float]] = {}
  if not isinstance(bands, list):
    return out
  for entry in bands:
    if not isinstance(entry, dict):
      continue
    key = str(entry.get("metric_key") or "").strip()
    if key not in BAND_METRIC_KEYS:
      continue
    by_q: Dict[int, float] = {}
    for row in entry.get("quarters") or []:
      if not isinstance(row, dict):
        continue
      try:
        q = int(row.get("q"))
      except (TypeError, ValueError):
        continue
      val = _f(row.get("value"))
      if 1 <= q <= _HORIZON and val is not None:
        by_q[q] = val
    if not by_q:
      continue
    # forward fill, then backfill any leading gap
    filled: Dict[int, float] = {}
    last: Optional[float] = None
    for q in range(1, _HORIZON + 1):
      if q in by_q:
        last = by_q[q]
      if last is not None:
        filled[q] = last
    first = next((q for q in range(1, _HORIZON + 1) if q in filled), None)
    if first is not None:
      for q in range(1, first):
        filled[q] = filled[first]
    if filled:
      out[key] = filled
  return out


def validate_and_clip(
  normalized: Dict[str, Dict[int, float]],
  envelope: Dict[str, Dict[str, float]],
) -> Tuple[Dict[str, Dict[int, float]], List[Dict[str, Any]]]:
  """Enforce the bounds GPT must author within:
    - every quarter value clipped to its metric's [min, max] envelope
    - cost ratios are non-increasing (step DOWN toward viability)
    - net_income_margin is non-decreasing through Q11 (provably climbing),
      and >= 0 for Q11..Q20 (the hard Q11 net-income rule)
  Returns (fitted, violations). Violations describe what GPT must fix on retry;
  the returned `fitted` is always bound-safe (Python enforces regardless)."""
  fitted: Dict[str, Dict[int, float]] = {}
  violations: List[Dict[str, Any]] = []

  for key in BAND_METRIC_KEYS:
    traj = normalized.get(key)
    if not traj:
      continue
    env = envelope.get(key) or {}
    lo = env.get("min")
    hi = env.get("max")
    series: Dict[int, float] = {}
    for q in range(1, _HORIZON + 1):
      v = traj.get(q)
      if v is None:
        continue
      clipped = v
      if lo is not None:
        clipped = max(clipped, lo)
      if hi is not None:
        clipped = min(clipped, hi)
      if abs(clipped - v) > 1e-9:
        violations.append({"metric_key": key, "q": q, "code": "outside_envelope",
                           "authored": v, "envelope": [lo, hi]})
      series[q] = clipped

    if key in _COST_RATIO_KEYS:
      # non-increasing: a cost ratio may step down but not climb back up
      prev: Optional[float] = None
      for q in range(1, _HORIZON + 1):
        if q not in series:
          continue
        if prev is not None and series[q] > prev + 1e-9:
          violations.append({"metric_key": key, "q": q, "code": "cost_ratio_increased",
                             "value": series[q], "prev": prev})
          series[q] = prev
        prev = series[q]
    elif key in _VIABILITY_SPINE_KEYS:
      # non-decreasing through Q11 (climbing into the checkpoint)
      prev = None
      for q in range(1, _Q11 + 1):
        if q not in series:
          continue
        if prev is not None and series[q] < prev - 1e-9:
          violations.append({"metric_key": key, "q": q, "code": "ni_not_climbing_to_q11",
                             "value": series[q], "prev": prev})
          series[q] = prev
        prev = series[q]
      # hard Q11 rule: >= 0 from Q11 onward, and non-decreasing floor afterward
      ni_floor_after = 0.0
      for q in range(_Q11, _HORIZON + 1):
        if q not in series:
          continue
        if series[q] < ni_floor_after - 1e-9:
          violations.append({"metric_key": key, "q": q, "code": "ni_negative_after_q11",
                             "value": series[q]})
          series[q] = ni_floor_after
        ni_floor_after = max(ni_floor_after, series[q])
    fitted[key] = series
  return fitted, violations


def run_band_fitting_pass(
  *,
  compact: Dict[str, Any],
  revenue_line: List[float],
  targets_payload: Dict[str, Any],
  operator_levels: Optional[Dict[str, float]] = None,
  model: Optional[str] = None,
  max_attempts: int = 2,
  _author_fn=None,
) -> Dict[str, Any]:
  """Fit the industry bands to this business. Returns
  ``{ok, fitted_bands, envelope, operator_levels, violations_resolved,
  raw_targets, error}``. ``fitted_bands`` is ``{metric_key: {q: value}}``
  (per-quarter). ok=False -> caller keeps the raw industry bands unchanged."""
  envelope = industry_envelope_from_targets(targets_payload)
  if not envelope:
    return {"ok": False, "fitted_bands": None, "envelope": {}, "error": "no_industry_envelope"}

  # PROPORTIONAL BAND-SCALING: rescale the WHOLE envelope (floor/target/max) to
  # the operator's real level, keeping the cohort's shape. Without this, a small
  # private business is floored at a large-public-company cohort's minimum and
  # the cascade is trapped above its real economics by construction.
  raw_envelope = {k: dict(v) for k, v in envelope.items()}
  if operator_levels:
    envelope = rescale_envelope_to_operator(envelope, operator_levels)

  author_fn = _author_fn
  if author_fn is None:
    from client_intake_and_finmo.post_intake_headcount.gpt_band_author import (  # type: ignore
      gpt_author_fitted_bands_once,
    )
    author_fn = gpt_author_fitted_bands_once

  previous_violations: Optional[List[Dict[str, Any]]] = None
  last_error: Optional[str] = None
  for _attempt in range(max(1, int(max_attempts))):
    result = author_fn(
      compact=compact,
      revenue_line=revenue_line,
      industry_envelope=envelope,
      previous_violations=previous_violations,
      model=model,
    )
    if not result.get("ok"):
      last_error = result.get("error")
      break
    normalized = normalize_band_trajectories(result.get("bands"))
    if not normalized:
      previous_violations = [{"code": "no_metrics", "message": "author all metrics x 20 quarters."}]
      last_error = "no_metrics_authored"
      continue
    fitted, violations = validate_and_clip(normalized, envelope)
    # Python has already enforced the bounds in `fitted`; surface violations so
    # GPT can re-author a shape that does not need clamping, but the fitted
    # bands are always returned bound-safe.
    return {
      "ok": True,
      "fitted_bands": fitted,
      "envelope": envelope,
      "raw_envelope": raw_envelope,
      "operator_levels": operator_levels or {},
      "violations_resolved": violations,
      "raw_targets": targets_payload,
      "error": None,
    }
  return {
    "ok": False,
    "fitted_bands": None,
    "envelope": envelope,
    "error": last_error or "band_fitting_failed",
  }


__all__ = [
  "run_band_fitting_pass",
  "industry_envelope_from_targets",
  "normalize_band_trajectories",
  "validate_and_clip",
]
