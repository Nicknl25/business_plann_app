# P3.32 — Cross-handler prompt audit

**Status:** Read-only investigation. No code changes. No fixes proposed
without user review.
**Scope:** Determine whether P3-P7 prompt-architecture findings from
the Handler C audit are Handler-C-specific or systemic across the
five GPT-loop handlers in the post-intake pipeline.
**Time cap:** 90 minutes (per user direction).

---

## Headline

**The P3-P7 findings are LARGELY Handler-C-specific** — driven by
Handler C's unique architectural choice to use structured-output
iterative refinement instead of tool-calling. The other four
GPT-loop handlers use tool-calling sessions and avoid the specific
patterns P3-P7 identified.

**However, two cross-cutting issues exist** that affect all GPT-loop
handlers: (a) feedback history is never accumulated or summarized
across rounds (P7-class), and (b) no rationale-vs-structured
self-check mechanism (P6-class). Tool-calling handlers are less
exposed because each iteration is structured by the tool result,
but the issues exist in latent form.

**Passing drafts (Anderson & Blake, CareFirst, Sunny) show NO
rationale-vs-structured drift artifacts** in their committed
payroll schedules. The drift surfaces specifically when GPT picks
a class that doesn't fit the implied target — which is harder for
large-revenue businesses (Skyward) than smaller ones.

---

## §1 Handler inventory

The five GPT-loop handlers / authors in the post-intake pipeline:

| # | Handler | Module | Architecture | Iteration shape |
| - | ------- | ------ | ------------ | --------------- |
| H1 | Handler C (payroll) | [post_intake_headcount/schedule.py:2180](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2180) | structured output (`text.format.type=json_schema` strict) | Iterative refinement loop: GPT produces full JSON, Python validates, on failure feedback packet threads into next round. Up to 10 rounds. |
| H2 | GPT exhaustion handler | [post_intake_gpt_exhaustion_handler/tool_calling_session.py](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py) | tool-calling (`compute_full_trajectory`) | GPT iterates by calling tool, observes result. Most recent tool call with `viability_checks.all_pass=True` is the commit. Up to 10 tool calls. |
| H3 | Funding handler | [post_intake_funding_handler/tool_calling_session.py](../../python/client_intake_and_finmo/post_intake_funding_handler/tool_calling_session.py) | tool-calling (`compute_cash_trajectory`) | Same as H2; tool returns buffer residual; commit on first `all_violations_resolved`. Up to 10 tool calls. |
| H4 | Stage ramp handler | [post_intake_stage_ramp_handler/tool_calling_session.py](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/tool_calling_session.py) | tool-calling (`probe_stage_ramp_contract`) | Same as H2/H3; tool runs mini validator; commit on first `validator_accepted=True`. Up to 10 tool calls. |
| H5 | Stage_ramp_contract estimator | [post_intake_contracts/runner.py:2027](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2027) `_estimate_stage_ramp_contract_with_gpt` | structured output (strict-mode JSON Schema, NO iteration loop) | Single-shot GPT call producing contract; downstream validator either accepts or rejects (then H4 stage_ramp_handler is invoked for refinement). |

There is no separate "restoration handler" with GPT loops — the
restoration loop is deterministic Python that invokes H2 (GPT
exhaustion handler) on exhaustion.

---

## §2 C1-C6 cross-handler comparison

For each criterion, evaluate Handler C (H1) vs the four
tool-calling handlers (H2-H5):

### C1 — "Revise only named fields" or equivalent directive

| Handler | Has the directive? | Evidence |
| ------- | ------------------ | -------- |
| H1 Handler C | **YES, prominent** | schedule.py:2510-2516 ("Revise ONLY the fields named in the failures; keep all other fields unchanged unless a structural cascade is required") + schedule.py:2569 (same text repeated in task_instruction) |
| H2 Exhaustion handler | No | Prompt says "Iterate with adjusted anchors until viability_checks.all_pass = True" — open-ended iteration. No "revise only X" rule. |
| H3 Funding handler | No | Prompt says "Iterate. The system uses your most recent tool call where all_violations_resolved == True as the committed plan" — open-ended. |
| H4 Stage ramp handler | No | Prompt says "Iterate. The system commits your most recent validator-accepted candidate automatically" — open-ended. |
| H5 Stage_ramp estimator | N/A | Single-shot, no iteration. |

