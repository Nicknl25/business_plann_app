"""PASS-2 SPEC 1 - labor-heavy COGS basis reconciliation (Option B,
resolution-time; Nick-approved 2026-08-08).

THE MECHANISM (CW-018 trace, janitorial): cohort COGS for labor-heavy
industries is labor-INCLUSIVE - public-company CostOfRevenue includes
service labor (NAICS 561720: 87.2% via public quarterly medians,
corroborated 87.7% via SEC EDGAR; gross margin 12.8% agrees) - while
intake captures labor-EXCLUSIVE books (supplies-only COGS + payroll as
its own line). The cohort's own rows prove the overlap: cogs% +
payroll% sums >100% at the same NAICS level, which is arithmetically
impossible unless the same labor sits inside both. Every raw-band
consumer therefore double-counts labor for cleaning, security,
staffing, home care, landscaping, and kin.

THE DOCTRINE (Nick, stated as ruling): keep the source truth raw and
apply judgment in code where it is visible and reversible - never
mutate the measurements table. This module is that code seam: the two
resolution paths every consumer flows through call it; raw SOI/EDGAR/
metrics rows stay untouched; every adjustment carries provenance.

THE GUARDRAIL (the one thing that must hold, per the ruling): no
cohort payroll coverage at any NAICS level -> NO conversion - the band
demotes to context, NEVER a guessed subtraction. A guessed subtraction
would manufacture a materials band from nothing, which is worse than
the double-count it replaces.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


_MATERIALS_FLOOR = 0.01  # a converted band edge never reaches zero


def _f(value: Any) -> Optional[float]:
  try:
    number = float(value)
  except (TypeError, ValueError):
    return None
  if number != number:
    return None
  return number


def cohort_payroll_share(naics_6: str) -> Optional[float]:
  """The cohort's payroll % of revenue at the closest covered NAICS
  level (CBP/SOI-derived; 298 six-digit rows with a level cascade
  behind them). None when no coverage exists anywhere - the caller's
  guardrail then forbids conversion."""
  try:
    from client_intake_and_finmo.post_intake_industry_baseline.lookup import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
    row = post_intake_industry_baseline_for_naics(
      metric_key="payroll_percent_of_revenue",
      naics_6=str(naics_6 or "").strip(),
    )
  except Exception:
    return None
  # THE GUARDRAIL: a level-0 cross-industry generic default is NOT this
  # cohort's payroll - subtracting it would be a guessed subtraction.
  # Only a real industry-level row (NAICS level >= 2) counts as coverage.
  try:
    level = int((row or {}).get("naics_level_used") or 0)
  except (TypeError, ValueError):
    level = 0
  if level < 2 or str((row or {}).get("trust_flag") or "") == "generic_default":
    return None
  share = _f((row or {}).get("benchmark_target"))
  if share is None or share <= 0 or share >= 1.0:
    return None
  return share


def maybe_labor_adjust_cogs_band(
  *,
  naics_6: str,
  band_min: Optional[float],
  band_target: Optional[float],
  band_max: Optional[float],
  labor_heavy_business: bool,
) -> Optional[Dict[str, Any]]:
  """Returns the labor-adjusted band {min, target, max, provenance} or
  None when no adjustment applies.

  Double-keyed detection (both required):
    DATA signal  - cohort cogs_target + cohort payroll_target > 1.0 at
                   the resolved level: arithmetic proof the bases
                   overlap (cannot false-fire on a genuinely
                   materials-heavy cohort - retail/manufacturing sums
                   sit well under 1).
    BUSINESS signal - the caller confirms this business's books are
                   labor-exclusive (capacity_driver == "labor" or the
                   margin-band measured basis).

  Conversion shifts ALL band edges by the cohort payroll share
  (preserving the P25-P75 spread shape), floored at the materials
  floor. Ordering min <= target <= max is preserved by construction.
  """
  if not labor_heavy_business:
    return None
  target = _f(band_target)
  if target is None or target <= 0:
    return None
  payroll = cohort_payroll_share(naics_6)
  if payroll is None:
    # THE GUARDRAIL + the edge RULING (Nick, 2026-08-08): a labor-heavy
    # business whose cohort payroll cannot be resolved gets NO
    # conversion - and the unverifiable labor-inclusive band DEMOTES TO
    # CONTEXT rather than keeping steering authority.
    return {
      "action": "demote",
      "provenance": {"basis": "labor_basis_unverifiable", "reason": "no_payroll_coverage"},
    }
  if target + payroll <= 1.0:
    return None  # bases provably compatible - the band keeps authority.
  lo = _f(band_min)
  hi = _f(band_max)
  adj_max = max(_MATERIALS_FLOOR, ((hi if hi is not None else target) - payroll))
  if adj_max < 0.02:
    # THE EDGE RULING: overlap is PROVEN (>100% sum) but the subtraction
    # collapses the whole band - we KNOW the band double-counts labor
    # and cannot cleanly fix it. A provably-wrong informant does not
    # keep authority: DEMOTE TO CONTEXT, same as no-coverage. Never a
    # manufactured band; the operator's own anchor governs downstream.
    return {
      "action": "demote",
      "provenance": {
        "basis": "labor_basis_overlap_unresolvable",
        "cohort_cogs_target": round(target, 6),
        "cohort_payroll_share": round(payroll, 6),
        "overlap_sum": round(target + payroll, 6),
      },
    }
  adj_target = min(max(_MATERIALS_FLOOR, target - payroll), adj_max)
  adj_min = min(
    max(_MATERIALS_FLOOR, (lo - payroll) if lo is not None else adj_target),
    adj_target,
  )
  return {
    "action": "convert",
    "min": round(adj_min, 6),
    "target": round(adj_target, 6),
    "max": round(adj_max, 6),
    "provenance": {
      "basis": "labor_adjusted",
      "cohort_cogs_target": round(target, 6),
      "cohort_payroll_share": round(payroll, 6),
      "overlap_sum": round(target + payroll, 6),
    },
  }
