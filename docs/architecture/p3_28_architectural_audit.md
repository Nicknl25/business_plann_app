# Phase 9 P3.28 — Architectural audit: handler authority × contract awareness

**Source data:** [p3_28_sweep_results.csv](./p3_28_sweep_results.csv),
[p3_28_sweep_results_summary.md](./p3_28_sweep_results_summary.md),
prior memos P3.20-P3.27.
**Scope:** Map every handler with authority over model_input /
finmo fields against the contracts and validators that constrain
those fields, surface awareness gaps, and propose remediation
sequencing. Read-only audit.

---

## §1 Handler authority inventory

### Handler GPT-Exhaustion (Site 1, restoration→handler)
**File:** [post_intake_gpt_exhaustion_handler/handler.py](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py)
**Authority (lever IDs):**

| Lever                                            | Scope    | Surface written                |
| ------------------------------------------------ | -------- | ------------------------------ |
| revenue::Unit Price                              | PNL_PATH | model_input.revenue::Unit Price |
| revenue::Capacity                                | PNL_PATH | model_input.revenue::Capacity   |
| revenue::Utilization                             | PNL_PATH | model_input.revenue::Utilization|
| expenses::Payroll                                | PNL_PATH | model_input.expenses::Payroll   |
| expenses::Cost of Goods Sold                     | PNL_PATH | model_input.expenses::COGS      |
| expenses::Marketing                              | PNL_PATH | model_input.expenses::Marketing |
| expenses::General & Administrative               | PNL_PATH | model_input.expenses::G&A       |
| expenses::Research & Development                 | PNL_PATH | model_input.expenses::R&D       |
| balance_sheet::Accounts Receivable Days          | BS_ONLY/PNL | mi.balance_sheet::AR Days     |
| balance_sheet::Accounts Payable Days             | BS_ONLY/PNL | mi.balance_sheet::AP Days     |
| balance_sheet::Inventory Days                    | BS_ONLY/PNL | mi.balance_sheet::Inventory Days |
| balance_sheet::Deferred Revenue (% of Revenue)   | BS_ONLY/PNL | mi.balance_sheet::Deferred Rev |
| balance_sheet::Prepaid Expenses (% of Revenue)   | BS_ONLY/PNL | mi.balance_sheet::Prepaid     |

Source-of-truth pin: `GPT_AUTHORED_LEVER_IDS` at
[handler.py:50-58](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L50-L58)
+ WC IDs alongside; mirrored in
[restoration_loop.py:149-166](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L149-L166).

**Triggered by:** restoration loop returning `EXHAUSTED` or
(post-P3.26 Commit 1) `ITERATING_STILL` with non-empty
`failing_metrics`.

### Handler C — payroll headcount schedule (canonical payroll writer)
**File:** [post_intake_headcount/schedule.py](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py)
(`estimate_payroll_headcount_schedule_with_gpt` at
[schedule.py:2180](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2180))
**Authority:** authors the canonical `payroll_headcount.quarter_totals`
schedule. The apply chain
(`apply_payroll_supported_capacity_to_model_input` +
`apply_payroll_headcount_payload_to_model_input` +
`apply_derived_driver_policies_to_model_input` +
`build_python_finmo_json`) propagates the dollars to ALL FOUR
payroll surfaces aligned BY DESIGN:
- payroll_headcount.quarter_totals.payroll
- model_input.expenses::Payroll
- finmo.pl.Payroll
- finmo.quarter_rows.payroll

Assertions
`assert_payroll_headcount_model_input_applied` +
`assert_finmo_payroll_matches_headcount_schedule` enforce the
alignment with zero tolerance — see doctrine pin in
[feasibility_repair.py:9-23 module docstring](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L9-L23).

**Triggered by:** payroll feasibility failures via P3.26 Commit 2's
`route_payroll_feasibility_to_handler_c` at
[feasibility_repair.py:107](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L107).