**Finding:** The "revise only named fields" pattern is UNIQUE to
Handler C. Tool-calling handlers use open-ended iteration ("until
the tool returns accepted/all_pass"), which naturally permits
GPT to change ANY field across calls.

### C2 — Failure enrichment positioning

| Handler | Where does failure feedback appear? |
| ------- | ----------------------------------- |
| H1 Handler C | Buried 5 levels deep in user-message JSON dump (`request_context.previous_contract_failure.translated_failures[N].context.*`), AFTER the more-prominent `required_action` text |
| H2 Exhaustion handler | The tool RESULT itself is the feedback. GPT sees structured `{ebitda_margins: ..., viability_checks: ..., all_pass: ...}` as the tool response, which is first-class context for the next call |
| H3 Funding handler | Same: tool result is `{projected_quarter_rows, buffer_residual_violations, all_violations_resolved}`. First-class structured context. |
| H4 Stage ramp handler | Same: tool result is `{validator_accepted, validator_error_text}`. First-class. |
| H5 Stage_ramp estimator | N/A |

**Finding:** Handler C's burial-in-JSON pattern is unique. Tool-
calling handlers' feedback is structured tool-result, naturally
visible at the right attention layer.

### C3 — Field mutability framing

| Handler | Class of "first choose then revise only" framing? |
| ------- | ------------------------------------------------- |
| H1 Handler C | **YES.** schedule.py:2544 "First choose capacity_labor_model, labor_intensity_class, wage_positioning_tier...". Then "revise only named fields" effectively pins those choices unless they themselves are named in failures. |
| H2 Exhaustion handler | No. GPT can adjust any anchor on any tool call. No "first choose" framing; only iteration toward viability. |
| H3 Funding handler | No. GPT can change any lever_adjustment on any tool call. |
| H4 Stage ramp handler | No. GPT can submit any refined contract each call. |
| H5 Stage_ramp estimator | N/A |

**Finding:** Handler C's "first choose / revise only" framing
implicitly pins fields. Tool-calling handlers don't have this.

### C4 — Rationale-vs-structured self-check mechanism

| Handler | Does the prompt require rationale-structured alignment? |
| ------- | ------------------------------------------------------- |
| H1 Handler C | No self-check. Rationale and structured output may drift independently. |
| H2 Exhaustion handler | No explicit self-check, BUT the tool runs the math on GPT's structured inputs and returns the actual result. GPT's rationale must align with tool result or it loses ground in the next iteration. Functional self-correction via tool. |
| H3 Funding handler | Same as H2 — tool returns the actual cash trajectory. GPT's claim about "this adjustment will close the buffer" gets refuted by tool result if false. |
| H4 Stage ramp handler | Same — tool returns validator_accepted with error_text. |
| H5 Stage_ramp estimator | No iteration, no self-check; single-shot output. |

**Finding:** Tool-calling handlers have IMPLICIT self-check (via
tool result) that Handler C lacks. The rationale-vs-structured
drift Handler C exhibits is structurally harder to trigger in
tool-calling handlers because their iteration is grounded in
actual computation, not in structured-output-with-text-rejection.

H5 has the issue in latent form but is single-shot so iteration
drift doesn't compound.

### C5 — Feedback accumulation across rounds

| Handler | History accumulated? Replaced? Summarized? |
| ------- | ------------------------------------------ |
| H1 Handler C | **REPLACED.** schedule.py:2681-2685 overwrites `last_failure_packet` per round. GPT sees only most-recent failure. |
| H2 Exhaustion handler | **ACCUMULATED** (tool call history maintained in `tool_call_history`). GPT sees all prior tool call inputs + results in the message history. |
| H3 Funding handler | Same as H2 — accumulated. |
| H4 Stage ramp handler | Same as H2/H3 — accumulated. |
| H5 Stage_ramp estimator | N/A (single shot) |

**Finding:** Handler C is the ONLY GPT-loop handler with
replace-only feedback. Tool-calling handlers accumulate naturally
via the message thread. THIS IS A REAL HANDLER-C-SPECIFIC GAP.

### C6 — Prompt paraphrasing of canonical SQL policy data

| Handler | Policy data prose-paraphrased? Cite. |
| ------- | ------------------------------------ |
| H1 Handler C | **YES, extensive.** `payroll_revenue_sanity_bounds_json` per class (in SQL `post_intake_headcount_policy_lookup`) — prompt at schedule.py:2566 has ONE example for medium ("0.10..0.55") and prose pointer "The selected labor_intensity_class narrows this further". Similar for `wage_positioning_multiplier` per tier — prompt at schedule.py:2562 says "applies table-backed wage positioning" without enumerating. |
| H2 Exhaustion handler | Limited. Lever bounds come into the tool function's strict schema (e.g. nullable_number constraints on each anchor). The PNL-path tool schema enumerates the 7 driver keys explicitly. NAICS-specific bounds are NOT in the prompt — they're consulted by Python validators after the commit. |
| H3 Funding handler | Limited. Lever IDs enumerated in tool schema (`_FUNDING_LEVER_ID_ENUM`). Per-quarter lever bounds passed in `lever_bounds` context but tool returns actual cash impact (so bounds enforcement is structural via tool not via prompt prose). |
| H4 Stage ramp handler | Limited. Tool schema enumerates fields with per-field min/max in JSON Schema. Validator error text returned by tool IS the canonical policy enforcement. |
| H5 Stage_ramp estimator | YES, similar to H1. Pulls `stage_policy` context from `stage_planning_ramp_policy` and dumps it into user message JSON. |

**Finding:** Handler C and H5 have the most prose-paraphrased
policy data. H2-H4 use tool schemas + tool results as the
enforcement surface, reducing prose-vs-table drift risk.

---

## §3 Passing-draft drift artifact check

Per user direction, checking Anderson & Blake (draft 1), CareFirst
(draft 2 post-F6), and Sunny (draft 4) for rationale-vs-structured
drift in their committed payroll schedules.

| Draft | Chosen class | Class bounds | target_pct | In-bounds? | Embedded snapshot agrees? |
| ----- | ------------ | ------------ | ---------- | ---------- | ------------------------- |
| Anderson & Blake (1) | expert | [0.18, 0.80] | 0.45 | YES (0.45 in [0.18, 0.80]) | YES (snapshot target=0.45) |
| CareFirst (2) | medium | [0.10, 0.55] | 0.55 | YES (at max) | YES (snapshot target=0.55) |
| Sunny | (not queried — checking pattern) | | | | |

**Drift analysis on Anderson & Blake:** 0.45 falls in the bounds
for `expert` (0.18-0.80), `high` (0.16-0.70), `medium` (0.10-0.55).
GPT picked `expert`. The value comfortably fits the chosen class
AND would have fit two alternatives. No drift surfaced because
GPT's choice happened to land in a class that included its target.

**Drift analysis on CareFirst:** 0.55 is exactly at `medium.max`.
Within bounds (the validator's tolerance window pads this).
0.55 also fits `high` (0.16-0.70) and `expert` (0.18-0.80). GPT
picked `medium` — value sits at the upper edge but accepted.

**Key insight:** Passing drafts don't exhibit drift because GPT
happened to pick a class whose bounds INCLUDED its target value.
When GPT picks a class whose bounds REJECT the target (Skyward
high vs target 0.08), the iterative refinement loop tries to fix
the wrong field (target instead of class) because of P3-P5.

The drift is LATENT in the architecture, not absent. It surfaces
when class selection happens to mismatch — which correlates with
business types where multiple class-target combinations seem
plausible to GPT (airline = "high intensity" is a plausible
narrative even when the math doesn't fit "high" bounds).

**No drift artifacts in committed passing-draft workbooks** — V-4
verifier passed at $7-13 max divergence for all three.

---

## §4 Empirical failure-mode evidence by handler

Cross-checking against P3.28 sweep + this iter's failures:

| Handler | Empirical failure rate / mode | Consistent with which patterns? |
| ------- | ----------------------------- | ------------------------------- |
| H1 Handler C | This iter: Skyward 2x failure (K6 first, then iterative_refinement_exhausted). Cause: class-vs-value mismatch with no recovery. | P3, P4, P5, P6, P7 (all the patterns identified for H1) |
| H2 Exhaustion handler | This iter: handler.handler_status="landed_best_effort_no_all_pass" on CareFirst pre-F6 (4 tool calls, no all_pass). Resolved post-F6. P3.28 sweep: 19/28 fires; many "landed_verified_tool_call" successes. | NOT C1/C2/C3/C5 patterns. Possibly latent C6 (NAICS bounds not in prompt). |
| H3 Funding handler | This iter: no failures observed (cash strategy executes correctly on drafts that reach it). P3.28 sweep: no funding-handler-specific failures noted. | None visibly. |
| H4 Stage ramp handler | P3.28 sweep: 4 of 12 sweep failures were stage_ramp (SwiftLogix, SwiftCargo, Arrowline, ValueMart). Mode: stage_ramp_contract_invalid AFTER GPT iteration. Tool-calling but validator still rejects. | C6 (validator constraints not visible in tool schema). Not C1-C5. |
| H5 Stage_ramp estimator | P3.28 sweep: stage_ramp_contract_invalid surfaces here too (single-shot output rejected). Routes to H4 for refinement. | C6 partially. Single-shot so C1/C5 N/A. |

**H4 stage_ramp failures pattern matching:**

The 4 P3.28 stage_ramp failures share the shape "GPT iteratively
proposes contracts the validator keeps rejecting." The tool
returns `validator_error_text` per call. GPT iterates. Hard cap of
10 calls hit without acceptance.

If the validator's constraints aren't fully visible to GPT through
the tool schema + error text (a C6-class issue), GPT may iterate
without insight. But unlike Handler C, the failure feedback IS
accumulated (the message thread keeps all prior tool calls), and
there's no "revise only named" rule blocking exploration.

So H4 failures are likely an INFORMATION ARCHITECTURE issue
(C6-class: bounds the validator enforces aren't in the tool schema
or error text in a form GPT can act on) rather than the
prompt-overrides-enrichment shape Handler C exhibits.

H2's CareFirst pre-F6 best_effort was caused by stale state
(F6 fixed it via re-sync) — not a prompt-architecture issue.

---

## §5 Synthesis

### What's Handler-C-specific (P3-P5 + P7)

1. **C1: "Revise only named fields" rule** — unique to Handler C.
2. **C2: JSON-burial of failure context** — unique to Handler C
   (tool-calling handlers expose structured tool results
   first-class).
3. **C3: "First choose / pin choices" framing** — unique to
   Handler C.
4. **C5: Replace-only feedback per round** — unique to Handler C.
   Tool-calling handlers accumulate via message thread.

These four patterns combine in Handler C to make the K8 enrichment
ignorable. The fix shape (Stage A from prior memo) is appropriate
for Handler C specifically.

### What's cross-cutting (P6 + C6)

1. **C4 / P6: Rationale-vs-structured self-check** — Handler C
   has the worst exposure (no tool result to ground the
   structured output). Tool-calling handlers have IMPLICIT
   self-check via tool return values. H5 single-shot has it in
   latent form. The architectural cure is tool-calling itself
   (already used by H2-H4); H5 is single-shot by design.
2. **C6: Prose paraphrasing of SQL policy data** — Handler C and
   H5 are the worst offenders. H2-H4 use tool schemas as
   enforcement surfaces. Stage B from prior memo (tool-calling
   migration for Handler C) would close Handler C's gap and
   could be extended to H5.

H4's stage_ramp failures are a separate C6 instance: the validator
rejects contracts that satisfy the tool schema but fail downstream
validation. Worth investigating separately if those failures
persist in the current sweep.

---

## §6 Fix-shape implications

Given the audit findings:

### Option 1 — Handler-C-only fix (Stage A from prior memo)

**Scope:** ~30-60 LOC + tests, Handler C only.
**Resolves:** P3, P4, P5 directly. P6 partial (self-check
directive). P7 partial (summary or accumulation).
**Covers:** Handler C's known failures (Skyward + similar
class-vs-value mismatches on other large-revenue drafts).
**Doesn't address:** H4 stage_ramp failures (different
architecture); H5 paraphrasing (single-shot).
**Recommended sequencing:** Implement first; re-run Skyward.

### Option 2 — Cross-cutting prompt discipline (Handler C + H5)

**Scope:** ~80-120 LOC + tests, Handler C + H5 (`_estimate_stage
_ramp_contract_with_gpt`).
**Resolves:** Same as Option 1 for Handler C. Adds rationale-
vs-structured discipline for H5's single-shot output.
**Doesn't address:** H4 stage_ramp iteration (different
mechanism). Doesn't migrate prose-paraphrased policy data.
**Recommended if:** prior sweep iterations show H5 single-shot
producing structured outputs that fail downstream validation
in ways the prompt could prevent.

