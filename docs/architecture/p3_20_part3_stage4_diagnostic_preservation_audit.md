# Phase 9 P3.20 Part 3 Stage 4 — Diagnostic Preservation Audit

**Outcome:** AUDIT-ONLY.  Zero fail-fasts found INADEQUATE.  Zero
fail-fasts found CLEARED.  Doctrine update lands; no code fixes
required.

## Scope

Every fail-fast in the codebase must produce diagnostic state that
**survives** whatever cleanup paths exist between the raise site
and the persisted run record.  The Stage 1 smoking gun was the cash
post-pass orchestrator atomic-reverting `cash_strategy_second_pass_
result`, which cleared the `cash_contract_failures` metadata the
post-pass validator had just populated.  Stage 1 removed the revert
(commits `ee291e4` at `orchestrator_invocation.py:545-558` and
`convergence/runner.py:3130-3150`).

This audit asks: does that pattern exist anywhere else?

## Method

1. Inventory every fail-fast raise site that carries a diagnostic
   payload.  Two vehicles:
   - `raise PostIntakePreconditionFailed(...)` (structured exception
     from `python/client_intake_and_finmo/fail_fast/common.py`).
     Carries `operation`, `pipeline_stage`, `expected`, `actual`,
     `details` dict, `cause`.
   - `fail_fast_raise(code, message, *, phase, stage, details)`
     (machinery wrapper that produces `FailFastError` under test mode).
     Carries `code`, `phase`, `stage`, `details`.
2. Classify each on two dimensions:
   - **Diagnostic adequacy** — does the `details` dict carry enough
     structured data to debug the failure from one log line?
   - **Survival** — does any upstream try/except / revert / data-
     overwrite path between the raise site and the persisted run
     record clear / overwrite / swallow the diagnostic?
3. Independently grep for data-structure-overwrite vectors (the
   Stage 1 smoking-gun pattern): code that replaces a validator-
   populated dict with a pre-pass deepcopy.

## Inventory (60 fail-fast sites)

Grouped by file.  Each entry: `file:line | operation/code |
details-dict keys`.

### post_intake_capital_lease/schedule.py (10)
- `120 | capital_lease_interest_components_misaligned | [interest_rate]`
- `129 | capital_lease_routing_double_count | [horizon_quarters]`
- `138 | capital_lease_asset_not_depreciating | [depreciation_quarters]`
- `158 | capital_lease_principal_exceeds_obligation | [quarter_index, principal_payment, opening]`
- `427 | capital_lease_builder_balance_drift | [violations]`
- `482 | capital_lease_builder_balance_drift | [violations]`
- `539 | capital_lease_orphaned_schedule_in_workbook | [orphaned_rows]`
- `574 | capital_lease_interest_components_misaligned | [violations]`
- `610 | capital_lease_asset_not_depreciating | [violations]`
- `654 | capital_lease_routing_double_count | [violations]`

### post_intake_cash_strategy/orchestrator_invocation.py (6)
- `246 | cash_strategy_build_context_failed | [cash_strategy_mode, draft_id]`
- `290 | cash_strategy_review_openai_failed | [cash_strategy_mode, draft_id]`
- `339 | cash_strategy_second_pass_plan_failed | [cash_strategy_mode]`
- `367 | cash_strategy_apply_exact_updates_failed | [cash_strategy_mode]`
- `460 | cash_strategy_final_finmo_rebuild_failed | [cash_strategy_mode]` (Phase 9 P3.10 Commit 4 intent, hoisted at Stage 3)
- `496 | cash_strategy_post_pass_validation_failed | [cash_strategy_mode]`

### post_intake_convergence/runtime.py (1)
- `4900 | unified_convergence_test_mode_failure | [strict_failure]` (full strict_failure dict deepcopied in)

