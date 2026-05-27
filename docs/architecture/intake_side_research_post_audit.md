# Intake-Side Research — Post Cloud-Claude Audit

**Status:** Research report. No code changes. Hold for Nick's
review before any subsequent action.

**Context:** Cloud Claude's audit of the P3.40 contract layer
flagged Finding A (R-d / `key_people_summary` submission gate)
and Finding E (5e/f/g/h skip rationale framing). This doc gives
the on-the-ground view from direct codebase inspection.

**Scope:** INTAKE side only (post-intake / contract layer is
done).

---

## 1. `key_people_summary` — Canonical Definition

### What the field semantically IS

`key_people_summary` is **a denormalized rendered narrative**: a
single string that is the concatenation of the per-person
`paragraph` fields from `people_json["people"][]`, separated by
blank lines.

Per the GPT system prompt at
[people_capability_consultant.py:387](../../python/client_intake_and_finmo/people_capability_consultant.py#L387):

> `key_people_summary` must be a concatenation of the per-person
> paragraphs in a clear order (separated by blank lines).

So it is **NOT primary data**. It is a **derived view** of the
`people` array. The per-person paragraphs are the source of
truth; `key_people_summary` is the rendered presentation form.

### Who produces it

GPT, in the `people_capability_finalize` call. The OpenAI strict
schema lists it as a required string. GPT generates it alongside
the per-person paragraphs in a single output.

### Who consumes it (intended)

The consumer-prompt rendering layer — specifically:
- The **review display** the intake conversation shows the user
  before People & Capability is locked in (build the
  `key_people_blocks` for the assistant turn).
- The **fact-template renderer** at
  [intake_consult.py:1060](../../python/api_handlers/intake_consult.py#L1060)
  which makes `{{fact:people.key_people_summary}}` resolvable.
- **Submission rendering** at
  [intake_consult.py:3454](../../python/api_handlers/intake_consult.py#L3454)
  inside the shared-context bundle.

All three are RENDERING consumers — none of them depend on the
field as a planning input.

### Why the schema marks it required AND why intake_consult.py:6241 pops it

This is the load-bearing tension.

The schema marks it required because GPT must produce it (so
the in-flight conversation has a coherent rendered narrative to
show the user immediately).

The pop is INTENTIONAL — added in commit `e57ff49 financials
stage cleanup, people collection hardened`. Design rationale:
the field is **redundant** with `people_json["people"][].paragraph`.
Storing both in the persisted draft means two sources of truth
for the same content, with drift risk if a future flow updates
one but not the other. The intake_consult.py codepath instead:
1. Receives `key_people_summary` from GPT (in-memory).
2. Per-person paragraphs are also persisted in
   `people_json["people"][].paragraph` (the canonical store).
3. The summary is popped before persistence to enforce single
   source of truth.
4. Downstream rendering reconstructs from per-person paragraphs
   on demand (the `key_people_blocks` build at
   [intake_consult.py:6284-6304](../../python/api_handlers/intake_consult.py#L6284)).

So the pop is **designed-in behavior, not legacy cruft**. The
field is semantically a view, and the design says views aren't
persisted.

### Where the design breaks

The design intent works for the rendering consumers (which
reconstruct from per-person paragraphs).

The design **breaks at the submission gate**. The gate at
[financials.py:164-168](../../python/api_handlers/financials.py#L164)
reads `pc_obj.get("key_people_summary")` directly from the
persisted draft and raises `IntakeValidationError` if it is
empty.

So:
- The PERSISTENCE layer treats `key_people_summary` as a view
  (don't store).
- The SUBMISSION-GATE layer treats `key_people_summary` as
  primary data (must be present, fail otherwise).

These two layers disagree. The contract layer caught the
mismatch (Contract 5d F1 typed `key_people_summary` as
`Optional[str] = None` per PSL2 production-reality-wins). But
the SUBMISSION-GATE inconsistency was not addressed by the
contract layer because the contract layer's scope is structural
typing at boundaries, not gate-time business-logic validation.

### Canonical statement

> `key_people_summary` is a **denormalized view** of
> `people_json["people"][].paragraph`. The source of truth is
> the per-person paragraphs. The summary is **never persisted**
> (popped by intake_consult.py:6241 + :10978 before write).
> Consumers that need the summary MUST reconstruct it from the
> per-person paragraphs.
>
> The submission gate at financials.py:164-168 reads the
> popped field directly from the draft, treating it as
> primary data. This is **inconsistent with the persistence
> design** and constitutes a real bug, not a design feature.

---

## 2. Lifecycle Trace

### Generation

[people_capability_consultant.py:80-147](../../python/client_intake_and_finmo/people_capability_consultant.py#L80)
`_final_schema()` lists `key_people_summary` as required string.
`people_capability_finalize()` at
[people_capability_consultant.py:368+](../../python/client_intake_and_finmo/people_capability_consultant.py#L368)
calls GPT with the strict schema; GPT returns a dict containing
`key_people_summary`.

### Persistence paths (TWO parallel handlers)

**Path A — LEGACY** (still wired but frontend no longer
calls it):
- [people_capability.py:554-562](../../python/api_handlers/people_capability.py#L554)
  `post_people_capability_handler` calls
  `append_messages(..., people_json=final_obj, ...)` where
  `final_obj` retains `key_people_summary` intact.
- Persisted draft → `people_json.key_people_summary` IS present.

**Path B — UNIFIED** (the path frontend currently uses):
- [intake_consult.py:6225-6241](../../python/api_handlers/intake_consult.py#L6225)
  the unified consult handler enriches the GPT output, then
  POPS `key_people_summary` at line 6241 before calling
  `append_messages(...)`.
- A second pop exists at
  [intake_consult.py:10978](../../python/api_handlers/intake_consult.py#L10978)
  for an alternate code path within the same handler.
- Persisted draft → `people_json.key_people_summary` is
  **absent**.

### Frontend wiring

The intake UI uses `apiClient.post("/api/intake-consult", ...)`
per [UnifiedConsultStep.tsx:588 + :654](../../frontend/src/intake_form/steps/UnifiedConsultStep.tsx#L588).
It does **NOT** call `/api/people-capability` directly. So Path
B (UNIFIED, with the pop) is the production path.

Frontend `SubmitStep.tsx` does NOT include `key_people_summary`
in the submission payload — the field is purely backend-side.

### Read sites (post-persistence)

| Reader | File:line | Read pattern | Outcome on persisted draft |
|---|---|---|---|
| Submission gate (THE BUG) | [financials.py:164](../../python/api_handlers/financials.py#L164) | `pc_obj.get("key_people_summary")` (direct from draft) | **None** → raises IntakeValidationError |
| Submission payload assembly | [financials.py:211-216](../../python/api_handlers/financials.py#L211) | uses local `key_people_summary` from line 164 + renders fact templates → sets `payload["key_people_summary"]` | **""** (passes through the bug) |
| Shared-context bundle | [intake_consult.py:1060](../../python/api_handlers/intake_consult.py#L1060) | `(people_ctx or {}).get("key_people_summary")` | **None** but bundle still constructed; downstream tolerates empty |
| Shared-context formatter | [intake_consult.py:3454](../../python/api_handlers/intake_consult.py#L3454) | `people_json.get("key_people_summary")` | **None** but renderer tolerates |
| Submit-service validator | [intake_submit_service.py:225, 231-233](../../python/client_intake_and_finmo/intake_submit_service.py#L225) | `payload.get("key_people_summary")` (after financials.py fills it) | **""** → raises `errors["key_people_summary"] = "key_people_summary is required"` |

### Why the gate fires today

1. User completes intake conversation via `/api/intake-consult`.
2. Unified handler pops `key_people_summary` before persistence.
3. User hits submit; frontend POSTs to `/api/financials`.
4. `post_financials_handler` loads the draft, reads
   `pc_obj.get("key_people_summary")` → **None**.
5. Raises `IntakeValidationError` with detail "People &
   Capability consult is missing key_people_summary."
6. Frontend surfaces the error; submission fails.

The reconstruction at intake_consult.py:6284-6304 builds
`key_people_blocks` in-memory for the assistant review turn but
does NOT mutate the persisted draft. So no path I found
reconstructs the summary into the draft post-pop.

### Symmetry with target_market_summary

The exact same pattern exists for `target_market_summary`:
- Popped at [intake_consult.py:10863](../../python/api_handlers/intake_consult.py#L10863)
  in the unified handler.
- Read at [financials.py:95-99](../../python/api_handlers/financials.py#L95)
  as a submission gate that raises `IntakeValidationError`
  ("Target market consult is missing target_market_summary.")
- Frontend doesn't send it; backend reads from draft.
- Same broken pipeline.

**This is the same bug class as Finding A, applied to a second
field. Cloud Claude flagged only `key_people_summary` because
that's what the spec doc R-d residual called out. The bug
extends to `target_market_summary` and any other
field that follows the same pop-but-gate-reads pattern.**

(See §4 for a check on whether other fields share this pattern.)

---

## 3. Cloud Claude Audit Findings — Your Assessment

### 3.1 Finding A (R-d submission gate) — **AGREE, scope wider than flagged**

Cloud Claude's read is correct. The submission gate hard-fails
on every unified-flow submission because `key_people_summary`
is popped pre-persistence.

**Wider than flagged**: the bug also applies to
`target_market_summary` (same pattern, same handler, same
submission gate, same hard-fail). Treating Finding A as a
1-field issue understates the scope.

#### Of cloud Claude's two options

**Option 1 — Stop popping** (persist `key_people_summary` +
`target_market_summary` in the draft, contract types as
`Optional[str]` becomes consistently populated).

  - PRO: Aligns gate behavior with persisted shape; submission
    works without further code change.
  - CON: Reintroduces the redundancy the pop was designed to
    eliminate. Two sources of truth for the rendered narrative.
    Drift risk: a future tool that updates `people_json["people"][i].paragraph`
    but not the cached summary causes the summary to lie.

**Option 2 — Reconstruct from people array in financials.py**
(rebuild summary from per-person paragraphs at gate time; check
the reconstruction is non-empty).

  - PRO: Respects the design intent (`key_people_summary` is a
    view). Aligns gate behavior with the persistence layer's
    canonicalization. No new persistence storage.
  - CON: The reconstruction logic must live at the gate site
    (or in a shared helper). Couples two layers.

#### Option 3 (the one cloud Claude didn't surface)

**Option 3 — Replace the check with a structural validator on
the per-person paragraphs.**

The check at financials.py:164-168 protects against "draft
where people consult never ran." But:
- Line 158 already checks `people_json` exists (real protection).
- Line 161 already checks `people_json` is a dict.
- A non-empty `key_people_summary` is a PROXY for "people
  consult produced output." The DIRECT check is "people_json has
  a non-empty `people` array with at least one entry that has
  a non-empty `paragraph`."

The direct check is what the gate REALLY wants to enforce.
`key_people_summary` was a convenient stand-in but the proxy
broke when the design canonicalized away from it.

Same applies to `target_market_summary` — the direct check is
"target_market_json has populated demographic intent + ACS
codes (consumer/mixed) or b2b cohort fields (b2b/mixed)" which
the gate at financials.py:117-155 ALREADY validates separately.
The `target_market_summary` non-empty check is redundant with
those structural checks.

#### My recommendation

**Option 3 (replace the proxy checks with direct structural
checks).** Rationale:

- Respects the design intent (`key_people_summary` +
  `target_market_summary` are views, not primary data).
- Removes the redundancy the proxy created.
- The "real" thing the gate wants to assert is structural
  presence of underlying data, which has separate validators.
- The fix is small and localized to financials.py.
- No persistence-layer behavior change → no risk to anything
  else.

Option 2 is the second-best fallback (also respects design;
slightly more work; same risk profile). Option 1 is the
worst — it reverses a deliberate design decision and
reintroduces drift risk just to satisfy a gate check.

If `key_people_summary` and `target_market_summary` need to
appear on the submission payload (line 216 + 244 in
financials.py write them into the payload for downstream
consumers), the reconstruction code at gate time (Option 2/3
hybrid) handles that: reconstruct from primary data, assign to
payload field, validate that the reconstruction is non-empty.

### 3.2 Finding E (5e/f/g/h skip rationale) — **PARTIAL AGREEMENT**

Cloud Claude is right that the skip framing is suboptimal but
the skip itself is defensible.

#### The framing critique

The spec doc Contract 5 R11 says (post-Cleanup-6): "NOT
PURSUED ... python-aggregated shapes (NOT OpenAI-schema-
enforced). The 5e/f/g/h retrofit track would follow a different
pattern than 5b/c/d; no current consumer warrants the work."

The "different pattern" framing IS misleading. The 5b/c/d
template (trace → spec → implementation, with §0 value-
constraint policy) is generic. It works for any sub-shape
typing — the only thing that differs is the source of truth
for the field roster:
- 5b/c/d: OpenAI strict schema (`_final_schema()` returns).
- 5e/f/g/h: producer code (whatever python function writes
  `financials_json` / `marketing_model_json` / etc.).

The trace work is harder for 5e/f/g/h because there's no single
canonical schema dict to lift fields from — you have to read
the producer code and derive the shape. But the spec template
and §0 policy apply identically.

So cloud Claude's reframing — "requires per-producer trace
work; out of scope for this cleanup pass" — is more honest.

#### Whether the skip itself stands

Yes, defensible. The trace work is real. The cleanup pass was
scoped to RESIDUAL closure, not new sub-contract typing waves.
The same logic that says Contract 1 R3 (Contract 1 sub-shape
typing of opaque blobs) is deferred applies to 5e/f/g/h.

But the framing should be cloud Claude's. I'd update Contract
5 §8 R11 to say:

> R11 — Sub-contract retrofits for `financials_json` /
> `financials_year1_json` / `marketing_model_json` /
> `planning_context_summary_json` / `fulfillment_json`. Each
> requires per-producer trace work (no single canonical schema
> like 5b/c/d's `_final_schema()` returns); each gets its own
> trace → spec → implementation series following the 5b/c/d
> template. Out of scope for the P3.40 cleanup pass. Re-open as
> a "Contract 5 python-aggregated retrofit wave" project when a
> downstream consumer warrants the structural typing investment
> on a specific field.

#### Coverage gap?

Looking at the 5 untyped fields with intake-side perspective:

- `financials_json` — has a producer (`financials_consultant.py`?
  or aggregation in intake_consult.py); shape is bounded.
  Retrofit feasibility: high.
- `financials_year1_json` — Python aggregated from
  financials_json + ops data; shape is bounded. Retrofit
  feasibility: high.
- `marketing_model_json` — `_refresh_marketing_model()` at
  intake_consult.py constructs it; shape is bounded. Retrofit
  feasibility: high.
- `planning_context_summary_json` — composed during initial
  grid; less direct producer. Retrofit feasibility: medium.
- `fulfillment_json` — Flag 1 (c) marked it as a candidate for
  AUDIT + drop entirely (may be vestigial). Retrofit
  feasibility: don't retrofit; audit first.

None of these 5 are currently consumed in a way that creates
the same gate-fails-silently bug as `key_people_summary`. The
gap is theoretical (less type safety) not operational (no
broken submissions today).

So: skip stands; framing should be updated.

---

## 4. Broader Intake-Side Observations

### 4.1 Other instances of the "pop + gate read" pattern

Per §1-2 above, **`target_market_summary` shares the exact bug
with `key_people_summary`.** Both:
- Pop in `intake_consult.py` unified handler (lines 6241 +
  10978 + 10863).
- Read directly from persisted draft at submission gate
  (financials.py lines 95-99 + 164-168).
- Hard-fail submission via `IntakeValidationError`.

I checked all `.pop(...)` calls in `intake_consult.py` +
`people_capability_consultant.py` + `target_market_consultant.py`
+ `intake_consultant.py` for similar patterns. Other pops found:
- `_ops_restatement_pending` / `_ops_restatement_text` (line
  8457) — internal flags, never persisted, no gate reads them.
  Safe.
- `_pending_*` fields (line 10864-10867) — same as above.
  Safe.

No other surprises. The bug class is contained to the 2 summary
fields (`key_people_summary` + `target_market_summary`) on the
unified flow.

### 4.2 Two-flow split (LEGACY vs UNIFIED)

The codebase has TWO parallel intake handler families:
- LEGACY: `target_market.py` + `people_capability.py` (each
  with its own API routes).
- UNIFIED: `intake_consult.py` (single handler routing all
  consult focuses).

The frontend uses UNIFIED exclusively
([UnifiedConsultStep.tsx](../../frontend/src/intake_form/steps/UnifiedConsultStep.tsx#L588)).
The LEGACY handlers are still wired in api.py:171-209 but the
frontend never calls them. They appear to be retained for:
- Direct dev/QA usage.
- Backward compatibility for clients that haven't migrated.
- Potential test harness usage.

This split is NOT necessarily a problem but it does mean any
intake-side fix must be applied to BOTH handlers OR explicitly
deprecate LEGACY first. If only UNIFIED is fixed and LEGACY
diverges further, the next consolidation pass becomes harder.

### 4.3 The frontend doesn't speak the persistence schema

`SubmitStep.tsx:34-45` shows the frontend submission payload
contains zero intake-consult JSONs. The frontend sends only
**form-collected fields** (business_name, address, contact info,
business_start_date, product_keywords, how_did_you_hear).

The backend assembles the intake JSONs from the draft (loaded
from DB) at submission time. This separation is fine BUT it
means any "the draft must contain X" assertion at the gate is
hardcoded backend logic — the frontend has no way to check
draft-state in advance.

So when the gate fails for missing `key_people_summary`, the
user sees a generic backend error mid-submission. They can't
preview what's missing. This is a UX consideration if the gate
behavior changes (e.g., reconstruction-from-paragraphs needs
to be robust enough to not surface for the user).

### 4.4 `business_description_summary` rendering path

A pattern related to but different from key_people_summary:
[financials.py:200](../../python/api_handlers/financials.py#L200)
sets `payload["business_description_summary"] = rendered_ops_summary`
from a `rendered_ops_summary` that was rendered via fact-template
expansion. This field IS in the OpenAI ops schema (Contract 5b)
and IS persisted (no pop). But the persisted version contains
`{{fact:...}}` placeholders; the gate-time render resolves them
to literal values for the submission payload.

This is a CORRECT design pattern: persist the templated source,
render at consumer time. The contrast with `key_people_summary`
illustrates the design tension — both could be modeled either
way. `business_description_summary` chose "persist + render".
`key_people_summary` chose "don't persist, reconstruct".

There's no right answer in general; the question is whether the
chosen design is consistently respected across all consumers.

### 4.5 The submission gate is a structural validator that uses semantic checks

The submission gate at financials.py + intake_submit_service.py
does TWO kinds of validation:
1. **Structural** (does the field exist? is the JSON a dict?).
2. **Semantic** (is the value non-empty? does it pass content
   sanity checks?).

The bug is that some "semantic" checks (non-empty summary) were
inadvertently making structural assertions (field-must-be-
persisted) without that requirement being designed-in.

If the cleanup of `key_people_summary` succeeds (via Option 3
above), the broader principle should be: the submission gate
asserts on PRIMARY DATA, not on VIEWS of primary data. Each
existing semantic check should be re-examined under that lens.

### 4.6 Items NOT seen but worth flagging

- I did **not** find another field that's both popped pre-
  persistence AND gate-checked post-load. Just the 2 summaries.
- I did **not** find frontend code that surfaces draft contents
  for inspection (no "preview submission" UI). So users have no
  way to see what the backend will check.
- I did **not** find a "shared validator" function — both the
  legacy and unified flows duplicate validation logic. Future
  consolidation work has structural similarity already in
  place but no shared helpers.

---

## 5. Recommended Path Forward

### Priority: BLOCKING for Fix #2

1. **Fix the unified-flow submission gate (extended Finding A).**

   Scope: BOTH `key_people_summary` AND `target_market_summary`.
   Approach: Option 3 (replace proxy checks with direct
   structural checks on primary data). Per the §1 canonical
   definition.

   Why blocking: if Fix #2 starts touching intake-side code with
   the gate broken today, every Fix-#2 dev workflow that hits
   the submission path will fail. Test infrastructure that
   depends on a happy-path submission will be unreliable.

   Estimated effort: small (financials.py changes; ~20-30 LOC
   plus tests).

### Priority: RECOMMENDED before Fix #2

2. **Reframe Contract 5 R11 disposition.**

   Adopt cloud Claude's framing ("requires per-producer trace
   work; out of scope for this cleanup pass") in the Contract 5
   spec §8. Document-only change. Removes the misleading "5b/c/d
   pattern doesn't apply" framing.

   Why before Fix #2: keeps the contract layer's
   documentation honest before downstream architectural work
   builds on it.

   Estimated effort: trivial.

3. **Document the dual-handler split formally.**

   Add a note to (a) the contract layer closeout doc or (b) a
   new intake-handler-architecture doc explaining that
   LEGACY (target_market.py + people_capability.py) and UNIFIED
   (intake_consult.py) coexist; frontend uses UNIFIED;
   submissions today rely on UNIFIED persisting correctly. This
   surfaces the constraint that any intake-side fix targeting
   the unified flow must consider whether the legacy handlers
   also need the same fix (or be marked deprecated).

   Why before Fix #2: Fix #2 may need to touch one or both
   handlers; knowing the split upfront avoids surprises.

   Estimated effort: small (1-page doc).

### Priority: NICE-TO-HAVE

4. **Audit other "semantic-via-proxy" submission checks.**

   Sweep `financials.py` + `intake_submit_service.py` for other
   "field-X-non-empty" checks that may be proxies for structural
   conditions. Replace proxies with direct checks where
   feasible. Same principle as Finding A fix, broader scope.

5. **Add `/api/financials` pre-flight endpoint.**

   Lets the frontend show users "your draft is missing X" before
   they hit submit. Reduces submission-time surprises. Not
   blocking; UX improvement.

6. **Deprecate LEGACY handlers OR add divergence-detection
   tests.**

   Either retire `target_market.py` + `people_capability.py`
   formally (delete + remove routes), OR add tests that pin
   their behavior so they don't silently diverge from UNIFIED.
   Currently they diverge on the summary-pop behavior.

### Priority: NOT WORTH PURSUING

7. **5e/f/g/h sub-contract typing wave.**

   Defensible to skip per cloud Claude's reframing. No current
   consumer warrants the investment. Re-open only when a
   specific consumer needs typing on a specific field.

8. **Option 1 from Finding A (stop popping).**

   Explicitly NOT recommended. Reverses a deliberate design
   decision to eliminate drift risk. The pop is correct; the
   gate is wrong.

---

## 6. Open Questions for Nick

1. **What's the SUBMISSION reality today?** The codebase says
   submissions via the unified flow should fail on the summary
   gates. But the system exists in production-shaped state
   (frontend wired, backend deployed). Have intake submissions
   been working? If yes: there's a path I missed. If no:
   confirm that this gate failure has been blocking submissions
   and the fix urgency is acute.

2. **LEGACY handler disposition** — keep around as fallback /
   delete entirely / freeze + deprecate? Doesn't block Finding
   A fix but answer informs scope of fix (only UNIFIED, or both).

3. **Option 2 vs Option 3 for the Finding A fix.** I recommended
   Option 3 (replace proxy with direct structural check) over
   Option 2 (reconstruct summary from paragraphs at gate time).
   But Option 2 has the benefit that the submission payload's
   `key_people_summary` field stays populated for downstream
   consumers that may need it. Option 3 leaves payload fields
   empty unless we ALSO add reconstruction at the payload-assembly
   site. Worth confirming which the downstream consumers actually
   need.

4. **`target_market_summary` symmetry** — confirm that the same
   fix should be applied to `target_market_summary` (per my
   §3.1 finding that the bug is wider than R-d alone). I'm 95%
   sure yes but want explicit confirmation.

5. **5e/f/g/h reframing in the spec doc** — am I authorized to
   make the documentation-only change in Cleanup-7 (or a small
   follow-up commit), or does this require a separate review
   cycle?

---

**End of research report. Awaiting Nick's review and direction.**
