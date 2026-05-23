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
    return float(q20 - (q11 - 0.01)), "fraction"
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
  if check_name == "revenue_not_flat_q1_q10":
    cv = detail.get("coefficient_of_variation"); first = detail.get("q1_to_q10_pct_change")
    cv_margin = (float(cv) - 0.02) if isinstance(cv, (int, float)) else None
    growth_margin = (float(first) - 0.05) if isinstance(first, (int, float)) else None
    candidates = [x for x in (cv_margin, growth_margin) if x is not None]
    return (max(candidates) if candidates else None), "dimensionless"
  if check_name == "net_income_trajectory_viable":
    q11 = detail.get("q11_margin"); q5 = detail.get("q5_margin")
    if isinstance(q11, (int, float)) and isinstance(q5, (int, float)):
      # the check requires q11 >= 0 AND q11 > q5 + 2pp; distance is the worse of the two
      return float(min(q11, (q11 - q5) - 0.02)), "fraction"
    return None, "fraction"
  # For meta and band-source checks, distance isn't meaningful as a scalar.
  return None, None


# ---------------------------------------------------------------------------
# Lever-margin computation (reads bands from the post_intake_cohort_bands
# table populated in Phase 3 step 1).
# ---------------------------------------------------------------------------
def _compute_lever_margins(
  conn,
  *,
  draft_id: str,
  planning_run_id: str,
  plan_state: Dict[str, Any],
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
    section_state = (plan_state or {}).get(section) or {}
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
) -> Tuple[List[CheckResult], List[QuarterTrajectory], Dict[str, Any]]:
  from client_intake_and_finmo.post_intake_gpt_exhaustion_handler.mini_finmo import (  # type: ignore
    compute_trajectory_from_anchors,
  )
  raw = compute_trajectory_from_anchors(anchors, operating_context)
  checks_dict = (raw.get("viability_checks") or {})
  violations = raw.get("stage_ramp_violations") or []
  results: List[CheckResult] = []
  for name, verdict in checks_dict.items():
    if name == "all_pass":
      continue
    if name in _CASH_RELATED_CHECKS:
      continue  # cash is a separate downstream process — filtered from session output
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
  return results, trajectory, raw


def _evaluate_full_acceptance_gate(
  conn,
  *,
  draft_id: str,
  planning_run_id: Optional[str],
  finmo_json: Optional[Dict[str, Any]],
) -> Tuple[List[CheckResult], List[QuarterTrajectory], Dict[str, Any]]:
  from client_intake_and_finmo.post_intake_acceptance.gate import (  # type: ignore
    verify_run_acceptance,
  )
  verdict = verify_run_acceptance(conn, draft_id=draft_id, planning_run_id=planning_run_id)
  results: List[CheckResult] = []
  for c in (verdict.get("checks") or []):
    name = str(c.get("name") or "")
    if name in _CASH_RELATED_CHECKS:
      continue  # cash is a separate downstream process — filtered from session output
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
  trajectory = _trajectory_from_finmo(finmo_json)
  return results, trajectory, verdict


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
  round_number: int = 1,
  # Inputs the mini_finmo path needs (caller supplies what it has):
  anchors: Optional[Dict[str, Any]] = None,
  operating_context: Optional[Dict[str, Any]] = None,
  # Input the full-gate trajectory wants:
  finmo_json: Optional[Dict[str, Any]] = None,
) -> EvaluatePlanResult:
  """Run the standards check and return a structured result.

  Strictness selection is the caller's call (the session driver in step 5
  tracks section-authored flags). ``structural_completeness=True`` selects
  the full 16-check acceptance gate; False selects the lighter mini_finmo
  viability + stage_ramp coherence set. Both produce the same shape.
  """
  notes: List[str] = []
  strictness = "full_acceptance_gate" if structural_completeness else "mini_finmo"
  checks: List[CheckResult] = []
  trajectory: List[QuarterTrajectory] = []
  if strictness == "mini_finmo":
    if not anchors or not operating_context:
      notes.append("mini_finmo path skipped: missing anchors / operating_context")
    else:
      checks, trajectory, _ = _evaluate_mini_finmo(anchors=anchors, operating_context=operating_context)
  else:
    if conn is None or not draft_id:
      notes.append("full_acceptance_gate path skipped: conn + draft_id required")
    else:
      checks, trajectory, _ = _evaluate_full_acceptance_gate(
        conn, draft_id=draft_id, planning_run_id=planning_run_id, finmo_json=finmo_json,
      )

  lever_margins: List[LeverMargin] = []
  if conn is not None and draft_id and planning_run_id:
    try:
      lever_margins = _compute_lever_margins(
        conn, draft_id=draft_id, planning_run_id=planning_run_id, plan_state=plan_state or {},
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
