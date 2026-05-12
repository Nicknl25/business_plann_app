# Phase 9 P3.10 — Sunny Glaze Donuts Precondition Failure Diagnosis

**Scope:** Read-only diagnostic. NO code changes. Document only.
**Target run:**
- `draft_id = 18e1d01bc1954defabdd74327983c1f0`
- `planning_run_id = 5923318c0e7045a88e129bb9fd74fe0e`
- Business: Sunny Glaze Donuts (NAICS 311811, operating stage, planning_mode=turnaround)
- Captured at: `2026-05-12T14:30:03.539941Z`
- Acceptance gate result: **13/16 (failed)**
- Environment: `CONVERGENCE_TEST_MODE=true` per `.env` line 18 — fail-fast was supposed to be active.

---

## 1. The smoking gun (one sentence)

The OpenAI Responses API call for the first turn of the GPT exhaustion handler's tool-calling session **failed with a DNS resolution error**; that failure was caught inside [_gpt_critic_io.py](python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py), wrapped in a status dict (`decision_source="python_proposer_only_critic_unexpected_error"`), returned to the session loop which broke out and returned `ToolCallSessionResult(status="failed_precondition", tool_calls_used=0)`, propagated up through `execute_tool_calling_session_and_commit` and `run_gpt_exhaustion_handler` as `HandlerResult(status=FAILED_PRECONDITION)`, and the orchestrator simply recorded this in `completion_trace` without raising. The run continued, the realism gate evaluated the un-restored model, four universal-viability EBITDA metrics hard-failed, and the acceptance gate landed at 13/16.

This is the canonical pattern the user wants destroyed: **a critical operation failed, the system did not halt, the diagnostic ended up only in a JSON payload that nobody reads in real time**, and the run continued long enough to manufacture a misleading "13/16" score.

---

## 2. Exact failure mode

### 2.1 Network failure

From the persisted run JSON (`Test Runs Data/05-12-2026 -- 18e1d01bc1954defabdd74327983c1f0.txt` line 114755 ff):

```
"gpt_exhaustion_handler": {
  "gpt_calls_made": 1,
  "provenance": {
    "tool_calling_session": {
      "decision_sources": ["python_proposer_only_critic_unexpected_error"],
      "detail": "gpt_turn_failed: HTTPSConnectionPool(host='api.openai.com', port=443):
                 Max retries exceeded with url: /v1/responses
                 (Caused by NameResolutionError(\"HTTPSConnection(host='api.openai.com',
                 port=443): Failed to resolve '...",
      "status": "failed_precondition",
      "tool_call_history": [],
      "tool_calls_used": 0,
      "verified_commit_call_n": null,
      "best_effort_call_n": null
    }
  },
  "reason": "tool_calling_session_failed: gpt_turn_failed: HTTPSConnectionPool(...)
             NameResolutionError: Failed to resolve 'api.openai.com'",
  "status": "failed_precondition"
}
```

Underlying cause: **transient DNS resolution failure** (`gaierror: [Errno 11001] getaddrinfo failed` — same error appears immediately below in `auto_email.reason="smtp_failed"` for `smtp.office365.com`, confirming this was a **machine-wide name-resolution outage** during the run window, not an OpenAI-specific event).

### 2.2 What the precondition check actually was

There is no single discrete "precondition" check that fires `FAILED_PRECONDITION`. The status is **derived** from the absence of any usable tool-call output:

1. Inside [tool_calling_session.run_tool_calling_session](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L505) (lines 505-606): the session loop's first turn calls `call_gpt_responses_api_turn(...)`. The returned dict has `decision_source != "python_proposer_plus_gpt_critic"`, so [lines 535-539](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L535) execute `break`, leaving the session loop with `history=[]`, `verified_commit_candidate=None`, `tool_calls_used=0`.
2. After the loop, the post-loop decision tree ([lines 608-656](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L608)):
   - `verified_commit_candidate is None` → not "verified"
   - `_best_effort_record(history)` returns `None` (empty history) → not "best_effort_no_all_pass"
   - Falls through to the **only remaining branch** at lines 646-656: `return ToolCallSessionResult(status="failed_precondition", tool_calls_used=0, ...)`.