### post_intake_funding_handler/handler.py (1, wrapper)
- `90 | funding_handler_machinery_violation (configurable) | varies by caller` (P3.12 machinery wrapper — concrete operation names: `funding_handler_state_corruption_between_rounds`, `funding_handler_budget_decoupling_violation`, `funding_handler_round_count_drift`, `funding_handler_authority_violation`, `funding_handler_output_malformed`, `funding_handler_best_effort_selection_drift`)

### post_intake_funding_handler/tool_calling_session.py (1)
- `580 | funding_handler_tool_calling_session_turn_failed | [tool_calls_used_before_failure, gpt_calls_made_before_failure, budget_extension_triggered, turn_detail, network_retry_exhausted]`

### post_intake_gpt_exhaustion_handler/handler.py (8)
- `355 | gpt_exhaustion_handler_wc_writer_non_numeric_value | [wc_key, lever_id]`
- `372 | gpt_exhaustion_handler_wc_writer_no_rows_for_lever | [wc_key, lever_id, value]`
- `496 | gpt_exhaustion_handler_writer_missing_pnl_anchor | [missing_driver_key, lever_id, present_pnl_driver_keys]`
- `539 | gpt_exhaustion_handler_writer_non_numeric_anchor | [driver_key, lever_id, anchor_raw]`
- `571 | gpt_exhaustion_handler_writer_no_rows_for_lever | [driver_key, lever_id, anchor, q1, q11, q20]`
- `709 | compute_metrics_to_mute_realism_lookup_failed | [gpt_authored_lever_count]`
- `796 | gpt_exhaustion_handler_pre_session_finmo_build | [model_input_section_count]`
- `831 | gpt_exhaustion_handler_module_import | [q1_state]`

### post_intake_gpt_exhaustion_handler/mini_finmo.py (3)
- `245 | mini_finmo_compute_trajectory_invalid_context | []` (msg carries detail)
- `275 | mini_finmo_writer_failed | [anchor_keys]`
- `292 | mini_finmo_build_finmo_failed | [anchor_keys]`

### post_intake_gpt_exhaustion_handler/tool_calling_session.py (3)
- `557 | gpt_exhaustion_handler_tool_calling_session_turn_failed | [tool_calls_used_before_failure, gpt_calls_made_before_failure, budget_extension_triggered, verified_commit_candidate_present, turn_detail, network_retry_exhausted]`
- `794 | gpt_exhaustion_handler_tool_calling_session_no_anchors | [tool_calls_used, gpt_calls_made, budget_extension_triggered, decision_sources, last_viability_checks]`
- `846 | gpt_exhaustion_handler_post_commit_finmo_rebuild | [session_status, tool_calls_used, implied_q11_ebitda_margin, verified_commit_call_n, best_effort_call_n]`

### post_intake_headcount/payroll_validator_translator.py (3)
- `167 | payroll_validator_translator_unmatched_code | [unmatched_codes, remediation]`
- `195 | payroll_validator_translator_malformed_output | [structured_failures_sample]`
- `204 | payroll_validator_translator_malformed_output | [failure]`

### post_intake_headcount/schedule.py (1, wrapper)
- `2010 | payroll_iterative_refinement_machinery_violation (configurable) | varies by caller`

### post_intake_mapping.py (1)
- `3020 | payroll_tier_bounds_mirror_drift | [mismatches, remediation]`

### post_intake_realism/validator.py (3)
- `536 | realism_validator_trajectory_formula_exception | [metric_key, formula_key]`
- `676 | realism_validator_naics_baseline_lookup_failed | [metric_key, business_naics_6]`
- `852 | realism_validator_per_quarter_formula_exception | [metric_key, formula_key, quarter_index]`

### post_intake_runtime_validation/workbook_model_status.py (4)
- `130 | workbook_model_status_workbook_path_missing | [workbook_path]`
- `137 | workbook_model_status_workbook_missing | [workbook_path]`
- `157 | workbook_model_status_read_failed | [workbook_path]`
- `174 | workbook_model_status_fail | [workbook_path, checks_sheet_model_status_cell]`

