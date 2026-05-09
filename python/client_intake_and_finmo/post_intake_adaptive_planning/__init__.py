"""Adaptive Operating Doctrine — Phase 9.

Single source of truth for stage profile, planning mode, viability deadlines,
allowed adaptation families, and client-input authority. Every downstream
consumer reads from the AdaptivePolicyContract returned by
compute_adaptive_policy(). Raw planning_mode / business_stage strings are not
to be consulted outside this module's policy output.

Phase C2 adds the path engine — deterministic shape functions and a
per-driver shape registry — so solver lever writes follow the doctrinal
trajectory shapes (s_curve, glidepath, capacity_expansion, etc.) instead
of broadcasting a scalar across Q1..Q20.
"""

from client_intake_and_finmo.post_intake_adaptive_planning.policy import (
  ADAPTATION_FAMILIES,
  ALLOWED_PLANNING_MODES,
  ALLOWED_PRIMARY_OBJECTIVES,
  ALLOWED_STAGE_PROFILES,
  AdaptivePolicyContract,
  compute_adaptive_policy,
)
from client_intake_and_finmo.post_intake_adaptive_planning.path_engine import (
  ALL_SHAPES,
  PathComputation,
  SHAPE_CALCULATED,
  SHAPE_CAPACITY_EXPANSION,
  SHAPE_FLAT,
  SHAPE_GLIDEPATH,
  SHAPE_HIRING_SCHEDULE,
  SHAPE_INDUSTRY_CONVERGENCE_DECAY,
  SHAPE_LINEAR_TO_MATURE,
  SHAPE_S_CURVE,
  SHAPE_SCHEDULE_LOCKED,
  SHAPE_STOCK_CARRYFORWARD,
  WRITABLE_SHAPES,
  capacity_expansion,
  compute_per_quarter_values,
  flat_path,
  glidepath,
  industry_convergence_decay,
  linear_to_mature,
  lookup_shape_for_lever,
  s_curve,
)
from client_intake_and_finmo.post_intake_adaptive_planning.issue_router import (
  ALL_SEVERITIES,
  IssueRoute,
  SEVERITY_ACCEPT_WITH_EXCEPTION,
  SEVERITY_ADAPTATION_REQUIRED,
  SEVERITY_STAGE_TOLERABLE,
  SEVERITY_TERMINAL_INFRASTRUCTURE,
  order_routes_by_deadline,
  route_cash_validation_issue,
  route_composite_revenue_violation,
  route_feasibility_diagnostic,
  route_realism_violation,
  route_schedule_sanity_warning,
  route_solver_residual,
)

__all__ = [
  "ADAPTATION_FAMILIES",
  "ALLOWED_PLANNING_MODES",
  "ALLOWED_PRIMARY_OBJECTIVES",
  "ALLOWED_STAGE_PROFILES",
  "ALL_SEVERITIES",
  "ALL_SHAPES",
  "AdaptivePolicyContract",
  "IssueRoute",
  "PathComputation",
  "SEVERITY_ACCEPT_WITH_EXCEPTION",
  "SEVERITY_ADAPTATION_REQUIRED",
  "SEVERITY_STAGE_TOLERABLE",
  "SEVERITY_TERMINAL_INFRASTRUCTURE",
  "SHAPE_CALCULATED",
  "SHAPE_CAPACITY_EXPANSION",
  "SHAPE_FLAT",
  "SHAPE_GLIDEPATH",
  "SHAPE_HIRING_SCHEDULE",
  "SHAPE_INDUSTRY_CONVERGENCE_DECAY",
  "SHAPE_LINEAR_TO_MATURE",
  "SHAPE_S_CURVE",
  "SHAPE_SCHEDULE_LOCKED",
  "SHAPE_STOCK_CARRYFORWARD",
  "WRITABLE_SHAPES",
  "capacity_expansion",
  "compute_adaptive_policy",
  "compute_per_quarter_values",
  "flat_path",
  "glidepath",
  "industry_convergence_decay",
  "linear_to_mature",
  "lookup_shape_for_lever",
  "order_routes_by_deadline",
  "route_cash_validation_issue",
  "route_composite_revenue_violation",
  "route_feasibility_diagnostic",
  "route_realism_violation",
  "route_schedule_sanity_warning",
  "route_solver_residual",
  "s_curve",
]
