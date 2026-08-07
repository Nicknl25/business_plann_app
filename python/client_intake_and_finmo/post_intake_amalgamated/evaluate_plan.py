"""evaluate_plan — the deterministic standards check.

Two strictness modes (per memo §1.3 Q4 resolution):
  - "mini_finmo" while round-1 authoring is incomplete: lighter 5-universal
    + 7-stage-ramp viability set (wraps mini_finmo._eval_viability_checks
    from the H2 handler — that logic is reused, not duplicated).
  - "full_acceptance_gate" the instant the plan is structurally complete
    (every authoring section authored ≥ once): wraps
    post_intake_acceptance.gate.verify_run_acceptance.

Whichever mode runs, the output is the same structured EvaluatePlanResult
the restructure protocol consumes. Mode selection is the caller's job
(driven by Python's section-authored bookkeeping in step 5).

Section attribution and failure-mode classification live in this module so
the registry is single-sourced; everyone reads from the same map.

CASH SCOPE: cash is a separate downstream process (cash pass runs AFTER
the amalgamated session). At session time the cash pass has not run, so
cash state is meaningless and including cash-related checks would always
show them failing and tempt the restructure protocol to act on them —
exactly what we do NOT want. evaluate_plan therefore FILTERS OUT cash-
related checks from its output (see ``_CASH_RELATED_CHECKS``). The
standalone post-cash-pass acceptance gate continues to validate cash
unchanged — verify_run_acceptance still runs all 16 checks; this module
just drops the cash-related ones before surfacing the result to GPT.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_amalgamated.evaluation_types import (  # type: ignore
  CheckResult,
  EvaluatePlanResult,
  FailureMode,
  LeverMargin,
  QuarterTrajectory,
  SECTIONS,
)


# ---------------------------------------------------------------------------
# Cash-related checks (filtered OUT of evaluate_plan output).
# ---------------------------------------------------------------------------
# The cash pass runs AFTER the amalgamated session, so cash state at session
# time is meaningless. Including these checks would always show them failing
# and tempt the restructure protocol to act on them. The standalone post-
# cash-pass acceptance gate continues to run these checks unchanged; we
# just don't surface them to the session's evaluate_plan caller.
_CASH_RELATED_CHECKS: frozenset = frozenset({
  "cash_legitimate_q1_q10",                  # Q1-Q10 cash >= 0 or interest > 0
  "current_assets_positive_q1_q10",          # cash is a component of current_assets
  "cash_health_operational_not_debt_funded", # interest/revenue ratio set by debt structure
  "balance_sheet_growth_plausible",          # uses Q20 cash explicitly
})


# ---------------------------------------------------------------------------
# Registry: check_name -> (FailureMode, implicated_sections)
# ---------------------------------------------------------------------------
# A check may implicate multiple sections; the protocol consumes all of them.
# Keep this single-sourced; downstream tools must not redefine it.
# Cash-related checks are NOT in this registry — they are filtered out of
# the evaluator output before classification.
_CHECK_REGISTRY: Dict[str, Tuple[FailureMode, Tuple[str, ...]]] = {
  # mini_finmo universal viability
  "ebitda_positive_by_q11":                     (FailureMode.VIABILITY_INVARIANT, ("drivers",)),
  "ebitda_recovery_trend_q5_q11":               (FailureMode.VIABILITY_INVARIANT, ("drivers", "stage_ramp")),
  "ebitda_margin_q20_holds_or_improves_vs_q11": (FailureMode.VIABILITY_INVARIANT, ("drivers", "stage_ramp")),
  "gross_margin_supports_ebitda_recovery":      (FailureMode.VIABILITY_INVARIANT, ("drivers",)),
  "fixed_cost_burden_reduced_or_scaled_by_q11": (FailureMode.VIABILITY_INVARIANT, ("drivers", "payroll")),
  # mini_finmo stage_ramp coherence
  "stage_ramp_rev_max_respected":       (FailureMode.COHERENCE_INVARIANT, ("stage_ramp", "drivers")),
  "stage_ramp_cogs_max_respected":      (FailureMode.COHERENCE_INVARIANT, ("stage_ramp", "drivers")),
  "stage_ramp_marketing_max_respected": (FailureMode.COHERENCE_INVARIANT, ("stage_ramp", "drivers")),
  "stage_ramp_rd_max_respected":        (FailureMode.COHERENCE_INVARIANT, ("stage_ramp", "drivers")),
  "stage_ramp_ga_max_respected":        (FailureMode.COHERENCE_INVARIANT, ("stage_ramp", "drivers")),
  "stage_ramp_ni_floor_respected":      (FailureMode.COHERENCE_INVARIANT, ("stage_ramp", "drivers")),
  "stage_ramp_max_util_respected":      (FailureMode.CAPACITY_INVARIANT,  ("stage_ramp", "drivers", "capex_rd")),
  # 16-check acceptance gate (cash-related entries intentionally absent)
  "stage_reached_finalize":                  (FailureMode.META_INVARIANT,      ()),
  "cascade_landed_tier_set":                 (FailureMode.META_INVARIANT,      ()),
  "plan_confidence_recorded":                (FailureMode.META_INVARIANT,      ()),
  "realism_gate_provenance_recorded":        (FailureMode.BAND_INVARIANT,      ("drivers", "stage_ramp")),
  "realism_gate_no_hard_fail_violations":    (FailureMode.BAND_INVARIANT,      ("drivers",)),
  "solver_target_assertion_checked":         (FailureMode.COHERENCE_INVARIANT, ()),
  "solver_target_assertion_no_hard_violations": (FailureMode.COHERENCE_INVARIANT, ("drivers",)),
  "revenue_not_flat_q1_q10":                 (FailureMode.GROWTH_INVARIANT,    ("stage_ramp", "drivers")),
  "net_income_trajectory_viable":            (FailureMode.VIABILITY_INVARIANT, ("drivers", "stage_ramp")),
  "cascade_exercised_or_documented":         (FailureMode.META_INVARIANT,      ()),
  "phase_3_calibrated_bands_consulted":      (FailureMode.BAND_INVARIANT,      ()),
  "viability_timeline_landed":               (FailureMode.VIABILITY_INVARIANT, ("drivers",)),
}


def classify_failure(check_name: str) -> Optional[FailureMode]:
  entry = _CHECK_REGISTRY.get(check_name)
  return entry[0] if entry else None


def attribute_to_sections(check_name: str) -> List[str]:
  entry = _CHECK_REGISTRY.get(check_name)
  return list(entry[1]) if entry else []


# ---------------------------------------------------------------------------
# Distance calculators
# ---------------------------------------------------------------------------
# mini_finmo viability check distances. Each takes the raw mini_finmo
# output dict and returns (signed_distance, units). Positive = passing
# with margin, negative = failing by that much.
def _mini_finmo_distance(check_name: str, mini: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
  em = mini.get("ebitda_margins") or {}
  gm = mini.get("gross_margin_percents") or {}
  q1, q5, q11, q20 = em.get("q1"), em.get("q5"), em.get("q11"), em.get("q20")
  g5, g11 = gm.get("q5"), gm.get("q11")
  if check_name == "ebitda_positive_by_q11":
    return (None if q11 is None else float(q11)), "fraction"
  if check_name == "ebitda_recovery_trend_q5_q11":
    return (None if q5 is None or q11 is None else float(q11 - q5)), "fraction"
  if check_name == "ebitda_margin_q20_holds_or_improves_vs_q11":
    if q11 is None or q20 is None:
      return None, "fraction"
    from client_intake_and_finmo.post_intake_realism.formulas import (  # type: ignore
      _EBITDA_Q20_HOLDS_OR_IMPROVES_TOLERANCE as _Q20_TOL,
    )
    return float(q20 - (q11 - float(_Q20_TOL))), "fraction"
  if check_name == "gross_margin_supports_ebitda_recovery":
    return (None if g5 is None or g11 is None else float(g11 - g5)), "fraction"
  if check_name == "fixed_cost_burden_reduced_or_scaled_by_q11":
    # mini_finmo only returns the rolled-up PASS/FAIL for this one; raw values not exposed.
    return None, "fraction"
  return None, None


def _stage_ramp_violation_distance(check_name: str, violations: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[str]]:
  """For a stage_ramp_*_respected check, signed distance = the worst
  bound − actual across violations of that field (negative when failing).
  """
  field_key = check_name.replace("stage_ramp_", "").replace("_respected", "")
  worst: Optional[float] = None
  for v in violations or []:
    if str(v.get("field") or "") != field_key:
      continue
    actual = v.get("actual"); bound = v.get("bound"); kind = str(v.get("bound_kind") or "max").lower()
    if actual is None or bound is None:
      continue
    # 'max' bound violated when actual > bound => distance = bound - actual (negative)
    # 'min'/'floor' violated when actual < bound => distance = actual - bound (negative)
    if kind in ("max", "ceiling", "cap"):
      d = float(bound) - float(actual)
    else:
      d = float(actual) - float(bound)
    worst = d if worst is None else min(worst, d)
  return worst, "fraction"


# Acceptance-gate detail keys we know how to read for distance.
# Cash-related checks are filtered before classification (see
# _CASH_RELATED_CHECKS); their distance handlers would be dead code here.
def _gate_distance(check_name: str, detail: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
  # Signed margin to feasibility (negative => infeasible). Reads the ACTUAL
  # detail keys the Fix #1 acceptance-gate check functions emit + their own
  # thresholds, so the in-cascade standard and the final gate agree on the
  # distance. (Earlier this read non-existent keys q11_margin/
  # coefficient_of_variation and always returned None -> worst_distance was
  # never measurable -> progress couldn't be detected.)
  def _n(*keys: str) -> Optional[float]:
    for k in keys:
      v = detail.get(k)
      if isinstance(v, (int, float)):
        return float(v)
    return None
  if check_name == "revenue_not_flat_q1_q10":
    cv = _n("stdev_over_mean", "coefficient_of_variation")
    cv_thr = _n("stdev_over_mean_threshold")
    growth = _n("q10_over_q1_delta", "q1_to_q10_pct_change")
    growth_thr = _n("q10_over_q1_delta_threshold")
    # CW-017 E12: fallback thresholds IMPORT from the acceptance gate -
    # hand-copied duplicates steered the cascade toward stale constants
    # whenever the gate's threshold moved.
    from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore
      REVENUE_FLAT_Q10_OVER_Q1_DELTA_THRESHOLD as _GATE_GROWTH_THR,
      REVENUE_FLAT_STDEV_OVER_MEAN_THRESHOLD as _GATE_CV_THR,
    )
    candidates = []
    if cv is not None:
      candidates.append(cv - (cv_thr if cv_thr is not None else float(_GATE_CV_THR)))
    if growth is not None:
      candidates.append(growth - (growth_thr if growth_thr is not None else float(_GATE_GROWTH_THR)))
    # Passes if EITHER path clears its threshold -> nearest-to-feasible is max.
    return (max(candidates) if candidates else None), "dimensionless"
  if check_name == "net_income_trajectory_viable":
    from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore
      _NI_TRAJECTORY_MIN_DELTA_Q5_TO_Q11 as _GATE_NI_DELTA_THR,
    )
    q11 = _n("q11_ni_margin", "q11_margin")
    req_q11 = _n("min_required_q11_margin")
    delta = _n("q5_to_q11_delta")
    req_delta = _n("min_required_delta")
    candidates = []
    if q11 is not None:
      candidates.append(q11 - (req_q11 if req_q11 is not None else 0.0))
    if delta is not None:
      candidates.append(delta - (req_delta if req_delta is not None else float(_GATE_NI_DELTA_THR)))
    # Requires BOTH conditions -> worst (most negative) is the binding gap.
    return (min(candidates) if candidates else None), "fraction"
  # For meta and band-source checks, distance isn't meaningful as a scalar.
  return None, None


# ---------------------------------------------------------------------------
# Lever-margin computation (reads bands from the post_intake_cohort_bands
# table populated in Phase 3 step 1).
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Fork A keystone — assemble-bands fallback for lever margins.
# ---------------------------------------------------------------------------
# The cohort-bands table (post_intake_cohort_bands) is empty for SMB NAICS
# (resolve_cohort_band has no public-firm coverage), so the cohort path
# yields no lever_margins -> the proposer emits vacuous (None) proposals ->
# no deltas. The realism gate enforces a DIFFERENT, populated source
# (assemble_finmo_output_targets, the phase_3_calibrated industry baselines).
# This fallback single-sources the cascade's lever margins to THAT SAME band
# source the plan is judged against, with current values read from the LIVE
# finmo.
#
# DANGER SPOT (verified by eye + a live per-tier correspondence proof): this
# map aims each lever at the ratio it directly controls. A wrong pair = the
# cascade chases the wrong band = confident FAKE convergence. Each pair is
# the % / ratio the lever sets, semantically 1:1.
_LEVER_TO_TARGET_METRIC_KEY: Dict[str, str] = {
  # drivers (P&L cost ratios) — the lever IS that % of revenue
  "expenses::Cost of Goods Sold":       "cogs_percent_of_revenue",
  "expenses::Marketing":                "marketing_percent_of_revenue",
  "expenses::General & Administrative": "sga_percent_of_revenue",
  "expenses::Research & Development":   "r_and_d_percent_of_revenue",
  # stage_ramp ceilings — cap the same ratios
  "stage_ramp::cogs_max":      "cogs_percent_of_revenue",
  "stage_ramp::marketing_max": "marketing_percent_of_revenue",
  "stage_ramp::ga_max":        "sga_percent_of_revenue",
  "stage_ramp::rd_max":        "r_and_d_percent_of_revenue",
  "stage_ramp::ni_floor":      "net_income_margin",
  # balance_sheet working-capital days
  "balance_sheet::Accounts Receivable Days": "ar_days_dso",
  "balance_sheet::Accounts Payable Days":    "ap_days_dpo",
  "balance_sheet::Inventory Days":           "inventory_days",
}

# CW-017 E11 (engine fragility ledger): the cascade used a flat 91.25
# days/quarter while the finalize validator judges the SAME days metrics
# at per-row actual-calendar days (90/91/92) - so the cascade could
# steer AR/AP/Inventory days to a value the validator then rejects.
# ONE authority: the validator's own per-row day count.
from client_intake_and_finmo.post_intake_runtime_validation.balance_sheet_driver_validation import (  # type: ignore  # noqa: E501
  _quarter_days_from_finmo_row as _days_in_quarter_for_row,
)


def _section_for_lever(lever_id: str) -> str:
  if lever_id.startswith("expenses::"):
    return "drivers"
  if lever_id.startswith("stage_ramp::"):
    return "stage_ramp"
  return "balance_sheet"


def _metric_current_from_finmo(metric_key: str, rows: List[Dict[str, Any]]) -> Optional[float]:
  """Current value of a cascade metric, computed from the LIVE finmo raw
  fields (the rows carry raw $ values, not ratios), averaged over the live
  quarters. Definitions match the realism gate's metric definitions so the
  cascade's 'current' agrees with what the plan is judged against."""
  def _mean(vals: List[Optional[float]]) -> Optional[float]:
    clean = [v for v in vals if isinstance(v, (int, float))]
    return (sum(clean) / len(clean)) if clean else None

  def _ratio(num_key: str, den_key: str) -> Optional[float]:
    out: List[Optional[float]] = []
    for r in rows:
      den = _f(r.get(den_key))
      num = _f(r.get(num_key))
      if den and num is not None and den != 0:
        out.append(num / den)
    return _mean(out)

  if metric_key == "cogs_percent_of_revenue":
    return _ratio("cogs", "revenue") if any(r.get("cogs") is not None for r in rows) else _ratio("cost_of_goods_sold", "revenue")
  if metric_key == "marketing_percent_of_revenue":
    return _ratio("marketing", "revenue")
  if metric_key == "sga_percent_of_revenue":
    return _ratio("general_and_administrative", "revenue") if any(r.get("general_and_administrative") is not None for r in rows) else _ratio("g_and_a", "revenue")
  if metric_key == "r_and_d_percent_of_revenue":
    return _ratio("research_and_development", "revenue")
  if metric_key == "net_income_margin":
    return _ratio("net_income", "revenue")
  if metric_key == "ar_days_dso":
    return _mean([
      (_f(r.get("accounts_receivable")) / _f(r.get("revenue")) * _days_in_quarter_for_row(r))
      for r in rows if _f(r.get("revenue"))
    ])
  if metric_key == "ap_days_dpo":
    return _mean([
      (_f(r.get("accounts_payable")) / _f(r.get("cogs")) * _days_in_quarter_for_row(r))
      for r in rows if _f(r.get("cogs"))
    ])
  if metric_key == "inventory_days":
    return _mean([
      (_f(r.get("inventory")) / _f(r.get("cogs")) * _days_in_quarter_for_row(r))
      for r in rows if _f(r.get("cogs"))
    ])
  return None


