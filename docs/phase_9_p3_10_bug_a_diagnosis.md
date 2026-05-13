# Bug A — Debt Principal Not Declining Without New Borrowing — Diagnosis

**Status:** Diagnostic only. NO code changes. Awaiting user authorization for fix.
**Surfaced by:** All three E2E runs (NexGen, Sunny, Express) when the orchestrator's `failed_downgraded_to_warning` wrapper was removed in Commit 2.
**Hard-fail diagnostic (NexGen example):**
```
POST_INTAKE:post_intake_schedule_marker_missing@post_intake_finalize_validation_global:
Debt schedule fail-fast failed; all debt must use the table-backed amortizing debt schedule:
debt_schedule_payload_invalid: [{quarter_index: 1..20,
  reason: 'principal_balance_not_declining_without_new_borrowing',
  opening: 300000, closing: 300000} × 20]
```

---

## 1. Where the validator fires

`validate_debt_schedule_payload` at [post_intake_debt_schedule/schedule.py:638](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L638-L639):

```python
if opening > 0 and issuance <= 0 and closing >= opening:
  violations.append({"quarter_index": quarter, "reason": "principal_balance_not_declining_without_new_borrowing", ...})
```

This is a self-check on the `debt_schedule` payload alone (no cross-payload comparison). If the payload's rows have `opening_debt=300000, actual_debt_issuance=0, closing_debt=300000` for every quarter, the validator raises.

The validator is correctly designed: a real debt instrument must amortize OR record explicit new borrowing to keep the balance steady. The combination caught is structurally impossible.

---

## 2. What the persisted state shows

Inspected the cloned NexGen draft `e15928eaf72b40e2b5c47316b155a62e` from the post-Commit-5 E2E:

| Surface | Value |
|---|---|
| `model_input.sections.schedules` row `schedules::Debt Repayment (Scheduled)` | `controller_write=True`, `values=[0.0, 0.0, …, 0.0]` (Q0-Q20 all zero) |
| `finmo.quarter_rows[*].debt_repayment` | 0.0 for every quarter |
| `finmo.quarter_rows[*].long_term_debt` | 300000.0 for every quarter |
| `finmo.quarter_rows[*].short_term_debt` | 0.0 for every quarter |
| `debt_schedule.rows[*].total_principal_payment` | 0 for every quarter |
| `debt_schedule.rows[*].closing_debt` | 300000 for every quarter |
| `debt_schedule.source_stage` | `"target_seeking_orchestrator_completed"` |

So the persisted state — model_input, finmo, debt_schedule — all agree: zero debt repayment, principal flat at $300K. The validator correctly catches the divergence.

---

## 3. Synthetic harness — `apply_minimum_debt_schedule` works correctly in isolation

Invoked `apply_minimum_debt_schedule` directly on NexGen's persisted model_input + finmo + financials inside an active sequence-controller scope:

```
result.applied_update_count: 40
result.minimum_debt_schedule_policy.status: ready
POST-APPLY Debt Repayment values_q0_q5: [0.0, 15000.0, 15000.0, 15000.0, 15000.0, 15000.0]
POST-APPLY finmo q=1 debt_opening=300000.0 debt_repayment=15000.0 debt_closing=285000.0
POST-APPLY finmo q=2 debt_opening=285000.0 debt_repayment=15000.0 debt_closing=270000.0
```

**Conclusion:** The function works exactly as designed. `build_debt_schedule_plan` produces 40 exact_updates (20 quarters × 2 levers: DEBT_REPAYMENT and INTEREST_RATE). `execute_numeric_plan` applies them. `apply_exact_lever_updates_to_model_input` correctly stamps the values. FINMO recomputes with proper amortization (Q1 opening=$300K → repayment=$15K → closing=$285K, etc.).

**The `or` fallback at [debt_schedule/schedule.py:547](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L547) does NOT fire** in this case — `execute_numeric_plan` returns a populated `updated_model_input_json` with the debt repayment values stamped.

So the bug is NOT in `apply_minimum_debt_schedule` or its descendants. The bug is upstream: the debt schedule that gets validated was built BEFORE the cash pass ran.

---

## 4. Root cause — architectural ordering bug at orchestrator.py:1251

[python/client_intake_and_finmo/post_intake_solver/orchestrator.py:1247-1287](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1247-L1287):

