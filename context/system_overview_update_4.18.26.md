# System Overview Update 4.18.26

## Purpose Of This File

This file is a Codex-facing handoff document for the `business_plann_app` repo.
It is meant to let a future Codex instance recover the app's real architecture,
current priorities, and non-negotiable product rules without relying on chat
history.

If the machine, editor, or current thread is lost, a future Codex should read
this file first, then inspect the files referenced below, before attempting any
post-intake planning changes.

## What This App Is

`business_plann_app` is a business-planning application that:

1. collects client/business intake,
2. converts that intake into structured operating and financial assumptions,
3. builds a live financial model,
4. runs a post-intake planning/convergence system to repair realism and
   viability problems,
5. persists the run state and latest accepted model state in SQL,
6. eventually hands the final plan to the writing phase.

This is not just a form app or a static plan generator. It is a system that is
trying to take imperfect client input and transform it into a viable,
commercially believable, internally consistent business plan.

## Core Product Philosophy

### 1. Intake Is Not Binding

Client intake numbers are starting assumptions, not sacred truth.

If intake is unrealistic, contradictory, or commercially broken, the system is
allowed to deviate materially from intake in order to produce a viable plan.
Realism and viability override intake preservation.

### 2. A Bad Plan Must Not Ship

The system may struggle internally, but the product goal is that the final
output should be a viable business plan, not a broken one.

### 3. GPT And Python Have Different Jobs

Python should own deterministic work:
- state measurement
- issue scoring
- progress/regression detection
- packet building
- lever scaffolding and band scaffolding
- persistence
- validation of shape / authorization / coverage

GPT should own judgment:
- strategy
- tradeoffs
- posture
- target choices within the allowed field
- deciding how to use levers
- deciding when to deviate further from intake

Solver should own numeric execution only.

### 4. Post-Intake Must Be Observable

If the system is running, SQL must show what it is doing.
Durable truth matters for:
- reruns
- resumes
- stoppages
- future multi-user workflows
- Excel / SQL monitoring

## High-Level App Flow

Current intended flow:

`intake -> realism memo / critic -> quarter grid -> applied model -> unified post-intake convergence -> writing`

Important distinction:
- Intake gathers and persists the business.
- Quarter grid creates an initial 20-quarter operating/financial shape.
- Post-intake convergence is the repair engine that tries to make the plan
  viable and realistic.
- Writing is downstream and should explain the resulting plan, not invent a new
  one.

## Main Domain Objects

### Intake Draft

The central durable row is in `intake_consult_drafts`.

This row stores latest accepted snapshots such as:
- intake consultant outputs
- `model_input_json`
- `finmo_json`
- post-intake planning snapshots
- runtime mirrors for monitoring

### Model Input

`model_input_json` is the writable driver model.
This is the driver layer GPT/solver ultimately manipulates.

### Finmo

`finmo_json` is the calculated financial model output.
This is the derived result after model inputs are applied.

### Realism Memo

`realism_memo_json` is the issue-oriented realism scan / advisory memo.
It describes where the business looks commercially wrong or incoherent.

### Planning Run Payload

`planning_run_json` is the broad persisted planning/run state.
It is useful, but it can become large and is not the right packet to send
directly to GPT for each repair cycle.

### Repair Guidance

`repair_guidance_json` is the standalone current-cycle GPT working packet for
the post-intake convergence loop. It is rebuilt each cycle and overwritten,
rather than accumulating history.

### Planning Convergence

`planning_convergence_json` is the standalone convergence monitoring JSON that
summarizes the cycle's measurable state in one place for SQL/monitoring.

## Current Post-Intake Architecture

### Unified Engine

The current target architecture is a single post-grid convergence engine.

The runtime entry point delegates here:
- `python/api_handlers/intake_consult.py`
- `_run_planning_system_for_draft(...)`
- `_run_planning_system_for_draft_unified(...)`
- `_run_unified_post_grid_system_run(...)`

The intention is that there is one true post-intake convergence owner rather
than multiple heavyweight stage-owned retry engines.

### What The Unified Loop Does

The intended loop is:

1. Python measures the current state.
2. Python builds issue packets, retry packets, target scaffolds, and lever-band
   scaffolds.
3. GPT sees the whole business at once:
   - planning mode
   - cash strategy
   - realism context
   - business type
   - business model
   - issue state
   - current Finmo shape
4. GPT returns structured targets, lever selections, tolerances, and rationale.
5. The numeric solver executes.
6. Finmo recalculates.
7. Python scores the result and determines whether the cycle improved,
   stalled, or regressed.
8. The loop continues until the issue state is sufficiently cleared and the
   plan remains viable.

### Current Important Caveat

Historically the repo had realism, cash strategy, final stabilizer, and final
guarantee as separate top-level ownership concepts.

The current direction is to keep those concepts as context inputs, not as
independent heavyweight convergence owners.

A future Codex should be very careful not to accidentally reintroduce those old
top-level engines just because helper functions or legacy prompt folders still
exist in the repo.

## Where The Important Logic Lives

### Main Post-Intake Orchestrator

File:
- `python/api_handlers/intake_consult.py`

This file is the main control tower for:
- intake session handler
- planning system-run handler
- unified post-intake convergence
- persistence hooks
- runtime payload construction
- GPT packet construction
- controller state / score computation

### Draft Persistence Layer

File:
- `python/client_intake_and_finmo/intake_consult_draft.py`

This file owns:
- SQL schema maintenance for `intake_consult_drafts`
- planning tables/checkpoints/events
- append/update operations
- runtime payload compaction
- persistence of:
  - `planning_run_json`
  - `planning_runtime_json`
  - `planning_convergence_json`
  - `repair_guidance_json`
  - `convergence_state_json`
  - `numeric_solver_feedback_json`

