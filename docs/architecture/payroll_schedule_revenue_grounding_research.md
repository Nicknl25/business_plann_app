# Payroll Schedule — Revenue-Grounding Research

**Status:** RESEARCH ONLY. No code, no implementation, no act-recommendation. A map + options
analysis for Nick to decide from. Builds on
[fix_2_headcount_derivation_trace.md](fix_2_headcount_derivation_trace.md) and
[fix_2_headcount_derivation_spec.md](fix_2_headcount_derivation_spec.md) — does not re-derive
the structure.

**Why this exists.** The Fix #2 causal reversal is shelved: it needs a productivity dataset
that doesn't exist (spec OQ-1), and payroll-%-of-revenue is too spotty to be a *driver* (it's
the CBP×SOI intersection, where the SOI revenue denominator is the weak link). Nick is
**keeping** the current GPT-authored, capacity-primary payroll schedule. The question now is
narrow: **within that structure, how can we make GPT ground its payroll authoring more in
revenue, so the output is less clearly detached?** Lighter-touch (context / prompt / guardrail
/ check), not a structural overhaul.

**Scope note.** Live GPT authoring is in transition to an "Executive" amalgamated session
([set_payroll_schedule](../../python/client_intake_and_finmo/post_intake_headcount/set_payroll_schedule.py));
options below note where they depend on that layer.

---

## Part A — The current GPT payroll-authoring process (end to end)

### A.1 What GPT authors

The `payroll_headcount_schedule` contract. Root fields + a per-title/per-quarter grid:

