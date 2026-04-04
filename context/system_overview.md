# System Overview

## Core Flow
`intake -> critic (baby AI) -> grid -> solver -> writing`

## Architecture
- Intake captures structured business facts across ops, market, people, fulfillment, and financials.
- Critic reviews the captured model for realism tension and incoherence.
- Grid turns the captured facts plus critic context into a quarter-by-quarter planning envelope.
- Solver fits the financial model inside that envelope and produces the feasible plan.
- Writing consumes the solved plan and intake summaries to generate business-plan narrative.

## Component Roles
### Intake
- Main orchestrator: `python/api_handlers/intake_consult.py`
- Supporting consultants live in `python/client_intake_and_finmo/`.
- Job: collect facts, normalize them, persist draft state, and hand off a usable baseline.

### Critic / Baby AI
- Main code: `python/client_intake_and_finmo/realism_memo.py`
- Prompts: `python/client_intake_and_finmo/prompts/realism_memo/`
- Job: surface realism issues only.
- Output: short advisory memo JSON.
- Non-role: it does not prescribe fixes, rewrite facts, or control planning.

### Grid
- Main code: `python/client_intake_and_finmo/quarter_grid.py`
- Job: build the quarter planning contract.
- It converts model inputs into bounded rows, calls GPT to fill realistic min/max bands, and prepares solver controls/targets.

### Solver
- Main code: `python/financial_model_engine/solver.py`
- Job: enforce feasibility.
- It optimizes within the allowed controls/targets and returns solved model inputs, solved finmo output, and diagnostics.

### Writing
- Writing is downstream of solving, not upstream of planning.
- It should explain the solved business, not invent a better one.

## Persistence / Runtime
- Draft state persists in `intake_consult_drafts`.
- Important stored artifacts:
  - `realism_memo_json`
  - `planning_run_json`
  - `model_input_json`
  - `finmo_json`

## Practical Rule
- If reality is off, fix the responsible upstream layer.
- Do not let downstream writing or ad hoc overrides become the planning engine.
