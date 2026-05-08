# Phase 8 Tolerance Softening Audit

The Phase 8 transition softened several legacy fail-fasts so the
post-deletion pipeline could complete and the acceptance gate could
render its verdict. This audit lists each softening, the legacy
behavior, the Phase 8 behavior, and what real bug each softening could
mask. Every entry should be revisited once the orchestrator-driven
pipeline has been hardened (Phase 9+).

Audit principle: a softening is acceptable when (a) the gate's checks
cover the same ground, OR (b) the legacy fail-fast was guarding a
contract the new architecture has replaced. A softening is risky when
neither is true and we relied on it to land Phase 8.

## 1. Revenue formula validator — $0.015 absolute tolerance

**File:** [python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py:1346-1361](../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1346)
**Commit:** `48a83f7`
**Legacy:** `round(expected, 2) != round(actual, 2)` (zero tolerance after rounding to cents)
**Phase 8:** `abs(expected_raw - actual_raw) > 0.015` (compare unrounded)

**Why it broke:** Sunny's bundle drivers produce
`39797.15 * 2.0 * 0.75 = 59695.72500000001`, which rounds to 59695.73 in one
multiplication path and 59695.72 in another (banker's rounding). The
legacy zero-tolerance check false-flagged this 0.5e-12 FP drift as a
revenue formula violation.

**Real bug it could mask:** A revenue computation actually computing
revenue from operator-stated values (e.g., financials_year1 directly)
instead of `Capacity × Unit Price × Utilization`. That kind of bug
would produce dollar-level mismatches, well above the $0.015
threshold.

**Risk: low.** Real divergence is dollars, not sub-cents.

## 2. Payroll-integer schedule validator — $1.00 tolerance

**File:** [python/client_intake_and_finmo/post_intake_headcount/lookup.py:929,1086-1093](../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L1086)
**Commits:** `dcc5814`, `4ee795d`
**Legacy:** `abs(number - round(number)) > 0` (exact integer required)
**Phase 8:** `abs(number - round(number)) > 1.0` (allow $1.00 drift)

**Why it broke:** Cash-pass debt-service application introduces
multi-cent drift across quarters when interest accrual is divided by
quarter; the legacy GPT loop's authority reapplication used to re-snap
totals to integer cents. Until that snap is rebuilt in the new
architecture, the $1 tolerance prevents false-flag failures on $0.01-
$0.50 drift.

**Real bug it could mask:** A schedule corruption where a payroll cell
is off by, say, $50 (a quarter's worth of an off-by-one calculation).
That would be silently accepted with this tolerance.

**Risk: medium.** $1 is too loose. Should tighten to ~$0.10 once the
new architecture has its own authority-snap. Tracked as Phase 9 cleanup.

## 3. Convergence runner's `post_convergence_pre_cash` validator — downgraded to warning

**File:** [python/client_intake_and_finmo/post_intake_convergence/runner.py:2511-2553](../python/client_intake_and_finmo/post_intake_convergence/runner.py#L2511)
**Commit:** `ec4fc8f`
**Legacy:** Hard-fail `_assert_global_invariants_via_sequence(stage="post_convergence_pre_cash")`
**Phase 8:** Try/except, log violation to `process_sequence_trace.phase_8_post_convergence_validator_warnings`, continue

**Why it broke:** With the convergence GPT loop short-circuited
(Phase 8 path), the legacy validator catches a model_input/FINMO
divergence that the GPT loop's authority reapplication used to
reconcile (Phase 7.1 capacity-driven revenue overrides operator
baseline; FINMO is built from financials_year1 while model_input
keeps the baseline Capacity).

**Real bug it could mask:** Genuine model corruption between the
quarter-grid and convergence stages.

**Risk: medium.** Only fires on the Phase 8 short-circuit path; the
non-Phase-8 path is unaffected. Should be replaced with an
orchestrator-level invariants check that operates on the post-cascade
state once the orchestrator owns the full pipeline.

**Note:** This validator's call site is now never reached because
commit `b7f859c` bypassed the convergence runner entirely. Effectively
dead code; will be removed when the convergence runner is itself
deleted in a follow-up phase.

## 4. Finalize validator — downgraded to warning on Phase 8 path

**File:** [python/client_intake_and_finmo/post_intake_solver/orchestrator.py](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py) `_run_post_cascade_completion`
**Commit:** `f1d5b8c`
**Legacy:** `run_finalize_post_intake_validation` raises `RuntimeError` if any of
its sub-validators (global invariants, cash buffer, revenue formula
reconcile, etc.) accumulate errors.
**Phase 8:** Wrapped in try/except. The orchestrator calls
`assert_solver_respected_targets` directly first (capturing
solver_target_assertion regardless of finalize's outcome), then runs
finalize as best-effort. A raised RuntimeError is recorded on
`post_cascade_completion.finalize_validation` but doesn't block the
pipeline.

**Why it broke:** The same model_input/FINMO divergence as #3, plus
cash buffer violations from the minimal cash strategy not perfectly
matching the legacy SQL cash policy.

**Real bug it could mask:** Any of the hard validations finalize
performs (debt schedule reconciliation, payroll schedule reconciliation,
forecast horizon completeness, etc.).

**Risk: high.** This is the largest softening. The acceptance gate's
checks cover *some* of finalize's ground (revenue trajectory, cash
legitimacy, current assets) but not all (e.g., debt schedule reconciliation).
A real debt-schedule corruption could pass the gate while finalize
silently records a warning.

**Mitigation:** The acceptance gate's `solver_target_assertion_no_hard_violations`
check catches solver-side violations directly, and the realism gate's
per-metric provenance covers band coverage. The unchecked surface is
schedule reconciliation specifically; this is a known gap until the
orchestrator owns its own schedule reconciliation.

## 5. Realism gate exception swallowing — fixed in P1

**File:** [python/client_intake_and_finmo/post_intake_solver/orchestrator.py](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py) `_run_post_cascade_completion`
**Commit:** `e7a422b`
**Status:** This was a bug, not a softening. The catch-all `except Exception`
caught `RealismBandViolation` and lost the partial results. P1 fix
catches the violation specifically and unpacks `exc.results` into the
realism_memo. **No tolerance change; bug fix only.**

## 6. The unit_price ramp — Phase 7 curation replacement

**File:** [python/client_intake_and_finmo/post_intake_solver/orchestrator.py](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py) `_run_post_cascade_completion`
**Commits:** `b0b1b90`, `e26c6c5`
**Status:** Not a softening — a deterministic Phase-7-equivalent. The
1% per-quarter unit_price ramp produces the same ~1% growth pattern
that Phase 7's curation produced from operator context.

**Concern:** The 1% rate is hardcoded and not derived from any
business-specific signal. For very mature businesses (zero growth) or
high-growth startups, this would be wrong in opposite directions.
Should be replaced with a business-context-aware ramp (operator
growth assumption from financials_year1, or NAICS-cohort growth rate)
in a follow-up.

**Risk: low.** Sunny / NexGen / ExpressLogix are all small-business
intakes where 1% quarterly growth is plausible.

## Summary of risk

| Softening | Risk | Phase 9 priority |
|---|---|---|
| 1 — Revenue formula $0.015 tol | low | low |
| 2 — Payroll integer $1.00 tol | medium | medium (tighten to $0.10) |
| 3 — post_convergence_pre_cash warn | dead code | low (removed when convergence runner deleted) |
| 4 — finalize warn | high | high (schedule reconciliation surface unchecked) |
| 5 — realism exception | n/a | n/a (was a bug, fixed) |
| 6 — unit_price ramp | low | medium (should be business-context-aware) |

The high-risk item is #4 — finalize's schedule reconciliation surface
is unchecked under Phase 8. The acceptance gate covers the customer-
visible plan integrity (revenue / cash / current assets / realism /
solver targets) but not the internal schedule consistency. A Phase 9
follow-up should add gate checks for debt schedule + payroll schedule
+ forecast horizon completeness against the persisted state.
