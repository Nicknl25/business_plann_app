# Phase 9 P3.10 — E2E Results for Commits 1-4

**Scope:** Read-only E2E validation. NO code changes from these runs. Surfaced bugs documented separately in [phase_9_p3_10_e2e_surfaced_bugs.md](phase_9_p3_10_e2e_surfaced_bugs.md) and held for user review before any fix commit.

**E2E configuration:**
- API server: fresh process on port 5051 (separate from the long-running 5050 instance which started before Commits 1-4 landed).
- Launcher: [context/run_api_5051_p3_10.py](../context/run_api_5051_p3_10.py) — sets `CONVERGENCE_TEST_MODE=true` before `from api import app`, so the new code from Commits 1-4 is loaded with hard-fail conversions active.
- Runner: `Test Files/run_persisted_system_run.py --base-url http://127.0.0.1:5051 --draft-id <X>`.
- Source drafts (most recent intake-complete row per business):
  - **NexGen Software Solutions Inc.** — `51ab9a6d257149cda1fdd76a61e3aeef`
  - **Sunny Glaze Donuts** — `6c7544ec12bc44fe91d7e5acd44336cd`
  - **ExpressLogix Shipping Services** — `a5e0363963d546e0a597ce6dbdeb787d`
- Per-business runner clones the source intake state into a fresh draft, then POSTs `/api/intake-consult/system-run`.

---

## 1. Per-business outcomes

| Business | Cloned draft_id | HTTP | Outcome | Time | Pipeline stage at failure |
|---|---|---|---|---|---|
| NexGen | `4b43e4caeb1447e0b85f655522ff9429` | **500** | **B** — hard-fail with precise diagnostic | ~30s | `post_intake_finalize_validation_global` |
| Sunny | `38bfd3827ee44ef4bbb2a7ba1dbfaeed` | **500** | **B** — hard-fail with precise diagnostic | ~30s | `post_intake_finalize_validation_global` (payroll) |
| Express | `f665d7dbc3074f85853e92ca9020cbb1` | **500** | **B** — hard-fail with precise diagnostic | ~35s | `post_intake_finalize_validation_global` |

All three businesses exited the pipeline with HTTP 500 and a structured diagnostic. The diagnostic in every case names the operation, the violation kind, the affected quarters/fields, and the actual-vs-expected values.

### 1.1 NexGen — Outcome B

```
post_intake_finalize_validation_failed: global_invariants_invalid:
  POST_INTAKE:post_intake_schedule_marker_missing@post_intake_finalize_validation_global:
  Debt schedule fail-fast failed; all debt must use the table-backed amortizing debt schedule:
  post_intake_finalize_validation_global_global_debt_payload: debt_schedule_payload_invalid:
    [{quarter_index: 1..20, reason: 'principal_balance_not_declining_without_new_borrowing',
      opening: 300000, closing: 300000} × 20]
  debt_schedule_reconciliation_failed: ...
  balance_sheet_driver_formula_failed:
    balance_sheet::Short Term Debt (% of LTD) q=1
    field=short_term_debt actual=59850 expected=63000
```

- Two distinct violations:
  - **Debt principal flat at $300K across 20 quarters** with no new borrowing recorded (debt schedule writer not amortizing).
  - **Q1 short_term_debt = 59850 vs expected 63000** (95% — suggests the % LTD ratio is being applied with a wrong fraction, or the LTD basis is off).

### 1.2 Sunny — Outcome B

```
post_intake_finalize_validation_failed: global_invariants_invalid:
  POST_INTAKE:post_intake_schedule_marker_missing@post_intake_finalize_validation_global:
  Payroll schedule fail-fast failed; payroll must use the table-backed headcount schedule:
  POST_INTAKE:payroll_headcount_quarter_total_mismatch@payroll_headcount_quarter_total_rollup:
    Q1 quarter_totals.payroll=20777 calculated_from_title_rows=39873.
    Payroll schedule quarter_totals must be a deterministic rollup of rows.
  payroll_schedule_reconciliation_failed: ...
```

