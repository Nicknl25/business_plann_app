# Phase 9 — NAICS Coverage Audit

Read-only audit. No code or DB writes.

Database: `biz_plan_revert` (MySQL 8). Snapshot date: 2026-05-09.

## 0. Scope summary

Two cohort sources feed the realism gate via different paths:

| Source | Table(s) | Row count | Distinct firms |
|---|---|---|---|
| **Alpha** (Alpha Vantage) | `alpha_data` joined with `alpha_match_naics_industry` → aggregated into `industry_metrics_raw` (the runtime cohort table) | 137,579 | 3,665 (with usable metrics) |
| **EDGAR** (SEC XBRL Frames API) | `sec_edgar_facts` (offline staging; aggregated into `post_intake_industry_baseline_lookup`) | 644,812 facts / 6,994 distinct CIKs | 2,547 (with usable rev + cost concepts and a NAICS-6) |

Two resolvers consume these:

1. **`cohort_band_resolver`** ([python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py](python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py)) — runtime, queries `industry_metrics_raw` only. Used by `output_target_assembler` and `driver_movement_assembler` (the solver path), **not by the realism gate**.
2. **`post_intake_industry_baseline_for_naics`** ([python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py](python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py)) — pre-aggregated cascade against `post_intake_industry_baseline_lookup`. **This is what the realism gate uses** ([python/client_intake_and_finmo/post_intake_realism/validator.py:587](python/client_intake_and_finmo/post_intake_realism/validator.py#L587)).

"Usable data" definition for this audit:
- **Alpha**: distinct (symbol) in `industry_metrics_raw` with at least one non-null value across the 12 hard-fail metric columns that exist there (cogs_percent, gross_margin_q, sga_percent, ebitda_margin_q, net_margin_q, dso, dpo, inventory_days, current_ratio, debt_to_equity, debt_to_assets, capex_percent_revenue).
- **EDGAR**: distinct (cik) in `sec_edgar_facts` with at least one revenue concept (`Revenues` / `RevenueFromContractWithCustomerExcludingAssessedTax`) AND at least one cost/margin concept (`CostOfRevenue`, `CostOfGoodsAndServicesSold`, `GrossProfit`, `OperatingIncomeLoss`, `NetIncomeLoss`).

## 1. NAICS coverage by digit level

### 1.1 Alpha source (industry_metrics_raw)

Number of NAICS prefixes at each digit level, and how many have ≥N firms providing usable data.

| digit | total NAICS prefixes | ≥2 firms | ≥5 | ≥8 | ≥10 | ≥20 | ≥50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 6 | 388 | 252 | 132 | 92 | 80 | 41 | 10 |
| 5 | 307 | 220 | 119 | 83 | 70 | 43 | 14 |
| 4 | 213 | 177 | 109 | 84 | 71 | 45 | 16 |
| 3 | 82 | 75 | 68 | 59 | 55 | 39 | 15 |
| 2 | 24 | 24 | 23 | 23 | 22 | 20 | 18 |

### 1.2 EDGAR source (sec_edgar_facts)

| digit | total NAICS prefixes | ≥2 firms | ≥5 | ≥8 | ≥10 | ≥20 | ≥50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 6 | 352 | 220 | 106 | 77 | 63 | 29 | 7 |
| 5 | 282 | 195 | 97 | 69 | 56 | 31 | 11 |
| 4 | 200 | 163 | 92 | 71 | 58 | 33 | 13 |
| 3 | 78 | 73 | 65 | 54 | 48 | 30 | 13 |
| 2 | 24 | 23 | 23 | 22 | 21 | 19 | 14 |

### 1.3 Combined / deduped union

Combined firm key = ticker if present (EDGAR rows have a `ticker` column for 100% of usable EDGAR firms; Alpha rows use `symbol`), else `cik_<cik>`.

| digit | total NAICS prefixes | ≥2 firms | ≥5 | ≥8 | ≥10 | ≥20 | ≥50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 6 | 388 | 252 | 132 | 92 | 80 | 41 | 10 |
| 5 | 307 | 220 | 119 | 83 | 70 | 43 | 14 |
| 4 | 213 | 177 | 109 | 84 | 71 | 45 | 16 |
| 3 | 82 | 75 | 68 | 59 | 55 | 39 | 15 |
| 2 | 24 | 24 | 23 | 23 | 22 | 20 | 18 |

**Combined ≡ Alpha.** Of 2,547 usable EDGAR firms, 100% (2,547/2,547) have tickers, and every one of those tickers is already present in Alpha. Alpha is a strict superset of EDGAR at the firm level. Conclusion: EDGAR adds no new firms at runtime; its independent value is the offline-aggregated rows in `post_intake_industry_baseline_lookup` for metrics whose `primary_source = SEC_EDGAR` (marketing, advertising, operating cash flow margin, stock-based comp).

### 1.4 Total firm counts (sanity)

| set | firms |
|---|---:|
| Alpha-only usable | 3,665 |
| EDGAR-only usable | 2,547 |
| Combined unique | 3,665 |
| Overlap (in both) | 2,547 |

## 2. ExpressLogix — NAICS 488510 (Freight Transportation Arrangement)

### 2.1 Firm counts at each NAICS level

| level | prefix | firms (Alpha) | rows (Alpha) |
|---|---|---:|---:|
| 6 | 488510 | 3 (CHRW, EXPD, HUBG) | 129 |
| 5 | 48851 | 3 | 129 |
| 4 | 4885 | 3 | 129 |
| 3 | 488 | 8 | 231 |
| 2 | 48 | 74 | 2,814 |

EDGAR has the same 3 firms at 488510 (also CHRW, EXPD, HUBG).

### 2.2 What the cascade actually does for 488510

For each Phase 9 hard-fail metric, the realism gate cascade ([industry_baseline/lookup.py:319-373](python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L319-L373)) walks 6 → 5 → 4 → 3 → 2 → 0. At L6 it ONLY accepts rows where `data_source = primary_source` AND `confidence_tier IN ('high', 'medium')`. From the L5 step onward it accepts any source.

Confidence tiers in `post_intake_industry_baseline_lookup` (from observed `sample_size` cutoffs on `industry_metrics_raw` rows):

| tier | sample_size cutoff |
|---|---|
| high | n ≥ 40 |
| medium | 10 ≤ n ≤ 39 |
| low | 3 ≤ n ≤ 9 |

`sample_size` is **firm-quarter row count**, not distinct firms. Average rows-per-firm in Alpha = 37.5 quarters; so a NAICS-6 with 2 firms typically has ~75 rows → "high" tier.

For 488510 specifically (Phase 9 hard-fail metrics; level shown is the level the cascade actually settles at):

| metric | primary_source | level used | data_source used | confidence | n | p25 | p50 | p75 |
|---|---|---:|---|---|---:|---:|---:|---:|
| cogs_percent_of_revenue | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 0.862 | 0.891 | 0.923 |
| gross_margin_percent | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 0.077 | 0.109 | 0.138 |
| ebitda_margin | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 0.054 | 0.094 | 0.107 |
| net_income_margin | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 0.028 | 0.040 | 0.073 |
| sga_percent_of_revenue | industry_metrics_raw | 6 | industry_metrics_raw | high | 44 | 0.030 | 0.035 | 0.042 |
| capex_percent_of_revenue | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 0.004 | 0.005 | 0.012 |
| current_ratio | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 1.320 | 1.490 | 1.771 |
| debt_to_assets | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 0.440 | 0.516 | 0.675 |
| debt_to_equity | industry_metrics_raw | 6 | industry_metrics_raw | high | 45 | 0.785 | 1.068 | 2.077 |
| ap_days_dpo | industry_metrics_raw | 6 | industry_metrics_raw | high | 43 | 29.74 | 32.67 | 38.40 |
| inventory_days | industry_metrics_raw | 6 | industry_metrics_raw | medium | 21 | 0.000 | 0.812 | 7.886 |
| ar_days_dso | industry_metrics_raw | (not present at L6 — falls through) | — | — | — | — | — | — |
| **marketing_percent_of_revenue** | **SEC_EDGAR** | **5 (48851)** | SEC_EDGAR | low→capped medium | 5 | 0.0032 | 0.0033 | 0.0033 |
| **payroll_percent_of_revenue** | **derived_CBP_SOI** | (Census/SOI roll-up; covered) | — | — | — | — | — | — |
| **total_assets_to_revenue** | **IRS_SOI** | (IRS roll-up; covered) | — | — | — | — | — | — |
| **owners_capital_percent_of_assets** | **IRS_SOI** | (IRS roll-up; covered) | — | — | — | — | — | — |
| **distributions_percent_of_net_income** | **expert_default** | **0 (generic_default)** | expert_default | generic_default | NULL | 0.000 | 0.300 | 0.800 |

**Key observation.** For the 12 hard-fail metrics whose primary_source is `industry_metrics_raw`, 488510 resolves at NAICS-6 with high or medium confidence (45 rows). The over-aggregation hypothesis is **false** for those metrics — the cascade is not falling through to NAICS-3 for 488510.

The over-aggregation that DOES happen on 488510:
- **marketing_percent_of_revenue**: only 5 EDGAR rows at L6, falls through to L5 (still 5 rows from the same 3 firms — the entire freight-broker NAICS-6 / 5 / 4 cohort overlaps).
- **distributions_percent_of_net_income**: hardcoded to expert_default at L0 — NEVER resolves at NAICS-6, regardless of available data.

### 2.3 What the bands would be if forced to NAICS-3 vs NAICS-2 (hypothetical)

If 488510 fell through to NAICS-3 (488) or NAICS-2 (48) the bands would change as follows. NAICS-3 (488 = freight broker + air/water support activities) is close to NAICS-6, but NAICS-2 (48 = all transportation/warehousing including trucking, rail, water, pipelines) is dramatically different.

| metric | 488510 (NAICS-6) | 488 (NAICS-3) | 48 (NAICS-2) |
|---|---|---|---|
| cogs_percent: p25 / p50 / p75 | 0.868 / 0.883 / 0.918 | 0.852 / 0.877 / 0.920 | 0.643 / 0.791 / 0.872 |
| gross_margin_q: p25 / p50 / p75 | 0.082 / 0.117 / 0.132 | 0.080 / 0.123 / 0.148 | 0.129 / 0.212 / 0.367 |
| ebitda_margin_q: p25 / p50 / p75 | 0.053 / 0.074 / 0.106 | 0.032 / 0.069 / 0.109 | 0.071 / 0.153 / 0.315 |
| n (rows) | 129 | 213 | 2,713 |

Going to NAICS-2 would shift the COGS median from 0.88 to 0.79 (-9pp) and the EBITDA median from 0.07 to 0.15 (+8pp) — easily large enough to mis-classify a freight-broker-realistic plan as out-of-band.

## 3. Pairwise NAICS-3-shared comparisons

For each pair, NAICS-6 firm counts and the resolved p25/p50/p75 cogs / gross-margin / ebitda bands at NAICS-6 vs the shared parent prefix.

### 3.1 488510 (Freight Brokerage) vs 484121 (Long-Haul Truckload) — shared NAICS-2 48 (no shared NAICS-3)

| scope | firms | rows | cogs p25/p50/p75 | gm p25/p50/p75 | ebitda p25/p50/p75 |
|---|---:|---:|---|---|---|
| 488510 | 3 | 129 | 0.868 / 0.883 / 0.918 | 0.082 / 0.117 / 0.132 | 0.053 / 0.074 / 0.106 |
| 484121 | 15 | 585 | 0.800 / 0.834 / 0.868 | 0.132 / 0.166 / 0.200 | 0.080 / 0.133 / 0.176 |
| 48 (NAICS-2 parent) | 74 | 2,713 | 0.643 / 0.791 / 0.872 | 0.129 / 0.212 / 0.367 | 0.071 / 0.153 / 0.315 |

p50 cogs differential between 488510 and 484121 = 4.9 pp. Both round to NAICS-2 = ~9 pp away from 488510 truth. The two NAICS-6s are clearly distinct cost structures (asset-light brokerage vs asset-heavy trucking) and belong in their own buckets.

### 3.2 722511 (Full-Service Restaurants) vs 722515 (Snack & Coffee Bars) — shared NAICS-3 722 / NAICS-4 7225

| scope | firms | rows | cogs p25/p50/p75 | gm p25/p50/p75 | ebitda p25/p50/p75 |
|---|---:|---:|---|---|---|
| 722511 | 13 | 484 | 0.539 / 0.680 / 0.809 | 0.191 / 0.320 / 0.461 | 0.048 / 0.094 / 0.137 |
| 722515 | 2 | 66 | 0.698 / 0.722 / 0.744 | 0.256 / 0.278 / 0.302 | 0.145 / 0.190 / 0.223 |
| 722 (NAICS-3 parent) | 31 | 1,170 | 0.584 / 0.707 / 0.810 | 0.191 / 0.294 / 0.417 | 0.065 / 0.118 / 0.211 |

Snack/coffee bars (722515) have a 9-pp higher EBITDA margin median than full-service restaurants (722511). NAICS-3 hides that. The 2-firm 722515 cohort (66 rows = high confidence by row-count) DOES currently resolve at NAICS-6 — this is fine under the existing threshold.

### 3.3 513210 (Software Publishers) vs 513130 (Book Publishers) — shared NAICS-3 513

(Note: under the 2022 NAICS revision, what was 511210 / 511130 moved to 513210 / 513130. 511 has zero firms in `industry_metrics_raw`.)

| scope | firms | rows | cogs p25/p50/p75 | gm p25/p50/p75 | ebitda p25/p50/p75 |
|---|---:|---:|---|---|---|
| 513210 | 194 | 6,484 | 0.228 / 0.328 / 0.511 | 0.489 / 0.675 / 0.774 | -0.239 / 0.012 / 0.175 |
| 513130 | 3 | 130 | 0.294 / 0.340 / 0.437 | 0.563 / 0.660 / 0.706 | 0.000 / 0.103 / 0.194 |
| 513 (NAICS-3 parent) | 199 | 6,700 | 0.229 / 0.329 / 0.508 | 0.492 / 0.673 / 0.774 | -0.232 / 0.018 / 0.178 |

513 ≈ 513210 because 513210 dominates the count. NAICS-3 over-aggregation here is small in numerical terms but qualitatively wrong: book publishers are nothing like cloud-native software publishers.

### 3.4 513210 (Software Publishers) vs 519290 (Web Search Portals) — shared NAICS-2 51

| scope | firms | rows | cogs p25/p50/p75 | gm p25/p50/p75 | ebitda p25/p50/p75 |
|---|---:|---:|---|---|---|
| 513210 | 194 | 6,484 | 0.228 / 0.328 / 0.511 | 0.489 / 0.675 / 0.774 | -0.239 / 0.012 / 0.175 |
| 519290 | 27 | 921 | 0.206 / 0.337 / 0.464 | 0.536 / 0.663 / 0.795 | -0.198 / 0.057 / 0.195 |
| 51 (NAICS-2 parent) | 347 | 12,002 | 0.251 / 0.382 / 0.547 | 0.456 / 0.623 / 0.754 | -0.162 / 0.062 / 0.218 |

These two NAICS-6s have very similar bands (both ad-supported / SaaS-like cost structures). NAICS-2 is a few pp wider but not catastrophic. Both already resolve at NAICS-6.

### 3.5 513210 (Software Publishers) vs 516210 (Media Streaming / Telecom) — shared NAICS-2 51

| scope | firms | rows | cogs p25/p50/p75 | gm p25/p50/p75 | ebitda p25/p50/p75 |
|---|---:|---:|---|---|---|
| 513210 | 194 | 6,484 | 0.228 / 0.328 / 0.511 | 0.489 / 0.675 / 0.774 | -0.239 / 0.012 / 0.175 |
| 516210 | 32 | 1,067 | 0.190 / 0.346 / 0.571 | 0.429 / 0.655 / 0.810 | -0.150 / 0.034 / 0.206 |
| 51 (NAICS-2 parent) | 347 | 12,002 | 0.251 / 0.382 / 0.547 | 0.456 / 0.623 / 0.754 | -0.162 / 0.062 / 0.218 |

Both already resolve at NAICS-6. Cost structures are similar (subscription/ad-supported information services).

## 4. Threshold and hardcoded-fallback inventory

### 4.1 Effective firm-count / sample-size thresholds

| resolver | code path | rule | effective threshold |
|---|---|---|---|
| `cohort_band_resolver` (solver path) | [cohort_band_resolver.py:124-126, 483-484](python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L124-L126) | `n_used < 8 → return None (fall back to cascade)`. n_used = COUNT of metric rows with parsed-numeric value, NOT distinct firms. Tier thresholds: high ≥ 50, medium ≥ 20, low ≥ 8. | row-count ≥ 8 |
| `post_intake_industry_baseline_for_naics` cascade L6 (realism gate path) | [industry_baseline/lookup.py:319-337](python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L319-L337) | At L6, accept ONLY if `data_source = primary_source` AND `confidence_tier IN ('high','medium')`. Otherwise descend. | sample_size ≥ 10 (medium boundary on industry_metrics_raw rows). Implicit, not an explicit constant. |
| same cascade L5 / L4 / L3 / L2 | [industry_baseline/lookup.py:339-357](python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L339-L357) | Accept any row at the level (any data_source, any confidence tier). | none |

Both thresholds are **row count** based, not firm count. Average rows-per-firm in Alpha = 37.5; consequently a 2-firm NAICS-6 already exceeds the 10-row medium-tier threshold for the realism gate in almost every case.

Of 388 NAICS-6 codes in `industry_metrics_raw`:
- 252 have ≥ 2 firms (user's bar).
- **387 of 388 already resolve at L6** for `cogs_percent_of_revenue` with confidence high or medium (i.e., the cascade picks NAICS-6, not L5/L4/L3/L2).

### 4.2 Hardcoded primary_source fallbacks (per metric)

The L6 acceptance is gated on `data_source = primary_source`. Each realism hard-fail metric has its primary_source pinned in `post_intake_industry_metric_registry`:

| metric | primary_source | NAICS-6 codes that resolve at L6 (high/medium) | NAICS-6 with any L6 row | NAICS-5 codes covered | NAICS-3 codes covered |
|---|---|---:|---:|---:|---:|
| cogs_percent_of_revenue | industry_metrics_raw | 387 | 387 | 385 | 85 |
| gross_margin_percent | industry_metrics_raw | 387 | 387 | 385 | 85 |
| ebitda_margin | industry_metrics_raw | 387 | 387 | 306 | 81 |
| net_income_margin | industry_metrics_raw | 387 | 387 | 385 | 85 |
| sga_percent_of_revenue | industry_metrics_raw | 382 | 384 | 303 | 81 |
| capex_percent_of_revenue | industry_metrics_raw | 387 | 387 | 306 | 81 |
| current_ratio | industry_metrics_raw | 386 | 387 | 306 | 81 |
| debt_to_equity | industry_metrics_raw | 386 | 387 | 386 | 85 |
| debt_to_assets | industry_metrics_raw | 387 | 387 | 306 | 81 |
| ar_days_dso | industry_metrics_raw | 281 | 328 | 273 | 78 |
| ap_days_dpo | industry_metrics_raw | 311 | 335 | 274 | 80 |
| inventory_days | industry_metrics_raw | 210 | 272 | 232 | 78 |
| **marketing_percent_of_revenue** | **SEC_EDGAR** | **69** | 137 | 117 | 49 |
| **payroll_percent_of_revenue** | **derived_CBP_SOI** | **148** | 149 | 156 | 64 |
| **total_assets_to_revenue** | **IRS_SOI** | **166** | 202 | 197 | 79 |
| **owners_capital_percent_of_assets** | **IRS_SOI** | **167** | 203 | 198 | 79 |
| **distributions_percent_of_net_income** | **expert_default** | **0** | 0 | 0 | 0 |

**De facto hardcoded fallbacks (metrics that effectively never resolve at NAICS-6 because primary_source is sparse or generic):**

1. **`distributions_percent_of_net_income`** — primary_source is `expert_default`, which has 0 rows at NAICS-6 / 5 / 4 / 3 / 2 (only one row at L0 = `*`). This metric ALWAYS resolves at L0 (generic_default = 0.000 / 0.300 / 0.800), regardless of data availability for the NAICS. There ARE alpha_data and SEC_EDGAR rows at L6 for this metric (488510 has both, with sample_size 70 and 16) but the cascade rejects them because their data_source ≠ primary_source.

2. **`marketing_percent_of_revenue`** — primary_source is `SEC_EDGAR`, which itself only covers 69 of 388 NAICS-6 codes (because EDGAR firms tend to bundle marketing into SGA, with only a fraction breaking it out). The remaining 319 NAICS-6 codes fall through to L5 / L4 / L3 / L2.

3. **`payroll_percent_of_revenue` / `total_assets_to_revenue` / `owners_capital_percent_of_assets`** — primary_source is `derived_CBP_SOI` or `IRS_SOI`. These are public/industry-level rollups whose NAICS-6 coverage is partial: 148 / 166 / 167 of 388 codes resolve at L6 directly; the rest descend.

4. **`lease_percent_of_revenue` / `rent_percent_of_revenue` / `occupancy_total_percent_of_revenue`** (not in the audit's hard-fail list but adjacent) — primary_source is `expert_naics2_default` → only NAICS-2 rows exist (24 codes). These metrics always resolve at NAICS-2.

No code path explicitly hardcodes a NAICS level (e.g., "always use NAICS-3 for X"). The hardcoding is in the metric→primary_source map: when the primary_source is sparse, the L6-only rule combined with data_source enforcement produces the same effect.

### 4.3 What a `≥ 2 firms` rule would change

If the resolver lowered the L6 firm-count threshold to `firms ≥ 2` (the user's bar), the change would be:

- For Alpha-derived metrics (12 of 17 hard-fail metrics): essentially no change. 387 of 388 NAICS-6 codes already resolve at L6 with the current sample_size-based threshold.
- For SEC_EDGAR metrics (marketing, advertising): some additional NAICS-6 codes would resolve at L6 IF the L6 acceptance rule were also relaxed to allow `data_source IN (SEC_EDGAR, alpha_data, industry_metrics_raw)` rather than primary_source-only. Currently 488510 has alpha_data marketing rows at L6 with n=70 that the cascade rejects. (Caveat: marketing-as-component-of-SGA is the proxy used in `cohort_band_resolver`'s `LEVER_TO_METRIC_COLUMN` — so the data is conceptually a proxy.)
- For `distributions_percent_of_net_income`: changing to `firms ≥ 2` alone would do nothing. The alpha_data + SEC_EDGAR L6 rows are present but rejected by the primary_source rule. Either the primary_source assignment must change, OR the L6 rule must allow non-primary sources when no primary_source row exists.

## 5. NAICS-2 sample / parent-bucket sizes (for reference)

Total firms per NAICS-2 in Alpha:

```
NAICS-2  firms
22       19    (Utilities)
23       33    (Construction)
31       149   (Mfg part 1)
32       368   (Mfg part 2)
33       710   (Mfg part 3)
42       126   (Wholesale)
44       108   (Retail part 1)
45       38    (Retail part 2)
48       74    (Transportation)
49       28    (Warehousing/postal)
51       347   (Information — incl. software, telecom)
52       472   (Finance/Insurance)
53       219   (Real Estate)
54       422   (Professional/Scientific/Technical)
56       100   (Admin/Support)
61       33    (Educational Services)
62       111   (Health Care)
71       27    (Arts/Entertainment)
72       69    (Accommodation/Food)
81       29    (Other Services)
```

## 6. Two-stage EDGAR coverage expansion (executed 2026-05-09)

The audit above measured the cohort as it was on 2026-05-09. Subsequent
work expanded the cohort by classifying SEC filers that aren't in Alpha
and aggregating EDGAR concept facts into `industry_metrics_raw`.

### 6.1 Stage 1 — NAICS classification of EDGAR-only CIKs

Code: [python/data_pull/sic_to_naics_crosswalk.py](python/data_pull/sic_to_naics_crosswalk.py),
[python/data_pull/enrich_edgar_naics.py](python/data_pull/enrich_edgar_naics.py),
modifications to [python/data_pull/sec_edgar_xbrl_pull.py](python/data_pull/sec_edgar_xbrl_pull.py).

Premise correction: the original audit assumed EDGAR coverage was
constrained by an `alpha_match_naics_industry` filter inside the pull
script. It is not — `sec_edgar_xbrl_pull.py` already pulls the full
SEC universe via the Frames API. What `alpha_match` provided was NAICS
*classification*, not the CIK filter. Of the 6,994 distinct CIKs in
`sec_edgar_facts`, 3,773 had no ticker and therefore no NAICS — they
were unclassified rather than unpulled.

Approach:

1. Built a SIC → NAICS-6 canonical crosswalk covering all 309 SIC codes
   observed in `sec_edgar_facts` for ticker-less CIKs with rev+cost
   concepts. Source: Census Bureau 1997 SIC → 1997 NAICS Concordance,
   with 2022 NAICS revisions applied (511 → 513/516/519). When a SIC
   maps to multiple NAICS-6 codes, the crosswalk picks the canonical
   primary correspondence. Long-tail SICs not in the table fall back to
   a NAICS-2 fallback (`_SIC_2_TO_NAICS_2`, 20 entries).
2. Wrote `enrich_edgar_naics.py`: for each unmapped CIK with rev+cost
   concepts, hit `https://data.sec.gov/submissions/CIK{cik}.json` to
   fetch SIC, then UPDATE `sec_edgar_facts` to fill `naics_code` (and
   `ticker` when SEC has one we didn't).
3. Modified `sec_edgar_xbrl_pull.py`'s `build_cik_to_naics_map()` to
   apply the same SIC fallback on future pulls automatically.

Run results (1,946 CIKs, ~5 min at SEC's 7 req/sec):

| step | count |
|---|---:|
| Unmapped CIKs scanned | 1,946 |
| Resolved to NAICS-6 | **1,945** |
| No SIC in submissions | 1 |
| SICs missing in crosswalk | 0 |
| sec_edgar_facts rows updated | 184,109 |

EDGAR coverage in `sec_edgar_facts` after Stage 1:

| | pre-Stage-1 | post-Stage-1 | delta |
|---|---:|---:|---:|
| Distinct CIKs with NAICS-6 | 3,221 | 5,166 | +1,945 |
| EDGAR usable cohort firms (rev + cost concepts AND NAICS-6) | 2,547 | 4,492 | +1,945 |
| Distinct NAICS-6 codes covered | 352 | 450 | +98 |

### 6.2 Stage 2 — EDGAR aggregation into industry_metrics_raw

Code: [python/data_pull/edgar_data_growth_rates.py](python/data_pull/edgar_data_growth_rates.py)
(mirror of `alpha_data_growth_rates.py`).

Approach:
- Pivoted `sec_edgar_facts` rows from per-concept normalized form into
  `(cik, fp_end_at) → {concept: value}` buckets, picking the latest
  accession_number per concept when a period had amendments.
- Computed the same metric set as `alpha_data_growth_rates.py`:
  cogs_percent, gross_margin_q, ebitda_margin_q, sga_percent, dso, dpo,
  inventory_days, current_ratio, debt_to_equity, debt_to_assets,
  capex_percent_revenue, etc. (~24 derived ratios).
- Applied bounded sanity guards before insert: e.g.
  cogs_percent ∈ [0, 1.5], gross_margin_q ∈ [-1, 1], dso ∈ [0, 365].
  Out-of-range ratios are nulled (the row still inserts with valid
  columns); rows with non-positive total_revenue are dropped entirely.
- Added a `source` VARCHAR(10) NOT NULL DEFAULT 'alpha' column to
  `industry_metrics_raw` (idempotent; only added when missing).
- **Dedupe rule per directive**: Alpha-preferred. Only inserts EDGAR rows
  whose `(symbol, fiscalDateEnding)` is not already in
  `industry_metrics_raw`. Existing Alpha rows therefore "win" any
  overlap. EDGAR's contribution is firms (and quarters) Alpha doesn't
  track. For ticker-less EDGAR firms the symbol is `EDGAR_<cik_padded10>`.

Aggregation summary (2026-05-09):

| step | count |
|---|---:|
| EDGAR (cik, period) buckets pivoted | 35,156 |
| Rows dropped — non-positive revenue | 14,249 |
| Rows skipped — Alpha already has (symbol, fiscalDateEnding) | 11,590 |
| Rows inserted into industry_metrics_raw | **9,317** |
| Distinct new firms added | 3,083 |

Of the 3,083 newly-added EDGAR firms: 2,485 have real tickers (where
the ticker wasn't already in Alpha for any period), 598 are
`EDGAR_<cik>`-keyed because SEC has no ticker for that CIK.

### 6.3 Stage 3 — Coverage delta

`industry_metrics_raw` row counts by source (post-Stage-2):

| source | rows | distinct firms | distinct NAICS-6 |
|---|---:|---:|---:|
| alpha | 137,579 | 3,667 | 388 |
| edgar | 9,317 | 3,083 | 407 |

Delta in NAICS-6 coverage at each digit level (firm count `≥N`):

| digit | total NAICS pre→post | ≥2 firms pre→post (Δ) | ≥5 (Δ) | ≥8 (Δ) | ≥10 (Δ) | ≥20 (Δ) | ≥50 (Δ) |
|---|---|---|---|---|---|---|---|
| 6 | 388 → **473** (+85) | 252 → **335** (+83) | 132 → **194** (+62) | 92 → **131** (+39) | 80 → **110** (+30) | 41 → **62** (+21) | 10 → **20** (+10) |
| 5 | 307 → 367 (+60) | 220 → 278 (+58) | 119 → 166 (+47) | 83 → 116 (+33) | 70 → 98 (+28) | 43 → 58 (+15) | 14 → 22 (+8) |
| 4 | 213 → 232 (+19) | 177 → 199 (+22) | 109 → 150 (+41) | 84 → 114 (+30) | 71 → 97 (+26) | 45 → 62 (+17) | 16 → 23 (+7) |
| 3 | 82 → 85 (+3) | 75 → 81 (+6) | 68 → 72 (+4) | 59 → 65 (+6) | 55 → 63 (+8) | 39 → 49 (+10) | 15 → 25 (+10) |
| 2 | 24 → 24 | 24 → 24 | 23 → 23 | 23 → 23 | 22 → 22 | 20 → 22 (+2) | 18 → 19 (+1) |

Headline: **NAICS-6 codes meeting the ≥2-firm threshold went from 252 to 335 (+33%)**.
Codes meeting ≥5 went from 132 to 194 (+47%). The realism gate's de
facto threshold is sample_size ≥ 10 (medium tier); NAICS-6 codes
clearing that bar went from 80 to 110 (+38%).

### 6.4 ExpressLogix 488510 (Freight Transportation Arrangement)

| | pre | post |
|---|---:|---:|
| Distinct firms | 3 (CHRW, EXPD, HUBG) | **9** |
| Source breakdown post | — | 3 alpha + 6 EDGAR-only |

The 6 newly-added 488510 firms are ticker-less CIKs (3 EDGAR_<cik>-keyed)
plus 3 ticker'd firms (MGSD, NUTR, UNXP) that weren't in alpha_match. The
freight-brokerage cohort is now ~3× larger. Future cohort_band_resolver
queries against 488510 will draw from a deeper pool, with band stability
benefits visible at the next solver run.

### 6.5 Spot-check — NAICS-6 codes that were 1–2 firms in Alpha

Top expansions among NAICS-6 codes that Alpha barely covered:

| naics_6 | pre | post | delta | sector |
|---|---:|---:|---:|---|
| 523991 | 1 | 53 | +52 | Trust, Fiduciary, Custody |
| 211130 | 1 | 33 | +32 | Crude Petroleum Extraction |
| 111998 | 1 | 18 | +17 | Other Misc Crop Farming |
| 335312 | 1 | 6 | +5 | Motor & Generator Mfg |
| 336411 | 1 | 6 | +5 | Aircraft Mfg |
| 337122 | 1 | 6 | +5 | Non-upholstered Wood Household Furniture |
| 423310 | 1 | 6 | +5 | Lumber Wholesale |
| 423690 | 1 | 6 | +5 | Other Electronic Parts Wholesale |
| 325211 | 2 | 6 | +4 | Plastics Material & Resin Mfg |
| 334511 | 2 | 6 | +4 | Search/Detection/Navigation Mfg |
| 456110 | 2 | 6 | +4 | Pharmacies & Drug Stores |
| 811111 | 2 | 6 | +4 | General Auto Repair |

### 6.6 Newly-covered NAICS-6 codes (didn't exist in Alpha at all)

85 NAICS-6 codes are newly represented in `industry_metrics_raw`. Top
by firm count:

| naics_6 | firms | title |
|---|---:|---|
| 713990 | 24 | All Other Amusement and Recreation Industries |
| 454110 | 18 | Vending Machine Operators |
| 325411 | 18 | Medicinal and Botanical Manufacturing |
| 459990 | 17 | All Other Misc Store Retailers |
| 517919 | 14 | All Other Telecommunications |
| 523140 | 12 | Commodity Contracts Dealing |
| 333249 | 9 | Other Industrial Machinery Mfg |
| 522298 | 9 | All Other Nondepository Credit Intermediation |
| 334210 | 9 | Telephone Apparatus Manufacturing |
| 621399 | 8 | Offices of All Other Misc Health Practitioners |

### 6.7 Caveats

- **Cap_category for EDGAR-only firms is approximated from trailing 4Q
  revenue** (revenue < $250M → small, < $2B → mid, else large) since
  market_cap isn't in EDGAR. This may mis-sort firms whose enterprise
  value diverges from revenue scale. Acceptable for cohort resolution
  (cap_category gates cohort widening, not band computation).
- **EDGAR-derived ratios are not yet validated against Alpha-derived
  ratios on the same firm-quarter.** Per the directive's plan, the next
  step is a sanity check (cogs% within ±2pp on overlap firms) before
  considering flipping the dedupe preference to EDGAR.
- **Sanity guards null individual ratios but keep the row.** A row that
  passed revenue check but had an out-of-range debt_to_equity (say,
  because tse was near zero) will still contribute to other metrics'
  cohorts. This matches Alpha's behavior — the realism gate's per-metric
  cohort sums null values, not whole rows.
- **EDGAR pulls 4-8 quarters back by default** (`SEC_EDGAR_QUARTERS_BACK`
  env var). Alpha's history goes back to 2015. EDGAR's per-firm history
  in `industry_metrics_raw` is therefore shallower; the ~37 quarters/firm
  median for Alpha drops to ~3 quarters/firm for EDGAR-only rows. Deeper
  history would require expanding the Frames pull horizon.

## 7. Summary — what the data says about the freight-brokerage hypothesis

- The hypothesis was that 488510 is silently aggregating up to all-of-NAICS-488 trucking. **For the realism gate, this is not happening.** 488510 has 3 firms × ~15 quarters = 129 rows in Alpha. The `post_intake_industry_baseline_lookup` aggregates to 45 sample-size rows at L6 with confidence=high; the realism cascade picks NAICS-6 directly for cogs / gross_margin / ebitda / net_income / sga / capex / current_ratio / debt_to_equity / debt_to_assets / ap_days_dpo / inventory_days.
- The metrics where 488510 DOES fall through:
  - `marketing_percent_of_revenue` → falls through L6 (primary_source=SEC_EDGAR with only 5 EDGAR rows at L6=low) and lands at L5 with the same 5 rows of data. This is the "primary_source mismatch" failure mode, not over-aggregation.
  - `distributions_percent_of_net_income` → ALWAYS uses L0 generic default (0.000 / 0.300 / 0.800). Hardcoded by primary_source = `expert_default`.
- The threshold the resolver uses is **row count (sample_size) ≥ 10** for L6 medium-confidence acceptance, which corresponds to roughly `firms ≥ 1` for any NAICS-6 with a few quarters of history. The user's `firms ≥ 2` bar is already implicitly satisfied for 387 of 388 NAICS-6 codes for Alpha-derived metrics.
- The real coverage gaps are not threshold-related but source-availability-related: SEC_EDGAR coverage for marketing is sparse (69 of 388), and `expert_default` has zero NAICS-level data for distributions.