### Quarter Grid

Files under:
- `python/client_intake_and_finmo/quarter_grid.py`

Quarter grid creates the initial 20-quarter plan shape before unified
convergence tries to repair it further.

### Realism Memo / Critic

Files under:
- `python/client_intake_and_finmo/realism_memo.py`
- prompt folders under `python/client_intake_and_finmo/prompts/`

This layer identifies issues. It should not become the full planning engine.

## Key SQL / Persistence Model

### 1. `intake_consult_drafts`

Role:
- latest accepted draft snapshot
- latest visible business-plan state

Important columns for post-intake:
- `planning_run_json`
- `planning_runtime_json`
- `planning_convergence_json`
- `repair_guidance_json`
- `convergence_state_json`
- `numeric_solver_feedback_json`
- `model_input_json`
- `finmo_json`

Flat monitoring fields also live here, including:
- `planning_stage`
- `planning_status`
- `planning_last_review_iteration`
- `planning_current_retry_count`
- `planning_current_cycle`
- `planning_detected_issue_count`
- `planning_remaining_issue_count`
- `planning_resolved_issue_count`
- `planning_tolerated_issue_count`
- `planning_iteration_pending_issue_count`

### 2. `planning_runs`

Role:
- current execution truth for a run

### 3. `planning_run_checkpoints`

Role:
- durable resume history / accepted snapshots

### 4. `planning_stage_events`

Role:
- lightweight event timeline / observability

## The New Convergence-Specific JSONs

### `repair_guidance_json`

Purpose:
- current GPT repair packet for the unified convergence cycle
- rebuilt fresh each cycle
- not supposed to accumulate historical garbage

Important contents:
- planning context
- selected cash strategy
- unified convergence context
- current cycle convergence packet
- deterministic issue packets
- deterministic numeric guidance
- retry packet
- escalation packet
- retry scope
- quarter target scaffold
- tolerance scaffold
- compact writable lever catalog
- current writable lever values
- compact quarter view

Within deterministic numeric guidance, the critical parts are:
- `scope_quarters`
- `metric_pressure_packets`
- `lever_band_scaffold`

Lever scaffold now includes ranking / priority metadata so GPT can see not just
what levers exist, but which ones Python thinks are more relevant.

### `planning_convergence_json`

Purpose:
- single SQL-visible convergence summary
- keep the convergence truth in one place
- support monitoring without needing to parse the huge planning payload

Important contents:
- stage / status / run status
- current cycle and retry count
- detected / remaining / resolved / tolerated / pending issue counts
- `planning_quality_score`
- `planning_quality_grade`
- `planning_quality_pass`
- `planning_remaining_hard_issue_count`
- `planning_cycle_progress_status`
- `planning_score_delta`
- lowest quarter score
- failing quarters
- escalation status
- solver status
- target miss status
- compact repair-guidance summary
- compact convergence state
- compact numeric feedback

## Scoring / Closure Philosophy

The current convergence logic is not aiming for fake perfect exactness.

It uses a grade-aware idea of completion:
- A = 90+
- B = 80-89
- C = 70-79
- below 70 = fail

Important nuance:
- quarter-level floors matter
- one catastrophic quarter can still block practical acceptance
- tolerated issues can exist when they are sufficiently resolved under the
  scoring policy

This is meant to avoid endless iteration toward fake perfection while still
protecting viability.

## Operational Rules A Future Codex Must Respect

### Do Not Treat Intake As Sacred

If the business is unrealistic, the system should change the business shape.

### Do Not Re-Bloat GPT Payloads

Avoid sending giant planning/intake blobs directly to GPT each cycle.
Use dedicated current-cycle packets like `repair_guidance_json`.

### Do Not Let History Accumulate In Cycle Packets

Current-cycle repair payloads should be overwritten, not appended forever.

### Do Not Recreate Multiple Heavyweight Top-Level Convergence Engines

Realism, cash strategy, stabilizer, and guarantee concepts may still exist as
context, but they should not quietly regain separate top-level solver ownership.

### Do Not Move Judgment Fully Into Python

Python should not become the business strategist.
GPT should still decide how to solve within the allowed and measured field.

### Do Not Make Writing The Planner

Writing explains the resulting business.
It should not be used to paper over a broken plan.

## What A Future Codex Should Inspect First

If resuming work on post-intake planning, inspect in this order:

1. `context/current_state.md`
2. `context/next_steps.md`
3. this file
4. `python/api_handlers/intake_consult.py`
5. `python/client_intake_and_finmo/intake_consult_draft.py`

Then verify:
- what `_run_planning_system_for_draft(...)` actually calls
- what `_run_unified_post_grid_system_run(...)` actually persists
- what GPT packet is being built and sent
- what SQL JSONs are being updated each cycle

## What Success Looks Like

A successful post-intake run should:
- complete end-to-end without stalling silently
- show cycle-by-cycle truth in SQL
- use the unified convergence engine after quarter grid
- keep current-cycle GPT packets lightweight and non-accumulating
- improve issue counts and/or quality score over time
- produce a viable, commercially believable forecast

## Current Git / Branch Context

The working branch used during this phase has been `intake-stable`.
If a future Codex is resuming after a crash, it should verify the current
branch and current uncommitted status before doing anything destructive.

## Final Reminder

The most important thing to understand about this app is:

This is not a generic CRUD business-plan tool.
It is a guided business-synthesis and repair system whose hard part is the
post-intake convergence engine.

Any future Codex that forgets that and starts treating this like a simple form
app, or like a pure prompt-engineering problem, will drift in the wrong
direction fast.
