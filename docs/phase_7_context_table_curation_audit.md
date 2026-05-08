# Phase 7 — Context Table Curation Audit (DRAFT — pre-sign-off)

## Executive finding before anything else

**8 of the 16 JSON fields the directive listed are NULL on 100% of completed drafts** (`active_focus='done'`, n=1,214). The directive's curation plan needs adjustment — those fields aren't currently populated by the intake pipeline.

| Field | Population rate | Notes |
|---|---:|---|
| `operating_model_json` | **99.9 %** | rich; ~3-4 KB; carries business_type, NAICS, capacity/price/utilization, sales_modality, shipping_method, lob_models, primary_growth_lever, geography, competitive_advantage |
| `target_market_json` | **99.9 %** | rich; ~2-4 KB; ICP, B2B size/age/industry bands, marketing_plan_summary |
| `marketing_model_json` | 65.5 % | very rich, 9-13 KB total — but most is `signature` (6.5 KB hash) and narrative; **scalar signal fields are tiny** (see size breakdown below) |
| `people_json` | **99.9 %** | rich; 5-8 KB; current people, inferred_roles, hiring schedule |
| `financials_json` | **99.9 %** | dense scalars; ~1-3 KB; current state snapshot — AR, AP, inventory, cash, debt, lease, current_revenue/cogs/payroll |
| `financials_year1_json` | **99.9 %** | ~1.4 KB; operator-projected Year-1 revenue + LOB breakdown |
| `normalized_traits_json` | 3.7 % | sparse; out of scope |
| `benchmark_payload_json` | 3.7 % | sparse; out of scope |
| `customer_model_json` | **0 %** | future schema; **not consumable** |
| `revenue_model_json` | **0 %** | future schema; **not consumable** |
| `cogs_model_json` | **0 %** | future schema; **not consumable** |
| `gna_model_json` | **0 %** | future schema; **not consumable** |
| `fulfillment_model_json` | **0 %** | future schema; **not consumable** |
| `headcount_model_json` | **0 %** | future schema; **not consumable** |
| `milestones_model_json` | **0 %** | future schema; **not consumable** |
| `operating_structure_json` | **0 %** | future schema; **not consumable** |

**Implication.** The directive's plan said things like "COGS lever — cogs_model_json, fulfillment_model_json" and "AR Days — customer_model_json, revenue_model_json." Those four fields don't exist on real data. The discriminating signals the directive wanted from those fields **are present in `operating_model_json` instead** — it carries `business_type`, `consumer_type`, `sales_modality`, `shipping_method`, `capacity_driver`, `unit_*`, `lob_models`, `primary_growth_lever`, `geographic_coverage`, `competitive_advantage`. So the curation can hit the directive's intent (raw signals not pre-classified labels) by routing `operating_model_json` (and its specific subfields) to the right consultants — but the source paths are different from the directive's literal plan.

I want sign-off on this re-route before seeding the table. Two options below.

## How real signals differentiate the three baseline drafts

Each row of this table came directly from the populated JSON — these are the signals the consultants would actually see. Sunny / Express / NexGen produce three very different shapes that the current seed (which feeds pre-classified labels + cohort percentiles) does not surface.

| Signal (from operating_model_json or financials_json) | NexGen (B2B SaaS) | Sunny Glaze (B2C donut) | ExpressLogix (B2B/B2C logistics) |
|---|---|---|---|
| `consumer_type` | b2b | consumer | mixed |
| `sales_modality` | online | physical | hybrid |
| `shipping_method` | digital | in-person pickup | own fleet + partners |
| `capacity_driver` | labor | labor | labor |
| `unit_price` | $20,000 / mo subscription | $2 / donut | $15 / shipment |
| `units_per_period_capacity` | 50 | 1,200 | 250,000 |
| `cogs_pct` (current) | ~26% | 29% | **70%** |
| `ar_balance` | $100K | $0 | $200K |
| `ap_balance` | $20K | $3K | $120K |
| `inventory_balance` | $0 | $800 | $50K |
| `monthly_rent` | (low / cloud) | $2K | $50K |