def _ratio_at_row(metric_key: str, row: Dict[str, Any]) -> Optional[float]:
  """Per-quarter value of a cascade metric from ONE finmo row (band-fitting is
  per-quarter, so 'current' must be per-quarter to compare against fitted[q])."""
  def _r(num_key: str, den_key: str) -> Optional[float]:
    den = _f(row.get(den_key))
    num = _f(row.get(num_key))
    if den and num is not None and den != 0:
      return num / den
    return None
  if metric_key == "cogs_percent_of_revenue":
    return _r("cogs", "revenue") if row.get("cogs") is not None else _r("cost_of_goods_sold", "revenue")
  if metric_key == "marketing_percent_of_revenue":
    return _r("marketing", "revenue")
  if metric_key == "sga_percent_of_revenue":
    return _r("general_and_administrative", "revenue") if row.get("general_and_administrative") is not None else _r("g_and_a", "revenue")
  if metric_key == "r_and_d_percent_of_revenue":
    return _r("research_and_development", "revenue")
  if metric_key == "net_income_margin":
    return _r("net_income", "revenue")
  return None


def _fitted_lever_margins(
  fitted_payload: Dict[str, Any],
  finmo_json: Optional[Dict[str, Any]],
) -> List[LeverMargin]:
  """Per-quarter lever margins from the BUSINESS-FITTED bands (band_fitting +
  fitted_bands_store). Each cost-ratio / ni lever gets one margin PER QUARTER:
  current = the metric's ratio at that quarter; band_target = fitted[metric][q]
  (the viable, business-scaled target the executive should aim at); band_min/max
  = the validated envelope. This is the keystone: aiming a lever at its band now
  means aiming at viable, per quarter, with the Q11 net-income step intact."""
  fitted = (fitted_payload or {}).get("fitted") or {}
  envelope = (fitted_payload or {}).get("envelope") or {}
  if not fitted or not isinstance(finmo_json, dict):
    return []
  rows_by_q: Dict[int, Dict[str, Any]] = {}
  for r in (finmo_json.get("quarter_rows") or []):
    if isinstance(r, dict):
      try:
        qi = int(r.get("quarter_index") or 0)
      except (TypeError, ValueError):
        continue
      if 1 <= qi <= 20:
        rows_by_q[qi] = r
  if not rows_by_q:
    return []
  margins: List[LeverMargin] = []
  for lever_id, metric_key in _LEVER_TO_TARGET_METRIC_KEY.items():
    traj = fitted.get(metric_key)
    if not isinstance(traj, dict):
      continue
    env = envelope.get(metric_key) or {}
    bmin = _f(env.get("min"))
    bmax = _f(env.get("max"))
    section = _section_for_lever(lever_id)
    for q in range(1, 21):
      if q not in rows_by_q or q not in traj:
        continue
      current = _ratio_at_row(metric_key, rows_by_q[q])
      if current is None:
        continue
      band = {"benchmark_min": bmin, "benchmark_target": _f(traj.get(q)), "benchmark_max": bmax}
      margins.append(_lever_margin_from(section, lever_id, q, float(current), band))
  return margins


