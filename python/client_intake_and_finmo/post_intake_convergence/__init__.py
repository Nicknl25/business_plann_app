"""Post-intake convergence contract helpers."""

from .contracts import (
  build_unified_convergence_contract_policy,
  unified_convergence_contract_constraints,
  validate_unified_convergence_contract_horizon,
)
from .retry_scope import (
  build_retry_scope_payload,
  decorate_retry_scope_payload,
  evaluate_retry_improvement,
  full_horizon_quarters,
  full_horizon_retry_scope_mode,
  retry_scope_lever_ids,
  retry_scope_quarters,
  subset_numeric_solver_contract,
)
from .runner import (
  bind_runtime_dependencies,
)
from .runtime import *  # noqa: F401,F403
from .runtime import bind_runtime_dependencies as bind_convergence_runtime_dependencies

# Phase 9 P3.24 — `run_unified_post_grid_system_run` removed from the
# package surface. The function (and its alias) were deleted alongside
# the legacy convergence cycle loop. The post-intake pipeline is now
# driven entirely by `run_target_seeking_orchestrated_system_run` in
# post_intake_solver/orchestrator.py.

__all__ = [
  "build_unified_convergence_contract_policy",
  "build_retry_scope_payload",
  "decorate_retry_scope_payload",
  "evaluate_retry_improvement",
  "full_horizon_quarters",
  "full_horizon_retry_scope_mode",
  "retry_scope_lever_ids",
  "retry_scope_quarters",
  "bind_runtime_dependencies",
  "subset_numeric_solver_contract",
  "unified_convergence_contract_constraints",
  "validate_unified_convergence_contract_horizon",
  "bind_convergence_runtime_dependencies",
]
