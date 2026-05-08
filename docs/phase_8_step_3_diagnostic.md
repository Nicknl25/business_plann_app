# Phase 8 Step 3 — Convergence Runner Exit Path Diagnostic

**Question:** With the acceptance gate in place, why does Sunny exit at
`current_stage = "convergence_running"` with `run_status = "running"`,
cascade tier 3 landed, but no realism gate / no solver_target_assertion
/ flat revenue / negative cash / negative current assets?

**Answer:** The cascade lands, but the cash pass and finalize stages
are never run on the cascade's final state. They live inside the
convergence runner's normal-path tail and are bypassed when the inner
runner returns `abort_for_cascade`. The outer target-seeking
orchestrator's post-cascade path doesn't replicate them.

## Flow

1. `_run_planning_system_for_draft_unified`
   ([api_handlers/intake_consult.py:6842](../python/api_handlers/intake_consult.py#L6842))
2. → `prepare_initial_grid_for_draft` — sets stage `post_intake_initialize_validation_completed`
3. → `_run_unified_post_grid_system_run`
   ([api_handlers/intake_consult.py:6765](../python/api_handlers/intake_consult.py#L6765))
4. → `run_target_seeking_orchestrated_system_run`
   ([post_intake_solver/orchestrator.py](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py))
5. Orchestrator invokes `_inner_runner` (the convergence runner) at orchestrator.py:765-779
6. Convergence runner persists `stage="convergence_running"` at multiple
   checkpoints (runner.py:1251, 1275, 1358, 1532, 1557, 1906, 2425)
7. Convergence loop hits a stall condition and returns
   `_abort_for_cascade_result(abort_reason=…)`
   from one of: runner.py:1306, 1798, 1844, 1854, 2453
8. Orchestrator detects `status == "abort_for_cascade"` at orchestrator.py:789-797
9. Orchestrator fires `run_adaptation_cascade` at orchestrator.py:929
10. Cascade lands tier 3 → returns `final_payload`, `plan_confidence`, `cascade_diagnostics`
11. Orchestrator builds `debt_schedule` snapshot (orchestrator.py:984)
    and writes it directly to `intake_consult_drafts.debt_schedule`
    (orchestrator.py:1006)
12. Orchestrator returns `next_result` at orchestrator.py:1025
13. `_run_unified_post_grid_system_run` calls `persist_adaptation_cascade_outcome`
    at intake_consult.py:6830, which UPDATEs `planning_runs` with
    `cascade_landed_tier=3` and `plan_confidence="low_target_tolerance_widened"`
14. Returns to API handler → workbook export → "System run complete" response

## What is missing between steps 11 and 13

The convergence runner's normal-path tail (when convergence completes
without abort) does this work after the cycle loop, at runner.py:2489-3347:

| runner.py lines | Stage | What runs |
|---|---|---|
| 2489-2493 | post_convergence_pre_cash | OpenAI deadline reset; global invariants assertion |
| 2502-3000-ish | cash_pass | `_apply_cash_pass_minimum_debt_schedule` + short-term debt seed + cash strategy proposer + cash strategy review + second-pass cash strategy + final balance-sheet settling |
| 3325-3341 | finalize | `run_finalize_post_intake_validation` — runs the realism gate, runs `solver_target_assertion`, validates revenue formula reconciliation / payroll schedule reconciliation / debt schedule reconciliation / cash phase trace |
| 3344-3370 | finalize_validation_completed | `_persist_unified_convergence_state(stage="post_intake_finalize_validation_completed", status="completed")` |
| 3450-3483 | run_complete | `persist_post_intake_execution_state(checkpoint_kind="run_complete", status="completed")` |

When the inner convergence runner returns `abort_for_cascade`, control
exits the inner-runner before line 2489. None of the cash pass / finalize
/ status-completion writes happen. The cascade's `final_payload` carries
the model_input + finmo, but on Sunny:

- **Revenue $60K × 10**: the pre-shaping baseline solver state. The inner
  solver bailed before driving revenue to targets; the cascade's tier 3
  (`target_tolerance_widened`) widens tolerance bands but doesn't itself
  drive a new solver pass — that was supposed to be the inner runner's
  job, which it abandoned via `abort_for_cascade`.
- **Cash -$10K → -$174K, interest $0**: cash strategy never ran; debt
  was never raised against negative cash. The orchestrator's
  `build_debt_schedule_snapshot` at orchestrator.py:984 reads from the
  finmo state but doesn't itself raise debt — it snapshots the existing
  debt_interest series, which is empty because cash strategy never ran.
- **Current assets negative starting Q3**: balance sheet never settled.
- **No realism gate provenance, `solver_target_assertion.checked=false`**:
  both live in finalize (runner.py:3325 → finalize_post_intake.py); never
  ran.

## The legacy "lie" mechanism, named precisely

The abort condition at runner.py:2445-2449 reads:

    if (
      consecutive_no_progress_cycles >= non_productive_cycle_limit
      and not bool(quality_assessment.get("meaningful_progress"))
      and not bool(controller_resolution_state.get("all_cleared"))
    ):
      return _abort_for_cascade_result(abort_reason="no_meaningful_progress", ...)

`controller_resolution_state.all_cleared` is a value the legacy
post_intake_issues machinery is supposed to set. When the legacy
machinery is degraded (which the user has documented for weeks), this
field defaults to `None`. `not bool(None) == True`, so the abort fires
even on cycles where the convergence engine was actually making progress
toward feasibility — the abort is consulting a phantom verdict from
state the legacy machinery never wrote.

After the cascade lands, the run is **persisted as cascade-landed but
not finalized**, and the legacy `latest_remaining_issue_count` field on
`planning_runs` keeps whatever default value (0) was set at run start.
Test scripts read that field and report `remaining_issue_count=0`, which
combined with `exit_code=0` reads as "passed" without any single line of
new-architecture verdict ever being consulted.

## Step 4 implication

The exit path is fixed by either:

A. **Orchestrator drives the post-cascade tail.** After the cascade
   lands at orchestrator.py:929, invoke cash_pass + finalize on the
   cascade's final state. This means lifting cash_pass and finalize out
   of the convergence runner's normal-path tail and either putting them
   in the orchestrator or extracting them to a shared post-cascade
   completion module that both the convergence runner's normal-path tail
   and the orchestrator's post-cascade path call.

B. **Convergence runner becomes the only authority for completion.**
   The cascade returns to the convergence runner (rather than the
   orchestrator) and the convergence runner runs its cash_pass + finalize
   on the cascade's final state. The orchestrator becomes a thin wrapper
   for cascade selection.

Option A is cleaner because it concentrates completion logic in one
place. The convergence runner's cash_pass + finalize tail (runner.py:2489-3347)
extracts cleanly because it doesn't depend on the convergence loop's
local state — it operates on `final_model_input_json` and `final_finmo_json`,
both available from the orchestrator's `final_payload`.

The post_intake_issues legacy machinery deletion in Step 4 also removes
the `controller_resolution_state.all_cleared` abort path. After
deletion, the abort condition is rewritten to consult the realism gate
directly: "abort if realism gate has hard_fail violations AND
consecutive_no_progress_cycles exceeds limit." The cascade still fires
on hard-fail violations as a real signal rather than on a phantom
None-default.

## Acceptance gate verdict reference

For comparison, this is what the gate output for Sunny's most recent
"pass" (planning_run_id `b3eca6165b3d4593987b73d723523551`):

- **Failed:** stage_reached_finalize, realism_gate_provenance_recorded,
  solver_target_assertion_checked, revenue_not_flat_q1_q10,
  cash_legitimate_q1_q10, current_assets_positive_q1_q10
- **Passed:** cascade_landed_tier_set (3), plan_confidence_recorded
  (`low_target_tolerance_widened`), realism_gate_no_hard_fail_violations
  (vacuously — no results to violate), solver_target_assertion_no_hard_violations
  (vacuously — assertion never ran)

Each failure maps to one specific missing stage in the post-cascade tail.
