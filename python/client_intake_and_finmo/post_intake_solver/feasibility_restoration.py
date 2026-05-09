"""Phase 7.2 — Feasibility Restoration Cascade.

Phase 6 Step 9 introduced an upstream structural feasibility check that
HALTED the run on infeasibility. Phase 7.2 rewires that signal into a
cascade entry point: when the structural check finds the operator's
configured intake can't produce a feasible plan, this module ADAPTS the
inputs (payroll schedule, unit price, utilization, capacity) until the
gap closes.

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
  1. Headcount rationalization — when today's payroll exceeds capacity-
     implied requirements (NAICS payroll_percent_of_revenue × capacity-
     driven revenue), cap the schedule at the capacity-appropriate
     level. This is the deferred "headcount anchored on operator's
     current_payroll" bug, addressed here as part of the restoration
     toolkit.
  2. Unit price within band — push toward NAICS price ceiling.
  3. Utilization within band — push toward 0.95 cap.
  4. Capacity expansion (unbounded final guarantee) — whatever capacity
     it takes to clear the residual gap. Reports the multiplier so the
     operator sees "to be feasible, your business needs to scale to N
     units/period (Mx current)."

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

# When NAICS payroll baseline is missing, fall back to 35% of revenue —
# a conservative ratio that supports most retail/services businesses.
_FALLBACK_PAYROLL_PCT_OF_REVENUE = 0.35

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


def _naics_payroll_pct(
  business_naics_6: Optional[str],
  *,
  industry_profile: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
  """Phase 9 Step 2b — prefer Phase E IndustryProfile when provided.

  Falls back to direct NAICS lookup so the function still works when
  industry_profile isn't threaded through (e.g., upstream structural
  feasibility check that runs at intake time).
  """
  if isinstance(industry_profile, dict):
    bands = industry_profile.get("bands") or {}
    if isinstance(bands, dict):
      band_p = bands.get("payroll_percent_of_revenue")
      if isinstance(band_p, dict):
        target_p = _safe_float(band_p.get("benchmark_target"))
        if target_p is not None and 0.0 < target_p < 1.0:
          return float(target_p)
  if not business_naics_6:
    return None
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    band = post_intake_industry_baseline_for_naics(
      metric_key="payroll_percent_of_revenue",
      naics_6=str(business_naics_6),
    )
  except Exception:
    return None
  if not isinstance(band, dict):
    return None
  target = _safe_float(band.get("benchmark_target"))
  if target is not None and 0.0 < target < 1.0:
    return float(target)
  return None


def _annual_payroll_from_schedule(payroll_headcount: Optional[Dict[str, Any]]) -> Optional[float]:
  if not isinstance(payroll_headcount, dict):
    return None
  quarter_totals = payroll_headcount.get("quarter_totals")
  if not isinstance(quarter_totals, list) or not quarter_totals:
    return None
  values: List[float] = []
  for row in quarter_totals[:4]:
    if isinstance(row, dict):
      payroll = _safe_float(row.get("payroll"))
      if payroll is not None:
        values.append(payroll)
  if not values:
    return None
  return float(sum(values))


def _apply_headcount_rationalization(
  *,
  adjusted_payroll: Dict[str, Any],
  capacity_revenue_annual: float,
  business_naics_6: Optional[str],
  adjustments: List[Dict[str, Any]],
  industry_profile: Optional[Dict[str, Any]] = None,
) -> float:
  """Lever 1: cap payroll schedule at NAICS-implied capacity-appropriate
  level. Returns annual savings (positive number) or 0 when no
  rationalization needed.

  The current schedule anchors on operator's stated current_payroll/4
  (the deferred headcount bug). When operator is over-staffed for
  modeled capacity, this caps each quarter's payroll at
  ``capacity_revenue × naics_payroll_pct / 4``. Downstream consumers
  see the capped values; the override is flagged on the schedule so
  the planning narrative can explain the change.
  """
  current_annual = _annual_payroll_from_schedule(adjusted_payroll)
  if current_annual is None or current_annual <= 0:
    return 0.0

  payroll_pct = (
    _naics_payroll_pct(business_naics_6, industry_profile=industry_profile)
    or _FALLBACK_PAYROLL_PCT_OF_REVENUE
  )
  target_annual = capacity_revenue_annual * payroll_pct
  if current_annual <= target_annual:
    return 0.0

  target_quarter_payroll = target_annual / 4.0
  quarter_totals = adjusted_payroll.get("quarter_totals") or []
  capped_qts: List[Dict[str, Any]] = []
  for row in quarter_totals:
    if not isinstance(row, dict):
      capped_qts.append(row)
      continue
    new_row = dict(row)
    original = _safe_float(row.get("payroll")) or 0.0
    capped = min(original, target_quarter_payroll) if original > 0 else 0.0
    new_row["payroll"] = round(capped, 2)
    new_row["_phase_7_2_capped_for_capacity"] = True
    new_row["_phase_7_2_original_payroll"] = original
    capped_qts.append(new_row)
  adjusted_payroll["quarter_totals"] = capped_qts
  adjusted_payroll["_phase_7_2_headcount_rationalization_applied"] = True
  adjusted_payroll["_phase_7_2_target_annual_payroll"] = round(target_annual, 2)
  adjusted_payroll["_phase_7_2_naics_payroll_pct_used"] = payroll_pct

  capped_q1_q4 = sum(
    _safe_float(r.get("payroll")) or 0.0
    for r in capped_qts[:4] if isinstance(r, dict)
  )
  savings = float(current_annual) - float(capped_q1_q4)
  if savings <= 0:
    return 0.0

  adjustments.append({
    "lever": "headcount_rationalization",
    "payroll_pct_target": payroll_pct,
    "payroll_annual_before": round(current_annual, 2),
    "payroll_annual_after": round(capped_q1_q4, 2),
    "annual_savings": round(savings, 2),
    "rationale": (
      f"Operator's stated payroll (${current_annual:,.0f}/yr) exceeds the "
      f"capacity-implied level for NAICS {business_naics_6 or 'unknown'} "
      f"(payroll {payroll_pct * 100:.0f}% of capacity-driven revenue "
      f"${capacity_revenue_annual:,.0f} = ${target_annual:,.0f}/yr). "
      f"Capping payroll schedule at capacity-appropriate level."
    ),
  })
  return savings


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

  _ = financials_json, financials_year1_json  # accepted for forward compatibility

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

  # Lever 1: headcount rationalization
  payroll_savings = _apply_headcount_rationalization(
    adjusted_payroll=adjusted_payroll,
    capacity_revenue_annual=current_capacity_revenue,
    business_naics_6=business_naics_6,
    adjustments=adjustments,
    industry_profile=industry_profile,
  )
  current_gap -= payroll_savings

  # Lever 2: unit price within band (only fires if gap remains)
  if current_gap > 0:
    price_lift = _apply_price_lift(
      adjusted_ops=adjusted_ops,
      current_capacity_revenue_annual=current_capacity_revenue,
      current_gap_annual=current_gap,
      adjustments=adjustments,
    )
    current_gap -= price_lift
    current_capacity_revenue += price_lift

  # Lever 3: utilization within band
  if current_gap > 0:
    util_lift = _apply_utilization_lift(
      adjusted_ops=adjusted_ops,
      current_capacity_revenue_annual=current_capacity_revenue,
      current_gap_annual=current_gap,
      adjustments=adjustments,
    )
    current_gap -= util_lift
    current_capacity_revenue += util_lift

  # Lever 4: capacity expansion (unbounded final guarantee)
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
  fixed_cost_after = (
    fixed_cost_initial - sum(
      _safe_float(adj.get("annual_savings")) or 0.0
      for adj in adjustments if adj.get("lever") == "headcount_rationalization"
    )
  )

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