These are the signals that should drive band shaping decisions. The directive's expected outcomes (Sunny AR Days → 0; ExpressLogix COGS → 50-65%; NexGen → services-led shape) are reachable from `operating_model_json` + `financials_json`; they don't require the NULL fields.

## Two paths — choose one

### Option A — Curate from populated fields only (recommended)

Replace the 8 missing-JSON references in the directive's plan with pulls from the 6 populated fields. Reach the same intent: "raw signals, not pre-classified labels," via what's actually present.

Concretely:
- "fulfillment_model_json" → `operating_model_json:shipping_method` + `operating_model_json:lob_models` + `financials_json:inventory_balance`
- "customer_model_json" → `operating_model_json:consumer_type` + `target_market_json:consumer_type/b2b_industry_terms` + `financials_json:ar_balance` (a B2C cash-retail business has $0 AR)
- "revenue_model_json" → `operating_model_json:lob_models/unit_*/capacity_driver/primary_growth_lever` + `financials_year1_json:lobs`
- "cogs_model_json" → `operating_model_json:capacity_driver/shipping_method` + `financials_json:cogs_percent_of_revenue/cogs_total_year1`
- "gna_model_json" → `operating_model_json:legal_entity` + `financials_json:other_operating_expense/owner_compensation` + `people_json:inferred_roles_summary`
- "headcount_model_json" → `people_json:inferred_roles` (or summary for budget) + `financials_json:current_num_employees/current_payroll`
- "milestones_model_json" → `operating_model_json:milestones` + `business_start_date` (age signal)
- "operating_structure_json" → `operating_model_json:legal_entity` + `address_state`

Pros: ships now with what's real. Honest about source paths. Each row's signal is verifiable in real data today.

Cons: when the missing JSON fields get populated by future intake work, the source paths will need a second pass. That's acceptable — the table is the contract; rows get added as data becomes available.

### Option B — Audit declares the right shape, but seed only what's populated

Same actual rows as Option A, but the audit document records every directive-listed field with a status: `seeded` / `deferred_pending_intake_population`. When `customer_model_json` lands in production, the deferred row activates.

Pros: tracks the directive literally. Future-proof.

Cons: the lookup table can't have rows pointing at columns that don't exist — they'd resolve to None at runtime and (if `required=1`) raise; if `required=0`, they're skipped silently. Either way, the row is dead weight in the table. Better to add rows when the data is ready.

**Recommendation: Option A.** The audit doc records what's chosen and why; deferred-pending rows aren't worth the bookkeeping until the data lands.

## Per-consultant per-scope row design (proposed under Option A)

### Universal rows — every consultant call, every scope

| context_key | source_kind | source_path | max_chars | transform | reason |
|---|---|---|---:|---|---|
| `business_naics_6` | runtime_object | `business_profile_for_cohort.naics_6` | 20 | copy | Already in seed — keep. NAICS code is a raw signal (the cohort percentile math already uses it). |
| `business_start_date` | intake_field | `business_start_date` | 30 | copy | New. Business age signal — 1 month vs 25 years matters; replaces the `business_stage` pre-classified label by giving GPT the raw date to reason from. |
| `business_profile_for_cohort` | runtime_object | `business_profile_for_cohort` | 400 | copy | Already in seed — keep. Carries cohort match key (naics_6, target_revenue, stage_family). |
| `planning_mode_context` | runtime_object | `planning_mode_context` | 600 | copy | Already in seed — keep. turnaround/normalize/rebalance is a real policy, not a label-of-the-business. |

### Removed from current seed

