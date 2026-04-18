# Next Steps

## Immediate Priorities

### 1. Durable SQL Foundation
- Add `planning_runs`, `planning_run_checkpoints`, and `planning_stage_events`.
- Centralize post-intake persistence.
- Goal: trusted run state, resume truth, rerun history, and real-time observability.

### 2. Unified Convergence Engine Shift
- Remove heavyweight top-level convergence ownership from realism, cash strategy, and stabilizer.
- Replace them with one unified GPT/solver loop.
- Goal: one true convergence owner instead of overlapping partial solvers.
- Current progress:
  - cash strategy top-level retries reduced to a single shaping attempt
  - final stabilizer top-level retries reduced to a single shaping attempt
  - realism top-level loop reduced to one iteration, with main / cleanup / final-followup each limited to a single controller attempt
  - realism cleanup/followup solving removed; realism now finishes with deterministic post-scan refresh and hands remaining issues forward
  - deterministic issue packets now feed realism, initial restructure, and stabilizer/guarantee contexts from Python rather than leaving that framing to GPT
  - final guarantee post-solve scan now preserves prior ledger continuity instead of rebuilding issue state from scratch
  - retry-discipline rejections now feed back into the next planner context with explicit Python-owned reason codes and guidance
  - deterministic quarter-target scaffolds now constrain cash strategy, initial restructure, and stabilizer/guarantee target structure before GPT fills values
  - final guarantee still owns terminal multi-attempt convergence
  - the cutover validator now checks terminal completion / all-cleared state and accepts real artifact shapes from direct payloads, persisted rows, and live-monitor final-row output
  - the live E2E monitor can now persist a final result artifact and run the same cutover validator inline with `--validate-cutover`
  - deterministic convergence summaries and terminal acceptance gates now persist into planning and numeric feedback payloads, and terminal validation requires them
  - the live E2E monitor now captures durable planning-run truth, latest checkpoint summary, and recent stage events in addition to the draft mirror
  - terminal validation now also requires the durable planning run row, latest checkpoint, and recent stage events to agree with the draft-facing completion state
  - the live E2E monitor now also persists a compact `final_monitor_health_summary` so a single object shows whether the run heartbeated, checkpointed, emitted `run_completed`, and finished cleanly
  - terminal validation now also requires that monitor health summary on monitor artifacts
  - the next step is using the richer monitor+validator path in live runs and tightening any remaining runtime gaps the live artifacts expose

### 3. Deterministic Python Governance
- Move issue packet construction, severity, scope, tolerances, progress detection, and retry discipline into Python.
- Goal: GPT focuses on strategy, not mechanical interpretation.

### 4. Adaptive Broad-To-Narrow Behavior
- Make the unified loop broader early and narrower later, without rigid internal mini-stage bureaucracy.
- Goal: structured convergence without recreating the old fragmented architecture.

## Execution Order
1. Durable SQL foundation
2. Unified convergence engine shift
3. Deterministic Python governance
4. Adaptive broad-to-narrow behavior
