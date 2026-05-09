# Phase 9 — Hard-Fail Realism Gate Audit

**Branch:** intake-stable
**Date:** 2026-05-09
**Scope:** Every hard_fail row in `post_intake_finalize_realism_check_lookup`,
the acceptance gate's realism wiring, and the six Phase D universal
viability trajectory checks.

The proven `effective_tax_rate` skip-bug is the canary. This audit walks
the full surface to find the rest.

---

## TL;DR — bugs the audit identified

1. **Acceptance gate cannot detect realism hard_fails** ([gate.py:228-269](../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L228-L269), [state.py:86-99](../python/client_intake_and_finmo/post_intake_resolution_state/state.py#L86-L99)) — the validator emits status `"out_of_band_hard_fail"` but the consumers check for `"hard_fail"` / `"violation_hard_fail"` / `"fail"`. **Every realism hard_fail is silently passed by the 16-criterion verdict.**
2. **`effective_tax_rate` is Y1-aggregate** ([lookup.py:540](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L540)) — single check on Y1 pretax, with `skip_when_pretax_income_nonpositive` killing the entire 5-year tax check whenever Y1 is loss-making. The proven canary.
3. **`distributions_percent_of_net_income` is Y1-aggregate** ([lookup.py:898](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L898)) — same shape; any Y1 loss + nonzero Y2-Y5 distributions never get checked.
4. **`total_assets_to_revenue` and `owners_capital_percent_of_assets` are Y1-aggregate** ([lookup.py:738, 756](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L738)) — capital-intensity drift through Q5-Q20 invisible.
5. **`capex_percent_of_revenue` is Y1-aggregate** ([lookup.py:878](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L878)) — capex bursts in Y2+ never realism-checked.
6. **`trajectory_gross_margin_supports_recovery` floor is 0.0, not 0.20** ([formulas.py:646-656](../python/client_intake_and_finmo/post_intake_realism/formulas.py#L646-L656)) — passes any business with positive Q11 gross margin, no matter how thin. Doctrine says ≥ 0.20.
7. **`trajectory_fixed_cost_burden_at_industry_floor` floor is 0.0, not 0.35** ([formulas.py:659-680](../python/client_intake_and_finmo/post_intake_realism/formulas.py#L659-L680)) — passes whenever payroll+rent+G&A < 100% of revenue. Doctrine says industry floor ~0.65 of revenue (i.e., the formula should return ≥ 0.35).
8. **`r_and_d_when_applicable` skips on horizon-wide zero** ([validator.py:164-182](../python/client_intake_and_finmo/post_intake_realism/validator.py#L164-L182)) — fine for the disabled-lever case but quietly skips the metric when the model's R&D collapses to zero by mistake.
9. **`skip_when_distributions_zero` skips on horizon-wide zero** ([validator.py:200-219](../python/client_intake_and_finmo/post_intake_realism/validator.py#L200-L219)) — same shape; all-zero distributions across 5 years skips the whole metric, hiding "we forgot to schedule any distributions."

The combined result: a "passing" run can quietly skip up to ~10 of the 32 hard_fail metrics, AND emit hard_fails that the acceptance gate cannot detect at all because of a status-string mismatch. **The 16/16 verdict is paper for the realism dimension.**

---

## A1. Per-metric applicability audit

The 33 active rows in [`_DEFAULT_REALISM_CHECK_ROWS`](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L370-L1062) — 32 hard_fail + 1 skip_if_no_coverage. Each row's applicability rule logic is in [`_applicability_skip`](../python/client_intake_and_finmo/post_intake_realism/validator.py#L115-L221).

Legend:
- ✅ per-quarter, no rule, fires every quarter Q1–Q20.
- ⚠️ per-quarter with applicability gate that can silently skip individual quarters.
- 🔴 year-one-aggregate — only one check ever, regardless of horizon. Hides Y2–Y5 drift.
- 🟡 trajectory_check — Phase D viability rule.

### P&L (per_quarter, ratio metrics)

| # | Metric | Aggregation | Rule | Skip risk | Verdict |
|---|---|---|---|---|---|
| 1 | `cogs_percent_of_revenue` | per_quarter | none | nil | ✅ Keep as-is |
| 2 | `gross_margin_percent` | per_quarter | none | nil | ✅ Keep as-is |
| 3 | `marketing_percent_of_revenue` | per_quarter | none | nil | ✅ Keep as-is |
| 4 | `r_and_d_percent_of_revenue` | per_quarter | `r_and_d_when_applicable` | Whole-horizon zero R&D ⇒ silent skip even when intended applicable | ⚠️ Tighten — emit warn when applicable-by-NAICS but actual R&D is zero |
| 5 | `rent_percent_of_revenue` | per_quarter | none | nil | ✅ Keep as-is |
| 6 | `sga_percent_of_revenue` | per_quarter | none | nil | ✅ Keep as-is |
| 7 | `payroll_percent_of_revenue` | per_quarter | none | nil | ✅ Keep as-is |
| 8 | `depreciation_percent_of_revenue` | per_quarter | none | nil | ✅ Keep as-is |
| 9 | **`effective_tax_rate`** | **year_one_aggregate** | `skip_when_pretax_income_nonpositive` | **Hides Y2–Y5 tax drift entirely; skips wholesale on Y1 loss** | 🔴 **Promote to per-year-aggregate (Y1..Y5) AND make per-year skip conditional on per-year pretax** |
| 10 | `ebitda_margin` | per_quarter | `skip_when_revenue_zero` | Quarter-by-quarter skip is correct (revenue==0 quarters are pre-launch) | ✅ Keep as-is |
| 11 | `operating_margin_percent` | per_quarter | none | nil | ✅ Keep as-is |
| 12 | `net_income_margin` | per_quarter | none | nil | ✅ Keep as-is |

### Balance sheet

| # | Metric | Aggregation | Rule | Skip risk | Verdict |
|---|---|---|---|---|---|
| 13 | `ar_days_dso` | per_quarter | `skip_when_revenue_zero` | Per-quarter; revenue==0 means metric is undefined; correct skip | ✅ Keep as-is |
| 14 | `ap_days_dpo` | per_quarter | `skip_when_operating_expense_zero` | Per-quarter; opex==0 means metric is undefined; correct skip | ✅ Keep as-is |
| 15 | `inventory_days` | per_quarter | `inventory_when_business_has_inventory` | NAICS-2 in {31,32,33,42,44,45,72} only — software/services skip wholesale; intended | ✅ Keep as-is |
| 16 | `prepaid_expenses_percent_of_revenue` | per_quarter | none | nil | ✅ Keep as-is |
| 17 | `deferred_revenue_percent_of_revenue` | per_quarter | `deferred_revenue_when_business_has_recurring` | NAICS-2 in {51,52,53,54,62} only; intended | ✅ Keep as-is |
| 18 | **`total_assets_to_revenue`** | **year_one_aggregate** | none | **Hides Y2–Y5 capital-intensity drift** | 🔴 **Promote to per-year-aggregate (Y1..Y5)** |
| 19 | **`owners_capital_percent_of_assets`** | **year_one_aggregate** | none | **Hides Y2–Y5 capital-structure drift** | 🔴 **Promote to per-year-aggregate (Y1..Y5)** |
| 20 | `current_ratio` | per_quarter | none | nil | ✅ Keep as-is |
| 21 | `quick_ratio` | per_quarter | none | nil | ✅ Keep as-is |
| 22 | `debt_to_equity` | per_quarter | `skip_when_debt_zero` | Per-quarter; intended | ✅ Keep as-is |
| 23 | `debt_to_assets` | per_quarter | `skip_when_debt_zero` | Per-quarter; intended | ✅ Keep as-is |

### Cash flow

| # | Metric | Aggregation | Rule | Skip risk | Verdict |
|---|---|---|---|---|---|
| 24 | `operating_cash_flow_margin` | per_quarter | none | nil | ✅ Keep as-is |
| 25 | **`capex_percent_of_revenue`** | **year_one_aggregate** | none | **Y2–Y5 capex bursts invisible to realism** | 🔴 **Promote to per-year-aggregate (Y1..Y5)** |
| 26 | **`distributions_percent_of_net_income`** | **year_one_aggregate** | `skip_when_distributions_zero` | **Hides Y2–Y5 distribution behavior; whole-horizon zero ⇒ silent skip** | 🔴 **Promote to per-year-aggregate (Y1..Y5); make zero-skip per-year not horizon-wide** |

### Phase D — universal viability trajectory checks

| # | Metric | Formula key | Floor in validator | Doctrine floor (per row notes) | Verdict |
|---|---|---|---|---|---|
| 27 | `ebitda_positive_by_q11` | `trajectory_ebitda_positive_at_quarter` | 0.0 | 0.0 | ✅ Correct — checks Q11 EBITDA margin ≥ 0 |
| 28 | `ebitda_recovery_trend_q5_q11` | `trajectory_ebitda_recovery_trend` | 0.0 | Q11 − Q5 ≥ 0 | ✅ Correct — checks Q11 EBITDA margin ≥ Q5 EBITDA margin |
| 29 | `loss_window_funded_through_q5` | `trajectory_loss_window_funded` | 0.0 | min(Q1..Q5 cash) ≥ 0 | ✅ Correct — minimum ending cash across Q1..Q5 ≥ 0 |
| 30 | `no_post_recovery_relapse_q11_q20` | `trajectory_no_post_recovery_relapse` | 0.0 | min(Q11..Q20 EBITDA margin) ≥ 0 | ✅ Correct — guards against post-recovery relapse |
| 31 | **`gross_margin_supports_ebitda_recovery`** | `trajectory_gross_margin_supports_recovery` | **0.0** | **0.20 per row notes** | 🔴 **Floor mismatch — formula returns Q11 gross margin; validator compares to 0.0; should subtract 0.20 (or wire industry-derived floor)** |
| 32 | **`fixed_cost_burden_reduced_or_scaled_by_q11`** | `trajectory_fixed_cost_burden_at_industry_floor` | **0.0** | **fixed/revenue ≤ 0.65 ⇒ formula return ≥ 0.35** | 🔴 **Floor mismatch — formula returns (revenue − fixed)/revenue; validator compares to 0.0; should compare to 0.35** |

---

## A2. Does the gate actually fire on passing runs?

### Direct DB inspection of the ExpressLogix run

Source of truth: ExpressLogix end-to-end run on 2026-05-07, draft `4fd50ce10bc4421898a5523b45b2fc0e`. Run report: `Test Runs Data/05-07-2026 -- 4fd50ce10bc4421898a5523b45b2fc0e.txt` (13.6 MB).

The persisted `realism_memo_json` column contains:

```json
{
  "contract_version": "realism_memo_storage_v3",
  "last_review_iteration": 1,
  "owner": "controller",
  "state_source": "planning_run_json.controller_resolution_state",
  "storage_mode": "non_canonical",
  "verification_summary": { "executive_summary": "", "overall_assessment": "" }
}
```

**No `results` array. No `realism_gate.line_level.results` path. No band_source rows.** That's what the acceptance gate sees when it calls `_check_realism_no_hard_fail(realism_memo)`.

### The status-string mismatch — a structural bug

The realism validator emits status values from this set:

```
"in_band" | "out_of_band_warn" | "out_of_band_hard_fail" | "skipped" | "no_coverage"
```

(See [validator.py:55](../python/client_intake_and_finmo/post_intake_realism/validator.py#L55), [validator.py:495](../python/client_intake_and_finmo/post_intake_realism/validator.py#L495), [validator.py:829](../python/client_intake_and_finmo/post_intake_realism/validator.py#L829).)

But the consumers downstream check for a **different** status set:

```python
# gate.py:254
if status in ("hard_fail", "violation_hard_fail") or (status == "fail" and gate_kind == "hard_fail"):
    hard_violations.append(...)

# state.py:93
if status in ("hard_fail", "violation_hard_fail") or (status == "fail" and gate_kind == "hard_fail"):
    out.append(metric_key)
```

**`"out_of_band_hard_fail"` is in NEITHER list.** The validator's actual hard_fail status string is invisible to:
- `_check_realism_no_hard_fail` (acceptance gate criterion 5/16)
- `realism_gate_hard_fail_metric_keys` (controller_resolution_state populator)
- `build_controller_resolution_state` (downstream `all_cleared` flag)

So even if the persisted memo carried the `results` array, the acceptance gate would still pass `realism_gate_no_hard_fail_violations` regardless of how many rows are actually `out_of_band_hard_fail`. The realism gate has zero authority over the verdict in current code.

### Counts (best-available estimate)

For ExpressLogix specifically — without DB access we can compute the *upper bound* of skipped metrics from the lookup + validator code. ExpressLogix is NAICS 4889 (transportation logistics support), mature stage, profitable Y1.

For each of the 32 hard_fail rows × 20 quarters = **640 expected per-quarter checks** for an ideal universal sweep. Actual checks for an ExpressLogix-shaped run:

| Class | Count | Rationale |
|---|---|---|
| **Per-quarter rows that fire all 20 quarters** | 18 rows × 20q = **360** | The clean per-quarter ratios + skipped-only-when-revenue/opex/debt-zero rows |
| **Per-quarter rows skipped some quarters** (revenue==0 / opex==0 / debt==0) | ~40 individual quarter skips | Revenue/opex/debt ≠ 0 for ExpressLogix mature; near zero |
| **`r_and_d_when_applicable`** | 0 (NAICS 488 has zero NAICS-band R&D ⇒ horizon-wide skip; whole 20q absent) | The lever-disabled signal collapses 20 checks → 0 |
| **`inventory_when_business_has_inventory`** | 0 (NAICS-2 = 48 ⇒ not in inventory set; whole 20q absent) | Intended skip |
| **`deferred_revenue_when_business_has_recurring`** | 0 (NAICS-2 = 48 ⇒ not in recurring set; whole 20q absent) | Intended skip |
| **Year-one-aggregate rows (5 of them)** | 5 (one check each, Y1 only) | `effective_tax_rate`, `total_assets_to_revenue`, `owners_capital_percent_of_assets`, `capex_percent_of_revenue`, `distributions_percent_of_net_income`. **Y2–Y5 invisible.** |
| **Trajectory checks** | 6 (one each) | Phase D viability — but two (#31, #32) have wrong floors so they never fail |
| **Skipped wholesale via `skip_when_distributions_zero`** | 0 if distributions exist; +1 row × 1 check skipped if not | |

**Estimated effective coverage**: ~371 of 640 possible per-quarter checks (58%). And of the 32 hard_fail rows, **5 rows × 4 silent years = 20 lost yearly checks** beyond Y1; **2 trajectory rows × 1 quarter = 2 always-pass viability checks**; **1 row (`r_and_d_percent_of_revenue`) × 20 quarters = 20 lost** if R&D stays zero by mistake.

The 16/16 verdict for ExpressLogix is paper for these reasons:

1. The realism check criteria (`realism_gate_no_hard_fail_violations`) is structurally incapable of detecting hard_fails (status-string mismatch).
2. Even if the consumer matched the status, the persisted `realism_memo_json` doesn't carry the `results` array — only the `verification_summary` stub. So no rows to even inspect.
3. The 5 year-one-aggregate metrics evaluate Y1 once and call it done; Y2–Y5 invisible.
4. Two of the six universal viability trajectory checks have wrong floors.

---

## A3. Q11 viability trajectory checks per-quarter audit

The six Phase D rows are evaluated by [`evaluate_realism_formula`](../python/client_intake_and_finmo/post_intake_realism/formulas.py#L735-L752) inside the `if aggregation == "trajectory_check"` branch ([validator.py:455-513](../python/client_intake_and_finmo/post_intake_realism/validator.py#L455-L513)). The validator passes `quarter_index=None`; the formulas hardcode the relevant quarter(s) themselves.

### Per-formula correctness

| Row | Formula | Quarter(s) consulted | Threshold encoded | Doctrine threshold | Status |
|---|---|---|---|---|---|
| `ebitda_positive_by_q11` | `_quarter_ebitda_margin(finmo_json, 11)` | Q11 only | ≥ 0.0 | ≥ 0.0 | ✅ Correct |
| `ebitda_recovery_trend_q5_q11` | `Q11_ebitda_margin − Q5_ebitda_margin` | Q5 and Q11 | ≥ 0.0 | ≥ 0.0 (any positive recovery) | ✅ Correct |
| `loss_window_funded_through_q5` | `min(ending_cash[Q1..Q5])` | Q1..Q5 | ≥ 0.0 | ≥ 0.0 | ✅ Correct |
| `no_post_recovery_relapse_q11_q20` | `min(ebitda_margin[Q11..Q20])` | Q11..Q20 | ≥ 0.0 | ≥ 0.0 | ✅ Correct |
| `gross_margin_supports_ebitda_recovery` | `_quarter_gross_margin(finmo_json, 11)` (returns gross margin directly) | Q11 only | **≥ 0.0** in validator | **≥ 0.20 per the row's notes** | 🔴 **Floor mismatch — see Fix #6** |
| `fixed_cost_burden_reduced_or_scaled_by_q11` | `(revenue − payroll − lease_rent − g_and_a) / revenue` at Q11 | Q11 only | **≥ 0.0** (i.e., fixed < 100% of revenue) | **≥ 0.35** (i.e., fixed ≤ 65% of revenue per row's notes) | 🔴 **Floor mismatch — see Fix #7** |

So Q11 *quarter selection* is correct in all six formulas — the bug is in the **threshold** the validator compares against. The validator universally uses `>= 0.0` for trajectory checks, which is right for ratios that should "be ≥ 0" (margins, deltas, mins) but wrong for absolute-level metrics (`gross_margin_supports_…`) and inverted-direction metrics (`fixed_cost_burden_…`).

The cleanest fix is to subtract the doctrine floor inside the formula so the validator's universal `≥ 0.0` test still applies. That way the validator stays threshold-agnostic and the doctrine threshold lives next to the formula.

---

## Fix plan

The fixes split into three buckets:

### Bucket A — fix the gate's status-string mismatch (highest priority)

**Fix #1** — accept `out_of_band_hard_fail` as a hard_fail status in:
- [`gate.py:_check_realism_no_hard_fail`](../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L228) — line 254 status set
- [`state.py:realism_gate_hard_fail_metric_keys`](../python/client_intake_and_finmo/post_intake_resolution_state/state.py#L86) — line 93 status set

Without this, none of the other fixes matter — hard_fails can't reach the verdict.

### Bucket B — promote year-one-aggregate metrics to per-year-aggregate

These rows currently fire once for Y1 only. Promote each to `quarter_aggregation = "per_year_aggregate"` (new aggregation kind) so the validator runs once per fiscal year (Y1..Y5):

**Fix #2** — `effective_tax_rate`: per-year aggregate, with the skip rule re-scoped to skip *only that year* when its pretax income is non-positive (not the whole horizon). Y2–Y5 tax drift becomes visible.

**Fix #3** — `total_assets_to_revenue`: per-year aggregate.

**Fix #4** — `owners_capital_percent_of_assets`: per-year aggregate.

**Fix #5** — `capex_percent_of_revenue`: per-year aggregate.

**Fix #6 (a separate Bucket B item)** — `distributions_percent_of_net_income`: per-year aggregate, with `skip_when_distributions_zero` re-scoped to per-year (not horizon-wide).

This needs:
- a new `per_year_aggregate` value in `_QUARTER_AGGREGATIONS` ([lookup.py:25-30](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L25-L30))
- new "year_index" loop in the validator (Y1..Y5, each spanning 4 quarters)
- updated formula keys (`taxes_div_pretax_income_year_one` → `taxes_div_pretax_income_per_year`, etc.) that take a `year_index` parameter
- updated `_applicability_skip` so `skip_when_pretax_income_nonpositive` and `skip_when_distributions_zero` accept a `year_index` arg

Defer this to a follow-up phase if scope is too large for this session; document the intended shape and bring it back.

### Bucket C — fix trajectory floors

**Fix #7** — `_formula_trajectory_gross_margin_supports_recovery`: change `return _quarter_gross_margin(finmo_json, 11)` → `return _quarter_gross_margin(finmo_json, 11) - 0.20` so the validator's `>= 0.0` test now means "Q11 GM ≥ 20%". (Phase E will replace 0.20 with NAICS-keyed value, per the row's notes.)

**Fix #8** — `_formula_trajectory_fixed_cost_burden_at_industry_floor`: the formula already returns `(revenue − fixed) / revenue`. To enforce fixed ≤ 65% of revenue, subtract the inverted floor so `(revenue − fixed) / revenue >= 0.35` becomes `((revenue − fixed) / revenue) - 0.35 >= 0`. Change the final return to subtract `0.35`.

### Bucket D — tighten the silent-skip applicability rules

**Fix #9** — `r_and_d_when_applicable`: emit a visible warn (not silent skip) when the lever-disabled signal collapses but NAICS coverage exists for the metric. Rationale: a software business that loses its R&D line during pipeline construction shouldn't pass realism without trace. Implementation: when applicability rule decides "skip", check whether the NAICS row has R&D coverage; if yes, emit `status="out_of_band_warn"` with reason `"applicability_disabled_but_naics_has_coverage"` instead of `status="skipped"`.

**Fix #10** — `skip_when_distributions_zero`: same shape as #9. Emit warn when distributions are zero AND net income > 0 across the horizon (legitimate businesses distribute *something* by Y5 of profitability). Alternatively, simply tighten to per-year and let the year-by-year check handle it (covered by Fix #6).

---

## Implementation sequencing

This session lands Fix #1 (status-string mismatch), Fix #7 and Fix #8 (trajectory floors). These are surgical, ~3 lines each. Bucket B (per-year-aggregate) is a 50-100 line change touching the lookup, validator, and formulas — separate commit on the same branch.

The audit doc lands first (this commit); then Fix #1 and the trajectory fixes; then Bucket B; then Bucket D. Push at each phase boundary per branch convention.