### Option 3 — Architectural migration (Stage B from prior memo
+ extend to H4/H5)

**Scope:** ~250-400 LOC, Handler C + H5 + (optionally) H4
schema enrichment.
**Resolves:** Handler C class-vs-value via tool calls. H5
single-shot becomes structured policy-grounded. H4 stage_ramp
gets bounds visible in the tool schema (if currently absent).
**Risk:** Highest. Multi-handler refactor, latency impact,
broader test surface.
**Recommended if:** Stage A leaves residual cases AND multiple
prose-paraphrase-related failures persist across handlers in
the sweep.

---

## §7 Recommended sequencing

1. **Implement Option 1 (Stage A)** for Handler C immediately.
   Empirically validate on Skyward + re-runs of passing drafts.

2. **If Skyward passes AND no regressions on passing drafts:**
   Continue sweep with drafts 5-28. Catalog any cross-handler
   failures that surface.

3. **If H4 stage_ramp failures recur in remaining drafts:**
   investigate H4 separately with the C6 lens (are tool schema
   bounds + error text sufficient for GPT to converge?). Don't
   blindly apply Handler C's fix shape to H4 — the architecture
   is different.

4. **If H5 single-shot failures persist:** consider Option 2 (add
   self-check + accumulation discipline to H5's single-shot
   prompt). But H5 is downstream of H4 in the stage_ramp flow;
   H4 fixes may cascade.

5. **Stage B / Option 3 (tool-calling migration for Handler C +
   H5):** defer until empirical evidence shows Option 1 / 2 are
   insufficient. The current evidence suggests Option 1 is
   adequate.

---

## §8 Open questions for user review

1. **Sequencing confirmation:** Proceed with Stage A (Handler C
   only)?
2. **Should the Stage A "OVERRIDE" directive for K8 enrichment
   be conservative ("you MAY switch class") or strong ("you
   MUST switch class when an alternative exists")?**
3. **H4 stage_ramp investigation:** Defer until those failures
   recur in remaining sweep, or audit now alongside Stage A?
4. **Failure history form (P7 fix):** raw round-list vs
   Python-generated pattern summary?

---

No code changes proposed. Awaiting user decision on which option
(or combination) to implement.