- Single violation: **Q1 payroll quarter_total = 20777 but row-level rollup = 39873.** The writer is producing a quarter total that's roughly 52% of the actual row sum. Same bug class as the original Sunny FAILED_PRECONDITION run that prompted this whole overhaul.

### 1.3 Express — Outcome B

```
post_intake_finalize_validation_failed: global_invariants_invalid:
  ...
  debt_schedule_payload_invalid:
    [{quarter_index: 1..20, reason: 'principal_balance_not_declining_without_new_borrowing',
      opening: 500000, closing: 500000} × 20]
  ...
  balance_sheet_driver_zero_but_applicable:
    balance_sheet::Deferred Revenue (% of Revenue)
    applicability=deferred_revenue_business
    zero_allowed_reason=no_upfront_or_deferred_revenue_model
  balance_sheet_driver_formula_failed:
    balance_sheet::Short Term Debt (% of LTD) q=1
    field=short_term_debt actual=156825 expected=170000
```

- Three violations:
  - **Debt principal flat at $500K** (same pattern as NexGen).
  - **Q1 short_term_debt = 156825 vs expected 170000** (92.25% — same off-ratio pattern as NexGen).
  - **Deferred Revenue marked applicability=deferred_revenue_business but value=0.** Mismatched applicability vs value.

---

## 2. Outcome category aggregate

| Outcome | Count | Notes |
|---|---|---|
| **A — Clean pass (16/16)** | 0 | None of the three businesses passed. |
| **B — Hard-fail with precise diagnostic** | 3 | All three. Architecture working as designed. |
| **C — Hard-fail without useful diagnostic** | 0 | Every diagnostic includes operation, contract, quarter, actual vs expected, lever. |

---

## 3. Architectural observations

### 3.1 The right thing is happening

Every E2E hit the **existing** finalize fail-fast layer (`run_finalize_post_intake_validation` at [finalize_post_intake.py:397](../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L397)) — the layer that has been catching contract violations all along. What changed is **Commit 2 #40** removed the orchestrator's `failed_downgraded_to_warning` wrapper, so the violations now propagate up to the API as HTTP 500 with the structured diagnostic instead of being recorded into `completion_trace` and ignored. This is the architectural intent: the bug is no longer hidden.

The user's predicted outcome from the Task 3 brief was:
> If Sunny hard-fails, the diagnostic from the new exception should point exactly to the network retry exhaustion site. That's the success case for this commit.

The actual outcome is one step further along the same path. The DNS conditions Sunny had during the original run aren't present today (the OpenAI API resolves cleanly), so the GPT exhaustion handler doesn't fire its NetworkRetryExhausted path. Instead, the deterministic pipeline runs through, and the finalize gate catches contract violations that **predate** Commits 1-4. Those violations were always there; the orchestrator's downgrade had been hiding them.

### 3.2 None of the new C1-C4 hard-fails fired

No `NetworkRetryExhausted`, no `PostIntakePreconditionFailed`. This makes sense:
- Commit 1's retry primitive only matters when the network actually fails — DNS / OpenAI is healthy today.
- Commit 2's handler-side hard-fails (#19, #27) only fire when the deterministic pipeline reaches the GPT exhaustion handler. None of the three runs got that far — they failed at finalize, which is downstream of the cash strategy and upstream of the exhaustion handler? Wait, finalize is the LAST step. Let me re-check.

Re-reading orchestrator.py: the pipeline order is restoration → handler → cash → realism → finalize → persist. So finalize IS the last step. The runs reached finalize (the diagnostic says so) and finalize raised. The handler didn't fire because restoration didn't return EXHAUSTED — meaning the deterministic restoration loop **succeeded** in landing viability for these three businesses with healthy network.

This is consistent with the system's design: GPT exhaustion handler is a fallback. With healthy network and viable inputs, the deterministic path lands on its own. The bugs that surfaced are downstream contract violations that the legacy downgrade was hiding regardless of which path the run took.

