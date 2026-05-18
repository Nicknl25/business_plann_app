# Phase 9 P3.23a — Investigation of Sweep Failures 1, 2, and 3

**Status: READ-ONLY investigation. No code changes. No fix work proposed.**
The P3.23 sweep is paused. This memo classifies the three failures
captured before the stop and surfaces the doctrine-relevant architectural
question(s) each one raises. The user reviews and directs next steps.

## 0. Scope summary

| # | Business | Source / new draft | Outcome | Failing layer |
|---|---|---|---|---|
| 1 | Anderson & Blake Legal Associates | 25f74650… → a2585b3f… | acceptance_gate_failed (15/16) | Acceptance gate, post-run |
| 2 | CareFirst Home Health Services | 201d0ad1… → 7456b1ee… | FailFastError | `payroll_revenue_economic_feasibility_failed@quarter_grid_applied_global_payroll_revenue_feasibility` |
| 3 | Skyward Express Airlines | 41f014a5… → 5a89fd66… | FailFastError | `payroll_headcount_contract_timeout@payroll_headcount_contract_request` |

All three failed early in the sweep (positions 1, 2, 3). The full draft data is preserved in
[Test Runs Data](C:/Users/IgnatiusHenry/OneDrive%20-%20Tithe%20Financial%20Wealth%20Management/Apps/Test%20Runs%20Data),
[New Runner](C:/Users/IgnatiusHenry/OneDrive%20-%20Tithe%20Financial%20Wealth%20Management/Apps/New%20Runner),
and [Terminal Logs](C:/Users/IgnatiusHenry/OneDrive%20-%20Tithe%20Financial%20Wealth%20Management/Apps/Terminal%20Logs)
under each new-draft-id stamp; also captured in [_logs_5050_p3_23_sweep.txt](../../_logs_5050_p3_23_sweep.txt) and [_sweep_p3_23/per_draft_logs/](../../_sweep_p3_23/per_draft_logs/).

---

## DRAFT 1 — Anderson & Blake Legal Associates

Source draft `25f746500d1d456da638ee216669b78e` → new draft
`a2585b3f5402425abc6c5eea8e046c16`, planning run
`65d5e7c086ec4798847a7f96c4832214`. NAICS 541110 (legal services),
pre-revenue, planning_mode = `normalize` ("app_classified_overstated_or_overoptimistic_case").

### A. Did the relevant handler engage?

**Restoration loop: YES.** Engaged for 5 outer passes inside the inner
runner.

**GPT exhaustion (Restoration / Site 1) handler: NO.** `handler_fired:
False`, `handler_scope: None`, `handler_status: None`,
`tool_calls_used: None` in `run_diagnostics`. `plan_confidence:
high_no_adaptation`, `cascade_landed_tier: 0`.

Evidence:
- Persisted state, `Test Runs Data/05-18-2026 -- a2585b3f….txt` line 9 (acceptance verdict + run_diagnostics).
- `completion_trace.restoration_loop` block at line 128293 onward in the same file: `outer_passes_used: 5`, `final_viability_state.loss_window_funded_through_q5: false`, all others true.

### B. Engagement count vs. budget

- Restoration loop: **5 outer passes used** (max outer pass cap reached).
- GPT exhaustion handler: **0 tool calls** (handler never engaged).
- Cascade tiers attempted: **0** (cascade only fires on solver-target hard-fails or `inner_runner_abort_reason`; neither was set — `final_hard_fail_count: 0` in `_hard_fail_violations_from_assertion` terms).

### C. Did it touch the failing metrics?

**Yes — the restoration loop targeted ALL THREE failing metrics directly.**
Per `per_pass_diagnostics`:
- `ebitda_margin` (band_target 0.065952) — drivers at upper bound on `revenue::Unit Price` from outer-pass 1 onward; `status: bound_pinned`.
- `current_assets_minus_cash` (band_target 0.729235) — drivers at lower bound on `balance_sheet::Accounts Receivable Days` from pass 1; `status: bound_pinned`.
- `current_liabilities_to_revenue` (band_target 0.968137) — no drivers at bounds; `status: max_inner_iterations_reached` every pass.

### D. Per-round delta on the failing metrics

