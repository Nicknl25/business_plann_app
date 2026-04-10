# Critical Context

This file exists so the dev agents do not have to rediscover core product rules from scattered run history.

## Core Planning Truths

- The production planner is now the app-agent system under `python/client_intake_and_finmo/app_agents/`.
- The production AI shape is:
  - `realism_agent`
  - `operations_agent`
  - `capital_agent`
  - `grid_agent`
- `grid_agent` is the final grid author, but it is constrained by the outputs of the other three agents.
- Solver is downstream and must receive the same contract shape as before.

## Binding Constraint Rule

The specialist agents are not optional advisors.

- `realism_agent` defines believable and forbidden business behavior.
- `operations_agent` defines what is operationally supportable.
- `capital_agent` defines the cash-strategy and liquidity posture.
- `grid_agent` must satisfy those constraints together or return `blocked`.

## Solver Contract Rule

The new planner is a planner replacement, not a solver redesign.

Do not change:

- quarter count
- row ids
- row meanings
- min/max band semantics
- final solver payload shape

## Universal Strategy Rule

This is not a reinvest-only problem.

All four cash strategies must work in a materially visible, realistic, business-type-appropriate way:

- reinvest
- preserve cash
- shareholder return
- balanced

The business type should reveal the believable mechanisms. The chosen strategy should determine how strongly those mechanisms are used.

## Realism Rule

Everything the planner does must satisfy all of these at once:

- business-model realism
- business-type realism
- operational feasibility
- cash-strategy visibility
- cross-row business coherence

Rows must work together where business logic requires interaction. A valid plan should read like one believable business, not disconnected line-item edits.

## External Business Reasoning Rule

The app agents are expected to reason beyond local SQL.

They should use real-world business knowledge for:

- what this business type can plausibly do
- what growth opportunities are believable
- how staffing, facilities, demand, pricing, capital deployment, and liquidity usually behave
- how the selected cash strategy should visibly change the business

## Legacy Deletion Rule

Anything replaced by the new planner must stay deleted.

Legacy planner code must not be quietly reintroduced, including:

- `quarter_grid.py`
- `realism_memo.py`
- legacy quarter-grid prompts
- legacy realism-memo prompts

## What Not To Do

- Do not hardcode row values, quarter values, cash paths, or business outcomes.
- Do not add med-spa-specific heuristics.
- Do not weaken specialist outputs into vague prose suggestions.
- Do not let solver become the scapegoat for upstream planner failures.
- Do not preserve obsolete pre-cutover learnings as if they still describe the live architecture.

## Execution Trace Rule

When the planner fails, the dev agents must trace the live execution path end to end:

- API handler entry
- shared-context build
- each specialist-agent call
- grid-agent call
- schema validation
- solver handoff
- draft persistence

Do not treat an empty `app_agents_run_json` or a generic `system_run_failed` as the root cause.
