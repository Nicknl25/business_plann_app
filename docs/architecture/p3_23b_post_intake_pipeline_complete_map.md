# Phase 9 P3.23b — Post-Intake Pipeline Complete Map

**READ-ONLY. NO FIXES. NO COMMITS BEYOND THE MEMO.**

The P3.23a investigation revealed two handler-engagement timing
mismatches (Anderson & Blake + CareFirst). This audit answers — with
file:line citations and no conjecture — whether the same shape is
present elsewhere in the post-intake pipeline. Scope: every post-intake
process, the checks that fire on each, the handlers that engage on
each, and **whether the timing makes handler-on-check engagement
possible at all**.

---

## 0. Sequence-table reconciliation (the FIRST verification)

The user identified that a canonical sequence table exists in SQL.
**The canonical source of truth is the MySQL table
`post_intake_process_sequence_lookup`**, loaded by
[`load_post_intake_process_sequence_rows` at post_intake_mapping.py:6298](../../python/client_intake_and_finmo/post_intake_mapping.py#L6298)
and exposed via [`post_intake_process_sequence_lookup()` at post_intake_mapping.py:8997](../../python/client_intake_and_finmo/post_intake_mapping.py#L8997).
The table name constant is at [post_intake_mapping.py:26](../../python/client_intake_and_finmo/post_intake_mapping.py#L26):
`_PROCESS_SEQUENCE_TABLE_NAME = "post_intake_process_sequence_lookup"`.

The Skyward fail-fast diagnostic from P3.23a Draft 3 confirms this is
the live source-of-truth:
`'source_table': 'post_intake_process_sequence_lookup', 'step_key':
'payroll_gpt_contract_request'`.

### 0.1 Canonical sequence table — verbatim transcript

Live query result from MySQL (69 rows where `enabled=1`, ordered by
`phase ASC, step_order ASC, id ASC`):

| Phase | Order | step_key | parent_step_key | kind | executor_function |
|---|--:|---|---|---|---|
| runtime_validation | 1 | post_intake_initialize_validation | — | process | run_initialize_post_intake_validation |
| pre_convergence | 5 | realism_memo_review | — | process | generate_realism_memo_payload_safe |
| pre_convergence | 10 | baseline_model_input | — | process | prepare_baseline_model_input |
| pre_convergence | 10 | shared_context_build | baseline_model_input | subprocess | build_shared_context |
| pre_convergence | 11 | ops_context_load | baseline_model_input | subprocess | load_operating_model_context |
| pre_convergence | 12 | market_context_load | baseline_model_input | subprocess | load_target_market_context |
| pre_convergence | 13 | people_context_load | baseline_model_input | subprocess | load_people_context |
| pre_convergence | 14 | financials_context_load | baseline_model_input | subprocess | load_financials_context |
| pre_convergence | 15 | financials_year1_assembly | baseline_model_input | subprocess | assemble_financials_year1 |
| pre_convergence | 16 | marketing_context_build | baseline_model_input | subprocess | compute_marketing_model_json |
| pre_convergence | 17 | baseline_finmo_sync | baseline_model_input | subprocess | sync_planning_state_to_finmo |
| pre_convergence | 20 | maintenance_capex_percent | — | process | estimate_maintenance_capex_percent_with_gpt |
| pre_convergence | 30 | r_and_d_applicability | — | process | estimate_r_and_d_applicability_with_gpt |
| pre_convergence | 35 | r_and_d_policy_application | r_and_d_applicability | subprocess | apply_r_and_d_applicability_policy_to_model_input |
| pre_convergence | 40 | balance_sheet_contextual_seed | — | process | estimate_balance_sheet_contextual_seed_with_gpt |
| pre_convergence | 45 | balance_sheet_seed_application | balance_sheet_contextual_seed | subprocess | apply_balance_sheet_contextual_seed_to_model_input |
| pre_convergence | 50 | planning_mode_determination | — | process | determine_planning_mode |
| pre_convergence | 55 | stage_ramp_contract | — | process | estimate_stage_ramp_contract_with_gpt |
| initial_grid | 60 | **payroll_headcount_schedule** | — | process | estimate_payroll_headcount_schedule_with_gpt |
| initial_grid | 61 | payroll_context_build | payroll_headcount_schedule | subprocess | build_payroll_headcount_context |
| initial_grid | 62 | payroll_oews_title_catalog | payroll_headcount_schedule | subprocess | load_payroll_oews_title_catalog |
| initial_grid | 63 | payroll_gpt_contract_request | payroll_headcount_schedule | subprocess | estimate_payroll_headcount_schedule_with_gpt |
| initial_grid | 64 | payroll_contract_validation | payroll_headcount_schedule | subprocess | assert_payroll_headcount_payload_ready |
| initial_grid | 65 | **payroll_feasibility_repair** | payroll_headcount_schedule | subprocess | **retry_payroll_headcount_schedule_from_feasibility_failure** |
| initial_grid | 66 | payroll_capacity_derivation | payroll_headcount_schedule | subprocess | apply_payroll_supported_capacity_to_model_input |
| initial_grid | 67 | payroll_model_input_application | payroll_headcount_schedule | subprocess | apply_payroll_headcount_payload_to_model_input |
| initial_grid | 68 | payroll_finmo_rebuild_validation | payroll_headcount_schedule | subprocess | assert_finmo_payroll_matches_headcount_schedule |
| initial_grid | 69 | pre_quarter_grid_global_validation | payroll_headcount_schedule | subprocess | assert_post_intake_global_invariants |
| initial_grid | 70 | quarter_grid_generation | — | process | generate_live_quarter_grid_plan |
| initial_grid | 71 | quarter_grid_context_build | quarter_grid_generation | subprocess | build_quarter_grid_context |
| initial_grid | 72 | quarter_grid_gpt_plan | quarter_grid_generation | subprocess | generate_live_quarter_grid_plan |
| initial_grid | 73 | quarter_grid_validation | quarter_grid_generation | subprocess | validate_live_quarter_grid_plan |
| initial_grid | 74 | quarter_grid_apply_model_input | quarter_grid_generation | subprocess | apply_live_quarter_grid_plan |
| initial_grid | 75 | quarter_grid_reapply_locked_payroll | quarter_grid_generation | subprocess | reapply_payroll_authority_after_quarter_grid |
| initial_grid | 76 | quarter_grid_global_validation | quarter_grid_generation | subprocess | assert_post_intake_global_invariants |
| convergence | 80 | **issue_detection** | — | process | **detect_post_intake_issues** |
| convergence | 81 | issue_repair_scope_build | issue_detection | subprocess | build_post_intake_issue_repair_scope |
| convergence | 90 | **unified_convergence_decision** | — | process | **run_unified_convergence_cycle** |
| convergence | 90 | **unified_convergence_retry** | — | process | **run_unified_convergence_contract_retry** |
| convergence | 91 | unified_convergence_context_build | unified_convergence_decision | subprocess | build_unified_convergence_context |
| convergence | 92 | unified_convergence_gpt_decision | unified_convergence_decision | subprocess | run_unified_convergence_cycle |
| convergence | 93 | unified_convergence_plan_translation | unified_convergence_decision | subprocess | translate_unified_convergence_decision_to_updates |
| convergence | 94 | unified_convergence_apply_updates | unified_convergence_decision | subprocess | apply_unified_convergence_updates |
| convergence | 95 | unified_convergence_verify_progress | unified_convergence_decision | subprocess | verify_unified_convergence_progress |
| convergence | 96 | post_convergence_global_validation | unified_convergence_decision | subprocess | assert_post_intake_global_invariants |
| cash_pass | 100 | cash_minimum_debt_schedule | — | process | apply_cash_pass_minimum_debt_schedule |
| cash_pass | 101 | cash_debt_schedule_seed | cash_minimum_debt_schedule | subprocess | apply_cash_pass_minimum_debt_schedule |
| cash_pass | 102 | cash_short_term_debt_seed | cash_minimum_debt_schedule | subprocess | seed_cash_short_term_debt_current_portion |
| cash_pass | 110 | **cash_strategy_review** | — | process | **run_cash_strategy_review** |
| cash_pass | 111 | cash_review_context_build | cash_strategy_review | subprocess | build_cash_strategy_review_context |
| cash_pass | 112 | cash_gpt_review | cash_strategy_review | subprocess | run_cash_strategy_review |
| cash_pass | 113 | cash_translation_plan | cash_strategy_review | subprocess | translate_cash_strategy_decision_to_updates |
| cash_pass | 114 | cash_apply_exact_updates | cash_strategy_review | subprocess | apply_cash_strategy_exact_updates |
| cash_pass | 115 | cash_debt_schedule_rebuild | cash_strategy_review | subprocess | rebuild_cash_debt_schedule_after_updates |
| cash_pass | 116 | cash_short_term_debt_current_portion | cash_strategy_review | subprocess | apply_cash_short_term_debt_current_portion |
| cash_pass | 117 | cash_surplus_cleanup | cash_strategy_review | subprocess | deploy_cash_surplus_above_policy_ceiling |
| cash_pass | 120 | cash_pass_validation | — | process | validate_cash_pass |
| cash_pass | 121 | cash_post_validation | cash_pass_validation | subprocess | validate_cash_pass |
| final_validation | 130 | final_hard_gates | — | process | validate_final_post_intake_state |
| final_validation | 131 | cash_final_finmo_rebuild | final_hard_gates | subprocess | build_python_finmo_json |
| final_validation | 132 | cash_final_liquidity_gate | final_hard_gates | subprocess | assert_post_intake_cash_buffer_integrity |
| final_validation | 133 | **final_stage_ramp_revenue_limit_check** | final_hard_gates | subprocess | **apply_stage_ramp_revenue_driver_limits** |
| final_validation | 134 | final_global_validation | final_hard_gates | subprocess | assert_post_intake_global_invariants |
| runtime_validation | 140 | post_intake_finalize_validation | — | process | run_finalize_post_intake_validation |
| runtime_validation | 141 | finalize_mapping_integrity | post_intake_finalize_validation | subprocess | assert_post_intake_mapping_formula_application_integrity |
| runtime_validation | 142 | finalize_payroll_reconciliation | post_intake_finalize_validation | subprocess | assert_finmo_payroll_matches_headcount_schedule |
| runtime_validation | 143 | finalize_debt_reconciliation | post_intake_finalize_validation | subprocess | assert_finmo_matches_debt_schedule |
| runtime_validation | 144 | finalize_cash_phase_trace | post_intake_finalize_validation | subprocess | assert_cash_phase_trace_complete |
| runtime_validation | 145 | finalize_global_invariants | post_intake_finalize_validation | subprocess | assert_post_intake_global_invariants |

**Bold** rows are the ones where the live runtime materially diverges
from the canonical table — detail below.

### 0.2 Actual runtime sequence (from orchestrator code, file:line)

Phase A — `prepare_initial_grid_for_draft` ([initial_grid/runner.py:30](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30)):
- `baseline_model_input` placeholder marker [runner.py:421](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L421)
- `shared_context_build` [runner.py:434](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L434)
- `ops_context_load` [runner.py:444](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L444)
- `market_context_load` [runner.py:452](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L452)
- `people_context_load` [runner.py:460](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L460)
- `financials_context_load` [runner.py:468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L468)
- `base_year1` [runner.py:481](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L481)
- `marketing_model_json` [runner.py:504](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L504)
- `forecast_starting_ppe_decision` [runner.py:526](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L526)
- `sync_result` [runner.py:564](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L564)
- `r_and_d_applicability_decision` [runner.py:619](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L619)
- `r_and_d_policy_result` [runner.py:652](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L652)
- `balance_sheet_contextual_seed_decision` [runner.py:679](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L679)
- `balance_sheet_seed_result` [runner.py:722](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L722)
- `planning_choice` [runner.py:765](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L765) ← maps to **planning_mode_determination**
- `stage_ramp_contract` [runner.py:815](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L815)
- `_build_and_apply_payroll_schedule` [runner.py:1209 or 1252](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1209) → calls `estimate_payroll_headcount_schedule_with_gpt`
- `_assert_global_invariants_via_sequence` [runner.py:1224 / 1258](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1224) ← `pre_quarter_grid_global_validation`
- `quarter_grid_context_payload` [runner.py:1296](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1296)
- `planning_result` [runner.py:1323](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1323)
- `validated_quarter_grid_plan` [runner.py:1377](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1377)
- `grid_application_result` [runner.py:1408](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1408)
- `_assert_global_invariants_via_sequence` [runner.py:1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1469) ← `quarter_grid_global_validation`

Phase B — `run_target_seeking_orchestrated_system_run` ([solver/orchestrator.py:1024](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1024)):
- pre-flight target-seeking pass [orchestrator.py:1316](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1316) — **NOT IN TABLE**
- **INNER RUNNER BYPASSED** [orchestrator.py:1342](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342)
- post-flight assertion + cascade [orchestrator.py:1383-1530](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1383-L1530) — **NOT IN TABLE**
- restoration_loop [orchestrator.py:1933](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1933) — **NOT IN TABLE**
- GPT exhaustion handler Site 1 [orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977) — **NOT IN TABLE**
- pre-cash gate (Site 2) [orchestrator.py:2121-2200](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2121-L2200) — **NOT IN TABLE**
- `run_mode_based_cash_strategy` [orchestrator.py:2281](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2281) ← **table specifies `run_cash_strategy_review` for cash_pass:110**
- realism gate [orchestrator.py:2355](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2355) — **NOT IN TABLE**
- solver_target_assertion [orchestrator.py:2472](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2472) — **NOT IN TABLE**
- `run_finalize_post_intake_validation` [orchestrator.py:2679](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2679) ← `runtime_validation:140`

After orchestrator returns:
- `verify_run_acceptance` [intake_consult.py:7424](../../python/api_handlers/intake_consult.py#L7424) — **NOT IN TABLE**

### 0.3 Position-by-position reconciliation

#### A. Steps in the table but NOT invoked by current code (drift: code is missing canonical steps)

| Phase:order | step_key | executor_function | Status in code |
|---|---|---|---|
| pre_convergence:5 | realism_memo_review | generate_realism_memo_payload_safe | **NOT invoked in current `prepare_initial_grid_for_draft`**. The realism memo is built *post-cascade* at [orchestrator.py:2425](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2425) (via `build_realism_memo` on the realism_gate_payload), not in pre_convergence. **POSITION DRIFT.** |
| pre_convergence:20 | maintenance_capex_percent | estimate_maintenance_capex_percent_with_gpt | Replaced with deterministic NAICS-cascade at [intake_consult.py:7064](../../python/api_handlers/intake_consult.py#L7064): `estimate_maintenance_capex_percent_with_gpt=_derive_maintenance_capex_percent_from_naics`. The GPT call was **deleted** per the Module 5 Task 5.1 comment ([intake_consult.py:7060-7063](../../python/api_handlers/intake_consult.py#L7060-L7063)). The step still runs (as the deterministic substitute keeps the dependency-injection key) but the *executor* is no longer `estimate_maintenance_capex_percent_with_gpt`. |
| initial_grid:65 | **payroll_feasibility_repair** | **retry_payroll_headcount_schedule_from_feasibility_failure** | **NOT invoked.** Explicitly removed per [runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468) comment: *"Phase 9 P3.11 — post-quarter-grid invariant check. Previously wrapped in a try/except that caught payroll_revenue_economic_feasibility_failed... With the outer loop removed and the inner iterative refinement covering up to 10 rounds against the same feasibility validators, post-quarter-grid feasibility violations now hard-fail directly."* **This is the executor that would have addressed the CareFirst failure mode if it were still wired.** |
| convergence:80 | issue_detection | detect_post_intake_issues | **NOT invoked.** The convergence phase 80-96 implements the legacy `_run_unified_convergence_openai` engine; the orchestrator's inner-runner bypass at [orchestrator.py:1342](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342) skips this entire phase. |
| convergence:90 | **unified_convergence_decision** | **run_unified_convergence_cycle** | **NOT invoked.** Same bypass. Doctrine §6 lists this as the GPT-as-authoring-source convergence path; the table makes it the canonical step; the code bypasses it. |
| convergence:90 | unified_convergence_retry | run_unified_convergence_contract_retry | **NOT invoked.** Same bypass. |
| convergence:91-96 | unified_convergence_context_build, unified_convergence_gpt_decision, plan_translation, apply_updates, verify_progress, post_convergence_global_validation | various | **NOT invoked** (subprocesses of the bypassed step). |
| cash_pass:110 | **cash_strategy_review** | **run_cash_strategy_review** | **REPLACED.** The current orchestrator at [orchestrator.py:2281](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2281) calls `run_mode_based_cash_strategy` (mode-driven per-quarter funding policy) instead. The doctrine note at [orchestrator.py:2241-2250](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2241-L2250) explicitly describes this as *"replaces the Phase 8 minimal cash strategy."* The substitute keeps the same `_PROCESS_SEQUENCE_TABLE_NAME` step key for telemetry but the executor is different. |
| cash_pass:111-117 | cash_review_context_build, cash_gpt_review, cash_translation_plan, cash_apply_exact_updates, cash_debt_schedule_rebuild, cash_short_term_debt_current_portion, cash_surplus_cleanup | various | **Behaviorally replaced** by the internals of `run_mode_based_cash_strategy`. The table's GPT cash review path (`cash_gpt_review`, step 112) is the most material divergence — no GPT call there in current code. |
| cash_pass:100-102 | cash_minimum_debt_schedule + 2 subprocesses | apply_cash_pass_minimum_debt_schedule, seed_cash_short_term_debt_current_portion | **NOT explicitly invoked as a separate step.** The current orchestrator builds a debt_schedule snapshot at [orchestrator.py:2505](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2505) AFTER cash strategy, not as a step:100 process before cash strategy. **POSITION DRIFT.** |
| final_validation:130-134 | final_hard_gates + 4 subprocesses | validate_final_post_intake_state, build_python_finmo_json, assert_post_intake_cash_buffer_integrity, apply_stage_ramp_revenue_driver_limits, assert_post_intake_global_invariants | **PARTIAL.** The current finalize call at [orchestrator.py:2679](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2679) is the `runtime_validation:140` step. The `final_validation` phase's 130-134 steps don't run as named — their assertions are folded into the `runtime_validation:140` body. The step 133 `apply_stage_ramp_revenue_driver_limits` is **not invoked by name** in the orchestrator path. |

#### B. Steps in the code but NOT in the table (drift: code has extra steps)

| Code invocation | File:line | Status in table |
|---|---|---|
| `_run_target_seeking_pass` pre-flight | [orchestrator.py:1316](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1316) | NOT in table |
| Inner-runner bypass placeholder | [orchestrator.py:1342](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342) | NOT in table |
| Cascade tier walk | [orchestrator.py:1459-1530](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1459-L1530), [adaptation_cascade.py:382+](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L382) | NOT in table |
| `run_restoration_loop` | [orchestrator.py:1933](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1933) | NOT in table |
| GPT exhaustion handler Site 1 | [orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977) | NOT in table |
| Pre-cash GPT-authorable gate / handler Site 2 | [orchestrator.py:2121-2200](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2121-L2200) | NOT in table |
| Funding handler engagement | [orchestrator_invocation.py:618](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L618) | NOT in table |
| Realism gate (`validate_industry_realism_bands`) at post-cash | [orchestrator.py:2355](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2355) | NOT in table (but conceptually adjacent to `realism_memo_review` at pre_convergence:5) |
| solver_target_assertion | [orchestrator.py:2472](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2472) | NOT in table |
| Debt schedule snapshot build | [orchestrator.py:2505](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2505) | Different position than table's cash_pass:100 |
| Capital lease snapshot build | [orchestrator.py:2527](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2527) | NOT in table |
| `verify_run_acceptance` | [intake_consult.py:7424](../../python/api_handlers/intake_consult.py#L7424) | NOT in table |

#### C. Out-of-order steps (table says X-before-Y; code runs Y-before-X)

- **`realism_memo_review` (table: pre_convergence:5)** vs realism memo construction (code: post-cascade, [orchestrator.py:2425](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2425)). The table places memo review at the start of pre-convergence; the code builds it after the realism gate fires post-cash.
- **`cash_minimum_debt_schedule` (table: cash_pass:100)** vs debt_schedule snapshot (code: AFTER cash strategy at [orchestrator.py:2505](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2505)). Table says before; code does after.
- **`final_stage_ramp_revenue_limit_check` (table: final_validation:133)** is missing from the actual finalize body — finalize does `assert_post_intake_global_invariants` (which is `final_validation:134` and runtime_validation:145) but does not invoke `apply_stage_ramp_revenue_driver_limits` as a named subprocess. Either folded silently into global invariants or not invoked.

### 0.4 Source-of-truth analysis — does the orchestrator READ from the table?

**Partial.** The orchestrator uses **sequence-controller scopes** (e.g. [orchestrator.py:1929-1932](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1929-L1932), [orchestrator.py:1982-1985](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1982-L1985), [orchestrator.py:2277-2280](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2277-L2280)) that stamp telemetry with the table's `step_key` and `executor_function`. The post-intake sequence module [post_intake_sequence.py:80-100](../../python/client_intake_and_finmo/post_intake_sequence.py#L80-L100) has `assert_post_intake_sequence_controller_active` enforcing that domain functions only run inside a registered scope.

**BUT** the orchestrator does NOT use the table to drive **call order**. Examples:
- The orchestrator hard-codes `restoration_loop` → `exhaustion_handler` → `pre_cash_gate` → `cash_strategy` → `realism_gate` → `finalize` as Python control flow in `_run_post_cascade_completion`. None of this is read from the table.
- The cascade tier walk (`run_adaptation_cascade` at [adaptation_cascade.py:382](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L382)) iterates tiers 1-7 in code; the table has no row for "adaptation_cascade".
- The bypass at [orchestrator.py:1342](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342) explicitly **skips** the table's convergence phase (steps 80-96) with no flag in the table indicating this — the table still has `enabled=1` for those rows.

So the table is **enforced for individual step invocations** (where the
sequence-controller scope wraps them and demands a matching registered
step) **but is not the source of truth for top-level pipeline order**.
The orchestrator's order is the de-facto source of truth; the table is
*step-level governance + telemetry naming*.

This is doctrine **§3 Pattern 1 (Mirror Flavor 1) violation in
spirit**: the table claims to be the canonical sequence; the runtime
order is hard-coded elsewhere; they have diverged. The Skyward
diagnostic correctly cites `source_table:
post_intake_process_sequence_lookup, step_key:
payroll_gpt_contract_request` — proving the table IS consulted for the
step. But the table's `convergence:90 unified_convergence_decision` is
not consulted to gate whether to invoke `run_unified_convergence_cycle`
— the orchestrator just doesn't call it.

### 0.5 Cross-reference: which divergences correlate with timing-mismatch sites?

The two most damaging divergences correspond directly to the P3.23a failures:

1. **`payroll_feasibility_repair` (initial_grid:65) is in the table but is NOT invoked.** The table's executor is
   `retry_payroll_headcount_schedule_from_feasibility_failure` — exactly
   the handler that would have addressed `payroll_revenue_economic_feasibility_failed`
   in the CareFirst run (P3.23a Draft 2). The code removed this retry
   loop per the [runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468)
   comment. **The doctrinally-correct sequence has a retry; the code does not.**
   This is exactly the Pattern 2 (narrow trigger / missing handler engagement)
   shape — but the gap is a step the table specifies and the code removed,
   not a step that was never built.

2. **`unified_convergence_decision` (convergence:90) and its 6 subprocesses are in the table but BYPASSED in code.** The Anderson & Blake realism-band failure
   mode is exactly the kind of failure the GPT-authored convergence cycle
   was designed to address (per doctrine §6). Today the restoration loop
   + cascade attempt to cover this domain, but the trigger gap (Site 1 only
   fires on EXHAUSTED, ITERATING_STILL has no consumer) leaves Anderson &
   Blake unaddressed. **The table's intended path through convergence:90
   does not exist at runtime.**

These two divergences answer the user's reconciliation hypothesis with a
definitive YES: **the table specifies handler-engagement steps that the
code has removed or bypassed, and those exact removals correlate with
the two confirmed timing-mismatch sites from P3.23a.**

### 0.6 Sequence-table reconciliation gaps — proposed fix scope

| Divergence | Doctrinally correct | Fix scope | Risk |
|---|---|---|---|
| `payroll_feasibility_repair` removed | Re-wire the retry, OR update the table to reflect intentional removal | (a) If re-wiring: re-introduce the outer try/except that catches `payroll_revenue_economic_feasibility_failed` at [runner.py:1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1469) and routes to `retry_payroll_headcount_schedule_from_feasibility_failure`. Estimated 30-80 LOC. (b) If de-listing: remove the step from the SQL table and document the intentional architectural choice. | (a) Re-introduces the cycling behavior the P3.11 work explicitly removed. (b) Cleaner but locks in the CareFirst-class failure mode. **ARCHITECTURAL DECISION REQUIRED.** |
| `unified_convergence_decision` bypassed | Either re-enable the bypassed inner runner, or de-list `convergence:80-96` from the table | (a) If re-enabling: unsafe — the [orchestrator.py:1332-1342](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1332-L1342) comment notes the legacy convergence runner has known broken fail-fasts. (b) De-listing: requires doctrine §6 update because doctrine still names `_run_unified_convergence_openai` as the GPT-as-authoring-source convergence path. **ARCHITECTURAL DECISION REQUIRED.** |
| `cash_strategy_review` (table) → `run_mode_based_cash_strategy` (code) | Code is the live truth — Phase F-era replacement | Update the SQL table to reflect the new executor function. Estimated: 1 row UPDATE. **Documentation/table-update only.** |
| `cash_minimum_debt_schedule` (table:100, before cash strategy) → debt_schedule snapshot (code, after cash strategy) | Code position is the live truth (debt schedule reflects post-cash decisions) | Update the SQL table's `step_order` for `cash_minimum_debt_schedule` to fall after cash_pass:120 (`cash_pass_validation`), OR delete the row if subsumed. Estimated: 1 row UPDATE. **Table-update only.** |
| `realism_memo_review` (table:pre_convergence:5) → realism memo built post-cascade in code | Code position is the live truth | Update the SQL table to move `realism_memo_review` to after `runtime_validation:140`. Estimated: 1 row UPDATE. **Table-update only.** |
| Cascade / restoration loop / GPT exhaustion handler / pre-cash gate not in table | These are code-only adaptation steps | Add rows to the SQL table for: `target_seeking_preflight`, `adaptation_cascade`, `restoration_loop`, `gpt_exhaustion_handler_site_1`, `gpt_exhaustion_handler_site_2`, `realism_gate_post_cash`, `solver_target_assertion`, `acceptance_gate`. Estimated: 8 row INSERTs. **Table-update only.** |
| Top-level order is hard-coded in the orchestrator rather than read from the table | Doctrine §3 Mirror Flavor 1 — the table SHOULD be source of truth | Add a sequence-driven orchestrator that reads `phase + step_order` and dispatches via `executor_function`. Major architectural work — estimated 200+ LOC and meaningful behavior change. **ARCHITECTURAL DECISION REQUIRED.** |

**Most of the divergences are stale-table issues that should be
resolved by updating the table to match code.** Two are real
architectural decisions (payroll_feasibility_repair re-wire and
unified_convergence_decision re-enable / de-list).

The fact that the table is consulted for individual-step telemetry
naming but NOT for top-level call ordering is the deepest finding here:
the table is **half-applied as source-of-truth**. Either it should be
the canonical sequence (and the orchestrator should read from it), or
the doctrine should be updated to say it's a step-name registry only.

---

## 1. Pipeline diagram (top-level call order)

```
HTTP POST /api/intake-consult/system-run
  └─ post_intake_consult_system_run_handler           [api_handlers/intake_consult.py:7245]
       └─ _run_planning_system_for_draft (= _unified)  [intake_consult.py:7035]
            ├─ PHASE A. prepare_initial_grid_for_draft [initial_grid/runner.py:30]
            │    ├─ shared_context_build              [runner.py:434]
            │    ├─ ops/market/people/financials loads [runner.py:444-475]
            │    ├─ base_year1 / year1_drivers        [runner.py:481-497]
            │    ├─ marketing_model_json              [runner.py:504]
            │    ├─ forecast_starting_ppe_decision    [runner.py:526]
            │    ├─ sync_result (CashEquity_OwnersCap) [runner.py:564]
            │    ├─ r_and_d_applicability_decision    [runner.py:619] (conditional)
            │    ├─ r_and_d_policy_result             [runner.py:652]
            │    ├─ balance_sheet_contextual_seed     [runner.py:679-722]
            │    ├─ planning_choice                   [runner.py:765]
            │    ├─ ★ stage_ramp_contract             [runner.py:815]   ─┐
            │    │   = _stage_ramp_contract_python_first_with_handler   │ PROCESS 1
            │    │     [intake_consult.py:94] → _engage_stage_ramp_handler ┘
            │    ├─ (conditional, lease-bearing branch)
            │    │   ├─ capacity_model_input_json    [runner.py:1030]
            │    │   ├─ next_model_input_json        [runner.py:1072]
            │    │   ├─ next_finmo_json              [runner.py:1098]
            │    │   ├─ payroll_reapply_result       [runner.py:1172]
            │    │   ├─ ★ _build_and_apply_payroll_schedule [runner.py:1209] ─┐
            │    │   │     = estimate_payroll_headcount_schedule_with_gpt    │ PROCESS 2
            │    │   │       [schedule.py:2241+, hard-cap 10 rounds, 180s]   ┘
            │    │   └─ _assert_global_invariants_via_sequence [runner.py:1224]
            │    ├─ (default branch)
            │    │   └─ ★ _build_and_apply_payroll_schedule [runner.py:1252]
            │    │       _assert_global_invariants_via_sequence [runner.py:1258]
            │    ├─ quarter_grid_context_payload      [runner.py:1296]
            │    ├─ planning_result                    [runner.py:1323]
            │    ├─ validated_quarter_grid_plan        [runner.py:1377]
            │    ├─ ★ grid_application_result          [runner.py:1408]    ── PROCESS 3
            │    └─ ★ _assert_global_invariants_via_sequence [runner.py:1469]
            │
            └─ PHASE B. _run_unified_post_grid_system_run [intake_consult.py:6958]
                 └─ run_target_seeking_orchestrated_system_run [solver/orchestrator.py:1024]
                      ├─ pre-flight pass _run_target_seeking_pass [orchestrator.py:1316]
                      ├─ INNER RUNNER — BYPASSED [orchestrator.py:1342]
                      │   ("phase_8_inner_runner_bypassed" — legacy convergence runner dead code)
                      ├─ post-flight assertion + repair pass [orchestrator.py:1383-1410]
                      ├─ cascade [orchestrator.py:1459-1530, walks tiers 1-7]
                      ├─ ★ restoration_loop (target-driven, 4 metrics)    ─┐
                      │     run_restoration_loop [orchestrator.py:1933]    │ PROCESS 4
                      │     → restoration_loop.py:line 1265 (ITERATING_STILL),
                      │       1240 (EXHAUSTED via semantic/formal),
                      │       1138 (EXHAUSTED via forward-looking forecast),
                      │       1159 (LANDED)                              ┘
                      ├─ ★ GPT exhaustion handler — Site 1 [orchestrator.py:1977]
                      │     run_gpt_exhaustion_handler [exhaustion_handler/handler.py:747]
                      │     TRIGGER: restoration_result.status == EXHAUSTED
                      ├─ ★ Pre-cash GPT-authorable gate [orchestrator.py:2121]
                      │     _evaluate_gpt_authorable_pre_cash_checks [orchestrator.py:263]
                      │     ★ GPT exhaustion handler — Site 2 [orchestrator.py:2130]
                      │     TRIGGER: gate_violations AND NOT _gate_handler_already_ran
                      ├─ ★ Cash strategy [orchestrator.py:2281]            ─┐
                      │     run_mode_based_cash_strategy                    │ PROCESS 5
                      │     [cash_strategy/orchestrator_invocation.py:149]  │
                      │     ★ engage_funding_handler_on_violations          │
                      │     [orchestrator_invocation.py:618]                ┘
                      ├─ ★ Realism gate [orchestrator.py:2355]              ── PROCESS 6
                      │     validate_industry_realism_bands
                      ├─ solver_target_assertion [orchestrator.py:2472]
                      ├─ debt_schedule snapshot [orchestrator.py:2505]
                      ├─ capital_lease snapshot [orchestrator.py:2527]
                      ├─ pre_finalize_persist marker (SQL UPDATE) [orchestrator.py:2606]
                      ├─ ★ run_finalize_post_intake_validation             ─┐
                      │     [finalize_post_intake.py:455]                   │ PROCESS 7
                      │     ~15 validators, listed in §2.7                  ┘
                      └─ _persist_unified_convergence_state [orchestrator.py:2749]

  ★ AFTER orchestrator returns:
       └─ ★ verify_run_acceptance [intake_consult.py:7424]                  ── PROCESS 8
            [post_intake_acceptance/gate.py:660], 16 checks
```

★ = process audited in §2. Eight consolidated processes; the legacy
`post_intake_convergence/runner.py:615` inner runner is **bypassed
unconditionally** by `inner_result = {"status":
"phase_8_inner_runner_bypassed"}` at [orchestrator.py:1342](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342)
and is not part of the live pipeline.

## 2. Per-process Q1–Q6 audit

### 2.1 PROCESS 1 — Stage ramp contract authoring

**Q1. Where it runs.**
Inside `prepare_initial_grid_for_draft` at [runner.py:815](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L815),
invoked via `_stage_ramp_contract_python_first_with_handler` at
[intake_consult.py:94-138](../../python/api_handlers/intake_consult.py#L94-L138).
The wrapper calls `_engage_stage_ramp_handler` (Python proposes →
validator → handler-on-failure).
- Immediately before: `planning_choice` ([runner.py:765](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L765)).
- Immediately after: `_build_and_apply_payroll_schedule` (process 2).

**Q2. What it produces.**
Returns `stage_ramp_contract` dict — ramp shape, target margins, capacity
curve, cost ratio caps. Stamped into `shared_context["stage_ramp_contract_decision"]`
([runner.py:861-865](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L861-L865))
and `planning_context_summary_json["stage_ramp_contract"]`
([runner.py:867-870](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L867-L870)).
The output is the canonical state — no candidate-state pattern; the
returned contract IS what downstream consumes.

**Q3. Checks on its output.**
- `_validate_stage_ramp_contract_payload_for_handler` (called inside `_engage_stage_ramp_handler` per [p3_21_part1_audit_stage_ramp_handler.md:33-38](p3_21_part1_audit_stage_ramp_handler.md#L33-L38)). Schema/value-range check on the Python-proposed contract. Fires **in-loop** before the handler engages.
- Inside the handler session — same canonical validator re-runs after the GPT-tool-calling session per [iter_19_machinery_fail_fast_inventory.md:281](iter_19_machinery_fail_fast_inventory.md#L281).
- Downstream: stage-ramp expense path + profitability path checks at the pre-cash gate ([orchestrator.py:299, 327](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L299-L356)) and again at finalize (called via `assert_post_intake_global_invariants` from [finalize_post_intake.py:606-617](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L606-L617)).
- Tolerance: contract-level (P3.20 Part 3 Stage 5 widened to `1.10` for the FINMO-side cost-ratio diff and `0.005` for the margin floor; see [orchestrator.py:69-75](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L69-L75) for the FINMO-field → metric mapping the gate uses).
- Diagnostic on failure: `RuntimeError("stage_ramp_handler_exhausted: ...")` ([intake_consult.py:136-138](../../python/api_handlers/intake_consult.py#L136-L138)).

**Q4. When handler engages.**
Trigger: validator raises on the Python-built contract → `engage_stage_ramp_handler_on_validator_failure` ([p3_21_part1_audit_stage_ramp_handler.md:12](p3_21_part1_audit_stage_ramp_handler.md#L12), handler.py:352). Fires on **ANY validator failure** (P3.21 Property 2 audit: COMPLIANT). Re-engagement on residual rejection is the same path.

**Q5. Authority.**
Stage ramp contract fields (ramp shape, target margins, capacity curve, cost ratio caps) per doctrine.md:334. **Complete list** — the audit memo [p3_21_part1_audit_stage_ramp_handler.md](p3_21_part1_audit_stage_ramp_handler.md) confirms no leakage outside that scope.

**Q6. Timing.**
Validator and handler are co-located inside the same `_engage_stage_ramp_handler` call. The downstream checks (pre-cash gate, finalize) fire much later but route through the GPT exhaustion handler at Site 2 ([orchestrator.py:2130](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2130)) — which has authority over the underlying lever values, not the stage ramp contract itself. **In-loop only for the contract authoring** — no timing mismatch at this layer.

---

### 2.2 PROCESS 2 — Payroll iterative refinement

**Q1. Where it runs.**
Nested function `_build_and_apply_payroll_schedule` inside `prepare_initial_grid_for_draft` at [runner.py:873](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L873). Called at **two sites** depending on branch:
- Lease-bearing branch: [runner.py:1209](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1209) (after `next_finmo_json`).
- Default branch: [runner.py:1252](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1252).
Both call `estimate_payroll_headcount_schedule_with_gpt` at [schedule.py:2241+](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2241).

**Q2. What it produces.**
`schedule_payload` dict: OEWS title list, per-quarter `starting_fte`/`hires`/`ending_fte`, `capacity_labor_model`, `labor_intensity_class`, `wage_positioning_tier`, `wage_positioning_multiplier`, `target_payroll_percent_of_revenue`, `capacity_units_per_supporting_fte`, benefits percent. Returned at [schedule.py:2601](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2601). Output is canonical (no candidate state).

**Q3. Checks on its output.**

| Check | File:line | When | Diagnostic on fail |
|---|---|---|---|
| Layer A.1/A.2 contract validation | [schedule.py:2584](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2584) `validate_payroll_headcount_contract_payload` | In-loop per round | feedback packet to next round |
| Layer A.3 economic feasibility (PROJECTED finmo) | [schedule.py:2596-2600](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2596-L2600) `_assert_payroll_contract_economic_feasible_for_retry` → [schedule.py:1933-1956](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1933-L1956) | In-loop per round, against `projected_finmo_json = build_python_finmo_json(payroll_model_input_json)` | feedback packet |
| Global feasibility (FULLY-APPLIED finmo) | [schedule.py:3407-3433](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3407-L3433) `assert_payroll_revenue_feasibility` | After grid application — `_assert_global_invariants_via_sequence` [runner.py:1224, 1258, 1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1224) | HARD-FAIL `payroll_revenue_economic_feasibility_failed` |
| Pre-call budget guard | [schedule.py:2422-2436](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2422-L2436) | In-loop, before each GPT call | HARD-FAIL `payroll_headcount_contract_timeout` |
| Post-call budget guard | [schedule.py:2536-2549](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2536-L2549) | In-loop, after each GPT call | HARD-FAIL `payroll_headcount_contract_timeout` |
| Round-count drift | [schedule.py:2521-2526](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2521-L2526) | In-loop | HARD-FAIL machinery |
| State-intact invariant | [schedule.py:2414-2418](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2414-L2418) | In-loop per round | HARD-FAIL machinery |
| Exhausted (10 rounds) | [schedule.py:2627-2640](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2627-L2640) | After loop exits without acceptance | HARD-FAIL `payroll_iterative_refinement_exhausted` |
| Reconciliation (payroll lever ↔ headcount totals) | [finalize_post_intake.py:678-693](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L678-L693) `_assert_payroll_schedule_reconciles` | At finalize | error appended; finalize re-raises |

**Q4. When handler engages.**
This is **GPT-as-authoring-source**, not handler-on-failure (doctrine §6 + [p3_21_part1_audit_payroll_iterative_refinement.md:22-53](p3_21_part1_audit_payroll_iterative_refinement.md#L22-L53)). Trigger: validator failure inside the loop → next round (up to 10).
- Trigger expression: `except RuntimeError as exc:` at [schedule.py:2613](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2613) catches validator/feasibility failures and feeds them back via `_build_payroll_iterative_feedback_packet` ([schedule.py:2616-2620](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2616-L2620)).
- `PostIntakePreconditionFailed` re-raises immediately ([schedule.py:2602-2612](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2602-L2612)) — machinery violations don't loop.

**Q5. Authority.**
Per [p3_21_part1_audit_payroll_iterative_refinement.md:44-49](p3_21_part1_audit_payroll_iterative_refinement.md#L44-L49):
- OEWS title selection (from NAICS catalog).
- Per-quarter FTE schedule (`starting_fte`, `hires`, `ending_fte`).
- `capacity_labor_model`, `labor_intensity_class`, `wage_positioning_tier`, `wage_positioning_multiplier`, `target_payroll_percent_of_revenue`, `capacity_units_per_supporting_fte`, benefits percent.

**Does NOT have authority over** (explicit doctrine + [intake_consult.py docstring at 7110+]):
- Revenue drivers: Unit Price, Capacity, Utilization.
- Stage ramp shape/targets.
- COGS%, G&A%, Marketing%, R&D%, Rent%, SGA%.
- AR/AP/Inventory days, deferred revenue %, prepaid %.
- Debt / equity / distributions.

**Q6. Timing.**
- Layer A.1/A.2/A.3 fire IN-LOOP — refinement can react.
- **Global feasibility check fires STAGE-BOUNDARY** at [runner.py:1224, 1258, 1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1224) — AFTER grid application, BEFORE refinement returns. The refinement has already exited successfully when this check runs. The check operates on a **DIFFERENT FINMO** (fully-applied) than what the Layer A.3 in-loop check saw (payroll-only projection).
- Reconciliation fires at FINALIZE — far downstream.
- This is **CareFirst's pattern** (P3.23a Draft 2): in-loop validators accept; stage-boundary global check rejects on a different state; no handler with revenue-driver authority sits between intake and the global check.

---

### 2.3 PROCESS 3 — Quarter-grid build + apply (initial-grid finalize)

**Q1. Where it runs.**
Inside `prepare_initial_grid_for_draft`:
- `quarter_grid_context_payload` [runner.py:1296](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1296)
- `planning_result` [runner.py:1323](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1323)
- `validated_quarter_grid_plan` [runner.py:1377](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1377)
- `grid_application_result` [runner.py:1408](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1408)
- `_assert_global_invariants_via_sequence` [runner.py:1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1469).

**Q2. What it produces.**
`applied_model_input_json` (the model_input after all initial-grid drivers stamped in) + `applied_finmo_json` (full-horizon FINMO computed from the applied model_input). These become the starting state for Phase B (target-seeking orchestrator).

**Q3. Checks.**
- `assert_r_and_d_applicability_policy_applied` [runner.py:1455](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1455).
- `_assert_global_invariants_via_sequence` [runner.py:1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1469) calls `assert_post_intake_global_invariants` from `fail_fast/post_intake_fail_fast/fail_fast.py:1989+` which itself wraps:
  - `assert_payroll_revenue_feasibility` (already covered in §2.2).
  - Stage-ramp expense path applied.
  - Stage-ramp profitability path applied.
  - Other invariants per the post-intake fail-fast module.

All fire as STAGE-BOUNDARY hard-fails with no handler retry path at this point — the comment at [runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468) explicitly says "post-quarter-grid feasibility violations now hard-fail directly — surfacing the deeper issue rather than papering over with another rebuild."

**Q4. Handler engagement.** None. This is a terminal gate at the end of Phase A. **All failures here are unhandled hard-fails.**

**Q5. Authority.** N/A — no handler.

**Q6. Timing.**
This is the **boundary** between Phase A (initial grid) and Phase B (post-grid orchestrator). Every check that fires here is a stage-boundary hard-fail. Downstream handlers (target-seeking, restoration, GPT exhaustion, funding) **never run** if a check here fails — the run terminates before Phase B begins. This is by design per the [runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468) docstring; CareFirst (Draft 2) hit `assert_payroll_revenue_feasibility` here and ended the run before any Phase B handler could see the state.

---

### 2.4 PROCESS 4 — Target-seeking restoration loop / cascade / GPT exhaustion handler Site 1

**Q1. Where it runs.**
Phase B, inside `run_target_seeking_orchestrated_system_run`:
- Pre-flight target-seeking pass [orchestrator.py:1316-1328](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1316-L1328).
- Inner runner BYPASSED [orchestrator.py:1342-1347](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342-L1347).
- Post-flight repair pass [orchestrator.py:1389-1410](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1389-L1410).
- Cascade tier walk [orchestrator.py:1459-1530](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1459-L1530).
- Restoration loop [orchestrator.py:1933-1959](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1933-L1959).
- GPT exhaustion handler Site 1 [orchestrator.py:1977-2041](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977-L2041).
- Immediately before: pre-flight target-seeking pass; immediately after: pre-cash gate (process 5).

**Q2. What it produces.**
Updates `final_model_input_json` + `final_finmo_json` in place. The restoration loop targets 4 metrics (gross_margin, ebitda_margin, current_assets_minus_cash, current_liabilities_to_revenue) across all 20 quarters. The cascade may also call the inner runner with overrides ([adaptation_cascade.py:414-452](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L414-L452)).

**Q3. Checks on output.**
- Cascade trigger check (post-flight assertion + abort_reason): `_hard_fail_violations_from_assertion` [orchestrator.py:1383-1387, 1421-1425](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1383-L1425). Reads **solver_target_assertion**, not realism gate.
- Restoration loop exit-state checks ([restoration_loop.py:1109, 1170-1200, 1240, 1265](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1109)) determine which of {LANDED, EXHAUSTED, FAILED, ITERATING_STILL} returns.

**Q4. When handler engages (Site 1).**
Trigger expression at [orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977):
```python
if restoration_result.status == RestorationStatus.EXHAUSTED:
    handler_result = run_gpt_exhaustion_handler(...)
```
**Engages on:** EXHAUSTED only.
**Does NOT engage on:** LANDED, FAILED, **ITERATING_STILL** ([restoration_loop.py:1265](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1265)).
ITERATING_STILL is the "max outer passes reached without LANDED or EXHAUSTED" path — exactly **Anderson & Blake's exit state** (P3.23a Draft 1). The handler has authority over all 3 of A&B's failing metrics ([handler.py:105-125](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L105-L125)) but the trigger doesn't fire.

Two sub-issues that compound this gap (already audited in P3.23a):
1. `semantic_exhaustion` test [restoration_loop.py:1189-1200](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1189-L1200) under-counts when targets hit `max_inner_iterations_reached` — the target is counted in `attempted_count` but not in `bound_pinned + converged`, so the threshold `len(bp)+len(c) >= attempted_count` is False.
2. Forward-looking forecast classifier at [restoration_loop.py:1128-1156](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1128-L1156) only fires inside the LANDED branch (gated by `if all(final_viability...)` at line 1109). If any one viability metric is False, this classifier never runs and realism-band hard-fails are not surfaced as `forecast_failures`.

**Q5. Authority.**
Restoration handler (= GPT exhaustion handler): 12 P&L levers + 5 WC levers per [doctrine.md:332](doctrine.md#L332). The 5 WC levers are enumerated at [handler.py:105-111](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L105-L111): AR Days, AP Days, Inventory Days, Deferred Revenue %, Prepaid %.

**Q6. Timing.**
- Restoration loop runs IN-LOOP (its own outer-passes machinery).
- The cascade itself can re-call the inner runner ([adaptation_cascade.py:414-452](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L414-L452)) — but only if the post-flight repair pass leaves hard_fail residuals against **solver targets**, not against realism bands.
- The realism gate ([orchestrator.py:2355](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2355)) fires DOWNSTREAM of cascade + restoration + Site 1 handler. **A realism-band failure here is past the point where Site 1 could react.** Pattern 2 timing-mismatch site **confirmed**.

---

### 2.5 PROCESS 5 — Cash strategy with funding handler

**Q1. Where it runs.**
`run_mode_based_cash_strategy` at [orchestrator_invocation.py:149](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L149), invoked from orchestrator at [orchestrator.py:2281](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2281). Immediately before: pre-cash gate (process at 2121); immediately after: realism gate (process 6).

**Q2. What it produces.**
Updates `final_model_input_json` + `final_finmo_json` with mode-based cash strategy lever updates (debt issuance, debt repayment, owner's capital, other equity, distributions). Stage 1 of P3.20 made these updates **non-revertible** (`keep_changes` no longer atomically reverts).

**Q3. Checks on its output.**
- `_validate_cash_strategy_post_pass` (called inside) returns `cash_post_validation` with these categories:
  - `cash_buffer_violations`
  - `cash_distribution_violations`
  - `cash_surplus_ceiling_violations`
  - `cash_contract_failures`
  - `hard_rule_assessment` (cross-quarter)
- Reference list at [orchestrator_invocation.py:552-570](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L552-L570).
- `not keep_changes` (line 571-572) is the consolidated "any-validator-popped" boolean.

**Q4. When handler engages.**
Funding handler at [orchestrator_invocation.py:618](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L618). Trigger expression at [line 571-573](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L571-L573):
```python
if (
  not keep_changes
  and isinstance(cash_strategy_second_pass_result, dict)
):
    cash_funding_handler_result = engage_funding_handler_on_violations(...)
```

**Engages on: any validator failure** (per Stage 2 fix documented at [lines 520-549](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L520-L549)). All four categories (buffer / distribution / surplus / contract) plus hard_rule_assessment are passed in via Stage 3b broadening. This is the canonical Property 2-compliant trigger (per [p3_20_part2_validator_placement_audit.md](p3_20_part2_validator_placement_audit.md)).

**Q5. Authority.**
Per doctrine.md:333: `debt issuance, debt repayment, owner's capital, other equity, distributions, cash_strategy_mode override`.

The handler input payload was broadened at Stage 3b ([orchestrator_invocation.py:626-630](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L626-L630)) so the GPT session sees the **full failure picture** (buffer + distribution + surplus + contract + hard_rule), but the levers it can move are unchanged.

**Q6. Timing.**
- Cash post-validation fires AS PART OF the cash strategy step (IN-LOOP).
- Funding handler fires IN-LOOP on the boolean `not keep_changes`.
- Post-handler re-validation fires IN-LOOP at [orchestrator_invocation.py:639-668](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L639-L668).
- DOWNSTREAM cash-related checks: `assert_post_intake_cash_buffer_integrity` at [finalize_post_intake.py:641-648](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L641-L648). This is post-cash-strategy and post-realism gate — but if the cash strategy + funding handler resolved cash issues, the finalize check passes. If they didn't, finalize hard-fails with no further retry.
- **No Pattern 2 timing-mismatch at this layer.** Cash post-validation → funding handler is co-located. Funding handler is the only handler with cash-side authority and it engages on the canonical "any cash validator popped" signal.

---

### 2.6 PROCESS 6 — Realism gate (post-cash, pre-finalize)

**Q1. Where it runs.**
`validate_industry_realism_bands` at [orchestrator.py:2355](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2355). Inputs: `final_model_input_json` + `final_finmo_json` (post-cash). Phase 3 calibrated targets are passed via solver_input lookup ([orchestrator.py:2345-2353](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2345-L2353)).

**Q2. What it produces.**
`realism_gate_payload` dict with `results` (per-metric / per-quarter rows), `warnings`, `result_count`, `band_source` provenance per row. On hard_fail it raises `RealismBandViolation` with partial results which the orchestrator catches at [line 2370-2389](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2370-L2389) and preserves into `realism_gate_payload`. This becomes `realism_memo_json` (built at [orchestrator.py:2421-2429](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2421-L2429)).

**Q3. Checks.**
The realism gate IS the check — it raises `RealismBandViolation` on first per-quarter hard_fail. Results are stored regardless of whether the gate raised.

**Q4. Handler engagement.**
**NONE in the post-cash window.** The handler that previously could engage here (silod cascade re-fire) was **retired** at [orchestrator.py:2401-2418](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2401-L2418):
```python
# Phase 9 P3 — silo'd cascade re-fire on realism hard_fails RETIRED.
# ... replacement is the target-driven restoration loop in
# post_intake_target_solver/, wired into _run_post_cascade_completion
# above the cash strategy step.
completion_trace["realism_remediation"] = {
  "attempted": False,
  "status": "retired_phase_9_p3",
  "reason": "silod_cascade_replaced_by_target_driven_restoration_loop",
}
```

The replacement (restoration loop) runs UPSTREAM at [orchestrator.py:1933](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1933) and DOES target realism bands directly. But its trigger to escalate to the handler is `EXHAUSTED` only (process 4 Q4).

**Q5. Authority.** N/A — no handler at this site.

**Q6. Timing.**
The realism gate at line 2355 is DOWNSTREAM of restoration_loop, GPT exhaustion handler Site 1, pre-cash gate handler Site 2, and cash strategy. **Any realism-band hard-fail surfacing here is past every handler with authority over realism bands.**
- The intended design: restoration loop pre-empts realism failures by targeting the bands directly. If it succeeds → LANDED → realism gate passes.
- The actual gap: if restoration returns ITERATING_STILL (not EXHAUSTED), it doesn't trigger the Site 1 handler, but it ALSO doesn't necessarily produce a realism-passing state. The realism gate then sees the unfinished work.

**This is the second half of Anderson & Blake's pattern**: the realism gate is the "downstream check" that the upstream handler never got to react to.

---

### 2.7 PROCESS 7 — Finalize validation

**Q1. Where it runs.**
`run_finalize_post_intake_validation` at [finalize_post_intake.py:455](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L455), invoked from orchestrator at [orchestrator.py:2679](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2679). Immediately before: pre_finalize_persist marker UPDATE; immediately after: `_persist_unified_convergence_state`.

**Q2. What it produces.**
`finalize_result` dict containing `solver_target_assertion` (if computed inside), `status`, plus internal `errors` list. On non-empty errors → raises (under CONVERGENCE_TEST_MODE the exception propagates per [orchestrator.py:2712-2716](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2712-L2716)).

**Q3. Checks (in order, all FINALIZE-timing).**

| # | Check | File:line |
|---|---|---|
| 1 | `runtime_table_integrity` | [finalize_post_intake.py:548](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L548) |
| 2 | `required_process_sequence` | [finalize_post_intake.py:552](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L552) |
| 3 | `process_context_errors` | [finalize_post_intake.py:556](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L556) |
| 4 | `process_step_contexts` for 5 step keys | [finalize_post_intake.py:563-576](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L563-L576) |
| 5 | mapping_formula_integrity | [finalize_post_intake.py:579-602](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L579-L602) |
| 6 | `assert_post_intake_global_invariants` (includes payroll_revenue_feasibility, stage_ramp_expense, stage_ramp_profitability, etc.) | [finalize_post_intake.py:606-637](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L606-L637) |
| 7 | `assert_post_intake_cash_buffer_integrity` | [finalize_post_intake.py:641-648](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L641-L648) |
| 8 | `payroll_headcount_schedule_missing` | [finalize_post_intake.py:650-651](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L650-L651) |
| 9 | `debt_schedule_missing` | [finalize_post_intake.py:652-653](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L652-L653) |
| 10 | `_assert_forecast_horizon_complete` | [finalize_post_intake.py:654-659](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L654-L659) |
| 11 | `_assert_model_input_values_complete` | [finalize_post_intake.py:660-663](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L660-L663) |
| 12 | `_assert_finmo_values_complete` | [finalize_post_intake.py:664-667](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L664-L667) |
| 13 | `_assert_revenue_formula_reconciles` | [finalize_post_intake.py:668-672](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L668-L672) |
| 14 | `_assert_payroll_schedule_reconciles` | [finalize_post_intake.py:674-695](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L674-L695) |
| 15 | `_assert_debt_schedule_reconciles` | [finalize_post_intake.py:697-716](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L697-L716) |
| 16 | `_assert_capital_lease_schedule_reconciles` | [finalize_post_intake.py:721-729](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L721-L729) |
| 17 | `balance_sheet_driver_finalize_errors` | [finalize_post_intake.py:730-742](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L730-L742) |
| 18 | `balance_sheet_std_ltd_coherence_errors` | [finalize_post_intake.py:743-753](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L743-L753) |
| 19 | `balance_sheet_reconciliation_errors` | [finalize_post_intake.py:754-764](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L754-L764) |
| 20 | `_assert_cash_phase_trace_complete` | [finalize_post_intake.py:765-785](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L765-L785) |
| 21 | solver_target_assertion (passes through) | [finalize_post_intake.py:794+](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L794) |

All append to `errors`; finalize raises on non-empty errors. Under test mode the orchestrator propagates the exception. **Every check fires at FINALIZE timing.**

**Q4. Handler engagement.** None. Finalize is terminal.

**Q5. Authority.** N/A.

**Q6. Timing.**
All FINALIZE-timing. Any failure here is past every adaptation handler — there is no retry path. The intent (per the doctrine and Phase 9 P3.10 work) is that all conditions finalize checks for should have been satisfied by upstream processes/handlers. The actual failure modes when finalize raises are typically:
- Mapping integrity / structural drift (no handler authority over schema).
- Global invariants (stage_ramp + payroll_revenue + balance_sheet — partially handler-addressable upstream).
- Cash buffer integrity (funding handler authority — should have been resolved by cash strategy).
- Reconciliation checks (payroll/debt/lease vs FINMO — schema integrity, no handler).

**There's no handler with authority that fires AFTER finalize.** Pattern 2 risk is one stage upstream: if an upstream handler with authority over X didn't engage but X subsequently trips finalize, we get exactly the timing-mismatch shape.

---

### 2.8 PROCESS 8 — Acceptance gate

**Q1. Where it runs.**
`verify_run_acceptance` at [post_intake_acceptance/gate.py:660](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L660). Called from the API handler at [intake_consult.py:7424](../../python/api_handlers/intake_consult.py#L7424) AFTER `_run_planning_system_for_draft` returns successfully. Reads persisted state from `intake_consult_drafts` table; does not re-compute the run.

**Q2. What it produces.**
`acceptance_verdict` dict with `passed` bool, `failed_checks` list, per-check `detail`, and `field_snapshot`. Persisted to `planning_runs.acceptance_verdict_json`. **If `passed: False`, the API returns HTTP 500 with the verdict** ([intake_consult.py:7717+](../../python/api_handlers/intake_consult.py#L7717)).

**Q3. Checks (in order, from [gate.py:687-737](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L687-L737)).**

| # | Check name | Reads | Source check function |
|---|---|---|---|
| 1 | `stage_reached_finalize` | planning_runs.current_stage | [gate.py:160-167](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L160) |
| 2 | `cascade_landed_tier_set` | planning_runs.cascade_landed_tier | [gate.py:169-173](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L169) |
| 3 | `plan_confidence_recorded` | planning_runs.plan_confidence | [gate.py:175-178](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L175) |
| 4 | `realism_gate_provenance_recorded` | realism_memo_json[*].band_source presence | [gate.py:180-225](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L180) |
| 5 | `realism_gate_no_hard_fail_violations` | realism_memo_json[*].status hard_fail-like | [gate.py:228-273](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L228) |
| 6 | `solver_target_assertion_checked` | planning_run_json.cash_strategy_second_pass_result.post_intake_finalize_validation.solver_target_assertion.checked | [gate.py:304-313](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L304) |
| 7 | `solver_target_assertion_no_hard_violations` | same path | [gate.py:315-330](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L315) |
| 8 | `revenue_not_flat_q1_q10` | finmo_json.quarter_rows[].revenue | [gate.py:332-373](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L332) |
| 9 | `cash_legitimate_q1_q10` | finmo_json.quarter_rows[].cash | [gate.py:375-414](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L375) |
| 10 | `current_assets_positive_q1_q10` | finmo_json.quarter_rows[].current_assets | [gate.py:614-658](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L614) |
| 11 | `net_income_trajectory_viable` | finmo_json | [gate.py:416-442](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416) |
| 12 | `cash_health_operational_not_debt_funded` | finmo_json | [gate.py:444-466](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L444) |
| 13 | `cascade_exercised_or_documented` | planning_run + planning_run_json + realism_memo | [gate.py:468-512](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L468) |
| 14 | `phase_3_calibrated_bands_consulted` | realism_memo | [gate.py:514-546](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L514) |
| 15 | `balance_sheet_growth_plausible` | finmo_json | [gate.py:548-580](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L548) |
| 16 | `viability_timeline_landed` | realism_memo | [gate.py:582-612](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L582) |

**Q4. Handler engagement.** None. Acceptance is post-run, read-only.

**Q5. Authority.** N/A.

**Q6. Timing.**
All checks fire AFTER the entire orchestrator pipeline (and after `_run_planning_system_for_draft` returns). **No handler runs after the acceptance gate** — its failures cannot be adapted to. This is by design (the gate is the final yes/no on the run), but the architectural consequence is that any check the gate runs whose failing condition is fixable by an upstream handler — but where the upstream handler did NOT engage — is exactly the Pattern 2 timing-mismatch shape.

This is **Anderson & Blake's pattern**:
- Check #5 `realism_gate_no_hard_fail_violations` fails post-hoc on realism band violations.
- Restoration handler has authority over the failing bands.
- But the handler's Site 1 trigger (EXHAUSTED only) didn't fire because restoration returned ITERATING_STILL (process 4 Q4).

---

## 3. System-level answers (X1–X6)

### X1. Is there ANY check anywhere with handler-authority + pipeline-timing mismatch?

**Yes — three confirmed sites.** See timing-mismatch matrix in §4. Briefly:

1. **Acceptance gate check #5 `realism_gate_no_hard_fail_violations`** (Anderson & Blake pattern). Handler with authority: GPT exhaustion handler. Trigger gap: restoration returns ITERATING_STILL → no engagement → realism failures persist → acceptance gate catches them post-hoc.

2. **Initial-grid global invariants `assert_payroll_revenue_feasibility`** (CareFirst pattern). Handler with potential authority: NONE in the current architecture for revenue drivers. Payroll iterative refinement converged in-loop on payroll levers but couldn't fix revenue-side issue; check fires stage-boundary with no retry path.

3. **Finalize check #6 `assert_post_intake_global_invariants` (includes payroll_revenue_feasibility, stage_ramp_expense_path, stage_ramp_profitability_path)**. The pre-cash GPT-authorable gate at [orchestrator.py:2121](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2121) already catches stage_ramp_expense and stage_ramp_profitability and routes them to Site 2 handler. **Payroll_revenue_feasibility is NOT in `_GPT_AUTHORABLE_PRE_CASH_CHECK_NAMES`** ([orchestrator.py:57-61](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L57-L61)). If it fires at finalize there's no handler retry path.

### X2. Trigger condition gating per handler

| Handler | Trigger | File:line | Gating behavior |
|---|---|---|---|
| Stage ramp handler | Validator raises | `_engage_stage_ramp_handler` [handler.py:352, 428-461](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L352) | **Any validator failure** — Property 2 compliant per [p3_21 audit](p3_21_part1_audit_stage_ramp_handler.md). |
| Payroll iterative refinement (GPT-as-source) | `except RuntimeError` | [schedule.py:2613](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2613) | **Any validator failure** that's RuntimeError → next round. PostIntakePreconditionFailed re-raises. Property 2 analog compliant per [p3_21 audit](p3_21_part1_audit_payroll_iterative_refinement.md). |
| Restoration / GPT exhaustion — Site 1 | `restoration_result.status == EXHAUSTED` | [orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977) | **NARROW** — only EXHAUSTED. Misses ITERATING_STILL. **Pattern 2 anti-pattern at this trigger.** |
| Restoration / GPT exhaustion — Site 2 | `gate_violations and not _gate_handler_already_ran` | [orchestrator.py:2130](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2130) | Scope is the 3 named checks: `stage_ramp_expense_path_applied`, `stage_ramp_profitability_path_applied`, `balance_sheet_driver_zero_but_applicable` ([orchestrator.py:57-61](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L57-L61)). **NARROW by category** — `payroll_revenue_economic_feasibility_failed` is NOT in the list. |
| Funding handler | `not keep_changes` | [orchestrator_invocation.py:571-573](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L571-L573) | **Any validator failure** (buffer / distribution / surplus / contract / hard-rule). Property 2 compliant per [p3_20_part2_validator_placement_audit.md](p3_20_part2_validator_placement_audit.md). |

**Two narrow triggers.** Site 1 gates on `EXHAUSTED`-only; Site 2 gates on 3 named check categories.

### X3. State propagation after handler returns

| Handler | Output state | Revert path? |
|---|---|---|
| Stage ramp | Re-raises on exhaustion ([intake_consult.py:136-138](../../python/api_handlers/intake_consult.py#L136-L138)) — no revert; refined contract becomes the canonical one | None |
| Payroll iterative (GPT-as-source) | Returned schedule_payload at [schedule.py:2601](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2601) IS the canonical output | None |
| GPT exhaustion Site 1 | Mutates `final_model_input_json` in place; FINMO rebuilt at [orchestrator.py:2004-2008](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2004-L2008); if rebuild fails, model_input stays mutated, FINMO falls back (P3.21 Property 1 audit: COMPLIANT) | **No revert path** — `realism_flags_to_mute` additively merged at [orchestrator.py:2017-2026](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2017-L2026) |
| GPT exhaustion Site 2 | Same mutation pattern; FINMO rebuild at [orchestrator.py:2170-2177](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2170-L2177); Stage 3 of P3.20 closes the rebuild-failure divergence window | None |
| Funding | P3.20 Stage 1 made cash strategy output non-revertible ([orchestrator_invocation.py:671-680](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L671-L680)) | Removed |

**All handlers Property 1 (NEVER REVERT) compliant** at current HEAD. P3.20 Stages 1+2+3 closed every revert site identified.

### X4. Validator state = downstream state (Mirror Flavor 1)

| Handler / process | Validator state | Downstream consumer state | Same? |
|---|---|---|---|
| Stage ramp handler | Canonical validator output | What's stamped into shared_context + planning_context_summary_json | YES |
| Payroll iterative refinement Layer A.3 | `projected_finmo_json` built from `payroll_model_input_json` only ([schedule.py:1932](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1932)) | Fully-applied post-grid FINMO at [runner.py:1224, 1258, 1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1224) checks | **NO** — Pattern 1 divergence. |
| Restoration loop | `post_finmo = build_finmo(model_input)` after each pass | Same FINMO read by `_classify_forecast_exhaustion` ([restoration_loop.py:1128](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1128)) | YES at restoration-internal layer. But realism gate at orchestrator.py:2355 uses post-cash FINMO with `_muted_realism_metrics` filtering — different state. |
| GPT exhaustion Site 1 | Pre-rebuild model_input → handler authors → post-rebuild FINMO | Realism gate sees post-handler model_input (P3.20 Stage 3 single-source rebuild) | YES (per Stage 3 audit) |
| GPT exhaustion Site 2 | Same as Site 1; gate violations recomputed after handler at [orchestrator.py:2193-2200](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2193-L2200) | Cash strategy / realism gate see post-handler state | YES |
| Funding handler | Pre-handler model_input + lever_bounds + buffer_by_q | Post-handler model_input → re-validated by `_validate_cash_strategy_post_pass` at [orchestrator_invocation.py:639-651](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L639-L651) | YES (Stage 3 compliant) |

**One Pattern 1 site confirmed: Payroll Layer A.3 ↔ post-grid global invariants.** Already surfaced in P3.23a Draft 2 analysis. All other validator/downstream pairs use single-source-rebuild state per the Stage 3 work.

### X5. Diagnostic preservation on fail-fast

The Stage 4 inventory ([p3_20_part3_stage4_diagnostic_preservation_audit.md](p3_20_part3_stage4_diagnostic_preservation_audit.md)) confirmed Property 4 across the inventory it covered. P3.23a Draft 3 surfaced one new observation:

- **Timeout-path of payroll iterative refinement does NOT preserve `last_failure_packet`.** The rounds-exhausted path at [schedule.py:2627-2640](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2627-L2640) emits the trajectory; the timeout path at [schedule.py:2422-2436](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2422-L2436) and [2538-2549](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2538-L2549) emits only `round_n`, `elapsed_seconds`, `timeout_seconds`, `hard_cap_rounds`, `source_table`, `step_key`. Not a doctrine §3 violation (the diagnostic does survive to API caller) but cross-path asymmetry.

No other Property 4 gaps detected in this audit.

### X6. Processes the user listed vs. processes in the codebase

| User's list | Codebase mapping |
|---|---|
| Stage ramp (Python + handler) | Process 1 — confirmed |
| P&L / restoration (Python + handler) | Process 4 (restoration loop + GPT exhaustion Site 1 + Site 2 + cascade) — confirmed, expanded |
| Cash (Python + handler) | Process 5 — confirmed |
| Payroll (handler) | Process 2 — confirmed (note: GPT-as-source, not handler-on-failure per doctrine §6) |
| Convergence | Legacy `post_intake_convergence/runner.py:_run_unified_post_grid_system_run` is BYPASSED unconditionally by [orchestrator.py:1342](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342). It is **dead code** in the current pipeline. The "convergence" in production is the target-seeking orchestrator (process 4). |

**Processes the user did not list but the codebase has:**
- Realism gate (process 6).
- Finalize validation (process 7, ~21 sub-checks).
- Acceptance gate (process 8, 16 checks).
- Quarter-grid build + apply (process 3, includes global invariants checks).
- Pre-cash GPT-authorable gate (Site 2, part of process 4).

These are all downstream checks/gates, not new "handler" sites. The user's 5-item list is correct as a handler inventory; the codebase adds 4-5 more **check/gate** sites that interact with the handlers via timing.

## 4. Findings summary — Pattern 2 timing-mismatch matrix

Per the user's addendum: "any check-handler pair where (1) check fires at point P_check, (2) handler runs at point P_handler, (3) P_handler > P_check, (4) check is hard-fail, (5) handler has authority — is a Pattern 2 timing-mismatch site."

Pipeline-order timing scale (1 = earliest):
- 1 = Initial-grid pre-payroll body (runner.py 421-815)
- 2 = Stage ramp authoring (runner.py 815)
- 3 = Payroll iterative refinement loop (schedule.py 2412)
- 4 = Post-payroll initial-grid global invariants (runner.py 1224, 1258, 1469)
- 5 = Phase B pre-flight target-seeking (orchestrator.py 1316)
- 6 = Cascade tier walk (orchestrator.py 1459)
- 7 = Restoration loop (orchestrator.py 1933)
- 8 = GPT exhaustion handler Site 1 (orchestrator.py 1977)
- 9 = Pre-cash GPT-authorable gate / handler Site 2 (orchestrator.py 2121-2200)
- 10 = Cash strategy + funding handler (orchestrator.py 2281, orchestrator_invocation.py 618)
- 11 = Realism gate (orchestrator.py 2355)
- 12 = Solver target assertion (orchestrator.py 2472)
- 13 = Finalize validation (orchestrator.py 2679)
- 14 = Acceptance gate (intake_consult.py 7424)

| # | Check | Fires at | Handler with authority | Handler runs at | P_handler > P_check? | Hard-fail? | Confirmed mismatch? |
|---|---|---|---|---|---|---|---|
| A | Payroll Layer A.1/A.2/A.3 (in-loop) | 3 | Payroll iterative (=GPT-as-source) | 3 | No (co-located) | Yes via feedback packet (loops) | No |
| B | Initial-grid `assert_payroll_revenue_feasibility` (post-payroll global) | 4 | Payroll iterative (within its scope), GPT exhaustion (NOT in scope for `payroll_revenue_economic_feasibility_failed`), Funding (no payroll authority) | 3 (payroll iter completed); 8/9 (exhaustion); 10 (funding) | YES for all handlers with possible relevance | Yes | **YES — CareFirst pattern.** No handler with revenue-driver authority sits between initial-grid global check and intake. Process 3 ends the run on this check. |
| C | Initial-grid `stage_ramp_expense_path_applied` global invariant | 4 | GPT exhaustion (Site 2 has it in scope per [orchestrator.py:58-61](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L58-L61)) | 9 (Site 2) | YES — handler runs LATER | Yes at finalize; also fires at pre-cash gate (Site 2) | Partial. Site 2 covers the recheck at point 9, but if it fires at point 4 (post-payroll/initial-grid global), it hard-fails BEFORE reaching point 9. The "post-quarter-grid feasibility violations now hard-fail directly" comment at [runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468) makes this explicit. |
| D | Cascade post-flight solver_target hard_fails | 6 | Cascade tier walk | 6 (co-located) | No | Yes (raises CascadeAndRestorationExhausted) | No |
| E | Restoration loop forecast realism hard-fails (forward-looking exhaustion path) | 7 | GPT exhaustion (Site 1 via EXHAUSTED-with-forecast-scope) | 8 | Co-located via EXHAUSTED return + Site 1 trigger | Yes | No — when this path engages |
| F | Restoration loop `ITERATING_STILL` exit with realism residuals | 7 | GPT exhaustion (Site 1) — HAS AUTHORITY over the metrics | NEVER (trigger doesn't match ITERATING_STILL) | YES (handler doesn't run at all in this branch) | Realism gate at 11 catches; acceptance check #5 at 14 catches | **YES — Anderson & Blake pattern.** Site 1 trigger is `EXHAUSTED`-only. Two compounding sub-issues: `semantic_exhaustion` under-counts; forecast classifier gated on `all(viability)`. |
| G | Pre-cash gate violations (stage_ramp_expense / stage_ramp_profitability / balance_sheet_driver_zero) | 9 | GPT exhaustion (Site 2) | 9 (co-located) | No | Yes if unfixed (PostIntakePreconditionFailed) | No |
| H | Cash post-validation (buffer/distribution/surplus/contract/hard_rule) | 10 | Funding handler | 10 (co-located) | No | Yes if `not keep_changes` (handler escalation) | No |
| I | Realism gate hard_fail at orchestrator.py:2355 | 11 | None — silod cascade RETIRED at [orchestrator.py:2401-2418](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2401-L2418); restoration loop at 7 is the intended replacement | N/A | N/A (no handler) | Yes (RealismBandViolation caught and recorded; acceptance check #5 surfaces) | **YES (downstream-only)** — restoration loop is the only handler upstream that can address realism bands, and its trigger gap (F) means realism failures slip past it. |
| J | Solver target assertion violations | 12 | Cascade (point 6) is the only handler — runs upstream | N/A | N/A (only fires informationally) | Yes via acceptance check #7 | Partial — cascade already ran before this assertion. If solver-target violations remain at point 12, the cascade exhausted earlier. |
| K | Finalize `assert_post_intake_global_invariants` (re-runs payroll_revenue_feasibility, stage_ramp, etc.) | 13 | Same as B, C (timing-mismatched there); plus no further retry possible | 13 (terminal) | N/A | Yes (under test mode propagates) | If anything new reaches point 13 that wasn't caught at 4 or 9, no handler can react. |
| L | Finalize cash buffer integrity | 13 | Funding handler — ran at 10 | 10 (already ran) | YES (handler earlier) | Yes (raises) | Partial — funding handler's job at point 10 is to leave point 13 clean. If point 13 fails, the funding handler's resolution didn't hold (e.g., FINMO rebuild divergence). P3.20 Stage 3 addressed the divergence at the cash strategy layer. |
| M | Finalize reconciliation checks (payroll/debt/lease ↔ FINMO) | 13 | None (schema integrity, no handler) | N/A | N/A | Yes | No mismatch — these are mechanical integrity. |
| N | Finalize balance_sheet_reconciliation_errors | 13 | None | N/A | N/A | Yes | No mismatch — by design. |
| O | Acceptance check #5 `realism_gate_no_hard_fail_violations` | 14 | GPT exhaustion (point 8, has authority); funding handler (point 10, partial WC overlap) | 8 / 10 | YES (handler earlier) | Yes (acceptance gate fails the run, HTTP 500) | **YES — Anderson & Blake pattern, terminal manifestation.** |
| P | Acceptance check #8 `revenue_not_flat_q1_q10` | 14 | None directly — restoration loop targets revenue indirectly via Unit Price/Capacity/Utilization at point 7 | 7 | YES | Yes | If revenue lands flat, no handler at point 14 can fix it. Restoration at 7 has authority over the inputs. |
| Q | Acceptance check #11 `net_income_trajectory_viable` | 14 | Restoration loop targets ebitda_margin; GPT exhaustion has P&L authority | 7 / 8 | YES | Yes | If trajectory fails here, upstream handlers should have caught it at point 7 (forecast classifier) or 8 (Site 1) — gated by F. |
| R | Acceptance check #16 `viability_timeline_landed` | 14 | Restoration loop targets viability checks at point 7 | 7 | YES | Yes | Same: depends on restoration loop reaching LANDED or escalating EXHAUSTED. |

**Confirmed Pattern 2 timing-mismatch sites: B, C (variant), F/I/O (Anderson & Blake), and the trio P/Q/R (acceptance gate items whose upstream handler-trigger is the F-gap).**

## 5. Gap inventory & proposed fix scope (NOT implemented)

### Gap F-1 — Restoration loop ITERATING_STILL has no handler consumer

**Doctrine class:** Pattern 2 (narrow trigger anti-pattern).
**Location of trigger:** [orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977).
**Location of dead-end state:** [restoration_loop.py:1265](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1265).
**Proposed fix scope:** Widen Site 1 trigger to `status in {EXHAUSTED, ITERATING_STILL}` OR convert ITERATING_STILL into an EXHAUSTED return at the bottom of the outer-pass loop with `_classify_forecast_exhaustion` to populate `failing_metrics`. Estimated LOC: 3–10.
**Risk:** Drafts that currently land via LANDED are unaffected. Drafts whose realism residuals are minor and would survive acceptance might newly route to the handler — but the handler is allowed to attempt fixes; its budget-exhausted path is itself non-destructive (P3.21 audit). Cross-impact: zero for the currently-passing sweep cohort, **assuming the realism gate's hard-fail thresholds are stable**. Doctrine compliance: aligns Site 1 trigger with Property 2.

### Gap F-2 — `semantic_exhaustion` under-counts `max_inner_iterations_reached`

**Doctrine class:** Pattern 2 sub-issue.
**Location:** [restoration_loop.py:1189-1200](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1189-L1200).
**Proposed fix scope:** Include `max_inner_iterations_reached` in the "stuck" tally — either by changing the `len(targets_bound_pinned) + len(targets_converged) >= attempted_count` threshold to also include max-iter targets, OR by classifying `max_inner_iterations_reached` as a third "stuck" status. Estimated LOC: 2–5.
**Risk:** Same as F-1 — broadens EXHAUSTED return; non-destructive. **Best landed together with F-1.**

### Gap F-3 — Forecast classifier gated on `all(viability)`

**Doctrine class:** Pattern 2 sub-issue; coupling gap.
**Location:** [restoration_loop.py:1109-1156](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1109-L1156).
**Proposed fix scope:** Run `_classify_forecast_exhaustion` regardless of full-viability gate, so realism-band hard-fails are surfaced as `forecast_failures` even when one viability check (e.g., loss_window_funded_through_q5) is False. Estimated LOC: 5–15 (refactor of the conditional branch).
**Risk:** This is the one with the highest "cross-impact" — it potentially changes which scope the handler is invoked with for currently-LANDED drafts that happen to have viability gaps. Requires careful test coverage before landing.

### Gap B — CareFirst payroll_revenue gap

**Doctrine class:** Class C (lever-authority gap) AND Pattern 1 (Mirror Flavor 1: payroll-only projected FINMO ≠ post-grid applied FINMO).
**Location:** intake-side gap; check at [schedule.py:3407-3433](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3407-L3433); inner validator at [schedule.py:1932-1956](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1932-L1956).
**Proposed fix scope: ARCHITECTURAL DECISION REQUIRED.** Two possible directions:
1. **Upstream viability gate** at intake or initial-grid pre-payroll — reject business profiles whose revenue is structurally insufficient for any feasible labor cost given high labor intensity. Catches it at point 1, before commitment.
2. **Add `payroll_revenue_economic_feasibility_failed` to `_GPT_AUTHORABLE_PRE_CASH_CHECK_NAMES`** at [orchestrator.py:57-61](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L57-L61) AND expand the GPT exhaustion handler's authority to include revenue drivers (Unit Price, Capacity, Utilization). This violates the current handler-authority partition (doctrine §6) — handler authority gap is intentional.
The current design hard-fails at point 4 by intent ([runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468)) without a retry path. The decision is whether this is the right tradeoff.
**Risk:** High — touches handler authority partition. Not landable without doctrine update.

### Gap 3 — Payroll iterative timeout budget mismatch (Skyward Express)

**Doctrine class:** Budget-tuning bug; secondary Property 4 (diagnostic preservation) sub-observation.
**Location:** [schedule.py:2422-2436](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2422-L2436) (pre-call guard); [schedule.py:2538-2549](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2538-L2549) (post-call guard).
**Proposed fix scope:** Either raise the 180s cap (e.g., to 360s) or lower the 10-round hard cap (e.g., to 4 rounds) so the 180s/round-cap implied per-round latency (18s) matches observed per-round latency (~58s on a large business). Also add `last_failure_packet` to the timeout fail-fast details to bring diagnostic preservation to parity with the rounds-exhausted path. Estimated LOC: 5–15.
**Risk:** Low for the cap tuning — wider budget can't make currently-passing runs fail. Property 4 addition has zero risk to behavior.

### Gap I (informational) — Realism gate has no in-place handler

**Doctrine class:** By design (silod cascade retired). Not a fix candidate on its own — the architectural intent is that the restoration loop pre-empts realism failures.
**Note:** The gap closes if F-1/F-2/F-3 land (restoration → EXHAUSTED → handler with authority).

## 6. Out-of-scope but worth noting

- **Stage ramp handler:** No timing mismatch detected; Property 1/2/3/4 all compliant per P3.21 audit. Already healthy.
- **Funding handler:** Property 1/2/3/4 compliant per P3.20 audits + the cash strategy orchestrator wiring. Already healthy.
- **Payroll iterative refinement** (within its scope): Property 1/2/3/3b/4 analog compliant per P3.21 audit. Its **boundary** with downstream (Pattern 1 divergence at the post-grid global check) is gap B above — NOT a defect in the iterative refinement itself but in the handoff between in-loop projected FINMO and downstream applied FINMO.
- **Cascade (adaptation_cascade.py):** Tier walk is healthy on its own scope (solver-target hard_fails). Not in the realism-band path that drives Anderson & Blake's failure — solver_target_assertion and realism_memo are distinct signals.

## 7. Summary — answer to user's hypothesis

The user's hypothesis: "sequence timing is the architectural issue: checks fire at points in the pipeline where handlers can't react, or handlers fire after the checks that should have triggered them have already hard-failed the run."

**Confirmed for three concrete sites:**
1. **F/I/O** — restoration loop ITERATING_STILL → GPT exhaustion Site 1 doesn't fire → realism gate (process 6) and acceptance check #5 catch the residuals at points 11 and 14 with no further handler available. Anderson & Blake.
2. **B** — initial-grid global `assert_payroll_revenue_feasibility` at point 4 → no handler with revenue-driver authority exists in the pipeline. CareFirst.
3. **G/K** (partial) — `payroll_revenue_economic_feasibility_failed` is not in the pre-cash gate's covered list, so if it fires at point 13 (finalize) there's no retry path; it does fire at point 4 in practice (CareFirst), so the gap is upstream of finalize.

**Refuted for other handlers:**
- Funding handler trigger is correctly wired to "any cash validator popped"; cash post-validation runs co-located with the handler.
- Stage ramp handler trigger is correctly wired to validator failure.
- Payroll iterative refinement's GPT-as-source loop is correctly wired in its own scope.

**Conclusion:** The user's hypothesis is correct, but **the timing mismatch is localized to the restoration-loop ↔ Site 1 handler boundary AND the payroll-vs-revenue-driver authority partition**. The other handler engagement points in the pipeline are Property 2-compliant.

The smallest doctrine-compliant fix that addresses Anderson & Blake's pattern is Gap F-1 + F-2 together (estimated 5–15 LOC). CareFirst's pattern (Gap B) is an architectural decision rather than a discrete fix — it requires a deliberate choice about whether to expand handler authority or insert an upstream viability gate. Skyward's pattern (Gap 3) is independent budget tuning.