`current_liabilities_to_revenue` final_q11 progression across passes:
- Pass 1: 0.028 → 0.274 (Δ +0.246, 10 inner iters)
- Pass 2: 0.274 → 0.345 (Δ +0.071)
- Pass 3: 0.345 → 0.396 (Δ +0.051)
- Pass 4 & 5: each adds <0.05 (closing toward ~0.45)

Target 0.968. Progress was *real but slow* — getting smaller each pass.
After 5 passes the metric is still ~0.5 from the band floor. The loop
ran out of outer passes; not out of drivers.

`ebitda_margin` and `current_assets_minus_cash` were stuck (drivers fully
pinned) — final_q11 unchanged from pass 2 onward.

### E. `completion_trace` payload

From persisted state at line ~199050 (replicated downstream of the
acceptance verdict):

```json
{
  "restoration_loop": {
    "outer_passes_used": 5,
    "drivers_at_bounds_summary": {
      "balance_sheet::Accounts Receivable Days": "lower",
      "revenue::Unit Price": "upper"
    },
    "failing_metrics": [],
    "final_viability_state": {
      "ebitda_margin_q20_holds_or_improves_vs_q11": true,
      "ebitda_positive_by_q11": true,
      "ebitda_recovery_trend_q5_q11": true,
      "fixed_cost_burden_reduced_or_scaled_by_q11": true,
      "gross_margin_supports_ebitda_recovery": true,
      "loss_window_funded_through_q5": false
    },
    "per_pass_diagnostics": [ /* 5 passes, see Section D */ ]
  },
  "realism_remediation": {
    "attempted": false,
    "reason": "silod_cascade_replaced_by_target_driven_restoration_loop",
    "status": "retired_phase_9_p3"
  }
}
```

**Note:** `failing_metrics: []` is the field the restoration loop emits
as part of an `EXHAUSTED` return when the forecast classifier finds
GPT-authorable realism failures. Empty here means the loop's
`_classify_forecast_exhaustion` did not surface any failing metrics —
even though `loss_window_funded_through_q5` is false and three realism
band metrics will hard-fail in the acceptance gate downstream.

### F. Did the handler have authority over the failing metrics?

Yes — the restoration / GPT exhaustion handler's authority covers all
three failing metrics:

| Failing metric | Levers in handler authority |
|---|---|
| `current_liabilities_to_revenue` | `balance_sheet::Accounts Payable Days`, `balance_sheet::Deferred Revenue (% of Revenue)` |
| `current_assets_minus_cash` | `balance_sheet::Accounts Receivable Days`, `balance_sheet::Inventory Days`, `balance_sheet::Prepaid Expenses (% of Revenue)` |
| `ebitda_margin` | 12 P&L levers (Unit Price, COGS %, G&A %, Marketing %, Payroll %, Capacity, Utilization, etc. per [handler.py:105-125](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L105-L125)) |

**The handler had authority. It just was never invoked.**

### G. Doctrine classification

**REAL BUG IN TRIGGER CONDITION** — restoration loop exits with
`RestorationStatus.ITERATING_STILL` (the "max outer passes reached
without LANDED or EXHAUSTED" path at
[restoration_loop.py:1265](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1265)),
which **has no downstream consumer**. The Site 1 trigger at
[orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977)
checks for `EXHAUSTED` only:

```python
if restoration_result.status == RestorationStatus.EXHAUSTED:
    handler_result = run_gpt_exhaustion_handler(...)
```

So `ITERATING_STILL` falls through silently.

Two compounding sub-issues:

**Sub-issue 1: semantic_exhaustion test under-counts.**
At [restoration_loop.py:1189-1200](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1189-L1200):

```python
targets_attempted_count = len([
  t for t in (pass_diag.get("targets_attempted") or [])
  if t.get("status") in ("bound_pinned", "converged", "max_inner_iterations_reached")
])
targets_bound_pinned = list(pass_diag.get("targets_bound_pinned") or [])
targets_converged = list(pass_diag.get("targets_converged") or [])
semantic_exhaustion = (
  bool(targets_attempted_count)
  and len(targets_bound_pinned) + len(targets_converged) >= targets_attempted_count
  and len(targets_bound_pinned) >= 1
  and not all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS)
)
```

