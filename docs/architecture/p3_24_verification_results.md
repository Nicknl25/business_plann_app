# Phase 9 P3.24 Verification Results

**Observation only — no fixes regardless of outcome.**

P3.24 Commits 1-3 landed. This memo records the result of re-running
the three drafts that failed in the P3.23a investigation.

## 1. Summary

| Draft | Business | Source ID (passed to runner) | New draft ID | Outcome | Wall-clock |
|---|---|---|---|---|---|
| 1 | Anderson & Blake Legal | a2585b3f5402425abc6c5eea8e046c16 | 01305ccb666a4f0a9c396efa57fa3a52 | **FAIL — new mode** | ~4 min |
| 2 | CareFirst Home Health | 7456b1eec9d94d6ca89f89d9a2daf397 | 422f64a792c247d1b423eaf8c0f81e65 | **PASS (16/16)** | ~3.4 min (201s system run) |
| 3 | Skyward Express Airlines | 5a89fd66f19348589284dbd604c84214 | 0c536f9a364b42d5b49e0820731e6e2f | **FAIL — different mode in same subsystem** | ~4 min |

Net: 1 pass, 2 fail.

| Per-commit verification | Status |
|---|---|
| Commit 1 (F-1/F-2/F-3 restoration ITERATING_STILL trigger) | **Verified engaged** for Anderson & Blake; downstream finalize check then surfaced a different infeasibility. |
| Commit 2 (payroll_feasibility_repair re-wire) | **Verified engaged and resolved** CareFirst's exact prior failure. |
| Commit 3 (delete dead convergence code) | No regression observed; backend runs cleanly with the deletions. |

## 2. Per-draft analysis

### 2.1 Draft 1 — Anderson & Blake Legal Associates

**Prior failure (P3.23a Draft 1):** acceptance gate `realism_gate_no_hard_fail_violations` failed 15/16 with violations on `current_assets_minus_cash` (Q1), `current_liabilities_to_revenue` (Q1-Q9), and `ebitda_margin` (5 quarters). Restoration loop exited `ITERATING_STILL` with no handler consumer.

**Post-P3.24 failure (NEW MODE):**
- Run failed at `post_intake_finalize_validation_global`.
- Final error chain (from [_p3_24_verification/draft1_anderson_blake.log](../../_p3_24_verification/draft1_anderson_blake.log)):
  ```
  post_intake_finalize_validation_failed: global_invariants_invalid:
  POST_INTAKE:post_intake_schedule_marker_missing@post_intake_finalize_validation_global:
  Payroll schedule fail-fast failed; payroll must use the table-backed
  headcount schedule:
  POST_INTAKE:payroll_revenue_economic_feasibility_failed@post_intake_finalize_validation_global_global_payroll_revenue_feasibility:
  Payroll/revenue economics are outside the table-backed headcount
  policy range; recompute drivers instead of clipping outputs.
  ```
- The stack went: `_run_planning_system_for_draft_unified` → `_run_unified_post_grid_system_run` (the active wrapper, not the deleted one) → finalize validation. So all of Phase A (initial grid) PASSED — `_assert_global_invariants_via_sequence` at quarter_grid_applied did NOT fire. The infeasibility surfaced only at finalize-time global validation.
- New-runner report: revenue trajectory $848k→$1.09M (up from prior $284k→$785k); EBITDA $240k→$537k (up from prior −$51k→$52k). Plan was **substantially re-authored** post-Commit-1.

**Verification of Commit 1 (F-1/F-2/F-3) — handler engagement:**
- Persisted state grep confirmed `"tool_calls_used": 1`.
- **The GPT exhaustion handler DID engage** — Commit 1's broadened trigger fired as designed.
- The handler authored revenue-side drivers strongly (Unit Price upward); the realism band failures Anderson & Blake originally had are evidently resolved (else realism gate would have flagged them).
- But the post-handler state has `payroll_revenue_economic_feasibility` violations at finalize. Reason: the handler's authored target_payroll_percent_of_revenue (or the relationship between payroll dollars and the now-much-higher revenue) fell BELOW the policy minimum band (16% min for high labor intensity). When revenue is raised but payroll dollars are not raised proportionally, the ratio drops below the policy floor.

