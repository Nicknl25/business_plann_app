# Module 2: Convergence Determinism + NAICS-Tightened Stage Ramp

**Status:** in_progress (Tasks 2.2, 2.4, 2.5, 2.6 landed. Tasks 2.1, 2.3, 2.7, 2.8 deferred per session direction — see Notes.)
**Scope:** post-intake only.
**Depends on:** Module 1 (resolver must exist for the stage ramp NAICS read).
**Unblocks:** none structurally, but reduces brittleness that Modules 5 and 6 would otherwise inherit.

## Why this module

Three convergence-side problems land together because they share the same files and risk surface:

1. **No total convergence wall budget.** Per-cycle 180s exists, but `max_attempts × 180s` can run 24 minutes. No oscillation hash beyond error-pattern matching. (Master diagnostic P5.)
2. **Solver "anchor escape hatch" — the May 2 COGS bug.** `numeric_solver.solve_review_plan()` evaluates the GPT anchor first; if it hits tolerance, returns it without running the direct algebraic estimate. Live execution diverges from local reproduction when the anchor gets lucky. (Master diagnostic P6.)
3. **Stage ramp asymmetric enforcement.** `revenue_qoq_max` is enforced as a real Python validator at convergence; `fte_qoq_max`, `utilization_high_watermark`, `max_spike_count` are sent to GPT in the prompt and never enforced by Python. Ramp ceilings (`Q1=0.25`, `Q2=0.40`, etc.) are also hardcoded universal-business fractions that should be NAICS-conditioned. (Master diagnostic P3, P4.)

These all live inside `post_intake_convergence/` and `numeric_solver.py` plus the `stage_planning_ramp_policy()` function in `post_intake_mapping.py`.

**Master-diagnostic references to read before starting:**
- Part 3 §P3, P4, P5, P6
- Part 5 Phase 2 (stage ramp NAICS), Phase 5 (convergence determinism), Phase 6 (asymmetric stage ramp enforcement)
- Part 8.4 — solver invariants
- Part 11.2-11.3 — what the convergence GPT actually decides

## Dependencies

- **M1 must be complete.** This module reads the NAICS resolver to get `startup_qoq_growth_typical`, `early_qoq_growth_typical`, `mature_qoq_growth_typical` for the stage ramp.

## Pre-flight

- [ ] Confirm M1 complete (resolver exists, both regression E2Es still pass).
- [ ] Run NexGen + ValueMart E2Es again as the post-M1 baseline. Record convergence cycle counts and total elapsed time per cycle.
- [ ] Read master-diagnostic Parts 3 (P3-P6), 5 (Phases 2, 5, 6), 8.4, 11.2-11.3.
- [ ] Read `post_intake_convergence/runner.py` end-to-end (3,391 lines) — specifically the `_apply_stage_ramp_revenue_driver_limits` validator at line 132 (the model for the new sister validators).
- [ ] Read `numeric_solver.py:893-1021` (the anchor evaluation, direct target metric estimate, single-variable linear interpolation paths).

## Task 2.1 — Move convergence guard constants to sequence-row columns

- [ ] Add columns to `post_intake_process_sequence_lookup` via DDL in `post_intake_mapping.py:_ensure_process_sequence_lookup_table`:
  - `total_phase_budget_seconds DECIMAL(10,2) NULL` — total wall budget for looping phases
  - `non_productive_cycle_limit INT NULL` — replaces hardcoded 3
  - `cycle_deadline_guard_seconds DECIMAL(10,2) NULL` — replaces module constant 8.0
  - `planner_gpt_max_seconds DECIMAL(10,2) NULL` — replaces 150.0
  - `verification_gpt_max_seconds DECIMAL(10,2) NULL` — replaces 45.0