| Removed row | Why |
|---|---|
| `business_facts.fact_template.business_type` | Pre-classified label. The underlying signal is `operating_model_json:business_type` AND `operating_model_json:business_description_summary` AND `operating_model_json:lob_models` — feed those instead via per-scope rows. |
| `business_facts.fact_template.business_stage` | Pre-classified label. Replaced by `business_start_date` (raw signal) and `operating_model_json:milestones` where useful. The `planning_mode_context` carries the operative classification for solver behavior. |
| `business_facts.fact_template.business_model` | Pre-classified label. Definitively removed. The underlying signals (lob_models, capacity_driver, sales_modality, primary_growth_lever) are in `operating_model_json` — feed those, GPT reasons about model itself. |

### Band shaping consultant — per-lever rows

For every `gpt_editable` lever the consultant calls. Each lever gets its own targeted set; the universal rows above also flow.

#### `expenses::Cost of Goods Sold`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model` | `operating_model_json` (slim transform) | 1500 | Whole operating model: business_type, capacity_driver, shipping_method, lob_models, sales_modality, primary_growth_lever — these together tell GPT what shape the cost structure takes (asset-heavy logistics ≠ cloud SaaS ≠ retail food). The slim transform drops `business_description_summary` + `competitive_advantage` long narratives to fit budget. |
| `financials_snapshot_cogs` | `financials_json` subfields: `current_revenue`, `current_cogs`, `cogs_percent_of_revenue`, `cogs_total_year1` | 200 | Current-state snapshot anchors GPT to the operator's existing cost ratio. |
| `python_proposed_band` | `envelope_proposal.drivers.{lever_id}` (slim_lever_entry) | 2000 | Already in seed — keep. The Python proposer's band the consultant is critiquing. |
| `lever_mapping_metadata` | `mapping_row_for_lever:lever_id={lever_id}` (slim_mapping_row) | 1500 | Already in seed — keep. value_kind, absolute bounds, applicability_default. |

#### `expenses::Marketing`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model` | `operating_model_json` (slim) | 1500 | Same rationale — sales_modality, geographic_coverage, consumer_type drive marketing intensity. |
| `target_market_summary` | `target_market_json:marketing_plan_summary` | 800 | Marketing posture narrative if present. |
| `marketing_signals` | `marketing_model_json` subfield-pick: `marketing_intensity`, `baseline_marketing_percent`, `expected_customers_or_clients_year1`, `expected_units_year1`, `capture_rate_year1`, `reachable_market_b2b`, `reachable_market_b2c` | 400 | Specific scalar signals only; skips the 6.5 KB `signature` + 4.2 KB `marketing_basis_summary` narrative. |
| `financials_snapshot_marketing` | `financials_json` subfields: `current_revenue`, `marketing_total_year1`, `marketing_percent_of_revenue` | 200 | Operator's current marketing intensity. |
| `python_proposed_band` | (per-lever, as above) | 2000 | keep |
| `lever_mapping_metadata` | (per-lever, as above) | 1500 | keep |

#### `expenses::Research & Development`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model` | `operating_model_json` (slim) | 1500 | NAICS (information / software vs retail) + capacity_driver + lob_models tells GPT whether R&D is structural. |
| `people_summary` | `people_json:inferred_roles_summary` | 1500 | Headcount narrative — engineering-heavy team is an R&D signal. |
| `financials_snapshot_rd` | `financials_json` subfields: `current_revenue`, `r_and_d_percent`/`research_and_development_percent`/`rd_percent_of_revenue` (whichever populated) | 200 | Operator's current R&D intensity. |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

#### `expenses::Lease`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_lease_signal` | `operating_model_json` subfield-pick: `business_type`, `shipping_method`, `geographic_coverage`, `legal_entity` | 600 | Asset-heavy / retail / warehouse businesses lease more; cloud SaaS leases less. |
| `address_state` | intake_field `address_state` | 10 | Geography matters for rent — CA/NY ≠ TN/IL. |
| `financials_snapshot_lease` | `financials_json` subfields: `monthly_rent_expense`, `future_rent_expected`, `initial_lease`, `current_revenue` | 200 | Current rent / revenue ratio anchor. |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

