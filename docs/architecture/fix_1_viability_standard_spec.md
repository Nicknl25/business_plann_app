# Fix #1 — Viability Standard: Full Design Spec

**Status:** design spec. **No code.** This is the complete specification we would build to.
Every data/code claim is grounded `file:line` / column-level. Finance concepts labeled
*(general knowledge)*.

**Synthesizes five prior docs (does not redo them):**
- [fix_1_viability_metrics_research.md](fix_1_viability_metrics_research.md) — metric universe, normalization, trajectory framing.
- [cohort_data_sourcing_options.md](cohort_data_sourcing_options.md) — Alpha/EDGAR sourcing, the resolver toggle.
- [fix_1_viability_constructs_data_feasibility.md](fix_1_viability_constructs_data_feasibility.md) — confirms the data for the 5 constructs.
- [planning_mode_and_stage_derivation.md](planning_mode_and_stage_derivation.md) — what planning_mode is, the supersede/keep call, and the age-derived stage taxonomy.
- [cohort_bar_calibration_note.md](cohort_bar_calibration_note.md) — live cohort EBITDA/growth bands for SMB-heavy NAICS; calibrates the convergence percentile.

**Build-ready status:** the §7 questions are now **resolved** (locked defaults below), the
two-tier verdict is pass/refine, stage is age-derived, coverage rides the existing NAICS cascade
(no confidence-weighting layer, §5.2), and one build prerequisite is flagged (§5.1 resolver
registration of `revenue_growth_q`).

---

## 1. SCOPE & PHILOSOPHY (locked)

**This standard answers one question: is the business model economically sound?** It is a
real firm-viability standard built from the **operating engine only** — everything the funding
pass does NOT touch.

- **Excluded as not cohort-comparable / funding-owned:** cash, debt, interest, equity, **and
  capex**. Therefore **no** leverage, coverage, liquidity, return-on-equity, cash-flow-statement
  metrics, or capex ratios enter the standard.
- **Viability = ECONOMIC soundness, explicitly NOT solvency / runway.** Whether the firm can be
  *funded* through its losses is the funding pass's job and is out of scope here. A plan can be
  economically viable (sound unit economics, converging margins) yet still need funding — that
  is expected and is handled elsewhere.
- **Clean zone** *(per feasibility doc)*: P&L down to **EBITDA** + **operating working capital**
  + **cumulative operating earnings**. Nothing below EBITDA, nothing the funding pass writes.
- **Trajectory-first**: viability is always the *path* of a metric across the projection, never
  a single-quarter point-check (the Fix #1 root failure — see
  [fix_1_early_quarter_viability_scope.md](fix_1_early_quarter_viability_scope.md)).
- **Stage- and start-date-aware**, and **cohort-percentile-normalized** wherever a peer band
  exists.

---

## 2. THE 5 CONSTRUCTS (feasibility-confirmed)

All firm-side formulas use the per-quarter `FinmoQuarterResult`; all cohort sides are confirmed
in the [feasibility doc](fix_1_viability_constructs_data_feasibility.md). Constructs 1–3 require
**no Option-F recompute** — existing precomputed cohort columns suffice.

