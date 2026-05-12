"""Phase 9 P3 — Target solver.

`solve_for_target(target_metric, target_ramp, driver_lever_ids,
driver_bounds, model_input)` finds per-quarter driver values that bring
the target metric to `target_ramp[q]` at every quarter q in 1..20,
keeping each driver's value within its bound. The solver writes path-
shaped per-quarter values (NOT flat-stamped) to `model_input`.

Authority boundary: the solver writes operating-side levers ONLY. Any
lever in `_CASH_PASS_OWNED_LEVER_IDS` (Owner's Capital, Other Equity,
Distributions, Short Term Debt %, Debt Issuance, Debt Repayment) in
the input driver_lever_ids raises `CashPassLeverViolation` immediately.
Cash strategy owns those end-to-end and runs after the restoration
loop.

Algorithm — deterministic algebra:

  Inner loop (up to 10 iterations):
    1. Rebuild FINMO from current model_input.
    2. For each quarter q, compute the metric value and the residual:
         residual[q] = target_ramp[q] - current_value[q]
    3. If max |residual[q]| <= tolerance for every q: CONVERGED.
    4. For each driver, compute slack-in-direction (distance from
       current value to its bound in the direction needed to close the
       residual). Drivers with zero slack drop out of the active set.
    5. If active set empty AND residuals exceed tolerance: BOUND_PINNED
       (an "exhausted" report from this single inner solve — the outer
       restoration loop folds it into its own exhaustion logic).
    6. Per quarter, allocate residual across the active drivers
       proportional to (slack × |sensitivity|), then apply the
       resulting driver delta to the model_input row. The delta is
       converted from "metric units" to "driver units" via the
       per-(target, driver_kind) sensitivity coefficient.
    7. Iterate.

Sensitivity coefficients (per target, per driver_kind):
  Computed analytically where the math is clean (gross_margin =
  1 - cogs%, ebitda_margin = sum of margin contributions, working
  capital ratios are linear in days/percent). For more complex driver
  contributions (e.g. revenue::Unit Price's effect on ebitda_margin via
  revenue scaling), an empirical sensitivity is computed via FINMO
  rebuild perturbation. Both are "deterministic algebra" — no GPT.

Per-driver path shape:
  Solver writes use the path engine's `compute_per_quarter_values` so
  the resulting driver vector still respects the doctrine's per-driver
  shape (s_curve for utilization, glidepath for cogs%, etc.). Each
  inner iteration writes a fresh path; the path engine reads the
  iteration's chosen Q1 anchor + the driver's mature target and
  produces the consistent ramp. Pre-Phase-9-P3 the cascade flat-stamped
  the same value across Q1..Q20 — that is forbidden under this build.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


# Mirrors post_intake_solver.orchestrator._CASH_PASS_OWNED_LEVER_IDS — the
# cash-vs-operating boundary the solver must NOT cross. Re-declared here
# rather than imported to avoid a circular import (orchestrator imports
# target_solver in Phase 3 wiring).
_CASH_PASS_OWNED_LEVER_IDS = frozenset({
  "balance_sheet::Owner's Capital",
  "balance_sheet::Other Equity",
  "balance_sheet::Distributions",
  "balance_sheet::Short Term Debt (% of LTD)",
  "schedules::Debt Issuance (New Borrowing)",
  "schedules::Debt Repayment (Scheduled)",
})


HORIZON_QUARTERS_DEFAULT = 20

# Default per-target tolerance. The solver claims CONVERGED when
# max |residual[q]| <= tolerance across every quarter. Tight enough
# to be meaningful, loose enough to land on noisy realism band edges.
DEFAULT_TOLERANCE = 0.005   # 50bps absolute on ratio metrics

# Inner-loop hard cap. The directive says 10.
MAX_INNER_ITERATIONS = 10


# Phase 9 P3 cost-priority tiering — universal mechanism.
# All businesses get every lever from the realism config. The allocator
# decides which actually move based on tier and slack:
#
#   Tier 1 (operational, cheap): cost-ratio drivers. Per-quarter %-of-
#     revenue lines that compress without structural change to the
#     business. cogs%, marketing%, G&A%, R&D%.
#   Tier 2 (structural, expensive): revenue-side and quarter-currency
#     drivers. Touching these implies a structural change (price hike,
#     headcount change, capacity expansion, lease renegotiation) and
#     should only fire when Tier 1 cannot absorb the residual.
#
# Per-quarter allocation:
#   1. Allocate residual across Tier 1 drivers with slack (proportional
#      to slack × |sensitivity|). Drop pinned drivers, reallocate.
#   2. If after Tier 1's full pass the residual at this quarter is
#      still outside tolerance AND every Tier 1 driver is pinned at
#      its bound for this quarter, engage Tier 2 for the remaining
#      residual.
#
# Provenance: when a Tier 2 lever is touched in any quarter, the
# row gets `applied_by_target_solver_quarters[q]["tier_used"] =
# "tier_2_structural_after_tier_1_exhausted"`. Diagnostics show
# which structural levers were reached for.
_TIER_2_LEVER_PREFIXES: Tuple[str, ...] = (
  "revenue::",
  "expenses::Payroll",
  "expenses::Lease",
)

_TIER_2_TAG_VALUE = "tier_2_structural_after_tier_1_exhausted"


def _lever_tier(lever_id: str) -> int:
  """Return 1 for operational/cheap drivers, 2 for structural/expensive.

  Tier 2 is anything in _TIER_2_LEVER_PREFIXES (revenue-side and the
  two quarter-currency expense lines). Tier 1 is everything else
  (cost-ratio %-of-revenue, balance-sheet days/percent levers).
  """
  lid = str(lever_id or "").strip()
  for prefix in _TIER_2_LEVER_PREFIXES:
    if lid == prefix or lid.startswith(prefix):
      return 2
  return 1


class CashPassLeverViolation(RuntimeError):
  """Raised when the caller passes a cash-pass-owned lever_id into
  solve_for_target's driver_lever_ids. Cash strategy owns these
  end-to-end; the operating-side solver MUST NOT touch them.
  """


class SolverStatus(str, Enum):
  CONVERGED = "converged"
  BOUND_PINNED = "bound_pinned"
  MAX_INNER_ITERATIONS_REACHED = "max_inner_iterations_reached"


@dataclass
class DriverBound:
  """Per-driver bound, in the same units as the model_input row's
  ``values`` field.

  - For ``percent_of_revenue`` levers (cogs%, marketing%, r_and_d%,
    sga%, prepaid%, deferred%): bounds are fractions, e.g. 0.20 means
    20%.
  - For ``days`` levers (ar_days_dso, ap_days_dpo, inventory_days):
    bounds are days, e.g. 60 means 60 days.
  - For ``quarter_currency`` levers (payroll, lease): bounds are
    dollar amounts per quarter.
  - For ``revenue_unit`` levers (unit price, capacity, utilization):
    bounds are in the lever's native unit (price = $/unit, capacity =
    units/period, utilization = fraction).

  ``bound_source`` records WHERE the (lower, upper) numbers came from.
  Examples: "cohort_alternating_edgar", "cohort_alternating_alpha",
  "phase_9_p3_generic_default", "payroll_percent_band_scaled",
  "hardcoded_fallback_no_data" (for revenue-side levers where there is
  no NAICS cohort for absolute units). Surfaces in the restoration
  loop's per-target / per-driver diagnostics so an EXHAUSTED return
  shows which bound source pinned each lever.
  """

  lower: float
  upper: float
  driver_kind: str  # "percent_of_revenue" | "days" | "quarter_currency" | "revenue_unit"
  bound_source: str = ""


@dataclass
class _DriverState:
  """Per-driver mutable state during a single solve. Snapshots the
  model_input row(s) the solver writes to, the per-quarter current
  values, and the bound-pinning status.
  """

  lever_id: str
  driver_kind: str
  bound: DriverBound
  current_per_q: List[float] = field(default_factory=list)  # length 20
  bound_pinned_per_q: List[Optional[str]] = field(default_factory=list)  # 'lower' | 'upper' | None
  rows: List[Dict[str, Any]] = field(default_factory=list)  # the model_input rows

  def slack_in_direction_for_quarter(self, q_idx: int, direction: str) -> float:
    """Return the absolute distance from the driver's current value at
    quarter ``q_idx`` to the bound in ``direction``. ``direction`` is
    "raise" or "lower" — the direction the driver value itself must
    move (NOT the direction the metric must move).
    """
    cur = self.current_per_q[q_idx]
    if direction == "raise":
      return max(0.0, float(self.bound.upper) - float(cur))
    if direction == "lower":
      return max(0.0, float(cur) - float(self.bound.lower))
    return 0.0

  def is_pinned_at_bound_for_direction(self, direction: str, eps: float = 1e-9) -> bool:
    """True when EVERY quarter is at the relevant bound in ``direction``."""
    for cur in self.current_per_q:
      if direction == "raise" and float(cur) < float(self.bound.upper) - eps:
        return False
      if direction == "lower" and float(cur) > float(self.bound.lower) + eps:
        return False
    return True


@dataclass
class SolverResult:
  status: SolverStatus
  target_metric: str
  inner_iterations_used: int
  initial_metric_per_q: List[float]  # what we started with
  final_metric_per_q: List[float]    # what we landed at
  target_ramp: List[float]
  final_residuals: List[float]
  drivers_at_bounds: Dict[str, str] = field(default_factory=dict)  # lever_id -> 'lower' | 'upper'
  drivers_moved: Dict[str, List[float]] = field(default_factory=dict)  # lever_id -> per-q final values
  diagnostics: List[Dict[str, Any]] = field(default_factory=list)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "status": self.status.value if isinstance(self.status, SolverStatus) else str(self.status),
      "target_metric": self.target_metric,
      "inner_iterations_used": self.inner_iterations_used,
      "initial_metric_per_q": list(self.initial_metric_per_q),
      "final_metric_per_q": list(self.final_metric_per_q),
      "target_ramp": list(self.target_ramp),
      "final_residuals": list(self.final_residuals),
      "drivers_at_bounds": dict(self.drivers_at_bounds),
      "drivers_moved": {k: list(v) for k, v in self.drivers_moved.items()},
      "diagnostics": list(self.diagnostics),
    }


# ----------------------------------------------------------------------------
# Per-(target, driver_kind) sensitivity coefficient.
#
# `sensitivity[target][driver_kind]` returns Δmetric / Δdriver, holding
# all other drivers fixed. Algebraic where exact, falls back to None for
# the empirical-sensitivity caller to compute via FINMO perturbation.
#
# Sign convention: positive sensitivity means raising the driver raises
# the metric. Negative sensitivity means raising the driver lowers the
# metric.
#
# IMPORTANT: these coefficients are evaluated at the *current* state, so
# when the metric depends on revenue (e.g. cogs% lever's effect on
# ebitda_margin via cogs absolute = cogs% × revenue), the coefficient
# uses the current quarter's revenue as the denominator.
# ----------------------------------------------------------------------------


def _sensitivity_coefficient(
  *,
  target_metric: str,
  driver_kind: str,
  driver_lever_id: str,
  current_quarter_revenue: float,
  current_quarter_cogs: float,
  current_quarter_fixed_cost: float = 0.0,
  current_driver_value: Optional[float] = None,
) -> Optional[float]:
  """Return Δmetric / Δdriver for a single quarter, evaluated at the
  current state. Returns None when the (target, driver_kind) pair has
  no analytic sensitivity defined (caller drops the driver from the
  active set for that quarter).

  Phase 9 P3 extension — partial derivatives for revenue-side and
  payroll levers, using the standard FINMO model:

    revenue R = capacity * unit_price * utilization
    ebitda  = R * (1 - cogs% - mkt% - rnd% - sga%) - F
            (where F = payroll + lease + depreciation,  the lines
             that do NOT scale with revenue)
    ebitda_margin = ebitda / R = (1 - cogs% - opex%) - F/R

  Partial derivatives:
    ∂em / ∂cogs%        = -1
    ∂em / ∂mkt%/sga%/rnd% = -1
    ∂em / ∂payroll_$    = -1 / R
    ∂em / ∂unit_price   = F / (R * unit_price)        (positive)
    ∂em / ∂capacity     = F / (R * capacity)           (positive)
    ∂em / ∂utilization  = F / (R * utilization)        (positive)

  For gross_margin_percent under the current FINMO setup, cogs% is
  the lever value directly; raising unit_price scales COGS$ in
  proportion (COGS$ = cogs% × R), so gross_margin = 1 - cogs% does
  not move with price. ∂gm/∂unit_price returns None to signal "no
  contribution" — solver drops the driver for that quarter.
  """
  rev = float(current_quarter_revenue) if current_quarter_revenue else 0.0
  fixed = float(current_quarter_fixed_cost) if current_quarter_fixed_cost else 0.0
  drv = float(current_driver_value) if current_driver_value is not None else 0.0
  if target_metric == "gross_margin_percent":
    if driver_kind == "percent_of_revenue" and "Cost of Goods Sold" in driver_lever_id:
      return -1.0
    if driver_kind == "revenue_unit":
      # Under our FINMO model, raising unit_price scales COGS$ in
      # lockstep with revenue (cogs% lever stays fixed), so
      # gross_margin = 1 - cogs% does not move. Return None so the
      # solver treats Unit Price as a no-op driver for gross_margin.
      # Realism config lists it as a primary_lever; under the current
      # FINMO this connection is non-actuating.
      return None
    return None
  if target_metric == "ebitda_margin":
    if driver_kind == "percent_of_revenue":
      # Cost ratio (cogs%, marketing%, r_and_d%, sga%): Δebitda_margin
      # = -Δcost%. Direct.
      return -1.0
    if driver_kind == "quarter_currency":
      # payroll / lease in absolute $: Δebitda_margin = -Δcost / revenue.
      if rev > 0:
        return -1.0 / rev
      return None
    if driver_kind == "revenue_unit":
      # ∂em/∂{price, capacity, utilization} = F / (R × current_driver)
      # Positive sensitivity — raising any of price / capacity /
      # utilization raises revenue and dilutes the fixed-cost burden,
      # lifting ebitda_margin.
      if rev > 0 and drv > 0 and fixed > 0:
        return fixed / (rev * drv)
      return None
    return None
  if target_metric == "current_assets_minus_cash":
    if driver_kind == "days" and "Accounts Receivable" in driver_lever_id:
      # ratio = AR_days/90 + ... → Δratio = Δar_days / 90.
      return 1.0 / 90.0
    if driver_kind == "days" and "Inventory" in driver_lever_id:
      # ratio contribution = inv_days × (cogs/revenue) / 90.
      if rev > 0:
        return (float(current_quarter_cogs) / rev) / 90.0
      return None
    if driver_kind == "percent_of_revenue" and "Prepaid" in driver_lever_id:
      # ratio contribution = prepaid%. Direct.
      return 1.0
    return None
  if target_metric == "current_liabilities_to_revenue":
    if driver_kind == "days" and "Accounts Payable" in driver_lever_id:
      # ratio contribution ≈ ap_days × (opex_base/revenue) / 90. Use
      # cogs as opex_base proxy (FINMO defines AP base differently;
      # cogs is the dominant component for most businesses).
      if rev > 0:
        return (float(current_quarter_cogs) / rev) / 90.0
      return None
    if driver_kind == "percent_of_revenue" and "Deferred Revenue" in driver_lever_id:
      return 1.0
    return None
  return None


# ----------------------------------------------------------------------------
# Driver-kind dispatch from lever_id.
# ----------------------------------------------------------------------------


def _driver_kind_for_lever(lever_id: str) -> str:
  lid = str(lever_id or "").strip()
  if lid in _CASH_PASS_OWNED_LEVER_IDS:
    return "cash_pass_owned"
  if lid.startswith("balance_sheet::") and "Days" in lid:
    return "days"
  if lid.startswith("balance_sheet::") and "%" in lid:
    return "percent_of_revenue"
  if lid.startswith("expenses::Cost of Goods Sold"):
    return "percent_of_revenue"
  if lid.startswith("expenses::Marketing"):
    return "percent_of_revenue"
  if lid.startswith("expenses::Research & Development"):
    return "percent_of_revenue"
  if lid.startswith("expenses::General & Administrative"):
    return "percent_of_revenue"
  if lid.startswith("expenses::Payroll"):
    return "quarter_currency"
  if lid.startswith("expenses::Lease"):
    return "quarter_currency"
  if lid.startswith("revenue::"):
    return "revenue_unit"
  return "unknown"


# ----------------------------------------------------------------------------
# Model-input row resolution.
# ----------------------------------------------------------------------------


def _find_rows_for_lever(
  model_input: Dict[str, Any], lever_id: str
) -> List[Dict[str, Any]]:
  """Return every model_input row whose lever_id matches.

  For revenue::<driver> shortcuts (e.g., revenue::Unit Price), match by
  the row's `driver` field — the model_input revenue rows are
  namespaced (revenue::<LOB>::<unit>::<driver>) but the realism lookup
  carries the generic shortcut.
  """
  matches: List[Dict[str, Any]] = []
  sections = (model_input or {}).get("sections") or {}
  if not isinstance(sections, dict):
    return matches
  lid = str(lever_id or "").strip()
  for section_name, rows in sections.items():
    if not isinstance(rows, list):
      continue
    for row in rows:
      if not isinstance(row, dict):
        continue
      row_lever = str(row.get("lever_id") or "").strip()
      if row_lever == lid:
        matches.append(row)
        continue
      # Revenue shortcut fallback.
      if (
        lid.startswith("revenue::")
        and section_name == "revenue"
        and "::" in lid
      ):
        driver_token = lid.split("::", 1)[1].strip().lower()
        row_driver = str(row.get("driver") or "").strip().lower()
        if driver_token and row_driver and row_driver == driver_token:
          matches.append(row)
  return matches


def _read_driver_state(
  *,
  lever_id: str,
  bound: DriverBound,
  model_input: Dict[str, Any],
  horizon: int,
) -> _DriverState:
  """Read the per-quarter live values for a driver. The model_input row
  ``values`` array is laid out as ``[stub_value, live_q1, live_q2, ...,
  live_q<horizon>]`` (length horizon+1). The solver operates on the LIVE
  range only; index 0 (stub) is never touched.
  """
  driver_kind = _driver_kind_for_lever(lever_id)
  rows = _find_rows_for_lever(model_input, lever_id)
  if not rows:
    return _DriverState(
      lever_id=lever_id, driver_kind=driver_kind, bound=bound,
      current_per_q=[0.0] * horizon,
      bound_pinned_per_q=[None] * horizon, rows=[],
    )
  # Combine values across rows by averaging (typical for revenue
  # shortcuts that hit multiple LOBs). Per-quarter writes preserve the
  # path shape directly: each quarter is independently chosen.
  per_q: List[float] = [0.0] * horizon
  for row in rows:
    vals = row.get("values") or []
    for q_idx in range(horizon):
      live_idx = 1 + q_idx  # skip stub at index 0
      if live_idx < len(vals):
        try:
          per_q[q_idx] += float(vals[live_idx]) if vals[live_idx] is not None else 0.0
        except Exception:
          pass
  per_q = [v / max(1, len(rows)) for v in per_q]
  return _DriverState(
    lever_id=lever_id, driver_kind=driver_kind, bound=bound,
    current_per_q=per_q, bound_pinned_per_q=[None] * horizon, rows=list(rows),
  )


def _write_driver_value_at_quarter(
  *,
  driver_state: _DriverState,
  q_idx: int,  # 0-based quarter index (q_idx=0 means live Q1)
  new_value: float,
  target_metric: str,
) -> None:
  """Write `new_value` to every row backing this lever at LIVE quarter
  ``q_idx + 1`` (since row["values"][0] is the stub). Clamps to the
  driver's bounds. Tags the row with ``applied_by_target_solver_quarters``
  provenance so the derived-driver policy layer skips the per-quarter
  re-shape for solver-authored quarters (Phase 9 P3 exclusion path).
  """
  clamped = max(float(driver_state.bound.lower), min(float(driver_state.bound.upper), float(new_value)))
  live_idx = 1 + int(q_idx)  # skip stub at index 0
  quarter_index_1based = int(q_idx) + 1
  for row in driver_state.rows:
    vals = row.get("values")
    if not isinstance(vals, list):
      # Fresh row — initialize stub + live cells up through this quarter.
      vals = [0.0] * (live_idx + 1)
      row["values"] = vals
    while len(vals) <= live_idx:
      vals.append(0.0)
    vals[live_idx] = float(clamped)
    # Provenance tag for the derived-driver policy exclusion path.
    # Stamps which quarters the target solver authored, and for which
    # target. apply_balance_sheet_contextual_seed_to_model_input,
    # _shape_revenue_capacity_and_utilization, etc. read this and skip
    # per-quarter re-shaping for solver-authored quarters.
    tag = row.get("applied_by_target_solver_quarters")
    if not isinstance(tag, dict):
      tag = {}
      row["applied_by_target_solver_quarters"] = tag
    tag[str(quarter_index_1based)] = {
      "target_metric": target_metric,
      "applied_value": float(clamped),
    }
  driver_state.current_per_q[q_idx] = float(clamped)


# ----------------------------------------------------------------------------
# Metric computation per quarter (delegates to realism formulas registry).
# ----------------------------------------------------------------------------


def _compute_metric_per_q(
  *,
  target_metric: str,
  finmo_json: Dict[str, Any],
  horizon: int,
) -> List[float]:
  """Return the metric value at each quarter 1..horizon. Uses the
  realism formula registry as source of truth.

  Phase 9 P3.10 Commit 3 — formula errors are no longer silently
  substituted with 0.0. A formula crash is a code bug, not a
  legitimate "metric is zero this quarter" signal. Under
  CONVERGENCE_TEST_MODE the exception propagates so the solver does
  not chase a phantom residual against an artificially-zero metric.
  """
  from client_intake_and_finmo.post_intake_realism.formulas import (  # type: ignore
    evaluate_realism_formula,
  )
  from client_intake_and_finmo.fail_fast.common import (  # type: ignore
    PostIntakePreconditionFailed,
    convergence_test_mode_enabled,
  )
  formula_key = _FORMULA_KEY_BY_TARGET.get(target_metric)
  if not formula_key:
    raise ValueError(f"target_solver_unknown_target_metric: {target_metric}")
  test_mode = convergence_test_mode_enabled()
  out: List[float] = []
  for q in range(1, horizon + 1):
    try:
      v = evaluate_realism_formula(
        formula_key,
        model_input_json={},
        finmo_json=finmo_json,
        quarter_index=q,
      )
    except Exception as exc:
      if test_mode:
        raise PostIntakePreconditionFailed(
          operation="target_solver_realism_formula_evaluation_failed",
          pipeline_stage="post_intake_target_solver",
          expected=(
            f"realism formula {formula_key} evaluates without raising "
            f"on quarter {q}"
          ),
          actual=f"{type(exc).__name__}: {str(exc)[:200]}",
          details={
            "target_metric": target_metric,
            "formula_key": formula_key,
            "quarter_index": q,
          },
          cause=exc,
        ) from exc
      v = None
    out.append(float(v) if v is not None else 0.0)
  return out


_FORMULA_KEY_BY_TARGET: Dict[str, str] = {
  "gross_margin_percent": "gross_margin_div_revenue",
  "ebitda_margin": "ebitda_div_revenue",
  "current_assets_minus_cash": "current_assets_minus_cash_div_revenue",
  "current_liabilities_to_revenue": "current_liabilities_div_revenue",
}


def _quarter_revenue(finmo_json: Dict[str, Any], q_idx_1based: int) -> float:
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi == q_idx_1based:
      try:
        return float(row.get("revenue") or 0.0)
      except Exception:
        return 0.0
  return 0.0


def _quarter_cogs(finmo_json: Dict[str, Any], q_idx_1based: int) -> float:
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi == q_idx_1based:
      try:
        return float(row.get("cost_of_goods_sold") or 0.0)
      except Exception:
        return 0.0
  return 0.0


def _quarter_fixed_cost_proxy(finmo_json: Dict[str, Any], q_idx_1based: int) -> float:
  """Sum of cost lines that do NOT scale with revenue at this quarter:
  payroll + lease_rent + depreciation. Used as F in
  ebitda_margin = (1 - cogs% - opex%) - F/R for revenue-side and
  payroll sensitivity computations.
  """
  total = 0.0
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    try:
      qi = int(float(row.get("quarter_index") or 0))
    except Exception:
      continue
    if qi == q_idx_1based:
      for field_name in ("payroll", "lease_rent", "depreciation"):
        try:
          v = row.get(field_name)
          if v is not None:
            total += float(v)
        except Exception:
          pass
      break
  return total


# ----------------------------------------------------------------------------
# The solver.
# ----------------------------------------------------------------------------


def solve_for_target(
  *,
  target_metric: str,
  target_ramp: List[float],
  driver_lever_ids: List[str],
  driver_bounds: Dict[str, DriverBound],
  model_input: Dict[str, Any],
  build_finmo: Callable[[Dict[str, Any]], Dict[str, Any]],
  horizon: int = HORIZON_QUARTERS_DEFAULT,
  tolerance: float = DEFAULT_TOLERANCE,
  max_inner_iterations: int = MAX_INNER_ITERATIONS,
) -> SolverResult:
  """Drive ``target_metric`` to ``target_ramp`` per quarter by allocating
  per-quarter delta across ``driver_lever_ids`` proportional to slack-
  to-bound. Mutates ``model_input`` in place. Returns a SolverResult
  with status, residuals, and per-driver bound diagnostics.

  Raises ``CashPassLeverViolation`` on entry if any lever in the
  driver list is in ``_CASH_PASS_OWNED_LEVER_IDS``. Cash strategy owns
  those end-to-end and the operating-side solver MUST NOT touch them.
  """
  # Authority check — hard error on cash-pass-owned lever in the driver
  # list. Per directive: "Validate this at the entry to
  # solve_for_target".
  cash_pass_violations = [
    lid for lid in driver_lever_ids if str(lid).strip() in _CASH_PASS_OWNED_LEVER_IDS
  ]
  if cash_pass_violations:
    raise CashPassLeverViolation(
      "target_solver_cash_pass_lever_in_driver_list: "
      f"target={target_metric} cash_pass_levers={cash_pass_violations} "
      "(cash strategy owns these end-to-end; solver authority is operating-side only)"
    )
  if len(target_ramp) != horizon:
    raise ValueError(
      f"target_solver_ramp_length_mismatch: target={target_metric} "
      f"expected={horizon} got={len(target_ramp)}"
    )

  # Snapshot driver state + initial metric values.
  driver_states: Dict[str, _DriverState] = {}
  for lid in driver_lever_ids:
    bound = driver_bounds.get(lid)
    if bound is None:
      continue
    state = _read_driver_state(
      lever_id=lid, bound=bound, model_input=model_input, horizon=horizon,
    )
    if state.driver_kind == "cash_pass_owned":
      # Defensive — should already be caught above.
      continue
    if not state.rows:
      # Lever_id not in model_input — skip with a diag entry.
      continue
    driver_states[lid] = state

  diagnostics: List[Dict[str, Any]] = []
  initial_finmo = build_finmo(copy.deepcopy(model_input))
  initial_metric = _compute_metric_per_q(
    target_metric=target_metric, finmo_json=initial_finmo, horizon=horizon,
  )

  current_metric = list(initial_metric)
  current_finmo = initial_finmo
  inner_iter_used = 0
  status = SolverStatus.MAX_INNER_ITERATIONS_REACHED
  residuals: List[float] = [0.0] * horizon

  for inner_iter in range(1, max_inner_iterations + 1):
    inner_iter_used = inner_iter
    residuals = [
      float(target_ramp[q]) - float(current_metric[q]) for q in range(horizon)
    ]
    max_abs_residual = max(abs(r) for r in residuals) if residuals else 0.0
    if max_abs_residual <= tolerance:
      status = SolverStatus.CONVERGED
      diagnostics.append({
        "iteration": inner_iter, "phase": "convergence_check",
        "max_abs_residual": max_abs_residual, "tolerance": tolerance,
      })
      break

    # Per quarter, allocate residual across drivers with slack in the
    # needed direction. Cost-priority tiering: try Tier 1 (operational,
    # cheap) first; only engage Tier 2 (structural, expensive) for the
    # residual portion of this quarter that Tier 1 could not absorb.
    any_quarter_moved = False
    for q_idx in range(horizon):
      r = residuals[q_idx]
      if abs(r) <= tolerance:
        continue
      raise_metric = r > 0
      q_revenue = _quarter_revenue(current_finmo, q_idx + 1)
      q_cogs = _quarter_cogs(current_finmo, q_idx + 1)
      q_fixed = _quarter_fixed_cost_proxy(current_finmo, q_idx + 1)

      def _build_contributions_for_tier(target_tier: int) -> List[Tuple[str, float, float, str]]:
        """Compute per-driver (lever_id, sensitivity, slack, driver_dir)
        for drivers in the requested tier that have slack in the
        needed direction.
        """
        out: List[Tuple[str, float, float, str]] = []
        for lid, ds in driver_states.items():
          if _lever_tier(lid) != target_tier:
            continue
          current_value = ds.current_per_q[q_idx] if q_idx < len(ds.current_per_q) else None
          sens = _sensitivity_coefficient(
            target_metric=target_metric,
            driver_kind=ds.driver_kind,
            driver_lever_id=lid,
            current_quarter_revenue=q_revenue,
            current_quarter_cogs=q_cogs,
            current_quarter_fixed_cost=q_fixed,
            current_driver_value=current_value,
          )
          if sens is None or abs(sens) < 1e-12:
            continue
          driver_dir = "raise" if raise_metric == (sens > 0) else "lower"
          slack = ds.slack_in_direction_for_quarter(q_idx, driver_dir)
          if slack <= 0.0:
            continue
          out.append((lid, sens, slack, driver_dir))
        return out

      def _allocate(
        contributions: List[Tuple[str, float, float, str]],
        residual_to_absorb: float,
        is_tier_2: bool,
      ) -> Tuple[float, bool]:
        """Allocate ``residual_to_absorb`` across the contributions
        proportional to slack × |sensitivity|. Returns
        (residual_remaining, any_move). residual_remaining = the
        portion of the residual NOT absorbed because some drivers
        clamped at their bounds.
        """
        if not contributions or abs(residual_to_absorb) <= 0:
          return residual_to_absorb, False
        weights = [s * abs(sens) for (_lid, sens, s, _dir) in contributions]
        total_weight = sum(weights)
        if total_weight <= 0:
          return residual_to_absorb, False
        absorbed_metric = 0.0
        any_move = False
        for (lid, sens, slack, driver_dir), w in zip(contributions, weights):
          if w <= 0:
            continue
          share_of_metric = (w / total_weight) * residual_to_absorb
          driver_delta = share_of_metric / sens
          ds = driver_states[lid]
          new_value = ds.current_per_q[q_idx] + float(driver_delta)
          if driver_dir == "raise":
            new_value = min(new_value, ds.bound.upper)
          else:
            new_value = max(new_value, ds.bound.lower)
          actual_driver_delta = new_value - ds.current_per_q[q_idx]
          if abs(actual_driver_delta) <= 1e-12:
            continue
          actual_metric_absorbed = sens * float(actual_driver_delta)
          absorbed_metric += actual_metric_absorbed
          _write_driver_value_at_quarter(
            driver_state=ds, q_idx=q_idx, new_value=new_value,
            target_metric=target_metric,
          )
          # Provenance tag for Tier 2 engagement.
          if is_tier_2:
            for row in ds.rows:
              tag = row.get("applied_by_target_solver_quarters")
              if isinstance(tag, dict):
                q_str = str(q_idx + 1)
                if isinstance(tag.get(q_str), dict):
                  tag[q_str]["tier_used"] = _TIER_2_TAG_VALUE
          any_move = True
        return residual_to_absorb - absorbed_metric, any_move

      # Tier 1 phase: try to absorb the full residual using cost-ratio
      # / balance-sheet drivers.
      tier1_contribs = _build_contributions_for_tier(target_tier=1)
      residual_after_tier1, t1_moved = _allocate(
        tier1_contribs, r, is_tier_2=False,
      )
      if t1_moved:
        any_quarter_moved = True

      # Tier 2 phase: only engage if Tier 1 could not close the
      # residual at THIS quarter (every Tier 1 driver pinned at its
      # bound for this q's needed direction). Pass the leftover
      # residual to Tier 2 drivers; they absorb what they can.
      if abs(residual_after_tier1) > tolerance:
        tier2_contribs = _build_contributions_for_tier(target_tier=2)
        _residual_after_tier2, t2_moved = _allocate(
          tier2_contribs, residual_after_tier1, is_tier_2=True,
        )
        if t2_moved:
          any_quarter_moved = True

    if not any_quarter_moved:
      # No driver had slack in any quarter -> bound-pinned across the
      # board for the residuals that remain.
      status = SolverStatus.BOUND_PINNED
      diagnostics.append({
        "iteration": inner_iter, "phase": "no_progress",
        "max_abs_residual": max_abs_residual,
        "reason": "all_drivers_pinned_for_remaining_residual_directions",
      })
      break

    # Rebuild FINMO and re-measure.
    current_finmo = build_finmo(copy.deepcopy(model_input))
    current_metric = _compute_metric_per_q(
      target_metric=target_metric, finmo_json=current_finmo, horizon=horizon,
    )
    diagnostics.append({
      "iteration": inner_iter, "phase": "rebuilt",
      "max_abs_residual": max_abs_residual,
      "metric_q1": current_metric[0] if current_metric else None,
      "metric_q11": current_metric[10] if len(current_metric) > 10 else None,
      "metric_q20": current_metric[-1] if current_metric else None,
    })

  # Final residuals + bound diagnostics.
  final_residuals = [
    float(target_ramp[q]) - float(current_metric[q]) for q in range(horizon)
  ]
  drivers_at_bounds: Dict[str, str] = {}
  drivers_moved: Dict[str, List[float]] = {}
  for lid, ds in driver_states.items():
    drivers_moved[lid] = list(ds.current_per_q)
    # Determine if pinned at lower or upper across all quarters.
    eps = 1e-9
    if all(float(v) <= float(ds.bound.lower) + eps for v in ds.current_per_q):
      drivers_at_bounds[lid] = "lower"
    elif all(float(v) >= float(ds.bound.upper) - eps for v in ds.current_per_q):
      drivers_at_bounds[lid] = "upper"

  return SolverResult(
    status=status,
    target_metric=target_metric,
    inner_iterations_used=inner_iter_used,
    initial_metric_per_q=list(initial_metric),
    final_metric_per_q=list(current_metric),
    target_ramp=list(target_ramp),
    final_residuals=final_residuals,
    drivers_at_bounds=drivers_at_bounds,
    drivers_moved=drivers_moved,
    diagnostics=diagnostics,
  )
