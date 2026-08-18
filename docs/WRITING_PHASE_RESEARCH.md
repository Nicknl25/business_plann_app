# THE WRITING PHASE — research for Nick's ruling (2026-08-18)

Status: RESEARCH ONLY. NOTHING BUILT, nothing seeded, no code or DB changes.
Traced against HEAD `101f1b3` (intake-stable) and the live MySQL DB
(`biz_plan_revert`, 78 tables). Real artifacts read: Millgate draft
`2e198cbf` / runs `3d4e1de9`+`5186501f`, Kestrelbrook `fd3d1b02` / run
`6055904d`, Bellweather run `30657ccb`, Nine Fathom `6d2823db` (runs
`10a81085`→`f44ff3f1`→`e8a03731`), Bellweather workbook built 08-17 21:36 on
the current builder. Line numbers are HEAD.

Six areas (Nick's five + Area 6 pipeline hook added mid-brief). Each: (a)
findings, (b) what we already have, (c) what building it requires, (d) open
questions for ruling. Ends with a recommended BUILD SEQUENCE.

Design premise confirmed up front: **the plan is mostly a rendering job for
the numbers and a grounded-rework job for the prose — and there is no writing
phase of any kind today** (no docx/narrative module, no route, no stage row,
`financial_story` writer removed, `planning_run_json.gpt_narrative` = None).
`context/system_overview.md:5,15,40-42` names "writing" as the pipeline's end
with no code pointer.

---

## AREA 1 — WHAT A PROFESSIONAL (FUNDABLE) BUSINESS PLAN IS

### (a) Findings — the real anatomy

The lender/investor-grade plan (SBA lender packet, bank credit-memo companion,
SCORE/SBDC "traditional plan") is remarkably stable in shape. The reader is a
credit officer or an investor doing diligence; they read the Executive Summary
and the Financials first, then spot-check the middle sections for internal
consistency.

| # | Section | Purpose / what the reader wants | Length |
|---|---|---|---|
| 0 | **Title page** | Legal name, address, owner + contact, date, "prepared for", confidentiality line, version stamp | 1 p |
| 0b | **Table of contents** | Page-numbered; lists figures/exhibits | 1 p |
| 1 | **Executive Summary** | The whole case in one page: what the business is, who it serves, why it wins, the ask (amount/use/term), headline numbers (Y1 revenue, Y1/Y3 EBITDA, break-even point, coverage). Written LAST, read FIRST. Lender rule: if the summary doesn't state the ask and how it's repaid, the packet is incomplete. | 1–2 pp |
| 2 | **Company / Business Description** | Legal structure, location, stage (startup vs operating), mission, problem solved, ownership, history/milestones, the owner's stated goal | 1–2 pp |
| 3 | **Market Analysis** | Industry overview (NAICS-defined: size, growth, trend, seasonality, regulation), target market (geography, demographics, segment size — census-grounded), competitive landscape (density, competitor types, positioning), differentiator. Reader wants *cited* data and a target market plausibly larger than the revenue plan needs. | 3–5 pp |
| 4 | **Organization & Management** | Ownership, org chart, owner/manager experience, key hires + timing, headcount plan, advisors, compensation. Lender reads management depth as repayment character. | 1–3 pp |
| 5 | **Products / Services** | Per line: what is sold, unit/pricing model, cost of delivery (COGS basis), capacity, seasonality, suppliers, licenses. Reader checks price × capacity × utilization reconciles to the revenue model. | 1–3 pp |
| 6 | **Marketing & Sales** | Positioning, channels, acquisition, pricing strategy, retention, marketing budget as % of revenue. Reader ties this to the marketing line in the P&L. | 1–2 pp |
| 7 | **Funding Request / Capital Plan** | Amount, type (term/LOC/SBA 7(a)/equity), sources & uses, collateral, owner injection, term/rate, repayment source (DSCR). Only when funding is sought; otherwise "Capital plan". | 1–2 pp |
| 8 | **Financial Projections** | 3–5 yr (we have 20 quarters = 5 yrs) P&L, BS, CF; quarterly Y1–Y2 then annual is the norm; **assumptions page** (price, capacity, utilization, COGS %, payroll, rent, growth — sourced); ratios (GM %, EBITDA %, DSCR); **break-even analysis**; charts. Reader looks for: assumptions stated & sourced, narrative numbers == statement numbers, no hockey stick without a driver, tax/depreciation present, debt service covered. | 4–8 pp + appendix |
| 9 | **Appendix** | Full statements, resumes, licenses, leases, LOIs, data-source tables, methodology, glossary | as needed |

Total body 15–30 pages for a small business; longer is a red flag.

**What makes it credible to a lender (vs. a template):**
1. *Specificity* — named location, named products, actual prices, actual rent, actual staffing: the client's own facts.
2. *Grounding* — every market/industry claim has a source and a vintage (Census/BLS/BDS/FRED/SBA are exactly the right kind — and we have them, Area 2B).
3. *Internal consistency* — narrative numbers ARE the statement numbers (Y1 revenue in the summary = P&L Y1; headcount in §4 = payroll in §8; marketing % in §6 = marketing line in §8). This is the #1 place templates fail and the place our pipeline is structurally strong (one engine, one home per number — the universal-engine law).
4. *Honest assumptions* — stated, sourced, and where the modeler departed from the owner's own figure it says so and why (Area 3, the founding principle).
5. *Repayment logic* — break-even, cash trough, coverage. Even for non-borrowers these are what an experienced reader hunts for (Area 4).
6. *Professional finish* — TOC, page numbers, consistent headings, tables for numbers, captioned charts with units, appendix instead of a bloated body.

**Formatting conventions:** title page → TOC → numbered H1/H2 body; running header (business name) and footer ("Confidential · page X of Y · version/date"); tables for any ≥3 numbers; charts captioned "Figure n — …" and referenced in text; currency rounded consistently ($ thousands in narrative, exact in appendix); one font family, 11pt, 1" margins; 20-quarter statements as landscape appendix pages.

**Charts that matter (and where they go):** revenue projection (quarterly, stacked by line for multi-line) — §8 opening / summary mini; break-even chart — §8 break-even subsection; ending-cash trend with the trough marked — §8/§7; margin trends (GM %, EBITDA % over 20 quarters with the industry band shaded) — §8; cost structure (Y1 opex composition) — §8 assumptions; optional headcount ramp (§4), sources & uses (§7), market-size funnel (§3). These are exactly the Dashboard charts in Area 5 — the document should render the SAME series the workbook charts, so the two artifacts never disagree.

### (b) What we already have
- §8 body: FINMO's 20-quarter P&L/BS/CF, drivers, bands, diagnostics — a rendering job (`intake_consult_drafts.finmo_json`, `model_input_json`).
- §2/§4/§5/§6 raw material: the intake narrative fields (Area 2A).
- §3: real government reference data (Area 2B) — grounded, citable, some of it already joined per client (marketing_model_json carries ACS/CBP counts).
- §7 partially: `financials_json.funding_preference/cash_strategy`, `debt_schedule`, SBA rate policy, cash-pass prose (Areas 3/6) — sources & uses is derivable.
- NOT present: break-even (Area 4), charts (Area 5), any renderer, any disclosure registry (Area 3), licenses/leases (client attachments), and the plan's own "goal" as a discrete field (it lives in `operating_model_json.milestones` + `primary_growth_lever`; there is no `goal` column — see 2A).

### (c) Recommended section structure for OUR plan (mapped to what we can populate)
1. Title page + TOC — business name, address, owner, date, run/version id.
2. Executive Summary — engine headline numbers + goal + one-paragraph business + ask; **generated last** from the other sections.
3. The Business — `business_description_summary`, milestones/goal, legal entity, stage, location, start date.
4. Market & Industry — NAICS industry overview (industry_growth_table, BDS survival/formation, SOI benchmarks), target market (`target_market_json` + ACS for the ZIP/county), competition (CBP density + `competitive_advantage`).
5. Products & Services (per line) — `lob_models[].products[]`: what's sold, unit, price, cadence, capacity, utilization, cost-of-delivery basis; one subsection per line for multi-line.
6. Operations & Organization — `fulfillment_json`, ops delivery facts, `people_json.people[].paragraph`, `payroll_headcount` schedule, OEWS regional wage benchmarks.
7. Marketing & Sales — `marketing_plan_summary` + `marketing_model_json` (reachable market, expected customers, capture rate) + marketing line/ratio + fitted band context.
8. Financial Plan — assumptions page (drivers **with provenance/disclosure notes**), Y1–Y2 quarterly + Y3–Y5 annual P&L/BS/CF summaries, ratios, **break-even (Area 4)**, charts (Area 5), capital plan (sources & uses, debt schedule, DSCR).
9. Assumptions & Disclosures — the honest page: every departure from the client's stated figure in plain language (Area 3 core) + realism-memo tensions.
10. Appendix — full 20-quarter statements, data sources & vintages, methodology, intake fact sheet.

### (d) Open questions for ruling
- **Q1.1** Length target: full lender packet (~20 pp), or plan body + the workbook as the financial appendix?
- **Q1.2** §7 always present, or conditional on funding actually being sought (`funding_preference` / new debt in the model)?
- **Q1.3** §9 Disclosures as its own section (recommended — it is the founding principle) or folded into the §8 assumptions page?
- **Q1.4** Output format: `.docx` first (editable; python-docx, NOT installed today — `python/requirements.txt` has only openpyxl), PDF derived later? Recommendation: docx first.

---

## AREA 2 — WHAT WE ALREADY HAVE TO BUILD FROM (the inventory)

### 2A — The client's own narrative captured in intake

**One canonical table: `intake_consult_drafts`** (97 cols, 6,718 rows). The three
per-section draft tables (`intake_target_market_drafts`,
`intake_people_capability_drafts`, `intake_financials_drafts`) hold **0 rows** —
legacy. Real completed intakes: `submitted_at IS NOT NULL` (status is
overwritten back to `in_progress` by `persist_post_intake_execution_state`,
`intake_consult_draft.py:2751`, so `status` is not a completion signal).

**LIVE narrative/text columns** (populated on all 4 recent real drafts):

| Column | What's in it | Verbatim / structured / GPT-authored | Written by | Feeds |
|---|---|---|---|---|
| `business_name, business_address, address_street/city/state/zip/country, business_start_date` | IntakeForm identity | **client-entered** ("Millgate Press", "890 Main St, Dubuque, IA 52001", "2015-09-14") | `intake_consult_draft.py:2058-2080` ← `frontend/src/intake_form/schema.ts` | Title, §2 |
| **`messages_json`** | full chat, `[{"role","content"}]` — Millgate 97 turns (49 assistant / 48 user); no stage/timestamp keys | **user turns VERBATIM**; assistant turns naturalized + fact-template rendered at persist | `intake_consult_draft.py:1838 _naturalize_assistant_messages`, `:1689 _render_messages_for_storage`, write `:1937` | Appendix; the ONLY complete verbatim client voice. Stage per turn recoverable via `run_vitals_turns.turn_index` (== list index; Millgate: ops 17, market 4, people 7, financials 21) |
| **`operating_model_json`** | `consumer_type, business_type, business_stage, business_description_summary, lob_models[{lob_name, products[{product_name, unit_name, unit_description, unit_cadence, units_per_week_capacity, units_per_period_capacity, operating_periods_per_year, utilization_rate, unit_price, cogs_percent_of_line_revenue, origin}]}], unit_description, shipping_method, sales_modality, geographic_scope/coverage, countries[], milestones[{description, timing, timing_months_max}], capacity_driver, primary_growth_lever, legal_entity, confidence, line_split_confidence, split_rationale, competitive_advantage, business_naics_6, stream_discovery{ask_text, candidates[{label, commonality, answer, answered_from, removed_from}], survivors, dropped}` | structured GPT-normalized; `business_description_summary` = **GPT one paragraph** (prompt `intake_consultant.py:694`); `competitive_advantage` = **client's words when stated, else GPT proposal the client confirmed** (`intake_consultant.py:384`, `intake_consult.py:13056`); `milestones[].description` GPT-normalized from client ("Increase average production volume from ~21 jobs per week to ~26…"); `stream_discovery.*.answered_from/removed_from` = **client verbatim** | `api_handlers/intake_consult.py:20938 consultant_finalize` (`intake_consultant.py:648`), summary `:21024`, competitive_advantage `:17095/:21033`, stream_discovery `:11721-11756` | §2, §5, §3 (differentiator), Exec Summary (goal = milestones + primary_growth_lever) |
| **`target_market_json`** | `consumer_type, gender_age_intent[], income_intent[], selections[{segment, acs_codes[]}], b2b_industry_terms[] ("local banks and credit unions", "local law offices"), b2b_naics_6[], b2b_size_bands[], b2b_age_bands[], marketing_plan_summary, confidence` | structured; `marketing_plan_summary` = **GPT two paragraphs** (positioning + ≤5 channels; ends with the fixed sentence "…will be expanded into a detailed execution-level marketing plan in the full written business plan" — prompt `target_market_consultant.py:785`, i.e. intake already PROMISES the writing phase) | `intake_consult.py:21148` (`target_market_consultant.py:747`); `target_market_summary` popped `:21157` | §3, §6 |
| **`people_json`** | `people[{full_name, role_title, primary_responsibilities, relevant_background, experience_years, why_strengthens_business, paragraph, annual_wage, wage_source}], inferred_roles[], business_naics_6, rest_of_team_payroll_year1` | GPT-authored bios from client answers ("22 years of hands-on commercial printing experience… two-year graphic arts certificate"); `paragraph` = ready-to-use bio; wages client-stated or OEWS | `intake_consult.py:21229` (`people_capability_consultant.py:372`), OEWS wages `:21245`; `key_people_summary` popped `:21278` | §4 |
| **`financials_json`** | client-stated scalars (`current_revenue, current_payroll, owner_compensation, cogs_percent_of_revenue, current_cogs, marketing_total_year1, monthly_rent_expense, other_operating_expense, current_num_employees, current_capex, initial_assets/lease/equity, total_debt_outstanding, other_monthly_debt_payments, annual_interest/principal_payment, cash_on_hand, ar/ap/inventory_balance, cash_strategy, funding_preference`) + `payroll_basis_people_roles[]` + engine stamps `_cogs_baseline_resolution` (`cogs_basis_rationale`) and `_coherence` (`margin_band_judgment.{rationale, margin_character}, demand_response.{rationale, price_response.basis, marketing_response.basis, volume_headroom.basis}, essentials_response, eval.binding.sentence, converged_suffix, judged_growth, walls, roadmap, bounds`) | **client-stated numbers** + GPT judgment prose (engine-voiced) + ONE client-facing paragraph (`converged_suffix`) | financials flow via `_apply_scoped_patch`; `_coherence` by `intake_coherence/section.py` (352, 640, 705, 2420); `_cogs_baseline_resolution` `intake_consult.py:1281` | §7, §8, §9 |
| `fulfillment_json` | `{time, personnel}` short GPT phrases ("Jobs scheduled into weekly press time with turnaround from a few days to a few weeks…") | GPT-authored | `intake_consult.py:13802` | §6 Operations |
| **`marketing_model_json`** | Census/CBP counts (`geography_basis, b2b_basis_counts`), `reachable_market`, `expected_customers_or_clients_year1`, `capture_rate_year1`, `marketing_intensity`, `baseline_marketing`, `marketing_basis_summary` (4-paragraph GPT rationale) | structured + GPT prose | `intake_consult.py:5077 _compute_marketing_model_json`, `:16661` | §3 market size, §6 |
| `financials_year1_json` | per-LOB/product Year-1 revenue rollup | structured | intake_consult.py | §5, §8 |
| `planning_context_summary_json` | compact business/operating/market/people/financial/marketing profiles + `stage_ramp_contract`, r_and_d rationale, planning_mode, `year1_anchor_summary`, `selected_cash_strategy` | copies of the above (convenient single read) | `post_intake_convergence/runtime.py:401` | all sections (starting point for a "plan brief") |
| `intake_submissions` (row per submit) | `first_name, last_name, email_address, phone_number, how_did_you_hear, business_name, address, business_start_date, business_description_summary, legal_entity, business_type, naics_code, consumer_type, unit_name/description, shipping_method, geographic_coverage, milestones (JSON), primary_growth_lever, target_market_b2b_*` | client-typed identity + draft-derived copies; `key_people_summary` / `target_market_summary` **always empty** (popped before persist); `product_keywords` **dropped** (no column, `intake_submission.py:100`) | `financials.py:300` → `intake_submit_service.py:221` → `intake_submission.py` | Title/§2 contact |

**DEAD / never populated (do not design against these):** `revenue_model_json`,
`cogs_model_json`, `milestones_model_json`, `gna_model_json`,
`headcount_model_json`, `customer_model_json`, `operating_structure_json`,
`fulfillment_model_json` — **0 rows ever** (schema-drift leftovers, not in the
CREATE at `intake_consult_draft.py:1017`); `financial_story` — 120 stale rows
(last 2026-05-07 NexGen, `financial_story_v1` lender-narrative shape), **writer
removed from HEAD** (setter `intake_consult_draft.py:2027` has no caller; sole
reader `post_intake_resolution_state/state.py:269`); `planning_run_json.
gpt_narrative` = None; `app_agents_run_json`, `normalized_traits_json`,
`benchmark_payload_json`, `forecast_*` — legacy engine state, 0 on recent rows.
There is **no `goal` and no `business_description` column** — those live inside
`operating_model_json` (`milestones` + `primary_growth_lever`; `business_
description_summary`).

**Where the client's VERBATIM voice lives, exactly:** `messages_json` user
turns; `stream_discovery.candidates[].answered_from/removed_from`;
`competitive_advantage` (when client-stated); IntakeForm identity fields.
Everything else is GPT-normalized structure or GPT-authored prose already
template-rendered to literals — with at least one observed blank-slot artifact
(Millgate `business_description_summary`: "typical utilization around ." —
an unrendered `{{fact:…}}`). Generation must treat these summaries as
*sources to rework*, not as ship-ready copy.

### 2B — The government / market data warehouse

78 tables: 35 reference/gov, 43 app-operational. Geography today: address ZIP →
`zip_county_crosswalk` → county/state (`intake_consult.py:4347
_marketing_normalized_geography`); NAICS: `operating_model_json.business_naics_6`
via `business_type_naics.py:26` exact token match on `naics_master.business_types`.
No tract/CBSA/MSA resolution at runtime.

| Table | Contents | Keying | Rows / vintage | Current consumers | Plan section it can ground |
|---|---|---|---|---|---|
| **naics_master** | NAICS hierarchy 2–6 digit, titles, GPT `business_types` list | naics_code | 2,125 (1,012 six-digit) | `business_type_naics.py:26`; `business_types.py:75`; `target_market.py:802` | §3 industry naming/hierarchy |
| **industry_growth_table** | industry aggregate quarterly series (revenue growth, margins, sga/rnd/cogs %, dso/dpo, capex, roa/roe) | naics 6-digit (388), quarter | 21,297; 2015-01→2025-11 | `intake_consult.py:1308 _compute_cogs_baseline`; baseline loader | §3 industry growth trend, §8 assumption context |
| **industry_metrics_alpha / _edgar / _raw** | per-firm quarterly ratios (growth, GM/EBITDA/NI margins, cost ratios, WC days, leverage) w/ cap_category | naics 6 (+ prefix LIKE), period | 137k / 100k / 147k; through 2026-04 | `post_intake_industry_baseline/lookup.py:345`, `cohort_band_resolver.py:133,456` → `post_intake_cohort_bands` | §3/§8 "businesses like yours run X–Y%" (the bands the plan was judged against) |
| **industry_growth_index** | per (naics, level) firm_count/quarter_count/trust | naics+level | 1,014 | **none** | §3 confidence footnote |
| **bds_firm_age / bds_firm_size** | Census BDS: firms, estabs, emp, entry/exit rates, job creation, deaths by age/size bucket | (year, naics4, bucket); national | 159k / 132k; 1978–2023 | `intake_consult.py:4602-4756` (B2B signals); loader stage_ramp metrics (`startup_year1_exit_rate, mature_exit_rate…`) | §3 industry survival / formation / growth |
| **cbp_2022_raw** | County Business Patterns: estab, emp, annual pay by NAICS × **state only** | (state_fips, naics 2–6) | 92,927; 2022 | `intake_consult.py:4563-4681 _build_b2b_marketing_basis`; loader (emp/estab, avg wage) | §3 competitive density (state), B2B market size, §4 avg pay |
| **acs_zip_2022_part1 / part2** | ACS 5-yr: pop, median age, median HH income, income brackets, education, households, housing, race, labor force; sex×age | zcta | 33,774 each; ACS 2022 | `intake_consult.py:4193-4274` (weighted totals) → B2C reachable market | §3 target-market demographics & size |
| **target_market_mapping** | 83 ACS codes → segment/description | acs_code | 83 | `target_market.py:151,342,731`; `intake_consult.py:13812` | §3 segment definitions |
| **zip_county_crosswalk** | ZCTA↔county with pop/HU shares | (zcta, state, county) | 44,410 | `intake_consult.py:4158-4274` | geography resolver |
| **hud_zip_county/cbsa/tract_092025** | HUD-USPS crosswalks (res/bus ratios) | zip | 55k / 48k / 189k; 09/2025 | **none** | newer geography incl. CBSA/tract (unused) |
| **oews_state_wages** | BLS OEWS wage percentiles + employment by occupation × area; NAICS detail only on US rows; state rows cross-industry | (prim_state, naics, occ_code) | 414,437; May 2024 values | `people_roles.py:396-482`; `post_intake_headcount/schedule.py:925-1620`; `initial_grid/runner.py:2335` | §4 regional wages by role, §8 payroll assumption grounding |
| **sba_loan_7a_raw** | SBA 7(a) FOIA loans: amount, guarantee, rate, term, NAICS, state/county/zip, business age, status, charge-offs, jobs supported | naics6, ProjectState/County, BorrZip | 347,514; FY2020–2025 | `finmo_bridge.py:1126` (median rate → debt rate); loader (typical size/term/rate) | §7 loan size/term/rate benchmarks, lender names, charge-off context |
| **soi_corporate_tax_returns** | IRS SOI by industry: receipts, COGS, NI, tax, assets, net worth, depreciation | naics 2–4 (243 rows) | TY2020 | loader only (effective tax rate, cogs %, D&A %, PPE %, debt/equity) | §8 tax & structure benchmarks |
| **fred_macro_quarterly** | GDP, CPI, PCE, YoY inflation | quarter | 39; 2015Q4–2025Q2 | **none** | §3 macro context |
| **post_intake_industry_baseline_lookup** (+ metric_registry, coverage_audit) | derived min/target/max bands for 49 metric_keys, per naics level, w/ source + year + derivation | (naics, level, metric_key, source) | 47,700 | `lookup.py:193` ← finmo_bridge, labor_basis, contracts, realism, cascade… | §8 assumptions ("industry band"), §3 |
| **post_intake_cohort_bands / fitted_bands** | per-run resolved bands & fitted curves | (draft_id, planning_run_id, lever) | 2,068 / 746 | solver, evaluate_plan, stage_ramp | §8/§9 "the bands THIS plan was judged against" |
| alpha_data, sec_edgar_facts, alpha_match_naics_industry, ticker_metadata, earnings_calendar | raw upstream (3-statements, XBRL facts, ticker→NAICS) | symbol/cik | 138k / 4.3M / 3.7k | loaders only | (upstream) |
| business_types, industry_types, industry_mapping_lookup, post_intake_r_and_d_applicability_lookup | display/mapping | 3-digit | small | mostly dead / API pickers | — |

**Not present (don't assume):** no Google Places / Yelp / competitor tables
(the `google_*`/`overpass_*` scripts are experiments writing no table); no
county-level CBP; no consultant-context seed tables.

**Caveats for the writing phase:** CBP is state-level (no county density);
OEWS industry-specific wages are national only; SOI is TY2020; the loader
labels OEWS "2023" but values are May 2024. Every cited figure needs its
vintage in the appendix.

### Section-by-section MAP (client narrative + gov data → plan section)

| Plan section | Client narrative (2A) | Gov/market data (2B) | Engine (model) |
|---|---|---|---|
| Exec Summary | `business_description_summary`, `competitive_advantage`, `milestones` + `primary_growth_lever`, `funding_preference` | — | Y1/Y3/Y5 revenue, EBITDA, break-even qtr, cash trough (finmo_json) |
| §2 The Business | identity cols, `legal_entity`, `business_stage`, `business_start_date`, `geographic_scope`, `sales_modality`, `milestones` | naics_master title | — |
| §3 Market & Industry | `target_market_json` segments/terms, `marketing_model_json` reachable market + `marketing_basis_summary`, `competitive_advantage` | industry_growth_table, industry_metrics_* cohort bands, BDS survival, CBP density/pay, ACS demographics, FRED macro, industry_growth_index (confidence) | judged_growth / stage_ramp rationale |
| §4 Org & Mgmt | `people_json.people[].paragraph…`, `inferred_roles`, `payroll_basis_people_roles` | OEWS wages by role/state | `payroll_headcount` schedule, `payroll_provenance` |
| §5 Products & Services | `lob_models[].products[]`, `split_rationale`, `stream_discovery`, `fulfillment_json` | cohort COGS bands | per-line drivers (model_input_json revenue rows) |
| §6 Marketing & Sales | `marketing_plan_summary`, `marketing_model_json` capture/intensity, `marketing_total_year1` | CBP/ACS counts (already in marketing_model_json) | marketing % row, fitted band |
| §7 Funding / Capital | `funding_preference, cash_strategy, total_debt_outstanding, initial_equity, cash_on_hand` | sba_loan_7a_raw benchmarks | `debt_schedule`, `debt_interest_rate_policy`, cash-pass `policy_reasons` |
| §8 Financial Plan | `financials_json` stated scalars (as the "today" column) | baseline_lookup bands, SOI tax | finmo_json pl/bs/cf, model_input_json, break-even (new), charts (new) |
| §9 Disclosures | `_coherence.converged_suffix`, `_coherence.eval` | the bands used | override registry (new, Area 3) |
| Appendix | `messages_json` transcript, `run_vitals_runs.transcript_path` | source & vintage table | acceptance_verdict_json, realism_memo_json, restructuring_log |

### (d) Open questions for ruling
- **Q2.1** Should the writing phase read `post_intake_restructuring_log`, `workbook_deliveries`, `post_intake_run_diagnostics`, `intake_submissions` via joins (all keyed by draft_id/planning_run_id/client_id) — or should a "plan brief" assembler first mirror what it needs onto the draft row? (Recommendation: a read-only brief assembler that JOINS; no new mirrors except the disclosure registry in Area 3.)
- **Q2.2** Which unused warehouse tables get promoted into §3: FRED macro (cheap, national), HUD CBSA crosswalk (enables MSA-level OEWS wages and metro framing), industry_growth_index (confidence footnote)? Each is a small new reader.
- **Q2.3** The dead columns (`revenue_model_json` etc.) and the empty `intake_submissions.key_people_summary/target_market_summary` — delete per the remove-legacy law, or leave (they cost nothing but mislead designers)?

---

## AREA 3 — HOW WE GENERATE THE NARRATIVE (the honesty constraint)

### (a) Findings — the generation approach: grounded rework, not regurgitation

**Nothing today generates plan prose.** The existing client-facing GPT prose
pattern (intake naturalizer, recovery phrasing, coherence suffix) is
sentence-scale and *rephrases* fixed content; nothing composes multi-paragraph
sections. The prompts dir holds only engine-facing prompts
(`prompts/quarter_grid/*`, `realism_memo/*`, `unified_convergence/*`).

The approach that satisfies "not verbatim, not invented" is a **fact-sheet →
section-brief → GPT rework → verify** loop, one section at a time:

1. **Fact sheet (deterministic Python).** For each section, assemble a typed
   brief: the client facts (with source path), the gov-data points (with table
   + vintage), the engine numbers (with finmo/model_input path), and the
   disclosure items (Area 3b). Every fact carries an id (`F12`), a value, and a
   provenance string. This is the "Python proposes structure; GPT critiques/
   words" law applied to writing.
2. **GPT rework (gpt-5.1 via `openai_http.py:266 post_openai_with_retries`,
   response-locked).** System prompt: write section N of a lender-grade plan
   using ONLY the facts in the brief; every sentence that states a fact must
   cite fact ids inline (`[F12]`); numbers copied EXACTLY; no new numbers,
   claims, comparatives, or advice; plain business language; the vocabulary
   ban list; never mechanism-speak (the existing `_coherence_naturalize`
   rules, `intake_consult.py:15964-15996`). Output: prose with citation
   markers.
3. **Verify (deterministic).** (i) every `[Fnn]` resolves to the brief; (ii)
   every money/percent/count token in the prose appears in the brief
   (extends the existing `_MONEY_RE` survival check, `intake_coherence/
   section.py:2639-2652 _safe_naturalize`); (iii) sentence-level "unsupported
   claim" scan — sentences with no citation and a factual predicate get
   flagged; (iv) forbidden-vocabulary lint (extend `Test Files/
   _lint_client_copy.py`'s list to the writing module); (v) no `{{fact:` or
   blank-slot residue (the Millgate "utilization around ." class). Fail →
   regenerate once with the violations listed → still fail → fail-loud (no
   plan ships on substituted judgment; `fail_fast/common.py:105-116`).
4. **Strip markers for the rendered doc, keep them in a machine copy** so the
   document is auditable sentence-by-sentence (and so Cowork's detectors can
   verify a claim traces to a fact).
5. **Rework, not copy:** the brief hands GPT the *facts*, not the client's
   sentences (except where verbatim is the point — a quoted competitive
   advantage or a mission statement, marked as quotation). GPT-authored intake
   summaries (`business_description_summary`, `marketing_plan_summary`,
   `people[].paragraph`) go into the brief as *facts extracted from them*, or
   as "prior draft, may be reworked" — never pasted.

**Fidelity rules already in the system that bind generation** (cite): the
verbatim-figure/marker survival check (`section.py:2639`); the naturalizer's
"keep every $/%/price EXACTLY; no new number/claim/advice; never
'q11/eval/solver/band/constraint'; never 'Year 1'" (`intake_consult.py:15964-
15996`); recovery phrasing "never mention internal field names/systems;
deterministic fallback always" (`recovery_phrasing.py:1-106`); receipts built
from the committed write-set (`capture_receipt.py:1-16,121`); fact-template
"do NOT add new facts or claims" (`template_rewriter.py:80-115`); forbidden
vocabulary pin (`_lint_client_copy.py`, CW-024 #9); client-input authority
per driver (`post_intake_adaptive_planning/policy.py:89-103`); golden rule
"structure from lookup tables, not prompt prose" (`post_intake_foundation/
golden_rule.py`); fail-loud default ON. Every one of these transfers
directly; none needs inventing, only extending to a new module.

### (b) THE DISCLOSURE PRINCIPLE — where the override data lives today

Verified live map (Kestrelbrook `6055904d`, Millgate `3d4e1de9`/`5186501f`):

| # | Override family | Landed value lives (writer) | Client's stated value alongside? | Reason / text? | Draft-reachable w/o join? |
|---|---|---|---|---|---|
| 1 | Cascade tiers V1-V8 / G1-G7 / STAGNATION | `post_intake_restructuring_log.original/proposed/applied_value` (`restructuring_log_table.py:268`); 12,878 rows live; run 6055904d = 32 rows (e.g. id 12295 V1 COGS 0.438→0.345 gpt_confirmed; id 12316 V7 G&A 0.230→0.068 deterministic_floor) | YES `original_value` — but **NULL on Type-B rows** (V3 price / V4 util / V5 capacity) | `reason_code` enum (`reason_codes.py:24-79`, no text field) + `applied_by` + `veto_reason` (GPT→engine) | **NO** — join by planning_run_id; **and** rerun-id drift: Millgate's 32 rows sit under rerun `5186501f`, run `3d4e1de9` has 0; `planning_runs.cascade_landed_tier=0`, `cascade_tiers_attempted_json=NULL` despite the rows. `fetch_restructuring_log` (`:304`) has **no production caller** |
| 2 | SBA interest replacement | `model_input_json.derived_driver_policies.debt_interest_rate_policy` {annual/quarterly rate, source_detail{naics, sample_count, median_rate_pct}} (`finmo_bridge.py:4160-4169`) | stub only (`Interest Rate` values[0] = intake annual/4, `:3662-3665`) — unlabeled | machine keys | yes |
| 3 | Opening-PPE / depreciation | `derived_driver_policies.capex_depreciation_policy` (`finmo_bridge.py:1316-1332`) | YES `client_reported_ppe_stub` + source | keys | yes |
| 4 | Stub-vs-forecast basis (every row) | `sections.*[row].values[0]` = client, `[1..20]` = engine (`finmo_bridge.py:3745-3775`) — verified G&A `[0.253036, 0.0648…]` | implicit column 0 — never labelled | none | yes |
| 5 | Stage-ramp / judged growth | `planning_run_json.stage_ramp_contract` {grid, rationale, decision_source} (`orchestrator.py:5049`); `solver_input.judged_growth` (`initial_grid/runner.py:1751`); intake twin `financials_json._coherence.judged_growth` | no stated growth exists (year1_revenue "advisory") | engineer rationale | yes |
| 6 | Fitted cost bands | `solver_input.fitted_bands/fitted_envelope[_per_q]` (`runner.py:2133-2149`); `post_cascade_completion.fitted_cost_band_grounding` | no (client ratio only in stub cell) | none | yes |
| 7 | Judged floors / executive judgments | `solver_input.margin_band_judgment / wc_judgment / cash_judgment / headcount_coherence` (`runner.py:1073-1336`); `judgment_ledger` = {site:{authored, source}} (`:47`) | headcount_coherence ONLY (`stated_annual_payroll` vs `coherent_annual_payroll`, `right_size_factor`) | GPT `rationale` ≤600 chars, executive voice | yes |
| 8 | Restructure lines / multipliers | `solver_input.restructure_directive` (`searcher.py:1020-1042`: multipliers, revenue_mix, `overall_rationale` ≤900); `repair_guidance_json.restructure` (history, `final_passed`) | implicit (multipliers vs base) | engineer rationale | yes when active |
| 9 | Capacity/utilization stub back-solve | `finmo_bridge.py:3319-3365 stub_scale_factor` — **no stamp anywhere** | only `operating_model_json.lob_models` | none | value yes / provenance no |
| 10 | Payroll roster reconstruction | `solver_input.payroll_provenance` (`headcount/schedule.py:3673-3700`: doctrine, `stated_annual_wages`, `q1_roster_annual_wages`, ratio, band, wage_adaptations); per-role `wage_source` in `payroll_headcount` | **YES** (verified 1,465,000 vs 1,238,170) | doctrine sentence (concept, not decision) | yes |
| 11 | Cash funding policy | `post_cascade_completion.cash_pass.funding_source_policy.policy_reasons[]` (`post_intake_cash/runner.py:1333`) — draft copy only (checkpoint copy lacks `post_cascade_completion`) | `client_funding_preference` present | **YES real English** ("DEBT SERVICEABILITY CEILING: additional debt is capped at $1,353,896…") — engine-voiced, rendered nowhere | yes |
| 12 | R&D applicability | `derived_driver_policies["expenses::Research & Development"].rationale` (`finmo_bridge.py:1090-1097`) | n/a | engineer changelog | yes |
| 13 | G&A solver trim | row `applied_by_target_solver_quarters` (`target_solver.py:586-593`) + log row | stub values[0] only | `target_metric` label | stamp yes / log no |
| 14 | EBITDA-margin tempering | `solver_input.finmo_output_targets.metrics.ebitda_margin`; intake sentence `financials_json._coherence.converged_suffix` (`section.py:2420`; verified "…$189,721 (16.9%)… sits above the 6.0%-14.0%… the full build will temper it back…") | `_coherence.eval.q11.ebitda_margin` | intake sentence is client-facing but **lever-blind** (a forecast, not a disclosure) | yes |
| 15 | Phase-B lever search | `post_cascade_completion.phase_b_lever_search.revenue_moves_before_after {driver:{q1/q11/q20:[before,after]}}` (`orchestrator.py:4043-4053`); `payroll_lever` (`:3743`); `ceilings` (`:3510`) | before = pre-search state, not stated | engineer note | yes |
| 16 | Labor scaling post-solver | `post_cascade_completion.labor_scaling_post_solver.rationale` (`orchestrator.py:3051`) | no | GPT rationale (engineer-addressed) | yes |
| 17 | Balance-sheet WC seed | `derived_driver_policies.balance_sheet_contextual_seed.rationale` (`contextual_seed.py:547-559`) | Q0 anchors | engineer text | yes |
| 18 | Per-driver authority doctrine | `planning_run_json.adaptive_policy.client_input_authority` (`policy.py:89-103`: capacity/price/utilization `strong_if_plausible`; year1_revenue/rent/marketing `advisory`; current_payroll `context_only`) | n/a | codes | yes |
| 19 | Verdict / realism / acceptance | `planning_runs.acceptance_verdict_json` (18 checks), `realism_memo_json` (855 KB machine) | no | check names | run row: 1 join |

**Bottom line:** ~17 of 19 families are reachable from the draft row for
free but arrive as machine keys; the ONE record that holds stated→landed for
the whole cascade (`post_intake_restructuring_log`) is unjoined, partly
valueless (Type-B rows), suffers rerun-id drift, and its reader is test-only.
Zero families carry client-facing prose naming the override. Intake's own
promises ARE stored (`financials_json._coherence.*` + the sentence in
`messages_json`) — the writing phase can and should honor them ("at intake we
said the build would temper the margin; here is what that meant").

### (c) What building the disclosure mechanism requires

**D1 — A single stated→landed registry, values not booleans** (the
`judgment_ledger` shape extended with *what was decided*). One JSON block —
recommended home `planning_run_json.override_registry` (draft-reachable, on
the row every phase already reads) — appended to by every override author
at the moment it moves a number: `{family, lever/row, quarter_scope,
stated_value, stated_source (financials_json path / ops path / "not stated"),
landed_value, landed_source (policy version / band id / log id), reason_code,
evidence {band, cohort n, NAICS level, data table + vintage}, applied_by,
vetoed_by}`. Authors that already have the pair (payroll_provenance,
capex_depreciation_policy, headcount_coherence, cash policy) just write it
through; the silent ones (stub back-solve, SBA rate, fitted bands, stage
ramp, G&A trim, tempering) need a stamp added at their write site (Area 3
table above gives each file:line). Blast radius: touches many post-intake
writers → system-touching, but the stamps are additive metadata (values
unchanged) → the payroll_provenance precedent ("numbers unchanged, chain
stamped") applies; goldens should not move except the model_input contract
allow-list.
**D2 — Mirror the cascade log into the registry** (production reader for
`fetch_restructuring_log`, keyed by the *authoritative* run id incl. reruns;
fix `cascade_landed_tier`/`cascade_tiers_attempted_json` stamping; give
Type-B rows their before/after values or read them from
`phase_b_lever_search.revenue_moves_before_after`).
**D3 — reason_code → client-plain sentence templates** (deterministic
Python, one template per ReasonCode + family, with slots for stated/landed/
evidence). e.g. VIABILITY_BOUND_RELAXED on G&A: "You told us general and
administrative costs run about {stated_pct} of revenue ({stated_$}/quarter).
Businesses like yours in {naics_title} typically run {band_lo}–{band_hi}
({source}, {vintage}); to reach a plan that clears the viability bar we
modeled {landed_pct} from {quarter}, which the plan's own review {confirmed|
overrode}." GPT then reworks the *paragraph* under the Area 3(a) verifier;
the numbers must survive verbatim. This is exactly the tempering-disclosure
shape Nick asked for, generalized.
**D4 — Per-cell "you said / we modeled" labelling of the stub/forecast
boundary** (item 13 of the stub research) — the registry supplies it; the
workbook Model Inputs sheet and the doc assumptions page both render it.
**D5 — Extend the two lints** (`_lint_client_copy.py` MODULES list; the
verbatim-figure verifier) to the writing module.
**D6 — Naturalize the cash `policy_reasons`** through the same verifier
before a client sees them (they're engine-voiced today).

### (d) Open questions for ruling
- **Q3.1** Registry home: `planning_run_json.override_registry` (recommended: draft-reachable, checkpointed… note the checkpoint copy lacks `post_cascade_completion` today) vs a new table `post_intake_override_registry` (queryable, joins like the log). Or both (table = truth, JSON = mirror)?
- **Q3.2** Disclosure granularity in the document: one §9 page listing every family that moved (recommended), or inline footnotes on the assumptions table only, or both?
- **Q3.3** Voice: first-person-plural consultant ("we modeled") vs third-person ("the model uses") — affects every template.
- **Q3.4** Does the writing phase re-quote intake's promise (`converged_suffix`) and reconcile it against what happened, or only disclose from the registry? (Recommendation: both — it closes the loop the client heard.)
- **Q3.5** Sentence-level citation markers kept in a machine copy of the document (recommended, for Cowork/audit) — yes/no?

---

## AREA 4 — BREAK-EVEN ANALYSIS (in the MODEL and the DOCUMENT)

### (a) Findings — methodology
Standard: contribution margin (CM) = price − variable cost per unit; CM ratio
= 1 − variable-cost ratio; **break-even revenue = fixed costs ÷ CM ratio**;
**break-even units = fixed costs ÷ CM per unit**; margin of safety =
(planned revenue − BE revenue) ÷ planned revenue. Multi-line: **weighted/
blended** — BE revenue = fixed ÷ Σ(mix_i × CM_ratio_i) using the plan's
revenue mix; per-line BE units = BE revenue × mix_i ÷ price_i (report both
the blended point and the per-line unit counts, plus a "line-standalone" BE
only if fixed costs can be attributed, which ours cannot). Time dimension:
compute per quarter (fixed costs and mix change with the headcount schedule
and ramp) and report Q1, the first quarter EBITDA ≥ 0 ("break-even quarter"),
and Y1/Y5 annualized. Lender convention is EBITDA-basis (before interest/
depreciation/tax) with a second "cash break-even" line including debt
service; both are derivable.

### (b) What we already have (data present to compute it)
Model semantics (`model_inputs.py:110-119, 215-219, 287-298, 464-505`;
`finmo_model.py:59-118, 449-490`):
- **Per line, per quarter:** `Capacity` (units), `Utilization`, `Unit Price`
  → units = cap×util, revenue = units×price; per-line `COGS %` row when
  every product carries one (multi-line, `derived_driver=per_line_cogs_
  source`), else the blended `expenses::Cost of Goods Sold` ratio.
- **VARIABLE in model semantics (ratio of revenue):** COGS, Marketing, R&D,
  G&A (`value_kind=ratio`).
- **FIXED in model semantics ($/quarter):** `Lease`, `Payroll` (`value_kind=
  direct_number`; payroll from `payroll_headcount` FTE×wage/4).
- **Balance-driven (treat as fixed for BE):** Depreciation (`percent_of_prior_
  ppe` + ROU/20), Interest (avg debt × rate + lease). Taxes are on income —
  excluded from BE.
- **Persisted output:** `finmo_json` (`intake_consult_drafts.finmo_json`,
  written `orchestrator.py:4642`) = `{contract_version:"finmo_output_v1",
  periods[21], accounting_check, pl[13 rows], balance_sheet[19], cash_flow
  [15], quarter_rows[21] (FinmoQuarterResult.to_dict: revenue, cogs, gross_
  profit, marketing, r&d, lease_rent, payroll, g&a, ebitda, interest,
  depreciation, taxes, net_income, cash…)}` (`finmo_bridge.py:806-941
  build_python_finmo_json`). **Per-line revenue/COGS/units are NOT in
  finmo_json** — only the drivers in `model_input_json`.
- **Existing break-even code: ABSENT.** Only adjacent: `_fixed_cost_burden =
  (payroll+lease_rent)/revenue` (`gpt_exhaustion_handler/mini_finmo.py:82`,
  `intake_coherence/evaluator.py:149,195`) and the `near_breakeven` posture
  *label* in the stage-ramp contract (`post_intake_contracts/runner.py:693-
  835`). No `break_even`/`contribution`/`unit_economics` anywhere in
  `python/` or `client_statements_output_excel/`.

So: **BE_revenue_q = (payroll_q + lease_q + depreciation_q + interest_q) ÷
(1 − COGS%_q − Mkt%_q − R&D%_q − G&A%_q)** and per-line units as above are
fully computable from what is persisted, using `quarter_rows` for the fixed
dollars and the ratio rows / per-line COGS % rows for the CM.

**What's missing / approximations to declare:**
1. G&A / marketing / R&D are *variable* in the model even where economically
   fixed (the client's `other_operating_expense` is a $ figure that became a
   ratio) — the BE must say "operating ratios treated as variable, as the
   model does"; an optional "G&A-as-fixed" sensitivity is cheap.
2. No fixed/variable tag beyond `value_kind` (ratio vs direct_number) — the
   computation should key off `value_kind`, not label names, so it survives
   new rows.
3. Payroll is headcount-scheduled (fixed within a quarter, capacity-aware
   across quarters); no per-unit labor, no line attribution → per-line
   *standalone* BE is not honest; blended + per-line units is.
4. Interest/depreciation are balance-driven → "fixed" is an approximation
   (state it).
5. `Interest Rate` semantics mislabeled `percent_of_revenue` at
   `model_inputs.py:114` (cosmetic, but a BE classifier keyed on semantics
   would misfile it — key on label/value_kind).
6. Owner comp is inside payroll (Nick's earlier ruling) — BE includes it,
   which is the lender-correct treatment; say so.

### (c) Where it computes, how it persists, how the document renders it
- **Compute:** a pure post-process in `finmo_bridge.build_python_finmo_json`
  (`finmo_bridge.py:657-941`) — `quarter_rows` and `normalized_model_input`
  are both in scope there — adding **`finmo_json["break_even"]`**: per
  quarter `{fixed_costs, fixed_components{payroll, lease, depreciation,
  interest}, variable_ratio, variable_components{cogs, marketing, r_and_d,
  g_and_a}, cm_ratio, be_revenue, planned_revenue, margin_of_safety,
  per_line[{slot_key, lob, product, price, units_planned, cogs_pct,
  cm_per_unit, mix_share, be_units}]}` + summary `{first_ebitda_positive_
  quarter, q1, y1_annualized, y5_annualized, cash_be_revenue (adds scheduled
  principal)}`. **NOT in `finmo_model.py`** — that is engine math (full
  canary+prove); this is a derived read-out with no feedback into any
  driver, so by the verification law it is spot-check + artifact.
- **Persist:** automatic — the block rides `finmo_json` into
  `intake_consult_drafts.finmo_json` (and the finalize checkpoint).
  Contract note: `FinmoOutputContract` is `extra="ignore"`
  (`workbook_payload_contract.py:197`) so the extra key passes the consumer
  gate and the production builder uses raw `data.finmo_json` (`workbook_
  builder.py:47-58`); but `DraftWorkbookData.from_contract` (`data.py:243`,
  `model_dump`) would DROP it on replay/test paths → the contract needs the
  optional `break_even` field declared.
- **Workbook:** a `Break-Even` sheet (or a block on the Dashboard sheet,
  Area 5) — recommended as its own sheet with **live formulas** referencing
  FINMO/Model Inputs rows (fixed = `=FINMO!payroll+lease+dep+int`, CM =
  `=1-'Model Inputs'!cogs-…`, BE = fixed/CM, per-line units) so it recalcs
  with the model, plus a literal "as-persisted" audit column from
  `finmo_json.break_even` and a Checks tie-out (formula vs persisted).
  Formulas move the R32 formula-grid golden → one re-bless (see Area 5).
- **Document:** §8 break-even subsection renders the persisted block (Q1,
  break-even quarter, Y1, per-line units table, margin of safety) + the
  break-even chart; the prose sentence set is deterministic-templated then
  reworked under the Area 3 verifier.

### (d) Open questions for ruling
- **Q4.1** EBITDA-basis BE as the headline with a cash-BE second line (recommended), or cash-BE only?
- **Q4.2** Treat G&A/marketing/R&D as variable (as the model does — recommended for consistency, with a stated sensitivity) or reclassify G&A as fixed for BE?
- **Q4.3** Own `Break-Even` sheet with formulas (recommended, R32 re-bless once) vs literal-only block on the Dashboard (R32-neutral, but not live)?
- **Q4.4** Report per-line BE units on the blended mix only (honest) — confirm we do NOT report line-standalone BE (would require payroll attribution we don't have).

---

## AREA 5 — A DASHBOARD / GRAPHS SHEET IN THE WORKBOOK (dynamic)

### (a) Findings — the builder today
- **Library:** openpyxl **3.1.5** only (no xlsxwriter). Package
  `client_statements_output_excel/`: `workbook_builder.py:30 build_client_
  financial_model_workbook`; `excel_utils.py` (styles, `WorkbookBuildContext`
  row registry `:55-84`, `create_workbook` sets `fullCalcOnLoad` `:110`);
  `export_client_workbook.py:80/107` (save → `CLIENT_FINANCIAL_MODELS_DIR`,
  default `C:\dev\Cilient Plans`).
- **11 sheets** (verified in the 08-17 Bellweather file; formulas/literals):
  Revenue Drivers (159/387; per-line cap/price/util literals, revenue
  formulas), Payroll Schedule (508/599), Debt Schedule (332/200), CapEx
  Depreciation (163/116), Working Capital (0/309), Cash Equity Schedule
  (0/148), Model Inputs (1037/252; links to schedules, ratio drivers as
  literals), **FINMO** (1300/179; full 3-statement formulas), Audit Source
  (hidden, 0/1138 persisted values), Checks (486/1114; `Checks!B2` model
  status), Diagnostics (0/133 KV, appended last in try/except,
  `workbook_builder.py:71-77`). Layout: periods C..W (Stub+Q1..Q20), annual
  X..AB, freeze C6 (`excel_utils.py:26-30,138-171`).
- **No charts, no defined names, no tables anywhere** (verified:
  `charts=0`, `defined_names=[]` on every sheet; zero hits for
  `openpyxl.chart|LineChart|BarChart|add_chart` in the package). Cross-sheet
  references are literal cell addresses via `ctx.finmo_row/model_input_row/
  schedule_row`.
- **Delivery/tests:** called from `intake_consult.py:15487`; Excel-COM
  status check `assert_workbook_model_status_ok` (`workbook_model_status.py:
  100`); copy to `FINMO_MODEL_DELIVERY_DIR`; `workbook_deliveries` row;
  internal email. **R32** (`replay_gate/legs.py:1795 _r_workbook_formula_
  grid`) SHA-hashes `{sheet:{row_label:[formula strings]}}` across ALL sheets
  (only cells starting with `=`, `surface.py:611-631`) → a formula-bearing
  new sheet moves R32 (re-bless); a chart-only / literal-only sheet is
  invisible to R32. No byte-identical xlsx golden exists (exporter bytes
  non-deterministic, `surface.py:1806`).

**openpyxl 3.1.5 chart support (verified import):** `LineChart, BarChart,
AreaChart, ScatterChart, PieChart, DoughnutChart, …, Reference, Series`;
series from `Reference(ws, min_col, min_row, max_col, max_row)` on ANY
sheet (cross-sheet OK); `set_categories`, titles, axis titles, number
formats, secondary axis (`y_axis.crosses="max"`, `axId=200`, `chart1 +
chart2` combos for bar+line), size, `ws.add_chart(chart, "B2")`, markers,
data labels, gridlines. **Limitations:** XML only — no rendering; **no
cached values written**, so charts populate when Excel recalcs on open
(builder already sets `fullCalcOnLoad`; non-Excel previewers may show
empty charts); no sparklines/pivot charts; contiguous ranges per series.
Native, cell-driven charts = "dynamic" in exactly Nick's sense: they update
with the model.

### (b) Dashboard design
Sheet **`Dashboard`** (first visible tab or right after FINMO — ruling
Q5.2), tab-colored, no inputs, laid out as a one-screen page:

- **KPI tile row (formulas):** Y1 / Y3 / Y5 revenue; Y1 / Y5 EBITDA and
  margin; break-even quarter (`=MATCH(TRUE, ebitda_row>0, 0)`-style) and BE
  revenue (from Break-Even sheet); cash trough (`=MIN(ending_cash_row)`) and
  its quarter; peak debt; DSCR Y1/Y3 (if debt); headcount Q1→Q20.
- **Charts (all `Reference`s to existing FINMO / Revenue Drivers / Break-
  Even rows):**
  1. Revenue by quarter — clustered/stacked BarChart by line (Revenue
     Drivers per-line revenue rows; single-line = one series) + total line.
  2. Gross margin % and EBITDA margin % — LineChart over Q1..Q20, with the
     industry band (min/max from `post_intake_fitted_bands` written as two
     literal helper rows) as shaded/secondary series.
  3. Ending cash by quarter — LineChart (+ debt balance on secondary axis).
  4. Break-even — LineChart of BE revenue vs planned revenue by quarter
     (gap = margin of safety); classic volume-axis CVP chart as a second
     ScatterChart for Q1 (fixed / total cost / revenue lines vs units).
  5. Cost structure — PieChart (or 100% stacked bar) of Y1 opex composition
     (COGS, payroll, lease, marketing, G&A, R&D, depreciation, interest).
  6. Optional: headcount ramp (Payroll Schedule totals), sources & uses (Y1
     cash-flow financing rows).
- The **document (Area 1 §8) renders these SAME series** — either by
  regenerating the charts as images from `finmo_json` (matplotlib not
  installed; python-docx cannot embed live Excel charts) or by reading the
  same rows — so workbook and document never disagree.

### (c) Technical approach given the current builder
- New module `client_statements_output_excel/dashboard_sheet.py`, invoked
  from `workbook_builder.py` after `build_checks_sheet` (Diagnostics
  pattern: additive, try/except). Charts reference existing rows through
  `ctx.finmo_row(...)`/`ctx.schedule_row(...)` — **zero new formulas → R32
  unchanged, `Checks!B2` unchanged, first-10-sheet order unchanged,
  `wb.active` still FINMO** (`workbook_builder.py:79`). Add a `DASHBOARD_
  SHEET` constant + tab color in `excel_utils.py`.
- KPI tiles: if formulas → R32 moves once (bless together with the
  Break-Even sheet, one re-bless turn); if literals from `finmo_json`
  (+`break_even`) → R32-neutral but static. Recommendation: **formulas**
  (dynamic is the requirement); one planned re-bless.
- Verification: openpyxl round-trip check that the chart XML references
  resolve to the intended rows (charts are dropped on `load_workbook`, so
  assert on the saved zip's `xl/charts/chart*.xml` or on the builder's own
  chart objects), plus the existing Excel-COM open (`assert_workbook_model_
  status_ok`) as the "Excel accepts the file" proof; cell-value assertions
  for KPI tiles on the frozen fixtures.

### (d) Open questions for ruling
- **Q5.1** Dashboard tab position: first tab (client-facing) vs after FINMO (keeps the model-first order)?
- **Q5.2** KPI tiles as formulas (dynamic, R32 re-bless once — recommended) or literals (static, R32-neutral)?
- **Q5.3** Chart list: the five above (rev by line, margins+band, cash+debt, break-even, cost structure) — add headcount ramp / sources & uses?
- **Q5.4** Should the industry band series on the margin chart come from `post_intake_fitted_bands` (the bands THIS plan was judged against) — yes/no? (Recommended yes; it is the honest comparator and it feeds §9.)

---

## AREA 6 — WHERE THE WRITING PHASE HOOKS INTO THE PIPELINE

### (a) Findings — the pipeline end, exactly
Submit `POST /api/financials` (`financials.py:56`) → `intake_submit_service.
process_intake_submission` (`:221`, only writes `intake_submissions` + client
confirmation email) → `mark_submitted` → **daemon thread self-POSTs `/api/
intake-consult/system-run`** (`financials.py:9-38,316`; docstring: "Delivery
stays human-mediated — the run's output goes to the internal inbox only").
Then ONE HTTP request / ONE thread / in-process calls: `intake_consult.py:
14420 post_intake_consult_system_run_handler` → `_run_planning_system_for_
draft_unified` (`:14189`: entry recalc; `prepare_initial_grid_for_draft`
creates the `planning_runs` row; `run_target_seeking_orchestrated_system_run`
(`orchestrator.py:1168`) incl. cascade tiers → `_run_post_cascade_completion`
(`:1950`: solver → cash pass → realism → finalize; FINMO built at sequence
step 131 `cash_final_finmo_rebuild`; persist `post_intake_finalize_
validation_completed` `:4946` flips `run_status='completed'`)) →
`validate_solver_output_at_boundary` (`:14458`) → **`verify_run_acceptance`
(`:14644`, `post_intake_acceptance/gate.py:879`, persisted `gate.py:795` →
`planning_runs.acceptance_verdict_json`)** → `if not passed` → **restructure
net** (`:14683`: bounds → joint solve → GPT review → directive → `_rs_
persist_guidance` → full re-run creating a SECOND `planning_runs` row with
`source_planning_run_id` → second `verify_run_acceptance` `:15105`; dead net
→ `RestructureNetDeadError`, `run_status='failed'`, failure email, HTTP 500)
→ diagnostics persist (`:15458`) → **workbook export (`:15487`, "regardless
of acceptance verdict")** → COM status check → copy to delivery dir →
`record_workbook_delivery` (`:15597`) → `send_workbook_alert` (`:15647`,
`EMAIL_ALERTS_ADDRESS` only; subject `PASSED|FAILED (score)`) → **`:15672`
failed verdict = warning only** → **`:15691-15711 return jsonify({"action":
"system_run_complete", "acceptance_verdict", …}) HTTP 200` — the END, on
pass and on failed verdict alike.** The step catalogue is SQL
(`post_intake_process_sequence_lookup`, phases 1→145; last row `145
finalize_global_invariants`) but the gate/net/diagnostics/workbook/email are
hard-coded in the handler AFTER the sequence. **No writing step exists in
either.**

**The trigger point:** immediately after the authoritative verdict is
final — i.e. after the restructure block resolves (`:15105` second verdict
or the first at `:14644` when passed) and after the workbook is exported and
recorded (`:15597`), because the writing phase needs the workbook path
(`workbook_deliveries` is the ONLY place it is recorded) and the break-even
block inside `finmo_json`. Concretely: between `record_workbook_delivery`
and `send_workbook_alert`, or — per the architecture recommendation below —
as a *signal* emitted there and consumed by a separate phase.

### (b) THE GATE — pass-only, verified
- Verdict lives in **`planning_runs.acceptance_verdict_json`** `{passed:
  bool, failed_checks[], checks[18], field_snapshot, viability_standard
  (advisory), gate_version "phase_9_g_v1"}`; copies in `post_intake_run_
  diagnostics.acceptance_passed/acceptance_score`. **`run_status` does NOT
  encode the verdict** (Nine Fathom `10a81085`: `run_status='completed'`,
  `passed=False`, `failed_checks=[net_income_trajectory_viable]`, and a
  `workbook_deliveries` row id 26 — the delivered-failed-plan lesson).
  `draft.status` and `plan_confidence` are NOT usable (`restructured_viable_
  candidate` stamp is overwritten by `result.plan_confidence`; only 1 row
  ever carries it).
- **Rescued-by-net representation:** two `planning_runs` rows, the later
  with `source_planning_run_id` = the failed row and `passed=true`; the draft
  `planning_run_id` points at the later; `repair_guidance_json.restructure.
  final_passed=true` + `attempt_workbook_path` (only present when the net
  fired). Verified: Nine Fathom `10a81085`(F) → `f44ff3f1`(F, supervisor
  rerun) → `e8a03731`(T); `bb1ed60c`(F) → `05d34b67`(T); dead-net clone
  `72d40681` `run_status='failed'` → `f34e40a5`(F) → `59226120`(T).
- **The writing-phase gate condition:** on the draft's authoritative run
  (`intake_consult_drafts.planning_run_id`, which after a rescue IS the
  rescued row): `planning_runs.run_status='completed' AND JSON_EXTRACT(
  acceptance_verdict_json,'$.passed')=true` (equivalently the in-process
  `acceptance_verdict["passed"]` at `:15672`, or `post_intake_run_
  diagnostics.acceptance_passed=1` for the same run id). A plain pass and a
  rescued pass both satisfy it; a failed verdict and a run failure both do
  not — no document, the existing failure path (internal email) stands.
  Recommendation: the writing phase also *records* which case it was (plain
  vs rescued via `repair_guidance_json.restructure`) because §9 must
  disclose a rescue.

### (c) Architecture — inline vs distinct phase (recommendation: DISTINCT)
Facts: phases today are in-process calls in one 2-hour HTTP thread; the two
existing "react to a run reaching a status" patterns are the **supervisor**
(`scripts/run_supervisor.py`: polls `planning_runs`, acts via HTTP, records
`supervisor_actions`) and the **persona watcher/vitals finalizer** (poll
terminal `run_status` → INSERT `run_vitals_runs`); the closest "separately
invocable output phase" is `python -m client_statements_output_excel.export_
client_workbook --draft-id …` (`export_client_workbook.py:136`, reads the
draft row, produces the artifact); a "run a stage by name" endpoint exists
(`POST /system-run/control {"action":"run_process_step"}`, `intake_consult.
py:15719`, side-effect-free by default). **No monetization / entitlement
scaffolding exists anywhere** (grep clean).

**Recommended: (b) a distinct, separately-invocable WRITING phase, triggered
by a passed post-intake but not welded into it.**
- **Trigger record, not a call:** at the end of the system-run handler,
  after `record_workbook_delivery`, when the gate condition holds, INSERT a
  row into a new **`writing_phase_requests`** table (`draft_id, planning_run_
  id, workbook_delivery_id, requested_at, requested_by ∈ {auto_pass,
  operator, paid_update}, status ∈ {pending, running, completed, failed,
  skipped}, gate_snapshot (verdict passed + rescued flag), document_path,
  cost_tokens, error`). Nothing else changes in the handler (no LLM calls,
  no new latency, the 2-hour thread ends exactly as today).
- **Runner:** `python -m writing_phase.run --draft-id …` (the export_client_
  workbook shape) that (1) re-checks the gate against the DB (never trusts
  the request row alone — Nine Fathom lesson), (2) assembles the plan brief
  (Area 2 joins), (3) computes nothing financial (reads `finmo_json.break_
  even`), (4) generates sections under the Area 3 verifier, (5) renders docx
  + charts, (6) records `document_path` + status, (7) internal email (email
  path is a fence — writing sends through the existing `workbook_email`
  helper or not at all; ruling Q6.4). A supervisor-style poller (or an
  extension of `run_supervisor.py`) drains `pending` rows on a schedule;
  during development the poller is simply not running / `WRITING_PHASE_
  AUTORUN=0`, so no test run ever pays for a document; an operator can
  invoke the runner by hand for one draft.
- **Why distinct wins:** dev cost control (no LLM spend on every canary),
  monetization-ready (`requested_by=paid_update` is a row, not a code path;
  re-running writing on a re-priced model = a new request), failure isolation
  (a writing failure can never mark a passed run failed or block the workbook
  email), rerun-safe (a rerun that supersedes a run leaves the old request
  `skipped`), and it matches the existing supervisor/vitals pattern rather
  than inventing one.
- **Flags to respect:** `CONVERGENCE_TEST_MODE` fail-loud (default ON),
  `GPT_RESPONSE_LOCK` replay store (byte-identical regeneration for goldens),
  `EMAIL_*`, `FINMO_MODEL_DELIVERY_DIR`; add `WRITING_PHASE_AUTORUN` and a
  per-request `dry_run`.

### (d) What the writing phase RECEIVES — confirmed reachable
From `intake_consult_drafts` (97 cols): all narrative JSON (2A),
`model_input_json`, `finmo_json` (+`break_even` once built), `planning_run_
json` (incl. `post_cascade_completion` cash prose, `stage_ramp_contract`,
`adaptive_policy`), `realism_memo_json`, `planning_context_summary_json`,
`payroll_headcount`, `debt_schedule`, `repair_guidance_json` (rescue record),
`planning_run_id`. From `planning_runs` (1 join): `acceptance_verdict_json`,
`source_planning_run_id`, `plan_confidence`. Needs joins (all keyed): `workbook_
deliveries` (the workbook path), `post_intake_run_diagnostics`, `post_intake_
restructuring_log` (by the AUTHORITATIVE run id — beware rerun drift), `post_
intake_fitted_bands/cohort_bands`, `intake_submissions` (contact), `run_vitals_
runs.transcript_path`. Warehouse: all 2B tables by `business_naics_6` +
address ZIP/state. **Everything Areas 2–5 need is reachable; nothing requires
a new persistence except the override registry (D1) and the request table.**

### (e) Open questions for ruling
- **Q6.1** Confirm: distinct phase + request table + on-demand runner (recommended) vs inline call in the handler behind a flag.
- **Q6.2** Auto-enqueue on every passed run (row only, cheap) with the poller off in dev — or enqueue only when an operator/paid flag says so?
- **Q6.3** Rescued-by-net plans: document generated (they passed) with a mandatory §9 rescue disclosure — confirm.
- **Q6.4** Delivery of the document: internal inbox only (same as workbook, human-mediated) — confirm; the email path is fenced, so writing reuses `workbook_email.py` unchanged or writes to the delivery dir only.
- **Q6.5** Where the request table lives / name (`writing_phase_requests`), and whether `supervisor_actions` gains a `write_plan` action or writing gets its own poller.

---

## RECOMMENDED BUILD SEQUENCE (dependencies between the areas)

```
 W0  Rulings on this doc ──────────────────────────────────────────────────┐
 W1  Break-even block in finmo_json (Area 4c compute+persist+contract)     │  spot-check: red→green
     └─ needs nothing; unlocks W2 charts and W5 §8                          │  + artifact + single-line floor
 W2  Workbook: Break-Even sheet + Dashboard sheet (Area 5c)                 │  builder-only; ONE planned
     └─ needs W1; R32 re-bless once (formulas)                              │  R32 re-bless; COM open proof
 W3  Override registry D1+D2 (+D3 templates, D4 boundary labels) (Area 3c) │  system-touching stamps
     └─ independent of W1/W2; ordered here because W5 §9 needs it;          │  (values unchanged) →
        the ONLY engine-adjacent item — additive metadata only              │  neighbor-check + canary
 W4  Writing-phase skeleton (Area 6): request table, gate re-check, brief   │  no LLM calls yet;
     assembler (Area 2 joins + warehouse readers incl. FRED/BDS/CBP/OEWS/  │  unit-tested brief on the
     SBA/SOI), runner CLI, poller off by default                            │  frozen fixtures
 W5  Generation + renderer: section templates, GPT rework, verifier/lints   │  goldens via GPT_RESPONSE_LOCK
     (Area 3a), python-docx (new dependency), charts as images from the     │  replay; lint pins; one live
     same series as W2, title/TOC/footer; §8 from W1, §9 from W3            │  run on Sunny_V3 then a real
     └─ needs W1, W3, W4                                                    │  passed draft (Millgate)
 W6  Enable auto-enqueue on passed runs; first Cowork run with a document ──┘
```

Rationale: W1 before W2 (the dashboard charts break-even); W1/W2 are
builder-local and cheap, deliverable while rulings on Areas 3/6 settle; W3
before W5 (§9 cannot be written without a registry, and W3 is the
system-touching one so it gets its own turn and its own canary); W4 before
W5 (the brief is what generation is verified against — data inventory
before narrative); W6 last, per the canary-before-batch law. Each W is its
own turn with its own declared blast radius (split-by-blast-radius law);
none of W1/W2/W4/W5 touch engine math or intake, so goldens move only at
the planned R32 re-bless in W2.

Nothing built. Report for ruling.
