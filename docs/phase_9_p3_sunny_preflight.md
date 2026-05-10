# Phase 9 P3 — Sunny Glaze Donuts pre-flight

**Pre-flight date:** 2026-05-10
**Source draft (most recent completed):** `30e442be6809498984a307a268d78c54`
**NAICS-6:** `311811` (Retail Bakeries / Donut Shops)
**NAICS hierarchy:** 311811 → 31181 → 3118 → 311 → 31

---

## 1. Cohort coverage

The two cohort tables hold ZERO firms at NAICS-6/5/4 for donut shops; both
descend to L3 (NAICS 311 — Food Manufacturing, broad).

| Table | L6 (311811) | L5 (31181) | L4 (3118) | L3 (311) | L2 (31) |
|---|---:|---:|---:|---:|---:|
| `industry_metrics_alpha` | 0 | 0 | 0 | **49** | 101 |
| `industry_metrics_edgar` | 0 | 0 | 0 | **55** | 132 |

**Alternating walk path:** L6 → L5 → L4 → L3 (EDGAR first at each level).
First hit at **L3 = 311 (EDGAR, 55 firms)** → confidence_tier capped at `low`
for the alternating-walk's L3 returns, but the 55-firm sample is large
enough that the walk itself reports `confidence_tier=high` (cohort confidence
rule = ≥50 firms = high). Trust flag: `naics_3_fallback`.

This is **3 NAICS levels removed from Sunny's actual sub-industry** —
"donut shop" is being benchmarked against "all food manufacturing." That's
the best the cohort offers; broader-than-Sunny businesses (sugar/sweet
makers, soft drink bottlers, bakery chains, tortilla makers) are mixed
into the band.

---

## 2. Band resolution for the 4 solver targets at NAICS 311811

### Target 1 — gross_margin_percent

| Field | Value |
|---|---|
| Source | `cohort_alternating_edgar` |
| Level used | L3 (311) |
| Sample size | 266 firm-quarter rows |
| Confidence | high |
| Band (min, target, max) | **(0.200, 0.273, 0.364)** |

### Target 2 — ebitda_margin

| Field | Value |
|---|---|
| Source | `cohort_alternating_edgar` |
| Level used | L3 (311) |
| Sample size | 99 |
| Confidence | high |
| Band (min, target, max) | **(-0.011, 0.060, 0.114)** |

### Target 3 — current_assets_minus_cash

| Field | Value |
|---|---|
| Source | **`phase_9_p3_generic_default`** (no cohort/baseline coverage) |
| Level used | L0 (`*`) |
| Sample size | n/a |
| Confidence | generic_default |
| Band (min, target, max) | **(0.15, 0.225, 0.30)** |

### Target 4 — current_liabilities_to_revenue

| Field | Value |
|---|---|
| Source | **`phase_9_p3_generic_default`** (no cohort/baseline coverage) |
| Level used | L0 (`*`) |
| Sample size | n/a |
| Confidence | generic_default |
| Band (min, target, max) | **(0.08, 0.14, 0.20)** |

### Driver bounds (per-target)

| Target | Driver | Source | L | Bounds |
|---|---|---|---|---|
| gross_margin_percent | `expenses::Cost of Goods Sold` | cohort EDGAR | L3 | `[0.633, 0.795]` |
| ebitda_margin | `expenses::Cost of Goods Sold` | cohort EDGAR | L3 | `[0.633, 0.795]` |
| ebitda_margin | `expenses::Marketing` | cohort EDGAR | L3 | `[0.101, 0.264]` |
| ebitda_margin | `expenses::Research & Development` | cohort EDGAR | L3 | `[0.006, 0.023]` |
| ebitda_margin | `expenses::General & Administrative` | cohort EDGAR | L3 | `[0.101, 0.264]` |
| current_assets_minus_cash | `balance_sheet::Accounts Receivable Days` | cohort EDGAR | L3 | `[24.3, 41.7]` |
| current_assets_minus_cash | `balance_sheet::Inventory Days` | cohort EDGAR | L3 | `[50.9, 111.8]` |
| current_assets_minus_cash | `balance_sheet::Prepaid Expenses (% of Revenue)` | SEC EDGAR | L3 | `[0.009, 0.028]` |
| current_liabilities_to_revenue | `balance_sheet::Accounts Payable Days` | cohort EDGAR | L3 | `[24.3, 67.1]` |
| current_liabilities_to_revenue | `balance_sheet::Deferred Revenue (% of Revenue)` | SEC EDGAR | L3 | `[0.004, 0.015]` |