### post_intake_solver/adaptation_cascade.py (2)
- `690 | adaptation_cascade_tier7_envelope_build | [business_naics_6, business_stage]`
- `730 | adaptation_cascade_tier7_inner_runner | [business_naics_6, business_stage, widened_metric_count, envelope_source]`

### post_intake_solver/joint_feasibility_check.py (2)
- `110 | joint_feasibility_check_envelope_missing | [envelope_keys]`
- `127 | joint_feasibility_check_targets_missing | [targets_keys]`

### post_intake_solver/orchestrator.py (2)
- `236 | payroll_lever_not_applied_before_gate | [upstream_skipped_step, upstream_contract_owner, remediation, doctrine_reference, schedule_quarters_with_payroll, live_value_count]`
- `2200 | pre_cash_gate_gpt_authorable_checks_unfixed_after_handler | [violations_sample, handler_invoked, muted_metric_count]`

### post_intake_solver/structural_feasibility_check.py (2)
- `410 | structural_feasibility_check_insufficient_revenue_inputs | []` (msg carries detail)
- `498 | structural_feasibility_check_no_fixed_cost_components | []` (msg carries detail)

### post_intake_solver/target_seeking_loop.py (1)
- `335 | target_seeking_loop_inner_joint_fit_raised | [iteration, worst_metric, worst_quarter_index, inner_invocation_count]`

### post_intake_stage_ramp_handler/handler.py (1, wrapper)
- `66 | stage_ramp_handler_machinery_violation (configurable) | varies by caller`

### post_intake_stage_ramp_handler/tool_calling_session.py (1)
- `382 | stage_ramp_handler_tool_calling_session_turn_failed | [tool_calls_used_before_failure, gpt_calls_made_before_failure, budget_extension_triggered, turn_detail]`

### post_intake_target_solver/restoration_loop.py (6)
- `250 | restoration_loop_viability_formula_failed | [viability_metric, formula_key]`
- `499 | restoration_loop_band_resolver_baseline_lookup_failed | [target_metric, business_naics_6]`
- `680 | restoration_loop_driver_bound_baseline_lookup_failed | [lookup_metric_key, target_metric, business_naics_6]`
- `854 | forecast_classifier_validator_import_failed | []` (msg carries detail)
- `875 | forecast_classifier_validator_call_failed | [business_naics_6, planning_mode]`
- `905 | forecast_classifier_realism_rows_lookup_failed | []` (msg carries detail)

### post_intake_target_solver/target_solver.py (1)
- `556 | target_solver_realism_formula_evaluation_failed | [target_metric, formula_key, quarter_index]`

### fail_fast/post_intake_fail_fast/fail_fast.py (assertion functions, 6+)
- `456+ | _raise_if_violations | [violation_count, violations]`
- `521 | stage_ramp_revenue_path_not_applied | [stage_ramp_contract_present]`
- `593 | stage_ramp_revenue_path_not_applied | [violation_count, violations, payroll_supported_capacity_authority, rule]`
- `647 | quarter_grid_stage_ramp_revenue_bridge_failed | [validation_violation_count, composite_revenue_ramp_violations, impossible_quarter_count, impossible_quarters, adjusted_cell_count, adjusted_cells_sample, repair_reason, contract_authority]`
- (+ similar assertion functions emitting via `fail_fast_raise` with structured `details`)

## Classification

### Dimension 1 — Diagnostic adequacy

Every site sampled carries either:
- a structured `details` dict with the per-failure identifying fields
  (quarter_index, lever_id, metric_key, business_naics_6, etc.), OR
- an empty `details` dict where the `actual` / message string is the
  complete diagnostic (e.g., "horizon_quarters must be >= 1;
  received -3" — the bad scalar is in the message itself, and the
  trigger condition is trivial; nothing further to log).

**Result: 60/60 ADEQUATE.**

