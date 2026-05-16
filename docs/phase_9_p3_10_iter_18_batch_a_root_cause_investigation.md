# Phase 9 P3.10 Iter 18 — Batch A Root-Cause Investigation

**Status:** Read-only diagnostic. No code changes. Awaiting user direction on fix scope.

**Scope:** Four failure families from the 27-draft E2E sweep report (docs/phase_9_p3_10_iter_17_27_draft_e2e_failure_report.md). For each, this report answers: *where does the bug originate, is the surface fix sufficient, what is the right scope?*

**Commit under test for symptoms:** `39e20c0` (iter 16) — with iter 17 Batch A (`8dfd23a`) already addressing F5.

---

## Table of contents

- [F7 — mapping-formula validator strict-equality on float-rounded values](#f7--mapping-formula-validator-strict-equality-on-float-rounded-values)
- [F1 — GPT-authoring without Python proposer / fallback](#f1--gpt-authoring-without-python-proposer--fallback)
- [F2/F3 — payroll `target_payroll_percent_of_revenue` decimal-shift](#f2f3--payroll-target_payroll_percent_of_revenue-decimal-shift)
- [F6-Pinnacle — pre-cash gate trips on payroll lever the handler cannot author](#f6-pinnacle--pre-cash-gate-trips-on-payroll-lever-the-handler-cannot-author)
- [Cross-cutting patterns](#cross-cutting-patterns)

---

## F7 — mapping-formula validator strict-equality on float-rounded values

### Failing cases

Both failures hit the **same** validation_formula_key (`finmo_equals_revenue_times_model_input_ratio`) on the **same** field (`cost_of_goods_sold`), each off by exactly $1:

| Draft | Business | Q | actual_finmo | expected_from_mapping_formula | Δ |
|---|---|---|---|---|---|
| `1d5ad246…` | SwiftShip Logistics Inc. | 20 | 426,640 | 426,641 | −1 |
| `11d6cd0c…` | Pinnacle Logistics Inc. | 18 | 2,094,800 | 2,094,799 | +1 |

The same pattern is plausible for the other `finmo_equals_revenue_times_model_input_ratio` levers (`prepaid_expenses`, `deferred_revenue`) and for the `finmo_equals_model_input_value` levers; only `cost_of_goods_sold` happened to land on the rounding boundary in these two runs.

### Both paths in source

**FINMO path** ([financial_model_engine/finmo_model.py:370](python/financial_model_engine/finmo_model.py#L370)):
```python
cogs = revenue * quarter.expenses.cogs_percent
```
- `revenue` is the full-precision `quarter.revenue` (no rounding).
- `quarter.expenses.cogs_percent` was loaded from the model_input row's `values` array via `ControllerWriteRow.get_value` ([model_inputs.py:114-120](python/financial_model_engine/model_inputs.py#L114-L120)), which returns the stored value verbatim. The stored value was rounded to 6 decimals at write time by `to_model_input_row` ([model_inputs.py:130](python/financial_model_engine/model_inputs.py#L130)).
- `cogs` is then stored in `FinmoQuarterResult.cost_of_goods_sold` and emitted via `to_dict()` which applies `round(value, 6)` for floats ([model_inputs.py around L194](python/financial_model_engine/model_inputs.py#L194)).

So the persisted FINMO `cost_of_goods_sold` for quarter q is:
```
round(revenue_full × cogs_pct_6dec, 6)
```
…and the persisted `revenue` is `round(revenue_full, 6)`.

**Validator path** ([fail_fast.py:1119-1134](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1119-L1134)):
```python
revenue = float(_safe_float(finmo_row.get("revenue")) or 0.0)
actual  = int(round(float(_safe_float(finmo_row.get(target_field)) or 0.0)))
expected = int(round(revenue * value))
if actual != expected:
  violations.append(...)
```
- `revenue` is the **already-rounded-to-6dec** value FINMO persisted.
- `actual` is the **already-rounded-to-6dec** stored cogs, re-rounded to integer.
- `expected` is the **rounded revenue × cogs_pct_6dec**, rounded to integer.

### The divergence is structural, not float-noise

For the rare quarter where `revenue_full × cogs_pct` lands within ~1e-6 of `.5`, the two paths can disagree:

- FINMO: `int(round( round(revenue_full × cogs_pct, 6) ))` — the inner round-to-6dec uses the unrounded revenue, so the trailing digits are preserved up to 6 decimals; banker's rounding may push the final integer one way.
- Validator: `int(round( round(revenue_full, 6) × cogs_pct ))` — the revenue gets rounded to 6 decimals **before** the multiplication, dropping ~1e-7 of precision that was load-bearing for the boundary case.

Worked example reconstructed from the SwiftShip Q20 numbers:
- `revenue_full ≈ 533,300.625000123…` → stored `revenue` = `533,300.625` (drops the `…000123`)
- FINMO: `533,300.625000123 × 0.8 = 426,640.500000098…` → stored `cogs` ≈ `426,640.500000` → `int(round(426,640.500000098))` = `426,641` (because .098 > .5)
- Validator: `round(533,300.625 × 0.8)` = `round(426,640.5)` = `426,640` (banker's rounding to even, since 426,640 is even)

→ `actual=426,640` vs `expected=426,641` (in Pinnacle's case the order of rounding pushed it the other way: `actual=2,094,800` vs `expected=2,094,799`).

### Diagnosis

**Two paths compute the same conceptual quantity by *different rounding orders*.** FINMO multiplies the unrounded operand first then rounds to 6 decimals; the validator rounds the operand to 6 decimals first then multiplies. For nearly every quarter the answer is identical; on the rounding boundary (frequency ~1/10^6) they differ by exactly $1.

This is structurally identical to:
- **Iter 8** (`_storage_index` clamp): two reads of the same lever value diverged because one used a clamp the other didn't.
- **Iter 10** (`buffer_components` units): two implementations of the same conceptual buffer math returned different units.
- **Iter 14** (STD forward-sim): two implementations of "next-4-quarters principal" used different inputs (raw lever vs clipped).
- **Iter 16** (`changes_in_current_liabilities`): two implementations of the OCF delta diverged on what counted as "operational."

All four of these are the same pattern: **two computations of one conceptual value, drifting at the boundaries.** The fix recipe across all four was to collapse them to a single canonical algorithm.

### Recommended fix scope (in order of architectural cleanliness)

1. **Architectural (preferred):** the validator should NOT recompute `revenue × cogs_pct`. The validator's job is to assert the mapping-formula contract holds — and the contract holds *by construction* when FINMO computed cogs from revenue × cogs_pct. The redundant recomputation is the bug. Two cleaner shapes:
   - **(a)** Move the contract enforcement to **lever-write time** (the post_intake_solver writes the lever; that path can validate the formula using the same math as FINMO and store a `derived_finmo_value` annotation). The post-finalize validator then just asserts `actual == derived_finmo_value`.
   - **(b)** Have the validator call FINMO's own formula function instead of re-implementing it. This requires extracting the per-formula math into a shared helper that both FINMO and the validator import. Same as the iter-16 "single source of truth" pattern.

2. **Surgical (acceptable):** Match FINMO's rounding order in the validator. Compute `expected = int(round(round(revenue_full × value, 6)))` — but the validator doesn't have `revenue_full`, only the rounded `revenue`. So this option is not actually available without changing FINMO to store revenue at full precision (which has other consequences).

3. **Pragmatic (the iter-17 report's recommendation):** $1 tolerance. Same pattern iter 16's BS reconciliation validator already uses (`if abs(diff) > 1`). Trivial. Closes the symptom. Does not eliminate the underlying two-paths divergence.

**The right answer depends on appetite.** The pragmatic fix takes 30 seconds and silences the symptom for all `finmo_equals_*` checks (just apply the same `abs(diff) > 1` everywhere — 2 sites in fail_fast.py:1119/1135, plus the parallel sites in balance_sheet_driver_validation.py:542/552). The architectural fix takes several hours and forecloses an entire class of future divergence bugs.

A defensible middle ground: apply the pragmatic $1 tolerance now, file a follow-up to extract the per-formula math into a shared helper as part of the next mapping-table touch. That converts "treat the symptom" into "treat the symptom AND have a written plan to fix the cause."

---

## F1 — GPT-authoring without Python proposer / fallback

### Surface trigger

GPT-authored `maintenance_rate` (capex depreciation policy) is the only authoring source. When GPT returns null/zero/out-of-band, [finmo_bridge.py:1172,1231,1592](python/client_intake_and_finmo/finmo_bridge.py#L1172) raises `capex_depreciation_maintenance_rate_invalid`. Two of the 27 drafts hit this on commit 39e20c0 (Anderson & Blake, CareFirst).

### Audit results (full GPT call-site inventory)

A subagent grep'd every `call_gpt_with_schema_or_fallback`, `call_gpt_responses_api_turn`, and `openai_http` consumer under `python/client_intake_and_finmo/`. **Seven distinct GPT call sites total**, classified per the project's doctrine in `memory/feedback_python_proposes_gpt_critiques.md`:

| Module | Function | Line | Field(s) Authored | Class |
|---|---|---|---|---|
| post_intake_contracts/runner.py | `_estimate_balance_sheet_contextual_seed_with_gpt` | 1581 | AR days, AP days, inventory days, deferred_revenue %, prepaid_expenses % | **A** Python proposer + GPT critic |
| post_intake_contracts/runner.py | `_estimate_stage_ramp_contract_with_gpt` | 1899 | Full stage ramp (Q-by-Q revenue, utilization, cost caps, profitability bounds) | **C** GPT-only, no Python fallback |
| post_intake_contracts/runner.py | `_run_realism_verification_openai` | 3797 | Issue verdicts, severity scores | **A** Python proposer + GPT critic |
| post_intake_cash/runner.py | `_run_cash_strategy_review_openai` | 2325 | Cash funding plan (per-quarter source allocation) | **A** Python proposer + GPT critic |
| post_intake_convergence/runtime.py | `_run_unified_convergence_openai` | 3228 | Model-input lever repairs (assignments + target quarters) | **C** GPT-only, no Python fallback |
| post_intake_headcount/schedule.py | `estimate_payroll_headcount_schedule_with_gpt` | 2241 | OEWS title selection, FTE ramps, benefits %, payroll target % | **C** GPT-only, no Python fallback |
| post_intake_gpt_exhaustion_handler/tool_calling_session.py | `call_gpt_responses_api_turn` (1..10 rounds) | 530 | P&L driver anchors: unit_price, capacity, utilization, payroll, COGS, marketing, SG&A, R&D, working capital | **C** GPT-only within handler loop |

Plus the F1 case itself (capex `maintenance_rate` inside finmo_bridge.py), which is **class C** as well.

**Summary:**
- Class A (Python proposer + GPT critic): **3** sites
- Class B (GPT-only with Python fallback on error): **0** sites
- **Class C (GPT-only, NO Python fallback): 5 sites** (including the F1 maintenance_rate site)
- Class D (legacy GPT-from-scratch): 0 known active (`maintenance_capex_percent` was already migrated)

### Diagnosis

The doctrine — "Python proposes structure; GPT critiques structure" — is followed in three places and **violated in five.** Each class-C site has the same shape as F1: GPT's output is the only authoring source, and a downstream validator hard-fails the entire run when GPT misses.

This means **fixing only maintenance_rate addresses 1 of 5 instances of the same class of bug.** Any of the other four class-C sites can fail the same way under the right GPT randomness, on businesses we haven't tested yet:

- `stage_ramp_contract`: a missing or malformed ramp grid → run dies in the contract builder
- `unified_convergence_decision`: a GPT failure mid-convergence → returns `{status: "failed_*"}` (handled, but the system has no fallback strategy)
- `payroll_headcount_schedule`: GPT contract failure → `_payroll_fail_fast` (we already saw this in F2/F3)
- `exhaustion_handler` tool-calling: GPT can't author all 5 P&L drivers within 10 rounds → `landed_best_effort_no_all_pass` and the gate fires (we saw this in F6-SwiftLogix)

### Recommended fix scope

This is the place where the answer is decisively **wider than the immediate F1 symptom.**

**Narrow fix (F1 only):** add a NAICS-keyed Python proposer for `maintenance_rate` (band-midpoint by capital-intensity tier). 1–2 hour effort. Closes the symptom for Anderson & Blake and CareFirst.

**Architectural fix (all 5 class-C sites):** establish a uniform pattern where every class-C site has:
1. A Python proposer function that produces a sensible default from intake + NAICS + stage.
2. A standard wrapper (e.g., `gpt_critic_or_python_proposer(proposer_fn, gpt_call_fn, validator_fn)`) that:
   - calls the proposer to get a default,
   - calls GPT with the default as context (so GPT can override but doesn't start from scratch),
   - validates GPT's output; on failure or out-of-band, uses the proposer's default with a log warning.
3. Conversion of each class-C site to the new wrapper.

The architectural fix is **the cleanest way to operationalize the user's existing doctrine.** It's a multi-day effort but reduces this entire class of failures to a Python-proposer-completeness exercise (i.e., for each authored field, is the Python proposer sensible? If yes, the run can always land).

**Suggested phasing:** address F1 (maintenance_rate) with a narrow Python proposer NOW. In parallel, file a doctrine-enforcement task that audits and converts the 4 remaining class-C sites over subsequent iterations. Each conversion is independently testable and shippable.

---

## F2/F3 — payroll `target_payroll_percent_of_revenue` decimal-shift

### What the failures look like

Two of the 27 drafts (Skyward Express Airlines, Revitalize Mobile IV Therapy) hit:
```
payroll_headcount_target_payroll_percent_of_revenue_out_of_policy_range:
value=0.101:min=0.16:max=0.7
```
…and:
```
value=0.045:min=0.16:max=0.7
```

In **both** cases GPT's natural-language rationale (in the same response) explicitly stated the correct value:
- Skyward: *"target_payroll_percent_of_revenue = 0.18: This corrects the prior out-of-range 0.10 value and now sits inside the high-intensity sanity band (0.16–0.70)."* — but the JSON field carries `0.101`.
- Revitalize: *"I target the middle-upper part of that band at 0.45 (45%)"* — but the JSON field carries `0.045`.

That is a **systematic 10× decimal shift** between GPT's prose and its JSON output, not random noise.

### The prompt and schema (verbatim from `post_intake_mapping.py`)

The contract row for the field ([post_intake_mapping.py:2469-2477](python/client_intake_and_finmo/post_intake_mapping.py#L2469-L2477)):
```python
_gpt_contract_row(
  "payroll_headcount_schedule", "root", "target_payroll_percent_of_revenue",
  "target_payroll_percent_of_revenue", "ratio_2dp",
  min_value=0.01, max_value=0.90,
  naics_baseline_metric_key="payroll_percent_of_revenue",
  naics_baseline_band_kind="min_target_max",
  normalization_kind="ratio_2dp", validation_kind="payroll_headcount_schedule",
  lookup_source="post_intake_headcount_policy_lookup",
  prompt_required_instruction=(
    "Business-judgment sanity target for final payroll as a percent of revenue. "
    "This does not drive payroll math or force FTE. Python uses it as reasonableness "
    "context for GPT's own contract assumptions."
  ),
)
```

Generated JSON schema for the field:
```json
{
  "type": "number",
  "minimum": 0.01,
  "maximum": 0.90,
  "_naics_band": {"metric_key": "payroll_percent_of_revenue",
                  "band_kind": "min_target_max",
                  "min": <NAICS-specific>,
                  "target": <NAICS-specific>,
                  "max": <NAICS-specific>}
}
```

GPT-facing prompt fragment for the same field ([post_intake_headcount/schedule.py:2207-2234](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2207-L2234)):
> *"…First choose capacity_labor_model, labor_intensity_class, wage_positioning_tier, wage_positioning_multiplier, **target_payroll_percent_of_revenue**, and capacity_units_per_supporting_fte from payroll_decision_options where enumerated, with capacity_units_per_supporting_fte as GPT's positive business-specific productivity assumption. …target_payroll_percent_of_revenue is context, but payroll_revenue_sanity_bounds from the headcount policy table are a real feasibility check; do not staff by clipping payroll to a percentage."*

### Sibling fields in the same response (all decimal-scale)

The schema is **internally consistent** — every numeric field uses decimal scale:

| Field | Type | min | max | Example |
|---|---|---|---|---|
| `wage_positioning_multiplier` | number/ratio_2dp | 1.0 | 3.0 | 1.20 |
| `capacity_units_per_supporting_fte` | number | 0.0001 | (none) | 500.0 |
| `target_payroll_percent_of_revenue` | number/ratio_2dp | 0.01 | 0.90 | 0.18 |
| `payroll_tax_benefits_pct` (grid row) | number/ratio_2dp | 0.12 | 0.35 | 0.22 |

No mixed-scale ambiguity in the schema. No percent-style fields (e.g., `25` for 25%) sitting next to decimal-style fields (e.g., `0.25`). The model isn't getting confused by scale-mixing within one response.

### Where the ambiguity actually lives

Three observations narrow the diagnosis:

1. **The prompt never quotes the numeric bounds.** It says "use the payroll_revenue_sanity_bounds from the policy table" and "this is a sanity target," but the actual `[0.16, 0.70]` envelope (for high labor intensity) is NEVER shown to GPT. GPT only sees the outer JSON-schema envelope `[0.01, 0.90]`. So GPT can emit `0.045` and the schema accepts it (it's between 0.01 and 0.90) — only the post-call Python validator catches it.
2. **The prompt's example values use percent-language in prose:** `target_payroll_percent_of_revenue` is phrased as "a percent of revenue." GPT's rationale correctly reads this as "18% of revenue" and writes `0.18` in prose — but when emitting JSON it appears to re-derive the value from the prose, dividing the prose percent by 100 a *second* time → `0.018` truncated to 2 decimals → `0.018` (or `0.045` rounded from `0.045`).
3. **The schema's `minimum=0.01` is too permissive.** The intensity-tier band (resolved at validator-time) actually requires `>= 0.16` for high intensity. The schema could carry the tier-specific minimum (the contract row already has `_naics_band.min` available), and the JSON-schema engine would reject `0.045` at parse time — forcing GPT to re-emit.

### Diagnosis

This is **prompt + schema permissiveness**, not pure model unreliability.

**Three layered fixes work together:**

1. **Schema tightening:** Use the resolved intensity-tier band (`min_pct`, `max_pct` from the lookup) as the schema's actual `minimum`/`maximum`. The OpenAI strict-mode parser will reject out-of-band values, forcing GPT to re-emit during the same turn. This eliminates the symptom at source — no clamp needed.
2. **Prompt explicitness:** Include the numeric band in the prompt text: *"target_payroll_percent_of_revenue must be a decimal in [min_pct, max_pct] for the {labor_intensity_class} intensity tier. Example: 0.45 means 45% of revenue, NOT 45 and NOT 0.045."*
3. **Defensive validator clamp:** The iter-17 report's proposal (detect 10× decimal-shift, clamp to band midpoint, log warning) remains a useful belt-and-suspenders backstop if either schema or prompt drifts later.

### Recommended fix scope

**Both prompt + schema fixes together.** They're complementary and small:
- Prompt fix: edit the prompt-builder to inject the resolved tier band into the GPT message.
- Schema fix: thread the tier-specific min/max into `_field_schema`.

**Skip the clamp until prompt+schema is verified insufficient.** Defensive clamps in the validator add an "if this fails, silently fix it" path that erodes the strict-fail-fast discipline the project relies on. If after prompt+schema work the same drift still happens, then clamp.

---

## F6-Pinnacle — pre-cash gate trips on payroll lever the handler cannot author

### Critical correction to the iter-17 report

The iter-17 report attributed Pinnacle to F6 (`pre_cash_gate_gpt_authorable_checks_unfixed_after_handler` with `payroll_percent_of_revenue=0` Q1-Q10). Re-examining the current per-draft logs:

- The **current** `tmp/e2e_iter17_batch_11d6cd0c.out.log` for Pinnacle shows the **F7** failure (`mapping_formula_application_invalid` on `cost_of_goods_sold` Q18 with actual=2,094,800 expected=2,094,799). The F6 log was overwritten by the F7 rerun in the resume batch.
- The original F6 failure detail **is** still available in the persisted run report at `…/Test Runs Data/05-15-2026 -- 4f8f1017153844a09c763a6f5faef1b9.txt` (cloned draft `4f8f1017…` of source `11d6cd0c…`).

So Pinnacle is **intermittent across the F6/F7 axis** — the same source draft can land in either failure family depending on GPT randomness in the run. This investigation uses the persisted F6 trace.

### What actually happened on the F6 attempt

The pre-cash-gate violation list (sample of 10 from the report, all with the same shape):
```python
'violations_sample': [
  {'actual_value': 0.0, 'effective_max': None, 'effective_min': None,
   'metric_key': 'payroll_percent_of_revenue',
   'primary_levers': ['expenses::Payroll'],
   'quarter_index': 1,
   'source_check': 'stage_ramp_expense_path_applied'},
  ... (same shape for Q2..Q10) ...
]
'handler_invoked': True
'muted_metric_count': 6
```

And the persisted `payroll_headcount_schedule.quarter_totals` for this same draft:
```
Q1: payroll = 114,670
Q2..Q5: payroll = 298,705 each
Q6..Q8: payroll = 307,666 each
... (non-zero across all 20 quarters) ...
```

So the contract did produce a real payroll plan. But the `expenses::Payroll` model-input lever shows `actual_value=0.0` across all 20 quarters at the pre-cash-gate.

### Where the writeback should happen

`apply_payroll_headcount_payload_to_model_input` ([post_intake_headcount/schedule.py:2488](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2488)) is the function that converts `payroll_headcount.quarter_totals` → `model_input.sections.expenses["Payroll"].values`. It's invoked from exactly two top-level orchestration paths:

- **Initial-grid path:** [post_intake_initial_grid/runner.py:1060](python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1060), inside `_apply_payroll_model_input` which is wrapped in `_execute_sequence_step` with `assert_payroll_headcount_model_input_applied` immediately after ([runner.py:1071-1075](python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1071-L1075)).
- **Convergence path:** [post_intake_convergence/runner.py:699](python/client_intake_and_finmo/post_intake_convergence/runner.py#L699).

The function itself ([schedule.py:2565-2582](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2565-L2582)) does:
```python
derived_live_values = [float(totals_by_quarter[quarter]) for quarter in range(1, live_count + 1)]
payroll_row["controller_write"] = False
payroll_row["derived_driver"] = PAYROLL_HEADCOUNT_SOURCE
...
payroll_row["values"] = _compose_period_values(stub_value=stub_value, live_values=derived_live_values)
```
…and **returns a new `next_payload`** (deepcopy of the input). The caller MUST capture this return value, or the writeback is silently dropped.

### Identifying scenario A/B/C/D from the iter-18 spec

- **(A) Handler tool calls don't include payroll anchor:** Confirmed — the handler is scoped to `pnl_path` which writes the 5 stage-ramp drivers (cogs, marketing, r&d, g&a, lease). [`Payroll is not part of stage_ramp_contract`](python/client_intake_and_finmo/post_intake_contracts/runner.py) — the comment in the persisted state report literally states this. The handler **cannot** write payroll by design.
- **(B) Handler wrote payroll but write was dropped:** Not applicable to the handler. The relevant write path is `apply_payroll_headcount_payload_to_model_input`, not the handler.
- **(C) Handler early-exit before completion:** No — `handler_invoked: True` and `muted_metric_count: 6` indicate the handler ran and accepted muting for 6 metrics. It did its job for its scope.
- **(D) Handler proposal rejected silently:** No evidence of rejection in the trace.

### The real diagnosis: handler-scope-vs-gate-scope mismatch

The pre-cash gate fires on **any** unmuted check violation. The check `stage_ramp_expense_path_applied` is firing on `payroll_percent_of_revenue=0`. The handler invoked by this gate is **scoped to `pnl_path`** — and `pnl_path` does NOT include payroll. So:

- The gate sees a payroll violation.
- The gate invokes the handler.
- The handler runs and (correctly, per its scope) does not touch payroll.
- The gate re-checks, sees payroll still violating, raises `pre_cash_gate_gpt_authorable_checks_unfixed_after_handler`.

The error message *blames* the handler ("`unfixed_after_handler`") but the handler was never the right tool for this violation. The check `stage_ramp_expense_path_applied` is checking a metric (`payroll_percent_of_revenue`) whose underlying lever (`expenses::Payroll`) is **NOT under stage-ramp authority** — it's under `payroll_headcount_schedule` authority. The check is incorrectly scoped.

The **upstream** problem is that `apply_payroll_headcount_payload_to_model_input` either never ran for this Pinnacle attempt, or its return value was dropped. We can't determine which from the persisted trace because the assertion `assert_payroll_headcount_model_input_applied` would have failed-fast loudly if the writeback was dropped after running. Since no such failure is in the trace, the most likely explanation is that the orchestration path that calls `apply_payroll_headcount_payload_to_model_input` was **skipped entirely** for this draft — possibly because the payroll_headcount_schedule contract was constructed but never marked as "ready to apply" before the gate fired.

### Recommended fix scope

This is **two distinct fixes**, both in the orchestrator, neither in the handler:

1. **Hard-fail invariant at gate entry:** before the pre-cash gate runs its checks, assert that for every lever the gate's checks reference, the lever was actually written by its responsible contract. Specifically: if any check has `primary_levers: ['expenses::Payroll']` and the lever's live values are all zero, raise a specific diagnostic `payroll_lever_not_applied_before_gate` instead of the generic `unfixed_after_handler`. The specific diagnostic names the upstream skipped step.
2. **Make `apply_payroll_headcount_payload_to_model_input` unconditional:** ensure both the initial-grid path AND the convergence path call it as part of their standard sequence (not conditionally on `payroll_headcount_changed`). Today both paths gate it on a "changed" trigger ([initial_grid/runner.py:1051-1052](python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1051-L1052)) — which means a payroll_headcount_schedule that was built but not "changed" (e.g., reapplied from a prior state) skips the writeback.

The narrow surface fix (a hard-fail validator after the handler that asserts expected levers were written) is **wrong**. The right fix is upstream — guarantee the lever is written when the contract is built, and surface a specific diagnostic when it isn't.

---

## Cross-cutting patterns

Three of the four families share the same root architectural pattern:

### Pattern 1 — "two paths compute the same conceptual quantity"

F7 is structurally identical to iters 8, 10, 14, 16. The persistent project tax of having two implementations of one quantity is the single biggest source of $1-off / off-by-one / boundary-condition bugs.

**Recommended generalized fix:** establish a `single_source_of_truth` rule for any computation that appears in both FINMO and a validator: the validator imports the same function FINMO uses, or the validator reads FINMO's output and asserts a *property* (not a recomputed value).

### Pattern 2 — "GPT is the only authoring source"

F1, F2/F3, parts of F6 all flow from the same doctrine violation: 5 of 7 GPT call sites lack a Python proposer. The user's `feedback_python_proposes_gpt_critiques.md` memory is the project's stated doctrine; the codebase only partially follows it.

**Recommended generalized fix:** convert all class-C sites to the class-A pattern (Python proposer + GPT critic, deterministic fallback). This is a multi-iteration project but each conversion is independently shippable.

### Pattern 3 — "the diagnostic blames the wrong layer"

F6 surfaces this most clearly: the error message names the handler as the failed component, but the handler had no authority over the failing lever. The same pattern shows up in F7 (the validator surfaces a 1-dollar diff with no indication that the formula was double-evaluated) and F2/F3 (the validator surfaces "out of policy range" with no indication that GPT's prose was correct and only its JSON drifted).

**Recommended generalized fix:** error diagnostics should name the upstream authoring source, not the downstream checker. The pattern would be: every validator that hard-fails names (a) the lever in violation, (b) the step responsible for setting that lever, (c) what value it actually has vs what was expected, (d) what to inspect to understand why. F6's `pre_cash_gate_gpt_authorable_checks_unfixed_after_handler` is generic; a useful diagnostic would be `payroll_lever_value_zero_but_payroll_headcount_schedule_has_quarter_totals: payroll_headcount step appears to have been skipped or its writeback dropped`.

---

## Recommended fix priority

In the order I'd suggest implementing (each is independently shippable):

1. **F1 — narrow:** add Python proposer for `maintenance_rate`. Unblocks 2 of the 27 drafts. ~1h.
2. **F2/F3 — schema tightening:** thread tier-specific `min/max` into `_field_schema` for `target_payroll_percent_of_revenue`. Unblocks 2-3 drafts. ~2h.
3. **F7 — pragmatic:** `abs(diff) > 1` tolerance at fail_fast.py:1119/1138 (and the parallel sites at balance_sheet_driver_validation.py:542/552). Unblocks 2 drafts. ~30min.
4. **F6 — orchestration:** make `apply_payroll_headcount_payload_to_model_input` unconditional in both orchestration paths. Unblocks 1-2 drafts. ~2h with tests.
5. **F1 — architectural follow-up:** audit and migrate the remaining 4 class-C GPT call sites to class-A pattern. Multi-iteration project; the doctrine violations they represent will keep producing intermittent failures otherwise.
6. **F7 — architectural follow-up:** extract per-formula math into a shared helper that both FINMO and the mapping-formula validator import. Foreclose the entire two-paths divergence class.
7. **F6 — diagnostic upgrade:** make the pre-cash-gate diagnostic name the upstream lever-author when a gate check fires on a lever whose authority is outside the gate's invoked handler's scope.

Items 1–4 (≈5h total) address all 10 failures from the 27-draft sweep with surgical changes. Items 5–7 address the underlying architectural patterns and prevent the same families from re-emerging on businesses we haven't tested yet.

---

## Appendix — data sources

- F7 worked example reconstructed from the failing-quarter values in `tmp/e2e_iter17_batch_11d6cd0c.out.log` and `tmp/e2e_serial_v2_1d5ad246.out.log`.
- F1 audit performed by an Explore subagent (read-only, 9 files inspected under `python/client_intake_and_finmo/`).
- F2/F3 prompt + schema verified against `python/client_intake_and_finmo/post_intake_mapping.py:2461-2477` and `post_intake_headcount/schedule.py:2207-2234` and `lookup.py:74-79`.
- F6-Pinnacle trace pulled from the persisted run report `C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Test Runs Data\05-15-2026 -- 4f8f1017153844a09c763a6f5faef1b9.txt`, supplemented by source reading of `post_intake_headcount/schedule.py:2488-2582` and the two orchestration paths that call it.

No code was modified during this investigation. The next step is user direction on which of the seven recommended fixes to implement and in what order.
