"""Module 3 Task 3.8 — schedule-level sanity cross-checks.

Per master-diagnostic Part 6.2: in addition to the line-by-line realism
gate, the finalize stage runs four schedule-level sanity checks against
NAICS bands. These do NOT rewrite drivers or statements — they surface
the upstream input that's wrong (wage_positioning_tier mismatch, debt
rate sourced from the wrong cascade, capex out of line with PPE buildup).

Returns the same `RealismCheckResult` shape used by the line-level gate so
the workbook can render warnings uniformly. Hard-fail behavior is the same
contract: one violation raises immediately.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .validator import (
  RealismBandViolation,
  RealismCheckResult,
  _safe_float,
)


# Default tolerances per master-diagnostic Phase 4 + tightened in v3.
# Schedule-level metrics share the same tier conventions as the line gate.
_RATIO_TOL_HIGH = 700
_RATIO_TOL_MEDIUM = 1200
_RATIO_TOL_LOW = 2000

_PER_FTE_TOL_HIGH = 2500    # 25% of target $/FTE
_PER_FTE_TOL_MEDIUM = 4000  # 40%
_PER_FTE_TOL_LOW = 6000     # 60%


def _resolve_band(metric_key: str, naics_6: Optional[str]) -> Optional[Dict[str, Any]]:
  if not naics_6:
    return None
  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    band = post_intake_industry_baseline_for_naics(metric_key=metric_key, naics_6=naics_6)
  except Exception:
    return None
  if not isinstance(band, dict) or band.get("trust_flag") == "no_coverage":
    return None
  return band


def _tier_tolerance(
  band: Dict[str, Any],
  *,
  high: int,
  medium: int,
  low: int,
  generic: Optional[int] = None,
) -> Optional[int]:
  tier = str((band or {}).get("confidence_tier") or "").strip().lower()
  if tier == "high":
    return high
  if tier == "medium":
    return medium
  if tier == "low":
    return low
  if tier == "generic_default":
    return generic
  return None


def _result(
  *,
  metric_key: str,
  finmo_line_label: str,
  derivation_formula_key: str,
  quarter_aggregation: str,
  quarter_index: Optional[int],
  actual: Optional[float],
  band: Optional[Dict[str, Any]],
  effective_min: Optional[float],
  effective_max: Optional[float],
  tolerance_bps: Optional[int],
  status: str,
  reason: str,
  governs_lever_id: Optional[str] = None,
  is_ratio: bool = True,
) -> RealismCheckResult:
  return RealismCheckResult(
    metric_key=metric_key,
    finmo_line_label=finmo_line_label,
    derivation_formula_key=derivation_formula_key,
    quarter_aggregation=quarter_aggregation,
    quarter_index=quarter_index,
    actual_value=actual,
    band_min=_safe_float((band or {}).get("benchmark_min")),
    band_max=_safe_float((band or {}).get("benchmark_max")),
    band_target=_safe_float((band or {}).get("benchmark_target")),
    band_naics_code=(band or {}).get("naics_code_used"),
    band_naics_level=(band or {}).get("naics_level_used"),
    band_confidence_tier=(band or {}).get("confidence_tier"),
    band_data_source=(band or {}).get("data_source"),
    band_trust_flag=(band or {}).get("trust_flag"),
    tolerance_applied_bps=tolerance_bps,
    effective_min=effective_min,
    effective_max=effective_max,
    status=status,
    reason=reason,
    governs_lever_id=governs_lever_id,
  )


def _band_with_tolerance(
  band: Optional[Dict[str, Any]],
  *,
  tolerance_bps: Optional[int],
  ratio_metric: bool,
) -> Optional[Dict[str, float]]:
  if band is None or tolerance_bps is None:
    return None
  bench_min = _safe_float(band.get("benchmark_min"))
  bench_target = _safe_float(band.get("benchmark_target"))
  bench_max = _safe_float(band.get("benchmark_max"))
  raw_min = bench_min if bench_min is not None else bench_target
  raw_max = bench_max if bench_max is not None else bench_target
  if raw_min is None or raw_max is None:
    return None
  if ratio_metric:
    tol_units = float(tolerance_bps) / 10000.0
  else:
    ref = float(bench_target) if bench_target is not None else (
      (float(raw_min) + float(raw_max)) / 2.0
    )
    tol_units = abs(ref) * float(tolerance_bps) / 10000.0
  return {"min": float(raw_min) - tol_units, "max": float(raw_max) + tol_units}


# ---------------------------------------------------------------------------
# Wage realism — produced average wage per supporting-staff FTE vs NAICS
# avg_wage_per_fte band.
# ---------------------------------------------------------------------------


def _check_wage_realism(
  *,
  payroll_headcount: Dict[str, Any],
  business_naics_6: Optional[str],
) -> Optional[RealismCheckResult]:
  rows = (payroll_headcount or {}).get("payroll_headcount_grid") or []
  if not isinstance(rows, list) or not rows:
    return None
  total_wages = 0.0
  total_fte = 0.0
  for r in rows:
    if not isinstance(r, dict):
      continue
    if str(r.get("staffing_class") or "").strip().lower() == "key_person":
      continue
    annual_wage = _safe_float(r.get("annual_wage"))
    fte = _safe_float(r.get("ending_fte"))
    if fte is None or fte <= 0.0:
      fte = _safe_float(r.get("starting_fte"))
    if annual_wage is None or fte is None or fte <= 0.0:
      continue
    total_wages += float(annual_wage) * float(fte)
    total_fte += float(fte)
  if total_fte <= 0.0:
    return None
  produced_wage_per_fte = total_wages / total_fte
  band = _resolve_band("avg_wage_per_fte", business_naics_6)
  if band is None:
    return _result(
      metric_key="avg_wage_per_fte",
      finmo_line_label="Wage Realism",
      derivation_formula_key="payroll_headcount_avg_wage_per_supporting_fte",
      quarter_aggregation="horizon_average",
      quarter_index=None,
      actual=produced_wage_per_fte,
      band=None,
      effective_min=None,
      effective_max=None,
      tolerance_bps=None,
      status="skipped",
      reason="no_naics_coverage_for_avg_wage_per_fte",
      governs_lever_id="payroll_headcount_schedule.wage_positioning_tier",
      is_ratio=False,
    )
  tolerance_bps = _tier_tolerance(
    band, high=_PER_FTE_TOL_HIGH, medium=_PER_FTE_TOL_MEDIUM, low=_PER_FTE_TOL_LOW, generic=None
  )
  if tolerance_bps is None:
    return _result(
      metric_key="avg_wage_per_fte",
      finmo_line_label="Wage Realism",
      derivation_formula_key="payroll_headcount_avg_wage_per_supporting_fte",
      quarter_aggregation="horizon_average",
      quarter_index=None,
      actual=produced_wage_per_fte,
      band=band,
      effective_min=None,
      effective_max=None,
      tolerance_bps=None,
      status="skipped",
      reason=f"no_tolerance_for_confidence_tier_{band.get('confidence_tier')}",
      governs_lever_id="payroll_headcount_schedule.wage_positioning_tier",
      is_ratio=False,
    )
  bounds = _band_with_tolerance(band, tolerance_bps=tolerance_bps, ratio_metric=False)
  in_band = bool(bounds and bounds["min"] <= produced_wage_per_fte <= bounds["max"])
  status = "in_band" if in_band else "out_of_band_warn"
  reason = "" if in_band else (
    f"actual_wage_per_fte=${produced_wage_per_fte:,.0f} band=[${bounds['min']:,.0f}..${bounds['max']:,.0f}] "
    f"naics_level_used={band.get('naics_level_used')} confidence_tier={band.get('confidence_tier')} "
    f"check=wage_positioning_tier_implausible"
  )
  return _result(
    metric_key="avg_wage_per_fte",
    finmo_line_label="Wage Realism",
    derivation_formula_key="payroll_headcount_avg_wage_per_supporting_fte",
    quarter_aggregation="horizon_average",
    quarter_index=None,
    actual=produced_wage_per_fte,
    band=band,
    effective_min=bounds["min"] if bounds else None,
    effective_max=bounds["max"] if bounds else None,
    tolerance_bps=tolerance_bps,
    status=status,
    reason=reason,
    governs_lever_id="payroll_headcount_schedule.wage_positioning_tier",
    is_ratio=False,
  )


# ---------------------------------------------------------------------------
# Productivity realism — produced revenue per total FTE vs NAICS revenue_per_fte.
# ---------------------------------------------------------------------------


def _check_productivity_realism(
  *,
  payroll_headcount: Dict[str, Any],
  finmo_json: Dict[str, Any],
  business_naics_6: Optional[str],
) -> Optional[RealismCheckResult]:
  rows = (payroll_headcount or {}).get("payroll_headcount_grid") or []
  if not isinstance(rows, list) or not rows:
    return None
  fte_by_quarter: Dict[int, float] = {}
  for r in rows:
    if not isinstance(r, dict):
      continue
    q = int(_safe_float(r.get("quarter_index")) or 0)
    if q < 1:
      continue
    fte = _safe_float(r.get("ending_fte"))
    if fte is None:
      fte = _safe_float(r.get("starting_fte"))
    if fte is None:
      continue
    fte_by_quarter[q] = fte_by_quarter.get(q, 0.0) + float(fte)
  if not fte_by_quarter:
    return None
  total_revenue = 0.0
  fte_sum = 0.0
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    q = int(_safe_float(row.get("quarter_index")) or 0)
    if q < 1:
      continue
    rev = _safe_float(row.get("revenue"))
    fte = fte_by_quarter.get(q)
    if rev is None or fte is None or fte <= 0.0:
      continue
    total_revenue += float(rev) * 4.0  # quarterly -> annualized weight
    fte_sum += float(fte)
  if fte_sum <= 0.0:
    return None
  # Average revenue/FTE across the horizon — annualized basis.
  produced_revenue_per_fte = total_revenue / fte_sum
  band = _resolve_band("revenue_per_fte", business_naics_6)
  if band is None:
    return _result(
      metric_key="revenue_per_fte",
      finmo_line_label="Productivity Realism",
      derivation_formula_key="finmo_revenue_div_total_fte_horizon_average",
      quarter_aggregation="horizon_average",
      quarter_index=None,
      actual=produced_revenue_per_fte,
      band=None,
      effective_min=None,
      effective_max=None,
      tolerance_bps=None,
      status="skipped",
      reason="no_naics_coverage_for_revenue_per_fte",
      governs_lever_id="payroll_headcount_schedule.capacity_units_per_supporting_fte",
      is_ratio=False,
    )
  tolerance_bps = _tier_tolerance(
    band, high=_PER_FTE_TOL_HIGH, medium=_PER_FTE_TOL_MEDIUM, low=_PER_FTE_TOL_LOW, generic=None
  )
  if tolerance_bps is None:
    return _result(
      metric_key="revenue_per_fte",
      finmo_line_label="Productivity Realism",
      derivation_formula_key="finmo_revenue_div_total_fte_horizon_average",
      quarter_aggregation="horizon_average",
      quarter_index=None,
      actual=produced_revenue_per_fte,
      band=band,
      effective_min=None,
      effective_max=None,
      tolerance_bps=None,
      status="skipped",
      reason=f"no_tolerance_for_confidence_tier_{band.get('confidence_tier')}",
      governs_lever_id="payroll_headcount_schedule.capacity_units_per_supporting_fte",
      is_ratio=False,
    )
  bounds = _band_with_tolerance(band, tolerance_bps=tolerance_bps, ratio_metric=False)
  in_band = bool(bounds and bounds["min"] <= produced_revenue_per_fte <= bounds["max"])
  status = "in_band" if in_band else "out_of_band_warn"
  reason = "" if in_band else (
    f"actual_revenue_per_fte=${produced_revenue_per_fte:,.0f} band=[${bounds['min']:,.0f}..${bounds['max']:,.0f}] "
    f"naics_level_used={band.get('naics_level_used')} confidence_tier={band.get('confidence_tier')} "
    f"check=capacity_units_per_supporting_fte_implausible_or_revenue_overstated"
  )
  return _result(
    metric_key="revenue_per_fte",
    finmo_line_label="Productivity Realism",
    derivation_formula_key="finmo_revenue_div_total_fte_horizon_average",
    quarter_aggregation="horizon_average",
    quarter_index=None,
    actual=produced_revenue_per_fte,
    band=band,
    effective_min=bounds["min"] if bounds else None,
    effective_max=bounds["max"] if bounds else None,
    tolerance_bps=tolerance_bps,
    status=status,
    reason=reason,
    governs_lever_id="payroll_headcount_schedule.capacity_units_per_supporting_fte",
    is_ratio=False,
  )


# ---------------------------------------------------------------------------
# Debt rate realism — produced quarterly interest rate vs NAICS sba_initial_interest_rate.
# Per master-diagnostic 12.6: cross-check with intake-anchored implied rate
# (annual_interest_payment / total_debt_outstanding) when intake gave both.
# ---------------------------------------------------------------------------


def _check_debt_rate_realism(
  *,
  finmo_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  business_naics_6: Optional[str],
) -> Optional[RealismCheckResult]:
  produced_rate: Optional[float] = None
  for row in (finmo_json or {}).get("quarter_rows") or []:
    if not isinstance(row, dict):
      continue
    q = int(_safe_float(row.get("quarter_index")) or 0)
    if q != 1:
      continue
    debt_open = _safe_float(row.get("debt_opening_balance"))
    if debt_open is None or abs(debt_open) <= 1e-6:
      continue
    rate = _safe_float(row.get("debt_interest_rate"))
    if rate is None:
      interest = _safe_float(row.get("debt_interest_expense")) or 0.0
      debt_close = _safe_float(row.get("debt_closing_balance")) or 0.0
      avg_debt = (float(debt_open) + float(debt_close)) / 2.0
      if avg_debt > 1e-6:
        rate = float(interest) / avg_debt
    if rate is None:
      continue
    # quarterly -> annualized
    produced_rate = float(rate) * 4.0
    break
  if produced_rate is None:
    return None
  band = _resolve_band("sba_initial_interest_rate", business_naics_6)
  if band is None:
    return _result(
      metric_key="sba_initial_interest_rate",
      finmo_line_label="Debt Rate Realism",
      derivation_formula_key="finmo_q1_debt_interest_annualized",
      quarter_aggregation="per_quarter",
      quarter_index=1,
      actual=produced_rate,
      band=None,
      effective_min=None,
      effective_max=None,
      tolerance_bps=None,
      status="skipped",
      reason="no_naics_coverage_for_sba_initial_interest_rate",
      governs_lever_id="expenses::Interest Rate",
      is_ratio=True,
    )
  tolerance_bps = _tier_tolerance(
    band, high=_RATIO_TOL_HIGH, medium=_RATIO_TOL_MEDIUM, low=_RATIO_TOL_LOW, generic=None
  )
  bounds = _band_with_tolerance(band, tolerance_bps=tolerance_bps, ratio_metric=True)
  if bounds is None or tolerance_bps is None:
    return _result(
      metric_key="sba_initial_interest_rate",
      finmo_line_label="Debt Rate Realism",
      derivation_formula_key="finmo_q1_debt_interest_annualized",
      quarter_aggregation="per_quarter",
      quarter_index=1,
      actual=produced_rate,
      band=band,
      effective_min=None,
      effective_max=None,
      tolerance_bps=tolerance_bps,
      status="skipped",
      reason="band_or_tolerance_unavailable",
      governs_lever_id="expenses::Interest Rate",
      is_ratio=True,
    )
  in_band = bounds["min"] <= produced_rate <= bounds["max"]
  status = "in_band" if in_band else "out_of_band_warn"
  reason = ""
  if not in_band:
    intake_implied = None
    annual_interest = _safe_float((financials_json or {}).get("annual_interest_payment"))
    total_debt = _safe_float((financials_json or {}).get("total_debt_outstanding"))
    if annual_interest is not None and total_debt is not None and total_debt > 1e-6:
      intake_implied = float(annual_interest) / float(total_debt)
    reason = (
      f"actual_interest_rate={produced_rate:.4f} band=[{bounds['min']:.4f}..{bounds['max']:.4f}] "
      f"naics_level_used={band.get('naics_level_used')} confidence_tier={band.get('confidence_tier')}"
    )
    if intake_implied is not None:
      reason += f" intake_implied_rate={intake_implied:.4f}"
    reason += " check=interest_rate_source_priority_or_schedule_mismatch"
  return _result(
    metric_key="sba_initial_interest_rate",
    finmo_line_label="Debt Rate Realism",
    derivation_formula_key="finmo_q1_debt_interest_annualized",
    quarter_aggregation="per_quarter",
    quarter_index=1,
    actual=produced_rate,
    band=band,
    effective_min=bounds["min"],
    effective_max=bounds["max"],
    tolerance_bps=tolerance_bps,
    status=status,
    reason=reason,
    governs_lever_id="expenses::Interest Rate",
    is_ratio=True,
  )


# ---------------------------------------------------------------------------
# Capex / PPE / depreciation realism — already covered by the line-level
# gate (capex%, ppe%, depreciation%); the schedule check adds a cross-
# consistency rule: PPE buildup should be consistent with the capex
# minus depreciation flow over year 1.
# ---------------------------------------------------------------------------


def _check_capex_ppe_consistency(
  *,
  finmo_json: Dict[str, Any],
  business_naics_6: Optional[str],
) -> Optional[RealismCheckResult]:
  """Walk Q2..Q4 and confirm PPE_q - PPE_(q-1) = capex_q - depreciation_q.

  Any quarter where the chain breaks signals a mapping-table / FINMO calc
  inconsistency — either capex is not flowing into PPE, or depreciation
  isn't being subtracted, or a writeoff was applied without being recorded
  on the schedule. Q1 is excluded because its capex/depreciation are
  baked into the FINMO-reported `ppe` end-of-Q1 balance and we have no
  forecast-only opening balance to compare against.
  """
  rows = (finmo_json or {}).get("quarter_rows") or []
  if not rows:
    return None
  by_q: Dict[int, Dict[str, Any]] = {}
  for r in rows:
    if isinstance(r, dict):
      qi = int(_safe_float(r.get("quarter_index")) or 0)
      if qi >= 1:
        by_q[qi] = r
  drift_total = 0.0
  capex_total = 0.0
  found_any = False
  worst_drift = 0.0
  worst_q = 0
  worst_observed = 0.0
  worst_expected = 0.0
  for q in range(2, 5):
    prev = by_q.get(q - 1)
    cur = by_q.get(q)
    if prev is None or cur is None:
      continue
    ppe_prev = _safe_float(prev.get("ppe"))
    ppe_cur = _safe_float(cur.get("ppe"))
    if ppe_prev is None or ppe_cur is None:
      continue
    capex = _safe_float(cur.get("capital_expenditures")) or 0.0
    depreciation = _safe_float(cur.get("depreciation")) or 0.0
    expected = float(capex) - float(depreciation)
    observed = float(ppe_cur) - float(ppe_prev)
    drift = abs(observed - expected)
    capex_total += abs(float(capex))
    drift_total += drift
    found_any = True
    if drift > worst_drift:
      worst_drift = drift
      worst_q = q
      worst_observed = observed
      worst_expected = expected
  if not found_any:
    return None
  abs_capex = abs(capex_total) if abs(capex_total) > 1.0 else 1.0
  drift_ratio = drift_total / abs_capex
  status = "in_band" if drift_ratio <= 0.05 else "out_of_band_warn"
  reason = "" if drift_ratio <= 0.05 else (
    f"max_drift_quarter=Q{worst_q} ppe_change={worst_observed:,.2f} "
    f"expected_from_capex_minus_depreciation={worst_expected:,.2f} "
    f"total_drift_ratio={drift_ratio:.4f} "
    f"check=capex_ppe_depreciation_chain_inconsistent"
  )
  return _result(
    metric_key="capex_ppe_depreciation_chain",
    finmo_line_label="Capex / PPE / Depreciation Chain",
    derivation_formula_key="ppe_change_minus_capex_minus_depreciation_q2_to_q4",
    quarter_aggregation="year_one_aggregate",
    quarter_index=None,
    actual=drift_ratio,
    band=None,
    effective_min=0.0,
    effective_max=0.05,
    tolerance_bps=500,
    status=status,
    reason=reason,
    governs_lever_id="schedules::Capital Expenditures",
    is_ratio=True,
  )


# ---------------------------------------------------------------------------
# Public entry.
# ---------------------------------------------------------------------------


def validate_schedule_sanity(
  *,
  model_input_json: Dict[str, Any],
  finmo_json: Dict[str, Any],
  business_naics_6: Optional[str],
  payroll_headcount: Optional[Dict[str, Any]] = None,
  financials_json: Optional[Dict[str, Any]] = None,
  raise_on_hard_fail: bool = False,
) -> Dict[str, Any]:
  """Run the four schedule-level sanity checks and return their results.

  All schedule checks are warn-only by default in v3 (no hard_fail). The
  payload is shaped identically to `validate_industry_realism_bands` so
  finalize can append both into the same `realism_gate.warnings` list.
  """
  payroll = payroll_headcount if isinstance(payroll_headcount, dict) else {}
  financials = financials_json if isinstance(financials_json, dict) else {}

  results: List[RealismCheckResult] = []
  for fn, args in (
    (_check_wage_realism, dict(payroll_headcount=payroll, business_naics_6=business_naics_6)),
    (_check_productivity_realism, dict(payroll_headcount=payroll, finmo_json=finmo_json, business_naics_6=business_naics_6)),
    (_check_debt_rate_realism, dict(finmo_json=finmo_json, financials_json=financials, business_naics_6=business_naics_6)),
    (_check_capex_ppe_consistency, dict(finmo_json=finmo_json, business_naics_6=business_naics_6)),
  ):
    try:
      out = fn(**args)
    except Exception as exc:
      out = _result(
        metric_key=fn.__name__,
        finmo_line_label="Schedule Sanity",
        derivation_formula_key="schedule_sanity_check",
        quarter_aggregation="horizon_average",
        quarter_index=None,
        actual=None,
        band=None,
        effective_min=None,
        effective_max=None,
        tolerance_bps=None,
        status="skipped",
        reason=f"check_error:{type(exc).__name__}:{exc}",
      )
    if out is not None:
      results.append(out)
      if raise_on_hard_fail and out.status == "out_of_band_hard_fail":
        raise RealismBandViolation(
          f"post_intake_finalize_schedule_sanity_violation: {out.metric_key}: {out.reason}",
          results=results,
        )

  warnings_list = [r.to_dict() for r in results if r.status.startswith("out_of_band")]
  return {
    "results": [r.to_dict() for r in results],
    "warnings": warnings_list,
    "warning_count": len(warnings_list),
    "checked_metric_count": len({r.metric_key for r in results}),
    "result_count": len(results),
  }