#### `expenses::General & Administrative`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_gna_signal` | `operating_model_json` subfield-pick: `legal_entity`, `business_type`, `geographic_coverage` | 400 | Multi-state / multi-entity → higher G&A; sole prop → minimal. |
| `people_summary` | `people_json:inferred_roles_summary` | 1500 | Admin/finance/HR roles signal G&A scale. |
| `financials_snapshot_gna` | `financials_json` subfields: `current_revenue`, `other_operating_expense`, `owner_compensation` | 200 | Current G&A intensity. |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

#### Revenue levers — `revenue::*::*::Capacity`, `revenue::*::*::Unit Price`, `revenue::*::*::Utilization`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_revenue_signal` | `operating_model_json` subfield-pick: `unit_name`, `unit_description`, `unit_cadence`, `unit_price`, `units_per_period_capacity`, `utilization_rate`, `capacity_driver`, `primary_growth_lever`, `lob_models` | 1500 | All the revenue-shape signals in one bundle. |
| `target_market_summary` | `target_market_json:marketing_plan_summary`, `target_market_json:b2b_industry_terms`, `target_market_json:consumer_type` | 1000 | ICP + market scope determines plausible utilization & price elasticity. |
| `financials_year1_revenue` | `financials_year1_json:company_revenue_total_year1` + `financials_year1_json:lobs` | 1000 | Operator's projected Year-1 revenue (advisory only — see caveat below). |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

#### Working-capital levers — `balance_sheet::Accounts Receivable Days`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_payment_signal` | `operating_model_json` subfield-pick: `consumer_type`, `sales_modality`, `shipping_method`, `business_type` | 400 | B2C cash-retail (sunny donut) → AR ≈ 0 days; B2B billed → 30-60+ days. |
| `target_market_consumer_type` | `target_market_json:consumer_type`, `target_market_json:b2b_industry_terms` | 200 | Reinforces b2b-vs-b2c signal. |
| `financials_snapshot_ar` | `financials_json` subfields: `current_revenue`, `ar_balance` | 100 | Operator's existing AR — sunny donut has $0 AR; that's a hard signal. |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

#### Working-capital levers — `balance_sheet::Accounts Payable Days`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_supplier_signal` | `operating_model_json` subfield-pick: `business_type`, `shipping_method`, `capacity_driver`, `lob_models` | 400 | Asset-heavy supplier networks have longer AP terms. |
| `financials_snapshot_ap` | `financials_json` subfields: `ap_balance`, `current_cogs`, `cogs_total_year1` | 100 | Operator's existing AP. |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

#### Working-capital levers — `balance_sheet::Inventory Days`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_inventory_signal` | `operating_model_json` subfield-pick: `business_type`, `shipping_method`, `lob_models` | 400 | Retail/manufacturing has inventory; SaaS/services don't. |
| `financials_snapshot_inv` | `financials_json` subfields: `inventory_balance`, `current_cogs` | 100 | Operator's existing inventory. |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

#### Working-capital levers — `balance_sheet::Deferred Revenue (% of Revenue)`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_revenue_pattern` | `operating_model_json` subfield-pick: `unit_cadence`, `business_type`, `lob_models` | 400 | Subscription/recurring → deferred revenue; transactional → none. |
| `financials_snapshot_def_rev` | `financials_json:current_revenue` + sample of revenue cadence fields | 200 | Anchor to operator's current state. |
| `python_proposed_band` + `lever_mapping_metadata` | (as universal per-lever) | | keep |

### Target shaping consultant — per-metric rows