def _assemble_fallback_lever_margins(
  finmo_json: Optional[Dict[str, Any]],
  business_naics_6: Optional[str],
) -> List[LeverMargin]:
  """Lever margins sourced from assemble_finmo_output_targets (industry
  baseline bands, the realism-gate source) + current values from the live
  finmo. Used when the cohort-bands table is empty (SMB NAICS)."""
  naics = "".join(ch for ch in str(business_naics_6 or "") if ch.isdigit())
  if not naics or not isinstance(finmo_json, dict):
    return []
  try:
    from client_intake_and_finmo.post_intake_solver import (  # type: ignore
      assemble_finmo_output_targets,
    )
    targets = (assemble_finmo_output_targets(business_naics_6=naics) or {}).get("metrics") or {}
  except Exception:
    return []
  rows = [
    r for r in (finmo_json.get("quarter_rows") or [])
    if isinstance(r, dict) and 1 <= int(r.get("quarter_index") or 0) <= 20
  ]
  if not rows or not targets:
    return []
  margins: List[LeverMargin] = []
  for lever_id, metric_key in _LEVER_TO_TARGET_METRIC_KEY.items():
    band_row = targets.get(metric_key)
    if not isinstance(band_row, dict):
      continue
    current = _metric_current_from_finmo(metric_key, rows)
    if current is None:
      continue
    band = {
      "benchmark_min": _f(band_row.get("target_min")),
      "benchmark_target": _f(band_row.get("target_target")),
      "benchmark_max": _f(band_row.get("target_max")),
    }
    margins.append(_lever_margin_from(
      _section_for_lever(lever_id), lever_id, None, float(current), band,
    ))
  return margins


