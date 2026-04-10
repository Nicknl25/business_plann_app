# App Map

## Core Runtime Surfaces

- `python/api_handlers/intake_consult.py`
  - live entry point after intake
  - orchestrates `system-run`
  - persists planning outputs
  - likely surface for backend `500` failures and bad runtime handoffs

- `python/client_intake_and_finmo/app_agents/planner.py`
  - top-level app-agent orchestration
  - builds shared context
  - runs the specialist agents
  - validates specialist outputs
  - returns the full `app_agents_run_json`

- `python/client_intake_and_finmo/app_agents/shared_context.py`
  - canonical business context assembler
  - likely surface for missing facts, bad business-type framing, weak row catalog, or missing planner invariants

- `python/client_intake_and_finmo/app_agents/solver_bridge.py`
  - translates the planner's final grid into solver controls and targets
  - preserves the downstream solver contract
  - likely surface for grid-to-solver contract bugs

- `python/client_intake_and_finmo/intake_consult_draft.py`
  - draft-table persistence
  - stores `planning_run_json` and `app_agents_run_json`
  - likely surface for missing planner outputs or SQL drift

## Specialist Planner Surfaces

- `python/client_intake_and_finmo/app_agents/realism_agent.py`
  - business-model and business-type realism specialist

- `python/client_intake_and_finmo/app_agents/operations_agent.py`
  - throughput, staffing, capacity, and sequencing specialist

- `python/client_intake_and_finmo/app_agents/capital_agent.py`
  - liquidity, capital allocation, and four-strategy specialist

- `python/client_intake_and_finmo/app_agents/grid_agent.py`
  - constrained final integrator
  - produces the solver-compatible final grid

- `python/client_intake_and_finmo/app_agents/prompts/*.md`
  - specialist prompt contracts

- `python/client_intake_and_finmo/app_agents/schemas/*.json`
  - strict JSON-schema contracts for shared context and each agent output

## Intended AI Process

1. shared business context is assembled once
2. `realism_agent` defines believable behavior and forbidden patterns
3. `operations_agent` defines operationally supportable behavior
4. `capital_agent` defines liquidity and cash-strategy constraints
5. `grid_agent` integrates those constraints into the final grid
6. `solver_bridge.py` converts that grid into the exact downstream solver contract
7. solver/model evaluate the result

## Persistence / Inspection Surfaces

- `planning_run_json`
  - compact run summary

- `app_agents_run_json`
  - full planner payload
  - includes:
    - `shared_context`
    - `realism_agent`
    - `operations_agent`
    - `capital_agent`
    - `grid_agent`

This is the primary inspection artifact for understanding what each app agent contributed.

## Common Failure Classes

- `system_run_failed`
  - backend pipeline failure; still analyzable

- planner schema / OpenAI response-format failure
  - specialist output contract issue

- planner `blocked`
  - specialist constraints could not be satisfied together

- solver failure
  - final grid still produced an infeasible planning problem

## What To Inspect First

When the run fails:

1. command stdout/stderr
2. latest draft row
3. `app_agents_run_json`
4. `planning_run_json`
5. final `grid_agent.grid_json`
6. solver summary / solved outputs
7. planner prompts, schemas, and shared context assembly

## Dangerous Anti-Patterns

- blaming solver first
- debugging deleted legacy planner files
- treating specialist-agent outputs as prose-only commentary
- allowing `grid_agent` to silently ignore specialist constraints
- changing solver contract while claiming the planner architecture stayed the same
