# Evaluation Rules

## A Change Is Better When

- the run succeeds
- or the first failing quarter moves later
- or the cash-band miss gets smaller
- or the failure becomes more precise and closer to the true root cause
- or a backend pipeline failure becomes a normal planning failure that can be iterated on
- or realism clearly improves
- or the 20-quarter cash shape becomes more visibly consistent with the selected cash strategy without becoming less believable
- or the grid more faithfully obeys the intended quarter-by-quarter baby-AI cash posture across all quarters rather than only matching a few anchor points
- or row-to-row coherence improves so the plan reads more like one real business and less like disconnected line-item edits
- or the row magnitudes materially support the claimed strategy instead of only showing timid directional movement

## A Change Is Worse When

- rows become flat or mechanically repeated without a believable reason
- revenue / COGS / payroll / marketing / G&A lose realism
- the fix only hides the failure instead of solving it
- the helper starts reusing stale drafts or stale evidence
- solver tuning is used to compensate for obviously bad upstream inputs
- the change hardcodes business values or quarter outcomes instead of repairing the app behavior that generated them

## Realism Red Flags

- Q2-Q20 rows are constant with no business justification
- P&L lines look peanut-buttered across quarters
- cash posture is visible only because the operating plan became unrealistic
- cash strategy becomes invisible in the 20-quarter outputs even when the app says strategy should matter
- the grid behaves as though baby-AI cash is only advisory instead of a binding quarter-by-quarter law
- rows no longer work together logically even if the run still passes
- the narrative claims major deployment, retention, or extraction but the rows only show maintenance-scale movement
- the plan “passes” but reads less like a real operating business

## Root-Cause Priority Order

Prefer investigating in roughly this order:

1. app orchestration / handoff bugs
2. prompt and payload authority problems
3. fallback logic that silently flattens rows
4. infeasible cash / planning setup
5. solver logic

## Stopping Rule

The helper may keep going up to the configured iteration cap.

But when comparing alternatives, prefer the fix that:

- restores the intended product behavior
- keeps the production runtime simpler
- improves realism
- and reduces repeated failure modes across reruns