#### Profitability metrics — `ebitda_margin`, `net_income_margin`, `operating_margin_percent`, `gross_margin_percent`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model` | `operating_model_json` (slim) | 1500 | Stage / capacity_driver / lob_models drive what profitability is realistic. |
| `financials_snapshot` | `financials_json` (slim — current_revenue, current_cogs, cogs_percent, marketing_percent, monthly_rent, owner_compensation, total_debt) | 600 | Current-state P&L composition. |
| `financials_year1_advisory` | `financials_year1_json:company_revenue_total_year1` + `financials_year1_json:lobs` | 1000 | **Advisory only.** Operator's Year-1 expectation gives planning posture context (operator targeting $500k vs $5M tells GPT how aggressive the calibration should be). Per directive: not authoritative, doesn't override cohort calibration. |
| `python_proposed_target` | runtime_object (slim_metric_entry) | 2500 | Already in seed — keep. |
| `realism_check_metadata` | `realism_row_for_metric:metric_key={metric_key}` | 1500 | Already in seed — keep. |

#### Working-capital metrics — `ar_days_dso`, `ap_days_dpo`, `inventory_days`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_payment_or_supply_signal` | `operating_model_json` subfield-pick (different per metric) | 400 | Same per-lever signals as the band shaping working-capital levers. |
| `financials_snapshot_wc` | `financials_json` working-capital subfields | 200 | Current AR/AP/inventory balances. |
| `python_proposed_target` + `realism_check_metadata` | (universal) | | keep |

