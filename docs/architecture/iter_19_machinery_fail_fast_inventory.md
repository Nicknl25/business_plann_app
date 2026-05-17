# Iter 19 Machinery Fail-Fast Inventory

**Iter:** Phase 9 P3.12 Phase 1
**Status:** Read-only memo. No code changes in this commit.
**Purpose:** Identify gaps in machinery fail-fasts across iter 19's
stages so Phase 2 can add them. Per the P3.12 conceptual primer,
machinery fail-fasts protect the iteration/handler infrastructure
itself from silent degradation — distinct from validators, which
check business logic outputs.

This inventory was produced after the iter P3.11 payroll iterative
refinement work shipped, which set the bar for machinery fail-fast
coverage. P3.11's payroll loop has seven machinery invariants in
place; this memo audits iter 19's funding handler (Stage 4), stage
ramp handler (Stage 5), and the surgical stages (1/2/3) against the
same bar.

---

## Audit framework

The seven machinery fail-fast categories from the P3.12 directive:

1. **Round count drift** — handlers with tool-calling sessions
2. **Budget decoupling violation** — handlers with GPT calls
3. **State corruption between rounds** — handlers with multi-round state passing
4. **Authority violation** — handlers with declared lever authority
5. **Output malformation** — handlers returning structured results
6. **Best-effort selection drift** — handlers with verified-commit-candidate tracking
7. **Pre-gate contract-lever invariant** — Stage 3 helper pattern, extended to other gates

For each stage:
- Files modified
- Machinery components introduced
- Existing machinery fail-fasts (cited)
- Missing machinery fail-fasts (proposed)
- Recommended operation code per gap
- Estimated LOC

---

## Stage 1 — F7 + F1 surgical fixes (commit `d8c3ec3`)

### Files modified

- [python/financial_model_engine/finmo_model.py](../../python/financial_model_engine/finmo_model.py) — added `compute_revenue_times_ratio`, `compute_model_input_value`, `compute_working_capital_days_formula`, `MAPPING_FORMULA_INT_TOLERANCE = 1`.
- [python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py) — replaced 2 inline formula sites with helper calls + tolerance.
- [python/client_intake_and_finmo/post_intake_runtime_validation/balance_sheet_driver_validation.py](../../python/client_intake_and_finmo/post_intake_runtime_validation/balance_sheet_driver_validation.py) — replaced 2 inline formula sites.
- [python/client_intake_and_finmo/post_intake_contracts/runner.py](../../python/client_intake_and_finmo/post_intake_contracts/runner.py) — `_derive_maintenance_capex_percent_from_naics` conservative-default fallback.
- [python/client_intake_and_finmo/finmo_bridge.py](../../python/client_intake_and_finmo/finmo_bridge.py) — three defensive-guard message updates.

### Machinery components

- Three canonical math helpers (Mirror Flavor 1, doctrine §4).
- One tolerance constant (`MAPPING_FORMULA_INT_TOLERANCE = 1`).
- Conservative-default fallback branch in maintenance-rate resolver.

### Existing machinery fail-fasts

- None specific to this stage's machinery. Failures here are validator-level (`post_intake_mapping_formula_application_invalid`, `balance_sheet_driver_formula_failed`); not iteration machinery.

### Missing machinery fail-fasts

Stage 1 has no iteration mechanics, no handler, no multi-round state, no GPT calls. The seven categories largely don't apply:

| Category | Applicable? | Note |
|---|---|---|
| 1. Round count drift | No | No rounds |
| 2. Budget decoupling | No | No GPT calls |
| 3. State corruption between rounds | No | No multi-round state |
| 4. Authority violation | No | No lever authoring |
| 5. Output malformation | No | No structured handler result |
| 6. Best-effort selection drift | No | No verified-commit tracking |
| 7. Pre-gate contract-lever invariant | No | Not a gate stage |

**One latent gap** — the `MAPPING_FORMULA_INT_TOLERANCE = 1` constant is load-bearing for the validator's correctness; if a future refactor sets it to 0 or omits it, the divergence-tolerance contract silently weakens. This is a one-line invariant:

- **Proposed code:** `mapping_formula_int_tolerance_invariant_violated`
- **Check:** at module import + at validator-call time, assert `MAPPING_FORMULA_INT_TOLERANCE >= 1`.
- **LOC:** ~10 (constant guard + one validator-side import-time assertion).
- **Priority:** low. The constant is a module-level integer; refactor risk is low and the validator's behavior is the primary test surface anyway.

**Recommendation:** SKIP. Stage 1's machinery surface is too small to justify machinery fail-fasts; the validators are the right defensive layer.

---

## Stage 2 — F2/F3 schema + prompt tightening (commit `0824aff`)

### Files modified

- [python/client_intake_and_finmo/post_intake_mapping.py](../../python/client_intake_and_finmo/post_intake_mapping.py) — tightened contract row envelope (0.06, 0.80); added `_augment_root_schema_for_contract` + `_PAYROLL_INTENSITY_TIER_BOUNDS`.
- [python/client_intake_and_finmo/post_intake_headcount/schedule.py](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py) — prompt anti-confusion example.

### Machinery components

- `_augment_root_schema_for_contract` — contract-specific schema augmentation function.
- `_PAYROLL_INTENSITY_TIER_BOUNDS` — Python-side mirror of `post_intake_headcount_policy_lookup.payroll_revenue_sanity_bounds_json`.

### Existing machinery fail-fasts

- None. The augmenter is silently a no-op for contracts it doesn't recognize (correct behavior).

### Missing machinery fail-fasts