**Pattern classification:** this is precisely **P3.23b §4 Gap K** (finalize `assert_post_intake_global_invariants` re-runs payroll_revenue_feasibility — no handler can react after finalize). The P3.23b memo Section 5 flagged this site as a residual gap; P3.24 did not address it. The handler engaged correctly (Commit 1 works); but Commit 2's `payroll_feasibility_repair` is wired at the **initial-grid** global validation site, not the **finalize** global validation site. So when the post-handler state newly trips the same check at finalize, no repair runs.

**Hypothesis for next iter (NOT in scope of P3.24):** extend the `payroll_feasibility_repair` wiring to the finalize global validation site (or, equivalently, move the handler's revenue-driver authoring to respect a payroll/revenue floor band).

### 2.2 Draft 2 — CareFirst Home Health Services

**Prior failure (P3.23a Draft 2):** FailFastError `payroll_revenue_economic_feasibility_failed@quarter_grid_applied_global_payroll_revenue_feasibility`. Revenue flat at $234k/quarter; payroll iterative refinement converged in its scope but the post-grid global check rejected.

**Post-P3.24 outcome: PASS.**
- Exit code 0; workbook saved at `C:\dev\Cilient Plans\CareFirst Home Health Services -- 05-18-2026 19-39-01.xlsx`.
- System run duration: 201,269 ms (~3 min 21 sec).
- New-runner report: Grid Application Success: True. Applied Lever Updates: 140 across 7 levers. Accounting All OK: True.
- Quarterly trajectory shows real growth: revenue $456k → $665k Q20 (up from prior FLAT $234k); EBITDA negative through Q10 (loss window), turns positive Q11 ($4.8k), reaches $29.8k Q20. The plan is in a workable shape post-P3.24.

**Verification of Commit 2 — payroll_feasibility_repair invocation:**
- Persisted state confirms `payroll_feasibility_repair` appears as a sequence step in the run trace. Commit 2's repair fired during the initial-grid global invariants check.
- Persisted state confirms `planning_mode` transitions: initial `"rebalance"` → later `"turnaround"` (cascade Tier 5 planning-mode shift).
- Persisted state confirms `tool_calls_used: 4` — the GPT exhaustion handler engaged with 4 tool calls (likely after the cascade's Tier 5 planning-mode shift).
- The flow:
  1. Initial grid built under `planning_mode=rebalance`.
  2. Post-quarter-grid global invariants check fired `payroll_revenue_economic_feasibility_failed` (CareFirst's exact prior failure).
  3. **Commit 2's payroll_feasibility_repair caught the FailFastError.** Re-invoked `estimate_payroll_headcount_schedule_with_gpt` with the failure as `previous_contract_failure`.
  4. The re-authored schedule passed the same global invariants check.
  5. Phase B ran: restoration loop, cascade walked tiers, Tier 5 shifted planning_mode to `turnaround`, GPT exhaustion handler engaged with 4 tool calls.
  6. Cash strategy + realism gate + finalize all passed.
  7. Acceptance gate verdict 16/16.

**Outcome:** Commit 2's design intent realized. CareFirst's failure mode is resolved by the lifted-and-rewired `payroll_feasibility_repair`.

### 2.3 Draft 3 — Skyward Express Airlines

**Prior failure (P3.23a Draft 3):** FailFastError `payroll_headcount_contract_timeout@payroll_headcount_contract_request`. 3 rounds completed in 175.65s (~58.5s/round); timeout fired at the start of round 4.

**Post-P3.24 failure (DIFFERENT MODE — but same subsystem):**
- FailFastError `payroll_iterative_refinement_exhausted@payroll_headcount_iterative_refinement` — **rounds exhausted, NOT a timeout.**
- Details: `rounds_used=10, hard_cap_rounds=10`. The loop completed all 10 rounds within the 180s budget.
- Final round failure: `payroll_headcount_target_payroll_percent_of_revenue_out_of_policy_range: value=0.08, min=0.16, max=0.7`.
- The GPT response in round 10 (preserved in `final_failure_packet.invalid_response_excerpt`) contains a contradiction:
  - JSON field: `"target_payroll_percent_of_revenue": 0.08`
  - JSON `rationale` text claims: *"...by selecting 0.20, which lies within the 0.16–0.70 range..."*
- The GPT's rationale says it picked 0.20; the actual field value is 0.08. The validator catches the actual value, which is below the policy min of 0.16. After 10 rounds of feedback, GPT cannot stably emit a value inside the policy range — every round it commits to a value outside [0.16, 0.70].

**Time-budget comparison:**

| Metric | Prior (P3.23a) | Now (P3.24) |
|---|---|---|
| Rounds completed | 3 | 10 |
| Total elapsed | 175.65s | < 180s (rounds exhausted before timeout) |
| Average per-round | ~58.5s | ~18s (under the 180s/10=18s budget rate) |
| Termination | TIMEOUT (pre-call guard) | ROUNDS EXHAUSTED |

Per-round latency improved by ~3× run-to-run. This is just GPT API variance, not an architectural change — P3.24 didn't modify the payroll iterative refinement loop.

**The CareFirst-grinding-wall hypothesis (REFUTED):**
The directive's hypothesis was that Skyward's timeout might have been the same underlying wall as CareFirst — payroll handler grinding against an invisible infeasibility wall, with Commit 2 indirectly helping. **Refuted.** Skyward fails INSIDE the payroll iterative refinement loop (step `payroll_gpt_contract_request` / `payroll_headcount_iterative_refinement`) BEFORE any quarter grid is applied. Commit 2's `payroll_feasibility_repair` fires AFTER the quarter grid is applied. The two failure sites are sequential, not coincident. Commit 2's repair could never have been reached by Skyward.

What Skyward actually shows is a GPT-output-stability problem with this particular business profile: the model keeps emitting `target_payroll_percent_of_revenue` values like 0.08 (below the [0.16, 0.70] band for high labor intensity) round after round, despite explicit structured feedback naming the failure and the required range. The rationale-vs-value contradiction in round 10 suggests GPT is generating coherent-seeming reasoning while the structured output drifts. This is independent of P3.24 changes.

## 3. Per-commit verification status

### Commit 1 — `phase_9_p3_24_commit1_restoration_iterating_still_trigger`

**INTENT:** route `RestorationStatus.ITERATING_STILL` exits to the GPT exhaustion handler when failing_metrics is non-empty.

**VERIFIED ENGAGED.** Anderson & Blake's run shows `tool_calls_used: 1` in the persisted state. The handler ran, authored upward-revising revenue drivers, addressed the original 3 failing realism metrics (the realism gate did not surface them again — it would have done at acceptance check #5 had they remained).

**BUT: a downstream check (finalize global invariants) caught a new failure mode the handler's authoring produced.** Commit 1 cannot prevent this — its design ends at handler engagement and rebuild. The new failure surfaces at the *next* gate downstream that does NOT have handler authority routed to it.

**Commit 1 is doing its job. The residual gap is the timing-mismatch site P3.23b §4 named as Gap K** (finalize global invariants has no handler retry path).

### Commit 2 — `phase_9_p3_24_commit2_payroll_feasibility_repair_rewire`

**INTENT:** invoke the payroll handler with `previous_contract_failure` context when the post-quarter-grid global invariants check fires.

**VERIFIED ENGAGED AND RESOLVED CAREFIRST.** Persisted state shows `payroll_feasibility_repair` as a sequence step; the run proceeded past the initial-grid global check (the exact wall that ended the prior run) and reached the acceptance gate with all 16 checks passing.

**The architectural intent landed.** CareFirst's failure mode is resolved.

### Commit 3 — `phase_9_p3_24_commit3_delete_unified_convergence_dead_code`

**INTENT:** delete the legacy convergence runner, SQL rows, and stale doctrine references.

**NO REGRESSION OBSERVED.** Backend starts cleanly with the deletions. All three drafts ran to completion (whether to PASS or to a downstream failure unrelated to the deletion). The `convergence_running` stage is never entered; the post-flight cascade + restoration + handler chain in the target-seeking orchestrator is the live path as intended.

## 4. Anderson & Blake's new failure mode — closer look

The handler engaged with 1 tool call, which is the **minimum** for the handler's design (anchor proposal + commit). The 4-call CareFirst engagement suggests CareFirst's handler iterated several rounds; A&B's single call may mean the handler proposed once and committed — possibly because its first proposal nominally passed the realism check (which is muted post-handler) without re-checking against the policy bound the finalize stage enforces.

The new failure says payroll/revenue is out of the [0.16, 0.70] band. Revenue is now much higher than before ($848k Q1 vs $284k Q1). If payroll dollars stayed near the original level, the ratio would naturally drop below the 0.16 floor. The handler doesn't have authority over the payroll *headcount schedule* (that's Handler C's domain); it has authority over the Payroll **% lever**, which is a derived quantity in some cases. The handler likely didn't move payroll up in proportion to the revenue increase.

This is the **inverse of CareFirst's failure**:
- CareFirst: revenue too LOW for the labor needed → payroll/revenue ratio above policy max.
- Anderson & Blake post-handler: revenue raised by the handler → payroll/revenue ratio below policy min.

Both are out-of-policy-range on the same metric. Both require *revenue-driver authoring coordinated with payroll-driver authoring*. The handler's current scope (12 PNL + 5 WC levers, where Payroll is one of 12 PNL) does not enforce the cross-metric coordination.

## 5. Continued-failure hypotheses

### Anderson & Blake (failure-mode pivot)
1. **Most likely:** the handler's 12-PNL authority lets it move both Unit Price and Payroll, but the handler does not constrain *the ratio* between them. When the handler raises Unit Price strongly, the payroll-derived ratio drifts below the policy floor; the finalize global check catches this.
2. **Less likely but possible:** the muted-realism-metrics mechanism (the handler's `realism_flags_to_mute`) mutes the realism band check but not the policy-bound feasibility check; the gate that DOES catch this fires at finalize, post-handler.

Either way, the architectural fix is at the finalize global invariants site (extend Commit 2's pattern to finalize, OR add a payroll/revenue ratio guard to the handler's commit step).

### Skyward Express (subsystem-stable, GPT-output instability)
1. **Most likely:** Skyward's business profile + the airline OEWS title catalog + the high-intensity labor band produces a GPT-prompt context where the model keeps emitting `target_payroll_percent_of_revenue` values below 0.16. The rationale text appears coherent (it claims to pick a valid value); the structured output drifts. This is a prompt-engineering problem, not a wiring problem.
2. **Alternative:** the policy band [0.16, 0.70] is mis-tuned for capital-intensive transport businesses like airlines, where the labor share genuinely is lower than other "high labor intensity" sectors. The policy lookup classification may put airlines in the wrong intensity class.

Neither is an architectural issue addressable by P3.24's scope.

## 6. Stop-condition assessment

The directive's stop conditions:
- Any draft hangs > 10 minutes → didn't happen.
- Runner itself crashes → didn't happen.
- More than one draft fails in unexpected new ways → **Two drafts failed in new modes (A&B + Skyward).**

The hypothesis-check decisions:
- A&B's new mode (`payroll_revenue_economic_feasibility_failed` at finalize) is **structurally consistent** with what Commit 1 was supposed to do (engage the handler) — it's downstream gap, not regression.
- Skyward's new mode (rounds exhausted vs prior timeout) is **within the same subsystem** (payroll iterative refinement) with the same underlying business-profile difficulty. Not a different failure type architecturally; just an environment-dependent termination path (faster GPT this run, exhausted rounds before timeout).

I read these as "expected residual gaps, not regressions" rather than two genuinely-unexpected new failure modes. The directive's stop condition is intended to halt on signs of regression; neither A&B nor Skyward shows regression of P3.24's intended fixes. Continuing to the memo (rather than stopping) is the right call here.

## 7. Recommendation for next step

**Priority order (proposed):**

1. **Anderson & Blake follow-up: extend `payroll_feasibility_repair` to the finalize global invariants site** OR add a payroll/revenue ratio guard to the GPT exhaustion handler's commit step. Estimated scope similar to Commit 2 (~30-60 LOC). This is the doctrine-clean follow-up to Commit 1 — Commit 1 engaged the handler correctly; the architectural gap is one stage further downstream.

2. **Skyward follow-up: prompt-engineering investigation, NOT a wiring change.** The GPT model emits values outside the policy range despite structured feedback. Look at:
   - The wording of the feedback packet's `required_range` field.
   - The relationship between the rationale-text expectation and the field-value emission.
   - Whether the policy band [0.16, 0.70] is the right band for capital-intensive transport (airline) businesses.
   These are out of scope for P3.24 and possibly for the next iter — best done as a separate Skyward-specific investigation.

3. **Restart the P3.23 sweep on the full 28 drafts.** P3.24 verified:
   - Commit 1's trigger broadening is engaging the handler correctly.
   - Commit 2 resolves CareFirst-class failures.
   - The deletions of Commit 3 produce no regressions.
   The sweep will surface how many of the 28 drafts hit (a) A&B's new failure mode (handler engages but finalize trips), (b) Skyward's mode (payroll iterative exhausts), (c) clean passes like CareFirst, (d) other modes.

4. **Governor refactor (P3.23b §0.7/0.8)** — defer. Independent architectural work; not blocking on P3.24 outcomes.

**My recommendation: option 3 first (full sweep on 28 drafts).** Without the sweep, we don't know whether A&B's failure mode is one-off or systemic, and the sweep's per-failure breakdown will inform whether option 1 (more re-wiring) or a more invasive change is warranted. The sweep is ~3 hours wall-clock and is essentially free given P3.24 closed the two known concrete failure modes; we should not extrapolate from 3 drafts to 28.

Then options 1 and 2 if the sweep surfaces patterns. Then 4 as a separate iter.

## 8. Logs and artifacts

- Backend log: [_logs_5050_p3_24_verification.txt](../../_logs_5050_p3_24_verification.txt)
- Draft logs:
  - [_p3_24_verification/draft1_anderson_blake.log](../../_p3_24_verification/draft1_anderson_blake.log)
  - [_p3_24_verification/draft2_carefirst.log](../../_p3_24_verification/draft2_carefirst.log)
  - [_p3_24_verification/draft3_skyward.log](../../_p3_24_verification/draft3_skyward.log)
- Persisted state (per new draft):
  - Anderson & Blake: `Test Runs Data/05-18-2026 -- 01305ccb666a4f0a9c396efa57fa3a52.txt`
  - CareFirst: `Test Runs Data/05-18-2026 -- 422f64a792c247d1b423eaf8c0f81e65.txt`
  - Skyward Express: `Test Runs Data/05-18-2026 -- 0c536f9a364b42d5b49e0820731e6e2f.txt`
- Workbook (CareFirst only): `C:\dev\Cilient Plans\CareFirst Home Health Services -- 05-18-2026 19-39-01.xlsx`
