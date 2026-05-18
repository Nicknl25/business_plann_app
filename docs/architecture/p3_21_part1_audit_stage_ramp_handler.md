# Phase 9 P3.21 Part 1 — Handler A audit: Stage Ramp Handler

**Overall classification: COMPLIANT.**  All four doctrinal
properties hold.  No fix work required.

## 1. Handler identification

- **Name:** Stage Ramp Handler
- **Module:** `python/client_intake_and_finmo/post_intake_stage_ramp_handler/`
- **Entry points:**
  - `run_stage_ramp_handler` at [handler.py:252](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L252) — given a Python-built contract + validator error, runs the GPT tool-calling session to refine the contract.
  - `engage_stage_ramp_handler_on_validator_failure` at [handler.py:352](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L352) — production wiring entry point: Python-first, handler-on-validator-failure.
- **Tool session:** `run_stage_ramp_tool_calling_session` at [tool_calling_session.py:260](python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py#L260).
- **Orchestrator integration:** `_stage_ramp_contract_python_first_with_handler` wrapper at [api_handlers/intake_consult.py:94](python/api_handlers/intake_consult.py#L94), dependency-injected at [intake_consult.py:7066](python/api_handlers/intake_consult.py#L7066) into the `_run_unified_post_grid_system_run` flow via `estimate_stage_ramp_contract_with_gpt=...`.

## 2. Pattern classification

**Python→GPT handler-on-failure — confirmed.**  Matches the funding-
handler shape from P3.20 Part 3:
1. Python builder produces the contract (`build_python_stage_ramp_contract`).
2. Canonical validator (`_validate_stage_ramp_contract_payload`) runs on Python output.
3. If validator raises, handler engages (`run_stage_ramp_handler`).
4. Handler iterates within a 10-tool-call budget, using the same validator as a per-turn probe.
5. RESOLVED → refined contract returned with provenance annotation; EXHAUSTED → `RuntimeError` raised with residual diagnostic.

Authority is the `stage_ramp_contract` grid fields per `STAGE_RAMP_FIELD_AUTHORITY` (doctrine §6 row "Stage ramp").

## 3. PROPERTY 1 — NEVER REVERT

**Conclusion: COMPLIANT.**

Code paths examined:
- [handler.py:428-461](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L428-L461) `engage_stage_ramp_handler_on_validator_failure`:
  - Validator fails → handler invoked.
  - Handler RESOLVED → return refined contract (annotated provenance).
  - Handler EXHAUSTED → `raise RuntimeError(handler_result.diagnostic) from exc` at line 451.  Hard-fail with diagnostic.  No fallback to pre-handler state.
- [intake_consult.py:111-134](python/api_handlers/intake_consult.py#L111-L134) wrapper `_stage_ramp_contract_python_first_with_handler`:
  - Wraps `_engage_stage_ramp_handler` in `try: ... except RuntimeError: raise RuntimeError("stage_ramp_handler_exhausted: " + str(exc)) from exc`.
  - **No fallback to legacy GPT path** (the docstring at line 109-110 mentions a legacy fallback but the code does not implement one — only re-raises).  Stale comment, not a doctrine violation.
- Downstream consumption: the returned contract is persisted into the orchestrator's working state and used by every subsequent process.  No site overwrites it.

Grepped for revert patterns specific to stage ramp:
```
git grep -E "(stage_ramp_contract\s*=\s*\{|stage_ramp_contract\s*=\s*copy\.deepcopy\(pre_)"
```
No matches.  Stage ramp contract is never reverted, replaced with a pre-state copy, or cleared.

The hard-fail-on-EXHAUSTED behavior is doctrinally correct: per doctrine §1 hard-fail with diagnostic, not silent recovery.  Stage 1's "never revert" rule applies to handler output that succeeded; EXHAUSTED is the intentional hard-fail mode.

## 4. PROPERTY 2 — TRIGGER ON ANY VALIDATOR FAILURE

**Conclusion: COMPLIANT.**

Trigger condition at [handler.py:428-449](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L428-L449):

```python
try:
    validator(payload=python_contract, ...)
except RuntimeError as exc:
    # Python output rejected — escalate to handler.
    handler_result = run_stage_ramp_handler(
        python_contract=python_contract,
        validator_error_text=str(exc),
        ...
    )
```

The trigger is binary: *any* `RuntimeError` from `_validate_stage_ramp_contract_payload` escalates.  No category-specific gating.  No buffer-violations-only-style narrow gate.

The validator itself raises on any of:
- Stage family mismatch (operational / strategic / ramp / etc.)
- Ramp shape mismatch (qoq band / monotonicity / floor)
- Target margin out of policy band
- Capacity curve violations
- Cost ratio cap violations
- R&D applicability vs `r_and_d_enabled` mismatch
- ...

Every one of these raises a `RuntimeError`, which the trigger catches uniformly.  There is no "ignore distribution failures" or "only fire on capacity failures" filter.

## 5. PROPERTY 3 — MIRROR FLAVOR 1 / SINGLE SOURCE OF TRUTH

**Conclusion: COMPLIANT.**  Textbook Mirror Flavor 1 application.

The validator (`_validate_stage_ramp_contract_payload`) is **threaded as a single canonical reference** through every probe site:

- [intake_consult.py:114](python/api_handlers/intake_consult.py#L114): production wrapper injects the validator via `validator=_validate_stage_ramp_contract_payload_for_handler`.
- [handler.py:429](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L429): `engage_*` calls it once on the Python contract.
- [handler.py:319-327](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L319-L327): `run_stage_ramp_handler` post-session re-runs the same validator as the canonical acceptance check after the session reports a verified candidate (defensive — catches session-vs-canonical drift).
- [tool_calling_session.py:288-292](python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py#L288-L292): session resolves the validator from the same module (`_validate_stage_ramp_contract_payload`).
- [tool_calling_session.py:429-445](python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py#L429-L445): per-turn validator probe inside the session loop uses the same validator.
- [handler.py:446-448](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L446-L448): the engage wrapper threads its caller's validator down to `run_stage_ramp_handler` via `_validator=validator` so the production validator and the in-session probe are guaranteed to be the same callable.

The contract that the validator accepts at the session probe is the same contract that the post-session canonical check evaluates, is the same contract that downstream consumes.  No divergent rebuild.  No "session built one shape, post-session validates another."

This is Mirror Flavor 1 — single canonical reference, no parallel paths.

## 6. PROPERTY 3b — FULL FAILURE PAYLOAD

**Conclusion: COMPLIANT — structurally not applicable in the
funding-handler sense; the validator's API is monolithic.**

The funding handler's Property 3b violation was: validator emits five
distinct failure categories (buffer / distribution / surplus / contract
/ hard rule), but the handler historically received only
`cash_buffer_violations`.  Other categories were invisible inside the
handler's reasoning.

The stage ramp validator does **not** have multi-category output.  It
raises a single `RuntimeError` whose message string contains the
specific rejection reason (e.g., `"stage_ramp_qoq_band_violated:
Q3 actual_growth=0.18 exceeds upper_band=0.12 ..."`).  There is no
parallel failure-category list to selectively pass through.

The handler receives the **complete** validator error text:
- [handler.py:441](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L441): `validator_error_text=str(exc)` — the full message.
- [tool_calling_session.py:302](python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py#L302): passed into the initial user prompt.
- [tool_calling_session.py:443-444](python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py#L443-L444): per-turn probe failures return `{"validator_accepted": False, "validator_error_text": str(exc)}` to GPT, giving it the canonical error to reason against.

If a future change splits the validator into multiple category-specific
raises, this property would need re-evaluation.  As of HEAD, the
validator's monolithic-rejection API is the complete payload.

## 7. PROPERTY 4 — DIAGNOSTIC PRESERVATION

**Conclusion: COMPLIANT.**  Confirmed by Stage 4 codebase-wide audit
and reconfirmed in handler-specific context.

Fail-fasts in this handler's domain (per Stage 4 inventory):
- [stage_ramp_handler/handler.py:66](python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L66) — `_stage_ramp_handler_machinery_fail_fast` wrapper.  Concrete operations: `stage_ramp_handler_state_corruption_between_rounds`, `stage_ramp_handler_budget_decoupling_violation`, `stage_ramp_handler_round_count_drift`, `stage_ramp_handler_authority_violation`.
- [stage_ramp_handler/tool_calling_session.py:382](python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py#L382) — `stage_ramp_handler_tool_calling_session_turn_failed`.  Carries `tool_calls_used_before_failure`, `gpt_calls_made_before_failure`, `budget_extension_triggered`, `turn_detail` (500-char clip).

All carry structured `details` payloads (Stage 4 classification: ADEQUATE).

Survival check (Stage 4 audit + handler-specific reconfirmation):
- `PostIntakePreconditionFailed` exceptions propagate — only one catch site exists at `post_intake_solver/orchestrator.py:2215` (which re-raises unconditionally).  SURVIVES.
- The intake_consult.py wrapper at [line 126-134](python/api_handlers/intake_consult.py#L126-L134) catches `RuntimeError` (not `PostIntakePreconditionFailed`) and re-raises with a prefixed message.  Diagnostic survives in the chained exception (`from exc`).  SURVIVES.
- No `except: pass` or silent log-and-continue patterns in this handler's path.

The handler's RESOLVED return path carries the validator-accepted refined contract; the EXHAUSTED return path carries the residual diagnostic text in `StageRampHandlerResult.diagnostic`.  Both reach the orchestrator's persistence layer (the contract is persisted into draft state; the diagnostic surfaces in the chained RuntimeError that hard-fails the system run).

## 8. Overall classification

**COMPLIANT.**  All four properties hold:

| Property | Status |
|---|---|
| 1 — Never revert | COMPLIANT |
| 2 — Trigger on any validator failure | COMPLIANT |
| 3 — Mirror Flavor 1 / single source of truth | COMPLIANT (textbook) |
| 3b — Full failure payload | COMPLIANT (validator API is monolithic; full error text passed through) |
| 4 — Diagnostic preservation | COMPLIANT |

No violations found.  No fix work required.

## 9. Recommended fix scope

**None.**

The stage ramp handler was built in iter 19 Stage 5 with the
Python-first + handler-on-validator-failure pattern already applied
cleanly.  The same validator reference is threaded through every probe
site (Mirror Flavor 1 by construction).  The handler hard-fails with
the residual diagnostic on EXHAUSTED rather than reverting (Stage 1
discipline by construction).  The trigger is `validator raises` —
binary, no category gating (Stage 2 discipline by construction).  The
validator API has a single error string (Stage 3b is structurally
n/a).  Fail-fasts carry rich diagnostic payloads and propagate cleanly
(Stage 4 confirmed).

If a future change to `_validate_stage_ramp_contract_payload` splits
its output into structured category lists (analogous to the cash
post-pass validator's `cash_buffer_violations` / `cash_distribution_
violations` / etc.), Property 3b should be re-audited at that point.
Until then, the contract is doctrine-compliant by design.

## Minor housekeeping note (not a doctrine violation)

The wrapper docstring at [intake_consult.py:107-110](python/api_handlers/intake_consult.py#L107-L110) reads:

> "On Python-and-handler exhaustion, falls back to the legacy GPT call so existing behavior is preserved for cases the new path cannot resolve."

The code at lines 111-134 does NOT implement a legacy-GPT fallback —
it re-raises with a prefixed message.  The docstring is stale from an
earlier iter design.  Recommend updating the docstring on the next
touch of this file; not in P3.21 scope (read-only audit) and not a
doctrine violation either way.
