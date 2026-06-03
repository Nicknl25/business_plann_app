# Cohort Data Sourcing — Alpha vs EDGAR vs Both: Options

**Status:** research + options. No code, no implementation. Companion to
[fix_1_viability_metrics_research.md](fix_1_viability_metrics_research.md) — that doc
centered the viability framework's cohort grounding on the legacy Alpha table; this doc maps
the **full** sourcing picture (current state **and** build options) so the framework isn't
needlessly locked to one source.

**Convention.** Code claims `file:line`. **Data counts are from a live read-only query against
`industry_metrics_alpha` / `industry_metrics_edgar` on 2026-06-02** (stated inline; re-run the
query to refresh — exact queries reproduced in the appendix). Finance concepts labeled
*(general knowledge)*.

---

## 0. Headline

> EDGAR is the **broader** universe (more firms, more NAICS codes, clears the ≥2-firm band
> gate in more buckets, more recent). Alpha has the **deeper per-firm history** and richer
> coverage on several profitability/coverage metrics. **The existing cohort resolver already
> combines them** via an alternating EDGAR→Alpha walk nested inside the NAICS-depth cascade —
> a proven, de-dup-safe pattern the viability framework can reuse as-is. The biggest untapped
> gain is **per-metric source selection** (each source is stronger on different ratios), not
> raw union (which double-counts ~2,983 shared firms).

---

## 1. EDGAR vs ALPHA — head-to-head (live counts, 2026-06-02)

| Dimension | `industry_metrics_alpha` | `industry_metrics_edgar` | Winner |
|---|---|---|---|
| Total rows (firm-quarters) | **137,579** | 99,847 | Alpha |
| Distinct firms | 3,667 | **4,811** (+31%) | EDGAR |
| Distinct NAICS-6 codes | 388 | **465** (+77) | EDGAR |
| NAICS depth stored | 6-digit (all rows) | 6-digit (all rows) | tie |
| Avg firm-quarters / firm | **~37.5** | ~20.8 | Alpha (deeper history) |
| Period min → max | 2015-01-31 → 2025-11-30 | 2015-05-29 → **2026-04-05** | EDGAR (more recent) |
| NAICS-6 buckets with **≥2 firms** | 253 | **323** | EDGAR |
| NAICS-3 buckets with ≥2 firms | 76 | **82** | EDGAR |