---

## 3. Sunny intake quick read + Q1 starting-state vs band

### Stated intake (operator inputs)

| Field | Value |
|---|---|
| business_naics_6 | 311811 |
| units_per_period_capacity | 1,200 donuts/period |
| unit_price | $2.00 |
| utilization_rate | 0.75 |
| current_revenue (intake-quoted weekly) | $4,500 |
| current_cogs (intake-quoted) | $27,144 |
| **stated cogs_percent_of_revenue** | **0.29 (29%)** |
| baseline_marketing_percent | 0.07 |
| current_payroll (annual) | $183,323 |
| monthly_rent_expense | $2,000 |
| ar_balance | $0 |
| ap_balance | $3,000 |
| inventory_balance | $800 |
| total_debt_outstanding | $0 |
| company_revenue_total_year1 | $93,600 |
| current_num_employees | 2 |

### Q1 metric values from the persisted FINMO (post-intake, pre-system-run)

The persisted draft's `finmo_json` reflects the planner's Q1 build from
intake. Sunny's actual Q1 figures:

| Field | Q1 value |
|---|---:|
| revenue | $67,598 |
| cost_of_goods_sold | $33,799 |
| gross_profit | $33,799 |
| ebitda | **-$26,806** |
| net_income | -$26,811 |
| accounts_receivable | $22,121 |
| accounts_payable | $19,137 |
| inventory | $14,464 |
| prepaid_expenses | $1,352 |
| deferred_revenue | $25,687 |
| current_assets (computed) | $17,721 |
| current_liabilities | $44,824 |
| cash | -$20,216 |

(Note: the operator-stated `cogs_percent_of_revenue` of 0.29 differs from
the FINMO-computed Q1 value of 0.50. The planner appears to have re-derived
cogs from a different base — likely capacity × ingredient-implied cost — so
the FINMO Q1 reflects what the system actually plans against, not the
operator's stated 29%.)

### Q1 starting state vs band (the 4 solver targets)

| Target | Q1 actual | Band | Direction needed | Magnitude |
|---|---:|---|---|---:|
| `gross_margin_percent` | **0.500** | [0.20, 0.27, 0.36] | **ABOVE band → LOWER (compress)** | ~0.14 |
| `ebitda_margin` | **-0.397** | [-0.011, 0.060, 0.114] | **BELOW band → RAISE (lift losses)** | ~0.40 |
| `current_assets_minus_cash` | **0.561** | [0.15, 0.225, 0.30] | **ABOVE band → LOWER (compress WC)** | ~0.26 |
| `current_liabilities_to_revenue` | **0.663** | [0.08, 0.14, 0.20] | **ABOVE band → LOWER (compress liabilities)** | ~0.46 |

---

## 4. Comparison to ExpressLogix + risk flags

### How Sunny differs from ExpressLogix

| Dimension | ExpressLogix | Sunny |
|---|---|---|
| NAICS | 488 — Transportation (cohort at L4) | 311811 — Donut shop (cohort at **L3, 3 levels off**) |
| Q1 gross_margin | below band → **lift** | **above band → compress** (opposite!) |
| Q1 ebitda | -25% (deep loss) | **-40% (deeper loss)** |
| Q1 working capital | within range | **way above band** (deferred revenue ~38% of revenue) |
| Solver direction | unidirectional (raise everything) | **adversarial** (compress GM AND lift EBITDA) |
| Cohort coverage | NAICS-6 / NAICS-5 hits | **L3 generic food-manufacturing** + 2 generic_default targets |

### Risk flag — adversarial targets

The solver's gross_margin target wants cogs% to **rise** (from 0.50 toward
the cohort 0.633-0.795 range) to compress gross margin from 0.50 down to
0.27. But the ebitda target wants total cost to **fall** to lift EBITDA
from -40% toward 0. Raising cogs% adds COGS — directly hurts EBITDA.

