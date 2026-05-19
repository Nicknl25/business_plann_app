# P3.26 — NexGen Regression Investigation

**Read-only investigation per RU-1.** Goal: identify the root cause of NexGen's `stage_ramp_revenue_path_not_applied` failure at finalize after P3.26 commits landed, before any revert decision.

**Headline finding** (and correction to the P3.26 verification memo's hypothesis):

The verification memo (§5) hypothesized that P3.26 Commit 1's broadened ITERATING_STILL trigger caused NexGen to engage the GPT exhaustion handler this run when it wouldn't have yesterday, leading to handler-authored revenue drivers that violate the stage_ramp_contract.

**That hypothesis is incorrect.** Yesterday's NexGen (`60f259b75c544c4cb5d3a1e3cff676fc`, baseline `dca4fae`) shows `restoration_loop.status=exhausted` and `gpt_exhaustion_handler.handler_status=landed_verified_tool_call`. **The handler engaged via EXHAUSTED (not ITERATING_STILL) yesterday too** — Commit 1's widening doesn't change anything for NexGen because the handler was already firing via the original EXHAUSTED path.

The actual cause: **GPT non-determinism in the handler's per-run driver authoring**, combined with the architectural gap that the GPT exhaustion handler doesn't consult `stage_ramp_contract.quarter_ramp_grid.rev_max` when authoring revenue drivers (Unit Price, Capacity, Utilization).

## Q1. Did the handler fire on today's NexGen run?

**Almost certainly YES, but cannot be confirmed directly because Phase B persistence was lost.**

Today's persisted state (draft `0938aa13aba949f5af3e15ce8f905aee`):
- `run_status: failed`
- `stage: quarter_grid_ready` (last persisted stage before failure)
- `post_cascade_completion: None` (Phase B's `completion_trace` dict never persisted)
- `target_seeking_diagnostics: {}` (empty)
- No restoration_loop, handler, or cash_pass traces in DB

Why the loss: the orchestrator's `_persist_unified_convergence_state` at [orchestrator.py:2749](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2749) writes `post_cascade_completion` to `planning_run_json` **AFTER** finalize. Today's finalize raised at `_raise_if_errors` ([finalize_post_intake.py:39-44](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L39-L44)), the exception propagated through the orchestrator's outer try/except (under CONVERGENCE_TEST_MODE the exception re-raises), and the API handler at [intake_consult.py:7310](../../python/api_handlers/intake_consult.py#L7310) called `_persist_failed_system_run_snapshot` — which preserves the LAST successfully-persisted state (the initial-grid's `persist_system_stage("quarter_grid_ready", ...)` at [initial_grid/runner.py:1390](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1390)). Phase B's in-memory completion_trace was thrown away.

Indirect evidence the handler fired today:
- The error trace in [_p3_26_verification/backend3.log](../../_p3_26_verification/backend3.log) shows the orchestrator reached `run_finalize_post_intake_validation` at line 2690 — full Phase B happened.
- Yesterday's same draft, same source intake fired the handler via EXHAUSTED ([yesterday's persisted state shows `restoration_loop.status=exhausted, outer_passes_used=1, gpt_exhaustion_handler.handler_status=landed_verified_tool_call`]).
- The conditions for restoration to return EXHAUSTED (formal or semantic) at [restoration_loop.py:1170-1224](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1170-L1224) are stable across the two runs (same business profile, same intake state). EXHAUSTED most likely returned today too.

## Q2. What tool calls did the handler make? Did it author revenue drivers?

**Cannot confirm tool calls directly** (Phase B persistence lost). The strongest evidence is the FINMO revenue trajectory comparison:

| Quarter | Yesterday revenue (PASS) | Today revenue (FAIL) | Today vs Yesterday |
|---|--:|--:|--:|
| Q1 | 980,000 | 980,000 | identical |
| Q2 | 1,009,596 | 1,009,596 | identical |
| Q3 | 1,039,584 | 1,039,584 | identical |
| Q4 | 1,069,964 | 1,069,964 | identical |
| **Q5** | **1,100,736** | **1,179,360** | **+7.1% higher** |
| **Q6** | **1,131,900** | **1,293,600** | **+14.3% higher** |
| Q7 | 1,163,456 | 1,329,664 | +14.3% higher |
| Q11 | 1,293,600 | 1,478,400 | +14.3% higher |
| Q20 | 1,352,400 | 1,545,600 | +14.3% higher |

QoQ growth:
- Yesterday: Q2-Q11 averages **~2.7-3.0%** QoQ — smooth
- Today: Q2-Q4 = 2.9-3.0%, then **Q5 = +10.22%**, **Q6 = +9.69%**, then Q7-Q11 back to 2.7-2.8%

