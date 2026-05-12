# Phase 9 P3.8 — Cohort window analysis: full history vs 5-year rolling

**Date:** 2026-05-11
**Subject:** Compare cohort cascade resolution under (A) full history (2015-now) vs (B) 5-year rolling window (`fiscal_year_min = 2021`). Across the 3 test businesses × 17 metrics. **No code changes. No E2E runs.** Analysis-only.

Window definitions in this report:
- **Full history**: every row in `industry_metrics_edgar` + `industry_metrics_alpha`, no fiscal-year filter.
- **5-year window**: rows with `YEAR(fiscalDateEnding) >= 2021` (i.e. fiscal year 2021 forward, ~5 years through Q1 2026).

The simple alternating-walk methodology mirrors `lookup.py::_cohort_alt_walk` (EDGAR-first → Alpha; first L/source pair with ≥2 distinct firms wins). The production `cohort_band_resolver` also widens revenue/date inside each (level, source); for this analysis I omit those to isolate the time-window effect.

---

## 1. Per-business resolution matrices

For each business × metric, columns:
- **Level/Source**: NAICS level & cohort table that won the walk (e.g. `L6/edgar`)
- **Firms**: distinct ticker count backing the band
- **Rows**: total firm-quarter observations
- **p25 / p50 / p75**: percentile band (target = p50, min = p25, max = p75 in the resolver's contract)

### 1.1 Sunny — NAICS 311811 (Retail Bakeries; full-history walk lands at L3=311 because the L4/L5/L6 cohort coverage is empty at this code)

| Metric | Full level | Firms | p25 | **p50** | p75 | | 5yr level | Firms | p25 | **p50** | p75 | | Δp50 |
|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|---|---:|
| gross_margin_percent | L3/edgar | 59 | 0.198 | **0.279** | 0.362 | | L3/edgar | 56 | 0.190 | **0.270** | 0.354 | | −3% |
| ebitda_margin | L3/edgar | 31 | 0.008 | **0.070** | 0.136 | | L3/edgar | 29 | −0.042 | **0.054** | 0.122 | | **−23%** |
| operating_margin_percent | L3/edgar | 56 | 0.005 | **0.070** | 0.125 | | L3/edgar | 53 | −0.033 | **0.063** | 0.113 | | −10% |
| net_income_margin | L3/edgar | 58 | −0.005 | **0.043** | 0.082 | | L3/edgar | 55 | −0.032 | **0.040** | 0.080 | | −7% |
| current_liabilities_to_revenue | L3/edgar | 60 | 0.379 | **0.540** | 0.798 | | L3/edgar | 57 | 0.285 | **0.513** | 0.773 | | −5% |
| current_assets_minus_cash_to_revenue | L3/edgar | 59 | 0.443 | **0.706** | 1.050 | | L3/edgar | 56 | 0.491 | **0.780** | 1.138 | | +11% |
| ar_days_dso | L3/edgar | 51 | 25.4 | **33.0** | 41.0 | | L3/edgar | 47 | 24.7 | **32.4** | 41.2 | | −2% |
| ap_days_dpo | L3/edgar | 50 | 22.2 | **31.5** | 50.7 | | L3/edgar | 47 | 22.6 | **31.9** | 57.1 | | +1% |
| inventory_days | L3/edgar | 55 | 49.9 | **72.2** | 106.9 | | L3/edgar | 52 | 50.7 | **74.4** | 117.0 | | +3% |
| cogs_percent_of_revenue | L3/edgar | 59 | 0.633 | **0.715** | 0.798 | | L3/edgar | 56 | 0.637 | **0.724** | 0.802 | | +1% |
| sga_percent (mkt proxy) | L3/edgar | 56 | 0.096 | **0.162** | 0.267 | | L3/edgar | 53 | 0.099 | **0.171** | 0.282 | | +6% |
| rnd_percent_of_revenue | L3/edgar | 10 | 0.006 | **0.016** | 0.044 | | L3/edgar | 9 | 0.005 | **0.012** | 0.054 | | −26% |
| current_ratio | L3/edgar | 59 | 1.32 | **1.94** | 3.07 | | L3/edgar | 56 | 1.27 | **1.93** | 3.16 | | −1% |
| quick_ratio | L3/edgar | 59 | 0.70 | **1.11** | 1.90 | | L3/edgar | 56 | 0.67 | **1.06** | 1.88 | | −4% |
| debt_to_equity | L3/edgar | 47 | 0.39 | **1.10** | 2.02 | | L3/edgar | 45 | 0.34 | **1.13** | 2.00 | | +2% |
| debt_to_assets | L3/edgar | 47 | 0.36 | **0.558** | 0.713 | | L3/edgar | 45 | 0.345 | **0.560** | 0.710 | | 0% |
| capex_percent_of_revenue | L3/edgar | 43 | 0.013 | **0.026** | 0.043 | | L3/edgar | 39 | 0.014 | **0.027** | 0.043 | | +4% |

**Sunny summary:** zero NAICS-level shifts. Firm counts drop ~5%, well above the 2-firm threshold. The big shifts are profitability metrics: **ebitda_margin p50 −23%, p25 went from +0.008 to −0.042** (more loss-makers in the recent window — food-manufacturing margin compression in 2022-2024). `current_liabilities_to_revenue` also softens 5%, suggesting modern food firms run leaner working capital.

### 1.2 Express — NAICS 488510 (Freight Transportation Arrangement)

| Metric | Full level | Firms | p25 | **p50** | p75 | | 5yr level | Firms | p25 | **p50** | p75 | | Δp50 |
|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|---|---:|
| gross_margin_percent | L6/edgar | 6 | 0.112 | **0.148** | 0.376 | | L6/edgar | 6 | 0.139 | **0.243** | 0.429 | | **+64%** |
| ebitda_margin | L6/edgar | 8 | 0.023 | **0.048** | 0.064 | | L6/edgar | 8 | 0.017 | **0.049** | 0.073 | | +1% |
| operating_margin_percent | L6/edgar | 9 | 0.016 | **0.047** | 0.092 | | L6/edgar | 9 | −0.015 | **0.041** | 0.093 | | −13% |
| net_income_margin | L6/edgar | 10 | 0.019 | **0.037** | 0.072 | | L6/edgar | 10 | −0.064 | **0.029** | 0.073 | | **−21%** |
| current_liabilities_to_revenue | L6/edgar | 8 | 0.377 | **0.553** | 0.630 | | L6/edgar | 8 | 0.00001 | **0.532** | 0.681 | | −4% |
| current_assets_minus_cash_to_revenue | L6/edgar | 8 | 0.400 | **0.644** | 0.722 | | L6/edgar | 7 | 0.383 | **0.601** | 0.740 | | −7% |
| ar_days_dso | L6/edgar | 7 | 37.8 | **58.2** | 65.0 | | L6/edgar | 6 | 36.1 | **56.8** | 66.8 | | −3% |
| ap_days_dpo | L6/edgar | 5 | 9.5 | **26.9** | 34.8 | | L6/edgar | 5 | 0.4 | **27.1** | 34.9 | | +1% |
| inventory_days | L6/alpha | 3 | 0.0 | **0.08** | 1.43 | | L6/alpha | 3 | 0.0 | **0.19** | 9.61 | | +143% (tiny numbers) |
| cogs_percent_of_revenue | L6/edgar | 6 | 0.615 | **0.839** | 0.886 | | L6/edgar | 6 | 0.577 | **0.757** | 0.858 | | **−10%** |
| sga_percent (mkt proxy) | L6/edgar | 7 | 0.026 | **0.031** | 0.140 | | L6/edgar | 6 | 0.024 | **0.085** | 0.238 | | **+173%** |
| rnd_percent_of_revenue | L6/alpha | 3 | 0.0 | **0.0** | 0.001 | | **L3/alpha** | 4 | 0.002 | **0.028** | 0.052 | | **LEVEL SHIFT — L6→L3** |
| current_ratio | L6/edgar | 10 | 1.09 | **1.37** | 1.84 | | L6/edgar | 10 | 0.83 | **1.36** | 1.65 | | −1% |
| quick_ratio | L6/edgar | 10 | 1.09 | **1.37** | 1.84 | | L6/edgar | 10 | 0.83 | **1.36** | 1.65 | | −1% |
| debt_to_equity | L6/edgar | 7 | −1.26 | **1.84** | 2.31 | | L6/edgar | 7 | −0.28 | **2.09** | 3.05 | | +14% |
| debt_to_assets | L6/edgar | 7 | 0.65 | **0.72** | 1.01 | | L6/edgar | 7 | 0.68 | **0.80** | 0.99 | | +11% |
| capex_percent_of_revenue | L6/edgar | 5 | 0.002 | **0.010** | 0.024 | | L6/edgar | 5 | 0.002 | **0.008** | 0.023 | | −17% |

**Express summary:** ONE level shift (`rnd_percent_of_revenue`: L6 with 3 firms full → falls below threshold under 5-year, falls back to L3=488). Big band shifts on profitability: **gross_margin +64%** (COVID-era freight boom), net_income_margin −21% (sector contraction since 2023). The COVID era materially distorts Express's recent-window band. **sga_percent jumps from 0.031 to 0.085** (+173%) — likely a sampling artifact of the tiny L6 cohort (6 firms).

### 1.3 NexGen — NAICS 513210 (Software Publishers)

| Metric | Full level | Firms | p25 | **p50** | p75 | | 5yr level | Firms | p25 | **p50** | p75 | | Δp50 |
|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|---|---:|
| gross_margin_percent | L6/edgar | 267 | 0.502 | **0.692** | 0.784 | | L6/edgar | 255 | 0.498 | **0.700** | 0.786 | | +1% |
| ebitda_margin | L6/edgar | 206 | −0.224 | **−0.029** | 0.099 | | L6/edgar | 192 | −0.238 | **−0.032** | 0.100 | | −10% |
| operating_margin_percent | L6/edgar | 280 | −0.234 | **−0.038** | 0.095 | | L6/edgar | 271 | −0.246 | **−0.042** | 0.089 | | −11% |
| net_income_margin | L6/edgar | 283 | −0.239 | **−0.039** | 0.087 | | L6/edgar | 272 | −0.253 | **−0.043** | 0.082 | | −10% |
| current_liabilities_to_revenue | L6/edgar | 280 | 0.464 | **1.341** | 2.132 | | L6/edgar | 270 | 0.084 | **0.921** | 1.951 | | **−31%** |
| current_assets_minus_cash_to_revenue | L6/edgar | 279 | 0.409 | **0.598** | 0.839 | | L6/edgar | 269 | 0.384 | **0.579** | 0.826 | | −3% |
| ar_days_dso | L6/edgar | 277 | 35.6 | **50.8** | 70.7 | | L6/edgar | 266 | 32.7 | **49.0** | 68.9 | | −4% |
| ap_days_dpo | L6/edgar | 209 | 15.7 | **31.5** | 63.7 | | L6/edgar | 199 | 14.5 | **30.3** | 61.8 | | −4% |
| inventory_days | L6/edgar | 64 | 10.5 | **34.6** | 74.5 | | L6/edgar | 59 | 7.1 | **35.8** | 85.7 | | +4% |
| cogs_percent_of_revenue | L6/edgar | 259 | 0.217 | **0.308** | 0.492 | | L6/edgar | 249 | 0.216 | **0.302** | 0.499 | | −2% |
| sga_percent (mkt proxy) | L6/edgar | 285 | 0.119 | **0.190** | 0.310 | | L6/edgar | 277 | 0.119 | **0.194** | 0.321 | | +2% |
| rnd_percent_of_revenue | L6/edgar | 232 | 0.130 | **0.208** | 0.296 | | L6/edgar | 224 | 0.132 | **0.215** | 0.304 | | +4% |
| current_ratio | L6/edgar | 308 | 0.98 | **1.55** | 2.63 | | L6/edgar | 299 | 0.98 | **1.54** | 2.68 | | 0% |
| quick_ratio | L6/edgar | 308 | 0.95 | **1.50** | 2.56 | | L6/edgar | 299 | 0.95 | **1.49** | 2.61 | | −1% |
| debt_to_equity | L6/edgar | 290 | 0.246 | **0.764** | 1.781 | | L6/edgar | 280 | 0.245 | **0.755** | 1.761 | | −1% |
| debt_to_assets | L6/edgar | 283 | 0.337 | **0.529** | 0.763 | | L6/edgar | 274 | 0.335 | **0.525** | 0.776 | | −1% |
| capex_percent_of_revenue | L6/edgar | 214 | 0.005 | **0.015** | 0.035 | | L6/edgar | 202 | 0.004 | **0.011** | 0.028 | | −27% |

**NexGen summary:** zero NAICS-level shifts. Firm counts drop ~4-6%, deep above threshold (cohort has 200+ firms throughout). The headline shift: **`current_liabilities_to_revenue` p50 drops 31% (1.34 → 0.92)** — modern SaaS firms (2021-now) run leaner working-capital books than the 2015-2020 cohort. `capex_percent_of_revenue` drops 27% (asset-lighter SaaS recently). Everything else moves <11%.

---

## 2. Aggregate questions

### 2.1 Coverage impact (level shifts under 5-year window)

Counting `(business, metric)` pairs where 5-year window resolved at a different NAICS level than full history:

| Resolution outcome | Count | Examples |
|---|---:|---|
| **No level shift** | 50 / 51 | All Sunny / NexGen metrics; nearly all Express metrics |
| **L6 → L3 fallback** | 1 | Express `rnd_percent_of_revenue` (full: 3 firms@L6 → 5yr: <2 firms@L6, falls to L3=488 with 4 firms) |
| **L6 → L4 fallback** | 0 | — |
| **L6 → L5 fallback** | 0 | — |
| **Falls to `phase_3_calibrated`** | 0 | — |
| **Firm count drops below 2-firm threshold** | 1 | (same case as the L6→L3 fallback) |

Coverage is robust under the 5-year window. **Only ONE (1) of 51 (business, metric) pairs degrades**, and it degrades by exactly one NAICS level (L6→L3) — not all the way to generic fallback. The 11-year backfill gave the cohort tables enough density that even halving the time window keeps coverage intact in 50/51 cells.

### 2.2 Band shift magnitudes

Counting pairs where `|Δp50| / p50_full > 25%` (material shift):

| Business | Material-shift metrics | Direction notes |
|---|---|---|
| **Sunny (NAICS 311811)** | 0 metrics with Δp50 > 25% (closest: rnd_percent_of_revenue −26%, but that metric resolves on a 10-firm cohort — noise-dominated) | Profitability margins compressed ~10-20%, but none cross the 25% threshold on p50. |
| **Express (NAICS 488510)** | **3 metrics**: gross_margin_percent (+64%), sga_percent (+173%, but small-cohort noise), rnd_percent_of_revenue (level shift). net_income_margin (−21%) is at the edge. | Freight COVID-era distortion is real and material. Plus small-cohort sampling noise. |
| **NexGen (NAICS 513210)** | **2 metrics**: current_liabilities_to_revenue (−31%), capex_percent_of_revenue (−27%) | SaaS structural shift — 2021-now firms run leaner working capital and lighter capex than the 2015-2020 cohort. |

Across the 51 pairs total, **6 have material shifts** (~12%). Most of these have a plausible economic explanation; one (Express sga) is sampling noise on a 6-firm cohort.

### 2.3 NexGen-specific check on `current_liabilities_to_revenue`

Yesterday's NexGen failed Q1-Q9 hard-fail on this metric (actual 0.594, band cap 0.351).

After the 11-year EDGAR backfill (full history):
- L6 cohort target = **1.341**, band [0.464, 2.132]
- NexGen Q1 = 0.594 is **comfortably in-band**

Under 5-year window:
- L6 cohort target = **0.921**, band [0.084, 1.951]
- NexGen Q1 = 0.594 is **still comfortably in-band** (between p25=0.084 and p75=1.951)

Both windows resolve this metric in NexGen's favor — the failure that triggered P3.7 wouldn't fire under either. The 5-year window produces a tighter, more contemporary band (target 92% vs 134%) which arguably better fits modern SaaS, but doesn't change the in/out-of-band verdict for NexGen.

### 2.4 COVID-era distortion question

The 5-year window covers fiscal years 2021-2026 — heavily including the COVID-era anomalies of 2021-2022. Observed distortions:

| Sector | COVID-era effect | Evidence in this dataset |
|---|---|---|
| **Freight (NAICS 488510, Express)** | 2021-2022 freight rates spiked. Margins inflated. | gross_margin p50: full 0.148 → 5yr **0.243** (+64%). The 5-year window overweights the boom; mean reversion to 2024-2026 norms is masked. Would PRODUCE bands ill-suited for 2026 freight startups. |
| **Food manufacturing (NAICS 311, Sunny)** | 2022 input cost spike compressed margins; 2023-2024 still recovering. | ebitda_margin p25: full +0.008 → 5yr **−0.042**. Recent window over-weights loss-makers. |
| **Software publishing (NAICS 513210, NexGen)** | 2021 ZIRP-era growth-at-all-costs; 2023-2024 efficiency reset. Two opposing forces. | ebitda_margin shifts only −10%; net effect of the two regimes is small. **But current_liabilities_to_revenue drops 31%** — likely captures the deferred-revenue-deflation as SaaS firms shorten contract terms post-ZIRP. |
| **Retail bakeries (Sunny's actual L6)** | not in cohort at L6 — resolves at L3=311 (broader food manufacturing) | Sunny inherits food-mfg distortions, not retail-specific ones. |

**Net assessment:** the 5-year window IS introducing distortion, but only in sectors with cyclical or single-shock dynamics. Stable-margin sectors (NexGen gross_margin, NexGen ar/ap_days, Sunny inventory_days) move <5%. Cyclic sectors (freight) and recently-shifting sectors (SaaS working capital) move 20%+.

This is the core tradeoff: the 5-year window is more "economically current" by construction, but "current" includes recent anomalies. The full history smooths anomalies via longer averaging but lags structural shifts.

### 2.5 Time-decay alternatives (brief)

| Approach | Trade-off |
|---|---|
| **3-year window (2023+)** | More current still, but risks dropping coverage at small-NAICS-6 cohorts. Express's 6-firm L6 cohort might fall below threshold for several metrics; NAICS-3 fallback affects many more pairs. Probably too aggressive. |
| **5-year window (2021+)** | This document's tested option. Solid coverage (50/51 pairs at original level) and meaningful currentness. Captures COVID-era anomalies for 2 of the 3 sample sectors. |
| **7-year window (2019+)** | Smoother. Excludes pre-2019 dotcom-era distortion (relevant for some SaaS L6 firms with 25+ year histories) but keeps COVID. Better noise/recency balance for cyclic sectors. |
| **10-year window (2016+)** | Effectively current behavior (the cohort already starts in 2015). Marginal effect over full history given the backfill we just did. |
| **Recency-weighted (exponential decay)** | Each row weighted by `exp(-λ × years_old)`. Avoids hard cutoffs. λ tunes the half-life (e.g., λ=0.2 gives 3.5-year half-life). Better than a hard window in theory; needs a percentile-with-weights computation (not trivial in SQL, doable in Python). Best fit if the team wants smoothness AND recency. |
| **Stage-adaptive window** | Pre-revenue / early-stage businesses get longer windows (need stable industry baselines); operating / mature get shorter windows (need contemporary benchmarks). Architecturally cleaner than a per-business override but adds a stage→window mapping. |
| **Volatility-aware window** | Tighter window when cohort variance is rising (regime change in progress); wider window when cohort is stable. Detects regime changes automatically. More complex; would need volatility estimation per (metric, NAICS). |

The most defensible single value, given the data: **7 years** (2019+) — captures the COVID anomaly without overweighting it, keeps coverage solid, and excludes pre-cloud-software distortion for sectors like NexGen's NAICS 513210.

The most flexible option: **stage-adaptive** — startups need historical context (full window) to build a plausible trajectory; operating firms benchmark against current performance (5-7 year window).

The most rigorous option: **recency-weighted with exponential decay** — produces continuous shift rather than discrete window edges, and individual metrics can have different half-lives if needed.

---

## 3. Recommendation summary (not for implementation — for the decision)

| Choice | Pros | Cons |
|---|---|---|
| **Keep full history (do nothing)** | Maximum sample size, smooth bands, no architectural change. | Bands lag economic regime shifts. NexGen's `current_liabilities_to_revenue` band at 1.34 reflects partly-irrelevant 2015-2020 SaaS economics. |
| **Switch to 5-year window** | Bands reflect recent economic conditions. Coverage holds at 50/51 pairs. | COVID-era anomalies (freight margins, food cost shocks) get overweighted. Small-NAICS-6 cohorts (Express) lose 1 metric to broader NAICS fallback. |
| **Switch to 7-year window** | Better noise/recency balance. Excludes obsolete pre-2019 distortion without overweighting COVID. Sample depth more robust than 5-year. | Compromise position; not as clean a "this is the right number" answer as 5 or 10. |
| **Recency-weighted** | Best theoretical fit. No hard cutoff. Can tune per metric. | Architectural change (weighted percentile SQL). Risk of harder-to-debug bands. Justifies a careful design pass. |

If the decision is to introduce ANY windowing: **prefer recency-weighted exponential decay over a hard 5-year cutoff**, because it captures the user's intent ("more economically current") while sidestepping the COVID-overweighting trap and the small-cohort-degradation risk on Express-class drafts.

If the decision is to KEEP full history: the EDGAR backfill alone resolved Finding 3 (NexGen current_liabilities_to_revenue) without any windowing — full history is sufficient there. The remaining Findings 1 and 2 need code-level work regardless of window choice.