def _compute_lever_margins(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  plan_state: Dict[str, Any],
  finmo_json: Optional[Dict[str, Any]] = None,
  business_naics_6: Optional[str] = None,
) -> List[LeverMargin]:
  from client_intake_and_finmo.post_intake_solver.cohort_bands_table import (  # type: ignore
    get_cohort_bands,
  )
  margins: List[LeverMargin] = []
  if not draft_id or not planning_run_id:
    return margins
  rows = get_cohort_bands(conn, draft_id=draft_id, planning_run_id=planning_run_id)
  bands_by_section: Dict[str, Dict[str, Dict[str, Any]]] = {}
  for row in rows:
    section = str(row.get("section") or "")
    lever_id = str(row.get("lever_id") or "")
    if not section or not lever_id:
      continue
    bands_by_section.setdefault(section, {})[lever_id] = row

  for section in SECTIONS:
    section_state = plan_state.get(section) if plan_state else None
    if section_state is None:
      # plan_state was None entirely — caller has no state to evaluate
      # margins against; skip silently (the public entry already gates
      # on plan_state presence above).
      continue
    if not isinstance(section_state, dict):
      continue
    section_bands = bands_by_section.get(section) or {}
    for lever_id, current in section_state.items():
      band = section_bands.get(lever_id)
      if not isinstance(current, (int, float)):
        # quarter-indexed lever stored as a per-quarter dict (e.g. drivers anchors)
        if isinstance(current, dict):
          for q_key, q_val in current.items():
            if isinstance(q_val, (int, float)):
              margins.append(_lever_margin_from(section, lever_id, q_key, float(q_val), band))
        continue
      margins.append(_lever_margin_from(section, lever_id, None, float(current), band))

  # Band-fitting keystone: prefer the BUSINESS-FITTED per-quarter bands when the
  # run has them (band_fitting + fitted_bands_store). These re-point each lever
  # at a business-scaled, per-quarter VIABLE target (a law firm's R&D at ~0, not
  # a 74% industry envelope max), with the Q11 net-income step intact, so the
  # cascade aiming at a band means aiming at viable. Falls back to the raw
  # industry envelope (assemble_finmo_output_targets) for any lever the fitted /
  # cohort paths did not band.
  _banded = {
    m.lever_id for m in margins
    if getattr(m, "band_min", None) is not None or getattr(m, "band_max", None) is not None
  }
  fitted_payload: Dict[str, Any] = {}
  try:
    from client_intake_and_finmo.post_intake_solver.fitted_bands_store import (  # type: ignore
      get_fitted_bands,
    )
    fitted_payload = get_fitted_bands(conn, draft_id=draft_id, planning_run_id=planning_run_id)
  except Exception:
    fitted_payload = {}
  if fitted_payload.get("fitted"):
    for fm in _fitted_lever_margins(fitted_payload, finmo_json):
      margins.append(fm)
      _banded.add(fm.lever_id)
  for fm in _assemble_fallback_lever_margins(finmo_json, business_naics_6):
    if fm.lever_id not in _banded:
      margins.append(fm)
  return margins