#### Liquidity / leverage metrics — `current_ratio`, `quick_ratio`, `debt_to_equity`, `debt_to_assets`
| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model_capital_signal` | `operating_model_json` subfield-pick: `business_type`, `legal_entity`, `lob_models` | 400 | Asset-heavy / debt-funded businesses tolerate different ratios. |
| `financials_snapshot_balance_sheet` | `financials_json` subfields: `cash_on_hand`, `total_debt_outstanding`, `initial_assets`, `initial_equity`, `ar_balance`, `ap_balance`, `inventory_balance` | 400 | Current balance-sheet shape. |
| `python_proposed_target` + `realism_check_metadata` | (universal) | | keep |

### Conflict adjudication consultant — per-conflict rows

The conflict adjudication consultant decides keep_intake / keep_band / split per detected conflict.

| context_key | source_path | max_chars | reason |
|---|---|---:|---|
| `operating_model` | `operating_model_json` (slim) | 1500 | Same rationale — gives GPT the operator's narrative for "is this intake value plausible for this business." |
| `financials_full_snapshot` | `financials_json` (full, capped) | 1200 | Conflict adjudication needs the operator's full current-state picture, not just one metric. |
| `financials_year1_advisory` | `financials_year1_json` (full, capped) | 1500 | **The strongest case for `financials_year1_json`** per directive: "what the operator said they'd do" context for conflict resolution. |
| `messages_excerpt` | (deferred — see open question below) | — | The directive notes this is "the strongest case for messages_json." Need a transform that pulls only the relevant exchange. **Marking as deferred — propose a follow-up transform addition rather than ship a 200KB messages dump.** |
| `lever_python_proposed_band` | `envelope_proposal.drivers.{lever_id}` (slim_lever_entry) | 2500 | Already in seed — keep. |
| `lever_mapping_metadata` | `mapping_row_for_lever:lever_id={lever_id}` (slim_mapping_row) | 1500 | Already in seed — keep. |

## Per-call payload-size projection

Before changes (Phase 5.2 redo): 1.3KB median, 2.1KB max.

After changes (rough projection based on field sizes I sampled):
- **Band shaping per-lever** call: 4-6 universal/proposed-band/mapping rows + 2-4 lever-specific rows. Each lever's payload should land 2.0-3.5KB. Below 5KB cap with margin.
- **Target shaping per-metric**: 4-6 rows. ~2.5-4KB.
- **Conflict adjudication per-conflict**: 5-7 rows including `financials_year1_advisory`. ~3-5KB.

The biggest risk: `operating_model_json` at full 3-4KB is the load-bearing row across most calls. With `max_chars=1500` slim, it must be transformed. **A new transform `slim_operating_model` is needed** to extract a curated subset of fields. Existing transforms (`copy`, `slim_lever_entry`, `slim_metric_entry`, `slim_mapping_row`) don't apply.

## New transform required

`slim_operating_model` — accepts `operating_model_json`, returns a dict with only the fields below (drops `business_description_summary`, `competitive_advantage`, narrative-heavy fields):

```
business_type, business_naics_6, business_stage, consumer_type,
sales_modality, shipping_method, capacity_driver,
unit_name, unit_description, unit_cadence, unit_price,
units_per_period_capacity, utilization_rate, operating_periods_per_year,
primary_growth_lever, geographic_coverage, geographic_scope, legal_entity,
lob_models (truncated to first 5 LOBs, name + revenue_share only), milestones
```

Estimated post-transform size: ~600-1000 B per draft. Fits a `max_chars=1500` row with margin.

## Open questions for sign-off

1. **Option A vs B?** I recommend Option A (curate from populated fields only). Confirm.

2. **Pre-classified labels — keep `business_facts.fact_template.business_type` for any case?** My read: no. `operating_model_json:business_type` is the same string from the same upstream classification; the difference is the consultant gets the surrounding signals alongside, not the label in isolation. Removing `business_facts.*` rows entirely is the cleaner move. Confirm.

3. **`messages_json` for conflict adjudication?** The directive flagged this as the strongest case but messages are large (8-100+ KB raw). Two options:
   - **(3a)** Defer it — add later when a `messages_summary_json` field is populated by intake (a future field). Conflict adjudication relies on `financials_year1_advisory` + the calibrated band metadata for now.
   - **(3b)** Add a new transform `messages_excerpt_for_conflict` that pulls the last N message turns mentioning the conflict's lever (e.g., "AR" / "marketing") and caps at 1500 chars.

   I recommend **(3a)** — defer. Adding (3b) is its own scope and the heuristic for "find the conflict-relevant excerpt" needs careful design. Confirm.

4. **`marketing_model_json` subfield pick vs full payload?** I'm proposing subfield-pick (just the scalars, ~400 chars) instead of feeding the 9-13 KB full blob. The narrative `marketing_basis_summary` (4.2 KB) and `signature` (6.5 KB hash) carry no signal for band shaping. Confirm this is acceptable.

5. **`financials_year1_json` to band shaping consultant — yes for revenue levers only?** The directive says "Do NOT include it as a hard input that GPT might treat as ground truth." For revenue levers (Capacity / Unit Price / Utilization), the operator's projected Year-1 revenue + LOB structure is highly relevant context. For other band-shaping calls (COGS, R&D, AR Days, etc.), it's less so. Proposed: include in **revenue lever calls + target shaping calls + conflict adjudication**, exclude from the rest. Confirm.

6. **Removal of pre-classified labels — `business_stage` replaced by `business_start_date`?** The lookup table currently has `business_stage` from `business_facts.fact_template.business_stage`. Replacing with `business_start_date` lets GPT compute "this business started in 1998 — mature" vs "started in 2024 — early-stage" from the raw date. The `planning_mode_context` still carries the classification when relevant for solver behavior. Confirm.

## What stays out of scope per directive

- Changing the resolver, buffer rule, cascade, or any Phase 6 architecture.
- Tuning the GPT consultant prompts.
- Adding new GPT consultants.
- Adding new transform handlers unless reuse genuinely can't deliver. (`slim_operating_model` is the one new transform proposed and is justified above.)

## Next steps after sign-off

1. Implement `slim_operating_model` transform in `consultant_context_resolver.py`.
2. Update `scripts/seed_phase52_consultant_context_rows.py` to delete current rows and seed the curated set.
3. Run idempotently against the lookup table.
4. Verify per-call payload sizes on the three baseline drafts.
5. Commit seed update + this audit doc + transform addition.
