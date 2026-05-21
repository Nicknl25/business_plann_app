"""Phase 9 P3 — Outer restoration loop.

Iterates the 4 solver targets in priority order. For each target, builds
the per-quarter ramp from the cohort band shape (Q1 = current intake,
Q11 = viability binding, Q20 = industry mature p50) and calls
`solve_for_target`. After each target, re-evaluates the realism gate's
viability trajectory checks; exits early when all viability conditions
satisfied.

Iteration discipline (strict, per directive):

  Outer loop: up to 5 passes until either
    (a) every viability trajectory check passes, OR
    (b) every operating driver across all 4 targets is pinned at its
        bound in the needed direction (true exhaustion).

  Single outer pass when viability still failing is unacceptable.
  Worst-case walk: 4 targets × 10 inner × 5 outer = 200 iterations of
  sub-second algebra.

`exhausted` is returned ONLY when:
  - Every operating driver in every target's driver list is pinned at
    its bound, AND
  - Viability still failing.

Lesser conditions (a driver still has slack, a target was skipped, an
inner loop exited early) MUST iterate further. Per-driver bound
diagnostics are returned so the user can identify whether the cohort
tolerances are too tight, the operator's intake has structural issues,
or stage shift is needed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_target_solver.target_solver import (
  CashPassLeverViolation,
  DriverBound,
  HORIZON_QUARTERS_DEFAULT,
  SolverResult,
  SolverStatus,
  _CASH_PASS_OWNED_LEVER_IDS,
  solve_for_target,
)


# Targets in priority order. The outer loop solves them in sequence;
# after each, re-evaluates viability and exits if all conditions met.
#
# Phase 9 P3 — gross_margin_percent REMOVED as a solver target. It is
# mathematically downstream of COGS% (gross_margin = 1 - cogs%) and
# the cohort band is 1 - cogs_percent_band. COGS% is already a Tier 1
# driver in ebitda_margin's primary_levers, so whatever COGS% lands at
# to satisfy ebitda viability, gross_margin reflects automatically.
# Keeping gross_margin as a separate target created cross-target
# conflict on revenue::Unit Price (gm solver compressed price-down,
# ebitda solver wanted price-up). The trajectory check
# gross_margin_supports_ebitda_recovery (Q5->Q11 movement test) stays
# active in the realism gate; the band-check row is gate_kind="skip".
TARGETS_IN_PRIORITY_ORDER: Tuple[str, ...] = (
  "ebitda_margin",
  "current_assets_minus_cash",
  "current_liabilities_to_revenue",
)


# Viability trajectory checks. The restoration loop's "landed" exit
# condition: all of these pass on the post-solve realism evaluation.
_VIABILITY_TRAJECTORY_METRICS: Tuple[str, ...] = (
  "ebitda_positive_by_q11",
  "ebitda_recovery_trend_q5_q11",
  "loss_window_funded_through_q5",
  # Phase 9 P3.8 — renamed from no_post_recovery_relapse_q11_q20. The
  # old formula (min EBITDA Q11..Q20 >= 0) was a positivity test, not
  # a relapse test. The new check enforces Q20 >= Q11 - 0.01.
  "ebitda_margin_q20_holds_or_improves_vs_q11",
  "gross_margin_supports_ebitda_recovery",
  "fixed_cost_burden_reduced_or_scaled_by_q11",
)

# Hard cap on outer passes per directive.
MAX_OUTER_PASSES = 5


# Phase 9 P3 case (b) — conservative fallback multipliers for revenue-side
# levers (Unit Price, Capacity, Utilization). There is no NAICS cohort
# for these absolute-unit levers; bounds derive from the operator-stated
# current value plus a documented multiplier. NOT widened to make any
# specific business land — these are the doctrine's standing fallback.
#
# Unit Price: ±15% / +20% asymmetric — pricing power is bounded above
# by competitive market position; downside is tighter (operators rarely
# cut prices below a floor without harming brand).
_REVENUE_PRICE_LOWER_FRAC = 0.85
_REVENUE_PRICE_UPPER_FRAC = 1.20

# Capacity: 0% downside, +50% upside — plant/equipment/headcount can
# expand within a planning horizon but seldom contracts; closing a
# location is a structural change outside the solver's authority.
_REVENUE_CAPACITY_LOWER_FRAC = 1.00
_REVENUE_CAPACITY_UPPER_FRAC = 1.50

# Utilization: bounded below by current operator state (no manufactured
# slack), bounded above by 0.84 — strictly BELOW FINMO's
# capacity_utilization_ceiling = 0.85 to avoid triggering
# _shape_revenue_capacity_and_utilization's one-shot capacity expansion
# branch, which would (a) auto-expand capacity once and freeze it for
# the rest of the horizon (breaking revenue_not_flat_q1_q10), and
# (b) clip utilization back to post_expansion_utilization = 0.70,
# silently UNDOING the solver's utilization writes and leaving the
# lever effectively pinned at lower bound on every subsequent
# iteration. Stay below the ceiling so writes hold.
_REVENUE_UTILIZATION_UPPER = 0.84


class RestorationStatus(str, Enum):
  LANDED = "landed"
  EXHAUSTED = "exhausted"
  ITERATING_STILL = "iterating_still"
  FAILED = "failed"


# Phase 9 P3.7 — Scoped GPT authority. The restoration loop's
# forward-looking exhaustion semantics classify which lever set GPT
# is authorized to author on the handler invocation.
class HandlerScope(str, Enum):
  # Handler authors all 7 P&L drivers + all 5 working capital drivers.
  # Used when any forecast-failing realism metric has at least one P&L
  # primary_lever (matches the P3.6 behavior used for Sunny).
  PNL_PATH = "pnl_path"
  # Handler authors only working capital drivers (P&L is left at the
  # deterministic-solver values). Used when every forecast-failing
  # realism metric's primary_levers are all in the WC set.
  BS_ONLY_PATH = "bs_only_path"


# Lever-set membership for the trigger classifier. Mirrors the
# post_intake_gpt_exhaustion_handler constants intentionally — these
# are the levers the handler has authority over. Source-of-truth
# duplication is acceptable here because importing the handler module
# would introduce a circular-ish dependency (handler imports
# restoration_loop via the orchestrator); the trigger logic is
# universal across NAICS / stage so the constants stay synchronised by
# convention.
#
# Phase 9 P3.32 K1 (F1+F2): "expenses::Payroll" removed in lockstep
# with handler.py GPT_AUTHORED_LEVER_IDS. Handler C is the canonical
# Payroll writer; the trigger classifier must agree so that
# payroll-touching realism failures do not route to the exhaustion
# handler. P3.31 Leak A closure.
_GPT_AUTHORED_PNL_LEVER_IDS: frozenset = frozenset({
  "revenue::Unit Price",
  "revenue::Capacity",
  "revenue::Utilization",
  "expenses::Cost of Goods Sold",
  "expenses::Marketing",
  "expenses::General & Administrative",
  "expenses::Research & Development",
})
_GPT_AUTHORED_WC_LEVER_IDS: frozenset = frozenset({
  "balance_sheet::Accounts Receivable Days",
  "balance_sheet::Accounts Payable Days",
  "balance_sheet::Inventory Days",
  "balance_sheet::Deferred Revenue (% of Revenue)",
  "balance_sheet::Prepaid Expenses (% of Revenue)",
})
_GPT_AUTHORED_ALL: frozenset = _GPT_AUTHORED_PNL_LEVER_IDS | _GPT_AUTHORED_WC_LEVER_IDS


@dataclass
class RestorationResult:
  status: RestorationStatus
  outer_passes_used: int
  per_pass_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
  final_viability_state: Dict[str, bool] = field(default_factory=dict)
  drivers_at_bounds_summary: Dict[str, str] = field(default_factory=dict)
  per_target_results: List[Dict[str, Any]] = field(default_factory=list)
  q11_ebitda_margin: Optional[float] = None
  reason: str = ""
  # Phase 9 P3.7 — handler scope set by the forward-looking trigger
  # classifier. Populated only when status == EXHAUSTED. None on LANDED.
  scope: Optional[HandlerScope] = None
  # Failing realism metrics that triggered the EXHAUSTED verdict.
  # Each entry: {"metric_key", "quarter_index", "actual_value",
  # "effective_min", "effective_max", "primary_levers"}. Used by the
  # handler to tell GPT which specific metrics need fixing.
  failing_metrics: List[Dict[str, Any]] = field(default_factory=list)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status.value if isinstance(self.status, RestorationStatus) else str(self.status),
      "outer_passes_used": self.outer_passes_used,
      "per_pass_diagnostics": list(self.per_pass_diagnostics),
      "final_viability_state": dict(self.final_viability_state),
      "drivers_at_bounds_summary": dict(self.drivers_at_bounds_summary),
      "per_target_results": list(self.per_target_results),
      "q11_ebitda_margin": self.q11_ebitda_margin,
      "reason": self.reason,
      "scope": (
        self.scope.value
        if isinstance(self.scope, HandlerScope)
        else (self.scope or None)
      ),
      "failing_metrics": list(self.failing_metrics),
    }


# ----------------------------------------------------------------------------
# Helpers — viability evaluation, ramp generation, driver list assembly.
# ----------------------------------------------------------------------------


def _evaluate_viability(
  *,
  finmo_json: Dict[str, Any],
) -> Dict[str, bool]:
  """Evaluate the 6 viability trajectory checks. True = pass.

  Reads the formulas from the realism formulas registry (single source
  of truth — the validator uses the same registry).
  """
  from client_intake_and_finmo.post_intake_realism.formulas import (  # type: ignore
    evaluate_realism_formula,
  )
  formula_keys = {
    "ebitda_positive_by_q11": "trajectory_ebitda_positive_at_quarter",
    "ebitda_recovery_trend_q5_q11": "trajectory_ebitda_recovery_trend",
    "loss_window_funded_through_q5": "trajectory_loss_window_funded",
    "ebitda_margin_q20_holds_or_improves_vs_q11": "trajectory_ebitda_q20_holds_or_improves_vs_q11",
    "gross_margin_supports_ebitda_recovery": "trajectory_gross_margin_supports_recovery",
    "fixed_cost_burden_reduced_or_scaled_by_q11": "trajectory_fixed_cost_burden_at_industry_floor",
  }
  # Phase 9 P3.10 Commit 3 — formula errors no longer flip viability
  # to False. A formula crash during viability evaluation is a code bug
  # — it must propagate so the solver doesn't route to EXHAUSTED on a
  # phantom failure (the audit's #16 finding: "error becomes business
  # verdict").
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )
  test_mode_v = convergence_test_mode_enabled()
  out: Dict[str, bool] = {}
  for metric, fkey in formula_keys.items():
    try:
      v = evaluate_realism_formula(
        fkey, model_input_json={}, finmo_json=finmo_json, quarter_index=None,
      )
    except Exception as exc:
      if test_mode_v:
        raise PostIntakePreconditionFailed(
          operation="restoration_loop_viability_formula_failed",
          pipeline_stage="post_intake_target_seeking_restoration_loop",
          expected=f"realism trajectory formula {fkey} evaluates without raising",
          actual=f"{type(exc).__name__}: {str(exc)[:200]}",
          details={"viability_metric": metric, "formula_key": fkey},
          cause=exc,
        ) from exc
      v = None
    if v is None:
      out[metric] = False
    else:
      out[metric] = float(v) >= 0.0
  return out


_PROFITABILITY_FLOOR_METRICS_FOR_RAMP = ("gross_margin_percent", "ebitda_margin")


def _planning_mode_floor_per_q(
  *,
  target_metric: str,
  planning_mode: Optional[str],
  horizon: int,
) -> List[float]:
  """Per-quarter floor that the realism gate's planning_mode_policy
  applies. Mirrors the realism validator's _profitability_floor_for_quarter
  branching (Q1-Q4 / Q5-Q10 / Q11-Q20 buckets) so the solver's target
  ramp respects the same floor the gate enforces. None floors decay to
  0.0; non-profitability targets get a flat 0.0 floor (no per-quarter
  adjustment).
  """
  floor_per_q = [0.0] * horizon
  if target_metric not in _PROFITABILITY_FLOOR_METRICS_FOR_RAMP:
    return floor_per_q
  policy: Optional[Dict[str, Any]] = None
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_planning_mode_policy_for,
    )
    policy = post_intake_planning_mode_policy_for(planning_mode) if planning_mode else None
  except Exception:
    policy = None
  if not isinstance(policy, dict):
    return floor_per_q
  def _val(key: str) -> float:
    raw = policy.get(key)
    if raw is None:
      return 0.0
    try:
      return float(raw)
    except Exception:
      return 0.0
  q1_q4 = _val("profitability_floor_q1_q4")
  q5_q10 = _val("profitability_floor_q5_q10")
  q11_q20 = _val("profitability_floor_q11_q20")
  for q in range(horizon):
    quarter_index = q + 1
    if quarter_index <= 4:
      floor_per_q[q] = q1_q4
    elif quarter_index <= 10:
      floor_per_q[q] = q5_q10
    else:
      floor_per_q[q] = q11_q20
  return floor_per_q


# Phase 9 P3 case (b) iter 4 — planning-mode tolerance map. When the
# active planning_mode lists the metric's below-band issue code in its
# tolerated_issue_codes, the realism gate downgrades per-quarter
# below-band hits to warn (band_source includes
# "_tolerated_per_planning_mode"). The ramp builder honours the same
# tolerance: Q1 anchor falls back to the OPERATOR-stated intake value
# (no floor clamp) so the solver gets room to ramp drivers Q1->Q11
# rather than pinning all drivers at bound trying to lift Q1 to floor.
# The Q11 binding (>= 0) still applies — universal viability rule
# does not bend.
_METRIC_TOLERATED_ISSUE_CODE: Dict[str, str] = {
  "ebitda_margin": "mature_loss_state",
  "gross_margin_percent": "early_revenue_under_run_rate",
}


def _planning_mode_tolerates_q1_loss(
  *, target_metric: str, planning_mode: Optional[str]
) -> bool:
  issue_code = _METRIC_TOLERATED_ISSUE_CODE.get(target_metric)
  if not issue_code or not planning_mode:
    return False
  try:
    from client_intake_and_finmo.post_intake_mapping import (  # type: ignore
      post_intake_planning_mode_policy_for,
    )
    policy = post_intake_planning_mode_policy_for(planning_mode)
  except Exception:
    return False
  if not isinstance(policy, dict):
    return False
  tolerated = policy.get("tolerated_issue_codes") or []
  if not isinstance(tolerated, (list, tuple)):
    return False
  return any(str(code or "").strip().lower() == issue_code for code in tolerated)


def _build_target_ramp(
  *,
  target_metric: str,
  current_metric_per_q: List[float],
  band_target: float,
  band_min: float,
  horizon: int,
  planning_mode_floor_per_q: Optional[List[float]] = None,
  planning_mode: Optional[str] = None,
) -> List[float]:
  """Build the 20-quarter target ramp. Q1 starts at max(current intake
  state, band_min) so the ramp respects the realism gate's per-quarter
  band floor; Q20 lands at industry typical (cohort p50 / band_target);
  Q11 binds the viability constraint (>= 0) for profitability metrics.

  Phase 9 P3 iter 2 — for gross_margin_percent / ebitda_margin, every
  ramp quarter is clamped to >= max(0.0, band_min). The realism gate
  applies a planning_mode_floor of 0.0 on effective_min for these
  profitability metrics, so a ramp that lets Q1..Q10 stay negative
  (linear interpolation from a negative current value) leaves the
  solver landing metrics in [-0.25, +0.04] which the gate rejects.
  Forcing the ramp to start at the band floor pushes the solver to
  drive Q1..Q10 metrics to >= 0 (or hit BOUND_PINNED honestly when
  drivers exhaust). Working-capital metrics (current_assets_minus_cash,
  current_liabilities_to_revenue) keep the linear interpolation since
  they have no positive-only viability constraint.
  """
  q1_current = float(current_metric_per_q[0]) if current_metric_per_q else float(band_target)
  q20_target = float(band_target)
  pm_floor = planning_mode_floor_per_q if isinstance(planning_mode_floor_per_q, list) else [0.0] * horizon
  is_profit_metric = target_metric in _PROFITABILITY_FLOOR_METRICS_FOR_RAMP
  q1_loss_tolerated = _planning_mode_tolerates_q1_loss(
    target_metric=target_metric, planning_mode=planning_mode,
  )

  if not is_profit_metric:
    # Working-capital / non-profitability targets: linear ramp Q1 -> Q20.
    ramp = [0.0] * horizon
    for q in range(horizon):
      frac = q / max(1, horizon - 1)
      ramp[q] = (1.0 - frac) * q1_current + frac * q20_target
    return ramp

  # Profitability metrics (gross_margin_percent, ebitda_margin) — 2-phase
  # ramp shaped by the universal viability doctrine:
  #   Q1..Q4    >= floor_q1_q4 + safety
  #   Q5..Q10   >= floor_q5_q10 + safety
  #   Q11       >= max(q20_target, Q5_floor + recovery_delta + safety)
  #   Q12..Q20  linear Q11 -> q20_target (no relapse: must stay >= 0)
  # This bakes in the recovery requirement so Q11 is always >= Q5 + the
  # 0.02 doctrine recovery delta, regardless of where q20_target lands.
  safety = 0.005   # 50 bps above floor to avoid knife-edge tolerance misses
  recovery_delta = 0.020  # doctrine: ebitda_recovery_trend_q5_q11 requires
  recovery_delta_safety = 0.005  # +50 bps margin above the doctrine threshold
  band_floor = max(0.0, float(band_min))

  def _floor_for_quarter(q_idx_zero_based: int) -> float:
    pm_q = float(pm_floor[q_idx_zero_based]) if q_idx_zero_based < len(pm_floor) else 0.0
    base = max(band_floor, pm_q)
    return base + safety if base > 0.0 else safety

  if q1_loss_tolerated and q1_current < _floor_for_quarter(0):
    # Planning mode tolerates Q1 loss for this metric — anchor at the
    # operator's intake state. Without this, the solver pins all
    # drivers at bound trying to lift Q1 from intake (e.g. -0.40)
    # straight to floor (e.g. +0.005), exhausting Q1's authority and
    # producing flat ramp shapes for Q1..Q11. With anchor at intake,
    # the solver spreads the lift across Q1..Q11 (smaller deltas at
    # Q1 -> larger at Q11), which produces a natural revenue ramp
    # via varying per-quarter solver writes.
    q1_anchor = q1_current
  else:
    q1_anchor = max(q1_current, _floor_for_quarter(0))
  # Q11 binding: max( cohort q20_target, Q5_floor + recovery_delta + safety )
  q5_floor = _floor_for_quarter(4)  # Q5 = index 4
  q11_binding = max(q20_target, q5_floor + recovery_delta + recovery_delta_safety)

  ramp = [0.0] * horizon
  # Phase 1: Q1 (idx 0) -> Q11 (idx 10) linear from q1_anchor to q11_binding.
  for q in range(min(11, horizon)):
    frac = q / 10.0 if horizon > 10 else q / max(1, horizon - 1)
    ramp[q] = (1.0 - frac) * q1_anchor + frac * q11_binding
  # Phase 2: Q11 (idx 10) -> Q20 (idx horizon-1) linear from q11_binding to q20_target.
  if horizon > 11:
    for q in range(11, horizon):
      frac = (q - 10) / max(1, horizon - 1 - 10)
      ramp[q] = (1.0 - frac) * q11_binding + frac * q20_target

  # Final per-quarter floor enforcement. When the planning mode
  # tolerates Q1-Q4 losses for this metric, skip the floor for
  # Q1..Q4; the loss window is doctrine-permitted. Q5+ floors and
  # the Q11 binding still apply.
  for q in range(horizon):
    if q < 4 and q1_loss_tolerated:
      continue
    floor_q = _floor_for_quarter(q)
    if ramp[q] < floor_q:
      ramp[q] = floor_q
  # Defensive: Q11 must be >= Q5 + recovery_delta after all clamping.
  if horizon > 10:
    required_q11 = ramp[4] + recovery_delta + recovery_delta_safety
    if ramp[10] < required_q11:
      ramp[10] = required_q11
      # Re-interpolate Q12..Q20 from the bumped Q11.
      if horizon > 11:
        for q in range(11, horizon):
          frac = (q - 10) / max(1, horizon - 1 - 10)
          q20_clamped = max(q20_target, ramp[10])
          ramp[q] = (1.0 - frac) * ramp[10] + frac * q20_clamped
      # And re-walk to honor floors again.
      for q in range(11, horizon):
        floor_q = _floor_for_quarter(q)
        if ramp[q] < floor_q:
          ramp[q] = floor_q
  return ramp


def _resolve_band_for_target(
  *,
  target_metric: str,
  business_naics_6: Optional[str],
) -> Tuple[float, float, float]:
  """Resolve (band_min, band_target, band_max) for a target via the
  industry baseline resolver. Falls back to the realism lookup row's
  Phase 9 P3 generic-default for the new metrics, which the resolver
  already wires.
  """
  from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
    post_intake_industry_baseline_for_naics,
  )
  # Phase 9 P3.10 Commit 3 — band resolver exception swallow removed
  # under test mode. Audit #18: NAICS baseline service outage silently
  # strips levers from the driver list, leaving restoration with zero
  # authority. Under test mode the resolver failure now propagates.
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )
  payload: Optional[Dict[str, Any]] = None
  try:
    payload = post_intake_industry_baseline_for_naics(
      metric_key=target_metric, naics_6=business_naics_6 or "",
    )
  except Exception as exc:
    if convergence_test_mode_enabled():
      raise PostIntakePreconditionFailed(
        operation="restoration_loop_band_resolver_baseline_lookup_failed",
        pipeline_stage="post_intake_target_seeking_restoration_loop",
        expected="post_intake_industry_baseline_for_naics returns payload (or None for no-coverage)",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={
          "target_metric": target_metric,
          "business_naics_6": business_naics_6,
        },
        cause=exc,
      ) from exc
    payload = None
  if not payload:
    return (0.0, 0.0, 0.0)
  band_min = payload.get("benchmark_min")
  band_target = payload.get("benchmark_target")
  band_max = payload.get("benchmark_max")
  if band_min is None and band_target is not None:
    band_min = float(band_target) * 0.8
  if band_max is None and band_target is not None:
    band_max = float(band_target) * 1.2
  if band_target is None:
    if band_min is not None and band_max is not None:
      band_target = (float(band_min) + float(band_max)) / 2.0
    else:
      band_target = 0.0
  return (float(band_min or 0.0), float(band_target or 0.0), float(band_max or 0.0))


# ----------------------------------------------------------------------------
# Driver list + bounds assembly.
# ----------------------------------------------------------------------------


# Per-lever-kind metadata. Maps lever_id (or a prefix) to (NAICS metric_key
# the cohort cascade uses for the bound, driver_kind tag used by the solver).
# This is the single source of truth for "how do I look up this lever's
# bound in the cohort tables." Adding a new lever to a target's
# primary_levers in the realism config picks it up here automatically when
# the lever_id matches a known prefix; otherwise it falls through to the
# revenue-side fallback or is dropped with a no_band_resolved diagnostic.
_LEVER_TO_NAICS_METRIC_KEY: Dict[str, str] = {
  "expenses::Cost of Goods Sold":           "cogs_percent_of_revenue",
  "expenses::Marketing":                    "marketing_percent_of_revenue",
  "expenses::Research & Development":       "r_and_d_percent_of_revenue",
  "expenses::General & Administrative":     "sga_percent_of_revenue",
  "expenses::Payroll":                      "payroll_percent_of_revenue",
  "expenses::Lease":                        "rent_percent_of_revenue",
  "balance_sheet::Accounts Receivable Days":      "ar_days_dso",
  "balance_sheet::Accounts Payable Days":         "ap_days_dpo",
  "balance_sheet::Inventory Days":                "inventory_days",
  "balance_sheet::Prepaid Expenses (% of Revenue)":   "prepaid_expenses_percent_of_revenue",
  "balance_sheet::Deferred Revenue (% of Revenue)":   "deferred_revenue_percent_of_revenue",
}


def _q1_revenue(model_input: Dict[str, Any], build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]]) -> float:
  """Q1 revenue from the current model_input via FINMO build. Used as
  the scaling base for payroll / lease quarter-currency bounds.
  """
  try:
    finmo = build_finmo(copy.deepcopy(model_input or {}))
  except Exception:
    return 0.0
  for row in (finmo or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      if int(float(row.get("quarter_index") or 0)) == 1:
        return float(row.get("revenue") or 0.0)
    except Exception:
      continue
  return 0.0


def _current_revenue_lever_value(
  model_input: Dict[str, Any], lever_id: str, horizon: int,
) -> Optional[float]:
  """Read the operator-stated current value for a revenue-side lever
  (Unit Price / Capacity / Utilization). Averages across LOB rows when
  the shortcut maps to multiple model_input rows. Reads live Q1
  (index 1 in the [stub, live_q1, ...] layout); returns None when
  the lever is not present.
  """
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _find_rows_for_lever,
  )
  rows = _find_rows_for_lever(model_input or {}, lever_id)
  if not rows:
    return None
  values: List[float] = []
  for row in rows:
    vals = row.get("values") or []
    if len(vals) >= 2 and vals[1] is not None:
      try:
        v = float(vals[1])
        if v > 0:
          values.append(v)
      except Exception:
        pass
  if not values:
    return None
  return sum(values) / len(values)


def _driver_bounds_for_target(
  *,
  target_metric: str,
  business_naics_6: Optional[str],
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  horizon: int = HORIZON_QUARTERS_DEFAULT,
) -> Dict[str, DriverBound]:
  """Resolve per-driver (lower, upper) bounds for the target metric's
  primary_levers list. Single source of truth: the realism lookup row
  for ``target_metric`` — what the realism gate evaluates against is
  what the solver tries to land.

  Per-lever-kind dispatch (driven by ``_driver_kind_for_lever``):

    percent_of_revenue (cogs%, marketing%, r_and_d%, sga%, prepaid%,
                        deferred%): bounds from the corresponding
                        cohort *_percent_of_revenue row.
    days (AR/AP/Inventory days): bounds from the corresponding cohort
                        *_days row.
    quarter_currency (Payroll, Lease): bounds = (cohort
                        *_percent_of_revenue band) × Q1 revenue,
                        producing dollar-denominated lower/upper.
                        bound_source = "payroll_percent_band_scaled".
    revenue_unit (Unit Price, Capacity, Utilization): bounds from
                        operator-stated current value × the named
                        conservative fallback multipliers. There is no
                        NAICS cohort for absolute price / capacity /
                        utilization. bound_source =
                        "hardcoded_fallback_no_data".

  Cash-pass-owned levers are skipped (cash strategy owns those
  end-to-end). Levers without resolvable bounds are dropped with no
  error — the solver simply has no authority over them.
  """
  from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
    post_intake_industry_baseline_for_naics,
  )
  from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
    post_intake_finalize_realism_check_for_metric,
  )
  from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
    _driver_kind_for_lever,
  )

  realism_row = post_intake_finalize_realism_check_for_metric(target_metric) or {}
  primary_levers = list(realism_row.get("primary_levers") or [])
  bounds: Dict[str, DriverBound] = {}

  if not primary_levers:
    return bounds

  # Compute Q1 revenue once (used for quarter_currency lever bounds).
  q1_revenue_cached: Optional[float] = None

  # Phase 9 P3 case (b) — when the cohort cascade returns a band_target
  # but no min/max (e.g., derived_CBP_SOI_rollup payroll rows), fan out
  # to a ±30% envelope around the target. Documented margin, not magic;
  # matches the validator's tolerance-around-target convention.
  _TARGET_ONLY_FALLBACK_LOWER_FRAC = 0.70
  _TARGET_ONLY_FALLBACK_UPPER_FRAC = 1.30

  def _band(metric_key: str) -> Optional[Tuple[float, float, str]]:
    # Phase 9 P3.10 Commit 3 — same band-resolver fix as
    # _resolve_band_for_target. Service outage no longer silently
    # returns None (which strips the lever).
    from client_intake_and_finmo.fail_fast.common import (  # type: ignore
      PostIntakePreconditionFailed,
      convergence_test_mode_enabled,
    )
    try:
      payload = post_intake_industry_baseline_for_naics(
        metric_key=metric_key, naics_6=business_naics_6 or "",
      )
    except Exception as exc:
      if convergence_test_mode_enabled():
        raise PostIntakePreconditionFailed(
          operation="restoration_loop_driver_bound_baseline_lookup_failed",
          pipeline_stage="post_intake_target_seeking_restoration_loop",
          expected="post_intake_industry_baseline_for_naics returns payload (or None for no-coverage)",
          actual=f"{type(exc).__name__}: {str(exc)[:200]}",
          details={
            "lookup_metric_key": metric_key,
            "target_metric": target_metric,
            "business_naics_6": business_naics_6,
          },
          cause=exc,
        ) from exc
      return None
    bmin = payload.get("benchmark_min") if payload else None
    bmax = payload.get("benchmark_max") if payload else None
    btarget = payload.get("benchmark_target") if payload else None
    src = str((payload or {}).get("data_source") or "unknown").strip()
    if bmin is None and bmax is None and btarget is None:
      return None
    if bmin is None and bmax is None and btarget is not None:
      # Target-only band — fan out around target.
      bmin = float(btarget) * _TARGET_ONLY_FALLBACK_LOWER_FRAC
      bmax = float(btarget) * _TARGET_ONLY_FALLBACK_UPPER_FRAC
      src = f"{src}_target_only_envelope"
    if bmin is None:
      bmin = float(bmax) * 0.5 if bmax is not None else 0.0
    if bmax is None:
      bmax = float(bmin) * 1.5
    return (float(bmin), float(bmax), src)

  for lever_id in primary_levers:
    lid = str(lever_id or "").strip()
    if not lid:
      continue
    if lid in _CASH_PASS_OWNED_LEVER_IDS:
      # Cash strategy owns these end-to-end; solver MUST NOT touch.
      continue

    driver_kind = _driver_kind_for_lever(lid)

    if driver_kind == "percent_of_revenue":
      naics_metric = _LEVER_TO_NAICS_METRIC_KEY.get(lid)
      if not naics_metric:
        continue
      band = _band(naics_metric)
      if band is None:
        continue
      bmin, bmax, src = band
      bounds[lid] = DriverBound(
        lower=bmin, upper=bmax, driver_kind="percent_of_revenue",
        bound_source=f"cohort_{src}" if src and not src.startswith("cohort_") else src,
      )
      continue

    if driver_kind == "days":
      naics_metric = _LEVER_TO_NAICS_METRIC_KEY.get(lid)
      if not naics_metric:
        continue
      band = _band(naics_metric)
      if band is None:
        continue
      bmin, bmax, src = band
      bounds[lid] = DriverBound(
        lower=bmin, upper=bmax, driver_kind="days",
        bound_source=f"cohort_{src}" if src and not src.startswith("cohort_") else src,
      )
      continue

    if driver_kind == "quarter_currency":
      # Payroll / Lease — scale the percent-of-revenue cohort band by
      # current Q1 revenue to produce dollar bounds.
      naics_metric = _LEVER_TO_NAICS_METRIC_KEY.get(lid)
      if not naics_metric:
        continue
      band = _band(naics_metric)
      if band is None:
        continue
      bmin_pct, bmax_pct, src = band
      if q1_revenue_cached is None:
        q1_revenue_cached = _q1_revenue(model_input, build_finmo)
      r = float(q1_revenue_cached or 0.0)
      if r <= 0.0:
        continue
      bounds[lid] = DriverBound(
        lower=bmin_pct * r, upper=bmax_pct * r, driver_kind="quarter_currency",
        bound_source=f"payroll_percent_band_scaled (cohort_src={src}, Q1_revenue={r:.2f})",
      )
      continue

    if driver_kind == "revenue_unit":
      cur = _current_revenue_lever_value(model_input, lid, horizon)
      if cur is None or cur <= 0.0:
        continue
      if "Unit Price" in lid:
        lower = cur * _REVENUE_PRICE_LOWER_FRAC
        upper = cur * _REVENUE_PRICE_UPPER_FRAC
      elif "Capacity" in lid:
        lower = cur * _REVENUE_CAPACITY_LOWER_FRAC
        upper = cur * _REVENUE_CAPACITY_UPPER_FRAC
      elif "Utilization" in lid:
        lower = cur
        upper = max(cur, _REVENUE_UTILIZATION_UPPER)
      else:
        # Unknown revenue lever — skip rather than guess.
        continue
      bounds[lid] = DriverBound(
        lower=lower, upper=upper, driver_kind="revenue_unit",
        bound_source=(
          f"hardcoded_fallback_no_data (current={cur:.4f}, "
          f"lower_frac={lower/cur:.2f}, upper_frac={upper/cur:.2f})"
        ),
      )
      continue

    # Unknown driver_kind — skip with no entry. Solver simply has no
    # authority over levers it cannot bound.

  return bounds


# ----------------------------------------------------------------------------
# The outer restoration loop.
# ----------------------------------------------------------------------------


def _classify_forecast_exhaustion(
  *,
  model_input: Dict[str, Any],
  post_finmo: Dict[str, Any],
  business_naics_6: Optional[str],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  planning_mode: Optional[str],
  solver_targets_payload: Optional[Dict[str, Any]],
) -> Tuple[Optional[HandlerScope], List[Dict[str, Any]]]:
  """Phase 9 P3.7 — Forward-looking exhaustion classifier.

  Runs the realism validator on the post-restoration FINMO state and
  inspects its hard_fail_violations. Filters to violations where every
  primary_lever is in the GPT-authored superset (P&L + WC). Returns:
    - (None, []) when no GPT-authorable metric forecasts to hard-fail
      (restoration is genuinely LANDED; handler does not fire).
    - (HandlerScope.PNL_PATH, [...]) when any failing metric has a
      primary_lever in the P&L set (GPT authors all 12 drivers).
    - (HandlerScope.BS_ONLY_PATH, [...]) when every failing metric's
      primary_levers are entirely in the WC set (GPT authors only WC
      drivers; the deterministic solver's P&L work is left alone).

  Universal-app: scope is derived from generic signals (realism config
  primary_levers + post-restoration FINMO metric values + the validator's
  own band-resolution cascade). No NAICS / archetype / stage branching.

  Defensive: if the validator raises or returns no hard_fail_violations,
  treats as no-exhaustion. The realism gate downstream will catch the
  same failures the validator would have reported, so the worst case is
  a missed EXHAUSTED → handler trigger (i.e. the acceptance gate fails
  later, same outcome the system had before P3.7).
  """
  # Phase 9 P3.10 Commit 3 — classifier exception swallows removed
  # under test mode. Audit #17 finding: silent (None, []) return on
  # validator failure routes to default HandlerScope.PNL_PATH or skips
  # handler entirely on LANDED path — classifier correctness IS the
  # run's correctness.
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )
  test_mode_cls = convergence_test_mode_enabled()
  try:
    from client_intake_and_finmo.post_intake_realism.validator import (  # type: ignore
      validate_industry_realism_bands,
    )
  except Exception as exc:
    if test_mode_cls:
      raise PostIntakePreconditionFailed(
        operation="forecast_classifier_validator_import_failed",
        pipeline_stage="post_intake_target_seeking_restoration_loop",
        expected="post_intake_realism.validator module importable",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={},
        cause=exc,
      ) from exc
    return None, []
  try:
    payload = validate_industry_realism_bands(
      model_input_json=model_input or {},
      finmo_json=post_finmo or {},
      business_naics_6=business_naics_6,
      ops_json=ops_json or {},
      financials_json=financials_json or {},
      solver_input_targets_payload=solver_targets_payload,
      planning_mode=planning_mode,
    )
  except Exception as exc:
    if test_mode_cls:
      raise PostIntakePreconditionFailed(
        operation="forecast_classifier_validator_call_failed",
        pipeline_stage="post_intake_target_seeking_restoration_loop",
        expected="validate_industry_realism_bands returns realism payload",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={
          "business_naics_6": business_naics_6,
          "planning_mode": planning_mode,
        },
        cause=exc,
      ) from exc
    return None, []

  violations = (payload or {}).get("hard_fail_violations") or []
  if not isinstance(violations, list):
    return None, []

  # The validator's hard_fail_violations entries don't always carry
  # primary_levers inline. Look them up from the realism row config.
  # Phase 9 P3.10 Commit 3 — under test mode, lookup failures must
  # raise (audit #17): silent rows=[] makes every metric appear to
  # have no primary_levers, so authorable_failures stays empty and the
  # classifier returns the wrong (None, []) verdict.
  try:
    from client_intake_and_finmo.post_intake_realism.lookup import (  # type: ignore
      post_intake_finalize_realism_check_rows,
    )
    rows = post_intake_finalize_realism_check_rows() or []
  except Exception as exc:
    if test_mode_cls:
      raise PostIntakePreconditionFailed(
        operation="forecast_classifier_realism_rows_lookup_failed",
        pipeline_stage="post_intake_target_seeking_restoration_loop",
        expected="post_intake_finalize_realism_check_rows() returns row list",
        actual=f"{type(exc).__name__}: {str(exc)[:200]}",
        details={},
        cause=exc,
      ) from exc
    rows = []
  levers_by_metric: Dict[str, List[str]] = {}
  for r in rows:
    if not isinstance(r, dict):
      continue
    mk = str(r.get("metric_key") or "").strip()
    if not mk:
      continue
    pl = r.get("primary_levers") or []
    if isinstance(pl, (list, tuple)):
      levers_by_metric[mk] = [str(p).strip() for p in pl if str(p or "").strip()]

  authorable_failures: List[Dict[str, Any]] = []
  any_pnl_reference = False
  for v in violations:
    if not isinstance(v, dict):
      continue
    mk = str(v.get("metric_key") or "").strip()
    if not mk:
      continue
    levers = list(levers_by_metric.get(mk) or [])
    if not levers:
      # No primary_levers configured -> can't decide scope; skip the
      # metric from the GPT-authorable filter (the realism gate will
      # still surface it downstream).
      continue
    if not all(lev in _GPT_AUTHORED_ALL for lev in levers):
      # Some primary_lever is outside GPT's authority (e.g. debt
      # schedule, owner's capital). The handler can't fix this metric
      # by writing its 12 drivers, so don't trigger on it.
      continue
    if any(lev in _GPT_AUTHORED_PNL_LEVER_IDS for lev in levers):
      any_pnl_reference = True
    authorable_failures.append({
      "metric_key": mk,
      "quarter_index": v.get("quarter_index"),
      "actual_value": v.get("actual_value"),
      "effective_min": v.get("effective_min"),
      "effective_max": v.get("effective_max"),
      "band_source": v.get("band_source"),
      "primary_levers": levers,
    })

  if not authorable_failures:
    return None, []
  scope = HandlerScope.PNL_PATH if any_pnl_reference else HandlerScope.BS_ONLY_PATH
  return scope, authorable_failures


def run_restoration_loop(
  *,
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  business_naics_6: Optional[str],
  horizon: int = HORIZON_QUARTERS_DEFAULT,
  max_outer_passes: int = MAX_OUTER_PASSES,
  planning_mode: Optional[str] = None,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  solver_targets_payload: Optional[Dict[str, Any]] = None,
) -> RestorationResult:
  """Outer loop over the 4 solver targets in priority order.

  Mutates ``model_input`` in place. Returns a RestorationResult
  carrying status, per-pass diagnostics, final viability state, and
  per-driver bound summary.
  """
  per_pass_diagnostics: List[Dict[str, Any]] = []
  per_target_results: List[Dict[str, Any]] = []
  drivers_at_bounds_summary: Dict[str, str] = {}
  outer_passes_used = 0
  final_viability: Dict[str, bool] = {}

  # Phase 9 P3 case (b) iter 3 — snapshot the intake model_input ONCE
  # at restoration loop entry, then resolve driver bounds against this
  # snapshot for every outer pass. Without this, bounds for revenue-side
  # levers (Unit Price, Capacity, Utilization) re-resolve against the
  # post-solver value each pass — bound = current_value × multiplier
  # — which silently WIDENS the bound upward every pass (price 2.00 ->
  # 2.40 -> 2.88 -> 3.46 -> ...). The solver effectively ignores its
  # own conservative fallback bounds. Snapshotting fixes the bound to
  # operator-stated intake values.
  intake_snapshot = copy.deepcopy(model_input or {})

  # Compute driver_bounds for each target ONCE up front against the
  # intake snapshot. Reused across all outer passes.
  bounds_by_target: Dict[str, Dict[str, DriverBound]] = {}
  for target_metric in TARGETS_IN_PRIORITY_ORDER:
    bounds_by_target[target_metric] = _driver_bounds_for_target(
      target_metric=target_metric, business_naics_6=business_naics_6,
      model_input=intake_snapshot, build_finmo=build_finmo, horizon=horizon,
    )

  for outer_pass in range(1, max_outer_passes + 1):
    outer_passes_used = outer_pass
    pass_diag: Dict[str, Any] = {
      "outer_pass": outer_pass,
      "targets_attempted": [],
      "targets_converged": [],
      "targets_bound_pinned": [],
    }

    for target_metric in TARGETS_IN_PRIORITY_ORDER:
      band_min, band_target, band_max = _resolve_band_for_target(
        target_metric=target_metric, business_naics_6=business_naics_6,
      )
      # Bounds for the target's drivers — snapshotted at restoration
      # loop entry; reused across all outer passes to avoid bound
      # creep on revenue-side levers (multiplier × current_value would
      # otherwise widen each pass).
      driver_bounds = bounds_by_target.get(target_metric, {})
      if not driver_bounds:
        pass_diag["targets_attempted"].append({
          "target": target_metric, "skipped_reason": "no_driver_bounds_resolved",
        })
        continue

      # Compute current per-q metric BEFORE building the ramp so Q1
      # anchor matches reality.
      current_finmo = build_finmo(copy.deepcopy(model_input))
      from client_intake_and_finmo.post_intake_target_solver.target_solver import (  # type: ignore
        _compute_metric_per_q,
      )
      current_metric_per_q = _compute_metric_per_q(
        target_metric=target_metric, finmo_json=current_finmo, horizon=horizon,
      )
      pm_floor_per_q = _planning_mode_floor_per_q(
        target_metric=target_metric,
        planning_mode=planning_mode,
        horizon=horizon,
      )
      target_ramp = _build_target_ramp(
        target_metric=target_metric,
        current_metric_per_q=current_metric_per_q,
        band_target=band_target,
        band_min=band_min,
        horizon=horizon,
        planning_mode_floor_per_q=pm_floor_per_q,
        planning_mode=planning_mode,
      )

      try:
        result = solve_for_target(
          target_metric=target_metric,
          target_ramp=target_ramp,
          driver_lever_ids=list(driver_bounds.keys()),
          driver_bounds=driver_bounds,
          model_input=model_input,
          build_finmo=build_finmo,
          horizon=horizon,
        )
      except CashPassLeverViolation as exc:
        # Should never happen — _driver_bounds_for_target excludes them.
        # But if a future driver list change misses this guard, fail loud.
        return RestorationResult(
          status=RestorationStatus.FAILED,
          outer_passes_used=outer_pass,
          per_pass_diagnostics=per_pass_diagnostics + [pass_diag],
          per_target_results=per_target_results,
          reason=f"cash_pass_lever_violation: {exc}",
        )

      pass_diag["targets_attempted"].append({
        "target": target_metric,
        "status": result.status.value,
        "inner_iterations": result.inner_iterations_used,
        "band_target": band_target,
        "ramp_q1": target_ramp[0] if target_ramp else None,
        "ramp_q11": target_ramp[10] if len(target_ramp) > 10 else None,
        "ramp_q20": target_ramp[-1] if target_ramp else None,
        "initial_q11": result.initial_metric_per_q[10] if len(result.initial_metric_per_q) > 10 else None,
        "final_q11": result.final_metric_per_q[10] if len(result.final_metric_per_q) > 10 else None,
        "drivers_at_bounds": dict(result.drivers_at_bounds),
      })
      per_target_results.append({
        "outer_pass": outer_pass,
        "target": target_metric,
        "result": result.to_dict(),
      })
      if result.status == SolverStatus.CONVERGED:
        pass_diag["targets_converged"].append(target_metric)
      elif result.status == SolverStatus.BOUND_PINNED:
        pass_diag["targets_bound_pinned"].append(target_metric)
      # Roll bound summary forward.
      for lid, bound_dir in result.drivers_at_bounds.items():
        # Latest pass wins — accurately reflects current state.
        drivers_at_bounds_summary[lid] = bound_dir

    # After all 4 targets attempted in this pass, evaluate viability.
    post_finmo = build_finmo(copy.deepcopy(model_input))
    final_viability = _evaluate_viability(finmo_json=post_finmo)
    pass_diag["viability_after_pass"] = dict(final_viability)
    per_pass_diagnostics.append(pass_diag)

    # Landed exit: every viability trajectory check passes AND no
    # GPT-authorable realism metric forecasts to hard-fail.
    if all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS):
      # Compute Q11 EBITDA for the report.
      from client_intake_and_finmo.post_intake_realism.formulas import (  # type: ignore
        evaluate_realism_formula,
      )
      try:
        q11_em = evaluate_realism_formula(
          "ebitda_div_revenue",
          model_input_json={}, finmo_json=post_finmo, quarter_index=11,
        )
      except Exception:
        q11_em = None

      # Phase 9 P3.7 — forward-looking exhaustion. If the post-restore
      # FINMO would hard-fail a GPT-authorable realism metric, route to
      # the handler via EXHAUSTED with a scope rather than returning
      # LANDED. This catches NexGen-class cases where the deterministic
      # solver clears viability but bound-pins a BS target and leaves a
      # band-check overshoot in Q1-Q9.
      forecast_scope, forecast_failures = _classify_forecast_exhaustion(
        model_input=model_input,
        post_finmo=post_finmo,
        business_naics_6=business_naics_6,
        ops_json=ops_json,
        financials_json=financials_json,
        planning_mode=planning_mode,
        solver_targets_payload=solver_targets_payload,
      )
      if forecast_scope is not None:
        return RestorationResult(
          status=RestorationStatus.EXHAUSTED,
          outer_passes_used=outer_pass,
          per_pass_diagnostics=per_pass_diagnostics,
          final_viability_state=final_viability,
          drivers_at_bounds_summary=drivers_at_bounds_summary,
          per_target_results=per_target_results,
          q11_ebitda_margin=float(q11_em) if q11_em is not None else None,
          reason=(
            "viability_passed_but_forecast_realism_hard_fail "
            f"scope={forecast_scope.value} "
            f"failing_metric_keys={sorted({fm.get('metric_key') for fm in forecast_failures})} "
            "diagnostic: deterministic solver landed viability but the "
            "post-solver state would hard-fail one or more GPT-authorable "
            "realism band checks; routing to handler under the "
            "forward-looking exhaustion semantics."
          ),
          scope=forecast_scope,
          failing_metrics=forecast_failures,
        )

      return RestorationResult(
        status=RestorationStatus.LANDED,
        outer_passes_used=outer_pass,
        per_pass_diagnostics=per_pass_diagnostics,
        final_viability_state=final_viability,
        drivers_at_bounds_summary=drivers_at_bounds_summary,
        per_target_results=per_target_results,
        q11_ebitda_margin=float(q11_em) if q11_em is not None else None,
        reason="all_viability_trajectory_checks_passed_and_realism_forecast_clean",
      )

    # Exhausted exit (formal): every operating driver across all
    # targets is fully pinned at its bound across all 20 quarters.
    # This is the strict shape — drivers_at_bounds_summary gets a lid
    # entry only when EVERY quarter's value is at the bound.
    all_drivers: set = set()
    for target_metric in TARGETS_IN_PRIORITY_ORDER:
      all_drivers.update(bounds_by_target.get(target_metric, {}).keys())
    formal_exhaustion = bool(all_drivers) and all(
      lid in drivers_at_bounds_summary for lid in all_drivers
    )

    # Exhausted exit (semantic): every attempted target is stuck —
    # bound_pinned, converged, or max_inner_iterations_reached.
    # P3.26 F-2: max_inner_iterations_reached now counts toward the
    # stuck threshold (pre-fix it was attempted-only, dropping
    # Anderson & Blake's pass-5 shape).
    targets_attempted_count = len([
      t for t in (pass_diag.get("targets_attempted") or [])
      if t.get("status") in ("bound_pinned", "converged", "max_inner_iterations_reached")
    ])
    targets_bound_pinned = list(pass_diag.get("targets_bound_pinned") or [])
    targets_converged = list(pass_diag.get("targets_converged") or [])
    targets_max_inner_iters: List[str] = [
      str(t.get("target") or "").strip()
      for t in (pass_diag.get("targets_attempted") or [])
      if t.get("status") == "max_inner_iterations_reached" and str(t.get("target") or "").strip()
    ]
    semantic_exhaustion = (
      bool(targets_attempted_count)
      and (len(targets_bound_pinned) + len(targets_converged) + len(targets_max_inner_iters)) >= targets_attempted_count
      and (len(targets_bound_pinned) + len(targets_max_inner_iters)) >= 1
      and not all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS)
    )

    if formal_exhaustion or semantic_exhaustion:
      from client_intake_and_finmo.post_intake_realism.formulas import (  # type: ignore
        evaluate_realism_formula,
      )
      try:
        q11_em = evaluate_realism_formula(
          "ebitda_div_revenue",
          model_input_json={}, finmo_json=post_finmo, quarter_index=11,
        )
      except Exception:
        q11_em = None
      reason = (
        "every_operating_driver_pinned_at_bound "
        f"drivers={sorted(all_drivers)} "
        "diagnostic: cohort tolerances may be too tight, operator intake "
        "may have structural issues, or stage shift may be needed"
        if formal_exhaustion else
        "every_target_returned_bound_pinned_in_latest_pass "
        f"targets_bound_pinned={targets_bound_pinned} "
        f"targets_converged={targets_converged} "
        "diagnostic: deterministic algebra exhausted; no further driver "
        "movement available within conservative bounds"
      )
      # Phase 9 P3.7 — classify scope on the existing EXHAUSTED paths
      # too. Sunny-class exhaustions (viability not reachable) will
      # surface failing P&L metrics -> pnl_path. Defaulting to PNL_PATH
      # when the forecast classifier returns no signal preserves the
      # P3.5/P3.6 all-12-drivers behavior for prior-EXHAUSTED cases.
      forecast_scope, forecast_failures = _classify_forecast_exhaustion(
        model_input=model_input,
        post_finmo=post_finmo,
        business_naics_6=business_naics_6,
        ops_json=ops_json,
        financials_json=financials_json,
        planning_mode=planning_mode,
        solver_targets_payload=solver_targets_payload,
      )
      effective_scope = forecast_scope if forecast_scope is not None else HandlerScope.PNL_PATH
      return RestorationResult(
        status=RestorationStatus.EXHAUSTED,
        outer_passes_used=outer_pass,
        per_pass_diagnostics=per_pass_diagnostics,
        final_viability_state=final_viability,
        drivers_at_bounds_summary=drivers_at_bounds_summary,
        per_target_results=per_target_results,
        q11_ebitda_margin=float(q11_em) if q11_em is not None else None,
        reason=reason,
        scope=effective_scope,
        failing_metrics=forecast_failures,
      )

  # Hit max outer passes without landing or exhausting. P3.26 F-3:
  # populate scope + failing_metrics so the orchestrator's broadened
  # Site 1 trigger (F-1) can route ITERATING_STILL with realism
  # forecast failures to the handler with full payload. Empty
  # failing_metrics correctly leaves the handler skipped.
  from client_intake_and_finmo.post_intake_realism.formulas import (  # type: ignore
    evaluate_realism_formula,
  )
  final_finmo: Dict[str, Any] = {}
  try:
    final_finmo = build_finmo(copy.deepcopy(model_input))
    q11_em = evaluate_realism_formula(
      "ebitda_div_revenue",
      model_input_json={}, finmo_json=final_finmo, quarter_index=11,
    )
  except Exception:
    q11_em = None
  forecast_scope, forecast_failures = _classify_forecast_exhaustion(
    model_input=model_input,
    post_finmo=final_finmo,
    business_naics_6=business_naics_6,
    ops_json=ops_json,
    financials_json=financials_json,
    planning_mode=planning_mode,
    solver_targets_payload=solver_targets_payload,
  )
  effective_scope = forecast_scope if forecast_scope is not None else (
    HandlerScope.PNL_PATH if forecast_failures else None
  )
  return RestorationResult(
    status=RestorationStatus.ITERATING_STILL,
    outer_passes_used=outer_passes_used,
    per_pass_diagnostics=per_pass_diagnostics,
    final_viability_state=final_viability,
    drivers_at_bounds_summary=drivers_at_bounds_summary,
    per_target_results=per_target_results,
    q11_ebitda_margin=float(q11_em) if q11_em is not None else None,
    reason="max_outer_passes_reached_without_landed_or_exhausted",
    scope=effective_scope,
    failing_metrics=forecast_failures,
  )