For Anderson & Blake pass 5: `targets_attempted_count = 3`
(`bound_pinned`, `bound_pinned`, `max_inner_iterations_reached`), but
`targets_bound_pinned + targets_converged = 2 + 0 = 2`. The check
`2 >= 3` is False, so `semantic_exhaustion` is False even though every
target is in fact stuck.

**Sub-issue 2: forward-looking forecast classifier under-detects.**
The LANDED-or-EXHAUSTED branch at
[restoration_loop.py:1109-1156](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1109-L1156)
is only entered when `all(final_viability...)` is True. Because
`loss_window_funded_through_q5` was False, the forecast classifier was
never called. So the realism-band failures (current_liabilities_to_revenue,
etc.) never had a chance to surface as `forecast_failures` and route to
the handler via the P3.7 forward-looking exhaustion path.

The acceptance gate's `_check_realism_no_hard_fail` reads the
**realism memo's results** ([acceptance/gate.py:228-273](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L228-L273))
— a different code path than the restoration loop. The realism memo
correctly recorded the hard-fail counts (1 + 9 + 5) but no adaptation
machinery consumed them.

This is closest to a **new variant of doctrine §3 Pattern 2**: handler
trigger filter is too narrow (`EXHAUSTED` only), and a real-but-not-classified-as-exhausted terminal state (`ITERATING_STILL` with
realism failures) silently slips through.

It can also be read as **Pattern 3 (diagnostic blames wrong layer)**:
the failure surfaces at the acceptance gate, blaming the realism
gate's contents, when the architectural cause is the restoration
loop's exit classification gap.

**Not a Class C (lever-authority gap):** the handler has authority.

---

## DRAFT 2 — CareFirst Home Health Services

Source draft `201d0ad18ae243dba933703d19cda4df` → new draft
`7456b1eec9d94d6ca89f89d9a2daf397`. Revenue $234k/quarter (flat across
all 20 quarters in the failure-state finmo); EBITDA −$89k → −$107k
trending more negative. Labor intensity class "high".

### A. Did the relevant handler engage?

**Payroll iterative refinement: YES.** Engaged inside
`_build_and_apply_payroll_schedule` (called from
`prepare_initial_grid_for_draft`). Converged successfully — the
persisted state shows a complete validator-accepted schedule:

- `capacity_labor_model: "labor_driven"`
- `labor_intensity_class: "high"`
- `wage_positioning_tier: "market"`, multiplier 1.25
- `target_payroll_percent_of_revenue: 0.6`
- `capacity_units_per_supporting_fte: 520.0`

The schedule passed Layer A.1 / A.2 / A.3 + Layer B validators
(`_assert_payroll_contract_economic_feasible_for_retry`). The iteration
loop exited cleanly via the success path at
[schedule.py:2601](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2601) (`return schedule_payload`).

**The fail-fast fired AFTER the grid was applied**, at the post-quarter-grid
global invariants check.

### B. Engagement count vs. budget

- Rounds used by iterative refinement: not surfaced into persisted state (the loop exited successfully — no `rounds_used` field is emitted on success). The schedule_payload was produced; no exhaustion fail-fast.
- Budget: 10-round hard cap; 180s soft cap. Iteration succeeded within both.

### C. What did it author?

The iterative refinement authored only its scoped fields per [P3.21 Part 1 audit](p3_21_part1_audit_payroll_iterative_refinement.md):
- OEWS occupational titles from the NAICS title catalog.
- Per-quarter `starting_fte` / `hires` / `ending_fte`.
- `capacity_labor_model`, `labor_intensity_class`, `wage_positioning_tier`,
  `wage_positioning_multiplier`, `target_payroll_percent_of_revenue`,
  `capacity_units_per_supporting_fte`.
- Benefits percent.

It did **NOT** author revenue drivers (Unit Price, Capacity,
Utilization, stage ramp) — these are outside its contract.

### D. Per-round delta

Not applicable. The iterative refinement converged. The fail-fast that
killed the run fired in a different validator, against a different
state, after grid application.

### E. `completion_trace` payload

