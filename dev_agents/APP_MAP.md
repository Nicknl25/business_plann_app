# App Map

## Core Runtime Surfaces

- `python/api_handlers/intake_consult.py`
  - entry point after intake
  - orchestrates the handoff into planning/system-run
  - a likely root-cause surface for backend `500` failures and handoff bugs

- `python/client_intake_and_finmo/quarter_grid.py`
  - main planning/orchestration surface
  - planning mode classification
  - prompt payload assembly
  - target extraction
  - bridge between AI planning output and solver/model evaluation
  - a likely root-cause surface for prompt leakage, baseline authority, target setup, and flat-row behavior
  - primary surface where grid AI receives context and produces quarter-grid rows

- `python/financial_model_engine/solver.py`
  - optimization engine
  - should honor the problem it is given
  - not the primary scapegoat when upstream planning inputs are infeasible

## Support / Execution Surfaces

- `Test Files/run_live_args_intake.py`
  - live test harness that drives the intake/planning flow

- `Test Files/run_live_args_intake_1_product.py`
  - one-product wrapper around the live test harness

- `Test Files/run_dual_agent_intake.py`
  - posts to the local backend and reports failures

## Intended AI Process

- baby AI:
  - interprets the selected cash strategy
  - defines the intended cash posture as a binding quarter-by-quarter constraint
  - should not directly author quarter-grid rows
  - is not optional context; its cash output is something the rest of the planning system must honor

- grid AI:
  - receives business facts, baseline context, and baby-AI cash constraints
  - produces the actual quarter-by-quarter planning rows
  - is the main AI surface responsible for making strategy visible in the plan while preserving realism
  - must build every quarter in relation to the baby-AI cash constraints, not just early or late anchor quarters
  - should be treated as failing if it produces a plan that does not align with the intended quarter-by-quarter cash posture
  - must keep interacting rows logically coherent, so revenue, COGS, payroll, marketing, G&A, debt behavior, capex, and cash all read like one believable business system

## Baseline Context Interpretation

- Q1 baseline is the most anchored operating reference.
- Q2-Q20 baseline values may exist in the app, but they are often synthetic spread values.
- Agents should not assume those later-quarter values are authoritative future intent.
- If the app is over-preserving Q2-Q20 baseline behavior, that is a legitimate root-cause surface.

- solver/model:
  - evaluate the planning problem handed to them
  - should not be expected to compensate for bad AI planning inputs

## Common Failure Classes

- `planning_solver_failed`
  - usually means the planning problem handed to solver is infeasible

- `system_run_failed`
  - backend pipeline failure; still analyzable

- `Q1 cash anchor was not derived and applied coherently`
  - handoff or audit inconsistency in the app’s cash-anchor pipeline

## What To Inspect First

When the run fails:

1. command stdout/stderr
2. latest draft row and `planning_run_json`
3. `gpt_grid_metadata`
4. authoritative cash bands and solved cash outputs
5. the first failing quarter
6. prompt/payload authority in `quarter_grid.py`

## Dangerous Anti-Patterns

- blaming solver first
- treating stale drafts as fresh evidence
- confusing a prompt-only issue with a logic/fallback issue
- treating flat rows as acceptable just because a run did not crash
- forgetting that the intended runtime is currently the older simpler baby-AI plus grid-AI flow
