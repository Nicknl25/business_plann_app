# Phase 9 P3.7 — NexGen post-recovery EBITDA decline + WC anomaly diagnosis

**Date:** 2026-05-11
**Subject drafts:** NexGen P3.7 `51ab9a6d257149cda1fdd76a61e3aeef`, Express P3.7 `01fcf425464441238679f2fafe2c4756`
**Both passed 16/16 on the acceptance gate.** This document diagnoses the underlying mechanisms — not a regression report.

---

## Part 1 — NexGen's Q11→Q20 EBITDA decline

### 1.1 The trajectory

| Quarter | Revenue | COGS % | Marketing % | G&A % | Payroll | EBITDA $ | EBITDA % |
|---:|---:|---:|---:|---:|---:|---:|---:|
| Q1 | $1.74M | 27.2 | **17.0** | **17.0** | $272K | $8.7K | **0.5%** |
| Q5 | $1.82M | 26.6 | 16.5 | 16.5 | $280K | $45.6K | 2.5% |
| Q11 | $2.01M | 26.1 | **16.2** | **16.2** | $289K | $100.4K | **5.0%** (peak) |
| Q15 | $2.11M | 27.2 | 17.1 | 17.1 | $298K | $53.7K | 2.5% |
| Q20 | $2.13M | 27.8 | **17.7** | **17.7** | $306K | $10.7K | **0.5%** (back to Q1) |

EBITDA peaks at Q11 then declines 90% by Q20. COGS / Marketing / G&A ratios bottom at Q11 then climb back. Payroll grows ~6% Q1→Q20 (linear), revenue grows ~6%, so the payroll-to-revenue ratio is flat.

### 1.2 Mechanism — the target_ramp shape

Pulling `post_cascade_completion.restoration_loop.per_target_results[ebitda_margin].result`:

```
target_ramp Q1/Q5/Q11/Q15/Q20: 0.005, 0.025, 0.050, 0.0254, 0.005
```

The ramp peaks at Q11=5.0% then declines linearly to Q20=0.5% — **the same value as Q1**. The deterministic solver dutifully drove cost ratios to whatever produced that EBITDA shape. The Marketing / G&A / COGS provenance shows `target_metric: ebitda_margin` for every quarter Q1–Q20, confirming the solver authored the values.

### 1.3 Why the ramp is shaped that way

`_build_target_ramp` for profitability metrics builds a two-phase ramp:
1. **Q1 → Q11 (lift to viability)**: linear from `q1_anchor` to `q11_binding`.
2. **Q11 → Q20 (relax to cohort)**: linear from `q11_binding` to `q20_target`.

The anchor values:

| Field | Formula | NexGen value |
|---|---|---|
| `q1_anchor` | `max(q1_current, _floor_for_quarter(0))` | 0.005 (safety floor) |
| `q11_binding` | `max(q20_target, q5_floor + 0.020 + 0.005)` | 0.050 |
| `q20_target` | `float(band_target)` (clamped to `max(0.0, band_min) + safety`) | **0.005** (cohort target for NAICS 51 EBITDA is −0.005; clamped to 0 + safety = 0.005) |

So `q11_binding=0.050` (forced positive by the recovery-delta doctrine) and `q20_target=0.005` (driven by the NAICS 51 cohort). The Q11 → Q20 segment is a 90% decline by construction.

### 1.4 The NAICS 51 cohort EBITDA target is negative

`post_intake_industry_baseline_for_naics(metric_key="ebitda_margin", naics_6="513210")`:

```
band = [-0.1826, -0.0053, 0.1304]   # min / target / max
```

**The target (median) EBITDA margin for NAICS 51 software publishing is −0.5%.** The cohort is dominated by historical "Information sector" firms that ran at break-even or losses; modern SaaS profitability isn't representative.

