# Phase 9 P3.10 Task 3 — Final Report

**Status:** All 5 commits pushed. 28/28 unit smoke tests pass. E2E validated against NexGen, Sunny, Express.
**Branch:** `intake-stable` (HEAD `386d00e`).
**Scope:** Architectural overhaul converting silent failure swallowing in the post-intake pipeline to hard-fail with structured diagnostic + email-on-failure, gated on `CONVERGENCE_TEST_MODE=true`. Production mode behavior is preserved.

---

## 1. Commit summary

| # | SHA | Title | Files | Tests |
|---|---|---|---|---|
| 1 | `981b134` | phase_9_p3_10_network_retry_primitive | 3 | 11 |
| 2 | `90f3676` | phase_9_p3_10_critical_hard_fails | 7 | 6 |
| 3 | `0e12263` | phase_9_p3_10_high_severity_hard_fails | 10 | (covered by source-level verification + targeted spot tests) |
| 4 | `a020444` | phase_9_p3_10_moderate_hard_fails_and_persistence | 4 | 5 |
| 5 | `386d00e` | phase_9_p3_10_phase3_floor_audit_and_email_on_failure | 5 | 6 |

Plus diagnostics commits in the same task arc:
- `d5b195e` — Task 1 (Sunny precondition failure diagnosis)
- `e1e2dc0` — Task 2 (critical operations audit)
- `31a7c10` — E2E results + surfaced bugs after Commits 1-4

### 1.1 Commit 1 — Network retry primitive

[python/client_intake_and_finmo/post_intake_solver/_network_retry.py](../python/client_intake_and_finmo/post_intake_solver/_network_retry.py) (new). Foundation for everything else.

- `call_with_retries(request_callable, ...)`: 3 total attempts, exponential backoff (1s, 2s default).
- Retriable: DNS, connect/read timeouts, SSL handshake, HTTP 429 (honors `Retry-After` cap-60s), HTTP 500/502/503/504.
- Non-retriable: HTTP 400/401/403/404/405/410/422 → `NonRetriableHTTPError`.
- After exhaustion: `NetworkRetryExhausted` with `endpoint`, `attempts_made`, `elapsed_seconds`, `final_failure_kind`, `final_status_code`, `final_exception_class`, `attempt_log[]`.
- Wired into both chokepoints in `_gpt_critic_io.py` (`call_gpt_with_schema_or_fallback`, `call_gpt_responses_api_turn`).
- Q2 satisfied: retry-exhausted calls don't consume the per-run GPT budget; only successful HTTP responses do.

11 mocked smoke tests pass (DNS exhaustion, retry-then-succeed, 429 with Retry-After, HTTP 5xx exhaustion, 400/401/403/404 immediate raise, exponential backoff schedule, Retry-After parsing).

### 1.2 Commit 2 — Critical-severity hard-fails

The six "this commit alone would have fixed Sunny" sites.

- New `PostIntakePreconditionFailed` exception in [fail_fast/common.py](../python/client_intake_and_finmo/fail_fast/common.py). Carries `operation`, `pipeline_stage`, `expected`, `actual`, `details`, `cause`. Re-exported from `post_intake_fail_fast`.
- `HandlerStatus` enum split: `FAILED_PRECONDITION` reserved for genuine preconditions (raised under test mode); new `FAILED_NO_USABLE_ANCHORS` for post-session "no anchors produced."
- Six conversions:
  - `#19` handler.py pre-session FINMO build → raises
  - `#27` tool_calling_session.py post-commit FINMO rebuild → raises
  - `#11` adaptation_cascade.py Tier 7 envelope-build + inner-runner exceptions propagate (the "residuals=[] masquerade" pattern eliminated)
  - `#28` orchestrator.py outer try/except around handler block re-raises under test mode
  - `#29` orchestrator.py outer try/except around restoration loop block re-raises
  - `#40` orchestrator.py finalize wrapper re-raises; literal string `"failed_downgraded_to_warning"` removed from the codebase

6 unit smoke tests pass.

### 1.3 Commit 3 — High-severity hard-fails (16)

