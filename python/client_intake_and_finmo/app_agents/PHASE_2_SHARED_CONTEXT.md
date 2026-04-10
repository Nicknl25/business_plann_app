# Phase 2 Shared Context Contract

## Purpose

Define the single authoritative context object that all four app agents consume.

The new planner must not let agents reason from different partial snapshots. Every agent must read from the same shared context payload for the same run.

## Shared context design goals

- one canonical object for all app agents
- no hidden agent-specific context branches
- explicit business model and business type framing
- explicit financial baseline and row catalog
- explicit solver-contract preservation metadata
- explicit capture of the selected cash strategy

## Required top-level sections

### `contract`

Metadata about the app-agent planning run:
- contract version
- planner version
- run timestamp
- draft id
- business name

### `business_profile`

Identity and business framing:
- business name
- business description
- business model
- business type
- legal entity
- geography
- stage
- business start date
- customer type
- delivery method
- sales channel
- growth lever
- competitive advantage

### `strategy_profile`

Current strategy framing:
- selected cash strategy
- strategy label
- strategy intent summary
- business goal summary
- explicit strategy implications expected to become visible in the plan

### `intake_context`

Raw or normalized intake sections:
- `ops_json`
- `target_market_json`
- `people_json`
- `financials_json`
- `financials_year1_json`
- `marketing_model_json`
- `fulfillment_json`
- `business_facts`

### `financial_baseline`

Baseline model state that agents must reason from:
- `model_input_json`
- `finmo_json`
- summary metrics
- opening balance seeds
- baseline output highlights

### `row_catalog`

The planner-facing catalog of rows the solver already understands:
- row id
- row type
- section
- label
- baseline values
- row semantics
- whether the row is:
  - operational
  - capital-allocation-relevant
  - output-only
  - likely constrained by shared capacity

### `planner_invariants`

Hard rules the agents may not violate:
- solver contract unchanged
- row ids unchanged
- row meanings unchanged
- min/max semantics unchanged
- quarter count unchanged
- no legacy planner dependencies

### `external_business_reasoning_requirements`

Explicit reminder that agents must not rely only on local SQL or app state.

They must reason using:
- business type knowledge
- business model knowledge
- operating reality
- capital allocation reality
- real-world growth mechanics

## Important exclusion

The shared context for the new architecture must not depend on:
- realism memo prompts
- any other replaced legacy planner artifact

## Persisted visibility requirement

The exact shared context object used by the app-agent planner should be stored inside `app_agents_run_json` so later review can see:
- what every agent saw
- what every agent produced
- how the final grid was assembled