Persisted state shows `controller_resolution_state.status:
terminal_failure`, `display_status: "terminal failure"`,
`overall_completion_grade: "D"`. No `completion_trace.payroll_iterative_refinement`
block — the iteration succeeded and is not separately logged.

The terminal failure message preserves the full call chain:

```
POST_INTAKE:post_intake_schedule_marker_missing@quarter_grid_applied:
Payroll schedule fail-fast failed; payroll must use the table-backed
headcount schedule:
POST_INTAKE:payroll_revenue_economic_feasibility_failed@quarter_grid_applied_global_payroll_revenue_feasibility:
Payroll/revenue economics are outside the table-backed headcount
policy range; recompute drivers instead of clipping outputs.
```

Stack: [_logs_5050_p3_23_sweep.txt:2879-2936](../../_logs_5050_p3_23_sweep.txt#L2879-L2936)
walks `prepare_initial_grid_for_draft` → `_assert_global_invariants_via_sequence`
([initial_grid/runner.py:1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1469))
→ `assert_post_intake_global_invariants` → `assert_payroll_revenue_feasibility`
([headcount/schedule.py:3421](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3421)).

### F. Did the handler have authority over the failing mode?

**NO.** The fail-fast message itself names the gap:

> "recompute drivers instead of clipping outputs."

Drivers in question = revenue drivers (Unit Price, Capacity,
Utilization, stage ramp). The payroll iterative refinement's authority is
*headcount + wage positioning + capacity_units_per_supporting_fte* — NOT
revenue drivers. The refinement can lower headcount (raising
per-FTE supported capacity) but cannot lower the underlying revenue
target or raise the unit price to push payroll/revenue back into band.

Even with full lever authority *within its scope*, the refinement
converged to the best schedule its authority allowed, and the
post-grid state was still outside the policy bounds.

### G. Doctrine classification

**Class C — lever-authority gap, COMPOUNDED by Pattern 1 (Mirror Flavor
1) divergence.**

**Authority gap:** the only adaptation in the call path between intake and
the post-grid global invariants check is the payroll iterative refinement.
Its authority is structurally insufficient to fix
`payroll_revenue_economic_feasibility_failed@quarter_grid_applied_global_payroll_revenue_feasibility`
when the cause is revenue too low for any feasible labor cost (rather
than payroll schedule too high). The intentional design at
[initial_grid/runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468)
explicitly chose to NOT retry payroll on this failure — the comment
says "post-quarter-grid feasibility violations now hard-fail directly
— surfacing the deeper issue rather than papering over with another
rebuild." That choice is correct ONLY if a layer further upstream (or
downstream) has the lever authority to fix it. There currently is none
in this code path before convergence.

**Mirror Flavor 1 divergence:** the iterative refinement's Layer B
validator (`_assert_payroll_contract_economic_feasible_for_retry` at
[schedule.py:2596-2600](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2596-L2600))
evaluates against a `projected_finmo_json` built from the
*payroll-only* model_input ([schedule.py:1932](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1932)).
The global check at `assert_payroll_revenue_feasibility`
([schedule.py:3407](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3407))
runs against the fully-applied post-grid finmo. The two finmos can
differ: the projection doesn't include stage ramp effects on revenue, capacity expansion,
or the full driver application chain. So the refinement's validator
sees a different revenue profile than the global check — and can
declare convergence while the global check finds violations.

This is doctrine §3 Pattern 1 (Mirror Flavor 1): validator state must
equal downstream state. The two states here are not the same
construction.

The underlying *business question* — is CareFirst's intake feasible at
$234k/quarter revenue with high labor intensity? — is a separate
question. If the answer is "no", that's a Class B (plan-viability gap)
that intake should catch; if "yes with adjustment", the system needs an
authority site that can adjust revenue drivers given a payroll/revenue
infeasibility signal. Today there is none in the initial-grid path.

---

## DRAFT 3 — Skyward Express Airlines

Source draft `41f014a5567041d99b2572a67fe6b03d` → new draft
`5a89fd66f19348589284dbd604c84214`, planning run `cae6b4c501234c6aa705e2f679d91443`.
Revenue $22.113M/quarter (large business), EBITDA +$3.017M/quarter,
quarterly grid never populated past Q1 fallback (revenue and EBITDA flat
across all quarters because the run never produced an applied grid).

