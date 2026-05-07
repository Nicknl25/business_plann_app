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
from typing import Any, Dict, List, Optional


# Plausible-maximum utilization for the upper-bound revenue estimate.
# 0.95 because hitting 100% sustained is not realistic; 0.80 would be
# too conservative and reject borderline-feasible businesses.
_UPPER_BOUND_UTILIZATION = 0.95

# Fixed-cost ratio applied to operating expenses for businesses that
# don't itemize lease / payroll separately. Conservative — keeps the
# check from over-rejecting.
_FIXED_COST_BUFFER_FRACTION = 0.05

# Quarters over which the feasibility window is evaluated. Year 1 is
# the steady-state envelope.
_FEASIBILITY_WINDOW_QUARTERS = 4


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


def _upper_bound_annual_revenue(
  *,
  ops_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  financials_json: Dict[str, Any],
) -> Optional[float]:
  """Best estimate of the maximum revenue this business can plausibly
  generate at the configured capacity and pricing.

  Priority order:
    1. financials_year1_json.company_revenue_total_year1 / revenue_total_year1
       (already scoped to the planning window — most authoritative).
    2. capacity * unit_price * operating_periods_per_year * upper-bound utilization.
    3. financials_json.current_revenue (snapshot).

  Returns None when none of these resolve — the structural check then
  declines to assert infeasibility (the assembler's NAICS / cohort
  resolver will produce a baseline anyway).
  """
  rev_year_one = (
    _safe_float(financials_year1_json.get("company_revenue_total_year1"))
    or _safe_float(financials_year1_json.get("revenue_total_year1"))
  )
  if rev_year_one is not None and rev_year_one > 0:
    return float(rev_year_one)

  capacity = (
    _safe_float(ops_json.get("units_per_period_capacity"))
    or _safe_float(ops_json.get("units_per_week_capacity"))
  )
  unit_price = _safe_float(ops_json.get("unit_price"))
  periods = _safe_float(ops_json.get("operating_periods_per_year")) or 12.0
  if capacity and unit_price and capacity > 0 and unit_price > 0:
    return float(capacity) * float(unit_price) * float(periods) * _UPPER_BOUND_UTILIZATION

  current_rev = _safe_float(financials_json.get("current_revenue"))
  if current_rev is not None and current_rev > 0:
    return float(current_rev)
  return None


