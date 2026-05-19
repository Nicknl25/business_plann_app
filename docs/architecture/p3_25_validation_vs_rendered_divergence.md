# Phase 9 P3.25 — Validation-vs-Rendered State Divergence

**READ-ONLY investigation. No fixes. No sweep work.**

The CareFirst run reported PASSED 16/16. The workbook delivered to the operator shows cash going to **−$281,014** at Q20, EBITDA negative all 20 quarters, total equity negative starting Q15. These cannot both be true.

This memo answers: **does "PASSED" mean what we think it means?**

**Answer: No. The validators and the workbook evaluate different state for the same draft.** The divergence is real, concrete, and reproducible. Yesterday's passing runs did NOT have this divergence — it is new in the P3.24-verification CareFirst run.

## 1. The smoking gun (CareFirst draft `422f64a792c247d1b423eaf8c0f81e65`)

For the same draft, the same DB row:

| Quarter | `model_input.expenses::Payroll` | `payroll_headcount.quarter_totals[].payroll` | Difference |
|---|--:|--:|--:|
| Q1 | 107,440 | **142,725** | −35,285 |
| Q5 | 110,666 | **147,008** | −36,342 |
| Q10 | 113,985 | **151,419** | −37,434 |
| Q11 | 113,985 | **151,419** | −37,434 |
| Q15 | 117,403 | **155,958** | −38,555 |
| Q20 | 120,926 | **160,639** | −39,713 |

`finmo_json.quarter_rows[].payroll` and `finmo_json.pl[Payroll].values` BOTH equal the `model_input` numbers (107,440 Q1 → 120,926 Q20). The validator reads the persisted FINMO; the workbook reads the persisted payroll_headcount via a chain through the Payroll Schedule sheet.