The ramp builder takes this −0.5% target, clamps it to the band floor (0.0) + safety (0.005), and feeds it into Q20. Result: Q20 is anchored at 0.5%. The solver writes cost ratios that produce 0.5% Q20 EBITDA.

### 1.5 Comparison — Express's ramp

```
target_ramp Q1/Q5/Q11/Q15/Q20: 0.0050, 0.0250, 0.0500, 0.0471, 0.0435
```

Express's `q20_target = 0.0435`, near Q11's 0.05. The Q11 → Q20 segment is essentially flat (~65 bps decline). Express's NAICS 488510 (Freight Arrangement) cohort:

```
ebitda_margin band = [0.015, 0.0463, 0.0674]
```

Cohort target is +4.63% → q20_target lands at 4.35% (after safety) → ramp is nearly flat post-Q11. Same mechanism, materially different magnitude because the cohort fits.

| Business | NAICS | Cohort EBITDA target | q20_target after clamp | Q11→Q20 decline |
|---|---|---:|---:|---:|
| NexGen | 513210 (software publishing) | **−0.5%** | 0.5% | **−4.5pp** |
| Express | 488510 (freight arrangement) | +4.6% | 4.35% | −0.65pp |

The shape is identical; the slope is set by the cohort.

### 1.6 Why `no_post_recovery_relapse_q11_q20` passed for NexGen

The realism row reports:

```
metric_key: no_post_recovery_relapse_q11_q20
quarter_index: null
actual_value: 0.005
effective_min: 0.0
effective_max: null
status: in_band
band_source: universal_viability_doctrine
```