```python
# Build + persist debt_schedule SNAPSHOT — happens before
# _run_post_cascade_completion runs the cash pass + finalize.
debt_schedule_payload = build_debt_schedule_snapshot(
  finmo_payload=copy.deepcopy(final_finmo_json or {}),
  model_input_json=copy.deepcopy(final_model_input_json or {}),
  source_stage="target_seeking_orchestrator_completed",
)
...
# Persist the debt_schedule directly to the draft row
cur.execute(
  "UPDATE intake_consult_drafts SET debt_schedule=%s WHERE draft_id=%s",
  (_json.dumps(debt_schedule_payload, ensure_ascii=False, default=str),
   str(draft_id or "").strip()),
)
conn.commit()
```

This builds and persists the debt_schedule using `final_model_input_json` and `final_finmo_json` AS THEY EXIST at line 1251 — BEFORE `_run_post_cascade_completion` runs (which includes the cash pass that's responsible for stamping `DEBT_REPAYMENT_LEVER_ID` values).

Then in `_run_post_cascade_completion`:
- Target-seeking solver runs (mutates model_input)
- Path stamp pass runs
- Composite revenue check
- Restoration loop
- (Optional) GPT exhaustion handler
- **Cash pass at orchestrator.py:1791** — calls `_apply_cash_pass_minimum_debt_schedule` as Step 1 of `run_mode_based_cash_strategy` ([orchestrator_invocation.py:199](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L199)). This DOES update DEBT_REPAYMENT in memory.
- FINMO is rebuilt at orchestrator.py:1809-1813.
- Realism gate
- **Finalize at orchestrator.py:1965** — receives `debt_schedule=copy.deepcopy(debt_schedule_payload or {})` — the STALE PRE-CASH-PASS snapshot.
- Persist at orchestrator.py:2063 — but only if finalize succeeds.

So when finalize calls `assert_post_intake_global_invariants` → `assert_debt_schedule_payload_ready` → `validate_debt_schedule_payload`, it validates the stale payload built at line 1251 (with `total_principal_payment=0` because at that point in the pipeline, model_input had `DEBT_REPAYMENT_LEVER` values all 0). The validator correctly raises.

The cash pass IS running, but its in-memory DEBT_REPAYMENT updates never reach the validated debt_schedule. They also never reach SQL persistence on a failed run because the final persist happens after finalize.

### 4.1 Layer-by-layer responsibility

| Layer | What it does | Why it doesn't see the cash-pass debt_repayment |
|---|---|---|
| `build_debt_schedule_snapshot` (orchestrator.py:1251) | Builds snapshot from current finmo + model_input | Called too early — before `_run_post_cascade_completion` |
| `apply_minimum_debt_schedule` (cash pass step 1) | Updates DEBT_REPAYMENT_LEVER | Updates in-memory `final_model_input_json` correctly |
| FINMO rebuild (orchestrator.py:1809) | Rebuilds finmo from updated model_input | Sees positive debt_repayment in-memory |
| `run_finalize_post_intake_validation` (orchestrator.py:1965) | Validates global invariants | Receives STALE `debt_schedule_payload` from line 1251 |
| `_persist_unified_convergence_state` (line 2063) | Persists post-cascade state | Never fires when finalize raises |
| `_persist_failed_system_run_snapshot` (intake_consult.py error path) | Persists failure snapshot | Reads model_input/finmo from SQL — these are pre-cash-pass state |

This explains every observation: persisted state shows zero debt_repayment because it's the LAST PERSISTED state from BEFORE the cash pass; the validator raises because the stale `debt_schedule_payload` it receives reflects that same pre-cash-pass state.

### 4.2 Why the `or` fallback at line 547 is NOT the root cause

The `or` fallback at [debt_schedule/schedule.py:547](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L547):

```python
result["updated_model_input_json"] = execution_result.get("updated_model_input_json") or model_input_json
```

This silently uses the original `model_input_json` if `execute_numeric_plan` returns a falsy `updated_model_input_json`. The synthetic harness confirms `execute_numeric_plan` returns a properly-populated dict. So this fallback does NOT fire in this scenario.

The fallback is still a code smell — it's the kind of silent-degradation pattern P3.10 is trying to eliminate — but it's not the operative cause of Bug A. (Worth converting to a hard-fail in a follow-up commit, but separately scoped.)

### 4.3 Why `max_solver_attempts_per_pass: 1` is not the cause

[debt_schedule/schedule.py:538](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L538) sets `solver_settings={"max_solver_attempts_per_pass": 1}`. This caps the numeric solver retry budget — but `execute_numeric_plan` doesn't fail in this scenario (the solver isn't even strictly invoked; the deterministic exact_updates are applied via `execute_core_model_updates` regardless). The synthetic harness with this exact setting succeeds.

