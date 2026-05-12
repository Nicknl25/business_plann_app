# Phase 9 P3.10 — E2E Surfaced Bugs

**Source E2E:** [phase_9_p3_10_e2e_results_commits_1_through_4.md](phase_9_p3_10_e2e_results_commits_1_through_4.md). All three businesses (NexGen, Sunny, Express) hard-failed at the existing finalize fail-fast layer once Commit 2's `failed_downgraded_to_warning` wrapper was removed. The bugs documented here all predate Commits 1-4; the architectural overhaul stopped hiding them, it didn't introduce them.

**User directive:** DO NOT FIX in this session. Fix in subsequent focused commits, each its own commit, after user reviews this document.

---

## Bug A — Debt schedule principal not amortizing without new borrowing

**Severity:** Affects 2 of 3 test businesses (NexGen, Express). Likely affects every business with a long-term debt instrument.
**Surfaced by:** `assert_debt_schedule_payload_ready` (existing fail-fast).
**Diagnostic flag:** `principal_balance_not_declining_without_new_borrowing`.
**Failure footprint:** Q1-Q20 — every quarter shows opening == closing == initial principal, and the writer records no new borrowing entry to explain the static balance.

### Observed
| Business | Opening principal | Closing principal | Quarters affected |
|---|---|---|---|
| NexGen | $300,000 | $300,000 | Q1-Q20 (all 20) |
| Express | $500,000 | $500,000 | Q1-Q20 (all 20) |

### Hypothesis
The cash strategy or debt schedule builder is producing an interest-only payment plan (or no payment plan at all) for the LTD instrument, then handing the schedule to FINMO without any amortization. The fail-fast assert correctly catches "principal didn't change AND no new borrowing recorded" because that combination is structurally impossible for a real debt instrument.

### Likely culprit modules
- [post_intake_debt_schedule/schedule.py](../python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py) — the schedule writer.
- [post_intake_cash/runner.py](../python/client_intake_and_finmo/post_intake_cash/runner.py) — `_apply_cash_pass_minimum_debt_schedule` re-applies a minimum amortization plan; if it's a no-op for these inputs, the principal stays flat.

### What a fix looks like
Walk the LTD computation: given starting principal, term length, interest rate, what's the per-quarter amortization payment? Verify the writer applies that amortization or records explicit `new_borrowing` events to keep the assert satisfied.

---

## Bug B — Q1 short_term_debt formula off by ~5-8%

**Severity:** Affects 2 of 3 test businesses (NexGen, Express). Same businesses that have Bug A.
**Surfaced by:** `balance_sheet_driver_formula_failed` on `balance_sheet::Short Term Debt (% of LTD)` at quarter 1.
**Diagnostic flag:** `balance_sheet_driver_formula_failed`.

### Observed
| Business | Q1 actual short_term_debt | Q1 expected | Ratio |
|---|---|---|---|
| NexGen | $59,850 | $63,000 | 0.95 (5% short) |
| Express | $156,825 | $170,000 | 0.9225 (7.75% short) |

### Hypothesis
The "% of LTD" stamp is applying a slightly-less-than-1.0 multiplier somewhere — possibly an explicit 0.95 / 0.9225 default, possibly a rounding artifact from the seed policy, possibly a clamp against the buffer. Both businesses have a similar but not identical fraction, suggesting the multiplier is per-business derived rather than a literal constant.

The expected values are clean (NexGen $63,000 = 21% of $300K; Express $170,000 = 34% of $500K) — they look like intake-stated `short_term_debt_percent_of_long_term_debt` parameters (21%, 34% respectively). The actuals are 95% and 92.25% of those.

### Likely culprit modules
- [post_intake_balance_sheet/contextual_seed.py](../python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py) — seed-policy that may be adjusting the LTD ratio.
- The mapping formula registry — the formula that computes `short_term_debt = LTD × ratio` may be applying an extra multiplier.

### What a fix looks like
Trace where the Q1 short_term_debt value gets stamped. Find the multiplier that produces 0.95 / 0.9225 and either remove it or document why it differs from the user-stated ratio.

---

## Bug C — Sunny payroll quarter_total mismatches row-level rollup

**Severity:** Affects Sunny only — but blocks every Sunny run. Same bug class as Sunny's original FAILED_PRECONDITION (which was the trigger for this whole P3.10 overhaul).
**Surfaced by:** `payroll_headcount_quarter_total_mismatch` (existing fail-fast).
**Diagnostic flag:** `payroll_headcount_quarter_total_mismatch@payroll_headcount_quarter_total_rollup`.