3. Inside [tool_calling_session.execute_tool_calling_session_and_commit](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L659): `session_result.final_anchors is None`, so [lines 740-752](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L740) execute `return HandlerResult(status=HandlerStatus.FAILED_PRECONDITION, reason="tool_calling_session_failed: ...")`.

So the literal precondition that "failed" was **"the tool-calling session produced no usable anchors"**. The first-order cause was **a network error on the very first GPT API call**. The handler's "FAILED_PRECONDITION" enum name is misleading — it lumps together (a) genuine pre-session preflight failures (FINMO build, import error) and (b) post-session "no usable anchors" outcomes, including network outages that prevented the session from probing at all.

### 2.3 Full call stack of the failure

```
api.intake-consult/system-run
  → post_intake_solver.orchestrator.run_post_intake_solver
    → run_restoration_loop                                  → returned EXHAUSTED
    → run_gpt_exhaustion_handler                            (orchestrator.py:1669)
      → execute_tool_calling_session_and_commit             (handler.py:686, tcs.py:659)
        → run_tool_calling_session                          (tcs.py:715, tcs.py:431)
          → call_gpt_responses_api_turn                     (tcs.py:522, _gpt_critic_io.py:366)
            → openai_http.post_openai_with_retries          (tcs.py:467)
              → requests.post                               → HTTPSConnectionPool / NameResolutionError
            ← except Exception as exc                       (_gpt_critic_io.py:488-500)
              returns {"decision_source": "python_proposer_only_critic_unexpected_error",
                       "detail": "<urllib3 error string>", ...}    # NEVER RAISES
          ← decision_source != "python_proposer_plus_gpt_critic"
            break                                            (tcs.py:539)         # SILENT
        ← ToolCallSessionResult(status="failed_precondition") (tcs.py:646)        # STATUS ENUM, not exception
      ← HandlerResult(status=FAILED_PRECONDITION,
                      reason="tool_calling_session_failed: ...") (tcs.py:741)
    ← completion_trace["gpt_exhaustion_handler"] = ...      (orchestrator.py:1694) # RECORDED, NOT RAISED
    → cash strategy pass runs anyway                        (orchestrator.py:1721+)
    → realism gate runs on un-restored model
    → acceptance gate scores 13/16
```

Every step from the network error to the acceptance gate is wrapped in a non-raising path.

---

## 3. Where was the failure logged?

