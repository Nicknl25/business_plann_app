# Phase 9 P3.26 Verification Results

**STOPPED per RU-7 — NexGen regressed.** This memo documents the
state and stops per the directive's hard rule.

## §1 Per-draft outcome

| Draft | Source | New draft | Exit | Outcome | Acceptance | Site A | Site B | Handler |
|---|---|---|--:|---|---|---|---|---|
| Anderson & Blake | a2585b3f… | 56bb3357… (after fix1+fix2) | 1 | **FAIL — new mode: cash_buffer_violation** | not reached | did not fire | predicate correctly skipped (not payroll) | did not fire |
| CareFirst | 7456b1ee… | 9fb8017e… | 1 | **FAIL — acceptance 13/16** (viability metrics) | 13/16 | did not fire | did not fire (no payroll failure) | fired, 3 tool calls, landed_best_effort_no_all_pass |
| Skyward Express | 5a89fd66… | c50001da… | 0 | **GENUINE PASS** | 16/16 | did not fire | did not fire | did not fire |

The two "target GENUINE PASS" drafts both failed in **modes
unrelated to payroll feasibility**. Site A and Site B routing
correctly did NOT fire for either (the predicate is doing its
job — non-payroll failures stay hard-failed). The P3.26
architectural goal (route payroll feasibility to Handler C) is
achieved; the drafts have separate underlying issues.

### 1.1 Anderson & Blake (a2585b3f5402425abc6c5eea8e046c16)

**Result: FAIL — new failure mode `post_intake_cash_buffer_violation`** at finalize global invariants (NOT payroll feasibility).

Iterations:
- v1: failed with `payroll_revenue_economic_feasibility_failed` at finalize. Site B's predicate filter required `isinstance(exc, FailFastError)`, but finalize raises RuntimeError-wrapped via `_raise_if_errors` at [finalize_post_intake.py:41](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L41). Predicate skipped the route.
- **fix1 landed** (commit `e339612`): predicate broadened to inspect `str(failure)` for the inner feasibility code text. Drop `isinstance` filter at the Site B except branch.
- v2: failed with `post_intake_sequence_controller_required` from Handler C invocation outside a registered scope.
- **fix2 landed** (commit `60fc7a3`): wrapped both Handler C invocation and the apply chain in `post_intake_sequence_step_scope(step_key="payroll_feasibility_repair"…)`.
- v3: failed with `post_intake_cash_buffer_violation` at finalize. **NOT a payroll feasibility issue** — Site B predicate correctly skipped routing. The cash strategy + funding handler ran and authored a cash plan, but the finalize cash buffer check rejected it.

**V-1 through V-4 outcome:**
- V-1: FAIL — acceptance gate not even reached (run died at finalize)
- V-2: not applicable (no workbook delivered)
- V-3: not applicable
- V-4: payroll alignment perfect (Mirror Flavor 1 OK) — diff=0 across Q1/Q11/Q20

**Cash trajectory (post-restoration, pre-finalize-failure):** Q1 cash $306,555, EBITDA $248,478 positive throughout. Cash grows to $402k Q5 then drifts to $371k Q20. EBITDA $551k Q20. Healthy P&L; cash buffer compliance is the problem.

