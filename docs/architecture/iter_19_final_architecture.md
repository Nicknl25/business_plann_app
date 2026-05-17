# Iter 19 — Final Architecture State

**Branch:** `intake-stable`
**Period:** Phase 9 P3.10 iter 19
**Doctrine reference:** [doctrine.md](doctrine.md)

This document is the closing report for iter 19. It catalogs every
handler in the post-intake pipeline at iter close, lists the
doctrine-compliance checks for the architectural conversions
(Stages 4 and 5), and captures the work that was deferred or
intentionally canceled.

Live end-to-end verification across the 27-draft sweep is
**intentionally deferred to a separate session** per the iter 19
directive. The smoke and unit tests in this iter exercise the code
paths and the orchestration shape; integration against live OpenAI
will be the next session's first work.

---

## 1. Final scope

| Stage | Deliverable | Status |
|---|---|---|
| 0 | Doctrine — `docs/architecture/doctrine.md` (269+ lines authored, updated again at Stage 8) | Shipped `dffb013` |
| 1 | F7 + F1 surgical fixes | Shipped `d8c3ec3` |
| 2 | F2/F3 schema tightening + prompt explicitness | Shipped `0824aff` |
| 3 | F6-Pinnacle pre-cash gate diagnostic + Stage 3 correction (unconditional payroll writeback) | Shipped `568cbbf` + `2a12b19` |
| 4 | Cash adaptation + funding handler + Stage 4 correction (full GPT tool-calling loop, production wiring) | Shipped `898429f` + `b846a86` |
| 5 | Stage ramp adaptation (Python builder + handler + full GPT tool-calling loop + production wiring) | Shipped `1721c2c` |
| 6 | Payroll adaptation | **Deferred** to a focused future session. Payroll authoring stays GPT-as-source; the orchestration bug was handled by the Stage 3 correction. |
| 7 | Convergence adaptation | **Canceled.** The original directive proposed dropping `_run_unified_convergence_openai`; investigation found this was based on a misunderstanding of the codebase (the cascade re-enters the same convergence runner, so removing the routine GPT call would break every plan with no recovery). Convergence is correctly GPT-authored. See §5 for the analysis. |
| 8 | Final architecture documentation (this document + doctrine.md updates) | This commit |

---

## 2. Handler Inventory at iter 19 close

