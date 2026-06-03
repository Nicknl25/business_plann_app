"""Cohort band resolution for the graded constructs (Fix #1 spec §4/§5).

Resolves the per-metric cohort percentile bands the Tier-1 grade needs,
**via the existing resolver** `resolve_cohort_band`
(post_intake_solver/cohort_band_resolver.py) — EDGAR+Alpha toggle × NAICS
6→2 cascade × >=2-firm gate. NO confidence-weighting layer (§5.2): the
cascade is the coverage mechanism; thin NAICS-6 bands simply resolve to a
closer coarser band, accepted as-is for the grade. `naics_level_used` /
`firm_count` are recorded for provenance only.

The graded constructs decompose into single-column cohort metrics that the
resolver can answer directly; the Tier-1 grade (grade.py) scores each firm
construct against these bands and combines in PERCENTILE space (not by
adding bands). Mapping construct -> cohort reference column(s):

  C1 operating-cash proxy  -> ebitda_margin_q   (closest resolvable operating-
        profitability anchor; the firm's proxy adds the ΔNWC term, whose drag
        is separately benchmarked by C3 — there is no single-column peer
        operating-cash-margin in the cohort tables, so EBITDA margin is the
        documented level anchor, NOT a silent substitution).
  C2 Rule-of-40           -> revenue_growth_q + ebitda_margin_q (scored per
        component, percentiles averaged in grade.py).
  C3 WC intensity         -> current_assets_minus_cash_to_revenue (lower
        better) and current_liabilities_to_revenue (higher better => lower NWC).
  C4 slope / op-leverage  -> ebitda_margin_q as the CONVERGENCE target only;
        slopes have no point-in-time cohort analog, so C4 contributes via
        trajectory (grade.py), not a level percentile.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Direction: does a higher raw value mean healthier? Used for percentile
# orientation in grade.py so 100% always means "better".
HIGHER_BETTER = "higher_better"
LOWER_BETTER = "lower_better"

#: The cohort metric columns the graded constructs reference, with orientation.
VIABILITY_METRIC_DIRECTIONS: Dict[str, str] = {
  "ebitda_margin_q": HIGHER_BETTER,
  "revenue_growth_q": HIGHER_BETTER,
  "current_assets_minus_cash_to_revenue": LOWER_BETTER,
  # More operating-liability financing -> lower net working capital -> healthier
  # cash position, so for the NWC-intensity lens higher CL/revenue is "better".
  "current_liabilities_to_revenue": HIGHER_BETTER,
}

#: construct -> cohort reference column(s). See module docstring for rationale.
CONSTRUCT_COHORT_REFERENCES: Dict[str, Any] = {
  "operating_cash_proxy": ["ebitda_margin_q"],
  "rule_of_40": ["revenue_growth_q", "ebitda_margin_q"],
  "nwc_intensity": ["current_assets_minus_cash_to_revenue", "current_liabilities_to_revenue"],
  "ebitda_ramp": ["ebitda_margin_q"],  # convergence target only (trajectory construct)
}


def _band_to_dict(result: Any, column: str) -> Dict[str, Any]:
  """Normalize a CohortBandResult (or None) to a plain dict with an
  `available` flag. Never fakes a band — None resolution => available False."""
  if result is None:
    return {
      "metric_column": column,
      "available": False,
      "p25": None, "p50": None, "p75": None,
      "naics_level_used": None, "cohort_table": None, "firm_count": None,
      "direction": VIABILITY_METRIC_DIRECTIONS.get(column),
    }
  d = result.to_dict() if hasattr(result, "to_dict") else dict(result)
  return {
    "metric_column": d.get("metric_column") or column,
    "available": d.get("benchmark_target") is not None,
    "p25": d.get("benchmark_min"),
    "p50": d.get("benchmark_target"),
    "p75": d.get("benchmark_max"),
    "naics_level_used": d.get("naics_level_used"),
    "cohort_table": d.get("cohort_table"),
    "firm_count": d.get("firm_count"),
    "direction": VIABILITY_METRIC_DIRECTIONS.get(column),
  }


def resolve_viability_bands(business_profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
  """Resolve every cohort band the graded constructs need.

  business_profile: {naics_6, target_annual_revenue, stage (age-derived,
  Unit 2)} — passed straight to resolve_cohort_band, which applies its own
  NAICS cascade and >=2-firm gate. Returns {metric_column: band_dict}; a
  band that the resolver could not produce (even after cascade) is marked
  available=False rather than fabricated.
  """
  from client_intake_and_finmo.post_intake_solver.cohort_band_resolver import (  # type: ignore
    resolve_cohort_band,
  )
  bands: Dict[str, Dict[str, Any]] = {}
  for column in VIABILITY_METRIC_DIRECTIONS:
    try:
      result = resolve_cohort_band(
        metric_key=column,
        business_profile=business_profile,
        metric_column_override=column,
      )
    except Exception:
      result = None
    bands[column] = _band_to_dict(result, column)
  return bands