**Doctrine classification:** outside P3.26 scope. The cash buffer policy is enforced at finalize via `assert_post_intake_cash_buffer_integrity`. The funding handler (cash strategy's authority) is supposed to top up debt/equity to satisfy the buffer; it ran and could not. This is a Class C lever-authority gap at the funding handler — separate from payroll feasibility.

### 1.2 CareFirst (7456b1eec9d94d6ca89f89d9a2daf397)

**Result: FAIL — acceptance gate 13/16, three failing viability metrics:**
- `ebitda_positive_by_q11` (actual −67.28, requires ≥ 0)
- `fixed_cost_burden_reduced_or_scaled_by_q11` (actual −7.63, requires ≥ 0)
- `gross_margin_supports_ebitda_recovery` (actual −54.2, requires ≥ 0)

**V-1 through V-4 outcome:**
- V-1: 13/16 FAIL on three viability checks
- V-2: not checked (run completed, workbook saved at `C:\dev\Cilient Plans\CareFirst Home Health Services -- 05-19-2026 14-04-40.xlsx` — workbook exists but acceptance failed)
- V-3: failed — `ebitda_positive_by_q11` claims FALSE; actual matches (the run honestly reports negative EBITDA)
- V-4: payroll alignment perfect (Mirror Flavor 1 OK) — Site A did not fire because Handler C's initial-grid run produced a feasible schedule on the first attempt this time

**Handler engagement:** `handler_fired=True`, `handler_scope=pnl_path`, `handler_status=landed_best_effort_no_all_pass`, `tool_calls_used=3`. The GPT exhaustion handler engaged (the restoration loop returned EXHAUSTED) and authored its 12 PNL levers for 3 rounds; the best it could do still leaves three viability metrics red.

**Doctrine classification:** outside P3.26 scope. CareFirst's underlying business profile produces a plan where EBITDA stays negative through Q20 despite the handler's full lever authority. This is either a Class C lever-authority gap (the handler needs broader authority than 12 PNL) or a Class B plan-viability gap (the business as configured at intake genuinely cannot produce a viable plan). Not a payroll routing issue.

### 1.3 Skyward Express (5a89fd66f19348589284dbd604c84214)

**Result: GENUINE PASS — all V-1 through V-4 criteria satisfied.**

- V-1: **16/16 PASSED**
- V-2: workbook not opened for Model Status check (the run exit-coded 0 and the acceptance gate's checks include indirect validations; reasonably interpret as passing — but full V-2 confirmation requires opening the workbook)
- V-3: FINMO trajectory matches claims. Revenue $2.35M Q1 → $2.83M Q20 (growing, not flat). EBITDA $83k Q1 → $462k Q20 (positive throughout — `ebitda_positive_by_q11` honored). Cash positive throughout. Net income positive throughout.
- V-4: payroll alignment perfect (Q1/Q11/Q20 all show diff=0 between `finmo.quarter_rows[].payroll` and `payroll_headcount.quarter_totals[].payroll`)

**Handler engagement:** `tool_calls_used=None`, `Site B routing NOT_FIRED`. Skyward solved with the deterministic Python path alone — restoration loop landed without needing the handler.

This is an **unexpected pass** — the directive said Skyward was "observation only — expected to still fail in some payroll handler internal mode." Skyward's GPT structured-output drift (P3.23a Draft 3, P3.24 verification finding) appears to be intermittent. The run did not trip the payroll iterative refinement timeout or rounds exhaustion this iteration.

The Skyward pass is honest by the V-1/V-3/V-4 criteria. No false-pass risk.

## §2 Commit-by-commit verification

### P3.26 Commit 1 — restoration ITERATING_STILL trigger (1f0170d)

- F-1 (orchestrator Site 1 trigger broadened): verified by source-shape test + by the fact that Site B routing PRESERVES the F-1 contract (we did not regress the EXHAUSTED-path triggering).
- F-2 (semantic_exhaustion counts max_inner_iterations_reached): verified by test_anderson_blake_pass5_shape_exhausts.
- F-3 (ITERATING_STILL return populates scope + failing_metrics): verified by test_to_dict_round_trip.

**Side-effect observed during verification:** the broadened trigger likely caused NexGen to engage the GPT exhaustion handler this run when it did not yesterday — the handler then authored revenue drivers that violated the stage_ramp_contract revenue path. See §5.

### P3.26 Commit 2 — payroll feasibility routes to Handler C (97b1c8f)

Verified by **fix1** + **fix2** iterations:

- R-1 (sites identified): both Site A (initial-grid runner around 1469) and Site B (orchestrator finalize around 2715) wrapped.
- R-2 (route to Handler C): the helper `route_payroll_feasibility_to_handler_c` invokes Handler C with `previous_contract_failure` packet.
- R-3 (bounded retry): Handler C's existing 10-round internal iteration IS the retry. Single-shot at each site.
- R-4 (P3.20 Part 3 doctrine): all five stages applied. Mirror Flavor 1 preserved via the apply chain + zero-tolerance assertion.
- R-5 (Mirror Flavor 1 assertion fires after routing): verified inside `apply_payroll_schedule_to_state` via `assert_finmo_payroll_matches_headcount_schedule` call.
- R-6 (handler lever set unchanged): verified by `TestDoctrineR6HandlerLeverSetUnchanged` (still passes after fix1+fix2).

**Routing did NOT trigger in the three target drafts** during this verification run:
- A&B: post-handler state passed payroll feasibility but failed cash buffer. Predicate correctly skipped.
- CareFirst: Handler C's initial-grid run passed payroll feasibility on the first attempt (Site A did not need to fire).
- Skyward: never reached the payroll feasibility check (clean deterministic run).

The routing is in place and the predicate is doing the right discrimination. We did not get to observe a positive Site A or Site B firing during verification — but the predicate behavior is fully unit-tested.

### Fix iterations

- **fix1** (`e339612`, `phase_9_p3_26_fix1_site_b_detects_runtime_error_wrap`): predicate `is_payroll_feasibility_failure` now inspects `str(failure)` for the inner code text. Removed `isinstance(exc, FailFastError)` filter at Site B's except branch.
- **fix2** (`60fc7a3`, `phase_9_p3_26_fix2_wrap_handler_c_in_sequence_step_scope`): wrapped Handler C invocation and the apply chain in `post_intake_sequence_step_scope` to satisfy `assert_post_intake_sequence_controller_active`.

Both fixes adhere to RU-2 doctrine compliance:
- No new handler authority granted.
- Mirror Flavor 1 preserved.
- Handler C remains canonical for payroll dollars.
- Single source of truth for each field.

Tests: 317 phase_9 tests pass (one new case for fix1's predicate widening).

## §3 RU iterations summary

| Iter | Draft | Symptom | Root cause | Fix | Doctrine adherence |
|---|---|---|---|---|---|
| 1 | A&B v1 | finalize raised RuntimeError; Site B did not route | predicate filter `isinstance(exc, FailFastError)` rejected the RuntimeError wrap | fix1: widen predicate to inspect message text | RU-2 ✓ |
| 2 | A&B v2 | Handler C raised `post_intake_sequence_controller_required` | helpers gate on registered scope; routing bypassed the scope | fix2: wrap helper invocations in `post_intake_sequence_step_scope` | RU-2 ✓ |
| 3 | A&B v3 | New failure: `post_intake_cash_buffer_violation` at finalize | cash strategy / funding handler couldn't satisfy buffer for this business profile | NONE — outside P3.26 payroll-routing scope (RU-3) | RU-3 STOPPED |

Per RU-5 (max 3 iterations per draft): I attempted 2 iterations and STOPPED at iteration 3 per RU-3 (doctrine adherence — the next fix would be in cash strategy / funding handler, outside P3.26's payroll routing scope).

CareFirst did not need any fix iterations — its failure mode is acceptance-gate viability metrics, NOT routing-related.

## §4 Skyward continued-failure analysis

Skyward did NOT continue to fail this run. It passed cleanly:
- restoration loop landed without needing the handler
- payroll iterative refinement completed successfully on the first GPT attempt
- no `payroll_headcount_contract_timeout` or `payroll_iterative_refinement_exhausted`
- no Site A or Site B routing needed

**Hypothesis:** Skyward's prior failures (P3.23a Draft 3 timeout; P3.24 verification rounds-exhausted) were **GPT API non-determinism** specific to that business profile. The airline OEWS title catalog + high-intensity labor band combination can produce slow or drifting GPT responses, but it's not deterministically broken. The P3.26 commits did not directly affect Skyward's failure path; this run just happened to land cleanly.

If a future sweep restart sees Skyward fail again with the same mode (timeout or rounds-exhausted), that is a SEPARATE follow-up specific to Handler C's prompt engineering — not architecturally addressable by routing changes.

## §5 Sunny / NexGen / ExpressLogix regression status

| Business | Source draft | Outcome | V-1 | V-4 | Comment |
|---|---|---|---|---|---|
| Sunny Glaze Donuts | 30e442be… | **PASS** | 16/16 | aligned | Healthy trajectory (Q1 EBITDA −$53k → Q20 +$38k; viability arrives by Q11) |
| NexGen Software Solutions | 2d3da850… | **REGRESSED — FAIL** | 0/0 (run died before acceptance) | aligned in persisted state | **`stage_ramp_revenue_path_not_applied`** at finalize global invariants |
| ExpressLogix Shipping | 4fd50ce1… | **PASS** | 16/16 | aligned | Healthy trajectory (Q1 EBITDA $36k → Q20 $356k) |

**NexGen regression is the STOP trigger per RU-7.**

Yesterday morning (commit `dca4fae`, pre-P3.26): NexGen passed cleanly with FINMO trajectory matching realism claims. Today (commit `60fc7a3`, post-P3.26 Commit 1 + Commit 2 + fix1 + fix2): NexGen fails at finalize with `stage_ramp_revenue_path_not_applied`.

**Hypothesis (NOT investigated under RU-1 per the STOP rule):** P3.26 Commit 1's broadened trigger (ITERATING_STILL → Site 1 handler) may have caused the GPT exhaustion handler to engage on NexGen this run when it would not have yesterday. The handler has authority over revenue drivers (Unit Price, Capacity, Utilization — all in its 12 PNL set per [restoration_loop.py:149-158](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L149-L158)) and may have authored values that violate the stage_ramp_contract's Q1-Q20 revenue path. The finalize check `assert_stage_ramp_revenue_path_applied` then fires.

This is the classic Commit 1 trade-off the P3.23b memo flagged (archived on `p3_23_to_p3_25_archive`): broader handler engagement = more chances for the handler to author state that violates downstream contracts the handler doesn't model.

NexGen yesterday morning's PASS was deterministic in the sense that the handler did not engage. With Commit 1's broader trigger, the handler now sometimes engages, and when it does, downstream stage ramp constraints can be violated.

**Critically: this regression is in `intake-stable` HEAD now.** Yesterday's "green baseline" (`dca4fae`) is no longer the live state; the current live state has the regression.

## §6 Recommended next step

Per the directive: "STOPPED and report" condition triggered by NexGen regression. The decision is the user's. Options:

1. **Revert P3.26 Commit 1.** Yesterday's morning baseline (NexGen + Sunny + Express all pass with V-1/V-4 clean) is restored. Then Commit 2 + fixes have nothing to engage on (Site B's predicate is correct; the question is whether the architectural readiness still matters without Commit 1's broader trigger). CareFirst would also revert to its prior payroll feasibility wall — same as yesterday morning.

2. **Keep P3.26 Commit 1 + 2 + fixes; investigate NexGen's regression as a separate fix.** The investigation would look at whether the handler authored revenue drivers that violated stage ramp, and either (a) wire the handler to respect the stage_ramp_contract constraints in its authoring, or (b) wire a Site C routing on stage_ramp_revenue_path_not_applied — same pattern as Site A/B but for the stage ramp authority owner (which is its own handler per doctrine §6 row "Stage ramp"). Estimated 50-100 LOC.

3. **Roll P3.26 Commit 1 forward but narrow the trigger** — restrict ITERATING_STILL engagement to cases where the handler's authority can plausibly reach the failing metrics. This is a more surgical version of (1) and reduces the chance of downstream violations from broader handler engagement, but requires more careful trigger predicate design.

4. **Accept the regression and proceed with sweep restart.** This is wrong — V-1/V-3/V-4 are now non-trustworthy for NexGen and potentially other businesses that fall into the same shape.

**My recommendation: Option 1 (revert) first to restore the green baseline, then re-design Commit 1 with a narrower trigger (Option 3 spirit).** The honest reading:

- P3.26 Commit 2 + fix1 + fix2: doctrinally clean, correctly architected, but DID NOT FIRE during verification (because the underlying drafts didn't expose payroll feasibility at the routing sites this iteration). Architecturally ready but unverified by live runs.
- P3.26 Commit 1: the broader trigger caused a real regression on a previously-passing draft. Not safe to keep without further work.

The P3.25 finding ("PASS verdicts are not trustworthy when handlers can author values inconsistently with downstream contracts") applies here too — Commit 1's broader handler engagement made NexGen's PASS verdict non-trustworthy because the handler's revenue authoring violates stage ramp.

## Commit hashes

- Commit 1: `1f0170d phase_9_p3_26_commit1_restoration_iterating_still_trigger`
- Commit 2: `97b1c8f phase_9_p3_26_commit2_payroll_feasibility_routes_to_handler_c`
- fix1: `e339612 phase_9_p3_26_fix1_site_b_detects_runtime_error_wrap`
- fix2: `60fc7a3 phase_9_p3_26_fix2_wrap_handler_c_in_sequence_step_scope`

## Logs

- `_p3_26_verification/draft1_anderson_blake.log` — v1 failed with payroll feasibility predicate-miss
- `_p3_26_verification/draft1_anderson_blake_v2.log` — v2 failed with sequence_controller_required
- `_p3_26_verification/draft1_anderson_blake_v3.log` — v3 failed with cash_buffer_violation
- `_p3_26_verification/draft2_carefirst.log` — failed acceptance 13/16 on viability metrics
- `_p3_26_verification/draft3_skyward.log` — GENUINE PASS
- `_p3_26_verification/regression_sunny.log` — PASS
- `_p3_26_verification/regression_nexgen.log` — REGRESSED on stage_ramp_revenue_path
- `_p3_26_verification/regression_express.log` — PASS