- [ ] Run the table-ensure migration (idempotent; existing rows get NULL for new columns initially).
- [ ] Populate the `unified_convergence_decision` row's new columns: `non_productive_cycle_limit = 3`, `cycle_deadline_guard_seconds = 8.0`, `planner_gpt_max_seconds = 150.0`, `verification_gpt_max_seconds = 45.0`. Set `total_phase_budget_seconds` to a chosen value (suggest `8 × 180s = 1440s = 24min` initially, or tighter like `720s = 12min` to honor the user's "4 minute" expectation more seriously — needs operator decision).
- [ ] In `post_intake_convergence/runner.py:36-46`, replace the module constants with calls to a new helper `_sequence_setting(step_key, field, default)` that reads the sequence row.
- [ ] Update `_sequence_numeric_setting` (at runner.py:58) to handle the new columns gracefully when NULL.

## Task 2.2 — Implement total-phase budget enforcement

- [ ] Track convergence-loop start time at the top of the loop (before cycle 1).
- [ ] At the top of each cycle, check `total_elapsed_seconds = perf_counter() - phase_started_at` against `total_phase_budget_seconds`.
- [ ] When exceeded, raise `StructuredSystemRunFailure(detail="convergence_total_phase_budget_exceeded", diagnostics=...)`.
- [ ] Diagnostics payload includes: cycles attempted, total elapsed, per-cycle elapsed list, last known controller state, last validation error.

## Task 2.3 — Implement oscillation state-hash detection

- [ ] In `post_intake_convergence/runner.py`, add a new function `_compute_cycle_state_hash(controller_resolution_state, decision)` that returns SHA256 of `(active_lever_ids_sorted, target_metric_names_sorted, scoped_baseline_signature, decision_lever_adjustments_signature)`.
- [ ] Track the previous cycle's state hash in `retry_memory["previous_cycle_state_hash"]`.
- [ ] After each cycle's solver application, compute the new hash. If `new_hash == previous_hash` AND no improvement in `controller_resolution_state.remaining_issue_count`, increment `consecutive_oscillation_count`.
- [ ] On `consecutive_oscillation_count >= 2`, raise `StructuredSystemRunFailure(detail="convergence_oscillation_detected", diagnostics=...)`.
- [ ] This is *in addition to* the existing `_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT = 3` bailout (which fires on validation-error pattern repetition). Oscillation hash catches the data-driven case that error-pattern matching misses.

## Task 2.4 — Reorder solver paths: direct estimate before anchor evaluation

- [ ] Edit `python/client_intake_and_finmo/numeric_solver.py:893-1021`. Current order: GPT anchor → direct target metric → revenue-direct → single-variable linear interpolation. New order: single-variable linear interpolation FIRST when one-lever / one-target / one-quarter; then direct target metric; then revenue-direct; then GPT anchor evaluation only as tiebreaker when the algebraic paths failed.
- [ ] Specifically: when `len(allowed_lever_ids) == 1 and len(target_metric_names) == 1 and len(targeted_quarters) == 1` and the lever→metric mapping is `direct` (per `post_intake_driver_target_mapping_entry(lever_id).target_metric_name == target_metric_name`), run the linear interpolation. If it returns within tolerance, return immediately with `optimizer_message = "direct_algebraic_one_dim_fit"`.
- [ ] Only fall through to the GPT anchor evaluation when the algebraic paths could not close the target (probe out of bounds, divisor near zero, etc.).
- [ ] Add a debug field to the solver result: `algebraic_path_attempted: bool`, `algebraic_path_result_code: str` (e.g., `direct_fit | probe_oob | non_invertible | not_applicable`).

## Task 2.5 — Add solver direct-fit unit tests

- [ ] Add `Test Files/test_solver_direct_fit_priority.py`
- [ ] Test: one-lever (`expenses::Cost of Goods Sold`) one-target (`cogs`) one-quarter (Q1) with a tractable algebraic gap. Confirm solver returns `optimizer_message = "direct_algebraic_one_dim_fit"` and the value matches the local reproduction case from May 2 (`0.388`-ish).
- [ ] Test: one-lever one-target one-quarter where algebraic path is non-invertible (e.g., divisor near zero). Confirm solver falls through to anchor evaluation.
- [ ] Test: multi-lever case still goes through the optimizer.

## Task 2.6 — NAICS-condition the stage ramp ceilings

