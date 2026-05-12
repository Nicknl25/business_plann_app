"""Phase 7.2 — Feasibility Restoration Cascade.

Phase 6 Step 9 introduced an upstream structural feasibility check that
HALTED the run on infeasibility. Phase 7.2 rewires that signal into a
cascade entry point: when the structural check finds the operator's
configured intake can't produce a feasible plan, this module ADAPTS the
inputs (unit price, utilization, capacity) until the gap closes.

Architectural principle (Phase 7.2 directive):
  - The system fixes infeasibility, it does not report infeasibility.
  - The customer always gets a plan. "Failure for a customer is not an
    option."
  - The restoration cascade tries levers in priority order. Each lever
    has a band ceiling drawn from NAICS percentiles or the mapping
    table. Cumulative gap-closing.
  - If after all in-band levers the gap is still > 0, the final lever
    is unbounded capacity expansion. The plan transparently reports
    what assumption was stretched so the operator knows what they need
    to actually change.

Lever priority:
  1. Unit price within band — push toward NAICS price ceiling.
  2. Utilization within band — push toward 0.95 cap.
  3. Capacity expansion (unbounded final guarantee) — whatever capacity
     it takes to clear the residual gap. Reports the multiplier so the
     operator sees "to be feasible, your business needs to scale to N
     units/period (Mx current)."

Phase 9 P3.10 Bug C — the prior "headcount rationalization" Lever 1
was removed in commit
phase_9_p3_10_fix_bug_c_remove_phase_7_2_headcount_rationalization.
That lever was a workaround for a build-time bug (schedule anchoring
on operator_stated_current_payroll / 4) that no longer exists; today's
schedule build is per-row OEWS-resolved. Capping payroll without
rebuilding rows produced the divergence the existing
``payroll_headcount_quarter_total_mismatch`` fail-fast catches.
``post_intake_realism/lookup.py:548`` Golden Rule (payroll is not
clipped to NAICS) is the operative policy.

The orchestrator consumes ``RestorationResult.adjusted_ops_json`` and
``adjusted_payroll_headcount`` and patches the model_input rows for the
revenue drivers and payroll expense before Phase 3 consultants run.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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


# Maximum permissive utilization. Anything higher is structurally
# unrealistic.
_UTILIZATION_BAND_MAX = 0.95

# Price uplift cap as a multiplier of stated price. Going beyond 2x
# requires explicit operator review of pricing strategy.
_PRICE_BAND_MAX_MULTIPLIER = 2.0


@dataclass
class RestorationResult:
  feasible_after_adjustment: bool
  initial_gap_annual: float
  residual_gap_annual: float
  capacity_revenue_annual: float
  fixed_cost_annual_after: Optional[float] = None
  applied_adjustments: List[Dict[str, Any]] = field(default_factory=list)
  adjusted_ops_json: Optional[Dict[str, Any]] = None
  adjusted_payroll_headcount: Optional[Dict[str, Any]] = None
  diagnostic_narrative: str = ""

  def to_dict(self) -> Dict[str, Any]:
    return {
      "feasible_after_adjustment": bool(self.feasible_after_adjustment),
      "initial_gap_annual": float(self.initial_gap_annual or 0.0),
      "residual_gap_annual": float(self.residual_gap_annual or 0.0),
      "capacity_revenue_annual": float(self.capacity_revenue_annual or 0.0),
      "fixed_cost_annual_after": (
        float(self.fixed_cost_annual_after)
        if self.fixed_cost_annual_after is not None else None
      ),
      "applied_adjustments": list(self.applied_adjustments),
      "diagnostic_narrative": self.diagnostic_narrative,
    }


def _capacity_revenue_from_ops(ops_json: Dict[str, Any]) -> Optional[float]:
  capacity = (
    _safe_float(ops_json.get("units_per_period_capacity"))
    or _safe_float(ops_json.get("units_per_week_capacity"))
  )
  unit_price = _safe_float(ops_json.get("unit_price"))
  periods = _safe_float(ops_json.get("operating_periods_per_year")) or 12.0
  utilization = _safe_float(ops_json.get("utilization_rate")) or _UTILIZATION_BAND_MAX
  utilization = min(utilization, _UTILIZATION_BAND_MAX)
  if capacity and unit_price and capacity > 0 and unit_price > 0:
    return float(capacity) * float(unit_price) * float(periods) * float(utilization)
  return None


def _apply_price_lift(
  *,
  adjusted_ops: Dict[str, Any],
  current_capacity_revenue_annual: float,
  current_gap_annual: float,
  adjustments: List[Dict[str, Any]],
) -> float:
  """Lever 2: raise unit_price within band. Returns the revenue lift
  contribution toward closing the gap."""
  current_price = _safe_float(adjusted_ops.get("unit_price"))
  if current_price is None or current_price <= 0:
    return 0.0
  capacity = (
    _safe_float(adjusted_ops.get("units_per_period_capacity"))
    or _safe_float(adjusted_ops.get("units_per_week_capacity"))
  )
  periods = _safe_float(adjusted_ops.get("operating_periods_per_year")) or 12.0
  utilization = min(
    _safe_float(adjusted_ops.get("utilization_rate")) or _UTILIZATION_BAND_MAX,
    _UTILIZATION_BAND_MAX,
  )
  if not capacity or capacity <= 0 or not periods or periods <= 0:
    return 0.0

  # Required price to close the gap (with 5% buffer).
  required_revenue_annual = current_capacity_revenue_annual + current_gap_annual * 1.05
  required_price = required_revenue_annual / (
    float(capacity) * float(periods) * float(utilization)
  )
  band_max_price = float(current_price) * _PRICE_BAND_MAX_MULTIPLIER
  new_price = min(required_price, band_max_price)
  if new_price <= current_price:
    return 0.0

  adjusted_ops["unit_price"] = round(new_price, 4)
  adjusted_ops["_phase_7_2_price_lifted_from"] = current_price
  revenue_lift = (new_price - current_price) * float(capacity) * float(periods) * float(utilization)
  adjustments.append({
    "lever": "unit_price_within_band",
    "price_before": float(current_price),
    "price_after": round(new_price, 4),
    "annual_revenue_lift": round(revenue_lift, 2),
    "rationale": (
      f"Lifting unit_price from ${current_price:.2f} to ${new_price:.2f} "
      f"(within {_PRICE_BAND_MAX_MULTIPLIER:.1f}x band ceiling) closes "
      f"${revenue_lift:,.0f}/yr of the residual gap."
    ),
  })
  return revenue_lift


def _apply_utilization_lift(
  *,
  adjusted_ops: Dict[str, Any],
  current_capacity_revenue_annual: float,
  current_gap_annual: float,
  adjustments: List[Dict[str, Any]],
) -> float:
  """Lever 3: raise utilization toward 0.95 ceiling."""
  current_util = _safe_float(adjusted_ops.get("utilization_rate"))
  if current_util is None or current_util >= _UTILIZATION_BAND_MAX:
    return 0.0
  if current_util <= 0:
    return 0.0
  new_util = _UTILIZATION_BAND_MAX
  if new_util <= current_util:
    return 0.0

  capacity = (
    _safe_float(adjusted_ops.get("units_per_period_capacity"))
    or _safe_float(adjusted_ops.get("units_per_week_capacity"))
  )
  unit_price = _safe_float(adjusted_ops.get("unit_price"))
  periods = _safe_float(adjusted_ops.get("operating_periods_per_year")) or 12.0
  if not (capacity and unit_price and capacity > 0 and unit_price > 0):
    return 0.0

  revenue_lift_per_unit_util = float(capacity) * float(unit_price) * float(periods)
  revenue_lift = (new_util - current_util) * revenue_lift_per_unit_util
  if revenue_lift <= 0:
    return 0.0

  adjusted_ops["utilization_rate"] = new_util
  adjusted_ops["_phase_7_2_utilization_lifted_from"] = current_util
  adjustments.append({
    "lever": "utilization_within_band",
    "utilization_before": float(current_util),
    "utilization_after": float(new_util),
    "annual_revenue_lift": round(revenue_lift, 2),
    "rationale": (
      f"Lifting utilization from {current_util:.2f} to {new_util:.2f} "
      f"(plausible-maximum) closes ${revenue_lift:,.0f}/yr."
    ),
  })
  _ = current_gap_annual  # used by caller for gap accounting
  return revenue_lift


def _apply_capacity_expansion(
  *,
  adjusted_ops: Dict[str, Any],
  current_capacity_revenue_annual: float,
  current_gap_annual: float,
  adjustments: List[Dict[str, Any]],
) -> float:
  """Lever 4 (final guarantee): expand capacity to whatever-needed.

  No upper bound. The plan transparently reports the multiplier so the
  operator sees what scale the business needs to reach for the plan to
  be viable. Per Phase 7.2 directive: customer always gets a plan; this
  is the final fallback that guarantees that.

  Phase 9.5 Fix D — removed the prior `if required_capacity <=
  current_capacity: return 0.0` early-exit. That guard was structurally
  wrong for the "always lands" guarantee: the only signal the lever
  needs is `current_gap_annual > 0` (still residual to close). When
  upstream lever math (price / utilization) was computed against a
  zero baseline and produced a degenerate "you don't need it" result,
  the capacity lever was the last line of defense and bowing out
  silently let the plan ship infeasible.
  """
  if current_gap_annual <= 0:
    return 0.0
  current_capacity = (
    _safe_float(adjusted_ops.get("units_per_period_capacity"))
    or _safe_float(adjusted_ops.get("units_per_week_capacity"))
  )
  unit_price = _safe_float(adjusted_ops.get("unit_price"))
  periods = _safe_float(adjusted_ops.get("operating_periods_per_year")) or 12.0
  utilization = min(
    _safe_float(adjusted_ops.get("utilization_rate")) or _UTILIZATION_BAND_MAX,
    _UTILIZATION_BAND_MAX,
  )
  if not (current_capacity and unit_price and current_capacity > 0 and unit_price > 0):
    return 0.0

  required_revenue_annual = current_capacity_revenue_annual + current_gap_annual * 1.05
  required_capacity_raw = required_revenue_annual / (
    float(unit_price) * float(periods) * float(utilization)
  )
  # Always expand by enough to close the residual gap, even if the
  # arithmetic produces a value at or below current capacity (would
  # only happen with a degenerate baseline). The customer-final
  # guarantee is "always lands" — bowing out here breaks it.
  required_capacity = max(
    required_capacity_raw,
    float(current_capacity) + current_gap_annual / (
      float(unit_price) * float(periods) * float(utilization)
    ),
  )
  if required_capacity <= current_capacity:
    # Even after the floor, the math says no expansion is meaningful.
    # This should be unreachable when current_gap_annual > 0.
    return 0.0

  adjusted_ops["units_per_period_capacity"] = round(required_capacity, 2)
  if "units_per_week_capacity" in adjusted_ops:
    adjusted_ops["units_per_week_capacity"] = round(required_capacity, 2)
  adjusted_ops["_phase_7_2_capacity_expanded_from"] = current_capacity
  multiplier = required_capacity / float(current_capacity)
  revenue_lift = (required_capacity - current_capacity) * float(unit_price) * float(periods) * float(utilization)
  adjustments.append({
    "lever": "capacity_expansion_unbounded",
    "capacity_before": float(current_capacity),
    "capacity_after": round(required_capacity, 2),
    "expansion_multiplier": round(multiplier, 2),
    "annual_revenue_lift": round(revenue_lift, 2),
    "rationale": (
      f"Expanding capacity from {current_capacity:.0f} to "
      f"{required_capacity:.0f} units/period ({multiplier:.2f}x) closes "
      f"the remaining ${current_gap_annual:,.0f}/yr gap. Final-tier "
      "lever: the plan is viable AT this scale; the operator must "
      "evaluate whether expansion to that level is achievable."
    ),
  })
  return revenue_lift


def restore_feasibility(
  *,
  structural_result: Any,
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]],
  payroll_headcount: Optional[Dict[str, Any]],
  business_naics_6: Optional[str],
  industry_profile: Optional[Dict[str, Any]] = None,
) -> RestorationResult:
  """Phase 7.2 cascade entry point. Tries levers in priority until gap
  closes; final lever (capacity expansion) is unbounded so the customer
  always gets a feasible plan.

  Returns adjusted ops_json + payroll_headcount the orchestrator should
  swap in before Phase 3 consultants run.
  """
  initial_gap = _safe_float(getattr(structural_result, "feasibility_gap", None)) or 0.0
  capacity_revenue_initial = (
    _safe_float(getattr(structural_result, "upper_bound_annual_revenue", None)) or 0.0
  )
  fixed_cost_initial = (
    _safe_float(getattr(structural_result, "lower_bound_annual_fixed_cost", None)) or 0.0
  )

  adjustments: List[Dict[str, Any]] = []
  adjusted_ops = copy.deepcopy(ops_json or {})
  adjusted_payroll = copy.deepcopy(payroll_headcount or {})

  # Phase 9 P3.10 Bug C — business_naics_6 + industry_profile were
  # consumed only by the removed headcount_rationalization lever; kept
  # in the signature so existing callers don't break.
  _ = financials_json, financials_year1_json, business_naics_6, industry_profile

  if initial_gap <= 0:
    return RestorationResult(
      feasible_after_adjustment=True,
      initial_gap_annual=0.0,
      residual_gap_annual=0.0,
      capacity_revenue_annual=capacity_revenue_initial,
      fixed_cost_annual_after=fixed_cost_initial,
      applied_adjustments=[],
      adjusted_ops_json=adjusted_ops,
      adjusted_payroll_headcount=adjusted_payroll,
      diagnostic_narrative="Already feasible; no restoration applied.",
    )

  current_gap = float(initial_gap)
  current_capacity_revenue = float(capacity_revenue_initial)

  # Phase 9 P3.10 Bug C — the prior Lever 1 (headcount rationalization)
  # was removed. The current schedule build is per-row OEWS-resolved
  # (no current_payroll/4 anchor), so the cap workaround it patched is
  # obsolete; capping payroll while leaving rows untouched produced the
  # divergence the existing payroll_headcount_quarter_total_mismatch
  # fail-fast catches. Levers 1-3 below (price / utilization / capacity)
  # absorb any structural gap the operator-stated payroll exposes.

  # Lever 1: unit price within band
  if current_gap > 0:
    price_lift = _apply_price_lift(
      adjusted_ops=adjusted_ops,
      current_capacity_revenue_annual=current_capacity_revenue,
      current_gap_annual=current_gap,
      adjustments=adjustments,
    )
    current_gap -= price_lift
    current_capacity_revenue += price_lift

  # Lever 2: utilization within band
  if current_gap > 0:
    util_lift = _apply_utilization_lift(
      adjusted_ops=adjusted_ops,
      current_capacity_revenue_annual=current_capacity_revenue,
      current_gap_annual=current_gap,
      adjustments=adjustments,
    )
    current_gap -= util_lift
    current_capacity_revenue += util_lift

  # Lever 3: capacity expansion (unbounded final guarantee)
  if current_gap > 0:
    capacity_lift = _apply_capacity_expansion(
      adjusted_ops=adjusted_ops,
      current_capacity_revenue_annual=current_capacity_revenue,
      current_gap_annual=current_gap,
      adjustments=adjustments,
    )
    current_gap -= capacity_lift
    current_capacity_revenue += capacity_lift

  feasible = current_gap <= 0
  # Phase 9 P3.10 Bug C — fixed_cost_after no longer subtracts the
  # removed headcount_rationalization savings; pass-through unchanged.
  fixed_cost_after = fixed_cost_initial

  if not adjustments:
    narrative = "No adjustments applicable; restoration cascade had no levers to pull."
  else:
    lever_summary = ", ".join(adj["lever"] for adj in adjustments)
    if feasible:
      narrative = (
        f"Feasibility restored via cascade (levers applied: {lever_summary}). "
        f"Initial gap: ${initial_gap:,.0f}/yr. Plan can land at the adapted "
        "configuration; downstream solver continues with adjusted inputs."
      )
    else:
      narrative = (
        f"Restoration cascade exhausted at gap=${current_gap:,.0f}/yr after "
        f"applying levers: {lever_summary}. This is the customer-final "
        "guarantee path; the plan will reflect the adapted configuration "
        "but residual gap remains and the final report should flag the "
        "operator to review intake assumptions."
      )

  return RestorationResult(
    feasible_after_adjustment=feasible,
    initial_gap_annual=float(initial_gap),
    residual_gap_annual=round(current_gap, 2),
    capacity_revenue_annual=round(current_capacity_revenue, 2),
    fixed_cost_annual_after=round(fixed_cost_after, 2),
    applied_adjustments=adjustments,
    adjusted_ops_json=adjusted_ops,
    adjusted_payroll_headcount=adjusted_payroll,
    diagnostic_narrative=narrative,
  )
