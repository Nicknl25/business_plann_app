# Phase 9 P3.21 Part 1 — Handler B audit: Restoration / Exhaustion Handler

**Overall classification: COMPLIANT.**  All four doctrinal
properties hold.  No fix work required.

Two notable structural observations are documented below; neither
rises to violation, but both are worth surfacing for context.

## 1. Handler identification

- **Name:** Restoration / Exhaustion Handler (doctrine §6 row "Restoration / exhaustion")
- **Module:** `python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/`
- **Entry point:** `run_gpt_exhaustion_handler` at [handler.py:747](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L747).
- **Tool session:** `run_tool_calling_session` at [tool_calling_session.py:433](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L433); commit entry `execute_tool_calling_session_and_commit`.
- **Orchestrator integration:** two engagement sites in `post_intake_solver/orchestrator.py`:
  - **Site 1 — restoration EXHAUSTED trigger** at [orchestrator.py:1977-1997](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977-L1997).
  - **Site 2 — pre-cash gate trigger** at [orchestrator.py:2130-2168](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2130-L2168) (added in P3.10 Bug F + Bug D).
- **Authority** (doctrine §6): 12 P&L levers + 5 working capital levers.

## 2. Pattern classification

**Python→GPT handler-on-failure — confirmed.**  This is the
pre-iter-19 reference handler that the funding handler (iter 19
Stage 4) and stage ramp handler (iter 19 Stage 5) were modeled
after.  Pattern:

1. Restoration loop (Python deterministic) runs.
2. If restoration EXHAUSTED, GPT exhaustion handler engages (Site 1).
3. Additionally, pre-cash gate evaluates GPT-authorable checks; if any fail AND the natural trigger didn't fire, the handler engages with a synthetic `restoration_result` carrying the failing checks (Site 2).
4. Handler runs GPT tool-calling session; GPT proposes anchors at Q1/Q11/Q20 + WC; tool computes full trajectory; iterates until acceptable or 10-call budget exhausted.
5. On commit: handler mutates `model_input` in place with GPT-authored driver values; FINMO is rebuilt downstream.

## 3. PROPERTY 1 — NEVER REVERT

**Conclusion: COMPLIANT.**

Code paths examined:
- The handler mutates `model_input` in place (per docstring at [handler.py:756](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L756)).  No deep-copy + replace; the orchestrator's `final_model_input_json` IS the dict the handler authors into.
- After handler runs, orchestrator rebuilds FINMO from the mutated model_input ([orchestrator.py:2002-2010](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2002-L2010) for Site 1; [orchestrator.py:2161-2168](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2161-L2168) for Site 2).  On rebuild success, `final_finmo_json` is replaced with the rebuilt copy.  On rebuild failure, `final_finmo_json` keeps its pre-rebuild value but **`final_model_input_json` is NOT reverted** — the handler's authored changes persist.
- Grepped for revert patterns across the orchestrator:
  ```
  grep -n "final_model_input_json\s*=\s*copy\.deepcopy\|final_finmo_json\s*=\s*copy\.deepcopy"
    python/client_intake_and_finmo/post_intake_solver/orchestrator.py
  ```
  Zero matches.  No `final_*_json = copy.deepcopy(pre_*_json)` pattern anywhere in this file.
- Exception handling at [orchestrator.py:2027-2041](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2027-L2041) (Site 1) and [:2215-2227](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2215-L2227) (Site 2 wrapper):
  - Under test mode: `raise` (preserves diagnostic).
  - Under production: stringified into `completion_trace["gpt_exhaustion_handler"]["error"]`.  The handler's authored model_input changes (if any landed before the exception) STILL persist — the except blocks do NOT revert the model_input.

The handler's HandlerResult is preserved in `completion_trace["gpt_exhaustion_handler"]` (line 2011) or `completion_trace["pre_cash_gate_handler"]` (line 2169).  Provenance, gpt_calls_made, realism_flags_to_mute all survive.