### Observed
| Quarter | quarter_totals.payroll | Σ(title_rows.payroll) | Ratio |
|---|---|---|---|
| Q1 | $20,777 | $39,873 | 0.521 |

The `quarter_totals.payroll` field is roughly half the actual sum of the `title_rows`. The assert correctly catches this — `quarter_totals` are supposed to be a deterministic rollup of `title_rows`.

### Hypothesis
Three plausible causes:
1. The writer is summing only some title rows (e.g., only "support" titles, or only post-Q1 titles) into `quarter_totals.payroll`.
2. Half the title rows have been emitted with mismatched `quarter_index` so they don't roll into Q1's bucket.
3. There's a stale cache or a divide-by-2 in the rollup helper.

The 52% ratio is suspicious — close to 50% but not exact, which rules out a clean divide-by-2 and suggests subset-summing is the most likely cause.

### Likely culprit modules
- [post_intake_headcount/schedule.py](../python/client_intake_and_finmo/post_intake_headcount/schedule.py) — the payroll headcount writer that produces both `title_rows` and `quarter_totals`.

### What a fix looks like
Open the writer's quarter-totals computation and verify it iterates over EVERY `title_row` for that quarter index. Add a unit assertion in the writer that `quarter_totals.payroll == Σ(title_rows.payroll)` so the contract violation surfaces at write-time instead of at finalize-time.

---

## Bug D — Express deferred revenue applicability vs value contradiction

**Severity:** Affects Express only.
**Surfaced by:** `balance_sheet_driver_zero_but_applicable` (existing fail-fast).
**Diagnostic flag:** `balance_sheet_driver_zero_but_applicable`.

### Observed
```
balance_sheet::Deferred Revenue (% of Revenue)
  applicability = deferred_revenue_business
  zero_allowed_reason = no_upfront_or_deferred_revenue_model
  value = 0
```

The driver is marked `applicability=deferred_revenue_business` (i.e., this business has a deferred-revenue model), but the value is 0 and the policy stamps `zero_allowed_reason=no_upfront_or_deferred_revenue_model`. These two assertions are logically contradictory.

### Hypothesis
The applicability flag is being set by one consultant (operating-model or revenue model classifier) while the value/reason is being set by another (the seed policy). They're not reconciling: one says "deferred revenue applies", the other says "this business doesn't have a deferred-revenue model so zero is allowed".

### Likely culprit modules
- [post_intake_balance_sheet/contextual_seed.py](../python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py) — seed policy that picks the value AND the zero_allowed_reason.
- The applicability decision module (search for `applicability=deferred_revenue_business`).

### What a fix looks like
Pick one source of truth for "does this business model use deferred revenue?" and propagate that decision to BOTH the applicability flag and the seed value. If applicability says yes, the value must be > 0; if applicability says no, the value must be 0 with `zero_allowed_reason=not_applicable`.

---

## Bug E (meta) — All three test draft baselines were captured before the corresponding fail-fasts were tightened

This isn't a code bug; it's a test-data observation. The persisted intake states for these three businesses were created during a window when the orchestrator's `failed_downgraded_to_warning` was active, so the upstream consultants and writers learned to produce outputs that the finalize gate would have caught — except finalize was being downgraded. The downgrade let these contract violations accumulate as "tolerated."

Now that the downgrade is gone, every persisted intake state from that window is likely to surface at least one of Bugs A-D. The right path:
1. **Fix the bugs** (A, B, C, D) one at a time, each with its own commit.
2. **Re-run the same E2E** after each fix to confirm the relevant failure category is resolved.
3. **Eventually re-create the test baselines** (intake-complete drafts) under the tightened pipeline so future E2Es start clean.

---

## Suggested fix sequencing (for user review)

The user authorizes any subset of these in any order:

1. **Bug C (Sunny payroll rollup)** — single business, single writer, smallest blast radius. Good first fix.
2. **Bug A (debt principal flat)** — affects 2 businesses but the fix is in one place (debt schedule writer or cash strategy minimum-plan applier).
3. **Bug B (STD formula off by 5-8%)** — needs a trace of where the multiplier comes from. Low-risk surgical fix once located.
4. **Bug D (Express applicability vs value)** — needs cross-module reconciliation; potentially the most architectural of the four.
5. **Bug E (test baselines)** — only after A-D are fixed, regenerate intake-complete drafts.

Each fix gets:
- Its own commit, named `phase_9_p3_10_fix_bug_<X>_<short_description>`.
- A targeted unit test that would have caught the bug.
- An E2E re-run on the affected business(es) to confirm the fix.
- The next fix only after the previous is pushed and verified.