The formula ([formulas.py:823-836](python/client_intake_and_finmo/post_intake_realism/formulas.py#L823)):

```python
def _formula_trajectory_no_post_recovery_relapse(...) -> Optional[float]:
  """Minimum EBITDA margin across Q11..Q20. Positive = no post-recovery relapse."""
  values: List[float] = []
  for q in range(11, 21):
    v = _quarter_ebitda_margin(finmo_json, q)
    if v is not None:
      values.append(float(v))
  return min(values)
```

**The check is `min(EBITDA margin Q11..Q20) ≥ 0`**, not "Q20 ≥ Q11 − 2pp" as I had documented in the P3.5 design notes. NexGen's `min = 0.005` (Q20) satisfies `≥ 0` → in_band. The 4.5pp decline from Q11 to Q20 fully passes this universal-viability check.

This is a real architectural gap between the doctrine documentation ("no post-recovery relapse") and the implementation (just "non-negative minimum"). The implementation tolerates arbitrarily large declines as long as Q20 stays above zero — which is exactly what the NexGen cohort ramp produces.

### 1.7 The cost-priority tiering allocator's role

The solver isn't doing anything wrong. Per the solver's outer loop, the residual at each quarter is `target_ramp[q] - current_metric[q]`, and drivers are allocated proportional to slack × |sensitivity|. Tier 1 (cost ratios) absorbs first; Tier 2 (structural) only engages when Tier 1 saturates.

For NexGen, Tier 1 had enough slack to land Q11 = 0.05 (band ranges for Marketing/G&A go up to 0.33; for COGS up to 0.47; plenty of room to compress at Q11). It then released those compressions at Q20 to match `target_ramp[19] = 0.005`. The driver-moves table confirms this:

```
expenses::Marketing:                Q1=17.0%  Q5=16.5%  Q11=16.2%  Q15=17.1%  Q20=17.7%
expenses::General & Administrative: Q1=17.0%  Q5=16.5%  Q11=16.2%  Q15=17.1%  Q20=17.7%
expenses::Cost of Goods Sold:       Q1=27.2%  Q5=26.6%  Q11=26.1%  Q15=27.2%  Q20=27.8%
```

Marketing and G&A are identical because they have the same cohort band and similar Tier 1 priority; the allocator distributes evenly.

### 1.8 What this means structurally

The "peak-then-decline" trajectory for NexGen is an emergent property of three load-bearing components interacting correctly:

1. **`_build_target_ramp`** for profitability metrics builds a Q1-low / Q11-high / Q20-cohort shape. The "recover by Q11, then settle at cohort" pattern is doctrinally intended.
2. **The NAICS 51 cohort target is negative**, so the "settle at cohort" leg drops back to break-even.
3. **The `no_post_recovery_relapse_q11_q20` check** measures `min ≥ 0`, which a Q11=5% → Q20=0.5% trajectory satisfies trivially.

The result is a plan that the gate accepts as viable but that an operator reading the workbook would intuitively call "we recover then immediately decay back to break-even." The P3.7 architecture didn't introduce this — it was always there for any business whose cohort target sits well below the q11_binding floor.

### 1.9 What P3.7's bs_only_path didn't and couldn't change

When NexGen triggered `scope=bs_only_path`, GPT's authority covered only the 5 working-capital drivers. **Marketing %, G&A %, COGS %, Payroll, Unit Price, Utilization, Capacity stayed at deterministic-solver values.** The peak-then-decline shape is in those P&L drivers; GPT had no say on this path.

A `scope=pnl_path` fire would have given GPT P&L authority and the chance to author Q20 Marketing/G&A ratios that don't climb back to 17.7%. But NexGen didn't trigger pnl_path because no GPT-authorable P&L metric was forecast to hard-fail (every per-quarter Marketing %, G&A %, COGS % was in band at NAICS 51's wide cohort tolerances).

---

## Part 2 — NexGen's WC anomalies

### 2.1 AR Days: Q1=4.34 vs Q2-Q20=30.80

| Quarter | Value | Source |
|---:|---:|---|
| Stub (Q0) | 0.0 | Tier A intake anchor is in `schedules.accounts_receivable_opening_balance_seed` (dollars), not in this row's stub. |
| Q1 | **4.34** | `balance_sheet_contextual_seed`. Seed_value=4.34, derived from operator's intake (Tier A anchor implied 3.16 days) blended with the cascade target (46.91 days). No solver provenance — Q1 wasn't written by the target solver. |
| Q2 | 30.13 | Target solver, `target_metric=current_assets_minus_cash`. First write — solver moved AR Days toward the cohort band's lower edge (band lower = 30.80). |
| Q3..Q11 | 30.80 | Solver kept AR Days at the band lower edge. |
| Q12..Q20 | 30.80 → 31.94 | Solver gradually raised AR Days toward the cohort target. |

**Why the Q1→Q2 discontinuity?** Because the solver's ramp anchors `ramp[0] = q1_current` (per the Q1/stub alignment audit), and `q1_current` for AR Days came out of the seed at 4.34. The ramp tells the solver Q1 is fine; it starts writing at Q2. Meanwhile the ramp's `q20_target` for `current_assets_minus_cash` (the metric, not a driver) requires *Q2-Q20* AR Days to be in the cohort range to lift current-assets-to-revenue toward the cohort median. Result: Q1 stays near operator-intake (4.34 days), Q2-Q20 jumps to cohort (30.80 days). Discontinuity visible in any quarterly view.

### 2.2 Prepaid Expenses (% of Revenue): Q1=0.01 vs Q5+=0.028

| Quarter | Value | Source |
|---:|---:|---|
| Stub | 0.0 | seed preserves; intake-derived |
| Q1 | **0.010** | `balance_sheet_contextual_seed`. Seed_value=0.01, cascade target=0.0415. |
| Q2..Q5+ | 0.028 → 0.034 | Target solver, `target_metric=current_assets_minus_cash`. Moved Prepaid % up toward cohort band lower edge (0.0278) and beyond. |

Same mechanism as AR Days. Cohort band:
```
prepaid_expenses_percent_of_revenue: [0.028, 0.041, 0.067]
```
The seed's 0.01 is below the cohort lower edge. The solver lifts Q2-Q20 into the band; Q1 stays at the seed because the ramp anchors there.

### 2.3 Inventory Days: 35.92 at Q1, 7.57 at Q11, 55.49 at Q20 — for software

This one has the most going on.

| Quarter | Value | Source |
|---:|---:|---|
| Stub | 0.0 | preserved |
| Q1 | **35.92** | NOT from `balance_sheet_contextual_seed` for this row (seed says `applicable=False, naics2_51_not_in_applicable_set`). When `applicable=False`, the seed PRESERVES whatever was already in the cell. So 35.92 was placed there by an earlier policy/initialization step, likely the cohort-baseline initializer that populates BS rows to cohort targets at model_input construction time. The cohort target for inventory_days at NAICS 513210 is **34.21 days** (cohort band [7.57, 34.21, 83.89]). 35.92 is essentially that target, presumably with rounding/blending. |
| Q2..Q11 | 7.57 | Target solver, `target_metric=current_assets_minus_cash`. Moved Inventory Days DOWN to the cohort lower edge (7.57) to reduce current_assets_minus_cash toward the band ramp. |
| Q12..Q20 | 7.57 → 55.49 | Solver gradually raised Inventory Days back toward the cohort target (and beyond). |

**Why does the cohort have 34 days of inventory for software publishing?** Because `industry_metrics_edgar` / `industry_metrics_alpha` at NAICS L3 (511) include book publishers, periodical publishers, sound recording, etc. — all of which carry physical inventory. The cohort isn't SaaS-pure; it's the full Information sector. Pure software firms have ~0 inventory days; the cohort median is dragged up by the legacy publishing subsegments.

**Why didn't the realism gate flag it?** The realism row for `inventory_days` carries:
```
applicability_rule_key: "inventory_when_business_has_inventory"
notes: "Applicability gate skips for software / professional services NAICS-2"
gate_kind: "skip"
```
So the gate SKIPS inventory_days for NAICS 51. All 20 NexGen realism rows for inventory_days show `status="skipped"`. The metric is invisible to:
- the gate's hard-fail logic (no violation),
- the forecast classifier (no candidate failure to detect → no scope trigger),
- the handler's prompt (GPT never sees "inventory_days is failing").

The applicability skip is correct as a "don't fail the operator on this metric" rule, but it also means the system writes inventory-heavy Inventory Days values to the model_input that nobody downstream re-evaluates.

### 2.4 Inventory Days Q11→Q20 volatility (7.57 → 55.49)

This is the same `current_assets_minus_cash` target solver behavior as Marketing/G&A vs ebitda_margin. The target_ramp for `current_assets_minus_cash` ramps Q1→Q20:

```
target_ramp Q1/Q11/Q20: 0.163  0.371  0.559
```

Cohort target for current_assets_minus_cash at NAICS 51 = **0.559** (i.e. current-assets-minus-cash equals 55.9% of revenue at maturity). To produce that, the solver writes Inventory Days, AR Days, and Prepaid % at high values. Inventory Days does most of the heavy lifting because AR Days and Prepaid % have tighter bounds.

So Inventory Days swings 7.57 → 55.49 not because the model thinks NexGen actually buys inventory, but because Inventory Days is the most-elastic driver of the `current_assets_minus_cash` target, and the cohort target for that metric is 55.9% of revenue. The solver uses Inventory Days as a balance-sheet absorber.

### 2.5 Why GPT didn't fix Inventory Days

NexGen's tool-calling session fired with `scope=bs_only_path`. The handler's user prompt listed only the metrics the forecast classifier had flagged as hard-fail-able:

```
Failing metrics:
- current_liabilities_to_revenue (Q1): actual=0.368, band=[-0.20, 0.35]
- current_liabilities_to_revenue (Q2): actual=0.352, band=[-0.20, 0.35]

Primary_levers:
  - balance_sheet::Accounts Payable Days
  - balance_sheet::Deferred Revenue (% of Revenue)
```

`inventory_days` was NOT in the prompt because the realism gate marks it `skipped` for NAICS 51 → forecast classifier never saw it as failing → it didn't surface to GPT.

The system prompt instructs GPT explicitly:
> "Author only the working capital drivers needed to fix the failing metrics. Leave the others as null in your commit; the existing values will be preserved."

GPT followed the instructions — surgical, by design. He authored AP Days = 20 and Deferred Revenue % = 0.10. He left AR Days, Inventory Days, and Prepaid % as `null` (preserved at solver/seed values). Tool feedback would have shown him the trajectory across all 20 quarters, including Inventory Days swinging 7.57 → 55, but with no realism-side hard-fail attached and no prompt-side instruction to fix it, surgical-mode GPT correctly did nothing.

This is the **trade-off the user designed into P3.7**: surgical scope means drivers that are weird-but-not-failing-realism stay at cohort defaults. It's narrow blast-radius (good for cases like NexGen where over-authoring would touch unrelated levers) but it also means cohort-skipped metrics like `inventory_days` go unchecked when they're misaligned with the actual business.

---

## Part 3 — Cross-cutting architectural findings

### 3.1 The cohort-target Q20 problem

Two of NexGen's structural issues — the EBITDA peak-then-decline and the Inventory Days swing — share a root cause: **the target_ramp's Q20 anchor is `band_target` (the cohort median)**. When the cohort is a poor fit for the actual sub-industry:

- Cohort EBITDA target = −0.5% (NAICS 51 with traditional publishers) → ramp drives Q20 EBITDA back to 0.5%.
- Cohort Inventory Days target = 34 days (NAICS 51 with publishers) → ramp drives Q20 Inventory Days up to 55 days.
- Cohort AR Days target = 47 days → ramp drives Q20 AR Days to ~32 (cohort band lower edge, since current_assets_minus_cash bound-pinned).

For businesses where the cohort fits (Express NAICS 488510, Sunny NAICS 311811), Q20 anchors are sensible. For NexGen (modern SaaS in a cohort dominated by publishers), Q20 anchors look like operator-baseline regression.

### 3.2 The doctrine-implementation mismatch on `no_post_recovery_relapse`

The metric name implies "no relapse" — the trajectory should not decline back toward Q1 levels. The formula implements "minimum positive", which tolerates arbitrarily large declines as long as the floor is positive.

NexGen passes this check with a 4.5pp Q11→Q20 decline. Express passes with 0.65pp. Both are "min ≥ 0" pass; only the trajectory shape distinguishes them. The metric does NOT enforce the doctrine.

### 3.3 The applicability-skip blind spot

`inventory_days.gate_kind = "skip"` and `applicability_rule_key = "inventory_when_business_has_inventory"` means:

- The metric is skipped for service-only NAICS-2 (51, 54, 62, etc.).
- Skipped rows produce `status="skipped"` in the realism memo.
- Skipped rows are invisible to the forecast classifier (it only looks at `out_of_band_hard_fail`).
- Skipped rows are invisible to the handler's prompt.
- The model_input nonetheless carries the cohort-derived values, and they flow into FINMO and the workbook.

So a metric that "should not apply" silently ships with cohort-driven values. For Inventory Days at NexGen this manifests as "35 days of inventory for a software firm" — a workbook value the operator would call wrong, and that nothing in the pipeline pushes back on.

### 3.4 The surgical-scope trade-off (P3.7 design choice)

The user's P3.7 spec is explicit:
> "Author only the working capital drivers needed to fix the failing metrics. Leave the others as null."

This is intentional — narrow blast radius, deterministic mute calculation. The cost is that cohort-misalignment NOT caught by the realism gate stays in the plan.

Options for closing this gap, in increasing scope-creep order:

| Option | Description | Trade-off |
|---|---|---|
| **A** | Tighten `no_post_recovery_relapse_q11_q20` formula to `Q20 ≥ Q11 − 0.02` per its name. Promotes any cohort-driven decline into a hard-fail-able metric → forecast classifier catches it → handler fires. | Single formula change. Risks regressing Sunny / Express runs whose Q20 ramps look like decline. |
| **B** | Tighten `_build_target_ramp` for profitability so `q20_target = max(q11_binding, band_target)`. Q20 never dips below Q11 in the ramp. | Bigger blast radius — every solver run sees a different ramp. Could over-tighten cohort fits. |
| **C** | Expand the BS-only path's prompt to include "anomalies the system noticed but didn't formally fail," letting GPT optionally fix them. | Loosens the surgical-scope discipline; harder mute calculation. |
| **D** | Add a "cohort sub-industry fit" check that downgrades cohort confidence when the actual NAICS-6 doesn't appear in the cohort's underlying firms. Surface the misalignment as a soft signal. | Architectural addition; cross-cuts the cohort resolver. |
| **E** | Tighten `inventory_days` applicability to actually FAIL for NAICS-2 service businesses if Inventory Days is non-zero (rather than skipping it). | Changes the universal applicability rule. |

This document does not recommend a path. The findings stand; the user decides which (if any) are worth closing.

---

## Summary table

| Question | Answer |
|---|---|
| Why does NexGen EBITDA peak at Q11 and decline to Q20? | `target_ramp[20] = cohort EBITDA target` and NAICS 51 cohort target = −0.5% (clamped to 0.5% by safety floor). Two-phase ramp lifts to Q11 then declines to cohort. Solver dutifully writes cost ratios that produce that shape. |
| Why didn't `no_post_recovery_relapse_q11_q20` catch the 4.5pp decline? | Formula returns `min(EBITDA margin Q11..Q20) ≥ 0`. NexGen's min is Q20=0.5% → passes. The check enforces non-negativity, not "no decline." |
| Why is NAICS 51 cohort EBITDA negative? | Cohort `industry_metrics_*` at L3=511 includes book publishers, periodical publishers, sound recording — historical low-margin segments. Not SaaS-specific. |
| How does Express compare? | Same mechanism. Express's `q20_target = 4.35%` (NAICS 488 freight cohort) lands close to Q11=5%. Decline of 65bp vs NexGen's 4.5pp. The architecture is identical; the cohort fit determines the magnitude. |
| Why does NexGen show Q1=4.34 AR Days but Q2-Q20=30.8? | Seed flat-stamps Q1 at the seed_value (a blend of intake 3.16 and cascade 46.91, resolved to 4.34). Target solver starts at Q2 because the ramp anchors `ramp[0] = q1_current = 4.34` → residual at Q1 = 0. Solver writes Q2-Q20 toward cohort. |
| Why does NexGen have 35 days of inventory at Q1 for software? | Cohort-baseline initializer populates BS rows to cohort target before the seed runs. Inventory Days seed says `applicable=False, NAICS-2 51`, which makes the seed PRESERVE existing values. The pre-seed value (cohort target 34.21 days) sticks. |
| Why didn't the realism gate flag 35 days inventory? | `inventory_days.gate_kind = "skip"` with `applicability_rule_key = "inventory_when_business_has_inventory"`. The metric is structurally skipped for software / professional services NAICS-2. All 20 NexGen rows = `status="skipped"`. |
| Why didn't GPT fix Inventory Days? | Forecast classifier ignores `skipped` rows → Inventory Days not in failing_metrics → GPT's prompt doesn't mention it. Surgical-scope instruction tells GPT to author only what's needed for the failing metrics; he correctly left it null. |
| Is this a P3.7 regression? | No. The mechanisms predate P3.7 and would produce the same trajectory in P3.6 if NexGen had fired the handler at all. P3.7 simply makes NexGen fire the handler (where P3.6 didn't), which is the correct improvement. The remaining anomalies are deterministic-solver / cohort-fit / formula-implementation issues. |