Both tables share an identical ratio schema (DDLs:
[alpha_data_growth_rates.py:47-93](../../python/data_pull/alpha_data_growth_rates.py#L47-L93),
[edgar_data_growth_rates.py:109-150](../../python/data_pull/edgar_data_growth_rates.py#L109-L150)):
growth, 5 margins, expense ratios, working-capital days + CCC, liquidity (current/quick),
leverage/coverage (D/E, D/A, D/EBITDA, interest coverage), capex/depreciation %, ROA/ROE, and
the P3 working-capital-structure columns. **Neither carries a column the other lacks** — the
difference is *fill density per column*, not schema.

**Per-metric coverage is complementary (firms with a non-null value, 2026-06-02):**

| Metric column | Alpha firms | EDGAR firms | Richer source |
|---|---|---|---|
| `ebitda_margin_q` | **3,594** | 2,659 | Alpha |
| `interest_coverage` | **3,605** | 2,570 | Alpha |
| `debt_to_ebitda` | **3,381** | 3,008 | Alpha |
| `roe` | 3,666 | **4,537** | EDGAR |

So "which source is better" is **metric-dependent**: Alpha dominates EBITDA-margin / interest
coverage / debt-to-EBITDA; EDGAR dominates returns (ROE) and the overall firm + NAICS breadth.
This complementarity is the single most actionable finding for the viability framework
(§5–6).

**Does EDGAR give better coverage than Alpha?** For **breadth** (firms, NAICS codes, deep
peer-sets that clear the ≥2-firm gate, recency): **yes, clearly** — and the resolver comment
states the design rationale: EDGAR is the "broader SIC-classified universe; ~3K extra firms
beyond the Alpha SEC-listed set" ([cohort_band_resolver.py:120-122](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L120-L122)).
For **per-firm history depth** and **specific profitability/coverage metrics**: Alpha wins.
Neither dominates outright — which is exactly why the resolver uses both.

---

## 2. COMBINING THEM

### 2.1 Coverage fill
- **NAICS-6 buckets clearing the ≥2-firm gate:** Alpha 253, EDGAR 323, **union 344**.
  Combining adds only **+21 over EDGAR-alone** (but +91 over Alpha-alone) at NAICS-6 — the
  union gain is modest *at the deepest level* because the two universes overlap heavily, but
  EDGAR-alone already beats Alpha-alone substantially. Where one source's NAICS-6 bucket is a
  singleton, the other frequently fills it, pushing the bucket over the gate.
- **Per-metric fill:** §1's table shows each source rescues the other on different metrics
  (Alpha for EBITDA margin / coverage, EDGAR for ROE) — the highest-value form of "fill."

### 2.2 De-dup / reconciliation — the real risk in a naive union
- **2,983 firms appear in BOTH tables under the same exact ticker symbol** (live query,
  2026-06-02) — ~81% of Alpha's 3,667 firms are also in EDGAR. A naive `UNION ALL` pool would
  **double-count** these firms, biasing percentiles toward the over-represented overlap set and
  corrupting the ≥2-firm gate (one real firm counted as two).
- EDGAR additionally carries **599 firms under `EDGAR_<cik>` synthetic symbols**
  (no ticker; e.g. `EDGAR_0000002178`) — these never collide with Alpha tickers, so the
  non-overlap EDGAR contribution is genuine net-new.
- **Definition/unit differences** *(general knowledge + table-level)*: Alpha and EDGAR compute
  the same ratio columns from different raw feeds (Alpha API financials vs SEC XBRL concepts
  pivoted in [edgar_data_growth_rates.py:253-289](../../python/data_pull/edgar_data_growth_rates.py#L253-L289),
  with concept-fallback chains for reporting variance and sanity-bound nulling at
  [edgar_data_growth_rates.py:206-235](../../python/data_pull/edgar_data_growth_rates.py#L206-L235)).
  For an overlapping firm-quarter the two can disagree on the same ratio. Any true union must
  pick a per-(firm, period) winner or accept the discrepancy.

### 2.3 The key implication
Naive union is the **worst** combine option: it imports the de-dup bias for little NAICS-6 gain.
The valuable combinations are (a) **toggle/fallback** — take a whole band from one source (no
pooling, no de-dup problem), and (b) **per-metric source preference** — choose the
higher-fill source per ratio. The existing resolver already does (a); (b) is the build
opportunity.

---

## 3. THE EXISTING ALPHA↔EDGAR TOGGLE (the proven pattern — item 3)

**Found it.** It is the live cohort band resolver: `resolve_cohort_band`
([cohort_band_resolver.py:544-577](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L544-L577)).

**Source list:** `_COHORT_TABLES = (("edgar", "industry_metrics_edgar"), ("alpha", "industry_metrics_alpha"))`
— [cohort_band_resolver.py:126-128](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L126-L128).

**How it picks / falls back** (the docstring spells out the walk,
[:550-563](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L550-L563)):
- Outer loop over NAICS levels 6→5→4→3→2 ([:608](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L608),
  ladder at [:138](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L138)).
- Inner loop over sources **EDGAR then Alpha** at each level ([:612](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L612)).
- Within each (level, source) it widens revenue window then date window
  ([:600-616](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L600-L616);
  ladders at [:133-137](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L133-L137)).
- Accepts the **FIRST** (level, source, window) combo with **≥2 distinct firms** carrying a
  non-null value for that metric column ([_try_cohort_at_filter:496-536](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L496-L536),
  gate `_COHORT_FIRM_MIN = 2` at [:130](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L130)).
- Rationale encoded in the docstring: "an EDGAR NAICS-5 cohort is more relevant than an Alpha
  NAICS-2 cohort" ([:562-563](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L562-L563))
  — i.e. NAICS depth dominates source identity in the priority order.

**De-dup safety:** because each band is taken from **exactly one (level, source) bucket**
([_try_cohort_at_filter](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L496-L536)),
the resolver **never pools both tables into one percentile computation** — so the 2,983-firm
overlap (§2.2) is structurally avoided. This is a major point in the pattern's favor.

**Provenance:** the chosen table, NAICS level, firm_count, and confidence tier are tagged on the
`CohortBandResult` and materialized into `post_intake_cohort_bands`
([cohort_bands_table.py:33-59](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L33-L59),
columns `cohort_table`, `naics_level_used`, `firm_count`, `cohort_query`).

**Reusable for the viability framework?** **Yes, directly.** It already returns a metric's
percentile band keyed on `(metric_key, business_profile{naics_6, target_annual_revenue,
stage})` ([:544-594](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L544-L594)).
The viability scorecard (companion doc §6) needs exactly this — a cohort percentile band per
metric — so the framework can call the same resolver rather than re-grounding on a single
table. Its **one limitation** for viability use: it picks the first source that clears the gate
**per band**, optimizing for *coverage*, not for the source with the *best fill / most firms*
for that metric — see §5 Option D.

---

## 4. NAICS FALLBACK CASCADE × SOURCE SELECTION

The two are **already layered**: source toggle is nested *inside* the NAICS-depth cascade.
- NAICS ladder 6→5→4→3→2 — [cohort_band_resolver.py:138](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L138),
  driven at [:608](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L608).
- Source toggle EDGAR→Alpha *within each level* — [:612](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L612).
- Net priority: **NAICS depth first, source second** — an EDGAR-or-Alpha NAICS-6 band beats any
  NAICS-5 band; within a level EDGAR is tried before Alpha.
- A separate **static baseline cascade** (`post_intake_industry_baseline_lookup`,
  [load_industry_baseline_lookup.py:44-77](../../scripts/load_industry_baseline_lookup.py#L44-L77))
  provides 6→5→4→3→2→generic_default bands with confidence downgrading as a final fallback when
  the live cohort walk finds no qualifying bucket at any level/source.

So "layer source-toggle + NAICS-cascade for maximum coverage" is **already the implemented
design**. The open question is only the *ordering policy* (depth-first vs fill-first vs
per-metric) and whether to add a per-metric source preference — §5.

---

## 5. ALL OPTIONS (full menu — current state and build)

| # | Option | Coverage / robustness gain | Use-as-is or build | Tradeoffs |
|---|---|---|---|---|
| **A** | **Alpha-only** | Deepest per-firm history (37.5 q/firm); best fill on EBITDA margin / interest coverage / D-EBITDA. But fewest firms (3,667), fewest NAICS-6 codes (388), only 253 NAICS-6 buckets clear the ≥2 gate; data ends 2025-11. | Use-as-is | Narrowest breadth; many NAICS-6 fall to NAICS-3/2 bands (less specific). Weak on ROE. The companion doc's current grounding. |
| **B** | **EDGAR-only** | Broadest universe (4,811 firms, 465 NAICS codes, 323 NAICS-6 buckets ≥2, most recent to 2026-04); best ROE fill. | Use-as-is (swap table) | Shallower per-firm history; weaker on EBITDA margin / coverage metrics; 599 firms are CIK-only (fine, just no ticker). |
| **C** | **Both — naive union (pool rows)** | Union NAICS-6 ≥2 buckets = 344 (+21 vs EDGAR). | Build | **Worst option:** double-counts 2,983 overlapping firms → biased percentiles, corrupted ≥2 gate; needs (firm,period) de-dup + ratio reconciliation. Small NAICS-6 gain for large bias risk. |
| **D (existing)** | **Both — toggle/fallback (the §3 resolver)** | EDGAR→Alpha within each NAICS level, first bucket ≥2 firms wins; de-dup-safe (one source per band). Effectively EDGAR-breadth with Alpha as per-band backstop. | **Use-as-is** | Picks first-to-clear-gate, not best-fill; a thin EDGAR-6 bucket (2 firms) is taken over a rich Alpha-6 bucket (50 firms). Coverage-optimal, not quality-optimal. |
| **E** | **Both — toggle + NAICS cascade + per-metric source preference** | D, but per metric choose the source with higher fill / firm count for that ratio (Alpha for EBITDA margin & coverage; EDGAR for ROE & breadth). Best of both per §1 complementarity. | Build (small — a per-metric source-order map layered on D) | Adds a per-metric policy table to maintain; must define tie-breaks (depth vs fill). Highest robustness for the *specific* metrics the viability standard uses. |
| **F** | **Recompute additional metrics from raw upstream line items** | EDGAR raw XBRL persists in `sec_edgar_facts` ([sec_edgar_xbrl_pull.py:118-142](../../python/data_pull/sec_edgar_xbrl_pull.py#L118-L142)); the ratio tables discard raw lines after computing ratios. Recomputing from raw enables peer bands for metrics the cohort lacks today — **FCF margin, cash conversion, ROIC** (companion doc §2 gaps). | Build (larger — extend ingest to compute + persist new columns; backfill) | Alpha raw retention unclear (ratios computed at ingest, [alpha_data_growth_rates.py:268-350]); EDGAR raw is available in `sec_edgar_facts`. Effort: new columns + recompute both feeds + backfill. Unlocks net-new viability metrics, not just better fill of existing ones. |

---

## 6. RECOMMENDATION — cohort grounding for the viability framework

**Ground the viability framework on the existing resolver (Option D), and invest in Option E
(per-metric source preference) for the handful of metrics the viability standard actually
scores.** Concretely:

1. **Reuse `resolve_cohort_band` as the cohort-grounding entry point** (§3,
   [cohort_band_resolver.py:544](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L544)).
   Do **not** re-ground the framework on Alpha-only — that was a legacy artifact, and §1 shows
   it is the *narrowest* breadth option. The resolver already returns exactly the per-metric,
   NAICS-and-stage-conditioned percentile band the scorecard needs, with provenance, and is
   de-dup-safe.
2. **Layer per-metric source preference (Option E)** for the scorecard's metrics, using §1's
   complementarity: prefer **Alpha** for EBITDA margin, interest coverage, debt-to-EBITDA;
   prefer **EDGAR** for ROE and for any metric where EDGAR's broader universe yields a
   deeper qualifying NAICS-6 bucket. This keeps EDGAR's breadth advantage while recovering
   Alpha's metric-specific depth — addressing D's "first-to-clear, not best-fill" limitation.
3. **Reject naive union (Option C):** the 2,983-firm overlap makes pooled percentiles unsafe
   for little NAICS-6 gain; the toggle already captures the union's coverage benefit without
   the bias.
4. **Scope Option F as a follow-on, not a blocker:** if the viability standard wants peer bands
   for FCF margin / cash conversion / ROIC (companion doc §2 flagged these as firm-computable
   but cohort-bandless), recompute them from `sec_edgar_facts` raw XBRL. This is the only path
   to benchmarking those metrics, but it is an ingest build — sequence it after the level/
   trajectory scorecard ships on the metrics that already have bands.
5. **Keep the static NAICS baseline cascade as the final fallback** (§4,
   [load_industry_baseline_lookup.py:44-77](../../scripts/load_industry_baseline_lookup.py#L44-L77))
   so a metric with no qualifying live cohort at any level/source still resolves to a band
   rather than going un-scored.

**Net:** the framework should be grounded on **EDGAR-breadth-first with Alpha as a per-metric
depth source (D + E)**, the static baseline as backstop, and an optional raw-recompute build
(F) to extend the benchmarkable metric set — never on Alpha alone, and never on a naive union.

---

## Appendix — reproduce the data counts

Live read-only queries against the project DB (`get_mysql_connection`,
[intake_submission](../../python/client_intake_and_finmo/intake_submission.py#L41-L52)),
run 2026-06-02. Re-run to refresh:
- Totals: `SELECT COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT naics_code), MIN(fiscalDateEnding), MAX(fiscalDateEnding) FROM industry_metrics_{alpha|edgar}`
- NAICS-6 buckets ≥2 firms: `SELECT COUNT(*) FROM (SELECT LEFT(naics_code,6) n6, COUNT(DISTINCT symbol) f FROM <t> GROUP BY n6 HAVING f>=2) x`
- Symbol overlap: `SELECT COUNT(*) FROM (SELECT DISTINCT symbol FROM industry_metrics_alpha) a JOIN (SELECT DISTINCT symbol FROM industry_metrics_edgar) e ON a.symbol=e.symbol`
- Per-metric fill: `SELECT COUNT(DISTINCT symbol) FROM <t> WHERE <metric_col> IS NOT NULL`

Results captured above: Alpha 137,579 rows / 3,667 firms / 388 NAICS-6 / 2015-01→2025-11;
EDGAR 99,847 rows / 4,811 firms / 465 NAICS-6 / 2015-05→2026-04; symbol overlap 2,983;
EDGAR CIK-only symbols 599; union NAICS-6 ≥2 = 344.
