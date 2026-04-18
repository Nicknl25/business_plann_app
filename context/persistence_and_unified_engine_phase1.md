# Phase 1: Durable SQL And Unified Convergence Architecture

## Purpose
- Lock the target architecture before schema and runtime changes.
- Define the durable SQL model for post-intake execution.
- Define the target convergence architecture so later implementation does not drift back into multiple heavyweight loops.

## Why This Phase Comes First
- Post-intake planning already persists into SQL and the app is operationally judged through those SQL updates.
- If SQL state is stale, incomplete, or ambiguous, we cannot trust E2E runs, resumes, reruns, or monitoring.
- The current planning design is over-layered: multiple top-level loops attempt partial convergence, while terminal convergence still carries the real burden.

## Architecture Decisions Locked In

### 1. SQL Is Durable Operational Truth
- Python memory may hold live working state during a request.
- SQL must hold the durable run ledger and latest accepted snapshots.
- We will not introduce Redis at this stage.

### 2. One Unified Convergence Engine
- We are not keeping multiple top-level convergence loops as peer engines.
- We are not replacing them with one shapeless mega-loop.
- We are building one unified GPT/solver convergence engine with adaptive behavior.

### 3. Concepts Stay, Heavy Loops Go
- The concepts behind realism, cash posture, stabilization, and terminal guarantee are still important.
- Those concepts should inform the unified loop.
- They should not survive as separate heavyweight retry engines.

### 4. Adaptive Posture, Not Rigid Mini-Stages
- The unified engine should behave more broadly when the system is badly broken.
- It should narrow as viability improves.
- It should widen again in a controlled way when stalled.
- This behavior should be policy-driven and state-driven, not a bureaucratic internal mode machine.

### 5. Python vs GPT Responsibility Split
- Python owns deterministic work:
  - issue packet construction
  - severity
  - affected quarter scope
  - eligible lever space
  - tolerance checks
  - progress / regression / stall detection
  - accounting checks
  - viability checks
  - retry discipline
  - checkpoint acceptance / rejection
- GPT owns judgment:
  - strategic posture
  - tradeoffs
  - degree of deviation from intake
  - which lever families to use
  - how to respond when a tactic fails
  - how broad or narrow the next move should be

## Durable SQL Model

### A. `intake_consult_drafts`
Role:
- latest accepted draft snapshot
- latest accepted business facts
- latest accepted model snapshot
- latest accepted finmo snapshot
- latest accepted planning summary visible to the app and reporting

Keep here:
- `model_input_json`
- `finmo_json`
- `planning_run_json`
- `numeric_solver_feedback_json`
- current flat reporting fields already useful for UI / Excel

Important rule:
- This table is not the full execution history.

### B. `planning_runs`
Role:
- current execution truth for one run
- one draft may have many runs
- every rerun creates a new `planning_run_id`

Must track at minimum:
- `planning_run_id`
- `draft_id`
- `client_id`
- `run_status`
- `current_stage`
- `current_stage_status`
- `current_iteration`
- `current_retry_count`
- `current_cycle`
- `latest_detected_issue_count`
- `latest_remaining_issue_count`
- `latest_resolved_issue_count`
- `latest_checkpoint_id`
- `last_heartbeat_at`
- `started_at`
- `completed_at`
- `failure_reason`
- `trigger_type`

### C. `planning_run_checkpoints`
Role:
- durable resume truth
- audit trail of accepted execution state

Must hold accepted snapshots such as:
- controller resolution state
- planning payload
- numeric solver feedback
- `model_input_json`
- `finmo_json`
- diagnostics
- iteration / cycle / stage metadata

Important rule:
- Resume should come from the latest accepted checkpoint, not by guessing from the draft row.

### D. `planning_stage_events`
Role:
- operational timeline / observability
- lightweight stage and retry telemetry

Examples:
- stage entered
- planner called
- solver called
- checkpoint written
- stall detected
- attempt accepted / rejected
- run resumed
- run completed

## Canonical Truth Rules

### Current Run Truth
- `planning_runs` is the canonical record for current execution state.

### Resume Truth
- `planning_run_checkpoints` is the canonical source for resume and audit history.

### Latest Visible Draft Truth
- `intake_consult_drafts` is the canonical latest accepted business-plan snapshot.

### Operational Timeline
- `planning_stage_events` is the canonical timeline for observing what happened.

## Runtime Model

### What Lives In Memory
- working model state
- working finmo state
- retry memory
- live issue ledger
- transient planner inputs / outputs

### What Must Persist Continuously
- run stage / status
- heartbeat
- issue counts
- latest accepted snapshots
- accepted checkpoints
- final completion state

## Unified Convergence Engine Target

### What We Are Replacing
Current direction to move away from:
- realism as a heavyweight retry engine
- cash strategy as a heavyweight retry engine
- stabilizer as a heavyweight retry engine
- final guarantee as the only stage that truly must finish

### What We Are Building
Target direction:
- one unified convergence engine
- one GPT/solver loop
- one deterministic evaluation layer
- one persistence path

### Loop Shape
The unified loop should behave like this:
1. Python evaluates current model state and issue state.
2. Python builds deterministic issue / constraint / lever eligibility context.
3. GPT sees the business holistically.
4. GPT emits strategic posture, targets, and lever-family intent.
5. Solver runs numerically.
6. Finmo recalcs.
7. Python evaluates result quality, progress, and viability.
8. Retry only if needed, under strict change discipline.

### Behavior Expectations
- Broad when structural damage is severe.
- Narrow when viability improves.
- Broaden again only when a stall or regression requires it.
- Exit only when remaining issues are zero and viability still holds.

## Completion Invariant
The system must not mark a run complete unless all are true:
- canonical remaining issues = 0
- accounting check passes
- viability holds
- latest accepted checkpoint persisted
- `planning_runs.run_status = completed`
- latest accepted draft snapshot mirrored back into `intake_consult_drafts`

## What This Phase Does Not Change Yet
- no schema migrations yet
- no planner refactor yet
- no solver contract rewrite yet
- no legacy-path deletions yet

This phase only locks the architecture target so later implementation has a stable design reference.

## Immediate Follow-On Implementation Order
1. Add SQL tables and indexes.
2. Build centralized post-intake persistence service.
3. Add run lifecycle semantics.
4. Flatten critical monitoring fields.
5. Start refactoring away from multiple top-level convergence loops.