| Surface | Logged? | Detail |
|---|---|---|
| Server stderr/stdout logs | **Partial** — `logger.warning("post_intake_solver:%s_critic_unexpected_error: %s", ...)` at [_gpt_critic_io.py:489](python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py#L489). A WARNING-level line, not ERROR; trivially scrolled past in a 200K-line run log. |
| Persisted run JSON (Test Runs Data file) | **Yes** — full provenance recorded at line 114755 under `completion_trace.gpt_exhaustion_handler`, with `status="failed_precondition"`, `decision_sources`, and the network error string in `detail`. |
| `post_intake_run_diagnostics` table / diagnostic payload | **Yes** — captured the four headline fields (`handler_fired=true`, `handler_status="failed_precondition"`, `tool_calls_used=0`, `budget_extension_triggered=false`). This is the field set the user already added in P3.9. |
| Acceptance gate response | **No** — the handler's failure status is not propagated as a `failed_checks` entry. The gate sees only the downstream effects: realism violations, viability_timeline_failed, net_income_trajectory_viable=false. |
| HTTP 500 stop reason returned to the e2e runner | **Implicitly only** — the 500 is raised by acceptance_gate failing, not by the handler. The handler's `failed_precondition` is invisible at the top of the error payload; you have to scroll into `run_diagnostics` to see it. |
| Email alerts | **No** — auto_email itself failed with `gaierror` (same DNS outage), so the operator was not paged. |

The diagnostic payload field `handler_status="failed_precondition"` is the user's existing P3.9 hook into the acceptance gate. It records what happened but **does not gate the run**. The user's directive: convert this to a hard fail under `CONVERGENCE_TEST_MODE=true`.

---

## 4. The defensive code that swallowed the failure

There are six layers between the original `socket.gaierror` and the operator. Every one of them needs to be considered in Task 3.

### 4.1 Layer 1 — `call_gpt_responses_api_turn` `except Exception` (decisive layer)

[python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py:488-500](python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py#L488)

```python
except Exception as exc:
  logger.warning("post_intake_solver:%s_critic_unexpected_error: %s", consultant_name, exc)
  _record_gpt_call(consultant_name, "python_proposer_only_critic_unexpected_error")
  return {
    "tool_calls": [],
    ...
    "decision_source": "python_proposer_only_critic_unexpected_error",
    "detail": str(exc)[:200],
    ...
  }
```

The module's docstring at line 205-208 states the design intent explicitly:
> **"Never raises.** The orchestrator treats anything other than python_proposer_plus_gpt_critic as 'Python proposal stands as the safety floor' and tags affected entries with calibration_source=uncalibrated_due_to_gpt_failure."

This is the canonical "soft-degrade by status return" pattern the user is overhauling. For *most* Phase 3 consultants this design is correct (a Phase-3 critic is supplemental — Python's proposal is a valid floor). But for the exhaustion handler the handler **does not have a Python fallback** — the whole point of the handler is "GPT authors the operating model because deterministic algebra is exhausted." Without GPT, there is no fallback, only the broken plan the restoration loop already gave up on.

### 4.2 Layer 2 — Session loop `decision_source != ...` break

[tool_calling_session.py:535-539](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L535)

```python
if turn_resp.get("decision_source") != "python_proposer_plus_gpt_critic":
  detail = (
    f"gpt_turn_failed: {turn_resp.get('detail') or turn_resp.get('decision_source')}"
  )
  break
```

`break` instead of `raise`. The session loop has six failure escape routes (this one, plus parsing failures at lines 559-581, plus parallel tool-call mishaps), every one of which converts the failure into a status string.

### 4.3 Layer 3 — `run_tool_calling_session` fallback return

[tool_calling_session.py:646-656](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L646)

```python
return ToolCallSessionResult(
  status="failed_precondition",
  tool_calls_used=tool_calls_used,
  ...
)
```

Returns status enum, not exception.

### 4.4 Layer 4 — `execute_tool_calling_session_and_commit` no-anchors branch

[tool_calling_session.py:740-752](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L740)

```python
if session_result.final_anchors is None:
  return HandlerResult(
    status=HandlerStatus.FAILED_PRECONDITION,
    ...
    reason=(
      f"tool_calling_session_failed: {session_result.detail or 'unknown'}"
    ),
  )
```

Returns `HandlerResult`, not exception.

### 4.5 Layer 5 — Orchestrator outer `try/except`

[python/client_intake_and_finmo/post_intake_solver/orchestrator.py:1710-1714](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1710)

```python
except Exception as exc:
  completion_trace["gpt_exhaustion_handler"] = {
    "status": "failed",
    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
  }
```

This block wraps the *entire* handler block. Even if Task 3 makes the handler raise, this outer `except Exception` would catch it and continue silently. **This catch must be removed (or scoped to whitelisted exception types) in Task 3 under CONVERGENCE_TEST_MODE.**

### 4.6 Layer 6 — Outer `try/except` around `restoration_loop`

[python/client_intake_and_finmo/post_intake_solver/orchestrator.py:1715-1719](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1715)

```python
except Exception as exc:
  completion_trace["restoration_loop"] = {
    "status": "failed",
    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
  }
```

Wraps the restoration loop and handler block together. Same swallowing pattern — the audit must flag this too.

---

## 5. What about the pre-session FINMO build / import error paths?

The `HandlerStatus.FAILED_PRECONDITION` enum has three documented entry points in [handler.py](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py):

| Site | Lines | Trigger |
|---|---|---|
| Pre-session FINMO build | [handler.py:644-656](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L644) | `build_finmo(model_input)` raises before the session can start |
| `tool_calling_session` module import | [handler.py:661-684](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L661) | The session module is missing — legacy "phase_1_internals_deleted" reason kept for transition |
| Post-session no-anchors / rebuild-after-commit | [tcs.py:740-752](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L740) and [tcs.py:765-778](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L765) | session produced no anchors, or post-commit FINMO rebuild raised |

Sunny's run took **the post-session no-anchors branch** ([tcs.py:740-752](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L740)). The pre-session branches did not fire (FINMO built successfully — see `q1_state` populated in the provenance: revenue=48298.97, ebitda=-48482.10).

All three sites need fail-fast treatment in Task 3.

---

## 6. Why the run produced a misleading 13/16

With the handler returning FAILED_PRECONDITION and no model_input rewrite, the post-handler pipeline saw:

- Restoration-loop output unchanged: every operating-side driver still pinned at its conservative bound, Q11 EBITDA margin = -0.49 (from the exhaustion_diagnostic block).
- Cash strategy ran (balanced mode) — succeeded, because cash strategy doesn't care about EBITDA viability.
- Realism gate fired with no muted metrics (because the handler never populated `_muted_realism_metrics`). The four universal-viability metrics hard-failed:
  - `ebitda_positive_by_q11` (-0.4908)
  - `ebitda_margin_q20_holds_or_improves_vs_q11` (-0.0255)
  - `ebitda_recovery_trend_q5_q11` (-0.0170)
  - `fixed_cost_burden_reduced_or_scaled_by_q11` (-0.1119)
- Acceptance gate failed three of its 16 checks: `realism_gate_no_hard_fail_violations`, `net_income_trajectory_viable`, `viability_timeline_landed`.
- Workbook generated, email send failed (same DNS outage).

The 13/16 number is structurally meaningless — the run never had a usable plan. But because the system delivered a workbook and a score, an inattentive reader could read this as "13/16, close but didn't quite land" rather than "the system never produced a real answer."

---

## 7. Summary for Task 3 scope

The fix is **not** in `_gpt_critic_io.py` (whose "never raises" design is correct for most consultants). The fix is in the exhaustion handler's failure layers (3 sites in handler.py + tool_calling_session.py) and in the orchestrator's outer catches:

- Convert `HandlerStatus.FAILED_PRECONDITION` returns to **raise** under `CONVERGENCE_TEST_MODE=true`, with the existing `provenance` payload as the structured diagnostic.
- Tighten or remove the orchestrator's outer `except Exception` around the handler block (lines 1710-1714) under test mode.
- Decide whether the "no Python fallback" property generalizes to other handler-like sites in post-intake — the audit in Task 2 will enumerate them.

Under `CONVERGENCE_TEST_MODE=true` the failure mode for Sunny's run should have been:

```
RuntimeError: POST_INTAKE:gpt_exhaustion_handler_no_anchors@phase_9_p3_5_gpt_exhaustion_handler:
  Tool-calling session produced no usable anchors (tool_calls_used=0).
  Underlying turn-1 detail: python_proposer_only_critic_unexpected_error —
  HTTPSConnectionPool(host='api.openai.com', port=443): Failed to resolve 'api.openai.com'.
  draft_id=18e1d01bc1954defabdd74327983c1f0
  planning_run_id=5923318c0e7045a88e129bb9fd74fe0e
```

That message — surfaced at the top of the system-run HTTP 500 — would have pointed the operator at the DNS outage in seconds.

---

## 8. Open questions for Task 3 (architectural)

These are NOT decided here; they are deferred to Task 3 with user input.

1. **Network errors as fail-fast — yes or retry?** A transient DNS hiccup is a different shape from a malformed model_input. Should the handler retry the first turn N times before raising? The current code already calls `post_openai_with_retries(max_attempts=3, retryable_status=(429,500,502,503,504))` — but that retries on HTTP status codes, not on connection-level errors raised by urllib3. Worth deciding whether to widen the retry guard to network exceptions before promoting the handler-level failure to fail-fast.
2. **Should the `_GPT_CALL_BUDGET_PER_RUN` accounting count failed calls?** A DNS-failed call currently still costs against the run budget (`_record_gpt_call(... "python_proposer_only_critic_unexpected_error")`). If a future P3.9 retry happens after a transient outage, the budget is already burned.
3. **Phase 3 consultants vs. handler.** The `"never raises"` design at [_gpt_critic_io.py:205](python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py#L205) is correct for Phase-3 consultants where Python has a deterministic floor. The handler does not. Confirm: should the audit in Task 2 also re-check every consultant call site for whether the "Python floor" actually exists?

These three are flagged here so the audit (Task 2) can scope them; the user will decide their disposition before Task 3.
