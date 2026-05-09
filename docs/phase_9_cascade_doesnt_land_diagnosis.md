# Phase 9 — Cascade Doesn't Land Q11 EBITDA Viable

**Run inspected:** ExpressLogix `d36bbb09d37e433697d7dc0ad29aa30f` /
planning_run `b0f5595cb7604c0a805db7dba0a54e9c` (2026-05-09 17:49 EDT,
post commits aa39e89 + aeb2af6).
**Read source:** `intake_consult_drafts.planning_run_json` for the run.
**Doctrine reference (binding):** "Restoration cascade always lands viable
plan, modifies business model (payroll, capacity, price, utilization)
until Q11 EBITDA positive. NO infeasible outcome."

The cascade does NOT land viable. This doc is the trace of WHY.

---

## 1. What the iteration log actually says

`post_cascade_completion.realism_remediation` (verbatim from the blob):

| Iteration | Violations in | Levers adjusted | Hard-fails after |
|---|---|---|---|
| 1 | 119 | 207 | 119 |
| 2 | 119 | 207 | 119 |
| 3 | 119 | 207 | 119 |
| 4 | 119 | 207 | 119 |
| 5 | 119 | 207 | 119 |

**Five iterations of the gap-B cascade, all logged "iteration_completed,"
zero net change in the hard-fail count.** The cascade burns its full
budget making no measurable progress and quietly hands off to
`restoration_landed`. No "no_progress" detection exists in
[orchestrator.py:712-724](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L712-L724);
the loop exits only on `new_hard_fail_count == 0`, so a stall is
indistinguishable from steady work in the diagnostic.

---

## 2. Why the cascade made no progress — the lever_id namespacing bug

The realism lookup row for `ebitda_margin` (and every other margin/
trajectory metric) carries `primary_levers`:

```
['expenses::Cost of Goods Sold', 'expenses::Marketing',
 'expenses::General & Administrative', 'expenses::Payroll',
 'revenue::Unit Price', 'revenue::Utilization']
```

The model_input rows that those revenue strings are supposed to address
have lever_ids:

```
revenue::Primary line of business::shipment::Capacity
revenue::Primary line of business::shipment::Unit Price
revenue::Primary line of business::shipment::Utilization
```

The cascade looks up the row by exact string match in
`rows_by_lever_id` ([orchestrator.py:369-378](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L369-L378)):

```python
for _row in _rows:
    _lev = str(_row.get("lever_id") or "").strip()
    if _lev:
        rows_by_lever_id[_lev] = _row
...
row = rows_by_lever_id.get(lever_id_clean)
if not row:
    continue   # <-- silent skip
```

`rows_by_lever_id["revenue::Unit Price"]` returns `None` because the
actual key is `"revenue::Primary line of business::shipment::Unit Price"`.
**Every revenue lever lookup misses; the cascade silently skips them.**
Only cost-side levers (`expenses::Cost of Goods Sold` etc.) match —
those have stable, business-agnostic lever_ids.

Concrete proof in the persisted model_input:
- Unit Price Q1=15, Q5=15.14, Q11=15.74, Q20=16.07 — about 7 % lift end-to-end.
- Cascade nominally lifts Unit Price 1.15× per route per iteration.
  21+ revenue-touching routes per iteration × 5 iterations would be
  `1.15^105 ≈ 10^7×` if the lift compounded. It didn't fire at all;
  the ~7 % shift came from one upstream path-stamp pass.

