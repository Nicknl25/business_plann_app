# Fix #1 — Viability Metrics: Research + Recommendation (no code)

**Status:** research + recommendation. No code, no implementation. Positions us to
*decide* which metrics define firm viability.

**Scope.** Fix #1 = the viability + trajectory of the **whole firm**. This doc decides the
viability **standard** — the metrics, their normalization against the cohort, and how
trajectory expresses them. The manager / executor / adaptation cascade that *achieves*
viability is a separate later build and is **out of scope** here. Prior shortlists
(margins / profit / growth / FCF) were examples, not the menu.

**Convention.** Code/data claims are grounded `file:line`. Finance concepts are labeled
*(general knowledge)*.

---

## 1. RAW MATERIAL — what we actually have

The hard rule: confirm the raw material before theorizing. The headline:

> **The FIRM gives us full, raw 3-statement detail per quarter (Q1–Q20).
> The COHORT gives us precomputed ratios only (no raw line items), expressed as
> NAICS-and-stage-conditioned percentile bands.**

This asymmetry is the single most important fact for the recommendation: **we can compute
any ratio for the firm, but we can only *benchmark* a ratio the cohort tables also carry.**

### 1.1 THE FIRM — all three statements, per quarter, computable

The per-quarter row is the `FinmoQuarterResult` dataclass —
[finmo_model.py:145-220](../../python/financial_model_engine/finmo_model.py#L145-L220) —
emitted into `finmo_json.quarter_rows` at
[finmo_bridge.py:886-908](../../python/client_intake_and_finmo/finmo_bridge.py#L886-L908).
Horizon = **20 quarters**, [model_inputs.py:8](../../python/financial_model_engine/model_inputs.py#L8)
(`QUARTER_COUNT = 20`); `quarter_index` 1–20 live, 0 = opening stub
([finmo_model.py:147](../../python/financial_model_engine/finmo_model.py#L147)).

All three statements are buildable per quarter:

**Income statement** — `revenue`, `cost_of_goods_sold`, `gross_profit`, `payroll`,
`marketing`, `research_and_development`, `lease_rent`, `general_and_administrative`,
`ebitda`, `interest`, `depreciation`, `taxes`, `net_income`
([finmo_model.py:153-165](../../python/financial_model_engine/finmo_model.py#L153-L165)),
plus interest/depreciation splits ([finmo_model.py:214-217](../../python/financial_model_engine/finmo_model.py#L214-L217)).

**Balance sheet** — `cash`/`ending_cash`, `accounts_receivable`, `inventory`,
`prepaid_expenses`, `current_assets`, `ppe`, `accumulated_depreciation`,
`right_of_use_asset`, `total_assets`, `accounts_payable`, `short_term_debt`,
`deferred_revenue`, `current_liabilities`, `long_term_debt`, `capital_lease_obligation`,
`total_liabilities`, `owners_capital`, `retained_earnings`, `distributions`,
`other_equity`, `total_equity`, `total_liabilities_and_equity`, with an
`accounting_equation_check` tie-out
([finmo_model.py:152, 166-185, 219-220](../../python/financial_model_engine/finmo_model.py#L166-L185)).

**Cash flow statement** — `beginning_cash`, `changes_in_current_assets`,
`changes_in_current_liabilities`, `operating_cash_flow`, `capital_expenditures`,
`investing_cash_flow`, `debt_issuance`, `debt_repayment`, `equity`, `owner_distributions`,
`financing_cash_flow`, `net_cash_flow`, `ending_cash`
([finmo_model.py:186-204](../../python/financial_model_engine/finmo_model.py#L186-L204)).

**Free cash flow is derivable, not stored as a field** *(general knowledge: FCF = operating
cash flow − capex)*: both inputs exist —
`operating_cash_flow` ([finmo_model.py:189](../../python/financial_model_engine/finmo_model.py#L189))
and `capital_expenditures` / `investing_cash_flow`
([finmo_model.py:190-191](../../python/financial_model_engine/finmo_model.py#L190-L191)).

**Implication:** for the firm, the *entire* ratio/trajectory universe in §2 is computable
per quarter — margins, returns, leverage, coverage, liquidity, efficiency, cash
generation. The only things missing are market/valuation inputs (no share price for a
private firm).

### 1.2 THE COHORT — precomputed ratios, percentile bands, NAICS+stage conditioned

Two cohort fact tables, **identical ratio schema**, one row per firm-quarter:
- `industry_metrics_alpha` (Alpha Vantage) — DDL [alpha_data_growth_rates.py:47-93](../../python/data_pull/alpha_data_growth_rates.py#L47-L93).
- `industry_metrics_edgar` (SEC EDGAR XBRL) — DDL [edgar_data_growth_rates.py:109-150](../../python/data_pull/edgar_data_growth_rates.py#L109-L150);
  raw XBRL pulled to `sec_edgar_facts` ([sec_edgar_xbrl_pull.py:118-142](../../python/data_pull/sec_edgar_xbrl_pull.py#L118-L142))
  then pivoted to ratios ([edgar_data_growth_rates.py:253-289](../../python/data_pull/edgar_data_growth_rates.py#L253-L289)).

**Critical: the cohort tables store RATIOS, not raw statements.** The only raw line item
persisted is `total_revenue` ([alpha_data_growth_rates.py:54](../../python/data_pull/alpha_data_growth_rates.py#L54)).
Everything else is a precomputed ratio
([alpha_data_growth_rates.py:55-90](../../python/data_pull/alpha_data_growth_rates.py#L55-L90)):

| Cohort ratio family | Columns |
|---|---|
| Growth | `revenue_growth_q` |
| Margins | `gross_margin_q`, `operating_margin_q`, `ebit_margin_q`, `ebitda_margin_q`, `net_margin_q` |
| Expense ratios | `sga_percent`, `rnd_percent`, `cogs_percent` |
| Working-capital efficiency | `dso`, `dpo`, `inventory_days`, `ccc` |
| Liquidity | `current_ratio`, `quick_ratio` |
| Leverage / coverage | `debt_to_equity`, `debt_to_assets`, `debt_to_ebitda`, `interest_coverage` |
| Investment | `capex_percent_revenue`, `depreciation_percent_revenue` |
| Returns | `roa`, `roe` |
| WC structure (P3) | `current_assets_minus_cash_to_revenue`, `current_liabilities_to_revenue` |
| Classifiers | `market_cap`, `cap_category`, `naics_code`, `fiscalDateEnding` |

**Consequence of "ratios not line items":** we can benchmark the firm on any metric in this
list, and **only** these. A ratio the firm can compute but the cohort doesn't carry (e.g.
ROIC, FCF-conversion) has **no peer band** unless it is added to the ingest pipeline. This
bounds the real possibility space.

**Bands are percentiles, gated on firm count.** At runtime the cohort resolver computes
**p25 / p50 / p75** for the matched cohort —
[cohort_band_resolver.py:4](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L4),
[:268-322](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L268-L322)
(`benchmark_min` = 25th pct, `benchmark_max` = 75th pct,
[:156-160](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L156-L160)),
accepting the first NAICS-level/source bucket with **≥ 2 distinct firms**
([cohort_band_resolver.py:125-130](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L125-L130)).
Materialized into `post_intake_cohort_bands`
([cohort_bands_table.py:33-59](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L33-L59)),
which also stores `robust_min` / `robust_max`, `confidence_tier`, `firm_count`, and the
full `cohort_query` audit.

**NAICS coverage is a cascade.** A static baseline (`post_intake_industry_baseline_lookup`,
[load_industry_baseline_lookup.py:44-77](../../scripts/load_industry_baseline_lookup.py#L44-L77))
resolves bands down a 6→5→4→3→2→generic_default hierarchy with confidence downgrading as it
deepens. The runtime cohort walk alternates EDGAR/Alpha across NAICS levels and falls back to
this static cascade when fewer than 2 firms match.

**Stage and revenue already select the cohort.** `_cap_categories_for` maps
`(target_revenue, stage)` → an allowed `cap_category` set
([cohort_band_resolver.py:214-238](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L214-L238))
— growth tokens → {mid, large}, mature/operational → established set, early/startup tokens →
a distinct set — and a revenue window further filters the peers
([cohort_band_resolver.py:432-433](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L432-L433)).
**So the machinery to pick a stage-appropriate peer group already exists** — §5 builds on it.

**Time dimension.** Each cohort row is a point-in-time firm-quarter (`fiscalDateEnding`,
[alpha_data_growth_rates.py:53](../../python/data_pull/alpha_data_growth_rates.py#L53)); the
resolver widens the fiscal-date window when the cohort is thin. There is **no stored
multi-period trajectory** per peer — peer trajectory, if wanted, must be assembled from the
sequence of a peer's firm-quarter rows at analysis time.

**Metrics that already carry realism bands** (the existing standard, for reference) —
[post_intake_realism/lookup.py:407-1146](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L407-L1146):
~26 per-quarter ratio metrics (cogs%, gross margin, marketing%, R&D%, rent%, SGA%, payroll%,
depreciation%, effective tax rate, **ebitda_margin** [:598], operating margin [:635],
**net_income_margin** [:657], AR/AP/inventory days, prepaid%, deferred rev%,
total_assets/revenue, **current_ratio** [:798], **quick_ratio** [:819], **debt_to_equity**
[:839], debt_to_assets, **operating_cash_flow_margin** [:879], **capex%** [:901], WC
structure) **plus 6 trajectory_check rows** (ebitda_positive_by_q11 [:1000], recovery trend
[:1026], loss_window_funded_through_q5 [:1052], q20-holds-vs-q11 [:1074], gross-margin-supports
[:1098], fixed-cost-burden [:1116]). This tells us the plumbing for both **level** bands and
**trajectory** checks already exists.

---

## 2. THE FULL METRIC UNIVERSE (the menu, unfiltered)

*(All formulas below are general knowledge.)* The "Firm?" column = computable per quarter
from §1.1. The "Cohort band?" column = a peer band exists today per §1.2 (so it can be
normalized now without new ingest). "Needs market data" = requires a share price /
enterprise value a private firm lacks.

### Growth
| Metric | Firm? | Cohort band? |
|---|---|---|
| Revenue growth (QoQ / YoY) | ✅ | ✅ `revenue_growth_q` |
| Gross-profit / EBITDA / net-income growth | ✅ (derive) | ❌ (derive from peer margin×revenue) |
| FCF growth | ✅ (derive) | ❌ |

### Margins (profitability levels)
| Metric | Firm? | Cohort band? |
|---|---|---|
| Gross margin | ✅ | ✅ |
| Operating margin | ✅ | ✅ |
| EBIT / EBITDA margin | ✅ | ✅ |
| Net margin | ✅ | ✅ |

### Cash generation
| Metric | Firm? | Cohort band? |
|---|---|---|
| Operating cash-flow margin | ✅ | ✅ `operating_cash_flow_margin` (realism) |
| Free cash flow ($) | ✅ (OCF − capex) | ❌ (derive from capex% + OCF margin) |
| FCF margin | ✅ (derive) | ⚠️ derivable from `capex_percent_revenue` + OCF margin |
| Cash conversion (OCF / EBITDA) | ✅ (derive) | ❌ |
| Cash runway (cash / burn) | ✅ (derive) | ❌ (firm-internal, not a peer ratio) |

### Returns
| Metric | Firm? | Cohort band? |
|---|---|---|
| ROA | ✅ (NI / total_assets) | ✅ `roa` |
| ROE | ✅ (NI / total_equity) | ✅ `roe` |
| ROIC | ✅ (derive: NOPAT / invested capital) | ❌ |

### Efficiency / working capital
| Metric | Firm? | Cohort band? |
|---|---|---|
| DSO / DPO / Inventory days | ✅ | ✅ |
| Cash conversion cycle | ✅ (derive) | ✅ `ccc` |
| Asset turnover (rev / assets) | ✅ | ⚠️ inverse of `total_assets_to_revenue` band |
| Expense ratios (COGS/SGA/R&D %) | ✅ | ✅ |

### Leverage / coverage / solvency
| Metric | Firm? | Cohort band? |
|---|---|---|
| Debt / equity | ✅ | ✅ |
| Debt / assets | ✅ | ✅ |
| Debt / EBITDA | ✅ (derive) | ✅ `debt_to_ebitda` |
| Interest coverage (EBIT / interest) | ✅ (derive) | ✅ `interest_coverage` |

### Liquidity
| Metric | Firm? | Cohort band? |
|---|---|---|
| Current ratio | ✅ | ✅ |
| Quick ratio | ✅ | ✅ |

### Valuation / multiples — **NOT available for a private firm**
| Metric | Firm? | Cohort band? |
|---|---|---|
| P/E, EV/EBITDA, P/S, P/B | ❌ no share price | ⚠️ cohort has `market_cap` but firm has none |

**Read of the menu.** The firm can compute everything except valuation multiples. The
**benchmarkable** subset (firm ✅ AND cohort band ✅) spans every viability dimension that
matters — profitability (margins), cash generation (OCF margin), returns (ROA/ROE), leverage
& coverage (D/E, D/EBITDA, interest coverage), liquidity (current/quick), efficiency (days,
expense ratios), and growth (`revenue_growth_q`). A few high-value metrics (FCF margin,
cash conversion, ROIC) are firm-computable but **lack a peer band today** — a deliberate
ingest decision, not a hard limit. **Valuation multiples are structurally out** (private firm).

---

## 3. NORMALIZATION — "backing into percentages" relative to the cohort

We need to express the firm's standing relative to peers in a way that is **robust** (not
whipsawed by a thin or skewed cohort) and **interpretable** (the cascade acts on it; the user
reads it). Four candidate transforms *(general knowledge)*:

| Method | What it yields | Robustness | Interpretability | Fit to our cohort data |
|---|---|---|---|---|
| **Percentile rank** | firm's position in peer distribution (0–100%) | High — rank-based, ignores outlier magnitude | Very high ("75th percentile margin") | **Native** — resolver already computes p25/p50/p75 ([cohort_band_resolver.py:268-322](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L268-L322)) |
| Ratio-to-benchmark | firm / median | Medium — sensitive to small medians, sign flips | High | Easy from p50 |
| Distance-to-median | firm − median (raw units) | Medium | Medium (units differ per metric) | Easy from p50 |
| Z-score | (firm − mean)/σ | Low–medium — needs σ, breaks on skew/small n | Low (σ not intuitive) | Cohort tables don't store σ; would need recompute |

**Recommended primary: percentile rank, interpolated within the p25/p50/p75 band the
resolver already produces.** Rationale:
1. **Cohort-native and already robust-gated** — the resolver computes percentiles, enforces
   ≥2 distinct firms ([:125-130](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L125-L130)),
   and records `confidence_tier`/`firm_count` so a thin cohort can be flagged rather than
   trusted blindly.
2. **Handles the public-company character correctly** *(general knowledge)*: percentiles are
   computed on **ratios**, so a $1M-revenue firm and a $1B peer are compared on margin/return
   *shape*, never on dollar absolutes. This is exactly why §1.2's "ratios not line items"
   asymmetry is acceptable.
3. **Direction-aware** *(general knowledge)*: some metrics are "higher is better" (margins,
   coverage, returns), some "lower is better" (leverage, days, expense ratios). Percentile
   must be oriented per metric so 100% always means "healthier," using the same direction
   metadata the realism bands already encode (min/target/max semantics).

**Robustness guards to specify (not yet built):** confidence-tier weighting (down-weight
low-firm-count bands), winsorize the percentile interpolation at the band edges, and fall
back to the static NAICS baseline cascade when the live cohort is below threshold — all of
which mirror the existing resolver fallback behavior.

**Use ratio-to-median as the secondary, human-facing gloss** ("EBITDA margin 0.8× the peer
median") because a ratio is easier to narrate than a percentile for a single headline metric.
**Avoid z-score** as the primary: σ isn't stored, and it degrades on the skewed, small-n
cohorts we routinely hit.

---

## 4. TRAJECTORY — the core of the standard

This is the heart of the recommendation, not an add-on. A point-in-time snapshot cannot
distinguish a ramping startup from a permanently-unviable firm (this is exactly the Fix #1
failure: a single early-quarter level test mis-classifies a healthy ramp — see the companion
[fix_1_early_quarter_viability_scope.md](fix_1_early_quarter_viability_scope.md)). Viability
must be expressed as the **path** each metric takes across Q1–Q20.

**Precedent in the codebase** *(this is exactly how the existing viability checks already
think)*: the realism `trajectory_check` rows evaluate a *path* property and pass when a
trajectory value ≥ 0 ([validator.py:574](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L574)),
e.g. `ebitda_recovery_trend_q5_q11` (Q11 − Q5 improvement,
[lookup.py:1026](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L1026)) and
`ebitda_margin_q20_holds_or_improves_vs_q11`
([lookup.py:1074](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L1074)).
The acceptance gate's `net_income_trajectory_viable` likewise tests Q5→Q11 improvement, not an
early-quarter level ([gate.py:416-441](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416-L441)).
The trajectory frame is already the doctrine; Fix #1 generalizes it from a few hand-picked
checks to the metric set.

**Trajectory primitives to define per metric** *(general knowledge)*:
- **Slope / rate of improvement** — regression slope or average QoQ delta of the metric across
  the horizon (is the metric getting healthier?).
- **Momentum** — slope of the back half vs the front half (is improvement accelerating or
  stalling?), so a firm that improves then plateaus below health is caught.
- **Convergence-to-cohort-health** — does the metric's *percentile* (§3) reach a target band
  (e.g. ≥ p50, or inside [p25, p75]) **by a horizon quarter** appropriate to the stage (§5)?
  This is the key construct: not "in band every quarter," but "**lands in the healthy band by
  quarter K and holds**."
- **Stability after convergence** — once converged, does it hold or relapse (the existing
  `q20_holds_or_improves_vs_q11` idea generalized).
- **Time-to-health** — the quarter at which the metric first enters and stays in the healthy
  band; a compact, interpretable scalar.

**How level and trajectory combine** *(recommendation)*: score each metric on **two axes** —
- **Level**: current/terminal percentile vs cohort (§3).
- **Trajectory**: slope + convergence + stability across the horizon.

A firm is viable on a metric when **either** it is already at cohort-health **or** it is on a
credible, converging path to cohort-health by its stage-appropriate horizon. Neither axis
alone is sufficient: level-only mis-fails ramps (Fix #1), trajectory-only would pass a firm
forever "improving" but never arriving. The pairing is the standard.

---

## 5. STAGE + START DATE — what conditions the metrics and the expected path

Stage and start date condition **both** (a) *which* metrics carry weight and (b) the *expected
trajectory and threshold* for each. The codebase already has the hooks:

- Cohort **peer selection** keys on stage today
  ([cohort_band_resolver.py:214-238](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L214-L238))
  — startup/early, growth/scaling, mature/operational map to different cap-category peer sets.
- The realism profitability floor is **stage × quarter-band** today: `_profitability_floor_for_quarter`
  picks q1_q4 / q5_q10 / q11_q20 ([validator.py:323-345](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L323-L345)),
  and the planning-mode policy carries startup/early/operational/mature variants
  ([post_intake_mapping.py:4805-4863](../../python/client_intake_and_finmo/post_intake_mapping.py#L4805-L4863),
  e.g. startup Q1-Q4 floor −0.20 to −0.40). **This is the existing model for stage-conditioned
  thresholds** — extend it to the whole metric set rather than just profitability.

**Stage → metric weighting and expected path** *(general knowledge, framed as policy we'd set)*:

| Stage | Metrics that matter most | Expected trajectory / threshold |
|---|---|---|
| **Startup / early** | Revenue growth, gross margin, credible **path-to-margin**, cash runway / loss funded | Deep early losses **tolerated**; require *converging* EBITDA/NI percentile reaching ≥ p25–p50 by a **later** horizon quarter (longer runway). Growth + slope dominate; absolute level is nearly ignored early. |
| **Growth / scaling** | Revenue growth, operating leverage (margin slope), cash conversion, leverage discipline | Margins must be **improving** quarter-over-quarter and crossing into the cohort band mid-horizon; growth high but moderating. |
| **Mature / operational** | Current margins, **FCF stability**, returns (ROA/ROE), leverage/coverage, liquidity | Level dominates: metrics should already sit in [p25, p75] and **hold**; trajectory check becomes "no relapse" rather than "must improve." |
| **Turnaround** | **Rate of improvement** above all, interest coverage, liquidity | Start below band is expected; pass on a steep, sustained improvement slope converging to the band by horizon end. |

**Start date is what places the firm on this timeline** *(recommendation)*: the projection is
20 fixed quarters, but the firm's **age at projection start** determines how many of those
quarters are still "ramp" vs "expected steady-state." A firm starting from zero gets the full
ramp horizon before convergence is required; a firm already 3 years old at Q1 should already be
near cohort-health at Q1 and is judged mostly on level + stability. Concretely, start date /
months-in-operation sets the **convergence-deadline quarter K** (§4) per metric — the same role
`deadline_quarter` plays for the existing realism trajectory metrics
([realism/lookup.py:621](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L621), `deadline_quarter=11`).

So: **stage selects the peer cohort and the metric weights; start date sets where "now" falls
on the ramp and therefore the convergence deadline; together they turn a generic metric band
into a firm-specific expected path.**

---

## 6. RECOMMENDATION — a robust, interpretable, multi-metric, trajectory-first standard

Not one metric; not an opaque mega-score. A small, legible **scorecard** the cascade can act on
and the user can read.

### 6.1 Shape
A **dimension scorecard**, ~5–6 viability dimensions, each backed by 1–3 benchmarkable metrics
(§2, firm ✅ + cohort band ✅):

1. **Profitability** — EBITDA margin, operating margin, net margin.
2. **Cash generation** — operating-cash-flow margin; FCF margin (add cohort band) as it matures.
3. **Growth / operating leverage** — revenue growth + margin slope.
4. **Solvency & coverage** — debt/EBITDA, interest coverage, debt/equity.
5. **Liquidity** — current ratio, quick ratio.
6. **Returns** — ROA, ROE.

### 6.2 How each metric is scored — two axes, percentile-normalized
For every metric, compute **both** *(per §3 + §4)*:
- **Level score** = direction-oriented **percentile** vs the stage-selected cohort
  (p25/p50/p75 from [cohort_band_resolver.py:268-322](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L268-L322)),
  evaluated at the firm's "now"/terminal quarter.
- **Trajectory score** = slope + **convergence-to-band by deadline-quarter K** + post-convergence
  stability across Q1–Q20.

Metric verdict = viable if **at-band-now OR credibly-converging-to-band-by-K**. Dimension verdict
= a transparent roll-up of its metrics (worst-of, or weighted), never a hidden weighting.

### 6.3 How stage + start date condition it
- **Stage** picks the peer cohort ([cohort_band_resolver.py:214-238](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L214-L238))
  and the **dimension weights** (startup → growth/path-to-margin heavy; mature → level/FCF/returns
  heavy; turnaround → slope heavy) — §5 table.
- **Start date** sets the **convergence deadline K** per metric (longer for young firms, near-zero
  for established ones), generalizing the existing `deadline_quarter` mechanism
  ([realism/lookup.py:621](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L621)).

### 6.4 Why this is robust *and* interpretable
- **Robust**: percentile/rank normalization on ratios (outlier- and scale-insensitive),
  confidence-tier and ≥2-firm gating already enforced by the resolver, NAICS fallback cascade,
  and a *multi-metric* surface so no single noisy metric decides viability.
- **Interpretable**: each dimension reads as a plain sentence — "EBITDA margin at the 30th
  percentile of peers but converging to the median by Q9; mature-stage liquidity already in
  band." The cascade gets a per-metric (level, trajectory, gap-to-band, deadline) tuple to act
  on; the user gets a six-line scorecard. **No opaque composite.**

### 6.5 Tradeoffs to decide on
- **Breadth vs noise**: more metrics = fuller picture but more thin-cohort bands. Mitigate via
  confidence weighting; start with the dimensions in 6.1 that have solid cohort coverage today.
- **New ingest**: FCF margin, cash conversion, and ROIC are firm-computable but lack peer bands
  (§2). Decide whether to extend the Alpha/EDGAR ingest to carry them, or score them firm-internal
  (level/trajectory without a peer percentile).
- **Convergence deadline K**: a policy lever per stage/metric — too short re-introduces the
  Fix #1 early-quarter failure; too long lets a never-arriving firm pass. Anchor it to start
  date + stage, as §5.
- **Roll-up rule**: worst-of (strict, conservative) vs weighted-average (forgiving). Worst-of is
  closer to current hard-fail doctrine; weighted is more startup-friendly. This is a per-stage
  choice, not a global one.
- **Peer-trajectory baseline**: §1.2 notes the cohort stores point-in-time rows, not stored peer
  trajectories. If we want "is the firm improving *faster than peers improved at the same age*,"
  that requires assembling peer trajectories at analysis time — a richer but heavier construct to
  decide on later.

### 6.6 One-line summary for the decision
**Score the firm on a 5–6 dimension scorecard of benchmarkable ratios; normalize each as a
direction-oriented percentile vs a stage-selected peer cohort; judge each on two axes — level
now and trajectory/convergence-to-band by a start-date-driven deadline — with stage setting both
the peer group and the dimension weights. Robust (rank-based, multi-metric, confidence-gated),
interpretable (plain-language per dimension, no hidden composite), and trajectory-first by
construction.**

---

### Appendix — load-bearing file:line anchors
- Firm 3-statement row schema: [finmo_model.py:145-220](../../python/financial_model_engine/finmo_model.py#L145-L220); horizon [model_inputs.py:8](../../python/financial_model_engine/model_inputs.py#L8).
- Cohort ratio tables: [alpha_data_growth_rates.py:47-93](../../python/data_pull/alpha_data_growth_rates.py#L47-L93), [edgar_data_growth_rates.py:109-150](../../python/data_pull/edgar_data_growth_rates.py#L109-L150).
- Percentile bands + firm-count gating: [cohort_band_resolver.py:125-130](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L125-L130), [:268-322](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L268-L322).
- Stage→cohort selection: [cohort_band_resolver.py:214-238](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L214-L238).
- Materialized bands: [cohort_bands_table.py:33-59](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L33-L59).
- Existing realism level + trajectory metrics: [post_intake_realism/lookup.py:407-1146](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L407-L1146).
- Stage × quarter-band thresholds (model to extend): [validator.py:323-345](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L323-L345), [post_intake_mapping.py:4805-4863](../../python/client_intake_and_finmo/post_intake_mapping.py#L4805-L4863).
- Trajectory-check evaluation precedent: [validator.py:574](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L574); [gate.py:416-441](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416-L441).
