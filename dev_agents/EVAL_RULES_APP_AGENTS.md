# Evaluation Rules

## A Change Is Better When

- the run succeeds
- or the planner reaches `ready` instead of `blocked`
- or the first failing quarter moves later
- or the failure becomes more precise and closer to the true root cause
- or a backend pipeline failure becomes a normal planning failure that can be iterated on
- or realism clearly improves
- or the 20-quarter cash shape becomes more visibly consistent with the selected strategy without becoming less believable
- or the specialist-agent outputs become more meaningful and machine-usable
- or `grid_agent` more faithfully obeys realism, operations, and capital constraints
- or row-to-row coherence improves so the plan reads more like one real business
- or the row magnitudes materially support the claimed strategy

## A Change Is Worse When

- rows become flat or mechanically repeated without a believable reason
- revenue / COGS / payroll / marketing / G&A lose realism
- the fix only hides the failure instead of solving it
- specialist-agent outputs become weaker, vaguer, or easier for `grid_agent` to ignore
- solver tuning is used to compensate for obviously bad upstream inputs
- the change hardcodes business values or quarter outcomes instead of repairing planner behavior
- the change quietly rebuilds deleted legacy planner surfaces

## Realism Red Flags

- business-model behavior is numerically unsupported
- business-type behavior is implausible
- staffing, throughput, demand, and capital deployment stop making sense together
- cash strategy becomes invisible in the 20-quarter outputs
- the narrative claims major deployment, retention, or extraction but the rows only show maintenance-scale movement
- the plan "passes" but reads less like a real operating business

## Root-Cause Priority Order

Prefer investigating in roughly this order:

1. app-agent orchestration / handoff bugs
2. shared-context assembly problems
3. schema or prompt contract problems
4. `grid_agent` integration / constraint-resolution problems
5. solver-bridge translation bugs
6. solver logic

## Stopping Rule

The helper may keep going up to the configured iteration cap.

But when comparing alternatives, prefer the fix that:

- preserves the app-agent architecture
- keeps the solver contract unchanged
- improves realism
- strengthens specialist-agent constraint quality
- and reduces repeated failure modes across reruns
