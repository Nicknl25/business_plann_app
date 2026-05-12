# Bug C — Sunny Payroll Quarter-Total Rollup Mismatch — Diagnosis

**Status:** Diagnostic only. No code changes. Awaiting user authorization for fix.
**Surfaced by:** Sunny E2E run on fresh draft `01f163c4894e4ee38e11525faf29ef16` (2026-05-12, against API 5051 with C1-C5 loaded, `CONVERGENCE_TEST_MODE=true`).
**Hard-fail diagnostic:**
```
POST_INTAKE:payroll_headcount_quarter_total_mismatch@payroll_headcount_quarter_total_rollup:
Q1 quarter_totals.payroll=20777 calculated_from_title_rows=39620.
Payroll schedule quarter_totals must be a deterministic rollup of rows.
```

---

## 1. Where the values come from

### 1.1 The "expected" value (`calculated_from_title_rows=39620`)

Computed by [`_payroll_totals_by_quarter_from_rows`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2413) — a fresh recompute over the schedule's row data. For Sunny's Q1 the math is:

| staffing | title | sFTE | eFTE | annual_wage | benefits% | qwage | qbenefits | total |
|---|---|---|---|---|---|---|---|---|
| key_person | Owner and Manager | 1.00 | 1.00 | $75,820 | 0.22 | $18,955 | $4,170 | $23,125 |
| key_person | Lead Baker | 1.00 | 1.00 | $36,550 | 0.22 | $9,138 | $2,010 | $11,148 |
| supporting_staff | Fast Food and Counter Workers | 0.50 | 0.50 | $36,246 | 0.18 | $4,531 | $816 | $5,347 |
| | | | | | | | **Σ** | **$39,620** |

Each row's `total = ((sFTE + eFTE) / 2 × annual_wage / 4) + (qwage × benefits%)`. The same math the writer at [schedule.py:1794-1825](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1794) uses when it first builds `quarter_totals_by_index`.

### 1.2 The "provided" value (`quarter_totals.payroll=20777`)

The schedule was originally built with `quarter_totals[0].payroll = 39620` (matches the row sum). I confirmed this by querying both the source draft `6c7544ec…` and the cloned draft `01f163c4…` after the run — both have `quarter_totals[0].payroll = 39620` in the persisted `payroll_headcount` JSON.

So **`20777` is not what the schedule writer produced**. It's what the schedule held *during the validator call*, which is different from what was persisted.

### 1.3 The mutation site

