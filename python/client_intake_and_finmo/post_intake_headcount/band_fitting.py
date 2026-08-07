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
# The viability search may FINE-TUNE a cost line at most this far (relative)
# from the manager's defended path -- and only at the far end of the horizon
# (the corridor scales linearly from zero width at Q1). Larger deviations are
# a different plan and belong to the manager's judgment, not the solver.
_MAX_SEARCH_DEVIATION = 0.10


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
    # other_opex_absolute is the ANNUAL figure (intake derives it as monthly x 12);
    # other_operating_expense itself is MONTHLY, so a legacy draft without the
    # annual field must be annualized here or the SGA anchor lands ~12x too low
    # (annual revenue in the denominator).
    ga = _f(fin.get("other_opex_absolute"))
    if ga is None:
      ga_monthly = _f(fin.get("other_operating_expense"))
      if ga_monthly is not None:
        ga = ga_monthly * 12.0
    if ga is not None and ga >= 0:
      levels["sga_percent_of_revenue"] = ga / rev
  return levels


def rescale_envelope_to_operator(
  envelope: Dict[str, Dict[str, float]],
  operator_levels: Dict[str, float],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
  """Proportional band-scaling: keep the cohort SHAPE, move the LEVEL to the
  operator's reality. For each metric the operator filled, anchor the target to
  the operator level and scale the floor AND ceiling by the same factor so the
  relative spread (the cohort's shape) is preserved. This frees a small private
  business from being floored at a large-public-company's minimum -- the whole
  envelope (min/target/max) shifts to the business's scale, not just the target.
  Metrics with no operator anchor keep the raw cohort band.

  DEGENERATE-ANCHOR SANITY GUARD: bounds are only as real as their anchors. An
  operator anchor so far from the cohort that the RESCALED band no longer even
  OVERLAPS the raw cohort band contradicts every business the cohort has seen
  (Luna: $1,200/yr opex -> a 0.07-0.18% SGA band no retailer on earth runs at).
  The credibility test is derived from the cohort's own spread -- no tuned
  threshold. Low-side degeneracy (the viability-manufacturing direction) falls
  back to the raw cohort band; high-side (operator spends MORE than the cohort
  ceiling -- conservative, lender-believable) keeps the operator level and is
  flagged only. Returns ``(rescaled_envelope, degenerate_anchors)`` where
  ``degenerate_anchors`` is ``{metric: {operator_level, cohort_min, cohort_max,
  side, action}}``."""
  out: Dict[str, Dict[str, float]] = {}
  degenerate: Dict[str, Dict[str, Any]] = {}
  for metric, band in (envelope or {}).items():
    lvl = operator_levels.get(metric) if operator_levels else None
    tgt = _f(band.get("target"))
    if lvl is not None and tgt is not None and tgt > 1e-9 and lvl >= 0:
      scale = lvl / tgt
      mn = _f(band.get("min"))
      mx = _f(band.get("max"))
      if (
        mn is not None and mx is not None
        and mn > 1e-12 and mx >= mn
        and (mx * scale) < mn
      ):
        # Rescaled band sits entirely BELOW the cohort floor. RULED
        # (CW-017 informant-authority, Nick 2026-08-07): a client's
        # stated fact can never be REMOVED by a cohort statistic. The
        # pre-arbitration posture keeps the UNION span - the operator's
        # stated level stays inside the search range (fact preserved,
        # target anchored to it) while the ceiling keeps raw-cohort
        # reach so the search can move costs to realistic levels (the
        # Luna case still cannot manufacture viability: the walk/search
        # answers viability, not the band floor). The executive anchor
        # arbitration then rules within its seat - an explicit "cohort"
        # verdict may still replace the band and mark the fact a data
        # error (the owner's judgment, retained).
        degenerate[metric] = {
          "operator_level": lvl,
          "cohort_min": mn,
          "cohort_max": mx,
          "side": "below_cohort_floor",
          "action": "kept_union_span_fact_preserved",
        }
        out[metric] = {
          "target": lvl,
          "min": max(0.0, min(mn * scale, lvl)),
          "max": mx,
        }
        continue
      if (
        mn is not None and mx is not None
        and mn > 1e-12 and mx >= mn
        and (mn * scale) > mx
      ):
        # Rescaled band sits entirely ABOVE the cohort ceiling. High costs are
        # the conservative direction (they only make viability harder), so the
        # operator's stated reality stands -- but flag it for the trace.
        degenerate[metric] = {
          "operator_level": lvl,
          "cohort_min": mn,
          "cohort_max": mx,
          "side": "above_cohort_ceiling",
          "action": "kept_operator_level",
        }
      nb: Dict[str, float] = {"target": lvl}
      if mn is not None:
        nb["min"] = max(0.0, mn * scale)
      if mx is not None:
        nb["max"] = max(nb.get("min", 0.0), mx * scale)
      out[metric] = nb
    else:
      out[metric] = dict(band)
  return out, degenerate


def _rescale_band_to_level(
  raw_band: Dict[str, Any], level: Optional[float],
) -> Dict[str, float]:
  """Rescale ONE raw cohort band to an arbitrated level, preserving the
  cohort's shape -- the same proportional math as
  ``rescale_envelope_to_operator`` for a single metric."""
  tgt = _f((raw_band or {}).get("target"))
  lvl = _f(level)
  if tgt is None or tgt <= 1e-9 or lvl is None or lvl < 0:
    return dict(raw_band or {})
  scale = lvl / tgt
  nb: Dict[str, float] = {"target": lvl}
  mn = _f(raw_band.get("min"))
  mx = _f(raw_band.get("max"))
  if mn is not None:
    nb["min"] = max(0.0, mn * scale)
  if mx is not None:
    nb["max"] = max(nb.get("min", 0.0), mx * scale)
  return nb


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


def clamp_cost_rows_to_envelope(
  model_input: Optional[Dict[str, Any]],
  fitted_envelope: Optional[Dict[str, Any]],
  fitted_envelope_per_q: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
  """Coherence CLAMP, not an overwrite: keep whatever value the viability
  search chose for each cost row, clamped into the operator-rescaled fitted
  envelope [min, max].

  The fitted bands are SEARCH RANGES. The earlier design stamped the band
  TARGET trajectory onto the cost rows at the end of the pipeline, which
  ERASED the restoration loop's search (Luna: COGS searched down to the band
  minimum 42.8%, then stamped back to the 60-65% target trajectory before the
  gates measured it). Now the target trajectory is stamped only as the
  BASELINE before the search runs; afterwards this clamp guarantees the final
  point still lies inside the defensible band without undoing the search.
  Mutates ``model_input`` in place; returns {row_label: clamped_quarter_count}
  (empty when nothing needed clamping)."""
  clamped: Dict[str, int] = {}
  if not isinstance(model_input, dict) or not isinstance(fitted_envelope, dict) or not fitted_envelope:
    return clamped
  rows = (model_input.get("sections") or {}).get("expenses") or []
  if not isinstance(rows, list):
    return clamped
  for row in rows:
    if not isinstance(row, dict):
      continue
    label = str(row.get("label") or "")
    metric = FITTED_BAND_ROW_LABEL_TO_METRIC.get(label)
    if not metric:
      continue
    if str(row.get("value_kind") or "").strip().lower() != "ratio":
      continue
    band = fitted_envelope.get(metric)
    if not isinstance(band, dict):
      continue
    band_min = _f(band.get("min"))
    band_max = _f(band.get("max"))
    if band_min is None or band_max is None or band_max < band_min:
      continue
    # Per-quarter walls (managerial shaping): when present they take
    # precedence over the flat scalar box, so out-of-range values pin to
    # the MATURING path's wall at that quarter -- not one flat edge that
    # freezes the ratio for five years.
    per_q_band = (fitted_envelope_per_q or {}).get(metric)
    per_q_min = (per_q_band or {}).get("min") if isinstance(per_q_band, dict) else None
    per_q_max = (per_q_band or {}).get("max") if isinstance(per_q_band, dict) else None
    values = row.get("values")
    if not isinstance(values, list) or not values:
      continue
    count = 0
    for q in range(1, len(values)):
      value = _f(values[q])
      if value is None:
        continue
      lo, hi = band_min, band_max
      if isinstance(per_q_min, dict) and isinstance(per_q_max, dict):
        q_lo = _f(per_q_min.get(str(q)))
        q_hi = _f(per_q_max.get(str(q)))
        if q_lo is not None and q_hi is not None and q_hi >= q_lo:
          lo, hi = q_lo, q_hi
      pinned = min(max(value, lo), hi)
      if abs(pinned - value) > 1e-9:
        values[q] = pinned
        count += 1
    if count:
      clamped[label] = count
  return clamped


# The cost metrics that arithmetically compose EBITDA (revenue minus these):
# cogs + marketing + G&A + R&D are the fitted-band cost lines; payroll + rent
# are the plan's own actual per-quarter lines. The engine's EBITDA subtracts
# ALL of them: EBITDA = revenue - cogs - marketing - R&D - G&A - payroll - rent.
# R&D was originally omitted here under the assumption "there is no R&D line
# for these businesses" — true while the executive killed R&D fleet-wide, and
# catastrophically false for the first business with a REAL R&D line (Orion:
# 19% of revenue): the derived band demanded EBITDA >= 33.7% for a P&L the
# derivation pretended had no R&D spend, hard-failing a plan that sat exactly
# ON the manager's own coherent EBITDA forecast (Q11 forecast 22%, actual
# 21.5%). A killed R&D line is absent from the envelope (or zero-width), so
# including the metric costs the no-R&D fleet nothing.
_EBITDA_FITTED_COST_METRICS = (
  "cogs_percent_of_revenue",
  "marketing_percent_of_revenue",
  "sga_percent_of_revenue",
  "r_and_d_percent_of_revenue",
)


def derive_ebitda_margin_band_from_costs(
  fitted_envelope: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  horizon: int = 20,
) -> Optional[Dict[str, float]]:
  """Derive the EBITDA-margin realism band FROM the grounded cost bands + the
  plan's own payroll/rent, instead of judging a derived number (EBITDA) against
  an independent public-cohort band (the two-sources-of-truth bug).

  EBITDA margin = 1 - cogs% - marketing% - G&A% - payroll% - rent%. The banded
  costs (cogs/marketing/G&A) supply their operator-rescaled min/target/max from
  ``fitted_envelope``; payroll% and rent% are the plan's actual per-quarter
  values from ``finmo_json``. The band edges take the cost floors with the
  lightest payroll+rent quarter (max achievable EBITDA) and the cost ceilings
  with the heaviest payroll+rent quarter (min EBITDA), so EVERY quarter's actual
  EBITDA is contained by construction whenever the actual costs sit inside their
  bands. Returns ``{target_min, target_target, target_max}`` (the shape the
  realism gate reads from ``solver_input.finmo_output_targets``) or None when the
  inputs are missing.
  """
  if not isinstance(fitted_envelope, dict) or not isinstance(finmo_json, dict):
    return None
  sum_min = sum_target = sum_max = 0.0
  metrics_used: List[str] = []
  for metric in _EBITDA_FITTED_COST_METRICS:
    band = fitted_envelope.get(metric)
    if not isinstance(band, dict):
      continue
    mn = _f(band.get("min"))
    tg = _f(band.get("target"))
    mx = _f(band.get("max"))
    if mn is None or tg is None or mx is None:
      continue
    sum_min += mn
    sum_target += tg
    sum_max += mx
    metrics_used.append(metric)
  if not metrics_used:
    return None

  rows = finmo_json.get("quarter_rows") or []
  if not isinstance(rows, list) or not rows:
    return None
  payroll_rent_ratios: List[float] = []
  last_q = min(int(horizon or 20), len(rows) - 1)
  for q in range(1, last_q + 1):
    row = rows[q] if q < len(rows) else None
    if not isinstance(row, dict):
      continue
    rev = _f(row.get("revenue"))
    if rev is None or rev <= 0:
      continue
    payroll = _f(row.get("payroll")) or 0.0
    rent = _f(row.get("lease_rent")) or 0.0
    payroll_rent_ratios.append((payroll + rent) / rev)
  if not payroll_rent_ratios:
    return None
  pr_min = min(payroll_rent_ratios)
  pr_max = max(payroll_rent_ratios)
  pr_avg = sum(payroll_rent_ratios) / len(payroll_rent_ratios)

  band_max = 1.0 - sum_min - pr_min   # cost floors + lightest payroll -> most EBITDA
  band_min = 1.0 - sum_max - pr_max   # cost ceilings + heaviest payroll -> least EBITDA
  band_target = 1.0 - sum_target - pr_avg
  # Keep ordering sane even if the envelope is degenerate.
  band_min = min(band_min, band_target, band_max)
  band_max = max(band_min, band_target, band_max)
  return {
    "target_min": band_min,
    "target_target": band_target,
    "target_max": band_max,
    "provenance": {
      "calibration_source": "derived_from_grounded_cost_bands",
      "cost_metrics": metrics_used,
      "payroll_rent_ratio_min": pr_min,
      "payroll_rent_ratio_max": pr_max,
    },
  }



def _interpolate_anchors(q1: float, q11: float, q20: float) -> Dict[int, float]:
  """Linear glide Q1->Q11->Q20: the manager sets the anchors, Python draws
  the smooth deterministic path between them (no free-form 20-point authoring
  to drift run-to-run; smoothness is by construction, not by cap)."""
  series: Dict[int, float] = {}
  for q in range(1, _Q11 + 1):
    frac = (q - 1) / float(_Q11 - 1)
    series[q] = q1 + (q11 - q1) * frac
  for q in range(_Q11 + 1, _HORIZON + 1):
    frac = (q - _Q11) / float(_HORIZON - _Q11)
    series[q] = q11 + (q20 - q11) * frac
  return series


def validate_manager_forecast(
  forecast_rows: Optional[List[Dict[str, Any]]],
  *,
  envelope: Dict[str, Dict[str, float]],
  credible_facts: Dict[str, float],
  judged_margin_band: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Dict[int, float]], Dict[str, bool], List[Dict[str, Any]], Dict[str, str]]:
  """Turn the manager's anchor forecast into per-quarter trajectories,
  enforcing FACTS and hard viability rules -- not cohort boxes.

  Enforced (grounded in place, each logged as a violation for the retry
  prompt):
    - Q1 FACT-GROUNDING: where the operator stated a credible present-day
      level, the manager's Q1 must sit within [0.8, 1.2] x that fact; outside
      it snaps to the fact. Forecasting the future never edits the present.
    - KILL GUARD: a line with a credible stated level > 0 cannot be killed
      (the operator pays it today); the kill is rejected and the line kept.
    - Cost ratios live in [0, 0.95]; killed lines are zero across the horizon.
    - Spine rules (unchanged doctrine): net income climbs into the Q11
      checkpoint (q1 <= q11), q11 >= 0, non-decreasing after (q20 >= q11);
      ebitda >= net income every quarter.

  Returns ``(fitted, applicability, violations, rationales)``."""
  fitted: Dict[str, Dict[int, float]] = {}
  applicability: Dict[str, bool] = {}
  violations: List[Dict[str, Any]] = []
  rationales: Dict[str, str] = {}
  rows_by_metric: Dict[str, Dict[str, Any]] = {}
  for row in (forecast_rows or []):
    if isinstance(row, dict):
      mk = str(row.get("metric_key") or "").strip()
      if mk:
        rows_by_metric[mk] = row

  for metric in BAND_METRIC_KEYS:
    if metric not in envelope:
      continue
    row = rows_by_metric.get(metric)
    if row is None:
      violations.append({
        "metric_key": metric, "code": "metric_missing",
        "message": "forecast every metric listed in the reference bands",
      })
      continue
    q1 = _f(row.get("q1_level"))
    q11 = _f(row.get("q11_level"))
    q20 = _f(row.get("q20_level"))
    if q1 is None or q11 is None or q20 is None:
      violations.append({
        "metric_key": metric, "code": "anchors_missing",
        "message": "q1_level, q11_level and q20_level are all required numbers",
      })
      continue
    rationales[metric] = str(row.get("rationale") or "")[:400]
    applicable = bool(row.get("applicable", True))

    if metric in _COST_RATIO_KEYS:
      fact = credible_facts.get(metric)
      if not applicable:
        if fact is not None and fact > 1e-6:
          violations.append({
            "metric_key": metric, "code": "killed_stated_cost",
            "message": (
              f"the operator reported paying this line today ({fact:.4f} of "
              "revenue); it cannot be killed -- forecast its maturation instead"
            ),
          })
          applicable = True
        else:
          applicability[metric] = False
          fitted[metric] = {q: 0.0 for q in range(1, _HORIZON + 1)}
          continue
      if fact is not None and fact > 1e-9:
        lo, hi = fact * 0.8, fact * 1.2
        if not (lo <= q1 <= hi):
          violations.append({
            "metric_key": metric, "code": "q1_off_stated_fact",
            "message": (
              f"Q1 must reflect the operator's stated present-day level "
              f"{fact:.4f} (authored {q1:.4f}); snapped to the fact"
            ),
          })
          q1 = fact
      q1 = min(max(q1, 0.0), 0.95)
      q11 = min(max(q11, 0.0), 0.95)
      q20 = min(max(q20, 0.0), 0.95)
      applicability[metric] = True
      fitted[metric] = _interpolate_anchors(q1, q11, q20)
      continue

    # Margin spines: always applicable; enforce the Q11 doctrine on anchors.
    applicability[metric] = True
    if metric == _NI_KEY or metric in _VIABILITY_SPINE_KEYS:
      if q11 < 0.0:
        violations.append({
          "metric_key": metric, "code": "spine_negative_at_q11",
          "message": f"by Q11 the margin must be leading into positive (authored {q11:.4f}); snapped to 0",
        })
        q11 = 0.0
      if q20 < q11:
        violations.append({
          "metric_key": metric, "code": "spine_declines_after_q11",
          "message": f"the margin may not decay after Q11 (q20 {q20:.4f} < q11 {q11:.4f}); snapped",
        })
        q20 = q11
      if q1 > q11:
        violations.append({
          "metric_key": metric, "code": "spine_not_climbing_to_q11",
          "message": f"the margin must climb into the Q11 checkpoint (q1 {q1:.4f} > q11 {q11:.4f}); snapped",
        })
        q1 = q11
    # EXECUTIVE MARGIN BAND — the judged healthy band (viability-blind,
    # railed) is the standard the plan will be judged against, so the
    # manager's own EBITDA spine anchors must land inside it: a spine
    # below the band forecasts an unhealthy business as the PLAN; a spine
    # above it forecasts a margin the type cannot believably earn.
    if metric == "ebitda_margin" and isinstance(judged_margin_band, dict):
      for _anchor_name, _anchor_band_key in (("q11", "q11"), ("q20", "q20")):
        _jband = judged_margin_band.get(_anchor_band_key) or {}
        _jlo = _f(_jband.get("low"))
        _jhi = _f(_jband.get("high"))
        if _jlo is None or _jhi is None:
          continue
        _val = q11 if _anchor_name == "q11" else q20
        _snapped = min(max(_val, _jlo), _jhi)
        if abs(_snapped - _val) > 1e-9:
          violations.append({
            "metric_key": metric, "code": f"spine_outside_judged_band_{_anchor_name}",
            "message": (
              f"the executive judged this business's healthy EBITDA band at "
              f"{_anchor_name.upper()} as [{_jlo:.4f}, {_jhi:.4f}] (authored "
              f"{_val:.4f}); your cost path must arithmetically produce a "
              f"margin inside it — rework the COST anchors, not just this spine"
            ),
          })
          if _anchor_name == "q11":
            q11 = _snapped
            q20 = max(q20, q11)
          else:
            q20 = max(_snapped, q11)
    fitted[metric] = _interpolate_anchors(q1, q11, q20)

  # ebitda >= net income in every quarter (arithmetic identity of the P&L).
  ni = fitted.get("net_income_margin")
  eb = fitted.get("ebitda_margin")
  if ni and eb:
    for q in range(1, _HORIZON + 1):
      if eb.get(q, 0.0) < ni.get(q, 0.0):
        eb[q] = ni[q]

  # EXECUTIVE MARGIN BAND — arithmetic coherence of the COST anchors with
  # the judged healthy band. EBITDA = 1 - costs - payroll - rent, so even
  # BEFORE payroll and rent, 1 - (sum of authored cost anchors) must clear
  # the judged band low at the mature checkpoints; when it cannot, the
  # cost path arithmetically forecloses the healthy margin the executive
  # judged for this business type and the manager must rework the COSTS
  # (this is a retry signal — the final attempt keeps the manager's path
  # and the search/verdict machinery renders the honest outcome).
  if isinstance(judged_margin_band, dict):
    for _cq, _ckey in ((11, "q11"), (20, "q20")):
      _cjlo = _f((judged_margin_band.get(_ckey) or {}).get("low"))
      if _cjlo is None:
        continue
      _cost_sum = sum(
        float((fitted.get(_cm) or {}).get(_cq, 0.0))
        for _cm in _COST_RATIO_KEYS
        if applicability.get(_cm, False)
      )
      if (1.0 - _cost_sum) < _cjlo:
        violations.append({
          "metric_key": "ebitda_margin",
          "code": f"cost_anchors_foreclose_judged_band_q{_cq}",
          "message": (
            f"your cost anchors sum to {_cost_sum:.4f} of revenue at Q{_cq}, "
            f"leaving at most {1.0 - _cost_sum:.4f} EBITDA BEFORE payroll and "
            f"rent — arithmetically below the executive's judged healthy band "
            f"low of {_cjlo:.4f}. Mature the cost lines to levels a healthy "
            f"business of this type actually runs (defensible on merits), or "
            f"the plan cannot reach the margin the type is judged against"
          ),
        })

  return fitted, applicability, violations, rationales


def run_band_fitting_pass(
  *,
  compact: Dict[str, Any],
  revenue_line: List[float],
  targets_payload: Dict[str, Any],
  operator_levels: Optional[Dict[str, float]] = None,
  margin_band_judgment: Optional[Dict[str, Any]] = None,
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
  degenerate_anchors: Dict[str, Dict[str, Any]] = {}
  if operator_levels:
    envelope, degenerate_anchors = rescale_envelope_to_operator(
      envelope, operator_levels,
    )

  # DEGENERATE-ANCHOR ARBITRATION: Python detected that the operator anchor
  # and the cohort band radically disagree (no overlap). Which side is wrong
  # is an identity judgment (Luna's $1,200/yr opex = garbage anchor; Golden
  # Ring's 28% COGS vs a factory cohort = garbage cohort), so the identity-
  # aware executive arbitrates -- ONE locked call per business, verdicts
  # enforced by Python inside the disagreement interval. A failed call keeps
  # the conservative side already placed by the rescale guard (low-side ->
  # raw cohort band, high-side -> operator level; both are the expensive
  # direction, so a failure can never manufacture viability).
  anchor_arbitration: Dict[str, Any] = {}
  if degenerate_anchors:
    try:
      from client_intake_and_finmo.post_intake_headcount.gpt_anchor_arbiter import (  # type: ignore  # noqa: E501
        gpt_arbitrate_cost_anchors_once,
      )
      year1_revenue = sum(float(v or 0.0) for v in (revenue_line or [])[:4])
      disagreements: List[Dict[str, Any]] = []
      for mk in sorted(degenerate_anchors.keys()):
        d = degenerate_anchors[mk]
        lvl = float(d.get("operator_level") or 0.0)
        disagreements.append({
          "metric_key": mk,
          "operator_level": lvl,
          "operator_implied_annual_dollars": (
            round(lvl * year1_revenue, 2) if year1_revenue > 0.0 else None
          ),
          "cohort_band": {
            "min": d.get("cohort_min"),
            "target": _f((raw_envelope.get(mk) or {}).get("target")),
            "max": d.get("cohort_max"),
          },
          "side": d.get("side"),
        })
      arb = gpt_arbitrate_cost_anchors_once(
        compact=compact, disagreements=disagreements, model=model,
      )
      verdicts = (arb.get("verdicts") or {}) if arb.get("ok") else {}
      for mk, d in degenerate_anchors.items():
        v = dict(verdicts.get(mk) or {})
        verdict = str(v.get("verdict") or "")
        raw_band = raw_envelope.get(mk) or {}
        lvl = float(d.get("operator_level") or 0.0)
        if verdict == "custom":
          custom = _f(v.get("custom_level"))
          lo = min(lvl, float(d.get("cohort_min") or 0.0))
          hi = max(lvl, float(d.get("cohort_max") or 0.0))
          if custom is None:
            verdict = "conservative_default"
          else:
            enforced = min(max(custom, lo), hi)
            v["custom_level_enforced"] = enforced
            envelope[mk] = _rescale_band_to_level(raw_band, enforced)
        if verdict == "operator":
          envelope[mk] = _rescale_band_to_level(raw_band, lvl)
        elif verdict == "cohort":
          envelope[mk] = dict(raw_band)
        elif verdict not in ("custom",):
          # No/invalid verdict: the rescale guard already left the
          # conservative side in `envelope`; just record it.
          verdict = "conservative_default"
        v["verdict_applied"] = verdict
        d["arbitration"] = v
      anchor_arbitration = {
        "ok": bool(arb.get("ok")),
        "error": arb.get("error"),
        "disputed_metrics": sorted(degenerate_anchors.keys()),
      }
    except Exception as _arb_exc:  # noqa: BLE001 — conservative side already placed
      anchor_arbitration = {
        "ok": False,
        "error": f"{type(_arb_exc).__name__}: {str(_arb_exc)[:200]}",
        "disputed_metrics": sorted(degenerate_anchors.keys()),
      }

  author_fn = _author_fn
  if author_fn is None:
    from client_intake_and_finmo.post_intake_headcount.gpt_band_author import (  # type: ignore
      gpt_author_fitted_bands_once,
    )
    author_fn = gpt_author_fitted_bands_once

  # OPERATOR FACTS for the manager: the stated present-day cost levels, with
  # a credibility verdict from the anchor arbitration. Credible facts pin the
  # manager's Q1 (the present is a fact, not a lever); non-credible ones
  # (arbitrated data errors) are context only.
  operator_facts: Dict[str, Any] = {}
  for _mk, _lvl in (operator_levels or {}).items():
    _deg = degenerate_anchors.get(_mk) or {}
    _arb = (_deg.get("arbitration") or {}) if _deg else {}
    _verdict = str(_arb.get("verdict_applied") or "")
    if not _deg:
      operator_facts[_mk] = {"level": float(_lvl), "credible": True}
    elif _verdict == "operator":
      operator_facts[_mk] = {
        "level": float(_lvl), "credible": True,
        "note": "anchor disputed vs cohort; executive judged the operator level real",
      }
    elif _verdict == "custom":
      _cl = _f(_arb.get("custom_level_enforced"))
      operator_facts[_mk] = {
        "level": float(_cl) if _cl is not None else float(_lvl),
        "credible": _cl is not None,
        "note": "stated level judged not credible; executive substituted a defensible level",
      }
    elif _verdict == "cohort":
      # The EXECUTIVE explicitly judged the stated level a data error -
      # the owner's seat may remove a fact; the cohort alone may not.
      operator_facts[_mk] = {
        "level": float(_lvl), "credible": False,
        "note": (
          "stated level judged a data error by the executive arbiter; "
          "judge the honest level from the business itself and the "
          "dollar test, not from the cohort statistic"
        ),
      }
    else:
      # NO verdict (arbitration absent or failed): nobody judged, so the
      # client's stated fact STANDS - an informant outage cannot delete
      # a fact (CW-017 ruling). The disagreement stays recorded on the
      # degenerate-anchor trace for the manager's context.
      operator_facts[_mk] = {
        "level": float(_lvl), "credible": True,
        "note": (
          "anchor disputed vs cohort and unarbitrated - the stated fact "
          "stands until an executive verdict rules otherwise"
        ),
      }

  credible_facts: Dict[str, float] = {
    mk: float(v["level"]) for mk, v in operator_facts.items()
    if v.get("credible") and _f(v.get("level")) is not None
  }

  previous_violations: Optional[List[Dict[str, Any]]] = None
  last_error: Optional[str] = None
  forecast_rows: Optional[List[Dict[str, Any]]] = None
  for _attempt in range(max(1, int(max_attempts))):
    result = author_fn(
      compact=compact,
      revenue_line=revenue_line,
      industry_envelope=envelope,
      previous_violations=previous_violations,
      operator_facts=operator_facts or None,
      judged_margin_band=margin_band_judgment,
      model=model,
    )
    if not result.get("ok"):
      last_error = result.get("error")
      break
    forecast_rows = result.get("forecast")
    fitted, applicability, violations, rationales = validate_manager_forecast(
      forecast_rows, envelope=envelope, credible_facts=credible_facts,
      judged_margin_band=margin_band_judgment,
    )
    if violations and _attempt + 1 < max(1, int(max_attempts)):
      # Give the manager one shot to fix its own submission; the final
      # attempt is GROUNDED in place (facts snap, rules enforce) instead
      # of failing the pass.
      previous_violations = violations
      last_error = "manager_forecast_violations"
      continue
    if not fitted:
      last_error = "no_metrics_authored"
      break
    # PER-QUARTER WALLS around the manager's maturation path. The manager's
    # judgment IS the plan; the viability search only FINE-TUNES it. The
    # corridor is +/- _MAX_SEARCH_DEVIATION relative, scaled by forecast
    # distance: ZERO width at Q1 (the present is a fact -- the first
    # corridor attempt used the cohort's own relative spread and the search
    # promptly priced Luna's Q1 COGS 18 points below her stated reality) and
    # the full +/-10% only by Q20, where genuine forecast uncertainty lives.
    # A bigger deviation than that is a different plan and needs the
    # manager's judgment, not a solver's. Killed lines get zero-width walls
    # at zero. The Phase A clamp pins back into these walls per quarter, so
    # the maturation shape survives the whole pipeline.
    envelope_per_q: Dict[str, Dict[str, Dict[str, float]]] = {}
    new_scalar_envelope: Dict[str, Dict[str, float]] = {}
    for _mk, _series in fitted.items():
      _cohort = envelope.get(_mk) or {}
      _mn = _f(_cohort.get("min"))
      _mx = _f(_cohort.get("max"))
      _mins: Dict[str, float] = {}
      _maxs: Dict[str, float] = {}
      for _q in range(1, _HORIZON + 1):
        _v = float(_series.get(_q, 0.0))
        _wf = (_q - 1) / float(_HORIZON - 1)  # 0 at Q1 -> 1 at Q20
        if _mk in _COST_RATIO_KEYS and not applicability.get(_mk, True):
          _mins[str(_q)] = 0.0
          _maxs[str(_q)] = 0.0
        elif _mk in _COST_RATIO_KEYS:
          _dev = _MAX_SEARCH_DEVIATION * _wf
          _mins[str(_q)] = max(0.0, _v * (1.0 - _dev))
          _maxs[str(_q)] = _v * (1.0 + _dev)
        else:
          # Margin spines: symmetric absolute spread off the cohort band
          # width (margins cross zero; relative spread is meaningless).
          # The realism gate ultimately judges EBITDA against the band
          # DERIVED from the cost walls, so these stay wide.
          _half = abs((_mx - _mn) / 2.0) if (_mn is not None and _mx is not None) else 0.1
          _mins[str(_q)] = _v - _half
          _maxs[str(_q)] = _v + _half
      envelope_per_q[_mk] = {"min": _mins, "max": _maxs}
      _all_mins = [float(x) for x in _mins.values()]
      _all_maxs = [float(x) for x in _maxs.values()]
      _path_vals = [float(_series.get(_q, 0.0)) for _q in range(1, _HORIZON + 1)]
      new_scalar_envelope[_mk] = {
        "min": min(_all_mins) if _all_mins else 0.0,
        "target": (sum(_path_vals) / len(_path_vals)) if _path_vals else 0.0,
        "max": max(_all_maxs) if _all_maxs else 0.0,
      }
    # Metrics the manager did not forecast (not in BAND_METRIC_KEYS) keep
    # their arbitrated cohort band as the scalar envelope.
    for _mk, _band in envelope.items():
      if _mk not in new_scalar_envelope:
        new_scalar_envelope[_mk] = dict(_band)
    return {
      "ok": True,
      "fitted_bands": fitted,
      "envelope": new_scalar_envelope,
      "envelope_per_q": envelope_per_q,
      "cohort_reference_envelope": envelope,
      "raw_envelope": raw_envelope,
      "operator_levels": operator_levels or {},
      "operator_facts": operator_facts,
      "degenerate_anchors": degenerate_anchors,
      "anchor_arbitration": anchor_arbitration,
      "managerial_forecast": {
        "applicability": applicability,
        "rationales": rationales,
        "anchors": {
          str((r or {}).get("metric_key") or ""): {
            "applicable": bool((r or {}).get("applicable", True)),
            "q1": _f((r or {}).get("q1_level")),
            "q11": _f((r or {}).get("q11_level")),
            "q20": _f((r or {}).get("q20_level")),
          }
          for r in (forecast_rows or []) if isinstance(r, dict)
        },
      },
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
  "validate_manager_forecast",
]
