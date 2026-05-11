# Phase 9 P3.8 — EDGAR period coverage parity (backfill report)

**Date:** 2026-05-11
**Subject:** Extend `industry_metrics_edgar` historical coverage to match `industry_metrics_alpha`'s time range. No schema changes. ADD-only writes (`INSERT IGNORE` on both staging and final tables).

---

## 1. Why

The cohort cascade in `post_intake_industry_baseline` walks between alpha and EDGAR sources at each NAICS level. Pre-backfill, EDGAR carried only ~2 years of data (the script's default `SEC_EDGAR_QUARTERS_BACK=8`) vs alpha's ~10.8 years. Any business where EDGAR resolved the cohort had a shallower historical sample than businesses where alpha resolved.

The objective: same historical depth in both sources, so the cascade's per-business cohort-fit is comparable regardless of which source matches.

---

## 2. Before / after

### 2.1 `industry_metrics_edgar`

| Field | Pre-backfill | Post-backfill | Δ |
|---|---:|---:|---:|
| Row count | 20,907 | **99,847** | +78,940 (4.78×) |
| Distinct fiscal-end-dates | 206 | **1,133** | +927 (5.50×) |
| Distinct symbols | 4,355 | **4,811** | +456 |
| Distinct NAICS-6 codes | 448 | **465** | +17 |
| Date range | 2024-05-24 → 2026-04-05 | **2015-05-29 → 2026-04-05** | +9 years backfilled |
| Avg rows per NAICS-6 | ~46.7 | **~214.7** | +168 rows/NAICS (4.60×) |

### 2.2 `industry_metrics_alpha` (unchanged, for comparison)

| Field | Value |
|---|---:|
| Row count | 137,579 |
| Distinct fiscal-end-dates | 137 |
| Distinct symbols | 3,667 |
| Distinct NAICS-6 codes | 388 |
| Date range | 2015-01-31 → 2025-11-30 |
| Avg rows per NAICS-6 | ~354.4 |

### 2.3 Coverage parity

- **Time range**: now matches. Both sources cover 2015 → 2025/2026. EDGAR's lower bound (2015-05) is ~4 months later than alpha's (2015-01), inherent to the SEC Frames calendar-quarter granularity vs alpha's monthly fiscal-end dates.
- **NAICS coverage**: EDGAR now spans 465 NAICS-6 codes (vs alpha's 388). EDGAR is broader because the CIK→NAICS map cascades from alpha_match → SIC→NAICS crosswalk, picking up small-cap and historical filers alpha doesn't cover.
- **Per-NAICS depth**: EDGAR averages 215 rows/NAICS, alpha 354. Alpha is still denser per NAICS because its monthly cadence is finer-grained than EDGAR's quarterly-fiscal-end pattern. For cohort-resolver purposes, both now provide sufficient sample sizes at every NAICS level — the cascade no longer trips on EDGAR's shallow tail.

### 2.4 Year-by-year backfill distribution

```
year   edgar    alpha
----   -----    -----
2015   3,046   10,307
2016   4,663   10,691
2017   8,188   11,099
2018   9,292   11,535
2019   9,529   12,168
2020   9,776   13,348
2021   9,627   13,928
2022   9,908   14,291
2023  10,343   14,562
2024  11,860   14,650
2025  11,316   11,000
2026   2,299        0   (alpha had not yet pulled 2026 monthly closes)
```

EDGAR is denser than alpha in 2026 (alpha hadn't ingested current-year monthly closes). Alpha remains denser in 2015-2023, especially the earliest years where EDGAR's SEC Frames API was less comprehensive for small filers.

---

## 3. Pipeline used

Both scripts were re-run unmodified. Behavior is INSERT-IGNORE on a uniqueness constraint, so existing rows are preserved and only new (cik, fiscal_period, accession_number) combinations are inserted.

### 3.1 Stage 1: SEC Frames API → `sec_edgar_facts`

Script: `python/data_pull/sec_edgar_xbrl_pull.py`

Invocation:
```bash
SEC_EDGAR_QUARTERS_BACK=44 python python/data_pull/sec_edgar_xbrl_pull.py
```

Pulled the last 44 calendar quarters (2015 Q2 through 2026 Q1) for 49 concepts × 6,391 CIKs.

| `sec_edgar_facts` field | Pre | Post |
|---|---:|---:|
| Row count | 644,812 | **4,280,585** (6.64×) |
| Distinct CIKs | 6,994 | **12,569** |
| Distinct concepts | 49 | 49 |
| Date range | 2024-05-19 → 2026-04-05 | **2015-05-18 → 2026-04-05** |

Run summary (from `/tmp/edgar_backfill.log`):
```
Done. Seen=4,249,347, inserted=3,635,773.
```

Wall-clock: ~70 minutes. CIK→NAICS submissions API was the bulk of the time (single-pass over 6,391 CIKs at ~7 req/s respecting SEC rate limits).

### 3.2 Stage 2: aggregate `sec_edgar_facts` → `industry_metrics_edgar`

Script: `python/data_pull/edgar_data_growth_rates.py`

Invocation:
```bash
python python/data_pull/edgar_data_growth_rates.py
```

Aggregator pivots `sec_edgar_facts` by `(cik, fp_end_at)`, computes ratios, and `INSERT IGNORE`s into `industry_metrics_edgar`. No data lost; existing 20,907 rows kept; 78,940 new rows added.

Run summary (from `/tmp/edgar_aggregator.log`):
```
Inserted (rowcount): 78940
```

Wall-clock: ~3 minutes.

---

## 4. Discipline notes

- **No schema changes.** Both tables retain their pre-existing column lists. The SQL writes were the script's existing `INSERT IGNORE` statements; no manual schema-touching.
- **No DELETEs / DROPs.** Existing rows untouched. The 20,907 pre-existing EDGAR aggregate rows + 644,812 pre-existing facts staging rows are all still present.
- **Source-of-truth idempotency.** The SEC Frames API + `INSERT IGNORE` on `(cik, concept, fiscal_period, accession_number)` makes both scripts safe to re-run. Future incremental pulls (e.g. weekly) will only add new rows.
- **Re-runnable.** Both scripts are now part of the data-pipeline maintenance toolkit. To refresh: re-run Stage 1 with whatever `SEC_EDGAR_QUARTERS_BACK` is desired (currently 44 = ~11 years), then Stage 2.

---

## 5. Implications for findings 1 and 2

The remaining Phase 9 P3.7 findings — Inventory Days at 35 days for NAICS 51 software, EBITDA decline Q11→Q20 driven by NAICS 51 cohort target of -0.5% — should be re-evaluated against the new cohort depth. Likely outcomes:

- **Cohort target shifts.** NAICS 51 cohort EBITDA target was -0.5% on the pre-backfill data. With 4.7× more rows (most of them added from older periods 2015-2020 when traditional publishers dominated), the target may shift in either direction — older data could pull it more negative (publishing era losses), or modern SaaS firms that filed for the full 2015-2020 window could pull it more positive. To be measured empirically.
- **Cohort confidence tier shifts.** Sample sizes at L4 (4-digit NAICS) and L5 (5-digit NAICS) likely improve materially, which means the cascade resolves at deeper levels (closer to the actual sub-industry) with higher confidence. NexGen's NAICS 513210 cohort should now resolve at L4 or L5 instead of falling back to L3 = "all Information sector."

These are claims to verify in a follow-up empirical check. This document only certifies the data parity; downstream impact on findings 1 / 2 is a separate measurement.
