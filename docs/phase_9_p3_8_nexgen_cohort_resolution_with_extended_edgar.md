# Phase 9 P3.8 — NexGen cohort resolution with extended EDGAR

**Date:** 2026-05-11
**Subject:** Does the EDGAR backfill (20,907 → 99,847 rows, 2015 → 2026 coverage) materially change the cohort cascade for NexGen's three problem metrics? Read-only inspection — no E2E run, no code changes.

---

## 0. NAICS-code reconciliation

The user's prompt referenced NAICS **511210**. NexGen's actual draft tags `business_naics_6 = "513210"` ([yesterday's P3.7 NexGen draft `51ab9a6d…`](#)). The two codes refer to the same activity at different points in time:

- **511210 — Software Publishers** in the 2017 NAICS taxonomy.
- **513210 — Software Publishers** in the 2022 NAICS revision (the entire subsector moved from `511` to `513`).

The cohort tables (`industry_metrics_edgar`, `industry_metrics_alpha`) use the 2022 NAICS codes. Modern Software Publishers tagged `513210` are well-represented; the legacy `511210` code has zero rows in either table.

**For accuracy this report uses 513210 (NexGen's actual code).** A short Appendix B at the end shows what 511210 resolves to (it falls all the way through to NAICS-2 because the prefix doesn't appear in the data).

---

## 1. EDGAR depth at 513210 — before vs after the backfill

| | Pre-backfill (≤ yesterday) | Post-backfill (today) |
|---|---:|---:|
| Rows in `industry_metrics_edgar` at NAICS 513210 | 1,378 (since 2024-05-19) | **5,605** (since 2015-05-29) |
| Distinct firms at 513210 | 289 | **312** |
| Date range at 513210 | 2024-05 → 2026-04 | **2015-05 → 2026-03** |
| Distinct fiscal years | 3 | 12 |

Year-by-year breakdown post-backfill at 513210:

```
year   rows   firms
----   ----   -----
2015    141     58
2016    222     71
2017    341    111
2018    437    133
2019    481    144
2020    561    187
2021    589    199
2022    610    209
2023    633    216
2024    762    285
2025    713    255
2026    115    115
```

Alpha at 513210 (unchanged): 6,661 rows, 194 firms, 2015-01 → 2025-10.

---

## 2. Cohort cascade output — the three problem metrics

There are TWO cohort resolvers in the codebase:

1. **`post_intake_industry_baseline.lookup.post_intake_industry_baseline_for_naics`** — alternating EDGAR/Alpha walk, NAICS cascade only, ≥ 2 distinct firms threshold. Used as the cohort-cascade fallback.
2. **`post_intake_solver.cohort_band_resolver.resolve_cohort_band`** — alternating EDGAR/Alpha walk PLUS revenue-window and date-window cascades and `cap_category` filtering. Used by `assemble_finmo_output_targets` to populate `solver_input.finmo_output_targets.metrics` — i.e., the `phase_3_calibrated` bands the realism gate consumes.

Both run end-to-end here so the doc reflects exactly what the runtime would compute.

### 2.1 `current_liabilities_to_revenue`

| Resolver | NAICS level | band min | **band target** | band max | data source | firms | sample | confidence |
|---|---:|---:|---:|---:|---|---:|---:|---|
| alternating walk (lookup.py) | **L6=513210** | 0.464 | **1.341** | 2.132 | cohort_alternating_edgar | 280 | 4,389 | high |
| cohort_band_resolver (assembler) | **L6=513210** | 0.397 | **1.244** | 2.052 | cohort_alternating_edgar | 271 | 3,688 | high |

Yesterday's realism row for Q1 (`51ab9a6d…` draft):

```
band_naics_code:        513210
band_naics_level:       6
band_target:            0.0567     (5.67%)
band_min:              -0.13335
band_max:               0.281102
effective_max:          0.351102    (after 700bp tolerance)
band_data_source:       phase_3_target_shaping_consultant
band_confidence_tier:   high
```

**The cohort target shifted from 0.0567 → ~1.24 — a 22× increase.** The new 11-year cohort includes 2015-2023 SaaS firms with mature deferred-revenue books and high opex; the cap_categories ['small','mid'] filter narrows to growth-stage / pre-IPO SaaS where current_liabilities run 50-150% of revenue.

NexGen's actual Q1 = 0.594 (59% CL/Rev) — hard-failed yesterday's band [0.351 cap]. Today's cohort band would put it **comfortably in-band** (cohort band 0.40 – 2.05).

### 2.2 `inventory_days`

| Resolver | NAICS level | band min | **band target** | band max | firms | sample | confidence |
|---|---:|---:|---:|---:|---:|---:|---|
| alternating walk (lookup.py) | **L6=513210** | 10.5 | **34.6** | 74.5 | 64 | 868 | high |
| cohort_band_resolver (assembler) | **L6=513210** | 9.3 | **39.2** | 86.1 | 63 | 622 | high |

Pre-backfill cohort target at NAICS-3=511 was 34.21 days ([P3.7 decline diagnosis doc](phase_9_p3_7_post_recovery_decline_diagnosis.md)). Today the value is essentially unchanged at L6=513210 (target 34-39 days).

**Mechanism:** the cohort includes firms tagged 513210 that DO carry physical inventory — legacy software publishers (boxed media), software firms with hardware addons, and firms whose NAICS tag is imprecise (SIC→NAICS crosswalk maps several borderline activities into 513210). Pure SaaS firms with inventory_days ≈ 0 are diluted by inventory-carrying members of the cohort.

**The realism gate skips this metric entirely for NAICS-2 in {31,32,33,42,44,45,72} via `inventory_when_business_has_inventory`** ([P3.8 applicability audit doc](phase_9_p3_8_applicability_rule_audit.md)). NAICS-2=51 is NOT in the applicable set, so inventory_days is `status="skipped"` at every quarter regardless of cohort value. **The EDGAR backfill does not change this outcome — the 35-day Inventory Days problem is structurally the same.**

### 2.3 `deferred_revenue_percent_of_revenue`

| Resolver | NAICS level | band min | **band target** | band max | firms | sample | confidence |
|---|---:|---:|---:|---:|---:|---:|---|
| alternating walk (lookup.py) | **L5=51321** | 0.032 | **0.123** | 0.343 | — | 752 | medium |
| cohort_band_resolver (assembler) | — | — | — | — | — | — | None (metric not in `METRIC_KEY_TO_COLUMN`) |

`deferred_revenue_percent_of_revenue` is NOT in `cohort_band_resolver.METRIC_KEY_TO_COLUMN`, so the per-business `phase_3_calibrated` path returns None for it. The realism gate falls through to the `naics_baseline` cascade (lookup.py's alternating walk). At NAICS 513210, the walk lands at **L5=51321** with target = **12.3%**.

**Yesterday's NexGen seed_value for deferred revenue was 30%** ([balance_sheet_contextual_seed](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py)), set by `seed_value: 0.30` with rationale `naics_cascade (deferred_revenue_percent_of_revenue target=0.2138)`. The seed proposer's cascade target was 21.38% then. With the deeper cohort, the cascade now suggests 12.31% — closer to operator-realistic SaaS values.

The seed proposer's RUNTIME would now seed at ~12% instead of 30% if the proposer were re-run for NexGen post-backfill (it isn't on a static draft).

### 2.4 Bonus: `ebitda_margin`

| Resolver | NAICS level | band min | **band target** | band max | firms | sample | confidence |
|---|---:|---:|---:|---:|---:|---:|---|
| alternating walk (lookup.py) | **L6=513210** | -0.224 | **-0.029** | 0.099 | 206 | 2,426 | high |
| cohort_band_resolver (assembler) | **L6=513210** | -0.254 | **-0.052** | 0.074 | 201 | 2,108 | high |

Pre-backfill cohort target at L6=513210 was -0.5%. **Post-backfill it's MORE negative — between -2.9% and -5.2%.**

Why: the 2015-2020 cohort of SaaS firms is materially less profitable than the post-2024-only window. Includes growth-stage firms running at -10% EBITDA margins. Median across the longer history is more negative than the 2024-only snapshot.

**Implication for the Q11→Q20 EBITDA decline finding:** the cohort target for ebitda_margin drives `q20_target` in `_build_target_ramp`. Post-clamp (`max(0.0, band_min) + safety`), yesterday's q20_target was 0.005 (band_min=-0.18, clamped to 0 + safety). With the new band_min = -0.254, the clamp still yields 0.005. Q20 ramp anchor unchanged. **However**, if downstream the clamp logic ever uses band_target directly (not min), the new target -0.052 would push Q20 anchor further negative → the peak-then-decline trajectory worsens, not improves.

---

## 3. What the EDGAR backfill actually fixed / didn't fix

| Yesterday's NexGen issue | Pre-backfill cohort | Post-backfill cohort | Fixed by backfill alone? |
|---|---|---|---|
| `current_liabilities_to_revenue` Q1-Q9 hard-fail (actual 0.594, cap 0.351) | band target 0.057, cap 0.351 | band target 1.24, cap 2.05 | **YES** — actual 0.594 is now in band by a wide margin. Would not have hard-failed. |
| `inventory_days` ≈ 35 days for software | target 34.2 days | target 34.6-39.2 days | **NO** — same magnitude. AND realism gate skips this metric for NAICS-2=51, so the issue would remain hidden either way. |
| `deferred_revenue_percent_of_revenue` seed at 30% | cascade target 21.4% | cascade target 12.3% | **PARTIALLY** — seed proposer would suggest ~12% next run, but existing drafts have the 30% baked in (`balance_sheet_contextual_seed.seed_value` is persisted per-draft). |
| Q11→Q20 EBITDA decline (5% → 0.5%) | cohort target -0.5% | cohort target -2.9% to -5.2% | **NO — would WORSEN.** Q20 ramp anchor is driven by `band_target` clamped to `max(0, band_min)+safety`. New band_min is even more negative, but the clamp still yields 0.005. If the ramp ever uses target directly, the decline depth grows. |

---

## 4. Bottom-line answer to "does findings 1/2 fix still need to be implemented?"

**Yes for findings 1 and 3, no for finding 2 — and a new concern surfaces.**

| Finding | Status |
|---|---|
| **#1 (Q11→Q20 post-recovery decline)** | **Still needs fix.** EDGAR backfill makes it WORSE, not better. The new cohort EBITDA target at NAICS 513210 is -2.9% to -5.2%. The decline-to-cohort-target trajectory is intrinsic to `_build_target_ramp`'s q20 anchor logic; the data extension doesn't change the shape. |
| **#2 (Inventory Days at 35 for software)** | **Still cohort-sourced.** Backfill does not move the cohort target meaningfully. The realism gate skip still hides it via the NAICS-2 applicability rule. The root cause is the cohort's NAICS-tag dilution (legacy publishers + hardware-bundle firms tagged 513210). A fix would need to either (a) tighten the applicability rule, (b) filter the cohort tables by business model signal, or (c) accept the cohort as-is and let GPT author Inventory Days as part of a future scope expansion. |
| **#3 (NexGen current_liabilities_to_revenue Q1 overshoot)** | **Resolved by data alone.** The cohort cascade now puts the band cap at ~2.05 vs yesterday's 0.351. NexGen's Q1 = 0.594 is comfortably in-band. The P3.7 BS_ONLY_PATH handler that fired yesterday wouldn't have been triggered today. |

**New concern surfaced:** the Q11→Q20 decline is now larger in EXPECTATION than yesterday because the cohort EBITDA target is more negative. If the realism gate's `phase_3_calibrated` band changes match the cohort cascade output (they do per `output_target_assembler`), this means **every NAICS-51 business that fires the restoration loop with `q20_target = cohort EBITDA target` will see a steeper Q11→Q20 EBITDA decline on a fresh re-run**. Even Sunny / Express would be unaffected because their cohort targets fit, but any modern SaaS draft would re-run with a more negative Q20 anchor.

---

## 5. Recommended next move

1. **Re-run NexGen E2E** with the post-backfill data. Confirm:
   - The forecast classifier no longer flags `current_liabilities_to_revenue` as failing → `scope=bs_only_path` no longer triggers
   - But the deterministic restoration loop produces a STEEPER Q11→Q20 EBITDA decline
   - The acceptance gate's 16/16 verdict — does it still hold or do new failures surface?
2. **Address Finding 1 (post-recovery decline)** as the next code change. The data extension didn't help; the ramp builder's `q20_target = cohort band_target` is the actual mechanism, and it's now anchored at more negative values.
3. **Address Finding 2 (Inventory Days)** with the applicability rule + scope expansion path (covered in the [phase_9_p3_8_applicability_rule_audit.md](phase_9_p3_8_applicability_rule_audit.md)) — not a data-side fix.

---

## Appendix A — Yesterday's NexGen `current_liabilities_to_revenue` Q1 realism row

```
band_naics_code:        513210
band_naics_level:       6                     <-- already L6, even pre-backfill
band_target:            0.0567   (5.67%)
band_min:              -0.13335
band_max:               0.281102
effective_min:         -0.20335   (after 700bp tolerance)
effective_max:          0.351102
band_data_source:       phase_3_target_shaping_consultant
band_confidence_tier:   high
actual_value:           0.5937
status:                 (would have been out_of_band_hard_fail if not muted)
```

The L6=513210 lookup was already happening yesterday. The data extension shifted band VALUES, not the resolution level.

## Appendix B — User's NAICS 511210 (deprecated 2017 code)

For NAICS 511210, all metrics fall through to NAICS-2=51 because the cohort tables have ZERO rows starting with `511`. The 511 prefix only existed under the 2017 NAICS taxonomy; the 2022 NAICS revision moved Publishing Industries (except Internet) elsewhere. Sample output:

```
NAICS 511210 — current_liabilities_to_revenue:
  band: [0.540, 1.134, 1.925]   data_source=cohort_alternating_edgar
  naics_level_used: 2 (51)      firms: 476     sample: 7,801     confidence: high

NAICS 511210 — inventory_days:
  band: [8.07, 26.12, 65.03]    data_source=cohort_alternating_edgar
  naics_level_used: 2 (51)      firms: 120     sample: 1,463     confidence: high

NAICS 511210 — ebitda_margin:
  band: [-0.159, 0.028, 0.181]  data_source=cohort_alternating_edgar
  naics_level_used: 2 (51)      firms: 360     sample: 4,558     confidence: high
```

When using 511210, the broader NAICS-2 cohort (476 firms) gives more sample but less sub-industry fit. Real NexGen is `513210` so this is academic; flagged here for completeness in case any historical drafts have the 2017 code.