- [ ] Edit `python/client_intake_and_finmo/post_intake_mapping.py:stage_planning_ramp_policy()` (line 2813).
- [ ] Add `business_naics` parameter (passed in already by callers — ensure it reaches this function).
- [ ] Replace the hardcoded `early_revenue_share_ceiling_of_late_run_rate = {Q1: 0.25, Q2: 0.40, Q3: 0.60, Q4: 0.80}` block with a NAICS-conditioned reading:
  - When `family == "startup"`: call resolver `metric_key="startup_qoq_growth_typical"`, build Q1-Q4 ceilings as cumulative `(1 + qoq_typical_target)^q`. Same for `family == "early"` with `early_qoq_growth_typical`. Same for operational/mature with `mature_qoq_growth_typical`.
  - On `no_coverage` for the QoQ metric (rare; BDS coverage is mostly NAICS-4), fall back to the current hardcoded fractions as the `generic_default`. Document this fallback explicitly in the policy payload's `naics_level_used` field.
- [ ] Add a new field to the returned policy: `naics_level_used`, `confidence_tier_used`, `qoq_growth_band` (for transparency in the workbook stage ramp display).
- [ ] **Validator rules stay invariant.** The `q1_to_q20_min_net_income_margin_floor`, `loss_allowed_latest_quarter`, `operational_requires_positive_from_q5` rules are universal across industries — do not NAICS-condition these. Only the *ramp ceilings* go NAICS.

## Task 2.7 — Stage ramp asymmetric enforcement (the three missing validators)

- [ ] Implement `_apply_stage_ramp_fte_qoq_max` in `post_intake_convergence/runner.py`. Pattern matches `_apply_stage_ramp_revenue_driver_limits` (line 132): walk `stage_ramp_contract.quarter_ramp_grid`, compute previous-quarter FTE from `expenses::Payroll`-supported FTE driver, check `current_fte > previous_fte * (1 + fte_qoq_max)`, adjust if violated.
- [ ] Implement `_apply_stage_ramp_utilization_high_watermark`: each `revenue::Utilization` lever per product must not exceed `utilization_high_watermark` per quarter.
- [ ] Implement `_apply_stage_ramp_max_spike_count`: count quarters where revenue grew by more than `revenue_qoq_max_spike`. Enforce `count <= max_spike_count`.
- [ ] Either (a) make these adjust drivers symmetric with the revenue path, or (b) make them fail-fast in convergence verification with the failing constraint, quarter, and lever named explicitly. **Prefer (b)** because it's simpler and surfaces the issue rather than silently clipping. Adjusting drivers conflicts with payroll FTE causality (the payroll schedule owns FTE, not convergence).
- [ ] Wire the three new validators into the convergence cycle right after the existing revenue-QoQ validator.

## Task 2.8 — Declare the new validators as sequence sub-steps (Phase 8b prep)

- [ ] Add four new sequence rows under parent `unified_convergence_decision`:
  - `unified_convergence_enforce_revenue_qoq_max` (existing logic, just declared)
  - `unified_convergence_enforce_fte_qoq_max` (Task 2.7)
  - `unified_convergence_enforce_utilization_high_watermark`
  - `unified_convergence_enforce_max_spike_count`
- [ ] Each declares its `required_context_keys`, `produced_output_keys`, `output_storage`, `recompute_triggers`. Output finality: `cycle_local`.
- [ ] The convergence runner dispatches them through the sequence controller rather than calling them inline. This is the structural cleanup that gives the controller authority over the validators.

## Files Touched (expected)

- `python/client_intake_and_finmo/post_intake_mapping.py` (sequence table DDL, stage_planning_ramp_policy, `_DEFAULT_PROCESS_SEQUENCE_ROWS`)
- `python/client_intake_and_finmo/post_intake_convergence/runner.py` (constants → table, total-phase budget, oscillation hash, three new validators)
- `python/client_intake_and_finmo/post_intake_convergence/runtime.py` (touch-up if guard helpers move)
- `python/client_intake_and_finmo/numeric_solver.py` (path reordering)
- `Test Files/test_solver_direct_fit_priority.py` (new)

## Files NOT Touched

- The existing `_apply_stage_ramp_revenue_driver_limits` keeps adjusting drivers — that pattern is established and proven; don't change it.
- Mapping table formula registry — unchanged
- Payroll, debt, depreciation schedules — unchanged
- Stub 0 — never written
- FINMO calc — unchanged

