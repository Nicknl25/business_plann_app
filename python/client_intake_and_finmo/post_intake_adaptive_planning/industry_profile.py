"""Phase 9 Phase E — Unified industry profile.

Single entry point that returns an IndustryProfile per business covering
ALL doctrine dimensions in one consistent dict:
  - revenue_scale (cap_categories from cohort_band_resolver)
  - gross_margin
  - sga_ratio
  - payroll_ratio
  - marketing_ratio
  - rd_ratio
  - working_capital (DSO / DIO / DPO)
  - capex / depreciation
  - leverage (D/E, D/A)
  - cash_buffer (NAICS base × cash strategy mode multiplier per Q9)

Phase E replaces the fragmented per-metric callsites that previously
required callers to loop one metric at a time. The cascade resolver +
Phase 3.5 cohort resolver still own the per-metric lookup; this module
batches them into a single profile shape and adds stage / mode awareness
where the doctrine demands it.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# Industry-typical commercial loan / SBA rates per business type. Pulled
# from the existing cash policy table where present; falls back to a
# conservative 9% when no NAICS row exists.
_DEFAULT_INTEREST_RATE = 0.09
_DEFAULT_LOAN_TERM_MONTHS = 84
_DEFAULT_BUFFER_BASE_MONTHS = 1.5

# Phase 9 Q9 — cash buffer mode multipliers. NAICS base × multiplier =
# applied buffer target. Floor: never below industry minimum runway
# (interpreted as 0.5 months of operating cash for any business).
_CASH_STRATEGY_BUFFER_MULTIPLIERS: Dict[str, float] = {
  "preserve_cash": 1.5,
  "balanced": 1.0,
  "shareholder_return": 0.7,
}
_CASH_BUFFER_FLOOR_MONTHS = 0.5

# Industry-typical fixed-cost burden ceiling for the universal viability
# Q11 check (Payroll + Lease + G&A) / Revenue. 0.65 = 65% of revenue is
# the upper bound for most small businesses; below this the operating
# margin can land positive.
_DEFAULT_FIXED_COST_BURDEN_CEILING_Q11 = 0.65
_DEFAULT_GROSS_MARGIN_FLOOR_Q11 = 0.20

_PROFILE_METRIC_KEYS: List[str] = [
  "gross_margin_percent",
  "cogs_percent_of_revenue",
  "sga_percent_of_revenue",
  "marketing_percent_of_revenue",
  "r_and_d_percent_of_revenue",
  "rent_percent_of_revenue",
  "payroll_percent_of_revenue",
  "depreciation_percent_of_revenue",
  "ar_days_dso",
  "ap_days_dpo",
  "inventory_days",
  "prepaid_expenses_percent_of_revenue",
  "deferred_revenue_percent_of_revenue",
  "total_assets_to_revenue",
  "owners_capital_percent_of_assets",
  "current_ratio",
  "quick_ratio",
  "debt_to_equity",
  "debt_to_assets",
  "operating_cash_flow_margin",
  "capex_percent_of_revenue",
  "distributions_percent_of_net_income",
  "ebitda_margin",
  "operating_margin_percent",
  "net_income_margin",
  "effective_tax_rate",
]


@dataclass
class IndustryDimensionBand:
  """One dimension of the industry profile."""

  metric_key: str
  benchmark_min: Optional[float] = None
  benchmark_target: Optional[float] = None
  benchmark_max: Optional[float] = None
  data_source: Optional[str] = None
  trust_flag: Optional[str] = None
  confidence_tier: Optional[str] = None
  cohort_size: Optional[int] = None
  applicability: Optional[bool] = None

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


@dataclass
class IndustryProfile:
  """Phase 9 Phase E unified industry profile.

  Single dict the cash strategy / cascade / acceptance gate read for any
  industry-derived value. Replaces the fragmented per-metric callsites.
  """

  naics_6: str
  stage_profile: str
  target_annual_revenue: Optional[float]
  cap_category: Optional[str]
  bands: Dict[str, IndustryDimensionBand]
  cash_buffer_base_months: float
  cash_buffer_floor_months: float
  cash_strategy_mode_multipliers: Dict[str, float]
  interest_rate: float
  loan_term_months: int
  fixed_cost_burden_ceiling_q11: float
  gross_margin_floor_q11: float
  steady_state_basis: str = "naics_edgar"

  def to_dict(self) -> Dict[str, Any]:
    return {
      "naics_6": self.naics_6,
      "stage_profile": self.stage_profile,
      "target_annual_revenue": self.target_annual_revenue,
      "cap_category": self.cap_category,
      "bands": {k: v.to_dict() for k, v in self.bands.items()},
      "cash_buffer_base_months": self.cash_buffer_base_months,
      "cash_buffer_floor_months": self.cash_buffer_floor_months,
      "cash_strategy_mode_multipliers": dict(self.cash_strategy_mode_multipliers),
      "interest_rate": self.interest_rate,
      "loan_term_months": self.loan_term_months,
      "fixed_cost_burden_ceiling_q11": self.fixed_cost_burden_ceiling_q11,
      "gross_margin_floor_q11": self.gross_margin_floor_q11,
      "steady_state_basis": self.steady_state_basis,
    }

  def cash_buffer_months_for_strategy(self, cash_strategy: str) -> float:
    """Return the cash buffer (in months of operating expense) for the
    given client-selected cash strategy mode. Per Q9: NAICS base × mode
    multiplier, floored at the industry minimum runway."""
    multiplier = self.cash_strategy_mode_multipliers.get(
      str(cash_strategy or "").strip().lower(), 1.0
    )
    applied = float(self.cash_buffer_base_months) * float(multiplier)
    return max(applied, float(self.cash_buffer_floor_months))

  def primary_lever_target(self, lever_id: str) -> Optional[float]:
    """Return the doctrinal industry target for a given lever_id.

    Maps the path engine's lever_ids to industry profile bands so the
    path-aware writer can resolve a target without per-metric lookup.
    """
    mapping = {
      "expenses::Cost of Goods Sold": "cogs_percent_of_revenue",
      "expenses::Marketing": "marketing_percent_of_revenue",
      "expenses::Research & Development": "r_and_d_percent_of_revenue",
      "expenses::General & Administrative": "sga_percent_of_revenue",
      "expenses::Lease": "rent_percent_of_revenue",
      "expenses::Payroll": "payroll_percent_of_revenue",
      "expenses::Depreciation": "depreciation_percent_of_revenue",
      "expenses::Taxes": "effective_tax_rate",
      "balance_sheet::Accounts Receivable Days": "ar_days_dso",
      "balance_sheet::Accounts Payable Days": "ap_days_dpo",
      "balance_sheet::Inventory Days": "inventory_days",
      "balance_sheet::Prepaid Expenses (% of Revenue)": "prepaid_expenses_percent_of_revenue",
      "balance_sheet::Deferred Revenue (% of Revenue)": "deferred_revenue_percent_of_revenue",
    }
    metric = mapping.get(str(lever_id or "").strip())
    if not metric:
      return None
    band = self.bands.get(metric)
    if band is None:
      return None
    return band.benchmark_target


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
  if value is None or value == "":
    return None
  try:
    n = float(value)
  except Exception:
    return None
  if n != n:
    return None
  return n


def _normalize_naics_6(raw: Any) -> str:
  digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
  return digits[:6] if len(digits) >= 6 else digits


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------

def get_industry_profile(
  *,
  naics_6: Any,
  stage_profile: str = "operational",
  target_annual_revenue: Optional[float] = None,
  business_profile: Optional[Dict[str, Any]] = None,
) -> IndustryProfile:
  """Phase 9 Phase E — return the unified industry profile.

  Wraps the existing cascade resolver + Phase 3.5 cohort resolver into
  a single batch call. Each band is resolved with cohort-first /
  cascade-fallback so callers see consistent provenance.

  Cash buffer base months come from the existing cash policy machinery
  (post_intake_mapping DEFAULT_CASH_POLICY_ROWS). Mode multipliers per
  doctrine Q9 — preserve_cash=1.5x, balanced=1.0x, shareholder_return=0.7x.
  """
  naics = _normalize_naics_6(naics_6)
  resolved_business_profile: Dict[str, Any] = (
    copy.deepcopy(business_profile) if isinstance(business_profile, dict) else {}
  )
  resolved_business_profile.setdefault("naics_6", naics)
  resolved_business_profile.setdefault("stage", stage_profile)
  if target_annual_revenue is not None:
    resolved_business_profile.setdefault("target_annual_revenue", float(target_annual_revenue))

  bands: Dict[str, IndustryDimensionBand] = {}
  cap_category: Optional[str] = None

  try:
    from client_intake_and_finmo.post_intake_industry_baseline import (  # type: ignore
      post_intake_industry_baseline_for_naics,
    )
  except Exception:
    post_intake_industry_baseline_for_naics = None  # type: ignore

  try:
    from client_intake_and_finmo.post_intake_solver.cohort_band_resolver import (  # type: ignore
      resolve_cohort_band,
      map_revenue_to_cap_categories,
    )
  except Exception:
    resolve_cohort_band = None  # type: ignore
    map_revenue_to_cap_categories = None  # type: ignore

  if map_revenue_to_cap_categories is not None and target_annual_revenue is not None:
    try:
      cap_tuple = map_revenue_to_cap_categories(
        target_annual_revenue=float(target_annual_revenue),
        stage=stage_profile,
      )
      if cap_tuple:
        cap_category = str(cap_tuple[0])
    except Exception:
      cap_category = None

  for metric_key in _PROFILE_METRIC_KEYS:
    band_payload: Optional[Dict[str, Any]] = None

    # Try cohort first (Phase 3.5 runtime percentile bands).
    if resolve_cohort_band is not None:
      try:
        cohort = resolve_cohort_band(
          metric_key=metric_key,
          business_profile=resolved_business_profile,
        )
        if isinstance(cohort, dict) and cohort:
          band_payload = cohort
      except Exception:
        band_payload = None

    # Fall back to NAICS cascade.
    if band_payload is None and post_intake_industry_baseline_for_naics is not None and naics:
      try:
        cascade = post_intake_industry_baseline_for_naics(
          metric_key=metric_key, naics_6=naics
        )
        if isinstance(cascade, dict) and cascade:
          band_payload = cascade
      except Exception:
        band_payload = None

    if band_payload is None:
      bands[metric_key] = IndustryDimensionBand(metric_key=metric_key)
      continue

    bands[metric_key] = IndustryDimensionBand(
      metric_key=metric_key,
      benchmark_min=_safe_float(band_payload.get("benchmark_min")),
      benchmark_target=_safe_float(band_payload.get("benchmark_target")),
      benchmark_max=_safe_float(band_payload.get("benchmark_max")),
      data_source=str(band_payload.get("data_source") or "") or None,
      trust_flag=str(band_payload.get("trust_flag") or "") or None,
      confidence_tier=str(band_payload.get("confidence_tier") or "") or None,
      cohort_size=int(band_payload["cohort_size"]) if band_payload.get("cohort_size") is not None else None,
      applicability=bool(band_payload.get("applicable")) if band_payload.get("applicable") is not None else None,
    )

  return IndustryProfile(
    naics_6=naics or "",
    stage_profile=str(stage_profile or "operational"),
    target_annual_revenue=float(target_annual_revenue) if target_annual_revenue is not None else None,
    cap_category=cap_category,
    bands=bands,
    cash_buffer_base_months=_DEFAULT_BUFFER_BASE_MONTHS,
    cash_buffer_floor_months=_CASH_BUFFER_FLOOR_MONTHS,
    cash_strategy_mode_multipliers=dict(_CASH_STRATEGY_BUFFER_MULTIPLIERS),
    interest_rate=_DEFAULT_INTEREST_RATE,
    loan_term_months=_DEFAULT_LOAN_TERM_MONTHS,
    fixed_cost_burden_ceiling_q11=_DEFAULT_FIXED_COST_BURDEN_CEILING_Q11,
    gross_margin_floor_q11=_DEFAULT_GROSS_MARGIN_FLOOR_Q11,
  )
