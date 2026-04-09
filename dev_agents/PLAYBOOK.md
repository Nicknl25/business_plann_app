# Dev Agents Playbook

This helper system is dev-only. It is not part of the production app.

## Product Intent

The app turns intake answers into a believable forward-looking business plan.

After intake, the important production behavior is:

- intake gathers business facts and financial setup
- baby AI helps shape strategy-oriented guidance
- grid AI builds the quarter grid
- the model and solver evaluate feasibility
- the resulting plan should look like a real business, not a mechanically convenient spreadsheet

## Current Intended Runtime Shape

The intended production runtime currently mirrors the older good flow anchored by commit `5367da4` for:

- `python/client_intake_and_finmo/quarter_grid.py`
- `python/financial_model_engine/solver.py`
- `python/api_handlers/intake_consult.py`

The intended production AI shape is:

- original baby AI
- original grid AI

## Baseline / Quarter Treatment

- Q1 is the anchored quarter.
- Q2 through Q20 baseline values are often spread placeholders rather than true future operating intent.
- Those later-quarter baseline values should be overridden when realism, strategy, and baby-AI cash constraints require it.
- The presence of later-quarter baseline values does not give them automatic authority.

## Intended AI Responsibility Split

The current intended production split is:

- baby AI owns strategic cash-posture guidance and the binding cash law
- grid AI owns actual quarter-grid row planning

That means:

- baby AI should define the intended cash posture in a way that acts as a real constraint on the plan
- baby AI should not directly author the operating rows, but its cash posture is not a nice-to-have suggestion
- grid AI is the component that turns strategy plus business facts into the actual quarter-by-quarter row behavior under that cash law
- grid AI must make the operating plan obey the cash constraints rather than treating them as advisory context
- grid AI must also preserve realism and cross-row business coherence while doing so

Do not “fix” the app by collapsing those responsibilities together unless the evidence clearly shows the product design itself is wrong.

## Intended Post-Intake Planning Process

After intake, the intended flow is:

1. intake captures business facts, financial setup, and the user’s cash strategy intent
2. baby AI interprets that cash-strategy intent and defines the quarter-by-quarter cash posture that the rest of the plan must obey
3. grid AI receives the business context, baseline context, and strategy guidance
4. grid AI constructs the actual quarter-by-quarter planning grid
5. the model and solver evaluate the resulting plan
6. the output should show a believable business with visible strategy expression in ending cash over the 20-quarter horizon

In this design:

- baby AI is not the quarter-grid author
- grid AI is not supposed to ignore or soften baby-AI cash constraints
- baby-AI cash posture must be respected quarter by quarter across the entire 20-quarter horizon, not just in a few anchor quarters
- grid AI must make rows work together where the business logic requires interaction, rather than treating each row as an isolated knob
- the correct plan is one where realism, cash-constraint obedience, and row-to-row coherence all hold at the same time
- solver is not supposed to invent strategy; it only works with the planning problem it receives

## Universal Cash-Strategy Expression

The target is not merely to make reinvest visible.

The target is to make each of the four cash strategies materially visible, realistic, and business-type-appropriate:

- reinvest
- preserve cash
- shareholder return
- balanced

Grid AI should infer the believable deployment or retention channels from the business type itself, then use the existing rows to express the chosen strategy.

Examples of the principle:

- a clinic may express reinvest through providers, rooms, equipment, footprint, marketing, or working-capital support
- a retail concept may express it through locations, inventory, staffing, and store buildout
- a SaaS business may express it through hiring, marketing, product build, and infrastructure

The point is not to hardcode those outputs. The point is to make the system infer them from business type and then express them through the existing rows.

Do not reintroduce deleted experimental production modules unless there is no simpler root-cause fix:

- `python/client_intake_and_finmo/cash_contract_baby_ai.py`
- `python/client_intake_and_finmo/capital_allocation_baby_ai.py`

## Non-Negotiable Invariants

- Fix root causes, not bandaids.
- Treat solver as downstream by default. Solver can only work with the rows, bands, and targets it receives.
- Preserve realism. A solver pass with unrealistic P&L behavior is not a win.
- Do not flatten Q2-Q20 by accident.
- Do not introduce business-specific hardcodes for the med spa test.
- Do not hardcode quarter values, row values, cash paths, or business outcomes just to make a run pass.
- Do not act as the planner by inserting ad hoc business numbers directly. Fix the app logic, prompts, payloads, fallbacks, orchestration, or model behavior that caused the bad plan.
- Do not silently change the product philosophy just to make a test pass.
- Use fresh artifacts from the current run whenever possible.
- A backend `500` or `system_run_failed` is a planning failure to diagnose, not a reason to stop.

## What “Realistic” Means Here

Realism means:

- revenue, COGS, payroll, marketing, and G&A should evolve in believable ways
- strategy should be visible without destroying business logic
- cash behavior should emerge from a believable business plan
- the selected cash strategy should be visibly legible across the 20-quarter horizon rather than disappearing into a generic staircase
- the row magnitudes should support the claimed strategy, not merely move in the right direction by token amounts
- later-quarter rows should not become flat just because a fallback or baseline spread leaked through

Realism does not mean:

- preserving every baseline value forever
- forcing cash at the expense of believable P&L mechanics
- making every quarter wildly different for cosmetic reasons

## Root-Cause Heuristics

If the run fails after intake, prefer these explanations before blaming solver:

- prompt or payload authority is pushing AI too close to baseline
- baseline or fallback logic is flattening rows
- cash path is infeasible relative to the operating engine
- capital deployment ranges are too weak
- the operating engine remains too strong for the cash posture
- a Q1 anchor or handoff pipeline is internally inconsistent

Only reach for solver changes when the evidence clearly shows solver logic is the root issue.

## Good Fixes

Good fixes usually:

- repair upstream orchestration, prompt, payload, fallback, or handoff logic
- restore intended runtime behavior
- reduce repeated failure modes
- preserve or improve realism
- make the next rerun more informative

## Bad Fixes

Bad fixes usually:

- tune solver to hide upstream planning problems
- add ad hoc med-spa-specific rules
- insert hardcoded planning values or direct quarter outcomes instead of fixing why the app produced bad ones
- remove important business context just to reduce prompt complexity
- create a fake pass while keeping unrealistic flat rows
- add new production AI layers when the intended runtime is the simpler original flow

## What Success Looks Like

Success is not just “no exception.”

Success means:

- the run completes or gets materially closer to completion
- the first failing quarter moves later, or the failure becomes smaller and better explained
- the P&L remains believable
- the 20-quarter cash path visibly expresses the intended cash posture while staying realistic
- fixes are understandable and traceable
- the system gets better at solving the real planning problem rather than routing around it