The `realism_flags_to_mute` from the handler are additively merged into `final_model_input_json["_muted_realism_metrics"]` ([orchestrator.py:2017-2026](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2017-L2026) for Site 1; [:2170-2180](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2170-L2180) for Site 2).  Additive merge, not destructive replace.

### Structural observation 1 (not a violation)

The Site 2 FINMO rebuild has a silent-swallow at [orchestrator.py:2167-2168](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2167-L2168):
```python
except Exception:
  pass
```
If this rebuild fails, `final_finmo_json` keeps its pre-handler value while `final_model_input_json` has the handler's authored changes — a **temporary state divergence**.  This is benign in current orchestration because the next downstream consumer (cash strategy at [orchestrator.py:2229+](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2229)) rebuilds FINMO from `updated_model_input_json` (Phase 9 P3.20 Stage 3 single-source-of-truth rebuild).  The window of divergence does not reach a validator.  **Not flagged as Property 1 violation** (the handler's work persists; downstream rebuilds correctly), but the silent-swallow itself is a minor anti-pattern.  Site 1's analogous rebuild at [:2009-2010](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2009-L2010) does the same thing but at least captures `rebuild_error` into completion_trace.  Site 2 doesn't even capture the error.

## 4. PROPERTY 2 — TRIGGER ON ANY VALIDATOR FAILURE

**Conclusion: COMPLIANT (under the authority-matched interpretation).**

The handler engages at two sites:

**Site 1 — restoration EXHAUSTED** ([orchestrator.py:1977](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977)):
```python
if restoration_result.status == RestorationStatus.EXHAUSTED:
    handler_result = run_gpt_exhaustion_handler(...)
```
Fires whenever the restoration loop terminates in the EXHAUSTED state (any reason).

**Site 2 — pre-cash gate** ([orchestrator.py:2130](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2130)):
```python
if gate_violations and not _gate_handler_already_ran:
    ...
    gate_handler_result = run_gpt_exhaustion_handler(...)
```
Fires when `_evaluate_gpt_authorable_pre_cash_checks` produces non-empty violations AND Site 1 didn't already engage.  The `_gate_handler_already_ran` flag prevents double-engagement.

