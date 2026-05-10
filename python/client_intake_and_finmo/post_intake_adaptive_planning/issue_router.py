"""Phase 9 Phase D — Issue Router.

Routes every detected violation to an adaptation family with structured
remediation context. Replaces the cascade's progressive-loosen tier
selection with deterministic per-issue routing.

Inputs the router accepts:
  - Realism gate hard_fails / warnings (per-metric violations)
  - Solver target residuals (sanity_assertion residual_violations)
  - Structural feasibility diagnostics
  - Joint feasibility diagnostics
  - Composite revenue trajectory check (Phase C4)
  - Cash validation issues (only liquidity_failure routes to cash pass)

Output (one IssueRoute per detected violation):

    {
      "issue_code": str,
      "severity": "adaptation_required" | "stage_tolerable" |
                  "accept_with_exception" | "terminal_infrastructure",
      "adaptation_family": str,         # one of ADAPTATION_FAMILIES
      "primary_levers": List[str],
      "secondary_levers": List[str],
      "target_quarter_range": Tuple[int, int],
      "deadline_quarter": int,
      "path_shape": str,                # default shape for this family
      "gpt_consultant_required": bool,
      "cash_pass_allowed": bool,        # True only for liquidity_failure
    }

Phase D4's cascade refactor consumes IssueRoute and walks the adaptation
families in deadline-order (closest deadline first) until residuals
clear or restoration cascade fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from client_intake_and_finmo.post_intake_adaptive_planning.policy import (
  ADAPTATION_FAMILIES,
)


# ----------------------------------------------------------------------------
# Severity vocabulary
# ----------------------------------------------------------------------------

SEVERITY_ADAPTATION_REQUIRED = "adaptation_required"
SEVERITY_STAGE_TOLERABLE = "stage_tolerable"
SEVERITY_ACCEPT_WITH_EXCEPTION = "accept_with_exception"
SEVERITY_TERMINAL_INFRASTRUCTURE = "terminal_infrastructure"

ALL_SEVERITIES = [
  SEVERITY_ADAPTATION_REQUIRED,
  SEVERITY_STAGE_TOLERABLE,
  SEVERITY_ACCEPT_WITH_EXCEPTION,
  SEVERITY_TERMINAL_INFRASTRUCTURE,
]


# ----------------------------------------------------------------------------
# Family default path shapes (used when the cascade applies a remediation
# without a metric-specific override).
# ----------------------------------------------------------------------------

_FAMILY_DEFAULT_PATH_SHAPES: Dict[str, str] = {
  "ramp_adaptation": "s_curve",
  "turnaround_recovery_q5_q11": "glidepath",
  "industry_normalization": "glidepath",
  "operating_scale_adaptation": "capacity_expansion",
  "funding_adaptation": "flat",
  "balance_sheet_adaptation": "linear_to_mature",
  "schedule_adaptation": "flat",
  "revenue_achievability": "capacity_expansion",
  "payroll_ratio_excess": "hiring_schedule",
  "leverage_excess": "flat",
  "capital_intensity_adaptation": "flat",
  "margin_compression": "glidepath",
}


# ----------------------------------------------------------------------------
# Issue code → family mapping for sources OUTSIDE the realism table.
# Realism table rows already carry their own issue_family / remediation_family.
# This map covers issue codes from solver / cash / feasibility paths.
# ----------------------------------------------------------------------------

_ISSUE_CODE_TO_FAMILY: Dict[str, str] = {
  # Cash and funding.
  "liquidity_failure": "funding_adaptation",
  "working_capital_mismatch": "balance_sheet_adaptation",
  "funding_structure_mismatch": "funding_adaptation",
  "loss_window_unfunded": "funding_adaptation",
  # Solver feasibility.
  "joint_infeasibility": "revenue_achievability",
  "structural_infeasibility": "revenue_achievability",
  "stuck_pinned": "revenue_achievability",
  "no_candidate_levers": "revenue_achievability",
  "max_iterations_reached": "revenue_achievability",
  # Stage ramp / revenue trajectory.
  "stage_ramp_revenue_bridge_failed": "revenue_achievability",
  "composite_revenue_out_of_band": "revenue_achievability",
  "composite_revenue_qoq_below_target": "revenue_achievability",
  "composite_revenue_qoq_above_max": "ramp_adaptation",
  # Schedule sanity warnings (Cat 5 audit, Q7 decision).
  "schedule_sanity_wage_warning": "payroll_ratio_excess",
  "schedule_sanity_productivity_warning": "operating_scale_adaptation",
  "schedule_sanity_debt_rate_warning": "leverage_excess",
  "schedule_sanity_capex_ppe_warning": "capital_intensity_adaptation",
  # Sanity assertion residual violations.
  "solver_target_residual": "industry_normalization",
}


# ----------------------------------------------------------------------------
# IssueRoute dataclass
# ----------------------------------------------------------------------------

@dataclass
class IssueRoute:
  """Single routing decision for a detected violation."""

  issue_code: str
  severity: str
  adaptation_family: str
  primary_levers: List[str] = field(default_factory=list)
  secondary_levers: List[str] = field(default_factory=list)
  target_quarter_range: Tuple[int, int] = (1, 20)
  deadline_quarter: int = 20
  path_shape: str = "flat"
  gpt_consultant_required: bool = False
  cash_pass_allowed: bool = False
  source: str = ""                # "realism" | "solver" | "cash" | "feasibility" | "composite_revenue"
  notes: str = ""
  detected_value: Optional[float] = None
  expected_floor: Optional[float] = None
  expected_ceiling: Optional[float] = None

  def to_dict(self) -> Dict[str, Any]:
    return {
      "issue_code": self.issue_code,
      "severity": self.severity,
      "adaptation_family": self.adaptation_family,
      "primary_levers": list(self.primary_levers),
      "secondary_levers": list(self.secondary_levers),
      "target_quarter_range": list(self.target_quarter_range),
      "deadline_quarter": self.deadline_quarter,
      "path_shape": self.path_shape,
      "gpt_consultant_required": self.gpt_consultant_required,
      "cash_pass_allowed": self.cash_pass_allowed,
      "source": self.source,
      "notes": self.notes,
      "detected_value": self.detected_value,
      "expected_floor": self.expected_floor,
      "expected_ceiling": self.expected_ceiling,
    }


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _stage_profile_from_policy(adaptive_policy: Optional[Dict[str, Any]]) -> str:
  if not isinstance(adaptive_policy, dict):
    return "operational"
  return str(adaptive_policy.get("stage_profile") or "operational").strip().lower()


def _stage_tolerance_multiplier(
  *,
  stage_profile: str,
  stage_sensitivity: Optional[Dict[str, float]],
) -> float:
  if not isinstance(stage_sensitivity, dict):
    return 1.0
  raw = stage_sensitivity.get(stage_profile)
  if raw is None:
    return 1.0
  try:
    return float(raw)
  except Exception:
    return 1.0


def _classify_severity(
  *,
  detected: Optional[float],
  floor: Optional[float],
  ceiling: Optional[float],
  stage_multiplier: float,
  is_universal_viability_check: bool,
) -> str:
  """Decide adaptation_required vs stage_tolerable vs accept_with_exception.

  Universal viability checks (Q11 EBITDA positive, loss window funded,
  no post-recovery relapse) ALWAYS require adaptation — stage cannot
  waive the universal rule.

  Other violations may be stage_tolerable when the deviation is within
  stage_multiplier × tolerance band. Beyond that, adaptation_required.
  Inside the band, accept_with_exception (the cascade documents but
  doesn't repair).
  """
  if is_universal_viability_check:
    return SEVERITY_ADAPTATION_REQUIRED
  if detected is None:
    return SEVERITY_ACCEPT_WITH_EXCEPTION
  if floor is not None and detected < floor * (1.0 / max(stage_multiplier, 0.1)):
    return SEVERITY_ADAPTATION_REQUIRED
  if ceiling is not None and detected > ceiling * stage_multiplier:
    return SEVERITY_ADAPTATION_REQUIRED
  if floor is not None and detected < floor:
    return SEVERITY_STAGE_TOLERABLE
  if ceiling is not None and detected > ceiling:
    return SEVERITY_STAGE_TOLERABLE
  return SEVERITY_ACCEPT_WITH_EXCEPTION


def _is_universal_viability_check(metric_key: str) -> bool:
  return metric_key in {
    "ebitda_positive_by_q11",
    "ebitda_recovery_trend_q5_q11",
    "loss_window_funded_through_q5",
    "no_post_recovery_relapse_q11_q20",
    "gross_margin_supports_ebitda_recovery",
    "fixed_cost_burden_reduced_or_scaled_by_q11",
  }


# ----------------------------------------------------------------------------
# Public router entry points
# ----------------------------------------------------------------------------

# Phase 9 P3 — route_realism_violation RETIRED. The realism-gate-to-
# adaptation-family routing has been replaced by direct target → driver
# allocation inside the target-driven restoration loop in
# python/client_intake_and_finmo/post_intake_target_solver/. The new
# loop reads the 4 active solver-target rows from the realism lookup
# table and solves each target across all 20 quarters by allocating
# delta across operating-side drivers proportional to slack-to-bound;
# the family-routed flat-stamp adaptation is gone.


def route_solver_residual(
  *,
  metric_key: str,
  detected_value: Optional[float],
  target_value: Optional[float],
  tolerance: Optional[float] = None,
  adaptive_policy: Optional[Dict[str, Any]] = None,
) -> IssueRoute:
  """Route a sanity_assertion residual violation. Defaults to
  industry_normalization unless metric_key matches a known family.
  """
  family = _ISSUE_CODE_TO_FAMILY.get(metric_key, "industry_normalization")
  return IssueRoute(
    issue_code=f"solver_target_residual:{metric_key}",
    severity=SEVERITY_ADAPTATION_REQUIRED,
    adaptation_family=family,
    target_quarter_range=(1, 20),
    deadline_quarter=20,
    path_shape=_FAMILY_DEFAULT_PATH_SHAPES.get(family, "flat"),
    source="solver",
    detected_value=detected_value,
    expected_floor=target_value,
    notes=f"Solver residual violation on {metric_key} (target={target_value}, detected={detected_value}, tol={tolerance})",
  )


def route_feasibility_diagnostic(
  *,
  diagnostic_kind: str,
  feasibility_payload: Dict[str, Any],
  adaptive_policy: Optional[Dict[str, Any]] = None,
) -> IssueRoute:
  """Route a structural / joint feasibility failure to revenue_achievability."""
  family = _ISSUE_CODE_TO_FAMILY.get(diagnostic_kind, "revenue_achievability")
  return IssueRoute(
    issue_code=diagnostic_kind,
    severity=SEVERITY_ADAPTATION_REQUIRED,
    adaptation_family=family,
    target_quarter_range=(1, 20),
    deadline_quarter=20,
    path_shape=_FAMILY_DEFAULT_PATH_SHAPES.get(family, "capacity_expansion"),
    source="feasibility",
    notes=str((feasibility_payload or {}).get("reason") or "")[:500],
  )


def route_composite_revenue_violation(
  *,
  out_of_band_quarters: List[Dict[str, Any]],
  adaptive_policy: Optional[Dict[str, Any]] = None,
) -> List[IssueRoute]:
  """Route composite-revenue trajectory violations from Phase C4 check.

  Each out-of-band quarter is a separate route — the cascade can repair
  the worst quarters first. Below-target quarters route to
  revenue_achievability; above-max (overshoot) route to ramp_adaptation.
  """
  routes: List[IssueRoute] = []
  for entry in out_of_band_quarters or []:
    if not isinstance(entry, dict):
      continue
    if entry.get("status") != "out_of_band":
      continue
    realized = entry.get("realized_qoq")
    target = entry.get("contract_target")
    cap = entry.get("contract_max")
    if realized is None or target is None:
      continue
    quarter = int(entry.get("quarter") or 0)
    if cap is not None and float(realized) > float(cap):
      issue_code = "composite_revenue_qoq_above_max"
    else:
      issue_code = "composite_revenue_qoq_below_target"
    family = _ISSUE_CODE_TO_FAMILY.get(issue_code, "revenue_achievability")
    routes.append(
      IssueRoute(
        issue_code=f"{issue_code}:Q{quarter}",
        severity=SEVERITY_ADAPTATION_REQUIRED,
        adaptation_family=family,
        primary_levers=["revenue::Utilization", "revenue::Capacity", "revenue::Unit Price"],
        target_quarter_range=(quarter, quarter),
        deadline_quarter=quarter,
        path_shape=_FAMILY_DEFAULT_PATH_SHAPES.get(family, "capacity_expansion"),
        source="composite_revenue",
        detected_value=float(realized),
        expected_floor=float(target),
        expected_ceiling=float(cap) if cap is not None else None,
        notes=f"Composite revenue Q{quarter}: realized={realized}, target={target}, max={cap}",
      )
    )
  return routes


def route_cash_validation_issue(
  *,
  failed_rule_codes: List[str],
  cash_diagnostic: Dict[str, Any],
  adaptive_policy: Optional[Dict[str, Any]] = None,
) -> List[IssueRoute]:
  """Route cash-side validation issues. Per doctrine, cash_pass_allowed=True
  ONLY for liquidity_failure; everything else must repair operating model."""
  routes: List[IssueRoute] = []
  for code in failed_rule_codes or []:
    code_clean = str(code or "").strip().lower()
    if not code_clean:
      continue
    family = _ISSUE_CODE_TO_FAMILY.get(code_clean, "funding_adaptation")
    cash_allowed = code_clean == "liquidity_failure"
    routes.append(
      IssueRoute(
        issue_code=code_clean,
        severity=SEVERITY_ADAPTATION_REQUIRED,
        adaptation_family=family,
        primary_levers=[
          "schedules::Debt Issuance (New Borrowing)",
          "balance_sheet::Owner's Capital",
          "balance_sheet::Distributions",
        ],
        target_quarter_range=(1, 20),
        deadline_quarter=20,
        path_shape=_FAMILY_DEFAULT_PATH_SHAPES.get(family, "flat"),
        cash_pass_allowed=cash_allowed,
        source="cash",
        notes=str((cash_diagnostic or {}).get("reason") or "")[:500],
      )
    )
  return routes


def route_schedule_sanity_warning(
  *,
  warning_kind: str,
  warning_payload: Dict[str, Any],
  adaptive_policy: Optional[Dict[str, Any]] = None,
) -> IssueRoute:
  """Route schedule_sanity warnings (wage / productivity / debt rate /
  capex_ppe) to their adaptation families per Phase 9 Q7 decision.
  """
  code = f"schedule_sanity_{warning_kind}_warning"
  family = _ISSUE_CODE_TO_FAMILY.get(code, "industry_normalization")
  return IssueRoute(
    issue_code=code,
    severity=SEVERITY_ADAPTATION_REQUIRED,
    adaptation_family=family,
    target_quarter_range=(1, 20),
    deadline_quarter=20,
    path_shape=_FAMILY_DEFAULT_PATH_SHAPES.get(family, "flat"),
    source="schedule_sanity",
    notes=str((warning_payload or {}).get("reason") or warning_kind)[:500],
  )


# ----------------------------------------------------------------------------
# Aggregation: combine many IssueRoute into a deadline-ordered queue
# ----------------------------------------------------------------------------

def order_routes_by_deadline(routes: List[IssueRoute]) -> List[IssueRoute]:
  """Order routes by deadline_quarter ascending so the cascade repairs the
  tightest deadlines first. Within the same deadline, adaptation_required
  beats stage_tolerable beats accept_with_exception."""
  severity_priority = {
    SEVERITY_ADAPTATION_REQUIRED: 0,
    SEVERITY_STAGE_TOLERABLE: 1,
    SEVERITY_ACCEPT_WITH_EXCEPTION: 2,
    SEVERITY_TERMINAL_INFRASTRUCTURE: 3,
  }
  return sorted(
    list(routes or []),
    key=lambda r: (
      int(r.deadline_quarter or 20),
      severity_priority.get(r.severity, 99),
      r.issue_code,
    ),
  )