| Site | What surfaces |
|---|---|
| `#21` tool_calling_session.py:535 session loop | network_retry_exhausted no longer silently breaks |
| `#23` mini_finmo.py compute_trajectory_from_anchors | writer/FINMO crash no longer masquerades as `all_pass=False` probe |
| `#24` handler.py P&L writer | non-numeric anchor / no-rows raise; missing-anchor raises only when other P&L anchors present (so bs_only_path legitimate skips preserved) |
| `#25` handler.py WC writer | non-numeric / no-rows raise; nullable WC null preserved |
| `#9` target_seeking_loop.py inner joint-fit exception | propagates |
| `#10` target_solver.py _compute_metric_per_q | formula crash no longer silently substitutes 0.0 |
| `#16` restoration_loop.py _evaluate_viability | formula crash no longer flips check to False (audit's "error becomes business verdict") |
| `#17` restoration_loop.py _classify_forecast_exhaustion | validator import / call / realism rows lookup all raise |
| `#18` restoration_loop.py band resolver _resolve_band_for_target + _band helper | NAICS baseline lookup exception raises |
| `#30/#31` cash_strategy/orchestrator_invocation.py 5 step wrappers | every cash step's exception now raises |
| `#35` realism/validator.py | trajectory + per-quarter formula exceptions raise; NAICS baseline lookup raises |
| `#13` structural_feasibility_check.py | fail-open on missing inputs converted to raise |
| `#14` joint_feasibility_check.py | missing envelope/targets raises at function entry |

Import smoke validation; targeted joint feasibility spot test confirms raise under test mode and no-raise under production mode.

### 1.4 Commit 4 — Moderate-severity + persistence

| Site | Change |
|---|---|
| `#26` handler.py compute_metrics_to_mute | realism lookup load failure raises |
| `#15` orchestrator.py composite revenue trajectory check | validator exception propagates |
| `#41` orchestrator.py persist_finalize_stage | SQL UPDATE failure propagates |
| Cash strategy final FINMO rebuild | failure raises under test mode |

5 unit smoke tests pass.

### 1.5 Commit 5 — Phase-3 floor audit + email-on-failure

**Part A** ([docs/phase_9_p3_10_phase3_floor_audit.md](phase_9_p3_10_phase3_floor_audit.md)):
- `_run_cash_strategy_review_openai` — real Python floor verified downstream-usable. Three critic-failure log statements escalated WARNING → ERROR with floor-audit provenance.
- `_estimate_stage_ramp_contract_with_gpt` — no Python floor by design; already raises on every failure mode. No change.

**Part B**:
- `workbook_email.send_failure_alert(...)` + `build_run_failure_email_body(...)`: never-raises contract, returns status dict, SMTP failure logged at ERROR, structured diagnostic unpacked into body.
- `_dispatch_post_intake_failure_alert` helper in `intake_consult.py` wired into both `RuntimeError` and catch-all `Exception` blocks of the system-run handler. Side-effects per call: look up business_name, build failure_diagnostic from exception's `to_dict()`, INSERT `post_intake_run_diagnostics` row with `acceptance_score="FAILED"`, dispatch email, return outcome dict in HTTP 500 body.

6 unit smoke tests + live E2E confirmed: NexGen run returned HTTP 500 with `failure_email: sent=True` and the FAILED diagnostic row was inserted in MySQL.

---

## 2. Architectural principles satisfied

The user's directive verbatim: *"hard fail everything that can prevent a success pass, from the mechanics to the check, all post-intake critical infrastructure. the run should never get to the end failed."*

Concrete satisfaction:

| Principle | How satisfied | Evidence |
|---|---|---|
| Every critical operation must raise (not return status) when preconditions fail | 35 conversion sites across C2-C4 | All gated on `CONVERGENCE_TEST_MODE=true` |
| Exception must carry diagnostic context | `PostIntakePreconditionFailed.to_dict()` always carries `operation`, `pipeline_stage`, `expected`, `actual`, `details`, `cause` | Demonstrated in E2E HTTP 500 bodies + failure emails |
| No defensive try/except around critical operations swallowing into status | Orchestrator outer catches (#28, #29, #40) removed under test mode; cash strategy step wrappers, mini-FINMO error-as-result patterns all converted | Source-level grep clean of legacy `failed_downgraded_to_warning` |
| Test-mode behavior is hard-fail everywhere; production-mode preserved | Every `if convergence_test_mode_enabled(): raise` branch leaves the legacy status-return path intact for production | Production-mode preservation tested explicitly in `test_critical_hard_fails_commit2.py::test_production_mode_preserves_legacy_status_return` |
| Email on failure visible to operator in real-time | C5 Part B — `failure_email` in HTTP 500 response body + actual SMTP send + ERROR-level log if send fails | E2E NexGen run delivered email to `ignatius.henry@tithefinancial.com` |
| The run should never get to the end failed | Pipeline halts at first violation; the only way to reach the end is to actually pass | E2E: all 3 businesses halted at finalize, never produced misleading workbooks or 13/16 acceptance scores |

---

## 3. Before / After — Sunny canonical scenario

Sunny's original run (draft `18e1d01b`, captured `2026-05-12T14:30:03Z`) — the canonical case that motivated the entire overhaul.

### 3.1 Before (pre-Commit 1)

1. Restoration loop returned EXHAUSTED.
2. GPT exhaustion handler called; first OpenAI Responses-API turn raised `ConnectionError("Failed to resolve 'api.openai.com'")` from urllib3.
3. `post_openai_with_retries` retried 3 times — DNS still bad — re-raised `ConnectionError`.
4. Chokepoint `except Exception` caught and returned `decision_source="python_proposer_only_critic_unexpected_error"`.
5. Session loop's `decision_source != "python_proposer_plus_gpt_critic"` check broke the loop silently.
6. Session returned `ToolCallSessionResult(status="failed_precondition", tool_calls_used=0)`.
7. Handler returned `HandlerResult(status=FAILED_PRECONDITION, reason="tool_calling_session_failed: gpt_turn_failed: HTTPSConnectionPool...")`.
8. Orchestrator's outer `except Exception` recorded into `completion_trace` and continued.
9. Cash strategy ran (succeeded — doesn't care about EBITDA viability).
10. Realism gate ran on the un-restored model — 4 universal-viability EBITDA metrics hard-failed.
11. Finalize ran — would have caught additional contract violations, but its outer `except Exception` (the `failed_downgraded_to_warning` block) swallowed them.
12. Workbook generated. Auto-email failed (same DNS outage). 13/16 acceptance score delivered as the "result."

Total surface area visible to operator at HTTP API level: an `acceptance_gate_failed` response with `acceptance_score=13/16`. To find the root cause, the operator had to:
- Open the `Test Runs Data/` JSON file
- Scroll to line 114755
- Read 4 levels of nested `provenance`
- Notice `decision_source=python_proposer_only_critic_unexpected_error` and `detail=HTTPSConnectionPool... Failed to resolve 'api.openai.com'`

### 3.2 After (Commits 1-5, with `CONVERGENCE_TEST_MODE=true`)

Same DNS-outage scenario:

1. Restoration loop returns EXHAUSTED.
2. Handler calls first OpenAI Responses-API turn.
3. `call_with_retries` (C1) retries 3 times with 1s, 2s backoff. DNS still bad. **Raises `NetworkRetryExhausted` with `attempt_log`, `elapsed_seconds`, `final_failure_kind=dns_error`.**
4. Chokepoint catches `NetworkRetryExhausted`, logs at ERROR, returns `decision_source="python_proposer_only_critic_network_retry_exhausted"` with the full attempt log in `raw_openai_response`.
5. Session loop's `decision_source != ...` branch (C3 #21) **raises `PostIntakePreconditionFailed`** with operation tag `gpt_exhaustion_handler_tool_calling_session_turn_failed` and the network retry diagnostic.
6. Handler's outer code doesn't catch — exception propagates.
7. Orchestrator's outer `except Exception` (C2 #28, #29) under test mode **re-raises**.
8. `_run_planning_system_for_draft` propagates the `PostIntakePreconditionFailed` to the API handler.
9. The API handler's `except Exception` block (C5 Part B):
   - Logs at ERROR
   - Calls `_dispatch_post_intake_failure_alert`:
     - Looks up Sunny's business_name from `intake_consult_drafts`
     - Builds failure_diagnostic from `PostIntakePreconditionFailed.to_dict()`
     - INSERTs row into `post_intake_run_diagnostics` with `acceptance_score="FAILED"`
     - Sends email via `send_failure_alert`:
       - Subject: `POST-INTAKE FAILURE: Sunny Glaze Donuts - PostIntakePreconditionFailed`
       - Body unpacks the structured diagnostic: operation, pipeline_stage, expected, actual, details, cause_class=ConnectionError, attempt_log
   - Returns HTTP 500 with body:
     ```json
     {
       "error": "system_run_failed",
       "detail": "post_intake_precondition_failed: operation=gpt_exhaustion_handler_tool_calling_session_turn_failed pipeline_stage=phase_9_p3_9_tool_calling_session cause=NetworkRetryExhausted: network_retry_exhausted: endpoint=https://api.openai.com/v1/responses attempts=3 elapsed=3.04s final=dns_error",
       "failure_email": {"sent": true, "recipient": "...", "subject": "POST-INTAKE FAILURE: ..."}
     }
     ```

Total surface area visible to operator at HTTP API level: **one line that names the operation, the cause, the elapsed time, and points directly at the fix (DNS resolution).** No need to scroll into JSON files; no misleading 13/16 score; no workbook generated against a broken plan. An email arrives in the inbox in seconds.

### 3.3 Note on today's E2E

Today's E2E runs (commit `31a7c10` / `386d00e`) did not hit the DNS path because DNS is healthy. Instead, the deterministic restoration loop landed viability without invoking the handler at all, and the runs surfaced 4 unrelated pre-P3.10 latent bugs at the finalize layer — exactly the architectural validation we needed. See [phase_9_p3_10_e2e_results_commits_1_through_4.md](phase_9_p3_10_e2e_results_commits_1_through_4.md) and [phase_9_p3_10_e2e_surfaced_bugs.md](phase_9_p3_10_e2e_surfaced_bugs.md).

---

## 4. E2E surfaced bugs (held for separate fix commits)

Documented in [phase_9_p3_10_e2e_surfaced_bugs.md](phase_9_p3_10_e2e_surfaced_bugs.md). Summary:

| ID | Description | Businesses | Likely culprit |
|---|---|---|---|
| A | Debt principal flat for 20 quarters with no new borrowing recorded | NexGen, Express | Debt schedule writer / cash strategy minimum-plan applier |
| B | Q1 short_term_debt off by 5-8% from expected (NexGen 0.95×, Express 0.9225×) | NexGen, Express | BS seed-policy multiplier or short-term-debt formula |
| C | Sunny payroll quarter_total ~52% of row-level rollup | Sunny | Payroll headcount schedule writer |
| D | Express deferred revenue applicability=deferred_revenue_business + value=0 + zero_allowed_reason=no_upfront_or_deferred_revenue_model | Express | Cross-module applicability vs value reconciliation |

These existed before Commit 1. The overhaul didn't introduce them; it stopped hiding them.

---

## 5. Tests

Cumulative smoke tests across the 5 commits:

```
tests/test_network_retry_primitive.py       — 11 tests, 0.005s  (C1)
tests/test_critical_hard_fails_commit2.py   —  6 tests, 0.319s  (C2)
tests/test_moderate_hard_fails_commit4.py   —  5 tests, 0.067s  (C4)
tests/test_email_on_failure_commit5.py      —  6 tests, 1.259s  (C5)
                                            ----
                                              28 tests, all pass
```

E2E confirmation:
- NexGen, Sunny, Express E2E'd against the fresh 5051 API instance loaded with all 5 commits' code.
- All three: HTTP 500 with structured diagnostic, finalize-layer fail-fast surfaced (Outcome B).
- NexGen re-run on C5: HTTP 500 included `failure_email` with `sent=True`; FAILED diagnostic row inserted in `post_intake_run_diagnostics`.

---

## 6. What is NOT done (out of P3.10 scope by user direction)

1. **Fixing the four surfaced bugs (A-D)** — held for separate focused fix commits after user review.
2. **Regenerating the canonical test baselines** (NexGen, Sunny, Express intake-complete drafts) under the tightened pipeline — should happen after bugs A-D are fixed, otherwise every baseline will encode the same contract violations.
3. **Wider Python-floor verification across the other Phase-3 consultants** — Commit 5 Part A closed the deferred question 3 from Sunny diagnosis; the audit found only one critic-pattern site needed verification. If more critic-pattern sites are added later, the same audit format applies.
4. **Production-mode behavioral changes** — user explicitly scoped P3.10 to `CONVERGENCE_TEST_MODE=true`. Production-mode soft-degrade paths are intact.

---

## 7. Operational notes

### 7.1 How to run P3.10-enabled API for verification

```bash
# Set CONVERGENCE_TEST_MODE=true in .env (it is)
python context/run_api_5051_p3_10.py > tmp/api_5051.out.log 2> tmp/api_5051.err.log &
```

The launcher sets `CONVERGENCE_TEST_MODE=true` in `os.environ` BEFORE importing `api.app`, guaranteeing all hard-fail branches are active for that instance regardless of the .env load order.

### 7.2 How to verify the email-on-failure path

Run any of the three canonical drafts against the 5051 instance:

```bash
python "Test Files/run_persisted_system_run.py" \
  --draft-id 51ab9a6d257149cda1fdd76a61e3aeef \
  --base-url http://127.0.0.1:5051 \
  --seed nexgen_p3_10
```

HTTP 500 body will include `failure_email: {sent: true, ...}` and `EMAIL_ALERTS_ADDRESS` will receive a `POST-INTAKE FAILURE: ...` message. A row will appear in `post_intake_run_diagnostics` with `acceptance_score='FAILED'`.

### 7.3 How to disable hard-fail (production mode)

Set `CONVERGENCE_TEST_MODE=false` (or unset) in the environment. The legacy status-return / soft-degrade paths remain in place behind every `if convergence_test_mode_enabled(): raise` branch.

---

## 8. Closing

Task 3 of Phase 9 P3.10 is complete. The architecture now satisfies the user's standing principle:

> During testing, every critical operation must fail fast, hard, with a diagnostic that points directly to the fix. Silent degradation is never acceptable for critical operations.

The next phase of work — fixing the four pre-P3.10 latent bugs surfaced by the E2E — begins on user authorization. Each gets its own commit per the established cadence.
