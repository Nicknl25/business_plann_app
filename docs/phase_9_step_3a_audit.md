# Phase 9 Step 3a — `post_intake_convergence/` import audit

**Audit date:** 2026-05-09
**Branch:** intake-stable

Per the directive: identify which `post_intake_convergence` consumers are
Phase-8-bypassed dead code vs genuinely live, so the directory can be
safely deleted.

## Live consumers (cannot delete without migration)

| Symbol | Consumer | Evidence | Disposition |
|---|---|---|---|
| `_persist_unified_convergence_state` | `post_intake_solver/orchestrator.py:2483` | Imports + calls in the Phase 9 finalize-stage persist block | **EXTRACT to `post_intake_persistence/`** before deleting convergence |
| `_build_planning_context_summary_payload` | `api_handlers/intake_consult.py:84` (then passed to `_run_unified_post_grid_system_run` at line 6872) | Builds the planning_context_summary input passed to every system run | **EXTRACT to a separate context-summary module** |
| `bind_runtime_dependencies` (runtime + runner) | `intake_consult.py:66-67`, called at intake_consult.py:221-222 | Threads handler-side helpers into runtime/runner globals before any run | Live indirectly: only matters because runtime helpers above are still called. Once those are extracted, bind hooks become no-ops and can be removed. |
| `build_retry_scope_payload`, `build_unified_convergence_contract_policy`, `evaluate_retry_improvement`, `full_horizon_quarters`, `full_horizon_retry_scope_mode`, `retry_scope_lever_ids`, `retry_scope_quarters`, `subset_numeric_solver_contract`, `unified_convergence_contract_constraints`, `validate_unified_convergence_contract_horizon` | `intake_consult.py:87-98` re-exports + listed in module `__all__` at lines 166-175 | Public-API surface; consumers outside intake_consult may import these names | **AUDIT each consumer** before removing. Most likely Phase-8-bypassed. |

## Phase-8-bypassed dead consumers

| Surface | Status | Disposition |
|---|---|---|
| `run_unified_post_grid_system_run` (convergence runner main entry) | DEAD — Phase 8 swap-in replaced this with `run_target_seeking_orchestrated_system_run` | Delete with the directory |
| Convergence GPT loop logic in `runner.py` (~3500 LOC) | DEAD — never called from the Phase 9 path | Delete with the directory |
| `runner.py:220` internal use of `_solved_lever_value_map` | DEAD (only used by dead runner) | Delete with the directory |

## Recommended migration sequence

1. **Extract `_persist_unified_convergence_state`** to a new
   `post_intake_persistence/` module. Update orchestrator.py:2483 import.
2. **Extract `_build_planning_context_summary_payload`** to either a new
   `post_intake_planning_context/` module or merge into
   `post_intake_state/`. Update intake_consult.py:84.
3. **Audit each public re-export consumer** (lines 87-98) — grep the
   codebase for `convergence_build_retry_scope_payload` etc. If no live
   callers, remove from `__all__` and the re-export block.
4. **Remove bind_runtime_dependencies hooks** from intake_consult.py
   (lines 66-67, 221-222) once the runtime helpers are extracted.
5. **Delete `python/client_intake_and_finmo/post_intake_convergence/`**
   directory once the imports above resolve to the new modules.
6. Re-run all 3 drafts to confirm no regression.

## Why this couldn't land in this session

The directive's Step 3 had a tight scope (delete + audit). Performing the
extraction safely requires:
- Reading the 4309-line `runner.py` to confirm `_persist_unified_convergence_state`
  doesn't depend on private helpers in the same file
- Reading the runtime.py file to confirm `_build_planning_context_summary_payload`
  doesn't depend on convergence-specific state
- Grepping every public re-export for live callers across the codebase

That's ~5 commits of careful migration. Steps 1-2 of Phase 9 corrective
landed substantive E2E improvements (cascade_exercised gate fix,
restoration executes, payroll wiring threaded). Step 3 cleanup is real
but doesn't move the gate verdict — it improves maintainability.

## Recommendation

Land Steps 1-2 now (already pushed). Treat Step 3 as a follow-up
cleanup commit chain after the gate verdict reaches passing for all 3
drafts. The directive's verdict requirement (16/16) is the binding
quality bar; the directory deletion is hygiene.