The sole near-miss is `orchestrator.py:2200` (`pre_cash_gate_gpt_
authorable_checks_unfixed_after_handler`): `details.violations_
sample` is truncated to first 10 entries.  The total count is in
the `actual` string (`f"{len(unmuted)} unmuted check violation(s)
remain"`), so the operator can still see how many were clipped.
Not flagged — the truncation is documented and the count survives.

### Dimension 2 — Survival across cleanup paths

Two vectors of clearing exist in principle.

**Vector A — try/except that swallows the raised exception.**

Greps:
- `except PostIntakePreconditionFailed:` — exactly **one** site
  (`post_intake_solver/orchestrator.py:2215`), and it `raise`s
  immediately.  Pass-through.  **SURVIVES.**
- `except FailFastError as exc:` — exactly **two** sites
  (`post_intake_solver/orchestrator.py:308` and `:334`).  Both
  destructure `exc.details["violations"]` into a `failing_metrics`
  list that is surfaced to the orchestrator's downstream
  `_evaluate_gpt_authorable_pre_cash_checks` consumer.  This is
  **preservation by transformation**, not loss — the data flows
  forward in a structured form the next stage can consume.
  **SURVIVES.**
- No `except Exception: pass` patterns exist in
  `post_intake_runtime_validation/finalize_post_intake.py`, the
  funding handler, or other fail-fast-adjacent modules.  (The
  Explore subagent's initial report flagged "45+ silent-pass
  try/except blocks" in finalize — manual verification: ZERO.
  False alarm.)

The `except Exception:` patterns that do exist (e.g.
`orchestrator.py:1524-1547`, `:2217-2227`) all either re-raise
under test mode or transcribe the exception into a structured
diagnostics dict (`cascade_diagnostics`, `completion_trace[...]`).
The diagnostic propagates.

**Result for Vector A: SURVIVES across the board.**

**Vector B — data-structure overwrite (the Stage 1 smoking gun).**

The Stage 1 bug was: validator populates
`cash_strategy_second_pass_result["cash_contract_failures"]`, then
the orchestrator unconditionally replaces
`cash_strategy_second_pass_result` with a deepcopy of pre-cash
state, erasing the metadata.

Greps for related patterns:
- `final_finmo_json = copy.deepcopy(pre_cash_finmo_json)` — **zero
  matches in production code**.  Stage 1's removal stuck.
- `cash_strategy_second_pass_result = copy.deepcopy(...)` — 8
  matches across `convergence/runtime.py`, `convergence/runner.py`,
  `state/runner.py`, `finalize_post_intake.py`,
  `solver/orchestrator.py`.  Every match is a deepcopy passed AS A
  KWARG to a downstream function (forwarding for safe mutation by
  the callee), not a reassignment that replaces the live working
  state.  The one exception
  (`solver/orchestrator.py:2679: cash_strategy_second_pass_result =
  {"post_intake_finalize_validation": {}}`) constructs a wholly new
  payload destined for finalize — not a revert of a populated
  state.
- `cash_contract_failures = []` / `cash_contract_failures.clear()`
  — only the validator's own local-variable init at
  `post_intake_cash/runner.py:4064`.  No site re-zeros the
  populated list.
- Functions named `_revert*`, `_rollback*`, `_clear*`, `_reset*`
  that wholesale replace persisted state — none found that touch
  fail-fast-adjacent dicts.

**Result for Vector B: SURVIVES across the board.  Stage 1 was the
only such site; it is fixed.**

### Combined classification

| Bucket | Count |
|---|---|
| ADEQUATE + SURVIVES (healthy) | **60** |
| ADEQUATE + CLEARED | 0 |
| INADEQUATE + SURVIVES | 0 |
| INADEQUATE + CLEARED | 0 |

## Cleanup / revert / clear paths