For ExpressLogix the directions aligned (lower cogs% raises BOTH gm and
ebitda). For Sunny they oppose. The slack-proportional allocator will
land somewhere between, not on either target; depending on weights, this
may park ebitda short of viability OR park gross_margin above band.

**The cogs% lever has zero slack in the "raise ebitda" direction**: Q1
cogs% = 0.50 is already below the cohort lower bound 0.633. Solver
cannot lower cogs% further. To lift ebitda to ≥ 0 by Q11, slack must
come from marketing% (current 6%, bound [0.10, 0.26] — also below lower
bound, can't compress), r_and_d% (bound [0.006, 0.023]), or sga% (bound
[0.10, 0.26]).

**Net read:** Sunny may exhaust the operating-side driver list before
landing ebitda ≥ 0. The exhaustion would be honest (every lever pinned),
and the per-driver bound diagnostic would flag that this business model
cannot reach industry-typical EBITDA without a structural change
(price increase, capacity expansion, headcount cut) that lives outside
the current 4-target driver list.

### Risk flag — deferred revenue inapplicability

Sunny's NAICS-2 = 31 (Manufacturing) is **not** in the deferred-revenue-
applicable set `{51, 52, 53, 54, 62}` per
`_DEFERRED_REVENUE_APPLICABLE_NAICS2`. The realism row for
`deferred_revenue_percent_of_revenue` would skip via applicability rule
in the validator. But the solver's `current_liabilities_to_revenue` target
includes `balance_sheet::Deferred Revenue (% of Revenue)` as a driver.
If the deferred-revenue lever has no operating semantics for a donut
shop, the solver may still write to it (lowering deferred%) and FINMO
will reflect lower current liabilities — but the underlying business
shouldn't have $25k deferred revenue at Q1 in the first place. This is
an upstream intake / FINMO model issue showing as a target the solver
will try to fix.

### Risk flag — generic-default bands for Targets 3 & 4

`current_assets_minus_cash` and `current_liabilities_to_revenue` resolve
to the Phase 9 P3 inline `generic_default` bands (15-30% and 8-20%).
These are cross-industry defaults; donut shops in particular probably
have lower working-capital and lower current-liability ratios than that
generic. Sunny's Q1 values (0.56, 0.66) are far above either default,
so the solver will compress aggressively; whether the resulting state
matches a real donut-shop balance sheet is unverified.

---

## 5. Likely E2E outcome

Based on the data above:

- **gross_margin_percent**: solver will compress from 0.50 toward 0.27.
  Should land — cogs% has plenty of slack to raise (current 0.50, upper
  bound 0.795).
- **ebitda_margin**: high risk of BOUND_PINNED exit. Q1 = -0.40, target
  Q11 ≥ 0. Operating drivers are at or below their lower bounds in the
  cost-cutting direction. Likely exhaustion with honest diagnostic.
- **current_assets_minus_cash**: solver will compress from 0.56 toward
  0.225 by lowering AR_days, inventory_days, prepaid%. Should land.
- **current_liabilities_to_revenue**: solver will compress from 0.66
  toward 0.14 by lowering AP_days and deferred%. Should land —
  AP_days at 35.9 is in band already, deferred% at 38% has lots of
  room to fall toward [0.004, 0.015].

Expected acceptance gate: **likely 14-15 of 16**. The two that may not
land:
- `realism_gate_no_hard_fail_violations` — if ebitda stays negative
  through Q11+
- `viability_timeline_landed` — same root cause (`ebitda_positive_by_q11`
  fails)

If the loop exhausts honestly, the per-driver bound diagnostic will
report which levers are pinned, and the user can decide whether to
expand the driver authority (e.g., add revenue::Unit Price to the
ebitda target) or accept the diagnosis "this business model cannot
reach industry-typical EBITDA at the operator-stated scale."

---

## Standby

No code changes from this pre-flight. Awaiting OK to run E2E.
