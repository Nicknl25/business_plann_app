# Phase 9 P3.21 Part 1 — Handler C audit: Payroll Iterative Refinement

**Pattern classification: NOT a Python→GPT handler-on-failure pattern.**
This is a **GPT-as-authoring-source** with intra-GPT iterative refinement,
explicitly documented as such in doctrine §6.

The P3.20 Part 3 four-property doctrine does not apply in the
funding-handler sense.  However, three of the four properties have
modified-form analogs that DO apply to GPT-as-authoring-source
iteration loops; those are audited below.  All applicable analogs hold.

**Outcome: COMPLIANT with the applicable doctrine.  No fix work
required.**

## 1. Handler identification

- **Function:** `estimate_payroll_headcount_schedule_with_gpt` at [post_intake_headcount/schedule.py:2180](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2180).
- **Module:** `python/client_intake_and_finmo/post_intake_headcount/`.
- **Related:** `payroll_validator_translator.py` translates validator failures into structured GPT-feedback packets ([line 167+](python/client_intake_and_finmo/post_intake_headcount/payroll_validator_translator.py#L167)).
- **Orchestrator integration:** invoked from the initial-grid build path and from the convergence runner's payroll-repair path (the latter passes `previous_contract_failure` carrying downstream-detected failure context per the docstring at [schedule.py:2206-2210](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2206-L2210)).

## 2. Pattern classification

**Not Python→GPT handler-on-failure.**  This is **GPT-as-authoring-source
with iterative refinement** — explicitly catalogued in doctrine §6 row
"Payroll headcount schedule" under "GPT-as-authoring-source (intentional,
NOT handler-on-failure)":

> Selecting OEWS occupational titles from the NAICS catalog is judgment
> about the operator's business model.  The catalog has hundreds of
> candidates; choosing among them is not table lookup.  Python provides
> tier-bound schema (iter 19 Stage 2), title-catalog filtering, wage/FTE
> mechanical math, and post-parse policy validators.

### Why the funding-handler doctrine doesn't apply directly

The funding-handler doctrine (P3.20 Part 3 four properties) presumes a
specific shape:
- Python deterministic builder runs first.
- A validator (post-pass check) evaluates the Python output.
- If validator fails, a separate GPT handler engages.
- The GPT handler iterates within a budget; on success its output replaces the Python output; on exhaustion it hard-fails.

Payroll iterative refinement is a different shape:
- **No Python deterministic builder runs first.**  GPT is the sole authoring source for the OEWS title selection + per-quarter FTE schedule (the parts of the contract too business-specific for table lookup).
- **The validator is post-PARSE, not post-pass.**  `validate_payroll_headcount_contract_payload` runs inside the GPT-iteration loop on each round's parsed contract.
- **The "handler" is GPT itself, calling itself again with feedback.**  There is no separate Python→GPT escalation boundary; the loop is GPT → Python validator → structured feedback packet → GPT.
- **Output is the only output.**  There is no Python fallback to revert to; if GPT fails, the system hard-fails with the residual diagnostic.

Per doctrine §6 the analog pair (other "GPT-as-authoring-source") is the
unified convergence GPT call (`_run_unified_convergence_openai`).  Both
have the same structural property: Python has no rule set to apply, so
GPT is the authoring source.

### Mapping the four properties to GPT-as-authoring-source

| Property | Funding-handler form | Iteration-loop analog |
|---|---|---|
| 1 — Never revert | Handler output persists into downstream state | GPT's accepted output is the only output; no revert by structure |
| 2 — Trigger on any validator failure | Handler engages on any post-pass validator failure | Iteration continues on any validation failure (per-round) until accepted or budget exhausted |
| 3 — Mirror Flavor 1 / single source of truth | Validator state == handler state == downstream state | Validator state == GPT input state (next round sees the same parsed contract the validator rejected, plus structured feedback) |
| 3b — Full failure payload | Handler receives all failure categories | GPT receives the full structured feedback packet (all failures from the round, dispatched by exception class) |
| 4 — Diagnostic preservation | Every fail-fast survives cleanup | Same — applies universally |

## 3. PROPERTY 1 analog — NEVER REVERT (GPT output persists)

**Conclusion: COMPLIANT.**

- GPT iteration returns the validator-accepted `schedule_payload` at [schedule.py:2594](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2594) (success path).  No pre-iteration fallback to revert to — there is no Python proposer.
- On hard-cap exhaustion ([schedule.py:2609-2624](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2609-L2624)), the function calls `_payroll_fail_fast("payroll_iterative_refinement_exhausted", ...)` with the rounds_used + last failure details.  Hard-fail, not revert.
- No `except: pass` swallows the GPT output anywhere in the iteration loop.

## 4. PROPERTY 2 analog — TRIGGER ON ANY VALIDATOR FAILURE (per-round)

**Conclusion: COMPLIANT.**

Each round's validation:
- `validate_payroll_headcount_contract_payload` at [schedule.py:2577](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2577) — Layer A.1 + A.2 + A.3 contract validation.
- `_assert_payroll_contract_economic_feasible_for_retry` at [schedule.py:2589](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2589) — Layer B economic feasibility check.

Both raise `RuntimeError` on failure.  Both are caught by the same `except RuntimeError` at [schedule.py:2595](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2595).  The handler (= GPT in the next round) gets the full structured failure via `_build_payroll_iterative_feedback_packet` at [schedule.py:2598](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2598).

No category-specific filter.  Any validation failure → feedback packet → next round.

## 5. PROPERTY 3 analog — MIRROR FLAVOR 1 (no divergent parse/validate paths)

**Conclusion: COMPLIANT.**

- Round N's GPT output is parsed by `_parse_responses_json_dict` ([schedule.py:2550](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2550)).
- The parsed dict is validated by `validate_payroll_headcount_contract_payload` ([schedule.py:2577](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2577)).
- On failure, `last_parsed = deepcopy(parsed)` ([schedule.py:2575](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2575)) preserves the rejected payload; the feedback packet built at [schedule.py:2598](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2598) includes it for the next round's `previous_contract_failure` context.
- On success, the SAME parsed contract becomes the `schedule_payload` ([schedule.py:2580](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2580)) returned to the caller.

No divergent rebuild paths.  The state the validator evaluates IS the state the next round sees IS the state returned on success.

## 6. PROPERTY 3b analog — FULL FAILURE PAYLOAD

**Conclusion: COMPLIANT.**

`_build_payroll_iterative_feedback_packet` at [schedule.py:2598](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2598) constructs the structured feedback packet from the `RuntimeError` raised by the validator.  The packet is dispatched by exception class (per the docstring at [schedule.py:2201](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2201)) — every validator failure type produces a packet with the appropriate `feedback_class` and structured fields (field name, actual value, required range, failure category, etc.).

The translator `payroll_validator_translator.py` ([line 167+](python/client_intake_and_finmo/post_intake_headcount/payroll_validator_translator.py#L167)) carries fail-fasts for unmatched codes (`payroll_validator_translator_unmatched_code`) and malformed outputs — meaning if any validator failure code is NOT recognized by the translator, the system hard-fails rather than silently dropping it.  This is the doctrinal safeguard against "feedback packet missed a failure type" drift.

Convergence-runner-initiated calls also pass downstream-detected failure context via `previous_contract_failure` kwarg ([schedule.py:2194](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2194)).  Round 1 seeds with that context.  So a payroll refinement initiated by a downstream failure (e.g., post-quarter-grid feasibility violation) starts with the full downstream context, not just the local validator state.

## 7. PROPERTY 4 — DIAGNOSTIC PRESERVATION

**Conclusion: COMPLIANT.**  Confirmed by Stage 4 codebase-wide audit
and reconfirmed in handler-specific context.

Fail-fasts in this handler's domain (per Stage 4 inventory):

| File | Lines | Operations |
|---|---|---|
| `post_intake_headcount/schedule.py` | 2010, 2030, 2039, 2067 (machinery wrapper + invariants), 2516, 2610 | Machinery: state corruption / budget decoupling / round count drift; business: iterative_refinement_exhausted |
| `post_intake_headcount/payroll_validator_translator.py` | 167, 195, 204 | Validator translator: unmatched_code + malformed_output |
| `post_intake_mapping.py` | 3020 | payroll_tier_bounds_mirror_drift (Python↔SQL mirror) |

All carry structured `details` payloads (Stage 4 classification: ADEQUATE).

Survival check:
- All raises propagate as `PostIntakePreconditionFailed` exceptions.
- The single catch site for `PostIntakePreconditionFailed` at `post_intake_solver/orchestrator.py:2215` re-raises unconditionally.
- The iteration loop's own `except RuntimeError` at [schedule.py:2595](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2595) catches **validator exceptions** to build the feedback packet — but `PostIntakePreconditionFailed` is a subclass of `RuntimeError`, so machinery fail-fasts inside the loop would also be caught here.  **Worth double-checking.**

### Sub-audit: PostIntakePreconditionFailed vs the loop's `except RuntimeError`

Looking at the loop body more carefully: the `except RuntimeError` at [schedule.py:2595](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2595) wraps the validator + feasibility-check block ([schedule.py:2576-2594](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2576-L2594)).

The machinery fail-fasts (`payroll_iterative_refinement_*_*`) fire OUTSIDE this try block — at:
- `_assert_payroll_iterative_budget_decoupled` ([schedule.py:2510](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2510)) — before the GPT call.
- Round-count-drift check ([schedule.py:2514-2519](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2514-L2519)) — before the GPT call.

These machinery raises happen BEFORE the `try:` block at [schedule.py:2576](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2576).  They are NOT caught by the loop's `except RuntimeError`.  Survives.

The validator translator's fail-fasts (`payroll_validator_translator_*`) fire INSIDE `validate_payroll_headcount_contract_payload`'s normal exception path.  These ARE inside the try block, but the translator's intent is to catch malformed validator output that the iteration loop should not silently retry — and indeed it raises `PostIntakePreconditionFailed`.  When caught by the loop's `except RuntimeError`, the loop treats it as a validation failure and feeds it back to GPT for the next round.

**Is this a Property 4 violation?**  Subtle question.  The translator fail-fast at `payroll_validator_translator_unmatched_code` (schedule.py raises this via `_payroll_iterative_machinery_fail_fast`) is meant to indicate that the validator emitted a failure code the translator doesn't recognize.  If the loop catches it and feeds it back to GPT, the machinery violation is silently turned into another GPT round.  The DIAGNOSTIC SURVIVES in the form of `last_failure_packet` (which includes the exception text), so when the loop exhausts and hard-fails at [schedule.py:2609](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2609) it reports the residual.  Operator sees the failure eventually.  But the SPECIFIC machinery diagnostic ("translator can't match code X") may be confused with a business validation failure in the iteration log.

This is a borderline observation — not a violation in the Stage 4 sense (the diagnostic does survive into `payroll_iterative_refinement_exhausted`'s `last_exc_message`), but worth surfacing.  **Flagged as Structural Observation A below.**

## 8. Overall classification

**COMPLIANT** with the applicable analog doctrine (GPT-as-authoring-source
iteration loop).  No fix work required.

| Property analog | Status |
|---|---|
| 1 (output persists) | COMPLIANT |
| 2 (any per-round validator failure triggers next round) | COMPLIANT |
| 3 (single canonical parse/validate path) | COMPLIANT |
| 3b (full structured feedback packet) | COMPLIANT |
| 4 (diagnostic preservation) | COMPLIANT (Structural Observation A: validator-translator machinery fail-fasts may be coalesced into the iteration's residual diagnostic on the exhausted-path; not a doctrine violation per Stage 4, but worth surfacing) |

## 9. Recommended fix scope

**None required.**

### Structural Observation A (optional cleanup, not in P3.21 scope)

The iteration loop's `except RuntimeError` at [schedule.py:2595](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2595) catches both:
- Validator business-failures (intended for GPT-retry).
- `PostIntakePreconditionFailed` from `payroll_validator_translator_unmatched_code` / `payroll_validator_translator_malformed_output` (which represents a translator machinery violation, NOT a GPT business decision GPT can fix).

Consider re-raising `PostIntakePreconditionFailed` explicitly rather than catching it as a `RuntimeError` and feeding back to GPT:

```python
except PostIntakePreconditionFailed:
  raise  # Machinery violation — do not feed to GPT, hard-fail.
except RuntimeError as exc:
  # Business-validation failure — feed back to GPT for next round.
  ...
```

~3 LOC, not in P3.21 read-only scope.  Not a doctrine violation either way — the diagnostic survives into the eventual exhaustion fail-fast.

## 10. Cross-reference to additional-handler search

Greps performed:
- `def engage_` and `def run_*_handler` across `python/` — no additional entry points beyond the 3 known handlers (funding / stage_ramp / gpt_exhaustion).
- Directory listing of `python/client_intake_and_finmo/*_handler*` — exactly 3 handler packages.
- `grep -rn "_handler/handler.py\|_handler/tool_calling_session.py"` — only references to the 3 known packages.

**No additional Python→GPT handler-on-failure patterns discovered.**

The audit scope of three named handlers (A, B, C) is the complete
inventory.  P3.21 Part 1 is finished after this memo lands.

## Summary across P3.21 Part 1

| Handler | Pattern | Properties | Verdict |
|---|---|---|---|
| A — Stage ramp | Python→GPT handler-on-failure | 1, 2, 3, 3b, 4 all hold | COMPLIANT |
| B — Restoration / exhaustion | Python→GPT handler-on-failure | 1, 2, 3, 3b, 4 all hold | COMPLIANT (with 2 minor structural observations) |
| C — Payroll iterative refinement | GPT-as-authoring-source (NOT handler-on-failure) | Analog properties hold | COMPLIANT (with 1 minor structural observation) |

No handlers require Part 2 fix work.  The Stage 1-4 retrofit pattern
that the funding handler needed was specific to a handler that had
been built before the doctrine was codified — the stage ramp handler
and the iter 19 Stage 5 patterns were built doctrine-compliant by
construction, and the restoration handler (the original reference)
was the doctrine source.

The post-intake pipeline is doctrine-compliant codebase-wide.  No
whack-a-mole exposure for the 27-draft sweep on this axis.