### Stage-ramp contract handler (GPT-driven)
**File:** [post_intake_contracts/runner.py](../../python/client_intake_and_finmo/post_intake_contracts/runner.py)
(`_estimate_stage_ramp_contract_with_gpt` at
[runner.py:2027](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2027); python-first wrap at
[api_handlers/intake_consult.py:94](../../python/api_handlers/intake_consult.py#L94))
**Authority:** writes `stage_ramp_contract.quarter_ramp_grid` with
per-quarter `rev_max`, `utilization_cap`, and stage classification.
Validator: `_validate_stage_ramp_contract_payload` at
[runner.py:632](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L632).

### Restoration loop (deterministic algebra)
**File:** [post_intake_target_solver/restoration_loop.py](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py)
**Authority:** per-quarter solver writes to the same lever
catalogue as Handler GPT-Exhaustion, plus driver bounds from the
NAICS cohort cascade. Bounds resolved once per restoration entry,
not per outer pass — see snapshot logic at
[restoration_loop.py:986-1004](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L986-L1004).

### Payroll iterative refinement (initial-grid path)
**File:** [post_intake_initial_grid/runner.py](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py)
**Authority:** narrow — adjusts payroll dollars locally within an
initial-grid round-budget. Pre-P3.26 this was the *only* repair
path for payroll feasibility violations. Post-P3.26 Commit 2,
payroll feasibility failures are routed via Site A to
`route_payroll_feasibility_to_handler_c`, so the iterative refinement
remains as a per-grid local adjustment but no longer carries
end-to-end repair responsibility for feasibility issues.

### Cash-buffer (no authoring handler)
**Authority:** none. The cash-buffer minimum is enforced as a
fail-fast at finalize
(`post_intake_cash_buffer_violation@post_intake_finalize_validation_global`)
but no upstream handler is invoked to re-author cash policy when
the violation surfaces. This is the architectural shape of Pattern
P4 / P7 in the sweep summary.

---

## §2 Contract / constraint inventory

### Contract 1 — `stage_ramp_contract.quarter_ramp_grid`
**Definition:** `_stage_ramp_contract_schema` at
[post_intake_contracts/runner.py:598](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L598).
**Persistence:** part of model_input / draft state.
**Consumed by:** initial-grid revenue ramping;
`_compact_stage_ramp_contract_for_prompt` at
[quarter_grid.py:996](../../python/client_intake_and_finmo/quarter_grid.py#L996)
for handler prompts; finalize-stage validators.
**Handlers with authority over fields this constrains:**
- Stage-ramp handler (writes the contract itself).
- Handler GPT-Exhaustion (writes revenue::Unit Price / Capacity /
  Utilization — which together determine quarterly revenue — but
  **does NOT consult `quarter_ramp_grid.rev_max`** when authoring.
  This is the architectural gap P3.27 NexGen investigation
  surfaced and the sweep's stage_ramp_contract_invalid failures
  (SwiftLogix, SwiftCargo, Arrowline) corroborate.

### Contract 2 — payroll_revenue_economic_feasibility
**Definition:** assertion in post-grid + finalize feasibility
checks (`payroll_revenue_economic_feasibility_failed`).
**Consumed by:** initial-grid global feasibility check; finalize
global validation.
**Handlers with authority:** Handler C (canonical writer post-P3.26
Commit 2).

### Contract 3 — cash-buffer minimum (SQL cash-policy buffer)
**Definition:** SQL `cash_policy.required_buffer` per planning
mode and business stage.
**Consumed by:**
`post_intake_cash_buffer_violation@post_intake_finalize_validation_global`
fail-fast.
**Handlers with authority:** **NONE** (see §1 gap).

### Contract 4 — accounting equation (Assets = Liab + Equity)
**Definition:** Phase 9 P3.17 introduced
`accounting_equation_violation` fail-fast (commit `0e4dadf`).
**Consumed by:** post-FINMO build assertion.
**Handlers with authority:** indirect — every handler that writes
expense or balance-sheet drivers participates; the FINMO build
itself reconciles.

### Contract 5 — revenue driver formula
**Definition:** P3.22 Part 2 contract:
`FINMO revenue == sum(Capacity × Unit Price × Utilization)` per
quarter (`revenue_driver_formula_contract_failed`).
**Consumed by:** post-grid invariant check.
**Handlers with authority:** Handler GPT-Exhaustion (writes the
three revenue levers); restoration loop solver. Both can break
this contract if the FINMO build rounds differently than the
driver-product rounds (sweep's Pinnacle Logistics failure with
delta=0.035 / ~$10M = 3 ppb suggests precision threshold issue).

### Contract 6 — realism band (cohort + planning_mode)
**Definition:** per-NAICS, per-metric band rows in
`post_intake_finalize_realism_check_*` plus planning-mode floor
policy.
**Consumed by:** realism validator
(`validate_industry_realism_bands`).
**Handlers with authority:** Handler GPT-Exhaustion (PNL + WC
levers); restoration loop solver. Both consult the bands via the
restoration-loop driver-bound resolver and the forecast classifier.

### Contract 7 — viability trajectory (6 metrics)
**Definition:**
`_VIABILITY_TRAJECTORY_METRICS` at
[restoration_loop.py:73-83](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L73-L83).
**Consumed by:** `_evaluate_viability` after each restoration
outer pass.
**Handlers with authority:** Handler GPT-Exhaustion; restoration
loop (drives 3 solver targets toward viability ramps).

### Contract 8 — payroll-headcount alignment (Mirror Flavor 1)
**Definition:** Assertions
`assert_payroll_headcount_model_input_applied` +
`assert_finmo_payroll_matches_headcount_schedule`.
**Consumed by:** Handler C apply chain + feasibility repair apply
chain.
**Handlers with authority:** Handler C is the single writer post
P3.26 Commit 2. Handler GPT-Exhaustion writes `expenses::Payroll`
through model_input, **breaking** the alignment if invoked
independently — but the doctrine pin in
[feasibility_repair.py:18-23](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L18-L23)
forbids extending the handler's authority over Payroll outside
Handler C. The handler still *can* write `expenses::Payroll`
in the PNL scope; whether it should is the P1 design question
the doctrine leaves open.

---

## §3 Cross-reference matrix — (handler, field, contract)

| Handler          | Field written            | Contract                  | Awareness gap? |
| ---------------- | ------------------------ | ------------------------- | -------------- |
| GPT-Exhaustion   | revenue::Unit Price      | stage_ramp_contract (C1)  | **YES** (P2)   |
| GPT-Exhaustion   | revenue::Capacity        | stage_ramp_contract (C1)  | **YES** (P2)   |
| GPT-Exhaustion   | revenue::Utilization     | stage_ramp_contract (C1)  | **YES** (P2)   |
| GPT-Exhaustion   | expenses::Payroll        | payroll-headcount (C8)    | **YES** (P1)   |
| GPT-Exhaustion   | expenses::Payroll        | payroll-revenue feas (C2) | partial — finalize check still runs |
| GPT-Exhaustion   | revenue triple           | revenue driver formula (C5) | partial — assertion catches violations |
| GPT-Exhaustion   | revenue triple           | viability trajectory (C7) | aware — drives toward viability ramp |
| GPT-Exhaustion   | revenue triple           | realism band (C6)         | aware via forecast classifier |
| Stage-ramp       | quarter_ramp_grid        | stage_ramp_contract (C1)  | self — writes the contract |
| Handler C        | payroll dollars          | payroll-headcount (C8)    | aware — single writer |
| Handler C        | payroll dollars          | payroll-revenue feas (C2) | aware — feasibility-repair-driven invocation |
| Restoration solver | PNL + WC levers        | realism band (C6)         | aware via cohort bound cascade |
| Restoration solver | PNL + WC levers        | viability trajectory (C7) | aware via target ramps |
| Restoration solver | PNL + WC levers        | stage_ramp_contract (C1)  | **YES** (P2)   |
| Restoration solver | PNL + WC levers        | accounting equation (C4)  | indirect — FINMO reconciles |
| No handler       | cash policy              | cash-buffer (C3)          | **YES (no writer)** |

Three architectural gaps emerge:

1. **GPT-Exhaustion ignores stage_ramp_contract.** Both handlers
   that write revenue levers (Unit Price / Capacity / Utilization)
   do so without consulting the QoQ `rev_max` caps. Sweep
   stage_ramp failures (4 of 12) corroborate: GPT either produces
   invalid stage ramp contracts or its own revenue writes violate
   the contract's caps.
2. **GPT-Exhaustion writes Payroll independent of Handler C.**
   Despite the P3.26 Commit 2 doctrine pin, the handler's lever
   catalogue still includes `expenses::Payroll`. If invoked in a
   non-payroll-feasibility path, the handler could overwrite
   Handler C's payroll dollars and re-introduce the P3.25 Mirror
   Flavor 1 divergence.
3. **Cash-buffer has no repair authority.** 3 of 12 sweep failures
   are `post_intake_cash_buffer_violation` — there is no upstream
   re-author path. The acceptance handler chain terminates at
   finalize without invoking any handler equipped to adjust cash
   policy, funding levers, or expense levers in service of the
   buffer.

---

## §4 Reconciliation gaps (Pattern P1 instances)

### Payroll dollars (four surfaces)
- payroll_headcount.quarter_totals.payroll
- model_input.expenses::Payroll
- finmo.pl.Payroll
- finmo.quarter_rows.payroll

**Writes that update which surfaces:**
- Handler C apply chain: all four (BY DESIGN, with zero-tolerance
  assertions).
- Handler GPT-Exhaustion writing `expenses::Payroll`: model_input
  only. FINMO is rebuilt from model_input, so finmo.pl.Payroll
  and finmo.quarter_rows.payroll update too — but
  `payroll_headcount.quarter_totals.payroll` does **not**. P3.25
  documented this as the CareFirst divergence.

**Reconciliation mechanism:** None automatic. P3.26 Commit 2
addressed it by routing payroll feasibility failures back through
Handler C as the single writer. The handler module's writable
catalogue *still* includes Payroll; this is a doctrine pin
(comment-level), not a code-enforced constraint.

**Risk:** Medium. The sweep did not detect a recurrence today, but
nothing in the codebase prevents Handler GPT-Exhaustion from
writing Payroll in a future invocation that doesn't route through
Handler C first.

### Revenue triple (Unit Price × Capacity × Utilization)
- Surfaces: model_input::revenue rows × Capacity × Utilization;
  FINMO revenue per quarter.
- Contract: `FINMO revenue == sum(Capacity × Unit Price ×
  Utilization)`.
- Pinnacle Logistics failure at 3 ppb suggests rounding tolerance
  vs precision boundary — investigation in P3.22 Part 2 set the
  contract; tolerance may need a controlled relaxation.

---

## §5 Doctrine compliance review (last 30 days)

Commits that granted or modified handler authority over any field:

| Commit       | Date       | Change                                                  | Surfaces analysis? | Contract analysis? |
| ------------ | ---------- | ------------------------------------------------------- | ------------------ | ------------------ |
| `0e4dadf`    | 2026-05-?? | P3.17 accounting equation fail-fast                     | Yes (P3.17 audit)  | Yes (per metric)   |
| `8a36ed0`    | 2026-05-?? | P3.7 forecast-driven EXHAUSTED + handler scope          | Yes                | Yes                |
| `db9561b`    | 2026-05-?? | P3.8 viability trajectory math fix                      | Yes                | Yes                |
| `dca4fae`    | 2026-05-?? | P3.22 Part 2 revenue driver formula single source       | Yes                | Yes                |
| `9cac970`    | 2026-05-?? | P3.24 Commit 2 payroll feasibility (later superseded)   | **No**             | Partial            |
| `26d2002`    | 2026-05-?? | P3.24 Commit 1 ITERATING_STILL trigger (later superseded) | Yes              | Yes                |
| `97b1c8f`    | 2026-05-?? | P3.26 Commit 2 payroll feasibility routes to Handler C  | **Yes**            | **Yes**            |
| `1f0170d`    | 2026-05-18 | P3.26 Commit 1 restoration trigger broadening           | Yes                | Yes                |
| `60fc7a3`    | 2026-05-18 | P3.26 fix2 sequence_step_scope wrap                     | Implicit           | Implicit           |

**Retrospective gap:** P3.24 Commit 2 (Pattern P1 / Mirror Flavor
1) was the only commit in this 30-day window that lifted handler
authority without a clean surfaces analysis. P3.26 Commit 2
explicitly restored discipline (single writer + doctrine pin in
module docstring).

---

## §6 Recommended remediation paths

| Gap                                                | Fix shape                                                                                  | Est. LOC | Risk   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------ | -------- | ------ |
| GPT-Exhaustion ignores stage_ramp_contract (P2)    | Add awareness: handler prompt includes `quarter_ramp_grid.rev_max` per quarter; structured-output validator checks the per-quarter QoQ vs `rev_max` before accepting. | 60-100   | Med    |
| GPT-Exhaustion writes Payroll outside Handler C    | Restrict authority: remove `expenses::Payroll` from `GPT_AUTHORED_LEVER_IDS` ([handler.py:54](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L54)). All payroll repair routes through Handler C. | ~20      | Low    |
| Cash-buffer has no repair authority (P4/P7)        | New route: at finalize-stage `post_intake_cash_buffer_violation`, route to a cash-pass-aware handler (Handler GPT-Exhaustion with cash-policy + WC lever scope, or a new dedicated cash-buffer handler). Pattern mirrors P3.26 Commit 2's payroll feasibility routing. | 150-200  | Med    |
| Revenue driver contract tolerance (Pinnacle)       | Investigate Pinnacle's 0.035 / $10M delta. Either widen tolerance to absorb FP noise, or fix the FINMO-vs-driver-product rounding gap. | 20-50    | Low    |
| Workbook V-4 cannot be exercised without Excel-open | Build a one-shot V-4 verifier that opens each GENUINE_PASS workbook via libreoffice/excel headless, saves, re-reads. Or compute baseline deltas analytically from `model_input` + `audit_source` json. | 60-100   | Low    |
| Stage_ramp_contract_invalid (3 of 4 failures)      | GPT structured-output stability: tighten the validator to surface the *specific* utilization_cap / rev_max contradiction in the error message so the next round can self-correct. | 30-50    | Low    |

**Sequencing recommendation:**

1. **First** — fix the workbook V-4 verifier (P3.28 follow-up).
   Without it, every future sweep is blind to Pattern P1
   regressions. Low risk, modest LOC.
2. **Second** — restrict Handler GPT-Exhaustion's Payroll
   authority. Lowest LOC, lowest risk, directly enforces P3.26
   Commit 2's doctrine pin in code.
3. **Third** — investigate and resolve the revenue driver
   contract tolerance issue. Small scope, hardens P3.22 Part 2.
4. **Fourth (parallel)** — add `stage_ramp_contract` awareness to
   the GPT-Exhaustion handler. Higher LOC, but the highest-yield
   gap given the sweep's 4 stage_ramp failures.
5. **Fifth** — design the cash-buffer repair path. Largest scope;
   should be staged as a separate work item with its own
   surfaces + contract analysis (doctrine 3-question check).

---

## §7 Open architectural questions

1. **Handler-C-payroll-pin vs handler-catalog-payroll-presence.**
   The P3.26 Commit 2 module docstring forbids extending payroll
   authority outside Handler C, but
   `GPT_AUTHORED_LEVER_IDS` still lists `expenses::Payroll`. Is
   the doctrine pin sufficient, or should the catalog be
   tightened? (See §6 sequencing item #2.)
2. **Cash-buffer remediation: which scope?** A cash-buffer repair
   handler could be (a) cash-policy authoring, (b) funding-lever
   authoring (debt issuance, equity injection), (c) expense
   compression to grow ending-cash, or (d) all of the above.
   Each implies a different scope envelope and a different set of
   surfaces to keep aligned. User direction needed.
3. **Stage-ramp contract authority — who owns it during
   exhaustion?** Currently the stage-ramp handler is the writer;
   Handler GPT-Exhaustion is a consumer-in-name-only (does not
   read it). When exhaustion fires AFTER stage-ramp acceptance,
   should the handler be allowed to *update* the contract (e.g.
   relax a `rev_max`)? Or should it be strictly read-only? The
   sweep's 4 stage_ramp failures are upstream of exhaustion, so
   they don't speak to this question directly.
4. **V-2 inference vs Excel-open verification.** Today's CSV
   marks 16 drafts GENUINE_PASS with `v2_model_status =
   OK_inferred`. Should the sweep harness require a closed-loop
   Excel-open verification before recording GENUINE_PASS, or is
   the runner-side validation evidence enough? See §6 item #1.
5. **Pattern P1 surveillance — periodic vs continuous?** The
   payroll Mirror Flavor 1 fix (P3.26 Commit 2) addressed the
   acute issue but did not add a continuous regression guard.
   Should the workbook V-4 check be promoted from "sweep memo
   item" to "per-run assertion"? That would catch any future P1
   reintroduction instantly.

User direction required before any code changes per the P3.28
read-only directive.