def _lower_bound_annual_fixed_cost(
  *,
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  payroll_headcount: Optional[Dict[str, Any]],
) -> Optional[float]:
  """Lower-bound estimate of annual fixed costs the business must cover
  regardless of revenue. Includes:
    - payroll (from headcount schedule when available, else intake's
      annual payroll estimate)
    - lease/rent (intake)
    - debt service (annual interest from intake)

  Variable costs (COGS, marketing scaled to revenue) are NOT included
  here — they scale with revenue and the structural check is about
  fixed-cost coverage at upper-bound revenue.
  """
  components: List[float] = []

  payroll_year_one: Optional[float] = None
  if isinstance(payroll_headcount, dict):
    quarter_totals = payroll_headcount.get("quarter_totals")
    if isinstance(quarter_totals, list) and quarter_totals:
      year_one = [
        _safe_float(row.get("payroll"))
        for row in quarter_totals[: _FEASIBILITY_WINDOW_QUARTERS]
        if isinstance(row, dict)
      ]
      year_one = [v for v in year_one if v is not None]
      if year_one:
        payroll_year_one = float(sum(year_one))
  if payroll_year_one is None:
    payroll_year_one = (
      _safe_float(financials_year1_json.get("annual_payroll_total"))
      or _safe_float(financials_year1_json.get("payroll_year_one"))
      or _safe_float(financials_json.get("annual_payroll"))
    )
  if payroll_year_one is not None and payroll_year_one > 0:
    components.append(float(payroll_year_one))

  lease_annual = (
    _safe_float(financials_year1_json.get("lease_year_one"))
    or _safe_float(financials_year1_json.get("annual_lease_total"))
    or _safe_float(financials_json.get("annual_lease"))
    or _safe_float(financials_json.get("lease_amount_annual"))
  )
  if lease_annual is not None and lease_annual > 0:
    components.append(float(lease_annual))

  interest_annual = (
    _safe_float(financials_json.get("annual_interest_payment"))
    or _safe_float(financials_year1_json.get("interest_year_one"))
  )
  if interest_annual is not None and interest_annual > 0:
    components.append(float(interest_annual))

  if not components:
    return None
  return sum(components)


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
  """Pre-flight structural feasibility check.

  Returns a StructuralFeasibilityResult with feasible=False and concrete
  recommended_adjustments when revenue at maximum plausible utilization
  cannot cover the lower-bound fixed costs. Returns feasible=True
  (potentially with diagnostic_message="insufficient_inputs") when
  inputs aren't rich enough to assert infeasibility — the check is
  intentionally conservative; it only fires on clearly infeasible
  configurations.

  Args:
    ops_json: intake operating model — capacity, unit_price, periods/yr.
    financials_json: intake snapshot — current_revenue, annual_lease,
      annual_interest_payment.
    financials_year1_json: year-1 projections — revenue_total_year1,
      payroll_year_one, lease_year_one.
    payroll_headcount: payroll headcount schedule — preferred source for
      fixed payroll component.
    business_profile: forwarded for forward compatibility; not used yet.
  """
  ops = ops_json if isinstance(ops_json, dict) else {}
  fin = financials_json if isinstance(financials_json, dict) else {}
  fin_y1 = financials_year1_json if isinstance(financials_year1_json, dict) else {}
  _ = business_profile  # accepted for forward compatibility

  upper_revenue = _upper_bound_annual_revenue(
    ops_json=ops, financials_year1_json=fin_y1, financials_json=fin,
  )
  lower_cost = _lower_bound_annual_fixed_cost(
    financials_json=fin,
    financials_year1_json=fin_y1,
    payroll_headcount=payroll_headcount,
  )

  inputs_used: Dict[str, Any] = {
    "revenue_source": (
      "financials_year1_json.company_revenue_total_year1"
      if _safe_float(fin_y1.get("company_revenue_total_year1"))
      else (
        "ops_json.capacity_x_unit_price_x_utilization"
        if (_safe_float(ops.get("units_per_period_capacity"))
            and _safe_float(ops.get("unit_price")))
        else "financials_json.current_revenue"
      )
    ),
    "fixed_cost_components": [],
    "upper_bound_utilization": _UPPER_BOUND_UTILIZATION,
    "feasibility_window_quarters": _FEASIBILITY_WINDOW_QUARTERS,
  }
  if isinstance(payroll_headcount, dict) and payroll_headcount.get("quarter_totals"):
    inputs_used["fixed_cost_components"].append("payroll_headcount.quarter_totals")
  elif fin_y1.get("annual_payroll_total") or fin_y1.get("payroll_year_one"):
    inputs_used["fixed_cost_components"].append("financials_year1_json.payroll")
  if (
    fin_y1.get("lease_year_one")
    or fin_y1.get("annual_lease_total")
    or fin.get("annual_lease")
    or fin.get("lease_amount_annual")
  ):
    inputs_used["fixed_cost_components"].append("lease_annual")
  if fin.get("annual_interest_payment") or fin_y1.get("interest_year_one"):
    inputs_used["fixed_cost_components"].append("annual_interest_payment")

  if upper_revenue is None or lower_cost is None:
    return StructuralFeasibilityResult(
      feasible=True,
      upper_bound_annual_revenue=upper_revenue,
      lower_bound_annual_fixed_cost=lower_cost,
      feasibility_gap=None,
      diagnostic_message=(
        "insufficient_inputs: structural check requires both an upper-bound "
        "revenue estimate and at least one fixed-cost component (payroll / "
        "lease / interest) to assert infeasibility. Skipping check."
      ),
      inputs_used=inputs_used,
    )

  gap = float(lower_cost) - float(upper_revenue)
  if gap <= 0:
    return StructuralFeasibilityResult(
      feasible=True,
      upper_bound_annual_revenue=float(upper_revenue),
      lower_bound_annual_fixed_cost=float(lower_cost),
      feasibility_gap=round(gap, 2),
      diagnostic_message="structural_feasibility_satisfied",
      inputs_used=inputs_used,
    )

  recommendations = _build_recommended_adjustments(
    upper_bound_revenue=float(upper_revenue),
    lower_bound_cost=float(lower_cost),
    ops_json=ops,
    payroll_headcount=payroll_headcount,
  )

  return StructuralFeasibilityResult(
    feasible=False,
    upper_bound_annual_revenue=float(upper_revenue),
    lower_bound_annual_fixed_cost=float(lower_cost),
    feasibility_gap=round(gap, 2),
    diagnostic_message=(
      f"structurally_infeasible: at upper-bound revenue "
      f"${float(upper_revenue):,.0f}/yr and lower-bound fixed cost "
      f"${float(lower_cost):,.0f}/yr, the business as configured cannot "
      f"cover its fixed costs (gap=${gap:,.0f}). The system cannot "
      "produce a profitable plan from this configuration; consultant "
      "review of the intake assumptions is required."
    ),
    recommended_adjustments=recommendations,
    inputs_used=inputs_used,
  )
