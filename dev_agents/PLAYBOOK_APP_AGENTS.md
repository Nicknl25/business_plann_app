# Dev Agents Playbook

This helper system is dev-only. It is not part of the production app.

## Product Intent

The app turns intake answers into a believable forward-looking business plan.

After intake, the important production behavior is:

- intake gathers business facts and financial setup
- four specialist app agents build the planning view
- the solver evaluates the resulting grid
- the resulting plan should look like a real business, not a mechanically convenient spreadsheet

## Current Intended Runtime Shape

The intended production runtime is now the app-agent planner under:

- `python/client_intake_and_finmo/app_agents/`
- `python/api_handlers/intake_consult.py`
- `python/client_intake_and_finmo/intake_consult_draft.py`

The intended production AI shape is:

- `realism_agent`
- `operations_agent`
- `capital_agent`
- `grid_agent`

`grid_agent` is the final integrator, but it is constrained by the other three agents.

## App-Agent Responsibility Split

- `realism_agent`
  - owns business-model and business-type realism
  - defines what is believable and what is forbidden

- `operations_agent`
  - owns operating feasibility
  - defines what staffing, throughput, capacity, facility, and sequencing behavior is actually supportable

- `capital_agent`
  - owns liquidity, capital allocation, and visible cash-strategy expression
  - defines what the four cash strategies should mean for this business in a materially visible way

- `grid_agent`
  - owns final grid assembly
  - must preserve solver contract
  - must not ignore specialist constraints
  - must surface `blocked` status if the specialist constraints cannot be satisfied together

## Non-Negotiable Invariants

- Fix root causes, not bandaids.
- Solver contract must not change.
- Grid shape must not change.
- Row ids, row meanings, quarter count, and min/max semantics must not change.
- Do not reintroduce deleted legacy planner infrastructure.
- Do not hardcode quarter values, row values, cash paths, or business outcomes just to make a run pass.
- Do not add med-spa-specific heuristics.
- Do not treat specialist-agent outputs as optional commentary; they are binding planning data.
- Preserve realism, row coherence, and visible strategy expression together.
- A backend `500` or `system_run_failed` is a planning failure to diagnose, not a reason to stop.

## Legacy Deletions To Preserve

The following planner surfaces are legacy and must stay deleted unless there is overwhelming evidence that the architecture itself was wrong:

- `python/client_intake_and_finmo/quarter_grid.py`
- `python/client_intake_and_finmo/realism_memo.py`
- `python/client_intake_and_finmo/prompts/quarter_grid/*`
- `python/client_intake_and_finmo/prompts/realism_memo/*`

Do not "fix" the app by quietly rebuilding those paths under new names.

## Universal Cash-Strategy Expression

This is not a reinvest-only problem.

All four cash strategies must work in a materially visible, realistic, business-type-appropriate way:

- reinvest
- preserve cash
- shareholder return
- balanced

The business type should reveal the believable deployment, retention, extraction, or liquidity mechanisms. The selected strategy should determine how strongly those mechanisms are used.

## What "Realistic" Means Here

Realism means:

- business-model and business-type behavior are believable
- revenue, COGS, payroll, marketing, G&A, financing, and capital deployment evolve in believable ways
- row-to-row behavior reads like one integrated operating business
- cash strategy is visible in the 20-quarter outputs
- row magnitudes support the claimed strategy, not just the narrative

Realism does not mean:

- preserving stale planning assumptions
- hiding cash problems behind weak row movement
- making every quarter noisy for cosmetic reasons

## Good Fixes

Good fixes usually:

- repair app-agent prompts, schemas, orchestration, validation, solver-bridge logic, or persistence
- add end-to-end execution tracing when planner failures are opaque
- improve specialist-agent constraint quality
- improve `grid_agent` integration under specialist constraints
- preserve solver contract while improving realism
- make the next rerun more informative

## Authority

The dev agents have authority to change any file inside this repo that is needed to get the app-agent planner working, including:

- runtime API handlers
- app-agent code
- schemas
- prompts
- DB persistence code
- debug tracing
- runner scripts
- tests

Do not stop at the first top-level `500`. Trace the execution path end to end until the failing substep is identified.

## Bad Fixes

Bad fixes usually:

- reintroduce legacy planner code
- tune solver to hide upstream planning problems
- inject ad hoc business numbers
- weaken specialist constraints so `grid_agent` can pass more easily
- create a fake pass while realism degrades

## What Success Looks Like

Success is not just "no exception."

Success means:

- the run completes or gets materially closer to completion
- the app-agent payload is internally coherent
- specialist outputs are meaningful structured planning data
- the final grid preserves solver contract
- the 20-quarter cash path visibly expresses the selected strategy while staying realistic
- fixes are understandable and traceable
