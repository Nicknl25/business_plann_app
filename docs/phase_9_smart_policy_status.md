# Phase 9 — Smart Funding Source Policy Status

**Branch:** intake-stable
**Date:** 2026-05-09

This session fixed the cash death-spiral by wiring the smart funding
source policy from f949316 into the Phase F cash strategy. ExpressLogix
now lands 16/16. Sunny + NexGen at 13/16 with one remaining wiring
issue documented below.

## What landed (10 commits)

| SHA | What |
|---|---|
| `f73b0ca` | Step 1: StructuralFeasibilityResult kwarg fix |
| `ce8b097` | Step 2: 4 wiring items (router-keyed gap, industry_profile, payroll, soft Q1 fractions) |
| `a841996` | Step 2 finishers: payroll_headcount threading + gate cascade-exercised bug fix |
| `5f02a32` | Step 3a audit doc |
| `20c6bc3` | Status report |
| `77e4889` | **Smart funding source policy wired** — replaces static `_MODE_FUNDING_LEVER_PRIORITY` |
| `47e06f0` | Stock semantics for owners_capital + other_equity (cumulative not flat) |
| `25dd1b8` | Stock-lever carry-forward fill (Q11+ inherits last cumulative) |
| `b67e8ae` | Worst-cumulative-shortfall sizing |

## Verdicts

| Draft | Result | Δ this session | Δ Phase 9 baseline |
|---|---|---|---|
| ExpressLogix Shipping Services | **16/16 ✓** | +2 | +6 |
| NexGen Software Solutions Inc. | 13/16 | +1 | +3 |
| Sunny Glaze Donuts | 13/16 | +2 | +2 |

## ExpressLogix 16/16 — proof that the architecture works

The smart funding source policy correctly evaluates ExpressLogix's
operating model post-restoration:
- chronic_liquidity_gap: False (gap_count < 5 — operating model viable)
- debt_interest_drag_material: True (rate ≥ 3%)
- external_equity_justified: False (no chronic gap, no excessive leverage)
- excluded: other_equity (preserved for outside-investor situations)
- effective_funding_priority: [debt_issuance, owners_capital]
- Total funding: $0 (operating model already healthy)
- All 16 gate criteria pass

## Sunny + NexGen — remaining wiring issue

Both at 13/16. Common 3 failures:
- `net_income_trajectory_viable` — Q11 NI margin negative, Q5→Q11 delta close to but below 0.02
- `viability_timeline_landed` — `ebitda_positive_by_q11` failing
- (Sunny) `cash_health_operational_not_debt_funded` — interest/revenue 6.8%
- (NexGen) `current_assets_positive_q1_q10` — cash dipping despite OC ramping

## The root cause for Sunny + NexGen — multi-writer coherence

Restoration cascade fires correctly:
- Sunny Lever 4: capacity 1200 → 1604 units/period (1.34x)
- NexGen Lever 4: capacity 50 → 69 units/period (1.38x)
- All 4 levers fire and close their assigned gaps

But the model_input revenue rows post-pipeline show non-coherent
values:

```
Sunny revenue rows (final model_input):
  capacity     Q1=1604.34  Q5=37750.0  Q11=37750.0  Q20=37750.0
  unit price   Q1=4.0      Q5=3.74     Q11=3.89     Q20=3.97
  utilization  Q1=0.95     Q5=0.85     Q11=0.85     Q20=0.85
```

Capacity Q1=1604 (restoration's adjusted_ops write) but Q5+ shows
37,750 — a value not from restoration's adjustments. Multiple writers
in the post-cascade pipeline are stomping each other:

1. Path stamp pass (Gap A) — writes per-driver ramped trajectory
2. Restoration's adjusted_ops application — writes flat-restored value
3. Gap B remediation iterations — re-runs path stamp + restoration
4. Final composite revenue check + cash strategy

The order/precedence of writes isn't coherent. For ExpressLogix the
operating model is healthy enough that any of these writes produce a
viable plan. For Sunny + NexGen the multi-write incoherence leaves
mature capacity at the wrong level.

## Fix scope (next session, single commit)

Option A: Make restoration's `adjusted_ops` write the FINAL word
on revenue drivers — write to all 20 quarters, set a "restoration-
applied" flag, and have subsequent path stamp / Gap B passes skip
revenue drivers that already have the flag.

Option B: Have restoration's lever 4 (capacity expansion) write the
mature anchor and rely on the path engine's stage_q1_anchor_fraction
to produce Q1, then NOT call path stamp again afterward. Single-pass
write per row.

Option C: Move restoration to AFTER path stamp pass + Gap B
remediation, so it's the LAST writer. The current sequence has
restoration in the middle of remediation iterations.

Each option is ~10-30 lines. The smart policy + cumulative OC + worst-
shortfall sizing are now correct and validated by ExpressLogix; this
final coherence fix unblocks Sunny + NexGen.

## Step 3 cleanup deferred

Convergence directory deletion + legacy_compat shim audit remain as
documented in [docs/phase_9_step_3a_audit.md](phase_9_step_3a_audit.md).
Not a verdict-mover; should land after 16/16 across all 3 drafts.
