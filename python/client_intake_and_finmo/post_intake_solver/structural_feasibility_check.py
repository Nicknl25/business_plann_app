"""Phase 6 Step 9 — pre-flight structural feasibility check.

Runs BEFORE Phase 3 calibration and BEFORE the inner runner. Catches
the case where a business as configured cannot be modeled by the
system: no combination of band-internal lever values can produce a
viable plan because revenue at any plausible utilization can't cover
the configured fixed costs.

Pre-Phase-6, the system would run the full convergence cycle, fail to
land, and either raise out the stack or land at Tier 7 with a
papered-over plan (Phase 5.2 work confirmed this for Sunny Glaze). The
honest answer for that class of business is "this configuration cannot
be modeled — revenue must increase, costs must decrease, or capital
injection must fund losses." Step 9 produces that diagnostic upstream.

The check is intentionally lightweight:
  - Compute upper-bound annual revenue at maximum plausible utilization
    using the intake's stated capacity and pricing.
  - Compute lower-bound annual fixed costs from the intake's stated
    payroll headcount, lease, and debt service.
  - Flag structurally_infeasible when upper revenue < lower cost.
  - Compute concrete recommended adjustments (revenue delta, cost
    delta, or required capital injection) to bridge the gap.

When infeasible, the orchestrator surfaces a structured diagnostic and
halts the run. The cascade's Tier 7 is no longer asked to invent a
plan for a business that mathematically can't have one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# Plausible-maximum utilization for the upper-bound revenue estimate.
# 0.95 because hitting 100% sustained is not realistic; 0.80 would be
# too conservative and reject borderline-feasible businesses.
_UPPER_BOUND_UTILIZATION = 0.95

# Fixed-cost ratio applied to operating expenses for businesses that
# don't itemize lease / payroll separately. Conservative — keeps the
# check from over-rejecting.
_FIXED_COST_BUFFER_FRACTION = 0.05

# Mature quarters over which feasibility is evaluated. The check asks
# "at any mature quarter, does capacity-driven revenue cover quarter
# fixed cost?" — comparing a ramp's first year to steady-state cost
# rejects every legitimate startup. Q12-Q20 (years 4-5) is the
# steady-state window.
_MATURE_QUARTER_RANGE = range(12, 21)


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


@dataclass
class StructuralFeasibilityResult:
  feasible: bool
  upper_bound_annual_revenue: Optional[float] = None
  lower_bound_annual_fixed_cost: Optional[float] = None
  feasibility_gap: Optional[float] = None
  diagnostic_message: str = ""
  recommended_adjustments: List[Dict[str, Any]] = field(default_factory=list)
  inputs_used: Dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> Dict[str, Any]:
    return {
      "feasible": bool(self.feasible),
      "upper_bound_annual_revenue": self.upper_bound_annual_revenue,
      "lower_bound_annual_fixed_cost": self.lower_bound_annual_fixed_cost,
      "feasibility_gap": self.feasibility_gap,
      "diagnostic_message": self.diagnostic_message,
      "recommended_adjustments": list(self.recommended_adjustments),
      "inputs_used": dict(self.inputs_used),
    }


def capacity_driven_annual_revenue(
  *,
  ops_json: Optional[Dict[str, Any]],
  upper_bound_utilization: float = _UPPER_BOUND_UTILIZATION,
) -> Optional[float]:
  """Capacity-driven mature-state annual revenue ceiling.

  Returns ``capacity * unit_price * operating_periods_per_year *
  upper_bound_utilization`` from the intake operating model. This is the
  authoritative answer to "what can this business produce at full
  capacity?" — the upper bound for any derived quantity that needs a
  revenue ceiling (structural feasibility, balance-sheet-days divisor,
  cohort revenue bucket, COGS-ratio fallback denominator).

  Returns None when the intake didn't supply capacity or unit_price —
  callers decide whether to fall back to operator's Year-1 projection
  or to a snapshot value.

  Note: ``operating_periods_per_year`` defaults to 12 (monthly) when
  not stated; this matches the existing system convention but produces
  wrong scale if the cadence is weekly/daily and the field is missing.
  Intake validation should catch that upstream.
  """
  ops = ops_json if isinstance(ops_json, dict) else {}
  capacity = (
    _safe_float(ops.get("units_per_period_capacity"))
    or _safe_float(ops.get("units_per_week_capacity"))
  )
  unit_price = _safe_float(ops.get("unit_price"))
  periods = _safe_float(ops.get("operating_periods_per_year")) or 12.0
  if capacity and unit_price and capacity > 0 and unit_price > 0:
    return float(capacity) * float(unit_price) * float(periods) * float(upper_bound_utilization)
  return None


def authoritative_annual_revenue(
  *,
  ops_json: Optional[Dict[str, Any]],
  financials_year1_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  upper_bound_utilization: float = _UPPER_BOUND_UTILIZATION,
) -> Optional[float]:
  """Authoritative annual revenue for any post-intake derivation.

  Priority order:
    1. ``capacity_driven_annual_revenue(ops_json)`` — capacity * price *
       periods * upper-bound utilization. The architecturally correct
       answer for "what's the revenue ceiling this business can produce?"
    2. ``financials_year1_json.company_revenue_total_year1`` /
       ``revenue_total_year1`` — operator's Year-1 ramp projection.
       Fallback ONLY when capacity data is missing. The operator's
       projection is a planning expectation, not a structural ceiling.
    3. ``financials_json.current_revenue`` — current-state snapshot.
       Last resort; used when both capacity and Year-1 projection are
       absent.

  Returns None when no source has usable data.

  This is the single source of truth for the post-intake "what scale
  is this business?" question across the structural feasibility check,
  balance-sheet-days computation, COGS ratio fallback, planning-mode
  classification, and cohort selection. Anywhere code previously read
  ``company_revenue_total_year1`` / ``current_revenue`` directly to
  derive a downstream quantity, it should call this helper instead.
  """
  capacity_revenue = capacity_driven_annual_revenue(
    ops_json=ops_json, upper_bound_utilization=upper_bound_utilization,
  )
  if capacity_revenue is not None and capacity_revenue > 0:
    return capacity_revenue

  year1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  rev_year_one = (
    _safe_float(year1.get("company_revenue_total_year1"))
    or _safe_float(year1.get("revenue_total_year1"))
  )
  if rev_year_one is not None and rev_year_one > 0:
    return float(rev_year_one)

  fin = financials_json if isinstance(financials_json, dict) else {}
  current_rev = _safe_float(fin.get("current_revenue"))
  if current_rev is not None and current_rev > 0:
    return float(current_rev)
  return None


def _annual_lease_and_interest(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Tuple[Optional[float], Optional[float]]:
  """Annual lease and interest from intake. Both scale per quarter as
  annual / 4. Returns (lease_annual, interest_annual)."""
  lease_annual = (
    _safe_float(financials_year1_json.get("lease_year_one"))
    or _safe_float(financials_year1_json.get("annual_lease_total"))
    or _safe_float(financials_json.get("annual_lease"))
    or _safe_float(financials_json.get("lease_amount_annual"))
  )
  monthly_rent = _safe_float(financials_json.get("monthly_rent_expense"))
  if (lease_annual is None or lease_annual <= 0) and monthly_rent and monthly_rent > 0:
    lease_annual = float(monthly_rent) * 12.0
  interest_annual = (
    _safe_float(financials_json.get("annual_interest_payment"))
    or _safe_float(financials_year1_json.get("interest_year_one"))
  )
  return (
    float(lease_annual) if lease_annual and lease_annual > 0 else None,
    float(interest_annual) if interest_annual and interest_annual > 0 else None,
  )


def _payroll_at_quarter(
  *,
  payroll_headcount: Optional[Dict[str, Any]],
  quarter_index: int,
  fallback_annual_payroll: Optional[float],
) -> Optional[float]:
  """Quarter-level payroll for the given quarter index.

  Reads ``payroll_headcount.quarter_totals[quarter_index - 1].payroll``.
  Falls back to ``fallback_annual_payroll / 4`` (year-1 averaged) when
  the schedule is absent. Returns None when no source has data.
  """
  if isinstance(payroll_headcount, dict):
    quarter_totals = payroll_headcount.get("quarter_totals")
    if isinstance(quarter_totals, list):
      idx = int(quarter_index) - 1
      if 0 <= idx < len(quarter_totals):
        row = quarter_totals[idx]
        if isinstance(row, dict):
          payroll_q = _safe_float(row.get("payroll"))
          if payroll_q is not None and payroll_q >= 0:
            return float(payroll_q)
  if fallback_annual_payroll is not None and fallback_annual_payroll > 0:
    return float(fallback_annual_payroll) / 4.0
  return None


def _fallback_annual_payroll(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
) -> Optional[float]:
  return (
    _safe_float(financials_year1_json.get("annual_payroll_total"))
    or _safe_float(financials_year1_json.get("payroll_year_one"))
    or _safe_float(financials_json.get("annual_payroll"))
    or _safe_float(financials_json.get("current_payroll"))
  )


def _build_recommended_adjustments(
  *,
  upper_bound_revenue: float,
  lower_bound_cost: float,
  ops_json: Dict[str, Any],
  payroll_headcount: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
  """Compute concrete deltas the consultant can act on. Returns a list
  of three options (revenue increase / cost decrease / capital injection)
  plus narrative context. Each option has the magnitude needed to close
  the gap.
  """
  gap = float(lower_bound_cost) - float(upper_bound_revenue)
  if gap <= 0:
    return []
  recs: List[Dict[str, Any]] = []

  capacity = (
    _safe_float(ops_json.get("units_per_period_capacity"))
    or _safe_float(ops_json.get("units_per_week_capacity"))
  )
  unit_price = _safe_float(ops_json.get("unit_price"))
  periods = _safe_float(ops_json.get("operating_periods_per_year")) or 12.0

  if capacity and unit_price and capacity > 0 and unit_price > 0:
    additional_revenue = float(gap) * 1.10
    additional_units_per_period = additional_revenue / (
      float(unit_price) * float(periods) * _UPPER_BOUND_UTILIZATION
    )
    new_capacity = float(capacity) + additional_units_per_period
    new_unit_price = (
      float(unit_price)
      + additional_revenue / max(1.0, float(capacity) * float(periods) * _UPPER_BOUND_UTILIZATION)
    )
    recs.append({
      "kind": "increase_revenue",
      "additional_annual_revenue_required": round(additional_revenue, 2),
      "option_a_capacity_increase": {
        "from_units_per_period": float(capacity),
        "to_units_per_period": round(new_capacity, 2),
        "delta_units_per_period": round(additional_units_per_period, 2),
      },
      "option_b_unit_price_increase": {
        "from_price": float(unit_price),
        "to_price": round(new_unit_price, 2),
        "delta_price": round(new_unit_price - float(unit_price), 2),
      },
      "rationale": (
        "Revenue at configured capacity * price * utilization can't cover "
        "fixed costs. Raise capacity OR raise price to bridge the gap "
        "(values shown are independent — pick one or split between them)."
      ),
    })

  payroll_total = (
    _safe_float((payroll_headcount or {}).get("year_one_payroll_total"))
  )
  recs.append({
    "kind": "decrease_fixed_costs",
    "fixed_cost_reduction_required": round(float(gap) * 1.05, 2),
    "options": [
      "Reduce payroll headcount or compensation",
      "Renegotiate lease / sublet space",
      "Defer debt service or refinance to lower interest",
    ],
    "rationale": (
      "Fixed costs (payroll + lease + interest) exceed achievable revenue. "
      "The gap can also be closed by reducing fixed costs rather than "
      "increasing revenue."
    ),
    "current_payroll_year_one_total": payroll_total,
  })

  recs.append({
    "kind": "capital_injection",
    "capital_required_to_fund_year_one_losses": round(float(gap) * 1.20, 2),
    "rationale": (
      "If revenue and cost adjustments are not feasible, the business "
      "needs capital to fund operating losses through the period until "
      "revenue catches up to fixed costs (typically 12-24 months for "
      "stage-appropriate ramp businesses). The 1.2x buffer covers "
      "working capital needs beyond the bare gap."
    ),
  })

  return recs


def verify_structural_feasibility(
  *,
  ops_json: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
  business_profile: Optional[Dict[str, Any]] = None,
) -> StructuralFeasibilityResult:
  """Pre-flight structural feasibility check (horizon-aware).

  Asks: at any mature quarter (Q12-Q20), does capacity-driven revenue
  cover that quarter's fixed cost? If at least one mature quarter
  passes → feasible. If all mature quarters fail → genuinely
  infeasible.

  Comparing year-1 ramp revenue against year-1 steady-state cost (the
  pre-fix shape) rejects every legitimate startup. The right question
  is whether the business can reach steady-state coverage — a
  forecastability check, not a "current year covers steady-state cost"
  check.

  Args:
    ops_json: intake operating model — capacity, unit_price, periods/yr.
    financials_json: intake snapshot — current_revenue, annual_lease,
      annual_interest_payment, monthly_rent_expense.
    financials_year1_json: year-1 projections (advisory fallback only).
    payroll_headcount: payroll headcount schedule — provides per-quarter
      payroll values for the mature-quarter cost computation.
    business_profile: forwarded for forward compatibility; not used yet.
  """
  ops = ops_json if isinstance(ops_json, dict) else {}
  fin = financials_json if isinstance(financials_json, dict) else {}
  fin_y1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  _ = business_profile  # accepted for forward compatibility

  capacity_revenue_annual = capacity_driven_annual_revenue(ops_json=ops)
  upper_revenue = authoritative_annual_revenue(
    ops_json=ops, financials_year1_json=fin_y1, financials_json=fin,
  )

  lease_annual, interest_annual = _annual_lease_and_interest(
    financials_json=fin, financials_year1_json=fin_y1,
  )
  fallback_payroll = _fallback_annual_payroll(
    financials_json=fin, financials_year1_json=fin_y1,
  )

  inputs_used: Dict[str, Any] = {
    "revenue_source": (
      "ops_json.capacity_x_unit_price_x_periods_x_upper_bound_utilization"
      if capacity_revenue_annual is not None
      else (
        "financials_year1_json.company_revenue_total_year1"
        if _safe_float(fin_y1.get("company_revenue_total_year1"))
        else "financials_json.current_revenue"
      )
    ),
    "capacity_revenue_annual": capacity_revenue_annual,
    "fixed_cost_components": [],
    "upper_bound_utilization": _UPPER_BOUND_UTILIZATION,
    "mature_quarter_range": [_MATURE_QUARTER_RANGE.start, _MATURE_QUARTER_RANGE.stop - 1],
  }
  if isinstance(payroll_headcount, dict) and payroll_headcount.get("quarter_totals"):
    inputs_used["fixed_cost_components"].append("payroll_headcount.quarter_totals (per-quarter)")
  elif fallback_payroll is not None:
    inputs_used["fixed_cost_components"].append("annual_payroll_fallback / 4")
  if lease_annual is not None:
    inputs_used["fixed_cost_components"].append("lease_annual / 4")
  if interest_annual is not None:
    inputs_used["fixed_cost_components"].append("interest_annual / 4")

  if upper_revenue is None:
    return StructuralFeasibilityResult(
      feasible=True,
      upper_bound_annual_revenue=upper_revenue,
      lower_bound_annual_fixed_cost=None,
      feasibility_gap=None,
      diagnostic_message=(
        "insufficient_inputs: capacity / unit_price / Year-1 projection / "
        "current revenue all missing. Cannot assess feasibility; skipping."
      ),
      inputs_used=inputs_used,
    )

  # Per-mature-quarter cost evaluation. Capacity-driven revenue is constant
  # across the horizon by construction (capacity * price * util), so we
  # compare each mature quarter's fixed cost against the same quarterly
  # revenue ceiling. Feasible iff at least one mature quarter clears.
  quarter_revenue_ceiling = float(upper_revenue) / 4.0
  quarter_lease = float(lease_annual) / 4.0 if lease_annual else 0.0
  quarter_interest = float(interest_annual) / 4.0 if interest_annual else 0.0

  per_quarter_evaluation: List[Dict[str, Any]] = []
  any_feasible_quarter = False
  best_quarter: Optional[Dict[str, Any]] = None  # smallest gap (most favorable)

  for quarter_idx in _MATURE_QUARTER_RANGE:
    payroll_q = _payroll_at_quarter(
      payroll_headcount=payroll_headcount,
      quarter_index=quarter_idx,
      fallback_annual_payroll=fallback_payroll,
    )
    if payroll_q is None:
      # No cost data for this quarter — can't evaluate.
      continue
    quarter_cost = float(payroll_q) + quarter_lease + quarter_interest
    quarter_gap = quarter_cost - quarter_revenue_ceiling
    quarter_record = {
      "quarter_index": quarter_idx,
      "quarter_revenue_ceiling": round(quarter_revenue_ceiling, 2),
      "quarter_payroll": round(payroll_q, 2),
      "quarter_lease": round(quarter_lease, 2),
      "quarter_interest": round(quarter_interest, 2),
      "quarter_fixed_cost": round(quarter_cost, 2),
      "quarter_gap": round(quarter_gap, 2),
      "feasible": quarter_gap <= 0,
    }
    per_quarter_evaluation.append(quarter_record)
    if quarter_gap <= 0:
      any_feasible_quarter = True
    if best_quarter is None or quarter_gap < best_quarter["quarter_gap"]:
      best_quarter = quarter_record

  inputs_used["mature_quarter_evaluation"] = per_quarter_evaluation

  if not per_quarter_evaluation:
    # No mature-quarter cost data available — fall back to year-1 totals
    # so the check still runs (with the old shape). Treats absence of
    # schedule as "insufficient inputs" rather than a free pass.
    annualized_payroll = (
      fallback_payroll
      if fallback_payroll and fallback_payroll > 0
      else None
    )
    components_total: List[float] = []
    if annualized_payroll:
      components_total.append(annualized_payroll)
    if lease_annual:
      components_total.append(lease_annual)
    if interest_annual:
      components_total.append(interest_annual)
    if not components_total:
      return StructuralFeasibilityResult(
        feasible=True,
        upper_bound_annual_revenue=float(upper_revenue),
        lower_bound_annual_fixed_cost=None,
        feasibility_gap=None,
        diagnostic_message=(
          "insufficient_inputs: no payroll headcount schedule and no "
          "annual payroll fallback. Cannot evaluate feasibility; skipping."
        ),
        inputs_used=inputs_used,
      )
    annual_cost = sum(components_total)
    gap = float(annual_cost) - float(upper_revenue)
    if gap <= 0:
      return StructuralFeasibilityResult(
        feasible=True,
        upper_bound_annual_revenue=float(upper_revenue),
        lower_bound_annual_fixed_cost=float(annual_cost),
        feasibility_gap=round(gap, 2),
        diagnostic_message="structural_feasibility_satisfied",
        inputs_used=inputs_used,
      )
    recommendations = _build_recommended_adjustments(
      upper_bound_revenue=float(upper_revenue),
      lower_bound_cost=float(annual_cost),
      ops_json=ops,
      payroll_headcount=payroll_headcount,
    )
    return StructuralFeasibilityResult(
      feasible=False,
      upper_bound_annual_revenue=float(upper_revenue),
      lower_bound_annual_fixed_cost=float(annual_cost),
      feasibility_gap=round(gap, 2),
      diagnostic_message=(
        f"structurally_infeasible: at upper-bound revenue "
        f"${float(upper_revenue):,.0f}/yr and annual fixed cost "
        f"${float(annual_cost):,.0f}/yr, the business cannot cover its "
        f"fixed costs (gap=${gap:,.0f}). No payroll headcount schedule "
        "available to evaluate per-mature-quarter; consultant review of "
        "the intake assumptions is required."
      ),
      recommended_adjustments=recommendations,
      inputs_used=inputs_used,
    )

  if any_feasible_quarter:
    feasible_quarters = [r["quarter_index"] for r in per_quarter_evaluation if r["feasible"]]
    return StructuralFeasibilityResult(
      feasible=True,
      upper_bound_annual_revenue=float(upper_revenue),
      lower_bound_annual_fixed_cost=(
        round(best_quarter["quarter_fixed_cost"] * 4.0, 2)
        if best_quarter else None
      ),
      feasibility_gap=round(best_quarter["quarter_gap"], 2) if best_quarter else None,
      diagnostic_message=(
        f"structural_feasibility_satisfied: at least one mature quarter "
        f"clears the capacity-driven revenue ceiling. Feasible quarters "
        f"(of Q{_MATURE_QUARTER_RANGE.start}-Q{_MATURE_QUARTER_RANGE.stop - 1}): "
        f"{feasible_quarters}."
      ),
      inputs_used=inputs_used,
    )

  # All mature quarters fail. Report against the most-favorable quarter
  # (smallest gap) so recommended_adjustments give the closest path to
  # feasibility.
  closest_gap_annualized = float(best_quarter["quarter_gap"]) * 4.0
  closest_cost_annualized = float(best_quarter["quarter_fixed_cost"]) * 4.0
  recommendations = _build_recommended_adjustments(
    upper_bound_revenue=float(upper_revenue),
    lower_bound_cost=closest_cost_annualized,
    ops_json=ops,
    payroll_headcount=payroll_headcount,
  )
  return StructuralFeasibilityResult(
    feasible=False,
    upper_bound_annual_revenue=float(upper_revenue),
    lower_bound_annual_fixed_cost=round(closest_cost_annualized, 2),
    feasibility_gap=round(closest_gap_annualized, 2),
    diagnostic_message=(
      f"structurally_infeasible: at full capacity, revenue ceiling is "
      f"${float(upper_revenue):,.0f}/yr (capacity * price * "
      f"{_UPPER_BOUND_UTILIZATION:.2f} utilization). At the most-"
      f"favorable mature quarter (Q{best_quarter['quarter_index']}), "
      f"annualized fixed cost is ${closest_cost_annualized:,.0f}/yr "
      f"(payroll-dominant). Gap=${closest_gap_annualized:,.0f}/yr. The "
      "business cannot reach feasibility at the modeled capacity vs "
      "the modeled fixed-cost structure; recommended adjustments: "
      "reduce headcount to staff appropriate for capacity, raise unit "
      "price, or expand capacity."
    ),
    recommended_adjustments=recommendations,
    inputs_used=inputs_used,
  )