### A. Did the relevant handler engage?

**Payroll iterative refinement: YES** — but **did not converge**.
The fail-fast `payroll_headcount_contract_timeout` fired at
[schedule.py:2424](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2424)
during the pre-call budget guard at the start of round 4.

### B. Engagement count vs. budget

- `round_n: 4` (this is the start-of-round number; round 4 was rejected before its GPT call).
- `hard_cap_rounds: 10`.
- `elapsed_seconds: 175.65` of `timeout_seconds: 180.0`.
- The pre-call guard rejects when `remaining_seconds < 15.0` ([schedule.py:2423](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2423)). Remaining = 4.35s; rejected.
- **3 rounds completed** within the 175.65s of elapsed time. Round 4 was rejected before issuing the GPT call.

### C. What did it author?

The same scoped contract as Draft 2's iterative refinement (OEWS titles,
per-quarter FTE schedule, capacity_labor_model, etc.). It authored 3
rounds but none was validator-accepted by the time the budget ran out.

### D. Per-round delta on the failing metrics

Persisted state does not surface per-round validator-feedback deltas on
the timeout path (the loop's `last_failure_packet` is only persisted on
the EXHAUSTED-by-rounds path at
[schedule.py:2627](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2627)).
The timeout path raises directly without writing the last packet
trajectory.

The persisted state shows `terminal_failure` everywhere; the run
never produced an applied grid. Cannot tell whether the 3 attempted
rounds were getting closer or oscillating.

### E. `completion_trace` payload

```json
{
  "details": {
    "round_n": 4,
    "hard_cap_rounds": 10,
    "elapsed_seconds": 175.65,
    "timeout_seconds": 180.0,
    "source_table": "post_intake_process_sequence_lookup",
    "step_key": "payroll_gpt_contract_request"
  }
}
```

`controller_resolution_state.status: terminal_failure`.
`Grid Application Success: False`. `Applied Lever Updates: None`.

### F. Did the handler have authority?

Authority is not the issue here. The handler was *trying* to author
within its scope. The handler ran out of *wall-clock budget*, not
authority.

### G. Doctrine classification

**REAL BUG — BUDGET / GPT-LATENCY MISMATCH.** Not a doctrine §3
pattern; not Class C. The handler's contract assumes ~18s/round
(180s budget ÷ 10-round cap = 18s/round). Observed per-round wall clock
on this run: ~58.5s/round (175.65s ÷ 3 completed rounds).

The 10-round hard cap is unreachable at the observed GPT-response
latency on a large/complex business profile (airlines have many OEWS
title candidates; GPT responses for the full per-quarter schedule are
correspondingly long and slow). The 180s soft cap caps you to ~3
rounds at this latency.

### H. Time-budget analysis

| Metric | Value |
|---|---|
| Total elapsed before timeout | 175.65 s |
| Rounds completed | 3 (round 4 rejected before GPT call) |
| Average per-round wall clock | 58.55 s |
| Budget-implied per-round expectation | 18.0 s (180s ÷ 10) |
| Ratio actual : expected | 3.25 × |

**Was each round genuinely slow?** Almost certainly yes. The bulk of
per-round wall clock is the OpenAI `/v1/responses` call; for a
$22M-quarter airline with many feasible OEWS titles, the response
length (per-quarter FTE schedule across many titles) drives latency
into the tens of seconds per call.

**Did it converge logically before the budget?** Cannot tell from
persisted state. The timeout path does NOT preserve the
`last_failure_packet` (only the exhaustion-by-rounds path at
[schedule.py:2627-2640](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2627-L2640) does).
This is itself a **Property 4 diagnostic-preservation observation**:
the rounds-exhausted path emits the residual packet; the
budget-exhausted path does not. Same handler, two terminal paths, two
levels of diagnostic richness.