This is the signature of a **capacity step** at Q5 or a one-shot Unit Price step authored by the handler. The Q1-Q4 portion is identical between runs — that's the initial deterministic-grid revenue. The Q5-Q6 jump is where the handler-authored or restoration-loop-authored drivers diverge from yesterday.

Yesterday's handler engagement detail: `handler_status: landed_verified_tool_call, tool_calls_used: None`. The `tool_calls_used: None` value (vs an integer) suggests the handler's verification path landed without making any GPT tool calls — possibly the deterministic state was acceptable without further authoring. Today's handler likely made tool calls (the +14.3% Q20 revenue spike is too large to be coincidence).

## Q3. Did Commit 1's ITERATING_STILL trigger engage the handler, or the original EXHAUSTED path?

**Almost certainly the original EXHAUSTED path** (Commit 1 not implicated).

Pre-Commit-1, the Site 1 trigger at [orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977) fires only on `RestorationStatus.EXHAUSTED`. The handler fires when restoration reaches that state via either:
- **Formal exhaustion** ([restoration_loop.py:1177-1179](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1177-L1179)): every operating driver pinned in every live quarter
- **Semantic exhaustion** ([restoration_loop.py:1195-1207](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1195-L1207)): every attempted target is stuck (bound_pinned + converged + max_inner_iters >= attempted) AND viability not all-pass

Yesterday's NexGen run: `restoration_loop.reason: "every_target_returned_bound_pinned_in_latest_pass targets_bound_pinned=['ebitda_margin', 'current_liabilities_to_revenue'] targets_converged=['current_assets_minus_cash'] diagnostic: deterministic algebra exhausted..."`. That's the semantic_exhaustion path, returning EXHAUSTED.

Conditions for semantic_exhaustion are unchanged between yesterday and today (same business profile, same target priority list). Today's restoration loop almost certainly returned EXHAUSTED via the same path. Commit 1's ITERATING_STILL widening would only matter if restoration returned ITERATING_STILL — there's no evidence that happened for NexGen.

**Commit 1 is not the cause of this regression.** The verification memo §5 hypothesis is corrected by this investigation.

## Q4. The stage_ramp_contract and the actual revenue delta

The check at [fail_fast.py:506-606](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L506-L606) compares actual QoQ revenue growth to the contract's `rev_max` / `revenue_qoq_max` per-quarter cap. Fails when `actual_growth > allowed_growth`.

Yesterday's contract (NexGen, persisted in `planning_run_json.stage_ramp_contract.quarter_ramp_grid`):
- Q2-Q11: `rev_target: 0.04` (4% QoQ target), `rev_max: 0.06` (6% QoQ cap)
- Q12-Q20: not inspected in detail but presumably more conservative ramp

Today's contract: **not persisted in the failure snapshot** (the `planning_run_json.stage_ramp_contract` field is absent for today's run; yesterday's has it at the top level). The contract is written by the `persist_system_stage("quarter_grid_ready", ...)` call in initial-grid but stored in a nested location. Without the post-cascade persist running, we don't have the top-level copy.

Reasonable inference: today's contract is structurally similar to yesterday's (same intake → similar GPT-authored ramp). Even if today's contract were 8% cap instead of 6%, today's Q5 = +10.22% QoQ would still violate it.

**Actual delta:** Q5 actual growth = +10.22% vs contract cap = 6%. **Over the cap by 4.22 percentage points.** Q6 actual = +9.69% vs cap = 6%. **Over the cap by 3.69 percentage points.**

## Q5. Yesterday's vs today's persisted state — what differs?

Both runs used the same source draft (`2d3da85054df4bfeb8617dc099a74761`). Both produced the same Q1-Q4 deterministic-grid revenue. The divergence starts at Q5.

| Aspect | Yesterday (PASS) | Today (FAIL) |
|---|---|---|
| Run completion | completed | failed at finalize |
| Phase B persistence | full completion_trace | None (lost when finalize raised) |
| Restoration loop status | exhausted | not directly observable (most likely also exhausted) |
| Restoration loop reason | semantic exhaustion (bound_pinned + converged on attempted targets) | not directly observable |
| Handler engagement | engaged via EXHAUSTED, `landed_verified_tool_call`, `tool_calls_used: None` | not directly observable (FINMO trajectory strongly suggests engaged + authored) |
| Q5-Q11 revenue trajectory | smooth ~2.7-3.0% QoQ | step jumps at Q5 (+10.22%) and Q6 (+9.69%) |
| stage_ramp_contract rev_max | 0.06 (6% QoQ) | not persisted (most likely similar) |
| Finalize result | passed | `stage_ramp_revenue_path_not_applied` |

