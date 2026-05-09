"""Phase 9 Phase B — Adaptive Operating Doctrine policy contract.

Computes the AdaptivePolicyContract from intake + FINMO snapshot + industry
profile in pure deterministic Python. No GPT. No SQL writes. Read-only inputs.

The contract is the single source of truth for:
  - stage_profile (startup | early | operational | mature)
  - planning_mode (normalize | turnaround | rebalance | growth_investment | preservation)
  - loss_tolerance_through_q (Q1..Qn losses tolerated for this stage)
  - ebitda_positive_required_by_q (always 11 per universal viability rule)
  - primary_objective (restore_viability | support_ramp | industry_alignment | growth_investment | stability)
  - allowed_adaptation_families (which families the cascade may use)
  - cash_pass_role (always "funding_only")
  - steady_state_target_basis (always "naics_edgar")
  - client_input_authority (per-driver authority map)
  - viability_deadline_quarters (per-metric deadlines per Q3 decision)

Wired into run_target_seeking_orchestrated_system_run as Step 0, before any
target seeking, structural feasibility, or Phase 3 calibration. Downstream
consumers (cascade, realism gate, cash pass) read from this contract instead
of inferring stage / mode locally.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


# ----------------------------------------------------------------------------
# Doctrine vocabulary
# ----------------------------------------------------------------------------

ALLOWED_STAGE_PROFILES: List[str] = ["startup", "early", "operational", "mature"]

ALLOWED_PLANNING_MODES: List[str] = [
  "normalize",
  "turnaround",
  "rebalance",
  "growth_investment",
  "preservation",
]

ALLOWED_PRIMARY_OBJECTIVES: List[str] = [
  "restore_viability",
  "support_ramp",
  "industry_alignment",
  "growth_investment",
  "stability",
]

# The 12 issue-aware adaptation families per Phase 9 doctrine. Phase D wires
# the cascade refactor; Phase B carries the canonical list.
ADAPTATION_FAMILIES: List[str] = [
  "ramp_adaptation",
  "turnaround_recovery_q5_q11",
  "industry_normalization",
  "operating_scale_adaptation",
  "funding_adaptation",
  "balance_sheet_adaptation",
  "schedule_adaptation",
  "revenue_achievability",
  "payroll_ratio_excess",
  "leverage_excess",
  "capital_intensity_adaptation",
  "margin_compression",
]


# Universal viability deadlines (Q3 decision). Profitability metrics bind at
# Q11; working capital approaches industry by Q11 and matches by Q20; leverage
# steadies by Q20; payroll matures by Q11.
DEFAULT_VIABILITY_DEADLINE_QUARTERS: Dict[str, int] = {
  "ebitda_positive": 11,
  "working_capital_approach": 11,
  "working_capital_match": 20,
  "leverage_steady_state": 20,
  "payroll_ratio_mature": 11,
}


# Per-driver authority map per Phase 9 directive. The values describe how
# Phase D's issue router treats client input vs derived envelopes:
#   strong_if_plausible  - client input wins inside a plausibility band
#   advisory             - client input is one signal among several
#   context_only         - client input is informational; derived value rules
#   q0_anchor_only       - client input anchors Q0 only; Q1+ comes from ramp
DEFAULT_CLIENT_INPUT_AUTHORITY: Dict[str, str] = {
  # Operating drivers
  "capacity": "strong_if_plausible",
  "price": "strong_if_plausible",
  "utilization": "strong_if_plausible",
  "current_payroll": "context_only",
  "headcount_target": "advisory",
  "year1_revenue": "advisory",
  "marketing_spend": "advisory",
  "rd_spend": "advisory",
  "sga_spend": "advisory",
  "rent": "advisory",
  # Balance sheet anchors (Q0 only — Q1+ is ramp-derived)
  "current_ar": "q0_anchor_only",
  "current_ap": "q0_anchor_only",
  "current_inventory": "q0_anchor_only",
  "current_cash": "q0_anchor_only",
  "current_debt": "q0_anchor_only",
  "current_ppe": "q0_anchor_only",
  "owner_capital": "context_only",
  "starting_assets": "advisory",
  # Schedule anchors
  "capex_schedule": "advisory",
  "debt_schedule": "advisory",
  "headcount_schedule": "advisory",
}


# ----------------------------------------------------------------------------
# Stage profile and lifecycle helpers
# ----------------------------------------------------------------------------

# Maturity threshold: businesses operating ≥ 60 months (5 years) shift from
# "operational" to "mature". This is the same lifecycle break the steady-state
# realism band assumes (mature operating ratios), and matches the audit's
# observation that operational-vs-mature affects WHEN the floor binds, not
# WHETHER it binds.
_MATURE_AGE_MONTHS_THRESHOLD: int = 60


def _clean_text(value: Any) -> str:
  return str(value or "").strip()


def _parse_date(raw: Any) -> Optional[date]:
  if raw is None:
    return None
  if isinstance(raw, date):
    return raw
  text = _clean_text(raw)
  if not text:
    return None
  for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
    try:
      return datetime.strptime(text, fmt).date()
    except ValueError:
      continue
  return None


def _whole_months_between(start_date: date, end_date: date) -> int:
  months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
  if end_date.day < start_date.day:
    months -= 1
  return int(months)


def _business_age_months(
  start_date_raw: Any, *, current_date: Optional[date] = None
) -> Optional[int]:
  start = _parse_date(start_date_raw)
  if start is None:
    return None
  today = current_date or datetime.utcnow().date()
  if start > today:
    return 0
  return max(0, _whole_months_between(start, today))


def _normalize_stage_profile(
  raw_business_stage: Any, business_age_months: Optional[int]
) -> str:
  norm = _clean_text(raw_business_stage).lower().replace("_", "-")
  if norm in {"pre-revenue", "pre revenue", "startup", "start-up", "new", "launch"}:
    return "startup"
  if norm in {"early", "early-stage", "early stage", "growth"}:
    return "early"
  age = int(business_age_months or 0)
  if age >= _MATURE_AGE_MONTHS_THRESHOLD:
    return "mature"
  return "operational"


def _normalize_planning_mode(raw_mode: Any) -> str:
  norm = _clean_text(raw_mode).lower()
  if norm in ALLOWED_PLANNING_MODES:
    return norm
  # Phase 9 doctrine: when intake omits or supplies an unknown mode, default
  # to "turnaround" so adaptation has the broadest authority. This matches
  # the existing behaviour at post_intake_mapping.py:2986 and is the safest
  # default for the cascade.
  return "turnaround"


def _detect_distress_context(planning_mode: str, planning_mode_reason: Any) -> bool:
  if planning_mode == "turnaround":
    return True
  reason = _clean_text(planning_mode_reason).lower()
  if not reason:
    return False
  for token in ("distress", "rescue", "insolven", "survival", "turnaround"):
    if token in reason:
      return True
  return False


# ----------------------------------------------------------------------------
# Doctrine derivations
# ----------------------------------------------------------------------------

def _loss_tolerance_through_q(stage_profile: str) -> int:
  """Q1..Qn losses tolerated when stage-appropriate AND funded.

  Universal viability rule (doctrine §): Q1-Q5 is the loss-tolerance window.
  Stage shifts WHEN inside that window the floor binds, not WHETHER it binds.
  Startup uses the full Q5 window; mature compresses to Q1 only.
  """
  return {
    "startup": 5,
    "early": 4,
    "operational": 2,
    "mature": 1,
  }.get(stage_profile, 5)


def _primary_objective_for(planning_mode: str, stage_profile: str) -> str:
  if planning_mode == "turnaround":
    return "restore_viability"
  if planning_mode == "growth_investment":
    return "growth_investment"
  if planning_mode == "preservation":
    return "stability"
  if planning_mode == "rebalance":
    return "industry_alignment"
  if planning_mode == "normalize":
    if stage_profile in {"startup", "early"}:
      return "support_ramp"
    return "industry_alignment"
  return "restore_viability"


def _allowed_families_for(planning_mode: str, stage_profile: str) -> List[str]:
  """All families available by default. The cascade picks per detected issue.

  Phase B carries the full list; Phase D may scope per stage/mode (e.g.,
  a Q11+ business in turnaround mode skipping ramp_adaptation). For now
  the contract advertises every family the cascade may invoke.
  """
  return list(ADAPTATION_FAMILIES)


def _safe_naics_6(ops_json: Optional[Dict[str, Any]]) -> Optional[str]:
  if not isinstance(ops_json, dict):
    return None
  raw = ops_json.get("business_naics_6") or ops_json.get("business_naics")
  digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
  return digits or None


def _safe_industry_basis(industry_profile: Optional[Dict[str, Any]]) -> str:
  """Steady-state target basis comes from the unified industry profile when
  available; otherwise NAICS+EDGAR cascade per Phase 8 default.
  """
  if isinstance(industry_profile, dict):
    basis = _clean_text(industry_profile.get("steady_state_basis"))
    if basis:
      return basis
  return "naics_edgar"


# ----------------------------------------------------------------------------
# Contract dataclass
# ----------------------------------------------------------------------------

@dataclass
class AdaptivePolicyContract:
  """Phase 9 Phase B adaptive policy contract.

  Returned by compute_adaptive_policy() and stamped on the orchestrator's
  result payload. Downstream consumers (cascade, realism gate, cash pass,
  Phase D issue router) read from this contract.
  """

  stage_profile: str
  planning_mode: str
  loss_tolerance_through_q: int
  ebitda_positive_required_by_q: int
  primary_objective: str
  allowed_adaptation_families: List[str]
  cash_pass_role: str = "funding_only"
  selected_cash_strategy: str = "balanced"
  steady_state_target_basis: str = "naics_edgar"
  client_input_authority: Dict[str, str] = field(
    default_factory=lambda: dict(DEFAULT_CLIENT_INPUT_AUTHORITY)
  )
  viability_deadline_quarters: Dict[str, int] = field(
    default_factory=lambda: dict(DEFAULT_VIABILITY_DEADLINE_QUARTERS)
  )
  policy_version: str = "adaptive_policy_v1"
  computation_inputs: Dict[str, Any] = field(default_factory=dict)
  explicit_distress_context: bool = False

  def to_dict(self) -> Dict[str, Any]:
    return asdict(self)


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

_VALID_CASH_STRATEGIES: List[str] = ["preserve_cash", "balanced", "shareholder_return"]


def _normalize_selected_cash_strategy(
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
) -> str:
  """Pull the client-selected cash strategy mode from intake. Defaults to
  ``balanced`` when unset. Aliases (conservative -> preserve_cash,
  aggressive -> shareholder_return) are normalized."""
  for source in (business_facts or {}, (business_facts or {}).get("fact_template") or {}, ops_json or {}):
    if not isinstance(source, dict):
      continue
    raw = source.get("cash_strategy") or source.get("selected_cash_strategy")
    if not raw:
      continue
    norm = str(raw).strip().lower().replace("-", "_")
    if norm == "conservative":
      return "preserve_cash"
    if norm == "aggressive":
      return "shareholder_return"
    if norm in _VALID_CASH_STRATEGIES:
      return norm
  return "balanced"


def compute_adaptive_policy(
  *,
  business_facts: Optional[Dict[str, Any]],
  ops_json: Optional[Dict[str, Any]],
  financials_json: Optional[Dict[str, Any]] = None,
  financials_year1_json: Optional[Dict[str, Any]] = None,
  finmo_snapshot: Optional[Dict[str, Any]] = None,
  industry_profile: Optional[Dict[str, Any]] = None,
  planning_mode: Optional[str] = None,
  planning_mode_reason: Optional[str] = None,
  current_date: Optional[date] = None,
) -> AdaptivePolicyContract:
  """Compute the AdaptivePolicyContract for a planning run.

  Pure-Python deterministic. Inputs are read-only. Output is the single
  source of truth for stage / mode / viability deadlines / adaptation
  authority used by all downstream Phase B–G phases.
  """

  facts = business_facts if isinstance(business_facts, dict) else {}
  fact_template = facts.get("fact_template")
  fact_template = fact_template if isinstance(fact_template, dict) else {}

  raw_stage = (
    _clean_text(fact_template.get("business_stage"))
    or _clean_text(facts.get("business_stage"))
    or _clean_text((ops_json or {}).get("business_stage"))
  )
  raw_start_date = (
    fact_template.get("business_start_date")
    or facts.get("business_start_date")
    or (ops_json or {}).get("business_start_date")
  )

  age_months = _business_age_months(raw_start_date, current_date=current_date)
  stage_profile = _normalize_stage_profile(raw_stage, age_months)
  mode = _normalize_planning_mode(planning_mode)
  distress = _detect_distress_context(mode, planning_mode_reason)

  loss_through_q = _loss_tolerance_through_q(stage_profile)
  primary_objective = _primary_objective_for(mode, stage_profile)
  allowed_families = _allowed_families_for(mode, stage_profile)
  steady_state_basis = _safe_industry_basis(industry_profile)
  selected_cash_strategy = _normalize_selected_cash_strategy(business_facts, ops_json)

  computation_inputs: Dict[str, Any] = {
    "raw_business_stage": raw_stage,
    "business_start_date": _clean_text(raw_start_date),
    "business_age_months_at_run": age_months,
    "raw_planning_mode": _clean_text(planning_mode),
    "planning_mode_reason": _clean_text(planning_mode_reason),
    "naics_6": _safe_naics_6(ops_json),
    "industry_profile_present": bool(industry_profile),
    "finmo_snapshot_present": bool(finmo_snapshot),
    "current_date": (current_date or datetime.utcnow().date()).isoformat(),
  }

  return AdaptivePolicyContract(
    stage_profile=stage_profile,
    planning_mode=mode,
    loss_tolerance_through_q=loss_through_q,
    ebitda_positive_required_by_q=DEFAULT_VIABILITY_DEADLINE_QUARTERS["ebitda_positive"],
    primary_objective=primary_objective,
    allowed_adaptation_families=allowed_families,
    selected_cash_strategy=selected_cash_strategy,
    steady_state_target_basis=steady_state_basis,
    explicit_distress_context=distress,
    computation_inputs=computation_inputs,
  )