**Comparison with yesterday's known-passing payroll runs (Sunny Glaze
Donuts and ExpressLogix Shipping Services):** the persisted state and
test-runs files for [05-17-2026 -- 866cc1ae….txt](C:/Users/IgnatiusHenry/OneDrive%20-%20Tithe%20Financial%20Wealth%20Management/Apps/Test%20Runs/05-17-2026%20--%20866cc1ae2ff54fac8a3844d8f8096e95.txt)
(Sunny Glaze Donuts) and [05-17-2026 -- 6cfa1dffe….txt](C:/Users/IgnatiusHenry/OneDrive%20-%20Tithe%20Financial%20Wealth%20Management/Apps/Test%20Runs/05-17-2026%20--%206cfa1dffe74d4d3f8afa6b93c6f71cd1.txt)
(ExpressLogix) do not surface per-round timing data — the success path
discards the `rounds_used` / `elapsed_seconds` after returning the
schedule. Direct round-time comparison is therefore **unavailable
without instrumentation changes**. Indirect signal: both runs completed
end-to-end within their system-run duration, so the payroll cycle
finished comfortably under 180s on a donut shop and a shipping
services SMB; the airline-scale business is the visible discriminator
on this sample of three.

---

## Cross-cutting findings

### Three different doctrine classes, three failures

| Draft | Class | Root |
|---|---|---|
| 1 (Anderson & Blake) | Trigger-condition bug (Pattern 2 variant + Pattern 3) | `ITERATING_STILL` has no consumer; `semantic_exhaustion` under-counts when targets hit `max_inner_iterations_reached` |
| 2 (CareFirst) | Class C lever-authority gap + Pattern 1 (Mirror Flavor 1) | No adaptation site between intake and post-grid global invariants can author revenue drivers; iterative refinement's validator state ≠ global validator state |
| 3 (Skyward) | Budget / latency mismatch (not a §3 pattern) | 180s/10 rounds assumes ~18s/round; observed 58.5s/round on a large airline business; secondary Property 4 observation on timeout-path diagnostic preservation |

### Notes for downstream P3.23 work

- **None of the three failures is the same root cause.** A single fix won't address all three.
- **Pattern 1 is in play in Drafts 1 and 2 in different ways.** Draft 1: realism memo state isn't reflected back to restoration loop's failing_metrics. Draft 2: payroll-only projected finmo ≠ fully-applied post-grid finmo.
- **Property 4 (diagnostic preservation) Draft 3 sub-finding:** worth recording even though it isn't the immediate cause of failure — `payroll_iterative_refinement_exhausted` preserves the trajectory packet; `payroll_headcount_contract_timeout` does not. Cross-path inconsistency.
- **No regression detected:** all three failures are consistent with current HEAD behavior. The fail-fasts are working as designed for what they cover; the gaps are in coverage / trigger / authority, not in HEAD-introduced bugs.
- **Hard-stop condition #2 (regression that would have caught the multi-biz runs) is NOT triggered.** Draft 1's realism failure is acceptance-gate caught post-hoc, not a deeper-layer fail-fast. Drafts 2 and 3 fail at the payroll layer for business-profile reasons that ExpressLogix Shipping Services (yesterday's E2E target) didn't surface.

## Open architectural questions for the user

1. **Draft 1:** Should `ITERATING_STILL` route to the GPT exhaustion handler the same way `EXHAUSTED` does? (Logically the same situation — driver work hit the outer limit without landing; handler has authority to author further on the failing metrics.) OR should `semantic_exhaustion` be widened to include `max_inner_iterations_reached` targets (so the EXHAUSTED branch fires instead)?
2. **Draft 2:** Is the design choice at [initial_grid/runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468) — "hard-fail post-grid feasibility instead of retrying payroll" — still the right call when the message itself says the fix needs *driver* recomputation that no current adaptation site owns? Or does this signal a need for an upstream intake-level viability gate that rejects revenue-too-low intakes for the required labor profile before they reach the planning run?
3. **Draft 3:** Two independent levers:
   - **Budget tuning:** raise the 180s cap to (say) 360s, *or* lower the 10-round hard cap to (say) 4 and accept that the iteration runs against a *time* budget primarily?
   - **Latency reduction:** shrink the GPT response surface (smaller per-round prompt/response) — but this changes the contract, which is its own decision.
   - **Property 4 observation:** add the `last_failure_packet` to the timeout fail-fast details, so the handler that didn't converge still emits its trajectory.

None of these answers can land without a doctrine decision. This memo
captures the data; the directions are the user's to choose.