**Materialized impact** (Excel formula chain at [finmo_sheet.py:188](../../client_statements_output_excel/finmo_sheet.py#L188)):
```
EBITDA = Gross Profit − (Marketing + R&D + Lease + Payroll + G&A)
```
Q11 with the workbook's Payroll (151,419):
```
EBITDA Q11 = 272,073 − 64,779 − 3,239 − 7,500 − 151,419 − 77,735 = −32,599
```
matches the user's reported workbook Q11 EBITDA exactly.

Q11 with the validator's Payroll (113,985):
```
EBITDA Q11 = 272,073 − 64,779 − 3,239 − 7,500 − 113,985 − 77,735 = +4,835
```
matches the persisted FINMO Q11 EBITDA exactly.

**Same formula, two source values, two trajectories, two opposite verdicts.**

## 2. Per-question answers

### Q1 — What state did the acceptance gate evaluate?

The acceptance gate at [post_intake_acceptance/gate.py:660](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L660) reads three persisted JSON columns from `intake_consult_drafts`:
- `finmo_json` (line 681)
- `realism_memo_json` (line 682) — built post-cash from `validate_industry_realism_bands(finmo_json, ...)` at [orchestrator.py:2355](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2355)
- `planning_run_json` (line 683)

Of the 16 checks, the ones the user names as having reported PASS despite catastrophic FINMO trajectory:

| Check | Reads | Why it "PASSED" |
|---|---|---|
| `ebitda_positive_by_q11` (acceptance check #16's component) | `realism_memo_json.results` (rows from `validate_industry_realism_bands(finmo_json)`) | `finmo_json.quarter_rows[11].ebitda = +4,835` (positive). The validator sees a passing trajectory. The workbook computes Q11 EBITDA = −32,599 from the Excel formula using Payroll=151,419 — but this number is computed at workbook-open time and is NOT what was persisted to finmo_json. |
| `loss_window_funded_through_q5` (viability metric) | Same realism memo path; computed against `finmo_json.quarter_rows[].ending_cash` | Persisted cash Q1=351,990 → Q5=349,294. Never negative through Q5 (per persisted finmo). |
| `operating_cash_flow_margin` | Realism band check on `finmo_json` | Persisted OCF positive most quarters; passes the band. |
| `net_income_margin` | Same | Persisted NI: −248,101 Q1 → +22,545 Q20 (per finmo). Within bands. |
| `ebitda_margin` | Same | Persisted EBITDA Q1=−247,360, turns positive at Q11. Within bands. |

**All 16 checks evaluate the persisted FINMO, which uses Payroll=107,440 Q1.** None of them ever sees Payroll=142,725.

### Q2 — What state got written to the workbook?

The workbook has TWO statement-state surfaces:

1. **Audit Source sheet** ([source_audit_sheet.py:30](../../client_statements_output_excel/source_audit_sheet.py#L30)):
   ```python
   for item in data.finmo_json.get(statement_key) or []:
     ...
     for idx, value in enumerate(values_21(item.get("values"))):
       cell = ws.cell(row=row, column=3 + idx, value=value)
   ```
   Direct values from `finmo_json.pl`/`balance_sheet`/`cash_flow`. **This is the same source the validator reads.** Hidden sheet (line 44: `ws.sheet_state = "hidden"`).

2. **FINMO sheet** ([finmo_sheet.py:154](../../client_statements_output_excel/finmo_sheet.py#L154)) — **Excel formulas that reference Model Inputs cells**:
   ```python
   _set_formula(ws, ..., "Revenue", col, f"={_mi(ctx, 'is::Revenue', col)}")
   _set_formula(ws, ..., "Cost of Goods Sold", col, f"={_fr(...,'Revenue',col)}*{_mi(ctx, 'is::Cost of Goods Sold', col)}")
   _set_formula(ws, ..., "Payroll", col, f"={_mi(ctx, 'is::Payroll', col)}")
   _set_formula(ws, ..., "EBITDA", col, "=Gross Profit - SUM(Marketing:G&A)")
   ```
   Every line is a formula; the formulas re-compute the three statements live from the Model Inputs sheet at workbook open time.

The Model Inputs Payroll cell ([model_inputs_sheet.py:134](../../client_statements_output_excel/model_inputs_sheet.py#L134)) links to:
```python
"Payroll": (PAYROLL_SHEET, "Total Payroll"),
```
i.e., `=Payroll Schedule!{Total Payroll row}`. The Payroll Schedule sheet's `Total Payroll` row is computed from `data.payroll_headcount` (the persisted JSON column).

**Result:** the FINMO sheet's Payroll = `payroll_headcount.quarter_totals[].payroll` = 142,725 → 160,639. The Audit Source sheet's Payroll = `finmo_json.pl["Payroll"].values` = 107,440 → 120,926. Same workbook, two different sheets, two different values.

### Q3 — Source the divergence

**Same DB row. DIFFERENT JSON columns. The two columns disagree.**

The single SQL `UPDATE` chain at run-complete time writes BOTH:
- `finmo_json` (from in-memory `final_finmo_json` after the orchestrator's Phase B finishes; the Payroll row in this finmo = 107,440)
- `payroll_headcount` (the schedule the initial-grid phase last set; quarter_totals.payroll = 142,725)

The intermediate writer:
- [intake_consult_draft.py:1900-1902](../../python/client_intake_and_finmo/intake_consult_draft.py#L1900-L1902) writes `payroll_headcount` if the caller passes it.
- [orchestrator.py:2749 → _persist_unified_convergence_state](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2749) writes finmo_json + model_input_json at finalize. It does NOT pass `payroll_headcount`, so that column retains whatever value the upstream caller (initial-grid path) wrote.

**The mutation timeline:**

1. Initial-grid `_build_and_apply_payroll_schedule` builds payroll headcount v1 (the original GPT-authored schedule). Calls `apply_payroll_headcount_payload_to_model_input` which writes v1 totals INTO `model_input.expenses.Payroll`. State is aligned.
2. Quarter-grid global invariants fires `payroll_revenue_economic_feasibility_failed` on v1.
3. **P3.24 Commit 2's `payroll_feasibility_repair`** (the new step I landed) re-authors payroll: schedule v2 (142,725 Q1). My commit calls `_apply_existing_payroll_authority` which re-runs `apply_payroll_headcount_payload_to_model_input` writing v2 INTO `model_input.expenses.Payroll`. Then builds finmo from updated model_input. State is aligned at v2.
4. `prepare_initial_grid_for_draft` returns; Phase B starts. The local `payroll_headcount_payload` (in the orchestrator) is v2 (142,725).
5. **Phase B's GPT exhaustion handler engaged with `tool_calls_used=4`** (persisted state confirms). The exhaustion handler has authority over `expenses::Payroll` (1 of its 12 PNL levers). It mutates `model_input.expenses.Payroll` from 142,725 back to 107,440 (re-asserting the original payroll as part of its broader plan). FINMO is rebuilt from the handler's mutated model_input — finmo.pl.Payroll now = 107,440 again.
6. `payroll_headcount.quarter_totals[].payroll` was NEVER updated to track the handler's lever change. It still = 142,725.
7. Finalize global invariants runs. The call passes BOTH model_input and payroll_headcount.
8. Persist to DB: model_input + finmo_json show 107,440; payroll_headcount shows 142,725.

This is doctrine Pattern 1 / Mirror Flavor 1 violation in its purest form: the same logical quantity (payroll dollars per quarter) has TWO authorities (Handler C's headcount schedule and the GPT exhaustion handler's PNL lever) writing to TWO surfaces (`payroll_headcount.quarter_totals` and `model_input.expenses.Payroll`) without a reconciliation step.

### Q4 — What is "Audit Source"?

"Audit Source" is a hidden workbook sheet that copies the persisted FINMO json directly into Excel cells (no formulas). Built at [source_audit_sheet.py:17-44](../../client_statements_output_excel/source_audit_sheet.py#L17-L44). It exists so an operator opening the workbook in Excel can see what the SERVER computed, distinct from what the live formulas re-compute. The title text at line 20 calls it "Persisted system outputs used only for checks and audit tie-outs."

For CareFirst:
- Audit Source Q20 EBITDA = `+29,806` (server-computed; what the validator passed against)
- Audit Source Q20 Cash = `+416,706`
- FINMO sheet Q20 EBITDA = `−9,907` (Excel-formula-computed from Model Inputs)
- FINMO sheet Q20 Cash = `−281,014`

**The acceptance gate is reading the same source as Audit Source (i.e., `finmo_json` directly). It cannot see what the FINMO sheet's formulas compute, because those formulas run at workbook open time, not server-side.**

### Q5 — Yesterday's passing runs

Direct DB query across the most recent persisted runs for the three businesses the directive named:

| Business | Draft (most recent) | `mi.expenses::Payroll Q1` | `headcount.qts.payroll Q1` | Divergence |
|---|---|--:|--:|--:|
| NexGen Software Solutions Inc. | 2d3da85054df4bfe… (2026-05-07) | 216,484 | 216,484 | **0** |
| Sunny Glaze Donuts | 30e442be68094989… (2026-05-07) | 46,493 | 46,493 | **0** |
| ExpressLogix Shipping Services | 4fd50ce10bc44218… (2026-05-07) | 349,482 | 349,482 | **0** |

**Yesterday's "passes" are real: zero divergence between the two surfaces.** For those runs, the workbook FINMO sheet and the persisted FINMO produce the same trajectory, so the validator's PASS matches what the operator saw.

The divergence is **new with P3.24** — specifically with the path where:
- Commit 2's `payroll_feasibility_repair` re-authors the payroll headcount schedule (v2)
- AND the Phase B GPT exhaustion handler subsequently mutates `model_input.expenses.Payroll` independently of the headcount schedule

Yesterday's runs didn't trigger Commit 2's repair (it didn't exist yet) AND didn't have the exhaustion handler authoring Payroll downward in a way that desync'd from headcount. So they ran clean.

## 3. The architecture defect

The pipeline has FOUR sources of truth for payroll dollars per quarter:

| Source | Authority | Last writer at run end |
|---|---|---|
| `payroll_headcount.quarter_totals[].payroll` | Handler C (payroll iterative refinement / `payroll_feasibility_repair`) | Initial-grid (or my Commit 2 repair) |
| `model_input.sections.expenses["Payroll"].values` | Initial-grid `apply_payroll_headcount_payload_to_model_input` writes Handler C's schedule. Phase B GPT exhaustion handler then has authority to mutate this as one of its 12 PNL levers. | Whoever wrote last (handler in Phase B for CareFirst). |
| `finmo_json.pl["Payroll"].values` | Derived from `model_input.expenses.Payroll` via `build_python_finmo_json` | Phase B FINMO rebuild after handler |
| `finmo_json.quarter_rows[].payroll` | Same as above | Same |

Three of the four (model_input.expenses.Payroll, finmo.pl.Payroll, finmo.quarter_rows.payroll) are kept aligned by the FINMO build chain — change one, the others recompute. **`payroll_headcount.quarter_totals` is the orphan.** It is set by Handler C and never updated when downstream layers mutate Payroll dollars.

The doctrinal name for this gap: **doctrine §3 Pattern 1 (Mirror Flavor 1) violation — two surfaces representing the same logical quantity diverge because they have different authorities and no reconciliation step.** The audits have fought this pattern through P3.17, P3.19, P3.20 Stages 1–3; payroll specifically was P3.21 Part 1 Handler C. The new path P3.24 Commit 2 opened recreates the divergence at a different timing site.

**There IS an existing assertion meant to catch this**, at [schedule.py:3192 `assert_finmo_payroll_matches_headcount_schedule`](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3192). It compares `finmo.quarter_rows[].payroll` against `payroll_headcount.quarter_totals[].payroll` with NO TOLERANCE; if expected ≠ actual it raises `payroll_headcount_finmo_mismatch`.

The assertion is invoked from `assert_post_intake_global_invariants` ([fail_fast.py:2002](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L2002)) which the finalize validation calls at [finalize_post_intake.py:606-637](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L606-L637). For the CareFirst PASSING run, the finalize result was `{"status": "completed"}` — the assertion did NOT raise.

**Why didn't it raise on a clearly diverged state?** Three possibilities, none yet confirmed:

1. **The values WERE aligned at finalize-time, and one was mutated AFTER finalize but BEFORE persist.** Inspect the orchestrator's path between [orchestrator.py:2679 finalize](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2679) and [orchestrator.py:2749 _persist_unified_convergence_state](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2749) for any state mutation. There is intervening code (debt schedule snapshot, capital lease snapshot, pre_finalize_persist marker, etc.) — none should touch Payroll, but the audit needs to confirm.

2. **`payroll_headcount` passed to finalize is a different version than `payroll_headcount` persisted to DB.** Verify by checking the value the orchestrator passes to finalize vs the value last written to the DB column. The local `payroll_headcount` parameter could be a stale or transformed version.

3. **`assert_finmo_payroll_matches_headcount_schedule` did not actually execute** despite being in the call chain. There's a wrapping `try`/`except` at [fail_fast.py:1984-2018](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1984-L2018) that catches Exception and rewraps. If one of the assertions BEFORE the `assert_finmo_payroll_matches_headcount_schedule` line (e.g., `assert_payroll_headcount_payload_ready` at line 1992, `assert_payroll_headcount_model_input_applied` at line 1997) raised AND was caught silently somewhere, the chain might exit without the mismatch check ever running. But: the wrapping `except` at line 2012 re-raises as `post_intake_schedule_marker_missing`, which would have hard-failed the run. So this seems implausible.

Possibility (1) is the most likely. The persistence write at line 2749 calls `_persist_unified_convergence_state` which itself rebuilds `model_input_json` indirectly via `_model_input_with_controller_catalog` and writes it. If that rebuild path resets `expenses.Payroll` back to a snapshot that doesn't reflect the handler's commit, that explains it. **Confirming the exact mutation site is the next investigation step, NOT in scope for this memo.**

## 4. Answer to the user's foundational question

**Does "PASSED" mean what we think it means? NO** — not when Handler C's headcount schedule and the GPT exhaustion handler's PNL Payroll lever can independently write to the same logical quantity. The validator evaluates ONE surface; the workbook renders the OTHER; they can disagree without any layer noticing.

**Is the validator correct but the workbook rendering broken? NO** — the workbook is correct given its inputs (it applies the Excel formula to the persisted `payroll_headcount` quarter totals). The validator is correct given its inputs (it reads the persisted `finmo_json`). Both are correct in isolation. Their **inputs disagree** at the source-of-truth level.

**Implication for the architectural decisions on the table:**

- Anderson & Blake's NEW failure mode (P3.24 verification §2.1) — `payroll_revenue_economic_feasibility_failed at finalize` — is ALSO this same class of divergence, but caught by the policy-bound check rather than the headcount-mismatch check. Same root cause: the handler authored Payroll independent of the headcount schedule.
- The recommendation in P3.24 §7 (item 2, "extend Commit 2's pattern to finalize OR add payroll/revenue ratio guard to handler") is the WRONG fix shape. Adding more catches at later stages doesn't address the architectural defect.
- The CORRECT fix shape is **reconcile or rebind the payroll authority**: either (a) when the GPT exhaustion handler writes `expenses::Payroll`, it must ALSO update `payroll_headcount.quarter_totals[].payroll` (or the headcount payload as a whole), OR (b) remove the handler's authority over `expenses::Payroll` entirely (Handler C is supposed to own it; the exhaustion handler should not).

This is the foundational issue. Until it's resolved:

- **Every run's "PASS" verdict is potentially meaningless** if any Phase B handler authored `expenses::Payroll`.
- **The P3.23 sweep should NOT be restarted on the current architecture** — its results would be uninterpretable; we cannot trust the PASS counts.
- **The P3.24 sweep's CareFirst pass cannot be claimed as a real fix verification.** The validator passed; the plan delivered to the operator is catastrophic.

## 5. Yesterday's runs — re-examination

The "passes" reported for Sunny / Express / NexGen yesterday have zero `mi.expenses::Payroll` vs `headcount.qts.payroll` divergence — direct DB verification.

However, the broader question "are those passes real" requires verifying that ALL surfaces agree, not just payroll. The mi-vs-headcount alignment is one signal; mi-vs-handler-output is another. Yesterday's runs DID engage the GPT exhaustion handler (it's the canonical adaptation in the new path). So either:
- The handler didn't author `expenses::Payroll` on those runs, OR
- Some implicit reconciliation kept them aligned.

I did NOT trace the post-handler state alignment for yesterday's runs in this memo. **The honest answer: those passes are LIKELY real (the surfaces I checked agree), but the broader question of whether all other surfaces (revenue drivers, WC levers, etc.) similarly agree needs separate verification.**

## 6. Logs / artifacts cited

- CareFirst run (P3.24 verification): draft `422f64a792c247d1b423eaf8c0f81e65`, planning_run `5f80c47b4f84408c9294cfe96a860974`.
- Workbook: `C:\dev\Cilient Plans\CareFirst Home Health Services -- 05-18-2026 19-39-01.xlsx` (the file the user uploaded showing −$281k cash Q20).
- New Runner trace: `Apps\New Runner\05-18-2026 -- 422f64a792c247d1b423eaf8c0f81e65.txt`.
- Run log: [_p3_24_verification/draft2_carefirst.log](../../_p3_24_verification/draft2_carefirst.log).
- Acceptance verdict: `planning_runs.acceptance_verdict_json` for planning_run_id `5f80c47b4f84408c9294cfe96a860974` — 16/16 PASS.

## 7. What to do — open question for the user

The architectural decision the user faces:

1. **Lock the boundary.** Strip the GPT exhaustion handler's authority over `expenses::Payroll`. Handler C (payroll headcount) is the authority. The exhaustion handler can author its OTHER 11 PNL levers; Payroll is off-limits. Estimated 5-15 LOC + doctrine §6 update. Risk: low; aligns with doctrine §3 Pattern 3 (named authority owner per quantity).

2. **Bidirectional reconciliation.** When ANY handler authors `expenses::Payroll`, the headcount schedule's `quarter_totals[].payroll` must update to track. Bigger change because the handler's lever values may not correspond to a valid headcount schedule (the handler doesn't author FTE counts, just dollars). Risk: high — the headcount-schedule contract requires FTE × wage math.

3. **Surface the divergence as a hard-fail.** Find the reason `assert_finmo_payroll_matches_headcount_schedule` didn't catch this; ensure it always fires. Doesn't fix the root cause but ensures PASS verdicts are real.

The directive's question — "is the validator correct but the workbook broken, or vice versa?" — has the answer "neither; the surfaces disagree." The action depends on which authority is the canonical one for payroll, which is a doctrine §6 decision.

**P3.23 sweep restart is contraindicated until this is resolved.** Sweep PASS counts on the current architecture are not trustworthy signals.