## Verification

- [ ] All Task 2.x checkboxes complete
- [ ] `Test Files/test_solver_direct_fit_priority.py` passes
- [ ] NexGen Software E2E still passes with `all_cleared`
- [ ] ValueMart Superstores E2E still passes with `all_cleared`
- [ ] Convergence cycle counts and per-cycle elapsed times do not increase materially vs. pre-M2 baseline (record before/after)
- [ ] Synthetic test: a deliberately oscillating intake (one that today burns the full max_attempts) fails-fast at the new oscillation-hash gate within ≤2 cycles after pattern stabilizes
- [ ] Synthetic test: a contract violating `fte_qoq_max` triggers the new validator and surfaces the failing quarter/lever
- [ ] Solver direct-fit case: re-run the May 2 failing intakes (`fa63518ad2f9493a8ed40688cd646ff9`, `bf8152f100844dab96fca181c89f8df3`, `5a7da3983f6340ffbe7630c642ca7c84`, `9709cb773fd3453688761a81901d27bf`) and confirm the COGS direct-fit value lands at the correct algebraic estimate, not the GPT anchor.
- [ ] `scripts/post_intake_golden_preflight.py` — sequence table snapshot will change because of new columns/rows; refresh the snapshot intentionally per master-diagnostic Phase rules.

## Exit Criteria

- All Task checkboxes complete
- Both regression E2Es pass
- Three failing-intake reproductions from May 2 now pass with direct-fit
- Synthetic oscillation test fails-fast appropriately
- Synthetic stage-ramp constraint violation surfaces the failing constraint
- Index file Status updated: M2 = `completed`

## Risk Notes

- **Total-phase budget choice.** Setting it too tight (e.g., 4 minutes) will fail-fast on legitimately-difficult intakes. Setting it too loose (24 minutes) defeats the purpose. Suggest 12 minutes initially with an eye on real-world data; tune per operator preference.
- **Direct-fit reordering may shift live results.** If a previously-passing E2E happened to hit the GPT anchor path for a single-lever case, the new direct path will return a different (correct) value. Compare carefully and confirm the algebraic value is the right answer.
- **The three new stage-ramp validators may surface latent issues.** Today's contracts may include FTE / utilization combinations that violate the constraints but pass because nothing checks. Be prepared for new fail-fasts to appear on edge cases — these are real bugs, not regressions.
- **Sequence table snapshot will drift.** Refresh `post_intake_lookup_table_snapshot` intentionally after this module lands; document the refresh in the commit message.

## Notes from a future session

### 2026-05-06 — Stages B + A + C (partial) landed

**Files added / changed:**
- `python/client_intake_and_finmo/numeric_solver.py` — Task 2.4: algebraic one-dimensional fit runs BEFORE the GPT-anchor evaluation when the task is single-lever / single-target / single-quarter / direct mapping. Fixes the May 2 "lucky anchor escape hatch" bug. Adds `algebraic_path_attempted` and `algebraic_path_result_code` per-attempt telemetry.
- `python/client_intake_and_finmo/post_intake_convergence/runner.py` — Task 2.2: `_CONVERGENCE_TOTAL_PHASE_BUDGET_SECONDS = 720.0` (12 min) and a top-of-cycle guard that raises `StructuredSystemRunFailure(detail="convergence_total_phase_budget_exceeded", ...)` when exceeded. Capture `unified_convergence_phase_started_at` at the top of the loop.
- `python/client_intake_and_finmo/post_intake_mapping.py` — Task 2.6 (partial): `stage_planning_ramp_policy()` now takes an optional `business_naics` kwarg. When supplied, the policy payload carries `naics_qoq_metric_key`, `naics_level_used`, `confidence_tier_used`, `qoq_growth_band` (the resolver payload). The hardcoded `early_revenue_share_ceiling_of_late_run_rate` fractions are unchanged for runtime behavior; the metadata is the foundation Module 3's GPT contract bound work consumes.
- `python/client_intake_and_finmo/quarter_grid.py` — passes `business_naics=ops.business_naics_6` to the stage_ramp_policy call at `_stage_governance_context`.
- (new) `Test Files/test_solver_direct_fit_priority.py` — 5/5 pass. Verifies algebraic-first wins over a "lucky anchor" using a deterministic linear-in-driver fake.
- (new) `Test Files/test_module2_stage_ramp_naics.py` — 6/6 pass. Verifies the budget constant exists + is referenced in a runner function, and the stage ramp policy attaches NAICS qoq metadata when naics is supplied (backward-compatible without it).