def _lever_margin_from(
  section: str,
  lever_id: str,
  quarter_key: Optional[Any],
  current: float,
  band: Optional[Dict[str, Any]],
) -> LeverMargin:
  quarter: Optional[int] = None
  if isinstance(quarter_key, int):
    quarter = quarter_key
  elif isinstance(quarter_key, str):
    digits = "".join(ch for ch in quarter_key if ch.isdigit())
    if digits:
      try:
        quarter = int(digits)
      except Exception:
        quarter = None
  bmin = bmax = btgt = None
  if isinstance(band, dict):
    bmin = _f(band.get("robust_min") if band.get("robust_min") is not None else band.get("benchmark_min"))
    bmax = _f(band.get("robust_max") if band.get("robust_max") is not None else band.get("benchmark_max"))
    btgt = _f(band.get("benchmark_target"))
  dmin = (current - bmin) if (bmin is not None) else None
  dmax = (bmax - current) if (bmax is not None) else None
  return LeverMargin(
    lever_id=lever_id,
    section=section,
    quarter=quarter,
    current=current,
    band_min=bmin, band_target=btgt, band_max=bmax,
    distance_to_min=dmin, distance_to_max=dmax,
    pinned_min=(bmin is not None and current <= bmin),
    pinned_max=(bmax is not None and current >= bmax),
    outside_band=((bmin is not None and current < bmin) or (bmax is not None and current > bmax)),
  )


def _f(v: Any) -> Optional[float]:
  if v is None:
    return None
  try:
    return float(v)
  except Exception:
    return None


# ---------------------------------------------------------------------------
# Trajectory extraction from finmo_json quarter_rows.
# ---------------------------------------------------------------------------
def _trajectory_from_finmo(finmo_json: Optional[Dict[str, Any]]) -> List[QuarterTrajectory]:
  if not isinstance(finmo_json, dict):
    return []
  rows = finmo_json.get("quarter_rows") or []
  out: List[QuarterTrajectory] = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    q = row.get("quarter") or row.get("q")
    try:
      qi = int(q)
    except Exception:
      continue
    rev = _f(row.get("revenue"))
    cash = _f(row.get("ending_cash") if row.get("ending_cash") is not None else row.get("cash"))
    eb = _f(row.get("ebitda"))
    ni = _f(row.get("net_income"))
    out.append(QuarterTrajectory(
      quarter=qi,
      revenue=rev, cash=cash, ebitda=eb,
      ebitda_margin=(eb / rev if rev and eb is not None else None),
      gross_margin=_f(row.get("gross_margin_percent") or row.get("gross_margin")),
      net_income=ni,
      net_income_margin=(ni / rev if rev and ni is not None else None),
      utilization=_f(row.get("utilization")),
      cogs_ratio=_f(row.get("cogs_percent_of_revenue")),
    ))
  return out


