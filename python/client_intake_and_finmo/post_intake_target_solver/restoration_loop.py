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
TARGETS_IN_PRIORITY_ORDER: Tuple[str, ...] = (
  "gross_margin_percent",
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
  "no_post_recovery_relapse_q11_q20",
  "gross_margin_supports_ebitda_recovery",
  "fixed_cost_burden_reduced_or_scaled_by_q11",
)

# Hard cap on outer passes per directive.
MAX_OUTER_PASSES = 5


class RestorationStatus(str, Enum):
  LANDED = "landed"
  EXHAUSTED = "exhausted"
  ITERATING_STILL = "iterating_still"
  FAILED = "failed"


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
    "no_post_recovery_relapse_q11_q20": "trajectory_no_post_recovery_relapse",
    "gross_margin_supports_ebitda_recovery": "trajectory_gross_margin_supports_recovery",
    "fixed_cost_burden_reduced_or_scaled_by_q11": "trajectory_fixed_cost_burden_at_industry_floor",
  }
  out: Dict[str, bool] = {}
  for metric, fkey in formula_keys.items():
    try:
      v = evaluate_realism_formula(
        fkey, model_input_json={}, finmo_json=finmo_json, quarter_index=None,
      )
    except Exception:
      v = None
    if v is None:
      out[metric] = False
    else:
      out[metric] = float(v) >= 0.0
  return out


def _build_target_ramp(
  *,
  target_metric: str,
  current_metric_per_q: List[float],
  band_target: float,
  band_min: float,
  horizon: int,
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
  q1_anchor = q1_current
  if target_metric in ("gross_margin_percent", "ebitda_margin"):
    floor = max(0.0, float(band_min))
    q1_anchor = max(q1_current, floor)
  ramp = [0.0] * horizon
  for q in range(horizon):
    frac = q / max(1, horizon - 1)
    ramp[q] = (1.0 - frac) * q1_anchor + frac * q20_target
  if target_metric in ("gross_margin_percent", "ebitda_margin"):
    floor = max(0.0, float(band_min))
    for q in range(horizon):
      if ramp[q] < floor:
        ramp[q] = floor
    if horizon > 10 and ramp[10] < 0.0:
      ramp[10] = max(0.0, q20_target / 2.0)
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
  payload: Optional[Dict[str, Any]] = None
  try:
    payload = post_intake_industry_baseline_for_naics(
      metric_key=target_metric, naics_6=business_naics_6 or "",
    )
  except Exception:
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


def _driver_bounds_for_target(
  *,
  target_metric: str,
  business_naics_6: Optional[str],
) -> Dict[str, DriverBound]:
  """Resolve per-driver (lower, upper) bounds from the cohort/baseline
  resolver. Per-driver kind dispatch:

    - cogs%, marketing%, r_and_d%, sga%, prepaid%, deferred%:
      bounds from the corresponding ``*_percent_of_revenue`` cohort row.
    - ar_days_dso, ap_days_dpo, inventory_days: bounds from the
      corresponding ``*_days`` cohort row.
    - revenue::Unit Price, Capacity, Utilization: bounds derived
      conservatively from the current model value (±50%) — there is
      no NAICS cohort for these absolute units.
    - quarter_currency (payroll, lease): bounds derived from the
      corresponding *_percent_of_revenue band scaled by current
      revenue.
  """
  from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
    post_intake_industry_baseline_for_naics,
  )
  bounds: Dict[str, DriverBound] = {}

  def _band(metric_key: str) -> Optional[Tuple[float, float]]:
    try:
      payload = post_intake_industry_baseline_for_naics(
        metric_key=metric_key, naics_6=business_naics_6 or "",
      )
    except Exception:
      return None
    bmin = payload.get("benchmark_min") if payload else None
    bmax = payload.get("benchmark_max") if payload else None
    if bmin is None and bmax is None:
      return None
    if bmin is None:
      bmin = float(bmax) * 0.5 if bmax is not None else 0.0
    if bmax is None:
      bmax = float(bmin) * 1.5
    return (float(bmin), float(bmax))

  # Operating-side levers per target. Strictly excludes
  # _CASH_PASS_OWNED_LEVER_IDS.
  if target_metric == "gross_margin_percent":
    b = _band("cogs_percent_of_revenue")
    if b is not None:
      bounds["expenses::Cost of Goods Sold"] = DriverBound(
        lower=b[0], upper=b[1], driver_kind="percent_of_revenue",
      )
  elif target_metric == "ebitda_margin":
    for metric_key, lever_id in (
      ("cogs_percent_of_revenue", "expenses::Cost of Goods Sold"),
      ("marketing_percent_of_revenue", "expenses::Marketing"),
      ("r_and_d_percent_of_revenue", "expenses::Research & Development"),
      ("sga_percent_of_revenue", "expenses::General & Administrative"),
    ):
      b = _band(metric_key)
      if b is not None:
        bounds[lever_id] = DriverBound(
          lower=b[0], upper=b[1], driver_kind="percent_of_revenue",
        )
  elif target_metric == "current_assets_minus_cash":
    ar = _band("ar_days_dso")
    if ar is not None:
      bounds["balance_sheet::Accounts Receivable Days"] = DriverBound(
        lower=ar[0], upper=ar[1], driver_kind="days",
      )
    inv = _band("inventory_days")
    if inv is not None:
      bounds["balance_sheet::Inventory Days"] = DriverBound(
        lower=inv[0], upper=inv[1], driver_kind="days",
      )
    pp = _band("prepaid_expenses_percent_of_revenue")
    if pp is not None:
      bounds["balance_sheet::Prepaid Expenses (% of Revenue)"] = DriverBound(
        lower=pp[0], upper=pp[1], driver_kind="percent_of_revenue",
      )
  elif target_metric == "current_liabilities_to_revenue":
    ap = _band("ap_days_dpo")
    if ap is not None:
      bounds["balance_sheet::Accounts Payable Days"] = DriverBound(
        lower=ap[0], upper=ap[1], driver_kind="days",
      )
    dr = _band("deferred_revenue_percent_of_revenue")
    if dr is not None:
      bounds["balance_sheet::Deferred Revenue (% of Revenue)"] = DriverBound(
        lower=dr[0], upper=dr[1], driver_kind="percent_of_revenue",
      )

  # Defensive: strip cash-pass-owned levers if any slipped in.
  for lid in list(bounds.keys()):
    if lid in _CASH_PASS_OWNED_LEVER_IDS:
      del bounds[lid]
  return bounds