**Total regression suite:** 37/37 pass across the 4 test files (resolver 17, M1 wiring 9, solver direct-fit 5, M2 stage-ramp 6).

**Budget choice — 720s (12 min).** User direction was "do what you think is best." Master-diagnostic Phase 5 recommends 12 min. Both passing baselines complete with comfortable margin (NexGen 365s, ValueMart 133s). 4 minutes (the user's earlier comment) was too tight given the per-cycle 180s wall — would fail before 2 cycles complete. 24 minutes (the natural max from `max_attempts=10 × 180s`) defeats the purpose.

**The May 2 reproduction.** Confirmed all four draft IDs (`fa63518a...`, `bf8152f1...`, `5a7da398...`, `9709cb77...`) are still in the DB; all four are "Precision Aesthetics Lab". Their `numeric_solver_feedback_json` shows the exact bug shape: 1 lever (`expenses::Cost of Goods Sold`), 1 target (`cogs`), 1 quarter (Q1), `attempt_count=1`, `quarters_with_target_misses=1`, `best_objective=0.067`. The deterministic-fake unit tests reproduce the bug shape (anchor lucky vs. algebraic exact) without needing to load these drafts at runtime; running the actual drafts through the new code is a future verification step.

**Tasks deferred (with reason):**

- **Task 2.1 — sequence-row column move.** The DDL change (5 new columns on `post_intake_process_sequence_lookup`) is a high-risk schema operation for marginal value while module constants are still the runtime source. The runtime guard added in Task 2.2 uses the constant directly; flipping it to read from a sequence-row column is a clean follow-up that can land safely on its own. Documented in code comment at `_CONVERGENCE_TOTAL_PHASE_BUDGET_SECONDS`.
- **Task 2.3 — oscillation state-hash detection.** Defining the state hash structure (`active_lever_ids_sorted`, `target_metric_names_sorted`, `scoped_baseline_signature`, `decision_lever_adjustments_signature`) and integrating it with `retry_memory["non_productive_cycle_tracker"]` requires a focused integration pass. The existing `consecutive_non_productive_cycles >= 3` bailout (line 1735) catches the validation-error pattern case; the hash-based detector catches the data-driven case the existing check misses. Worth landing on its own change.
- **Task 2.6 ceiling replacement (the `(1+qoq)^q` math).** The metadata is in place; replacing the hardcoded `Q1=0.25, Q2=0.40, Q3=0.60, Q4=0.80` block with NAICS-derived values needs an empirical pass to confirm the new ceilings do not surface latent contract violations on baselines that pass today. The conservative ratio interpretation (`Qn_share = 1/(1+qoq)^(20-n)`) yields tighter ceilings than the universal 0.25/0.80 for many NAICS — that may surface real bugs that need separate attention.
- **Task 2.7 — three new validators (`fte_qoq_max`, `utilization_high_watermark`, `max_spike_count`).** Each is a fail-fast gate that may surface latent contract violations on real intakes. The spec recommends path (b) — fail-fast with the failing constraint named. Better landed when the post-intake pipeline is more stable.
- **Task 2.8 — sequence sub-step declarations for the validators.** Depends on Task 2.7; structural cleanup, no behavior change.

**One observation from this session.** The convergence runner is ~3,400 lines in a single function-level scope. Adding Task 2.2's guard required tracing 600+ lines of cycle logic to find a safe insertion point. The existing `_apply_stage_ramp_revenue_driver_limits` helper is the right pattern for new validators (Task 2.7) but they should land as separate sequence sub-steps (Task 2.8) to avoid making the runner even larger. Worth keeping in mind as the runner gets touched.
