# Phase 7 Validation

## Purpose

Phase 7 defines how the new app-agent planner is judged before broader rollout.

The goal is not merely "did the solver run?" The goal is to evaluate:
- realism
- strategy visibility
- row coherence
- grid contract integrity
- business-type fit
- absence of generic staircase-by-default behavior

## Validation dimensions

### 1. Contract integrity

- shared context is valid
- agent outputs are valid
- final `app_agents_run_json` is valid
- final grid matches the existing solver contract
- row ids and row counts are preserved

### 2. Planner readiness

- planner status is `ready`
- no hidden blocking conflicts
- grid agent self-check passes all required dimensions

### 3. Strategy visibility

- selected cash strategy is visible in the grid
- supporting rows reflect the claimed strategy
- row movement is materially visible, not just cosmetic

### 4. Staircase risk

- `Cash` output row should not default to a smooth staircase when the strategy and business support meaningful deployment or extraction
- reinvest and shareholder-return cases are especially sensitive to staircase risk

### 5. Row coherence

- revenue growth should have believable support
- capital deployment should have believable magnitude when claimed
- support rows should not remain static while the narrative implies major change

## Validation outputs

Phase 7 produces structured validation payloads that can be stored, reviewed, or compared across scenario runs.

## Scenario battery principle

Validation must cover:
- multiple business types
- multiple business models
- all four cash strategies

The point is to avoid overfitting to a single med spa reinvest case.

