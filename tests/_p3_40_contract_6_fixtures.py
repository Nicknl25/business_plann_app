"""Shared fixture builders for Contract 6
(IndustryBaselineResolvedContract) acceptance tests.

Module is leading-underscore-prefixed so the test runner does NOT
auto-discover it as a test module.

ZERO re-uses of Contracts 1-5 fixtures per F1 (Contract 6 has no
composition with prior contracts). All fixtures emit dicts
matching production verbatim (per F5-α: NO cohort_query on
Shape A; per F2: business_model always None; per F12
monotonicity: benchmark fields ordered min <= target <= max).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional


HERE = os.path.abspath(os.path.dirname(__file__))
PYTHON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, "python"))
if PYTHON_ROOT not in sys.path:
  sys.path.insert(0, PYTHON_ROOT)
if HERE not in sys.path:
  sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
# BusinessProfileInputContract
# ---------------------------------------------------------------------------

def valid_business_profile_dict(
  *,
  include_naics_6: bool = True,
  include_target_annual_revenue: bool = True,
  include_stage: bool = True,
) -> Dict[str, Any]:
  """4-field business_profile input dict per
  runner.py:573-579."""
  payload: Dict[str, Any] = {
    "business_model": None,  # F2: always-None placeholder
  }
  if include_naics_6:
    payload["naics_6"] = "722515"  # valid 6-digit per F11
  if include_target_annual_revenue:
    payload["target_annual_revenue"] = 1500000.0
  if include_stage:
    payload["stage"] = "growth"
  return payload


# ---------------------------------------------------------------------------
# Shape A -- CascadeResolverPayloadContract (13 fields per F5-α)
# ---------------------------------------------------------------------------

def valid_cascade_resolver_payload_dict(
  *,
  metric_key: str = "gross_margin_percent",
  level_used: int = 6,
  trust_flag: str = "naics_6_direct",
  confidence_tier: str = "high",
  raw_confidence_tier: Optional[str] = "high",
) -> Dict[str, Any]:
  """13-field cascade resolver payload per
  lookup.py:240-256. F5-α: NO cohort_query.

  Default profile matches the happy-path SQL-row emission at
  lookup.py:240-256 (raw_confidence_tier=\"high\"). Pass
  ``raw_confidence_tier=None`` to exercise the no-coverage /
  generic-default / cohort-alternating fallback paths
  (lookup.py:299/:319/:483) where the producer emits the field
  as None for any business hitting those paths.
  """
  return {
    "metric_key": metric_key,
    "benchmark_min": 0.20,
    "benchmark_target": 0.40,
    "benchmark_max": 0.55,
    "naics_code_used": "722515",
    "naics_level_used": level_used,
    "data_source": "industry_metrics_alpha",
    "source_year": 2024,
    "sample_size": 142,
    "confidence_tier": confidence_tier,
    "raw_confidence_tier": raw_confidence_tier,
    "trust_flag": trust_flag,
    "fallback_chain_attempted": ["naics_6"],
  }


# ---------------------------------------------------------------------------
# Shape B -- CohortSqlRowContract (20 fields incl. cohort_query + resolved_at)
# Cleanup Commit 1: cohort_query added per R10 closure (previously
# silently dropped at SQL INSERT).
# ---------------------------------------------------------------------------

def valid_cohort_sql_row_dict(
  *,
  section: str = "drivers",
  lever_id: str = "gross_margin_percent_lever",
  metric_key: str = "gross_margin_percent",
  benchmark_min: float = 0.20,
  benchmark_target: float = 0.40,
  benchmark_max: float = 0.55,
  draft_id: str = "draft_test_001",
  planning_run_id: str = "run_test_001",
) -> Dict[str, Any]:
  """20-field cohort SQL row per cohort_bands_table.py:32-58
  schema. F12 monotonicity satisfied by default.

  R10 closure: cohort_query populated with a representative
  dict matching CohortBandResult.cohort_query shape at
  cohort_band_resolver.py:656+."""
  return {
    "draft_id": draft_id,
    "planning_run_id": planning_run_id,
    "section": section,
    "lever_id": lever_id,
    "metric_key": metric_key,
    "metric_column": "gross_margin_percent_col",
    "benchmark_min": benchmark_min,
    "benchmark_target": benchmark_target,
    "benchmark_max": benchmark_max,
    "robust_min": benchmark_min,
    "robust_max": benchmark_max,
    "naics_level_used": 6,
    "naics_prefix_used": "722515",
    "cohort_size": 50,
    "firm_count": 12,
    "confidence_tier": "high",
    "cohort_table": "alpha",
    "data_source": "industry_metrics_alpha",
    "cohort_query": {
      "naics_prefix": "722515",
      "metric_column": "gross_margin_percent_col",
      "min_firms": 5,
    },
    "resolved_at": datetime(2026, 5, 26, 12, 0, 0),
  }


# ---------------------------------------------------------------------------
# Shape C -- GetBandsViewBandContract (14 fields per band)
# Cleanup Commit 1: naics_prefix_used + data_source added per R11
# closure (previously silently dropped at SQL -> in-memory translation).
# ---------------------------------------------------------------------------

def valid_get_bands_view_band_dict(
  *,
  metric_key: str = "gross_margin_percent",
  benchmark_min: float = 0.20,
  benchmark_target: float = 0.40,
  benchmark_max: float = 0.55,
) -> Dict[str, Any]:
  """14-field band dict per cohort_bands_table.py:347-386
  (production writer post-Cleanup-Commit-1). R11 closure:
  naics_prefix_used + data_source now flow through Shape B
  -> Shape C symmetrically (asymmetry previously documented
  via F7; now resolved)."""
  return {
    "metric_key": metric_key,
    "metric_column": "gross_margin_percent_col",
    "benchmark_min": benchmark_min,
    "benchmark_target": benchmark_target,
    "benchmark_max": benchmark_max,
    "robust_min": benchmark_min,
    "robust_max": benchmark_max,
    "confidence_tier": "high",
    "cohort_size": 50,
    "firm_count": 12,
    "naics_level_used": 6,
    "cohort_table": "alpha",
    # R11 closure (Cleanup Commit 1)
    "naics_prefix_used": "722515",
    "data_source": "industry_metrics_alpha",
  }


def valid_get_bands_view_dict(
  *,
  section: str = "drivers",
  lever_ids: Optional[List[str]] = None,
  draft_id: str = "draft_test_001",
  planning_run_id: str = "run_test_001",
) -> Dict[str, Any]:
  """Envelope + nested bands dict per cohort_bands_table.py:386-392."""
  if lever_ids is None:
    lever_ids = ["gross_margin_percent_lever", "marketing_percent_lever"]
  bands = {
    lever_id: valid_get_bands_view_band_dict(metric_key=f"{lever_id}_metric")
    for lever_id in lever_ids
  }
  return {
    "section": section,
    "draft_id": draft_id,
    "planning_run_id": planning_run_id,
    "count": len(bands),
    "bands": bands,
  }


# ---------------------------------------------------------------------------
# Shape D -- PopulationSummary{,Section}Contract
# ---------------------------------------------------------------------------

def valid_population_summary_section_dict(
  *,
  resolved: int = 5,
  skipped: int = 0,
) -> Dict[str, Any]:
  return {"resolved": resolved, "skipped": skipped}


def valid_population_summary_dict(
  *,
  include_drivers: bool = True,
  include_balance_sheet: bool = True,
  include_stage_ramp: bool = True,
  include_capex_rd: bool = False,
  include_payroll: bool = False,
) -> Dict[str, Any]:
  """Population summary per
  populate_cohort_bands_for_run return shape. F3 includes 5
  sections; capex_rd + payroll default to absent per v1 §D-2
  (defined-but-not-populated). F10: total resolved >= 1
  satisfied by default (drivers=5)."""
  payload: Dict[str, Any] = {}
  if include_drivers:
    payload["drivers"] = valid_population_summary_section_dict(resolved=5)
  if include_balance_sheet:
    payload["balance_sheet"] = valid_population_summary_section_dict(resolved=12)
  if include_stage_ramp:
    payload["stage_ramp"] = valid_population_summary_section_dict(resolved=8)
  if include_capex_rd:
    payload["capex_rd"] = valid_population_summary_section_dict(resolved=3)
  if include_payroll:
    payload["payroll"] = valid_population_summary_section_dict(resolved=2)
  return payload


# ---------------------------------------------------------------------------
# Top-level IndustryBaselineResolvedContract
# ---------------------------------------------------------------------------

def valid_industry_baseline_resolved_dict(
  *,
  cascade_metric_keys: Optional[List[str]] = None,
  cohort_section_lever_pairs: Optional[List[tuple]] = None,
  get_bands_sections: Optional[List[str]] = None,
  include_population_summary: bool = True,
) -> Dict[str, Any]:
  """Top-level wrapper bundling INPUT (business_profile) + all 4
  OUTPUT shapes."""
  if cascade_metric_keys is None:
    cascade_metric_keys = ["gross_margin_percent", "marketing_percent_revenue"]
  if cohort_section_lever_pairs is None:
    cohort_section_lever_pairs = [
      ("drivers", "gross_margin_percent_lever"),
      ("balance_sheet", "ar_days_lever"),
    ]
  if get_bands_sections is None:
    get_bands_sections = ["drivers", "balance_sheet"]

  payload: Dict[str, Any] = {
    "business_profile": valid_business_profile_dict(),
    "cascade_payloads": {
      mk: valid_cascade_resolver_payload_dict(metric_key=mk)
      for mk in cascade_metric_keys
    },
    "cohort_rows": [
      valid_cohort_sql_row_dict(section=s, lever_id=l)
      for s, l in cohort_section_lever_pairs
    ],
    "get_bands_views": {
      s: valid_get_bands_view_dict(section=s) for s in get_bands_sections
    },
  }
  if include_population_summary:
    payload["population_summary"] = valid_population_summary_dict()
  return payload
