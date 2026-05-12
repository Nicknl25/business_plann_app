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