| Field | File:line | What GPT chooses |
|---|---|---|
| `payroll_headcount_grid[]` (`q`, `oews_occ_title`, `starting_fte`, `hires`, `ending_fte`, `payroll_tax_benefits_pct`) | [post_intake_mapping.py:2048-2054](../../python/client_intake_and_finmo/post_intake_mapping.py#L2048-L2054) | supporting-staff OEWS titles + FTE ramp per quarter Q1-Q20 + benefits % |
| `capacity_units_per_supporting_fte` | [post_intake_mapping.py:2139](../../python/client_intake_and_finmo/post_intake_mapping.py#L2139) | productivity (capacity units one FTE supports/quarter) |
| `capacity_labor_model` | [post_intake_mapping.py:2135](../../python/client_intake_and_finmo/post_intake_mapping.py#L2135) | enum: labor_driven/hybrid/system_driven/expert_driven |
| `labor_intensity_class` | [post_intake_mapping.py:2136](../../python/client_intake_and_finmo/post_intake_mapping.py#L2136) | enum: low/medium/high/expert |
| `wage_positioning_tier` + `wage_positioning_multiplier` | [post_intake_mapping.py:2137-2138](../../python/client_intake_and_finmo/post_intake_mapping.py#L2137-L2138) | wage level vs OEWS floor |
| `target_payroll_percent_of_revenue` | [post_intake_mapping.py:2150-2158](../../python/client_intake_and_finmo/post_intake_mapping.py#L2150-L2158) | a *sanity target*, expressly **not** a driver |
| `rationale` | [post_intake_mapping.py:2159](../../python/client_intake_and_finmo/post_intake_mapping.py#L2159) | free text |

### A.2 What Python does before and after

- **Before:** loads OEWS title catalog + headcount policy; injects key people from intake
  (GPT authors *supporting* roles only — [post_intake_mapping.py:2133](../../python/client_intake_and_finmo/post_intake_mapping.py#L2133)); assembles GPT context (A.3).
- **After:** resolves OEWS wages × positioning × inflation → payroll dollars
  (`avg_FTE × wage`, [schedule.py ~1946-1982](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py));
  derives payroll-supported Capacity from FTE and **overwrites** revenue Capacity
  (`apply_payroll_supported_capacity_to_model_input`,
  [schedule.py:2525](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2525));
  runs the payroll-%-of-revenue feasibility check + repair (A.6).

### A.3 Every context key GPT sees at authoring time

Declared at [post_intake_mapping.py:2516-2531](../../python/client_intake_and_finmo/post_intake_mapping.py#L2516-L2531).
The revenue-bearing ones (the critical question):

| Context key | Builder | Revenue content GPT sees |
|---|---|---|
| `revenue_driver_context` | `_revenue_driver_context_from_model_input` [schedule.py:2244-2316](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2244-L2316) | **per-quarter Q1-Q20 `computed_revenue_from_model_input` and `finmo_revenue`** ([schedule.py:2303-2310](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2303-L2310)); per-product `product_rows` (capacity/price/utilization) **dropped by compaction** ([schedule.py:921-929](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L921-L929)) |
| `payroll_capacity_grid` | `_payroll_capacity_grid_for_gpt` [schedule.py:1674-1716](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1674-L1716) | per-quarter `total_structural_capacity_units`, `weighted_utilization`, `computed_revenue_from_model_input`, key-people avg FTE; rule = **"Context only… this grid is not a demand floor"** ([schedule.py:1696-1699](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1696-L1699)) |
| `financial_context` | [runner.py:2192-2202](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L2192-L2202) | `annual_revenue` (Year-1 total) + cash/assets/debt |
| `current_model_snapshot` | [runner.py:2210-2224](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L2210-L2224) | `finmo_revenue_first_4_quarters`, revenue driver states first 4 quarters |
| `payroll_decision_options` / `payroll_capacity_guardrails` | [schedule.py:1558-1647](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1558-L1647) | rules that frame revenue as a *consequence* of FTE, not an input (A.5) |

There is also an **informational** intake-implied payroll/revenue intensity
(`_intake_implied_operating_intensity`, [schedule.py:1730-1775](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1730-L1775)),
explicitly marked non-binding.

### A.4 Timing

Revenue Capacity is authored at **Step 10** (`prepare_baseline_model_input`, pre_convergence,
[post_intake_mapping.py:686-708](../../python/client_intake_and_finmo/post_intake_mapping.py#L686-L708))
— **before** payroll authoring at Steps 62-67. So by the time GPT authors FTE, the revenue plan
and its per-quarter trajectory already exist and are in context. The feasibility check, however,
runs **after** payroll → finmo, in the finalize global-invariants pass
([fail_fast.py:2018-2022](../../python/client_intake_and_finmo/fail_fast.py#L2018-L2022)).

---

## Part B — Where the detachment actually is (precisely)

**The detachment is NOT "revenue is invisible to GPT."** GPT *does* see a per-quarter revenue
trajectory (`computed_revenue_from_model_input`, `finmo_revenue` for Q1-Q20) and a per-quarter
capacity/utilization grid. The detachment is in three specific places:

1. **No instruction connects FTE to revenue.** Across *every* field's
   `prompt_required_instruction`, none says "staff toward your revenue plan" or "size FTE
   against revenue." The grid fields say "GPT owns the FTE ramp; Python derives Capacity from
   it" ([post_intake_mapping.py:2051-2053](../../python/client_intake_and_finmo/post_intake_mapping.py#L2051-L2053)).
   The only revenue-named field, `target_payroll_percent_of_revenue`, is explicitly told **"This
   does not drive payroll math or force FTE"** ([post_intake_mapping.py:2157](../../python/client_intake_and_finmo/post_intake_mapping.py#L2157)).
   Revenue is in the room but GPT is never asked to staff to it.

2. **The doctrine in the context rules tells GPT revenue is downstream of FTE.** The capacity
   grid rule: *"revenue is constrained by that derived capacity and this grid is not a demand
   floor"* ([schedule.py:1696-1699](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1696-L1699)).
   The guardrails: *"Python then uses payroll FTE as the causal capacity envelope; revenue can
   only be supported by that capacity"* ([schedule.py:1558-1613](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1558-L1613)).
   So GPT is actively told **not** to treat revenue as a target — capacity (hence revenue) is a
   *result* of its FTE choice. This is the capacity-primary doctrine working as designed; it is
   also exactly what makes the output look detached from revenue.

3. **The post-hoc check is too wide to pull, and it pulls the wrong lever.** It runs after the
   model is built (B.timing), and the acceptable band is enormous (Part C). When it does fire,
   it nudges **productivity**, not FTE/payroll directly (C.3) — so even the correction doesn't
   tie headcount to revenue; it rescales the capacity GPT's FTE implies.

**Net:** GPT authors FTE from business judgment (titles, intensity, productivity) with revenue
*present but framed as a downstream consequence*, then a wide post-hoc band rubber-stamps almost
anything. The output is "detached" because nothing in the authoring step asks it to be attached,
and the only attachment mechanism (the band) is loose and late.

---

## Part C — Existing revenue-connection points (inventory)

### C.1 The payroll-%-of-revenue feasibility check

Bands (`payroll_revenue_sanity_bounds_json`, [lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79))
widened by tolerances (`tolerance_pct=0.03`, `relative_tolerance=0.20`,
[lookup.py:80-81](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L80-L81);
effective-bound math at [schedule.py:2867-2868](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2867-L2868)):

| intensity | policy band | **effective band after tolerances** |
|---|---|---|
| low | 6%–45% | **≈3%–54%** |
| medium | 10%–55% | **≈7%–66%** |
| high | 16%–70% | **≈12.8%–84%** |
| expert | 18%–80% | **≈14.4%–96%** |

A medium-intensity plan passes for any payroll between **7% and 66% of revenue** — a 59-point
window. This is wide enough that, by inspection, most authored schedules land inside it without
repair. (This is a reasoned inference from band width, not a measured pass-rate; if Nick wants
certainty, the pass/repair rate is instrumentable.)

- **Fires:** per-quarter, `ratio = payroll/revenue` vs effective min/max
  ([schedule.py:2879-2888](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2879-L2888)).
- **Severity:** hard fail when violated (`payroll_revenue_economic_feasibility_failed`,
  [schedule.py:3001-3018](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3001-L3018)),
  raised in finalize ([fail_fast.py:2018-2022](../../python/client_intake_and_finmo/fail_fast.py#L2018-L2022)).
- **What it nudges:** the repair gives GPT a *specific productivity target*
  (`safe_capacity_units_per_supporting_fte_target_with_buffer`,
  `required_capacity_units_per_supporting_fte_direction`,
  [schedule.py:2947-2962](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2947-L2962),
  constraints at [schedule.py:600-630](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L600-L630))
  and re-invokes Handler C
  ([feasibility_repair.py:159-179](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L159-L179)).
  It corrects *productivity/capacity*, not FTE directly.

### C.2 There is also an authoring-time band check — but only on the declared target

`set_payroll_schedule` runs `_check_band_violations`
([set_payroll_schedule.py:119-158](../../python/client_intake_and_finmo/post_intake_headcount/set_payroll_schedule.py#L119-L158))
during authoring — but it only checks that the **declared `target_payroll_percent_of_revenue`**
sits in its class band. It does **not** check the actual per-quarter payroll/revenue the FTE grid
implies. So the only authoring-time revenue check validates a self-declared number, not the real
output.

### C.3 Revenue context GPT already receives

Per A.3: per-quarter revenue trajectory, capacity/utilization grid, Year-1 annual revenue, first
4 quarters of finmo revenue. **The raw material for revenue grounding is already in the prompt** —
what's missing is a budget reference and an instruction to use it.

---

## Part D — Options to ground GPT's authoring more in revenue

Each option: what it entails, how much it moves the needle, risk/blast radius, lighter-touch?,
and the **critical data-dependency filter** — does it lean on the business's OWN revenue plan
(always present, sustainable) or on spotty external cohort data (Nick's objection)?

### D1. Feed GPT a revenue-implied payroll-budget REFERENCE at authoring time (anchor, not constraint)

- **Entails:** add a context field that, from the business's own per-quarter revenue (already in
  `revenue_driver_context`), computes a *reference* payroll envelope — e.g. "at X% of your Q-by-Q
  revenue, payroll ≈ $A–$B; at your chosen avg wage that's ≈ Y–Z FTE." Shown *before* GPT picks
  FTE, labeled non-binding.
- **Needle:** **high.** This is the single most direct fix for Part B.1 — it converts the
  revenue GPT already sees into a headcount/payroll number in the units GPT is authoring.
  Anchoring effects are strong even when labeled non-binding.
- **Risk/blast radius:** low–medium. New context field + builder; no validator/contract change.
  Risk is choosing the X% — if sourced from spotty cohort data it inherits that weakness (see
  filter).
- **Lighter-touch?** Yes — context-only addition.
- **Data filter:** **Can be built entirely on the business's own revenue plan** if the X% comes
  from the *policy tier band midpoint* (`payroll_revenue_sanity_bounds`, already in
  [lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79))
  rather than the NAICS cohort. Strongly preferred form: anchor = (own revenue) × (tier-band
  midpoint). No external data dependency. A NAICS-cohort X% is an *optional* refinement where
  coverage exists (Part E), with graceful fallback to the tier midpoint.

### D2. Strengthen the prompt to require GPT to justify FTE against the revenue plan

- **Entails:** add an instruction (grid array field and/or `rationale`) like "Your FTE ramp must
  be consistent with the per-quarter revenue trajectory in revenue_driver_context; in `rationale`,
  state the implied payroll-%-of-revenue per year and why it fits the business." Optionally
  reverse the "this does not force FTE" framing on `target_payroll_percent_of_revenue`.
- **Needle:** **medium.** Directly attacks Part B.1 (no instruction connects FTE to revenue).
  Effect depends on the live GPT honoring it; weaker than a numeric anchor but composes with D1.
- **Risk/blast radius:** low. Prompt text only. Caveat: contradicts the capacity-primary doctrine
  text (B.2) — wording must avoid telling GPT both "revenue is downstream of FTE" and "staff to
  revenue." Needs a coherent reconciled message.
- **Lighter-touch?** Yes — prompt only.
- **Data filter:** **Own revenue plan only.** No external dependency.

### D3. Tighten the sanity band and/or move the check earlier (make the post-hoc pull harder)

- **Entails:** narrow the effective band (reduce the 0.03/0.20 tolerances and/or tighten the
  class bands) so the check engages more often; and/or run `payroll_revenue_feasibility_violations`
  during authoring as feedback (it currently runs only in finalize), so GPT corrects in-session
  instead of via a post-hoc repair round.
- **Needle:** **medium–high** for "less detached output" (a tighter band mechanically forces
  payroll closer to a revenue-proportional figure). But it pulls via **productivity rescaling**
  (C.1), so it tightens the payroll/revenue *ratio* without making GPT *reason* from revenue —
  cosmetic alignment unless paired with D1/D2.
- **Risk/blast radius:** **medium–high.** Tightening a hard-fail band risks more
  `payroll_revenue_economic_feasibility_failed` halts and more repair rounds; could destabilize
  runs that pass today. Needs the pass/repair-rate measurement first.
- **Lighter-touch?** Partial — values are config (lookup.py), but behavior change is real.
- **Data filter:** The *band itself* is the policy tier table (own-data, sustainable). It becomes
  cohort-dependent only if Nick narrows it using NAICS payroll-% — avoid that; keep the band as a
  tier policy and let D1 carry any NAICS refinement.

### D4. Give GPT the revenue-derived required-capacity as explicit context (voluntary staffing target)

- **Entails:** surface, per quarter, the capacity the revenue plan *requires*
  (`required_capacity = revenue ÷ (price × utilization)`, the inverse of the revenue formula
  [finmo_bridge.py:634](../../python/client_intake_and_finmo/finmo_bridge.py#L634)) and, given the
  chosen productivity, the *implied* supporting FTE — as context GPT can staff toward. This is the
  Fix #2 math used as a *hint*, not a hard derivation.
- **Needle:** **high.** Gives GPT the exact quantity Part B says it's missing, in capacity/FTE
  units, without inverting the pipeline.
- **Risk/blast radius:** low–medium (context + builder; no overwrite change). But it surfaces the
  productivity dependency: the implied FTE is only meaningful once productivity is chosen — a
  chicken/egg that D1's dollar-based anchor avoids. Best shown as a range over plausible
  productivity, or after a first-pass productivity guess.
- **Lighter-touch?** Yes — context only.
- **Data filter:** **Own revenue plan only** (revenue, price, utilization are all intake/model
  values). No external dependency. This is the most self-contained strong option.

### D5. Add an authoring-time check on the IMPLIED (not declared) payroll/revenue

- **Entails:** extend `_check_band_violations` (C.2) to compute the per-quarter payroll/revenue
  the FTE grid actually implies and warn/fail in-session if it's outside band — closing the gap
  where today only the self-declared target is checked.
- **Needle:** **medium.** Stops GPT declaring a compliant target while authoring an
  off-target grid. Complements D3 by moving the real check into the session.
- **Risk/blast radius:** medium (authoring-loop logic; retry budget interplay).
- **Lighter-touch?** Partial.
- **Data filter:** Own revenue plan + the policy band (own-data). Sustainable.

### D6 (noted, not preferred). NAICS-cohort payroll-% as the anchor source

- Using the `derived_CBP_SOI` payroll-% band (Part E) as the X% in D1. **De-preferred:** it
  covers only ~148/388 NAICS-6 codes and frequently cascades to NAICS-3
  ([phase_9_naics_coverage_audit.md:232,243](phase_9_naics_coverage_audit.md)). Acceptable only
  as an *optional refinement* over the own-data anchor, never the sole source.

---

## Part E — NAICS-keyed datasets we could anchor to (honest coverage assessment)

The objective: find a **sustainable, well-populated NAICS-keyed source** to back a
revenue-grounded staffing/payroll figure from. Verdict up front: **the employment / payroll /
wage side is robustly NAICS-covered; the REVENUE side is the perennial weak link.** Any
external "revenue → headcount" ratio is bottlenecked by its revenue denominator, which is exactly
the wall Fix #2 hit. The grounding that survives uses the business's OWN revenue plus a
well-covered NAICS employment/wage quantity.

### E.1 Datasets already wired into this repo

| Dataset | Loader / table | NAICS-keyed quantities | Coverage / reliability |
|---|---|---|---|
| **BLS OEWS** | `bls_employment_wages_loader.py` → `oews_state_wages` ([cols incl. `naics`, `occ_code`, `tot_emp`, `a_mean`](../../python/data_pull/bls_employment_wages_loader.py#L166-L174)) | occupation **employment counts** (`tot_emp`) and **annual wages** (`a_mean`/`a_median`) by **NAICS industry × occupation** | **Strong.** Near-complete at NAICS 3–4 digit national industry files; 6-digit partial (suppression in small cells). Already the wage backbone. Gives **staffing MIX + wage levels**, no revenue. |
| **Census CBP 2022** | `cbp_2022_raw.py` → `cbp_2022_raw` ([cols `naics, estab, pay_ann, pay_q1, emp`](../../python/data_pull/cbp_2022_raw.py#L60)) | **establishments**, **employment**, **annual payroll** by NAICS (by state) | **Strong (near-census of employer establishments).** NAICS to 6-digit with cell suppression for small (state×NAICS-6) cells; national×NAICS-6 very complete. Gives **payroll/employee** and **employees/establishment** robustly. No revenue. |
| **IRS SOI** | `SOI_corporate_tax_returns.py` | business **receipts/revenue** by NAICS | **Spotty / sample-based.** This is the weak denominator behind `derived_CBP_SOI` payroll-% (only ~148/388 NAICS-6 resolve; rest cascade up — [coverage audit §4.2](phase_9_naics_coverage_audit.md)). |
| **Census BDS** | `load_bds_firm_tables.py` | firm/establishment/job counts & dynamics by sector | Census-based, reliable, but **coarse NAICS** (sector/3–4 digit) and **no revenue**. Useful for firm-size priors, not revenue-per-head. |
| **Alpha + EDGAR** | `industry_metrics_alpha` / `industry_metrics_edgar` | public-company financial ratios (margins, etc.) | Good NAICS-6 breadth post-expansion (473 codes), but **public-company-skewed** (revenue scale ≫ a typical SMB plan); revenue is the firms' own, not an industry-representative figure. |
| **SBA 7(a)** | `sba_load_7a.py` | loan-level (sometimes revenue/jobs) by NAICS | Lender-selected sample; not industry-representative. |

### E.2 Robust public NAICS datasets NOT yet in the repo (candidates)

(General public-data knowledge; characteristics stated honestly, not from this codebase.)

| Candidate | What it carries by NAICS | Coverage / reliability | Revenue? |
|---|---|---|---|
| **BLS QCEW** (Quarterly Census of Employment and Wages) | establishment counts, **monthly employment**, **total quarterly wages**, avg weekly wage | **Best-in-class.** A near-census of all UI-covered employment (~95%+ of jobs), NAICS to 6-digit, quarterly, national/state/county. Disclosure suppression mainly at fine geography×NAICS. **The authoritative employment+payroll source.** | **No** |
| **Census SUSB** (Statistics of U.S. Businesses) | employment, annual payroll, establishments, **firms** by NAICS **and employment-size class** | Strong, annual, census-based; NAICS to 6-digit. Size-class breakdown is uniquely useful for matching an SMB plan to like-sized firms. Receipts only in economic-census years. | **Only every 5 yrs** |
| **Census Economic Census** | **receipts/revenue**, payroll, employment, establishments by NAICS to 6-digit | The one broad **revenue-by-NAICS** source. But **every 5 years** (latest 2022, released staggered), with suppression at fine cells → stale + gappy. | **Yes (5-yearly)** |
| **Census County/Economic data → revenue-per-employee** | derivable: Econ Census receipts ÷ employment | Good NAICS-6 for many sectors **in census years**; the only defensible external **revenue-per-employee** by detailed NAICS. | Yes, but infrequent |

### E.3 Honest verdict

- **For headcount/payroll/wage by NAICS: yes, robust sources exist and are sustainable.** CBP
  (already loaded) and QCEW/SUSB (loadable) give establishment counts, employment, and payroll at
  NAICS-6 with near-census reliability and annual/quarterly refresh. OEWS (loaded) gives the
  occupation mix and wage levels. **Average wage per worker and employees-per-establishment by
  NAICS are well-populated and sustainable.**
- **For the revenue linkage: no sustainable, well-covered, frequently-refreshed NAICS-6 source
  exists.** Receipts-by-NAICS comes from IRS SOI (sample, sparse — the audit's spotty side) or
  the Economic Census (5-yearly, suppressed). So a *revenue-per-employee* or *payroll-%-of-revenue*
  benchmark at fine NAICS is fundamentally limited by the revenue denominator. Adding QCEW/SUSB
  improves the employment/payroll side but **does not fix the revenue side** — it would still need
  SOI/Econ-Census revenue to close the loop.
- **Therefore the sustainable grounding is the inversion of the original instinct:** don't import
  external revenue at all. Use the **business's OWN revenue plan** (always present, intake-anchored
  per the spec) as the revenue side, and use well-covered NAICS data only for the conversion
  *factors that are robust*: average wage per worker (CBP/OEWS) and, where it exists, a payroll-%
  band — with graceful fallback to the policy tier band. This is exactly the data filter that makes
  options **D1 and D4** preferred and **D6** de-preferred.
- **Coarser NAICS is the realistic compromise for any external ratio.** Where a NAICS-6
  payroll-% or revenue-per-employee is absent, a NAICS-3 figure (decent coverage: payroll-% has
  64 NAICS-3 codes; the cascade already does this) is a defensible, sustainable fallback — but it
  should *refine* an own-data anchor, not replace it.

---

## Part F — Honest flags

- **Moves the needle (substantive):** **D1** (revenue-implied payroll-budget anchor from own
  revenue × tier-band midpoint) and **D4** (revenue-derived required-capacity / implied-FTE as
  context). These put the missing quantity in front of GPT in the units it authors, using only the
  business's own plan. **D2** (prompt-to-justify) compounds them.
- **Cosmetic unless paired:** **D3** (tighten/relocate the band) and **D5** (implied-ratio
  authoring check) tighten the payroll/revenue *ratio* and pull via productivity rescaling — they
  make the number look aligned without making GPT *reason* from revenue. Worth doing **with** D1/D4,
  not instead of them.
- **Executive-layer dependence:** all prompt/context options (D1, D2, D4) only bite if the live
  GPT authoring path honors them. Authoring is migrating to the amalgamated "Executive" session
  (`set_payroll_schedule`); these options should be specced against that path, not the deprecated
  tool-loop. The *check/band* options (D3, D5) are Python-side and independent of the GPT layer.
- **Doctrine tension (must reconcile):** the current context rules explicitly tell GPT revenue is
  *downstream* of FTE (B.2). Any "staff toward revenue" instruction (D2/D4) must reword that
  framing or GPT receives contradictory guidance. This is a wording reconciliation, not a
  structural change — but it has to be done deliberately.
- **Is the current process already near-best without new data?** For the *band/check* machinery —
  largely yes; the bands are a policy choice and the cohort data behind a tighter NAICS band is too
  spotty to lean on. The genuine, un-exploited headroom is **context/prompt grounding from the
  business's own revenue** (D1/D4), which needs **no new data at all**. The honest conclusion: the
  biggest available improvement is not a new dataset — it's converting the revenue GPT *already
  sees* into a headcount/payroll reference and asking it to staff toward it.

---

## Part G — Hard-rule compliance

Research only — no code, no implementation, no act-recommendation. Every codebase claim is
grounded in file:line; external public-dataset coverage in Part E.2 is labeled as general
public-data knowledge, stated with its real limitations (suppression, sample-vs-census, refresh
cadence). Options are described and assessed, not selected. The data filter is applied throughout:
own-revenue-plan grounding (D1/D4) is preferred over spotty external cohort data (D6 de-preferred),
per Nick's objection that cohort data isn't sustainable.
