"""Post-intake convergence contract helpers.

The legacy ``runner.py`` / ``runtime.py`` GPT-loop machinery was deleted
in Phase 3 step 7. What remains in this package is the surviving
deterministic-helper surface that other parts of the post-intake
pipeline (cash strategy, contracts, state) still consume:

  - ``contracts.py``     — unified-convergence contract policy + validators
  - ``retry_scope.py``   — retry scope payload builders + numeric solver
                           contract subsetter (used by post_intake_contracts)

The new restructure protocol (``post_intake_amalgamated.protocol``) is the
GPT-driven authoring path going forward; integration into the orchestrator
is the subject of step 8 (separate commit).
"""

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

__all__ = [
  "build_unified_convergence_contract_policy",
  "build_retry_scope_payload",
  "decorate_retry_scope_payload",
  "evaluate_retry_improvement",
  "full_horizon_quarters",
  "full_horizon_retry_scope_mode",
  "retry_scope_lever_ids",
  "retry_scope_quarters",
  "subset_numeric_solver_contract",
  "unified_convergence_contract_constraints",
  "validate_unified_convergence_contract_horizon",
]