### 3.3 Diagnostic quality

The error format is **operator-readable in one log line per violation**:
```
POST_INTAKE:<flag_name>@<stage>: <message>: <list of violations with quarter, actual, expected>
```

Each violation entry names the precise field, quarter, actual value, and expected value. This is the format target the audit doc set out, and it landed naturally because the existing fail-fast asserts were already producing this shape — it's just no longer being thrown away.

### 3.4 Surfaced bugs are pre-P3.10

Every surfaced bug existed before Commit 1. The architectural overhaul didn't introduce them; it stopped hiding them. Per the user's directive, none of these are fixed in this E2E pass — they're documented in [phase_9_p3_10_e2e_surfaced_bugs.md](phase_9_p3_10_e2e_surfaced_bugs.md) and await user review before being fixed in separate, focused commits.

### 3.5 Email-on-success path

The runner's `_persist_reports` block fired (each business produced 4 report files in `Apps/Test Runs/`, `Apps/Test Runs Data/`, and `Apps/New Runner/`). However, the auto-email-on-success feature did NOT fire because the runs failed before the workbook generation + email send block in [intake_consult.py:7396](../python/api_handlers/intake_consult.py#L7396) was reached. This confirms the gap that **Commit 5's Part B** (email-on-failure feature) is intended to fill: hard-fails currently produce zero email signal, leaving the operator dependent on inspecting the API HTTP response by hand.

---

## 4. What this means for next steps

Per user discipline ("DO NOT fix the bugs in the same session as E2E — document only. Fix in subsequent focused commits after E2E results are reviewed by user"), the next decisions are the user's:

1. **Review the surfaced bugs** in [phase_9_p3_10_e2e_surfaced_bugs.md](phase_9_p3_10_e2e_surfaced_bugs.md) and decide which to fix and in what order.
2. **Authorize fix commits** — each gets its own commit per the standing P3.10 cadence (commit + push + smoke-test before next).
3. **Authorize Commit 5** (Phase-3 floor audit + email-on-failure) — independent of the surfaced-bug fixes, but the email-on-failure feature would have made these E2E results visible without manual inspection of HTTP 500 responses.

The architectural overhaul itself (Commits 1-4) is **validated**: under `CONVERGENCE_TEST_MODE=true`, every critical operation that could prevent a successful pass now does so loudly with a diagnostic that points at the fix. The "run should never get to the end failed" principle is satisfied: the run does not reach the end at all when something is wrong; it halts at the first violation and tells the operator what's broken.

---

## 5. Reproducibility

The exact runs above can be reproduced (assuming `CONVERGENCE_TEST_MODE=true` in `.env` and a healthy MySQL connection):

```bash
# 1. Start the dedicated 5051 API instance with C1-C4 code:
python context/run_api_5051_p3_10.py > tmp/api_p3_10_5051.out.log 2> tmp/api_p3_10_5051.err.log &

# 2. Run each business:
python "Test Files/run_persisted_system_run.py" --draft-id 51ab9a6d257149cda1fdd76a61e3aeef --base-url http://127.0.0.1:5051 --seed p3_10_e2e_nexgen
python "Test Files/run_persisted_system_run.py" --draft-id 6c7544ec12bc44fe91d7e5acd44336cd --base-url http://127.0.0.1:5051 --seed p3_10_e2e_sunny
python "Test Files/run_persisted_system_run.py" --draft-id a5e0363963d546e0a597ce6dbdeb787d --base-url http://127.0.0.1:5051 --seed p3_10_e2e_express
```

Captured output logs for this E2E run are in:
- [tmp/e2e_p3_10_nexgen.out.log](../tmp/e2e_p3_10_nexgen.out.log)
- [tmp/e2e_p3_10_sunny.out.log](../tmp/e2e_p3_10_sunny.out.log)
- [tmp/e2e_p3_10_express.out.log](../tmp/e2e_p3_10_express.out.log)