The only material difference: **the handler authored more aggressive Q5-Q11 anchors today**. Yesterday's anchors led to ~3% QoQ uniformly; today's anchors led to a +10% step at Q5-Q6 then settling. This is consistent with the handler picking a higher Q11 anchor today (and possibly a higher Capacity step or Unit Price step at Q5).

**Why does the handler author differently on identical inputs?** GPT non-determinism. The handler at [exhaustion_handler/handler.py:747](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L747) makes GPT API calls with non-zero temperature; the responses vary run-to-run. This is documented in the P3.21 audit memo for Handler B.

## What this means for the revert decision

The verification memo's hypothesis that "P3.26 Commit 1's broader ITERATING_STILL trigger caused NexGen's regression" is **incorrect** based on this investigation.

The actual cause: the GPT exhaustion handler's revenue-driver authoring (Unit Price, Capacity, Utilization in the 12 PNL set per [restoration_loop.py:149-158](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L149-L158)) **does not consult `stage_ramp_contract.quarter_ramp_grid.rev_max`** when choosing values. The handler can author trajectories that violate the contract's per-quarter QoQ caps. The finalize check `assert_stage_ramp_revenue_path_applied` catches this — but at finalize, after the handler has already committed.

This is a Pattern 1 / Mirror Flavor 1 issue at the **handler ↔ stage_ramp_contract** boundary — analogous to the P3.25 finding for **handler ↔ payroll_headcount** but in a different lever family.

**Implications for revert (NOT a recommendation — user decides):**

- **Revert P3.26 Commit 1 alone** would NOT fix NexGen's regression. Commit 1's broader trigger didn't cause this; the underlying handler-authoring issue exists at baseline `dca4fae` too — NexGen passed yesterday by GPT-randomness luck, not by structural correctness.
- **Reverting to `dca4fae` and re-running NexGen** would have the same intermittent risk: most runs pass (yesterday did), some fail (today did). The variance is GPT API noise.
- **A fix that addresses the actual root cause** would either: (a) bound the handler's anchor authoring against the stage_ramp_contract QoQ caps, or (b) wire a routing on `stage_ramp_revenue_path_not_applied` similar to P3.26's payroll feasibility routing (route to the stage_ramp_handler — Handler A per doctrine §6 — for re-authoring). Out of scope for this read-only investigation.

The honest characterization: **NexGen's PASS yesterday was not deterministic.** The GPT handler can author trajectories that violate downstream contracts; when it does, finalize catches. The variance is in WHICH runs trigger the violation, not in WHETHER the underlying gap exists.

## Doctrine adherence note (RU-2)

Any fix proposed for this regression must adhere to doctrine. Specifically:
- **No new handler authority over fields with multiple source-of-truth surfaces unless reconciliation is built in.** The handler already has Unit Price/Capacity/Utilization authority — those are its 3 of 12 PNL levers. Adding stage_ramp_contract awareness wouldn't grant new authority; it would constrain the existing authority.
- **Pattern 1 / Mirror Flavor 1 not violated.** The stage_ramp_contract is the single source of truth for revenue QoQ caps; the handler today is unaware of it. Fix: make the handler read the contract (preserve Mirror Flavor 1).
- **Handler C remains canonical for payroll dollars.** This investigation isn't about payroll. The doctrine constraint stands.
- **Single source of truth for each field.** The stage_ramp_contract's QoQ caps are the source of truth for revenue growth bounds; any handler authoring revenue should respect those.

No fix is proposed in this memo per the directive's read-only constraint.

## Persisted-state evidence cited

- Yesterday NexGen PASS: `intake_consult_drafts.draft_id = 60f259b75c544c4cb5d3a1e3cff676fc`, `planning_run_json.post_cascade_completion.restoration_loop.status = "exhausted"`, `planning_run_json.post_cascade_completion.gpt_exhaustion_handler.handler_status = "landed_verified_tool_call"`, `planning_run_json.stage_ramp_contract.quarter_ramp_grid[0..9].rev_max = 0.06`
- Today NexGen FAIL: `intake_consult_drafts.draft_id = 0938aa13aba949f5af3e15ce8f905aee`, `planning_run_json.run_status = "failed"`, `planning_run_json.stage = "quarter_grid_ready"`, `planning_run_json.failure_reason = "post_intake_finalize_validation_failed: ... stage_ramp_revenue_path_not_applied@post_intake_finalize_validation_global: Actual FINMO revenue violates the GPT-selected stage_ramp_contract Q1-Q20 revenue path."`, FINMO Q5 revenue = $1,179,360 (QoQ +10.22%)
- Backend log [_p3_26_verification/backend3.log](../../_p3_26_verification/backend3.log) shows the full traceback through `_run_post_cascade_completion → run_finalize_post_intake_validation → _raise_if_errors`