Per [doctrine.md §6](doctrine.md#6-handler-inventory).

### Handlers — Python-first + handler-on-validator-failure

| Handler | Module | Authority | Trigger | Tool-call budget | Run-budget decoupled |
|---|---|---|---|---|---|
| **Restoration / exhaustion** | [`post_intake_gpt_exhaustion_handler`](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/) | 8 P&L drivers (unit_price, capacity, utilization, payroll dollars, COGS%, marketing%, SG&A%, R&D%) + 5 WC drivers (AR days, AP days, inventory days, deferred revenue %, prepaid expenses %) | `RestorationStatus.EXHAUSTED` from the deterministic restoration loop | 10 (`HARD_CAP_TOOL_CALLS`) | Yes |
| **Funding** | [`post_intake_funding_handler`](../../python/client_intake_and_finmo/post_intake_funding_handler/) | `schedules::Debt Issuance (New Borrowing)`, `schedules::Debt Repayment (Scheduled)`, `balance_sheet::Owner's Capital`, `balance_sheet::Other Equity`, `balance_sheet::Distributions` (pulldown) | `cash_buffer_violations` non-empty after cash strategy post-pass, AND Python deterministic allocator leaves residual gaps | 10 | Yes |
| **Stage ramp** | [`post_intake_stage_ramp_handler`](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/) | `stage_ramp_contract` grid fields (rev_target, rev_max, rev_spike, rev_spike_max, max_util, cogs_target/_max, marketing_max, rd_max, ga_max, lease_max, ni_floor, posture), `stage_family`, `utilization_high_watermark`, `rationale` | `_validate_stage_ramp_contract_payload` rejects the Python deterministic builder's output | 10 | Yes |

### GPT-as-authoring-source (intentional, NOT handler-on-failure)

Per doctrine §1 and §6: these operations are GPT-authored every plan
by design. Python provides structure around them.

| Operation | Entry point | Python structure |
|---|---|---|
| **Unified convergence decision** | [`_run_unified_convergence_openai`](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L2776) | Strict-mode JSON schema for `unified_convergence_decision` contract; post-parse `_validate_unified_convergence_decision_payload`; numeric solver drives the GPT-authored target_values mechanically. |
| **Payroll headcount schedule** | [`estimate_payroll_headcount_schedule_with_gpt`](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2241) | Tier-conditional `allOf`/if-then schema bounds for `target_payroll_percent_of_revenue` (iter 19 Stage 2); NAICS-filtered OEWS title catalog; Python computes wage / payroll dollars / supported capacity from GPT-authored FTE counts. |

---

## 3. Python-deterministic / Handler-corrective / Hard-fail / GPT-authored

Breakdown by post-intake operation.

| Operation | Authoring source | Validator | On validator failure |
|---|---|---|---|
| `maintenance_rate` (capex policy) | Python (NAICS cohort midpoint, conservative default 0.05 on miss) — iter 19 Stage 1 F1 | `_default_capex_depreciation_policy` range check `[0.02, 0.15]` | Defensive guard only (data corruption); validator should never fire post Stage 1 |
| `r_and_d_applicability` | Python (universal, applicable to every NAICS) | n/a | n/a |
| Mapping-formula reconciliation (cogs / prepaid / deferred / WC days) | FINMO (per-quarter math); validator compares via single-source helpers (iter 19 Stage 1 F7) | `assert_post_intake_mapping_formula_application_applied` + `balance_sheet_driver_validation` | $1 tolerance for rounding-boundary cases (Mirror Flavor 1 + Flavor 4) |
| Balance sheet contextual seed (Q1 anchors) | Python proposer + GPT critic (existing pre-iter-19 pattern) | `_normalize_post_intake_contract_payload` + critique-contract | Python proposal stands as safety floor |
| Stage ramp contract | Python deterministic builder (iter 19 Stage 5) | `_validate_stage_ramp_contract_payload` | `post_intake_stage_ramp_handler` engages; on exhaustion → `RuntimeError("stage_ramp_handler_exhausted: ...")` |
| Payroll headcount schedule (FTE counts, title selection) | GPT (intentional — judgment-heavy, doctrine §1) | `validate_payroll_headcount_payload` + `headcount_payroll_revenue_sanity_bounds` post-parse | GPT retries with `previous_contract_failure` injected; failure produces structured `payroll_headcount_*` fail-fast |
| Cash strategy review decision | Python proposer (iter 19 Stage 4 — routine GPT critic dropped) | `_cash_strategy_review_decision_contract_error` | Python proposal stands |
| Cash strategy post-pass (buffer violations) | Python validator | `_validate_cash_strategy_post_pass` returning `cash_buffer_violations` | `post_intake_funding_handler` engages (Stage 4 correction); on exhaustion → cash strategy reverts to pre-cash state with the residual diagnostic attached |
| Unified convergence decision | GPT (intentional — judgment-heavy, doctrine §1) | `_unified_convergence_decision_contract_error` | Cycle rejects-before-solver; convergence loop retries with `previous_contract_failure` injected |
| Restoration loop (target seeking) | Python (deterministic algebra) | Realism + viability validators | `post_intake_gpt_exhaustion_handler` engages on `RestorationStatus.EXHAUSTED` |
| Realism verification (post-applied-updates) | Python proposer + GPT critic | `propose_realism_verification_payload` + critique-contract | Python proposal stands |
| Pre-cash gate (GPT-authorable checks) | Python check evaluators | `_evaluate_gpt_authorable_pre_cash_checks` | (iter 19 Stage 3) Pre-gate sanity helper checks contract-derived levers are written; raises specific `payroll_lever_not_applied_before_gate` on mismatch. Otherwise the existing exhaustion handler engages. |

---

## 4. Doctrine compliance check for Stages 4 and 5

Per doctrine §5 every handler has six invariants. The architectural
conversions in iter 19 (Stages 4 and 5) introduce two new handlers.
Compliance:

### Funding handler (Stage 4 + correction)

| Invariant | Status |
|---|---|
| 1. Module location `post_intake_<name>_handler/` with 5 files | ✓ [`post_intake_funding_handler/`](../../python/client_intake_and_finmo/post_intake_funding_handler/) — `__init__.py`, `handler.py`, `tool_calling_session.py`, `prompts.py`, `mini_finmo.py` |
| 2. Defined lever authority (explicit, not "whatever it needs") | ✓ `FUNDING_LEVER_AUTHORITY` enumerates 5 funding levers; strict-mode tool schema requires the same 5 lever_ids; operating-side levers are absent by construction |
| 3. `HARD_CAP_TOOL_CALLS = 10` | ✓ `tool_calling_session.HARD_CAP_TOOL_CALLS = INITIAL_TOOL_CALL_BUDGET (8) + EXTENSION_TOOL_CALLS (2) = 10` |
| 4. `counts_against_run_budget=False` on every API call | ✓ `tool_calling_session.COUNTS_AGAINST_RUN_BUDGET = False`; threaded through every `call_gpt_responses_api_turn` invocation |
| 5. Specific validator trigger | ✓ `cash_buffer_violations` non-empty after `_validate_cash_strategy_post_pass`, only when keep_changes is False |
| 6. Specific hard-fail diagnostic | ✓ `FundingHandlerStatus.EXHAUSTED` with `residual_violations` naming each unfillable quarter; orchestrator falls through to revert with `funding_handler_engagement` diagnostic attached |

### Stage ramp handler (Stage 5)

| Invariant | Status |
|---|---|
| 1. Module location with 5 files | ✓ [`post_intake_stage_ramp_handler/`](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/) — same 5-file layout |
| 2. Defined lever authority | ✓ `STAGE_RAMP_FIELD_AUTHORITY` enumerates 16 stage_ramp_contract field paths; strict-mode tool schema requires the full grid shape; operating-side and funding levers are absent by construction |
| 3. `HARD_CAP_TOOL_CALLS = 10` | ✓ Same constants as funding handler |
| 4. `counts_against_run_budget=False` | ✓ Same wiring as funding handler |
| 5. Specific validator trigger | ✓ `_validate_stage_ramp_contract_payload` raising `RuntimeError` on the Python builder's output |
| 6. Specific hard-fail diagnostic | ✓ `StageRampHandlerStatus.EXHAUSTED` with `validator_error_text` carrying the residual rejection reason; `engage_stage_ramp_handler_on_validator_failure` raises `RuntimeError("stage_ramp_handler_exhausted: ...")` with the diagnostic |

---

## 5. Why Stage 7 was canceled

The original iter 19 directive's Stage 7 proposed:

> Currently `_run_unified_convergence_openai` is GPT-only and runs
> routinely. Convert to handler-on-failure. The existing convergence
> loop's Python machinery (target-seeking, restoration loop, etc.)
> is the deterministic engine. Most cases converge through pure
> Python. Remove the routine `_run_unified_convergence_openai`
> invocation. Python convergence runs to completion or exhausts.

Investigation during iter 19 surfaced three facts that contradict
the directive's premise:

1. `_run_unified_convergence_openai` is the **only** producer of
   `unified_convergence_decision` payloads in the convergence
   runner. There is no Python proposer for this contract.

2. The plan-builder requires the GPT decision: without it,
   `decision_status != "completed"` triggers a `validation_error`,
   the cycle rejects-before-solver, and the loop hits
   `no_meaningful_progress` after a few non-productive cycles.

3. The `abort_for_cascade` path **re-enters the same convergence
   runner** via [`run_adaptation_cascade`'s
   `inner_runner_callable`](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L356).
   The cascade tries different planning_mode + band amendments, but
   the inner runner still needs the GPT decision. With the GPT call
   removed, every cascade retry hits the same wall.

4. The exhaustion handler is wired in
   [`post_intake_solver/orchestrator.py:1977`](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977),
   downstream of the cascade and tied to `restoration_loop`
   EXHAUSTED — which is a **separate** path from the convergence
   loop. Removing the convergence GPT call does not, by itself,
   route plans through the restoration / exhaustion-handler path.

The directive's claim "Most cases converge through pure Python" did
not match the runtime structure. Dropping
`_run_unified_convergence_openai` would have broken every plan with
no fallback — the cascade retry would loop without progress until
tier exhaustion.

Conclusion: convergence decision authoring is **judgment-heavy by
nature**. Which levers to move, which metrics to target, and the
per-quarter target_values to drive the numeric solver toward is the
class of problem that has no cohort-default rule. Python wraps the
GPT call with strict-mode schema bounds, post-parse validation, and
the numeric solver that drives mechanically on the GPT-authored
targets. This is the **GPT-as-authoring-source** pattern the
doctrine §1 and §6 now explicitly endorse.

---

## 6. Verification deferred to a separate session

Per the iter 19 directive (updated mid-iter), no E2E reruns happen
in iter 19. The smoke + unit tests in each stage exercise the code
paths and the orchestration shape. Live API integration of the
funding handler's GPT tool-calling loop and the stage ramp
handler's GPT tool-calling loop is **unverified pending the
end-of-iter E2E sweep** — explicitly accepted under Option B
direction.

When the E2E sweep runs, expect integration issues from:

- OpenAI Responses-API edge cases not exercised in mocked tests
  (e.g., tool-call argument shape variants, multi-tool-call turns,
  network retry exhaustion on the first turn).
- The funding handler's strict-mode schema requires every quarter
  key (1..20) in `lever_adjustments`. If GPT emits non-string keys
  or omits any quarter, the OpenAI strict-mode parser will reject
  the response and the handler's session-failed-turn diagnostic
  fires. The handler's `_coerce_lever_adjustments` tolerates string
  vs int keys but the parser is enforced upstream.
- The stage ramp handler validates each probe against the
  production validator; the validator's posture / ni_floor /
  utilization-non-decreasing rules are strict. GPT may need
  multiple probes to satisfy all constraints simultaneously; if
  the budget exhausts before acceptance, the handler hard-fails
  with the residual `validator_error_text`.

Integration findings should be filed as targeted fixes, not
architectural revisions. The architecture is now stable.

---

## 7. Test inventory

All tests are in [`Test Files/`](../../Test Files/). Each stage's
test file is self-contained and runnable independently.

| Test file | Stage | Pass count |
|---|---|---|
| [`test_iter_19_stage1.py`](../../Test Files/test_iter_19_stage1.py) | 1 | 16/16 |
| [`test_iter_19_stage2.py`](../../Test Files/test_iter_19_stage2.py) | 2 | 10/10 |
| [`test_iter_19_stage3.py`](../../Test Files/test_iter_19_stage3.py) | 3 | 10/10 |
| [`test_iter_19_stage3_correction.py`](../../Test Files/test_iter_19_stage3_correction.py) | 3 correction | 6/6 |
| [`test_iter_19_stage4.py`](../../Test Files/test_iter_19_stage4.py) | 4 | 16/16 |
| [`test_iter_19_stage4_correction.py`](../../Test Files/test_iter_19_stage4_correction.py) | 4 correction | 18/18 |
| [`test_iter_19_stage5.py`](../../Test Files/test_iter_19_stage5.py) | 5 | 22/22 |
| [`test_module5_gpt_reductions.py`](../../Test Files/test_module5_gpt_reductions.py) | Regression | 21/21 |
| [`test_module3_contract_sweep.py`](../../Test Files/test_module3_contract_sweep.py) | Regression | 9/9 |

Total iter 19 test count: **128/128 passing** at iter close.

---

## 8. Next iter — recommended scope

Items the directive flagged as "intentionally deferred" or that
this iter surfaced as worthwhile:

1. **E2E verification sweep** across the 27-draft set. Catch the
   live-API integration issues that the smoke tests cannot see.
   File each as a targeted fix.
2. **Payroll adaptation (Stage 6 of original directive).** A
   focused session that respects payroll's fragility. The original
   directive's payroll-handler approach assumed Python-deterministic
   FTE / title selection; the iter 19 doctrine update reframes
   this as a GPT-as-authoring-source operation, so the right next
   step is probably to **tighten the Python structure around the
   existing GPT call** (richer post-parse validators, stricter
   schema, tier-bound enforcement at write time) rather than to
   build a payroll *handler* per the original pattern.
3. **Funding handler GPT-loop live verification.** First live
   stress-test target. The deterministic allocator covers most
   cases; the GPT loop's value-add is the chronic-buffer-violation
   scenarios that the priority order doesn't solve.
4. **Stage ramp handler GPT-loop live verification.** Same shape
   as #3.
5. **Doctrine §4 Flavor 1 sweep.** The mapping-formula helpers
   were one Mirror Flavor 1 conversion; iter 18 noted there are
   other "two paths compute same value" candidates worth a sweep.

---

## 9. Follow-up iters — P3.11 and P3.12

After iter 19 shipped, two follow-up iters landed in quick succession.
Both are recorded here so the architectural state captured by this
document remains current.

### Iter P3.11 — Payroll iterative refinement

Commit: `0379a4b` (phase_9_p3_11_payroll_iterative_refinement).

Per the iter 19 doctrine §1 (GPT-as-authoring-source for
judgment-heavy operations), payroll authoring stays as GPT-as-source
rather than being refactored into a handler-on-failure pattern.
P3.11 adds **iterative refinement** around the existing GPT call:
when validators reject GPT's proposal, GPT sees structured failure
feedback and retries up to 10 rounds before hard-failing with a
residual diagnostic.

New module: [post_intake_headcount/payroll_validator_translator.py](../../python/client_intake_and_finmo/post_intake_headcount/payroll_validator_translator.py)
— pattern-based translator for the Layer A.2 token-format validator
codes. Six patterns (out-of-range numeric, missing, invalid enum,
per-row field, title lifecycle, structural). Fail-fast on unmatched
codes per doctrine §5b.

Three-path dispatch in the iterative loop:
- Layer A.1 (contract-table prose errors): pass verbatim into
  `contract_table_errors`.
- Layer A.2 (token codes): translator (strict fail-fast).
- Layer A.3 (economic feasibility): existing
  `_compact_payroll_failure_for_gpt`.

Seven machinery fail-fast invariants on the iteration mechanics:
- `payroll_iterative_refinement_round_count_drift`
- `payroll_iterative_refinement_budget_decoupling_violation`
- `payroll_iterative_refinement_state_corruption`
- `payroll_validator_translator_unmatched_code`
- `payroll_validator_translator_malformed_output`
- (parse failure preserved as existing `payroll_headcount_contract_parse_failed`)
- Plus the planned exhaustion hard-fail:
  `payroll_iterative_refinement_exhausted`.

Removed the outer `payroll_grid_rebuild_limit` retry in
[post_intake_initial_grid/runner.py](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py).
Post-quarter-grid feasibility violations now hard-fail rather than
retry-eligible (intentional behavior change).

Tests: 30/30 PASS in
[Test Files/test_payroll_iterative_refinement.py](../../Test Files/test_payroll_iterative_refinement.py).

### Iter P3.12 — Machinery Fail-Fast Consistency Backfill

Three-phase iter:
- Phase 1 (`f7461e6`): read-only inventory memo
  ([iter_19_machinery_fail_fast_inventory.md](iter_19_machinery_fail_fast_inventory.md))
  identifying 11 missing machinery fail-fasts across iter 19 stages.
- Phase 2 (`fb9d0b1`): implementation of all 11 checks.
- Phase 3 (this commit): doctrine documentation updates.

Brought every iter 19 stage to the same machinery fail-fast bar
that iter P3.11 set for payroll. Closes the asymmetry where iter 19
handlers had exhaustion fail-fasts (planned business-logic hard-
fails) but lacked machinery fail-fasts (infrastructure
malfunctioning hard-fails).

**Funding handler (Stage 4) — 6 new fail-fasts:**

| # | Operation code | What it catches |
|---|---|---|
| 1 | `funding_handler_round_count_drift` | Loop counter diverges from actual GPT call count |
| 2 | `funding_handler_budget_decoupling_violation` | A GPT call inside the session passed `counts_against_run_budget=True` |
| 3 | `funding_handler_state_corruption_between_rounds` | `input_items` / `history` / `verified_commit_candidate` malformed at round entry |
| 4 | `funding_handler_authority_violation` | `apply_authored_lever_changes_to_model_input` saw a lever_id outside `FUNDING_LEVER_AUTHORITY` (replaces the previous silent skip) |
| 5 | `funding_handler_output_malformed` | RESOLVED status with empty authored changes, or EXHAUSTED with no diagnostic |
| 6 | `funding_handler_best_effort_selection_drift` | Best-effort record at hard cap is actually all-resolved (should have been verified commit candidate) |

**Stage ramp handler (Stage 5) — 4 new fail-fasts:**

| # | Operation code | What it catches |
|---|---|---|
| 7 | `stage_ramp_handler_round_count_drift` | Same shape as funding handler |
| 8 | `stage_ramp_handler_budget_decoupling_violation` | Same shape |
| 9 | `stage_ramp_handler_state_corruption_between_rounds` | Same shape |
| 10 | `stage_ramp_handler_authority_violation` | Refined contract contains root field outside the handler's declared authority |

Invariants 5 and 6 (output malformation, best-effort selection
drift) were **already covered** by Stage 5's post-session canonical
validator re-check shipped with the original Stage 5 commit; no new
checks needed for those categories.

**Stage 2 — 1 new fail-fast:**

| # | Operation code | What it catches |
|---|---|---|
| 11 | `payroll_tier_bounds_mirror_drift` | Python-side `_PAYROLL_INTENSITY_TIER_BOUNDS` mirror diverged from SQL `post_intake_headcount_policy_lookup.payroll_revenue_sanity_bounds` |

Per doctrine §4 Flavor 4 (invariant check): the JSON schema uses
the Python mirror; the runtime validator uses the SQL policy. If
they diverge, the strict-mode parser enforces one set of bounds
while the runtime validator enforces another — silently
inconsistent. The check fires at schema-construction time,
catching drift before any contract is built with the wrong bounds.

Tests: 28/28 PASS in
[Test Files/test_p3_12_machinery_fail_fasts.py](../../Test Files/test_p3_12_machinery_fail_fasts.py).

After P3.12 the system's machinery fail-fast inventory is uniform
across all iter 19 stages, P3.11 payroll, and Stage 3's prototype
pre-gate diagnostic. Every iteration-bearing component has guards
on round count, budget decoupling, state, authority, output shape,
and best-effort selection where applicable.
