# System Overview Update 4.23.26

## Purpose Of This File

This file is a Codex-facing handoff document for the `business_plann_app`
repository as it exists on `4.23.26`.

It is written as if a future Codex needs this file in order to truly understand
how the app works, what the hard architectural rules are, what the live
post-intake system is trying to do, and what must not be broken while making
changes.

If the thread, editor, or machine state is lost, a future Codex should read
this file first, then inspect the files referenced here before changing the
system.

## What This App Is

`business_plann_app` is a business-planning application that:

1. collects structured business intake,
2. converts that intake into normalized operating and financial inputs,
3. builds a deterministic driver model in `model_input_json`,
4. recalculates a financial model in `finmo_json`,
5. runs a post-intake repair/convergence system to fix realism, viability, and
   planning issues,
6. runs a post-convergence cash/capital pass,
7. persists the latest state and run history in SQL,
8. hands the accepted plan downstream to writing/reporting.

This is not a static form app. It is a guided business-synthesis and repair
system that tries to turn imperfect client input into a viable, commercially
believable plan.

## Non-Negotiable Architecture

### 1. Model Input Drives, FINMO Calculates

This is the most important system rule.

The architecture is:

`writable levers -> model_input_json drivers -> FINMO calculates -> financial outputs`

That means:

- `model_input_json` is the driver layer.
- `finmo_json` is the calculated output layer.
- Solver/GPT/Python may change drivers.
- They must not directly author financial outputs as if outputs were inputs.
- `FINMO` remains the calculation engine.

This must not be violated.

### 2. Mapping Is A Separate Layer

Mapping answers one question only:

`if a lever is used, what direct financial-model field does it hit?`

Mapping should not:

- guess,
- proxy,
- vary by issue,
- map to aggregates/ratios/margins,
- invent targets dynamically.

Mapping is now meant to be lookup-driven from one table, not buried across many
code paths.

### 3. Deterministic Work vs GPT Work

Python should own:

- intake normalization,
- model-input construction,
- deterministic mapping lookup,
- issue detection,
- packet building,
- validation,
- persistence,
- numeric execution boundaries,
- fail-fast behavior,
- deterministic derived-driver rules.

GPT should own:

- strategy,
- tradeoffs,
- lever choice within the allowed scope,
- how to solve the current problem within the deterministic contract,
- rationale.

Solver/numeric execution should own:

- applying exact approved lever changes to `model_input_json`,
- rebuilding `finmo_json`,
- reporting numeric before/after results.

### 4. Do Not Let Legacy Logic Fight The New System

The main recurring source of pain in this app has been legacy post-intake logic
that:

- broadened targets,
- used proxy metrics,
- guessed mappings,
- auto-completed GPT decisions,
- injected escalation behavior,
- or kept old fallback semantics alive after a redesign.

When a class of bug appears repeatedly, the right fix is usually:

- find the root legacy path,
- remove it from the active system,
- and make the new explicit contract the only live path.

## High-Level Flow

Current practical flow:

`intake -> normalize facts -> build model_input -> build finmo -> realism/issue scan -> quarter grid -> unified post-intake convergence -> cash pass -> writing`

There are three especially important transitions:

1. intake data becomes structured operating/financial facts,
2. those facts become `model_input_json`,
3. `model_input_json` becomes `finmo_json`, which is then repaired by the
   post-intake system.

## Core Durable Objects

### `intake_consult_drafts`

This is the main durable draft row.

It stores:

- intake-stage JSON payloads,
- `model_input_json`,
- `finmo_json`,
- planning/convergence payloads,
- cash review payloads,
- monitoring fields,
- latest accepted state.

Important JSON columns:

- `operating_model_json`
- `people_json`
- `financials_json`
- `financials_year1_json`
- `forecast_quarters_json`
- `model_input_json`
- `finmo_json`
- `planning_run_json`
- `planning_runtime_json`
- `planning_convergence_json`
- `repair_guidance_json`
- `convergence_state_json`
- `numeric_solver_feedback_json`

Important flat monitoring columns:

- `planning_stage`
- `planning_status`
- `planning_run_status`
- `planning_current_cycle`
- `planning_current_retry_count`
- `planning_remaining_issue_count`
- `planning_resolved_issue_count`
- `planning_failure_reason`

### `planning_runs`

This is the active run-tracking table for current execution truth.

### `planning_run_checkpoints`

This is the durable checkpoint table used to persist important accepted states
and provide resume/recovery history.

### `planning_stage_events`

This is the event/timeline table for monitoring what the system is doing over
time.

## Main Runtime Owners

### 1. Main Orchestrator

File:

- `python/api_handlers/intake_consult.py`

This file is the control tower for:

- intake session flow,
- post-intake system-run orchestration,
- unified convergence,
- cash strategy review / cash pass,
- validation,
- persistence hooks,
- runtime probe/status surfaces,
- planning packet construction.

If a future Codex only reads one code file first, it should usually be this
file.