# ----------------------------------------------------------------------------
# The outer restoration loop.
# ----------------------------------------------------------------------------


def run_restoration_loop(
  *,
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  business_naics_6: Optional[str],
  horizon: int = HORIZON_QUARTERS_DEFAULT,
  max_outer_passes: int = MAX_OUTER_PASSES,
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
      # Bounds for the target's drivers.
      driver_bounds = _driver_bounds_for_target(
        target_metric=target_metric, business_naics_6=business_naics_6,
      )
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
      target_ramp = _build_target_ramp(
        target_metric=target_metric,
        current_metric_per_q=current_metric_per_q,
        band_target=band_target,
        band_min=band_min,
        horizon=horizon,
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

    # Landed exit: every viability trajectory check passes.
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
      return RestorationResult(
        status=RestorationStatus.LANDED,
        outer_passes_used=outer_pass,
        per_pass_diagnostics=per_pass_diagnostics,
        final_viability_state=final_viability,
        drivers_at_bounds_summary=drivers_at_bounds_summary,
        per_target_results=per_target_results,
        q11_ebitda_margin=float(q11_em) if q11_em is not None else None,
        reason="all_viability_trajectory_checks_passed",
      )

    # Exhausted exit: every operating driver across all 4 targets is
    # pinned at its bound. Re-resolve the union of driver lists for the
    # exhaustion check (drivers_at_bounds_summary captures the
    # cumulative state).
    all_drivers: set = set()
    for target_metric in TARGETS_IN_PRIORITY_ORDER:
      bounds = _driver_bounds_for_target(
        target_metric=target_metric, business_naics_6=business_naics_6,
      )
      all_drivers.update(bounds.keys())
    if all_drivers and all(lid in drivers_at_bounds_summary for lid in all_drivers):
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
      return RestorationResult(
        status=RestorationStatus.EXHAUSTED,
        outer_passes_used=outer_pass,
        per_pass_diagnostics=per_pass_diagnostics,
        final_viability_state=final_viability,
        drivers_at_bounds_summary=drivers_at_bounds_summary,
        per_target_results=per_target_results,
        q11_ebitda_margin=float(q11_em) if q11_em is not None else None,
        reason=(
          "every_operating_driver_pinned_at_bound "
          f"drivers={sorted(all_drivers)} "
          "diagnostic: cohort tolerances may be too tight, operator intake "
          "may have structural issues, or stage shift may be needed"
        ),
      )

  # Hit max outer passes without landing or exhausting.
  from client_intake_and_finmo.post_intake_realism.formulas import (  # type: ignore
    evaluate_realism_formula,
  )
  try:
    final_finmo = build_finmo(copy.deepcopy(model_input))
    q11_em = evaluate_realism_formula(
      "ebitda_div_revenue",
      model_input_json={}, finmo_json=final_finmo, quarter_index=11,
    )
  except Exception:
    q11_em = None
  return RestorationResult(
    status=RestorationStatus.ITERATING_STILL,
    outer_passes_used=outer_passes_used,
    per_pass_diagnostics=per_pass_diagnostics,
    final_viability_state=final_viability,
    drivers_at_bounds_summary=drivers_at_bounds_summary,
    per_target_results=per_target_results,
    q11_ebitda_margin=float(q11_em) if q11_em is not None else None,
    reason="max_outer_passes_reached_without_landed_or_exhausted",
  )
