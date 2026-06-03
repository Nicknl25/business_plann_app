# Cohort Bar Calibration Check — live data read

**Status:** findings note. Live read via `resolve_cohort_band` (the exact path the viability
standard will use) on 2026-06-02. **No code, no standard changes.** Purpose: see where the public
cohort's operating-economics band actually sits for SMB-heavy industries, to calibrate the Tier-1
convergence percentile against reality.

Sunny's NAICS is **311811 (Retail Bakeries)** — pulled from the fixture, not guessed:
`structured.operating_model_json.business_naics_6 = 311811`
([Test Files/intake_bypass_baselines/sunny_glaze_donuts.json](../../Test%20Files/intake_bypass_baselines/sunny_glaze_donuts.json)).

---

## EBITDA-margin band (from `resolve_cohort_band`, metric `ebitda_margin_q`)

| NAICS | Industry | p25 | p50 | p75 | resolved level | source | firms | rows |
|---|---|---|---|---|---|---|---|---|
| **311811** | Retail Bakeries *(Sunny)* | **−4.3%** | **4.6%** | **10.3%** | **L3** (cascaded up from 6) | edgar | 28 | 298 |
| 722511 | Full-Service Restaurants | −23.1% | 5.8% | 15.8% | L6 (direct) | edgar | 18 | 209 |
| 722513 | Limited-Service Restaurants | 4.5% | 11.2% | 17.7% | L6 (direct) | edgar | 10 | 122 |
| 812112 | Beauty Salons | −6.9% | 1.1% | 5.8% | L4 (cascaded) | edgar | **2** ⚠ | 8 |
| 448140 | Family Clothing Stores | −6.4% | 4.1% | 9.7% | **L2** (cascaded way up) | edgar | 30 | 337 |

Coverage caveats: only the two restaurant codes resolve to a **true NAICS-6** band. Sunny's
bakery band is cascaded to **L3** (broad food-mfg, not bakeries specifically); clothing falls all
the way to **L2** (all of retail); **salons sit on just 2 firms** — right at the `_COHORT_FIRM_MIN`
gate, statistically fragile.

## Rule-of-40 growth component (`revenue_growth_q`)

**The resolver returned NO BAND for `revenue_growth_q` on every code** — it is **not registered**
in `_KNOWN_METRIC_COLUMNS`, so `resolve_cohort_band` exits with `None`
([cohort_band_resolver.py:583](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L583)).
This is a real coverage gap for the Rule-of-40 growth term — the column exists in the tables
(`revenue_growth_q`, [alpha_data_growth_rates.py:55](../../python/data_pull/alpha_data_growth_rates.py#L55))
but the resolver can't surface it without registration. Direct-query percentiles below for
context **(supplementary — NOT via the resolver; QoQ, point-in-time):**

| NAICS prefix | p25 | p50 | p75 | n |
|---|---|---|---|---|
| 311 (bakery, L3) | −4.7% | 2.0% | 9.3% | 739 |
| 722511 (FSR) | −4.9% | 2.2% | 9.5% | 352 |
| 722513 (LSR) | −2.8% | 1.4% | 7.1% | 214 |
| 8121 (salons, L4) | −7.9% | −4.2% | 2.6% | 57 |
| 44 (retail, L2) | −5.1% | 1.7% | 10.5% | 859 |

QoQ revenue growth p50 is low single-digit (~1–2%) across SMB-heavy codes; salons net negative.

---

## Calibration read (where would a realistic 8–15% EBITDA-margin operator land?)

- Against Sunny's **Retail Bakeries** band (p50 4.6% / p75 10.3%), an 8–15% operator lands **around
  p50–p75 and above** — i.e. a genuinely profitable single-location bakery looks **strong**, not
  weak, versus the public cohort. Same picture for restaurants (FSR p50 5.8/p75 15.8) and retail
  (p50 4.1/p75 9.7); against salons (p75 only 5.8%) an 8–15% operator is **above p75**.
- **So p25-clear / p50-strong is comfortably reachable for a real profitable SMB — if anything the
  bar is generous, not harsh.** The public **p25 floor is frequently negative** (bakeries −4.3%,
  restaurants −23%, salons/clothing ≈ −6%) because public small-/micro-cap filers in these codes
  carry losses and roll-up write-offs; the risk is the band being **too lenient at the bottom**, not
  too strict. No lower anchor is needed; the live numbers support **p25-clear, p50-full-credit**.
- **Watch coverage, not the bar:** weight calibration toward the well-covered L6 codes (restaurants);
  treat cascaded/thin bands (bakery L3, clothing L2, salons n=2) as low-confidence and lean on the
  resolver's existing `confidence_tier` / `firm_count` when these are the resolved source.

---

## Queries reproduced
- EBITDA band (per NAICS): `resolve_cohort_band(metric_key='ebitda_margin_q', business_profile={'naics_6': <code>, 'target_annual_revenue': 1500000, 'stage':'operational'}, metric_column_override='ebitda_margin_q')` → `.to_dict()` `benchmark_min/target/max`, `naics_level_used`, `cohort_table`, `firm_count`, `cohort_size`.
- Growth (supplementary, direct): `SELECT revenue_growth_q FROM industry_metrics_edgar WHERE naics_code LIKE '<prefix>%' AND revenue_growth_q IS NOT NULL AND fiscalDateEnding>='2019-01-01'`, percentiles computed p25/p50/p75.
- All values live as of 2026-06-02; `.env` loaded read-only for the DB connection. No tables modified.