### 2. Model Input / FINMO Bridge

File:

- `python/client_intake_and_finmo/finmo_bridge.py`

This file owns:

- Python-side construction of `model_input_json`,
- Q0/stub anchoring,
- deterministic derived-driver policies,
- Python-side build of `finmo_json` from `model_input_json`,
- the hard boundary:
  - model input in,
  - FINMO outputs out.

This is where the rule `model_input drives, FINMO calculates` is concretely
enforced.

### 3. Numeric Execution Boundary

File:

- `python/client_intake_and_finmo/numeric_execution.py`

This file owns the shared numeric execution boundary between planning logic and
the model. It is where the system:

- defines solver/numeric contract shapes,
- translates accepted lever changes into exact model-input writes,
- rebuilds `finmo_json`,
- and returns before/after payloads to the planner.

The important principle here is:

- planning chooses,
- numeric execution applies,
- FINMO recalculates.

### 4. Exact Driver Writes

File:

- `python/client_intake_and_finmo/quarter_grid.py`

This file is responsible for quarter-grid behavior and direct application of
exact lever updates to `model_input_json`.

It is part of the writable-driver layer, not the financial-output layer.

### 5. Draft Persistence Layer

File:

- `python/client_intake_and_finmo/intake_consult_draft.py`

This file owns SQL schema/bootstrap and most draft persistence/update behavior.

It is where the app turns large runtime payloads into durable database state.

## How Model Input Is Built

The Python-side model-input build starts in:

- `python/client_intake_and_finmo/finmo_bridge.py`
- `build_python_model_input_json(...)`

That function:

1. creates a baseline `model_input_json` template,
2. fills revenue, expense, balance-sheet, and schedule rows,
3. applies deterministic Q0/stub anchoring,
4. applies deterministic derived-driver policies,
5. returns a ready `model_input_json`.

Important current rule:

- the app should treat `model_input_json` as the only writable source of truth
  for what drives the model.

## How FINMO Is Built

The Python-side FINMO build happens in:

- `python/client_intake_and_finmo/finmo_bridge.py`
- `build_python_finmo_json(...)`

This function:

1. takes `model_input_json`,
2. reapplies derived-driver policies to make sure deterministic derived rows are
   current,
3. converts that into `FinancialModelInputs`,
4. calls the financial model,
5. returns calculated quarter rows and rollforwards as `finmo_json`.

That is the core implementation of:

`model_input_json -> FINMO -> finmo_json`

## Mapping Layer

### Current Direction

Mapping is now intended to be table-driven from one single lookup source.

Current active loader:

- `python/client_intake_and_finmo/post_intake_mapping.py`

Current mapping table:

- `python/client_intake_and_finmo/config/post_intake_driver_target_mapping.csv`

That table is meant to answer:

- `lever_id`
- `driver_category`
- `target_driver`
- `model_input_field`
- `financial_model_field`
- `impact_type`
- `notes`

### What Mapping Means Now

Mapping should now be read as:

`lever_id -> direct financial_model_field hit`

The execution layer may still add:

- issue context,
- quarter context,
- allowed action scope.

But mapping itself should remain simple lookup.

### What Mapping Must Not Do

Mapping must not:

- use proxy target metrics,
- choose different targets based on issue code,
- map levers to aggregates like EBITDA or ratios,
- guess from “close enough” metrics,
- compete with the lookup table via old in-code dictionaries.

### Why The Table Matters

The main benefit of the table is that when the app says a lever is supposed to
move something, everyone can inspect the same source of truth instead of
debugging scattered mapping logic.

This should make:

- target selection more reliable,
- solver targeting more reliable,
- GPT packets clearer,
- and debugging much easier.

## Derived Drivers

Some rows in `model_input_json` are not supposed to stay arbitrary direct
controller inputs forever. They are derived deterministically from upstream
drivers.

### Payroll

Payroll is already treated as a derived driver:

- revenue-driven,
- OEWS-informed,
- deterministic in the derived-driver layer.

It is removed from writable controller scope and recomputed in
`apply_derived_driver_policies_to_model_input(...)`.

### Capex / Depreciation

As of `4.23.26`, capex and depreciation are also handled in the derived-driver
layer.

Current deterministic rule:

- maintenance capex comes from prior PPE,
- expansion capex comes from structural `Capacity` growth only,
- final capex used for the quarter drives depreciation,
- depreciation is converted into the existing FINMO input format:
  `percent_of_prior_ppe`.

Important boundaries:

- no FINMO formula change,
- no convergence ownership,
- no cash-pass ownership,
- no revenue-based fallback,
- no utilization-based trigger,
- no proxy logic.

This logic lives in:

- `python/client_intake_and_finmo/finmo_bridge.py`
- `_derived_capex_and_depreciation_runtime(...)`
- `apply_derived_driver_policies_to_model_input(...)`

## Quarter Grid

Quarter grid is the first post-intake planning layer that creates a
quarter-by-quarter shape for the business.