| Site | What runs | Effect on fail-fast diagnostic |
|---|---|---|
| `orchestrator.py:1524-1547` | `except Exception as cascade_exc:` — extracts `cascade_exc.diagnostic_payload` into `cascade_diagnostics["diagnostic"]`; surfaces on `next_result["adaptation_cascade_diagnostics"]`. Re-raises unexpected exception types. | Preserves |
| `orchestrator.py:2215-2227` | `except PostIntakePreconditionFailed: raise` (pass-through) + `except Exception as gate_exc:` (re-raises under test mode; transcribes to `completion_trace["pre_cash_gate"]["error"]` under production). | Preserves |
| `orchestrator.py:308, :334` | `except FailFastError as exc:` — unpacks `exc.details["violations"]` into `failing_metrics` list consumed by `_evaluate_gpt_authorable_pre_cash_checks`. | Preserves (transformed) |
| `orchestrator_invocation.py:361, :490` (and 4 sibling cash-strategy try/except sites) | Under test mode: raise `PostIntakePreconditionFailed` with `cause=exc` and `details={...}`. Under production: return `_failure_result(...)` dataclass with `reason=f"{type(exc).__name__}: {str(exc)[:300]}"`. | Preserves under test mode (the fail-fast path). Production-mode path is not a fail-fast — it's an alternative return contract — so out of scope for this audit. |
| `convergence/runtime.py:4896-4910` | `if test_mode: fail_fast_raise(...)`; `else: logger.warning(detail)`. | Preserves under test mode. Production path logs the same `detail` string. |
| Stage 1's removed sites (`orchestrator_invocation.py:545-558`, `convergence/runner.py:3130-3150`) | NO LONGER EXIST. Stage 1 verified. | — |

## Conclusion

The audit found **zero** fail-fasts that are INADEQUATE or CLEARED.
Stage 1 removed the only known data-overwrite vector; no analogous
patterns exist elsewhere.  Every fail-fast raise site carries
adequate diagnostic context, and either propagates as an exception
that survives the call stack or is structurally transformed
(unpacked into a downstream diagnostics dict) by a catch site
designed to preserve the data.

**No code fixes required.**  Per the directive: "If no INADEQUATE
or CLEARED fail-fasts are found, this stage is audit-only.  The
memo lands, doctrine updates, no fix commits needed."

## Doctrine update

The diagnostic-preservation rule is added to
`docs/architecture/doctrine.md` §7 (Anti-Patterns):

> **Cleared fail-fast diagnostics.** A fail-fast that raises with a
> rich `details=` payload, then has that payload swallowed by an
> upstream `try: ... except: ...` without re-raise, transformed
> into a generic status string that loses the structured fields,
> or cleared by a downstream revert that overwrites validator-
> populated state with a pre-pass deepcopy.  Every fail-fast must
> produce diagnostic state that survives downstream cleanup paths.
> Anti-example: Phase 9 P3.20 Part 3 Stage 1 (commit ee291e4) — the
> cash post-pass orchestrator atomic-reverted
> `cash_strategy_second_pass_result` on validator failure, clearing
> the `cash_contract_failures` metadata the validator had just
> populated.  Operators saw a generic "liquidity failure" at
> finalize with no record of which contract failure actually
> tripped the revert.  Fix: never overwrite validator-populated
> state with pre-pass state; let the failures live alongside the
> proposer's output for downstream inspection.

Placement: directly after the existing "Silent fall-through" and
"Silent machinery degradation" entries.  Conceptually adjacent —
those entries describe diagnostics never produced; this entry
describes diagnostics produced but lost.

No conflict with existing §5b text — §5b defines the two fail
types; this entry constrains how their diagnostics flow.

## Stage 4 totals

- Fail-fasts inventoried: **60**
- ADEQUATE + SURVIVES (healthy): **60**
- INADEQUATE: **0** (none to fix)
- CLEARED: **0** (none to fix)
- Doctrine update lines: **~20** in §7
- Total LOC change: memo (~250) + doctrine (~20) = ~270; no
  production code touched
- Stages 1, 2, 3, 3b invariants: PRESERVED (no changes touch
  handler, orchestrator, validator, or tool session code)

Ready for the user's combined E2E verification covering Stages 1
through 4.
