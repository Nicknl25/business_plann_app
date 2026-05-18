# Phase 9 P3.23c — `unified_convergence_decision` status verification

**READ-ONLY. NO FIXES. NO DELETIONS.**

Before the user decides delete vs. re-enable vs. finish-replacement, this
memo answers three questions about the bypassed `unified_convergence_decision`
step (P3.23b §0.6 divergence #2), with code citations.

## Q1. The bypass marker

### Verbatim transcript — [orchestrator.py:1332-1347](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1332-L1347)

```python
  # ---------- Inner runner — Phase 8 bypass ----------
  # The legacy convergence runner is broken post-deletion of the issue
  # machinery: every fail-fast the legacy GPT loop's authority-
  # reapplication used to suppress now fires (revenue formula
  # validators, payroll schedule rollups, etc.). The orchestrator-
  # driven post-cascade tail (cash pass + realism gate + finalize +
  # persist) is the new authoritative path. Skip the legacy inner
  # runner and use a passthrough so the cascade has a starting state
  # to work from. The acceptance gate's verdict is the authority on
  # whether the resulting plan is sensible.
  inner_result = {
    "status": "phase_8_inner_runner_bypassed",
    "model_input_json": copy.deepcopy(pre_shaped_model_input or {}),
    "finmo_json": copy.deepcopy(pre_shaped_finmo or applied_finmo_json or {}),
    "abort_reason": "phase_8_legacy_convergence_runner_skipped",
  }
```

### Marker classification

The marker is NOT labeled "temporary", "deprecated", "TODO", or "FIXME".
It reads as a deliberate architectural decision:
- `Phase 8 bypass` (the label) — names the architectural phase that made the change.
- *"The orchestrator-driven post-cascade tail … is the new authoritative path"* — states a finished replacement, not a placeholder.
- *"The acceptance gate's verdict is the authority on whether the resulting plan is sensible"* — points to the new authority.

The marker also carries an explicit warning about why the legacy code
is no longer functional:
> *"The legacy convergence runner is broken post-deletion of the issue machinery: every fail-fast the legacy GPT loop's authority-reapplication used to suppress now fires (revenue formula validators, payroll schedule rollups, etc.)"*

### Git blame

The bypass was committed on **2026-05-08** by `b7f859c`:

```
b7f859c 2026-05-08 Phase 8 step 4 (11/N): bypass legacy convergence runner from orchestrator
```

The original `inner_result` call (26 lines) directly invoked
`run_unified_post_grid_system_run` from `post_intake_convergence/runner.py`.
That direct call was inserted earlier on **2026-05-06** by `1cacf96`:

```
1cacf96 2026-05-06 Phase 2.5: target-seeking outer loop is the authoritative convergence path
```

So the call existed for two days before being replaced by the
passthrough. The Phase 2.5 commit positioned the target-seeking
orchestrator AS the authoritative path while keeping the legacy
runner as an inner tool; the Phase 8 step 4 commit cut the legacy
runner out entirely.

**Two-day window between "target-seeking is authoritative, legacy is
an inner tool" and "legacy is bypassed entirely" tells us the legacy
runner's continued use was already understood to be incidental by
Phase 2.5 and became actively broken by Phase 8.**

---

## Q2. What `run_unified_convergence_cycle` actually does

### Locating the implementation

`run_unified_convergence_cycle` is the **handler key string** (not a
Python function) — it appears in two places:

- As `expected_handler_key="run_unified_convergence_cycle"` in the
  sequence-controller wrapper at
  [convergence/runner.py:1657](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1657).
- As a registered `handler_key` value in
  [post_intake_mapping.py:1128](../../python/client_intake_and_finmo/post_intake_mapping.py#L1128)
  and [:1777](../../python/client_intake_and_finmo/post_intake_mapping.py#L1777).

The actual Python implementation that handler key dispatches to is
the **outer convergence cycle loop** in
[`_run_unified_post_grid_system_run` at convergence/runner.py:615](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L615).
The cycle's GPT planner call is
[`_run_unified_convergence_openai` at runtime.py:2776](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L2776).

### Inputs / outputs / loop shape

- **Max cycles:** `_UNIFIED_CONVERGENCE_MAX_CYCLES` read from SQL
  `post_intake_process_sequence_lookup.max_attempts` for step
  `unified_convergence_decision` ([runner.py:112-114](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L112-L114)).
- **Per-cycle wall-clock:** `_UNIFIED_CONVERGENCE_CYCLE_TIMEOUT_SECONDS`
  ([runner.py:115-117](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L115-L117)).
- **Loop condition:** `controller_resolution_state.all_cleared` AND hard rules clear → break ([runner.py:1326-1330](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1326-L1330)). Otherwise next cycle.
- **Exhaustion:** `if unified_convergence_cycle_count > _UNIFIED_CONVERGENCE_MAX_CYCLES: raise RuntimeError("unified_convergence_unresolved_after_max_cycles")` ([runner.py:1331-1333](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1331-L1333)).
- **Total-phase budget guard:** total_phase_budget_seconds from SQL; on exceed, returns `abort_for_cascade` ([runner.py:1337-1354](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1337-L1354)).
- **GPT planner step:** `_run_unified_convergence_openai` at the per-cycle GPT call site [runner.py:1630-1665](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1630-L1665). Reads `prompts/unified_convergence/reviewer.md`; allowed_lever_ids drawn from `writable_lever_catalog`; outputs a `decision` dict.
- **Plan translation step:** `translate_unified_convergence_decision_to_updates` at [runner.py:1709-1750](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1709-L1750).
- **Apply step:** `apply_unified_convergence_updates` and `verify_unified_convergence_progress` (SQL table convergence:94 + 95).

### What failure modes it addresses

Per the convergence runner body:

1. **Realism-band hard-fails** (via the realism_issue_ledger that
   feeds `_payroll_repair_failure_from_issue_ledger` at
   [runner.py:1368](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1368)
   and the GPT planner's full context).
2. **Payroll feasibility failures** via the
   [`_rebuild_payroll_authority`](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L780-L826)
   branch at [runner.py:1375-1389](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1375-L1389):
   ```python
   if payroll_repair_failure and payroll_repair_signature not in attempted_payroll_repairs:
     _rebuild_payroll_authority(copy.deepcopy(payroll_repair_failure))
   ```
   This invokes `estimate_payroll_headcount_schedule_with_gpt` with
   `previous_contract_failure=payroll_repair_failure` and the
   `payroll_feasibility_repair` step_key — **exactly the table's
   initial_grid:65 step that P3.23b §0 flagged as missing in the
   current path.**
3. **Hard-rule violations** (`hard_rule_assessment` informs the
   loop-exit condition at [runner.py:1326-1330](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1326-L1330)).
4. **Per-cycle exhaustion**, deferred to the `abort_for_cascade` path
   (the orchestrator-driven cascade gets to try afterward).

### What levers it adjusts

The GPT planner's allowed lever set is the full
`writable_lever_catalog` for the current cycle ([runtime.py:2849-2856](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L2849-L2856)).
This is **a broader set than the GPT exhaustion handler's 17 levers**
because the writable_lever_catalog draws from the full numeric solver
contract, which includes:
- All P&L drivers (12 from doctrine §6 handler authority list).
- All WC drivers (5 from doctrine §6).
- Revenue drivers (Unit Price, Capacity, Utilization) — outside the
  current 17-lever handler authority.
- Other levers per the cycle's `retry_scope_payload.lever_catalog_entries`
  filtering ([runtime.py:2872-2878](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L2872-L2878)).

### Cross-reference with P3.23b §4 timing-mismatch matrix

If unified_convergence_decision were re-enabled and functional:

| P3.23b pair | Would convergence cover? | Why |
|---|---|---|
| **F/I/O — Anderson & Blake** (ITERATING_STILL → realism hard-fail) | **YES.** | GPT planner could re-author on the per-cycle realism_issue_ledger; multi-cycle iteration would press on the failing metrics until `all_cleared` or `max_attempts`. |
| **B — CareFirst** (payroll_revenue_feasibility @ post-grid global) | **PARTIAL — the `_rebuild_payroll_authority` branch addresses it post-grid IF the run reaches convergence.** The CareFirst run failed at initial-grid global ([initial_grid/runner.py:1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1469)) — *before* the convergence phase. The convergence runner's repair branch is downstream of the failure point. So convergence does not by itself fix CareFirst; CareFirst needs the **`payroll_feasibility_repair` step wired into initial-grid as a try-except** (which doctrine table specifies and code removed). |
| **C — stage_ramp_expense initial-grid** | NO — fires before convergence runs. |
| **D — cascade post-flight solver_target hard_fails** | YES — but the cascade already covers this; convergence would be redundant here. |
| **E — restoration loop forward-looking exhaustion realism hard-fails** | YES — same coverage as F. |
| **G — pre-cash gate violations** | YES — covered by existing Site 2 already, convergence redundant. |
| **H — cash post-validation (buffer/distribution/surplus/contract/hard_rule)** | YES — but funding handler already covers, convergence redundant. |
| **J — solver target assertion at post-finalize** | YES — informational anyway. |
| **K — finalize global_invariants** | PARTIAL — only the realism / margin-class failures. Pure mechanical reconciliation isn't authorable. |
| **L — finalize cash buffer integrity** | YES via the multi-cycle iteration + cash strategy in the convergence path. |
| **M/N — finalize reconciliation / BS reconciliation** | NO — schema integrity, no handler. |
| **O/P/Q/R — acceptance gate items** | YES — these are downstream of convergence's natural failure-mode scope. |

**Net:** convergence would cover Anderson & Blake (F/I/O, P, Q, R) and
*partially* address CareFirst (only if the failure happens during
convergence, not at initial-grid). It would NOT cover stage_ramp_expense
initial-grid failures, schema reconciliation failures, or anything that
hard-fails before the convergence phase.

---

## Q3. Path comparison

### Path A — extend restoration + cascade to cover ITERATING_STILL

Three patches, all read-only-named in P3.23b §5 (gaps F-1, F-2, F-3):

| Sub-fix | File:line | Estimated LOC | Risk |
|---|---|---|---|
| F-1: widen Site 1 trigger to `status in {EXHAUSTED, ITERATING_STILL}` OR convert ITERATING_STILL to EXHAUSTED at bottom of loop | [orchestrator.py:1977](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977) + [restoration_loop.py:1265](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1265) | 3-10 | Low — handler is non-destructive |
| F-2: include `max_inner_iterations_reached` in `semantic_exhaustion` counting | [restoration_loop.py:1189-1200](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1189-L1200) | 2-5 | Low |
| F-3: ungate `_classify_forecast_exhaustion` from `all(viability)` | [restoration_loop.py:1109-1156](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1109-L1156) | 5-15 | Medium — changes scope determination |
| **Subtotal (Anderson & Blake only)** | | **10-30 LOC** | **Low–medium** |

To also address CareFirst with Path A:

| Sub-fix | File:line | Estimated LOC | Risk |
|---|---|---|---|
| Re-wire the `payroll_feasibility_repair` step into [initial_grid/runner.py:1469](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1469) as a try-except, invoking `estimate_payroll_headcount_schedule_with_gpt` with `previous_contract_failure` — mirroring [convergence/runner.py:780-826](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L780-L826) and [:1375-1389](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1375-L1389) | initial_grid/runner.py:1469 | 30-60 | Medium — reintroduces a retry the P3.11 work removed; the comment at [runner.py:1460-1468](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1460-L1468) explicitly chose hard-fail over rebuild. Architectural decision needed. |
| **Subtotal (Anderson & Blake + CareFirst)** | | **40-90 LOC** | **Medium** |

### Path B — re-enable `unified_convergence_decision`

Mechanical steps:

| Step | LOC delta | Notes |
|---|---|---|
| Remove the 6-line bypass at [orchestrator.py:1342-1347](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1342-L1347) | -6 | |
| Restore the original `_inner_runner = run_unified_post_grid_system_run` call (26 lines per the git diff of b7f859c) | +26 | |
| Update the bypass comment to remove the "broken" warning | -5 | |
| Subtotal mechanical | **+15 LOC** | |

**But the bypass marker explicitly warns**: *"every fail-fast the legacy GPT loop's authority-reapplication used to suppress now fires (revenue formula validators, payroll schedule rollups, etc.)"*. Re-enabling the call alone is not enough — the validators that fail during the legacy GPT loop's authority re-application were hardened by Phase 9 work (P3.10, P3.17, P3.19, P3.20) and they now hard-fail under CONVERGENCE_TEST_MODE rather than getting suppressed.

To make convergence functional again, every fail-fast that fires
inside the convergence runner's authority-reapplication path needs
handling. From the warning's enumeration:
- **Revenue formula validators** — `_assert_revenue_formula_reconciles` and related; these were added/hardened in P3.10–P3.19. Each fail-fast in the convergence path needs either:
  - A handler-on-failure to repair, OR
  - A demonstration that the GPT planner's output would have respected the validator (likely requires prompt updates), OR
  - A suppression flag for the convergence-internal authority-reapplication phase
- **Payroll schedule rollups** — payroll reconciliation checks; similar treatment.
- **Other fail-fasts** the comment alludes to without enumerating — to find the complete list, one would need to dry-run convergence and surface each fail-fast that fires.

Estimated additional work to handle the broken fail-fasts:

| Fail-fast category | LOC to handle | Notes |
|---|---|---|
| Revenue formula validators (P3.19 work) | 40-80 | Add validator-aware retry inside convergence loop OR suppression flag |
| Payroll schedule rollups (P3.20 work) | 30-60 | Probably already handled by `_rebuild_payroll_authority` branch but needs verification |
| Other latent fail-fasts the bypass warns about (count unknown without dry-run) | 30-150+ | One-off discovery + handling per fail-fast |
| Subtotal | **100-290 LOC** | High uncertainty |

| **Path B total** | **115-305 LOC** | **High risk** |

### Honest assessment

**Path A is materially cleaner.** Reasons:

1. **Architectural alignment.** Phase 2.5 (commit 1cacf96) and Phase 8
   step 4 (commit b7f859c) made target-seeking the authoritative path
   and bypassed the legacy convergence runner. Re-enabling is
   essentially "undo Phase 8," contradicting two months of
   architectural direction. Path A extends the new path.

2. **No "broken code" to repair.** The bypass marker says the legacy
   runner is broken under current validator hardening. Path B requires
   surfacing and fixing each broken fail-fast, with high
   discovery-uncertainty (the warning enumerates only two categories
   and ends with "etc."). Path A touches code that is currently
   functional.

3. **Smaller blast radius.** Path A is 40-90 LOC across 3 files; Path
   B is 115-305 LOC across many files, plus uncertain follow-up to
   address fail-fasts surfaced by initial re-enabling.

4. **The two paths overlap heavily.** The convergence runner's
   `_rebuild_payroll_authority` at [runner.py:780-826](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L780-L826) is exactly the
   `payroll_feasibility_repair` step Path A would re-wire into the
   initial-grid runner. The GPT planner in the convergence runner is
   conceptually similar to the GPT exhaustion handler the restoration
   loop already escalates to (just with broader lever authority).
   Path A reuses these existing pieces; Path B brings them back as a
   parallel-but-not-quite-identical layer.

5. **Doctrine drift.** The SQL table still lists
   `unified_convergence_decision` and its 6 subprocesses as
   `enabled=1` (P3.23b §0.1). Path B aligns code with the
   still-active table rows. Path A would require the table to be
   updated (de-list the convergence rows + add the rows for the new
   path's steps) — a cleaner doctrine reconciliation than restoring
   the bypassed code.

**Where Path B has an edge:** the convergence runner's GPT planner
authority is BROADER (the full `writable_lever_catalog` including
revenue drivers) than the GPT exhaustion handler's 17-lever authority.
If the actual failure-mode space requires revenue-driver authority
that the current handler can't reach, Path A patches alone do not
add it. The cleanest way to address that on the new path is to
either:
- Expand the GPT exhaustion handler's authority (architectural
  decision — doctrine §6 partition), OR
- Add revenue-driver authoring as a new step in the new path's
  sequence (e.g., a "revenue driver re-authoring" handler engaged on
  the same triggers as the exhaustion handler).

Path B implicitly gives you the broader authority but with the cost
of carrying the legacy GPT planner + the cycle iteration machinery +
all its now-broken fail-fast interactions.

### Recommendation

**Path A — extend restoration + cascade.** Re-enabling convergence
brings back a layer the architecture explicitly retired, with
non-trivial repair cost and substantial overlap to what the new path
already does. The 17-lever authority constraint is a real gap, but
the right way to close it is a targeted handler-authority expansion
on the new path, not by reintroducing the old architecture.

**Suggested commit shape (NOT implemented in this memo):**

1. Land Gap F-1 + F-2 + F-3 together as `phase_9_p3_24_restoration_iterating_still_routes_to_handler` (5–25 LOC, addresses Anderson & Blake). Verify on the 28-draft sweep.
2. Make the architectural decision on payroll_feasibility_repair (Section 0.6 divergence #1). If re-wire approved: land as `phase_9_p3_25_payroll_feasibility_repair_post_grid_retry` (30–60 LOC, addresses CareFirst).
3. Make the architectural decision on revenue-driver authority. If the next sweep surfaces failures the 17-lever handler can't reach, that decision becomes concrete; if not, defer.
4. **Separately**, delete the now-dead convergence code path and de-list its rows from the SQL table — `phase_9_p3_2x_retire_legacy_convergence_runner`. Cleans up the bypassed code and aligns the table with the live architecture.

The "finish-replacement" option in the user's framing is steps 1–4 above.
The "re-enable" option (Path B) is materially more work for the same
end-state coverage. The "delete" option is step 4 above, presumably
combined with whichever fixes from steps 1–3 are needed first.
