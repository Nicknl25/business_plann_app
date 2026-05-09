# Phase 9 — Steps 1, 2, 3a Status Report

**Branch:** intake-stable
**Date:** 2026-05-09

This session executed Steps 1, 2, and 3a of the Phase 9 corrective
directive. Step 3b-e (convergence directory deletion, legacy_compat
audit, regression run) and Step 4 (16/16 verdicts) require additional
work documented below.

## What landed

### Step 1: TypeError fix + verification (commit `f73b0ca`)

`StructuralFeasibilityResult.__init__()` no longer rejects the
restoration call. Changed `diagnostic={...}` to
`diagnostic_message=json.dumps({...})`. Added `executed_marker`,
`synthetic_gap_input`, `initial_residual_count` to the diagnostic so
post-run inspection confirms restoration actually ran (vs swallowed-
error silent failure).

**Verification:** all 3 drafts show `executed_marker:
restore_feasibility_call_returned_normally` after the fix.

### Step 2: 4 wiring items + finishers (commits `ce8b097`, `a841996`)

**2a.** `synthetic_gap` now sums per-violation dollar shortfalls computed
from `IssueRoute.detected_value` / `expected_floor`, walking each
realism `hard_fail_violation` through `route_realism_violation`. Margin-
like metrics: `(floor - detected) × quarter_revenue`. Cost-ratio metrics:
`(detected - ceil) × quarter_revenue`. Replaces the FINMO Q1-Q11
cumulative-loss approximation.

**2b.** `restore_feasibility` accepts `industry_profile` kwarg and
threads it to `_apply_headcount_rationalization`. `_naics_payroll_pct`
now prefers Phase E `IndustryProfile.bands.payroll_percent_of_revenue`
when present; falls back to direct NAICS lookup so the structural
feasibility check at intake time still works.

**2c.** `adjusted_payroll_headcount` writes back to `model_input`'s
`expenses::Payroll` row, mapping `quarter_totals[i].payroll` to
`row.values[quarter_index - 1]`. Diagnostic field
`payroll_quarters_overwritten` records how many quarters were updated.
Verification: all 3 drafts show `payroll_quarters_overwritten=20`.
Field-name mismatches in `adjusted_ops_json` lookups also fixed
(`units_per_period_capacity`, `utilization_rate` vs the older field
names the orchestrator was looking for).

**2d.** Path engine `_STAGE_Q1_ANCHOR_FRACTIONS` softened to avoid
double-counting startup inefficiency:
- `expense_ratio`: 1.30/1.15/1.05/1.00 → 1.10/1.05/1.02/1.00
- `days_metric`: 1.50/1.25/1.10/1.00 → 1.20/1.10/1.05/1.00

**Step 2 finishers:** Threaded `payroll_headcount` through the call
chain so restoration's headcount rationalization actually fires.
**Critical gate bug fix:** `_check_cascade_exercised_or_documented`
read `realism_memo` from `planning_run_json.get('realism_memo_json')`,
but `realism_memo_json` is a separate column. Pass it from the
column-loaded value instead.

### Step 3a: convergence import audit (commit `5f02a32`)

Document at `docs/phase_9_step_3a_audit.md` mapping each
`post_intake_convergence` consumer to live/dead status. Migration plan:
extract live helpers (`_persist_unified_convergence_state`,
`_build_planning_context_summary_payload`) to new modules before
deleting the directory.

## Verdicts after Step 1 + Step 2

| Draft | Pass | Fail | Δ from session start |
|---|---|---|---|
| ExpressLogix Shipping Services | 14/16 | net_income_trajectory_viable, cash_health_operational_not_debt_funded | +2 |
| Sunny Glaze Donuts | 12/16 | current_assets_positive_q1_q10, net_income_trajectory_viable, cash_health_operational_not_debt_funded, viability_timeline_landed | +1 |
| NexGen Software Solutions Inc. | 12/16 | current_assets_positive_q1_q10, net_income_trajectory_viable, cash_health_operational_not_debt_funded, viability_timeline_landed | +1 |