# ---------------------------------------------------------------------------
# Evaluators (one per strictness mode)
# ---------------------------------------------------------------------------
def _evaluate_mini_finmo(
  *,
  anchors: Dict[str, Any],
  operating_context: Dict[str, Any],
  emit_diagnostic_fn=None,
) -> Tuple[List[CheckResult], List[QuarterTrajectory], Dict[str, Any], int]:
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # type: ignore
    compute_trajectory_from_anchors,
  )
  raw = compute_trajectory_from_anchors(anchors, operating_context)
  checks_dict = (raw.get("viability_checks") or {})
  violations = raw.get("stage_ramp_violations") or []
  results: List[CheckResult] = []
  # B4 — count exceptions per check so the caller can fail-fast if ALL
  # checks raised (the partial-result return path is still safe when at
  # least one check resolved).
  exception_count = 0
  for name, verdict in checks_dict.items():
    if name == "all_pass":
      continue
    if name in _CASH_RELATED_CHECKS:
      continue  # cash is a separate downstream process — filtered from session output
    try:
      passed = str(verdict).upper() in {"PASS", "SKIPPED"}
      if name.startswith("stage_ramp_") and name.endswith("_respected"):
        distance, units = _stage_ramp_violation_distance(name, violations)
      else:
        distance, units = _mini_finmo_distance(name, raw)
      results.append(CheckResult(
        name=name, passed=passed,
        failure_mode=(None if passed else classify_failure(name)),
        distance_to_feasibility=distance, distance_units=units,
        implicated_sections=attribute_to_sections(name) if not passed else [],
        detail={"raw_verdict": str(verdict)},
      ))
    except Exception as exc:
      exception_count += 1
      _emit_check_exception(emit_diagnostic_fn, name, exc)
      # Synthesize a failed-by-infinite-distance check so downstream
      # consumers see this as a META failure rather than missing the
      # check entirely.
      results.append(CheckResult(
        name=name, passed=False,
        failure_mode=FailureMode.META_INVARIANT,
        distance_to_feasibility=float("-inf"),
        distance_units=None,
        implicated_sections=[],
        detail={"exception_type": type(exc).__name__,
                "exception_detail": str(exc)[:480]},
      ))
  trajectory: List[QuarterTrajectory] = []
  # The mini_finmo output exposes key-quarter scalars only, not full grids.
  for q_key, q_label in (("q1", 1), ("q5", 5), ("q11", 11), ("q15", 15), ("q20", 20)):
    em = (raw.get("ebitda_margins") or {}).get(q_key)
    gm = (raw.get("gross_margin_percents") or {}).get(q_key)
    rev = (raw.get("revenues") or {}).get(q_key)
    eb = (raw.get("ebitda_dollars") or {}).get(q_key)
    if em is None and gm is None and rev is None and eb is None:
      continue
    trajectory.append(QuarterTrajectory(
      quarter=q_label, revenue=_f(rev), ebitda=_f(eb),
      ebitda_margin=_f(em), gross_margin=_f(gm),
    ))
  return results, trajectory, raw, exception_count


def _evaluate_full_acceptance_gate(
  conn,
  *,
  draft_id: str,
  planning_run_id: Optional[str],
  finmo_json: Optional[Dict[str, Any]],
  emit_diagnostic_fn=None,
) -> Tuple[List[CheckResult], List[QuarterTrajectory], Dict[str, Any], int]:
  from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore
    verify_run_acceptance,
  )
  verdict = verify_run_acceptance(conn, draft_id=draft_id, planning_run_id=planning_run_id)
  results: List[CheckResult] = []
  # B4 — per-check try/except so a single check raising can't crash
  # evaluate_plan; the caller can fail-fast if ALL checks raised.
  exception_count = 0
  for c in (verdict.get("checks") or []):
    name = str(c.get("name") or "")
    if name in _CASH_RELATED_CHECKS:
      continue  # cash is a separate downstream process — filtered from session output
    try:
      passed = bool(c.get("passed"))
      detail = c.get("detail") or {}
      distance, units = _gate_distance(name, detail) if not passed else (None, None)
      results.append(CheckResult(
        name=name, passed=passed,
        failure_mode=(None if passed else classify_failure(name)),
        distance_to_feasibility=distance, distance_units=units,
        implicated_sections=attribute_to_sections(name) if not passed else [],
        detail=detail if isinstance(detail, dict) else {},
      ))
    except Exception as exc:
      exception_count += 1
      _emit_check_exception(emit_diagnostic_fn, name, exc)
      results.append(CheckResult(
        name=name, passed=False,
        failure_mode=FailureMode.META_INVARIANT,
        distance_to_feasibility=float("-inf"),
        distance_units=None,
        implicated_sections=[],
        detail={"exception_type": type(exc).__name__,
                "exception_detail": str(exc)[:480]},
      ))
  trajectory = _trajectory_from_finmo(finmo_json)
  return results, trajectory, verdict, exception_count


# ---------------------------------------------------------------------------
# In-cascade evaluator (Fork A — Wall A) — the in-LOOP standard.
# ---------------------------------------------------------------------------
# The cascade restructures the LIVE plan, so its standard must score the live
# finmo (rebuilt each round from the mirror's plan_state) on the RESTRUCTURABLE
# economic checks ONLY. It deliberately excludes:
#   - the post-hoc COMPLETION checks (stage_reached_finalize,
#     cascade_landed_tier_set, plan_confidence_recorded,
#     cascade_exercised_or_documented) + the realism/solver-artifact checks,
#     which can only pass after the run finalizes. Those stay ENFORCED,
#     unchanged, at the FINAL acceptance gate (verify_run_acceptance).
#   - the CASH-dependent checks (current_assets_positive_q1_q10,
#     balance_sheet_growth_plausible, cash_*), because the cash pass runs
#     AFTER the session — cash is meaningless here and its levers are walled
#     off from the cascade (see _CASH_RELATED_CHECKS). Including them would
#     inject permanent failures the cascade cannot fix and block convergence.
# Net in-loop set: the two non-cash, finmo-based, restructurable gate checks —
# net_income_trajectory_viable (VIABILITY) and revenue_not_flat_q1_q10
# (GROWTH). A genuine exception in a check still yields a META_INVARIANT
# failure, so a real protocol/structural failure halts the cascade (the
# structural META-halt SURVIVES; only the premature completion checks are
# removed from the in-loop set).
_IN_CASCADE_ECONOMIC_CHECKS: Tuple[str, ...] = (
  "net_income_trajectory_viable",
  "revenue_not_flat_q1_q10",
)