The notable gap is **policy-mirror drift**: `_PAYROLL_INTENSITY_TIER_BOUNDS` is a Python-side mirror of the policy table. If the SQL `payroll_revenue_sanity_bounds_json` changes (e.g., medium tier's max bumped from 0.55 to 0.60) and the Python mirror isn't updated, the JSON schema enforces the OLD bounds while the runtime validator enforces the NEW bounds. That's a Mirror Flavor 4 (doctrine §4) invariant violation.

This is the same shape as Stage 5's stage_ramp_handler post-session validator check — the two paths must agree.

| Category | Applicable? | Proposed |
|---|---|---|
| 1. Round count drift | No | — |
| 2. Budget decoupling | No | — |
| 3. State corruption between rounds | No | — |
| 4. Authority violation | No | — |
| 5. Output malformation | No | — |
| 6. Best-effort selection drift | No | — |
| 7. Pre-gate contract-lever invariant | No | — |
| **Custom: policy-mirror drift** | **Yes** | See below |

- **Proposed code:** `payroll_tier_bounds_mirror_drift`
- **Check:** at module-import time (or first use), compare `_PAYROLL_INTENSITY_TIER_BOUNDS` against `post_intake_headcount_policy_for("default")["payroll_revenue_sanity_bounds"]`. On mismatch, raise `PostIntakePreconditionFailed`.
- **LOC:** ~30 (one-time check function + invocation guard).
- **Priority:** medium. Drift here would silently weaken the schema enforcement; the runtime validator would still fire, but the strict-mode parser would accept invalid values until then. Catching at import-time fails fast.

**Recommendation:** ADD `payroll_tier_bounds_mirror_drift`. Schedule it for Phase 2.

---

## Stage 3 — F6 pre-cash gate diagnostic (commit `568cbbf`)

### Files modified

- [python/client_intake_and_finmo/post_intake_solver/orchestrator.py](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py) — added `_assert_pre_cash_gate_contract_levers_written`, wired into `_evaluate_gpt_authorable_pre_cash_checks` call site.
- [python/client_intake_and_finmo/post_intake_convergence/runner.py](../../python/client_intake_and_finmo/post_intake_convergence/runner.py) — silent-skip path on missing payload converted to structured log (later replaced by Stage 3 correction).

### Machinery components

- `_assert_pre_cash_gate_contract_levers_written` — pre-gate sanity helper.

### Existing machinery fail-fasts

- `payroll_lever_not_applied_before_gate` ([orchestrator.py:191-265](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L191-L265)) — this **IS** a machinery fail-fast (category 7 prototype). When the payroll contract authored positive totals but the model_input lever is all zero, raises `PostIntakePreconditionFailed` with diagnostic naming the upstream skipped step. This is the pattern P3.12 generalizes.

### Missing machinery fail-fasts

| Category | Applicable? | Note |
|---|---|---|
| 7. Pre-gate contract-lever invariant | **Yes — extend to other gates** | See below |

**Other gates worth auditing:**

- **`_evaluate_gpt_authorable_pre_cash_checks` itself** ([orchestrator.py:282-414](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L282-L414)) — calls `assert_stage_ramp_expense_path_applied`, `assert_stage_ramp_profitability_path_applied`, and `balance_sheet_driver_zero_but_applicable_errors`. The Stage 3 helper covers ONE specific lever→contract pairing (payroll). Other check / lever pairs:
  - `stage_ramp_expense_path` references `_STAGE_RAMP_EXPENSE_FINMO_FIELD_TO_METRIC_LEVER` — covers cogs, marketing, ga, lease. These levers come from FINMO computation, not direct writes — the "contract authored but writeback skipped" pattern doesn't apply the same way.
  - `balance_sheet_driver_zero_but_applicable_errors` — checks lever-id values against applicability. Has its own diagnostic structure already.
- **Convergence runner's `_apply_payroll_authority` writeback** (Stage 3 correction made writebacks unconditional) — the "contract authored but lever zero" case is structurally prevented now. The pre-gate helper is the belt-and-suspenders.
- **Finalize-time gates** — validators run in [post_intake_runtime_validation/finalize_post_intake.py](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py). These are end-state validators, not gate-style pre-checks. The contract-lever invariant doesn't naturally apply.

**Other contract-lever pairs that COULD have a Stage-3-style pre-gate check:**

- **Stage ramp contract → expenses::Cost of Goods Sold lever**: if `stage_ramp_contract.quarter_ramp_grid[].cogs_target` is non-zero but the model_input cogs lever is all-zero, that's the same shape as the payroll case. But cogs is a percent-of-revenue driver computed inside FINMO, not directly written from the contract — so the analogy doesn't hold structurally. SKIP.
- **Funding handler's authored changes → balance_sheet levers**: when the handler authors lever changes (Stage 4 correction's `apply_authored_lever_changes_to_model_input`), the lever-write path needs an authority-violation check (which is category 4, handled in Stage 4's audit below).

**Recommendation:** Stage 3 itself needs nothing new. The category 7 fail-fast Stage 3 introduced is already in place. The extension to other gates is moot — no other gate has the same contract→writeback→lever pattern as payroll.

---

## Stage 3 correction — unconditional payroll writeback (commit `2a12b19`)

### Files modified

- [python/client_intake_and_finmo/post_intake_headcount/schedule.py](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py) — writeback no-op branches on empty payload.
- [python/client_intake_and_finmo/post_intake_convergence/runner.py](../../python/client_intake_and_finmo/post_intake_convergence/runner.py) — removed conditional skip.

### Machinery components

- No-op branches in two writeback functions (`apply_payroll_headcount_payload_to_model_input`, `apply_payroll_supported_capacity_to_model_input`).

### Existing machinery fail-fasts

- The strict validators downstream of the no-op branch (`validate_payroll_headcount_payload` runs on non-empty payloads) still fire.
- Stage 3's `_assert_pre_cash_gate_contract_levers_written` catches the "contract authored but lever zero" case.

### Missing machinery fail-fasts

None. The Stage 3 correction's machinery is the no-op branch; it's safe by construction (no payload → no work). The downstream gate is the protection.

**Recommendation:** NONE.

---

## Stage 4 (+ correction) — cash adaptation + funding handler (commits `898429f` + `b846a86`)

### Files modified

- [python/client_intake_and_finmo/post_intake_cash/runner.py](../../python/client_intake_and_finmo/post_intake_cash/runner.py) — routine GPT critic dropped.
- [python/client_intake_and_finmo/post_intake_funding_handler/](../../python/client_intake_and_finmo/post_intake_funding_handler/) — 5 new files (handler, session, prompts, mini_finmo, init).
- [python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py](../../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py) — engage helper wired.

### Machinery components

- `FundingHandlerResult` / `FundingHandlerStatus` dataclasses.
- Python deterministic allocator (`_run_python_allocator`).
- GPT tool-calling session (`run_funding_tool_calling_session`) — full P3.9-style loop.
- `compute_cash_trajectory` tool definition (Responses-API strict schema).
- `mini_finmo` preview helpers (`project_cash_trajectory_with_adjustments`, `buffer_residual_after_adjustments`).
- Two-stage handler pipeline (Python first → GPT session escalation).
- `apply_authored_lever_changes_to_model_input` lever-write helper.
- `engage_funding_handler_on_violations` orchestrator-wiring entry point.
- Module constants: `HARD_CAP_TOOL_CALLS = 10`, `INITIAL_TOOL_CALL_BUDGET = 8`, `EXTENSION_TOOL_CALLS = 2`, `COUNTS_AGAINST_RUN_BUDGET = False`.

### Existing machinery fail-fasts

- **HARD_CAP_TOOL_CALLS enforced** ([tool_calling_session.py:48](../../python/client_intake_and_finmo/post_intake_funding_handler/tool_calling_session.py#L48)) — loop exits at hard cap.
- **`payroll_iterative_refinement_*` style** — NO, that's P3.11. Funding handler has its own:
- **`funding_handler_tool_calling_session_turn_failed`** ([tool_calling_session.py:447-463](../../python/client_intake_and_finmo/post_intake_funding_handler/tool_calling_session.py#L447-L463)) — raises `PostIntakePreconditionFailed` under `convergence_test_mode_enabled()` when a GPT turn returns a non-success `decision_source`.
- **`FundingHandlerStatus.EXHAUSTED`** — the planned hard-fail when handler can't resolve (this is a *business-logic* exhaustion, not machinery — but it's the right diagnostic for the "handler engaged and couldn't fix" case).

### Missing machinery fail-fasts

| Category | Applicable? | Status |
|---|---|---|
| 1. Round count drift | Yes | **MISSING** |
| 2. Budget decoupling | Yes | **MISSING (only constant declared)** |
| 3. State corruption between rounds | Yes | **MISSING** |
| 4. Authority violation | Yes | **MISSING (silent skip in lever-write)** |
| 5. Output malformation | Yes | **MISSING (FundingHandlerResult shape trusted)** |
| 6. Best-effort selection drift | Yes | **MISSING** |
| 7. Pre-gate contract-lever invariant | No | — |

**Details on each gap:**

1. **Round count drift** — the session loop tracks `tool_calls_used` locally; if some inner code path makes an extra `call_gpt_responses_api_turn` call, the counter would diverge. No runtime check.
   - **Code:** `funding_handler_round_count_drift`
   - **LOC:** ~20 (contextvar + post-call increment + verification)

2. **Budget decoupling violation** — `COUNTS_AGAINST_RUN_BUDGET = False` is a module constant. Threading through to `call_gpt_responses_api_turn` is hardcoded. But there's no runtime assertion that the constant is actually False at call-site, nor that future code can't accidentally call `call_gpt_responses_api_turn` from the session with `counts_against_run_budget=True`.
   - **Code:** `funding_handler_budget_decoupling_violation`
   - **LOC:** ~15 (assertion before each call site)

3. **State corruption between rounds** — `input_items`, `history`, `verified_commit_candidate` are loop-local. If they become malformed (e.g., a turn-handler bug appends a non-dict to `input_items`), the next round's API call would fail with an obscure error. No explicit guard.
   - **Code:** `funding_handler_state_corruption_between_rounds`
   - **LOC:** ~25 (round-entry assertion on `input_items` shape + `history` integrity)

4. **Authority violation** — `apply_authored_lever_changes_to_model_input` in [handler.py:484-528](../../python/client_intake_and_finmo/post_intake_funding_handler/handler.py#L484-L528) iterates `_LEVER_SECTION_MAP`. If GPT proposes a lever_id outside the authority (e.g., due to a schema mis-render or post-parse mutation), the loop's `if lever_id not in _LEVER_SECTION_MAP` SILENTLY SKIPS that lever. This is the doctrine §3 F6-Pinnacle pattern: handler authority must match check. Currently the silent skip mutes the violation.
   - **Code:** `funding_handler_authority_violation`
   - **LOC:** ~20 (replace silent skip with fail-fast diagnostic)

5. **Output malformation** — `FundingHandlerResult` is a dataclass; field types are statically declared. But `engage_funding_handler_on_violations` ([handler.py:545-595](../../python/client_intake_and_finmo/post_intake_funding_handler/handler.py#L545-L595)) constructs the return dict manually. If `result.status == RESOLVED` but `authored_lever_changes` is empty (logically impossible per the handler's branches, but no check), the caller would apply nothing. No explicit guard.
   - **Code:** `funding_handler_output_malformed`
   - **LOC:** ~20 (post-construction shape assertion in engage_helper)

6. **Best-effort selection drift** — `_best_effort_record` ([tool_calling_session.py:267-275](../../python/client_intake_and_finmo/post_intake_funding_handler/tool_calling_session.py#L267-L275)) selects the record with the lowest residual count. The verified-commit-candidate logic separately selects "any all_violations_resolved == True." On hard cap with no verified candidate, the best-effort logic should also reject candidates that the commit-verifier would. Currently there's no cross-check.
   - **Code:** `funding_handler_best_effort_selection_drift`
   - **LOC:** ~25 (post-selection verifier check)

**Total Stage 4 implementation estimate:** ~125 LOC across 6 checks.

---

## Stage 5 — stage ramp adaptation (commit `1721c2c`)

### Files modified

- [python/client_intake_and_finmo/post_intake_contracts/runner.py](../../python/client_intake_and_finmo/post_intake_contracts/runner.py) — `build_python_stage_ramp_contract` Python builder + helpers.
- [python/client_intake_and_finmo/post_intake_stage_ramp_handler/](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/) — 5 new files.
- [python/api_handlers/intake_consult.py](../../python/api_handlers/intake_consult.py) — wiring.

### Machinery components

- `StageRampHandlerResult` / `StageRampHandlerStatus` dataclasses.
- Python deterministic builder.
- GPT tool-calling session (`run_stage_ramp_tool_calling_session`).
- `probe_stage_ramp_contract` tool — uses the production validator as the per-turn probe (Mirror Flavor 3 via `mini_finmo.probe_stage_ramp_contract`).
- `engage_stage_ramp_handler_on_validator_failure` orchestrator-wiring entry point.
- Module constants matching the funding handler (`HARD_CAP_TOOL_CALLS = 10`, etc.).

### Existing machinery fail-fasts

- **HARD_CAP_TOOL_CALLS enforced** in session loop.
- **`stage_ramp_handler_tool_calling_session_turn_failed`** ([tool_calling_session.py:362-380](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py#L362-L380)) — analogous to funding's turn-failed check.
- **Post-session canonical validator re-check** in `run_stage_ramp_handler` ([handler.py:140-165](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L140-L165)) — catches the case where the session reports `verified` but the canonical validator rejects the refined contract. This **IS a best-effort-selection-drift check** (category 6).
- **`StageRampHandlerStatus.EXHAUSTED`** — planned hard-fail.

### Missing machinery fail-fasts

| Category | Applicable? | Status |
|---|---|---|
| 1. Round count drift | Yes | **MISSING** |
| 2. Budget decoupling | Yes | **MISSING (only constant declared)** |
| 3. State corruption between rounds | Yes | **MISSING** |
| 4. Authority violation | Partially covered | Schema enforces; runtime check missing |
| 5. Output malformation | Mostly covered | Post-session validator re-check covers most |
| 6. Best-effort selection drift | **COVERED** | Post-session canonical validator check ([handler.py:140-165](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L140-L165)) |
| 7. Pre-gate contract-lever invariant | No | — |

**Details on each gap:**

1. **Round count drift** — same as funding handler, no contextvar tracking.
   - **Code:** `stage_ramp_handler_round_count_drift`
   - **LOC:** ~20

2. **Budget decoupling violation** — same shape as funding handler.
   - **Code:** `stage_ramp_handler_budget_decoupling_violation`
   - **LOC:** ~15

3. **State corruption between rounds** — same shape as funding handler.
   - **Code:** `stage_ramp_handler_state_corruption_between_rounds`
   - **LOC:** ~25

4. **Authority violation** — the strict-mode JSON schema enforces that GPT can only emit fields in the contract's grid (no operating-side levers reachable). The validator enforces the field set on parse. Authority is therefore covered structurally at the schema layer. **One runtime gap**: if the handler's refined_contract is constructed by handler-side code (rather than verbatim from GPT's parsed payload), there's no check that it stays within authority. Today the handler returns GPT's payload verbatim, so no gap in practice. But a future refactor adding handler-side post-processing would benefit from a guard.
   - **Code:** `stage_ramp_handler_authority_violation`
   - **LOC:** ~15 (forward-looking guard)
   - **Priority:** lower than funding handler's (handler is verbatim today; gap is theoretical).

5. **Output malformation** — `StageRampHandlerResult` dataclass typing covers most. The post-session canonical validator re-check covers the "session reports verified but commit is invalid" drift.
   - **Recommendation:** SKIP — covered by existing checks.

6. **Best-effort selection drift** — **already covered** by the post-session canonical validator check at [handler.py:140-165](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L140-L165). This is exactly the pattern P3.12 asks for: catch the case where session-internal verification disagrees with the canonical verifier. Stage 5 had this from the start.
   - **Recommendation:** SKIP — covered.

**Total Stage 5 implementation estimate:** ~75 LOC across 4 checks (1, 2, 3, 4).

---

## Summary

| Stage | Gaps found | Recommended adds | Est. LOC |
|---|---|---|---|
| Stage 1 | None substantive | None | 0 |
| Stage 2 | Policy-mirror drift | 1 check | ~30 |
| Stage 3 | None (already shipped category 7) | None | 0 |
| Stage 3 correction | None | None | 0 |
| Stage 4 | Categories 1–6 all missing | 6 checks | ~125 |
| Stage 5 | Categories 1–4 missing (5, 6 already covered) | 4 checks | ~75 |
| **Total** | | **11 checks** | **~230 LOC** |

Plus tests: estimate ~20 LOC per check for unit tests = ~220 LOC of tests.

**Total Phase 2 estimate: ~450 LOC** (well under the 1500 LOC stop condition).

---

## Operation-code inventory (Phase 2 will register these)

### Funding handler (Stage 4)

1. `funding_handler_round_count_drift`
2. `funding_handler_budget_decoupling_violation`
3. `funding_handler_state_corruption_between_rounds`
4. `funding_handler_authority_violation`
5. `funding_handler_output_malformed`
6. `funding_handler_best_effort_selection_drift`

### Stage ramp handler (Stage 5)

7. `stage_ramp_handler_round_count_drift`
8. `stage_ramp_handler_budget_decoupling_violation`
9. `stage_ramp_handler_state_corruption_between_rounds`
10. `stage_ramp_handler_authority_violation`

### Stage 2

11. `payroll_tier_bounds_mirror_drift`

---

## Phase 2 implementation plan (Phase 2 deliverable; this memo only sketches)

- Centralize the new machinery fail-fast helpers in
  [post_intake_funding_handler/handler.py](../../python/client_intake_and_finmo/post_intake_funding_handler/handler.py)
  and
  [post_intake_stage_ramp_handler/handler.py](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py)
  (handler-specific contextvars + helpers, mirroring the
  `_payroll_iterative_machinery_fail_fast` pattern from P3.11).
- One additional helper module if the policy-mirror drift check
  ends up living in `post_intake_mapping.py` alongside
  `_PAYROLL_INTENSITY_TIER_BOUNDS`.
- Unit tests for each new fail-fast: synthetic state representing
  the malfunction, invoke the relevant code path, assert
  `PostIntakePreconditionFailed` with the expected operation code.
- All existing tests must still pass. No behavior change for
  healthy runs.

---

## Phase 3 plan (Phase 3 deliverable; this memo only sketches)

Update [doctrine.md](doctrine.md):
- Add §5b "Two Fail Types: Validators vs Machinery Fail-Fasts" (the conceptual primer).
- Update §5 to add machinery-fail-fast invariants list.
- Update §7 anti-patterns to add "silent machinery degradation."

Update [iter_19_final_architecture.md](iter_19_final_architecture.md):
- Add "Iter P3.12 — Machinery Fail-Fast Consistency Backfill" section enumerating the new fail-fasts per stage.
