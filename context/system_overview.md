# System Overview

## Core Flow
Current live flow:
`intake -> critic (baby AI) -> grid -> direct model writes -> planning system-run -> writing`

Target post-intake flow:
`intake -> critic (baby AI) -> grid -> direct model writes -> unified convergence engine -> writing`

## Architecture
- Intake captures structured business facts across ops, market, people, fulfillment, and financials.
- Critic reviews the captured model for realism tension and incoherence.
- Grid turns the captured facts plus critic context into exact quarter-by-quarter driver values.
- Those direct driver writes recalculate the financial model immediately.
- Writing consumes the recalculated plan and intake summaries to generate business-plan narrative.

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
- Job: build the quarter planning contract and return exact quarter-by-quarter writable lever values.
- It converts model inputs into writable rows, calls GPT to fill exact values, and writes those values back into `model_input_json`.

### Unified Convergence Engine
- Target role: the only true iterative repair owner after grid/direct model writes.
- It should unify realism, cash posture, stabilization, and terminal guarantee concepts in one GPT/solver loop.
- It should adapt its breadth based on current state rather than switching through heavyweight mini-passes.

### Writing
- Writing is downstream of direct model application, not upstream of planning.
- It should explain the recalculated business, not invent a better one.

## Persistence / Runtime
- Draft state persists in `intake_consult_drafts`.
- Target run-state architecture also includes:
  - `planning_runs` for current execution truth
  - `planning_run_checkpoints` for durable resume truth
  - `planning_stage_events` for the execution timeline
- Important stored artifacts:
  - `realism_memo_json`
  - `planning_run_json`
  - `model_input_json`
  - `finmo_json`

## Practical Rule
- If reality is off, fix the responsible upstream layer.
- Do not let downstream writing or ad hoc overrides become the planning engine.