Cost-side levers (which DO match) get pinned at industry_target by
`apply_path_stamp_pass` ([path_engine.py:739-743](python/client_intake_and_finmo/post_intake_adaptive_planning/path_engine.py#L739-L743)),
so the cascade's per-iteration cost-lever lift is also no-op. **Net
effect: the cascade has zero authority over any lever that could move
Q11 EBITDA, every iteration.**

---

## 3. What restoration actually did

`post_cascade_completion.realism_remediation.restoration_landed`
(verbatim):

```
engaged: True
feasible_after_adjustment: False
synthetic_gap_input: $131,879,750
applied_adjustments:
  1. headcount_rationalization
     payroll_pct_target: 0.000677
     payroll_annual_before: $6,238,600
     payroll_annual_after: $0
     rationale: NAICS 488999 payroll target = 0.067% of capacity-driven
                revenue $0 → cap payroll at $0/yr.
  2. utilization_within_band
     0.80 → 0.95, annual_revenue_lift $29,250,000
diagnostic_narrative: "Restoration cascade exhausted at gap=$96,391,150/yr
  ... residual gap remains and the final report should flag the operator
  to review intake assumptions."
final_hard_fail_count: 119
payroll_quarters_overwritten: 20
```

Three doctrine violations in this one block:

**3a. "Restoration always lands" is silently skipped.** Restoration
exits with `feasible_after_adjustment: False`. The orchestrator
([orchestrator.py:980-983](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L980-L983))
just records the False outcome and ships the plan as-is. There is no
re-cascade, no terminal-fallback enforcement, no "this run cannot
ship." The plan-confidence stays `high_no_adaptation` and the run
proceeds to acceptance.

**3b. Levers 2 (price) and 4 (capacity expansion) silently no-op.**
Restoration's lever ladder is `headcount → price → utilization →
capacity_expansion`. Lever 2 was called and returned 0; lever 4 was
called and returned 0. Why:

`_apply_price_lift` ([feasibility_restoration.py:269-277](python/client_intake_and_finmo/post_intake_solver/feasibility_restoration.py#L269-L277))
computes `required_revenue = current_capacity_revenue + gap × 1.05`,
then `required_price = required_revenue / (capacity × periods × util)`,
then `if new_price <= current_price: return 0.0`. The synth call
passes `current_capacity_revenue = 0.0` and `gap = $131.88M`. With
`periods=52, capacity=250000, util=0.80`, required_price comes to
`$131.88M / (250000 × 52 × 0.80) = $12.69/unit` — less than the current
$15. Lever bows out: "you don't need a higher price."

`_apply_capacity_expansion` ([feasibility_restoration.py:373-377](python/client_intake_and_finmo/post_intake_solver/feasibility_restoration.py#L373-L377))
does the same math after lever 3's $29.25M lift:
`required_revenue = $29.25M + $96.39M × 1.05 = $130.46M`,
`required_capacity = $130.46M / ($15 × 52 × 0.95) = 176,058 units/period`
— less than the current 250,000. Lever 4 bows out the same way.

The "always lands" lever 4 has a hidden ceiling (`if required_capacity
<= current_capacity: return 0.0`) that breaks the unbounded guarantee.

**3c. Synthetic gap is a non-physical number passed as an annual
dollar feasibility gap.** [orchestrator.py:770-813](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L770-L813)
sums per-quarter ratio shortfalls (`(floor − actual) × quarter_revenue`)
across 119 hard_fails on 9 different metrics across 20 quarters. The
result, $131.88M, is in mixed units — it's the cumulative "ratio gap
times Q-revenue" across quarters and metrics. Restoration treats it
as `feasibility_gap_annual_dollars` and computes lever sizing against
it. The math is meaningless against any one true gap.

Pre-fix in the orchestrator (the dead `current_capacity_revenue=0.0`
and `lower_bound_annual_fixed_cost=0.0` synth values) is the same
class of error: the synth wraps the gap but throws away the baseline
restoration's math depends on.

---

## 4. Family / lever metadata IS correct

`post_intake_finalize_realism_check_lookup` rows for the failing
metrics (read live):

| Metric | Family | Primary levers |
|---|---|---|
| `ebitda_margin` | turnaround_recovery_q5_q11 | COGS, Marketing, G&A, Payroll, **Unit Price**, **Utilization** |
| `ebitda_positive_by_q11` | turnaround_recovery_q5_q11 | (same) |
| `ebitda_recovery_trend_q5_q11` | turnaround_recovery_q5_q11 | COGS, Marketing, G&A, Unit Price, Utilization |
| `net_income_margin` | turnaround_recovery_q5_q11 | COGS, Marketing, G&A, Unit Price |
| `operating_margin_percent` | turnaround_recovery_q5_q11 | (same) |
| `no_post_recovery_relapse_q11_q20` | industry_normalization | COGS, Marketing, G&A |

Revenue levers ARE in scope per the lookup — the cascade simply can't
reach them because of the lever_id namespacing bug above. Capacity is
NOT in any margin family's primary_levers (only `total_assets_to_revenue`
mentions it). Capacity expansion lives entirely in `feasibility_restoration`'s
lever 4 — which itself silently no-ops per §3b.

---

## 5. Stage shift — not triggered

`adaptive_policy.stage_profile = "operational"`, `planning_mode =
"rebalance"`, `explicit_distress_context = False`.

The realism gate emits `ebitda_positive_by_q11` failure (Q11 EBITDA
margin = -17.5%). Doctrine says stages should shift when floors bind.
There is no stage-shift hook between the realism gate and the cascade
or restoration — the stage_profile is set once, very early in the run,
from the intake's stated business stage and is never reconsidered when
the cascade fails to land. Whether a stage shift would help here is
secondary; the absence of any reconsideration loop is itself a doctrine
gap.

---

## 6. Why the prior fixes worked but didn't reach Q11

- Bug 1 (trajectory_check → hard_fail_violations, commit aeb2af6):
  ✅ working. `ebitda_positive_by_q11` and
  `no_post_recovery_relapse_q11_q20` now appear in the 119 hard_fails.
- Bug 2 (per-lever direction, commit aeb2af6): ✅ working at the
  classifier level (verified in unit smoke). Doesn't matter at the
  cascade level because all the revenue lever lookups still miss.
- Cash-pass-owned skip (commit a406eb8): ✅ no change to this finding.

The cascade is now **routing the right metrics with the right
direction** — but the lever lookup blocks it from doing anything to the
levers that would actually move Q11 EBITDA. That's the reason the
cascade reports "iteration_completed" five times with zero progress.

---

## Fix list

**Fix A (root cause). Resolve revenue lever_ids by driver, not by exact
string match.** When the cascade can't find a row for `revenue::<X>`,
fall through to a driver-based scan of the revenue section
(`driver == "Unit Price"`, `"Utilization"`, `"Capacity"`). This is
exactly what `feasibility_restoration`'s apply block already does
([orchestrator.py:874-886](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L874-L886));
the cascade just needs the same resolver. Same fix needed for
balance_sheet days levers if any business namespaces those (audit
separately).

**Fix B. Detect no-progress stalls.** If `hard_fails_after >=
hard_fails_before` for two consecutive iterations, exit the loop early
with an `iteration_status: "stalled"` marker and pass straight to
restoration. Burning the full budget on no-op iterations wastes time
and hides the real problem in diagnostics.

**Fix C. Pass real baselines to restoration.** When building the synth
`StructuralFeasibilityResult` for restoration's corrective entry, set
`upper_bound_annual_revenue` to the actual annual run-rate from the
current FINMO output (sum Q1..Q4 revenue, or annualize the most recent
4-quarter slice), and `lower_bound_annual_fixed_cost` to the same
slice's fixed-cost total. Restoration's price/capacity math is then
computed against the real model state, not zero.

**Fix D. Lever 4 must close any residual gap, no early-exit.** Remove
the `if required_capacity <= current_capacity: return 0.0` guard in
`_apply_capacity_expansion`. The unbounded guarantee can never short-
circuit on the basis of "you don't need it" — if the metric-level gap
is still open, capacity must rise to whatever closes it, even if the
lever-math arithmetic happens to look satisfied. (After Fix C the math
will rarely produce a degenerate "you don't need it" result anyway,
but the guard is structurally wrong even with a clean baseline.)

**Fix E (next PR after we see Fix A-D land).** Synthetic gap should
be computed from a single canonical signal — the Q11 EBITDA shortfall
in dollars — not the sum of mixed-unit per-metric ratio shortfalls.
The single signal restoration needs is "how much annual EBITDA do I
need to lift, and from what baseline." Today's signal is overstated
and metric-coupled.

**Fix F (out of scope, log only).** The NAICS-488 payroll baseline of
0.067 % of revenue (target 0.000677) drives lever 1 to cap payroll at
$0/yr. That's a cohort-data plausibility issue (real freight is 15-30 %
payroll); the system honors the band literally even when honoring it
zeros out the workforce. Cohort audit needed in a separate PR.

**Fix G (out of scope, log only).** No stage-shift loop exists between
the cascade and restoration. When EBITDA universal floor binds and
the cascade can't move Q11 into the band, doctrine implies a stage
shift (`operational` → `early` opens looser EBITDA tolerances) — but
no module reconsiders `stage_profile` mid-run. Separate decision.

---

## What I'm doing in this PR

Fixes A, B, C, D — all in code, with commit + push + E2E re-run.
F and G are flagged-only.