# REQ1 (cascade engages on the SAME viability signal as the final verdict):
# the universal EBITDA-viability checks the acceptance verdict's
# viability_timeline reflects. The two economic checks above are loss-tolerant
# (a negative-but-improving plan passes both), so without these a plan the
# verdict marks non_viable on EBITDA would slip through the in-loop standard
# and the cascade would exit at tier 0 UN-ADAPTED. Computed from the SAME live
# finmo via mini_finmo._eval_viability_checks (single source of truth with the
# realism gate that feeds the verdict). Cash-side checks are excluded (a
# downstream pass owns them).
_IN_CASCADE_VIABILITY_CHECKS: Tuple[str, ...] = (
  "ebitda_positive_by_q11",
  "ebitda_recovery_trend_q5_q11",
  "ebitda_margin_q20_holds_or_improves_vs_q11",
  "gross_margin_supports_ebitda_recovery",
  "fixed_cost_burden_reduced_or_scaled_by_q11",
)


def _evaluate_in_cascade(
  *,
  finmo_json: Optional[Dict[str, Any]],
  emit_diagnostic_fn=None,
) -> Tuple[List[CheckResult], List[QuarterTrajectory], Dict[str, Any], int]:
  """Run the restructurable economic checks on the LIVE finmo. Reuses the
  Fix #1 acceptance-gate finmo check functions (single source of truth) so
  the in-loop standard and the final gate agree on what 'economically
  failing' means; the in-loop set just omits the post-hoc + cash checks."""
  from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore
    _check_net_income_trajectory_viable,
    _check_revenue_not_flat,
  )
  fj = finmo_json if isinstance(finmo_json, dict) else {}
  runners = {
    "net_income_trajectory_viable": _check_net_income_trajectory_viable,
    "revenue_not_flat_q1_q10": _check_revenue_not_flat,
  }
  results: List[CheckResult] = []
  exception_count = 0
  for name in _IN_CASCADE_ECONOMIC_CHECKS:
    fn = runners[name]
    try:
      passed, detail = fn(fj)
      distance, units = _gate_distance(name, detail) if not passed else (None, None)
      results.append(CheckResult(
        name=name, passed=bool(passed),
        failure_mode=(None if passed else classify_failure(name)),
        distance_to_feasibility=distance, distance_units=units,
        implicated_sections=attribute_to_sections(name) if not passed else [],
        detail=detail if isinstance(detail, dict) else {},
      ))
    except Exception as exc:
      exception_count += 1
      _emit_check_exception(emit_diagnostic_fn, name, exc)
      results.append(CheckResult(
        name=name, passed=False,
        failure_mode=FailureMode.META_INVARIANT,
        distance_to_feasibility=float("-inf"),
        distance_units=None,
        implicated_sections=[],
        detail={"exception_type": type(exc).__name__,
                "exception_detail": str(exc)[:480]},
      ))
  # REQ1: add the universal EBITDA-viability checks from the SAME live finmo so
  # the in-loop standard agrees with the verdict on whether the plan is viable.
  try:
    from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # type: ignore  # noqa: E501
      _eval_viability_checks,
    )
    viab = _eval_viability_checks(fj)
    viab_checks = viab.get("viability_checks") or {}
    for name in _IN_CASCADE_VIABILITY_CHECKS:
      verdict = viab_checks.get(name)
      if verdict is None:
        continue
      passed = str(verdict).upper() in {"PASS", "SKIPPED"}
      distance, units = _mini_finmo_distance(name, viab) if not passed else (None, None)
      results.append(CheckResult(
        name=name, passed=passed,
        failure_mode=(None if passed else classify_failure(name)),
        distance_to_feasibility=distance, distance_units=units,
        implicated_sections=attribute_to_sections(name) if not passed else [],
        detail={"raw_verdict": str(verdict)},
      ))
  except Exception as exc:
    exception_count += 1
    _emit_check_exception(emit_diagnostic_fn, "in_cascade_viability_checks", exc)
  trajectory = _trajectory_from_finmo(fj)
  return results, trajectory, {}, exception_count


