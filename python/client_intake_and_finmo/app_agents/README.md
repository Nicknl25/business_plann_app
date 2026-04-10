# App Agents Phase 1

This folder is the clean-room staging area for replacing the current app-side planner with a new multi-agent planner.

Phase 1 is intentionally non-invasive. It freezes the current planner surfaces, records the solver contract that must remain unchanged, and defines the migration rules for the cutover.

Current Phase 1 baseline:
- Recorded on: `2026-04-09`
- Git `HEAD`: `6ba13fc`
- Runtime note: the live worktree is intentionally not a pure `HEAD` checkout. It reflects the realism-memo-era runtime plus manual removal of all consistency code and mechanics.

Phase 1 deliverables in this folder:
- `PHASE_1_CURRENT_STATE.md`
- `PHASE_1_SOLVER_CONTRACT.md`
- `PHASE_1_CUTOVER_RULES.md`
- `phase_1_manifest.json`

Phase 1 does not introduce any new planner logic.

Phase 2 deliverables in this folder:
- `PHASE_2_SHARED_CONTEXT.md`
- `PHASE_2_AGENT_CONTRACTS.md`
- `PHASE_2_CONFLICT_RULES.md`
- `phase_2_manifest.json`
- `schemas/`

Phase 2 also does not introduce planner runtime logic. It defines the shared context contract, the per-agent output contracts, the persisted app-agent run payload, and the binding conflict-resolution rules.

Phase 3 deliverables in this folder:
- `phase_3_manifest.json`
- `__init__.py`
- `version.py`
- `schema_loader.py`
- `agent_base.py`
- `shared_context.py`
- `run_payload.py`
- `realism_agent.py`
- `operations_agent.py`
- `capital_agent.py`
- `grid_agent.py`

Phase 3 creates the clean-room Python package and scaffolding for the new planner, but it still does not wire the new planner into live runtime.

Phase 4 deliverables in this folder:
- `phase_4_manifest.json`
- `openai_client.py`
- `prompt_loader.py`
- `prompts/realism_agent.md`
- `prompts/operations_agent.md`
- `prompts/capital_agent.md`

Phase 4 upgrades the three specialist agents from scaffolds to real structured-output agents that can call OpenAI using strict JSON schemas. It still does not wire the new planner into live runtime.

Phase 5 deliverables in this folder:
- `phase_5_manifest.json`
- `schema_validation.py`
- `planner.py`

Phase 5 adds the full planner orchestration layer. It validates shared context and per-agent outputs, runs the specialist agents, passes their outputs into `grid_agent`, and assembles the final `app_agents_run_json` payload. It still does not cut over live runtime.

Phase 6 deliverables in this folder:
- `phase_6_manifest.json`

Phase 6 is the live wiring cutover. The production `system-run` path now routes through `AppAgentsPlanner`, persists `app_agents_run_json`, and still hands the same grid shape to the unchanged solver path.

Phase 7 deliverables in this folder:
- `phase_7_manifest.json`
- `PHASE_7_VALIDATION.md`
- `validation.py`
- `scenario_matrix.json`
- `schemas/validation_result.schema.json`

Phase 7 adds the validation framework for the new planner: scenario matrix, quality gates, and structured evaluation results for contract integrity, planner readiness, strategy visibility, staircase risk, and row coherence.
