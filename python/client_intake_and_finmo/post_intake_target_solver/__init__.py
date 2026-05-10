"""Phase 9 P3 — Target-driven restoration loop.

Replaces the silo'd cascade adaptation that lived in
post_intake_solver.orchestrator._remediate_realism_hard_fails. The new
loop iterates 4 solver targets in priority order, allocating each
target's per-quarter delta across operating-side drivers proportional
to slack-to-bound. Cash strategy continues to own financing levers
(Owner's Capital, Other Equity, Distributions, Short Term Debt %, Debt
Issuance, Debt Repayment) end-to-end and runs after this loop.

Targets, in priority order:
  1. gross_margin_percent
  2. ebitda_margin
  3. current_assets_minus_cash
  4. current_liabilities_to_revenue

Iteration discipline (strict, per Phase 9 P3 directive):
  Inner loop (per target): up to 10 iterations until either (a) target
    metric within tolerance at every quarter, OR (b) every driver is
    pinned at its bound in the needed direction.
  Outer loop (across targets): up to 5 passes until either (a) viability
    conditions all satisfied, OR (b) every operating driver across all
    4 targets is pinned at its bound.
  Worst-case walk before claiming infeasibility: 4 × 10 × 5 = 200
    iterations of sub-second algebra.

`exhausted` is returned ONLY when every operating driver in every
target's driver list is pinned at its bound AND viability is still
failing. Lesser conditions iterate further.

The solver itself is deterministic algebra — it does NOT consume any
GPT calls. The 4-call GPT cap from Phase H is preserved by:
  - Cash strategy review (post-restoration) — unchanged
  - Path engine ramp generation — consumed but not invoked here
  - Intake / narrative — untouched
  - The new solver's allocation + iteration logic — pure deterministic
    Python.
"""

from client_intake_and_finmo.post_intake_target_solver.target_solver import (
  CashPassLeverViolation,
  DriverBound,
  SolverResult,
  SolverStatus,
  solve_for_target,
)
from client_intake_and_finmo.post_intake_target_solver.restoration_loop import (
  RestorationResult,
  RestorationStatus,
  TARGETS_IN_PRIORITY_ORDER,
  run_restoration_loop,
)

__all__ = [
  "CashPassLeverViolation",
  "DriverBound",
  "RestorationResult",
  "RestorationStatus",
  "SolverResult",
  "SolverStatus",
  "TARGETS_IN_PRIORITY_ORDER",
  "run_restoration_loop",
  "solve_for_target",
]