### Construct 1 — Operating-cash proxy = EBITDA − Δ(operating NWC)
*(general knowledge: an operating-cash signal that excludes the contaminated cash statement)*
- **FIRM:** `ebitda` ([finmo_model.py:609](../../python/financial_model_engine/finmo_model.py#L609))
  minus the change in operating NWC, reusing finmo's **already-isolated clean deltas**:
  `changes_in_current_assets` (−Δ of AR+inventory+prepaid, ex-cash,
  [finmo_model.py:562](../../python/financial_model_engine/finmo_model.py#L562)) and the
  `operational_current_liabilities` delta (AP+deferred, ex-short-term-debt,
  [finmo_model.py:571-572](../../python/financial_model_engine/finmo_model.py#L571-L572)).
  Express as % of `revenue` ([:601](../../python/financial_model_engine/finmo_model.py#L601))
  for normalization.
- **COHORT:** reconstruct from `ebitda_margin_q`
  ([alpha_data_growth_rates.py:60](../../python/data_pull/alpha_data_growth_rates.py#L60)) minus
  ΔNWC% computed across consecutive same-firm rows from the WC days / P3 WC columns (Construct 3
  source). Both operating-clean.

### Construct 2 — Rule-of-40 = revenue-growth% + EBITDA-margin%
- **FIRM:** QoQ/YoY growth of `revenue` ([:601](../../python/financial_model_engine/finmo_model.py#L601))
  + `ebitda`/`revenue` ([:609/:601](../../python/financial_model_engine/finmo_model.py#L609)).
- **COHORT:** `revenue_growth_q` ([alpha_data_growth_rates.py:55](../../python/data_pull/alpha_data_growth_rates.py#L55))
  + `ebitda_margin_q` ([:60](../../python/data_pull/alpha_data_growth_rates.py#L60)). Direct, cleanest.

### Construct 3 — Working-capital intensity = operating-NWC / revenue + trajectory
*(general knowledge: a cash-trap signal — rising WC intensity ties up operating cash)*
- **FIRM:** operating NWC = (AR [:491] + inventory [:492] + prepaid [:493]) − (AP [:503] +
  deferred [:494]) ÷ `revenue` ([:601]); track its trajectory across quarters.
- **COHORT:** `current_assets_minus_cash_to_revenue` − `current_liabilities_to_revenue`
  ([alpha_data_growth_rates.py:89-90](../../python/data_pull/alpha_data_growth_rates.py#L89-L90)),
  or the granular `dso` / `dpo` / `inventory_days` ([:67-69](../../python/data_pull/alpha_data_growth_rates.py#L67-L69)).
  Operating-clean (cohort treats STD as 0 — see §6).

### Construct 4 — EBITDA ramp shape
Three sub-signals: **time-to-breakeven**, **EBITDA-margin slope**, **margin-expansion-with-scale
(operating leverage)** *(general knowledge: operating leverage = margin rising as revenue scales)*.
- **FIRM:** per-quarter `ebitda` ([:609]) + `revenue` ([:601]): breakeven = first quarter
  `ebitda ≥ 0`; slope = Δ(ebitda/revenue); operating leverage = Δmargin vs Δrevenue.
- **COHORT:** slope + operating leverage reconstructable from consecutive `ebitda_margin_q` +
  `revenue_growth_q`. **Time-to-breakeven has NO clean cohort analog** (per feasibility doc) →
  it moves to **Tier 2 Gate A**, not the graded tier.

### Construct 5 — Cumulative EBITDA
*(general knowledge: clean operating analog of retained earnings)*
- **FIRM:** running sum of per-quarter `ebitda` ([:609]).
- **COHORT:** **NO clean benchmark** (per feasibility doc — point-in-time ratio cohort has no
  cumulative / retained-earnings analog; cumulative EBITDA is an absolute, not a normalizable
  ratio) → it moves to **Tier 2 Gate B**, firm-internal.

---

## 3. TWO-TIER STRUCTURE (locked)

The roll-up is a **weighted competitive score sitting ON TOP OF hard gates** — neither pure
worst-of nor pure weighted-average. A plan **cannot score past a failed gate**; above the gates
it competes on percentile + trajectory.

### TIER 2 — absolute gates (firm-internal, no peer percentile)
Evaluated first. Failing either gate ⇒ plan is non-viable regardless of Tier-1 standing.
- **GATE A (breakeven):** **sustained EBITDA-positive** (trailing-4-quarter, not a single-quarter
  snapshot) by **business-quarter-10**, age-anchored to start date (§4). This is Construct 4's
  breakeven-timing. **Posture exception:** under a genuine turnaround posture
  (`explicit_distress_context`, §4.3) the deadline is pushed **+4 quarters → ~business-quarter-14**.
- **GATE B (cumulative):** **cumulative EBITDA ≥ 0 by Q20** (Construct 5). **Stays FIRM** — posture
  does not relax it; a plan that never accumulates non-negative operating earnings over the full
  horizon is non-viable regardless of situation.

### TIER 1 — competitiveness GRADE (produces pass / refine ONLY)
Constructs **1, 2, 3, and Construct 4's slope + operating-leverage**. Each scored on **BOTH**:
- **Level-now** — direction-oriented **percentile vs cohort** (§5).
- **Trajectory** — gap-closure toward a healthy band by a deadline + slope momentum (§5).

Tier-1 is **stage-weighted** (§4) and **cohort-confidence-weighted** (§5.2). It is a
**competitiveness grade, NOT a viability verdict** — the gates (Tier 2) own non-viability, so
Tier-1 never emits "fail". Its only outputs are:
- **clear gates + strong Tier-1 → PASS**
- **clear gates + weak Tier-1 → REFINE**
- **failed gate → non-viable** (Tier-1 not consulted for the verdict; still computed for the
  refine signal).

*Rationale (general knowledge):* the gates encode "the operating model must actually become
self-sustaining" (binary, firm-internal, no peer needed); the graded tier encodes "how
competitive is it, and is it on a converging path" (relative, peer-normalized). Gates prevent a
high percentile from masking a business that never reaches breakeven; the graded tier separates a
barely-competitive-but-viable plan (refine) from a strong one (pass) **without** ever overriding
the gates' viability call.

---

## 4. STAGE + START DATE + POSTURE (locked)

Three distinct axes — do not conflate them:
- **Start date** → business **age** → age-anchors Gate A and derives **stage** (§4.1).
- **Stage** (lifecycle reality) → weights Tier-1 (§4.2).
- **Posture** (operating intent, e.g. turnaround) → loosens the gate/bar (§4.3). **Posture is NOT
  a stage** (correcting the prior draft's startup/mature/**turnaround** list — turnaround is a
  posture, per [planning_mode_and_stage_derivation.md](planning_mode_and_stage_derivation.md) §1.5).

### 4.1 START DATE → business age → stage (age-derived; drop nullable `business_stage`)
`business_start_date` is a **required** intake field, parsed to a `date`
([intake_submission.py:22-24](../../python/client_intake_and_finmo/intake_submission.py#L22-L24)),
stored on the draft ([intake_submit_service.py:241, 264, 276](../../python/client_intake_and_finmo/intake_submit_service.py#L241-L276)),
and **business age is already computed** as `business_age_months_at_run`
([quarter_grid.py:891, 928](../../python/client_intake_and_finmo/quarter_grid.py#L891);
`_whole_months_between` [:849-853](../../python/client_intake_and_finmo/quarter_grid.py#L849-L853)).

**Stage is derived from age — NOT the nullable `business_stage` intake field** (locked, per
[planning_mode_and_stage_derivation.md](planning_mode_and_stage_derivation.md) §3). Use the
**4-stage floors taxonomy**:

| Stage | Business age | Quarters elapsed |
|---|---|---|
| **startup** | < 12 months | age_q < 4 |
| **early** | 12 – < 36 months | 4 ≤ age_q < 12 |
| **operational** | 36 – < 84 months | 12 ≤ age_q < 28 |
| **mature** | ≥ 84 months | age_q ≥ 28 |

`age_q = business_age_months_at_run // 3`. A future-dated start (start > today) → **startup**.

This **fixes two confirmed bugs** the current code carries (per the derivation note): (a)
`_stage_family` never returns `mature` ([quarter_grid.py:862](../../python/client_intake_and_finmo/quarter_grid.py#L862)
defaults to `operational`), so the floor table's `_mature` columns are unreachable; (b) the age
fallback collapses everything older than 365 days to `operating`
([quarter_grid.py:887-890](../../python/client_intake_and_finmo/quarter_grid.py#L887-L890)),
unable to tell a 2-year firm from a 20-year one. **Build note:** `_stage_family`
([quarter_grid.py:856-862](../../python/client_intake_and_finmo/quarter_grid.py#L856-L862)) has
OTHER consumers (the stage-ramp policy/contract path); its other call sites must be checked before
reusing or extending it so the new mature label does not break them.

### 4.1b START DATE → age-anchors GATE A
*(general knowledge)* The plan's 20 quarters are not the firm's first 20 quarters. The breakeven
deadline is **business-quarter-10 = 10 quarters from `business_start_date`, NOT plan-Q1.**
- **Brand-new startup** (start_date ≈ plan-Q1): full 10 plan-quarters of runway before Gate A.
- **Older firm:** runway already elapsed; deadline = `plan-quarter (10 − quarters_elapsed_since_start)`.
- **Firm already past business-Q10 at plan-Q1:** breakeven expected near-immediately, **with a
  2-quarter grace window** (§7) — always the trailing-4-quarter sustained test, **never** an instant
  single-quarter snapshot.

### 4.2 STAGE → weights TIER 1
*(general knowledge; direction locked, exact numbers via calibration — §7.1)* Moderate tilt — the
lead construct(s) weighted ~1.5–2× the others, not winner-take-all:
- **startup / early:** weight toward **growth + path-to-margin** — Rule-of-40 (C2) and EBITDA-margin
  slope (C4).
- **operational:** balanced, tilting to level.
- **mature:** weight toward **level** — EBITDA-margin percentile and operating-cash proxy (C1).

### 4.3 POSTURE → loosens the gate/bar (supersedes the planning_mode floor function)
The new standard **supersedes `planning_mode`'s profitability-floor function** (the
`profitability_floor_q*` enforcement — see
[planning_mode_and_stage_derivation.md](planning_mode_and_stage_derivation.md) §1.5). What is
**retained** is `planning_mode`'s **posture** signal, specifically `explicit_distress_context`
([post_intake_mapping.py:2812-2815](../../python/client_intake_and_finmo/post_intake_mapping.py#L2812-L2815)),
which under a genuine turnaround:
- pushes **Gate A** out **+4 quarters** (~business-Q14, §3), and
- **relaxes the Tier-1 convergence bar** (accept a lower target percentile / slope-only credit).
- **Gate B stays firm** — cumulative EBITDA ≥ 0 by Q20 regardless of posture.

*(general knowledge: a real turnaround is judged on rate-of-improvement and a longer breakeven
runway, not held to a healthy-firm deadline — but it must still reach non-negative cumulative
operating earnings by the horizon.)*

---

## 5. SCORING MECHANICS — generalize existing precedents

Build by **generalizing patterns already in the codebase**, not inventing new machinery.

- **Level + trajectory scoring** generalizes the existing `trajectory_check` rows: a trajectory
  value evaluated against a floor ([validator.py:574](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L574))
  and the Q5→Q11 improvement test in `net_income_trajectory_viable`
  ([gate.py:416-441](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416-L441)).
  The standard extends this from a few hand-picked checks to all graded constructs.
- **Stage × deadline** generalizes the stage×quarter-band profitability floor model:
  `_profitability_floor_for_quarter` ([validator.py:323-345](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L323-L345))
  selecting q1_q4 / q5_q10 / q11_q20 variants from the planning-mode policy
  ([post_intake_mapping.py:4805-4863](../../python/client_intake_and_finmo/post_intake_mapping.py#L4805-L4863)).
  Gate A's age-anchored deadline is the same idea, anchored to start date instead of plan-quarter.
- **Normalization** *(per research doc §3)*: **direction-oriented percentile vs cohort** is
  primary (higher percentile = healthier, orientation per metric); **ratio-to-median** is the
  human-facing gloss; **z-score is rejected** (no σ stored in the cohort tables).
- **Cohort grounding**: call the existing resolver `resolve_cohort_band`
  ([cohort_band_resolver.py:544-577](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L544-L577))
  — EDGAR+Alpha toggle × NAICS 6→2 cascade × ≥2-firm gate
  ([:126-130](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L126-L130)).
  Per the sourcing doc, optionally layer per-metric source preference (Option E) for the specific
  metrics here, but **no Option-F recompute is needed for Constructs 1–3**.

### 5.1 BUILD PREREQUISITE — register `revenue_growth_q` in the resolver
**Construct 2's growth term does not resolve today.** `resolve_cohort_band` returns `None` for
`revenue_growth_q` because the column is **not in `_KNOWN_METRIC_COLUMNS`**, so the override path
exits early ([cohort_band_resolver.py:583](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L583)).
Confirmed live: every SMB NAICS returned NO BAND for `revenue_growth_q`
([cohort_bar_calibration_note.md](cohort_bar_calibration_note.md)). The column exists in the tables
(`revenue_growth_q`, [alpha_data_growth_rates.py:55](../../python/data_pull/alpha_data_growth_rates.py#L55)).
**Prerequisite (not optional):** register `revenue_growth_q` in `_KNOWN_METRIC_COLUMNS` and the
metric-key→column mapping ([cohort_band_resolver.py:107-116](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L107-L116))
so the Rule-of-40 growth band resolves through the same path. Without this, Construct 2 is
EBITDA-margin-only.

### 5.2 COVERAGE — rely on the existing NAICS cascade; NO confidence-weighting layer (locked)
Thin or missing bands are handled by the **existing NAICS 6→5→4→3→2 cascade** (closest-industry
fallback) already built into the resolver
([cohort_band_resolver.py:138](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L138),
walk at [:608-616](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L608-L616),
≥2-firm gate [:126-130](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L126-L130)).
**The cascade IS the coverage mechanism — do NOT add a separate confidence-weighting layer.**

Rationale (locked): since the **gates own viability** (§3), a weak or coarse band can only affect
the **pass/refine grade**, never the viability verdict — so a confidence down-weight would add
machinery for no viability benefit. When a NAICS-6 band is thin, the cascade simply resolves a
closer-available coarser band (e.g. Sunny's bakery resolving at L3, clothing at L2 —
[cohort_bar_calibration_note.md](cohort_bar_calibration_note.md)); that cascaded band is accepted
as-is for the grade. The resolver still records `naics_level_used` / `firm_count` on the result
for provenance/transparency, but Tier-1 does **not** modulate construct weights by them.

---

## 6. BUILD-TIME GUARDRAILS (notes, not decisions)

- **Read operating SUBSETS, never the displayed totals.** `current_assets` includes cash
  ([finmo_model.py:586](../../python/financial_model_engine/finmo_model.py#L586)) and
  `current_liabilities` includes short-term debt
  ([finmo_model.py:543](../../python/financial_model_engine/finmo_model.py#L543)) — both
  funding-contaminated. Use the clean operating fields finmo already builds:
  `changes_in_current_assets` ([:562]) and `operational_current_liabilities` ([:571-572]).
- **Firm/cohort WC asymmetry.** The cohort's `current_liabilities_to_revenue` treats short-term
  debt, deferred revenue, and accrued expenses as 0, and `current_assets_minus_cash_to_revenue`
  treats prepaid as 0 ([phase_9_p3_derive_working_capital_columns.py:8-22](../../python/scripts/phase_9_p3_derive_working_capital_columns.py#L8-L22)).
  The firm includes prepaid (CA) and deferred (CL). **Recommend stripping prepaid + deferred from
  the firm-side operating-NWC for symmetry** with the cohort, OR documenting the gap explicitly so
  the percentile comparison is apples-to-apples. (Decision deferred to build.)
- **Cohort rows are point-in-time, not age-aligned** (sourcing doc): peer "trajectory" must be
  assembled from a peer's sequence of firm-quarter rows at analysis time; it does not represent a
  startup ramp. This bounds how literally Construct 4's slope benchmark can be read.

---

## 7. RESOLVED DECISIONS (locked defaults — formerly open questions)

These are the build defaults. Calibration-tunable items say so explicitly.

1. **Stage weight values.** **LOCKED — direction per §4.2, moderate tilt (lead construct(s)
   ~1.5–2× the others, not winner-take-all).** Exact multipliers are **calibration-tunable**
   against known-good / known-bad plans; the direction and tilt magnitude are fixed.

2. **Convergence-band TARGET (which percentile is "healthy").** **LOCKED: p25-clear / p50-full-credit**,
   graded between. **Data-confirmed** — for SMB-heavy NAICS a realistic 8–15% EBITDA-margin operator
   lands ~p50–p75 and above, so p25-clear/p50-strong is reachable (often exceeded); the public p25 is
   frequently negative, so no lower anchor is needed
   ([cohort_bar_calibration_note.md](cohort_bar_calibration_note.md)).

3. **Grace-window length for firms past business-Q10.** **LOCKED: 2 quarters** (one full
   trailing-4-quarter window plus room, without single-snapshot fragility).

4. **Trajectory slope / convergence measure.** **LOCKED: gap-closure % toward the healthy band by
   the deadline quarter (primary)** — generalizes `net_income_trajectory_viable`
   ([gate.py:416-441](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416-L441)) —
   **plus OLS slope sign as the momentum secondary**.

5. **Trailing-4-quarter before 4 quarters exist (Q1–Q3).** **LOCKED: expanding window** (mean of
   Q1..Qn for n<4); **Gate A cannot fire before business-quarter-4**.

6. **Level-vs-trajectory split within each graded construct.** **LOCKED, stage-dependent:**
   startup **30 / 70**, early **40 / 60**, operational **55 / 45**, mature **65 / 35** (level / trajectory).

7. **Final TIER-1 → verdict mapping.** **LOCKED: pass / refine only** (§3) — gates own
   non-viability, so Tier-1 never emits "fail". Clear gates + strong Tier-1 → **pass**; clear gates
   + weak Tier-1 → **refine**. The pass/refine threshold on the weighted Tier-1 score is
   **calibration-tunable**.

---

## 8. ONE-PARAGRAPH BUILD SUMMARY

Build a viability standard over the operating clean zone (EBITDA + operating working capital +
cumulative EBITDA), with **two tiers**: absolute firm-internal **gates** that own viability —
sustained (trailing-4-quarter, expanding before Q4) EBITDA breakeven by **business-quarter-10**
(age-anchored to the required `business_start_date`; **+4 quarters under turnaround posture**) and
cumulative EBITDA ≥ 0 by Q20 (**firm, posture-independent**) — and, above the gates, a
**stage-weighted, cohort-confidence-weighted competitiveness GRADE** producing **pass / refine only**
over Constructs 1, 2, 3 and Construct 4's slope/operating-leverage, each scored on **level-now
(cohort percentile, p25-clear / p50-full-credit)** AND **trajectory (gap-closure toward band by
deadline + slope momentum)**, with the level/trajectory split stage-dependent (startup 30/70 →
mature 65/35). **Stage is age-derived** (startup <12mo / early 12–36mo / operational 36–84mo /
mature ≥84mo from `business_age_months_at_run`), **dropping the nullable `business_stage`**; the new
standard **supersedes `planning_mode`'s profitability-floor function** while keeping its
turnaround **posture** as a gate/bar loosener. Ground all cohort percentiles through the existing
`resolve_cohort_band` resolver — **first registering `revenue_growth_q`** (§5.1) so Construct 2's
growth term resolves, and **relying on the existing NAICS 6→2 cascade for thin/missing bands with
NO confidence-weighting layer** (§5.2 — the gates own viability, so a coarse band only affects the
pass/refine grade). Read finmo's clean operating-NWC deltas, never the funding-contaminated
balance-sheet totals. **All §7 questions are resolved**; remaining tunables (exact stage
multipliers, pass/refine threshold) are calibration, not design.
