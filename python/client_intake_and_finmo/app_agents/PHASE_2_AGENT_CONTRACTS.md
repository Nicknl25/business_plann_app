# Phase 2 Agent Contracts

## Purpose

Define the machine-usable responsibilities and outputs for the four app agents.

## Common rule for all specialist agents

The specialist agents are not prose-only advisors.

Each specialist agent must return structured output that includes:
- business read
- constraints
- vetoes
- row-level implications
- quarter-level implications
- magnitude guidance
- risks or tensions

Grid agent must consume those outputs directly.

## `realism_agent`

### Role

Owns business-model realism and business-type realism.

### Must answer

- What is believable for this kind of business?
- What is not believable?
- What growth, margin, staffing, facility, utilization, and cash stories would be nonsense?
- What row combinations would violate the business model or business type?

### Output must include

- binding realism constraints
- forbidden patterns
- realism vetoes
- row-level implications
- quarter-level realism pacing implications

## `operations_agent`

### Role

Owns operational feasibility.

### Must answer

- What can the business actually absorb operationally?
- How fast can capacity, staffing, throughput, and footprint move?
- What dependencies exist between growth and supporting rows?
- What expansion stories are operationally possible or impossible?

### Output must include

- operating constraints
- sequencing constraints
- support-row dependencies
- operational vetoes
- row-level implications
- quarter-level pacing implications

## `capital_agent`

### Role

Owns liquidity posture, buffers, accumulation, redeployment, shareholder return, and the four cash strategies.

### Must answer

- How much cash must stay as buffer?
- What counts as excess cash?
- When should excess cash trigger action?
- What kind of deployment or retention is believable for this business type?
- How should each of the four strategies become visibly legible in ending cash and supporting rows?

### Output must include

- liquidity constraints
- cash posture constraints
- strategy-specific implications
- capital allocation vetoes
- row-level implications
- quarter-level timing and deployment implications
- magnitude guidance for meaningful strategy expression

## `grid_agent`

### Role

Owns final integration and quarter-grid authoring.

### Must answer

- Can all specialist constraints be satisfied together?
- If not, what is the blocking contradiction?
- What exact quarter-grid min/max bands satisfy realism, operations, and capital together?
- Does the final grid remain solver-compatible without changing downstream contract?

### Output must include

- consumed specialist outputs
- explicit conflict resolutions
- final integration rationale
- final quarter-grid JSON
- self-check against realism, operations, and capital constraints
- unresolved blockers if no valid plan exists

## Top-level persisted run payload

The full run must be stored in `app_agents_run_json` and include:
- shared context
- `realism_agent`
- `operations_agent`
- `capital_agent`
- `grid_agent`
- run metadata
- final planner status