def _emit_check_exception(emit_fn, check_name: str, exc: BaseException) -> None:
  """Best-effort diagnostic emit for a per-check exception. Mirrors
  session_driver._emit — swallows any emitter failure so the evaluator
  never crashes on diagnostics."""
  if emit_fn is None:
    return
  try:
    from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # type: ignore
      EventCode, PhaseCode, Status,
    )
    emit_fn(
      phase=PhaseCode.EVALUATE_PLAN,
      event_code=EventCode.EVALUATE_PLAN_CHECK_EXCEPTION,
      status=Status.FAILED,
      diagnostic_data={
        "check_name": check_name,
        "exception_type": type(exc).__name__,
        "exception_detail": str(exc)[:480],
      },
    )
  except Exception:
    pass


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------
def evaluate_plan(
  conn=None,
  *,
  draft_id: Optional[str] = None,
  planning_run_id: Optional[str] = None,
  plan_state: Optional[Dict[str, Any]] = None,
  structural_completeness: bool = False,
  in_cascade: bool = False,
  business_naics_6: Optional[str] = None,
  round_number: int = 1,
  # Inputs the mini_finmo path needs (caller supplies what it has):
  anchors: Optional[Dict[str, Any]] = None,
  operating_context: Optional[Dict[str, Any]] = None,
  # Input the full-gate trajectory wants:
  finmo_json: Optional[Dict[str, Any]] = None,
  # Optional diagnostic emit closure (B4 — for per-check exception rows).
  emit_diagnostic_fn=None,
) -> EvaluatePlanResult:
  """Run the standards check and return a structured result.

  Strictness selection is the caller's call (the session driver in step 5
  tracks section-authored flags). ``structural_completeness=True`` selects
  the full 16-check acceptance gate; False selects the lighter mini_finmo
  viability + stage_ramp coherence set. Both produce the same shape.
  """
  notes: List[str] = []
  strictness = "full_acceptance_gate" if structural_completeness else "mini_finmo"
  if in_cascade:
    strictness = "in_cascade_economic"
  checks: List[CheckResult] = []
  trajectory: List[QuarterTrajectory] = []
  check_exception_count = 0
  total_check_attempts = 0

  # B5 — when plan_state is supplied, every authoring section must be
  # present (empty dict {} is OK and indicates "authored but no levers
  # yet"; missing key is NOT). The Round-1 fail-fast guards round 1, but
  # later evaluate_plan calls (mid-cascade) must enforce the same
  # invariant.
  if plan_state is not None:
    missing = [s for s in SECTIONS if s not in plan_state]
    if missing:
      from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
        raise_fail_fast,
      )
      from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # type: ignore
        PhaseCode,
      )
      from client_intake_and_finmo.post_intake_diagnostics.fail_fast_codes import (  # type: ignore
        FailFastCode,
      )
      raise_fail_fast(
        conn,
        draft_id=draft_id or "", planning_run_id=planning_run_id or "",
        phase=PhaseCode.EVALUATE_PLAN,
        code=FailFastCode.FAIL_EVALUATE_PLAN_MALFORMED,
        detail=f"plan_state missing required section(s): {missing!r}",
        where="evaluate_plan",
      )
  if in_cascade:
    # Fork A Wall A — the in-LOOP standard: restructurable economic checks
    # on the LIVE finmo (rebuilt by the caller from the mirror each round).
    checks, trajectory, _, check_exception_count = _evaluate_in_cascade(
      finmo_json=finmo_json, emit_diagnostic_fn=emit_diagnostic_fn,
    )
    total_check_attempts = len(checks)
  elif strictness == "mini_finmo":
    if not anchors or not operating_context:
      notes.append("mini_finmo path skipped: missing anchors / operating_context")
    else:
      checks, trajectory, _, check_exception_count = _evaluate_mini_finmo(
        anchors=anchors, operating_context=operating_context,
        emit_diagnostic_fn=emit_diagnostic_fn,
      )
      total_check_attempts = len(checks)
  else:
    if conn is None or not draft_id:
      notes.append("full_acceptance_gate path skipped: conn + draft_id required")
    else:
      checks, trajectory, _, check_exception_count = _evaluate_full_acceptance_gate(
        conn, draft_id=draft_id, planning_run_id=planning_run_id,
        finmo_json=finmo_json, emit_diagnostic_fn=emit_diagnostic_fn,
      )
      total_check_attempts = len(checks)

  # B4 — if every attempted check raised, the evaluator produced nothing
  # useful; fail-fast so the caller doesn't act on synthetic META-failed
  # placeholders. A partial result (at least one successful eval) is
  # still safe — the cascade dispatches the META failure(s) on the
  # exception-marked checks.
  if total_check_attempts > 0 and check_exception_count == total_check_attempts:
    from client_intake_and_finmo.post_intake_diagnostics import (  # type: ignore
      raise_fail_fast,
    )
    from client_intake_and_finmo.post_intake_diagnostics.phase_codes import (  # type: ignore
      PhaseCode,
    )
    from client_intake_and_finmo.post_intake_diagnostics.fail_fast_codes import (  # type: ignore
      FailFastCode,
    )
    raise_fail_fast(
      conn,
      draft_id=draft_id or "", planning_run_id=planning_run_id or "",
      phase=PhaseCode.EVALUATE_PLAN,
      code=FailFastCode.FAIL_EVALUATE_PLAN_EXCEPTION,
      detail=(
        f"all {total_check_attempts} attempted checks raised; no usable result. "
        f"strictness={strictness}"
      ),
      where="evaluate_plan",
    )

  lever_margins: List[LeverMargin] = []
  if conn is not None and draft_id and planning_run_id:
    try:
      lever_margins = _compute_lever_margins(
        conn, draft_id=draft_id, planning_run_id=planning_run_id, plan_state=plan_state or {},
        finmo_json=finmo_json, business_naics_6=business_naics_6,
      )
    except Exception as exc:  # never let margin computation break evaluation
      notes.append(f"lever_margins skipped: {exc!r}")

  all_pass = all(c.passed for c in checks) if checks else False
  worst: Optional[CheckResult] = None
  for c in checks:
    if c.passed or c.distance_to_feasibility is None:
      continue
    if worst is None or (c.distance_to_feasibility < (worst.distance_to_feasibility or 0.0)):
      worst = c
  return EvaluatePlanResult(
    all_pass=all_pass,
    round_number=int(round_number),
    structural_completeness=bool(structural_completeness),
    strictness=strictness,
    checks=checks,
    trajectory=trajectory,
    lever_margins=lever_margins,
    worst_failing_distance=(worst.distance_to_feasibility if worst is not None else None),
    worst_failing_check=(worst.name if worst is not None else None),
    evaluated_at=datetime.now(timezone.utc).isoformat(),
    notes=notes,
  )