Its job is to produce a concrete driver path, not to be the whole convergence
engine.

It should:

- shape the initial forecast horizon,
- write exact quarter driver values,
- hand off a usable starting point to convergence.

It should not:

- become a second hidden planning engine,
- own final realism resolution,
- or compete with the unified convergence loop.

## Unified Post-Intake Convergence

The intended post-intake convergence system is one unified loop.

The current direction is:

- one real convergence owner,
- not multiple heavyweight mini-engines,
- not separate top-level realism/stabilizer/guarantee/cash engines competing.

High-level cycle:

1. Python reads current `model_input_json` and `finmo_json`.
2. Python detects and scores issues.
3. Python builds a compact current-cycle planning packet.
4. GPT chooses a strategy and exact allowed moves within that packet.
5. Numeric execution applies the changes to `model_input_json`.
6. FINMO recalculates.
7. Python measures progress and decides whether to continue.

Important current rule:

- post-intake should be treated as a convergence/repair system, not as a
  writing problem or a prompt-only problem.

## Cash Pass

Cash pass is a separate post-convergence capital-allocation layer.

It currently runs after convergence and is designed to:

- evaluate liquidity/buffer position,
- apply hard cash rules,
- let GPT choose financing/capital moves within a constrained scope,
- validate the result.

Important current architectural rule:

- it is a capital-allocation / liquidity pass,
- not a replacement for FINMO,
- not a replacement for convergence,
- not a hidden Python top-up system.

The intended boundary is:

- convergence repairs the business shape,
- cash pass handles the resulting financing/liquidity posture.

## Current Important Product Rules

### 1. Intake Is Not Sacred

If the business is unrealistic, the app is allowed to move away from intake.

### 2. Driver Layer Is Sacred

The writable layer is `model_input_json`.

Outputs should not be treated like direct inputs.

### 3. Mapping Must Stay Explicit

If a lever hits a target, that relationship should come from the table, not
from fuzzy code logic.

### 4. Legacy Compensation Should Not Come Back

The system has historically suffered from helper paths that:

- patched incomplete GPT output,
- inferred missing targets,
- widened target sets,
- rewrote mappings,
- or let old escalation logic veto valid runs.

That kind of compensation should be removed, not revived.

### 5. Fix Classes Of Bugs, Not One-Off Symptoms

If the same bug appears across multiple drafts, it is usually a sign of one
shared active logic path, not many separate bugs.

The right response is:

- identify the root class,
- fix it everywhere it is active,
- and add fail-fast when appropriate.

## Persistence And Observability

Post-intake state should always be visible in SQL.

That means:

- current run stage should be visible,
- current planning status should be visible,
- latest `model_input_json` and `finmo_json` should be visible,
- convergence packets should be visible,
- checkpoint history should be visible,
- and failures should be inspectable after the fact.

This app is designed to be operationally inspected, not treated like a black
box.

## E2E / Live Validation

Preferred persisted-run E2E entrypoint:

- `Test Files/run_persisted_system_run.py --draft-id <draft_id> --base-url http://127.0.0.1:5050`

That runner:

1. loads a persisted intake-complete source draft,
2. clones it into a fresh draft/session,
3. triggers the system-run on the local backend,
4. lets the app persist the resulting state back to SQL,
5. makes it easy to inspect the cloned run independently.

This is the preferred way to validate post-intake behavior when the user wants
real SQL-visible proof.

## What A Future Codex Should Inspect First

If resuming work on this repo, inspect in this order:

1. `context/current_state.md`
2. `context/next_steps.md`
3. this file
4. `context/system_overview_update_4.18.26.md`
5. `python/api_handlers/intake_consult.py`
6. `python/client_intake_and_finmo/finmo_bridge.py`
7. `python/client_intake_and_finmo/post_intake_mapping.py`
8. `python/client_intake_and_finmo/numeric_execution.py`
9. `python/client_intake_and_finmo/intake_consult_draft.py`

Then verify:

- how `model_input_json` is being built,
- whether mapping is coming from the table,
- what current post-intake packet is actually being sent,
- what SQL JSONs are updating,
- and whether the live behavior matches the claimed architecture.

## What Success Looks Like

A healthy run should:

- build a valid `model_input_json`,
- produce a valid `finmo_json`,
- run quarter grid,
- run one unified post-intake convergence owner,
- run cash pass afterward,
- persist cycle/run truth into SQL,
- and finish with a commercially believable model.

At the architecture level, success also means:

- mapping is table-driven,
- `model_input` remains the writable driver layer,
- `FINMO` remains calculation-only,
- derived drivers are handled deterministically upstream,
- and legacy compensating logic does not quietly override the new system.

## Final Reminder

If a future Codex forgets everything else, it should remember these three
things:

1. `model_input` drives and `FINMO` calculates.
2. mapping should be explicit lookup, not fuzzy logic.
3. the hard part of this app is post-intake repair/convergence, not form
   collection and not writing.
