# Current State

## Working Now
- Python-first planning flow is live.
- Intake can reach a backend planning-ready state and persist the necessary draft artifacts.
- Baby AI realism review is implemented and stored as `realism_memo_json`.
- Quarter-grid planning runs off the live Python model path.
- Direct model application runs after grid generation and produces recalculated outputs plus diagnostics.
- Replay/debug tooling exists for grid and direct-application runs.

## Recent Breakthroughs
- Baby AI is now separated from the main planner and has a narrow advisory contract.
- Legacy workbook-heavy / old forecast-planning path has been purged from the main system path.
- The old closeout governor path has been removed; the real planning path is now critic -> grid -> direct application.
- Financials flow has been tightened to align more directly with ops context.
- Live planning outputs are persisted in `planning_run_json` rather than hidden behind chat-only state.

## Important Nuance
- The live intake flow now ends at Financials and hands off to planning artifacts plus system-run.
- Treat planning persistence as infrastructure, not as a second controller layer.
- Do not rebuild the old closeout governor model.

## Actively Being Worked On
- Re-architecting post-intake persistence so SQL becomes durable operational truth for runs, checkpoints, and observability.
- Replacing multiple heavyweight top-level convergence loops with one unified GPT/solver convergence engine.
- Preserving realism, cash posture, stabilization, and guarantee concepts inside the unified engine without recreating rigid mini-stages.
- Preparing for reruns, stoppages, resumes, and future multi-user / login-driven workflows.
- Phase 6 slice landed: cash strategy and final stabilizer no longer own multi-attempt top-level convergence; they now run as single-attempt shaping passes while final guarantee remains the only top-level multi-attempt closer.
- Phase 7 slice landed: realism no longer owns repeated top-level convergence; the main realism loop is capped to one top-level iteration, and the main / cleanup / final-followup realism subpasses now each run with a single controller attempt.
- Phase 8 slice landed: realism cleanup and final-followup no longer run as extra GPT/solver subpasses; realism now ends with a deterministic post-scan ledger refresh and hands any remaining open issues forward to terminal guarantee.
- Phase 9 slice landed: deterministic issue packets are now built in Python for initial restructure and stabilizer/guarantee contexts too, and final guarantee now refreshes issue state from post-solve scans without throwing away prior ledger continuity.
- Phase 10 slice landed: Python retry-governance rejections now persist into the next planner context, so blocked retries carry explicit machine-owned reason codes and instructions instead of forcing GPT to infer why the prior candidate was rejected.
- Phase 11 slice landed: Python-owned quarter-target scaffolds are now supplied across cash strategy, initial restructure, and stabilizer/guarantee paths, and cash strategy now also receives deterministic issue packets instead of relying on looser issue summaries alone.
- Phase 11 validation slice landed: `scripts/validate_numeric_cutover.py` now validates terminal completion and zero-issue acceptance, understands direct planning payloads / row wrappers / live-monitor final-row payloads, and reports failed run artifacts cleanly instead of crashing on non-success output.
- Phase 12 slice landed: `scripts/run_live_e2e_monitor.py` can now persist a real final-result artifact for each monitored run and optionally execute cutover validation inline via `--validate-cutover`, using the same validator module that the standalone cutover script uses.
- Phase 13 slice landed: `planning_run_json` and persisted `numeric_solver_feedback_json` now carry a Python-owned `deterministic_convergence_summary` with terminal acceptance gates, latest guarantee quality/stall state, and controller issue counts; the cutover validator now requires those deterministic completion signals on terminal output.
- Phase 14 slice landed: `scripts/run_live_e2e_monitor.py` now watches the durable `planning_runs` ledger in addition to the draft-row mirror, and final monitor artifacts now include the final planning-run row, latest checkpoint summary, and recent stage events for the run.
- Phase 15 slice landed: the cutover validator now enforces durable-run consistency on live monitor artifacts, requiring the final `planning_runs` row, latest checkpoint, recent stage events, and draft-facing completion story to agree on the same terminal completed run.
- Phase 16 slice landed: live monitor artifacts now include a Python-owned `final_monitor_health_summary` that condenses heartbeat, checkpoint, recent-event, stage-progress, and clean-completion signals into one terminal health object, and the cutover validator now requires that health summary on monitor artifacts.