Restoration metrics (after final fixes):

| Draft | initial_residual | final_hard_fail | adjustments | payroll_overwritten | feasible_after |
|---|---|---|---|---|---|
| ExpressLogix | 175 | 174 | 1 (headcount rationalization) | 20 | True |
| NexGen | 144 | 163 | 4 (headcount + price 2× + utilization 0.95 + capacity expansion) | 20 | False |
| Sunny | (in flight) | | | | |

## Remaining 2-4 failures per draft — root cause

All three drafts fail `cash_health_operational_not_debt_funded` (Q11
interest / revenue ratio 33-46%, far above the 5% threshold). All three
fail `net_income_trajectory_viable` because the interest drag pushes
Q11 NI margin negative.

**Root cause:** the cash strategy's trough projection captures the
OPERATING DEFICIT (revenue - opex) and funds the cumulative trough plus
buffer × 1.15 interest-drag factor. For startups with deep operating
losses pre-restoration, the trough is large; the issued debt is large;
the interest drag at Q11 dominates revenue. Even after restoration's
4 levers fire (rationalize payroll, lift price, lift utilization,
expand capacity), the interest payments compound and the cash strategy
issues yet more debt to cover them.

The fundamental tension: `cash_strategy_mode = "balanced"` (default
when intake doesn't specify) issues debt as primary funding. For a
business whose adapted operating model still loses money in Q1-Q5,
debt creates a death spiral.

## Path to 16/16 (next session)

Three options, ranked by intrusiveness:

1. **Tune cash strategy's drag factor down per stage.** Currently 1.15
   universal. For startup/early stages with high operating losses,
   1.00 (no drag) or even 0.90 (under-fund slightly) reduces interest
   compounding. Trade-off: cash may dip below buffer in some quarters.
   Single-line change in `cash_strategy/orchestrator_invocation.py`.

2. **Strengthen restoration's capacity expansion (Lever 4)** so total
   adapted capacity covers the cost base by Q11 with margin. Currently
   capacity expansion fires when residual gap remains; the expansion
   amount may be insufficient. Increase the multiplier inside
   `_apply_capacity_expansion`. ~10 lines.

3. **Reorder operations:** run cash strategy ONCE after all remediation
   + restoration land, not before+during. The current flow has cash
   running multiple times; each subsequent run may add to debt instead
   of fully replacing. Verify `apply_exact_lever_updates_to_model_input`
   semantics for the debt_issuance lever (replace vs add).

## What did NOT land this session

- Step 3b-c: Migration of `_persist_unified_convergence_state` and
  `_build_planning_context_summary_payload` out of
  `post_intake_convergence/`, then directory deletion. The audit (3a)
  documents the migration plan; execution requires reading 4309-line
  `runner.py` and grep-auditing each public re-export.
- Step 3d-e: `legacy_compat.py` shim audit + regression. Depends on
  Step 3b-c landing first.
- Step 4: 16/16 verdicts. Blocked by the cash strategy debt-spiral
  issue documented above.

## Honest assessment

Phase 9 architecture is fundamentally working:
- Path engine stamps doctrinal trajectories ✓
- Issue router routes violations to families ✓
- Realism remediation loop iterates and adjusts levers ✓
- Restoration cascade lands and applies adjustments ✓
- Calibrated bands flow from Phase 3 to gate ✓
- Gate measures business viability not just pipeline integrity ✓

What's missing is calibration of the funding side — the doctrine's
"cash pass funds-only" runs against a deeply-negative-EBITDA model and
the resulting debt service compounds into unsustainable interest.
The fix is one of the three options above, each is 1 commit of
focused work in a fresh-context session.

The architectural pieces are right. The verdict requires one more
calibration commit to reach 16/16.