---

## 5. Bug B linkage — same root cause, but residual delta possible

Bug B (Q1 short_term_debt formula off by 5-8%) shares the architectural cause:

1. The cash pass's Step 2 — `_apply_cash_pass_short_term_debt_current_portion` ([orchestrator_invocation.py:214](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L214)) — computes `short_term_debt_percent_of_long_term_debt` as the ratio of next-four-quarters' `DEBT_REPAYMENT_LEVER_ID` values divided by `long_term_debt`.
2. If the cash pass Step 1 updates DEBT_REPAYMENT to $15K/quarter, Step 2 computes ratio = (15000 × 4) / 300000 = **0.20** for NexGen.
3. STD = LTD × 0.20 = $300K × 0.20 = **$60,000**.
4. The validator's "expected" of **$63,000** for NexGen suggests the intake-stated `short_term_debt_percent_of_long_term_debt` is **0.21** (not 0.20).

So even after Bug A is fixed, NexGen Q1 STD will be ~$60,000 vs expected $63,000 — close but not exactly matching. The validator might tolerate the difference (depends on its threshold) or might still raise.

**Likely outcomes after Bug A fix:**

- **NexGen** STD: actual ≈ $60K vs expected $63K (5% delta). May pass with tolerance, may fail with smaller delta diagnostic.
- **Express** STD: actual ≈ ratio × $500K. With $500K LTD and 20-quarter amortization, repayment ≈ $25K/quarter, ratio ≈ 0.20, STD ≈ $100K vs expected $170K (intake stated 34%). Likely STILL fails with smaller delta.

So **Bug B is partially downstream of Bug A**. Bug A's fix will reduce Bug B's deltas significantly but may not fully resolve them. Bug B may need a separate fix to reconcile the cash-pass-derived STD% ratio with the intake-stated STD% (or to derive STD% from intake instead of from the cash-pass ratio).

If Bug B still surfaces after Bug A's fix, that becomes the next iteration of the loop.

---

## 6. Proposed fix shape

**Single change in `_run_post_cascade_completion`** (or in the orchestrator block that wraps `_run_post_cascade_completion` followed by finalize):

After the cash pass updates `final_model_input_json` and `final_finmo_json`, REBUILD `debt_schedule_payload` from the fresh state and use it for both finalize validation AND persistence.

```python
# After cash pass + FINMO rebuild, BEFORE finalize:
from client_intake_and_finmo.post_intake_debt_schedule import build_debt_schedule_snapshot
debt_schedule_payload = build_debt_schedule_snapshot(
  finmo_payload=copy.deepcopy(final_finmo_json or {}),
  model_input_json=copy.deepcopy(final_model_input_json or {}),
  source_stage="post_intake_finalize_validation",
)
debt_schedule_payload["persisted_column"] = "intake_consult_drafts.debt_schedule"
next_result["debt_schedule"] = debt_schedule_payload
# Re-persist the fresh snapshot to SQL so workbook export + acceptance gate
# read the post-cash-pass version.
if conn is not None:
  cur = conn.cursor()
  try:
    cur.execute(
      "UPDATE intake_consult_drafts SET debt_schedule=%s WHERE draft_id=%s",
      (json.dumps(debt_schedule_payload, ensure_ascii=False, default=str),
       str(draft_id or "").strip()),
    )
    conn.commit()
  finally:
    cur.close()
```

This rebuild happens immediately before `run_finalize_post_intake_validation` is invoked, with the post-cash-pass `final_finmo_json` and `final_model_input_json`. The validator then sees the proper amortizing schedule.

**Universal-app:** the fix changes orchestration ordering only. No NAICS branches. Applies identically to every business.

### 6.1 Scope choices

| Option | Description | Pros | Cons |
|---|---|---|---|
| **A (recommended)** | Rebuild debt_schedule after cash pass, before finalize. Keep the early build at line 1251 for the case where post-cascade-completion isn't reached. | Minimal change. Fresh schedule reflects all post-cascade mutations. Persists post-cash-pass version for workbook + acceptance gate. | Two build sites — could drift over time. |
| **B** | Move the line 1251 build entirely to after cash pass. Delete the early build. | Single source of truth. | If post-cascade-completion is skipped (some edge case), no debt_schedule gets persisted. Need to verify no caller depends on the early build. |
| **C** | Add a "rebuild on demand" helper, call it both at line 1251 (with current state) AND after cash pass (with updated state). | Symmetric. | Adds an indirection layer for marginal benefit over option A. |

