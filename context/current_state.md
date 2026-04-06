# Current State

## Working Now
- Python-first planning flow is live.
- Intake can reach a backend planning-ready state and persist the necessary draft artifacts.
- Baby AI realism review is implemented and stored as `realism_memo_json`.
- Quarter-grid planning runs off the live Python model path.
- Solver runs after grid generation and produces solved outputs plus diagnostics.
- Replay/debug tooling exists for grid and solver runs.

## Recent Breakthroughs
- Baby AI is now separated from the main planner and has a narrow advisory contract.
- Legacy workbook-heavy / old forecast-planning path has been purged from the main system path.
- The old closeout governor path has been removed; the real planning path is now critic -> grid -> solver.
- Financials flow has been tightened to align more directly with ops context.
- Live planning outputs are persisted in `planning_run_json` rather than hidden behind chat-only state.

## Important Nuance
- The live intake flow now ends at Financials and hands off to planning artifacts plus system-run.
- Treat planning persistence as infrastructure, not as a second controller layer.
- Do not rebuild the old closeout governor model.

## Actively Being Worked On
- Simplifying the financials consult so it captures less noise and reaches planning faster.
- Converting payroll assumptions into explicit FTE / labor-capacity constraints.
- Integrating cash preference into planning behavior without breaking feasibility.
- Adding R&D gating so R&D appears only when the business and stage justify it.