[`feasibility_restoration._apply_headcount_rationalization`](python/client_intake_and_finmo/post_intake_solver/feasibility_restoration.py#L156-L228), invoked from [`restore_feasibility`](python/client_intake_and_finmo/post_intake_solver/feasibility_restoration.py#L423) when `verify_structural_feasibility` returns infeasible.

Lines 187-204:

```python
target_quarter_payroll = target_annual / 4.0
quarter_totals = adjusted_payroll.get("quarter_totals") or []
capped_qts: List[Dict[str, Any]] = []
for row in quarter_totals:
  ...
  new_row = dict(row)
  original = _safe_float(row.get("payroll")) or 0.0
  capped = min(original, target_quarter_payroll) if original > 0 else 0.0
  new_row["payroll"] = round(capped, 2)
  new_row["_phase_7_2_capped_for_capacity"] = True
  new_row["_phase_7_2_original_payroll"] = original
  capped_qts.append(new_row)
adjusted_payroll["quarter_totals"] = capped_qts
```

The lever caps `quarter_totals[i].payroll` at `target_annual / 4.0`. **`adjusted_payroll["rows"]` is NOT touched** — the writer's per-row breakdown (FTE / wages / benefits / per-row totals) is preserved unchanged.

### 1.4 Why the cap value is exactly 20777

For Sunny:

- `capacity_revenue_annual ≈ 4 × Q1 revenue ≈ 4 × 59,625 = 238,500`
- NAICS 311811 (commercial bakeries) `payroll_pct ≈ 0.3485` (computed from `_naics_payroll_pct` lookup or fallback)
- `target_annual = 238,500 × 0.3485 = 83,108`
- `target_quarter_payroll = 83,108 / 4 = 20,777`

`min(39,620, 20,777) = 20,777` → quarter_total stamped at 20,777, rows still sum to 39,620.

Verified arithmetically — `(20777 × 4) / 238,500 = 0.3485` exactly.

---

## 2. Why the divergence is now caught

The strict assertion at [schedule.py:2463-2485](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2463) (`_validate_quarter_totals_match_title_rows`) is part of the existing fail-fast layer that Commit 2 stopped downgrading. Pre-Commit 2 the orchestrator's `failed_downgraded_to_warning` block swallowed it; post-Commit 2 it propagates to the API as the structured diagnostic the operator now sees.

The assertion's intent is captured in its message:
> "Payroll schedule quarter_totals must be a deterministic rollup of rows."

Phase 7.2's `_apply_headcount_rationalization` violates that intent **by design** — it's an explicit override that decouples the cap from the row sum so downstream FINMO/realism see the rationalized number. The two design choices were never reconciled.

---

## 3. Universal-app implications

This affects **every business that triggers feasibility restoration with the headcount rationalization lever active**. The trigger condition is:

`current_annual > capacity_revenue_annual × naics_payroll_pct`

A business hits this whenever its operator-stated payroll exceeds the NAICS-cohort-implied payroll percentage of their capacity-driven revenue. Sunny hits it because she's running 2 key people + 0.5 supporting staff (≈$159K/year payroll) against a small donut shop revenue base. The rationalization caps her to ≈$83K/year (cohort-appropriate for bakeries).

Whether NexGen and Express also trigger the cap is data-dependent — the same fail-fast would surface there if their operator-stated payroll exceeds the cohort cap. Their current E2E hard-fail is on a debt-schedule violation (Bug A), so the payroll path may or may not be a downstream issue for them.

The fix is **universal-app**: it changes how rationalization expresses its result, applies identically to every NAICS / stage / planning_mode.

---

## 4. Fix options

Three viable options. I recommend **Option D**.

### Option D (recommended) — validator skips rollup check on flagged rows

When the validator sees `_phase_7_2_capped_for_capacity=True` on a quarter_total row, treat the rollup-vs-total comparison as expected to differ; instead validate that:

1. `_phase_7_2_original_payroll` matches the row-rollup (sanity: cap was applied to the correct base — no upstream corruption).
2. The capped value is `≤` `_phase_7_2_original_payroll` (cap reduces, not inflates).

If either consistency check fails, raise the same `payroll_headcount_quarter_total_mismatch` flag with detail naming the override.

**Pros:**
- One-file change (validator only); no writer rebuild risk.
- Preserves the rationalization semantic ("we explicitly override this; here's the original we capped from").
- Other consumers continue to see the consistent capped quarter_totals.
- Smallest blast radius.

**Cons:**
- Weakens the "deterministic rollup" invariant for one specific override path.
- Requires the rationalization marker to remain on every flagged row indefinitely (already true — it's set once and propagated by deepcopy through downstream paths).

**Code site:** [`schedule.py:2463-2485`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2463) (validator). One-paragraph change inside the per-quarter loop.

### Option E — rebuild row data when capping

Inside `_apply_headcount_rationalization`, when capping a quarter, **also** scale per-row data so the row rollup matches the new total. The proportional approach:

```python
scale = capped / original  # e.g. 20777 / 39620 = 0.5244
for row in rows where row["quarter_index"] == this_quarter:
    row["ending_fte"] = round(row["ending_fte"] * scale, 2)
    row["starting_fte"] = round(row["starting_fte"] * scale, 2)
    # quarterly_wage_cost / quarterly_taxes_benefits get recomputed by the writer
```

**Pros:**
- Preserves the "rollup must match" invariant exactly.
- Communicates the rationalization semantic correctly: "your headcount is too high for capacity → reduced FTEs."

**Cons:**
- Touches multiple per-row fields. Other downstream consumers of FTE (capacity-driven revenue formulas, headcount narrative) see different FTE counts than the operator stated. Some may have fail-fasts that catch the divergence.
- Continuity assertions ([`_enforce_forward_fte_continuity`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2428)) may break because Q1 ending_fte changes don't match Q2 starting_fte.
- Larger blast radius — a writer-side change that ripples through the whole schedule.

### Option F — remove the rationalization lever entirely

Treat operator-stated payroll as ground truth; if the structural feasibility check sees overstaffing, raise `structural_feasibility_check_failed` and let the planning consultant communicate the issue to the user explicitly.

**Pros:**
- Cleanest semantics. Operator-stated reality is sacred.
- No invariant violation.

**Cons:**
- Breaks the intent of the Phase 7.2 cascade ("customer always gets a plan; the cascade adjusts the inputs"). Some businesses that previously got a plan will now hard-fail at the structural check.
- Architectural shift (out of scope for a single-bug fix).

---

## 5. Recommended fix scope (Option D)

### 5.1 The change

In [`schedule.py:2463-2485`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2463) (`_validate_quarter_totals_match_title_rows`), inside the per-quarter loop:

```python
# Phase 9 P3.10 Bug C fix — Phase 7.2 headcount rationalization
# explicitly caps quarter_totals.payroll below the row-level rollup as
# an intentional override (the operator's stated headcount exceeds the
# capacity-implied level). When the cap is active, validate the cap's
# integrity instead of the rollup match: the cap must reduce (not
# inflate) and the recorded original must equal the row rollup so the
# cap was applied to the correct base.
qt_row = next(
    (item for item in (schedule.get("quarter_totals") or [])
     if isinstance(item, dict) and int(item.get("quarter_index") or 0) == quarter_index),
    None,
)
if (
    isinstance(qt_row, dict)
    and bool(qt_row.get("_phase_7_2_capped_for_capacity"))
):
    original = int(round(float(_safe_float(qt_row.get("_phase_7_2_original_payroll")) or 0.0)))
    if original != expected:
        _payroll_fail_fast(
            "payroll_headcount_quarter_total_mismatch",
            f"Q{quarter_index} _phase_7_2_original_payroll={original} does not match "
            f"calculated_from_title_rows={expected}. Cap was applied to a different base "
            f"than the current row data; upstream mutated rows after rationalization.",
            stage="payroll_headcount_quarter_total_rollup",
            details={"quarter_index": quarter_index, "original": original, "expected": expected, "provided": provided},
        )
        continue
    if provided > original:
        _payroll_fail_fast(
            "payroll_headcount_quarter_total_mismatch",
            f"Q{quarter_index} capped quarter_totals.payroll={provided} exceeds "
            f"_phase_7_2_original_payroll={original}. Cap must reduce, not inflate.",
            stage="payroll_headcount_quarter_total_rollup",
            details={"quarter_index": quarter_index, "original": original, "provided": provided},
        )
        continue
    continue  # cap is consistent; skip the rollup-equality check for this quarter
if expected != provided:
    _payroll_fail_fast(...)  # existing behaviour
```

About 30 lines added inside the existing loop. No writer changes.

### 5.2 Risk assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Other code paths mutate `quarter_totals.payroll` without setting `_phase_7_2_capped_for_capacity` and now silently pass | Low. The flag is set only at one site (line 198). | The fallback `if expected != provided` still raises for any unflagged divergence. |
| `_phase_7_2_original_payroll` was set with stale row data so the new sanity check (original == row_rollup) raises | Possible if row data is mutated after rationalization. | This IS a separate bug if it happens; the new sanity check surfaces it. Acceptable. |
| Downstream consumers see capped `quarter_totals.payroll` and uncapped per-row totals, computing revenue/cash inconsistently | Already true today. Phase 7.2's intent is that downstream consumers consume `quarter_totals.payroll` (the contract surface), not `rows[].total_quarterly_payroll`. The change here doesn't alter that. | None needed. |
| `_apply_restoration_to_model_input` writes `quarter_totals.payroll` (capped) into `model_input.expenses.Payroll.values` — those values are what FINMO consumes. The rows are vestigial for FINMO purposes anyway | True. The rows are used for the realism/contract validation only. | None needed; this confirms Option D is safe. |

### 5.3 Test plan

**Unit smoke tests** ([tests/test_bug_c_payroll_rollup_fix.py](tests/test_bug_c_payroll_rollup_fix.py)) — new file:

1. Validator passes when `_phase_7_2_capped_for_capacity=True`, `_phase_7_2_original_payroll` matches row-rollup, and `provided ≤ original`.
2. Validator raises `payroll_headcount_quarter_total_mismatch` with detail "_phase_7_2_original_payroll=X does not match calculated_from_title_rows=Y" when cap base disagrees with current rows.
3. Validator raises `payroll_headcount_quarter_total_mismatch` with detail "capped quarter_totals.payroll=X exceeds _phase_7_2_original_payroll=Y" when cap value somehow inflated.
4. Validator STILL raises on plain row-vs-total mismatch (no override flag) — preserves the original universal behaviour.
5. Validator passes through other quarters cleanly when one quarter is flagged (mixed-flag case).

**E2E confirmation:**

Re-run Sunny E2E against the 5051 instance after the fix. Expected: payroll rollup check passes; the run either:
- Reaches 16/16 (Sunny clean) — would mean no other latent bugs left.
- Surfaces the next pre-existing bug (likely debt schedule, since NexGen/Express both hit it). Document the new surfaced bug separately.

If a new bug surfaces, that's the next iteration of the loop. Stop the fix here; do not bundle.

### 5.4 What this fix does NOT do

- Does NOT fix Bug A (debt principal not amortizing).
- Does NOT fix Bug B (Q1 short_term_debt off 5-8%).
- Does NOT fix Bug D (Express deferred revenue applicability/value contradiction).
- Does NOT regenerate any test baselines.
- Does NOT change production-mode behaviour (the validator still skips entirely when `CONVERGENCE_TEST_MODE=false`).

---

## 6. Awaiting user authorization

The proposed fix is one focused change in [`schedule.py:2463-2485`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2463) plus a unit smoke test file. Push as `phase_9_p3_10_bug_c_fix_payroll_rationalization_rollup_skip`.

**Awaiting your direction:** approve Option D as scoped, or pick Option E / F instead.

---

## 7. Addendum (post user follow-up): two pre-fix questions answered + revised recommendation

The user asked two questions before authorizing Option D. Both turn out to invalidate Options D and E and point to a fourth option: **the cap is dead workaround code; remove it.**

### 7.1 Q1 — Is the deferred-headcount-bug still live in the current schedule build path?

**No. It's been fixed at the source.** The rationalization docstring (lines 168-173) explains the cap was a workaround for "the deferred headcount bug" — the schedule used to anchor on `operator_stated_current_payroll / 4` distributed evenly. Today the schedule build path is entirely per-row OEWS-resolved:

- Key people ([`_key_people_rows_from_intake`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L746-L805)): one row per intake person, `annual_wage = person.get("annual_wage")` (intake/OEWS resolved per-person at lines 769-776), `starting_fte=ending_fte=1.0`. No reference to `current_payroll`.
- Supporting staff ([`_resolve_supporting_staff_wages`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1115-L1232)): one row per supporting position, `annual_wage` resolved from the **NAICS OEWS title catalog** for the business's naics_6 (lines 1124-1128, 1182-1198). Hard-fail if the OEWS title isn't in the catalog. No reference to `current_payroll`.

Sunny's persisted Q1 row data confirms this: 3 distinct rows with 3 distinct OEWS-resolved wages (75820, 36550, 36246) and stated FTEs. None of the wages are derived from `current_payroll / 3` or any flat distribution. The wages reflect actual cohort-typical OEWS values for bakery occupations.

The string `"current_payroll"` appears in `schedule.py` at exactly two sites — lines 542 and 3059 — both are intake-snapshot reflections (preserved in metadata), not used as the basis for any per-row wage. Verified by grep.

**Conclusion Q1:** the build-time bug the cap was patching no longer exists.

### 7.2 Q2 — Does FINMO read `quarter_totals.payroll` or re-sum rows?

**FINMO reads `quarter_totals.payroll` (indirectly via `model_input.expenses.Payroll.values`). It does NOT re-sum rows.** Verified by tracing:

1. Schedule writer or restoration cap → `quarter_totals[i].payroll`.
2. [`apply_payroll_headcount_payload_to_model_input`](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2549-L2582) line 2565: `derived_live_values = [float(totals_by_quarter[quarter]) for quarter in range(1, live_count + 1)]` — pulls from `quarter_totals.payroll` and stamps into `model_input.expenses.Payroll.values`. The `rows` field is **not consulted**.
3. [`_apply_restoration_to_model_input`](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L481-L502) does the same: reads `adjusted_payroll_headcount.quarter_totals[i].payroll`, writes to `model_input.expenses.Payroll.values`.
4. [`finmo_model.py:354`](python/financial_model_engine/finmo_model.py#L354): `payroll = quarter.expenses.payroll_amount`.
5. [`model_inputs.py:776`](python/financial_model_engine/model_inputs.py#L776): `quarter.expenses.payroll_amount = value` where `value` comes from the model_input Payroll row's `values` array.

So FINMO consumes the **capped** `quarter_totals.payroll` value. The row-level FTE / wage / per-row totals are vestigial as far as FINMO is concerned.

The `rows` field is read by exactly one consumer in the post-intake critical path: the validator `_validate_quarter_totals_match_title_rows` (the one we're trying to fix). Other consumers are non-critical (Diagnostics sheet narrative, FTE counts in workbook tabs).

**Conclusion Q2:** FINMO is happy with the cap. The cap successfully reduces FINMO payroll. The validator's "rows must match totals" check is the only place the cap divergence matters.

### 7.3 Implications: the cap is dead workaround code

Putting Q1 + Q2 together:

- The cap was a workaround for the deferred-headcount-bug (which made `current_payroll / 4` appear as the schedule baseline regardless of capacity). That bug is fixed.
- Without that bug, the schedule baseline IS already capacity-appropriate-by-construction: row-level FTE × OEWS-cohort wage × stated benefits %. There's nothing to "rationalize down."
- For Sunny: the operator stated 2 key people + 0.5 supporting staff at OEWS-cohort wages. The resulting Q1 payroll = $39,620 = the operator's actual reality. Capping it to $20,777 doesn't reflect any real "you're overstaffed" signal — it's the cap reapplying the OLD bug's logic on data that's already been built correctly.
- The cap fights downstream consumers: it forces FINMO payroll DOWN to a cohort target that doesn't reflect the operator's stated headcount. The realism gate then sees a payroll % of revenue that's artificially low; downstream targets and bands are computed against a phantom payroll level.
- The marker fields (`_phase_7_2_capped_for_capacity`, `_phase_7_2_original_payroll`, `_phase_7_2_target_annual_payroll`, `_phase_7_2_naics_payroll_pct_used`, `_phase_7_2_headcount_rationalization_applied`) are not consumed by any downstream code in `python/`. Verified by grep — the only matches outside `feasibility_restoration.py` are in three docs (this one + two pre-existing diagnostic docs). The cap leaves no narrative trace any consumer reads.
- The cascade ([`restore_feasibility`](python/client_intake_and_finmo/post_intake_solver/feasibility_restoration.py#L423-L550)) treats the rationalization lever as one of four. If it returns 0 savings, levers 2-4 (price lift / utilization lift / capacity expansion) absorb the gap. The cascade still functions; it just stops applying a phantom override.

### 7.4 Revised recommendation: Option G — remove the cap

Per the user's standing rule (*"Remove or convert legacy code, don't just route around it"*), the right fix is to delete `_apply_headcount_rationalization` entirely (or convert it to a no-op stub that always returns 0 savings) AND remove the call site at [`feasibility_restoration.py:471-478`](python/client_intake_and_finmo/post_intake_solver/feasibility_restoration.py#L471).

**Why this beats Options D / E / F:**

| | D (skip check on flag) | E (rebuild rows) | F (remove rationalization, hard-fail) | **G (remove cap entirely)** |
|---|---|---|---|---|
| Fixes Sunny | yes | yes | yes (different way) | **yes** |
| FINMO sees operator-stated payroll | no (capped) | no (capped, FTE rebuilt) | yes | **yes** |
| Realism gate sees operator-stated payroll % of revenue | no | no | yes | **yes** |
| Removes dead workaround | no (preserves dead path with new validator carve-out) | no (replaces with new dead path: scaled phantom FTE) | yes (but adds a new hard-fail surface) | **yes** |
| Cascade still has fallback levers (price / util / capacity) | n/a | n/a | no (removes a lever) | **yes (lever returns 0; cascade continues)** |
| Risk to production runs | low (validator-only) | medium (per-row FTE rewrites ripple) | high (some businesses now hard-fail at structural check) | **low (lever was already vestigial; FINMO already preferred uncapped baseline conceptually)** |

**Concrete change:**

```python
# python/client_intake_and_finmo/post_intake_solver/feasibility_restoration.py

def _apply_headcount_rationalization(*args, **kwargs) -> float:
  """Phase 9 P3.10 Bug C — DEAD WORKAROUND REMOVED.

  This lever was patching the deferred-headcount-bug (schedule built
  payroll from operator_stated_current_payroll / 4). That bug is fixed
  at the source: the current schedule build path resolves per-row
  OEWS wages × stated FTE, so the rollup is already cohort-appropriate
  by construction.

  Removing the cap restores the operator-stated row totals to FINMO,
  the realism gate, and downstream cohort comparisons. The cascade's
  remaining levers (price lift / utilization lift / capacity expansion)
  continue to absorb any structural feasibility gap.

  Kept as a stub returning 0.0 so the existing cascade signature
  (positional payroll_savings) is preserved. Caller updates can fold
  this lever out of the cascade list in a follow-up commit if desired.
  """
  return 0.0
```

Plus delete the helper functions only used by this lever (`_naics_payroll_pct`, `_annual_payroll_from_schedule` if not referenced elsewhere) — to be confirmed by grep before final cut.

**Universal-app discipline:** this change applies to every business identically. No NAICS / archetype branching.

**Risk assessment:**

| Risk | Likelihood | Mitigation |
|---|---|---|
| Some business that *was* relying on the cap to appear feasible now fails the structural check | Possible — any business currently capped goes through the cascade with `payroll_savings = 0` instead of `> 0`. Levers 2-4 try to close the gap; if they can't, the cascade hits its existing terminal-failure path. | The cascade's residual-gap path is already handled (it logs and returns infeasible-with-narrative; the orchestrator continues with the adjusted ops). The new behavior is correct: communicating to the planning consultant that price/utilization/capacity adjustments are needed instead of silently shrinking payroll. |
| FINMO payroll values change for previously-capped runs | Yes for any business where the cap fired. FINMO will see operator-stated payroll instead of the cap. | This IS the correct semantic. The realism gate has its own per-quarter cohort cap on `payroll_percent_of_revenue` — that's the proper place for "your payroll is too high relative to cohort." A failure there has the right diagnostic shape. |
| Realism gate may now flag payroll-percent-of-revenue out-of-band where the cap previously hid it | Yes — this is the surfaced-bug pattern again, exactly what the user's hard-fail architecture is designed to do: stop hiding latent issues. If the realism gate raises, the right next step is a planning-consultant communication, not a silent cap. | None needed; this is the correct behaviour under CONVERGENCE_TEST_MODE=true. |
| Two helper functions (`_naics_payroll_pct`, `_annual_payroll_from_schedule`) become dead code | Verified locally only; need a grep before deletion. | Confirm dead via grep; delete in same commit. |

**Test plan (revised):**

1. Unit smoke test: `_apply_headcount_rationalization(...)` returns 0.0 regardless of inputs (stub behaviour).
2. Unit smoke test: `restore_feasibility` produces a `RestorationResult` whose `applied_adjustments` does NOT include a `headcount_rationalization` entry, and whose `adjusted_payroll_headcount.quarter_totals[i]` are NOT carrying `_phase_7_2_capped_for_capacity` or `_phase_7_2_original_payroll`.
3. Unit smoke test: `restore_feasibility` for a structurally-infeasible business still produces a result (cascade levers 2-4 fire as before).
4. **E2E Sunny re-run:** payroll rollup check passes; surface the next bug or land 16/16.

**Push as:** `phase_9_p3_10_bug_c_remove_dead_payroll_rationalization_workaround`.

### 7.5 Awaiting your direction (revised)

Given Q1 + Q2 evidence, the cap is dead workaround code. Recommend **Option G — remove**.

Options D, E, F all preserve the cap in some form. They each fix the validator failure but leave the dead workaround in place, perpetuating the FINMO/realism distortion the cap creates. None of them serve the architectural intent of P3.10.

If you want to keep the cap for a non-obvious reason (e.g., it's protecting against a class of failure I haven't seen), say so and I'll re-scope. Otherwise, the cleanest path is delete.