**Recommend Option A** — surgical, preserves the existing early build as a safety net, and the rebuild after cash pass is the operative one.

### 6.2 Risk assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Other consumers read `debt_schedule_payload` between line 1258 and the cash pass and rely on its specific values | Low — `debt_schedule_payload` is set on `next_result["debt_schedule"]` and not consumed elsewhere in the post-cascade body until finalize. | Verified by grep: only finalize reads `debt_schedule` from `next_result`. |
| The cash pass might not update `DEBT_REPAYMENT_LEVER` for some businesses (e.g., when cash strategy returns failure and reverts) | Possible — `apply_minimum_debt_schedule` returns early at line 517 if model_input or finmo is empty. | The fresh rebuild correctly reflects whatever model_input ended up at. If cash pass didn't run, the rebuild matches the pre-cash-pass version (same as today). |
| The persistence UPDATE at line 1268-1287 fires twice on a successful run | True with Option A. | Acceptable — both UPDATEs target the same column; the second OVERWRITES with the post-cash-pass version, which is the correct final state. |
| The early build at line 1251 may now be vestigial (never the persisted version on a successful run) | True for Option A. | Acceptable. Could be removed in a follow-up cleanup commit. |

### 6.3 Universal-app verification

Sunny: Sunny has no debt → `opening_debt_seed=0` → `build_debt_schedule_plan` returns `status=skipped_no_debt`. No DEBT_REPAYMENT updates. The validator's `principal_balance_not_declining_without_new_borrowing` doesn't fire (only fires when `opening > 0`). So the fix is a no-op for Sunny — the rebuild produces an empty/zero debt_schedule, validator passes. Sunny's CURRENT failure is `stage_ramp_expense_path_not_applied` (Bug F), not Bug A.

NexGen ($300K LTD): cash pass produces $15K/quarter repayment. Rebuilt schedule shows proper amortization. Validator passes Bug A. (Bug B may still surface with smaller delta.)

Express ($500K LTD): same pattern. $25K/quarter repayment. Validator passes Bug A. (Bug B may still surface.)

---

## 7. Tests planned

**Unit smoke test** (`tests/test_bug_a_fix_rebuild_debt_schedule_post_cash_pass.py`) — new file:

1. Synthetic model_input + finmo + financials with $300K LTD, zero DEBT_REPAYMENT.
2. Build initial debt_schedule via `build_debt_schedule_snapshot` — confirm `total_principal_payment=0` and `closing_debt=300000` per quarter (matches today's bug state).
3. Apply `apply_minimum_debt_schedule` to update DEBT_REPAYMENT → confirm model_input + finmo show $15K/quarter.
4. REBUILD debt_schedule via `build_debt_schedule_snapshot` against the post-cash-pass state.
5. Validate the rebuilt schedule via `validate_debt_schedule_payload` → confirm zero violations.
6. Specifically assert `principal_balance_not_declining_without_new_borrowing` does NOT appear in the violation list.

**E2E confirmation** (after fix lands): re-run NexGen + Express on fresh 5051. Expected:

- Bug A's `principal_balance_not_declining_without_new_borrowing` GONE.
- Bug B may surface as smaller delta (`Short Term Debt (% of LTD) actual=$60K vs expected=$63K` for NexGen; document as next iteration if so).
- Sunny unchanged (already past Bug A; still hits Bug F).
- If NexGen and Express land 16/16 (Bug B was within tolerance), great. If not, Bug B becomes the next iteration.

---

## 8. Awaiting user authorization

The proposed fix is a single change in `orchestrator.py` (or possibly split into the orchestrator helper if the user prefers). The push name would be `phase_9_p3_10_fix_bug_a_rebuild_debt_schedule_post_cash_pass`.

Specifically:
- Rebuild `debt_schedule_payload` after the cash pass + FINMO rebuild, before finalize.
- Re-persist the rebuilt `debt_schedule_payload` to SQL.
- Pass the rebuilt payload to `run_finalize_post_intake_validation`.
- Add unit smoke test confirming validator passes on the rebuilt payload.
- E2E re-run on all three businesses; report outcomes.

Awaiting your direction. Specifically:
1. Approve Option A as scoped.
2. Or pick Option B (delete early build entirely).
3. Or pick Option C (helper function).
4. Or any other architectural shape.