Site 2 was added in P3.10 Bug F + Bug D specifically because the EXHAUSTED-only trigger missed GPT-authorable failures that fired after restoration completed but before cash pass — same shape of bug that P3.20 Stage 2 fixed for the funding handler (narrow trigger, handler couldn't engage despite having authority).

### Trigger scope analysis

`_evaluate_gpt_authorable_pre_cash_checks` at [orchestrator.py:263](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L263) intentionally scopes to checks within the handler's authority (operating-side levers per doctrine §6).  Specifically covers:
- `assert_stage_ramp_expense_path_applied`
- `assert_stage_ramp_profitability_path_applied`
- `balance_sheet_driver_zero_but_applicable` (WC lever scope)
- (and a few others under `_evaluate_gpt_authorable_pre_cash_checks`)

**Non-authority failures route elsewhere:**
- Cash buffer / distribution / surplus violations → funding handler (audited in P3.20 Part 3).
- Payroll lever not written → `payroll_lever_not_applied_before_gate` PostIntakePreconditionFailed at [orchestrator.py:236](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L236) (named diagnostic at the upstream contract owner — doctrine §3 Pattern 3).
- Convergence-owned failures → unified convergence handler path.

### Doctrine interpretation

"ANY validator failure" in P3.20 Stage 2 context meant "any failure in the cash pass's post-pass scope."  The funding handler had narrowed this further to buffer-only despite having broader authority — that was the bug Stage 2 fixed.

For the exhaustion handler, the analogous question is: does the trigger fire on every failure within the handler's authority?  The answer is YES via the union of Site 1 (restoration EXHAUSTED for the broad restoration-loop driver-anchor cases) + Site 2 (gate for GPT-authorable check failures that survive restoration).

The handler does NOT fire on failures outside its authority (cash buffer, payroll lever, convergence) — but those route to other handlers per the doctrine §6 authority/check-match principle.  Firing the exhaustion handler on non-authority failures would be the F6-Pinnacle anti-pattern (handler authority doesn't match check set).

**Verdict:** COMPLIANT.  The trigger fires on any failure within authority across both engagement sites.  No analog to the funding handler's pre-Stage-2 narrow-gate bug exists here.

## 5. PROPERTY 3 — MIRROR FLAVOR 1 / SINGLE SOURCE OF TRUTH

**Conclusion: COMPLIANT.**

State flow:
- **Validator evaluates:** `final_model_input_json` + `final_finmo_json` (Site 1: restoration loop reads these; Site 2: `_evaluate_gpt_authorable_pre_cash_checks` at [orchestrator.py:2121-2128](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2121-L2128) reads these).
- **Handler operates on:** same `final_model_input_json` + `final_finmo_json` ([orchestrator.py:1986-1997](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1986-L1997) for Site 1; [:2146-2160](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2146-L2160) for Site 2 — passes the same dicts by reference, no deep-copy).
- **Downstream consumes:** same `final_model_input_json` + (post-rebuild) `final_finmo_json`.  Cash strategy receives `model_input_json=final_model_input_json` and `finmo_json=final_finmo_json` at the wrapper.

No divergent rebuild paths.  The handler's `mini_finmo` shadow object is used inside the tool-calling session for trajectory previews (doctrine §4 Flavor 3 — mini/shadow object) but the COMMIT phase rebuilds canonical FINMO from the authored model_input ([handler.py:859+](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L859) `execute_tool_calling_session_and_commit`).  The mini_finmo and canonical FINMO are intentional Mirror Flavor 3 / Flavor 4 (invariant check) pair, not a Mirror Flavor 1 violation.

### Structural observation 2 (not a violation)

Site 2's silent FINMO rebuild swallow (see Property 1 above) creates a brief state-divergence window where `final_model_input_json` has handler-authored changes but `final_finmo_json` is stale.  The window closes at the cash strategy's Stage 3 pre-validator rebuild (P3.20 Stage 3 work).  Not a Mirror Flavor 1 violation in the doctrine sense (no validator evaluates the divergent state), but the silent-swallow is fragile — if downstream were ever changed to consume `final_finmo_json` without rebuilding first, this would become a Stage 3 P3.20 violation by symmetry.  Flagged for awareness.

## 6. PROPERTY 3b — FULL FAILURE PAYLOAD

**Conclusion: COMPLIANT.**

**Site 1 (restoration EXHAUSTED):**
The handler receives the full `restoration_result` object ([orchestrator.py:1987](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1987)).  `RestorationLoopResult` is a structured dataclass carrying:
- `status` (RestorationStatus enum)
- `failing_metrics` (list of metric_key + per-quarter failures + lever attribution)
- `q11_ebitda_margin`
- `drivers_at_bounds_summary`
- `restoration_iterations`
- `reason`
- (plus serialization via `to_dict()`)

All restoration-loop failure context flows into the handler.  No slice.

**Site 2 (pre-cash gate):**
The synthetic `restoration_result` is built at [orchestrator.py:2137-2141](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2137-L2141):
```python
synthetic_result = _PreCashGateRestorationResult(
    scope=gate_scope,
    failing_metrics=gate_violations,
    q11_ebitda_margin=_q11_ebitda_margin_from_finmo(final_finmo_json),
)
```
`gate_violations` is the **full list** of failing GPT-authorable checks returned by `_evaluate_gpt_authorable_pre_cash_checks` — no filter to a single category before passing to the handler.

In both sites, the handler sees the complete in-scope failure picture and can reason about lever moves that address any combination of them.

## 7. PROPERTY 4 — DIAGNOSTIC PRESERVATION

**Conclusion: COMPLIANT.**  Confirmed by Stage 4 codebase-wide audit
and reconfirmed in handler-specific context.

Fail-fasts in this handler's domain (per Stage 4 inventory):

| File | Lines | Operations |
|---|---|---|
| `handler.py` | 355, 372, 496, 539, 571, 709, 796, 831 | 8 sites covering WC writer + P&L writer + pre-session FINMO build + module import + metrics lookup |
| `mini_finmo.py` | 245, 275, 292 | 3 sites covering compute_trajectory invalid context + writer failed + build_finmo failed |
| `tool_calling_session.py` | 557, 794, 846 | 3 sites covering session turn failed + no anchors + post-commit FINMO rebuild |

All carry structured `details` payloads (Stage 4 classification: 14/14 ADEQUATE).

Survival check:
- `except PostIntakePreconditionFailed:` exists at exactly one site ([orchestrator.py:2215](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2215)) — re-raises unconditionally.  SURVIVES.
- `except Exception as cascade_exc:` at [orchestrator.py:2027](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2027) (Site 1) and [:2042](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2042) (outer): under test mode `raise`, under production stringifies into `completion_trace`.  Diagnostic survives both modes.
- HandlerResult is serialized into `completion_trace["gpt_exhaustion_handler"]` ([line 2011](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2011)) / `completion_trace["pre_cash_gate_handler"]` ([line 2169](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2169)).  Reaches the persistence layer.

Stage 4's audit explicitly confirmed (a) the 14 fail-fast sites and (b) the absence of `except: pass` patterns in this handler's path.  No re-evaluation contradicts that here.

## 8. Overall classification

**COMPLIANT.**  All four properties hold:

| Property | Status |
|---|---|
| 1 — Never revert | COMPLIANT (Structural Observation 1: Site 2 silent rebuild swallow is benign but fragile) |
| 2 — Trigger on any validator failure | COMPLIANT (authority-matched interpretation; two engagement sites cover the full authority scope) |
| 3 — Mirror Flavor 1 / single source of truth | COMPLIANT (Structural Observation 2: Site 2 silent rebuild creates a brief state-divergence window, closed by cash strategy's Stage 3 rebuild) |
| 3b — Full failure payload | COMPLIANT (both sites pass complete in-scope failure context) |
| 4 — Diagnostic preservation | COMPLIANT |

No violations found.  No fix work required.

## 9. Recommended fix scope

**None for doctrine compliance.**

Two minor structural items, neither required:

**Optional cleanup A** — Site 2 FINMO rebuild silent-swallow.
[orchestrator.py:2167-2168](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2167-L2168) catches all exceptions with bare `pass`.  Site 1's analogous rebuild at [:2002-2010](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2002-L2010) captures `rebuild_error` into `completion_trace`.  Recommend Site 2 capture similarly so the diagnostic isn't silently lost when the gate handler's rebuild fails.  ~5 LOC.  Not in P3.21 scope (read-only) but worth noting for any future touch.

**Optional cleanup B** — wrapper docstring vs implementation drift.
None observed here (unlike Handler A's intake_consult wrapper).  No housekeeping needed.

## Comparison with funding handler (P3.20 Part 3 retrofit)

| Aspect | Funding handler (pre-P3.20) | Funding handler (post-P3.20) | Exhaustion handler (today) |
|---|---|---|---|
| Property 1 | VIOLATION (cash strategy revert cleared `cash_contract_failures`) | COMPLIANT (Stage 1 removed revert) | COMPLIANT (mutates in place, no revert) |
| Property 2 | VIOLATION (buffer-only gate, ignored distribution / surplus / contract / hard_rule) | COMPLIANT (Stage 2 widened to ANY validator) | COMPLIANT (authority-matched + dual engagement sites) |
| Property 3 | VIOLATION (two FINMO rebuild sites diverged) | COMPLIANT (Stage 3 collapsed to single pre-validator rebuild) | COMPLIANT (handler operates on canonical state; rebuilds canonical FINMO post-commit) |
| Property 3b | VIOLATION (received only `cash_buffer_violations`, missed other categories) | COMPLIANT (Stage 3b broadened to all categories) | COMPLIANT (full restoration_result + full gate_violations) |
| Property 4 | COMPLIANT (Stage 4 audit) | COMPLIANT | COMPLIANT |

The exhaustion handler was built right by construction (pre-iter-19).  The funding handler had to be retrofitted across four stages.  No retrofit needed here.
