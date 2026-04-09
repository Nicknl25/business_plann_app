# Critical Context

This file exists so the dev agents do not have to rediscover core product rules from scattered run history.

## Core Planning Truths

- The intended production runtime is the older good post-intake flow anchored by commit `5367da4`.
- The intended production AI shape is the original `baby AI + grid AI` flow.
- The deleted experimental production modules should stay deleted unless there is overwhelming evidence that the product design itself must change.

## Baby AI vs Grid AI

- baby AI owns the intended cash posture and quarter-by-quarter cash law
- grid AI owns the actual quarter-grid row planning
- solver/model are downstream evaluators, not the source of strategy

This means:

- baby AI is not optional context
- baby AI is not just “nice-to-have” strategy flavor
- grid AI must build the plan under the baby-AI cash constraints across all quarters

## Quarter-by-Quarter Constraint Rule

- Cash must align with baby-AI intent quarter by quarter across the full 20-quarter horizon.
- This is not only about Q1, Q2, Q3, or the final quarter.
- A plan is still wrong if it only matches a few anchor quarters while drifting away elsewhere.

## Realism Rule

Everything grid AI does must satisfy all of these at once:

- realism
- baby-AI cash-constraint obedience
- cross-row business coherence

Rows must work together where the business logic requires interaction. A valid plan should read like one believable business, not disconnected line-item edits.

## Universal Strategy Rule

This is not a reinvest-only problem.

All four cash strategies must work in a materially visible, realistic, business-type-appropriate way:

- reinvest
- preserve cash
- shareholder return
- balanced

The same universal standard applies to all four:

- the business type should reveal the believable deployment or retention mechanisms
- the selected strategy should determine how strongly those mechanisms are used
- the resulting ending-cash path should be visibly different in a way that matches the chosen strategy
- the row magnitudes must numerically support the claimed strategy rather than only gesturing in the right direction

## Magnitude Rule

Directional movement is not enough.

If the narrative or strategy implies a material action such as expansion, major redeployment, meaningful retention, or capital extraction, the affected rows must show believable magnitude for that business type.

Bad example:

- claiming expansion while only making tiny maintenance-style capex moves

The system should infer *what* to invest in from the business type, not from a hardcoded rule.

## Baseline Treatment

- Q1 is the most anchored quarter.
- Q2 through Q20 baseline values are often synthetic spread placeholders.
- Those later-quarter baseline values are scaffolding, not truth.
- They should be overridden when realism, strategy, and baby-AI cash constraints require it.

Do not confuse “baseline exists” with “baseline should dominate planning.”

## What Not To Do

- Do not hardcode row values, quarter values, cash paths, or business outcomes just to make a run pass.
- Do not add med-spa-specific heuristics.
- Do not let solver become the scapegoat for upstream planning failures.
- Do not create a fake pass by flattening rows or preserving unrealistic spread values.

## Fix Philosophy

The agents are supposed to fix the app, not impersonate the planner.

Good fixes usually target:

- prompts
- payload authority
- fallback logic
- orchestration / handoff bugs
- validation rules
- model or solver behavior only when clearly necessary
